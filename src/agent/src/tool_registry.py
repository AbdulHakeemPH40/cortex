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
from Tool import Tool, Tools, tool_matches_name, ToolPermissionContext

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
    from utils.shell.shell_tool_utils import is_power_shell_tool_enabled
except ImportError:
    def is_power_shell_tool_enabled() -> bool:
        return False

try:
    from utils.agent_swarms_enabled import is_agent_swarms_enabled
except ImportError:
    def is_agent_swarms_enabled() -> bool:
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
        val = getattr(item, key, None)
        if val not in seen:
            seen.add(val)
            result.append(item)
    return result


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
    from tools.FileEditTool.completed.FileEditTool import FileEditTool
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
    from tools.TaskOutputTool.TaskOutputTool import TaskOutputTool
except ImportError:
    TaskOutputTool = None

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
    from tools.TungstenTool.TungstenTool import TungstenTool
except ImportError:
    TungstenTool = None

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
    from tools.ToolSearchTool.ToolSearchTool import ToolSearchTool
except ImportError:
    ToolSearchTool = None

try:
    from tools.ExitPlanModeTool.ExitPlanModeV2Tool import ExitPlanModeV2Tool
except ImportError:
    ExitPlanModeV2Tool = None

try:
    from tools.testing.TestingPermissionTool import TestingPermissionTool
except ImportError:
    TestingPermissionTool = None

try:
    from tools.GrepTool.GrepTool import GrepTool
except ImportError:
    GrepTool = None

try:
    from tools.EnterWorktreeTool.EnterWorktreeTool import EnterWorktreeTool
except ImportError:
    EnterWorktreeTool = None

try:
    from tools.ExitWorktreeTool.ExitWorktreeTool import ExitWorktreeTool
except ImportError:
    ExitWorktreeTool = None

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

try:
    from tools.SyntheticOutputTool.SyntheticOutputTool import SYNTHETIC_OUTPUT_TOOL_NAME
except ImportError:
    SYNTHETIC_OUTPUT_TOOL_NAME = "SyntheticOutput"


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
SuggestBackgroundPRTool = _get_conditional_tool('tools.SuggestBackgroundPRTool.SuggestBackgroundPRTool', 'SuggestBackgroundPRTool') if os.environ.get('USER_TYPE') == 'ant' else None

# Feature-flagged tools
SleepTool = _get_conditional_tool('tools.SleepTool.SleepTool', 'SleepTool') if (feature('PROACTIVE') or feature('KAIROS')) else None

cronTools = [
    _get_conditional_tool('tools.ScheduleCronTool.CronCreateTool', 'CronCreateTool'),
    _get_conditional_tool('tools.ScheduleCronTool.CronDeleteTool', 'CronDeleteTool'),
    _get_conditional_tool('tools.ScheduleCronTool.CronListTool', 'CronListTool'),
] if feature('AGENT_TRIGGERS') else []

# RemoteTriggerTool removed - cloud agent infrastructure not used
MonitorTool = _get_conditional_tool('tools.MonitorTool.MonitorTool', 'MonitorTool') if feature('MONITOR_TOOL') else None
SendUserFileTool = _get_conditional_tool('tools.SendUserFileTool.SendUserFileTool', 'SendUserFileTool') if feature('KAIROS') else None
PushNotificationTool = _get_conditional_tool('tools.PushNotificationTool.PushNotificationTool', 'PushNotificationTool') if (feature('KAIROS') or feature('KAIROS_PUSH_NOTIFICATION')) else None
SubscribePRTool = _get_conditional_tool('tools.SubscribePRTool.SubscribePRTool', 'SubscribePRTool') if feature('KAIROS_GITHUB_WEBHOOKS') else None
OverflowTestTool = _get_conditional_tool('tools.OverflowTestTool.OverflowTestTool', 'OverflowTestTool') if feature('OVERFLOW_TEST_TOOL') else None
CtxInspectTool = _get_conditional_tool('tools.CtxInspectTool.CtxInspectTool', 'CtxInspectTool') if feature('CONTEXT_COLLAPSE') else None
TerminalCaptureTool = _get_conditional_tool('tools.TerminalCaptureTool.TerminalCaptureTool', 'TerminalCaptureTool') if feature('TERMINAL_PANEL') else None
WebBrowserTool = _get_conditional_tool('tools.WebBrowserTool.WebBrowserTool', 'WebBrowserTool') if feature('WEB_BROWSER_TOOL') else None
SnipTool = _get_conditional_tool('tools.SnipTool.SnipTool', 'SnipTool') if feature('HISTORY_SNIP') else None
ListPeersTool = _get_conditional_tool('tools.ListPeersTool.ListPeersTool', 'ListPeersTool') if feature('UDS_INBOX') else None

# VerifyPlanExecutionTool (env-based)
VerifyPlanExecutionTool = _get_conditional_tool('tools.VerifyPlanExecutionTool.VerifyPlanExecutionTool', 'VerifyPlanExecutionTool') if os.environ.get('CLAUDE_CODE_VERIFY_PLAN') == 'true' else None

# WorkflowTool (requires initialization)
WorkflowTool = None
if feature('WORKFLOW_SCRIPTS'):
    try:
        from tools.WorkflowTool.bundled.index import init_bundled_workflows
        init_bundled_workflows()
        WorkflowTool = _get_conditional_tool('tools.WorkflowTool.WorkflowTool', 'WorkflowTool')
    except ImportError:
        pass

# Coordinator mode module
coordinator_mode_module = None
if feature('COORDINATOR_MODE'):
    try:
        import importlib
        coordinator_mode_module = importlib.import_module('coordinator.coordinatorMode')
    except ImportError:
        pass

# Lazy-loaded tools (to avoid circular dependencies)
def get_team_create_tool():
    return _get_conditional_tool('tools.TeamCreateTool.TeamCreateTool', 'TeamCreateTool')

def get_team_delete_tool():
    return _get_conditional_tool('tools.TeamDeleteTool.TeamDeleteTool', 'TeamDeleteTool')

def get_send_message_tool():
    return _get_conditional_tool('tools.SendMessageTool.SendMessageTool', 'SendMessageTool')

def get_power_shell_tool():
    if not is_power_shell_tool_enabled():
        return None
    return _get_conditional_tool('tools.PowerShellTool.PowerShellTool', 'PowerShellTool')


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
    is_enabled = [tool.is_enabled() for tool in tools if tool]
    return [tool.name for tool, enabled in zip(tools, is_enabled) if tool and enabled]


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
        TaskOutputTool,
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
        *( [TungstenTool] if os.environ.get('USER_TYPE') == 'ant' else [] ),
        *( [SuggestBackgroundPRTool] if SuggestBackgroundPRTool else [] ),
        *( [WebBrowserTool] if WebBrowserTool else [] ),
        *( [TaskCreateTool, TaskGetTool, TaskUpdateTool, TaskListTool] if is_todo_v2_enabled() else [] ),
        *( [OverflowTestTool] if OverflowTestTool else [] ),
        *( [CtxInspectTool] if CtxInspectTool else [] ),
        *( [TerminalCaptureTool] if TerminalCaptureTool else [] ),
        *( [LSPTool] if is_env_truthy(os.environ.get('ENABLE_LSP_TOOL', '')) else [] ),
        *( [EnterWorktreeTool, ExitWorktreeTool] if is_worktree_mode_enabled() else [] ),
        get_send_message_tool(),
        *( [ListPeersTool] if ListPeersTool else [] ),
        *( [get_team_create_tool(), get_team_delete_tool()] if is_agent_swarms_enabled() else [] ),
        *( [VerifyPlanExecutionTool] if VerifyPlanExecutionTool else [] ),
        *( [REPLTool] if os.environ.get('USER_TYPE') == 'ant' and REPLTool else [] ),
        *( [WorkflowTool] if WorkflowTool else [] ),
        *( [SleepTool] if SleepTool else [] ),
        *cronTools,
        # RemoteTriggerTool removed - cloud agent infrastructure not used
        *( [MonitorTool] if MonitorTool else [] ),
        BriefTool,
        *( [SendUserFileTool] if SendUserFileTool else [] ),
        *( [PushNotificationTool] if PushNotificationTool else [] ),
        *( [SubscribePRTool] if SubscribePRTool else [] ),
        *( [get_power_shell_tool()] if get_power_shell_tool() else [] ),
        *( [SnipTool] if SnipTool else [] ),
        *( [TestingPermissionTool] if os.environ.get('NODE_ENV') == 'test' else [] ),
        ListMcpResourcesTool,
        ReadMcpResourceTool,
        # Include ToolSearchTool when tool search might be enabled (optimistic check)
        # The actual decision to defer tools happens at request time in claude.ts
        *( [ToolSearchTool] if is_tool_search_enabled_optimistic() else [] ),
    ]
    
    # Filter out None values
    return [tool for tool in tools if tool is not None]


def filter_tools_by_deny_rules(tools: List[Tool], permission_context: ToolPermissionContext) -> List[Tool]:
    """
    Filter out tools that are blanket-denied by the permission context.
    A tool is filtered out if there's a deny rule matching its name with no
    ruleContent (i.e., a blanket deny for that tool).
    
    Uses the same matcher as the runtime permission check (step 1a), so MCP
    server-prefix rules like `mcp__server` strip all tools from that server
    before the model sees them — not just at call time.
    """
    return [tool for tool in tools if not get_deny_rule_for_tool(permission_context, tool)]


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
    
    tools = [tool for tool in get_all_base_tools() if tool and tool.name not in special_tools]
    
    # Filter out tools that are denied by the deny rules
    allowed_tools = filter_tools_by_deny_rules(tools, permission_context)
    
    # When REPL mode is enabled, hide primitive tools from direct use.
    # They're still accessible inside REPL via the VM context.
    if is_repl_mode_enabled():
        repl_enabled = any(tool_matches_name(tool, REPL_TOOL_NAME) for tool in allowed_tools)
        if repl_enabled:
            allowed_tools = [tool for tool in allowed_tools if tool and tool.name not in REPL_ONLY_TOOLS]
    
    # Filter by isEnabled
    return [tool for tool in allowed_tools if tool.is_enabled()]


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
    by_name = lambda a, b: (a.name > b.name) - (a.name < b.name)
    sorted_built_ins = sorted(built_in_tools, key=lambda t: t.name)
    sorted_mcp_tools = sorted(allowed_mcp_tools, key=lambda t: t.name)
    
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

