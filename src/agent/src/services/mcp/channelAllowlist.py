"""
services/mcp/channelAllowlist.py
Python conversion of services/mcp/channelAllowlist.ts (77 lines)

Approved channel plugins allowlist. --channels plugin:name@marketplace
entries only register if {marketplace, plugin} is on this list. server:
entries always fail (schema is plugin-only). The
--dangerously-load-development-channels flag bypasses for both kinds.
Lives in GrowthBook so it can be updated without a release.

Plugin-level granularity: if a plugin is approved, all its channel
servers are. Per-server gating was overengineering — a plugin that
sprouts a malicious second server is already compromised, and per-server
entries would break on harmless plugin refactors.

The allowlist check is a pure {marketplace, plugin} comparison against
the user's typed tag. The gate's separate 'marketplace' step verifies
the tag matches what's actually installed before this check runs.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional


@dataclass
class ChannelAllowlistEntry:
    """Entry in the channel allowlist."""
    marketplace: str
    plugin: str


def _validate_allowlist_entry(entry: Any) -> Optional[ChannelAllowlistEntry]:
    """
    Validate a single allowlist entry.
    
    Args:
        entry: Raw entry to validate
        
    Returns:
        ChannelAllowlistEntry if valid, None otherwise
    """
    if not isinstance(entry, dict):
        return None
    
    marketplace = entry.get('marketplace')
    plugin = entry.get('plugin')
    
    if not isinstance(marketplace, str) or not isinstance(plugin, str):
        return None
    
    return ChannelAllowlistEntry(marketplace=marketplace, plugin=plugin)


def validate_allowlist(raw: Any) -> List[ChannelAllowlistEntry]:
    """
    Validate the raw allowlist data.
    
    Args:
        raw: Raw data from feature flag
        
    Returns:
        List of valid ChannelAllowlistEntry objects
    """
    if not isinstance(raw, list):
        return []
    
    result = []
    for entry in raw:
        validated = _validate_allowlist_entry(entry)
        if validated:
            result.append(validated)
    
    return result


def get_channel_allowlist(
    get_feature_value: Optional[Callable[[str, Any], Any]] = None,
) -> List[ChannelAllowlistEntry]:
    """
    Get the channel allowlist from feature flags.
    
    Args:
        get_feature_value: Function to get feature flag value
        
    Returns:
        List of ChannelAllowlistEntry objects
    """
    if get_feature_value is None:
        return []
    
    raw = get_feature_value('tengu_harbor_ledger', [])
    return validate_allowlist(raw)


def is_channels_enabled(
    get_feature_value: Optional[Callable[[str, Any], Any]] = None,
) -> bool:
    """
    Overall channels on/off. Checked before any per-server gating —
    when false, --channels is a no-op and no handlers register.
    Default false; GrowthBook 5-min refresh.
    
    Args:
        get_feature_value: Function to get feature flag value
        
    Returns:
        True if channels are enabled
    """
    if get_feature_value is None:
        return False
    return bool(get_feature_value('tengu_harbor', False))


def parse_plugin_identifier(plugin_source: str) -> tuple:
    """
    Parse a plugin identifier string into name and marketplace components.
    
    Args:
        plugin_source: Plugin identifier (name or name@marketplace)
        
    Returns:
        Tuple of (name, marketplace or None)
        
    Note: Only the first '@' is used as separator. If the input contains multiple '@'
    symbols (e.g., "plugin@market@place"), everything after the second '@' is ignored.
    This is intentional as marketplace names should not contain '@'.
    """
    if '@' in plugin_source:
        parts = plugin_source.split('@')
        name = parts[0] if parts[0] else ''
        marketplace = parts[1] if len(parts) > 1 else None
        return name, marketplace
    return plugin_source, None


def is_channel_allowlisted(
    plugin_source: Optional[str],
    get_channel_allowlist_fn: Optional[Callable[[], List[ChannelAllowlistEntry]]] = None,
) -> bool:
    """
    Pure allowlist check keyed off the connection's pluginSource — for UI
    pre-filtering so the IDE only shows "Enable channel?" for servers that will
    actually pass the gate. Not a security boundary: channel_enable still runs
    the full gate. Matches the allowlist comparison inside gateChannelServer()
    but standalone (no session/marketplace coupling — those are tautologies
    when the entry is derived from pluginSource).
    
    Returns false for undefined pluginSource (non-plugin server — can never
    match the {marketplace, plugin}-keyed ledger) and for @-less sources
    (builtin/inline — same reason).
    
    Args:
        plugin_source: Plugin source identifier
        get_channel_allowlist_fn: Function to get the allowlist
        
    Returns:
        True if the plugin is on the allowlist
    """
    if not plugin_source:
        return False
    
    name, marketplace = parse_plugin_identifier(plugin_source)
    
    if not marketplace:
        return False
    
    allowlist = get_channel_allowlist_fn() if get_channel_allowlist_fn else []
    
    return any(
        e.plugin == name and e.marketplace == marketplace
        for e in allowlist
    )


__all__ = [
    'ChannelAllowlistEntry',
    'validate_allowlist',
    'get_channel_allowlist',
    'is_channels_enabled',
    'parse_plugin_identifier',
    'is_channel_allowlisted',
]
