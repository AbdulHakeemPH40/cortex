# tasks/LocalAgentTask/LocalAgentTask.py
# Stub file for local agent task management

from typing import Any, Dict, Optional


async def complete_async_agent(result: Any, set_app_state: callable) -> None:
    """Mark async agent as completed."""
    pass


def create_activity_description_resolver(tools: list) -> callable:
    """Create activity description resolver."""
    return lambda tool_use: "Activity"


def create_progress_tracker() -> Dict[str, Any]:
    """Create progress tracker."""
    return {"token_count": 0, "tool_use_count": 0}


async def enqueue_agent_notification(notification: Dict[str, Any]) -> None:
    """Enqueue agent notification."""
    pass


async def fail_async_agent(agent_id: str, error: str, set_app_state: callable) -> None:
    """Mark async agent as failed."""
    pass


def get_progress_update(tracker: Dict[str, Any]) -> Dict[str, Any]:
    """Get progress update from tracker."""
    return tracker


def get_token_count_from_tracker(tracker: Dict[str, Any]) -> int:
    """Get token count from tracker."""
    return tracker.get("token_count", 0)


async def kill_async_agent(agent_id: str, set_app_state: callable) -> None:
    """Kill an async agent."""
    pass


def register_agent_foreground(params: Dict[str, Any]) -> Dict[str, Any]:
    """Register foreground agent."""
    return {
        "task_id": params.get("agent_id", "unknown"),
        "background_signal": None,
        "cancel_auto_background": None,
    }


def register_async_agent(params: Dict[str, Any]) -> Dict[str, Any]:
    """Register async agent."""
    return {
        "agent_id": params.get("agent_id", "unknown"),
        "abort_controller": None,
    }


def unregister_agent_foreground(task_id: str, set_app_state: callable) -> None:
    """Unregister foreground agent."""
    pass


def update_agent_progress(task_id: str, progress: Dict[str, Any], set_app_state: callable) -> None:
    """Update agent progress."""
    pass


def update_progress_from_message(tracker: Dict[str, Any], message: Any, resolver: callable, tools: list) -> None:
    """Update progress from message."""
    pass


__all__ = [
    "complete_async_agent",
    "create_activity_description_resolver",
    "create_progress_tracker",
    "enqueue_agent_notification",
    "fail_async_agent",
    "get_progress_update",
    "get_token_count_from_tracker",
    "kill_async_agent",
    "register_agent_foreground",
    "register_async_agent",
    "unregister_agent_foreground",
    "update_agent_progress",
    "update_progress_from_message",
]
