# ------------------------------------------------------------
# prompt.py
# Python conversion of prompt.ts (lines 1-19)
# 
# GrepTool prompt template and description generator.
# ------------------------------------------------------------

from typing import Any

# Import from your codebase - replace with actual imports
try:
    from ..AgentTool.constants import AGENT_TOOL_NAME
except ImportError:
    # Fallback if module doesn't exist yet
    AGENT_TOOL_NAME = "Agent"

try:
    from ..BashTool.toolName import BASH_TOOL_NAME
except ImportError:
    # Fallback if module doesn't exist yet
    BASH_TOOL_NAME = "Bash"


# ============================================================
# TOOL CONSTANTS
# ============================================================

GREP_TOOL_NAME = "Grep"


# ============================================================
# GREP TOOL DESCRIPTION
# ============================================================

def get_description() -> str:
    """
    Get the description for the GrepTool.
    
    Returns:
        Complete description string for the grep tool
    """
    return f"""A powerful search tool built on ripgrep

Usage:
- ALWAYS use {GREP_TOOL_NAME} for search tasks. NEVER invoke `grep` or `rg` as a {BASH_TOOL_NAME} command. The {GREP_TOOL_NAME} tool has been optimized for correct permissions and access.
- Supports full regex syntax (e.g., "log.*Error", "function\\s+\\w+")
- Filter files with glob parameter (e.g., "*.js", "**/*.tsx") or type parameter (e.g., "js", "py", "rust")
- Output modes: "content" shows matching lines, "files_with_matches" shows only file paths (default), "count" shows match counts
- Use {AGENT_TOOL_NAME} tool for open-ended searches requiring multiple rounds
- Pattern syntax: Uses ripgrep (not grep) - literal braces need escaping (use `interface\\{{\\}}` to find `interface{{}}` in Go code)
- Multiline matching: By default patterns match within single lines only. For cross-line patterns like `struct \\{{[\\s\\S]*?field`, use `multiline: true`
"""


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "GREP_TOOL_NAME",
    "get_description",
]
