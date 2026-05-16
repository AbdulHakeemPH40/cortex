"""
services/mcp/useManageMCPConnections.py
Python conversion of services/mcp/useManageMCPConnections.ts (1142 lines)

Phase 1: Core utilities, constants, and helper functions
Phase 2: State management and update batching
Phase 3: Main connection management logic (React hooks → Python async)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Import from utils.py for stale client handling
try:
    from .utils import exclude_stale_plugin_clients
except ImportError:
    # Fallback if utils not available
    def exclude_stale_plugin_clients(mcp: Dict[str, Any], configs: Dict[str, Any]) -> Dict[str, Any]:
        return {**mcp, 'stale': []}

# Constants for reconnection with exponential backoff
MAX_RECONNECT_ATTEMPTS = 5
INITIAL_BACKOFF_MS = 1000
MAX_BACKOFF_MS = 30000

# Batched MCP state updates: queue individual server updates and flush them
# in a single setAppState call via setTimeout. Using a time-based window
# (instead of queueMicrotask) ensures updates are batched even when
# connection callbacks arrive at different times due to network I/O.
MCP_BATCH_FLUSH_MS = 0.016  # 16ms in seconds


@dataclass
class PendingUpdate:
    """Pending MCP server state update for batching."""
    name: str
    type: str
    config: Dict[str, Any]
    client: Optional[Any] = None
    tools: Optional[List[Dict[str, Any]]] = None
    commands: Optional[List[Dict[str, Any]]] = None
    resources: Optional[List[Dict[str, Any]]] = None
    capabilities: Optional[Dict[str, Any]] = None
    reconnect_attempt: int = 0
    max_reconnect_attempts: int = MAX_RECONNECT_ATTEMPTS


@dataclass
class PluginError:
    """Represents a plugin error with type, source, and optional plugin info."""
    type: str
    source: str
    plugin: Optional[str] = None


@dataclass
class MCPServerConnection:
    """Represents an MCP server connection state."""
    name: str
    type: str  # 'connected', 'failed', 'pending', 'disabled', 'needs-auth'
    config: Dict[str, Any]
    client: Optional[Any] = None  # MCP client instance
    tools: List[Dict[str, Any]] = field(default_factory=list)
    commands: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: Optional[Dict[str, Any]] = None
    reconnect_attempt: int = 0
    max_reconnect_attempts: int = MAX_RECONNECT_ATTEMPTS
    errors: List[PluginError] = field(default_factory=list)


def get_error_key(error: PluginError) -> str:
    """
    Create a unique key for a plugin error to enable deduplication.
    
    Args:
        error: PluginError instance
        
    Returns:
        Unique error key string
    """
    plugin = error.plugin or 'no-plugin'
    return f"{error.type}:{error.source}:{plugin}"


def add_errors_to_app_state(
    existing_errors: List[PluginError],
    new_errors: List[PluginError],
) -> List[PluginError]:
    """
    Add errors to existing error list, deduplicating to avoid showing the same error multiple times.
    
    Args:
        existing_errors: Current list of errors
        new_errors: New errors to add
        
    Returns:
        Updated error list with deduplication
    """
    if not new_errors:
        return existing_errors
    
    # Build set of existing error keys
    existing_keys = {get_error_key(e) for e in existing_errors}
    
    # Only add errors that don't already exist
    unique_new_errors = [
        error for error in new_errors
        if get_error_key(error) not in existing_keys
    ]
    
    if not unique_new_errors:
        return existing_errors
    
    return existing_errors + unique_new_errors


def get_transport_display_name(transport_type: str) -> str:
    """
    Get human-readable display name for transport type.
    
    Args:
        transport_type: Transport type string ('http', 'ws', 'ws-ide', 'sse', etc.)
        
    Returns:
        Display name string
    """
    transport_names = {
        'http': 'HTTP',
        'ws': 'WebSocket',
        'ws-ide': 'WebSocket',
    }
    return transport_names.get(transport_type, 'SSE')


async def reconnect_with_backoff(
    server_name: str,
    client_config: Dict[str, Any],
    reconnect_impl: Callable,
    update_callback: Callable,
    is_disabled_check: Callable[[str], bool],
) -> Optional[Dict[str, Any]]:
    """
    Attempt reconnection with exponential backoff.
    
    Args:
        server_name: Name of the MCP server
        client_config: Server configuration dict
        reconnect_impl: Async function to perform reconnection
        update_callback: Callback to update server state
        is_disabled_check: Function to check if server is disabled
        
    Returns:
        Reconnection result dict or None if gave up
    """
    config_type = client_config.get('type', 'stdio')
    transport_type = get_transport_display_name(config_type)
    
    for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
        # Check if server was disabled while we were waiting
        if is_disabled_check(server_name):
            logger.info(f"Server {server_name} disabled during reconnection, stopping retry")
            return None
        
        # Update state to pending
        update_callback({
            'name': server_name,
            'type': 'pending',
            'config': client_config,
            'reconnect_attempt': attempt,
            'max_reconnect_attempts': MAX_RECONNECT_ATTEMPTS,
        })
        
        reconnect_start_time = time.monotonic() * 1000  # milliseconds
        
        try:
            result = await reconnect_impl(server_name, client_config)
            elapsed = (time.monotonic() * 1000) - reconnect_start_time
            
            if result.get('client', {}).get('type') == 'connected':
                logger.info(
                    f"{transport_type} reconnection successful after {elapsed:.0f}ms "
                    f"(attempt {attempt})"
                )
                return result
            
            logger.debug(
                f"{transport_type} reconnection attempt {attempt} completed "
                f"with status: {result.get('client', {}).get('type')}"
            )
            
            # On final attempt, return the result
            if attempt == MAX_RECONNECT_ATTEMPTS:
                logger.warning(
                    f"Max reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) reached for {server_name}, giving up"
                )
                return result
                
        except Exception as error:
            elapsed = (time.monotonic() * 1000) - reconnect_start_time
            logger.error(
                f"{transport_type} reconnection attempt {attempt} failed after "
                f"{elapsed:.0f}ms: {error}"
            )
            
            # On final attempt, mark as failed
            if attempt == MAX_RECONNECT_ATTEMPTS:
                logger.warning(
                    f"Max reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) reached for {server_name}, giving up"
                )
                update_callback({
                    'name': server_name,
                    'type': 'failed',
                    'config': client_config,
                })
                return None
        
        # Schedule next retry with exponential backoff
        backoff_ms = min(
            INITIAL_BACKOFF_MS * (2 ** (attempt - 1)),
            MAX_BACKOFF_MS,
        )
        logger.debug(
            f"Scheduling reconnection attempt {attempt + 1} in {backoff_ms}ms"
        )
        
        # Wait for backoff period (can be interrupted)
        try:
            await asyncio.sleep(backoff_ms / 1000.0)
        except asyncio.CancelledError:
            logger.info(f"Reconnection cancelled for {server_name}")
            return None
    
    return None


def calculate_backoff_ms(attempt: int) -> int:
    """
    Calculate backoff time in milliseconds for a given attempt number.
    
    Args:
        attempt: Current attempt number (1-based)
        
    Returns:
        Backoff time in milliseconds
    """
    return min(
        INITIAL_BACKOFF_MS * (2 ** (attempt - 1)),
        MAX_BACKOFF_MS,
    )


def should_skip_reconnection(config_type: str) -> bool:
    """
    Check if reconnection should be skipped for this transport type.
    
    Skip stdio (local process) and sdk (internal) - they don't support reconnection.
    
    Args:
        config_type: Transport type string
        
    Returns:
        True if reconnection should be skipped
    """
    return config_type in ('stdio', 'sdk')


class MCPConnectionManager:
    """
    Manages MCP server connections, updates, and lifecycle.
    
    This is the Python equivalent of the useManageMCPConnections React hook,
    converted to an async class for non-React environments.
    """
    
    def __init__(
        self,
        get_mcp_configs: Callable,
        reconnect_impl: Callable,
        is_server_disabled: Callable[[str], bool],
        set_server_enabled: Callable[[str, bool], None],
        clear_server_cache: Callable,
        fetch_tools: Callable,
        fetch_commands: Callable,
        fetch_resources: Callable,
        state_update_callback: Callable[[Dict[str, Any]], None],
        log_debug: Callable[[str, str], None] = None,
        log_error: Callable[[str, str], None] = None,
        log_event: Callable[[str, Dict[str, Any]], None] = None,
    ):
        """
        Initialize the MCP connection manager.
        
        Args:
            get_mcp_configs: Async function to get MCP server configs
            reconnect_impl: Async function to reconnect a server
            is_server_disabled: Function to check if server is disabled
            set_server_enabled: Function to enable/disable a server
            clear_server_cache: Async function to clear server cache
            fetch_tools: Async function to fetch tools for a client
            fetch_commands: Async function to fetch commands for a client
            fetch_resources: Async function to fetch resources for a client
            state_update_callback: Function to apply state updates
            log_debug: Debug logging function
            log_error: Error logging function
            log_event: Analytics logging function
        """
        self._get_mcp_configs = get_mcp_configs
        self._reconnect_impl = reconnect_impl
        self._is_server_disabled = is_server_disabled
        self._set_server_enabled = set_server_enabled
        self._clear_server_cache = clear_server_cache
        self._fetch_tools = fetch_tools
        self._fetch_commands = fetch_commands
        self._fetch_resources = fetch_resources
        self._log_debug = log_debug or (lambda n, m: logger.debug(f"[{n}] {m}"))
        self._log_error = log_error or (lambda n, m: logger.error(f"[{n}] {m}"))
        self._log_event = log_event or (lambda e, d: None)
        
        # State batcher
        self._batcher = MCPStateBatcher(state_update_callback)
        
        # Track active reconnection tasks for cancellation
        self._reconnect_tasks: Dict[str, asyncio.Task] = {}
        
        # Current MCP state
        self._state: Dict[str, Any] = {
            'clients': [],
            'tools': [],
            'commands': [],
            'resources': {},
        }
        
        self._running = False
    
    async def start(
        self,
        dynamic_mcp_config: Optional[Dict[str, Any]] = None,
        is_strict_mcp_config: bool = False,
    ) -> None:
        """
        Start the MCP connection manager and initialize servers.
        
        Args:
            dynamic_mcp_config: Dynamic MCP server configs (e.g., from plugins)
            is_strict_mcp_config: If True, skip loading external configs
        """
        self._running = True
        
        # Initialize servers as pending
        await self._initialize_servers_as_pending(
            dynamic_mcp_config,
            is_strict_mcp_config,
        )
        
        # Load configs and connect
        await self._load_and_connect_mcp_configs(
            dynamic_mcp_config,
            is_strict_mcp_config,
        )
    
    async def stop(self) -> None:
        """Stop the MCP connection manager and cleanup."""
        self._running = False
        
        # Cancel all reconnect tasks
        for task in self._reconnect_tasks.values():
            if not task.done():
                task.cancel()
        self._reconnect_tasks.clear()
        
        # Flush pending updates
        self._batcher.flush_pending_updates()
        
        logger.info("MCP connection manager stopped")
    
    async def _initialize_servers_as_pending(
        self,
        dynamic_mcp_config: Optional[Dict[str, Any]],
        is_strict_mcp_config: bool,
    ) -> None:
        """
        Initialize all servers to pending state if they don't exist.
        
        Args:
            dynamic_mcp_config: Dynamic MCP server configs
            is_strict_mcp_config: If True, skip loading external configs
        """
        try:
            # Load MCP configs
            if is_strict_mcp_config:
                configs = {}
                mcp_errors = []
            else:
                result = await self._get_mcp_configs(dynamic_mcp_config)
                configs = result.get('servers', {})
                mcp_errors = result.get('errors', [])
            
            # Merge with dynamic configs
            if dynamic_mcp_config:
                configs = {**configs, **dynamic_mcp_config}
            
            # Add errors to state
            if mcp_errors:
                logger.warning(f"MCP config errors: {len(mcp_errors)}")
            
            # Find and clean up stale clients
            stale_result = exclude_stale_plugin_clients(self._state, configs)
            stale_clients = stale_result.get('stale', [])
            
            # Cleanup stale connections
            for stale_client in stale_clients:
                stale_name = stale_client.get('name', '')
                # Cancel any pending reconnect timer
                if stale_name in self._reconnect_tasks:
                    task = self._reconnect_tasks[stale_name]
                    if not task.done():
                        task.cancel()
                    del self._reconnect_tasks[stale_name]
                
                # Clear cache for connected stale servers
                if stale_client.get('type') == 'connected' and stale_client.get('client'):
                    try:
                        # Unset onclose to prevent reconnection race
                        if hasattr(stale_client['client'], 'onclose'):
                            stale_client['client'].onclose = None
                        # Clear server cache
                        asyncio.create_task(
                            self._clear_server_cache(stale_name, stale_client.get('config', {}))
                        )
                    except Exception:
                        pass
            
            # Update state without stale clients
            if stale_clients:
                self._state['clients'] = [
                    c for c in self._state['clients']
                    if c.get('name') not in {s.get('name') for s in stale_clients}
                ]
                self._log_debug(
                    'MCPManager',
                    f'Removed {len(stale_clients)} stale MCP clients',
                )
            
            # Initialize new servers as pending
            existing_names = {c['name'] for c in self._state['clients']}
            new_clients = []
            
            for name, config in configs.items():
                if name not in existing_names:
                    is_disabled = self._is_server_disabled(name)
                    new_clients.append({
                        'name': name,
                        'type': 'disabled' if is_disabled else 'pending',
                        'config': config,
                    })
            
            if new_clients:
                self._state['clients'].extend(new_clients)
                self._log_debug(
                    'MCPManager',
                    f'Initialized {len(new_clients)} servers as pending',
                )
                
        except Exception as error:
            self._log_error(
                'MCPManager',
                f'Failed to initialize servers: {error}',
            )
    
    async def _load_and_connect_mcp_configs(
        self,
        dynamic_mcp_config: Optional[Dict[str, Any]],
        is_strict_mcp_config: bool,
    ) -> None:
        """
        Load MCP configs and connect to servers.
        
        Two-phase loading:
        1. Claude Code configs (fast)
        2. Claude.ai configs (may be slow)
        
        Args:
            dynamic_mcp_config: Dynamic MCP server configs
            is_strict_mcp_config: If True, skip loading external configs
        """
        try:
            # Phase 1: Load Claude Code configs
            if is_strict_mcp_config:
                claude_code_configs = {}
                mcp_errors = []
            else:
                result = await self._get_mcp_configs(dynamic_mcp_config)
                claude_code_configs = result.get('servers', {})
                mcp_errors = result.get('errors', [])
            
            if not self._running:
                return
            
            # Merge configs
            configs = {**claude_code_configs, **(dynamic_mcp_config or {})}
            
            # Filter out disabled servers
            enabled_configs = {
                name: config
                for name, config in configs.items()
                if not self._is_server_disabled(name)
            }
            
            # Start connecting to servers
            await self._connect_to_servers(enabled_configs)
            
            # Phase 2: Claude.ai configs (if not strict)
            # TODO: Implement claude.ai config loading
            
            # Log server counts
            self._log_server_counts(configs)
            
        except Exception as error:
            self._log_error(
                'MCPManager',
                f'Failed to load and connect MCP configs: {error}',
            )
    
    async def _connect_to_servers(
        self,
        enabled_configs: Dict[str, Dict[str, Any]],
    ) -> None:
        """
        Connect to multiple MCP servers concurrently.
        
        Args:
            enabled_configs: Dict of server name -> config for enabled servers
        """
        if not enabled_configs:
            return
        
        self._log_debug(
            'MCPManager',
            f'Connecting to {len(enabled_configs)} MCP servers',
        )
        
        # TODO: Implement actual connection logic
        # This would call getMcpToolsCommandsAndResources from client.ts
        # For now, mark servers as pending
        for name, config in enabled_configs.items():
            self._batcher.update_server(PendingUpdate(
                name=name,
                type='pending',
                config=config,
            ))
    
    async def reconnect_server(self, server_name: str) -> Optional[Dict[str, Any]]:
        """
        Reconnect a specific MCP server.
        
        Args:
            server_name: Name of the server to reconnect
            
        Returns:
            Reconnection result dict or None
        """
        # Find the client
        client = next(
            (c for c in self._state['clients'] if c.get('name') == server_name),
            None,
        )
        
        if not client:
            raise ValueError(f"MCP server {server_name} not found")
        
        # Cancel any pending automatic reconnection
        if server_name in self._reconnect_tasks:
            task = self._reconnect_tasks[server_name]
            if not task.done():
                task.cancel()
            del self._reconnect_tasks[server_name]
        
        # Reconnect
        result = await self._reconnect_impl(server_name, client.get('config', {}))
        
        # Update state
        if result:
            self._on_connection_attempt(result)
        
        return result
    
    async def toggle_server(self, server_name: str) -> None:
        """
        Toggle a server's enabled/disabled state.
        
        Args:
            server_name: Name of the server to toggle
        """
        # Find the client
        client = next(
            (c for c in self._state['clients'] if c.get('name') == server_name),
            None,
        )
        
        if not client:
            raise ValueError(f"MCP server {server_name} not found")
        
        is_currently_disabled = client.get('type') == 'disabled'
        
        if not is_currently_disabled:
            # Disabling: cancel reconnect, persist state, disconnect
            if server_name in self._reconnect_tasks:
                task = self._reconnect_tasks[server_name]
                if not task.done():
                    task.cancel()
                del self._reconnect_tasks[server_name]
            
            # Persist disabled state
            self._set_server_enabled(server_name, False)
            
            # Disconnect if connected
            if client.get('type') == 'connected':
                await self._clear_server_cache(
                    server_name,
                    client.get('config', {}),
                )
            
            # Update to disabled state
            self._batcher.update_server(PendingUpdate(
                name=server_name,
                type='disabled',
                config=client.get('config', {}),
            ))
            
        else:
            # Enabling: persist state, mark as pending, reconnect
            self._set_server_enabled(server_name, True)
            
            self._batcher.update_server(PendingUpdate(
                name=server_name,
                type='pending',
                config=client.get('config', {}),
            ))
            
            # Reconnect
            result = await self._reconnect_impl(
                server_name,
                client.get('config', {}),
            )
            
            if result:
                self._on_connection_attempt(result)
    
    def _on_connection_attempt(self, result: Dict[str, Any]) -> None:
        """
        Handle connection attempt result.
        
        Args:
            result: Connection result dict with 'client', 'tools', 'commands', 'resources'
        """
        client = result.get('client', {})
        tools = result.get('tools', [])
        commands = result.get('commands', [])
        resources = result.get('resources', [])
        
        # Update server state
        self._batcher.update_server(PendingUpdate(
            name=client.get('name', ''),
            type=client.get('type', 'pending'),
            config=client.get('config', {}),
            client=client.get('client'),
            tools=tools,
            commands=commands,
            resources=resources,
            capabilities=client.get('capabilities'),
        ))
        
        # Handle side effects based on client state
        client_type = client.get('type')
        
        if client_type == 'connected':
            self._on_server_connected(client, tools, commands, resources)
        elif client_type in ('failed', 'pending', 'disabled', 'needs-auth'):
            # No special handling needed
            pass
    
    def _on_server_connected(
        self,
        client: Dict[str, Any],
        tools: List[Dict[str, Any]],
        commands: List[Dict[str, Any]],
        resources: List[Dict[str, Any]],
    ) -> None:
        """
        Handle server connected event.
        
        Args:
            client: Client connection dict
            tools: Available tools
            commands: Available commands
            resources: Available resources
        """
        server_name = client.get('name', '')
        config = client.get('config', {})
        config_type = config.get('type', 'stdio')
        mcp_client = client.get('client')
        capabilities = client.get('capabilities', {})
        
        self._log_debug(
            server_name,
            f'Server connected with {len(tools)} tools, {len(commands)} commands, {len(resources)} resources',
        )
        
        # Register elicitation handler if available
        if mcp_client and hasattr(mcp_client, 'setElicitationHandler'):
            # TODO: Import and call registerElicitationHandler
            pass
        
        # Setup onclose handler for automatic reconnection
        if mcp_client:
            self._setup_onclose_handler(client)
        
        # Setup notification handlers for tools/prompts/resources list_changed
        if capabilities:
            self._setup_notification_handlers(client)
    
    def _setup_onclose_handler(self, client: Dict[str, Any]) -> None:
        """
        Setup onclose handler for automatic reconnection.
        
        Args:
            client: Client connection dict
        """
        server_name = client.get('name', '')
        config = client.get('config', {})
        config_type = config.get('type', 'stdio')
        mcp_client = client.get('client')
        
        if not mcp_client:
            return
        
        # Define onclose callback
        async def on_close():
            # Clear server cache
            try:
                await self._clear_server_cache(server_name, config)
            except Exception as e:
                self._log_debug(
                    server_name,
                    f'Failed to invalidate server cache: {e}',
                )
            
            # Check if server was disabled
            if self._is_server_disabled(server_name):
                self._log_debug(
                    server_name,
                    'Server is disabled, skipping automatic reconnection',
                )
                return
            
            # Handle automatic reconnection for remote transports
            # Skip stdio (local process) and sdk (internal)
            if should_skip_reconnection(config_type):
                self._batcher.update_server(PendingUpdate(
                    name=server_name,
                    type='failed',
                    config=config,
                ))
                return
            
            transport_type = get_transport_display_name(config_type)
            self._log_debug(
                server_name,
                f'{transport_type} transport closed/disconnected, attempting automatic reconnection',
            )
            
            # Cancel any existing reconnection attempt
            if server_name in self._reconnect_tasks:
                existing_task = self._reconnect_tasks[server_name]
                if not existing_task.done():
                    existing_task.cancel()
            
            # Create reconnection task
            async def do_reconnect():
                result = await reconnect_with_backoff(
                    server_name=server_name,
                    client_config=config,
                    reconnect_impl=self._reconnect_impl,
                    update_callback=lambda u: self._batcher.update_server(PendingUpdate(
                        name=u.get('name', server_name),
                        type=u.get('type', 'pending'),
                        config=u.get('config', config),
                        reconnect_attempt=u.get('reconnect_attempt', 0),
                        max_reconnect_attempts=u.get('max_reconnect_attempts', MAX_RECONNECT_ATTEMPTS),
                    )),
                    is_disabled_check=self._is_server_disabled,
                )
                if result:
                    self._on_connection_attempt(result)
                else:
                    # Final attempt failed
                    self._batcher.update_server(PendingUpdate(
                        name=server_name,
                        type='failed',
                        config=config,
                    ))
            
            self._reconnect_tasks[server_name] = asyncio.create_task(do_reconnect())
        
        # Set onclose handler if client supports it
        if hasattr(mcp_client, 'onclose'):
            mcp_client.onclose = on_close
        elif hasattr(mcp_client, 'set_on_close'):
            mcp_client.set_on_close(on_close)
    
    def _setup_notification_handlers(self, client: Dict[str, Any]) -> None:
        """
        Setup notification handlers for tools/prompts/resources list_changed.
        
        Args:
            client: Client connection dict
        """
        server_name = client.get('name', '')
        mcp_client = client.get('client')
        capabilities = client.get('capabilities', {})
        
        if not mcp_client:
            return
        
        # Tools list changed handler
        if capabilities.get('tools', {}).get('listChanged'):
            async def on_tools_list_changed():
                self._log_debug(
                    server_name,
                    'Received tools/list_changed notification, refreshing tools',
                )
                try:
                    new_tools = await self._fetch_tools(client)
                    self._log_event('tengu_mcp_list_changed', {
                        'type': 'tools',
                        'newCount': len(new_tools),
                    })
                    self._batcher.update_server(PendingUpdate(
                        name=server_name,
                        type='connected',
                        config=client.get('config', {}),
                        tools=new_tools,
                    ))
                except Exception as error:
                    self._log_error(
                        server_name,
                        f'Failed to refresh tools after list_changed: {error}',
                    )
            
            if hasattr(mcp_client, 'setNotificationHandler'):
                mcp_client.setNotificationHandler(
                    'notifications/tools/list_changed',
                    on_tools_list_changed,
                )
        
        # Prompts list changed handler
        if capabilities.get('prompts', {}).get('listChanged'):
            async def on_prompts_list_changed():
                self._log_debug(
                    server_name,
                    'Received prompts/list_changed notification, refreshing prompts',
                )
                self._log_event('tengu_mcp_list_changed', {'type': 'prompts'})
                try:
                    new_commands = await self._fetch_commands(client)
                    self._batcher.update_server(PendingUpdate(
                        name=server_name,
                        type='connected',
                        config=client.get('config', {}),
                        commands=new_commands,
                    ))
                except Exception as error:
                    self._log_error(
                        server_name,
                        f'Failed to refresh prompts after list_changed: {error}',
                    )
            
            if hasattr(mcp_client, 'setNotificationHandler'):
                mcp_client.setNotificationHandler(
                    'notifications/prompts/list_changed',
                    on_prompts_list_changed,
                )
        
        # Resources list changed handler
        if capabilities.get('resources', {}).get('listChanged'):
            async def on_resources_list_changed():
                self._log_debug(
                    server_name,
                    'Received resources/list_changed notification, refreshing resources',
                )
                self._log_event('tengu_mcp_list_changed', {'type': 'resources'})
                try:
                    new_resources = await self._fetch_resources(client)
                    self._batcher.update_server(PendingUpdate(
                        name=server_name,
                        type='connected',
                        config=client.get('config', {}),
                        resources=new_resources,
                    ))
                except Exception as error:
                    self._log_error(
                        server_name,
                        f'Failed to refresh resources after list_changed: {error}',
                    )
            
            if hasattr(mcp_client, 'setNotificationHandler'):
                mcp_client.setNotificationHandler(
                    'notifications/resources/list_changed',
                    on_resources_list_changed,
                )
    
    def _log_server_counts(self, configs: Dict[str, Dict[str, Any]]) -> None:
        """
        Log server counts by scope for analytics.
        
        Args:
            configs: All MCP server configs
        """
        counts = {
            'enterprise': 0,
            'global': 0,
            'project': 0,
            'user': 0,
            'plugin': 0,
            'cloud': 0,
        }
        
        for name, config in configs.items():
            scope = config.get('scope', 'user')
            if scope == 'enterprise':
                counts['enterprise'] += 1
            elif scope == 'user':
                counts['global'] += 1
            elif scope == 'project':
                counts['project'] += 1
            elif scope == 'local':
                counts['user'] += 1
            elif scope == 'dynamic':
                counts['plugin'] += 1
            elif scope == 'cloud':
                counts['cloud'] += 1
        
        self._log_event('tengu_mcp_servers', counts)
    
    @property
    def state(self) -> Dict[str, Any]:
        """Get current MCP state."""
        return self._state.copy()
    
    @property
    def batcher(self) -> MCPStateBatcher:
        """Get the state batcher."""
        return self._batcher
    
    def get_client(self, server_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a client by server name.
        
        Args:
            server_name: Name of the server
            
        Returns:
            Client dict or None if not found
        """
        return next(
            (c for c in self._state['clients'] if c.get('name') == server_name),
            None,
        )
    
    def get_all_clients(self) -> List[Dict[str, Any]]:
        """Get all clients."""
        return self._state.get('clients', []).copy()
    
    def get_tools_for_server(self, server_name: str) -> List[Dict[str, Any]]:
        """Get tools for a specific server."""
        prefix = f"mcp__{server_name}__"
        return [
            t for t in self._state.get('tools', [])
            if t.get('name', '').startswith(prefix)
        ]
    
    def get_commands_for_server(self, server_name: str) -> List[Dict[str, Any]]:
        """Get commands for a specific server."""
        from .utils import command_belongs_to_server
        return [
            c for c in self._state.get('commands', [])
            if command_belongs_to_server(c, server_name)
        ]
    
    def get_resources_for_server(self, server_name: str) -> List[Dict[str, Any]]:
        """Get resources for a specific server."""
        return self._state.get('resources', {}).get(server_name, [])


class MCPStateBatcher:
    """
    Manages batched MCP state updates.
    
    Queues individual server updates and flushes them in a single
    setAppState call via a time-based window. This coalesces updates
    arriving within MCP_BATCH_FLUSH_MS due to network I/O timing.
    """
    
    def __init__(self, state_update_callback: Callable[[Dict[str, Any]], None]):
        """
        Initialize the state batcher.
        
        Args:
            state_update_callback: Function to apply batched state updates
        """
        self._pending_updates: List[PendingUpdate] = []
        self._flush_timer: Optional[asyncio.Task] = None
        self._state_update_callback = state_update_callback
    
    def update_server(self, update: PendingUpdate) -> None:
        """
        Queue a server state update for batched flushing.
        
        Args:
            update: PendingUpdate with server state changes
        """
        self._pending_updates.append(update)
        
        # Start flush timer if not already running
        if self._flush_timer is None or self._flush_timer.done():
            self._flush_timer = asyncio.create_task(
                self._schedule_flush()
            )
    
    async def _schedule_flush(self) -> None:
        """Wait for batch window then flush all pending updates."""
        await asyncio.sleep(MCP_BATCH_FLUSH_MS)
        self.flush_pending_updates()
    
    def flush_pending_updates(self) -> None:
        """
        Flush all pending updates in a single state update call.
        
        Processes all queued updates and applies them atomically to prevent
        partial state transitions.
        """
        if not self._pending_updates:
            return
        
        updates = self._pending_updates.copy()
        self._pending_updates.clear()
        
        # Apply all updates
        for update in updates:
            self._apply_single_update(update)
        
        logger.debug(f"Flushed {len(updates)} MCP state updates")
    
    def _apply_single_update(self, update: PendingUpdate) -> None:
        """
        Apply a single server update to the state.
        
        Args:
            update: PendingUpdate to apply
        """
        # For disabled/failed clients, clear tools/commands/resources
        if update.type in ('disabled', 'failed'):
            tools = update.tools or []
            commands = update.commands or []
            resources = update.resources or []
        else:
            tools = update.tools
            commands = update.commands
            resources = update.resources
        
        # Call state update callback
        self._state_update_callback({
            'name': update.name,
            'type': update.type,
            'config': update.config,
            'client': update.client,
            'tools': tools,
            'commands': commands,
            'resources': resources,
            'capabilities': update.capabilities,
            'reconnect_attempt': update.reconnect_attempt,
            'max_reconnect_attempts': update.max_reconnect_attempts,
        })
    
    def cancel_pending(self) -> None:
        """Cancel any pending flush timer and clear updates."""
        if self._flush_timer and not self._flush_timer.done():
            self._flush_timer.cancel()
        self._pending_updates.clear()
    
    @property
    def has_pending(self) -> bool:
        """Check if there are pending updates."""
        return len(self._pending_updates) > 0


def process_server_update(
    current_state: Dict[str, Any],
    update: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Process a single server update and return the new state.
    
    This replaces existing clients/tools/commands/resources for the server
    while preserving other servers' state.
    
    Args:
        current_state: Current MCP state dict with 'clients', 'tools', 'commands', 'resources'
        update: Update dict with server changes
        
    Returns:
        Updated state dict
    """
    server_name = update.get('name', '')
    if not server_name:
        logger.warning("Server update missing 'name' field")
        return current_state
    
    # Get MCP prefix for this server
    prefix = f"mcp__{server_name}__"
    
    # Update or add client
    clients = current_state.get('clients', [])
    existing_index = next(
        (i for i, c in enumerate(clients) if c.get('name') == server_name),
        -1
    )
    
    client_data = {
        'name': update.get('name'),
        'type': update.get('type'),
        'config': update.get('config', {}),
        'client': update.get('client'),
        'capabilities': update.get('capabilities'),
        'reconnect_attempt': update.get('reconnect_attempt', 0),
        'max_reconnect_attempts': update.get('max_reconnect_attempts', MAX_RECONNECT_ATTEMPTS),
    }
    
    if existing_index == -1:
        updated_clients = clients + [client_data]
    else:
        updated_clients = [
            client_data if i == existing_index else c
            for i, c in enumerate(clients)
        ]
    
    # Update tools: remove old tools for this server, add new ones
    tools = current_state.get('tools', [])
    if update.get('tools') is not None:
        new_tools = update['tools']
        updated_tools = [
            t for t in tools
            if not t.get('name', '').startswith(prefix)
        ] + new_tools
    else:
        updated_tools = tools
    
    # Update commands: remove old commands for this server, add new ones
    commands = current_state.get('commands', [])
    if update.get('commands') is not None:
        new_commands = update['commands']
        # Filter out commands belonging to this server
        def command_belongs_to_server(cmd: Dict[str, Any]) -> bool:
            cmd_name = cmd.get('name', '')
            if not cmd_name:
                return False
            return (cmd_name.startswith(f"mcp__{server_name}__") or
                    cmd_name.startswith(f"{server_name}:"))
        
        updated_commands = [
            c for c in commands
            if not command_belongs_to_server(c)
        ] + new_commands
    else:
        updated_commands = commands
    
    # Update resources: replace resources for this server
    resources = current_state.get('resources', {})
    if update.get('resources') is not None:
        new_resources = update['resources']
        updated_resources = {**resources}
        if len(new_resources) > 0:
            updated_resources[server_name] = new_resources
        else:
            updated_resources.pop(server_name, None)
    else:
        updated_resources = resources
    
    return {
        'clients': updated_clients,
        'tools': updated_tools,
        'commands': updated_commands,
        'resources': updated_resources,
    }


__all__ = [
    'PluginError',
    'MCPServerConnection',
    'PendingUpdate',
    'MCPStateBatcher',
    'MCPConnectionManager',
    'get_error_key',
    'add_errors_to_app_state',
    'get_transport_display_name',
    'reconnect_with_backoff',
    'calculate_backoff_ms',
    'should_skip_reconnection',
    'process_server_update',
    # Constants
    'MAX_RECONNECT_ATTEMPTS',
    'INITIAL_BACKOFF_MS',
    'MAX_BACKOFF_MS',
    'MCP_BATCH_FLUSH_MS',
]
