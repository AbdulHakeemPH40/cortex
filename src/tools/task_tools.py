"""
Task Management Tools - Complete task lifecycle for Cortex IDE

This module provides comprehensive task management capabilities:
- TaskCreateTool: Create new tasks with metadata
- TaskGetTool: Retrieve task details by ID
- TaskListTool: List all tasks with filtering
- TaskUpdateTool: Update task status, description, etc.
- TaskStopTool: Cancel/abort running tasks

Key Features:
- Task creation with subject, description, and metadata
- Status tracking (pending, in_progress, completed, failed, cancelled)
- Task dependencies (blocks/blockedBy)
- Active form display for spinners
- Metadata attachment for arbitrary data
- Auto-expansion of task UI on creation

Note: Simplified conversion focusing on core task management logic.
Terminal-specific UI rendering removed.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
import logging
import time
import uuid

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Possible states for a task."""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass
class Task:
    """Represents a task in the task management system."""
    id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    active_form: Optional[str] = None  # Present continuous for spinner (e.g., "Running tests")
    owner: Optional[str] = None  # Agent name who owns this task
    blocks: List[str] = field(default_factory=list)  # Task IDs this task blocks
    blocked_by: List[str] = field(default_factory=list)  # Task IDs blocking this task
    metadata: Dict[str, Any] = field(default_factory=dict)  # Arbitrary metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


@dataclass
class TaskCreateInput:
    """Input schema for TaskCreate tool."""
    subject: str  # Brief title
    description: str  # What needs to be done
    active_form: Optional[str] = None  # Present continuous for spinner
    metadata: Optional[Dict[str, Any]] = None  # Arbitrary metadata


@dataclass
class TaskCreateOutput:
    """Output schema for TaskCreate tool."""
    task_id: str
    subject: str


@dataclass
class TaskGetInput:
    """Input schema for TaskGet tool."""
    id: str  # Task ID to retrieve


@dataclass
class TaskGetOutput:
    """Output schema for TaskGet tool."""
    task: Task


@dataclass
class TaskListOutput:
    """Output schema for TaskList tool."""
    tasks: List[Task]
    count: int


@dataclass
class TaskUpdateInput:
    """Input schema for TaskUpdate tool."""
    id: str
    subject: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    active_form: Optional[str] = None
    blocks: Optional[List[str]] = None
    blocked_by: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class TaskUpdateOutput:
    """Output schema for TaskUpdate tool."""
    task: Task
    updated_fields: List[str]


@dataclass
class TaskStopInput:
    """Input schema for TaskStop tool."""
    id: str  # Task ID to stop
    reason: Optional[str] = None  # Optional reason for stopping


@dataclass
class TaskStopOutput:
    """Output schema for TaskStop tool."""
    success: bool
    message: str


# In-memory task store (will integrate with proper persistence)
_task_store: Dict[str, Task] = {}


async def create_task(
    input_data: TaskCreateInput,
    owner: Optional[str] = None
) -> TaskCreateOutput:
    """
    Create a new task in the task list.
    
    Args:
        input_data: Task creation input
        owner: Optional owner agent name
        
    Returns:
        TaskCreateOutput with task ID and subject
        
    Raises:
        ValueError: If subject is empty
    """
    if not input_data.subject.strip():
        raise ValueError("Task subject cannot be empty")
    
    # Generate unique task ID
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    
    # Create task object
    task = Task(
        id=task_id,
        subject=input_data.subject.strip(),
        description=input_data.description,
        active_form=input_data.active_form,
        owner=owner,
        metadata=input_data.metadata or {},
        status=TaskStatus.PENDING
    )
    
    # Store task
    _task_store[task_id] = task
    
    logger.info(f"Created task {task_id}: {task.subject}")
    
    # TODO: Execute task-created hooks when hook system is integrated
    # await execute_task_created_hooks(task_id, task.subject, task.description, owner)
    
    return TaskCreateOutput(
        task_id=task_id,
        subject=task.subject
    )


async def get_task(input_data: TaskGetInput) -> TaskGetOutput:
    """
    Retrieve a task by ID.
    
    Args:
        input_data: Task ID to retrieve
        
    Returns:
        TaskGetOutput with full task details
        
    Raises:
        ValueError: If task not found
    """
    if input_data.id not in _task_store:
        raise ValueError(f"Task {input_data.id} not found")
    
    task = _task_store[input_data.id]
    
    return TaskGetOutput(task=task)


async def list_tasks(
    status_filter: Optional[TaskStatus] = None,
    owner_filter: Optional[str] = None
) -> TaskListOutput:
    """
    List all tasks with optional filtering.
    
    Args:
        status_filter: Only return tasks with this status
        owner_filter: Only return tasks owned by this agent
        
    Returns:
        TaskListOutput with task list and count
    """
    tasks = list(_task_store.values())
    
    # Apply filters
    if status_filter:
        tasks = [t for t in tasks if t.status == status_filter]
    
    if owner_filter:
        tasks = [t for t in tasks if t.owner == owner_filter]
    
    return TaskListOutput(
        tasks=tasks,
        count=len(tasks)
    )


async def update_task(input_data: TaskUpdateInput) -> TaskUpdateOutput:
    """
    Update task fields.
    
    Args:
        input_data: Task ID and fields to update
        
    Returns:
        TaskUpdateOutput with updated task and list of changed fields
        
    Raises:
        ValueError: If task not found
    """
    if input_data.id not in _task_store:
        raise ValueError(f"Task {input_data.id} not found")
    
    task = _task_store[input_data.id]
    updated_fields = []
    
    # Update provided fields
    if input_data.subject is not None:
        task.subject = input_data.subject
        updated_fields.append('subject')
    
    if input_data.description is not None:
        task.description = input_data.description
        updated_fields.append('description')
    
    if input_data.status is not None:
        old_status = task.status
        task.status = input_data.status
        updated_fields.append('status')
        
        # Set completion timestamp if transitioning to terminal state
        if input_data.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            task.completed_at = time.time()
            logger.info(f"Task {task.id} transitioned from {old_status.value} to {input_data.status.value}")
    
    if input_data.active_form is not None:
        task.active_form = input_data.active_form
        updated_fields.append('active_form')
    
    if input_data.blocks is not None:
        task.blocks = input_data.blocks
        updated_fields.append('blocks')
    
    if input_data.blocked_by is not None:
        task.blocked_by = input_data.blocked_by
        updated_fields.append('blocked_by')
    
    if input_data.metadata is not None:
        task.metadata.update(input_data.metadata)
        updated_fields.append('metadata')
    
    # Update timestamp
    task.updated_at = time.time()
    
    logger.info(f"Updated task {task.id}: {', '.join(updated_fields)}")
    
    return TaskUpdateOutput(
        task=task,
        updated_fields=updated_fields
    )


async def stop_task(input_data: TaskStopInput) -> TaskStopOutput:
    """
    Stop/cancel a running or pending task.
    
    Args:
        input_data: Task ID and optional reason
        
    Returns:
        TaskStopOutput with result
    """
    if input_data.id not in _task_store:
        return TaskStopOutput(
            success=False,
            message=f"Task {input_data.id} not found"
        )
    
    task = _task_store[input_data.id]
    
    # Check if task can be stopped
    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
        return TaskStopOutput(
            success=False,
            message=f"Task {input_data.id} is already {task.status.value}"
        )
    
    # Update status to cancelled
    old_status = task.status
    task.status = TaskStatus.CANCELLED
    task.completed_at = time.time()
    task.updated_at = time.time()
    
    reason_msg = f" Reason: {input_data.reason}" if input_data.reason else ""
    
    logger.info(f"Stopped task {task.id} (was {old_status.value}){reason_msg}")
    
    return TaskStopOutput(
        success=True,
        message=f"Task {task.id} cancelled (was {old_status.value}){reason_msg}"
    )


def get_task_create_prompt() -> str:
    """Generate system prompt for TaskCreate tool."""
    return """
# TaskCreate - Create Tasks

Create a new task to track work that needs to be done.

## When to Use
- Breaking down complex work into manageable pieces
- Tracking multi-step processes
- Creating todo lists for yourself or teammates
- Organizing work that spans multiple turns

## Parameters
- **subject**: Brief title (5-10 words)
- **description**: Detailed explanation of what needs to be done
- **active_form**: Present continuous phrase for progress spinner (e.g., "Running tests", "Analyzing code")
- **metadata**: Optional key-value pairs for additional context

## Examples
```json
{"subject": "Fix authentication bug", "description": "Users can't login with special characters in password", "activeForm": "Fixing auth bug"}
{"subject": "Write unit tests", "description": "Add tests for payment processing module", "activeForm": "Writing tests", "metadata": {"module": "payments", "priority": "high"}}
```

Tasks start with status "pending". Use TaskUpdate to change status as work progresses.
""".strip()


def get_task_get_prompt() -> str:
    """Generate system prompt for TaskGet tool."""
    return """
# TaskGet - Retrieve Task Details

Get detailed information about a specific task by its ID.

## When to Use
- User asks about a specific task
- Need to check task status before updating
- Retrieving task metadata or description

Provide the task ID (e.g., "task_abc12345").
""".strip()


def get_task_list_prompt() -> str:
    """Generate system prompt for TaskList tool."""
    return """
# TaskList - List All Tasks

View all current tasks with their statuses.

## When to Use
- User asks "what tasks do I have?"
- Show progress overview
- Find task IDs for updates
- Review pending work

Returns all tasks with ID, subject, status, and owner.
""".strip()


def get_task_update_prompt() -> str:
    """Generate system prompt for TaskUpdate tool."""
    return """
# TaskUpdate - Update Task Status

Update any field of an existing task.

## Common Updates
- Change status: pending → in_progress → completed
- Update description as requirements clarify
- Modify active_form for better progress display
- Add metadata as more context becomes available

## Status Flow
pending → in_progress → completed/failed/cancelled

Only update fields that have actually changed. Don't send unchanged fields.
""".strip()


def get_task_stop_prompt() -> str:
    """Generate system prompt for TaskStop tool."""
    return """
# TaskStop - Cancel Tasks

Stop/cancel a task that is pending or in progress.

## When to Use
- User says "cancel that task"
- Task is no longer needed
- Work has been abandoned
- User changes their mind

Provide task ID and optional reason for cancellation.
Cannot stop tasks that are already completed/failed/cancelled.
""".strip()


# Export public API
__all__ = [
    'Task',
    'TaskStatus',
    'TaskCreateInput',
    'TaskCreateOutput',
    'TaskGetInput',
    'TaskGetOutput',
    'TaskListOutput',
    'TaskUpdateInput',
    'TaskUpdateOutput',
    'TaskStopInput',
    'TaskStopOutput',
    'create_task',
    'get_task',
    'list_tasks',
    'update_task',
    'stop_task',
    'get_task_create_prompt',
    'get_task_get_prompt',
    'get_task_list_prompt',
    'get_task_update_prompt',
    'get_task_stop_prompt',
]
