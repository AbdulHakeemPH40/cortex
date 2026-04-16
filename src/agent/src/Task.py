# ------------------------------------------------------------
# Task.py
# Python conversion of Task.ts (lines 1-126)
# 
# Task type definitions and management utilities including:
# - Task type enumeration (local_bash, local_agent, remote_agent, etc.)
# - Task status tracking (pending, running, completed, failed, killed)
# - Terminal state detection for cleanup and message injection guards
# - Secure task ID generation with type-specific prefixes
# - Task state base creation with output file paths
# - Task handle and context definitions
# ------------------------------------------------------------

import os
import secrets
from typing import Any, Callable, Dict, Optional


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from .state.AppState import AppState
except ImportError:
    AppState = Dict[str, Any]

try:
    from .agent_types.ids import AgentId
except ImportError:
    AgentId = str

try:
    from .utils.task.disk_output import get_task_output_path
except ImportError:
    def get_task_output_path(task_id: str) -> str:
        return f"/tmp/tasks/{task_id}.log"


# ============================================================
# TYPE DEFINITIONS
# ============================================================

TaskType = str
"""
Task type enumeration:
- 'local_bash': Local shell command execution
- 'local_agent': Local agent subprocess
- 'remote_agent': Remote agent connection
- 'in_process_teammate': In-process teammate task
- 'local_workflow': Local workflow orchestration
- 'monitor_mcp': MCP server monitoring
- 'dream': Dream/ideation task
"""

TaskStatus = str
"""
Task status enumeration:
- 'pending': Task created but not started
- 'running': Task currently executing
- 'completed': Task finished successfully
- 'failed': Task failed with error
- 'killed': Task was terminated
"""

TaskHandle = Dict[str, Any]
"""
Task handle returned when spawning a task:
- taskId: Unique task identifier
- cleanup: Optional cleanup function
"""

SetAppState = Callable[[Callable[[AppState], AppState]], None]
"""Function to update app state immutably."""

TaskContext = Dict[str, Any]
"""
Task execution context:
- abortController: Abort controller for cancellation
- getAppState: Function to get current app state
- setAppState: Function to update app state
"""

TaskStateBase = Dict[str, Any]
"""
Base task state shared by all task types:
- id: Unique task identifier
- type: Task type
- status: Current task status
- description: Human-readable description
- toolUseId: Associated tool use ID (optional)
- startTime: Task start timestamp (ms)
- endTime: Task end timestamp (ms, optional)
- totalPausedMs: Total paused duration (ms, optional)
- outputFile: Path to task output file
- outputOffset: Current read offset in output file
- notified: Whether completion notification was sent
"""

LocalShellSpawnInput = Dict[str, Any]
"""
Input for spawning local shell tasks:
- command: Shell command to execute
- description: Task description
- timeout: Execution timeout in ms (optional)
- toolUseId: Associated tool use ID (optional)
- agentId: Agent ID if spawned by agent (optional)
- kind: UI display variant ('bash' or 'monitor')
"""

Task = Dict[str, Any]
"""
Task definition with polymorphic kill method:
- name: Task name
- type: Task type
- kill: Async function to terminate task
"""


# ============================================================
# CONSTANTS
# ============================================================

# Task ID prefixes for each task type
TASK_ID_PREFIXES: Dict[TaskType, str] = {
    'local_bash': 'b',           # Keep as 'b' for backward compatibility
    'local_agent': 'a',
    'remote_agent': 'r',
    'in_process_teammate': 't',
    'local_workflow': 'w',
    'monitor_mcp': 'm',
    'dream': 'd',
}

# Case-insensitive-safe alphabet (digits + lowercase) for task IDs.
# 36^8 ≈ 2.8 trillion combinations, sufficient to resist brute-force symlink attacks.
TASK_ID_ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'


# ============================================================
# TASK STATUS UTILITIES
# ============================================================

def is_terminal_task_status(status: TaskStatus) -> bool:
    """
    Check if a task is in a terminal state and will not transition further.
    
    Used to guard against:
    - Injecting messages into dead teammates
    - Evicting finished tasks from AppState
    - Orphan-cleanup paths
    
    Args:
        status: Task status to check
    
    Returns:
        True if status is 'completed', 'failed', or 'killed'
    """
    return status in ('completed', 'failed', 'killed')


# ============================================================
# TASK ID GENERATION
# ============================================================

def get_task_id_prefix(task_type: TaskType) -> str:
    """
    Get the prefix character for a task type.
    
    Args:
        task_type: Type of task
    
    Returns:
        Single-character prefix (e.g., 'b' for local_bash)
    """
    return TASK_ID_PREFIXES.get(task_type, 'x')


def generate_task_id(task_type: TaskType) -> str:
    """
    Generate a secure, unique task ID with type-specific prefix.
    
    Format: {prefix}{8 random alphanumeric chars}
    Example: b3k9m2x7 (local_bash task)
    
    Uses cryptographically secure random bytes to prevent brute-force
    symlink attacks. 36^8 ≈ 2.8 trillion possible combinations.
    
    Args:
        task_type: Type of task (determines prefix)
    
    Returns:
        Unique task ID string
    """
    prefix = get_task_id_prefix(task_type)
    random_bytes = secrets.token_bytes(8)
    
    # Convert bytes to alphanumeric characters
    id_chars = []
    for byte in random_bytes:
        id_chars.append(TASK_ID_ALPHABET[byte % len(TASK_ID_ALPHABET)])
    
    return prefix + ''.join(id_chars)


# ============================================================
# TASK STATE CREATION
# ============================================================

def create_task_state_base(
    task_id: str,
    task_type: TaskType,
    description: str,
    tool_use_id: Optional[str] = None,
) -> TaskStateBase:
    """
    Create a new task state base object.
    
    Initializes a task with pending status, current timestamp, and
    output file path. Used as the foundation for all task state objects.
    
    Args:
        task_id: Unique task identifier
        task_type: Type of task
        description: Human-readable task description
        tool_use_id: Associated tool use ID (optional)
    
    Returns:
        TaskStateBase dictionary with initialized fields
    """
    import time
    
    return {
        'id': task_id,
        'type': task_type,
        'status': 'pending',
        'description': description,
        'toolUseId': tool_use_id,
        'startTime': int(time.time() * 1000),  # Milliseconds since epoch
        'outputFile': get_task_output_path(task_id),
        'outputOffset': 0,
        'notified': False,
    }


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    # Types (for documentation/type hints)
    "TaskType",
    "TaskStatus",
    "TaskHandle",
    "SetAppState",
    "TaskContext",
    "TaskStateBase",
    "LocalShellSpawnInput",
    "Task",
    
    # Status utilities
    "is_terminal_task_status",
    
    # ID generation
    "generate_task_id",
    "get_task_id_prefix",
    
    # State creation
    "create_task_state_base",
]
