"""
BriefTool - SendUserMessage tool for communicating with users.

This tool allows the AI agent to send messages to the user with optional
file attachments (photos, screenshots, diffs, logs, etc.). It supports
both normal replies and proactive notifications.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

# Defensive imports
try:
    from ...bootstrap.state import getKairosActive, getUserMsgOptIn
except ImportError:
    def getKairosActive():
        return False
    
    def getUserMsgOptIn():
        return False

try:
    from ...services.analytics.growthbook import getFeatureValue_CACHED_WITH_REFRESH
except ImportError:
    def getFeatureValue_CACHED_WITH_REFRESH(key, default, refresh_ms):
        return default

try:
    from ...services.analytics.index import logEvent
except ImportError:
    def logEvent(event_name, properties=None):
        pass

try:
    from ...Tool import buildTool, ToolDef, ValidationResult
except ImportError:
    class ValidationResult(TypedDict, total=False):
        result: bool
        message: str
        errorCode: int
    
    def buildTool(**kwargs):
        return kwargs

try:
    from ...utils.envUtils import isEnvTruthy
except ImportError:
    def isEnvTruthy(value):
        if value is None:
            return False
        return str(value).lower() in ('true', '1', 'yes')

try:
    from .attachments import resolveAttachments, validateAttachmentPaths
except ImportError:
    async def validateAttachmentPaths(paths):
        return {'result': True}
    
    async def resolveAttachments(paths, ctx):
        return []

try:
    from .prompt import BRIEF_TOOL_NAME, BRIEF_TOOL_PROMPT, DESCRIPTION, LEGACY_BRIEF_TOOL_NAME
except ImportError:
    BRIEF_TOOL_NAME = 'SendUserMessage'
    LEGACY_BRIEF_TOOL_NAME = 'Brief'
    DESCRIPTION = 'Send a message to the user'
    BRIEF_TOOL_PROMPT = '''Send a message the user will read. Text outside this tool is visible in the detail view, but most won't open it — the answer lives here.

`message` supports markdown. `attachments` takes file paths (absolute or cwd-relative) for images, diffs, logs.

`status` labels intent: 'normal' when replying to what they just asked; 'proactive' when you're initiating — a scheduled task finished, a blocker surfaced during background work, you need input on something they haven't asked about. Set it honestly; downstream routing uses it.'''

try:
    from .UI import renderToolResultMessage, renderToolUseMessage
except ImportError:
    def renderToolUseMessage(*args, **kwargs):
        return ''
    
    def renderToolResultMessage(*args, **kwargs):
        return ''


# Constants
KAIROS_BRIEF_REFRESH_MS = 5 * 60 * 1000  # 5 minutes


def isBriefEntitled() -> bool:
    """Entitlement check — is the user ALLOWED to use Brief?
    
    Combines build-time flags with runtime GB gate + assistant-mode passthrough.
    No opt-in check here — this decides whether opt-in should be HONORED, not
    whether the user has opted in.
    
    Build-time OR-gated on KAIROS || KAIROS_BRIEF (same pattern as
    PROACTIVE || KAIROS): assistant mode depends on Brief, so KAIROS alone
    must bundle it. KAIROS_BRIEF lets Brief ship independently.
    
    Use this to decide whether `--brief` / `defaultView: 'chat'` / `--tools`
    listing should be honored. Use `isBriefEnabled()` to decide whether the
    tool is actually active in the current session.
    
    CLAUDE_CODE_BRIEF env var force-grants entitlement for dev/testing —
    bypasses the GB gate so you can test without being enrolled. Still
    requires an opt-in action to activate (--brief, defaultView, etc.), but
    the env var alone also sets userMsgOptIn via maybeActivateBrief().
    """
    # Positive ternary — see docs/feature-gating.md. Negative early-return
    # would not eliminate the GB gate string from external builds.
    # Note: In Python, we don't have Bun's feature() function, so we check env vars
    kairos_enabled = isEnvTruthy(__import__('os').environ.get('KAIROS'))
    kairos_brief_enabled = isEnvTruthy(__import__('os').environ.get('KAIROS_BRIEF'))
    
    if kairos_enabled or kairos_brief_enabled:
        return (
            getKairosActive() or
            isEnvTruthy(__import__('os').environ.get('CLAUDE_CODE_BRIEF')) or
            getFeatureValue_CACHED_WITH_REFRESH(
                'tengu_kairos_brief',
                False,
                KAIROS_BRIEF_REFRESH_MS,
            )
        )
    return False


def isBriefEnabled() -> bool:
    """Unified activation gate for the Brief tool.
    
    Governs model-facing behavior as a unit: tool availability, system prompt
    section (getBriefSection), tool-deferral bypass (isDeferredTool), and
    todo-nag suppression.
    
    Activation requires explicit opt-in (userMsgOptIn) set by one of:
      - `--brief` AI agent flag (maybeActivateBrief in main.tsx)
      - `defaultView: 'chat'` in settings (main.tsx init)
      - `/brief` slash command (brief.ts)
      - `/config` defaultView picker (Config.tsx)
      - SendUserMessage in `--tools` / SDK `tools` option (main.tsx)
      - CLAUDE_CODE_BRIEF env var (maybeActivateBrief — dev/testing bypass)
    Assistant mode (kairosActive) bypasses opt-in since its system prompt
    hard-codes "you MUST use SendUserMessage" (systemPrompt.md:14).
    
    The GB gate is re-checked here as a kill-switch AND — flipping
    tengu_kairos_brief off mid-session disables the tool on the next 5-min
    refresh even for opted-in sessions. No opt-in → always false regardless
    of GB (this is the fix for "brief defaults on for enrolled ants").
    
    Called from Tool.isEnabled() (lazy, post-init), never at module scope.
    getKairosActive() and getUserMsgOptIn() are set in main.tsx before any
    caller reaches here.
    """
    # Top-level feature() Guard is load-bearing for DCE: Bun can constant-fold
    # the ternary to `false` in external builds and then dead-code the BriefTool
    # object. Composing isBriefEntitled() alone (which has its own guard) is
    # semantically equivalent but defeats constant-folding across the boundary.
    kairos_enabled = isEnvTruthy(__import__('os').environ.get('KAIROS'))
    kairos_brief_enabled = isEnvTruthy(__import__('os').environ.get('KAIROS_BRIEF'))
    
    if kairos_enabled or kairos_brief_enabled:
        return (getKairosActive() or getUserMsgOptIn()) and isBriefEntitled()
    return False


async def validateInput(input_data: Dict[str, Any], context) -> ValidationResult:
    """Validate attachment paths if provided."""
    attachments = input_data.get('attachments')
    if not attachments or len(attachments) == 0:
        return {'result': True}
    return await validateAttachmentPaths(attachments)


async def description() -> str:
    """Return tool description."""
    return DESCRIPTION


async def prompt() -> str:
    """Return tool prompt/instructions."""
    return BRIEF_TOOL_PROMPT


def mapToolResultToToolResultBlockParam(output: Dict[str, Any], toolUseID: str) -> Dict[str, Any]:
    """Map tool output to Anthropic API tool result block."""
    n = len(output.get('attachments', []) or [])
    suffix = '' if n == 0 else f' ({n} {"attachment" if n == 1 else "attachments"} included)'
    return {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': f'Message delivered to user.{suffix}',
    }


async def call(input_data: Dict[str, Any], context) -> Dict[str, Any]:
    """Execute the BriefTool - send message to user with optional attachments."""
    message = input_data['message']
    attachments = input_data.get('attachments')
    status = input_data.get('status', 'normal')
    
    sentAt = datetime.now(timezone.utc).isoformat()
    
    logEvent('tengu_brief_send', {
        'proactive': status == 'proactive',
        'attachment_count': len(attachments) if attachments else 0,
    })
    
    if not attachments or len(attachments) == 0:
        return {'data': {'message': message, 'sentAt': sentAt}}
    
    appState = context.getAppState()
    resolved = await resolveAttachments(attachments, {
        'replBridgeEnabled': appState.replBridgeEnabled,
        'signal': context.abortController.signal if hasattr(context, 'abortController') else None,
    })
    
    return {
        'data': {
            'message': message,
            'attachments': resolved,
            'sentAt': sentAt,
        },
    }


# Build the tool definition
BriefTool = buildTool(
    name=BRIEF_TOOL_NAME,
    aliases=[LEGACY_BRIEF_TOOL_NAME],
    searchHint='send a message to the user — your primary visible output channel',
    maxResultSizeChars=100_000,
    userFacingName=lambda: '',
    isEnabled=isBriefEnabled,
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda: True,
    toAutoClassifierInput=lambda input_data: input_data.get('message', ''),
    validateInput=validateInput,
    description=description,
    prompt=prompt,
    mapToolResultToToolResultBlockParam=mapToolResultToToolResultBlockParam,
    renderToolUseMessage=renderToolUseMessage,
    renderToolResultMessage=renderToolResultMessage,
    call=call,
)
