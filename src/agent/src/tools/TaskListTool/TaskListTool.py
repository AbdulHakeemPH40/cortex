# ------------------------------------------------------------
# TaskListTool.py
# Python conversion of TaskListTool/TaskListTool.ts
# 
# Full task listing tool for AI agents.
# Lists all tasks with smart dependency filtering - removes completed tasks from blockedBy arrays.
# Filters out internal/system tasks from the list.
# ------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from ...Tool import ToolDef, ToolResult, buildTool
    from ...utils.tasks import (
        getTaskListId,
        isTodoV2Enabled,
        listTasks,
    )
    from .constants import TASK_LIST_TOOL_NAME
    from .prompt import DESCRIPTION, getPrompt
except ImportError:
    # Fallback stubs for type checking
    TASK_LIST_TOOL_NAME = 'TaskList'
    DESCRIPTION = 'List all tasks in the task list'
    
    def getPrompt():
        return 'Use this tool to list all tasks in the task list.'
    
    @dataclass
    class ToolResult:
        data: Any = None
    
    def buildTool(**kwargs):
        return kwargs
    
    def getTaskListId():
        return None
    
    def isTodoV2Enabled():
        return False
    
    async def listTasks(*args, **kwargs):
        return []


@dataclass
class TaskSummary:
    """Summarized task information for AI agent display."""
    id: str
    subject: str
    status: str  # 'pending', 'in_progress', 'completed'
    owner: Optional[str] = None
    blockedBy: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.blockedBy is None:
            self.blockedBy = []


# Empty input schema - no parameters needed
inputSchema = {}

# Output schema definition (for validation/documentation)
outputSchema = {
    'type': 'object',
    'properties': {
        'tasks': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string'},
                    'subject': {'type': 'string'},
                    'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'completed']},
                    'owner': {'type': 'string'},
                    'blockedBy': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                },
                'required': ['id', 'subject', 'status', 'blockedBy'],
            },
        },
    },
    'required': ['tasks'],
}


async def call() -> ToolResult:
    """
    List all tasks in the task list.
    
    Filters out internal tasks and removes completed dependencies from blockedBy arrays.
    Returns summarized task information for AI agent consumption.
    """
    task_list_id = getTaskListId()
    
    # Get all tasks and filter out internal/system tasks
    all_tasks = await listTasks(task_list_id)
    filtered_tasks = [
        t for t in all_tasks
        if not (getattr(t, 'metadata', None) or {}).get('_internal', False)
    ]
    
    # Build a set of completed task IDs for filtering dependencies
    completed_task_ids = {
        t.id for t in filtered_tasks
        if getattr(t, 'status', None) == 'completed'
    }
    
    # Map tasks to summaries with filtered dependencies
    tasks = [
        TaskSummary(
            id=task.id,
            subject=task.subject,
            status=task.status,
            owner=getattr(task, 'owner', None),
            blockedBy=[
                dep_id for dep_id in getattr(task, 'blockedBy', [])
                if dep_id not in completed_task_ids
            ],
        )
        for task in filtered_tasks
    ]
    
    return ToolResult(data={
        'tasks': [
            {
                'id': t.id,
                'subject': t.subject,
                'status': t.status,
                'owner': t.owner,
                'blockedBy': t.blockedBy,
            }
            for t in tasks
        ]
    })


def map_tool_result_to_block_param(content: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """
    Map tool result to block parameter format.
    
    Formats task list as readable text with:
    - Task ID and subject
    - Status indicator
    - Owner information (if assigned)
    - Blocking dependencies (if any)
    """
    tasks_data = content.get('tasks', [])
    
    if not tasks_data:
        return {
            'tool_use_id': tool_use_id,
            'type': 'tool_result',
            'content': 'No tasks found',
        }
    
    lines = []
    for task in tasks_data:
        owner_str = f" ({task['owner']})" if task.get('owner') else ''
        
        blocked_by = task.get('blockedBy', [])
        blocked_str = (
            f" [blocked by {', '.join(f'#{dep_id}' for dep_id in blocked_by)}]"
            if blocked_by
            else ''
        )
        
        line = f"#{task['id']} [{task['status']}] {task['subject']}{owner_str}{blocked_str}"
        lines.append(line)
    
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': '\n'.join(lines),
    }


# Tool definition
TaskListTool = buildTool(
    name=TASK_LIST_TOOL_NAME,
    searchHint='list all tasks',
    maxResultSizeChars=100_000,
    description=lambda: DESCRIPTION,
    prompt=lambda: getPrompt(),
    inputSchema=lambda: inputSchema,
    outputSchema=lambda: outputSchema,
    userFacingName=lambda: 'TaskList',
    shouldDefer=True,
    isEnabled=lambda: isTodoV2Enabled(),
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda: True,
    renderToolUseMessage=lambda: None,
    call=call,
    mapToolResultToBlockParam=map_tool_result_to_block_param,
)
