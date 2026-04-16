# ------------------------------------------------------------
# CronCreateTool.py
# Python conversion of ScheduleCronTool/CronCreateTool.ts
# 
# Cron task creation tool for AI Agent IDE.
# Allows AI to schedule recurring or one-shot tasks.
# ------------------------------------------------------------

from typing import Any, Dict, Optional
from dataclasses import dataclass

# Import dependencies
try:
    from ...bootstrap.state import setScheduledTasksEnabled
except ImportError:
    def setScheduledTasksEnabled(enabled: bool):
        pass

try:
    from ...utils.cron import cronToHuman, parseCronExpression, nextCronRunMs
except ImportError:
    def cronToHuman(cron: str) -> str:
        return cron
    
    def parseCronExpression(cron: str) -> Optional[Dict]:
        # Basic validation - check 5 fields
        parts = cron.split()
        return {'valid': len(parts) == 5} if len(parts) == 5 else None
    
    def nextCronRunMs(cron: str, now_ms: int) -> Optional[int]:
        return now_ms + 60000  # Fake 1 minute from now

try:
    from ...utils.cronTasks import (
        addCronTask,
        getCronFilePath,
        listAllCronTasks,
    )
except ImportError:
    _fake_tasks = []
    
    async def addCronTask(cron: str, prompt: str, recurring: bool, durable: bool, agent_id: Optional[str] = None) -> str:
        import uuid
        task_id = str(uuid.uuid4())[:8]
        _fake_tasks.append({'id': task_id, 'cron': cron, 'prompt': prompt})
        return task_id
    
    async def listAllCronTasks() -> list:
        return _fake_tasks
    
    def getCronFilePath() -> str:
        return '.claude/scheduled_tasks.json'

try:
    from ...utils.semanticBoolean import semanticBoolean
except ImportError:
    def semanticBoolean(value):
        return value if value is not None else True

try:
    from ...utils.teammateContext import getTeammateContext
except ImportError:
    def getTeammateContext():
        return None

try:
    from ...Tool import buildTool, ToolDef
except ImportError:
    def buildTool(**kwargs):
        return kwargs

from .prompt import (
    buildCronCreateDescription,
    buildCronCreatePrompt,
    CRON_CREATE_TOOL_NAME,
    DEFAULT_MAX_AGE_DAYS,
    isDurableCronEnabled,
    isKairosCronEnabled,
)


# Maximum number of scheduled jobs
MAX_JOBS = 50


# ============================================================
# Schema Definitions
# ============================================================

INPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'cron': {
            'type': 'string',
            'description': 'Standard 5-field cron expression in local time: "M H DoM Mon DoW" (e.g. "*/5 * * * *" = every 5 minutes, "30 14 28 2 *" = Feb 28 at 2:30pm local once).',
        },
        'prompt': {
            'type': 'string',
            'description': 'The prompt to enqueue at each fire time.',
        },
        'recurring': {
            'type': 'boolean',
            'description': f'true (default) = fire on every cron match until deleted or auto-expired after {DEFAULT_MAX_AGE_DAYS} days. false = fire once at the next match, then auto-delete. Use false for "remind me at X" one-shot requests with pinned minute/hour/dom/month.',
        },
        'durable': {
            'type': 'boolean',
            'description': 'true = persist to .claude/scheduled_tasks.json and survive restarts. false (default) = in-memory only, dies when this Claude session ends. Use true only when the user asks the task to survive across sessions.',
        },
    },
    'required': ['cron', 'prompt'],
}

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'id': {
            'type': 'string',
            'description': 'Job ID',
        },
        'humanSchedule': {
            'type': 'string',
            'description': 'Human-readable schedule description',
        },
        'recurring': {
            'type': 'boolean',
            'description': 'Whether the job is recurring',
        },
        'durable': {
            'type': 'boolean',
            'description': 'Whether the job persists to disk',
        },
    },
    'required': ['id', 'humanSchedule', 'recurring'],
}


@dataclass
class CronCreateInput:
    """Input type for CronCreateTool."""
    cron: str
    prompt: str
    recurring: bool = True
    durable: bool = False


@dataclass
class CronCreateOutput:
    """Output type for CronCreateTool."""
    id: str
    humanSchedule: str
    recurring: bool
    durable: Optional[bool] = None


async def _validate_input(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate the input for CronCreateTool.
    
    Returns:
        Dict with 'result' (bool), optional 'message', and optional 'errorCode'
    """
    cron = input_data.get('cron', '')
    durable = input_data.get('durable', False)
    
    # Validate cron expression format
    if not parseCronExpression(cron):
        return {
            'result': False,
            'message': f"Invalid cron expression '{cron}'. Expected 5 fields: M H DoM Mon DoW.",
            'errorCode': 1,
        }
    
    # Validate cron has future matches
    if nextCronRunMs(cron, int(__import__('time').time() * 1000)) is None:
        return {
            'result': False,
            'message': f"Cron expression '{cron}' does not match any calendar date in the next year.",
            'errorCode': 2,
        }
    
    # Enforce max jobs limit
    tasks = await listAllCronTasks()
    if len(tasks) >= MAX_JOBS:
        return {
            'result': False,
            'message': f"Too many scheduled jobs (max {MAX_JOBS}). Cancel one first.",
            'errorCode': 3,
        }
    
    # Teammates don't persist across sessions, so a durable teammate cron
    # would orphan on restart (agentId would point to a nonexistent teammate)
    if durable and getTeammateContext():
        return {
            'result': False,
            'message': 'durable crons are not supported for teammates (teammates do not persist across sessions)',
            'errorCode': 4,
        }
    
    return {'result': True}


async def _call_cron_create(
    input_data: Dict[str, Any],
    context: Any,
) -> Dict[str, Any]:
    """
    Call the CronCreateTool.
    
    Creates a new scheduled cron task.
    """
    # Validate input
    validation = await _validate_input(input_data)
    if not validation['result']:
        raise ValueError(validation.get('message', 'Validation failed'))
    
    # Extract parameters
    cron = input_data.get('cron', '')
    prompt_text = input_data.get('prompt', '')
    recurring = input_data.get('recurring', True)
    durable = input_data.get('durable', False)
    
    # Kill switch forces session-only; schema stays stable so the model sees
    # no validation errors when the gate flips mid-session
    effective_durable = durable and isDurableCronEnabled()
    
    # Get teammate context
    teammate_ctx = getTeammateContext()
    agent_id = teammate_ctx.agentId if teammate_ctx else None
    
    # Create the task
    task_id = await addCronTask(
        cron,
        prompt_text,
        recurring,
        effective_durable,
        agent_id,
    )
    
    # Enable the scheduler so the task fires in this session
    setScheduledTasksEnabled(True)
    
    return {
        'data': {
            'id': task_id,
            'humanSchedule': cronToHuman(cron),
            'recurring': recurring,
            'durable': effective_durable,
        },
    }


# ============================================================
# Tool Definition
# ============================================================

CronCreateTool = buildTool(
    name=CRON_CREATE_TOOL_NAME,
    searchHint='schedule a recurring or one-shot prompt',
    maxResultSizeChars=100_000,
    shouldDefer=True,
    inputSchema=INPUT_SCHEMA,
    outputSchema=OUTPUT_SCHEMA,
    isEnabled=lambda: isKairosCronEnabled(),
    toAutoClassifierInput=lambda input_data: f"{input_data.get('cron', '')}: {input_data.get('prompt', '')}",
    description=lambda: buildCronCreateDescription(isDurableCronEnabled()),
    prompt=lambda: buildCronCreatePrompt(isDurableCronEnabled()),
    getPath=lambda: getCronFilePath(),
    call=_call_cron_create,
    mapToolResultToToolResultBlockParam=lambda output, toolUseID: {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': (
            f"Scheduled recurring job {output.get('id')} ({output.get('humanSchedule')}). "
            f"{'Persisted to .claude/scheduled_tasks.json' if output.get('durable') else 'Session-only (not written to disk, dies when Claude exits)'}. "
            f"Auto-expires after {DEFAULT_MAX_AGE_DAYS} days. Use CronDelete to cancel sooner."
            if output.get('recurring')
            else f"Scheduled one-shot task {output.get('id')} ({output.get('humanSchedule')}). "
                 f"{'Persisted to .claude/scheduled_tasks.json' if output.get('durable') else 'Session-only (not written to disk, dies when Claude exits)'}. "
                 f"It will fire once then auto-delete."
        ),
    },
    renderToolUseMessage=renderCreateToolUseMessage,
    renderToolResultMessage=renderCreateResultMessage,
)
