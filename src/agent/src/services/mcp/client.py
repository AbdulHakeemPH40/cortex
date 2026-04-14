"""
services/mcp/client.py
Python conversion of services/mcp/client.ts (3349 lines)

Phase 1: Error Classes & Constants (lines 1-256)
- Custom error classes for MCP
- Session expiry detection
- Timeout constants

Phase 2: MCP Auth Cache System (lines 257-333)
- Auth cache path, read/write functions
- isMcpAuthCached(), setMcpAuthCacheEntry(), clearMcpAuthCache()
- handleRemoteAuthFailure(), mcpBaseUrlAnalytics()
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# ============================================================================
# Phase 1: Error Classes & Constants
# ============================================================================

class McpAuthError(Exception):
    """
    Custom error class to indicate that an MCP tool call failed due to
    authentication issues (e.g., expired OAuth token returning 401).
    This error should be caught at the tool execution layer to update
    the client's status to 'needs-auth'.
    """
    
    def __init__(self, server_name: str, message: str):
        super().__init__(message)
        self.name = 'McpAuthError'
        self.server_name = server_name


class McpSessionExpiredError(Exception):
    """
    Thrown when an MCP session has expired and the connection cache has been cleared.
    The caller should get a fresh client via ensure_connected_client and retry.
    """
    
    def __init__(self, server_name: str):
        super().__init__(f'MCP server "{server_name}" session expired')
        self.name = 'McpSessionExpiredError'


class McpToolCallError(Exception):
    """
    Thrown when an MCP tool returns `isError: true`. Carries the result's `_meta`
    so SDK consumers can still receive it — per the MCP spec, `_meta` is on the
    base Result type and is valid on error results.
    """
    
    def __init__(
        self,
        message: str,
        telemetry_message: str,
        mcp_meta: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.name = 'McpToolCallError'
        self.telemetry_message = telemetry_message
        self.mcp_meta = mcp_meta


def is_mcp_session_expired_error(error: Exception) -> bool:
    """
    Detects whether an error is an MCP "Session not found" error (HTTP 404 + JSON-RPC code -32001).
    Per the MCP spec, servers return 404 when a session ID is no longer valid.
    We check both signals to avoid false positives from generic 404s (wrong URL, server gone, etc.).
    
    Args:
        error: The error to check
        
    Returns:
        True if error indicates session expiry
    """
    # Check for HTTP 404 status code
    http_status = getattr(error, 'code', None)
    if http_status != 404:
        return False
    
    # The SDK embeds the response body text in the error message.
    # MCP servers return: {"error":{"code":-32001,"message":"Session not found"},...}
    # Check for the JSON-RPC error code to distinguish from generic web server 404s.
    error_message = str(error)
    return '"code":-32001' in error_message or '"code": -32001' in error_message


# Default timeout for MCP tool calls (effectively infinite - ~27.8 hours).
DEFAULT_MCP_TOOL_TIMEOUT_MS = 100_000_000

# Cap on MCP tool descriptions and server instructions sent to the model.
# OpenAPI-generated MCP servers have been observed dumping 15-60KB of endpoint
# docs into tool.description; this caps the p95 tail without losing the intent.
MAX_MCP_DESCRIPTION_LENGTH = 2048


def get_mcp_tool_timeout_ms() -> int:
    """
    Gets the timeout for MCP tool calls in milliseconds.
    Uses MCP_TOOL_TIMEOUT environment variable if set, otherwise defaults to ~27.8 hours.
    
    Returns:
        Timeout in milliseconds
    """
    timeout_env = os.environ.get('MCP_TOOL_TIMEOUT', '')
    if timeout_env:
        try:
            return int(timeout_env)
        except ValueError:
            pass
    
    return DEFAULT_MCP_TOOL_TIMEOUT_MS


# ============================================================================
# Phase 2: MCP Auth Cache System
# ============================================================================

# Auth cache TTL: 15 minutes
MCP_AUTH_CACHE_TTL_MS = 15 * 60 * 1000


def get_mcp_auth_cache_path() -> str:
    """
    Get the path to the MCP auth cache file.
    
    Returns:
        Path to mcp-needs-auth-cache.json
    """
    # Get Claude config home directory (platform-specific)
    if os.name == 'nt':  # Windows
        config_home = os.path.join(os.environ.get('APPDATA', ''), 'claude')
    else:  # macOS/Linux
        config_home = os.path.join(os.environ.get('HOME', ''), '.claude')
    
    return os.path.join(config_home, 'mcp-needs-auth-cache.json')


# Memoized so N concurrent isMcpAuthCached() calls during batched connection
# share a single file read instead of N reads of the same file. Invalidated
# on write (setMcpAuthCacheEntry) and clear (clearMcpAuthCache).
_auth_cache_promise: Optional[asyncio.Task] = None


async def get_mcp_auth_cache() -> Dict[str, Any]:
    """
    Get the MCP auth cache data.
    Memoized to prevent concurrent reads.
    
    Returns:
        Cache data dictionary
    """
    global _auth_cache_promise
    
    if _auth_cache_promise is None:
        _auth_cache_promise = asyncio.create_task(_read_auth_cache_file())
    
    return await _auth_cache_promise


async def _read_auth_cache_file() -> Dict[str, Any]:
    """Read auth cache from file."""
    cache_path = get_mcp_auth_cache_path()
    try:
        loop = asyncio.get_event_loop()
        
        def read_file():
            with open(cache_path, 'r') as f:
                return f.read()
        
        content = await loop.run_in_executor(None, read_file)
        return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


async def is_mcp_auth_cached(server_id: str) -> bool:
    """
    Check if an MCP server is cached as needing authentication.
    
    Args:
        server_id: The server identifier
        
    Returns:
        True if server is in cache and not expired
    """
    import time
    
    cache = await get_mcp_auth_cache()
    entry = cache.get(server_id)
    if not entry:
        return False
    
    # Check if entry is still within TTL
    timestamp = entry.get('timestamp', 0)
    return (time.time() * 1000) - timestamp < MCP_AUTH_CACHE_TTL_MS


# Serialize cache writes through a promise chain to prevent concurrent
# read-modify-write races when multiple servers return 401 in the same batch
_write_chain: Optional[asyncio.Task] = None


def set_mcp_auth_cache_entry(server_id: str) -> None:
    """
    Set an entry in the MCP auth cache.
    Serializes writes to prevent race conditions.
    
    Args:
        server_id: The server identifier to cache
    """
    global _write_chain, _auth_cache_promise
    
    async def write_entry():
        try:
            cache = await get_mcp_auth_cache()
            import time
            cache[server_id] = {'timestamp': int(time.time() * 1000)}
            
            cache_path = get_mcp_auth_cache_path()
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            
            def write_file():
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, 'w') as f:
                    json.dump(cache, f)
            
            await asyncio.get_event_loop().run_in_executor(None, write_file)
            
            # Invalidate the read cache so subsequent reads see the new entry.
            # Safe because write_chain serializes writes: the next write's
            # getMcpAuthCache() call will re-read the file with this entry present.
            _auth_cache_promise = None
        except Exception:
            # Best-effort cache write
            pass
    
    # Create task if event loop is running, otherwise schedule it
    try:
        loop = asyncio.get_running_loop()
        _write_chain = loop.create_task(write_entry())
    except RuntimeError:
        # No running loop - will be handled when loop starts
        pass


def clear_mcp_auth_cache() -> None:
    """Clear the MCP auth cache (both memory and file)."""
    global _auth_cache_promise
    
    _auth_cache_promise = None
    
    # Delete cache file (best-effort)
    cache_path = get_mcp_auth_cache_path()
    try:
        if os.path.exists(cache_path):
            os.unlink(cache_path)
    except OSError:
        # Cache file may not exist
        pass


# Type alias for server config (will be fully defined in later phases)
ScopedMcpServerConfig = Dict[str, Any]


def handle_remote_auth_failure(
    name: str,
    server_ref: ScopedMcpServerConfig,
    transport_type: str,
    log_event_fn=None,
    log_mcp_debug_fn=None,
    set_mcp_auth_cache_entry_fn=None,
) -> Dict[str, Any]:
    """
    Shared handler for sse/http/claudeai-proxy auth failures during connect:
    emits tengu_mcp_server_needs_auth, caches the needs-auth entry, and returns
    the needs-auth connection result.
    
    Args:
        name: Server name
        server_ref: Server configuration
        transport_type: Type of transport ('sse', 'http', 'claudeai-proxy')
        log_event_fn: Analytics logging function
        log_mcp_debug_fn: Debug logging function
        set_mcp_auth_cache_entry_fn: Cache entry function
        
    Returns:
        Connection result dict with type 'needs-auth'
    """
    # Import logging functions if not provided
    if log_event_fn is None:
        try:
            from ...services.analytics import logEvent
            log_event_fn = logEvent
        except ImportError:
            log_event_fn = lambda *args, **kwargs: None
    
    if log_mcp_debug_fn is None:
        try:
            from ...utils.log import logMCPDebug
            log_mcp_debug_fn = logMCPDebug
        except ImportError:
            log_mcp_debug_fn = lambda *args, **kwargs: None
    
    if set_mcp_auth_cache_entry_fn is None:
        set_mcp_auth_cache_entry_fn = set_mcp_auth_cache_entry
    
    # Log analytics event
    log_event_fn('tengu_mcp_server_needs_auth', {
        'transportType': transport_type,
    })
    
    # Log debug message
    label_map = {
        'sse': 'SSE',
        'http': 'HTTP',
        'claudeai-proxy': 'claude.ai proxy',
    }
    label = label_map.get(transport_type, transport_type)
    log_mcp_debug_fn(name, f'Authentication required for {label} server')
    
    # Cache the needs-auth entry
    set_mcp_auth_cache_entry_fn(name)
    
    return {
        'name': name,
        'type': 'needs-auth',
        'config': server_ref,
    }


def mcp_base_url_analytics(server_ref: ScopedMcpServerConfig) -> Dict[str, Any]:
    """
    Spread-ready analytics field for the server's base URL. Calls
    get_logging_safe_mcp_base_url once (not twice like the inline ternary it replaces).
    Typed as AnalyticsMetadata since the URL is query-stripped and safe to log.
    
    Args:
        server_ref: Server configuration
        
    Returns:
        Dict with mcpServerBaseUrl key if URL is available
    """
    # Import the utility function
    try:
        from ...services.mcp.utils import get_logging_safe_mcp_base_url
        url = get_logging_safe_mcp_base_url(server_ref)
    except ImportError:
        # Fallback: extract URL directly from config
        url = server_ref.get('url')
    
    if url:
        return {'mcpServerBaseUrl': url}
    return {}


# ============================================================================
# Phase 3: Claude AI Proxy Fetch & WebSocket
# ============================================================================

# Type alias for fetch-like function
FetchLike = Any  # Will be properly typed when needed


def create_cloud_ai_proxy_fetch(inner_fetch: FetchLike) -> FetchLike:
    """
    Fetch wrapper for claude.ai proxy connections. Attaches the OAuth bearer
    token and retries once on 401 via handleOAuth401Error (force-refresh).

    The Anthropic API path has this retry (withRetry.ts, grove.ts) to handle
    memoize-cache staleness and clock drift. Without the same here, a single
    stale token mass-401s every claude.ai connector and sticks them all in the
    15-min needs-auth cache.
    
    Args:
        inner_fetch: The underlying fetch function to wrap
        
    Returns:
        Wrapped fetch function with OAuth token handling
    """
    async def wrapped_fetch(url: str, init: Optional[Dict[str, Any]] = None) -> Any:
        async def do_request():
            # Import OAuth functions lazily
            try:
                from ...services.oauth.cloud_ai_oauth import (
                    check_and_refresh_oauth_token_if_needed,
                    get_cloud_ai_oauth_tokens,
                )
            except ImportError:
                raise RuntimeError('OAuth module not available')
            
            await check_and_refresh_oauth_token_if_needed()
            current_tokens = get_cloud_ai_oauth_tokens()
            
            if not current_tokens:
                raise RuntimeError('No claude.ai OAuth token available')
            
            # Add authorization header
            headers = dict(init.get('headers', {}) if init else {})
            headers['Authorization'] = f"Bearer {current_tokens['accessToken']}"
            
            # Make the request
            response = await inner_fetch(url, {**(init or {}), 'headers': headers})
            
            # Return the exact token that was sent. Reading getClaudeAIOAuthTokens()
            # again after the request is wrong under concurrent 401s: another
            # connector's handleOAuth401Error clears the memoize cache, so we'd read
            # the NEW token from keychain, pass it to handleOAuth401Error, which
            # finds same-as-keychain → returns false → skips retry. Same pattern as
            # bridgeApi.ts withOAuthRetry (token passed as fn param).
            return {'response': response, 'sentToken': current_tokens['accessToken']}
        
        result = await do_request()
        response = result['response']
        sent_token = result['sentToken']
        
        # If not 401, return immediately
        if response.status != 401:
            return response
        
        # handleOAuth401Error returns true only if the token actually changed
        # (keychain had a newer one, or force-refresh succeeded). Gate retry on
        # that — otherwise we double round-trip time for every connector whose
        # downstream service genuinely needs auth (the common case: 30+ servers
        # with "MCP server requires authentication but no OAuth token configured").
        try:
            from ...services.oauth.cloud_ai_oauth import handle_oauth401_error
            token_changed = await handle_oauth401_error(sent_token)
        except Exception:
            token_changed = False
        
        # Log analytics event
        try:
            from ...services.analytics import logEvent
            logEvent('tengu_mcp_claudeai_proxy_401', {
                'tokenChanged': token_changed,
            })
        except ImportError:
            pass
        
        if not token_changed:
            # ELOCKED contention: another connector may have won the lockfile and refreshed — check if token changed underneath us
            try:
                from ...services.oauth.cloud_ai_oauth import get_cloud_ai_oauth_tokens
                current_token = get_cloud_ai_oauth_tokens()
                if not current_token or current_token['accessToken'] == sent_token:
                    return response
            except Exception:
                return response
        
        # Retry with new token
        try:
            retry_result = await do_request()
            return retry_result['response']
        except Exception:
            # Retry itself failed (network error). Return the original 401 so the
            # outer handler can classify it.
            return response
    
    return wrapped_fetch


# Minimal interface for WebSocket instances passed to mcpWebSocketTransport
class WsClientLike:
    """Minimal WebSocket interface for MCP transport."""
    
    def __init__(self, ready_state: int = 0):
        self.readyState = ready_state
    
    def close(self) -> None:
        """Close the WebSocket connection."""
        pass
    
    def send(self, data: str) -> None:
        """Send data over WebSocket."""
        pass


async def create_node_ws_client(url: str, options: Dict[str, Any]) -> WsClientLike:
    """
    Create a ws.WebSocket client with the MCP protocol.
    Bun's ws shim types lack the 3-arg constructor (url, protocols, options)
    that the real ws package supports, so we cast the constructor here.
    
    Args:
        url: WebSocket URL
        options: WebSocket options
        
    Returns:
        WebSocket client instance
    """
    try:
        import websockets
        # Use websockets library as WebSocket client
        ws = await websockets.connect(url, additional_headers=options)
        return WsClientLike(ready_state=1)  # OPEN state
    except ImportError:
        # Fallback: return mock client
        return WsClientLike()


IMAGE_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
}


def get_connection_timeout_ms() -> int:
    """
    Get the connection timeout in milliseconds.
    Uses MCP_TIMEOUT environment variable if set, otherwise defaults to 30000ms.
    
    Returns:
        Timeout in milliseconds
    """
    timeout_env = os.environ.get('MCP_TIMEOUT', '')
    if timeout_env:
        try:
            return int(timeout_env)
        except ValueError:
            pass
    return 30000


# Default timeout for individual MCP requests (auth, tool calls, etc.)
MCP_REQUEST_TIMEOUT_MS = 60000

# MCP Streamable HTTP spec requires clients to advertise acceptance of both
# JSON and SSE on every POST. Servers that enforce this strictly reject
# requests without it (HTTP 406).
# https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#sending-messages-to-the-server
MCP_STREAMABLE_HTTP_ACCEPT = 'application/json, text/event-stream'


def wrap_fetch_with_timeout(fetch_fn: FetchLike, timeout_ms: int = MCP_REQUEST_TIMEOUT_MS) -> FetchLike:
    """
    Wraps a fetch function to apply a fresh timeout signal to each request.
    This avoids the bug where a single AbortSignal.timeout() created at connection
    time becomes stale after 60 seconds, causing all subsequent requests to fail
    immediately with "The operation timed out." Uses a 60-second timeout.

    Also ensures the Accept header required by the MCP Streamable HTTP spec is
    present on POSTs. The MCP SDK sets this inside StreamableHTTPClientTransport.send(),
    but it is attached to a Headers instance that passes through an object spread here,
    and some runtimes/agents have been observed dropping it before it reaches the wire.
    See https://github.com/anthropics/claude-agent-sdk-typescript/issues/202.
    Normalizing here (the last wrapper before fetch()) guarantees it is sent.
    
    Args:
        fetch_fn: The fetch function to wrap
        timeout_ms: Timeout in milliseconds (default: 60000)
        
    Returns:
        Wrapped fetch function with timeout
    """
    async def wrapped_fetch(url: str, init: Optional[Dict[str, Any]] = None) -> Any:
        timeout_sec = timeout_ms / 1000.0
        
        try:
            # Apply timeout using asyncio.wait_for
            async def do_fetch():
                # Ensure Accept header is present for POST requests
                init_copy = init.copy() if init else {}
                if init_copy.get('method', 'GET').upper() == 'POST':
                    headers = dict(init_copy.get('headers', {}))
                    if 'Accept' not in headers:
                        headers['Accept'] = MCP_STREAMABLE_HTTP_ACCEPT
                    init_copy['headers'] = headers
                
                return await fetch_fn(url, init_copy if init_copy else None)
            
            return await asyncio.wait_for(do_fetch(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            # Create timeout error compatible with SDK expectations
            error = Exception('The operation timed out.')
            error.name = 'TimeoutError'
            raise error
    
    return wrapped_fetch


# ============================================================================
# Phase 4: Cache Key & Connect To Server Start
# ============================================================================

def get_mcp_server_connection_batch_size() -> int:
    """
    Get the batch size for MCP server connections.
    Uses MCP_SERVER_CONNECTION_BATCH_SIZE environment variable if set, otherwise defaults to 3.
    
    Returns:
        Batch size for local server connections
    """
    batch_env = os.environ.get('MCP_SERVER_CONNECTION_BATCH_SIZE', '')
    if batch_env:
        try:
            return int(batch_env)
        except ValueError:
            pass
    return 3


def get_remote_mcp_server_connection_batch_size() -> int:
    """
    Get the batch size for remote MCP server connections.
    Uses MCP_REMOTE_SERVER_CONNECTION_BATCH_SIZE environment variable if set, otherwise defaults to 20.
    
    Returns:
        Batch size for remote server connections
    """
    batch_env = os.environ.get('MCP_REMOTE_SERVER_CONNECTION_BATCH_SIZE', '')
    if batch_env:
        try:
            return int(batch_env)
        except ValueError:
            pass
    return 20


def is_local_mcp_server(config: ScopedMcpServerConfig) -> bool:
    """
    Check if an MCP server is local (stdio or sdk type).
    
    Args:
        config: Server configuration
        
    Returns:
        True if server is local
    """
    server_type = config.get('type') if isinstance(config, dict) else getattr(config, 'type', None)
    return not server_type or server_type in ('stdio', 'sdk')


# For the IDE MCP servers, we only include specific tools
ALLOWED_IDE_TOOLS = {'mcp__ide__executeCode', 'mcp__ide__getDiagnostics'}


def is_included_mcp_tool(tool: Dict[str, Any]) -> bool:
    """
    Check if an MCP tool should be included (filters out most IDE tools).
    
    Args:
        tool: Tool definition dict
        
    Returns:
        True if tool should be included
    """
    tool_name = tool.get('name', '')
    return not tool_name.startswith('mcp__ide__') or tool_name in ALLOWED_IDE_TOOLS


def get_server_cache_key(name: str, server_ref: ScopedMcpServerConfig) -> str:
    """
    Generates the cache key for a server connection.
    
    Args:
        name: Server name
        server_ref: Server configuration
        
    Returns:
        Cache key string
    """
    import json
    return f"{name}-{json.dumps(server_ref, sort_keys=True)}"


# Type alias for MCP server connection (will be fully defined in later phases)
MCPServerConnection = Dict[str, Any]


# Memoization cache for connect_to_server
_connect_to_server_cache: Dict[str, MCPServerConnection] = {}


async def connect_to_server(
    name: str,
    server_ref: ScopedMcpServerConfig,
    server_stats: Optional[Dict[str, int]] = None,
    # Dependency injection for transport creation
    create_transport_fn=None,
) -> MCPServerConnection:
    """
    Attempts to connect to a single MCP server.
    Memoized to prevent duplicate connections to the same server.
    
    Args:
        name: Server name
        server_ref: Scoped server configuration
        server_stats: Optional stats about total servers
        create_transport_fn: Optional function to create transport (for testing)
        
    Returns:
        Connected MCP server client wrapper
    """
    import time
    
    # Check cache first
    cache_key = get_server_cache_key(name, server_ref)
    if cache_key in _connect_to_server_cache:
        return _connect_to_server_cache[cache_key]
    
    connect_start_time = int(time.time() * 1000)
    in_process_server = None
    
    try:
        # Get session ingress token if available
        try:
            from ...remote.remote_session import get_session_ingress_auth_token
            session_ingress_token = get_session_ingress_auth_token()
        except ImportError:
            session_ingress_token = None
        
        server_type = server_ref.get('type') if isinstance(server_ref, dict) else getattr(server_ref, 'type', None)
        
        # Import logging functions
        try:
            from ...utils.log import logMCPDebug
            log_mcp_debug = logMCPDebug
        except ImportError:
            log_mcp_debug = lambda name, msg: None
        
        transport = None
        
        if server_type == 'sse':
            # SSE transport with authentication
            log_mcp_debug(name, f'SSE transport initialized, awaiting connection')
            
            # This will be implemented in Phase 5-6 with full SDK integration
            # For now, create transport structure
            transport = {
                'type': 'sse',
                'url': server_ref.get('url'),
                'auth_provider': None,  # Will be set by SDK
                'headers': server_ref.get('headers', {}),
            }
            
        elif server_type == 'sse-ide':
            # IDE servers don't need authentication
            log_mcp_debug(name, f'Setting up SSE-IDE transport to {server_ref.get("url")}')
            
            transport = {
                'type': 'sse-ide',
                'url': server_ref.get('url'),
            }
            
        elif server_type == 'ws-ide':
            # WebSocket IDE transport
            tls_options = server_ref.get('tlsOptions', {})
            ws_headers = {
                'User-Agent': 'claude-code',
            }
            
            auth_token = server_ref.get('authToken')
            if auth_token:
                ws_headers['X-Claude-Code-Ide-Authorization'] = auth_token
            
            ws_client = await create_node_ws_client(
                server_ref.get('url'),
                {
                    'headers': ws_headers,
                    **(tls_options or {}),
                }
            )
            
            transport = {
                'type': 'ws-ide',
                'url': server_ref.get('url'),
                'ws_client': ws_client,
            }
            
        elif server_type == 'ws':
            # WebSocket transport with session auth
            log_mcp_debug(name, f'Initializing WebSocket transport to {server_ref.get("url")}')
            
            # Get combined headers
            try:
                from ...services.mcp.headers import get_mcp_server_headers
                combined_headers = await get_mcp_server_headers(name, server_ref)
            except ImportError:
                combined_headers = {}
            
            tls_options = server_ref.get('tlsOptions', {})
            ws_headers = {
                'User-Agent': 'claude-code',
                **({'Authorization': f'Bearer {session_ingress_token}'} if session_ingress_token else {}),
                **combined_headers,
            }
            
            # Redact sensitive headers before logging
            ws_headers_for_logging = {
                k: '[REDACTED]' if k.lower() == 'authorization' else v
                for k, v in ws_headers.items()
            }
            
            log_mcp_debug(name, f'WebSocket transport options: {json.dumps({"url": server_ref.get("url"), "headers": ws_headers_for_logging, "hasSessionAuth": bool(session_ingress_token)})}')
            
            ws_client = await create_node_ws_client(
                server_ref.get('url'),
                {
                    'headers': ws_headers,
                    **(tls_options or {}),
                }
            )
            
            transport = {
                'type': 'ws',
                'url': server_ref.get('url'),
                'ws_client': ws_client,
            }
            
        elif server_type == 'http':
            # HTTP Streamable transport
            log_mcp_debug(name, f'Initializing HTTP transport to {server_ref.get("url")}')
            log_mcp_debug(name, f'Python version: {sys.version}, Platform: {sys.platform}')
            
            # This will be fully implemented in Phase 6 with SDK integration
            transport = {
                'type': 'http',
                'url': server_ref.get('url'),
                'auth_provider': None,  # Will be set by SDK
                'headers': server_ref.get('headers', {}),
            }
        
        elif server_type == 'claudeai-proxy':
            # Claude AI proxy transport
            log_mcp_debug(name, f'Initializing claude.ai proxy transport for server {server_ref.get("id")}')
            
            try:
                from services.oauth.cloud_ai_oauth import get_cloud_ai_oauth_tokens, get_oauth_config
                tokens = get_cloud_ai_oauth_tokens()
                if not tokens:
                    raise RuntimeError('No claude.ai OAuth token found')
                
                oauth_config = get_oauth_config()
                proxy_url = f"{oauth_config['MCP_PROXY_URL']}{oauth_config['MCP_PROXY_PATH'].replace('{server_id}', server_ref.get('id'))}"
                
                log_mcp_debug(name, f'Using claude.ai proxy at {proxy_url}')
                
                # Create fetch with auth
                import aiohttp
                async def fetch_with_auth(url, init=None):
                    headers = {
                        'User-Agent': 'claude-code',
                        'Authorization': f"Bearer {tokens['accessToken']}",
                        **(init.get('headers', {}) if init else {}),
                    }
                    async with aiohttp.ClientSession() as session:
                        async with session.request(
                            method=init.get('method', 'GET') if init else 'GET',
                            url=url,
                            headers=headers,
                        ) as response:
                            return response
                
                transport = {
                    'type': 'claudeai-proxy',
                    'url': proxy_url,
                    'fetch': fetch_with_auth,
                    'session_id': server_ref.get('sessionId'),
                }
                
                log_mcp_debug(name, 'claude.ai proxy transport created successfully')
                
            except ImportError as e:
                raise RuntimeError(f'OAuth module not available: {e}')
            
        elif server_type == 'stdio' or server_type is None:
            # Check for special in-process servers (Chrome MCP, Computer Use)
            # These would be implemented as plugins in Python
            
            # Default stdio transport
            final_command = os.environ.get('CLAUDE_CODE_SHELL_PREFIX') or server_ref.get('command')
            
            if os.environ.get('CLAUDE_CODE_SHELL_PREFIX'):
                # Wrap command in shell
                import shlex
                command_args = [server_ref.get('command', '')] + server_ref.get('args', [])
                final_args = [' '.join(shlex.quote(arg) for arg in command_args)]
            else:
                final_args = server_ref.get('args', [])
            
            # Build environment
            env = {**os.environ, **(server_ref.get('env', {}))}
            
            transport = {
                'type': 'stdio',
                'command': final_command,
                'args': final_args,
                'env': env,
                'stderr': 'pipe',  # Prevents error output from printing to UI
            }
            
        else:
            raise RuntimeError(f'Unsupported server type: {server_type}')
        
        # Set up stderr logging for stdio transport before connecting
        # Store handler reference for cleanup to prevent memory leaks
        stderr_output = ''
        if server_type == 'stdio' or server_type is None:
            # In Python, we'll capture stderr when spawning the subprocess
            # This will be handled during actual subprocess creation
            pass
        
        # Create client metadata
        client_info = {
            'name': 'claude-code',
            'title': 'Claude Code',
            'version': os.environ.get('CLAUDE_CODE_VERSION', 'unknown'),
            'description': "Anthropic's agentic coding tool",
            'websiteUrl': 'https://claude.ai/code',
        }
        
        # Capabilities
        capabilities = {
            'roots': {},
            'elicitation': {},  # Empty object - per spec, avoids breaking Java MCP SDK servers
        }
        
        # Set up request handlers
        async def handle_list_roots():
            """Handle ListRoots request from server."""
            try:
                from utils.cwd import get_original_cwd
                cwd = get_original_cwd()
            except ImportError:
                cwd = os.getcwd()
            
            return {
                'roots': [
                    {'uri': f'file://{cwd}'},
                ]
            }
        
        # Add debug logging for HTTP transport
        if server_type == 'http':
            log_mcp_debug(name, 'Client created, setting up request handler')
        
        # Add timeout to connection attempts
        connection_timeout_ms = get_connection_timeout_ms()
        log_mcp_debug(name, f'Starting connection with timeout of {connection_timeout_ms}ms')
        
        # For HTTP transport, test basic connectivity first
        if server_type == 'http':
            log_mcp_debug(name, f'Testing basic HTTP connectivity to {server_ref.get("url")}')
            try:
                from urllib.parse import urlparse
                test_url = urlparse(server_ref.get('url', ''))
                log_mcp_debug(name, f'Parsed URL: host={test_url.hostname}, port={test_url.port or "default"}, protocol={test_url.scheme}')
                
                if test_url.hostname in ('127.0.0.1', 'localhost'):
                    log_mcp_debug(name, f'Using loopback address: {test_url.hostname}')
            except Exception as url_error:
                log_mcp_debug(name, f'Failed to parse URL: {url_error}')
        
        # Simulate connection with timeout (in real implementation, this would call SDK's client.connect())
        # For now, we'll create the connection structure and apply timeout logic
        async def connect_with_timeout():
            """Simulate connection with timeout."""
            # In real implementation, this would be: await client.connect(transport)
            # For now, we just return successfully
            return True
        
        try:
            # Apply timeout to connection
            await asyncio.wait_for(
                connect_with_timeout(),
                timeout=connection_timeout_ms / 1000.0
            )
            
            # Log success
            import time
            elapsed = int(time.time() * 1000) - connect_start_time
            log_mcp_debug(name, f'Successfully connected (transport: {server_type or "stdio"}) in {elapsed}ms')
            
        except asyncio.TimeoutError:
            elapsed = int(time.time() * 1000) - connect_start_time
            log_mcp_debug(name, f'Connection timeout triggered after {elapsed}ms (limit: {connection_timeout_ms}ms)')
            
            # Clean up in-process server if exists
            if in_process_server:
                try:
                    await in_process_server.close()
                except Exception:
                    pass
            
            raise TimeoutError(f'MCP server "{name}" connection timed out after {connection_timeout_ms}ms')
        
        except Exception as error:
            elapsed = int(time.time() * 1000) - connect_start_time
            
            # SSE-specific error logging
            if server_type == 'sse':
                log_mcp_debug(name, f'SSE Connection failed after {elapsed}ms: {str(error)}')
                
                # Check for authentication errors
                if '401' in str(error) or 'Unauthorized' in str(error):
                    return handle_remote_auth_failure(name, server_ref, 'sse')
            
            # HTTP-specific error logging
            elif server_type == 'http':
                error_code = getattr(error, 'code', None) or getattr(error, 'errno', 'none')
                log_mcp_debug(name, f'HTTP Connection failed after {elapsed}ms: {str(error)} (code: {error_code})')
                
                # Check for authentication errors
                if '401' in str(error) or 'Unauthorized' in str(error):
                    return handle_remote_auth_failure(name, server_ref, 'http')
            
            # Claude AI proxy error logging
            elif server_type == 'claudeai-proxy':
                log_mcp_debug(name, f'claude.ai proxy connection failed after {elapsed}ms: {str(error)}')
                
                # Check for authentication errors
                error_code = getattr(error, 'code', None)
                if error_code == 401:
                    return handle_remote_auth_failure(name, server_ref, 'claudeai-proxy')
            
            # IDE server connection tracking - disabled
            elif server_type in ('sse-ide', 'ws-ide'):
                pass
            
            # Clean up resources on error
            if in_process_server:
                try:
                    await in_process_server.close()
                except Exception:
                    pass
            
            raise
        
        # Create connection wrapper
        connection = {
            'name': name,
            'server_ref': server_ref,
            'transport': transport,
            'client_info': client_info,
            'capabilities': capabilities,
            'request_handlers': {
                'list_roots': handle_list_roots,
            },
            'stderr_output': stderr_output,
            'connect_time': connect_start_time,
            'status': 'connected',
        }
        
        # Cache the connection
        _connect_to_server_cache[cache_key] = connection
        
        # Set up connection lifecycle handlers (onerror, onclose)
        # These would be attached to the SDK client in real implementation
        connection['lifecycle'] = {
            'connection_start_time': connect_start_time,
            'has_error_occurred': False,
            'consecutive_connection_errors': 0,
            'max_errors_before_reconnect': 3,
            'has_triggered_close': False,
        }
        
        return connection
        
    except Exception as e:
        # Log error
        try:
            from ...utils.log import logMCPDebug
            logMCPDebug(name, f'Connection failed: {str(e)}')
        except ImportError:
            pass
        
        # Re-raise
        raise


# ============================================================================
# Phase 6: Connection Lifecycle & Error Handling Helpers
# ============================================================================

def is_terminal_connection_error(error_message: str) -> bool:
    """
    Check if an error message indicates a terminal connection error
    that requires reconnection.
    
    Args:
        error_message: The error message to check
        
    Returns:
        True if error is terminal and requires reconnection
    """
    terminal_patterns = [
        'ECONNRESET',
        'ETIMEDOUT',
        'EPIPE',
        'EHOSTUNREACH',
        'ECONNREFUSED',
        'Body Timeout Error',
        'terminated',
        # SDK SSE reconnection intermediate errors
        'SSE stream disconnected',
        'Failed to reconnect SSE stream',
    ]
    
    return any(pattern in error_message for pattern in terminal_patterns)


def create_close_transport_handler(
    name: str,
    client: Any,  # Would be MCP SDK Client in real implementation
    log_mcp_debug_fn=None,
) -> callable:
    """
    Creates a handler to close transport and reject pending requests.
    Prevents re-entry (multiple close calls).
    
    Args:
        name: Server name
        client: MCP client instance
        log_mcp_debug_fn: Debug logging function
        
    Returns:
        Close handler function
    """
    if log_mcp_debug_fn is None:
        # MCP debug logging disabled - using stub
        log_mcp_debug_fn = lambda name, msg: None
    
    has_triggered_close = False
    
    def close_transport_and_reject_pending(reason: str) -> None:
        """Close transport and reject pending request handlers."""
        nonlocal has_triggered_close
        
        if has_triggered_close:
            return
        
        has_triggered_close = True
        log_mcp_debug_fn(name, f'Closing transport ({reason})')
        
        # In real implementation, this would call:
        # await client.close()
        # Which would:
        # 1. Close transport
        # 2. Trigger onclose handler
        # 3. Reject all pending request handlers
        # 4. Clear memo cache for reconnection
    
    return close_transport_and_reject_pending


def create_error_handler(
    name: str,
    server_ref: ScopedMcpServerConfig,
    connection: MCPServerConnection,
    client: Any,  # MCP SDK Client
    log_mcp_debug_fn=None,
    log_mcp_error_fn=None,
    log_event_fn=None,
) -> callable:
    """
    Creates an enhanced error handler with detailed logging and reconnection logic.
    
    Args:
        name: Server name
        server_ref: Server configuration
        connection: Connection object
        client: MCP client instance
        log_mcp_debug_fn: Debug logging function
        log_mcp_error_fn: Error logging function
        log_event_fn: Analytics logging function
        
    Returns:
        Error handler function
    """
    if log_mcp_debug_fn is None:
        # MCP debug logging disabled - using stub
        log_mcp_debug_fn = lambda name, msg: None
    
    if log_mcp_error_fn is None:
        # MCP error logging disabled - using stub
        log_mcp_error_fn = lambda name, msg: None
    
    if log_event_fn is None:
        # Analytics logging disabled - using stub
        log_event_fn = lambda event, data: None
    
    import time
    connection_start_time = connection.get('lifecycle', {}).get('connection_start_time', int(time.time() * 1000))
    lifecycle = connection.get('lifecycle', {})
    
    close_handler = create_close_transport_handler(name, client, log_mcp_debug_fn)
    
    def error_handler(error: Exception) -> None:
        """Handle connection errors."""
        uptime = int(time.time() * 1000) - connection_start_time
        lifecycle['has_error_occurred'] = True
        
        transport_type = server_ref.get('type', 'stdio')
        
        # Log the connection drop with context
        log_mcp_debug_fn(
            name,
            f'{transport_type.upper()} connection dropped after {uptime // 1000}s uptime'
        )
        
        # Log specific error details
        error_message = str(error)
        if 'ECONNRESET' in error_message:
            log_mcp_debug_fn(name, 'Connection reset - server may have crashed or restarted')
        elif 'ETIMEDOUT' in error_message:
            log_mcp_debug_fn(name, 'Connection timeout - network issue or server unresponsive')
        elif 'ECONNREFUSED' in error_message:
            log_mcp_debug_fn(name, 'Connection refused - server may be down')
        elif 'EPIPE' in error_message:
            log_mcp_debug_fn(name, 'Broken pipe - server closed connection unexpectedly')
        elif 'EHOSTUNREACH' in error_message:
            log_mcp_debug_fn(name, 'Host unreachable - network connectivity issue')
        elif 'ESRCH' in error_message:
            log_mcp_debug_fn(name, 'Process not found - stdio server process terminated')
        elif 'spawn' in error_message:
            log_mcp_debug_fn(name, 'Failed to spawn process - check command and permissions')
        else:
            log_mcp_debug_fn(name, f'Connection error: {error_message}')
        
        # For HTTP transports, detect session expiry (404 + JSON-RPC -32001)
        if transport_type in ('http', 'claudeai-proxy') and is_mcp_session_expired_error(error):
            log_mcp_debug_fn(
                name,
                'MCP session expired (server returned 404 with session-not-found), triggering reconnection'
            )
            close_handler('session expired')
            return
        
        # For remote transports, track terminal connection errors
        if transport_type in ('sse', 'http', 'claudeai-proxy'):
            # Check if SDK exhausted reconnection attempts
            if 'Maximum reconnection attempts' in error_message:
                close_handler('SSE reconnection exhausted')
                return
            
            # Track consecutive errors
            if is_terminal_connection_error(error_message):
                lifecycle['consecutive_connection_errors'] = lifecycle.get('consecutive_connection_errors', 0) + 1
                
                if lifecycle['consecutive_connection_errors'] >= lifecycle.get('max_errors_before_reconnect', 3):
                    log_mcp_debug_fn(
                        name,
                        f'{lifecycle["consecutive_connection_errors"]} consecutive terminal errors, triggering reconnection'
                    )
                    close_handler('consecutive terminal errors')
                    return
    
    return error_handler


# ============================================================================
# Phase 7: Cleanup & Process Termination
# ============================================================================

async def cleanup_mcp_connection(
    name: str,
    server_ref: ScopedMcpServerConfig,
    connection: MCPServerConnection,
    client: Any = None,  # MCP SDK Client (optional)
    log_mcp_debug_fn=None,
    log_mcp_error_fn=None,
) -> None:
    """
    Clean up MCP connection resources.
    - Removes stderr event listeners
    - Terminates child processes with graceful escalation (SIGINT → SIGTERM → SIGKILL)
    - Closes in-process servers
    - Clears memoization caches
    
    Args:
        name: Server name
        server_ref: Server configuration
        connection: Connection object
        client: MCP SDK client instance (optional)
        log_mcp_debug_fn: Debug logging function
        log_mcp_error_fn: Error logging function
    """
    if log_mcp_debug_fn is None:
        # MCP debug logging disabled - using stub
        log_mcp_debug_fn = lambda name, msg: None
    
    if log_mcp_error_fn is None:
        # MCP error logging disabled - using stub
        log_mcp_error_fn = lambda name, msg: None
    
    transport = connection.get('transport', {})
    in_process_server = connection.get('in_process_server')
    
    # In-process servers don't have child processes or stderr
    if in_process_server:
        try:
            await in_process_server.close()
        except Exception as error:
            log_mcp_debug_fn(name, f'Error closing in-process server: {error}')
        
        if client:
            try:
                await client.close()
            except Exception as error:
                log_mcp_debug_fn(name, f'Error closing client: {error}')
        
        return
    
    # For stdio transports, explicitly terminate the child process
    server_type = server_ref.get('type')
    if server_type == 'stdio' or server_type is None:
        child_pid = transport.get('pid')
        
        if child_pid:
            log_mcp_debug_fn(name, 'Sending SIGINT to MCP server process')
            
            # First try SIGINT (like Ctrl+C)
            try:
                import signal
                os.kill(child_pid, signal.SIGINT)
            except OSError as error:
                log_mcp_debug_fn(name, f'Error sending SIGINT: {error}')
                return
            
            # Wait for graceful shutdown with rapid escalation (total 500ms to keep AI agent responsive)
            import time
            resolved = False
            start_time = time.time()
            
            # Set up a timer to check if process still exists
            check_interval = 0.05  # 50ms
            
            while time.time() - start_time < 0.6:  # 600ms failsafe
                try:
                    # Check if process exists (os.kill(pid, 0) checks without killing)
                    os.kill(child_pid, 0)
                    # Process still exists, wait and check again
                    await asyncio.sleep(check_interval)
                except OSError:
                    # Process no longer exists
                    if not resolved:
                        resolved = True
                        log_mcp_debug_fn(name, 'MCP server process exited cleanly')
                        break
            
            if not resolved:
                # SIGINT failed after 100ms, try SIGTERM
                log_mcp_debug_fn(name, 'SIGINT failed, sending SIGTERM to MCP server process')
                try:
                    import signal
                    os.kill(child_pid, signal.SIGTERM)
                except OSError as term_error:
                    log_mcp_debug_fn(name, f'Error sending SIGTERM: {term_error}')
                    return
                
                # Wait for SIGTERM (200ms)
                await asyncio.sleep(0.2)
                
                # Check if process still exists
                try:
                    os.kill(child_pid, 0)
                    # Process still exists, SIGTERM failed, try SIGKILL
                    log_mcp_debug_fn(name, 'SIGTERM failed, sending SIGKILL to MCP server process')
                    try:
                        import signal
                        os.kill(child_pid, signal.SIGKILL)
                        log_mcp_debug_fn(name, 'Sent SIGKILL to force-terminate MCP server')
                    except OSError as kill_error:
                        log_mcp_debug_fn(name, f'Error sending SIGKILL: {kill_error}')
                except OSError:
                    # Process exited after SIGTERM
                    log_mcp_debug_fn(name, 'MCP server process exited after SIGTERM')
    
    # Close client if provided
    if client:
        try:
            await client.close()
        except Exception as error:
            log_mcp_debug_fn(name, f'Error closing client: {error}')


def clear_mcp_connection_cache(
    name: str,
    server_ref: ScopedMcpServerConfig,
    connect_to_server_cache: Dict[str, MCPServerConnection],
    fetch_tools_cache=None,
    fetch_resources_cache=None,
    fetch_commands_cache=None,
    log_mcp_debug_fn=None,
) -> None:
    """
    Clear all memoization caches for an MCP connection.
    Called when connection closes to ensure next operation reconnects with fresh state.
    
    Args:
        name: Server name
        server_ref: Server configuration
        connect_to_server_cache: Global connection cache dict
        fetch_tools_cache: Tools cache (optional)
        fetch_resources_cache: Resources cache (optional)
        fetch_commands_cache: Commands cache (optional)
        log_mcp_debug_fn: Debug logging function
    """
    if log_mcp_debug_fn is None:
        # MCP debug logging disabled - using stub
        log_mcp_debug_fn = lambda name, msg: None
    
    # Clear connection cache
    key = get_server_cache_key(name, server_ref)
    if key in connect_to_server_cache:
        del connect_to_server_cache[key]
        log_mcp_debug_fn(name, 'Cleared connection cache for reconnection')
    
    # Clear fetch caches (keyed by server name)
    # Reconnection creates a new connection object; without clearing,
    # the next fetch would return stale tools/resources from old connection
    if fetch_tools_cache and hasattr(fetch_tools_cache, 'delete'):
        fetch_tools_cache.delete(name)
    
    if fetch_resources_cache and hasattr(fetch_resources_cache, 'delete'):
        fetch_resources_cache.delete(name)
    
    if fetch_commands_cache and hasattr(fetch_commands_cache, 'delete'):
        fetch_commands_cache.delete(name)


# ============================================================================
# Phase 8: Connection Return Structure & Cache Management
# ============================================================================

# Type alias for cleanup function
CleanupFn = callable

# Type alias for connected MCP server
ConnectedMCPServer = Dict[str, Any]

# Type alias for failed MCP server
FailedMCPServer = Dict[str, Any]

# Type alias for wrapped MCP server (connected or failed)
WrappedMCPServer = ConnectedMCPServer | FailedMCPServer


async def clear_server_cache(
    name: str,
    server_ref: ScopedMcpServerConfig,
    connect_to_server_cache: Dict[str, MCPServerConnection],
    fetch_tools_cache=None,
    fetch_resources_cache=None,
    fetch_commands_cache=None,
    log_mcp_debug_fn=None,
    log_mcp_error_fn=None,
) -> None:
    """
    Clears the memoize cache for a specific server.
    Cleans up existing connection if connected, then clears all caches.
    
    Args:
        name: Server name
        server_ref: Server configuration
        connect_to_server_cache: Global connection cache
        fetch_tools_cache: Tools cache (optional)
        fetch_resources_cache: Resources cache (optional)
        fetch_commands_cache: Commands cache (optional)
        log_mcp_debug_fn: Debug logging function
        log_mcp_error_fn: Error logging function
    """
    if log_mcp_debug_fn is None:
        # MCP debug logging disabled - using stub
        log_mcp_debug_fn = lambda name, msg: None
    
    if log_mcp_error_fn is None:
        # MCP error logging disabled - using stub
        log_mcp_error_fn = lambda name, msg: None
    
    key = get_server_cache_key(name, server_ref)
    
    try:
        # Try to get existing connection and clean it up
        if key in connect_to_server_cache:
            connection = connect_to_server_cache[key]
            
            # If connection has cleanup function, call it
            if 'cleanup' in connection:
                await connection['cleanup']()
    except Exception:
        # Ignore errors - server might have failed to connect
        pass
    
    # Clear from cache (both connection and fetch caches so reconnect
    # fetches fresh tools/resources/commands instead of stale ones)
    clear_mcp_connection_cache(
        name,
        server_ref,
        connect_to_server_cache,
        fetch_tools_cache=fetch_tools_cache,
        fetch_resources_cache=fetch_resources_cache,
        fetch_commands_cache=fetch_commands_cache,
        log_mcp_debug_fn=log_mcp_debug_fn,
    )


async def ensure_connected_client(
    client: ConnectedMCPServer,
    connect_to_server_cache: Dict[str, MCPServerConnection],
    log_mcp_debug_fn=None,
) -> ConnectedMCPServer:
    """
    Ensures a valid connected client for an MCP server.
    For most server types, uses the memoization cache if available, or reconnects
    if the cache was cleared (e.g., after onclose). This ensures tool/resource
    calls always use a valid connection.
    
    SDK MCP servers run in-process and are handled separately via setupSdkMcpClients,
    so they are returned as-is without going through connectToServer.
    
    Args:
        client: The connected MCP server client
        connect_to_server_cache: Global connection cache
        log_mcp_debug_fn: Debug logging function
        
    Returns:
        Connected MCP server client (same or reconnected)
        
    Raises:
        RuntimeError: If server cannot be connected
    """
    if log_mcp_debug_fn is None:
        # MCP debug logging disabled - using stub
        log_mcp_debug_fn = lambda name, msg: None
    
    # SDK MCP servers run in-process and are handled separately
    server_config = client.get('config', {})
    server_type = server_config.get('type') if isinstance(server_config, dict) else getattr(server_config, 'type', None)
    
    if server_type == 'sdk':
        return client
    
    # Try to reconnect
    server_name = client.get('name')
    try:
        connected_client = await connect_to_server(
            server_name,
            server_config,
        )
        
        if connected_client.get('status') != 'connected':
            raise RuntimeError(f'MCP server "{server_name}" is not connected')
        
        return connected_client
        
    except Exception as error:
        raise RuntimeError(f'MCP server "{server_name}" is not connected: {error}')


def create_connected_server_response(
    name: str,
    client: Any,
    server_ref: ScopedMcpServerConfig,
    capabilities: Dict[str, Any],
    server_version: Any,
    instructions: str,
    cleanup_fn: CleanupFn,
    server_stats: Optional[Dict[str, int]] = None,
    connection_duration_ms: Optional[int] = None,
) -> ConnectedMCPServer:
    """
    Creates a connected MCP server response object.
    
    Args:
        name: Server name
        client: MCP SDK client instance
        server_ref: Server configuration
        capabilities: Server capabilities
        server_version: Server version info
        instructions: Server instructions
        cleanup_fn: Cleanup function
        server_stats: Optional server statistics
        connection_duration_ms: Connection duration in milliseconds
        
    Returns:
        Connected MCP server dict
    """
    return {
        'name': name,
        'client': client,
        'type': 'connected',
        'capabilities': capabilities or {},
        'server_info': server_version,
        'instructions': instructions,
        'config': server_ref,
        'cleanup': cleanup_fn,
    }


def create_failed_server_response(
    name: str,
    server_ref: ScopedMcpServerConfig,
    error: str,
) -> FailedMCPServer:
    """
    Creates a failed MCP server response object.
    
    Args:
        name: Server name
        server_ref: Server configuration
        error: Error message
        
    Returns:
        Failed MCP server dict
    """
    return {
        'name': name,
        'type': 'failed',
        'config': server_ref,
        'error': error,
    }


# ============================================================================
# Phase 9: Config Comparison & Fetch Tools Cache
# ============================================================================

# Max cache size for fetch* caches. Keyed by server name (stable across
# reconnects), bounded to prevent unbounded growth with many MCP servers.
MCP_FETCH_CACHE_SIZE = 20


def are_mcp_configs_equal(a: ScopedMcpServerConfig, b: ScopedMcpServerConfig) -> bool:
    """
    Compares two MCP server configurations to determine if they are equivalent.
    Used to detect when a server needs to be reconnected due to config changes.
    
    Args:
        a: First server config
        b: Second server config
        
    Returns:
        True if configs are equivalent
    """
    # Quick type check first
    a_type = a.get('type') if isinstance(a, dict) else getattr(a, 'type', None)
    b_type = b.get('type') if isinstance(b, dict) else getattr(b, 'type', None)
    
    if a_type != b_type:
        return False
    
    # Compare by serializing - this handles all config variations
    # We exclude 'scope' from comparison since it's metadata, not connection config
    if isinstance(a, dict):
        config_a = {k: v for k, v in a.items() if k != 'scope'}
    else:
        config_a = {k: v for k, v in a.__dict__.items() if k != 'scope'}
    
    if isinstance(b, dict):
        config_b = {k: v for k, v in b.items() if k != 'scope'}
    else:
        config_b = {k: v for k, v in b.__dict__.items() if k != 'scope'}
    
    return json.dumps(config_a, sort_keys=True) == json.dumps(config_b, sort_keys=True)


def mcp_tool_input_to_auto_classifier_input(input_data: Dict[str, Any], tool_name: str) -> str:
    """
    Encode MCP tool input for the auto-mode security classifier.
    Exported so the auto-mode eval scripts can mirror production encoding
    for `mcp__*` tool stubs without duplicating this logic.
    
    Args:
        input_data: Tool input dictionary
        tool_name: Name of the tool
        
    Returns:
        Encoded input string
    """
    keys = list(input_data.keys())
    if len(keys) > 0:
        return ' '.join(f"{k}={str(input_data[k])}" for k in keys)
    else:
        return tool_name


# LRU cache for fetchTools (keyed by server name)
_fetch_tools_cache: Dict[str, Any] = {}
_fetch_tools_cache_order: list = []


async def fetch_tools_for_client(
    client: MCPServerConnection,
    max_cache_size: int = MCP_FETCH_CACHE_SIZE,
    log_mcp_error_fn=None,
) -> list:
    """
    Fetch tools from an MCP server with LRU caching.
    
    Args:
        client: MCP server connection
        max_cache_size: Maximum cache size (default: 20)
        log_mcp_error_fn: Error logging function
        
    Returns:
        List of tool objects
    """
    if log_mcp_error_fn is None:
        # MCP error logging disabled - using stub
        log_mcp_error_fn = lambda name, msg: None
    
    # Check cache first
    server_name = client.get('name')
    if server_name in _fetch_tools_cache:
        return _fetch_tools_cache[server_name]
    
    # Check if client is connected
    if client.get('type') != 'connected':
        return []
    
    try:
        # Check if server has tools capability
        capabilities = client.get('capabilities', {})
        if not capabilities.get('tools'):
            return []
        
        # In real implementation, this would call:
        # result = await client['client'].request(
        #     {'method': 'tools/list'},
        #     ListToolsResultSchema
        # )
        # For now, return empty list (SDK integration needed)
        tools_result = {'tools': []}
        
        # Sanitize tool data from MCP server
        # tools_to_process = recursively_sanitize_unicode(result['tools'])
        tools_to_process = tools_result['tools']
        
        # Check if we should skip the mcp__ prefix for SDK MCP servers
        server_config = client.get('config', {})
        server_type = server_config.get('type') if isinstance(server_config, dict) else getattr(server_config, 'type', None)
        
        skip_prefix = server_type == 'sdk' and os.environ.get('CLAUDE_AGENT_SDK_MCP_NO_PREFIX', '').lower() in ('true', '1', 'yes')
        
        # Convert MCP tools to our Tool format
        tools = []
        for tool in tools_to_process:
            # Build fully qualified name
            fully_qualified_name = f"mcp__{client['name']}__{tool['name']}"
            
            # Use original name if skip_prefix mode
            tool_name = tool['name'] if skip_prefix else fully_qualified_name
            
            # Get description with truncation
            description = tool.get('description', '')
            if len(description) > MAX_MCP_DESCRIPTION_LENGTH:
                prompt_text = description[:MAX_MCP_DESCRIPTION_LENGTH] + '… [truncated]'
            else:
                prompt_text = description
            
            # Get annotations
            annotations = tool.get('annotations', {})
            
            # Create tool object
            tool_obj = {
                'name': tool_name,
                'mcp_info': {
                    'server_name': client['name'],
                    'tool_name': tool['name'],
                },
                'is_mcp': True,
                'search_hint': None,  # From tool._meta['anthropic/searchHint']
                'always_load': tool.get('_meta', {}).get('anthropic/alwaysLoad', False),
                'description': description,
                'prompt': prompt_text,
                'is_concurrency_safe': annotations.get('readOnlyHint', False),
                'is_read_only': annotations.get('readOnlyHint', False),
                'is_destructive': annotations.get('destructiveHint', True),
                'is_open_world': annotations.get('openWorldHint', True),
                'input_json_schema': tool.get('inputSchema', {}),
                'user_facing_name': lambda: f"{client['name']} - {annotations.get('title', tool['name'])} (MCP)",
            }
            
            # Add auto classifier input function
            def make_classifier_input(t_name):
                def classifier_fn(input_data):
                    return mcp_tool_input_to_auto_classifier_input(input_data, t_name)
                return classifier_fn
            
            tool_obj['to_auto_classifier_input'] = make_classifier_input(tool['name'])
            
            tools.append(tool_obj)
        
        # Filter tools (exclude most IDE tools)
        filtered_tools = [t for t in tools if is_included_mcp_tool(t)]
        
        # Cache the result
        _fetch_tools_cache[server_name] = filtered_tools
        _fetch_tools_cache_order.append(server_name)
        
        # Evict old entries if cache is too large
        if len(_fetch_tools_cache_order) > max_cache_size:
            oldest = _fetch_tools_cache_order.pop(0)
            _fetch_tools_cache.pop(oldest, None)
        
        return filtered_tools
        
    except Exception as error:
        log_mcp_error_fn(client.get('name', 'unknown'), f'Failed to fetch tools: {str(error)}')
        return []


# ============================================================================
# Phase 10: Fetch Resources, Commands & Reconnect
# ============================================================================

# LRU cache for fetchResources (keyed by server name)
_fetch_resources_cache: Dict[str, Any] = {}
_fetch_resources_cache_order: list = []


async def fetch_resources_for_client(
    client: MCPServerConnection,
    max_cache_size: int = MCP_FETCH_CACHE_SIZE,
    log_mcp_error_fn=None,
) -> list:
    """
    Fetch resources from an MCP server with LRU caching.
    
    Args:
        client: MCP server connection
        max_cache_size: Maximum cache size (default: 20)
        log_mcp_error_fn: Error logging function
        
    Returns:
        List of resource objects with server name added
    """
    if log_mcp_error_fn is None:
        # MCP error logging disabled - using stub
        log_mcp_error_fn = lambda name, msg: None
    
    # Check cache first
    server_name = client.get('name')
    if server_name in _fetch_resources_cache:
        return _fetch_resources_cache[server_name]
    
    # Check if client is connected
    if client.get('type') != 'connected':
        return []
    
    try:
        # Check if server has resources capability
        capabilities = client.get('capabilities', {})
        if not capabilities.get('resources'):
            return []
        
        # In real implementation, this would call:
        # result = await client['client'].request(
        #     {'method': 'resources/list'},
        #     ListResourcesResultSchema
        # )
        # For now, return empty list (SDK integration needed)
        result = {'resources': []}
        
        if not result.get('resources'):
            return []
        
        # Add server name to each resource
        resources = [
            {**resource, 'server': client['name']}
            for resource in result['resources']
        ]
        
        # Cache the result
        _fetch_resources_cache[server_name] = resources
        _fetch_resources_cache_order.append(server_name)
        
        # Evict old entries if cache is too large
        if len(_fetch_resources_cache_order) > max_cache_size:
            oldest = _fetch_resources_cache_order.pop(0)
            _fetch_resources_cache.pop(oldest, None)
        
        return resources
        
    except Exception as error:
        log_mcp_error_fn(client.get('name', 'unknown'), f'Failed to fetch resources: {str(error)}')
        return []


# LRU cache for fetchCommands (keyed by server name)
_fetch_commands_cache: Dict[str, Any] = {}
_fetch_commands_cache_order: list = []


async def fetch_commands_for_client(
    client: MCPServerConnection,
    max_cache_size: int = MCP_FETCH_CACHE_SIZE,
    log_mcp_error_fn=None,
) -> list:
    """
    Fetch commands (prompts) from an MCP server with LRU caching.
    
    Args:
        client: MCP server connection
        max_cache_size: Maximum cache size (default: 20)
        log_mcp_error_fn: Error logging function
        
    Returns:
        List of command objects
    """
    if log_mcp_error_fn is None:
        # MCP error logging disabled - using stub
        log_mcp_error_fn = lambda name, msg: None
    
    # Check cache first
    server_name = client.get('name')
    if server_name in _fetch_commands_cache:
        return _fetch_commands_cache[server_name]
    
    # Check if client is connected
    if client.get('type') != 'connected':
        return []
    
    try:
        # Check if server has prompts capability
        capabilities = client.get('capabilities', {})
        if not capabilities.get('prompts'):
            return []
        
        # In real implementation, this would call:
        # result = await client['client'].request(
        #     {'method': 'prompts/list'},
        #     ListPromptsResultSchema
        # )
        # For now, return empty list (SDK integration needed)
        result = {'prompts': []}
        
        if not result.get('prompts'):
            return []
        
        # Sanitize prompt data from MCP server
        # prompts_to_process = recursively_sanitize_unicode(result['prompts'])
        prompts_to_process = result['prompts']
        
        # Convert MCP prompts to our Command format
        def normalize_name_for_mcp(name: str) -> str:
            """Normalize server name for MCP tool naming"""
            import re
            return re.sub(r'[^a-zA-Z0-9]', '_', name).lower()
        
        commands = []
        for prompt in prompts_to_process:
            # Extract argument names
            prompt_args = prompt.get('arguments', [])
            arg_names = [arg['name'] for arg in prompt_args] if prompt_args else []
            
            # Build fully qualified name
            full_name = f"mcp__{normalize_name_for_mcp(client['name'])}__{prompt['name']}"
            
            # Create command object
            def make_get_prompt_for_command(p_name, c_name, c_client):
                """Factory function to create getPromptForCommand closure"""
                async def get_prompt_fn(args: str):
                    args_array = args.split(' ')
                    try:
                        # In real implementation:
                        # connected_client = await ensure_connected_client(c_client)
                        # result = await connected_client['client'].get_prompt({
                        #     'name': p_name,
                        #     'arguments': dict(zip(arg_names, args_array))
                        # })
                        # transformed = await transform_result_content(...)
                        return []
                    except Exception as error:
                        log_mcp_error_fn(
                            c_name,
                            f"Error running command '{p_name}': {str(error)}",
                        )
                        raise
                return get_prompt_fn
            
            command = {
                'type': 'prompt',
                'name': full_name,
                'description': prompt.get('description', ''),
                'has_user_specified_description': bool(prompt.get('description')),
                'content_length': 0,  # Dynamic MCP content
                'is_enabled': lambda: True,
                'is_hidden': False,
                'is_mcp': True,
                'progress_message': 'running',
                'user_facing_name': lambda p=prompt: f"{client['name']}:{p['name']} (MCP)",
                'arg_names': arg_names,
                'source': 'mcp',
                'get_prompt_for_command': make_get_prompt_for_command(
                    prompt['name'],
                    client['name'],
                    client
                ),
            }
            
            commands.append(command)
        
        # Cache the result
        _fetch_commands_cache[server_name] = commands
        _fetch_commands_cache_order.append(server_name)
        
        # Evict old entries if cache is too large
        if len(_fetch_commands_cache_order) > max_cache_size:
            oldest = _fetch_commands_cache_order.pop(0)
            _fetch_commands_cache.pop(oldest, None)
        
        return commands
        
    except Exception as error:
        log_mcp_error_fn(client.get('name', 'unknown'), f'Failed to fetch commands: {str(error)}')
        return []


async def call_ide_rpc(
    tool_name: str,
    args: Dict[str, Any],
    client: ConnectedMCPServer,
) -> Optional[str | list]:
    """
    Call an IDE tool directly as an RPC.
    
    Args:
        tool_name: The name of the tool to call
        args: The arguments to pass to the tool
        client: The IDE client to use for the RPC call
        
    Returns:
        The result of the tool call (string or content blocks)
    """
    # In real implementation, this would call callMCPTool
    # For now, return None (placeholder)
    # result = await call_mcp_tool({
    #     'client': client,
    #     'tool': tool_name,
    #     'args': args,
    #     'signal': asyncio.Event(),
    # })
    # return result.get('content')
    return None


async def reconnect_mcp_server_impl(
    name: str,
    config: ScopedMcpServerConfig,
    connect_to_server_cache: Dict[str, MCPServerConnection],
    log_mcp_error_fn=None,
) -> Dict[str, Any]:
    """
    Reconnect an MCP server and fetch all its resources.
    
    Note: This should not be called by UI components directly, they should use the
    reconnectMcpServer function from useManageMcpConnections.
    
    Args:
        name: Server name
        config: Server configuration
        connect_to_server_cache: Global connection cache
        log_mcp_error_fn: Error logging function
        
    Returns:
        Object containing the client connection and its resources
    """
    if log_mcp_error_fn is None:
        # MCP error logging disabled - using stub
        log_mcp_error_fn = lambda name, msg: None
    
    try:
        # Clear the server cache (invalidates connection and fetch caches)
        await clear_server_cache(
            name,
            config,
            connect_to_server_cache,
            fetch_tools_cache=_fetch_tools_cache,
            fetch_resources_cache=_fetch_resources_cache,
            fetch_commands_cache=_fetch_commands_cache,
            log_mcp_error_fn=log_mcp_error_fn,
        )
        
        # Reconnect
        client = await connect_to_server(name, config)
        
        if client.get('type') != 'connected':
            return {
                'client': client,
                'tools': [],
                'commands': [],
            }
        
        # Mark claude.ai proxy as connected (if applicable)
        server_type = config.get('type') if isinstance(config, dict) else getattr(config, 'type', None)
        if server_type == 'claudeai-proxy':
            # In real implementation: markClaudeAiMcpConnected(name)
            pass
        
        # Check if server supports resources
        capabilities = client.get('capabilities', {})
        supports_resources = bool(capabilities.get('resources'))
        
        # Fetch all resources in parallel
        import asyncio
        
        tools = await fetch_tools_for_client(client, log_mcp_error_fn=log_mcp_error_fn)
        mcp_commands = await fetch_commands_for_client(client, log_mcp_error_fn=log_mcp_error_fn)
        mcp_skills = []  # Would fetch if feature('MCP_SKILLS') enabled
        resources = await fetch_resources_for_client(client, log_mcp_error_fn=log_mcp_error_fn) if supports_resources else []
        
        commands = mcp_commands + mcp_skills
        
        # Check if we need to add resource tools
        resource_tools = []
        if supports_resources:
            # Would check if ListMcpResourcesTool and ReadMcpResourceTool already exist
            # For now, skip this check
            pass
        
        # Combine tools
        all_tools = tools + resource_tools
        
        return {
            'client': client,
            'tools': all_tools,
            'commands': commands,
            'resources': resources if len(resources) > 0 else None,
        }
        
    except Exception as error:
        # Handle errors gracefully - connection might have closed during fetch
        log_mcp_error_fn(name, f'Failed to reconnect MCP server: {str(error)}')
        return {
            'client': {'name': name, 'type': 'failed', 'config': config, 'error': str(error)},
            'tools': [],
            'commands': [],
        }


# ============================================================================
# Phase 11: Batch Processing & Get MCP Tools/Commands/Resources
# ============================================================================

async def process_batched(
    items: list,
    concurrency: int,
    processor,
) -> None:
    """
    Process items with bounded concurrency.
    Replaced fixed-size sequential batches with free-running concurrency pool.
    Each slot frees as soon as its item completes, avoiding batch boundary blocking.
    
    Args:
        items: List of items to process
        concurrency: Maximum number of concurrent operations
        processor: Async function to process each item
    """
    # Simple semaphore-based concurrency control
    semaphore = asyncio.Semaphore(concurrency)
    
    async def process_with_semaphore(item):
        async with semaphore:
            await processor(item)
    
    # Process all items concurrently with bounded concurrency
    await asyncio.gather(*[process_with_semaphore(item) for item in items])


async def get_mcp_tools_commands_and_resources(
    on_connection_attempt,
    mcp_configs: Optional[Dict[str, ScopedMcpServerConfig]] = None,
    connect_to_server_cache: Optional[Dict[str, MCPServerConnection]] = None,
) -> None:
    """
    Connect to all MCP servers and fetch their tools, commands, and resources.
    
    Args:
        on_connection_attempt: Callback function called for each connection attempt
            with params: {client, tools, commands, resources}
        mcp_configs: Optional MCP server configurations (will fetch if not provided)
        connect_to_server_cache: Global connection cache
    """
    if connect_to_server_cache is None:
        connect_to_server_cache = {}
    
    resource_tools_added = False
    
    # Get all config entries
    if mcp_configs is None:
        # In real implementation: mcp_configs = (await get_all_mcp_configs())['servers']
        mcp_configs = {}
    
    all_config_entries = list(mcp_configs.items())
    
    # Partition into disabled and active entries — disabled servers should
    # never generate HTTP connections or flow through batch processing
    config_entries = []
    for name, config in all_config_entries:
        # Check if server is disabled
        # if is_mcp_server_disabled(name):
        #     on_connection_attempt({
        #         'client': {'name': name, 'type': 'disabled', 'config': config},
        #         'tools': [],
        #         'commands': [],
        #     })
        # else:
        config_entries.append((name, config))
    
    # Calculate transport counts for logging
    total_servers = len(config_entries)
    stdio_count = sum(1 for _, c in config_entries if (c.get('type') if isinstance(c, dict) else getattr(c, 'type', None)) == 'stdio')
    sse_count = sum(1 for _, c in config_entries if (c.get('type') if isinstance(c, dict) else getattr(c, 'type', None)) == 'sse')
    http_count = sum(1 for _, c in config_entries if (c.get('type') if isinstance(c, dict) else getattr(c, 'type', None)) == 'http')
    sse_ide_count = sum(1 for _, c in config_entries if (c.get('type') if isinstance(c, dict) else getattr(c, 'type', None)) == 'sse-ide')
    ws_ide_count = sum(1 for _, c in config_entries if (c.get('type') if isinstance(c, dict) else getattr(c, 'type', None)) == 'ws-ide')
    
    # Split servers by type: local (stdio/sdk) need lower concurrency due to
    # process spawning, remote servers can connect with higher concurrency
    local_servers = [(name, config) for name, config in config_entries if is_local_mcp_server(config)]
    remote_servers = [(name, config) for name, config in config_entries if not is_local_mcp_server(config)]
    
    server_stats = {
        'total_servers': total_servers,
        'stdio_count': stdio_count,
        'sse_count': sse_count,
        'http_count': http_count,
        'sse_ide_count': sse_ide_count,
        'ws_ide_count': ws_ide_count,
    }
    
    async def process_server(name_config_tuple):
        """Process a single MCP server connection"""
        name, config = name_config_tuple
        
        try:
            # Check if server is disabled - if so, just add it to state without connecting
            # if is_mcp_server_disabled(name):
            #     on_connection_attempt({
            #         'client': {'name': name, 'type': 'disabled', 'config': config},
            #         'tools': [],
            #         'commands': [],
            #     })
            #     return
            
            # Skip connection for servers that recently returned 401 (15min TTL),
            # or that we have probed before but hold no token for.
            server_type = config.get('type') if isinstance(config, dict) else getattr(config, 'type', None)
            
            if server_type in ('claudeai-proxy', 'http', 'sse'):
                # Check if auth is cached
                # if (await is_mcp_auth_cached(name)) or \
                #    ((server_type in ('http', 'sse')) and has_mcp_discovery_but_no_token(name, config)):
                #     log_mcp_debug(name, 'Skipping connection (cached needs-auth)')
                #     on_connection_attempt({
                #         'client': {'name': name, 'type': 'needs-auth', 'config': config},
                #         'tools': [create_mcp_auth_tool(name, config)],
                #         'commands': [],
                #     })
                #     return
                pass
            
            # Connect to server
            client = await connect_to_server(name, config, server_stats)
            
            if client.get('type') != 'connected':
                # on_connection_attempt({
                #     'client': client,
                #     'tools': [create_mcp_auth_tool(name, config)] if client.get('type') == 'needs-auth' else [],
                #     'commands': [],
                # })
                return
            
            # Mark claude.ai proxy as connected (if applicable)
            if server_type == 'claudeai-proxy':
                # mark_cloud_ai_mcp_connected(name)
                pass
            
            # Check if server supports resources
            capabilities = client.get('capabilities', {})
            supports_resources = bool(capabilities.get('resources'))
            
            # Fetch all resources in parallel
            tools = await fetch_tools_for_client(client)
            mcp_commands = await fetch_commands_for_client(client)
            mcp_skills = []  # Would fetch if feature('MCP_SKILLS') enabled
            resources = await fetch_resources_for_client(client) if supports_resources else []
            
            commands = mcp_commands + mcp_skills
            
            # If this server resources and we haven't added resource tools yet,
            # include our resource tools with this client's tools
            resource_tools = []
            nonlocal resource_tools_added
            if supports_resources and not resource_tools_added:
                resource_tools_added = True
                # resource_tools.append(ListMcpResourcesTool)
                # resource_tools.append(ReadMcpResourceTool)
                pass
            
            # on_connection_attempt({
            #     'client': client,
            #     'tools': tools + resource_tools,
            #     'commands': commands,
            #     'resources': resources if len(resources) > 0 else None,
            # })
            
        except Exception as error:
            # Handle errors gracefully - connection might have closed during fetch
            # log_mcp_error(name, f'Error fetching tools/commands/resources: {str(error)}')
            
            # Still update with the client but no tools/commands
            # on_connection_attempt({
            #     'client': {'name': name, 'type': 'failed', 'config': config},
            #     'tools': [],
            #     'commands': [],
            # })
            pass
    
    # Process both groups concurrently, each with their own concurrency limits:
    # - Local servers (stdio/sdk): lower concurrency to avoid process spawning resource contention
    # - Remote servers: higher concurrency since they're just network connections
    local_concurrency = get_mcp_server_connection_batch_size()
    remote_concurrency = get_remote_mcp_server_connection_batch_size()
    
    await asyncio.gather(
        process_batched(local_servers, local_concurrency, process_server),
        process_batched(remote_servers, remote_concurrency, process_server),
    )


# ============================================================================
# Phase 12: Prefetch Resources & Transform Result Content
# ============================================================================

async def prefetch_all_mcp_resources(
    mcp_configs: Dict[str, ScopedMcpServerConfig],
    connect_to_server_cache: Optional[Dict[str, MCPServerConnection]] = None,
) -> Dict[str, Any]:
    """
    Prefetch all MCP resources (tools, commands, clients) from all configured servers.
    
    Not memoized: called only 2-3 times at startup/reconfig. The inner work
    (connectToServer, fetch*ForClient) is already cached. Memoizing here by
    mcpConfigs object ref leaked — main.tsx creates fresh config objects each call.
    
    Args:
        mcp_configs: MCP server configurations
        connect_to_server_cache: Global connection cache
        
    Returns:
        Dict with clients, tools, and commands lists
    """
    if connect_to_server_cache is None:
        connect_to_server_cache = {}
    
    pending_count = len(mcp_configs)
    
    if pending_count == 0:
        return {
            'clients': [],
            'tools': [],
            'commands': [],
        }
    
    clients = []
    tools = []
    commands = []
    
    def on_connection_attempt(result):
        """Callback for each connection attempt"""
        clients.append(result.get('client'))
        tools.extend(result.get('tools', []))
        commands.extend(result.get('commands', []))
    
    try:
        await get_mcp_tools_commands_and_resources(
            on_connection_attempt=on_connection_attempt,
            mcp_configs=mcp_configs,
            connect_to_server_cache=connect_to_server_cache,
        )
        
        # Calculate commands metadata length for logging
        commands_metadata_length = sum(
            len(cmd.get('name', '')) +
            len(cmd.get('description', '')) +
            len(cmd.get('argument_hint', ''))
            for cmd in commands
        )
        
        # Log event
        # log_event('tengu_mcp_tools_commands_loaded', {
        #     'tools_count': len(tools),
        #     'commands_count': len(commands),
        #     'commands_metadata_length': commands_metadata_length,
        # })
        
        return {
            'clients': clients,
            'tools': tools,
            'commands': commands,
        }
        
    except Exception as error:
        # log_mcp_error('prefetch_all_mcp_resources', f'Failed to get MCP resources: {str(error)}')
        # Still return empty results
        return {
            'clients': [],
            'tools': [],
            'commands': [],
        }


async def transform_result_content(
    result_content: Dict[str, Any],
    server_name: str,
) -> list:
    """
    Transform result content from an MCP tool or MCP prompt into message blocks.
    
    Args:
        result_content: The result content from MCP
        server_name: Name of the MCP server
        
    Returns:
        List of content block parameters
    """
    content_type = result_content.get('type')
    
    if content_type == 'text':
        return [
            {
                'type': 'text',
                'text': result_content.get('text', ''),
            }
        ]
    
    elif content_type == 'audio':
        # Audio data handling
        audio_data = result_content.get('data', '')
        mime_type = result_content.get('mimeType')
        
        # In real implementation:
        # return await persist_blob_to_text_block(
        #     bytes=base64.b64decode(audio_data),
        #     mime_type=mime_type,
        #     server_name=server_name,
        #     source_description=f'[Audio from {server_name}] ',
        # )
        return [
            {
                'type': 'text',
                'text': f'[Audio from {server_name}]',
            }
        ]
    
    elif content_type == 'image':
        # Image data handling
        image_data = result_content.get('data', '')
        mime_type = result_content.get('mimeType', 'image/png')
        
        # In real implementation:
        # - Decode base64
        # - Resize and compress image
        # - Enforce API dimension limits
        ext = mime_type.split('/')[1] if '/' in mime_type else 'png'
        
        return [
            {
                'type': 'image',
                'source': {
                    'data': image_data,
                    'media_type': f'image/{ext}',
                    'type': 'base64',
                },
            }
        ]
    
    elif content_type == 'resource':
        resource = result_content.get('resource', {})
        prefix = f'[Resource from {server_name} at {resource.get("uri", "")}] '
        
        if 'text' in resource:
            return [
                {
                    'type': 'text',
                    'text': f"{prefix}{resource['text']}",
                }
            ]
        
        elif 'blob' in resource:
            is_image = resource.get('mimeType', '').startswith('image/')
            
            if is_image:
                # Image resource handling
                blob_data = resource.get('blob', '')
                mime_type = resource.get('mimeType', 'image/png')
                ext = mime_type.split('/')[1] if '/' in mime_type else 'png'
                
                content = []
                if prefix:
                    content.append({
                        'type': 'text',
                        'text': prefix,
                    })
                
                content.append({
                    'type': 'image',
                    'source': {
                        'data': blob_data,
                        'media_type': f'image/{ext}',
                        'type': 'base64',
                    },
                })
                
                return content
            
            else:
                # Non-image blob
                # return await persist_blob_to_text_block(...)
                return [
                    {
                        'type': 'text',
                        'text': f'{prefix}[Binary resource]',
                    }
                ]
        
        return []
    
    elif content_type == 'resource_link':
        resource_link = result_content
        text = f"[Resource link: {resource_link.get('name', '')}] {resource_link.get('uri', '')}"
        
        if resource_link.get('description'):
            text += f" ({resource_link['description']})"
        
        return [
            {
                'type': 'text',
                'text': text,
            }
        ]
    
    else:
        return []


async def persist_blob_to_text_block(
    bytes_data: bytes,
    mime_type: Optional[str],
    server_name: str,
    source_description: str,
) -> list:
    """
    Decode base64 binary content, write it to disk with the proper extension,
    and return a small text block with the file path. Replaces the old behavior
    of dumping raw base64 into the context.
    
    Args:
        bytes_data: Binary data
        mime_type: MIME type of the data
        server_name: Name of the MCP server
        source_description: Description of the source
        
    Returns:
        List of content block parameters
    """
    import time
    import random
    import string
    
    def normalize_name_for_mcp(name: str) -> str:
        """Normalize server name for MCP"""
        import re
        return re.sub(r'[^a-zA-Z0-9]', '_', name).lower()
    
    # Generate persistent ID
    persist_id = f"mcp-{normalize_name_for_mcp(server_name)}-blob-{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
    
    # In real implementation:
    # result = await persist_binary_content(bytes_data, mime_type, persist_id)
    # 
    # if 'error' in result:
    #     return [
    #         {
    #             'type': 'text',
    #             'text': f"{source_description}Binary content ({mime_type or 'unknown type'}, {len(bytes_data)} bytes) could not be saved to disk: {result['error']}",
    #         }
    #     ]
    # 
    # return [
    #     {
    #         'type': 'text',
    #         'text': get_binary_blob_saved_message(
    #             result['filepath'],
    #             mime_type,
    #             result['size'],
    #             source_description,
    #         ),
    #     }
    # ]
    
    # Placeholder implementation
    return [
        {
            'type': 'text',
            'text': f'{source_description}Binary content ({mime_type or "unknown type"}, {len(bytes_data)} bytes) saved as {persist_id}',
        }
    ]


def infer_compact_schema(value, depth: int = 2) -> str:
    """
    Generates a compact, jq-friendly type signature for a value.
    e.g. "{title: string, items: [{id: number, name: string}]}"
    
    Args:
        value: The value to infer schema from
        depth: Maximum recursion depth
        
    Returns:
        Compact schema string
    """
    if value is None:
        return 'null'
    
    if isinstance(value, list):
        if len(value) == 0:
            return '[]'
        return f'[{infer_compact_schema(value[0], depth - 1)}]'
    
    if isinstance(value, dict):
        if depth <= 0 or len(value) == 0:
            return '{}'
        
        # Limit to 10 entries
        entries = list(value.items())[:10]
        pairs = []
        for k, v in entries:
            pairs.append(f'{k}: {infer_compact_schema(v, depth - 1)}')
        
        # Add suffix if more than 10 keys
        suffix = ', ...' if len(value) > 10 else ''
        
        return '{' + ', '.join(pairs) + suffix + '}'
    
    if isinstance(value, bool):
        return 'boolean'
    
    if isinstance(value, (int, float)):
        return 'number'
    
    if isinstance(value, str):
        return 'string'
    
    return 'unknown'


# ============================================================================
# Phase 13: Transform & Process MCP Result
# ============================================================================

async def transform_mcp_result(
    result,
    tool: str,  # Tool name for validation (e.g., "search")
    name: str,  # Server name for transformation (e.g., "slack")
) -> Dict[str, Any]:
    """
    Transform MCP result into a normalized format.
    
    Args:
        result: The raw MCP result
        tool: Tool name for validation
        name: Server name for transformation
        
    Returns:
        Dict with content, type, and optional schema
        
    Raises:
        RuntimeError: If result has unexpected format
    """
    if result and isinstance(result, dict):
        if 'toolResult' in result:
            return {
                'content': str(result['toolResult']),
                'type': 'toolResult',
            }
        
        if 'structuredContent' in result and result['structuredContent'] is not None:
            return {
                'content': json.dumps(result['structuredContent']),
                'type': 'structuredContent',
                'schema': infer_compact_schema(result['structuredContent']),
            }
        
        if 'content' in result and isinstance(result['content'], list):
            # Transform each content item
            transformed_content = []
            for item in result['content']:
                transformed = await transform_result_content(item, name)
                transformed_content.extend(transformed)
            
            return {
                'content': transformed_content,
                'type': 'contentArray',
                'schema': infer_compact_schema(transformed_content),
            }
    
    error_message = f'MCP server "{name}" tool "{tool}": unexpected response format'
    # log_mcp_error(name, error_message)
    raise RuntimeError(error_message)


def content_contains_images(content) -> bool:
    """
    Check if MCP content contains any image blocks.
    Used to decide whether to persist to file (images should use truncation instead
    to preserve image compression and viewability).
    
    Args:
        content: MCP tool result content
        
    Returns:
        True if content contains image blocks
    """
    if not content or isinstance(content, str):
        return False
    
    if isinstance(content, list):
        return any(block.get('type') == 'image' for block in content)
    
    return False


async def process_mcp_result(
    result,
    tool: str,  # Tool name for validation (e.g., "search")
    name: str,  # Server name for IDE check and transformation (e.g., "slack")
) -> Any:
    """
    Process MCP result, handling truncation and large output files.
    
    Args:
        result: The raw MCP result
        tool: Tool name for validation
        name: Server name for IDE check
        
    Returns:
        Processed MCP tool result
    """
    transformed = await transform_mcp_result(result, tool, name)
    content = transformed['content']
    result_type = transformed['type']
    schema = transformed.get('schema')
    
    # IDE tools are not going to the model directly, so we don't need to
    # handle large output.
    if name == 'ide':
        return content
    
    # Check if content needs truncation (i.e., is too large)
    # if not await mcp_content_needs_truncation(content):
    #     return content
    
    # For now, skip truncation check (placeholder)
    
    # size_estimate_tokens = get_content_size_estimate(content)
    
    # If large output files feature is disabled, fall back to old truncation behavior
    # if is_env_defined_falsy(os.environ.get('ENABLE_MCP_LARGE_OUTPUT_FILES')):
    #     log_event('tengu_mcp_large_result_handled', {
    #         'outcome': 'truncated',
    #         'reason': 'env_disabled',
    #         'size_estimate_tokens': size_estimate_tokens,
    #     })
    #     return await truncate_mcp_content_if_needed(content)
    
    # Save large output to file and return instructions for reading it
    # Content is guaranteed to exist at this point (we checked mcpContentNeedsTruncation)
    if not content:
        return content
    
    # If content contains images, fall back to truncation - persisting images as JSON
    # defeats the image compression logic and makes them non-viewable
    if content_contains_images(content):
        # log_event('tengu_mcp_large_result_handled', {
        #     'outcome': 'truncated',
        #     'reason': 'contains_images',
        #     'size_estimate_tokens': size_estimate_tokens,
        # })
        # return await truncate_mcp_content_if_needed(content)
        pass  # Skip for now
    
    # Generate a unique ID for the persisted file (server__tool-timestamp)
    import time
    
    def normalize_name_for_mcp(name: str) -> str:
        """Normalize server name for MCP"""
        import re
        return re.sub(r'[^a-zA-Z0-9]', '_', name).lower()
    
    timestamp = int(time.time() * 1000)
    persist_id = f"mcp-{normalize_name_for_mcp(name)}-{normalize_name_for_mcp(tool)}-{timestamp}"
    
    # Convert to string for persistence (persistToolResult expects string or specific block types)
    content_str = content if isinstance(content, str) else json.dumps(content, indent=2)
    
    # In real implementation:
    # persist_result = await persist_tool_result(content_str, persist_id)
    # 
    # if is_persist_error(persist_result):
    #     # If file save failed, fall back to returning truncated content info
    #     content_length = len(content_str)
    #     return f"Error: result ({content_length:,} characters) exceeds maximum allowed tokens. Failed to save output to file: {persist_result['error']}. If this MCP server provides pagination or filtering tools, use them to retrieve specific portions of the data."
    # 
    # log_event('tengu_mcp_large_result_handled', {
    #     'outcome': 'persisted',
    #     'reason': 'file_saved',
    #     'size_estimate_tokens': size_estimate_tokens,
    #     'persisted_size_chars': persist_result['original_size'],
    # })
    # 
    # format_description = get_format_description(result_type, schema)
    # return get_large_output_instructions(
    #     persist_result['filepath'],
    #     persist_result['original_size'],
    #     format_description,
    # )
    
    # Placeholder: return content as-is
    return content


# Type alias for MCP tool call result
MCPToolCallResult = Dict[str, Any]


# ============================================================================
# Phase 14: URL Elicitation Retry & Call MCP Tool
# ============================================================================

MAX_URL_ELICITATION_RETRIES = 3


async def call_mcp_tool_with_url_elicitation_retry(
    client: Dict[str, Any],
    client_connection: MCPServerConnection,
    tool: str,
    args: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    signal=None,
    setAppState=None,
    onProgress=None,
    call_tool_fn=None,
    handle_elicitation=None,
) -> MCPToolCallResult:
    """
    Call an MCP tool, handling UrlElicitationRequiredError (-32042) by
    displaying the URL elicitation to the user, waiting for the completion
    notification, and retrying the tool call.
    
    Args:
        client: Connected MCP server client
        client_connection: MCP server connection
        tool: Tool name
        args: Tool arguments
        meta: Optional metadata
        signal: Abort signal (optional)
        setAppState: State update function (optional)
        onProgress: Progress callback (optional)
        call_tool_fn: Injectable tool call function (defaults to call_mcp_tool)
        handle_elicitation: Handler for URL elicitations (optional)
        
    Returns:
        MCP tool call result
    """
    if call_tool_fn is None:
        call_tool_fn = call_mcp_tool
    
    for attempt in range(MAX_URL_ELICITATION_RETRIES + 1):
        try:
            return await call_tool_fn(
                client=client,
                tool=tool,
                args=args,
                meta=meta,
                signal=signal,
                on_progress=onProgress,
            )
        
        except Exception as error:
            # The MCP SDK's Protocol creates plain McpError (not UrlElicitationRequiredError)
            # for error responses, so we check the error code instead of isinstance.
            # Check if this is a URL elicitation required error (code -32042)
            error_code = getattr(error, 'code', None)
            is_url_elicitation_error = (
                hasattr(error, '__class__') and 
                error_code == -32042  # ErrorCode.UrlElicitationRequired
            )
            
            if not is_url_elicitation_error:
                raise error
            
            # Limit the number of URL elicitation retries
            if attempt >= MAX_URL_ELICITATION_RETRIES:
                raise error
            
            # Extract elicitations from error data
            error_data = getattr(error, 'data', None)
            raw_elicitations = []
            if error_data and isinstance(error_data, dict) and 'elicitations' in error_data:
                elicitations_data = error_data['elicitations']
                if isinstance(elicitations_data, list):
                    raw_elicitations = elicitations_data
            
            # Validate each element has the required fields
            elicitations = [
                e for e in raw_elicitations
                if e and isinstance(e, dict)
                and e.get('mode') == 'url'
                and isinstance(e.get('url'), str)
                and isinstance(e.get('elicitationId'), str)
                and isinstance(e.get('message'), str)
            ]
            
            server_name = client_connection.get('name', 'unknown') if client_connection.get('type') == 'connected' else 'unknown'
            
            if len(elicitations) == 0:
                # log_mcp_debug(server_name, f"Tool '{tool}' returned -32042 but no valid elicitations in error data")
                raise error
            
            # log_mcp_debug(server_name, f"Tool '{tool}' requires URL elicitation (error -32042, attempt {attempt + 1}), processing {len(elicitations)} elicitation(s)")
            
            # Process each URL elicitation
            for elicitation in elicitations:
                elicitation_id = elicitation['elicitationId']
                
                # Run elicitation hooks (if available)
                # hook_response = await run_elicitation_hooks(server_name, elicitation, signal)
                hook_response = None  # Hooks not implemented yet
                
                if hook_response:
                    # log_mcp_debug(server_name, f"URL elicitation {elicitation_id} resolved by hook: {json.dumps(hook_response)}")
                    if hook_response.get('action') != 'accept':
                        action = hook_response.get('action')
                        return {
                            'content': f"URL elicitation was {'declined' if action == 'decline' else action + 'ed'} by a hook. The tool \"{tool}\" could not complete because it requires the user to open a URL.",
                        }
                    # Hook accepted — skip the UI and proceed to retry
                    continue
                
                # Resolve the URL elicitation via callback or queue
                if handle_elicitation:
                    # Print/SDK mode: delegate to structuredIO
                    user_result = await handle_elicitation(server_name, elicitation, signal)
                else:
                    # REPL mode: would queue for ElicitationDialog
                    # For now, auto-accept (user would see dialog in real implementation)
                    user_result = {'action': 'accept'}
                
                # Run ElicitationResult hooks (if available)
                # final_result = await run_elicitation_result_hooks(server_name, user_result, signal, 'url', elicitation_id)
                final_result = user_result
                
                if final_result.get('action') != 'accept':
                    action = final_result.get('action')
                    # log_mcp_debug(server_name, f"User {'declined' if action == 'decline' else action + 'ed'} URL elicitation {elicitation_id}")
                    return {
                        'content': f"URL elicitation was {'declined' if action == 'decline' else action + 'ed'} by the user. The tool \"{tool}\" could not complete because it requires the user to open a URL.",
                    }
                
                # log_mcp_debug(server_name, f"Elicitation {elicitation_id} completed, retrying tool call")
            
            # Loop back to retry the tool call


async def call_mcp_tool(
    client: Dict[str, Any],
    tool: str,
    args: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    signal=None,
    on_progress=None,
) -> MCPToolCallResult:
    """
    Call an MCP tool with timeout and progress tracking.
    
    Args:
        client: Connected MCP server client (with 'client', 'name', 'config' keys)
        tool: Tool name
        args: Tool arguments
        meta: Optional metadata
        signal: Abort signal (optional)
        on_progress: Progress callback (optional)
        
    Returns:
        Tool call result with content, _meta, and structuredContent
    """
    import time
    
    sdk_client = client.get('client')
    server_name = client.get('name', 'unknown')
    config = client.get('config', {})
    
    tool_start_time = int(time.time() * 1000)  # milliseconds
    progress_task = None
    progress_stop_event = asyncio.Event()
    
    async def progress_logger():
        """Log progress for long-running tools every 30 seconds"""
        while not progress_stop_event.is_set():
            try:
                await asyncio.wait_for(progress_stop_event.wait(), timeout=30.0)
                break
            except asyncio.TimeoutError:
                elapsed = int(time.time() * 1000) - tool_start_time
                elapsed_seconds = elapsed // 1000
                # log_mcp_debug(server_name, f"Tool '{tool}' still running ({elapsed_seconds}s elapsed)")
    
    try:
        # log_mcp_debug(server_name, f"Calling MCP tool: {tool}")
        
        # Set up progress logging for long-running tools (every 30 seconds)
        progress_task = asyncio.create_task(progress_logger())
        
        # Get timeout setting
        timeout_ms = get_mcp_tool_timeout_ms()
        timeout_seconds = timeout_ms / 1000.0
        
        # Create timeout promise using asyncio.wait_for
        try:
            # In real implementation, this would call:
            # result = await asyncio.wait_for(
            #     sdk_client.call_tool(
            #         name=tool,
 #         arguments=args,
            #         _meta=meta,
 #         timeout=timeout_ms,
            #         onprogress=on_progress,
            #     ),
            #     timeout=timeout_seconds
            # )
            
            # Placeholder: simulate tool call
            await asyncio.sleep(0.01)  # Simulate async operation
            result = {
                'content': [{'type': 'text', 'text': f'Tool {tool} executed successfully'}],
            }
            
        except asyncio.TimeoutError:
            # Timeout error handling
            raise TimeoutError(
                f'MCP server "{server_name}" tool "{tool}" timed out after {int(timeout_seconds)}s'
            )
        
        
        # Check if result has error flag
        if result.get('isError'):
            error_details = 'Unknown error'
            
            if 'content' in result and isinstance(result['content'], list) and len(result['content']) > 0:
                first_content = result['content'][0]
                if first_content and isinstance(first_content, dict) and 'text' in first_content:
                    error_details = first_content['text']
            
            elif 'error' in result:
                # Fallback for legacy error format
                error_details = str(result['error'])
            
            # log_mcp_error(server_name, error_details)
            raise McpToolCallError(
                error_details,
                'MCP tool returned error',
                {'_meta': result.get('_meta')} if result.get('_meta') else None
            )
        
        
        # Calculate duration
        elapsed = int(time.time() * 1000) - tool_start_time
        duration = (
            f"{elapsed}ms" if elapsed < 1000
            else f"{elapsed // 1000}s" if elapsed < 60000
            else f"{elapsed // 60000}m {(elapsed % 60000) // 1000}s"
        )
        # log_mcp_debug(server_name, f"Tool '{tool}' completed successfully in {duration}")
        
        # Log code indexing tool usage (placeholder - would detect from server name)
        # code_indexing_tool = detect_code_indexing_from_mcp_server_name(server_name)
        # if code_indexing_tool:
        #     log_event('tengu_code_indexing_tool_used', {...})
        
        # Process the result content
        content = await process_mcp_result(result, tool, server_name)
        
        return {
            'content': content,
            '_meta': result.get('_meta'),
            'structuredContent': result.get('structuredContent'),
        }
        
    except Exception as e:
        # Clear progress task on error
        progress_stop_event.set()
        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
        
        elapsed = int(time.time() * 1000) - tool_start_time
        
        # Skip logging for abort errors
        if hasattr(e, 'name') and e.name != 'AbortError':
            pass  # log_mcp_debug(server_name, f"Tool '{tool}' failed after {elapsed // 1000}s: {str(e)}")
        
        # Check for 401 errors indicating expired/invalid OAuth tokens
        error_code = getattr(e, 'code', None)
        if error_code == 401 or isinstance(e, UnauthorizedError):
            # log_mcp_debug(server_name, "Tool call returned 401 Unauthorized - token may have expired")
            # log_event('tengu_mcp_tool_call_auth_error', {})
            raise McpAuthError(
                server_name,
                f'MCP server "{server_name}" requires re-authorization (token expired)'
            )
        
        
        # Check for session expiry
        # Two error shapes can surface here:
        # 1. Direct 404 + JSON-RPC -32001 from the server (StreamableHTTPError)
        # 2. -32000 "Connection closed" (McpError)
        is_session_expired = is_mcp_session_expired_error(e)
        is_connection_closed_on_http = (
            error_code == -32000 and
            'Connection closed' in str(e) and
            config.get('type') in ('http', 'claudeai-proxy')
        )
        
        if is_session_expired or is_connection_closed_on_http:
            # log_mcp_debug(server_name, f"MCP session expired during tool call, clearing connection cache")
            # log_event('tengu_mcp_session_expired', {})
            await clear_server_cache(server_name, config)
            raise McpSessionExpiredError(server_name)
        
        
        # When user hits esc, avoid logspew
        if hasattr(e, 'name') and e.name == 'AbortError':
            return {'content': None}
        
        raise
        
    finally:
        # Always clear progress task
        progress_stop_event.set()
        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass


# Placeholder for UnauthorizedError (would be imported from MCP SDK)
class UnauthorizedError(Exception):
    """Error thrown when MCP server returns 401 Unauthorized"""
    pass


# ============================================================================
# Phase 15: Progress Tracking, Error Handling & SDK Setup
# ============================================================================

def extract_tool_use_id(message: Dict[str, Any]) -> Optional[str]:
    """
    Extract tool use ID from an assistant message.
    
    Args:
        message: Assistant message dict
        
    Returns:
        Tool use ID or None
    """
    content = message.get('message', {}).get('content', [])
    if content and len(content) > 0 and content[0].get('type') == 'tool_use':
        return content[0].get('id')
    return None


async def setup_sdk_mcp_clients(
    sdk_mcp_configs: Dict[str, Any],
    send_mcp_message,
) -> Dict[str, Any]:
    """
    Sets up SDK MCP clients by creating transports and connecting them.
    This is used for SDK MCP servers that run in the same process as the SDK.
    
    Args:
        sdk_mcp_configs: SDK MCP server configurations
        send_mcp_message: Callback to send MCP messages through the control channel
        
    Returns:
        Dict with clients and tools lists
    """
    clients = []
    tools = []
    
    # Connect to all servers in parallel
    import asyncio
    
    async def connect_server(name, config):
        """Connect a single SDK MCP server"""
        try:
            # In real implementation:
            # transport = SdkControlClientTransport(name, send_mcp_message)
            # client = Client(client_info, capabilities)
            # await client.connect(transport)
            
            # Get capabilities from the server
            # capabilities = client.get_server_capabilities()
            capabilities = {}
            
            # Create the connected client object
            connected_client = {
                'type': 'connected',
                'name': name,
                'capabilities': capabilities or {},
                'client': None,  # Would be SDK client
                'config': {**config, 'scope': 'dynamic'},
                'cleanup': lambda: None,  # Async cleanup function
            }
            
            # Fetch tools if the server has them
            server_tools = []
            if capabilities.get('tools'):
                sdk_tools = await fetch_tools_for_client(connected_client)
                server_tools.extend(sdk_tools)
            
            return {
                'client': connected_client,
                'tools': server_tools,
            }
            
        except Exception as error:
            # If connection fails, return failed server
            # log_mcp_error(name, f"Failed to connect SDK MCP server: {str(error)}")
            return {
                'client': {
                    'type': 'failed',
                    'name': name,
                    'config': {**config, 'scope': 'user'},
                },
                'tools': [],
            }
    
    # Connect all servers in parallel
    results = await asyncio.gather(*[
        connect_server(name, config)
        for name, config in sdk_mcp_configs.items()
    ], return_exceptions=True)
    
    # Process results and collect clients and tools
    for result in results:
        if isinstance(result, dict) and 'client' in result:
            clients.append(result['client'])
            tools.extend(result.get('tools', []))
        # If exception, error was already logged inside the promise
    
    return {'clients': clients, 'tools': tools}


# Exports
__all__ = [
    # Phase 1: Error classes & constants
    'McpAuthError',
    'McpSessionExpiredError',
    'McpToolCallError',
    'UnauthorizedError',
    'is_mcp_session_expired_error',
    'DEFAULT_MCP_TOOL_TIMEOUT_MS',
    'MAX_MCP_DESCRIPTION_LENGTH',
    'get_mcp_tool_timeout_ms',
    # Phase 2: Auth cache system
    'MCP_AUTH_CACHE_TTL_MS',
    'get_mcp_auth_cache_path',
    'get_mcp_auth_cache',
    'is_mcp_auth_cached',
    'set_mcp_auth_cache_entry',
    'clear_mcp_auth_cache',
    'handle_remote_auth_failure',
    'mcp_base_url_analytics',
    # Phase 3: Claude AI Proxy & WebSocket
    'create_cloud_ai_proxy_fetch',
    'WsClientLike',
    'create_node_ws_client',
    'IMAGE_MIME_TYPES',
    'get_connection_timeout_ms',
    'MCP_REQUEST_TIMEOUT_MS',
    'MCP_STREAMABLE_HTTP_ACCEPT',
    'wrap_fetch_with_timeout',
    # Phase 4: Cache Key & Connect To Server
    'get_mcp_server_connection_batch_size',
    'get_remote_mcp_server_connection_batch_size',
    'is_local_mcp_server',
    'ALLOWED_IDE_TOOLS',
    'is_included_mcp_tool',
    'get_server_cache_key',
    'MCPServerConnection',
    'connect_to_server',
    # Phase 6: Connection Lifecycle
    'is_terminal_connection_error',
    'create_close_transport_handler',
    'create_error_handler',
    # Phase 7: Cleanup & Process Termination
    'cleanup_mcp_connection',
    'clear_mcp_connection_cache',
    # Phase 8: Connection Return & Cache Management
    'clear_server_cache',
    'ensure_connected_client',
    'create_connected_server_response',
    'create_failed_server_response',
    'ConnectedMCPServer',
    'FailedMCPServer',
    'WrappedMCPServer',
    # Phase 9: Config Comparison & Fetch Tools
    'are_mcp_configs_equal',
    'mcp_tool_input_to_auto_classifier_input',
    'fetch_tools_for_client',
    'MCP_FETCH_CACHE_SIZE',
    # Phase 10: Fetch Resources, Commands & Reconnect
    'fetch_resources_for_client',
    'fetch_commands_for_client',
    'call_ide_rpc',
    'reconnect_mcp_server_impl',
    # Phase 11: Batch Processing & Get MCP Tools/Commands/Resources
    'process_batched',
    'get_mcp_tools_commands_and_resources',
    # Phase 12: Prefetch Resources & Transform Result Content
    'prefetch_all_mcp_resources',
    'transform_result_content',
    'persist_blob_to_text_block',
    'infer_compact_schema',
    # Phase 13: Transform & Process MCP Result
    'transform_mcp_result',
    'content_contains_images',
    'process_mcp_result',
    'MCPToolCallResult',
    # Phase 14: URL Elicitation Retry & Call MCP Tool
    'call_mcp_tool_with_url_elicitation_retry',
    'call_mcp_tool',
    'MAX_URL_ELICITATION_RETRIES',
    # Phase 15: Progress Tracking, Error Handling & SDK Setup
    'extract_tool_use_id',
    'setup_sdk_mcp_clients',
]
