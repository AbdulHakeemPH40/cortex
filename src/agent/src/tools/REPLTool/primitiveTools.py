# ------------------------------------------------------------
# primitiveTools.py
# Python conversion of REPLTool/primitiveTools.ts
# 
# Primitive tool registry for REPL mode.
# These tools are hidden from direct AI use when REPL mode is on
# but still accessible inside the REPL context.
# ------------------------------------------------------------

from typing import Any, List, Optional

# Import tool definitions
try:
    from ..AgentTool.AgentTool import AgentTool
except ImportError:
    AgentTool = None

try:
    from ..BashTool.BashTool import BashTool
except ImportError:
    BashTool = None

try:
    from ..FileEditTool.completed.FileEditTool import FileEditTool
except ImportError:
    FileEditTool = None

try:
    from ..FileReadTool.FileReadTool import FileReadTool
except ImportError:
    FileReadTool = None

try:
    from ..FileWriteTool.FileWriteTool import FileWriteTool
except ImportError:
    FileWriteTool = None

try:
    from ..GlobTool.GlobTool import GlobTool
except ImportError:
    GlobTool = None

try:
    from ..GrepTool.GrepTool import GrepTool
except ImportError:
    GrepTool = None

try:
    from ..NotebookEditTool.NotebookEditTool import NotebookEditTool
except ImportError:
    NotebookEditTool = None


# Lazy-loaded primitive tools cache
_primitive_tools: Optional[List[Any]] = None


def getReplPrimitiveTools() -> List[Any]:
    """
    Get primitive tools hidden from direct model use when REPL mode is on.
    
    These are the tools in REPL_ONLY_TOOLS that are still accessible inside
    the REPL VM context. Exported so display-side code (collapseReadSearch,
    renderers) can classify/render virtual messages for these tools even
    when they're absent from the filtered execution tools list.
    
    Lazy getter — the import chain collapseReadSearch.py → primitiveTools.py
    → FileReadTool.py → ... loops back through the tool registry, so a
    top-level const hits "Cannot access before initialization". Deferring
    to call time avoids the TDZ.
    
    Referenced directly rather than via getAllBaseTools() because that
    excludes Glob/Grep when hasEmbeddedSearchTools() is true.
    
    Returns:
        List of primitive tool definitions
    """
    global _primitive_tools
    
    if _primitive_tools is None:
        _primitive_tools = [
            tool for tool in [
                FileReadTool,
                FileWriteTool,
                FileEditTool,
                GlobTool,
                GrepTool,
                BashTool,
                NotebookEditTool,
                AgentTool,
            ]
            if tool is not None  # Filter out failed imports
        ]
    
    return _primitive_tools
