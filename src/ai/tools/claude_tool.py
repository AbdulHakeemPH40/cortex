"""
Claude CLI-Compatible Tool Interface for Cortex IDE

Extends BaseTool with Claude Code's advanced features:
- Permission contexts with allow/deny/ask rules
- Progress callbacks
- Agent-specific tool filtering
- Concurrency safety checks
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Set
from datetime import datetime
from enum import Enum
import asyncio

from .base_tool import BaseTool, ToolResult


class ToolCapability(Enum):
    """Tool capabilities for permission filtering."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SEARCH = "search"
    NETWORK = "network"
    AGENTIC = "agentic"  # Spawns other agents


class AgentType(Enum):
    """Agent types for tool filtering."""
    MAIN = "main"           # Main thread - all tools
    ASYNC = "async"         # Async background agents
    COORDINATOR = "coordinator"  # Coordinator mode
    IN_PROCESS = "in_process"    # In-process teammates


@dataclass
class ToolPermissionContext:
    """
    Claude CLI-style permission context.
    Controls tool availability and auto-approval rules.
    
    From Claude CLI Tool.ts lines 122-138.
    """
    mode: str = "default"  # default, auto, bypass
    additional_working_dirs: Dict[str, str] = field(default_factory=dict)
    always_allow_rules: Dict[str, List[str]] = field(default_factory=dict)
    always_deny_rules: Dict[str, List[str]] = field(default_factory=dict)
    always_ask_rules: Dict[str, List[str]] = field(default_factory=dict)
    is_bypass_available: bool = False
    is_auto_mode_available: bool = False
    
    def can_use_tool(self, tool_name: str, tool_args: Dict) -> 'PermissionResult':
        """Check if tool can be used under current context."""
        # Check deny rules first (highest priority)
        if self._matches_rules(tool_name, tool_args, self.always_deny_rules):
            return PermissionResult(allowed=False, denied=True)
        
        # Check allow rules
        if self._matches_rules(tool_name, tool_args, self.always_allow_rules):
            return PermissionResult(allowed=True, auto_approved=True)
        
        # Check ask rules
        if self._matches_rules(tool_name, tool_args, self.always_ask_rules):
            return PermissionResult(needs_approval=True)
        
        # Default behavior based on mode
        if self.mode == "auto":
            return PermissionResult(allowed=True, auto_approved=True)
        
        return PermissionResult(needs_approval=True)
    
    def _matches_rules(
        self,
        tool_name: str,
        tool_args: Dict,
        rules: Dict[str, List[str]]
    ) -> bool:
        """Check if tool matches permission rules."""
        if tool_name in rules:
            rule_patterns = rules[tool_name]
            # Empty pattern list means match all
            if not rule_patterns:
                return True
            # Check each pattern against args
            for pattern in rule_patterns:
                if self._pattern_matches(pattern, tool_args):
                    return True
        return False
    
    def _pattern_matches(self, pattern: str, args: Dict) -> bool:
        """Check if pattern matches tool arguments."""
        # Simple pattern matching - can be extended
        if pattern == "*":
            return True
        # Parse pattern like "path:src/*" or "command:git *"
        if ":" in pattern:
            key, value_pattern = pattern.split(":", 1)
            arg_value = args.get(key, "")
            # Simple glob matching
            if value_pattern.endswith("*"):
                prefix = value_pattern[:-1]
                return arg_value.startswith(prefix)
            return arg_value == value_pattern
        return False


@dataclass
class PermissionResult:
    """Permission check result."""
    allowed: bool = False
    denied: bool = False
    needs_approval: bool = False
    auto_approved: bool = False
    updated_input: Optional[Dict] = None
    message: Optional[str] = None


@dataclass
class ToolUseContext:
    """
    Claude CLI ToolUseContext equivalent.
    Passed to every tool execution.
    
    From Claude CLI Tool.ts lines 158-300.
    """
    # Core context
    conversation_id: str = ""
    agent_id: Optional[str] = None  # Set for subagents
    agent_type: AgentType = AgentType.MAIN
    
    # State access
    app_state: Dict = field(default_factory=dict)
    messages: List[Dict] = field(default_factory=list)
    
    # File tracking
    read_file_state: Dict = field(default_factory=dict)  # LRU cache
    file_reading_limits: Dict = field(default_factory=dict)
    
    # Tool decisions cache
    tool_decisions: Dict = field(default_factory=dict)
    
    # Callbacks
    on_progress: Optional[Callable[[str, Dict], None]] = None
    set_app_state_for_tasks: Optional[Callable] = None
    
    # Permission
    permission_context: Optional[ToolPermissionContext] = None
    
    # Cancellation
    is_cancelled: bool = False
    
    def emit_progress(self, tool_name: str, progress_data: Dict):
        """Emit progress update if callback is set."""
        if self.on_progress:
            self.on_progress(tool_name, progress_data)


@dataclass
class ClaudeTool(BaseTool, ABC):
    """
    Claude CLI-compatible Tool interface for Cortex.
    
    Extends BaseTool with advanced features from Claude CLI:
    - Rich permission context
    - Progress callbacks  
    - Agent-specific handling
    - Async/concurrency safety checks
    
    Maps to Tool<Input, Output, P> from Claude CLI Tool.ts lines 362-695.
    """
    
    # Identification
    aliases: List[str] = field(default_factory=list)
    search_hint: str = ""  # For ToolSearch discovery (3-10 words)
    
    # Capabilities
    capabilities: Set[ToolCapability] = field(default_factory=set)
    max_result_size_chars: int = 10000
    strict_mode: bool = False
    
    # MCP/LSP integration
    is_mcp: bool = False
    is_lsp: bool = False
    mcp_info: Optional[Dict] = None
    
    # Loading strategy
    should_defer: bool = False  # Load via ToolSearch first
    always_load: bool = False   # Never defer
    
    def __post_init__(self):
        """Initialize after dataclass creation."""
        pass
    
    @abstractmethod
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ) -> ToolResult:
        """
        Execute the tool. Main entry point.
        
        Mirrors Tool.call() from Claude CLI Tool.ts line 379-385.
        
        Args:
            args: Tool parameters from AI
            context: Full execution context
            can_use_tool: Permission check function
            on_progress: Progress callback
            
        Returns:
            ToolResult with success/failure and data
        """
        pass
    
    def get_description_for_ai(self) -> str:
        """
        Generate AI-readable tool description.
        
        Used in system prompts to tell AI what tools are available.
        
        Returns:
            Formatted description with parameters
        """
        param_descriptions = []
        
        for param in self.parameters:
            req = "required" if param.required else "optional"
            default = f" (default: {param.default})" if param.default is not None else ""
            param_descriptions.append(
                f"  - {param.name} ({param.param_type}, {req}): {param.description}{default}"
            )
        
        return f"""Tool: {self.name}
Description: {self.description}
Parameters:
{chr(10).join(param_descriptions)}
"""
    
    def input_schema(self) -> Dict:
        """
        JSON Schema for tool parameters.
        Override for custom schemas.
        """
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {"type": param.param_type, "description": param.description}
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }
    
    # Permission & Safety (Claude CLI lines 401-416, 500-517)
    def is_concurrency_safe(self, args: Dict) -> bool:
        """
        Can this tool run in parallel with other tools?
        Default: False (fail-closed)
        """
        return False
    
    def is_read_only(self, args: Dict) -> bool:
        """
        Does this tool only read (no side effects)?
        Default: False (assume writes)
        """
        return ToolCapability.READ in self.capabilities and len(self.capabilities) == 1
    
    def is_destructive(self, args: Dict) -> bool:
        """
        Performs irreversible operations (delete, overwrite, send)?
        Default: False
        """
        return False
    
    def interrupt_behavior(self) -> str:
        """
        What happens when user sends new message while tool runs:
        - 'cancel': stop the tool and discard result
        - 'block': keep running, new message waits
        
        Default: 'block'
        """
        return "block"
    
    async def validate_input(
        self,
        args: Dict,
        context: ToolUseContext
    ) -> Dict:
        """
        Validate input before execution.
        
        Returns:
            {result: bool, message: str, error_code: int}
        """
        # Default validation from BaseTool
        is_valid, error = self.validate_params(args)
        
        if not is_valid:
            return {
                "result": False,
                "message": error,
                "error_code": 400
            }
        
        return {"result": True}
    
    async def check_permissions(
        self,
        args: Dict,
        context: ToolUseContext
    ) -> PermissionResult:
        """
        Tool-specific permission check.
        Called after validate_input() passes.
        
        Default: Allow (defer to general permission system)
        """
        if context.permission_context:
            return context.permission_context.can_use_tool(self.name, args)
        
        return PermissionResult(allowed=True)
    
    # UI Integration (Claude CLI lines 605-635)
    def get_activity_description(self, args: Dict) -> Optional[str]:
        """
        Present-tense description for spinner display.
        
        Examples:
        - "Reading src/foo.py"
        - "Running pytest"
        - "Searching for pattern"
        
        Returns None to fall back to tool name.
        """
        return None
    
    def get_tool_use_summary(self, args: Dict) -> Optional[str]:
        """Short summary for compact UI views."""
        return None
    
    def to_auto_classifier_input(self, args: Dict) -> Any:
        """
        Compact representation for security classifier.
        
        Examples:
        - 'ls -la' for Bash
        - '/tmp/x: new content' for Edit
        
        Return '' to skip in classifier.
        """
        return ""
    
    def is_enabled(self) -> bool:
        """Feature flag check. Override for conditional tools."""
        return True
    
    def tool_matches_name(self, name: str) -> bool:
        """Check if this tool matches the given name or alias."""
        if self.name == name:
            return True
        return name in self.aliases


# Tool allowlists from Claude CLI constants/tools.ts - imported from centralized location
from .constants import (
    ASYNC_AGENT_ALLOWED_TOOLS,
    COORDINATOR_MODE_ALLOWED_TOOLS,
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS,
    ALL_AGENT_DISALLOWED_TOOLS,
)
