"""
Agentic Tools - Claude CLI Compatible

Core multi-agent coordination tools:
- AgentTool: Spawn sub-agents
- TaskOutputTool: Async agent output
- SendMessageTool: Inter-agent messaging
"""

import uuid
from typing import Dict, Any, Callable, Optional

from ..claude_tool import ClaudeTool, ToolUseContext, ToolCapability, AgentType
from ..constants import (
    ASYNC_AGENT_ALLOWED_TOOLS,
    COORDINATOR_MODE_ALLOWED_TOOLS,
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS,
)
from ..base_tool import ToolParameter, success_result, error_result
from ..task_tools.models import get_task_manager, TaskStatus


class AgentTool(ClaudeTool):
    """
    Spawn a sub-agent to perform background work.
    
    Claude CLI AgentTool equivalent.
    
    BLOCKED FOR ASYNC AGENTS: Prevents infinite recursion.
    ALLOWED FOR: Main thread, Coordinator mode.
    
    Creates an isolated agent with:
    - Limited tool access (ASYNC_AGENT_ALLOWED_TOOLS)
    - Separate context (can't modify parent state directly)
    - Task-based output (via TaskOutputTool)
    
    Example tool call:
    {
        "prompt": "Analyze the security of auth.py",
        "tools": ["file_read", "grep", "glob"],
        "agent_type": "async"
    }
    
    Returns:
    {
        "agent_id": "agent_abc123",
        "status": "spawned",
        "allowed_tools": ["file_read", "grep", "glob"]
    }
    """
    
    name = "agent"
    description = "Spawn a sub-agent to perform background work with limited tool access"
    capabilities = {ToolCapability.AGENTIC}
    aliases = ["spawn_agent"]
    search_hint = "spawn async background agent worker"
    
    parameters = [
        ToolParameter(
            name="prompt",
            param_type="string",
            description="Instructions for the sub-agent (what to accomplish)",
            required=True
        ),
        ToolParameter(
            name="tools",
            param_type="array",
            description="List of tool names the agent is allowed to use",
            required=True
        ),
        ToolParameter(
            name="agent_type",
            param_type="string",
            description="Agent type: 'async' (background), 'in_process' (coordinated), or 'coordinator'",
            required=False,
            default="async"
        ),
        ToolParameter(
            name="parent_task_id",
            param_type="string",
            description="Optional: associate with existing task",
            required=False,
            default=None
        )
    ]
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Callable[[Dict], None] = None
    ):
        """Execute agent tool - spawn sub-agent."""
        try:
            prompt = args.get("prompt", "")
            tools = args.get("tools", [])
            agent_type_str = args.get("agent_type", "async")
            parent_task_id = args.get("parent_task_id")
            
            # Validate agent type
            try:
                agent_type = AgentType(agent_type_str)
            except ValueError:
                return error_result(f"Invalid agent_type: {agent_type_str}")
            
            # BLOCKED FOR ASYNC AGENTS
            # Async agents cannot spawn other agents (prevents infinite recursion)
            if context.agent_type == AgentType.ASYNC:
                return error_result(
                    "Agent tool is not available for async agents. "
                    "Only main thread and coordinator agents can spawn sub-agents."
                )
            
            # Validate tools against allowed set for agent type
            allowed = self._get_allowed_tools_for_agent(agent_type)
            invalid_tools = [t for t in tools if t not in allowed]
            if invalid_tools:
                return error_result(
                    f"Tools not allowed for {agent_type.value} agent: {invalid_tools}. "
                    f"Allowed: {sorted(allowed)}"
                )
            
            # Generate agent ID
            agent_id = f"agent_{uuid.uuid4().hex[:12]}"
            
            # Create sub-agent context (isolated from parent)
            sub_context = self._create_subagent_context(
                parent_context=context,
                agent_id=agent_id,
                agent_type=agent_type,
                allowed_tools=tools
            )
            
            # Create task for tracking if not provided
            task_id = None
            if not parent_task_id:
                task_manager = get_task_manager()
                task = task_manager.create_task(
                    description=f"Agent task: {prompt[:50]}",
                    metadata={
                        "agent_id": agent_id,
                        "agent_type": agent_type.value,
                        "prompt": prompt,
                        "allowed_tools": tools
                    }
                )
                task_id = task.id
                
                # Update task to running
                task_manager.update_task(task_id, status=TaskStatus.RUNNING, agent_id=agent_id)
            
            # Spawn the agent (implementation would integrate with agent system)
            await self._spawn_agent(
                agent_id=agent_id,
                prompt=prompt,
                tools=tools,
                context=sub_context,
                task_id=task_id or parent_task_id
            )
            
            return success_result(
                result={
                    "agent_id": agent_id,
                    "status": "spawned",
                    "agent_type": agent_type.value,
                    "task_id": task_id or parent_task_id,
                    "allowed_tools": tools
                },
                metadata={
                    "agent_id": agent_id,
                    "parent_agent": context.agent_id or "main"
                }
            )
            
        except Exception as e:
            return error_result(f"Failed to spawn agent: {str(e)}")
    
    def _get_allowed_tools_for_agent(self, agent_type: AgentType) -> set:
        """Get allowed tool set for agent type."""
        if agent_type == AgentType.ASYNC:
            return ASYNC_AGENT_ALLOWED_TOOLS
        elif agent_type == AgentType.COORDINATOR:
            return COORDINATOR_MODE_ALLOWED_TOOLS
        elif agent_type == AgentType.IN_PROCESS:
            return ASYNC_AGENT_ALLOWED_TOOLS | IN_PROCESS_TEAMMATE_ALLOWED_TOOLS
        else:
            # Main gets most tools
            return ASYNC_AGENT_ALLOWED_TOOLS | IN_PROCESS_TEAMMATE_ALLOWED_TOOLS | {"agent"}
    
    def _create_subagent_context(
        self,
        parent_context: ToolUseContext,
        agent_id: str,
        agent_type: AgentType,
        allowed_tools: list
    ) -> ToolUseContext:
        """
        Create isolated context for sub-agent.
        
        Key: setAppState is no-op for async agents (Claude CLI Tool.ts line 186-191).
        """
        # Build permission context with filtered tools
        perm_context = ToolPermissionContext(mode="default")
        perm_context.always_allow_rules = {t: ["*"] for t in allowed_tools}
        
        return ToolUseContext(
            conversation_id=parent_context.conversation_id,
            agent_id=agent_id,
            agent_type=agent_type,
            # Async agents use special callback to reach root store
            set_app_state_for_tasks=parent_context.set_app_state_for_tasks,
            # Inherit read-only file cache for performance
            read_file_state=parent_context.read_file_state,
            # Filtered permission context
            permission_context=perm_context
        )
    
    async def _spawn_agent(
        self,
        agent_id: str,
        prompt: str,
        tools: list,
        context: ToolUseContext,
        task_id: str
    ):
        """
        Actually spawn the agent.
        
        This is a placeholder - real implementation would:
        1. Create agent process/thread
        2. Set up message passing
        3. Start agent execution loop
        """
        # TODO: Integrate with Cortex's agent system
        # For now, just log
        print(f"[AgentTool] Spawning {context.agent_type.value} agent {agent_id}")
        print(f"[AgentTool] Task: {prompt[:60]}...")
        print(f"[AgentTool] Tools: {tools}")
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        agent_type = args.get("agent_type", "async")
        return f"Spawning {agent_type} agent"
    
    def is_destructive(self, args: Dict) -> bool:
        """Spawning agents creates persistent workers."""
        return True


class TaskOutputTool(ClaudeTool):
    """
    Record output from an async agent task.
    
    Claude CLI TaskOutputTool equivalent.
    
    BLOCKED FOR ASYNC AGENTS (Claude CLI constants/tools.ts line 36-37).
    
    This tool is used by async agents to return results without
    direct chat output. The parent agent retrieves results via task_get.
    
    Example tool call:
    {
        "task_id": "task_789.012",
        "content": "Analysis complete: 3 security issues found..."
    }
    
    Returns:
    {
        "task_id": "task_789.012",
        "recorded": true,
        "content_length": 1500
    }
    """
    
    name = "task_output"
    description = "Record output from an async agent task (used by background agents)"
    capabilities = {ToolCapability.WRITE, ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="task_id",
            param_type="string",
            description="ID of the task this output belongs to",
            required=True
        ),
        ToolParameter(
            name="content",
            param_type="string",
            description="The output content/result",
            required=True
        )
    ]
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Callable[[Dict], None] = None
    ):
        """Execute task_output tool."""
        try:
            task_id = args.get("task_id")
            content = args.get("content", "")
            
            if not task_id:
                return error_result("Missing required parameter: task_id")
            
            # Get task manager
            task_manager = get_task_manager()
            
            # Verify task exists
            task = task_manager.get_task(task_id)
            if not task:
                return error_result(f"Task '{task_id}' not found")
            
            # Verify this agent owns the task
            if task.agent_id and task.agent_id != context.agent_id:
                return error_result(
                    f"Task '{task_id}' is assigned to agent '{task.agent_id}', "
                    f"not '{context.agent_id}'"
                )
            
            # Store the output
            task_manager.update_task(
                task_id=task_id,
                result=content,
                status=TaskStatus.COMPLETED
            )
            
            return success_result(
                result={
                    "task_id": task_id,
                    "recorded": True,
                    "content_length": len(content)
                },
                metadata={
                    "task_id": task_id,
                    "agent_id": context.agent_id
                }
            )
            
        except Exception as e:
            return error_result(f"Failed to record task output: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        return f"Recording output for task {args.get('task_id', 'unknown')[:15]}"


class SendMessageTool(ClaudeTool):
    """
    Send a message to another agent.
    
    Claude CLI SendMessageTool equivalent.
    
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS includes this (constants/tools.ts line 77-88).
    
    Enables inter-agent communication for coordination.
    Messages are queued and retrieved by recipient agents.
    
    Example tool call:
    {
        "recipient_agent_id": "agent_def456",
        "content": "I've completed the file analysis. Starting security scan now."
    }
    
    Returns:
    {
        "sent": true,
        "recipient": "agent_def456",
        "message_id": "msg_abc123"
    }
    """
    
    name = "send_message"
    description = "Send a message to another agent for coordination"
    capabilities = {ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="recipient_agent_id",
            param_type="string",
            description="ID of the agent to send message to",
            required=True
        ),
        ToolParameter(
            name="content",
            param_type="string",
            description="Message content",
            required=True
        ),
        ToolParameter(
            name="task_id",
            param_type="string",
            description="Optional: associate with a task",
            required=False,
            default=None
        )
    ]
    
    # Message queue (in-memory, should be database-backed in production)
    _message_queue: Dict[str, list] = {}
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Callable[[Dict], None] = None
    ):
        """Execute send_message tool."""
        try:
            recipient = args.get("recipient_agent_id")
            content = args.get("content", "")
            task_id = args.get("task_id")
            
            if not recipient:
                return error_result("Missing required parameter: recipient_agent_id")
            
            # Generate message ID
            message_id = f"msg_{uuid.uuid4().hex[:12]}"
            
            # Queue message
            message = {
                "id": message_id,
                "sender": context.agent_id or "main",
                "recipient": recipient,
                "content": content,
                "task_id": task_id,
                "timestamp": str(uuid.uuid1().time)  # Simple timestamp
            }
            
            # Add to recipient's queue
            if recipient not in self._message_queue:
                self._message_queue[recipient] = []
            self._message_queue[recipient].append(message)
            
            return success_result(
                result={
                    "sent": True,
                    "recipient": recipient,
                    "message_id": message_id
                },
                metadata={
                    "message_id": message_id,
                    "sender": context.agent_id or "main"
                }
            )
            
        except Exception as e:
            return error_result(f"Failed to send message: {str(e)}")
    
    @classmethod
    def get_messages_for_agent(cls, agent_id: str) -> list:
        """Get queued messages for an agent (called by agent to check inbox)."""
        messages = cls._message_queue.get(agent_id, [])
        # Clear after retrieval
        cls._message_queue[agent_id] = []
        return messages
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        recipient = args.get("recipient_agent_id", "unknown")
        return f"Sending message to {recipient[:15]}"


# Export all agentic tools
from .advanced_agent_tools import (
    MultiAgentTool,
    AgentMemoryTool,
    AgentPlanningTool,
    AgentReasoningTool,
    AgentLearningTool,
    AgentEvaluationTool,
    AgentOrchestrationTool,
)

__all__ = [
    "AgentTool",
    "TaskOutputTool",
    "SendMessageTool",
    # Advanced agent tools
    "MultiAgentTool",
    "AgentMemoryTool",
    "AgentPlanningTool",
    "AgentReasoningTool",
    "AgentLearningTool",
    "AgentEvaluationTool",
    "AgentOrchestrationTool",
]
