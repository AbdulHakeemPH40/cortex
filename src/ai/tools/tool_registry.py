"""
Claude CLI-Compatible Tool Registry for Cortex IDE

Manages tool availability, filtering, and conditional loading.
Mirrors getAllBaseTools() and assembleToolPool() from Claude CLI tools.ts
"""

from typing import Dict, List, Optional, Type, Callable
import platform

from .claude_tool import ClaudeTool, ToolPermissionContext, AgentType
from .constants import (
    ASYNC_AGENT_ALLOWED_TOOLS,
    COORDINATOR_MODE_ALLOWED_TOOLS,
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS,
    ALL_AGENT_DISALLOWED_TOOLS
)


class ToolRegistry:
    """
    Claude CLI-style tool registry.
    
    Manages:
    - Core tools (always available)
    - Conditional tools (feature flags)
    - MCP tools (from external servers)
    - Tool filtering by agent type and permissions
    
    Mirrors patterns from Claude CLI tools.ts lines 193-367
    """
    
    def __init__(self):
        self._core_tools: Dict[str, ClaudeTool] = {}
        self._conditional_tools: List[tuple] = []
        self._mcp_tools: Dict[str, ClaudeTool] = {}
        self._feature_flags: Dict[str, bool] = {}
    
    def set_feature_flag(self, flag: str, enabled: bool):
        """Set a feature flag for conditional tool loading."""
        self._feature_flags[flag] = enabled
    
    def is_feature_enabled(self, flag: str) -> bool:
        """Check if a feature flag is enabled."""
        return self._feature_flags.get(flag, False)
    
    def register(self, tool: ClaudeTool):
        """
        Register a core tool (always available if is_enabled() returns True).
        
        Args:
            tool: Tool instance to register
        """
        self._core_tools[tool.name] = tool
        # Register aliases
        for alias in tool.aliases:
            self._core_tools[alias] = tool
    
    def register_conditional(
        self,
        tool_class: Type[ClaudeTool],
        condition: Callable[[], bool],
        feature_flag: Optional[str] = None
    ):
        """
        Register a tool that appears only when condition is met.
        
        Mirrors pattern from Claude CLI tools.ts lines 16-49:
        ```typescript
        const SleepTool = feature('PROACTIVE') || feature('KAIROS')
          ? require('./tools/SleepTool/SleepTool.js').SleepTool
          : null
        ```
        
        Args:
            tool_class: Tool class to instantiate when condition is true
            condition: Function returning True if tool should be available
            feature_flag: Optional feature flag name for tracking
        """
        self._conditional_tools.append((tool_class, condition, feature_flag))
    
    def register_mcp_tool(self, tool: ClaudeTool):
        """
        Register an MCP (Model Context Protocol) tool from external server.
        
        Args:
            tool: MCP tool instance
        """
        tool.is_mcp = True
        self._mcp_tools[tool.name] = tool
    
    def get_all_tools(
        self,
        permission_context: Optional[ToolPermissionContext] = None
    ) -> List[ClaudeTool]:
        """
        Get all available tools (THE SOURCE OF TRUTH).
        
        Mirrors getAllBaseTools() from Claude CLI tools.ts lines 193-251.
        
        Returns:
            List of all available tools, filtered by:
            - is_enabled() check
            - Conditional tool conditions
            - Permission deny rules
        """
        tools: List[ClaudeTool] = []
        
        # Add core tools that are enabled
        for tool in self._core_tools.values():
            if tool.is_enabled() and tool not in tools:
                tools.append(tool)
        
        # Add conditional tools
        for tool_class, condition, flag in self._conditional_tools:
            try:
                if condition():
                    tool = tool_class()
                    if tool.is_enabled() and tool not in tools:
                        tools.append(tool)
            except Exception as e:
                # Log but don't fail if a conditional tool fails to load
                print(f"[ToolRegistry] Failed to load conditional tool {tool_class.__name__}: {e}")
        
        # Filter by permissions
        if permission_context:
            tools = self._filter_by_deny_rules(tools, permission_context)
        
        # Deduplicate by name (built-ins take precedence)
        seen = set()
        unique_tools = []
        for tool in tools:
            if tool.name not in seen:
                seen.add(tool.name)
                unique_tools.append(tool)
        
        return unique_tools
    
    def get_tools_for_agent(
        self,
        agent_type: AgentType,
        permission_context: Optional[ToolPermissionContext] = None
    ) -> List[ClaudeTool]:
        """
        Filter tools based on agent type.
        
        Mirrors filterToolsForAgent from Claude CLI tools.ts.
        
        From Claude CLI constants/tools.ts:
        - ASYNC_AGENT_ALLOWED_TOOLS: Limited set for background agents
        - COORDINATOR_MODE_ALLOWED_TOOLS: Only agent management tools
        - IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: Async tools + team coordination
        
        Args:
            agent_type: Type of agent (MAIN, ASYNC, COORDINATOR, IN_PROCESS)
            permission_context: Optional permission filter
            
        Returns:
            Filtered list of tools appropriate for agent type
        """
        all_tools = self.get_all_tools(permission_context)
        
        # Get allowed set based on agent type
        if agent_type == AgentType.ASYNC:
            allowed = ASYNC_AGENT_ALLOWED_TOOLS
        elif agent_type == AgentType.COORDINATOR:
            allowed = COORDINATOR_MODE_ALLOWED_TOOLS
        elif agent_type == AgentType.IN_PROCESS:
            # In-process gets async tools + teammate tools
            allowed = ASYNC_AGENT_ALLOWED_TOOLS | IN_PROCESS_TEAMMATE_ALLOWED_TOOLS
        else:  # AgentType.MAIN
            # Main thread gets all tools except disallowed for agents
            all_names = {t.name for t in all_tools}
            allowed = all_names - ALL_AGENT_DISALLOWED_TOOLS
        
        return [t for t in all_tools if t.name in allowed]
    
    def assemble_tool_pool(
        self,
        permission_context: ToolPermissionContext,
        include_mcp: bool = True
    ) -> List[ClaudeTool]:
        """
        Combine built-in tools with MCP tools.
        
        Mirrors assembleToolPool from Claude CLI tools.ts lines 345-367.
        
        This is the single source of truth for combining built-in tools 
        with MCP tools. Ensures consistent tool pool assembly across:
        - Main chat interface
        - Async agent execution
        - Coordinator mode
        
        Args:
            permission_context: Permission context for filtering
            include_mcp: Whether to include MCP tools
            
        Returns:
            Combined, deduplicated list of built-in and MCP tools
        """
        # Get built-in tools
        built_in = self.get_all_tools(permission_context)
        
        if not include_mcp:
            return built_in
        
        # Get MCP tools
        mcp_tools = list(self._mcp_tools.values())
        
        # Filter MCP tools by deny rules
        allowed_mcp = self._filter_by_deny_rules(mcp_tools, permission_context)
        
        # Sort each partition for cache stability
        # Claude CLI puts built-ins first as a contiguous prefix for caching
        built_in_sorted = sorted(built_in, key=lambda t: t.name)
        mcp_sorted = sorted(allowed_mcp, key=lambda t: t.name)
        
        # Combine with built-ins taking precedence
        combined = built_in_sorted + mcp_sorted
        
        # Deduplicate by name
        seen = set()
        result = []
        for tool in combined:
            if tool.name not in seen:
                seen.add(tool.name)
                result.append(tool)
        
        return result
    
    def find_tool(
        self,
        name: str,
        permission_context: Optional[ToolPermissionContext] = None
    ) -> Optional[ClaudeTool]:
        """
        Find a tool by name or alias.
        
        Args:
            name: Tool name or alias to find
            permission_context: Optional permission filter
            
        Returns:
            Tool instance if found, None otherwise
        """
        tools = self.get_all_tools(permission_context)
        
        for tool in tools:
            if tool.tool_matches_name(name):
                return tool
        
        # Check MCP tools
        if name in self._mcp_tools:
            return self._mcp_tools[name]
        
        return None
    
    def _filter_by_deny_rules(
        self,
        tools: List[ClaudeTool],
        permission_context: ToolPermissionContext
    ) -> List[ClaudeTool]:
        """
        Filter out tools denied by permission rules.
        
        Mirrors filterToolsByDenyRules from Claude CLI tools.ts lines 262-269.
        
        A tool is filtered out if there's a deny rule matching its name
        with no rule content (blanket deny for that tool).
        
        Args:
            tools: List of tools to filter
            permission_context: Permission context with deny rules
            
        Returns:
            Filtered list of allowed tools
        """
        denied_tools = set()
        
        for tool in tools:
            if tool.name in permission_context.always_deny_rules:
                rules = permission_context.always_deny_rules[tool.name]
                # Empty list or None means blanket deny
                if not rules:
                    denied_tools.add(tool.name)
        
        return [t for t in tools if t.name not in denied_tools]


# Feature flag helpers
def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == "Windows"


def create_default_registry(
    feature_flags: Optional[Dict[str, bool]] = None
) -> ToolRegistry:
    """
    Create registry with all Claude CLI compatible tools.
    
    Mirrors getAllBaseTools() from Claude CLI tools.ts lines 193-251.
    
    Args:
        feature_flags: Optional dict of feature flag overrides
        
    Returns:
        Configured ToolRegistry with all tools registered
    """
    registry = ToolRegistry()
    
    # Set feature flags
    if feature_flags:
        for flag, enabled in feature_flags.items():
            registry.set_feature_flag(flag, enabled)
    
    # Note: Tool registration handled by _tools_monolithic.py
    # This modular registry is kept for future integration
    
    return registry


# Singleton instance
_default_registry: Optional[ToolRegistry] = None


def get_tool_registry(
    feature_flags: Optional[Dict[str, bool]] = None,
    reset: bool = False
) -> ToolRegistry:
    """
    Get or create the default tool registry singleton.
    
    Args:
        feature_flags: Optional feature flag overrides
        reset: If True, recreate the registry (useful for testing)
        
    Returns:
        ToolRegistry singleton instance
    """
    global _default_registry
    
    if _default_registry is None or reset:
        _default_registry = create_default_registry(feature_flags)
    
    return _default_registry
