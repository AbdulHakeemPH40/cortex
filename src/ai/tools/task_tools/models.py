"""
Task Management Models for Claude-Style Agentic Tools

Defines Task dataclass and status enums for task_create, task_get, 
task_list, task_update, and task_stop tools.

Mirrors Claude CLI task system for async agent coordination.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


class TaskStatus(Enum):
    """Task lifecycle states."""
    PENDING = "pending"       # Created but not started
    RUNNING = "running"       # Currently executing
    COMPLETED = "completed"   # Finished successfully
    FAILED = "failed"         # Error during execution
    CANCELLED = "cancelled"   # Stopped by user/system


@dataclass
class Task:
    """
    Task entity for Claude CLI-style task management.
    
    From Claude CLI constants/tools.ts - Task system for async agents.
    
    Attributes:
        id: Unique task identifier (task_<timestamp>)
        description: Human-readable task description
        status: Current task state
        agent_id: ID of agent executing this task (if assigned)
        parent_task_id: For sub-tasks (hierarchical tasks)
        created_at: Task creation timestamp
        updated_at: Last update timestamp
        completed_at: Completion timestamp (if finished)
        result: Task output/result (if completed)
        error_message: Error details (if failed)
        tool_calls: List of tools used during execution
        metadata: Additional task metadata
    """
    id: str
    description: str
    status: TaskStatus
    agent_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for serialization."""
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "agent_id": self.agent_id,
            "parent_task_id": self.parent_task_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error_message": self.error_message,
            "tool_calls": self.tool_calls,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create task from dictionary."""
        return cls(
            id=data["id"],
            description=data["description"],
            status=TaskStatus(data["status"]),
            agent_id=data.get("agent_id"),
            parent_task_id=data.get("parent_task_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            result=data.get("result"),
            error_message=data.get("error_message"),
            tool_calls=data.get("tool_calls", []),
            metadata=data.get("metadata", {})
        )
    
    def update_status(self, status: TaskStatus):
        """Update task status and timestamp."""
        self.status = status
        self.updated_at = datetime.now()
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.completed_at = datetime.now()


class TaskManager:
    """
    In-memory task storage and management.
    
    For production, this should be backed by database (see CortexDatabase).
    """
    
    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._callbacks: List[callable] = []
    
    def create_task(
        self,
        description: str,
        parent_task_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Task:
        """
        Create a new pending task.
        
        Args:
            description: Task description
            parent_task_id: Optional parent task ID
            metadata: Optional task metadata
            
        Returns:
            Created Task instance
        """
        task_id = f"task_{datetime.now().timestamp():.6f}"
        
        task = Task(
            id=task_id,
            description=description,
            status=TaskStatus.PENDING,
            parent_task_id=parent_task_id,
            metadata=metadata or {}
        )
        
        self._tasks[task_id] = task
        self._notify_change("created", task)
        
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self._tasks.get(task_id)
    
    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        agent_id: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> List[Task]:
        """
        List tasks with optional filtering.
        
        Args:
            status: Filter by status
            agent_id: Filter by assigned agent
            parent_task_id: Filter by parent task
            
        Returns:
            List of matching tasks
        """
        tasks = list(self._tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        if agent_id:
            tasks = [t for t in tasks if t.agent_id == agent_id]
        if parent_task_id is not None:
            tasks = [t for t in tasks if t.parent_task_id == parent_task_id]
        
        # Sort by creation time (newest first)
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        
        return tasks
    
    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        result: Optional[str] = None,
        error_message: Optional[str] = None,
        agent_id: Optional[str] = None
    ) -> Optional[Task]:
        """
        Update task fields.
        
        Args:
            task_id: Task to update
            status: New status
            result: Task result
            error_message: Error message
            agent_id: Agent assignment
            
        Returns:
            Updated task or None if not found
        """
        task = self._tasks.get(task_id)
        if not task:
            return None
        
        if status:
            task.update_status(status)
        if result is not None:
            task.result = result
        if error_message is not None:
            task.error_message = error_message
        if agent_id is not None:
            task.agent_id = agent_id
        
        task.updated_at = datetime.now()
        self._notify_change("updated", task)
        
        return task
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running or pending task.
        
        Args:
            task_id: Task to cancel
            
        Returns:
            True if cancelled, False if not found or already finished
        """
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        
        task.update_status(TaskStatus.CANCELLED)
        self._notify_change("cancelled", task)
        
        return True
    
    def delete_task(self, task_id: str) -> bool:
        """Delete task from storage."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False
    
    def register_callback(self, callback: callable):
        """Register callback for task changes."""
        self._callbacks.append(callback)
    
    def _notify_change(self, event: str, task: Task):
        """Notify all registered callbacks of task change."""
        for callback in self._callbacks:
            try:
                callback(event, task)
            except Exception:
                pass  # Don't let callbacks break task management


# Global task manager singleton
_global_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get or create global task manager."""
    global _global_task_manager
    if _global_task_manager is None:
        _global_task_manager = TaskManager()
    return _global_task_manager
