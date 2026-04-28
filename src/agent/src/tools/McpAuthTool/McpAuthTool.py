"""
McpAuthTool - Authenticate MCP servers via OAuth.

Creates pseudo-tools for MCP servers that require authentication, allowing
the AI agent to initiate OAuth flows on behalf of the user.
"""

from typing import Any, Dict, Optional, TypedDict

# Defensive imports
try:
    from ...services.mcp.auth import performMCPOAuthFlow
except ImportError:
    async def performMCPOAuthFlow(*args, **kwargs):
        return None

try:
    from ...services.mcp.client import clearMcpAuthCache, reconnectMcpServerImpl
except ImportError:
    def clearMcpAuthCache():
        pass
    
    async def reconnectMcpServerImpl(server_name, config):
        return type('Result', (), {
            'client': None,
            'tools': [],
            'commands': [],
            'resources': {},
        })()

try:
    from ...services.mcp.mcpStringUtils import buildMcpToolName, getMcpPrefix
except ImportError:
    def buildMcpToolName(server_name, tool_name):
        return f'mcp__{server_name}__{tool_name}'
    
    def getMcpPrefix(server_name):
        return f'mcp__{server_name}__'

try:
    from ...Tool import Tool
except ImportError:
    class Tool:
        pass

try:
    from ...utils.errors import errorMessage
except ImportError:
    def errorMessage(error):
        return str(error)

try:
    from ...utils.log import logMCPDebug, logMCPError
except ImportError:
    def logMCPDebug(server_name, message):
        print(f'MCP Debug [{server_name}]: {message}')
    
    def logMCPError(server_name, error_message):
        print(f'MCP Error [{server_name}]: {error_message}')


class McpAuthOutput(TypedDict, total=False):
    """Output schema for McpAuthTool."""
    status: str  # 'auth_url', 'unsupported', or 'error'
    message: str
    authUrl: Optional[str]


def getConfigUrl(config: Dict[str, Any]) -> Optional[str]:
    """Extract URL from MCP server config."""
    if 'url' in config:
        return config['url']
    return None


def createMcpAuthTool(server_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates a pseudo-tool for an MCP server that is installed but not
    authenticated. Surfaced in place of the server's real tools so the model
    knows the server exists and can start the OAuth flow on the user's behalf.
    
    When called, starts performMCPOAuthFlow with skipBrowserOpen and returns
    the authorization URL. The OAuth callback completes in the background;
    once it fires, reconnectMcpServerImpl runs and the server's real tools
    are swapped into appState.mcp.tools via the existing prefix-based
    replacement (useManageMCPConnections.updateServer wipes anything matching
    mcp__<server>__*, so this pseudo-tool is removed automatically).
    """
    url = getConfigUrl(config)
    transport = config.get('type') or 'stdio'
    location = f'{transport} at {url}' if url else transport
    
    description = (
        f'The `{server_name}` MCP server ({location}) is installed but requires authentication. '
        f'Call this tool to start the OAuth flow — you\'ll receive an authorization URL to share with the user. '
        f'Once the user completes authorization in their browser, the server\'s real tools will become available automatically.'
    )
    
    async def checkPermissions(input_data, context):
        return {'behavior': 'allow', 'updatedInput': input_data}
    
    async def call(input_data, context):
        # cortex.ai connectors use a separate auth flow (handleCortexAIAuth in
        # MCPRemoteServerMenu) that we don't invoke programmatically here —
        # just point the user at /mcp.
        if config.get('type') == 'cortexai-proxy':
            return {
                'data': {
                    'status': 'unsupported',
                    'message': f'This is a cortex.ai MCP connector. Ask the user to run /mcp and select "{server_name}" to authenticate.',
                },
            }
        
        # performMCPOAuthFlow only accepts sse/http. needs-auth state is only
        # set on HTTP 401 (UnauthorizedError) so other transports shouldn't
        # reach here, but be defensive.
        if config.get('type') not in ('sse', 'http'):
            return {
                'data': {
                    'status': 'unsupported',
                    'message': f'Server "{server_name}" uses {transport} transport which does not support OAuth from this tool. Ask the user to run /mcp and authenticate manually.',
                },
            }
        
        sse_or_http_config = config
        
        # Mirror cli/print.py mcp_authenticate: start the flow, capture the
        # URL via onAuthorizationUrl, return it immediately. The flow's
        # Promise resolves later when the browser callback fires.
        import asyncio
        
        auth_url_event = asyncio.Event()
        auth_url_value = [None]  # Use list to allow mutation in closure
        
        def resolve_auth_url(url):
            auth_url_value[0] = url
            auth_url_event.set()
        
        import concurrent.futures
        
        # Start OAuth flow in background
        loop = asyncio.get_running_loop()
        
        async def run_oauth():
            try:
                await performMCPOAuthFlow(
                    server_name,
                    sse_or_http_config,
                    resolve_auth_url,
                    None,  # abort_signal
                    {'skipBrowserOpen': True},
                )
            except Exception as err:
                logMCPError(
                    server_name,
                    f'OAuth flow failed after tool-triggered start: {errorMessage(err)}',
                )
        
        oauth_task = asyncio.create_task(run_oauth())
        
        # Background continuation: once OAuth completes, reconnect and swap
        # the real tools into appState. Prefix-based replacement removes this
        # pseudo-tool since it shares the mcp__<server>__ prefix.
        async def on_oauth_complete():
            try:
                await oauth_task
                clearMcpAuthCache()
                result = await reconnectMcpServerImpl(server_name, config)
                prefix = getMcpPrefix(server_name)
                
                set_app_state = context.setAppState
                
                def update_state(prev):
                    mcp = prev.get('mcp', {})
                    clients = mcp.get('clients', [])
                    tools = mcp.get('tools', [])
                    commands = mcp.get('commands', [])
                    
                    updated_clients = [
                        result.client if c.get('name') == server_name else c
                        for c in clients
                    ]
                    
                    updated_tools = [
                        t for t in tools if not t.get('name', '').startswith(prefix)
                    ] + result.tools
                    
                    updated_commands = [
                        c for c in commands if not c.get('name', '').startswith(prefix)
                    ] + result.commands
                    
                    resources = mcp.get('resources', {})
                    if result.resources:
                        resources = {**resources, server_name: result.resources}
                    
                    return {
                        **prev,
                        'mcp': {
                            **mcp,
                            'clients': updated_clients,
                            'tools': updated_tools,
                            'commands': updated_commands,
                            'resources': resources,
                        },
                    }
                
                set_app_state(update_state)
                
                logMCPDebug(
                    server_name,
                    f'OAuth complete, reconnected with {len(result.tools)} tool(s)',
                )
            except Exception as err:
                logMCPError(
                    server_name,
                    f'OAuth flow failed after tool-triggered start: {errorMessage(err)}',
                )
        
        # Run reconnection in background
        asyncio.create_task(on_oauth_complete())
        
        try:
            # Race: get the URL, or the flow completes without needing one
            # (e.g. XAA with cached IdP token — silent auth).
            try:
                # Wait up to 5 seconds for auth URL
                await asyncio.wait_for(auth_url_event.wait(), timeout=5.0)
                auth_url = auth_url_value[0]
            except asyncio.TimeoutError:
                auth_url = None
            
            if auth_url:
                return {
                    'data': {
                        'status': 'auth_url',
                        'authUrl': auth_url,
                        'message': f'Ask the user to open this URL in their browser to authorize the {server_name} MCP server:\n\n{auth_url}\n\nOnce they complete the flow, the server\'s tools will become available automatically.',
                    },
                }
            
            return {
                'data': {
                    'status': 'auth_url',
                    'message': f'Authentication completed silently for {server_name}. The server\'s tools should now be available.',
                },
            }
        except Exception as err:
            return {
                'data': {
                    'status': 'error',
                    'message': f'Failed to start OAuth flow for {server_name}: {errorMessage(err)}. Ask the user to run /mcp and authenticate manually.',
                },
            }
    
    def mapToolResultToToolResultBlockParam(data: McpAuthOutput, toolUseID: str) -> Dict[str, Any]:
        return {
            'tool_use_id': toolUseID,
            'type': 'tool_result',
            'content': data['message'],
        }
    
    return {
        'name': buildMcpToolName(server_name, 'authenticate'),
        'isMcp': True,
        'mcpInfo': {'serverName': server_name, 'toolName': 'authenticate'},
        'isEnabled': lambda: True,
        'isConcurrencySafe': lambda: False,
        'isReadOnly': lambda: False,
        'toAutoClassifierInput': lambda: server_name,
        'userFacingName': lambda: f'{server_name} - authenticate (MCP)',
        'maxResultSizeChars': 10_000,
        'renderToolUseMessage': lambda: f'Authenticate {server_name} MCP server',
        'description': lambda: description,
        'prompt': lambda: description,
        'checkPermissions': checkPermissions,
        'call': call,
        'mapToolResultToToolResultBlockParam': mapToolResultToToolResultBlockParam,
    }
