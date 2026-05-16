# ------------------------------------------------------------
# TestingPermissionTool.py
# Python conversion of TestingPermissionTool.tsx (lines 1-74)
# 
# A testing-only tool that always asks for permission before executing.
# Used for end-to-end testing of permission dialogs.
# ------------------------------------------------------------

from typing import TypedDict, Any, Dict

# ============================================================
# LOCAL IMPORTS
# ============================================================

try:
    from ..Tool import build_tool, ToolDef
except ImportError:
    # Stub if dependencies don't exist yet
    def build_tool(config):
        """Stub build_tool function."""
        return type('TestingPermissionTool', (), config)
    
    class ToolDef:
        """Stub ToolDef type."""
        pass


# ============================================================
# TOOL CONSTANTS
# ============================================================

NAME = "TestingPermission"


# ============================================================
# INPUT SCHEMA
# ============================================================

class InputSchema(TypedDict, total=False):
    """Input schema for TestingPermissionTool (empty - no parameters required)."""
    pass


# ============================================================
# TESTING PERMISSION TOOL
# ============================================================

class TestingPermissionTool:
    """
    Test tool that always asks for permission before executing.
    
    This tool is designed for end-to-end testing of the permission dialog system.
    It will always trigger a permission request popup when called by the model.
    """
    
    name = NAME
    max_result_size_chars = 100_000
    strict = True
    
    # ------------------------------------------------------------------
    # Public metadata helpers
    # ------------------------------------------------------------------
    
    @staticmethod
    async def description() -> str:
        """Get tool description."""
        return "Test tool that always asks for permission"
    
    @staticmethod
    async def prompt() -> str:
        """Get tool prompt/instructions."""
        return "Test tool that always asks for permission before executing. Used for end-to-end testing."
    
    @staticmethod
    def user_facing_name() -> str:
        """Get user-facing name for the tool."""
        return "TestingPermission"
    
    # ------------------------------------------------------------------
    # Schema accessors
    # ------------------------------------------------------------------
    
    @staticmethod
    def input_schema() -> type:
        """Return input schema type."""
        return InputSchema
    
    # ------------------------------------------------------------------
    # Tool capability flags
    # ------------------------------------------------------------------
    
    @staticmethod
    def is_enabled() -> bool:
        """Check if tool is enabled (only in test mode)."""
        # In production, this returns False
        # Set environment variable or config to enable in tests
        import os
        return os.environ.get("NODE_ENV") == "test"
    
    @staticmethod
    def is_concurrency_safe() -> bool:
        """Check if tool is safe to run concurrently."""
        return True
    
    @staticmethod
    def is_read_only() -> bool:
        """Check if tool is read-only."""
        return True
    
    # ------------------------------------------------------------------
    # Permission handling
    # ------------------------------------------------------------------
    
    @staticmethod
    async def check_permissions(input_: Dict, context: Any) -> Dict[str, Any]:
        """
        Check permissions for this tool.
        
        This tool ALWAYS requires permission - it will always show a dialog.
        
        Returns:
            Permission decision with 'ask' behavior
        """
        # This tool always requires permission
        return {
            "behavior": "ask",
            "message": "Run test?",
        }
    
    # ------------------------------------------------------------------
    # Message rendering (all return None - no custom UI messages)
    # ------------------------------------------------------------------
    
    @staticmethod
    def render_tool_use_message() -> None:
        """Render tool use message."""
        return None
    
    @staticmethod
    def render_tool_use_progress_message() -> None:
        """Render tool use progress message."""
        return None
    
    @staticmethod
    def render_tool_use_queued_message() -> None:
        """Render tool use queued message."""
        return None
    
    @staticmethod
    def render_tool_use_rejected_message() -> None:
        """Render tool use rejected message."""
        return None
    
    @staticmethod
    def render_tool_result_message() -> None:
        """Render tool result message."""
        return None
    
    @staticmethod
    def render_tool_use_error_message() -> None:
        """Render tool use error message."""
        return None
    
    # ------------------------------------------------------------------
    # Core execution logic
    # ------------------------------------------------------------------
    
    @staticmethod
    async def call(input_: Dict, context: Any) -> Dict[str, Any]:
        """
        Execute the test tool.
        
        Args:
            input_: Tool input (empty for this tool)
            context: Tool execution context
            
        Returns:
            Execution result
        """
        return {
            "data": f"{NAME} executed successfully"
        }
    
    # ------------------------------------------------------------------
    # Result formatting
    # ------------------------------------------------------------------
    
    @staticmethod
    def map_tool_result_to_block(result: Any, tool_use_id: str) -> Dict[str, Any]:
        """
        Map tool result to LLM-compatible block format.
        
        Args:
            result: Tool execution result
            tool_use_id: Unique identifier for this tool use
            
        Returns:
            Formatted tool result block
        """
        return {
            "type": "tool_result",
            "content": str(result),
            "tool_use_id": tool_use_id,
        }


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "TestingPermissionTool",
    "NAME",
    "InputSchema",
]
