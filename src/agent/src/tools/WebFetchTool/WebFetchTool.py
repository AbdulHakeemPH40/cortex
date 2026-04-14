"""WebFetch Tool - Fetch and extract content from URLs."""
import time
from typing import Any, Dict, Optional
try:
    from typing import TypeAlias
except ImportError:  # Python < 3.10
    from typing_extensions import TypeAlias
from urllib.parse import urlparse

# Defensive imports
try:
    from ...Tool import build_tool, ToolDef
except ImportError:
    def build_tool(**kwargs):
        """Stub build_tool."""
        return kwargs
    
    class ToolDef:
        """Stub ToolDef type."""
        pass

try:
    from ...utils.permissions.permissions import PermissionDecision
except ImportError:
    PermissionDecision: TypeAlias = Dict[str, Any]

try:
    from ...utils.permissions.permissions import get_rule_by_contents_for_tool
except ImportError:
    def get_rule_by_contents_for_tool(*args, **kwargs):
        """Stub permission checker."""
        return {}

try:
    from .preapproved import is_preapproved_host
except ImportError:
    def is_preapproved_host(hostname: str, pathname: str) -> bool:
        return False

try:
    from .prompt import DESCRIPTION, WEB_FETCH_TOOL_NAME
except ImportError:
    WEB_FETCH_TOOL_NAME = 'WebFetch'
    DESCRIPTION = 'Fetch web content'

try:
    from .UI import (
        get_tool_use_summary,
        render_tool_result_message,
        render_tool_use_message,
        render_tool_use_progress_message,
    )
except ImportError:
    def get_tool_use_summary(input_data):
        return input_data.get('url', '')
    
    def render_tool_use_message(*args, **kwargs):
        return "Fetching web page"
    
    def render_tool_use_progress_message(*args, **kwargs):
        return "Fetching..."
    
    def render_tool_result_message(*args, **kwargs):
        return "Done"

try:
    from .utils import (
        apply_prompt_to_markdown,
        FetchedContent,
        get_url_markdown_content,
        is_preapproved_url,
        MAX_MARKDOWN_LENGTH,
        RedirectInfo,
    )
except ImportError:
    async def apply_prompt_to_markdown(*args, **kwargs):
        return "No response from model"
    
    async def get_url_markdown_content(*args, **kwargs):
        raise NotImplementedError("utils not available")
    
    def is_preapproved_url(url: str) -> bool:
        return False
    
    MAX_MARKDOWN_LENGTH = 100_000


def web_fetch_tool_input_to_permission_rule_content(input_data: Dict[str, Any]) -> str:
    """Convert tool input to permission rule content (domain-based)."""
    try:
        url = input_data.get('url', '')
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname:
            return f'domain:{hostname}'
        return f'input:{str(input_data)}'
    except Exception:
        return f'input:{str(input_data)}'


def build_suggestions(rule_content: str) -> list:
    """Build permission update suggestions."""
    return [
        {
            'type': 'addRules',
            'destination': 'localSettings',
            'rules': [{'toolName': WEB_FETCH_TOOL_NAME, 'ruleContent': rule_content}],
            'behavior': 'allow',
        }
    ]


async def check_permissions(input_data: Dict[str, Any], context: Any) -> PermissionDecision:
    """Check permissions for WebFetch tool usage."""
    try:
        app_state = context.get_app_state()
        permission_context = app_state.tool_permission_context
        
        # Check if hostname is preapproved
        url = input_data.get('url', '')
        try:
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname or ''
            pathname = parsed_url.path or ''
            
            if is_preapproved_host(hostname, pathname):
                return {
                    'behavior': 'allow',
                    'updatedInput': input_data,
                    'decisionReason': {'type': 'other', 'reason': 'Preapproved host'},
                }
        except Exception:
            pass
        
        # Check for rules specific to the domain
        rule_content = web_fetch_tool_input_to_permission_rule_content(input_data)
        
        # Check deny rules
        deny_rules = get_rule_by_contents_for_tool(
            permission_context,
            WEB_FETCH_TOOL_NAME,
            'deny'
        )
        deny_rule = deny_rules.get(rule_content)
        if deny_rule:
            return {
                'behavior': 'deny',
                'message': f'{WEB_FETCH_TOOL_NAME} denied access to {rule_content}.',
                'decisionReason': {
                    'type': 'rule',
                    'rule': deny_rule,
                },
            }
        
        # Check ask rules
        ask_rules = get_rule_by_contents_for_tool(
            permission_context,
            WEB_FETCH_TOOL_NAME,
            'ask'
        )
        ask_rule = ask_rules.get(rule_content)
        if ask_rule:
            return {
                'behavior': 'ask',
                'message': f'Cortex requested permissions to use {WEB_FETCH_TOOL_NAME}, but you haven\'t granted it yet.',
                'decisionReason': {
                    'type': 'rule',
                    'rule': ask_rule,
                },
                'suggestions': build_suggestions(rule_content),
            }
        
        # Check allow rules
        allow_rules = get_rule_by_contents_for_tool(
            permission_context,
            WEB_FETCH_TOOL_NAME,
            'allow'
        )
        allow_rule = allow_rules.get(rule_content)
        if allow_rule:
            return {
                'behavior': 'allow',
                'updatedInput': input_data,
                'decisionReason': {
                    'type': 'rule',
                    'rule': allow_rule,
                },
            }
        
        # Default: ask for permission
        return {
            'behavior': 'ask',
            'message': f'Cortex requested permissions to use {WEB_FETCH_TOOL_NAME}, but you haven\'t granted it yet.',
            'suggestions': build_suggestions(rule_content),
        }
    
    except Exception as e:
        # On error, default to asking
        return {
            'behavior': 'ask',
            'message': f'Error checking permissions: {str(e)}',
        }


async def validate_input(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate WebFetch tool input."""
    url = input_data.get('url', '')
    
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Invalid URL")
        return {'result': True}
    except Exception:
        return {
            'result': False,
            'message': f'Error: Invalid URL "{url}". The URL provided could not be parsed.',
            'meta': {'reason': 'invalid_url'},
            'errorCode': 1,
        }


async def call_tool(
    input_data: Dict[str, Any],
    context: Any
) -> Dict[str, Any]:
    """Execute the WebFetch tool."""
    start_time = time.time()
    
    url = input_data.get('url', '')
    prompt = input_data.get('prompt', '')
    
    # Get abort controller from context
    abort_controller = getattr(context, 'abort_controller', None)
    options = getattr(context, 'options', {})
    is_non_interactive_session = options.get('isNonInteractiveSession', False)
    
    # Fetch the content
    response = await get_url_markdown_content(url, abort_controller)
    
    # Check if we got a redirect
    if isinstance(response, RedirectInfo):
        status_code = response.status_code
        
        if status_code == 301:
            status_text = 'Moved Permanently'
        elif status_code == 308:
            status_text = 'Permanent Redirect'
        elif status_code == 307:
            status_text = 'Temporary Redirect'
        else:
            status_text = 'Found'
        
        message = (
            f"REDIRECT DETECTED: The URL redirects to a different host.\n\n"
            f"Original URL: {response.original_url}\n"
            f"Redirect URL: {response.redirect_url}\n"
            f"Status: {status_code} {status_text}\n\n"
            f"To complete your request, I need to fetch content from the redirected URL. "
            f"Please use WebFetch again with these parameters:\n"
            f'- url: "{response.redirect_url}"\n'
            f'- prompt: "{prompt}"'
        )
        
        output = {
            'bytes': len(message.encode('utf-8')),
            'code': status_code,
            'codeText': status_text,
            'result': message,
            'durationMs': int((time.time() - start_time) * 1000),
            'url': url,
        }
        
        return {'data': output}
    
    # Process the fetched content
    content = response.content
    bytes_fetched = response.bytes
    code = response.code
    code_text = response.code_text
    content_type = response.content_type
    persisted_path = getattr(response, 'persisted_path', None)
    persisted_size = getattr(response, 'persisted_size', None)
    
    # Check if preapproved
    is_preapproved = is_preapproved_url(url)
    
    # Apply prompt or return raw content
    if (
        is_preapproved and
        'text/markdown' in content_type and
        len(content) < MAX_MARKDOWN_LENGTH
    ):
        result = content
    else:
        signal = getattr(abort_controller, 'signal', None) if abort_controller else None
        result = await apply_prompt_to_markdown(
            prompt,
            content,
            signal,
            is_non_interactive_session,
            is_preapproved
        )
    
    # Add note about binary content if saved
    if persisted_path:
        size_str = _format_file_size(persisted_size or bytes_fetched)
        result += f"\n\n[Binary content ({content_type}, {size_str}) also saved to {persisted_path}]"
    
    output = {
        'bytes': bytes_fetched,
        'code': code,
        'codeText': code_text,
        'result': result,
        'durationMs': int((time.time() - start_time) * 1000),
        'url': url,
    }
    
    return {'data': output}


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def map_tool_result_to_block_param(result_data: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """Map tool result to Anthropic API tool result block."""
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': result_data.get('result', ''),
    }


async def get_description(input_data: Dict[str, Any]) -> str:
    """Get dynamic description based on input."""
    url = input_data.get('url', '')
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname:
            return f'Cortex wants to fetch content from {hostname}'
    except Exception:
        pass
    return 'Cortex wants to fetch content from this URL'


def get_activity_description(input_data: Dict[str, Any]) -> str:
    """Get activity description for UI."""
    summary = get_tool_use_summary(input_data)
    return f'Fetching {summary}' if summary else 'Fetching web page'


def get_prompt(options: Dict[str, Any]) -> str:
    """Get the system prompt for this tool."""
    return (
        "IMPORTANT: WebFetch WILL FAIL for authenticated or private URLs. "
        "Before using this tool, check if the URL points to an authenticated service "
        "(e.g. Google Docs, Confluence, Jira, GitHub). If so, look for a specialized "
        "MCP tool that provides authenticated access.\n"
        f"{DESCRIPTION}"
    )


# Build the tool definition
WebFetchTool = build_tool(
    name=WEB_FETCH_TOOL_NAME,
    searchHint='fetch and extract content from a URL',
    maxResultSizeChars=100_000,
    shouldDefer=True,
    description=get_description,
    userFacingName=lambda: 'Fetch',
    getToolUseSummary=get_tool_use_summary,
    getActivityDescription=get_activity_description,
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda: True,
    toAutoClassifierInput=lambda input_data: f"{input_data.get('url', '')}: {input_data.get('prompt', '')}" if input_data.get('prompt') else input_data.get('url', ''),
    checkPermissions=check_permissions,
    prompt=get_prompt,
    validateInput=validate_input,
    renderToolUseMessage=render_tool_use_message,
    renderToolUseProgressMessage=render_tool_use_progress_message,
    renderToolResultMessage=render_tool_result_message,
    call=call_tool,
    mapToolResultToToolResultBlockParam=map_tool_result_to_block_param,
)
