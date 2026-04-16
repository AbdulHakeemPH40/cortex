# ------------------------------------------------------------
# processSlashCommand.py
# Stub for utils/processUserInput/processSlashCommand.tsx
#
# This module does not exist in the TypeScript source as a standalone file.
# It is dynamically imported from processUserInput.ts and
# SkillTool.ts. This stub provides the expected interface so the
# Python processUserInput pipeline can compile and run.
#
# Full implementation: slash commands would be routed here after
# parsing, loading attachment messages, and checking bridge-safety.
# The stub returns shouldQuery=False to fall back gracefully.
# ------------------------------------------------------------

from typing import Any, Callable, Dict, List, Optional

from .processUserInput import ProcessUserInputResult

__all__ = ["process_slash_command"]


async def process_slash_command(
    input_string: str,
    preceding_input_blocks: List[Dict[str, Any]],
    image_content_blocks: List[Dict[str, Any]],
    attachment_messages: List[Dict[str, Any]],
    context: Dict[str, Any],
    set_tool_jsx: Optional[Any] = None,
    uuid_arg: Optional[str] = None,
    is_already_processing: bool = False,
    can_use_tool: Optional[Callable[..., bool]] = None,
) -> ProcessUserInputResult:
    """
    Process a slash command and return the resulting messages.

    Stub: slash commands are not yet implemented in the Python port.
    Returns an empty result with shouldQuery=False.

    Args:
        input_string:           The raw slash command (e.g. '/search foo')
        preceding_input_blocks:  Content blocks that precede the command text
        image_content_blocks:    Processed image blocks
        attachment_messages:     Attachment messages from context loading
        context:                ToolUseContext dict/dataclass
        set_tool_jsx:           UI callback (not used in stub)
        uuid_arg:               Explicit UUID
        is_already_processing:  True if processing is already underway
        can_use_tool:           Tool permission checker

    Returns:
        ProcessUserInputResult with should_query=False (slash command not implemented)
    """
    # TODO: Implement slash command routing once the command system is ported.
    # Slash commands include:
    #   /search, /claude-code, /compact, /cost, /debug, /diff, /edit,
    #   /ensime, /evaluate, /export, /github, /improve, /kill, /lsp,
    #   /memory, /model, /mcp, /mcp-auth, /mcp-start, /mcp-stop,
    #   /package, /plan, /pr, /review, /scm, /skills, /todo, /web,
    #   /websearch, /whatsnew
    #
    # Each command is handled by a dedicated function in the commands/
    # package, loaded via findCommand() from the context's command registry.
    return ProcessUserInputResult(
        messages=[
            *([m for m in attachment_messages if m]),
        ],
        should_query=False,
    )
