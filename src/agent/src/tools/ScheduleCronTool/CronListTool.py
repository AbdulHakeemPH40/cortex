# ------------------------------------------------------------
# CronListTool.py
# Python conversion of ScheduleCronTool/CronListTool.ts
# 
# Cron task listing tool for AI Agent IDE.
# Allows AI to view scheduled tasks.
# ------------------------------------------------------------

from typing import Any, Dict, List
from dataclasses import dataclass, field

# Import dependencies
try:
    from ...utils.cron import cronToHuman
except ImportError:
    def cronToHuman(cron: str) -> str:
        return cron

try:
    from ...utils.cronTasks import listAllCronTasks
except ImportError:
    async def listAllCronTasks() -> list:
        return []

try:
    from ...utils.format import truncate
except ImportError:
    def truncate(text: str, length: int, add_ellipsis: bool = False) -> str:
        if len(text) <= length:
            return text
        if add_ellipsis:
            return text[:length-3] + '...'
        return text[:length]

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
    buildCronListPrompt,
    CRON_LIST_DESCRIPTION,
    CRON_LIST_TOOL_NAME,
    isDurableCronEnabled,
    isKairosCronEnabled,
)


# ============================================================
# Schema Definitions
# ============================================================

INPUT_SCHEMA = {
    'type': 'object',
    'properties': {},
}

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'jobs': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string'},
                    'cron': {'type': 'string'},
                    'humanSchedule': {'type': 'string'},
                    'prompt': {'type': 'string'},
                    'recurring': {'type': 'boolean'},
                    'durable': {'type': 'boolean'},
                },
            },
        },
    },
}


@dataclass
class CronJobInfo:
    """Info about a cron job."""
    id: str
    cron: str
    humanSchedule: str
    prompt: str
    recurring: bool = False
    durable: bool = False


@dataclass
class CronListOutput:
    """Output type for CronListTool."""
    jobs: List[CronJobInfo] = field(default_factory=list)


async def _call_cron_list(
    input_data: Dict[str, Any],
    context: Any,
) -> Dict[str, Any]:
    """
    Call the CronListTool.
    
    Lists all scheduled cron tasks.
    """
    # Get all tasks
    all_tasks = await listAllCronTasks()
    
    # Teammates only see their own crons; team lead (no ctx) sees all
    ctx = getTeammateContext()
    if ctx:
        tasks = [t for t in all_tasks if t.get('agentId') == ctx.agentId]
    else:
        tasks = all_tasks
    
    # Map to job info
    jobs = []
    for t in tasks:
        job = {
            'id': t.get('id', ''),
            'cron': t.get('cron', ''),
            'humanSchedule': cronToHuman(t.get('cron', '')),
            'prompt': t.get('prompt', ''),
        }
        
        # Only include optional fields if they differ from defaults
        if t.get('recurring'):
            job['recurring'] = True
        if t.get('durable') is False:
            job['durable'] = False
        
        jobs.append(job)
    
    return {'data': {'jobs': jobs}}


def _map_tool_result(output: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """
    Map tool result to tool result block param.
    
    Formats the job list for display.
    """
    jobs = output.get('jobs', [])
    
    if not jobs:
        content = 'No scheduled jobs.'
    else:
        lines = []
        for j in jobs:
            recurring_marker = ' (recurring)' if j.get('recurring') else ' (one-shot)'
            durable_marker = ' [session-only]' if j.get('durable') is False else ''
            prompt_preview = truncate(j.get('prompt', ''), 80, True)
            line = f"{j.get('id')} — {j.get('humanSchedule')}{recurring_marker}{durable_marker}: {prompt_preview}"
            lines.append(line)
        content = '\n'.join(lines)
    
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': content,
    }


# ============================================================
# Tool Definition
# ============================================================

CronListTool = buildTool(
    name=CRON_LIST_TOOL_NAME,
    searchHint='list active cron jobs',
    maxResultSizeChars=100_000,
    shouldDefer=True,
    inputSchema=INPUT_SCHEMA,
    outputSchema=OUTPUT_SCHEMA,
    isEnabled=lambda: isKairosCronEnabled(),
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda: True,
    description=lambda: CRON_LIST_DESCRIPTION,
    prompt=lambda: buildCronListPrompt(isDurableCronEnabled()),
    call=_call_cron_list,
    mapToolResultToToolResultBlockParam=_map_tool_result,
    renderToolUseMessage=renderListToolUseMessage,
    renderToolResultMessage=renderListResultMessage,
)
