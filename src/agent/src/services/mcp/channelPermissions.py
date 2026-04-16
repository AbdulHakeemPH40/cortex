"""
services/mcp/channelPermissions.py
Python conversion of services/mcp/channelPermissions.ts (241 lines)

Permission prompts over channels (Telegram, iMessage, Discord).
Handles structured permission relay from channel servers.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


# 25-letter alphabet: a-z minus 'l' (looks like 1/I). 25^5 ≈ 9.8M space.
ID_ALPHABET = 'abcdefghijkmnopqrstuvwxyz'

# Substring blocklist — 5 random letters can spell things.
# Non-exhaustive, covers the send-to-your-boss-by-accident tier.
ID_AVOID_SUBSTRINGS = [
    'fuck', 'shit', 'cunt', 'cock', 'dick', 'twat', 'piss', 'crap',
    'bitch', 'whore', 'ass', 'tit', 'cum', 'fag', 'dyke', 'nig',
    'kike', 'rape', 'nazi', 'damn', 'poo', 'pee', 'wank', 'anus',
]


def is_channel_permission_relay_enabled(
    get_feature_value: Optional[Callable[[str, Any], Any]] = None,
) -> bool:
    """
    GrowthBook runtime gate — separate from the channels gate (tengu_harbor)
    so channels can ship without permission-relay riding along.
    
    Default false; flip without a release. Checked once at connection mount —
    mid-session flag changes don't apply until restart.
    
    Args:
        get_feature_value: Function to get feature flag value
        
    Returns:
        True if permission relay is enabled
    """
    if get_feature_value is None:
        return False
    return bool(get_feature_value('tengu_harbor_permissions', False))


@dataclass
class ChannelPermissionResponse:
    """Response from a channel permission prompt."""
    behavior: str  # 'allow' | 'deny'
    # Which channel server the reply came from (e.g., "plugin:telegram:tg")
    from_server: str


class ChannelPermissionCallbacks:
    """
    Callbacks for channel permission handling.
    
    The pending Map is closed over — NOT module-level (per src/CLAUDE.md),
    NOT in AppState (functions-in-state causes issues with equality/serialization).
    
    resolve() is called from the dedicated notification handler
    (notifications/claude/channel/permission) with the structured payload.
    The server already parsed "yes tbxkq" → {request_id, behavior}; we just
    match against the pending map.
    """
    
    def __init__(self):
        """Initialize with empty pending map."""
        self._pending: Dict[str, Callable[[ChannelPermissionResponse], None]] = {}
    
    def on_response(
        self,
        request_id: str,
        handler: Callable[[ChannelPermissionResponse], None],
    ) -> Callable[[], None]:
        """
        Register a resolver for a request ID.
        
        Args:
            request_id: The request ID to match
            handler: Callback to invoke when response arrives
            
        Returns:
            Unsubscribe function
        """
        # Lowercase here too — resolve() already does; asymmetry means a
        # future caller passing a mixed-case ID would silently never match.
        # short_request_id always emits lowercase so this is a noop today,
        # but the symmetry makes the contract explicit.
        key = request_id.lower()
        self._pending[key] = handler
        
        def unsubscribe():
            self._pending.pop(key, None)
        
        return unsubscribe
    
    def resolve(
        self,
        request_id: str,
        behavior: str,
        from_server: str,
    ) -> bool:
        """
        Resolve a pending request from a structured channel event.
        
        Args:
            request_id: The request ID to resolve
            behavior: 'allow' or 'deny'
            from_server: Server name that sent the response
            
        Returns:
            True if the ID was pending and resolved, False otherwise
        """
        key = request_id.lower()
        resolver = self._pending.get(key)
        
        if not resolver:
            return False
        
        # Delete BEFORE calling — if resolver throws or re-enters, the
        # entry is already gone. Also handles duplicate events (second
        # emission falls through — server bug or network dup, ignore).
        del self._pending[key]
        
        try:
            resolver(ChannelPermissionResponse(
                behavior=behavior,
                from_server=from_server,
            ))
        except Exception:
            # Handler threw, but we already deleted - that's fine
            pass
        
        return True


# Regex for permission reply: "yes tbxkq" or "n abcde"
# 5 lowercase letters, no 'l' (looks like 1/I). Case-insensitive (phone autocorrect).
# No bare yes/no (conversational). No prefix/suffix chatter.
PERMISSION_REPLY_RE = re.compile(r'^\s*(y|yes|n|no)\s+([a-km-z]{5})\s*$', re.IGNORECASE)


def _hash_to_id(input_str: str) -> str:
    """
    FNV-1a hash to short ID string.
    
    FNV-1a → uint32, then base-25 encode. Not crypto, just a stable
    short letters-only ID. 32 bits / log2(25) ≈ 6.9 letters of entropy;
    taking 5 wastes a little, plenty for this.
    
    Args:
        input_str: String to hash
        
    Returns:
        5-character lowercase ID string
    """
    # FNV-1a 32-bit
    h = 0x811c9dc5
    for char in input_str:
        h ^= ord(char)
        h = (h * 0x01000193) & 0xFFFFFFFF
    
    # Base-25 encode
    result = []
    for _ in range(5):
        result.append(ID_ALPHABET[h % 25])
        h = h // 25
    
    return ''.join(result)


def short_request_id(tool_use_id: str) -> str:
    """
    Short ID from a toolUseID.
    
    5 letters from a 25-char alphabet (a-z minus 'l' — looks like 1/I in many fonts).
    25^5 ≈ 9.8M space, birthday collision at 50% needs ~3K simultaneous pending
    prompts, absurd for a single interactive session.
    
    Letters-only so phone users don't switch keyboard modes (hex alternates a-f/0-9
    → mode toggles). Re-hashes with a salt suffix if the result contains a
    blocklisted substring — 5 random letters can spell things you don't want in
    a text message to your phone.
    
    Args:
        tool_use_id: Tool use ID to convert
        
    Returns:
        5-character lowercase ID string
    """
    # 7 length-3 × 3 positions × 25² + 15 length-4 × 2 × 25 + 2 length-5
    # ≈ 13,877 blocked IDs out of 9.8M — roughly 1 in 700 hits the blocklist.
    # Cap at 10 retries; (1/700)^10 is negligible.
    candidate = _hash_to_id(tool_use_id)
    
    for salt in range(10):
        if not any(bad in candidate for bad in ID_AVOID_SUBSTRINGS):
            return candidate
        candidate = _hash_to_id(f"{tool_use_id}:{salt}")
    
    return candidate


def truncate_for_preview(input_data: Any) -> str:
    """
    Truncate tool input to a phone-sized JSON preview.
    
    200 chars is roughly 3 lines on a narrow phone screen. Full input is in
    the local terminal dialog; the channel gets a summary so Write(5KB-file)
    doesn't flood your texts. Server decides whether/how to show it.
    
    Args:
        input_data: Data to truncate
        
    Returns:
        Truncated JSON string
    """
    try:
        s = json.dumps(input_data, separators=(',', ':'))
        if len(s) > 200:
            return s[:200] + '…'
        return s
    except (TypeError, ValueError):
        return '(unserializable)'


def filter_permission_relay_clients(
    clients: List[Dict[str, Any]],
    is_in_allowlist: Callable[[str], bool],
) -> List[Dict[str, Any]]:
    """
    Filter MCP clients down to those that can relay permission prompts.
    
    Three conditions, ALL required: connected + in the session's --channels
    allowlist + declares BOTH capabilities. The second capability is the
    server's explicit opt-in — a relay-only channel never becomes a
    permission surface by accident.
    
    Args:
        clients: List of client dicts
        is_in_allowlist: Function to check if client is in allowlist
        
    Returns:
        Filtered list of connected clients with permission capability
    """
    result = []
    
    for c in clients:
        if c.get('type') != 'connected':
            continue
        
        name = c.get('name', '')
        if not is_in_allowlist(name):
            continue
        
        capabilities = c.get('capabilities', {})
        experimental = capabilities.get('experimental', {})
        
        if experimental.get('claude/channel') is None:
            continue
        
        if experimental.get('claude/channel/permission') is None:
            continue
        
        result.append(c)
    
    return result


def create_channel_permission_callbacks() -> ChannelPermissionCallbacks:
    """
    Factory for the callbacks object.
    
    Same lifetime pattern as `replBridgePermissionCallbacks`: constructed once
    per session inside a manager, stable reference stored in app state.
    
    Returns:
        New ChannelPermissionCallbacks instance
    """
    return ChannelPermissionCallbacks()


__all__ = [
    'ChannelPermissionResponse',
    'ChannelPermissionCallbacks',
    'PERMISSION_REPLY_RE',
    'ID_ALPHABET',
    'ID_AVOID_SUBSTRINGS',
    'is_channel_permission_relay_enabled',
    'short_request_id',
    'truncate_for_preview',
    'filter_permission_relay_clients',
    'create_channel_permission_callbacks',
]
