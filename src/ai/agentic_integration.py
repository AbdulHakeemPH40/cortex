"""
Agentic Tools Integration for Cortex IDE

Connects Claude CLI-compatible agentic tools to existing:
- agent.py (AIChatAgent worker thread)
- agents.py (Multi-agent system)
- main_window.py (UI integration)
- ai_chat.py (Chat interface)

Supports all providers: DeepSeek, Anthropic, OpenAI, etc.
"""

import asyncio
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal, QThread

from src.ai.tools import (
    # Tool system
    ToolRegistry,
    ToolUseContext,
    ToolPermissionContext,
    AgentType,
    
    # Task tools
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
    TaskStopTool,
    get_task_manager,
    TaskStatus,
    
    # Agent tools
    AgentTool,
    TaskOutputTool,
    SendMessageTool,
    
    # Constants
    ASYNC_AGENT_ALLOWED_TOOLS,
    COORDINATOR_MODE_ALLOWED_TOOLS,
)

from src.ai.prompts.agentic_system_prompts import (
    get_system_prompt_for_agent_type,
    get_deepseek_compatible_prompt,
)

from src.ai.providers import get_provider_registry, ProviderType
from src.utils.logger import get_logger

log = get_logger("agentic_integration")


# =============================================================================
# AGENTIC TOOL EXECUTOR
# =============================================================================

class AgenticToolExecutor:
    """
    Executes agentic tools with proper context management.
    
    Bridges between AI tool calls and the Claude-compatible tool system.
    Works with any LLM provider (DeepSeek, Anthropic, OpenAI, etc.)
    """
    
    def __init__(self, conversation_id: str, agent_id: Optional[str] = None):
        self.conversation_id = conversation_id
        # BUG #4 FIX: Generate unique agent_id if not provided (prevents collisions in parallel execution)
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex[:12]}"
        self.registry = ToolRegistry()
        self._register_default_tools()
        
    def _register_default_tools(self):
        """Register all agentic tools."""
        self.registry.register(TaskCreateTool())
        self.registry.register(TaskGetTool())
        self.registry.register(TaskListTool())
        self.registry.register(TaskUpdateTool())
        self.registry.register(TaskStopTool())
        self.registry.register(AgentTool())
        self.registry.register(TaskOutputTool())
        self.registry.register(SendMessageTool())
    
    async def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        agent_type: AgentType = AgentType.MAIN,
        on_progress: Optional[Callable[[str, Dict], None]] = None
    ) -> Dict[str, Any]:
        """
        Execute a tool with proper context.
        
        Args:
            tool_name: Name of tool to execute
            args: Tool arguments
            agent_type: Type of agent executing
            on_progress: Progress callback
            
        Returns:
            Tool execution result
        """
        # Build context with permission filtering
        perm_context = ToolPermissionContext()
        
        # Filter tools based on agent type (BUG #7 FIX: Now properly propagated)
        if agent_type == AgentType.ASYNC:
            perm_context.always_allow_rules = {
                t: ["*"] for t in ASYNC_AGENT_ALLOWED_TOOLS
            }
        elif agent_type == AgentType.COORDINATOR:
            perm_context.always_allow_rules = {
                t: ["*"] for t in COORDINATOR_MODE_ALLOWED_TOOLS
            }
        
        # Create context with full permission information
        context = ToolUseContext(
            conversation_id=self.conversation_id,
            agent_id=self.agent_id,
            agent_type=agent_type,
            permission_context=perm_context,  # BUG #7 FIX: Pass context to tool
            on_progress=on_progress
        )
        
        # Find and execute tool with permission check
        tool = self.registry.find_tool(tool_name, perm_context)
        if not tool:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not found or not allowed for {agent_type.value} agent"
            }
        
        try:
            # Check permissions before execution (BUG #7 FIX: Now enforced)
            perm_check = perm_context.can_use_tool(tool_name, args)
            if perm_check.denied:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' denied for {agent_type.value} agent"
                }
            
            result = await tool.call(args, context)
            return {
                "success": result.success,
                "result": result.result if hasattr(result, 'result') else result.data,
                "error": result.error,
                "metadata": result.metadata if hasattr(result, 'metadata') else {}
            }
        except Exception as e:
            log.error(f"Tool execution failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# AGENTIC AGENT WRAPPER
# =============================================================================

class AgenticAgentWrapper:
    """
    Wraps existing BaseAgent with agentic capabilities.
    
    Integrates with agents.py BaseAgent, BuildAgent, PlanAgent, etc.
    """
    
    def __init__(
        self,
        base_agent: 'BaseAgent',  # From agents.py
        conversation_id: str,
        enable_agentic_tools: bool = True
    ):
        self.base_agent = base_agent
        self.conversation_id = conversation_id
        self.enable_agentic_tools = enable_agentic_tools
        self.tool_executor = AgenticToolExecutor(
            conversation_id=conversation_id,
            agent_id=str(id(base_agent))
        )
        
    def get_system_prompt(self) -> str:
        """Get enhanced system prompt with agentic guidance."""
        base_prompt = self.base_agent._get_system_prompt()
        
        if not self.enable_agentic_tools:
            return base_prompt
        
        # Determine agent type from base agent
        agent_type_map = {
            "build": "main",
            "plan": "main", 
            "debug": "main",
            "general": "main",
        }
        agent_type = agent_type_map.get(
            self.base_agent.agent_type.value, 
            "main"
        )
        
        # Get agentic prompt addendum
        agentic_prompt = get_system_prompt_for_agent_type(
            agent_type,
            include_agentic_tools=True
        )
        
        # Combine
        return f"""{base_prompt}

---

AGENTIC CAPABILITIES:
{agentic_prompt}
"""
    
    async def execute_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool call from the AI.
        
        This is the main integration point - AI calls tools, this executes them.
        """
        # Map agent type
        agent_type = AgentType.MAIN
        if hasattr(self.base_agent, 'capabilities'):
            if self.base_agent.capabilities.read_only:
                # Read-only agents can't use agentic tools
                if tool_name in ["agent", "task_create", "task_stop"]:
                    return {
                        "success": False,
                        "error": f"Tool '{tool_name}' not available in read-only mode"
                    }
        
        return await self.tool_executor.execute_tool(
            tool_name=tool_name,
            args=args,
            agent_type=agent_type
        )
    
    def get_allowed_tools(self) -> List[str]:
        """Get list of tools this agent is allowed to use."""
        base_tools = self.base_agent.capabilities.allowed_tools or []
        
        if not self.enable_agentic_tools:
            return base_tools
        
        # Add agentic tools
        agentic_tools = [
            "task_create",
            "task_get", 
            "task_list",
            "task_update",
            "task_stop",
            "agent",
        ]
        
        return base_tools + agentic_tools


# =============================================================================
# UI INTEGRATION (main_window.py & ai_chat.py)
# =============================================================================

class AgenticTaskMonitor(QObject):
    """
    Monitors task status for UI updates.
    
    Emits signals for:
    - Task created
    - Task status changed
    - Task completed/failed
    - Agent spawned
    
    Connects to main_window.py UI components.
    """
    
    # Signals for UI updates
    task_created = pyqtSignal(str, str)  # task_id, description
    task_updated = pyqtSignal(str, str, str)  # task_id, status, result_preview
    task_completed = pyqtSignal(str, str)  # task_id, result
    task_failed = pyqtSignal(str, str)  # task_id, error
    agent_spawned = pyqtSignal(str, str, str)  # agent_id, task_id, agent_type
    message_received = pyqtSignal(str, str, str)  # agent_id, sender, content
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.task_manager = get_task_manager()
        self._setup_callbacks()
        self._polling = False
        
    def _setup_callbacks(self):
        """Set up task change callbacks."""
        self.task_manager.register_callback(self._on_task_change)
    
    def _on_task_change(self, event: str, task):
        """Handle task changes."""
        if event == "created":
            self.task_created.emit(task.id, task.description)
        elif event == "updated":
            preview = task.result[:100] if task.result else ""
            self.task_updated.emit(task.id, task.status.value, preview)
        elif event == "completed" or (event == "updated" and task.status.value == "completed"):
            self.task_completed.emit(task.id, task.result or "")
        elif event == "cancelled" or (event == "updated" and task.status.value == "failed"):
            self.task_failed.emit(task.id, task.error_message or "")
    
    def start_polling(self, interval_ms: int = 1000):
        """Start polling for task updates (if not using callbacks)."""
        # Could use QTimer for polling if needed
        pass
    
    def get_active_tasks(self) -> List[Dict]:
        """Get list of currently active tasks for UI display."""
        tasks = self.task_manager.list_tasks()
        return [task.to_dict() for task in tasks]


# =============================================================================
# CHAT INTERFACE INTEGRATION
# =============================================================================

class AgenticChatHandler:
    """
    Handles agentic tool calls from chat interface.
    
    Integrates with ai_chat.py and ai_chat.html
    """
    
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.tool_executor = AgenticToolExecutor(conversation_id)
        self.monitor = AgenticTaskMonitor()
        
    async def handle_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ui_callback: Optional[Callable[[str, Any], None]] = None
    ) -> Dict[str, Any]:
        """
        Handle a tool call from chat.
        
        Args:
            tool_name: Tool to execute
            args: Tool arguments from AI
            ui_callback: Optional callback for UI updates
            
        Returns:
            Tool result
        """
        # Progress callback
        def on_progress(tool: str, data: Dict):
            if ui_callback:
                ui_callback("progress", {"tool": tool, "data": data})
        
        result = await self.tool_executor.execute_tool(
            tool_name=tool_name,
            args=args,
            on_progress=on_progress
        )
        
        # Update UI via callback
        if ui_callback:
            ui_callback("complete", result)
        
        return result
    
    def get_system_prompt_addendum(self, provider_type: Optional[str] = None) -> str:
        """
        Get system prompt addendum for agentic tools.
        
        Args:
            provider_type: e.g., "deepseek", "anthropic", "openai"
            
        Returns:
            System prompt addendum
        """
        prompt = get_system_prompt_for_agent_type("main", include_agentic_tools=True)
        
        if provider_type and provider_type.lower() == "deepseek":
            prompt = get_deepseek_compatible_prompt(prompt)
        
        return prompt


# =============================================================================
# DEEPSEEK COMPATIBILITY
# =============================================================================

class DeepSeekAgenticAdapter:
    """
    Adapts agentic tools for DeepSeek provider.
    
    DeepSeek works with the standard tool system but may need:
    - Explicit tool descriptions
    - Few-shot examples
    - Specific formatting
    """
    
    def __init__(self):
        self.provider = get_provider_registry().get_provider(ProviderType.DEEPSEEK)
    
    def get_system_prompt(self) -> str:
        """Get DeepSeek-compatible system prompt with agentic tools."""
        return get_deepseek_compatible_prompt(
            get_system_prompt_for_agent_type("main", include_agentic_tools=True)
        )
    
    def format_tool_call(self, tool_name: str, args: Dict) -> str:
        """
        Format tool call for DeepSeek.
        
        DeepSeek may prefer specific formatting.
        """
        return f"""<tool>{tool_name}</tool>
<args>{args}</args>"""
    
    def supports_parallel_agents(self) -> bool:
        """Check if DeepSeek supports parallel agent spawning."""
        # DeepSeek supports tool calling, so yes
        return True


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_agentic_agent(
    agent_type: str,
    conversation_id: str,
    provider_type: ProviderType = ProviderType.DEEPSEEK,
    enable_agentic: bool = True
) -> AgenticAgentWrapper:
    """
    Factory function to create an agentic-enabled agent.
    
    Args:
        agent_type: "build", "plan", "debug", "general"
        conversation_id: Unique conversation ID
        provider_type: Which LLM provider to use
        enable_agentic: Whether to enable agentic tools
        
    Returns:
        AgenticAgentWrapper instance
    """
    # Import from agents.py
    from src.ai.agents import BuildAgent, PlanAgent, DebugAgent
    
    # Create base agent
    agent_map = {
        "build": BuildAgent,
        "plan": PlanAgent,
        "debug": DebugAgent,
    }
    
    agent_class = agent_map.get(agent_type, BuildAgent)
    base_agent = agent_class()
    
    # Wrap with agentic capabilities
    return AgenticAgentWrapper(
        base_agent=base_agent,
        conversation_id=conversation_id,
        enable_agentic_tools=enable_agentic
    )


def get_agentic_chat_handler(conversation_id: str) -> AgenticChatHandler:
    """Get or create agentic chat handler for a conversation."""
    return AgenticChatHandler(conversation_id)


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

async def example_usage():
    """Example: Using agentic integration."""
    
    # 1. Create agentic agent
    agent = create_agentic_agent(
        agent_type="build",
        conversation_id="conv_123",
        provider_type=ProviderType.DEEPSEEK
    )
    
    # 2. Get enhanced system prompt
    system_prompt = agent.get_system_prompt()
    print(f"System prompt length: {len(system_prompt)}")
    
    # 3. Execute agentic tool
    result = await agent.execute_tool_call(
        "task_create",
        {"description": "Analyze security vulnerabilities"}
    )
    print(f"Task created: {result}")
    
    # 4. Get chat handler
    chat_handler = get_agentic_chat_handler("conv_123")
    
    # 5. Get DeepSeek-compatible prompt
    deepseek_prompt = chat_handler.get_system_prompt_addendum("deepseek")
    print(f"DeepSeek prompt ready: {len(deepseek_prompt)} chars")


if __name__ == "__main__":
    asyncio.run(example_usage())
