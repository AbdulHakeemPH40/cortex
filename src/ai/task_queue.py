"""
Task Queue System for Cortex AI Agent IDE
Manages user prompt execution with queuing, progress tracking, and state management
"""

import uuid
import time
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from src.utils.logger import get_logger

log = get_logger("task_queue")


class TaskStatus(Enum):
    """Task execution states"""
    PENDING = auto()
    ANALYZING = auto()
    PLANNING = auto()
    EXECUTING = auto()
    VERIFYING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    PAUSED = auto()


class TaskPriority(Enum):
    """Task priority levels"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class TaskStep:
    """Individual step within a task"""
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Any = None
    error: Optional[str] = None
    requires_confirmation: bool = False
    confirmed: bool = False


@dataclass
class Task:
    """Represents a user request/task"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_prompt: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    steps: List[TaskStep] = field(default_factory=list)
    current_step_index: int = 0
    context: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[str] = None
    project_context: Optional[str] = None
    
    @property
    def progress_percentage(self) -> int:
        """Calculate completion percentage"""
        if not self.steps:
            return 0
        completed = sum(1 for s in self.steps if s.status in [TaskStatus.COMPLETED, TaskStatus.FAILED])
        return int((completed / len(self.steps)) * 100)
    
    @property
    def current_step(self) -> Optional[TaskStep]:
        """Get current active step"""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None
    
    @property
    def duration_seconds(self) -> float:
        """Get task duration"""
        if self.started_at:
            end = self.completed_at or datetime.now()
            return (end - self.started_at).total_seconds()
        return 0.0


class TaskQueue(QObject):
    """
    Manages task execution with queuing, priorities, and progress tracking
    
    Signals:
        task_added: Task was added to queue
        task_started: Task execution began
        task_progress: Task progress update (task_id, step_name, percentage)
        task_completed: Task finished successfully
        task_failed: Task failed with error
        task_cancelled: Task was cancelled
        queue_updated: Queue state changed
    """
    
    # Signals
    task_added = pyqtSignal(str)  # task_id
    task_started = pyqtSignal(str)  # task_id
    task_progress = pyqtSignal(str, str, int)  # task_id, step_name, percentage
    task_step_completed = pyqtSignal(str, str, str)  # task_id, step_name, result_summary
    task_completed = pyqtSignal(str, str)  # task_id, summary
    task_failed = pyqtSignal(str, str)  # task_id, error
    task_cancelled = pyqtSignal(str)  # task_id
    queue_updated = pyqtSignal(int)  # queue_length
    current_task_changed = pyqtSignal(str)  # task_id or ""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks: Dict[str, Task] = {}
        self.queue: List[str] = []  # Ordered list of task IDs
        self.current_task_id: Optional[str] = None
        self._is_processing = False
        self._should_stop = False
        self._should_pause = False
        self._max_queue_size = 50
        self._task_history: List[str] = []  # Completed task IDs
        self._history_limit = 100
        
    def enqueue(self, prompt: str, priority: TaskPriority = TaskPriority.NORMAL, 
                context: Optional[Dict[str, Any]] = None) -> str:
        """
        Add a new task to the queue
        
        Args:
            prompt: User's request/prompt
            priority: Task priority level
            context: Additional context (project info, files, etc.)
            
        Returns:
            task_id: Unique identifier for the task
        """
        if len(self.queue) >= self._max_queue_size:
            raise QueueFullError(f"Queue is full (max {self._max_queue_size} tasks)")
        
        task = Task(
            user_prompt=prompt,
            priority=priority,
            context=context or {}
        )
        
        self.tasks[task.id] = task
        
        # Insert based on priority
        insert_index = len(self.queue)
        for i, existing_id in enumerate(self.queue):
            existing_task = self.tasks[existing_id]
            if existing_task.priority.value < priority.value:
                insert_index = i
                break
        
        self.queue.insert(insert_index, task.id)
        
        log.info(f"Task {task.id} added to queue at position {insert_index}")
        self.task_added.emit(task.id)
        self.queue_updated.emit(len(self.queue))
        
        return task.id
    
    def start_processing(self):
        """Begin processing the queue"""
        if not self._is_processing:
            self._is_processing = True
            self._process_next()
    
    def stop_current(self, graceful: bool = True) -> bool:
        """
        Stop the current task
        
        Args:
            graceful: If True, allow current step to complete
            
        Returns:
            True if stop was initiated
        """
        if not self.current_task_id:
            return False
        
        self._should_stop = True
        log.info(f"Stop requested for task {self.current_task_id} (graceful={graceful})")
        
        if not graceful:
            # Force cancel immediately
            self._cancel_current_task()
        
        return True
    
    def pause_current(self) -> bool:
        """Pause the current task (will pause after current step)"""
        if not self.current_task_id:
            return False
        
        self._should_pause = True
        task = self.tasks[self.current_task_id]
        task.status = TaskStatus.PAUSED
        log.info(f"Task {task.id} paused")
        return True
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task"""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        if task.status != TaskStatus.PAUSED:
            return False
        
        task.status = TaskStatus.EXECUTING
        self._should_pause = False
        log.info(f"Task {task_id} resumed")
        
        # Continue processing
        self._process_current_task()
        return True
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a specific task by ID"""
        if task_id not in self.tasks:
            return False
        
        if task_id == self.current_task_id:
            return self.stop_current(graceful=False)
        
        if task_id in self.queue:
            self.queue.remove(task_id)
            task = self.tasks[task_id]
            task.status = TaskStatus.CANCELLED
            self.task_cancelled.emit(task_id)
            self.queue_updated.emit(len(self.queue))
            log.info(f"Task {task_id} cancelled")
            return True
        
        return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        return self.tasks.get(task_id)
    
    def get_current_task(self) -> Optional[Task]:
        """Get currently executing task"""
        if self.current_task_id:
            return self.tasks.get(self.current_task_id)
        return None
    
    def get_queue_position(self, task_id: str) -> int:
        """Get position in queue (0 = next)"""
        try:
            return self.queue.index(task_id)
        except ValueError:
            return -1
    
    def get_all_tasks(self) -> List[Task]:
        """Get all tasks including completed"""
        return list(self.tasks.values())
    
    def get_pending_tasks(self) -> List[Task]:
        """Get tasks waiting in queue"""
        return [self.tasks[tid] for tid in self.queue if tid in self.tasks]
    
    def get_completed_tasks(self, limit: int = 10) -> List[Task]:
        """Get recently completed tasks"""
        completed = []
        for tid in reversed(self._task_history[-limit:]):
            if tid in self.tasks:
                completed.append(self.tasks[tid])
        return completed
    
    def _process_next(self):
        """Process the next task in queue"""
        if not self._is_processing:
            return
        
        # Check if we should stop
        if self._should_stop:
            self._should_stop = False
            self._cancel_current_task()
            return
        
        # Get next task
        if not self.queue:
            self._is_processing = False
            self.current_task_id = None
            self.current_task_changed.emit("")
            return
        
        self.current_task_id = self.queue.pop(0)
        task = self.tasks[self.current_task_id]
        
        task.status = TaskStatus.ANALYZING
        task.started_at = datetime.now()
        
        log.info(f"Starting task {task.id}: {task.user_prompt[:50]}...")
        self.task_started.emit(task.id)
        self.current_task_changed.emit(task.id)
        self.queue_updated.emit(len(self.queue))
        
        # Begin execution
        self._process_current_task()
    
    def _process_current_task(self):
        """Continue processing current task"""
        if not self.current_task_id:
            self._process_next()
            return
        
        task = self.tasks[self.current_task_id]
        
        # Check for stop/pause
        if self._should_stop:
            self._should_stop = False
            self._cancel_current_task()
            return
        
        if self._should_pause:
            task.status = TaskStatus.PAUSED
            log.info(f"Task {task.id} paused at step {task.current_step_index}")
            return
        
        # Check if task has steps defined
        if not task.steps:
            # Task needs to be analyzed first
            self._analyze_task(task)
        
        # Execute next step
        if task.current_step_index < len(task.steps):
            step = task.steps[task.current_step_index]
            self._execute_step(task, step)
        else:
            # All steps completed
            self._complete_task(task)
    
    def _analyze_task(self, task: Task):
        """Analyze task and create execution steps"""
        # This will be overridden by AIAgent to use AI for planning
        task.status = TaskStatus.PLANNING
        
        # Default: create a single execution step
        step = TaskStep(
            id=f"{task.id}_step_0",
            name="Execute",
            description="Process user request",
            status=TaskStatus.PENDING
        )
        task.steps.append(step)
        
        log.info(f"Task {task.id} analyzed, {len(task.steps)} steps created")
    
    def _execute_step(self, task: Task, step: TaskStep):
        """Execute a single step - to be overridden"""
        step.status = TaskStatus.EXECUTING
        step.started_at = datetime.now()
        
        self.task_progress.emit(
            task.id,
            step.name,
            task.progress_percentage
        )
        
        log.info(f"Task {task.id}: Executing step '{step.name}'")
        
        # This is where the actual work happens
        # Subclasses should override this or connect to signals
    
    def complete_current_step(self, result: Any = None, error: Optional[str] = None):
        """Mark current step as completed"""
        if not self.current_task_id:
            return
        
        task = self.tasks[self.current_task_id]
        step = task.current_step
        
        if not step:
            return
        
        step.completed_at = datetime.now()
        step.result = result
        step.error = error
        
        if error:
            step.status = TaskStatus.FAILED
            task.status = TaskStatus.FAILED
            task.error = error
            self.task_failed.emit(task.id, error)
            self._finish_task(task)
        else:
            step.status = TaskStatus.COMPLETED
            result_summary = str(result)[:100] if result else "Completed"
            self.task_step_completed.emit(task.id, step.name, result_summary)
            
            # Move to next step
            task.current_step_index += 1
            
            # Continue processing
            self._process_current_task()
    
    def _complete_task(self, task: Task):
        """Mark task as completed"""
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        
        summary = self._generate_task_summary(task)
        task.result = summary
        
        log.info(f"Task {task.id} completed in {task.duration_seconds:.1f}s")
        self.task_completed.emit(task.id, summary)
        self._finish_task(task)
    
    def _cancel_current_task(self):
        """Cancel the current task"""
        if not self.current_task_id:
            return
        
        task = self.tasks[self.current_task_id]
        task.status = TaskStatus.CANCELLED
        
        # Mark current step as cancelled if exists
        if task.current_step:
            task.current_step.status = TaskStatus.CANCELLED
        
        log.info(f"Task {task.id} cancelled")
        self.task_cancelled.emit(task.id)
        self._finish_task(task)
    
    def _finish_task(self, task: Task):
        """Clean up after task completion"""
        # Add to history
        self._task_history.append(task.id)
        if len(self._task_history) > self._history_limit:
            old_id = self._task_history.pop(0)
            if old_id in self.tasks:
                del self.tasks[old_id]
        
        self.current_task_id = None
        self.current_task_changed.emit("")
        
        # Process next task
        self._process_next()
    
    def _generate_task_summary(self, task: Task) -> str:
        """Generate a summary of completed task"""
        parts = [
            f"✅ Task Completed: {task.user_prompt[:50]}{'...' if len(task.user_prompt) > 50 else ''}",
            f"⏱️ Duration: {task.duration_seconds:.1f} seconds",
            f"📋 Steps: {len([s for s in task.steps if s.status == TaskStatus.COMPLETED])}/{len(task.steps)} completed"
        ]
        return "\n".join(parts)
    
    def is_busy(self) -> bool:
        """Check if currently processing a task"""
        return self._is_processing and self.current_task_id is not None
    
    def clear_queue(self):
        """Clear all pending tasks"""
        for task_id in self.queue:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.status = TaskStatus.CANCELLED
        
        self.queue.clear()
        self.queue_updated.emit(0)
        log.info("Task queue cleared")
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status for UI display"""
        current = self.get_current_task()
        return {
            "is_processing": self._is_processing,
            "current_task": {
                "id": current.id if current else None,
                "prompt": current.user_prompt if current else None,
                "progress": current.progress_percentage if current else 0,
                "current_step": current.current_step.name if current and current.current_step else None,
                "status": current.status.name if current else None
            },
            "queue_length": len(self.queue),
            "pending_tasks": [
                {"id": t.id, "prompt": t.user_prompt[:50], "priority": t.priority.name}
                for t in self.get_pending_tasks()[:5]  # Show first 5
            ]
        }


class QueueFullError(Exception):
    """Raised when task queue is full"""
    pass


# Singleton instance
_task_queue = None


def get_task_queue(parent=None) -> TaskQueue:
    """Get singleton task queue instance"""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue(parent)
    return _task_queue
