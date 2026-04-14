# ------------------------------------------------------------
# RemoteTriggerTool.py
# Python conversion of RemoteTriggerTool/RemoteTriggerTool.ts
# 
# Remote Agent Trigger Manager for AI Agent IDE.
# Allows AI to manage scheduled remote Claude Code agents via claude.ai CCR API.
# OAuth authentication is handled in-process - token never exposed to shell.
# ------------------------------------------------------------

from typing import Any, Dict, Literal, Optional
from dataclasses import dataclass
import asyncio

# Import dependencies
try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from ...constants.oauth import getOauthConfig
except ImportError:
    def getOauthConfig():
        raise NotImplementedError("getOauthConfig not available")

try:
    from ...services.analytics.growthbook import getFeatureValue_CACHED_MAY_BE_STALE
except ImportError:
    def getFeatureValue_CACHED_MAY_BE_STALE(key, default):
        return default

try:
    from ...services.oauth.client import getOrganizationUUID
except ImportError:
    async def getOrganizationUUID():
        raise NotImplementedError("getOrganizationUUID not available")

try:
    from ...services.policyLimits import isPolicyAllowed
except ImportError:
    def isPolicyAllowed(policy):
        return True  # Fallback: allow if policy check not available

try:
    from ...utils.auth import (
        checkAndRefreshOAuthTokenIfNeeded,
        getClaudeAIOAuthTokens,
    )
except ImportError:
    async def checkAndRefreshOAuthTokenIfNeeded():
        pass
    
    def getClaudeAIOAuthTokens():
        return None

try:
    from ...utils.slowOperations import jsonStringify
except ImportError:
    def jsonStringify(obj: Any) -> str:
        import json
        return json.dumps(obj, default=str)

try:
    from ...Tool import buildTool, ToolDef
except ImportError:
    def buildTool(**kwargs):
        return kwargs

from .prompt import DESCRIPTION, PROMPT, REMOTE_TRIGGER_TOOL_NAME


# ============================================================
# Schema Definitions
# ============================================================

# Input schema: action + optional trigger_id + optional body
INPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'action': {
            'type': 'string',
            'enum': ['list', 'get', 'create', 'update', 'run'],
            'description': 'The action to perform',
        },
        'trigger_id': {
            'type': 'string',
            'pattern': r'^[\w-]+$',
            'description': 'Required for get, update, and run',
        },
        'body': {
            'type': 'object',
            'description': 'JSON body for create and update',
            'additionalProperties': True,
        },
    },
    'required': ['action'],
}

# Output schema: HTTP status + JSON response
OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'status': {
            'type': 'number',
            'description': 'HTTP status code',
        },
        'json': {
            'type': 'string',
            'description': 'JSON response from API',
        },
    },
    'required': ['status', 'json'],
}

TRIGGERS_BETA = 'ccr-triggers-2026-01-30'


@dataclass
class RemoteTriggerInput:
    """Input type for RemoteTriggerTool."""
    action: Literal['list', 'get', 'create', 'update', 'run']
    trigger_id: Optional[str] = None
    body: Optional[Dict[str, Any]] = None


@dataclass
class RemoteTriggerOutput:
    """Output type for RemoteTriggerTool."""
    status: int
    json: str


async def _call_remote_trigger(
    input_data: Dict[str, Any],
    context: Any,
) -> Dict[str, Any]:
    """
    Call the RemoteTriggerTool.
    
    Manages scheduled remote Claude Code agents via claude.ai CCR API.
    OAuth token is handled in-process and never exposed to shell.
    """
    # Check and refresh OAuth token if needed
    await checkAndRefreshOAuthTokenIfNeeded()
    
    # Get access token
    auth_tokens = getClaudeAIOAuthTokens()
    if not auth_tokens or not getattr(auth_tokens, 'accessToken', None):
        raise ValueError(
            'Not authenticated with a claude.ai account. Run /login and try again.'
        )
    accessToken = auth_tokens.accessToken
    
    # Get organization UUID
    orgUUID = await getOrganizationUUID()
    if not orgUUID:
        raise ValueError('Unable to resolve organization UUID.')
    
    # Build API base URL and headers
    oauth_config = getOauthConfig()
    base = f"{oauth_config.BASE_API_URL}/v1/code/triggers"
    headers = {
        'Authorization': f'Bearer {accessToken}',
        'Content-Type': 'application/json',
        'anthropic-version': '2023-06-01',
        'anthropic-beta': TRIGGERS_BETA,
        'x-organization-uuid': orgUUID,
    }
    
    # Extract input parameters
    action = input_data.get('action')
    trigger_id = input_data.get('trigger_id')
    body = input_data.get('body')
    
    # Determine HTTP method, URL, and data based on action
    method = None
    url = None
    data = None
    
    if action == 'list':
        method = 'GET'
        url = base
    
    elif action == 'get':
        if not trigger_id:
            raise ValueError('get requires trigger_id')
        method = 'GET'
        url = f"{base}/{trigger_id}"
    
    elif action == 'create':
        if not body:
            raise ValueError('create requires body')
        method = 'POST'
        url = base
        data = body
    
    elif action == 'update':
        if not trigger_id:
            raise ValueError('update requires trigger_id')
        if not body:
            raise ValueError('update requires body')
        method = 'POST'
        url = f"{base}/{trigger_id}"
        data = body
    
    elif action == 'run':
        if not trigger_id:
            raise ValueError('run requires trigger_id')
        method = 'POST'
        url = f"{base}/{trigger_id}/run"
        data = {}
    
    # Make the API request
    if aiohttp is None:
        raise ImportError('aiohttp is required for RemoteTriggerTool')
    
    timeout = aiohttp.ClientTimeout(total=20)
    
    # Get abort signal from context if available
    abort_signal = None
    if hasattr(context, 'abortController') and context.abortController:
        abort_signal = context.abortController
    
    async with aiohttp.ClientSession() as session:
        async with session.request(
            method=method,
            url=url,
            headers=headers,
            json=data,
            timeout=timeout,
            raise_for_status=False,  # We want to capture all status codes
        ) as res:
            response_data = await res.json()
            status_code = res.status
    
    return {
        'data': {
            'status': status_code,
            'json': jsonStringify(response_data),
        },
    }


# ============================================================
# Tool Definition
# ============================================================

RemoteTriggerTool = buildTool(
    name=REMOTE_TRIGGER_TOOL_NAME,
    searchHint='manage scheduled remote agent triggers',
    maxResultSizeChars=100_000,
    shouldDefer=True,
    inputSchema=INPUT_SCHEMA,
    outputSchema=OUTPUT_SCHEMA,
    isEnabled=lambda: (
        getFeatureValue_CACHED_MAY_BE_STALE('tengu_surreal_dali', False) and
        isPolicyAllowed('allow_remote_sessions')
    ),
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda input_data: input_data.get('action') in ('list', 'get'),
    toAutoClassifierInput=lambda input_data: (
        f"RemoteTrigger {input_data.get('action')}"
        f"{' ' + input_data.get('trigger_id', '') if input_data.get('trigger_id') else ''}"
    ),
    description=lambda: DESCRIPTION,
    prompt=lambda: PROMPT,
    call=_call_remote_trigger,
    mapToolResultToToolResultBlockParam=lambda output, toolUseID: {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': f"HTTP {output.get('status', 'unknown')}\n{output.get('json', '')}",
    },
    renderToolUseMessage=renderToolUseMessage,
    renderToolResultMessage=renderToolResultMessage,
)
