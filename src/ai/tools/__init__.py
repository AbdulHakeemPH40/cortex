"""
Modular Tool Architecture for Cortex IDE

Tools are organized into categories:
- file_tools: File operations (read, write, edit)
- search_tools: Code search and pattern matching (grep, glob)  
- web_tools: Web operations (fetch, websearch)
- system_tools: System operations (run_command, shell)
- interaction_tools: User interaction (question_tool)

Note: ToolRegistry remains in src.ai.tools (the module) to avoid circular imports.
This package only contains modular tool implementations.
"""

# Only export base classes from this package
from pathlib import Path
from typing import Optional

from .base_tool import BaseTool, ToolResult

__all__ = ['BaseTool', 'ToolResult', 'get_tool_registry']


_tool_registry_singleton = None


def get_tool_registry(project_root: Optional[str] = None):
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
