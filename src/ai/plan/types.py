"""
Plan and TODO Types
OpenCode-style plan management for Cortex IDE
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime


class TodoPriority(Enum):
    """TODO priority levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TodoStatus(Enum):
    """TODO status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class PlanStatus(Enum):
    """Plan status"""
    DRAFT = "draft"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED = "aborted"


class StepStatus(Enum):
    """Plan step status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TodoContext:
    """Context around a TODO comment"""
    before: str = ""
    after: str = ""
    function_name: str = ""
    class_name: str = ""
    imports: List[str] = field(default_factory=list)


@dataclass
class Todo:
    """Represents a TODO item found in code"""
    id: str
    file: str
    line: int
    text: str
    language: str
    priority: TodoPriority
    status: TodoStatus
    context: TodoContext
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    plan_id: Optional[str] = None


@dataclass
class PlanStep:
    """Single step in a plan"""
    id: str
    number: int
    title: str
    description: str
    status: StepStatus
    estimated_time: int  # minutes
    dependencies: List[str]  # step IDs
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class Plan:
    """Complete plan with steps"""
    id: str
    title: str
    description: str
    status: PlanStatus
    priority: TodoPriority
    steps: List[PlanStep]
    todos: List[str]  # TODO IDs
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_total_time: int = 0  # minutes
    progress_percentage: int = 0


@dataclass
class ExecutionSession:
    """Tracks plan execution"""
    id: str
    plan_id: str
    status: str  # running, completed, aborted
    current_step: int
    steps_completed: int
    start_time: datetime
    end_time: Optional[datetime] = None
    total_duration: int = 0  # seconds
    logs: List[Dict[str, Any]] = field(default_factory=list)


# TODO patterns for different languages
TODO_PATTERNS = {
    "python": [
        (r'#\s*TODO[:\s]*(.+)', TodoPriority.MEDIUM),
        (r'#\s*FIXME[:\s]*(.+)', TodoPriority.HIGH),
        (r'#\s*HACK[:\s]*(.+)', TodoPriority.LOW),
        (r'#\s*XXX[:\s]*(.+)', TodoPriority.LOW),
        (r'"""\s*TODO:\s*(.+?)"""', TodoPriority.MEDIUM),
    ],
    "javascript": [
        (r'//\s*TODO[:\s]*(.+)', TodoPriority.MEDIUM),
        (r'//\s*FIXME[:\s]*(.+)', TodoPriority.HIGH),
        (r'//\s*HACK[:\s]*(.+)', TodoPriority.LOW),
        (r'/\*\s*TODO:\s*(.+?)\*/', TodoPriority.MEDIUM),
    ],
    "typescript": [
        (r'//\s*TODO[:\s]*(.+)', TodoPriority.MEDIUM),
        (r'//\s*FIXME[:\s]*(.+)', TodoPriority.HIGH),
        (r'//\s*HACK[:\s]*(.+)', TodoPriority.LOW),
        (r'/\*\s*TODO:\s*(.+?)\*/', TodoPriority.MEDIUM),
    ],
    "java": [
        (r'//\s*TODO[:\s]*(.+)', TodoPriority.MEDIUM),
        (r'//\s*FIXME[:\s]*(.+)', TodoPriority.HIGH),
    ],
}


# Language from file extension
LANGUAGE_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.jsx': 'javascript',
    '.java': 'java',
    '.cpp': 'cpp',
    '.c': 'c',
    '.h': 'c',
    '.go': 'go',
    '.rs': 'rust',
    '.rb': 'ruby',
    '.php': 'php',
    '.swift': 'swift',
    '.kt': 'kotlin',
}
