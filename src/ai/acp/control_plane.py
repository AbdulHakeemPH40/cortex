"""
Agent Control Plane (ACP) for Cortex AI Agent
Multi-agent coordination and delegation system
Based on OpenCode's ACP (packages/opencode/src/acp/)
"""

from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from PyQt6.QtCore import QObject, pyqtSignal, QThread
import uuid
import json
from src.utils.logger import get_logger

log = get_logger("acp")


class AgentType(Enum):
    """Types of agents in the system."""
    BUILD = "build"           # Full edit/write permissions
    EXPLORE = "explore"       # Read-only analysis
    PLAN = "plan"            # Planning and design
    DEBUG = "debug"          # Debugging specialist
    GENERAL = "general"      # Complex task delegation
    GITHUB = "github"        # GitHub automation
    MCP = "mcp"             # External tool integration


class AgentStatus(Enum):
    """Agent execution status."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    DELEGATING = "delegating"


@dataclass
class AgentTask:
    """Represents a task assigned to an agent."""
    id: str
    description: str
    agent_type: AgentType
    parent_task_id: Optional[str] = None
    status: AgentStatus = AgentStatus.IDLE
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentMessage:
    """Message passed between agents."""
    from_agent: str
    to_agent: str
    task_id: str
    message_type: str  # request, response, delegate, complete
    content: Any
    timestamp: datetime = field(default_factory=datetime.now)


class BaseAgent(QObject):
    """Base class for all agents."""
    
    task_completed = pyqtSignal(str, Any)  # task_id, result
    task_failed = pyqtSignal(str, str)     # task_id, error
    message_sent = pyqtSignal(AgentMessage)
    
    def __init__(self, agent_id: str, agent_type: AgentType, parent=None):
        super().__init__(parent)
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.status = AgentStatus.IDLE
        self.current_task: Optional[AgentTask] = None
        self.subagents: Dict[str, 'BaseAgent'] = {}
        
        log.info(f"Agent {agent_id} ({agent_type.value}) initialized")
    
    def execute(self, task: AgentTask) -> Any:
        """
        Execute a task. Override in subclasses.
        
        Args:
            task: The task to execute
            
        Returns:
            Task result
        """
        raise NotImplementedError("Subclasses must implement execute()")
    
    def can_handle(self, task_description: str) -> bool:
        """
        Check if this agent can handle a task.
        
        Args:
            task_description: Description of the task
            
        Returns:
            True if agent can handle the task
        """
        return True
    
    def delegate_to(self, agent: 'BaseAgent', task: AgentTask) -> str:
        """
        Delegate a task to a subagent.
        
        Args:
            agent: Subagent to delegate to
            task: Task to delegate
            
        Returns:
            Task ID
        """
        task.parent_task_id = self.current_task.id if self.current_task else None
        self.subagents[agent.agent_id] = agent
        
        log.info(f"Agent {self.agent_id} delegating task {task.id} to {agent.agent_id}")
        
        # Start agent in thread
        worker = AgentWorker(agent, task)
        worker.finished.connect(self._on_subagent_finished)
        worker.error.connect(self._on_subagent_error)
        worker.start()
        
        return task.id
    
    def _on_subagent_finished(self, task_id: str, result: Any):
        """Handle subagent task completion."""
        log.info(f"Subagent completed task {task_id}")
        self.task_completed.emit(task_id, result)
    
    def _on_subagent_error(self, task_id: str, error: str):
        """Handle subagent task failure."""
        log.error(f"Subagent failed task {task_id}: {error}")
        self.task_failed.emit(task_id, error)
    
    def send_message(self, to_agent: str, message_type: str, content: Any):
        """Send message to another agent."""
        msg = AgentMessage(
            from_agent=self.agent_id,
            to_agent=to_agent,
            task_id=self.current_task.id if self.current_task else "",
            message_type=message_type,
            content=content
        )
        self.message_sent.emit(msg)


class AgentWorker(QThread):
    """Worker thread for agent execution."""
    
    finished = pyqtSignal(str, Any)  # task_id, result
    error = pyqtSignal(str, str)     # task_id, error_message
    
    def __init__(self, agent: BaseAgent, task: AgentTask):
        super().__init__()
        self.agent = agent
        self.task = task
    
    def run(self):
        """Execute agent task in background."""
        try:
            self.task.status = AgentStatus.RUNNING
            self.task.started_at = datetime.now()
            self.agent.current_task = self.task
            self.agent.status = AgentStatus.RUNNING
            
            # Execute the task
            result = self.agent.execute(self.task)
            
            # Mark as completed
            self.task.status = AgentStatus.COMPLETED
            self.task.completed_at = datetime.now()
            self.task.result = result
            self.agent.status = AgentStatus.IDLE
            
            self.finished.emit(self.task.id, result)
            
        except Exception as e:
            self.task.status = AgentStatus.ERROR
            self.task.error = str(e)
            self.task.completed_at = datetime.now()
            self.agent.status = AgentStatus.ERROR
            
            log.error(f"Agent {self.agent.agent_id} failed task {self.task.id}: {e}")
            self.error.emit(self.task.id, str(e))


class BuildAgent(BaseAgent):
    """Build agent - handles coding and file operations."""
    
    def __init__(self, agent_id: str = None, parent=None):
        super().__init__(agent_id or f"build_{uuid.uuid4().hex[:8]}", AgentType.BUILD, parent)
    
    def execute(self, task: AgentTask) -> Any:
        """Execute build task."""
        log.info(f"BuildAgent executing: {task.description}")
        
        # In production, this would:
        # 1. Use AI to generate code
        # 2. Create/modify files
        # 3. Run tests
        # 4. Return results
        
        return {
            "status": "success",
            "files_created": ["example.py"],
            "files_modified": [],
            "summary": f"Completed: {task.description}"
        }
    
    def can_handle(self, task_description: str) -> bool:
        """Check if task involves building/coding."""
        build_keywords = ['create', 'build', 'implement', 'write', 'code', 'develop', 'fix', 'refactor']
        return any(kw in task_description.lower() for kw in build_keywords)


class ExploreAgent(BaseAgent):
    """Explore agent - handles code analysis and exploration."""
    
    def __init__(self, agent_id: str = None, parent=None):
        super().__init__(agent_id or f"explore_{uuid.uuid4().hex[:8]}", AgentType.EXPLORE, parent)
    
    def execute(self, task: AgentTask) -> Any:
        """Execute exploration task."""
        log.info(f"ExploreAgent executing: {task.description}")
        
        # In production, this would:
        # 1. Read and analyze code
        # 2. Search for patterns
        # 3. Generate explanations
        # 4. Return analysis
        
        return {
            "status": "success",
            "files_analyzed": 5,
            "summary": f"Analysis complete: {task.description}",
            "findings": ["Pattern A found", "Pattern B detected"]
        }
    
    def can_handle(self, task_description: str) -> bool:
        """Check if task involves exploration."""
        explore_keywords = ['analyze', 'explore', 'understand', 'find', 'search', 'what', 'how', 'explain']
        return any(kw in task_description.lower() for kw in explore_keywords)


class PlanAgent(BaseAgent):
    """Plan agent - handles planning and design tasks."""
    
    def __init__(self, agent_id: str = None, parent=None):
        super().__init__(agent_id or f"plan_{uuid.uuid4().hex[:8]}", AgentType.PLAN, parent)
    
    def execute(self, task: AgentTask) -> Any:
        """Execute planning task."""
        log.info(f"PlanAgent executing: {task.description}")
        
        return {
            "status": "success",
            "plan": [
                "Step 1: Analyze requirements",
                "Step 2: Design architecture",
                "Step 3: Define interfaces"
            ],
            "estimated_time": "2 hours",
            "complexity": "medium"
        }
    
    def can_handle(self, task_description: str) -> bool:
        """Check if task involves planning."""
        plan_keywords = ['plan', 'design', 'architecture', 'structure', 'organize']
        return any(kw in task_description.lower() for kw in plan_keywords)


class DebugAgent(BaseAgent):
    """Debug agent - handles debugging and error fixing."""
    
    def __init__(self, agent_id: str = None, parent=None):
        super().__init__(agent_id or f"debug_{uuid.uuid4().hex[:8]}", AgentType.DEBUG, parent)
    
    def execute(self, task: AgentTask) -> Any:
        """Execute debugging task."""
        log.info(f"DebugAgent executing: {task.description}")
        
        return {
            "status": "success",
            "errors_found": 2,
            "fixes_applied": 2,
            "summary": "Debugged successfully"
        }
    
    def can_handle(self, task_description: str) -> bool:
        """Check if task involves debugging."""
        debug_keywords = ['debug', 'fix', 'error', 'bug', 'issue', 'problem', 'crash']
        return any(kw in task_description.lower() for kw in debug_keywords)


class AgentControlPlane(QObject):
    """
    Central coordinator for multi-agent system.
    
    Features:
    - Agent registration and discovery
    - Task routing and delegation
    - Message passing between agents
    - Task lifecycle management
    """
    
    task_completed = pyqtSignal(str, Any)  # task_id, result
    task_failed = pyqtSignal(str, str)     # task_id, error
    agent_registered = pyqtSignal(str, str)  # agent_id, agent_type
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.agents: Dict[str, BaseAgent] = {}
        self.tasks: Dict[str, AgentTask] = {}
        self.message_queue: List[AgentMessage] = []
        
        # Register default agents
        self._register_default_agents()
        
        log.info("Agent Control Plane initialized")
    
    def _register_default_agents(self):
        """Register the default set of agents."""
        self.register_agent(BuildAgent())
        self.register_agent(ExploreAgent())
        self.register_agent(PlanAgent())
        self.register_agent(DebugAgent())
    
    def register_agent(self, agent: BaseAgent) -> bool:
        """
        Register an agent with the ACP.
        
        Args:
            agent: Agent to register
            
        Returns:
            True if successful
        """
        if agent.agent_id in self.agents:
            log.warning(f"Agent {agent.agent_id} already registered")
            return False
        
        self.agents[agent.agent_id] = agent
        agent.task_completed.connect(self._on_task_completed)
        agent.task_failed.connect(self._on_task_failed)
        agent.message_sent.connect(self._on_agent_message)
        
        self.agent_registered.emit(agent.agent_id, agent.agent_type.value)
        log.info(f"Registered agent: {agent.agent_id} ({agent.agent_type.value})")
        
        return True
    
    def create_task(self, description: str, agent_type: AgentType = None,
                   preferred_agent: str = None) -> str:
        """
        Create and route a new task.
        
        Args:
            description: Task description
            agent_type: Type of agent to use (optional)
            preferred_agent: Specific agent ID to use (optional)
            
        Returns:
            Task ID
        """
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        
        # Determine agent type if not specified
        if agent_type is None:
            agent_type = self._determine_agent_type(description)
        
        task = AgentTask(
            id=task_id,
            description=description,
            agent_type=agent_type
        )
        
        self.tasks[task_id] = task
        
        # Find and assign agent
        if preferred_agent and preferred_agent in self.agents:
            agent = self.agents[preferred_agent]
        else:
            agent = self._find_best_agent(agent_type, description)
        
        if agent:
            log.info(f"Routing task {task_id} to agent {agent.agent_id}")
            self._execute_task(agent, task)
        else:
            log.error(f"No suitable agent found for task {task_id}")
            task.status = AgentStatus.ERROR
            task.error = "No suitable agent available"
        
        return task_id
    
    def _determine_agent_type(self, description: str) -> AgentType:
        """Determine best agent type for a task."""
        # Check each agent type
        if DebugAgent().can_handle(description):
            return AgentType.DEBUG
        elif BuildAgent().can_handle(description):
            return AgentType.BUILD
        elif PlanAgent().can_handle(description):
            return AgentType.PLAN
        elif ExploreAgent().can_handle(description):
            return AgentType.EXPLORE
        else:
            return AgentType.GENERAL
    
    def _find_best_agent(self, agent_type: AgentType, description: str) -> Optional[BaseAgent]:
        """Find the best available agent for a task."""
        # First, look for agents of the right type
        suitable_agents = [
            agent for agent in self.agents.values()
            if agent.agent_type == agent_type and agent.status == AgentStatus.IDLE
        ]
        
        if suitable_agents:
            return suitable_agents[0]
        
        # If none idle, look for any agent of right type
        suitable_agents = [
            agent for agent in self.agents.values()
            if agent.agent_type == agent_type
        ]
        
        if suitable_agents:
            return suitable_agents[0]
        
        # Fall back to general agent
        general_agents = [
            agent for agent in self.agents.values()
            if agent.agent_type == AgentType.GENERAL
        ]
        
        if general_agents:
            return general_agents[0]
        
        return None
    
    def _execute_task(self, agent: BaseAgent, task: AgentTask):
        """Execute a task with an agent."""
        worker = AgentWorker(agent, task)
        worker.finished.connect(lambda tid, result: self._on_task_completed(tid, result))
        worker.error.connect(lambda tid, error: self._on_task_failed(tid, error))
        worker.start()
    
    def _on_task_completed(self, task_id: str, result: Any):
        """Handle task completion."""
        if task_id in self.tasks:
            self.tasks[task_id].status = AgentStatus.COMPLETED
            self.tasks[task_id].result = result
        
        log.info(f"Task {task_id} completed")
        self.task_completed.emit(task_id, result)
    
    def _on_task_failed(self, task_id: str, error: str):
        """Handle task failure."""
        if task_id in self.tasks:
            self.tasks[task_id].status = AgentStatus.ERROR
            self.tasks[task_id].error = error
        
        log.error(f"Task {task_id} failed: {error}")
        self.task_failed.emit(task_id, error)
    
    def _on_agent_message(self, message: AgentMessage):
        """Handle message from agent."""
        self.message_queue.append(message)
        log.debug(f"Message from {message.from_agent} to {message.to_agent}: {message.message_type}")
        
        # Route to recipient if available
        if message.to_agent in self.agents:
            recipient = self.agents[message.to_agent]
            # Handle message (in production, would process based on message_type)
            log.debug(f"Routed message to {message.to_agent}")
    
    def get_task_status(self, task_id: str) -> Optional[AgentStatus]:
        """Get status of a task."""
        if task_id in self.tasks:
            return self.tasks[task_id].status
        return None
    
    def get_task_result(self, task_id: str) -> Any:
        """Get result of a completed task."""
        if task_id in self.tasks:
            return self.tasks[task_id].result
        return None
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """List all registered agents."""
        return [
            {
                "id": agent.agent_id,
                "type": agent.agent_type.value,
                "status": agent.status.value
            }
            for agent in self.agents.values()
        ]
    
    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all tasks."""
        return [
            {
                "id": task.id,
                "description": task.description,
                "type": task.agent_type.value,
                "status": task.status.value,
                "created_at": task.created_at.isoformat()
            }
            for task in self.tasks.values()
        ]


# Global instance
_acp: Optional[AgentControlPlane] = None


def get_agent_control_plane() -> AgentControlPlane:
    """Get global AgentControlPlane instance."""
    global _acp
    if _acp is None:
        _acp = AgentControlPlane()
    return _acp
