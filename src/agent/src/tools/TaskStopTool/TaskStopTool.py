# ------------------------------------------------------------
# TaskStopTool.py
# Python conversion of TaskStopTool/TaskStopTool.ts
# 
# Task stopping tool for AI agents.
# Stops running background tasks by ID with validation and error handling.
# Supports backward compatibility with deprecated KillShell tool.
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from ...Tool import ToolDef, ToolResult, buildTool
    from ...tasks.stopTask import stopTask
    from .prompt import DESCRIPTION, TASK_STOP_TOOL_NAME
except ImportError:
    # Fallback stubs for type checking
    TASK_STOP_TOOL_NAME = 'TaskStop'
    DESCRIPTION = 'Stop a running background task by ID'
    
    @dataclass
    class ToolResult:
        data: Any = None
    
    def buildTool(**kwargs):
        return kwargs
    
    async def stopTask(task_id: str, context: Dict[str, Any]) -> Any:
        class StopResult:
            taskId = task_id
            taskType = 'unknown'
            command = 'unknown'
        return StopResult()


# Input schema definition
inputSchema = {
    'type': 'object',
    'properties': {
        'task_id': {
            'type': 'string',
            'description': 'The ID of the background task to stop',
        },
        'shell_id': {
            'type': 'string',
            'description': 'Deprecated: use task_id instead',
        },
    },
}

# Output schema definition
outputSchema = {
    'type': 'object',
    'properties': {
        'message': {
            'type': 'string',
            'description': 'Status message about the operation',
        },
        'task_id': {
            'type': 'string',
            'description': 'The ID of the task that was stopped',
        },
        'task_type': {
            'type': 'string',
            'description': 'The type of the task that was stopped',
        },
        'command': {
            'type': 'string',
            'description': 'The command or description of the stopped task',
        },
    },
    'required': ['message', 'task_id', 'task_type'],
}


def to_auto_classifier_input(input_data: Dict[str, Any]) -> str:
    """
    Convert input to auto-classifier format.
    
    Returns task_id or shell_id for pattern matching.
    """
    return input_data.get('task_id') or input_data.get('shell_id') or ''


async def validate_input(
    input_data: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate input before stopping task.
    
    Checks:
    - task_id or shell_id is provided
    - Task exists in app state
    - Task is currently running
    
    Returns validation result with error details if invalid.
    """
    task_id = input_data.get('task_id')
    shell_id = input_data.get('shell_id')
    
    # Support both task_id and shell_id (deprecated KillShell compat)
    task_id_to_stop = task_id or shell_id
    
    if not task_id_to_stop:
        return {
            'result': False,
            'message': 'Missing required parameter: task_id',
            'errorCode': 1,
        }
    
    get_app_state = context.get('getAppState')
    if not get_app_state:
        return {
            'result': False,
            'message': 'App state not available',
            'errorCode': 1,
        }
    
    app_state = get_app_state()
    tasks = getattr(app_state, 'tasks', None) or app_state.get('tasks', {})
    task = tasks.get(task_id_to_stop)
    
    if not task:
        return {
            'result': False,
            'message': f'No task found with ID: {task_id_to_stop}',
            'errorCode': 1,
        }
    
    task_status = getattr(task, 'status', None) or task.get('status')
    if task_status != 'running':
        return {
            'result': False,
            'message': f'Task {task_id_to_stop} is not running (status: {task_status})',
            'errorCode': 3,
        }
    
    return {'result': True}


async def call(
    input_data: Dict[str, Any],
    context: Dict[str, Any],
) -> ToolResult:
    """
    Stop a running background task.
    
    Supports both task_id and shell_id for backward compatibility
    with the deprecated KillShell tool.
    
    Returns task stop result with details about the stopped task.
    """
    task_id = input_data.get('task_id')
    shell_id = input_data.get('shell_id')
    
    # Support both task_id and shell_id (deprecated KillShell compat)
    task_id_to_stop = task_id or shell_id
    
    if not task_id_to_stop:
        raise ValueError('Missing required parameter: task_id')
    
    result = await stopTask(
        task_id_to_stop,
        {
            'getAppState': context.get('getAppState'),
            'setAppState': context.get('setAppState'),
        },
    )
    
    return ToolResult(data={
        'message': f'Successfully stopped task: {result.taskId} ({result.command})',
        'task_id': result.taskId,
        'task_type': result.taskType,
        'command': result.command,
    })


def map_tool_result_to_block_param(output: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """
    Map tool result to block parameter format.
    
    Serializes output as JSON for display.
    """
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': json.dumps(output, indent=2),
    }


def render_tool_use_message() -> Optional[str]:
    """Render message when tool is used."""
    return None


def render_tool_result_message(result: Dict[str, Any]) -> Optional[str]:
    """Render message for tool result."""
    return None


def user_facing_name() -> str:
    """
    Get user-facing name for the tool.
    
    Returns empty string for 'ant' user type, otherwise 'Stop Task'.
    """
    return '' if os.environ.get('USER_TYPE') == 'ant' else 'Stop Task'


# Tool definition
TaskStopTool = buildTool(
    name=TASK_STOP_TOOL_NAME,
    searchHint='kill a running background task',
    aliases=['KillShell'],  # Deprecated name for backward compatibility
    maxResultSizeChars=100_000,
    userFacingName=user_facing_name,
    inputSchema=lambda: inputSchema,
    outputSchema=lambda: outputSchema,
    shouldDefer=True,
    isConcurrencySafe=lambda: True,
    toAutoClassifierInput=to_auto_classifier_input,
    validateInput=validate_input,
    description=lambda: 'Stop a running background task by ID',
    prompt=lambda: DESCRIPTION,
    mapToolResultToBlockParam=map_tool_result_to_block_param,
    renderToolUseMessage=render_tool_use_message,
    renderToolResultMessage=render_tool_result_message,
    call=call,
)
