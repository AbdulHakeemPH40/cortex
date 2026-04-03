"""
TODO/Task Management System for Cortex AI Agent
Track tasks within chat conversations
"""

import sqlite3
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from src.utils.logger import get_logger

log = get_logger("todo_manager")


class TaskStatus(Enum):
    """Status of a todo task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TodoTask:
    """Represents a todo task."""
    id: str
    session_id: str
    description: str
    status: TaskStatus
    priority: int  # 1=high, 2=medium, 3=low
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata or {}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TodoTask':
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            description=data["description"],
            status=TaskStatus(data["status"]),
            priority=data["priority"],
            created_at=datetime.fromisoformat(data["created_at"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            metadata=data.get("metadata", {})
        )


class TodoManager(QObject):
    """
    Manages todo tasks within chat sessions.
    
    Features:
    - Create, update, complete, and delete tasks
    - Track task status and progress
    - Persist to database
    - Priority levels (high, medium, low)
    """
    
    task_added = pyqtSignal(str)  # task_id
    task_updated = pyqtSignal(str)  # task_id
    task_completed = pyqtSignal(str)  # task_id
    task_deleted = pyqtSignal(str)  # task_id
    
    def __init__(self, db_path: str = None):
        """
        Initialize TodoManager.
        
        Args:
            db_path: Path to SQLite database. Defaults to ~/.cortex/todos.db
        """
        super().__init__()
        
        if db_path is None:
            home = Path.home()
            cortex_dir = home / ".cortex"
            cortex_dir.mkdir(exist_ok=True)
            db_path = cortex_dir / "todos.db"
        
        self.db_path = str(db_path)
        self._init_database()
        
        log.info(f"TodoManager initialized: {self.db_path}")
    
    def _init_database(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority INTEGER DEFAULT 2,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_todos_session 
                ON todos(session_id, status)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_todos_status 
                ON todos(status, priority)
            """)
            
            conn.commit()
            log.debug("Todo database schema initialized")
    
    def add_task(self, session_id: str, description: str, 
                 priority: int = 2, metadata: Dict = None) -> str:
        """
        Add a new todo task.
        
        Args:
            session_id: Session/chat ID
            description: Task description
            priority: 1=high, 2=medium, 3=low
            metadata: Optional metadata
            
        Returns:
            Task ID
        """
        import uuid
        
        task_id = f"todo_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO todos 
                    (id, session_id, description, status, priority, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_id, session_id, description, 
                    TaskStatus.PENDING.value, priority, now,
                    json.dumps(metadata) if metadata else None
                ))
                conn.commit()
            
            self.task_added.emit(task_id)
            log.info(f"Added task {task_id}: {description[:50]}...")
            return task_id
            
        except Exception as e:
            log.error(f"Failed to add task: {e}")
            raise
    
    def start_task(self, task_id: str) -> bool:
        """
        Mark task as in-progress.
        
        Args:
            task_id: Task ID
            
        Returns:
            True if successful
        """
        try:
            now = datetime.now().isoformat()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE todos 
                    SET status = ?, started_at = ?
                    WHERE id = ?
                """, (TaskStatus.IN_PROGRESS.value, now, task_id))
                conn.commit()
                
                if cursor.rowcount > 0:
                    self.task_updated.emit(task_id)
                    log.info(f"Started task: {task_id}")
                    return True
                return False
                
        except Exception as e:
            log.error(f"Failed to start task: {e}")
            return False
    
    def complete_task(self, task_id: str) -> bool:
        """
        Mark task as completed.
        
        Args:
            task_id: Task ID
            
        Returns:
            True if successful
        """
        try:
            now = datetime.now().isoformat()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE todos 
                    SET status = ?, completed_at = ?
                    WHERE id = ?
                """, (TaskStatus.COMPLETED.value, now, task_id))
                conn.commit()
                
                if cursor.rowcount > 0:
                    self.task_completed.emit(task_id)
                    log.info(f"Completed task: {task_id}")
                    return True
                return False
                
        except Exception as e:
            log.error(f"Failed to complete task: {e}")
            return False
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task.
        
        Args:
            task_id: Task ID
            
        Returns:
            True if successful
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE todos 
                    SET status = ?
                    WHERE id = ?
                """, (TaskStatus.CANCELLED.value, task_id))
                conn.commit()
                
                if cursor.rowcount > 0:
                    self.task_updated.emit(task_id)
                    log.info(f"Cancelled task: {task_id}")
                    return True
                return False
                
        except Exception as e:
            log.error(f"Failed to cancel task: {e}")
            return False
    
    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task permanently.
        
        Args:
            task_id: Task ID
            
        Returns:
            True if successful
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM todos WHERE id = ?", (task_id,))
                conn.commit()
                
                if cursor.rowcount > 0:
                    self.task_deleted.emit(task_id)
                    log.info(f"Deleted task: {task_id}")
                    return True
                return False
                
        except Exception as e:
            log.error(f"Failed to delete task: {e}")
            return False
    
    def get_task(self, task_id: str) -> Optional[TodoTask]:
        """Get a single task by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM todos WHERE id = ?", (task_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_task(row)
                return None
                
        except Exception as e:
            log.error(f"Failed to get task: {e}")
            return None
    
    def get_session_tasks(self, session_id: str, 
                         status: TaskStatus = None) -> List[TodoTask]:
        """
        Get all tasks for a session.
        
        Args:
            session_id: Session ID
            status: Optional status filter
            
        Returns:
            List of tasks
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if status:
                    cursor = conn.execute("""
                        SELECT * FROM todos 
                        WHERE session_id = ? AND status = ?
                        ORDER BY priority ASC, created_at DESC
                    """, (session_id, status.value))
                else:
                    cursor = conn.execute("""
                        SELECT * FROM todos 
                        WHERE session_id = ?
                        ORDER BY 
                            CASE status 
                                WHEN 'pending' THEN 1 
                                WHEN 'in_progress' THEN 2 
                                WHEN 'completed' THEN 3 
                                ELSE 4 
                            END,
                            priority ASC,
                            created_at DESC
                    """, (session_id,))
                
                return [self._row_to_task(row) for row in cursor.fetchall()]
                
        except Exception as e:
            log.error(f"Failed to get session tasks: {e}")
            return []
    
    def get_pending_tasks(self, session_id: str = None) -> List[TodoTask]:
        """
        Get all pending tasks.
        
        Args:
            session_id: Optional session filter
            
        Returns:
            List of pending tasks
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if session_id:
                    cursor = conn.execute("""
                        SELECT * FROM todos 
                        WHERE session_id = ? AND status IN ('pending', 'in_progress')
                        ORDER BY priority ASC, created_at DESC
                    """, (session_id,))
                else:
                    cursor = conn.execute("""
                        SELECT * FROM todos 
                        WHERE status IN ('pending', 'in_progress')
                        ORDER BY priority ASC, created_at DESC
                    """)
                
                return [self._row_to_task(row) for row in cursor.fetchall()]
                
        except Exception as e:
            log.error(f"Failed to get pending tasks: {e}")
            return []
    
    def get_task_stats(self, session_id: str = None) -> Dict[str, int]:
        """
        Get task statistics.
        
        Args:
            session_id: Optional session filter
            
        Returns:
            Dict with counts by status
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                if session_id:
                    cursor = conn.execute("""
                        SELECT status, COUNT(*) as count 
                        FROM todos 
                        WHERE session_id = ?
                        GROUP BY status
                    """, (session_id,))
                else:
                    cursor = conn.execute("""
                        SELECT status, COUNT(*) as count 
                        FROM todos 
                        GROUP BY status
                    """)
                
                stats = {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0}
                for row in cursor.fetchall():
                    stats[row[0]] = row[1]
                
                return stats
                
        except Exception as e:
            log.error(f"Failed to get task stats: {e}")
            return {}
    
    def update_task_description(self, task_id: str, description: str) -> bool:
        """Update task description."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "UPDATE todos SET description = ? WHERE id = ?",
                    (description, task_id)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    self.task_updated.emit(task_id)
                    return True
                return False
                
        except Exception as e:
            log.error(f"Failed to update task: {e}")
            return False
    
    def update_task_priority(self, task_id: str, priority: int) -> bool:
        """Update task priority."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "UPDATE todos SET priority = ? WHERE id = ?",
                    (priority, task_id)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    self.task_updated.emit(task_id)
                    return True
                return False
                
        except Exception as e:
            log.error(f"Failed to update task priority: {e}")
            return False
    
    def _row_to_task(self, row: sqlite3.Row) -> TodoTask:
        """Convert database row to TodoTask."""
        return TodoTask(
            id=row["id"],
            session_id=row["session_id"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            metadata=json.loads(row["metadata"]) if row["metadata"] else None
        )


# Global instance
_todo_manager: Optional[TodoManager] = None


def get_todo_manager() -> TodoManager:
    """Get global TodoManager instance."""
    global _todo_manager
    if _todo_manager is None:
        _todo_manager = TodoManager()
    return _todo_manager
