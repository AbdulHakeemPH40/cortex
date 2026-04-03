"""
Modular Tool Architecture for Cortex IDE

Tools are organized into categories:
- file_tools: File operations (read, write, edit)
- search_tools: Code search and pattern matching (grep, glob)  
- web_tools: Web operations (fetch, websearch)
- system_tools: System operations (run_command, shell)
- interaction_tools: User interaction (question_tool)
- task_tools: Task management (create, get, list, update, stop)
- agent_tools: Agent coordination (spawn, message, output)

Note: ToolRegistry remains in src.ai.tools (the module) to avoid circular imports.
This package only contains modular tool implementations.
"""

# Base classes (original)
from .base_tool import BaseTool, ToolResult

# Claude CLI-compatible enhanced tool system
from .claude_tool import (
    ClaudeTool,
    ToolUseContext,
    ToolPermissionContext,
    ToolCapability,
    AgentType,
    PermissionResult,
)

from .constants import (
    ASYNC_AGENT_ALLOWED_TOOLS,
    COORDINATOR_MODE_ALLOWED_TOOLS,
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS,
    ALL_AGENT_DISALLOWED_TOOLS,
)

from .tool_registry import (
    ToolRegistry,
    create_default_registry,
    get_tool_registry,
)

# Task management
from .task_tools.models import (
    Task,
    TaskStatus,
    TaskManager,
    get_task_manager,
)

from .task_tools import (
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
    TaskStopTool,
)

# Agent coordination
from .agent_tools import (
    AgentTool,
    TaskOutputTool,
    SendMessageTool,
    # Advanced agent tools
    MultiAgentTool,
    AgentMemoryTool,
    AgentPlanningTool,
    AgentReasoningTool,
    AgentLearningTool,
    AgentEvaluationTool,
    AgentOrchestrationTool,
)

__all__ = [
    # Base classes
    'BaseTool',
    'ToolResult',
    
    # Claude-compatible enhanced system
    'ClaudeTool',
    'ToolUseContext',
    'ToolPermissionContext',
    'ToolCapability',
    'AgentType',
    'PermissionResult',
    'ToolRegistry',
    'create_default_registry',
    'get_tool_registry',
    
    # Tool allowlists
    'ASYNC_AGENT_ALLOWED_TOOLS',
    'COORDINATOR_MODE_ALLOWED_TOOLS',
    'IN_PROCESS_TEAMMATE_ALLOWED_TOOLS',
    'ALL_AGENT_DISALLOWED_TOOLS',
    
    # Task management
    'Task',
    'TaskStatus',
    'TaskManager',
    'get_task_manager',
    'TaskCreateTool',
    'TaskGetTool',
    'TaskListTool',
    'TaskUpdateTool',
    'TaskStopTool',
    
    # Agent coordination
    'AgentTool',
    'TaskOutputTool',
    'SendMessageTool',
    # Advanced agent tools
    'MultiAgentTool',
    'AgentMemoryTool',
    'AgentPlanningTool',
    'AgentReasoningTool',
    'AgentLearningTool',
    'AgentEvaluationTool',
    'AgentOrchestrationTool',
]


# Legacy compatibility function - keep for existing code
def get_tool_registry_v2(project_root: Optional[str] = None):
    """
    Compatibility export for components expecting v2-style tool registry access.
    
    agent_v2 imports `get_tool_registry()` from `src.ai.tools`, but the real
    ToolRegistry implementation lives in `src.ai._tools_monolithic`.
    """
    global _tool_registry_singleton

    from src.ai._tools_monolithic import ToolRegistry

    root = project_root or str(Path.cwd())
    if (
        _tool_registry_singleton is None
        or getattr(_tool_registry_singleton, "project_root", None) != root
    ):
        _tool_registry_singleton = ToolRegistry(project_root=root)

        # agent_v2 expects `_tools`; monolithic registry stores tools on `.tools`
        _tool_registry_singleton._tools = _tool_registry_singleton.tools

    return _tool_registry_singleton


_tool_registry_singleton = None
