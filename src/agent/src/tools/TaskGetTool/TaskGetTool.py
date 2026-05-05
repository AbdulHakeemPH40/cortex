"""
Python conversion of TaskGetTool/TaskGetTool.ts

Task retrieval tool for AI agents with dependency tracking.
- Retrieve tasks by ID
- Track task dependencies (blocks/blockedBy)
- Feature flag gating for Todo v2
"""

from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass

# ============================================================================
# Defensive Imports
# ============================================================================

try:
    from utils.tasks import get_task, get_task_list_id, is_todo_v2_enabled
except ImportError:
    async def get_task(task_list_id: str, task_id: str):
        """Stub - implement actual task retrieval."""
        return None
    
    def get_task_list_id() -> str:
        """Stub - implement actual task list ID retrieval."""
        return 'default'
    
    def is_todo_v2_enabled() -> bool:
        """Stub - implement actual feature flag check."""
        return True

try:
    from constants import TASK_GET_TOOL_NAME
    from prompt import DESCRIPTION, PROMPT
except ImportError:
    TASK_GET_TOOL_NAME = 'TaskGet'
    DESCRIPTION = 'Get a task by ID from the task list'
    PROMPT = 'Use this tool to retrieve a task by its ID.'


# ============================================================================
# Type Definitions
# ============================================================================

@dataclass
class Task:
    """Task data structure."""
    id: str
    subject: str
    description: str
    status: str  # 'pending', 'in_progress', 'completed'
    blocks: list
    blockedBy: list


@dataclass
class ToolResult:
    """Result from tool execution."""
    data: Dict[str, Any]


@dataclass
class ToolDef:
    """Tool definition structure."""
    name: str
    description: str
    prompt: str
    search_hint: str
    max_result_size_chars: int
    is_enabled: Callable[[], bool]
    is_concurrency_safe: Callable[[], bool]
    is_read_only: Callable[[], bool]
    should_defer: bool
    user_facing_name: str
    to_auto_classifier_input: Callable[[Dict[str, Any]], str]
    render_tool_use_message: Callable[[], Optional[str]]
    call: Callable[..., Any]
    map_tool_result_to_block_param: Callable[..., Dict[str, Any]]


# ============================================================================
# Input/Output Schemas
# ============================================================================

def get_input_schema() -> Dict[str, Any]:
    """
    Get input schema for TaskGetTool.
    Requires taskId string.
    """
    return {
        'type': 'object',
        'properties': {
            'taskId': {
                'type': 'string',
                'description': 'The ID of the task to retrieve',
            },
        },
        'required': ['taskId'],
        'additionalProperties': False,
    }


def get_output_schema() -> Dict[str, Any]:
    """
    Get output schema for TaskGetTool.
    Returns task object or null.
    """
    return {
        'type': 'object',
        'properties': {
            'task': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string'},
                    'subject': {'type': 'string'},
                    'description': {'type': 'string'},
                    'status': {
                        'type': 'string',
                        'enum': ['pending', 'in_progress', 'completed', 'failed', 'cancelled'],
                    },
                    'blocks': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                    'blockedBy': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                },
                'nullable': True,
            },
        },
    }


# ============================================================================
# Helper Functions
# ============================================================================

def to_auto_classifier_input(input_data: Dict[str, Any]) -> str:
    """Convert input to auto-classifier format."""
    return input_data.get('taskId', '')


def render_tool_use_message() -> Optional[str]:
    """Render tool use message (minimal for this tool)."""
    return None


def map_tool_result_to_block_param(content: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """
    Map tool result to block parameter format.
    Formats task details with dependency information.
    """
    task = content.get('task')
    
    if not task:
        return {
            'tool_use_id': tool_use_id,
            'type': 'tool_result',
            'content': 'Task not found',
        }
    
    lines = [
        f"Task #{task['id']}: {task['subject']}",
        f"Status: {task['status']}",
        f"Description: {task['description']}",
    ]
    
    blocked_by = task.get('blockedBy', [])
    if blocked_by:
        lines.append(f"Blocked by: {', '.join(f'#{id}' for id in blocked_by)}")
    
    blocks = task.get('blocks', [])
    if blocks:
        lines.append(f"Blocks: {', '.join(f'#{id}' for id in blocks)}")
    
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': '\n'.join(lines),
    }


# ============================================================================
# Tool Call Implementation
# ============================================================================

async def call(input_data: Dict[str, Any]) -> ToolResult:
    """
    Retrieve a task by ID.
    
    Returns task details including dependencies.
    """
    task_id = input_data.get('taskId')
    task_list_id = get_task_list_id()
    
    task = await get_task(task_list_id, task_id)
    
    if not task:
        return ToolResult(data={'task': None})
    
    return ToolResult(data={
        'task': {
            'id': task.id,
            'subject': task.subject,
            'description': task.description,
            'status': task.status,
            'blocks': task.blocks,
            'blockedBy': task.blockedBy,
        },
    })


# ============================================================================
# Tool Definition
# ============================================================================

TaskGetTool = ToolDef(
    name=TASK_GET_TOOL_NAME,
    description=DESCRIPTION,
    prompt=PROMPT,
    search_hint='retrieve a task by ID',
    max_result_size_chars=100_000,
    is_enabled=is_todo_v2_enabled,
    is_concurrency_safe=lambda: True,
    is_read_only=lambda: True,
    should_defer=True,
    user_facing_name='TaskGet',
    to_auto_classifier_input=to_auto_classifier_input,
    render_tool_use_message=render_tool_use_message,
    call=call,
    map_tool_result_to_block_param=map_tool_result_to_block_param,
)


# ============================================================================
# Convenience Functions
# ============================================================================

def get_tool() -> ToolDef:
    """Get the TaskGetTool definition."""
    return TaskGetTool


def is_enabled() -> bool:
    """Check if TaskGetTool is enabled."""
    return is_todo_v2_enabled()
