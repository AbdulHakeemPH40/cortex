# tool_search.py
# Python conversion of toolSearch.ts (partial)
# Tool search utilities

import os


def is_tool_search_enabled_optimistic() -> bool:
    """
    Optimistic check for tool search feature.
    
    Used to decide whether to include ToolSearchTool in the tool registry.
    The actual decision to defer tools happens at request time.
    """
    from .env_utils import is_env_truthy
    return is_env_truthy(os.environ.get('CLAUDE_CODE_TOOL_SEARCH'))


__all__ = ['is_tool_search_enabled_optimistic']
