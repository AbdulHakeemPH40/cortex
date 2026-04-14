"""
services/api/apiClient.py
Python conversion of services/api/client.ts (390 lines)

Anthropic API client factory supporting multiple providers:
- Direct API (Anthropic)
- AWS Bedrock
- Google Vertex AI
- Azure Foundry
"""

import os
import uuid
from typing import Any, Dict, Optional

try:
    from anthropic import Anthropic
    from anthropic.types import NOT_GIVEN
except ImportError:
    Anthropic = None
    NOT_GIVEN = None

try:
    from ...utils.auth import (
        check_and_refresh_oauth_token_if_needed,
        get_anthropic_api_key,
        get_cloud_ai_oauth_tokens,
        is_cloud_ai_subscriber,
    )
except ImportError:
    def check_and_refresh_oauth_token_if_needed():
        pass
    def get_anthropic_api_key():
        return None
    def get_cloud_ai_oauth_tokens():
        return None
    def is_cloud_ai_subscriber():
        return False

try:
    from ...utils.http import get_user_agent
except ImportError:
    def get_user_agent():
        return 'claude-code-python'

try:
    from ...bootstrap.state import get_session_id, get_is_non_interactive_session
except ImportError:
    def get_session_id():
        return 'unknown'
    def get_is_non_interactive_session():
        return False

try:
    from ...constants.oauth import get_oauth_config
except ImportError:
    def get_oauth_config():
        return {}

try:
    from ...utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(msg):
        print(f"[DEBUG] {msg}")

try:
    from ...utils.envUtils import is_env_truthy
except ImportError:
    def is_env_truthy(value):
        if value is None:
            return False
        return value.lower() in ('true', '1', 'yes')


def _create_stderr_logger():
    """Create logger that outputs to stderr (for SDK debugging)"""
    import sys
    
    class StderrLogger:
        def error(self, msg, *args):
            print(f"[Anthropic SDK ERROR] {msg}", *args, file=sys.stderr)
        def warn(self, msg, *args):
            print(f"[Anthropic SDK WARN] {msg}", *args, file=sys.stderr)
        def info(self, msg, *args):
            print(f"[Anthropic SDK INFO] {msg}", *args, file=sys.stderr)
        def debug(self, msg, *args):
            print(f"[Anthropic SDK DEBUG] {msg}", *args, file=sys.stderr)
    
    return StderrLogger()


def _get_custom_headers() -> Dict[str, str]:
    """Parse ANTHROPIC_CUSTOM_HEADERS environment variable"""
    custom_headers = {}
    custom_headers_env = os.environ.get('ANTHROPIC_CUSTOM_HEADERS')
    
    if not custom_headers_env:
        return custom_headers
    
    # Split by newlines to support multiple headers
    header_strings = custom_headers_env.splitlines()
    
    for header_string in header_strings:
        if not header_string.strip():
            continue
        
        # Parse header in format "Name: Value"
        colon_idx = header_string.find(':')
        if colon_idx == -1:
            continue
        
        name = header_string[:colon_idx].strip()
        value = header_string[colon_idx + 1:].strip()
        if name:
            custom_headers[name] = value
    
    return custom_headers


async def _configure_api_key_headers(headers: Dict[str, str], is_non_interactive: bool) -> None:
    """Add API key authentication headers"""
    token = os.environ.get('ANTHROPIC_AUTH_TOKEN')
    if not token:
        # Would call get_api_key_from_key_helper in real implementation
        pass
    
    if token:
        headers['Authorization'] = f'Bearer {token}'


async def get_anthropic_client(
    api_key: Optional[str] = None,
    max_retries: int = 2,
    model: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """
    Create and configure Anthropic API client.
    
    Supports multiple providers:
    - Direct API (default)
    - AWS Bedrock (CLAUDE_CODE_USE_BEDROCK=1)
    - Azure Foundry (CLAUDE_CODE_USE_FOUNDRY=1)
    - Google Vertex AI (CLAUDE_CODE_USE_VERTEX=1)
    
    Returns:
        Anthropic client instance (or provider-specific variant)
    """
    if Anthropic is None:
        raise ImportError("anthropic package required: pip install anthropic")
    
    container_id = os.environ.get('CLAUDE_CODE_CONTAINER_ID')
    remote_session_id = os.environ.get('CLAUDE_CODE_REMOTE_SESSION_ID')
    client_app = os.environ.get('CLAUDE_AGENT_SDK_CLIENT_APP')
    
    # Build default headers
    custom_headers = _get_custom_headers()
    default_headers = {
        'x-app': 'cortex-ide',
        'User-Agent': get_user_agent(),
        'X-Claude-Code-Session-Id': get_session_id(),
        **custom_headers,
    }
    
    if container_id:
        default_headers['x-claude-remote-container-id'] = container_id
    if remote_session_id:
        default_headers['x-claude-remote-session-id'] = remote_session_id
    if client_app:
        default_headers['x-client-app'] = client_app
    
    # Log API client configuration
    log_for_debugging(
        f'[API:request] Creating client, ANTHROPIC_CUSTOM_HEADERS present: {bool(os.environ.get("ANTHROPIC_CUSTOM_HEADERS"))}, '
        f'has Authorization header: {"Authorization" in custom_headers}'
    )
    
    # Add additional protection header if enabled
    if is_env_truthy(os.environ.get('CLAUDE_CODE_ADDITIONAL_PROTECTION')):
        default_headers['x-anthropic-additional-protection'] = 'true'
    
    # Refresh OAuth token if needed
    log_for_debugging('[API:auth] OAuth token check starting')
    await check_and_refresh_oauth_token_if_needed()
    log_for_debugging('[API:auth] OAuth token check complete')
    
    # Configure API key headers for non-OAuth users
    if not is_cloud_ai_subscriber():
        await _configure_api_key_headers(default_headers, get_is_non_interactive_session())
    
    # Build base client arguments
    timeout_ms = int(os.environ.get('API_TIMEOUT_MS', str(600 * 1000)))
    client_args = {
        'default_headers': default_headers,
        'max_retries': max_retries,
        'timeout': timeout_ms,
    }
    
    # Add debug logger if enabled
    if os.environ.get('CLAUDE_CODE_DEBUG_TO_STDERR'):
        client_args['logger'] = _create_stderr_logger()
    
    # ---- AWS BEDROCK ----
    if is_env_truthy(os.environ.get('CLAUDE_CODE_USE_BEDROCK')):
        try:
            from anthropic_bedrock import AnthropicBedrock
        except ImportError:
            raise ImportError("anthropic-bedrock package required for Bedrock")
        
        # Determine AWS region
        aws_region = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
        
        bedrock_args = {
            **client_args,
            'aws_region': aws_region,
        }
        
        # Add API key authentication if available
        aws_bearer_token = os.environ.get('AWS_BEARER_TOKEN_BEDROCK')
        if aws_bearer_token:
            bedrock_args['default_headers'] = {
                **bedrock_args.get('default_headers', {}),
                'Authorization': f'Bearer {aws_bearer_token}',
            }
        
        return AnthropicBedrock(**bedrock_args)
    
    # ---- AZURE FOUNDRY ----
    if is_env_truthy(os.environ.get('CLAUDE_CODE_USE_FOUNDRY')):
        try:
            from anthropic_foundry import AnthropicFoundry
        except ImportError:
            raise ImportError("anthropic-foundry package required for Foundry")
        
        foundry_args = {**client_args}
        
        # Add Azure AD token provider if no API key
        if not os.environ.get('ANTHROPIC_FOUNDRY_API_KEY'):
            # Would use azure-identity for DefaultAzureCredential
            pass
        
        return AnthropicFoundry(**foundry_args)
    
    # ---- GOOGLE VERTEX AI ----
    if is_env_truthy(os.environ.get('CLAUDE_CODE_USE_VERTEX')):
        try:
            from anthropic_vertex import AnthropicVertex
        except ImportError:
            raise ImportError("anthropic-vertex package required for Vertex")
        
        # Determine Vertex region
        vertex_region = os.environ.get('CLOUD_ML_REGION', 'us-east5')
        
        vertex_args = {
            **client_args,
            'region': vertex_region,
        }
        
        return AnthropicVertex(**vertex_args)
    
    # ---- DIRECT API (default) ----
    client_config = {
        **client_args,
        'api_key': None if is_cloud_ai_subscriber() else (api_key or get_anthropic_api_key()),
    }
    
    # Use OAuth token for Claude.ai subscribers
    if is_cloud_ai_subscriber():
        oauth_tokens = get_cloud_ai_oauth_tokens()
        if oauth_tokens and oauth_tokens.get('accessToken'):
            client_config['auth_token'] = oauth_tokens['accessToken']
    
    # Use staging API URL if configured
    if os.environ.get('USER_TYPE') == 'ant' and is_env_truthy(os.environ.get('USE_STAGING_OAUTH')):
        oauth_config = get_oauth_config()
        client_config['base_url'] = oauth_config.get('BASE_API_URL')
    
    return Anthropic(**client_config)


def build_client_request_id() -> str:
    """Generate unique client request ID for correlation"""
    return str(uuid.uuid4())


CLIENT_REQUEST_ID_HEADER = 'x-client-request-id'


__all__ = [
    'get_anthropic_client',
    'build_client_request_id',
    'CLIENT_REQUEST_ID_HEADER',
]
