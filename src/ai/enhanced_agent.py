"""
enhanced_agent.py - Industry-Standard Agentic Architecture
Inspired by OpenCode's agent patterns with PyQt6 integration.

Key Features:
- Tool registry with automatic validation
- Permission system for safe execution  
- Session-based context management
- Planning and task tracking
- Skill-based capability system
"""

from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
from pathlib import Path


class PermissionLevel(Enum):
    """Permission levels for tool execution."""
    AUTO = "auto"           # No permission needed
    ASK = "ask"            # Ask user each time
    DENY = "deny"          # Never allow


@dataclass
class ToolDefinition:
    """Tool definition with metadata."""
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable
    permission: PermissionLevel = PermissionLevel.ASK
    requires_confirmation: bool = True
    is_safe: bool = False  # Auto-approve if True


@dataclass 
class SessionContext:
    """Session context for maintaining state."""
    session_id: str
    project_root: Path
    working_directory: Path
    environment: Dict[str, str] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class PlanStep:
    """Individual step in a plan."""
    id: str
    description: str
    tool: str
    parameters: Dict[str, Any]
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: Optional[str] = None


@dataclass
class Task:
    """Task with todos and progress tracking."""
    id: str
    title: str
    description: str
    todos: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "open"  # open, in_progress, completed, cancelled
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class EnhancedAgent:
    """
    Enhanced AI Agent with industry-standard architecture.
    
    Features:
    - Tool registry with validation
    - Permission management
    - Session context
    - Planning system
    - Task tracking
    - Skills system
    """
    
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.sessions: Dict[str, SessionContext] = {}
        self.current_session: Optional[str] = None
        self.plans: Dict[str, List[PlanStep]] = {}
        self.tasks: Dict[str, Task] = {}
        self.skills: Dict[str, Dict] = {}
        
    # ========== Tool Registry ==========
    
    def register_tool(self, name: str, description: str, parameters: Dict, 
                     handler: Callable, permission: PermissionLevel = PermissionLevel.ASK):
        """Register a tool with the agent."""
        self.tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            permission=permission
        )
        
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool by name."""
        return self.tools.get(name)
    
    def list_tools(self) -> List[str]:
        """List all registered tools."""
        return list(self.tools.keys())
    
    # ========== Session Management ==========
    
    def create_session(self, project_root: str) -> str:
        """Create a new session for a project."""
        import uuid
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = SessionContext(
            session_id=session_id,
            project_root=Path(project_root),
            working_directory=Path(project_root)
        )
        self.current_session = session_id
        return session_id
    
    def get_session(self) -> Optional[SessionContext]:
        """Get current session context."""
        if self.current_session:
            return self.sessions.get(self.current_session)
        return None
    
    def set_variable(self, key: str, value: Any):
        """Set session variable."""
        session = self.get_session()
        if session:
            session.variables[key] = value
    
    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get session variable."""
        session = self.get_session()
        if session:
            return session.variables.get(key, default)
        return default
    
    # ========== Permission System ==========
    
    def check_permission(self, tool_name: str) -> bool:
        """Check if tool can be executed."""
        tool = self.get_tool(tool_name)
        if not tool:
            return False
            
        if tool.permission == PermissionLevel.AUTO:
            return True
        elif tool.permission == PermissionLevel.DENY:
            return False
        else:  # ASK
            # In real implementation, this would show UI dialog
            return True
    
    # ========== Planning System ==========
    
    def create_plan(self, plan_id: str, steps: List[Dict]) -> str:
        """Create a plan with steps."""
        plan_steps = []
        for i, step_data in enumerate(steps):
            step = PlanStep(
                id=f"{plan_id}_step_{i}",
                description=step_data.get("description", ""),
                tool=step_data.get("tool", ""),
                parameters=step_data.get("parameters", {})
            )
            plan_steps.append(step)
        
        self.plans[plan_id] = plan_steps
        return plan_id
    
    def execute_plan(self, plan_id: str) -> List[Any]:
        """Execute all steps in a plan."""
        plan = self.plans.get(plan_id, [])
        results = []
        
        for step in plan:
            step.status = "running"
            try:
                tool = self.get_tool(step.tool)
                if tool:
                    result = tool.handler(**step.parameters)
                    step.result = result
                    step.status = "completed"
                    results.append(result)
                else:
                    step.error = f"Tool not found: {step.tool}"
                    step.status = "failed"
            except Exception as e:
                step.error = str(e)
                step.status = "failed"
                
        return results
    
    # ========== Task Management ==========
    
    def create_task(self, title: str, description: str) -> str:
        """Create a new task."""
        import uuid
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = Task(
            id=task_id,
            title=title,
            description=description
        )
        return task_id
    
    def add_todo(self, task_id: str, todo: str) -> bool:
        """Add todo to task."""
        task = self.tasks.get(task_id)
        if task:
            task.todos.append({
                "id": f"todo_{len(task.todos)}",
                "content": todo,
                "completed": False
            })
            return True
        return False
    
    def complete_todo(self, task_id: str, todo_index: int) -> bool:
        """Mark todo as completed."""
        task = self.tasks.get(task_id)
        if task and 0 <= todo_index < len(task.todos):
            task.todos[todo_index]["completed"] = True
            return True
        return False
    
    # ========== Skills System ==========
    
    def register_skill(self, name: str, description: str, tools: List[str]):
        """Register a skill (combination of tools)."""
        self.skills[name] = {
            "name": name,
            "description": description,
            "tools": tools
        }
    
    def get_skill(self, name: str) -> Optional[Dict]:
        """Get skill by name."""
        return self.skills.get(name)


# Global instance
_enhanced_agent: Optional[EnhancedAgent] = None

def get_enhanced_agent() -> EnhancedAgent:
    """Get or create enhanced agent instance."""
    global _enhanced_agent
    if _enhanced_agent is None:
        _enhanced_agent = EnhancedAgent()
    return _enhanced_agent
