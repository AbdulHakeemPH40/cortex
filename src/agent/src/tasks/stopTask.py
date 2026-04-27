# ------------------------------------------------------------
# stopTask.py
# Python conversion of stopTask.ts (lines 1-101)
# 
# Shared logic for stopping running tasks in multi-LLM AI agent IDE:
# - TaskStopTool: LLM-invoked tool for stopping background tasks
# - SDK stop_task: External SDK control requests
# - Task lifecycle management: Lookup, validate, kill, notify
# - Notification suppression: Reduces noise for killed shell tasks
# - SDK event emission: Notifies consumers of task termination
# ------------------------------------------------------------

import asyncio
from typing import Any, Callable, Dict, Optional


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from .state.AppState import AppState
except ImportError:
    AppState = Dict[str, Any]

try:
    from .Task import TaskStateBase, SetAppState
except ImportError:
    TaskStateBase = Dict[str, Any]
    SetAppState = Callable[[Callable[[dict], dict]], None]

try:
    from .tasks import getTaskByType
except ImportError:
    def getTaskByType(task_type: str) -> Optional[dict]:
        """Fallback task lookup - should be replaced with actual implementation."""
        return None

try:
    from .utils.sdkEventQueue import emitTaskTerminatedSdk
except ImportError:
    def emitTaskTerminatedSdk(task_id: str, status: str, metadata: dict = None) -> None:
        """Fallback SDK event emitter."""
        pass

try:
    from .LocalShellTask.guards import isLocalShellTask
except ImportError:
    def isLocalShellTask(task: Any) -> bool:
        """Fallback type guard for local shell tasks."""
        return (
            isinstance(task, dict) and
            task.get('type') == 'local_bash'
        )


# ============================================================
# EXCEPTION CLASS
# ============================================================

class StopTaskError(Exception):
    """
    Error raised when a task cannot be stopped.
    
    Attributes:
        code: Error code ('not_found', 'not_running', 'unsupported_type')
        message: Human-readable error message
    """
    
    def __init__(
        self,
        message: str,
        code: str,
    ):
        """
        Initialize StopTaskError.
        
        Args:
            message: Human-readable error message
            code: Error code ('not_found', 'not_running', 'unsupported_type')
        """
        super().__init__(message)
        self.name = 'StopTaskError'
        self.code = code


# ============================================================
# TYPE DEFINITIONS
# ============================================================

StopTaskContext = Dict[str, Any]
"""
Context for stopTask function:
- getAppState: Function to get current app state
- setAppState: Function to update app state
"""

StopTaskResult = Dict[str, Any]
"""
Result from successful task stop:
- taskId: Task ID that was stopped
- taskType: Type of task
- command: Command or description of task
"""


# ============================================================
# MAIN STOP TASK FUNCTION
# ============================================================

async def stopTask(
    task_id: str,
    context: StopTaskContext,
) -> StopTaskResult:
    """
    Look up a task by ID, validate it is running, kill it, and mark it as notified.
    
    Used by:
    - TaskStopTool: LLM-invoked tool for stopping background tasks
    - SDK stop_task: External SDK control requests
    
    Args:
        task_id: ID of task to stop
        context: Dict with getAppState and setAppState functions
    
    Returns:
        Dict with taskId, taskType, and command
    
    Raises:
        StopTaskError: When task cannot be stopped
            - 'not_found': No task with given ID
            - 'not_running': Task is not in running state
            - 'unsupported_type': Task type has no kill implementation
    """
    getAppState = context['getAppState']
    setAppState = context['setAppState']
    
    appState = getAppState()
    task = appState.get('tasks', {}).get(task_id)
    
    if not task:
        raise StopTaskError(
            f'No task found with ID: {task_id}',
            'not_found'
        )
    
    if task.get('status') != 'running':
        raise StopTaskError(
            f'Task {task_id} is not running (status: {task.get("status")})',
            'not_running'
        )
    
    taskImpl = getTaskByType(task.get('type'))
    if not taskImpl:
        raise StopTaskError(
            f'Unsupported task type: {task.get("type")}',
            'unsupported_type'
        )
    
    # Kill the task
    kill_fn = taskImpl.get('kill')
    if kill_fn:
        # Check if kill_fn is async
        if asyncio.iscoroutinefunction(kill_fn):
            await kill_fn(task_id, setAppState)
        else:
            kill_fn(task_id, setAppState)
    
    # Bash: suppress the "exit code 137" notification (noise). Agent tasks: don't
    # suppress — the AbortError catch sends a notification carrying
    # extractPartialResult(agentMessages), which is the payload not noise.
    if isLocalShellTask(task):
        suppressed = False
        
        def update_notified(prev: dict) -> dict:
            nonlocal suppressed
            prevTask = prev.get('tasks', {}).get(task_id)
            if not prevTask or prevTask.get('notified'):
                return prev
            suppressed = True
            return {
                **prev,
                'tasks': {
                    **prev.get('tasks', {}),
                    task_id: {**prevTask, 'notified': True},
                },
            }
        
        setAppState(update_notified)
        
        # Suppressing the XML notification also suppresses print.ts's parsed
        # task_notification SDK event — emit it directly so SDK consumers see
        # the task close.
        if suppressed:
            emitTaskTerminatedSdk(task_id, 'stopped', {
                'toolUseId': task.get('toolUseId'),
                'summary': task.get('description'),
            })
    
    command = task.get('command') if isLocalShellTask(task) else task.get('description')
    
    return {
        'taskId': task_id,
        'taskType': task.get('type'),
        'command': command,
    }


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "StopTaskError",
    "stopTask",
]
