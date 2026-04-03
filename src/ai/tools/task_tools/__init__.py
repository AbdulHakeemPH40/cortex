"""
Task Create Tool - Claude CLI Compatible

Creates async background tasks for agent coordination.
Part of the agentic tools suite for multi-agent support.
"""

from typing import Dict, Any, Callable

from ..claude_tool import ClaudeTool, ToolUseContext, ToolCapability
from ..base_tool import ToolParameter, success_result, error_result
from .models import get_task_manager, TaskStatus


class TaskCreateTool(ClaudeTool):
    """
    Create a new async background task.
    
    Claude CLI TaskCreateTool equivalent.
    
    This tool creates a task that can be executed by a background agent.
    The task starts in PENDING status and must be claimed by an agent
    to transition to RUNNING.
    
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS includes this (see constants/tools.ts).
    
    Example tool call:
    {
        "description": "Analyze the codebase for security issues",
        "parent_task_id": "task_123.456"  // Optional: for sub-tasks
    }
    
    Returns:
    {
        "task_id": "task_789.012",
        "status": "pending",
        "created_at": "2026-04-01T14:30:00"
    }
    """
    
    name = "task_create"
    description = "Create a new async background task that can be executed by a background agent"
    capabilities = {ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="description",
            param_type="string",
            description="Description of what the task should accomplish",
            required=True
        ),
        ToolParameter(
            name="parent_task_id",
            param_type="string",
            description="Optional parent task ID if this is a sub-task",
            required=False,
            default=None
        ),
        ToolParameter(
            name="tools",
            param_type="array",
            description="List of tool names this task is allowed to use",
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
        """Execute task_create tool."""
        try:
            description = args.get("description", "")
            parent_task_id = args.get("parent_task_id")
            allowed_tools = args.get("tools", [])
            
            # Validate parent task if specified
            if parent_task_id:
                task_manager = get_task_manager()
                parent = task_manager.get_task(parent_task_id)
                if not parent:
                    return error_result(
                        f"Parent task '{parent_task_id}' not found"
                    )
            
            # Create the task
            task_manager = get_task_manager()
            task = task_manager.create_task(
                description=description,
                parent_task_id=parent_task_id,
                metadata={
                    "requested_by": context.agent_id or "main",
                    "allowed_tools": allowed_tools,
                    "conversation_id": context.conversation_id
                }
            )
            
            return success_result(
                result={
                    "task_id": task.id,
                    "status": task.status.value,
                    "created_at": task.created_at.isoformat(),
                    "description": task.description[:100]  # Truncated for display
                },
                metadata={
                    "task_id": task.id,
                    "parent_task_id": parent_task_id
                }
            )
            
        except Exception as e:
            return error_result(f"Failed to create task: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        desc = args.get("description", "")
        return f"Creating task: {desc[:40]}{'...' if len(desc) > 40 else ''}"


class TaskGetTool(ClaudeTool):
    """
    Get task status and result by ID.
    
    Claude CLI TaskGetTool equivalent.
    
    Queries the current state of a task including:
    - Status (pending, running, completed, failed, cancelled)
    - Result (if completed)
    - Error message (if failed)
    - Assigned agent (if running)
    
    Example tool call:
    {
        "task_id": "task_789.012"
    }
    
    Returns:
    {
        "id": "task_789.012",
        "description": "Analyze the codebase...",
        "status": "completed",
        "result": "Found 3 security issues...",
        "agent_id": "agent_123",
        "created_at": "2026-04-01T14:30:00",
        "updated_at": "2026-04-01T14:35:00"
    }
    """
    
    name = "task_get"
    description = "Get the status and result of a task by its ID"
    capabilities = {ToolCapability.READ, ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="task_id",
            param_type="string",
            description="ID of the task to query",
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
        """Execute task_get tool."""
        try:
            task_id = args.get("task_id")
            
            if not task_id:
                return error_result("Missing required parameter: task_id")
            
            task_manager = get_task_manager()
            task = task_manager.get_task(task_id)
            
            if not task:
                return error_result(f"Task '{task_id}' not found")
            
            return success_result(
                result={
                    "id": task.id,
                    "description": task.description,
                    "status": task.status.value,
                    "result": task.result,
                    "error_message": task.error_message,
                    "agent_id": task.agent_id,
                    "parent_task_id": task.parent_task_id,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None
                },
                metadata={"task_id": task_id}
            )
            
        except Exception as e:
            return error_result(f"Failed to get task: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        return f"Getting task status: {args.get('task_id', 'unknown')[:20]}"


class TaskListTool(ClaudeTool):
    """
    List tasks with optional filtering.
    
    Claude CLI TaskListTool equivalent.
    
    Returns a list of tasks filtered by:
    - Status (pending, running, completed, failed, cancelled)
    - Agent ID (tasks assigned to specific agent)
    
    Results are sorted by creation time (newest first).
    
    Example tool call:
    {
        "status": "running",
        "agent_id": "agent_123"  // Optional
    }
    
    Returns:
    {
        "tasks": [
            {
                "id": "task_789.012",
                "description": "Analyze the codebase...",
                "status": "running",
                "agent_id": "agent_123"
            },
            ...
        ],
        "count": 5
    }
    """
    
    name = "task_list"
    description = "List tasks with optional status and agent filtering"
    capabilities = {ToolCapability.READ, ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="status",
            param_type="string",
            description="Filter by status: pending, running, completed, failed, cancelled",
            required=False,
            default=None
        ),
        ToolParameter(
            name="agent_id",
            param_type="string",
            description="Filter by assigned agent ID",
            required=False,
            default=None
        ),
        ToolParameter(
            name="parent_task_id",
            param_type="string",
            description="Filter by parent task ID (use null for top-level tasks)",
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
        """Execute task_list tool."""
        try:
            status_str = args.get("status")
            agent_id = args.get("agent_id")
            parent_task_id = args.get("parent_task_id")
            
            # Convert status string to enum
            status = None
            if status_str:
                try:
                    status = TaskStatus(status_str)
                except ValueError:
                    return error_result(f"Invalid status: {status_str}")
            
            task_manager = get_task_manager()
            tasks = task_manager.list_tasks(
                status=status,
                agent_id=agent_id,
                parent_task_id=parent_task_id
            )
            
            # Format for display
            task_summaries = []
            for task in tasks:
                task_summaries.append({
                    "id": task.id,
                    "description": task.description[:50] + ("..." if len(task.description) > 50 else ""),
                    "status": task.status.value,
                    "agent_id": task.agent_id,
                    "created_at": task.created_at.isoformat() if task.created_at else None
                })
            
            return success_result(
                result={
                    "tasks": task_summaries,
                    "count": len(task_summaries)
                },
                metadata={
                    "status_filter": status_str,
                    "agent_filter": agent_id
                }
            )
            
        except Exception as e:
            return error_result(f"Failed to list tasks: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        status = args.get("status", "all")
        return f"Listing {status} tasks"


class TaskUpdateTool(ClaudeTool):
    """
    Update task metadata.
    
    Claude CLI TaskUpdateTool equivalent.
    
    Updates task fields including:
    - Status (for manual state transitions)
    - Result (for async agent output)
    - Error message (for failure reporting)
    
    Note: Status updates should typically be done automatically
    by the task system, not manually.
    
    Example tool call:
    {
        "task_id": "task_789.012",
        "result": "Analysis complete: 3 issues found..."
    }
    
    Returns:
    {
        "task_id": "task_789.012",
        "updated": true,
        "fields_updated": ["result"]
    }
    """
    
    name = "task_update"
    description = "Update task metadata such as result or error message"
    capabilities = {ToolCapability.WRITE, ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="task_id",
            param_type="string",
            description="ID of the task to update",
            required=True
        ),
        ToolParameter(
            name="result",
            param_type="string",
            description="Task result/output (for async agents)",
            required=False,
            default=None
        ),
        ToolParameter(
            name="error_message",
            param_type="string",
            description="Error message if task failed",
            required=False,
            default=None
        ),
        ToolParameter(
            name="agent_id",
            param_type="string",
            description="Agent ID to assign/unassign (null to unassign)",
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
        """Execute task_update tool."""
        try:
            task_id = args.get("task_id")
            
            if not task_id:
                return error_result("Missing required parameter: task_id")
            
            # Collect updates
            updates = {}
            fields_updated = []
            
            if "result" in args and args["result"] is not None:
                updates["result"] = args["result"]
                fields_updated.append("result")
            
            if "error_message" in args and args["error_message"] is not None:
                updates["error_message"] = args["error_message"]
                fields_updated.append("error_message")
            
            if "agent_id" in args:
                updates["agent_id"] = args["agent_id"]
                fields_updated.append("agent_id")
            
            if not updates:
                return error_result("No fields to update provided")
            
            task_manager = get_task_manager()
            task = task_manager.update_task(task_id, **updates)
            
            if not task:
                return error_result(f"Task '{task_id}' not found")
            
            return success_result(
                result={
                    "task_id": task_id,
                    "updated": True,
                    "fields_updated": fields_updated,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None
                },
                metadata={"task_id": task_id}
            )
            
        except Exception as e:
            return error_result(f"Failed to update task: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        return f"Updating task: {args.get('task_id', 'unknown')[:20]}"


class TaskStopTool(ClaudeTool):
    """
    Cancel a running or pending task.
    
    Claude CLI TaskStopTool equivalent.
    
    COORDINATOR_MODE_ALLOWED_TOOLS includes this (see constants/tools.ts).
    
    This stops a task's execution. If the task is already completed,
    failed, or cancelled, this has no effect.
    
    Example tool call:
    {
        "task_id": "task_789.012"
    }
    
    Returns:
    {
        "task_id": "task_789.012",
        "cancelled": true,
        "previous_status": "running"
    }
    """
    
    name = "task_stop"
    description = "Cancel a running or pending task"
    capabilities = {ToolCapability.EXECUTE, ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="task_id",
            param_type="string",
            description="ID of the task to cancel",
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
        """Execute task_stop tool."""
        try:
            task_id = args.get("task_id")
            
            if not task_id:
                return error_result("Missing required parameter: task_id")
            
            task_manager = get_task_manager()
            
            # Get task for previous status
            task = task_manager.get_task(task_id)
            if not task:
                return error_result(f"Task '{task_id}' not found")
            
            previous_status = task.status.value
            
            # Cancel the task
            cancelled = task_manager.cancel_task(task_id)
            
            if not cancelled:
                return error_result(
                    f"Task '{task_id}' could not be cancelled (status: {previous_status})"
                )
            
            return success_result(
                result={
                    "task_id": task_id,
                    "cancelled": True,
                    "previous_status": previous_status
                },
                metadata={"task_id": task_id}
            )
            
        except Exception as e:
            return error_result(f"Failed to stop task: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        """Return activity description for UI."""
        return f"Stopping task: {args.get('task_id', 'unknown')[:20]}"
    
    def is_destructive(self, args: Dict) -> bool:
        """Stopping a task is destructive (terminates work)."""
        return True
