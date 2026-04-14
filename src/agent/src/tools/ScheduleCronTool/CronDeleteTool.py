# ------------------------------------------------------------
# CronDeleteTool.py
# Python conversion of ScheduleCronTool/CronDeleteTool.ts
# 
# Cron task deletion tool for AI Agent IDE.
# Allows AI to cancel scheduled tasks.
# ------------------------------------------------------------

from typing import Any, Dict
from dataclasses import dataclass

# Import dependencies
try:
    from ...utils.cronTasks import (
        getCronFilePath,
        listAllCronTasks,
        removeCronTasks,
    )
except ImportError:
    _fake_tasks = []
    
    async def listAllCronTasks() -> list:
        return _fake_tasks
    
    async def removeCronTasks(task_ids: list):
        global _fake_tasks
        _fake_tasks = [t for t in _fake_tasks if t.get('id') not in task_ids]
    
    def getCronFilePath() -> str:
        return '.claude/scheduled_tasks.json'

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
    buildCronDeletePrompt,
    CRON_DELETE_DESCRIPTION,
    CRON_DELETE_TOOL_NAME,
    isDurableCronEnabled,
    isKairosCronEnabled,
)


# ============================================================
# Schema Definitions
# ============================================================

INPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'id': {
            'type': 'string',
            'description': 'Job ID returned by CronCreate.',
        },
    },
    'required': ['id'],
}

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'id': {
            'type': 'string',
            'description': 'Cancelled job ID',
        },
    },
    'required': ['id'],
}


@dataclass
class CronDeleteInput:
    """Input type for CronDeleteTool."""
    id: str


@dataclass
class CronDeleteOutput:
    """Output type for CronDeleteTool."""
    id: str


async def _validate_input(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate the input for CronDeleteTool.
    
    Returns:
        Dict with 'result' (bool), optional 'message', and optional 'errorCode'
    """
    job_id = input_data.get('id', '')
    
    # Find the task
    tasks = await listAllCronTasks()
    task = next((t for t in tasks if t.get('id') == job_id), None)
    
    if not task:
        return {
            'result': False,
            'message': f"No scheduled job with id '{job_id}'",
            'errorCode': 1,
        }
    
    # Teammates may only delete their own crons
    ctx = getTeammateContext()
    if ctx and task.get('agentId') != ctx.agentId:
        return {
            'result': False,
            'message': f"Cannot delete cron job '{job_id}': owned by another agent",
            'errorCode': 2,
        }
    
    return {'result': True}


async def _call_cron_delete(
    input_data: Dict[str, Any],
    context: Any,
) -> Dict[str, Any]:
    """
    Call the CronDeleteTool.
    
    Cancels a scheduled cron task.
    """
    # Validate input
    validation = await _validate_input(input_data)
    if not validation['result']:
        raise ValueError(validation.get('message', 'Validation failed'))
    
    # Extract parameters
    job_id = input_data.get('id', '')
    
    # Remove the task
    await removeCronTasks([job_id])
    
    return {
        'data': {'id': job_id},
    }


# ============================================================
# Tool Definition
# ============================================================

CronDeleteTool = buildTool(
    name=CRON_DELETE_TOOL_NAME,
    searchHint='cancel a scheduled cron job',
    maxResultSizeChars=100_000,
    shouldDefer=True,
    inputSchema=INPUT_SCHEMA,
    outputSchema=OUTPUT_SCHEMA,
    isEnabled=lambda: isKairosCronEnabled(),
    toAutoClassifierInput=lambda input_data: input_data.get('id', ''),
    description=lambda: CRON_DELETE_DESCRIPTION,
    prompt=lambda: buildCronDeletePrompt(isDurableCronEnabled()),
    getPath=lambda: getCronFilePath(),
    call=_call_cron_delete,
    mapToolResultToToolResultBlockParam=lambda output, toolUseID: {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': f"Cancelled job {output.get('id')}.",
    },
    renderToolUseMessage=renderDeleteToolUseMessage,
    renderToolResultMessage=renderDeleteResultMessage,
)
