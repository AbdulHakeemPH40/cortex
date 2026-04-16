"""
ExitPlanModeV2Tool - Present plan for approval and start coding.

Allows the AI agent to exit plan mode after presenting a plan to the user,
handling teammate approval workflows and permission restoration.
"""

import os
from typing import Any, Dict, List, Optional, TypedDict

# Defensive imports
try:
    from ...bootstrap.state import (
        getAllowedChannels,
        hasExitedPlanModeInSession,
        setHasExitedPlanMode,
        setNeedsAutoModeExitAttachment,
        setNeedsPlanModeExitAttachment,
    )
except ImportError:
    def getAllowedChannels():
        return []
    
    def hasExitedPlanModeInSession():
        return False
    
    def setHasExitedPlanMode(value):
        pass
    
    def setNeedsAutoModeExitAttachment(value):
        pass
    
    def setNeedsPlanModeExitAttachment(value):
        pass

try:
    from ...services.analytics.index import logEvent
except ImportError:
    def logEvent(event_name, data=None):
        pass

try:
    from ...Tool import buildTool, ToolDef, toolMatchesName
except ImportError:
    def buildTool(**kwargs):
        return kwargs
    
    class ToolDef:
        pass
    
    def toolMatchesName(tool, name):
        return getattr(tool, 'name', '') == name

try:
    from ...utils.agentId import formatAgentId, generateRequestId
except ImportError:
    def formatAgentId(agent_name, team_name):
        return f'{agent_name}@{team_name}'
    
    def generateRequestId(prefix, agent_id):
        import uuid
        return f'{prefix}-{uuid.uuid4().hex[:8]}'

try:
    from ...utils.agentSwarmsEnabled import isAgentSwarmsEnabled
except ImportError:
    def isAgentSwarmsEnabled():
        return False

try:
    from ...utils.debug import logForDebugging
except ImportError:
    def logForDebugging(message, options=None):
        pass

try:
    from ...utils.inProcessTeammateHelpers import findInProcessTeammateTaskId, setAwaitingPlanApproval
except ImportError:
    def findInProcessTeammateTaskId(agent_name, app_state):
        return None
    
    def setAwaitingPlanApproval(task_id, set_app_state, value):
        pass

try:
    from ...utils.log import logError
except ImportError:
    def logError(error):
        print(f'Error: {error}')

try:
    from ...utils.plans import getPlan, getPlanFilePath, persistFileSnapshotIfRemote
except ImportError:
    def getPlan(agent_id=None):
        return None
    
    def getPlanFilePath(agent_id=None):
        return './plan.md'
    
    async def persistFileSnapshotIfRemote():
        pass

try:
    from ...utils.slowOperations import jsonStringify
except ImportError:
    import json
    def jsonStringify(obj):
        return json.dumps(obj)

try:
    from ...utils.teammate import getAgentName, getTeamName, isPlanModeRequired, isTeammate
except ImportError:
    def getAgentName():
        return None
    
    def getTeamName():
        return None
    
    def isPlanModeRequired():
        return False
    
    def isTeammate():
        return False

try:
    from ...utils.teammateMailbox import writeToMailbox
except ImportError:
    async def writeToMailbox(recipient, message, team_name=None):
        pass

try:
    from ..AgentTool.constants import AGENT_TOOL_NAME
except ImportError:
    AGENT_TOOL_NAME = 'Agent'

try:
    from ..TeamCreateTool.constants import TEAM_CREATE_TOOL_NAME
except ImportError:
    TEAM_CREATE_TOOL_NAME = 'TeamCreate'

try:
    from .constants import EXIT_PLAN_MODE_V2_TOOL_NAME
except ImportError:
    EXIT_PLAN_MODE_V2_TOOL_NAME = 'ExitPlanMode'

try:
    from .prompt import EXIT_PLAN_MODE_V2_TOOL_PROMPT
except ImportError:
    EXIT_PLAN_MODE_V2_TOOL_PROMPT = 'Prompts the user to exit plan mode and start coding'

try:
    from .UI import renderToolResultMessage, renderToolUseMessage, renderToolUseRejectedMessage
except ImportError:
    def renderToolUseMessage(*args, **kwargs):
        return None
    
    def renderToolResultMessage(*args, **kwargs):
        return ''
    
    def renderToolUseRejectedMessage(*args, **kwargs):
        return ''


class AllowedPrompt(TypedDict):
    """Schema for prompt-based permission requests."""
    tool: str
    prompt: str


class Input(TypedDict, total=False):
    """Input schema for ExitPlanModeV2Tool."""
    allowedPrompts: Optional[List[AllowedPrompt]]
    plan: Optional[str]  # Injected by normalizeToolInput
    planFilePath: Optional[str]  # Injected by normalizeToolInput


class Output(TypedDict, total=False):
    """Output schema for ExitPlanModeV2Tool."""
    plan: Optional[str]
    isAgent: bool
    filePath: Optional[str]
    hasTaskTool: Optional[bool]
    planWasEdited: Optional[bool]
    awaitingLeaderApproval: Optional[bool]
    requestId: Optional[str]


def isEnabled() -> bool:
    """Check if ExitPlanModeV2 tool is enabled."""
    # When --channels is active the user is likely on Telegram/Discord, not
    # watching the TUI. The plan-approval dialog would hang. Paired with the
    # same gate on EnterPlanMode so plan mode isn't a trap.
    kairos_enabled = os.environ.get('KAIROS', '').lower() in ('true', '1', 'yes')
    kairos_channels_enabled = os.environ.get('KAIROS_CHANNELS', '').lower() in ('true', '1', 'yes')
    
    if (kairos_enabled or kairos_channels_enabled) and len(getAllowedChannels()) > 0:
        return False
    
    return True


async def validateInput(input_data: Input, context) -> Dict[str, Any]:
    """Validate input before execution."""
    # Teammate AppState may show leader's mode (runAgent.py skips override in
    # acceptEdits/bypassPermissions/auto); isPlanModeRequired() is the real source
    if isTeammate():
        return {'result': True}
    
    # The deferred-tool list announces this tool regardless of mode, so the
    # model can call it after plan approval (fresh delta on compact/clear).
    # Reject before checkPermissions to avoid showing the approval dialog.
    mode = context.getAppState()['toolPermissionContext']['mode']
    if mode != 'plan':
        logEvent('tengu_exit_plan_mode_called_outside_plan', {
            'model': getattr(context.options, 'mainLoopModel', None),
            'mode': mode,
            'hasExitedPlanModeInSession': hasExitedPlanModeInSession(),
        })
        return {
            'result': False,
            'message': 'You are not in plan mode. This tool is only for exiting plan mode after writing a plan. If your plan was already approved, continue with implementation.',
            'errorCode': 1,
        }
    
    return {'result': True}


async def checkPermissions(input_data: Input, context) -> Dict[str, Any]:
    """Check permissions for tool execution."""
    # For ALL teammates, bypass the permission UI to avoid sending permission_request
    # The call() method handles the appropriate behavior:
    # - If isPlanModeRequired(): sends plan_approval_request to leader
    # - Otherwise: exits plan mode locally (voluntary plan mode)
    if isTeammate():
        return {
            'behavior': 'allow',
            'updatedInput': input_data,
        }
    
    # For non-teammates, require user confirmation to exit plan mode
    return {
        'behavior': 'ask',
        'message': 'Exit plan mode?',
        'updatedInput': input_data,
    }


async def call(input_data: Input, context) -> Dict[str, Any]:
    """Execute ExitPlanModeV2Tool - present plan and exit plan mode."""
    is_agent = bool(getattr(context, 'agentId', None))
    
    file_path = getPlanFilePath(getattr(context, 'agentId', None))
    
    # CCR web UI may send an edited plan via permissionResult.updatedInput.
    # queryHelpers.py full-replaces finalInput, so when CCR sends {} (no edit)
    # input_data.plan is undefined -> disk fallback. The internal inputSchema omits
    # `plan` (normally injected by normalizeToolInput), hence the narrowing.
    input_plan = input_data.get('plan') if isinstance(input_data.get('plan'), str) else None
    plan = input_plan or getPlan(getattr(context, 'agentId', None))
    
    # Sync disk so VerifyPlanExecution / Read see the edit. Re-snapshot
    # after: the only other persistFileSnapshotIfRemote call (api.py) runs
    # in normalizeToolInput, pre-permission — it captured the old plan.
    if input_plan is not None and file_path:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(input_plan)
        except Exception as e:
            logError(e)
        
        import asyncio
        asyncio.create_task(persistFileSnapshotIfRemote())
    
    # Check if this is a teammate that requires leader approval
    if isTeammate() and isPlanModeRequired():
        # Plan is required for plan_mode_required teammates
        if not plan:
            raise Exception(
                f'No plan file found at {file_path}. Please write your plan to this file before calling ExitPlanMode.'
            )
        
        agent_name = getAgentName() or 'unknown'
        team_name = getTeamName()
        request_id = generateRequestId(
            'plan_approval',
            formatAgentId(agent_name, team_name or 'default'),
        )
        
        approval_request = {
            'type': 'plan_approval_request',
            'from': agent_name,
            'timestamp': __import__('datetime').datetime.utcnow().isoformat(),
            'planFilePath': file_path,
            'planContent': plan,
            'requestId': request_id,
        }
        
        await writeToMailbox(
            'team-lead',
            {
                'from': agent_name,
                'text': jsonStringify(approval_request),
                'timestamp': __import__('datetime').datetime.utcnow().isoformat(),
            },
            team_name,
        )
        
        # Update task state to show awaiting approval (for in-process teammates)
        app_state = context.getAppState()
        agent_task_id = findInProcessTeammateTaskId(agent_name, app_state)
        if agent_task_id:
            setAwaitingPlanApproval(agent_task_id, context.setAppState, True)
        
        return {
            'data': {
                'plan': plan,
                'isAgent': True,
                'filePath': file_path,
                'awaitingLeaderApproval': True,
                'requestId': request_id,
            },
        }
    
    # Note: Background verification hook is registered in REPL.py AFTER context clear
    # via registerPlanVerificationHook(). Registering here would be cleared during context clear.
    
    # Ensure mode is changed when exiting plan mode.
    # This handles cases where permission flow didn't set the mode
    # (e.g., when PermissionRequest hook auto-approves without providing updatedPermissions).
    app_state = context.getAppState()
    
    # Compute gate-off fallback before setAppState so we can notify the user.
    # Circuit breaker defense: if prePlanMode was an auto-like mode but the
    # gate is now off (circuit breaker or settings disable), restore to
    # 'default' instead. Without this, ExitPlanMode would bypass the circuit
    # breaker by calling setAutoModeActive(True) directly.
    gate_fallback_notification = None
    
    pre_plan_raw = app_state['toolPermissionContext'].get('prePlanMode') or 'default'
    # Note: TRANSCRIPT_CLASSIFIER feature check omitted - assume disabled
    # In production, check: os.environ.get('TRANSCRIPT_CLASSIFIER', '').lower() in ('true', '1', 'yes')
    
    if gate_fallback_notification:
        if hasattr(context, 'addNotification'):
            context.addNotification({
                'key': 'auto-mode-gate-plan-exit-fallback',
                'text': f'plan exit → default · {gate_fallback_notification}',
                'priority': 'immediate',
                'color': 'warning',
                'timeoutMs': 10000,
            })
    
    context.setAppState(lambda prev: {
        **prev,
        'toolPermissionContext': {
            **prev['toolPermissionContext'],
            'mode': prev['toolPermissionContext'].get('prePlanMode') or 'default',
            'prePlanMode': None,
        },
    } if prev['toolPermissionContext']['mode'] == 'plan' else prev)
    
    setHasExitedPlanMode(True)
    setNeedsPlanModeExitAttachment(True)
    
    has_task_tool = (
        isAgentSwarmsEnabled() and
        any(toolMatchesName(t, AGENT_TOOL_NAME) for t in getattr(context.options, 'tools', []))
    )
    
    return {
        'data': {
            'plan': plan,
            'isAgent': is_agent,
            'filePath': file_path,
            'hasTaskTool': has_task_tool or None,
            'planWasEdited': input_plan is not None or None,
        },
    }


def mapToolResultToToolResultBlockParam(content: Output, toolUseID: str) -> Dict[str, Any]:
    """Map tool output to Anthropic API tool result block."""
    # Handle teammate awaiting leader approval
    if content.get('awaitingLeaderApproval'):
        return {
            'type': 'tool_result',
            'content': f'''Your plan has been submitted to the team lead for approval.

Plan file: {content.get('filePath')}

**What happens next:**
1. Wait for the team lead to review your plan
2. You will receive a message in your inbox with approval/rejection
3. If approved, you can proceed with implementation
4. If rejected, refine your plan based on the feedback

**Important:** Do NOT proceed until you receive approval. Check your inbox for response.

Request ID: {content.get('requestId')}''',
            'tool_use_id': toolUseID,
        }
    
    if content.get('isAgent'):
        return {
            'type': 'tool_result',
            'content': 'User has approved the plan. There is nothing else needed from you now. Please respond with "ok"',
            'tool_use_id': toolUseID,
        }
    
    # Handle empty plan
    plan = content.get('plan')
    if not plan or not plan.strip():
        return {
            'type': 'tool_result',
            'content': 'User has approved exiting plan mode. You can now proceed.',
            'tool_use_id': toolUseID,
        }
    
    has_task_tool = content.get('hasTaskTool')
    team_hint = f'\n\nIf this plan can be broken down into multiple independent tasks, consider using the {TEAM_CREATE_TOOL_NAME} tool to create a team and parallelize the work.' if has_task_tool else ''
    
    # Always include the plan — extractApprovedPlan() in the Ultraplan CCR
    # flow parses the tool_result to retrieve the plan text for the local AI agent.
    # Label edited plans so the model knows the user changed something.
    plan_label = 'Approved Plan (edited by user)' if content.get('planWasEdited') else 'Approved Plan'
    
    return {
        'type': 'tool_result',
        'content': f'''User has approved your plan. You can now start coding. Start with updating your todo list if applicable

Your plan has been saved to: {content.get('filePath')}
You can refer back to it if needed during implementation.{team_hint}

## {plan_label}:
{plan}''',
        'tool_use_id': toolUseID,
    }


# Build the tool definition
ExitPlanModeV2Tool = buildTool(
    name=EXIT_PLAN_MODE_V2_TOOL_NAME,
    searchHint='present plan for approval and start coding (plan mode only)',
    maxResultSizeChars=100_000,
    description=lambda: 'Prompts the user to exit plan mode and start coding',
    prompt=lambda: EXIT_PLAN_MODE_V2_TOOL_PROMPT,
    userFacingName=lambda: '',
    shouldDefer=True,
    isEnabled=isEnabled,
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda: False,  # Now writes to disk
    requiresUserInteraction=lambda: not isTeammate(),
    validateInput=validateInput,
    checkPermissions=checkPermissions,
    renderToolUseMessage=renderToolUseMessage,
    renderToolResultMessage=renderToolResultMessage,
    renderToolUseRejectedMessage=renderToolUseRejectedMessage,
    call=call,
    mapToolResultToToolResultBlockParam=mapToolResultToToolResultBlockParam,
)
