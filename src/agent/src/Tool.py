# ------------------------------------------------------------
# Tool.py
# Python conversion of Tool.ts (lines 1-793)
# 
# Core type definitions for the tool system including:
# - Tool interface and ToolDef builder pattern
# - ToolUseContext with all runtime context
# - Permission context and results
# - Progress tracking types
# - Validation and result types
# ------------------------------------------------------------

from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import asyncio


# ============================================================
# TYPE DEFINITIONS & ENUMS
# ============================================================

class PermissionMode(str, Enum):
    """Permission modes for tool execution."""
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS_PERMISSIONS = "bypassPermissions"
    DONT_ASK = "dontAsk"


class PermissionBehavior(str, Enum):
    """Permission decision behaviors."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    PASSTHROUGH = "passthrough"


@dataclass
class PermissionResult:
    """Result of a permission check."""
    behavior: PermissionBehavior
    updated_input: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    decision_reason: Optional[Dict[str, Any]] = None
    suggestions: Optional[List[str]] = None


@dataclass
class ValidationResult:
    """Result of input validation."""
    result: bool
    message: Optional[str] = None
    error_code: Optional[int] = None


@dataclass
class AdditionalWorkingDirectory:
    """Additional working directory configuration."""
    path: str
    # Add more fields as needed based on actual usage


ToolPermissionRulesBySource = Dict[str, List[str]]


@dataclass
class ToolPermissionContext:
    """
    Context for tool permission decisions.
    
    Contains mode, rules, and flags that determine whether
    a tool use requires user approval.
    """
    mode: PermissionMode = PermissionMode.DEFAULT
    additional_working_directories: Dict[str, AdditionalWorkingDirectory] = field(default_factory=dict)
    always_allow_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    always_deny_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    always_ask_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    is_bypass_permissions_mode_available: bool = False
    is_auto_mode_available: bool = False
    stripped_dangerous_rules: Optional[ToolPermissionRulesBySource] = None
    should_avoid_permission_prompts: bool = False
    await_automated_checks_before_dialog: bool = False
    pre_plan_mode: Optional[PermissionMode] = None


def get_empty_tool_permission_context() -> ToolPermissionContext:
    """Create an empty/default tool permission context."""
    return ToolPermissionContext(
        mode=PermissionMode.DEFAULT,
        additional_working_directories={},
        always_allow_rules={},
        always_deny_rules={},
        always_ask_rules={},
        is_bypass_permissions_mode_available=False,
    )


# Progress event types
CompactProgressEventType = str  # 'hooks_start', 'compact_start', 'compact_end'


@dataclass
class CompactProgressEvent:
    """Progress events for compact operations."""
    type: CompactProgressEventType
    hook_type: Optional[str] = None  # 'pre_compact', 'post_compact', 'session_start'


# Tool progress data types (simplified placeholders)
AgentToolProgress = Dict[str, Any]
BashProgress = Dict[str, Any]
MCPProgress = Dict[str, Any]
REPLToolProgress = Dict[str, Any]
SkillToolProgress = Dict[str, Any]
TaskOutputProgress = Dict[str, Any]
WebSearchProgress = Dict[str, Any]
HookProgress = Dict[str, Any]

ToolProgressData = Union[
    AgentToolProgress,
    BashProgress,
    MCPProgress,
    REPLToolProgress,
    SkillToolProgress,
    TaskOutputProgress,
    WebSearchProgress,
]

Progress = Union[ToolProgressData, HookProgress]


@dataclass
class ToolProgress:
    """Progress update for a tool call."""
    tool_use_id: str
    data: ToolProgressData


# Query chain tracking
@dataclass
class QueryChainTracking:
    """Tracking for nested query chains."""
    chain_id: str
    depth: int


# Spinner mode
SpinnerMode = str  # Simplified - actual implementation would be an enum


# Theme types
ThemeName = str
Theme = Dict[str, Any]


# Message types (simplified placeholders)
Message = Dict[str, Any]
UserMessage = Dict[str, Any]
AssistantMessage = Dict[str, Any]
AttachmentMessage = Dict[str, Any]
SystemMessage = Dict[str, Any]
SystemLocalCommandMessage = Dict[str, Any]
ProgressMessage = Dict[str, Any]


# Notification type
Notification = Dict[str, Any]


# MCP types
MCPServerConnection = Dict[str, Any]
ServerResource = Dict[str, Any]


# Agent definition
AgentDefinition = Dict[str, Any]
AgentDefinitionsResult = Dict[str, Any]


# File state cache
FileStateCache = Dict[str, Any]


# Denial tracking state
DenialTrackingState = Dict[str, Any]


# System prompt type
SystemPrompt = str


# Content replacement state
ContentReplacementState = Dict[str, Any]


# Attribution state
AttributionState = Dict[str, Any]


# File history state
FileHistoryState = Dict[str, Any]


# AppState
AppState = Dict[str, Any]


# Command type
Command = Dict[str, Any]


# Thinking config
ThinkingConfig = Dict[str, Any]


# UUID type
UUID = str


# Agent ID
AgentId = str


# Query source
QuerySource = str


# SDK Status
SDKStatus = str


# Prompt request/response
PromptRequest = Dict[str, Any]
PromptResponse = Dict[str, Any]


# CanUseTool function type
CanUseToolFn = Callable[[str, Dict[str, Any]], asyncio.Future]


# Tool result block param (Anthropic SDK type placeholder)
ToolResultBlockParam = Dict[str, Any]
ToolUseBlockParam = Dict[str, Any]


# Elicitation types (MCP SDK placeholder)
ElicitRequestURLParams = Dict[str, Any]
ElicitResult = Dict[str, Any]


# ============================================================
# TOOL INTERFACE
# ============================================================

class Tool:
    """
    Base tool interface defining the contract for all tools.
    
    Tools are the primary way Claude interacts with the system. Each tool
    has an input schema, description, and implementation that performs
    actions like reading files, running commands, or searching code.
    
    Attributes:
        name: Unique identifier for the tool
        input_schema: JSON Schema defining valid inputs
        description: Human-readable description of what the tool does
        max_result_size_chars: Maximum size before result is persisted to disk
    """
    
    # Required attributes
    name: str
    input_schema: Dict[str, Any]
    max_result_size_chars: int
    
    # Optional attributes
    aliases: Optional[List[str]] = None
    search_hint: Optional[str] = None
    input_json_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    should_defer: bool = False
    always_load: bool = False
    strict: bool = False
    is_mcp: bool = False
    is_lsp: bool = False
    mcp_info: Optional[Dict[str, str]] = None  # {serverName, toolName}
    
    def __init__(self):
        """Initialize tool with defaults."""
        self.max_result_size_chars = 50000  # Default 50KB
    
    async def call(
        self,
        args: Dict[str, Any],
        context: 'ToolUseContext',
        can_use_tool: CanUseToolFn,
        parent_message: AssistantMessage,
        on_progress: Optional[Callable[[ToolProgress], None]] = None,
    ) -> 'ToolResult':
        """
        Execute the tool with the given arguments.
        
        Args:
            args: Validated input arguments
            context: Runtime context with app state, permissions, etc.
            can_use_tool: Function to check if tool use is allowed
            parent_message: The assistant message that triggered this tool
            on_progress: Callback for progress updates
        
        Returns:
            ToolResult containing output data and optional new messages
        """
        raise NotImplementedError("Subclasses must implement call()")
    
    async def description(
        self,
        input_data: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        """
        Generate a dynamic description for the tool based on input.
        
        Args:
            input_data: The tool input
            options: Context including isNonInteractiveSession, toolPermissionContext, tools
        
        Returns:
            Description string for the model
        """
        raise NotImplementedError("Subclasses must implement description()")
    
    def is_enabled(self) -> bool:
        """Check if this tool is enabled in the current environment."""
        return True
    
    def is_concurrency_safe(self, input_data: Dict[str, Any]) -> bool:
        """
        Check if this tool can safely run concurrently with other instances.
        
        Args:
            input_data: The tool input
        
        Returns:
            True if concurrent execution is safe
        """
        return False
    
    def is_read_only(self, input_data: Dict[str, Any]) -> bool:
        """
        Check if this tool only reads data without modifying anything.
        
        Args:
            input_data: The tool input
        
        Returns:
            True if the tool is read-only
        """
        return False
    
    def is_destructive(self, input_data: Dict[str, Any]) -> bool:
        """
        Check if this tool performs irreversible operations.
        
        Args:
            input_data: The tool input
        
        Returns:
            True if the tool deletes, overwrites, or sends data
        """
        return False
    
    async def check_permissions(
        self,
        input_data: Dict[str, Any],
        context: 'ToolUseContext',
    ) -> PermissionResult:
        """
        Check if the user should be asked for permission.
        
        Called after validateInput() passes. General permission logic
        is in permissions.ts; this method contains tool-specific logic.
        
        Args:
            input_data: The tool input
            context: Runtime context
        
        Returns:
            PermissionResult with behavior (allow/ask/deny)
        """
        return PermissionResult(
            behavior=PermissionBehavior.ALLOW,
            updated_input=input_data,
        )
    
    async def validate_input(
        self,
        input_data: Dict[str, Any],
        context: 'ToolUseContext',
    ) -> ValidationResult:
        """
        Validate tool input before permission checks.
        
        Informs the model of why the tool use failed. Does not display UI.
        
        Args:
            input_data: The tool input
            context: Runtime context
        
        Returns:
            ValidationResult indicating if input is valid
        """
        return ValidationResult(result=True)
    
    def get_path(self, input_data: Dict[str, Any]) -> Optional[str]:
        """
        Get the file path this tool operates on (if applicable).
        
        Args:
            input_data: The tool input
        
        Returns:
            File path or None if not applicable
        """
        return None
    
    async def prepare_permission_matcher(
        self,
        input_data: Dict[str, Any],
    ) -> Optional[Callable[[str], bool]]:
        """
        Prepare a matcher for hook `if` conditions.
        
        Called once per hook-input pair. Any expensive parsing happens here.
        Returns a closure that is called per hook pattern. If not implemented,
        only tool-name-level matching works.
        
        Args:
            input_data: The tool input
        
        Returns:
            Matcher function or None
        """
        return None
    
    async def prompt(self, options: Dict[str, Any]) -> str:
        """
        Generate the system prompt for this tool.
        
        Args:
            options: Includes getToolPermissionContext, tools, agents, allowedAgentTypes
        
        Returns:
            System prompt string
        """
        raise NotImplementedError("Subclasses must implement prompt()")
    
    def user_facing_name(self, input_data: Optional[Dict[str, Any]] = None) -> str:
        """
        Get the human-readable name for display.
        
        Args:
            input_data: Partial tool input
        
        Returns:
            Display name
        """
        return self.name
    
    def user_facing_name_background_color(
        self,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Get background color key for the tool name badge.
        
        Args:
            input_data: Partial tool input
        
        Returns:
            Theme color key or None
        """
        return None
    
    def is_transparent_wrapper(self) -> bool:
        """
        Check if this tool is a transparent wrapper (e.g., REPL).
        
        Transparent wrappers delegate all rendering to their progress handler.
        
        Returns:
            True if this is a transparent wrapper
        """
        return False
    
    def get_tool_use_summary(
        self,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Get a short summary for compact views.
        
        Args:
            input_data: Partial tool input
        
        Returns:
            Summary string or None to not display
        """
        return None
    
    def get_activity_description(
        self,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Get present-tense activity description for spinner display.
        
        Example: "Reading src/foo.ts", "Running bun test"
        
        Args:
            input_data: Partial tool input
        
        Returns:
            Activity description or None to fall back to tool name
        """
        return None
    
    def to_auto_classifier_input(self, input_data: Dict[str, Any]) -> Any:
        """
        Get compact representation for auto-mode security classifier.
        
        Examples: `ls -la` for Bash, `/tmp/x: new content` for Edit.
        Return '' to skip this tool in the classifier transcript.
        
        Args:
            input_data: The tool input
        
        Returns:
            Classifier input (string or object to avoid double-encoding)
        """
        return ""
    
    def map_tool_result_to_tool_result_block_param(
        self,
        content: Any,
        tool_use_id: str,
    ) -> ToolResultBlockParam:
        """
        Convert tool result to Anthropic SDK format.
        
        Args:
            content: The tool output
            tool_use_id: The tool use ID
        
        Returns:
            ToolResultBlockParam for the API
        """
        raise NotImplementedError("Subclasses must implement map_tool_result_to_tool_result_block_param()")
    
    def render_tool_result_message(
        self,
        content: Any,
        progress_messages: List[ProgressMessage],
        options: Dict[str, Any],
    ) -> Any:
        """
        Render the tool result for display.
        
        Optional. When omitted, the tool result renders nothing.
        Omit for tools whose results are surfaced elsewhere (e.g., TodoWrite
        updates the todo panel, not the transcript).
        
        Args:
            content: The tool output
            progress_messages: Progress messages during execution
            options: Includes style, theme, tools, verbose, isTranscriptMode, isBriefOnly, input
        
        Returns:
            React node (or PyQt6 widget in Python version) or None
        """
        return None
    
    def extract_search_text(self, output: Any) -> str:
        """
        Extract flattened text for transcript search indexing.
        
        Must match what renderToolResultMessage shows in transcript mode.
        For count ≡ highlight fidelity.
        
        Args:
            output: The tool output
        
        Returns:
            Searchable text
        """
        return ""
    
    def render_tool_use_message(
        self,
        input_data: Dict[str, Any],
        options: Dict[str, Any],
    ) -> Any:
        """
        Render the tool use message (as parameters stream in).
        
        Note: input is partial because we render as soon as possible,
        possibly before tool parameters have fully streamed in.
        
        Args:
            input_data: Partial tool input
            options: Includes theme, verbose, commands
        
        Returns:
            React node (or PyQt6 widget in Python version)
        """
        raise NotImplementedError("Subclasses must implement render_tool_use_message()")
    
    def is_result_truncated(self, output: Any) -> bool:
        """
        Check if non-verbose rendering is truncated.
        
        Gates click-to-expand in fullscreen — only messages where verbose
        actually shows more get a hover/click affordance.
        
        Args:
            output: The tool output
        
        Returns:
            True if clicking would reveal more content
        """
        return False
    
    def render_tool_use_tag(self, input_data: Dict[str, Any]) -> Any:
        """
        Render an optional tag after the tool use message.
        
        Used for metadata like timeout, model, resume ID, etc.
        
        Args:
            input_data: Partial tool input
        
        Returns:
            React node (or PyQt6 widget) or None
        """
        return None
    
    def render_tool_use_progress_message(
        self,
        progress_messages: List[ProgressMessage],
        options: Dict[str, Any],
    ) -> Any:
        """
        Render progress UI while the tool runs.
        
        Optional. When omitted, no progress UI is shown.
        
        Args:
            progress_messages: Progress messages
            options: Includes tools, verbose, terminalSize, inProgressToolCallCount, isTranscriptMode
        
        Returns:
            React node (or PyQt6 widget) or None
        """
        return None
    
    def render_tool_use_queued_message(self) -> Any:
        """Render queued state message."""
        return None
    
    def render_tool_use_rejected_message(
        self,
        input_data: Dict[str, Any],
        options: Dict[str, Any],
    ) -> Any:
        """
        Render custom rejection UI.
        
        Optional. When omitted, falls back to FallbackToolUseRejectedMessage.
        Only define for tools that need custom rejection UI (e.g., file edits
        that show the rejected diff).
        
        Args:
            input_data: The tool input
            options: Includes columns, messages, style, theme, tools, verbose, progressMessagesForMessage, isTranscriptMode
        
        Returns:
            React node (or PyQt6 widget) or None
        """
        return None
    
    def render_tool_use_error_message(
        self,
        result: Any,
        options: Dict[str, Any],
    ) -> Any:
        """
        Render custom error UI.
        
        Optional. When omitted, falls back to FallbackToolUseErrorMessage.
        Only define for tools that need custom error UI (e.g., search tools
        that show "File not found" instead of the raw error).
        
        Args:
            result: Error content
            options: Includes progressMessagesForMessage, tools, verbose, isTranscriptMode
        
        Returns:
            React node (or PyQt6 widget) or None
        """
        return None
    
    def render_grouped_tool_use(
        self,
        tool_uses: List[Dict[str, Any]],
        options: Dict[str, Any],
    ) -> Any:
        """
        Render multiple tool uses as a group (non-verbose mode only).
        
        In verbose mode, individual tool uses render at their original positions.
        
        Args:
            tool_uses: Array of tool use objects with param, isResolved, isError, isInProgress, progressMessages, result
            options: Includes shouldAnimate, tools
        
        Returns:
            React node (or PyQt6 widget) or None to fall back to individual rendering
        """
        return None
    
    def interrupt_behavior(self) -> str:
        """
        Determine what happens when user submits a new message while tool is running.
        
        Returns:
            'cancel' — stop the tool and discard its result
            'block'  — keep running; the new message waits
        
        Defaults to 'block' when not implemented.
        """
        return "block"
    
    def is_search_or_read_command(
        self,
        input_data: Dict[str, Any],
    ) -> Dict[str, bool]:
        """
        Check if this tool use is a search/read operation for UI collapsing.
        
        Examples include file searching (Grep, Glob), file reading (Read),
        and bash commands like find, grep, wc, etc.
        
        Args:
            input_data: The tool input
        
        Returns:
            Dict with isSearch, isRead, isList booleans
        """
        return {"isSearch": False, "isRead": False, "isList": False}
    
    def is_open_world(self, input_data: Dict[str, Any]) -> bool:
        """
        Check if this tool accesses open-world resources (web, external APIs).
        
        Args:
            input_data: The tool input
        
        Returns:
            True if open-world access
        """
        return False
    
    def requires_user_interaction(self) -> bool:
        """
        Check if this tool requires direct user interaction.
        
        Returns:
            True if user interaction required
        """
        return False
    
    def backfill_observable_input(self, input_data: Dict[str, Any]) -> None:
        """
        Mutate input before observers see it (SDK stream, transcript, hooks).
        
        Called on copies of tool_use input. Mutate in place to add legacy/derived
        fields. Must be idempotent. The original API-bound input is never mutated
        (preserves prompt cache). Not re-applied when a hook/permission returns
        a fresh updatedInput — those own their shape.
        
        Args:
            input_data: Tool input to mutate
        """
        pass


# Type alias for list of tools
Tools = List[Tool]


# ============================================================
# TOOL USE CONTEXT OPTIONS
# ============================================================

@dataclass
class ToolUseContextOptions:
    """
    Options sub-object mirroring TS ToolUseContext.options.
    Exists at toolUseContext.options.tools for TS compatibility.
    """
    tools: Tools = field(default_factory=list)


# ============================================================
# TOOL USE CONTEXT
# ============================================================

@dataclass
class ToolUseContext:
    """
    Runtime context passed to tool calls.

    Contains everything a tool needs to execute: app state,
    permissions, abort signals, callbacks, and configuration.
    """

    # Options sub-object (mirrors TS toolUseContext.options.tools)
    options: ToolUseContextOptions = field(default_factory=ToolUseContextOptions)

    # Options/configuration
    commands: List[Command] = field(default_factory=list)
    debug: bool = False
    main_loop_model: str = ""
    verbose: bool = False
    thinking_config: Optional[ThinkingConfig] = None
    mcp_clients: List[MCPServerConnection] = field(default_factory=list)
    mcp_resources: Dict[str, List[ServerResource]] = field(default_factory=dict)
    is_non_interactive_session: bool = False
    agent_definitions: Optional[AgentDefinitionsResult] = None
    max_budget_usd: Optional[float] = None
    custom_system_prompt: Optional[str] = None
    append_system_prompt: Optional[str] = None
    query_source: Optional[QuerySource] = None
    refresh_tools: Optional[Callable[[], Tools]] = None
    
    # State management
    abort_controller: Optional[Any] = None  # AbortController equivalent
    read_file_state: Optional[FileStateCache] = None
    app_state: Optional[AppState] = None
    set_app_state: Optional[Callable[[Callable[[AppState], AppState]], None]] = None
    set_app_state_for_tasks: Optional[Callable[[Callable[[AppState], AppState]], None]] = None
    
    # Interactive features
    handle_elicitation: Optional[Callable[[str, ElicitRequestURLParams, Any], asyncio.Future]] = None
    set_tool_jsx: Optional[Callable[[Any], None]] = None
    add_notification: Optional[Callable[[Notification], None]] = None
    append_system_message: Optional[Callable[[SystemMessage], None]] = None
    send_os_notification: Optional[Callable[[Dict[str, str]], None]] = None
    
    # Memory and skills
    nested_memory_attachment_triggers: Optional[Set[str]] = None
    loaded_nested_memory_paths: Optional[Set[str]] = None
    dynamic_skill_dir_triggers: Optional[Set[str]] = None
    discovered_skill_names: Optional[Set[str]] = None
    
    # UI state
    user_modified: bool = False
    set_in_progress_tool_use_ids: Optional[Callable[[Callable[[Set[str]], Set[str]]], None]] = None
    set_has_interruptible_tool_in_progress: Optional[Callable[[bool], None]] = None
    set_response_length: Optional[Callable[[Callable[[int], int]], None]] = None
    push_api_metrics_entry: Optional[Callable[[float], None]] = None
    set_stream_mode: Optional[Callable[[SpinnerMode], None]] = None
    on_compact_progress: Optional[Callable[[CompactProgressEvent], None]] = None
    set_sdk_status: Optional[Callable[[SDKStatus], None]] = None
    open_message_selector: Optional[Callable[[], None]] = None
    
    # File tracking
    update_file_history_state: Optional[Callable[[Callable[[FileHistoryState], FileHistoryState]], None]] = None
    update_attribution_state: Optional[Callable[[Callable[[AttributionState], AttributionState]], None]] = None
    set_conversation_id: Optional[Callable[[UUID], None]] = None
    
    # Agent context
    agent_id: Optional[AgentId] = None
    agent_type: Optional[str] = None
    require_can_use_tool: bool = False
    
    # Messages and limits
    messages: List[Message] = field(default_factory=list)
    file_reading_limits: Optional[Dict[str, int]] = None
    glob_limits: Optional[Dict[str, int]] = None
    tool_decisions: Optional[Dict[str, Dict[str, Any]]] = None
    query_tracking: Optional[QueryChainTracking] = None
    
    # Prompts
    request_prompt: Optional[Callable[[str, Optional[str]], Callable[[PromptRequest], asyncio.Future]]] = None
    tool_use_id: Optional[str] = None
    critical_system_reminder_experimental: Optional[str] = None
    
    # Subagent settings
    preserve_tool_use_results: bool = False
    local_denial_tracking: Optional[DenialTrackingState] = None
    content_replacement_state: Optional[ContentReplacementState] = None
    rendered_system_prompt: Optional[SystemPrompt] = None


# ============================================================
# TOOL RESULT
# ============================================================

@dataclass
class ToolResult:
    """
    Result returned from a tool call.
    
    Contains the output data and optional side effects like
    new messages or context modifications.
    """
    data: Any
    new_messages: Optional[List[Union[UserMessage, AssistantMessage, AttachmentMessage, SystemMessage]]] = None
    context_modifier: Optional[Callable[[ToolUseContext], ToolUseContext]] = None
    mcp_meta: Optional[Dict[str, Any]] = None  # {_meta, structuredContent}


# ============================================================
# TOOL BUILDER PATTERN
# ============================================================

# Default values for optional tool methods
TOOL_DEFAULTS = {
    "is_enabled": lambda: True,
    "is_concurrency_safe": lambda input_data=None: False,
    "is_read_only": lambda input_data=None: False,
    "is_destructive": lambda input_data=None: False,
    "check_permissions": lambda input_data, ctx=None: asyncio.Future(),
    "to_auto_classifier_input": lambda input_data=None: "",
    "user_facing_name": lambda input_data=None: "",
}


def build_tool(def_dict: Dict[str, Any]) -> Tool:
    """
    Build a complete Tool from a partial definition, filling in safe defaults.
    
    All tool exports should go through this so that defaults live in one place
    and callers never need `.get('method', default)`.
    
    Defaults (fail-closed where it matters):
    - `is_enabled` → `True`
    - `is_concurrency_safe` → `False` (assume not safe)
    - `is_read_only` → `False` (assume writes)
    - `is_destructive` → `False`
    - `check_permissions` → `{behavior: 'allow', updatedInput}` (defer to general permission system)
    - `to_auto_classifier_input` → `''` (skip classifier — security-relevant tools must override)
    - `user_facing_name` → `name`
    
    Args:
        def_dict: Tool definition dictionary
    
    Returns:
        Complete Tool instance with defaults filled in
    """
    # Create a basic Tool instance
    tool = Tool()
    
    # Copy all attributes from definition
    for key, value in def_dict.items():
        setattr(tool, key, value)
    
    # Apply defaults for missing methods
    if not hasattr(tool, 'is_enabled') or tool.is_enabled is None:
        tool.is_enabled = TOOL_DEFAULTS["is_enabled"]
    
    if not hasattr(tool, 'is_concurrency_safe') or tool.is_concurrency_safe is None:
        tool.is_concurrency_safe = TOOL_DEFAULTS["is_concurrency_safe"]
    
    if not hasattr(tool, 'is_read_only') or tool.is_read_only is None:
        tool.is_read_only = TOOL_DEFAULTS["is_read_only"]
    
    if not hasattr(tool, 'is_destructive') or tool.is_destructive is None:
        tool.is_destructive = TOOL_DEFAULTS["is_destructive"]
    
    if not hasattr(tool, 'to_auto_classifier_input') or tool.to_auto_classifier_input is None:
        tool.to_auto_classifier_input = TOOL_DEFAULTS["to_auto_classifier_input"]
    
    # Default user_facing_name to tool name
    if not hasattr(tool, 'user_facing_name') or tool.user_facing_name is None:
        tool.user_facing_name = lambda input_data=None, name=tool.name: name
    
    # Default check_permissions
    if not hasattr(tool, 'check_permissions') or tool.check_permissions is None:
        async def default_check_permissions(input_data, ctx=None):
            return PermissionResult(
                behavior=PermissionBehavior.ALLOW,
                updated_input=input_data,
            )
        tool.check_permissions = default_check_permissions
    
    return tool


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def tool_matches_name(tool: Union[Tool, Dict[str, Any]], name: str) -> bool:
    """
    Check if a tool matches the given name (primary name or alias).
    
    Args:
        tool: Tool object or dict with 'name' and optional 'aliases'
        name: Name to match against
    
    Returns:
        True if tool name or any alias matches
    """
    if isinstance(tool, dict):
        tool_name = tool.get('name', '')
        aliases = tool.get('aliases', [])
    else:
        tool_name = tool.name
        aliases = getattr(tool, 'aliases', []) or []
    
    return tool_name == name or name in aliases


def find_tool_by_name(tools: Tools, name: str) -> Optional[Tool]:
    """
    Find a tool by name or alias from a list of tools.
    
    Args:
        tools: List of tools to search
        name: Name or alias to find
    
    Returns:
        Matching tool or None
    """
    for tool in tools:
        if tool_matches_name(tool, name):
            return tool
    return None


# ============================================================
# TOOLDEF CLASS (for backwards compatibility)
# ============================================================

@dataclass
class ToolDef:
    """
    Tool definition for building tools.
    Provides a structured way to define tool properties.
    """
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable] = None
    aliases: List[str] = field(default_factory=list)
    is_enabled: bool = True
    is_concurrency_safe: bool = False
    is_read_only: bool = False
    is_destructive: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for build_tool."""
        return {
            'name': self.name,
            'description': self.description,
            'input_schema': self.input_schema,
            'handler': self.handler,
            'aliases': self.aliases,
            'is_enabled': self.is_enabled,
            'is_concurrency_safe': self.is_concurrency_safe,
            'is_read_only': self.is_read_only,
            'is_destructive': self.is_destructive,
        }
    
    def build(self) -> Tool:
        """Build a Tool instance from this definition."""
        return build_tool(self.to_dict())


# CamelCase aliases for backwards compatibility
buildTool = build_tool
toolMatchesName = tool_matches_name
findToolByName = find_tool_by_name


def filter_tool_progress_messages(
    progress_messages: List[ProgressMessage],
) -> List[ProgressMessage]:
    """
    Filter out hook progress messages, keeping only tool progress.
    
    Args:
        progress_messages: Mixed progress messages
    
    Returns:
        Only tool progress messages
    """
    return [msg for msg in progress_messages if msg.get('data', {}).get('type') != 'hook_progress']


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    # Enums
    "PermissionMode",
    "PermissionBehavior",
    
    # Data classes
    "PermissionResult",
    "ValidationResult",
    "AdditionalWorkingDirectory",
    "ToolPermissionContext",
    "ToolProgress",
    "CompactProgressEvent",
    "QueryChainTracking",
    "ToolUseContext",
    "ToolUseContextOptions",
    "ToolResult",
    "ToolDef",
    
    # Core classes
    "Tool",
    
    # Type aliases
    "Tools",
    "ToolProgressData",
    "Progress",
    "AgentToolProgress",
    "BashProgress",
    "MCPProgress",
    "REPLToolProgress",
    "SkillToolProgress",
    "TaskOutputProgress",
    "WebSearchProgress",
    "HookProgress",
    
    # Builders
    "build_tool",
    "buildTool",
    
    # Utilities
    "get_empty_tool_permission_context",
    "tool_matches_name",
    "toolMatchesName",
    "find_tool_by_name",
    "findToolByName",
    "filter_tool_progress_messages",
]
