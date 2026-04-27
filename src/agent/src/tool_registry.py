# ------------------------------------------------------------
# tool_registry.py
# Python conversion of tools.ts (lines 1-390)
# 
# Central tool registry that assembles all available tools
# based on feature flags, environment variables, and permission contexts.
# Combines built-in tools with MCP tools for the complete tool pool.
# ------------------------------------------------------------

from typing import Any, Dict, List, Optional, Set, Union, TYPE_CHECKING
import os

# Core type imports - always available from Tool.py
from Tool import Tool, Tools, tool_matches_name, ToolPermissionContext, build_tool

# Export these at module level for IDE type checking
__all__ = [
    "TOOL_PRESETS",
    "parse_tool_preset",
    "get_tools_for_default_preset",
    "get_all_base_tools",
    "filter_tools_by_deny_rules",
    "get_tools",
    "assemble_tool_pool",
    "get_merged_tools",
    "ALL_AGENT_DISALLOWED_TOOLS",
    "CUSTOM_AGENT_DISALLOWED_TOOLS",
    "ASYNC_AGENT_ALLOWED_TOOLS",
    "COORDINATOR_MODE_ALLOWED_TOOLS",
    "REPL_ONLY_TOOLS",
    "Tool",
    "Tools", 
    "tool_matches_name",
    "ToolPermissionContext",
]

try:
    from bun.bundle import feature
except ImportError:
    def feature(feature_name: str) -> bool:
        """Stub: Check if a feature flag is enabled."""
        return False

try:
    from utils.env_utils import is_env_truthy
except ImportError:
    def is_env_truthy(env_var: str) -> bool:
        return os.environ.get(env_var, "").lower() in ["true", "1", "yes"]

try:
    from utils.embedded_tools import has_embedded_search_tools
except ImportError:
    def has_embedded_search_tools() -> bool:
        return False

try:
    from utils.tasks import is_todo_v2_enabled
except ImportError:
    def is_todo_v2_enabled() -> bool:
        return False

try:
    from utils.tool_search import is_tool_search_enabled_optimistic
except ImportError:
    def is_tool_search_enabled_optimistic() -> bool:
        return False

try:
    from utils.worktree_mode_enabled import is_worktree_mode_enabled
except ImportError:
    def is_worktree_mode_enabled() -> bool:
        return False

try:
    from tools.REPLTool.constants import REPL_TOOL_NAME, REPL_ONLY_TOOLS, is_repl_mode_enabled
except ImportError:
    REPL_TOOL_NAME = "REPL"
    REPL_ONLY_TOOLS = set()
    
    def is_repl_mode_enabled() -> bool:
        return False

try:
    from constants.tools import (
        ALL_AGENT_DISALLOWED_TOOLS,
        CUSTOM_AGENT_DISALLOWED_TOOLS,
        ASYNC_AGENT_ALLOWED_TOOLS,
        COORDINATOR_MODE_ALLOWED_TOOLS,
    )
except ImportError:
    ALL_AGENT_DISALLOWED_TOOLS = []
    CUSTOM_AGENT_DISALLOWED_TOOLS = []
    ASYNC_AGENT_ALLOWED_TOOLS = []
    COORDINATOR_MODE_ALLOWED_TOOLS = []

try:
    from utils.permissions.permissions import get_deny_rule_for_tool
except ImportError:
    def get_deny_rule_for_tool(context: Any, tool: Any) -> Optional[Any]:
        return None

def uniq_by(lst: List[Any], key: str) -> List[Any]:
    """
    Remove duplicates from a list based on a key attribute.
    Python equivalent of lodash's uniqBy function.
    
    Args:
        lst: List of items to deduplicate
        key: Attribute name to use for uniqueness comparison
    
    Returns:
        List with duplicates removed, preserving first occurrence order
    """
    seen = set()
    result = []
    for item in lst:
        if item is None:
            continue
        if isinstance(item, dict):
            val = item.get(key)
        else:
            val = getattr(item, key, None)
        if val not in seen:
            seen.add(val)
            result.append(item)
    return result


def _get_tool_name(tool: Any) -> str:
    """Get tool name from either Tool object or dict-like definition."""
    if tool is None:
        return ""
    if isinstance(tool, dict):
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", ""))


def _is_tool_enabled(tool: Any) -> bool:
    """Evaluate enabled status across Tool objects and dict-style definitions."""
    if tool is None:
        return False
    if isinstance(tool, dict):
        enabled = tool.get("isEnabled")
        if enabled is None:
            enabled = tool.get("is_enabled", True)
        return bool(enabled() if callable(enabled) else enabled)

    enabled_fn = getattr(tool, "is_enabled", None)
    if callable(enabled_fn):
        return bool(enabled_fn())
    return bool(enabled_fn) if enabled_fn is not None else True


def _normalize_tool(tool: Any) -> Optional[Any]:
    """Normalize dict-style tools into Tool objects for consistent downstream usage."""
    if tool is None:
        return None
    if isinstance(tool, dict):
        try:
            return build_tool(tool)
        except Exception:
            return None
    return tool


def _ensure_permission_context_compat(permission_context: Any) -> Any:
    """Populate camelCase aliases expected by legacy permission helpers."""
    if permission_context is None:
        return permission_context

    alias_map = {
        "alwaysAllowRules": "always_allow_rules",
        "alwaysDenyRules": "always_deny_rules",
        "alwaysAskRules": "always_ask_rules",
        "additionalWorkingDirectories": "additional_working_directories",
        "prePlanMode": "pre_plan_mode",
    }
    for camel_name, snake_name in alias_map.items():
        if not hasattr(permission_context, camel_name) and hasattr(permission_context, snake_name):
            try:
                setattr(permission_context, camel_name, getattr(permission_context, snake_name))
            except Exception:
                pass
    return permission_context


# ============================================================
# IMPORT ALL TOOLS
# ============================================================

# Core tools (always imported)
try:
    from tools.AgentTool.AgentTool import AgentTool
except ImportError:
    AgentTool = None

try:
    from tools.SkillTool.SkillTool import SkillTool
except ImportError:
    SkillTool = None

try:
    from tools.BashTool.BashTool import BashTool
except ImportError:
    BashTool = None

try:
    from tools.FileEditTool.FileEditTool import FileEditTool
except ImportError:
    FileEditTool = None

try:
    from tools.FileReadTool.FileReadTool import FileReadTool
except ImportError:
    FileReadTool = None

try:
    from tools.FileWriteTool.FileWriteTool import FileWriteTool
except ImportError:
    FileWriteTool = None

try:
    from tools.GlobTool.GlobTool import GlobTool
except ImportError:
    GlobTool = None

try:
    from tools.NotebookEditTool.NotebookEditTool import NotebookEditTool
except ImportError:
    NotebookEditTool = None

try:
    from tools.WebFetchTool.WebFetchTool import WebFetchTool
except ImportError:
    WebFetchTool = None

try:
    from tools.TaskStopTool.TaskStopTool import TaskStopTool
except ImportError:
    TaskStopTool = None

try:
    from tools.BriefTool.BriefTool import BriefTool
except ImportError:
    BriefTool = None


try:
    from tools.WebSearchTool.WebSearchTool import WebSearchTool
except ImportError:
    WebSearchTool = None

try:
    from tools.TodoWriteTool.TodoWriteTool import TodoWriteTool
except ImportError:
    TodoWriteTool = None

try:
    from tools.AskUserQuestionTool.AskUserQuestionTool import AskUserQuestionTool
except ImportError:
    AskUserQuestionTool = None

try:
    from tools.EnterPlanModeTool.EnterPlanModeTool import EnterPlanModeTool
except ImportError:
    EnterPlanModeTool = None

try:
    from tools.ConfigTool.ConfigTool import ConfigTool
except ImportError:
    ConfigTool = None

try:
    from tools.LSPTool.LSPTool import LSPTool
except ImportError:
    LSPTool = None

try:
    from tools.ListMcpResourcesTool.ListMcpResourcesTool import ListMcpResourcesTool
except ImportError:
    ListMcpResourcesTool = None

try:
    from tools.ReadMcpResourceTool.ReadMcpResourceTool import ReadMcpResourceTool
except ImportError:
    ReadMcpResourceTool = None

try:
    from tools.ExitPlanModeTool.ExitPlanModeV2Tool import ExitPlanModeV2Tool
except ImportError:
    ExitPlanModeV2Tool = None

try:
    from tools.GrepTool.GrepTool import GrepTool
except ImportError:
    GrepTool = None

try:
    from tools.ToolSearchTool.ToolSearchTool import ToolSearchTool
except ImportError:
    ToolSearchTool = None

try:
    from tools.testing.TestingPermissionTool import TestingPermissionTool
except ImportError:
    TestingPermissionTool = None

try:
    from tools.EnterWorktreeTool.EnterWorktreeTool import EnterWorktreeTool
except ImportError:
    EnterWorktreeTool = None

try:
    from tools.ExitWorktreeTool.ExitWorktreeTool import ExitWorktreeTool
except ImportError:
    ExitWorktreeTool = None

try:
    from tools.SyntheticOutputTool.SyntheticOutputTool import SYNTHETIC_OUTPUT_TOOL_NAME
except ImportError:
    SYNTHETIC_OUTPUT_TOOL_NAME = "SyntheticOutput"

try:
    from tools.TaskCreateTool.TaskCreateTool import TaskCreateTool
except ImportError:
    TaskCreateTool = None

try:
    from tools.TaskGetTool.TaskGetTool import TaskGetTool
except ImportError:
    TaskGetTool = None

try:
    from tools.TaskUpdateTool.TaskUpdateTool import TaskUpdateTool
except ImportError:
    TaskUpdateTool = None

try:
    from tools.TaskListTool.TaskListTool import TaskListTool
except ImportError:
    TaskListTool = None


# Conditional imports (feature-flagged or env-based)
def _get_conditional_tool(module_path: str, class_name: str) -> Optional[Any]:
    """Safely import a conditional tool."""
    try:
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, class_name, None)
    except (ImportError, AttributeError, ValueError, ModuleNotFoundError):
        return None


# Ant-only tools
REPLTool = _get_conditional_tool('tools.REPLTool.REPLTool', 'REPLTool') if os.environ.get('USER_TYPE') == 'ant' else None


# Coordinator mode module
coordinator_mode_module = None
if feature('COORDINATOR_MODE'):
    try:
        import importlib
        coordinator_mode_module = importlib.import_module('coordinator.coordinatorMode')
    except ImportError:
        pass

# Lazy-loaded tools (to avoid circular dependencies)
def get_send_message_tool():
    return _get_conditional_tool('tools.SendMessageTool.SendMessageTool', 'SendMessageTool')


# ============================================================
# TOOL PRESETS
# ============================================================

TOOL_PRESETS = ['default']

ToolPreset = str


def parse_tool_preset(preset: str) -> Optional[ToolPreset]:
    """Parse a tool preset string."""
    preset_string = preset.lower()
    if preset_string not in TOOL_PRESETS:
        return None
    return preset_string


def get_tools_for_default_preset() -> List[str]:
    """
    Get the list of tool names for the default preset.
    Filters out tools that are disabled via isEnabled() check.
    
    Returns:
        Array of tool names
    """
    tools = get_all_base_tools()
    return [_get_tool_name(tool) for tool in tools if _get_tool_name(tool) and _is_tool_enabled(tool)]


# ============================================================
# CORE TOOL ASSEMBLY FUNCTIONS
# ============================================================

def get_all_base_tools() -> Tools:
    """
    Get the complete exhaustive list of all tools that could be available
    in the current environment (respecting process.env flags).
    This is the source of truth for ALL tools.
    
    NOTE: This MUST stay in sync with the Statsig dynamic config for system prompt caching.
    """
    tools = [
        AgentTool,
        BashTool,
        # Ant-native builds have bfs/ugrep embedded in the bun binary.
        # When available, find/grep in Claude's shell are aliased to these
        # fast tools, so the dedicated Glob/Grep tools are unnecessary.
        *([] if has_embedded_search_tools() else [GlobTool, GrepTool]),
        ExitPlanModeV2Tool,
        FileReadTool,
        FileEditTool,
        FileWriteTool,
        NotebookEditTool,
        WebFetchTool,
        TodoWriteTool,
        WebSearchTool,
        TaskStopTool,
        AskUserQuestionTool,
        SkillTool,
        EnterPlanModeTool,
        *( [ConfigTool] if os.environ.get('USER_TYPE') == 'ant' else [] ),
        *( [TaskCreateTool, TaskGetTool, TaskUpdateTool, TaskListTool] if is_todo_v2_enabled() else [] ),
        *( [LSPTool] if is_env_truthy(os.environ.get('ENABLE_LSP_TOOL', '')) else [] ),
        *( [EnterWorktreeTool, ExitWorktreeTool] if is_worktree_mode_enabled() else [] ),
        get_send_message_tool(),
        BriefTool,
        *( [TestingPermissionTool] if os.environ.get('NODE_ENV') == 'test' else [] ),
        ListMcpResourcesTool,
        ReadMcpResourceTool,
        # Include ToolSearchTool when tool search might be enabled (optimistic check)
        # The actual decision to defer tools happens at request time in claude.ts
        *( [ToolSearchTool] if is_tool_search_enabled_optimistic() else [] ),
    ]
    
    # Filter out None values and normalize dict-style tool definitions.
    normalized_tools: List[Any] = []
    for tool in tools:
        normalized = _normalize_tool(tool)
        if normalized is not None:
            normalized_tools.append(normalized)
    return normalized_tools


def filter_tools_by_deny_rules(tools: List[Tool], permission_context: ToolPermissionContext) -> List[Tool]:
    """
    Filter out tools that are blanket-denied by the permission context.
    A tool is filtered out if there's a deny rule matching its name with no
    ruleContent (i.e., a blanket deny for that tool).
    
    Uses the same matcher as the runtime permission check (step 1a), so MCP
    server-prefix rules like `mcp__server` strip all tools from that server
    before the model sees them — not just at call time.
    """
    allowed: List[Tool] = []
    compat_context = _ensure_permission_context_compat(permission_context)
    for tool in tools:
        normalized = _normalize_tool(tool)
        if normalized is None:
            continue
        if not get_deny_rule_for_tool(compat_context, normalized):
            allowed.append(normalized)
    return allowed


def get_tools(permission_context: ToolPermissionContext) -> Tools:
    """
    Get the list of available tools for a given permission context.
    
    Args:
        permission_context: Context containing mode and permissions
    
    Returns:
        Filtered list of tools based on mode and permissions
    """
    # Simple mode: only Bash, Read, and Edit tools
    if is_env_truthy(os.environ.get('CLAUDE_CODE_SIMPLE', '')):
        # --bare + REPL mode: REPL wraps Bash/Read/Edit/etc inside the VM, so
        # return REPL instead of the raw primitives. Matches the non-bare path
        # below which also hides REPL_ONLY_TOOLS when REPL is enabled.
        if is_repl_mode_enabled() and REPLTool:
            repl_simple = [REPLTool]
            if feature('COORDINATOR_MODE') and coordinator_mode_module:
                try:
                    if hasattr(coordinator_mode_module, 'is_coordinator_mode') and coordinator_mode_module.is_coordinator_mode():
                        repl_simple.extend([TaskStopTool, get_send_message_tool()])
                except Exception:
                    pass
            return filter_tools_by_deny_rules(repl_simple, permission_context)
        
        simple_tools = [BashTool, FileReadTool, FileEditTool]
        # When coordinator mode is also active, include AgentTool and TaskStopTool
        # so the coordinator gets Task+TaskStop (via useMergedTools filtering) and
        # workers get Bash/Read/Edit (via filterToolsForAgent filtering).
        if feature('COORDINATOR_MODE') and coordinator_mode_module:
            try:
                if hasattr(coordinator_mode_module, 'is_coordinator_mode') and coordinator_mode_module.is_coordinator_mode():
                    simple_tools.extend([AgentTool, TaskStopTool, get_send_message_tool()])
            except Exception:
                pass
        return filter_tools_by_deny_rules(simple_tools, permission_context)
    
    # Get all base tools and filter out special tools that get added conditionally
    # Use getattr to safely access .name attribute, defaulting to empty string if tool is None
    special_tools = {
        getattr(ListMcpResourcesTool, 'name', ''),
        getattr(ReadMcpResourceTool, 'name', ''),
        SYNTHETIC_OUTPUT_TOOL_NAME,
    }
    
    tools = [tool for tool in get_all_base_tools() if tool and _get_tool_name(tool) not in special_tools]
    
    # Filter out tools that are denied by the deny rules
    allowed_tools = filter_tools_by_deny_rules(tools, permission_context)
    
    # When REPL mode is enabled, hide primitive tools from direct use.
    # They're still accessible inside REPL via the VM context.
    if is_repl_mode_enabled():
        repl_enabled = any(tool_matches_name(tool, REPL_TOOL_NAME) for tool in allowed_tools)
        if repl_enabled:
            allowed_tools = [tool for tool in allowed_tools if tool and _get_tool_name(tool) not in REPL_ONLY_TOOLS]
    
    # Filter by isEnabled
    return [tool for tool in allowed_tools if _is_tool_enabled(tool)]


def assemble_tool_pool(
    permission_context: ToolPermissionContext,
    mcp_tools: Tools,
) -> Tools:
    """
    Assemble the full tool pool for a given permission context and MCP tools.
    
    This is the single source of truth for combining built-in tools with MCP tools.
    Both REPL.tsx (via useMergedTools hook) and runAgent.ts (for coordinator workers)
    use this function to ensure consistent tool pool assembly.
    
    The function:
    1. Gets built-in tools via getTools() (respects mode filtering)
    2. Filters MCP tools by deny rules
    3. Deduplicates by tool name (built-in tools take precedence)
    
    Args:
        permission_context: Permission context for filtering built-in tools
        mcp_tools: MCP tools from appState.mcp.tools
    
    Returns:
        Combined, deduplicated array of built-in and MCP tools
    """
    built_in_tools = get_tools(permission_context)
    
    # Filter out MCP tools that are in the deny list
    allowed_mcp_tools = filter_tools_by_deny_rules(mcp_tools, permission_context)
    
    # Sort each partition for prompt-cache stability, keeping built-ins as a
    # contiguous prefix. The server's claude_code_system_cache_policy places a
    # global cache breakpoint after the last prefix-matched built-in tool; a flat
    # sort would interleave MCP tools into built-ins and invalidate all downstream
    # cache keys whenever an MCP tool sorts between existing built-ins. uniqBy
    # preserves insertion order, so built-ins win on name conflict.
    # Avoid Array.toSorted (Node 20+) — we support Node 18. builtInTools is
    # readonly so copy-then-sort; allowedMcpTools is a fresh .filter() result.
    sorted_built_ins = sorted(built_in_tools, key=lambda t: _get_tool_name(t))
    sorted_mcp_tools = sorted(allowed_mcp_tools, key=lambda t: _get_tool_name(t))
    
    return uniq_by(sorted_built_ins + sorted_mcp_tools, 'name')


def get_merged_tools(
    permission_context: ToolPermissionContext,
    mcp_tools: Tools,
) -> Tools:
    """
    Get all tools including both built-in tools and MCP tools.
    
    This is the preferred function when you need the complete tools list for:
    - Tool search threshold calculations (isToolSearchEnabled)
    - Token counting that includes MCP tools
    - Any context where MCP tools should be considered
    
    Use getTools() only when you specifically need just built-in tools.
    
    Args:
        permission_context: Permission context for filtering built-in tools
        mcp_tools: MCP tools from appState.mcp.tools
    
    Returns:
        Combined array of built-in and MCP tools
    """
    built_in_tools = get_tools(permission_context)
    return built_in_tools + mcp_tools


# ============================================================
# PUBLIC API EXPORTS
# ============================================================
# Note: __all__ is defined at the top of the file for IDE type checking

