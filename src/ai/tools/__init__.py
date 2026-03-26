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
from .base_tool import BaseTool, ToolResult

__all__ = ['BaseTool', 'ToolResult']
