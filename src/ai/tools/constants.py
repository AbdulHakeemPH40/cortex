"""
Tool Constants for Claude CLI-Compatible Agentic System

Defines tool allowlists for different agent types.
Mirrors Claude CLI constants/tools.ts
"""

from typing import FrozenSet

# =============================================================================
# AGENT TYPE TOOL ALLOWLISTS
# =============================================================================

ASYNC_AGENT_ALLOWED_TOOLS: FrozenSet[str] = frozenset({
    # Core file operations (Claude CLI official)
    "read_file",
    "edit_file", 
    "write_file",
    "glob",
    "grep",
    
    # Web (Claude CLI official)
    "web_fetch",
    "web_search",
    
    # Execution (Claude CLI official)
    "bash",
    
    # Project management (Claude CLI official)
    "todo_write",
    "skill",
    
    # Notebook (Claude CLI official)
    "notebook_edit",
    
    # Output (Claude CLI official - SYNTHETIC_OUTPUT_TOOL_NAME)
    "synthetic_output",
})
"""Tools allowed for async background agents (limited set for safety)."""


COORDINATOR_MODE_ALLOWED_TOOLS: FrozenSet[str] = frozenset({
    # Agent management
    "agent",
    "task_stop",
    "send_message",
    
    # Output
    "synthetic_output",
})
"""Tools allowed for coordinator agents (only agent management tools)."""


IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: FrozenSet[str] = frozenset({
    # Task management
    "task_create",
    "task_get",
    "task_list",
    "task_update",
    
    # Messaging
    "send_message",
    
    # Cron triggers (for scheduled tasks)
    "cron_create",
    "cron_delete",
    "cron_list",
})
"""Tools allowed only for in-process teammates (not general async agents)."""


ALL_AGENT_DISALLOWED_TOOLS: FrozenSet[str] = frozenset({
    # Blocked to prevent recursion
    "task_output",  # Use synthetic_output instead
    "exit_plan_mode_v2",
    "enter_plan_mode",
    
    # Require main thread access
    "ask_user_question",
    "task_stop",
    
    # Agent tool blocked for non-ant users (configurable)
    "agent",  # Only main/coordinator can spawn
    
    # Prevent recursive workflow execution
    "workflow",
})
"""Tools blocked for all agent types (main thread only)."""


# =============================================================================
# TOOL NAME CONSTANTS (for consistency)
# =============================================================================

# Core file tools
FILE_READ_TOOL_NAME = "read_file"
FILE_WRITE_TOOL_NAME = "write_file"
FILE_EDIT_TOOL_NAME = "edit_file"
GLOB_TOOL_NAME = "glob"
GREP_TOOL_NAME = "grep"

# Execution
BASH_TOOL_NAME = "bash"
POWERSHELL_TOOL_NAME = "powershell"

# Web
WEB_FETCH_TOOL_NAME = "web_fetch"
WEB_SEARCH_TOOL_NAME = "web_search"
WEB_BROWSER_TOOL_NAME = "web_browser"

# Project/Todo
TODO_WRITE_TOOL_NAME = "todo_write"

# Task management
TASK_CREATE_TOOL_NAME = "task_create"
TASK_GET_TOOL_NAME = "task_get"
TASK_LIST_TOOL_NAME = "task_list"
TASK_UPDATE_TOOL_NAME = "task_update"
TASK_STOP_TOOL_NAME = "task_stop"
TASK_OUTPUT_TOOL_NAME = "task_output"

# Agent coordination
AGENT_TOOL_NAME = "agent"
SEND_MESSAGE_TOOL_NAME = "send_message"

# Plan mode
ENTER_PLAN_MODE_TOOL_NAME = "enter_plan_mode"
EXIT_PLAN_MODE_TOOL_NAME = "exit_plan_mode_v2"
BRIEF_TOOL_NAME = "brief"

# Notebook
NOTEBOOK_EDIT_TOOL_NAME = "notebook_edit"

# Config
CONFIG_TOOL_NAME = "config"

# MCP
LIST_MCP_RESOURCES_TOOL_NAME = "list_mcp_resources"
READ_MCP_RESOURCE_TOOL_NAME = "read_mcp_resource"

# Skill
SKILL_TOOL_NAME = "skill"

# Search
TOOL_SEARCH_TOOL_NAME = "tool_search"

# Cron triggers
CRON_CREATE_TOOL_NAME = "cron_create"
CRON_DELETE_TOOL_NAME = "cron_delete"
CRON_LIST_TOOL_NAME = "cron_list"

# Workflow
WORKFLOW_TOOL_NAME = "workflow"

# Output
SYNTHETIC_OUTPUT_TOOL_NAME = "synthetic_output"


# =============================================================================
# COMBINED SETS FOR CONVENIENCE
# =============================================================================

def get_tools_for_agent_type(agent_type: str) -> Set[str]:
    """
    Get the set of allowed tool names for a given agent type.
    
    Args:
        agent_type: One of "main", "async", "coordinator", "in_process"
        
    Returns:
        Set of allowed tool names
    """
    if agent_type == "async":
        return set(ASYNC_AGENT_ALLOWED_TOOLS)
    elif agent_type == "coordinator":
        return set(COORDINATOR_MODE_ALLOWED_TOOLS)
    elif agent_type == "in_process":
        return set(ASYNC_AGENT_ALLOWED_TOOLS | IN_PROCESS_TEAMMATE_ALLOWED_TOOLS)
    elif agent_type == "main":
        # Main thread: all tools except disallowed
        # This would need to be computed from full tool list
        return set()  # Placeholder - actual implementation would filter
    else:
        return set(ASYNC_AGENT_ALLOWED_TOOLS)  # Safest default


# =============================================================================
# DEFAULT TOOL PRESETS
# =============================================================================

# Simple mode - minimal tools
SIMPLE_MODE_TOOLS = frozenset({
    "bash",
    "file_read",
    "file_edit",
})

# Bare mode - REPL wraps these
BARE_MODE_TOOLS = frozenset({
    "bash",
    "file_read", 
    "file_edit",
    "file_write",
})

# Default full set
DEFAULT_TOOLS = frozenset({
    "agent",
    "task_output",
    "bash",
    "file_read",
    "file_edit",
    "file_write",
    "glob",
    "grep",
    "notebook_edit",
    "web_fetch",
    "todo_write",
    "web_search",
    "exit_plan_mode_v2",
    "ask_user_question",
    "skill",
    "enter_plan_mode",
    "task_stop",
})
