# ------------------------------------------------------------
# prompt.py
# Python conversion of prompt.ts (lines 1-8)
# 
# GlobTool prompt template and description.
# ------------------------------------------------------------


# ============================================================
# TOOL CONSTANTS
# ============================================================

GLOB_TOOL_NAME = "Glob"


# ============================================================
# GLOB TOOL DESCRIPTION
# ============================================================

DESCRIPTION = """- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Agent tool instead"""


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "GLOB_TOOL_NAME",
    "DESCRIPTION",
]
