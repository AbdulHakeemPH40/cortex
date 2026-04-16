"""
Task management utilities for Cortex IDE.

Provides task creation, updating, and management for agent workflows.
Converted from TypeScript tasks.ts module.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from functools import lru_cache


class TaskStatus(Enum):
    """Task status types."""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'


@dataclass
class Task:
    """A task in the task list."""
    id: str
    subject: str
    description: str = ""
    active_form: Optional[str] = None  # Present continuous form for spinner
    owner: Optional[str] = None  # Agent ID
    status: TaskStatus = TaskStatus.PENDING
    blocks: List[str] = field(default_factory=list)  # Task IDs this task blocks
    blocked_by: List[str] = field(default_factory=list)  # Task IDs that block this task
    metadata: Dict[str, Any] = field(default_factory=dict)


# High water mark file name - stores the maximum task ID ever assigned
HIGH_WATER_MARK_FILE = '.highwatermark'

# Listeners for task list updates
_task_update_listeners: List[Callable[[], None]] = []

# Leader team name for task list resolution
_leader_team_name: Optional[str] = None


def is_todo_v2_enabled() -> bool:
    """
    Check if Todo V2 is enabled.
    
    Currently gated by environment variable.
    """
    from .env_utils import is_env_truthy
    return is_env_truthy(os.environ.get('CLAUDE_CODE_TODO_V2')) or \
           is_env_truthy(os.environ.get('CLAUDE_CODE_ENABLE_TASKS'))


def set_leader_team_name(team_name: str) -> None:
    """
    Sets the leader's team name for task list resolution.
    Called by TeamCreateTool when a team is created.
    """
    global _leader_team_name
    if _leader_team_name == team_name:
        return
    _leader_team_name = team_name
    notify_tasks_updated()


def clear_leader_team_name() -> None:
    """Clears the leader's team name. Called when a team is deleted."""
    global _leader_team_name
    if _leader_team_name is None:
        return
    _leader_team_name = None
    notify_tasks_updated()


def on_tasks_updated(callback: Callable[[], None]) -> Callable[[], None]:
    """
    Register a listener to be called when tasks are updated.
    Returns an unsubscribe function.
    """
    _task_update_listeners.append(callback)
    
    def unsubscribe():
        if callback in _task_update_listeners:
            _task_update_listeners.remove(callback)
    
    return unsubscribe


def notify_tasks_updated() -> None:
    """
    Notify listeners that tasks have been updated.
    Called internally after createTask, updateTask, etc.
    """
    for callback in _task_update_listeners:
        try:
            callback()
        except Exception:
            pass  # Ignore listener errors


def get_tasks_dir(task_list_id: str) -> Path:
    """Get the directory for storing tasks."""
    home = Path.home()
    config_dir = home / '.cortex' / 'tasks' / task_list_id
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_task_list_id(session_id: Optional[str] = None) -> str:
    """Get the task list ID for the current session."""
    global _leader_team_name
    
    if _leader_team_name:
        return _leader_team_name
    
    if session_id:
        return session_id
    
    # Default to 'default' if no session
    return 'default'


def _get_high_water_mark_path(task_list_id: str) -> Path:
    """Get the path to the high water mark file."""
    return get_tasks_dir(task_list_id) / HIGH_WATER_MARK_FILE


async def _read_high_water_mark(task_list_id: str) -> int:
    """Read the high water mark for task IDs."""
    path = _get_high_water_mark_path(task_list_id)
    try:
        content = await asyncio.to_thread(path.read_text)
        value = int(content.strip())
        return value if value > 0 else 0
    except (FileNotFoundError, ValueError):
        return 0


async def _write_high_water_mark(task_list_id: str, value: int) -> None:
    """Write the high water mark for task IDs."""
    path = _get_high_water_mark_path(task_list_id)
    await asyncio.to_thread(path.write_text, str(value))


async def reset_task_list(task_list_id: str) -> None:
    """
    Resets the task list for a new swarm - clears any existing tasks.
    Writes a high water mark file to prevent ID reuse after reset.
    """
    tasks_dir = get_tasks_dir(task_list_id)
    
    # Delete all task files
    try:
        for task_file in tasks_dir.glob('*.json'):
            if task_file.name != HIGH_WATER_MARK_FILE:
                await asyncio.to_thread(task_file.unlink)
    except Exception:
        pass
    
    # Reset high water mark
    await _write_high_water_mark(task_list_id, 0)
    notify_tasks_updated()


async def generate_task_id(task_list_id: str) -> str:
    """Generate a unique task ID using an incrementing counter."""
    high_water_mark = await _read_high_water_mark(task_list_id)
    new_id = high_water_mark + 1
    await _write_high_water_mark(task_list_id, new_id)
    return str(new_id)


def _task_to_dict(task: Task) -> Dict[str, Any]:
    """Convert a Task to a dictionary for serialization."""
    return {
        'id': task.id,
        'subject': task.subject,
        'description': task.description,
        'activeForm': task.active_form,
        'owner': task.owner,
        'status': task.status.value,
        'blocks': task.blocks,
        'blockedBy': task.blocked_by,
        'metadata': task.metadata
    }


def _dict_to_task(data: Dict[str, Any]) -> Task:
    """Convert a dictionary to a Task object."""
    return Task(
        id=data['id'],
        subject=data['subject'],
        description=data.get('description', ''),
        active_form=data.get('activeForm'),
        owner=data.get('owner'),
        status=TaskStatus(data.get('status', 'pending')),
        blocks=data.get('blocks', []),
        blocked_by=data.get('blockedBy', []),
        metadata=data.get('metadata', {})
    )


async def create_task(
    task_list_id: str,
    subject: str,
    description: str = "",
    active_form: Optional[str] = None,
    owner: Optional[str] = None,
    blocks: Optional[List[str]] = None,
    blocked_by: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Task:
    """Create a new task."""
    task_id = await generate_task_id(task_list_id)
    
    task = Task(
        id=task_id,
        subject=subject,
        description=description,
        active_form=active_form or f"Working on: {subject}",
        owner=owner,
        status=TaskStatus.PENDING,
        blocks=blocks or [],
        blocked_by=blocked_by or [],
        metadata=metadata or {}
    )
    
    # Save task
    task_path = get_tasks_dir(task_list_id) / f"{task_id}.json"
    await asyncio.to_thread(
        task_path.write_text,
        json.dumps(_task_to_dict(task), indent=2)
    )
    
    notify_tasks_updated()
    return task


async def get_task(task_list_id: str, task_id: str) -> Optional[Task]:
    """Get a task by ID."""
    task_path = get_tasks_dir(task_list_id) / f"{task_id}.json"
    try:
        content = await asyncio.to_thread(task_path.read_text)
        data = json.loads(content)
        return _dict_to_task(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


async def update_task(
    task_list_id: str,
    task_id: str,
    status: Optional[TaskStatus] = None,
    subject: Optional[str] = None,
    description: Optional[str] = None,
    active_form: Optional[str] = None,
    owner: Optional[str] = None,
    blocks: Optional[List[str]] = None,
    blocked_by: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[Task]:
    """Update an existing task."""
    task = await get_task(task_list_id, task_id)
    if not task:
        return None
    
    if status is not None:
        task.status = status
    if subject is not None:
        task.subject = subject
    if description is not None:
        task.description = description
    if active_form is not None:
        task.active_form = active_form
    if owner is not None:
        task.owner = owner
    if blocks is not None:
        task.blocks = blocks
    if blocked_by is not None:
        task.blocked_by = blocked_by
    if metadata is not None:
        task.metadata = metadata
    
    # Save updated task
    task_path = get_tasks_dir(task_list_id) / f"{task_id}.json"
    await asyncio.to_thread(
        task_path.write_text,
        json.dumps(_task_to_dict(task), indent=2)
    )
    
    notify_tasks_updated()
    return task


async def delete_task(task_list_id: str, task_id: str) -> bool:
    """Delete a task by ID."""
    task_path = get_tasks_dir(task_list_id) / f"{task_id}.json"
    try:
        await asyncio.to_thread(task_path.unlink)
        notify_tasks_updated()
        return True
    except FileNotFoundError:
        return False


async def list_tasks(task_list_id: str) -> List[Task]:
    """List all tasks in a task list."""
    tasks_dir = get_tasks_dir(task_list_id)
    tasks = []
    
    try:
        for task_file in tasks_dir.glob('*.json'):
            if task_file.name == HIGH_WATER_MARK_FILE:
                continue
            try:
                content = await asyncio.to_thread(task_file.read_text)
                data = json.loads(content)
                tasks.append(_dict_to_task(data))
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception:
        pass
    
    # Sort by task ID (numeric)
    tasks.sort(key=lambda t: int(t.id) if t.id.isdigit() else 0)
    return tasks


async def get_tasks_by_status(task_list_id: str, status: TaskStatus) -> List[Task]:
    """Get all tasks with a specific status."""
    tasks = await list_tasks(task_list_id)
    return [t for t in tasks if t.status == status]


async def get_pending_tasks(task_list_id: str) -> List[Task]:
    """Get all pending tasks."""
    return await get_tasks_by_status(task_list_id, TaskStatus.PENDING)


async def get_in_progress_tasks(task_list_id: str) -> List[Task]:
    """Get all in-progress tasks."""
    return await get_tasks_by_status(task_list_id, TaskStatus.IN_PROGRESS)


async def get_completed_tasks(task_list_id: str) -> List[Task]:
    """Get all completed tasks."""
    return await get_tasks_by_status(task_list_id, TaskStatus.COMPLETED)


async def start_task(task_list_id: str, task_id: str) -> Optional[Task]:
    """Mark a task as in progress."""
    return await update_task(task_list_id, task_id, status=TaskStatus.IN_PROGRESS)


async def complete_task(task_list_id: str, task_id: str) -> Optional[Task]:
    """Mark a task as completed."""
    return await update_task(task_list_id, task_id, status=TaskStatus.COMPLETED)


async def get_blocked_tasks(task_list_id: str) -> List[Task]:
    """Get tasks that are blocked by other tasks."""
    tasks = await list_tasks(task_list_id)
    completed_ids = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
    
    blocked = []
    for task in tasks:
        if task.blocked_by:
            # Check if any blocking task is not completed
            for blocker_id in task.blocked_by:
                if blocker_id not in completed_ids:
                    blocked.append(task)
                    break
    
    return blocked


async def get_ready_tasks(task_list_id: str) -> List[Task]:
    """Get tasks that are ready to be worked on (not blocked and not completed)."""
    tasks = await list_tasks(task_list_id)
    completed_ids = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
    
    ready = []
    for task in tasks:
        if task.status == TaskStatus.COMPLETED:
            continue
        
        if task.blocked_by:
            # Check if all blocking tasks are completed
            all_blockers_done = all(
                blocker_id in completed_ids
                for blocker_id in task.blocked_by
            )
            if not all_blockers_done:
                continue
        
        ready.append(task)
    
    return ready


__all__ = [
    'TaskStatus',
    'Task',
    'is_todo_v2_enabled',
    'set_leader_team_name',
    'clear_leader_team_name',
    'on_tasks_updated',
    'notify_tasks_updated',
    'get_tasks_dir',
    'get_task_list_id',
    'reset_task_list',
    'create_task',
    'get_task',
    'update_task',
    'delete_task',
    'list_tasks',
    'get_tasks_by_status',
    'get_pending_tasks',
    'get_in_progress_tasks',
    'get_completed_tasks',
    'start_task',
    'complete_task',
    'get_blocked_tasks',
    'get_ready_tasks',
]
