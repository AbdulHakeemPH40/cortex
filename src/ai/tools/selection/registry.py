"""
Tool Registry for Cortex AI Agent
Manages all available tools and their definitions
"""

from typing import Dict, List, Optional
from src.ai.tools.selection.types import ToolDefinition, ToolCategory
from src.utils.logger import get_logger

log = get_logger("tool_registry")


class ToolRegistry:
    """
    Registry of all available tools in the system.
    Provides centralized access to tool definitions.
    """
    
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_builtin_tools()
        log.info("ToolRegistry initialized with %d tools", len(self._tools))
    
    def _register_builtin_tools(self):
        """Register all built-in tools."""
        
        # File Tools
        self.register(ToolDefinition(
            name="read",
            description="Read the contents of a file",
            category=ToolCategory.FILE,
            keywords=["read", "view", "show", "file", "contents", "open"],
            required_permissions=["file_read"],
            parameters={
                "file_path": {"type": "string", "required": True},
                "offset": {"type": "integer", "required": False},
                "limit": {"type": "integer", "required": False}
            },
            estimated_time_ms=100
        ))
        
        self.register(ToolDefinition(
            name="write",
            description="Write content to a file (creates or overwrites)",
            category=ToolCategory.FILE,
            keywords=["write", "create", "save", "file", "new"],
            required_permissions=["file_write"],
            parameters={
                "file_path": {"type": "string", "required": True},
                "content": {"type": "string", "required": True}
            },
            estimated_time_ms=200
        ))
        
        self.register(ToolDefinition(
            name="edit",
            description="Make precise edits to a file using search and replace",
            category=ToolCategory.FILE,
            keywords=["edit", "modify", "change", "update", "replace", "fix"],
            required_permissions=["file_write"],
            parameters={
                "file_path": {"type": "string", "required": True},
                "old_string": {"type": "string", "required": True},
                "new_string": {"type": "string", "required": True}
            },
            estimated_time_ms=300,
            complexity="medium"
        ))
        
        # Search Tools
        self.register(ToolDefinition(
            name="grep",
            description="Search for patterns in files using regex",
            category=ToolCategory.SEARCH,
            keywords=["search", "find", "grep", "pattern", "regex", "locate"],
            required_permissions=["file_read"],
            parameters={
                "pattern": {"type": "string", "required": True},
                "path": {"type": "string", "required": False},
                "include": {"type": "string", "required": False}
            },
            estimated_time_ms=500
        ))
        
        self.register(ToolDefinition(
            name="glob",
            description="Find files matching a pattern",
            category=ToolCategory.SEARCH,
            keywords=["find", "glob", "files", "pattern", "match", "list"],
            required_permissions=["file_read"],
            parameters={
                "pattern": {"type": "string", "required": True},
                "path": {"type": "string", "required": False}
            },
            estimated_time_ms=200
        ))
        
        self.register(ToolDefinition(
            name="lsp",
            description="Use Language Server Protocol for code intelligence",
            category=ToolCategory.SEARCH,
            keywords=["lsp", "definition", "references", "symbols", "code"],
            required_permissions=["file_read"],
            parameters={
                "command": {"type": "string", "required": True},
                "file_path": {"type": "string", "required": True},
                "line": {"type": "integer", "required": True},
                "column": {"type": "integer", "required": True}
            },
            estimated_time_ms=1000,
            complexity="complex"
        ))
        
        # System Tools
        self.register(ToolDefinition(
            name="bash",
            description="Execute shell commands",
            category=ToolCategory.SYSTEM,
            keywords=["run", "execute", "command", "bash", "shell", "terminal", "cmd"],
            required_permissions=["terminal_execute"],
            parameters={
                "command": {"type": "string", "required": True},
                "cwd": {"type": "string", "required": False},
                "timeout": {"type": "integer", "required": False}
            },
            estimated_time_ms=2000,
            complexity="medium"
        ))
        
        self.register(ToolDefinition(
            name="task",
            description="Create and manage background tasks",
            category=ToolCategory.SYSTEM,
            keywords=["task", "background", "process", "job", "async"],
            required_permissions=["terminal_execute"],
            parameters={
                "command": {"type": "string", "required": True},
                "name": {"type": "string", "required": False}
            },
            estimated_time_ms=500
        ))
        
        # Web Tools
        self.register(ToolDefinition(
            name="websearch",
            description="Search the web for information",
            category=ToolCategory.WEB,
            keywords=["search", "web", "google", "find", "online", "internet"],
            required_permissions=["network_access"],
            parameters={
                "query": {"type": "string", "required": True},
                "num_results": {"type": "integer", "required": False}
            },
            estimated_time_ms=3000,
            complexity="medium"
        ))
        
        self.register(ToolDefinition(
            name="webfetch",
            description="Fetch content from a URL",
            category=ToolCategory.WEB,
            keywords=["fetch", "download", "url", "web", "page", "get"],
            required_permissions=["network_access"],
            parameters={
                "url": {"type": "string", "required": True},
                "format": {"type": "string", "required": False}
            },
            estimated_time_ms=2000
        ))
        
        # Interaction Tools
        self.register(ToolDefinition(
            name="question",
            description="Ask the user a question",
            category=ToolCategory.INTERACTION,
            keywords=["ask", "question", "clarify", "confirm", "input"],
            required_permissions=[],
            parameters={
                "text": {"type": "string", "required": True},
                "options": {"type": "array", "required": False}
            },
            estimated_time_ms=5000,
            complexity="medium"
        ))
    
    def register(self, tool: ToolDefinition):
        """Register a new tool."""
        self._tools[tool.name] = tool
        log.debug("Registered tool: %s", tool.name)
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def list_all(self) -> List[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())
    
    def list_by_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """List tools by category."""
        return [t for t in self._tools.values() if t.category == category]
    
    def search(self, keyword: str) -> List[ToolDefinition]:
        """Search tools by keyword."""
        keyword_lower = keyword.lower()
        results = []
        
        for tool in self._tools.values():
            # Check name
            if keyword_lower in tool.name.lower():
                results.append(tool)
                continue
            
            # Check description
            if keyword_lower in tool.description.lower():
                results.append(tool)
                continue
            
            # Check keywords
            if any(keyword_lower in k.lower() for k in tool.keywords):
                results.append(tool)
                continue
        
        return results
    
    def get_by_permission(self, permission: str) -> List[ToolDefinition]:
        """Get tools requiring a specific permission."""
        return [t for t in self._tools.values() if permission in t.required_permissions]


# Singleton instance
_tool_registry = None


def get_tool_registry() -> ToolRegistry:
    """Get singleton instance of ToolRegistry."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry
