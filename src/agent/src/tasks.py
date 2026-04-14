# ------------------------------------------------------------
# tasks.py
# Python conversion of tasks.ts (lines 1-40)
# 
# Task registry that assembles all available background tasks
# based on feature flags. Mirrors the pattern from tools.ts.
# Provides task lookup by type.
# ------------------------------------------------------------

from typing import List, Optional

try:
    from bun.bundle import feature
except ImportError:
    def feature(feature_name: str) -> bool:
        """Stub: Check if a feature flag is enabled."""
        return False

try:
    from .Task import Task, TaskType
except ImportError:
    class Task:
        """Type placeholder for Task class."""
        type = ""
    
    TaskType = str


# ============================================================
# IMPORT ALL TASKS
# ============================================================

# Core tasks (always imported)
try:
    from .tasks.DreamTask.DreamTask import DreamTask
except ImportError:
    DreamTask = None

try:
    from .tasks.LocalAgentTask.LocalAgentTask import LocalAgentTask
except ImportError:
    LocalAgentTask = None

try:
    from .tasks.LocalShellTask.LocalShellTask import LocalShellTask
except ImportError:
    LocalShellTask = None

try:
    from .tasks.RemoteAgentTask.RemoteAgentTask import RemoteAgentTask
except ImportError:
    RemoteAgentTask = None


# Conditional imports (feature-flagged)
def _get_conditional_task(module_path: str, class_name: str) -> Optional[Task]:
    """Safely import a conditional task."""
    try:
        parts = module_path.split('.')
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name, None)
    except (ImportError, AttributeError):
        return None


LocalWorkflowTask = _get_conditional_task('.tasks.LocalWorkflowTask.LocalWorkflowTask', 'LocalWorkflowTask') if feature('WORKFLOW_SCRIPTS') else None
MonitorMcpTask = _get_conditional_task('.tasks.MonitorMcpTask.MonitorMcpTask', 'MonitorMcpTask') if feature('MONITOR_TOOL') else None


# ============================================================
# TASK ASSEMBLY FUNCTIONS
# ============================================================

def get_all_tasks() -> List[Task]:
    """
    Get all tasks.
    
    Mirrors the pattern from tools.ts.
    Returns array inline to avoid circular dependency issues with top-level const.
    
    Returns:
        List of all available task instances
    """
    tasks = [
        LocalShellTask,
        LocalAgentTask,
        RemoteAgentTask,
        DreamTask,
    ]
    
    # Add conditional tasks
    if LocalWorkflowTask:
        tasks.append(LocalWorkflowTask)
    
    if MonitorMcpTask:
        tasks.append(MonitorMcpTask)
    
    # Filter out None values
    return [task for task in tasks if task is not None]


def get_task_by_type(task_type: TaskType) -> Optional[Task]:
    """
    Get a task by its type.
    
    Args:
        task_type: The task type to find
    
    Returns:
        Matching task or None if not found
    """
    for task in get_all_tasks():
        if task.type == task_type:
            return task
    return None


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "get_all_tasks",
    "get_task_by_type",
]
