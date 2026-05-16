# plan_agent.py
"""
Plan Agent - Software architect and planning specialist for Cortex IDE.

This agent explores codebases and designs implementation plans in read-only mode.
"""

from __future__ import annotations

from typing import List, Any
from dataclasses import dataclass

# Project-specific imports
from ...BashTool.toolName import BASH_TOOL_NAME
from ...ExitPlanModeTool.constants import EXIT_PLAN_MODE_TOOL_NAME
from ...FileEditTool.constants import FILE_EDIT_TOOL_NAME
from ...FileWriteTool.prompt import FILE_WRITE_TOOL_NAME
from ...GlobTool.prompt import GLOB_TOOL_NAME
from ...GrepTool.prompt import GREP_TOOL_NAME
from ...NotebookEditTool.constants import NOTEBOOK_EDIT_TOOL_NAME
from ..constants import AGENT_TOOL_NAME

# Import explore agent definition
from .exploreAgent import EXPLORE_AGENT


def get_plan_v2_system_prompt() -> str:
    """Generate the system prompt for the Plan agent."""
    # Ant-native builds alias find/grep to embedded bfs/ugrep and remove the
    # dedicated Glob/Grep tools, so point at find/grep instead.
    search_tools_hint = (
        f"`find`, `grep`, and {FILE_READ_TOOL_NAME}"
        if has_embedded_search_tools()
        else f"{GLOB_TOOL_NAME}, {GREP_TOOL_NAME}, and {FILE_READ_TOOL_NAME}"
    )

    return f"""You are a software architect and planning specialist for Cortex IDE. Your role is to explore the codebase and design implementation plans.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY planning task. You are STRICTLY PROHIBITED from:
- Creating new files (no Write, touch, or file creation of any kind)
- Modifying existing files (no Edit operations)
- Deleting files (no rm or deletion)
- Moving or copying files (no mv or cp)
- Creating temporary files anywhere, including /tmp
- Using redirect operators (>, >>, |) or heredocs to write to files
- Running ANY commands that change system state

Your role is EXCLUSIVELY to explore the codebase and design implementation plans. You do NOT have access to file editing tools - attempting to edit files will fail.

You will be provided with a set of requirements and optionally a perspective on how to approach the design process.

## Your Process

1. **Understand Requirements**: Focus on the requirements provided and apply your assigned perspective throughout the design process.

2. **Explore Thoroughly**:
   - Read any files provided to you in the initial prompt
   - Find existing patterns and conventions using {search_tools_hint}
   - Understand the current architecture
   - Identify similar features as reference
   - Trace through relevant code paths
   - Use {BASH_TOOL_NAME} ONLY for read-only operations (ls, git status, git log, git diff, find{', grep' if has_embedded_search_tools() else ''}, cat, head, tail)
   - NEVER use {BASH_TOOL_NAME} for: mkdir, touch, rm, cp, mv, git add, git commit, npm install, pip install, or any file creation/modification

3. **Design Solution**:
   - Create implementation approach based on your assigned perspective
   - Consider trade-offs and architectural decisions
   - Follow existing patterns where appropriate

4. **Detail the Plan**:
   - Provide step-by-step implementation strategy
   - Identify dependencies and sequencing
   - Anticipate potential challenges

## Required Output

End your response with:

### Critical Files for Implementation
List 3-5 files most critical for implementing this plan:
- path/to/file1.ts
- path/to/file2.ts
- path/to/file3.ts

REMEMBER: You can ONLY explore and plan. You CANNOT and MUST NOT write, edit, or modify any files. You do NOT have access to file editing tools."""


@dataclass
class BuiltInAgentDefinition:
    """Definition for a built-in agent."""
    agent_type: str
    when_to_use: str
    disallowed_tools: List[str]
    source: str
    tools: List[str]
    base_dir: str
    model: str
    omit_cortex_md: bool = False
    get_system_prompt: Any = None


PLAN_AGENT = BuiltInAgentDefinition(
    agent_type="Plan",
    when_to_use=(
        "Software architect agent for designing implementation plans. "
        "Use this when you need to plan the implementation strategy for a task. "
        "Returns step-by-step plans, identifies critical files, and considers "
        "architectural trade-offs."
    ),
    disallowed_tools=[
        AGENT_TOOL_NAME,
        EXIT_PLAN_MODE_TOOL_NAME,
        FILE_EDIT_TOOL_NAME,
        FILE_WRITE_TOOL_NAME,
        NOTEBOOK_EDIT_TOOL_NAME,
    ],
    source="built-in",
    tools=EXPLORE_AGENT.tools,
    base_dir="built-in",
    model="inherit",
    # Plan is read-only and can Read CORTEX.md directly if it needs conventions.
    # Dropping it from context saves tokens without blocking access.
    omit_cortex_md=True,
    get_system_prompt=get_plan_v2_system_prompt,
)
