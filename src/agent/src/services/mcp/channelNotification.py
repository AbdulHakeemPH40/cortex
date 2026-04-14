"""
services/mcp/channelNotification.py
Python conversion of services/mcp/channelNotification.ts (317 lines)

Channel notifications — lets an MCP server push user messages into the
conversation. A "channel" (Discord, Slack, SMS, etc.) is just an MCP server that:
  - exposes tools for outbound messages (e.g. `send_message`) — standard MCP
  - sends `notifications/claude/channel` notifications for inbound — this file
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union


# Meta keys become XML attribute NAMES — a crafted key like
# `x="" injected="y` would break out of the attribute structure. Only
# accept keys that look like plain identifiers. This is stricter than
# the XML spec (which allows `:`, `.`, `-`) but channel servers only
# send `chat_id`, `user`, `thread_ts`, `message_id` in practice.
SAFE_META_KEY = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

# Channel tag for XML wrapping
CHANNEL_TAG = 'channel'

# Permission notification method
CHANNEL_PERMISSION_METHOD = 'notifications/claude/channel/permission'

# Permission request method (outbound)
CHANNEL_PERMISSION_REQUEST_METHOD = 'notifications/claude/channel/permission_request'


def escape_xml_attr(value: str) -> str:
    """
    Escape a string for use as an XML attribute value.
    
    Args:
        value: String to escape
        
    Returns:
        Escaped string safe for XML attributes
    """
    return (
        value
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def wrap_channel_message(
    server_name: str,
    content: str,
    meta: Optional[Dict[str, str]] = None,
) -> str:
    """
    Wrap channel content in an XML tag for the conversation.
    
    Args:
        server_name: Name of the MCP server (source)
        content: Message content
        meta: Optional metadata to include as attributes
        
    Returns:
        XML-wrapped message string
    """
    attrs = ''
    
    if meta:
        for key, value in meta.items():
            if SAFE_META_KEY.match(key):
                attrs += f' {key}="{escape_xml_attr(value)}"'
    
    return f'<{CHANNEL_TAG} source="{escape_xml_attr(server_name)}"{attrs}>\n{content}\n</{CHANNEL_TAG}>'


@dataclass
class ChannelEntry:
    """Represents a parsed --channels entry."""
    name: str
    kind: str  # 'server' | 'plugin'
    marketplace: Optional[str] = None
    dev: bool = False


@dataclass
class ChannelAllowlistEntry:
    """Entry in the channel allowlist."""
    plugin: str
    marketplace: str


@dataclass
class ChannelGateResult:
    """Result of gating a channel server."""
    action: Literal['register', 'skip']
    kind: Optional[str] = None  # 'capability' | 'disabled' | 'auth' | 'policy' | 'session' | 'marketplace' | 'allowlist'
    reason: Optional[str] = None


@dataclass
class ChannelPermissionRequestParams:
    """Parameters for permission request notification."""
    request_id: str
    tool_name: str
    description: str
    # JSON-stringified tool input, truncated to 200 chars with …
    input_preview: str


def get_effective_channel_allowlist(
    sub: Optional[str],
    org_list: Optional[List[ChannelAllowlistEntry]],
    get_channel_allowlist: Callable[[], List[ChannelAllowlistEntry]],
) -> Tuple[List[ChannelAllowlistEntry], str]:
    """
    Get effective allowlist for the current session.
    
    Team/enterprise orgs can set allowedChannelPlugins in managed settings —
    when set, it REPLACES the GrowthBook ledger (admin owns the trust decision).
    Undefined falls back to the ledger. Unmanaged users always get the ledger.
    
    Args:
        sub: Subscription type ('team', 'enterprise', etc.)
        org_list: Org-managed allowlist entries
        get_channel_allowlist: Function to get ledger allowlist
        
    Returns:
        Tuple of (entries list, source string 'org' or 'ledger')
    """
    if sub in ('team', 'enterprise') and org_list is not None:
        return org_list, 'org'
    return get_channel_allowlist(), 'ledger'


def find_channel_entry(
    server_name: str,
    channels: List[ChannelEntry],
) -> Optional[ChannelEntry]:
    """
    Match a connected MCP server against the user's parsed --channels entries.
    
    server-kind is exact match on bare name; plugin-kind matches on the second
    segment of plugin:X:Y. Returns the matching entry so callers can read its
    kind — that's the user's trust declaration, not inferred from runtime shape.
    
    Args:
        server_name: Name of the MCP server
        channels: List of parsed channel entries
        
    Returns:
        Matching ChannelEntry or None
    """
    # split unconditionally — for a bare name like 'slack', parts is ['slack']
    # and the plugin-kind branch correctly never matches (parts[0] !== 'plugin').
    parts = server_name.split(':')
    
    for c in channels:
        if c.kind == 'server':
            if server_name == c.name:
                return c
        else:  # plugin-kind
            if parts[0] == 'plugin' and len(parts) > 1 and parts[1] == c.name:
                return c
    
    return None


def parse_plugin_identifier(plugin_source: str) -> Tuple[str, Optional[str]]:
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


def gate_channel_server(
    server_name: str,
    capabilities: Optional[Dict[str, Any]],
    plugin_source: Optional[str],
    is_channels_enabled: Callable[[], bool],
    get_oauth_tokens: Callable[[], Optional[Dict[str, Any]]],
    get_subscription_type: Callable[[], Optional[str]],
    get_settings_for_source: Callable[[str], Optional[Dict[str, Any]]],
    get_allowed_channels: Callable[[], List[ChannelEntry]],
    get_channel_allowlist: Callable[[], List[ChannelAllowlistEntry]],
) -> ChannelGateResult:
    """
    Gate an MCP server's channel-notification path.
    
    Gate order: capability → runtime gate (tengu_harbor) → auth (OAuth only) →
    org policy → session --channels → allowlist.
    
    API key users are blocked at the auth layer — channels requires
    claude.ai auth; console orgs have no admin opt-in surface yet.
    
    Args:
        server_name: Name of the MCP server
        capabilities: Server capabilities dict
        plugin_source: Plugin source identifier
        is_channels_enabled: Function to check if channels feature is enabled
        get_oauth_tokens: Function to get OAuth tokens
        get_subscription_type: Function to get subscription type
        get_settings_for_source: Function to get settings for a source
        get_allowed_channels: Function to get session --channels entries
        get_channel_allowlist: Function to get channel allowlist
        
    Returns:
        ChannelGateResult with action and optional reason
    """
    # Channel servers declare `experimental['claude/channel']: {}` (MCP's
    # presence-signal idiom — same as `tools: {}`). Truthy covers `{}` and
    # `true`; absent/undefined/explicit-`false` all fail.
    # IMPORTANT: In Python, {} is falsy unlike JS, so check 'is None' explicitly.
    experimental = (capabilities or {}).get('experimental', {})
    
    if experimental.get('claude/channel') is None:
        return ChannelGateResult(
            action='skip',
            kind='capability',
            reason='server did not declare claude/channel capability',
        )
    
    # Overall runtime gate. After capability so normal MCP servers never hit
    # this path. Before auth/policy so the killswitch works regardless of
    # session state.
    if not is_channels_enabled():
        return ChannelGateResult(
            action='skip',
            kind='disabled',
            reason='channels feature is not currently available',
        )
    
    # OAuth-only. API key users (console) are blocked — there's no
    # channelsEnabled admin surface in console yet.
    tokens = get_oauth_tokens()
    if not tokens or not tokens.get('accessToken'):
        return ChannelGateResult(
            action='skip',
            kind='auth',
            reason='channels requires claude.ai authentication (run /login)',
        )
    
    # Teams/Enterprise opt-in. Managed orgs must explicitly enable channels.
    # Default OFF — absent or false blocks.
    sub = get_subscription_type()
    managed = sub in ('team', 'enterprise')
    
    if managed:
        policy = get_settings_for_source('policySettings')
        if not policy or policy.get('channelsEnabled') is not True:
            return ChannelGateResult(
                action='skip',
                kind='policy',
                reason='channels not enabled by org policy (set channelsEnabled: true in managed settings)',
            )
    else:
        policy = None
    
    # User-level session opt-in. A server must be explicitly listed in
    # --channels to push inbound this session — protects against a trusted
    # server surprise-adding the capability.
    entry = find_channel_entry(server_name, get_allowed_channels())
    
    if not entry:
        return ChannelGateResult(
            action='skip',
            kind='session',
            reason=f'server {server_name} not in --channels list for this session',
        )
    
    if entry.kind == 'plugin':
        # Marketplace verification: the tag is intent (plugin:slack@anthropic),
        # the runtime name is just plugin:slack:X — could be slack@anthropic or
        # slack@evil depending on what's installed. Verify they match.
        actual = None
        if plugin_source:
            _, actual = parse_plugin_identifier(plugin_source)
        
        if actual != entry.marketplace:
            return ChannelGateResult(
                action='skip',
                kind='marketplace',
                reason=f'you asked for plugin:{entry.name}@{entry.marketplace} but the installed {entry.name} plugin is from {actual or "an unknown source"}',
            )
        
        # Approved-plugin allowlist. Marketplace gate already verified
        # tag == reality, so this is a pure entry check. entry.dev bypasses.
        if not entry.dev:
            org_list = policy.get('allowedChannelPlugins') if policy else None
            entries, source = get_effective_channel_allowlist(
                sub, org_list, get_channel_allowlist
            )
            
            is_allowed = any(
                e.plugin == entry.name and e.marketplace == entry.marketplace
                for e in entries
            )
            
            if not is_allowed:
                if source == 'org':
                    reason = f'plugin {entry.name}@{entry.marketplace} is not on your org\'s approved channels list (set allowedChannelPlugins in managed settings)'
                else:
                    reason = f'plugin {entry.name}@{entry.marketplace} is not on the approved channels allowlist (use --dangerously-load-development-channels for local dev)'
                return ChannelGateResult(
                    action='skip',
                    kind='allowlist',
                    reason=reason,
                )
    else:
        # server-kind: allowlist schema is {marketplace, plugin} — a server entry
        # can never match. Without this, --channels server:plugin:foo:bar would
        # match a plugin's runtime name and register with no allowlist check.
        if not entry.dev:
            return ChannelGateResult(
                action='skip',
                kind='allowlist',
                reason=f'server {entry.name} is not on the approved channels allowlist (use --dangerously-load-development-channels for local dev)',
            )
    
    return ChannelGateResult(action='register')


# Schema validation helpers (for JSON-RPC messages)

def validate_channel_message_notification(notification: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate a channel message notification.
    
    Expected format:
    {
        "method": "notifications/claude/channel",
        "params": {
            "content": string,
            "meta": { [key: string]: string } (optional)
        }
    }
    
    Args:
        notification: Notification dict to validate
        
    Returns:
        Validated params dict or None if invalid
    """
    if notification.get('method') != 'notifications/claude/channel':
        return None
    
    params = notification.get('params')
    if not isinstance(params, dict):
        return None
    
    content = params.get('content')
    if not isinstance(content, str):
        return None
    
    return params


def validate_channel_permission_notification(notification: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate a channel permission notification.
    
    Expected format:
    {
        "method": "notifications/claude/channel/permission",
        "params": {
            "request_id": string,
            "behavior": "allow" | "deny"
        }
    }
    
    Args:
        notification: Notification dict to validate
        
    Returns:
        Validated params dict or None if invalid
    """
    if notification.get('method') != CHANNEL_PERMISSION_METHOD:
        return None
    
    params = notification.get('params')
    if not isinstance(params, dict):
        return None
    
    request_id = params.get('request_id')
    behavior = params.get('behavior')
    
    if not isinstance(request_id, str):
        return None
    
    if behavior not in ('allow', 'deny'):
        return None
    
    return params


__all__ = [
    'SAFE_META_KEY',
    'CHANNEL_TAG',
    'CHANNEL_PERMISSION_METHOD',
    'CHANNEL_PERMISSION_REQUEST_METHOD',
    'ChannelEntry',
    'ChannelAllowlistEntry',
    'ChannelGateResult',
    'ChannelPermissionRequestParams',
    'escape_xml_attr',
    'wrap_channel_message',
    'get_effective_channel_allowlist',
    'find_channel_entry',
    'parse_plugin_identifier',
    'gate_channel_server',
    'validate_channel_message_notification',
    'validate_channel_permission_notification',
]
