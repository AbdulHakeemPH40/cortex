# ------------------------------------------------------------
# processBashCommand.py
# Stub for utils/processUserInput/processBashCommand.ts
#
# This module does not exist in the TypeScript source as a standalone file.
# It is dynamically imported from processUserInput.ts. This stub provides
# the expected interface so the Python processUserInput pipeline can
# compile and run.
#
# Full implementation: bash mode (! prefix) routes input to the bash tool.
# The stub returns shouldQuery=False to fall back gracefully.
# ------------------------------------------------------------

from typing import Any, Callable, Dict, List, Optional

from .processUserInput import ProcessUserInputResult

__all__ = ["process_bash_command"]


async def process_bash_command(
    input_string: str,
    preceding_input_blocks: List[Dict[str, Any]],
    attachment_messages: List[Dict[str, Any]],
    context: Dict[str, Any],
    set_tool_jsx: Optional[Any] = None,
) -> ProcessUserInputResult:
    """
    Process a bash-mode command (! prefix).

    Stub: bash mode is handled by the BashTool in the full tool system.
    In the Python port, bash execution is routed through the tool orchestration
    pipeline (streamingToolExecutor + toolExecution). This stub exists only
    to satisfy the import signature; real bash commands bypass this path.

    Args:
        input_string:           The raw bash command
        preceding_input_blocks: Content blocks preceding the command text
        attachment_messages:     Attachment messages
        context:                ToolUseContext dict/dataclass
        set_tool_jsx:           UI callback (not used in stub)

    Returns:
        ProcessUserInputResult with should_query=False (bash mode not stub-implemented)
    """
    # TODO: Implement bash mode once BashTool is ported.
    # In the Python port, bash commands are best handled by routing them
    # through toolExecution.run_tool_use() directly, rather than as a
    # separate processBashCommand step.
    return ProcessUserInputResult(
        messages=[
            *([m for m in attachment_messages if m]),
        ],
        should_query=False,
    )
