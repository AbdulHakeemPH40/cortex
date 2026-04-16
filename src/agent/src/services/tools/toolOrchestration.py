# ------------------------------------------------------------
# toolOrchestration.py
# Python conversion of services/tools/toolOrchestration.ts (lines 1-189)
#
# Orchestrates concurrent vs serial tool execution:
# - partitionToolCalls(): splits into concurrency-safe (parallel) batches
# - runTools(): main orchestrator — routes batches to serial/concurrent paths
# - runToolsSerially(): sequential execution for non-read-only tools
# - runToolsConcurrently(): concurrent execution for read-only tools
# - markToolUseAsComplete(): removes tool use ID from in-progress set
# ------------------------------------------------------------

import os
from dataclasses import dataclass, field
from typing import (
    Any, AsyncGenerator, Callable, Dict, List, Optional, Set,
)

from ...agent_types.message import (
    AssistantMessage, Message, Tool, ToolUseContext,
    ToolUseBlockParam, Tools, find_tool_by_name,
)
from ...services.tools.toolExecution import run_tool_use
from ...utils.generators import all_


# ============================================================
# CONCURRENCY CONFIG
# ============================================================

def get_max_tool_use_concurrency() -> int:
    """Read CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY from environment."""
    val = os.environ.get("CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY", "")
    return int(val) if val.strip() else 10


# ============================================================
# TYPE DEFINITIONS
# ============================================================

@dataclass
class MessageUpdate:
    """
    Yielded by runTools() and sub-functions during tool execution.

    Mirrors TS MessageUpdate:
    - message: a new message update to append to the conversation
    - newContext: updated ToolUseContext after this update
    """
    message: Optional[Message] = None
    new_context: ToolUseContext = field(
        default_factory=lambda: ToolUseContext(),
    )


@dataclass
class MessageUpdateLazy:
    """
    Yielded by runToolsConcurrently().
    Like MessageUpdate but includes optional contextModifier.

    Mirrors TS MessageUpdateLazy:
    - message: new message
    - newContext: optional updated context (used after full completion)
    - contextModifier: deferred context modifier to apply later
    """
    message: Optional[Message] = None
    new_context: Optional[ToolUseContext] = None
    context_modifier: Optional[Callable[[ToolUseContext], ToolUseContext]] = None


# ============================================================
# INPUT VALIDATION (mirrors _safeParseInput from toolExecution.py)
# ============================================================

def _safe_parse_input(tool: Tool, input_data: Dict) -> Dict[str, Any]:
    """
    Validate tool input against the tool's inputSchema.
    Mirrors the Zod schema safeParse() pattern.
    """
    try:
        schema = getattr(tool, "input_schema", None)
        if not schema:
            return {"success": True, "data": input_data, "error": None}
        try:
            import jsonschema
            jsonschema.validate(input_data, schema)
            return {"success": True, "data": input_data, "error": None}
        except (ImportError, Exception) as e:
            if isinstance(e, ImportError):
                return {"success": True, "data": input_data, "error": None}
            return {"success": False, "data": None, "error": str(e)}
    except Exception:
        return {"success": True, "data": input_data, "error": None}


# ============================================================
# BATCH PARTITIONING
# ============================================================

@dataclass
class Batch:
    """
    A partition of tool calls sharing the same concurrency safety.

    Mirrors TS Batch type:
    - isConcurrencySafe: True for read-only tools that can run in parallel
    - blocks: the ToolUseBlockParam entries in this batch
    """
    is_concurrency_safe: bool
    blocks: List[ToolUseBlockParam] = field(default_factory=list)


def partition_tool_calls(
    tool_use_messages: List[ToolUseBlockParam],
    tool_use_context: ToolUseContext,
) -> List[Batch]:
    """
    Partition tool calls into batches where each batch is either:
      1. A single non-read-only tool, or
      2. Multiple consecutive read-only (concurrency-safe) tools

    Mirrors TS partitionToolCalls() exactly.
    """
    batches: List[Batch] = []

    for tool_use in tool_use_messages:
        tool = find_tool_by_name(
            tool_use_context.options.tools,
            tool_use["name"],
        )
        parsed_input = _safe_parse_input(tool, tool_use["input"]) if tool else None

        is_concurrency_safe = False
        if parsed_input and parsed_input.get("success"):
            is_safe_fn = getattr(tool, "is_concurrency_safe", None)
            if is_safe_fn:
                try:
                    is_concurrency_safe = bool(is_safe_fn(parsed_input["data"]))
                except Exception:
                    # If isConcurrencySafe throws (e.g., shell-quote parse failure),
                    # treat as not concurrency-safe to be conservative
                    is_concurrency_safe = False

        # Append to the last batch if it's also concurrency-safe
        if is_concurrency_safe and batches and batches[-1].is_concurrency_safe:
            batches[-1].blocks.append(tool_use)
        else:
            batches.append(Batch(
                is_concurrency_safe=is_concurrency_safe,
                blocks=[tool_use],
            ))

    return batches


# ============================================================
# HELPERS
# ============================================================

def mark_tool_use_as_complete(
    tool_use_context: ToolUseContext,
    tool_use_id: str,
) -> None:
    """
    Remove a tool use ID from the in-progress set.

    Mirrors TS markToolUseAsComplete() exactly.
    """
    setter = getattr(tool_use_context, 'set_in_progress_tool_use_ids', None)
    if setter and callable(setter):
        def updater(prev: Set[str]) -> Set[str]:
            next_set = set(prev)
            next_set.discard(tool_use_id)
            return next_set
        setter(updater)


def _find_assistant_message_for_tool_use(
    assistant_messages: List[AssistantMessage],
    tool_use_id: str,
) -> Optional[AssistantMessage]:
    """
    Find the assistant message that contains the given tool_use_id in its content.

    Mirrors TS: assistantMessages.find(_ =>
        _.message.content.some(_ => _.type === 'tool_use' && _.id === toolUse.id)
    )
    """
    for assistant_message in assistant_messages:
        content = assistant_message.get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("id") == tool_use_id
                ):
                    return assistant_message
    return None


def _add_to_in_progress(
    tool_use_context: ToolUseContext,
    tool_use_id: str,
) -> None:
    """Mark a tool use ID as in-progress."""
    setter = getattr(tool_use_context, 'set_in_progress_tool_use_ids', None)
    if setter and callable(setter):
        def updater(prev: Set[str]) -> Set[str]:
            return set(prev) | {tool_use_id}
        setter(updater)


# ============================================================
# SERIAL EXECUTION
# ============================================================

async def run_tools_serially(
    tool_use_messages: List[ToolUseBlockParam],
    assistant_messages: List[AssistantMessage],
    can_use_tool: Callable,
    tool_use_context: ToolUseContext,
) -> AsyncGenerator[MessageUpdate, None]:
    """
    Run tool calls one at a time, yielding updates as each completes.
    Used for non-read-only (non-concurrency-safe) tools.

    Mirrors TS runToolsSerially() exactly:
      - Mark each tool in-progress before running
      - Run via run_tool_use()
      - Apply contextModifier if present
      - Mark complete after each tool
    """
    current_context = tool_use_context

    for tool_use in tool_use_messages:
        tool_use_id = tool_use["id"]

        # Mark as in-progress
        _add_to_in_progress(current_context, tool_use_id)

        # Find matching assistant message
        assistant_msg = _find_assistant_message_for_tool_use(
            assistant_messages, tool_use_id,
        )

        # Run the tool and yield updates
        async for update_dict in run_tool_use(
            tool_use,
            assistant_msg,
            can_use_tool,
            current_context,
        ):
            # update_dict keys: "message", "newContext", "contextModifier"
            if update_dict.get("contextModifier"):
                current_context = update_dict["contextModifier"](current_context)
            yield MessageUpdate(
                message=update_dict.get("message"),
                new_context=current_context,
            )

        # Mark as complete
        mark_tool_use_as_complete(current_context, tool_use_id)


# ============================================================
# CONCURRENT EXECUTION
# ============================================================

async def run_tools_concurrently(
    tool_use_messages: List[ToolUseBlockParam],
    assistant_messages: List[AssistantMessage],
    can_use_tool: Callable,
    tool_use_context: ToolUseContext,
) -> AsyncGenerator[MessageUpdateLazy, None]:
    """
    Run read-only tool calls concurrently, yielding updates as they arrive.
    Uses all_() to interleave concurrent generators up to the concurrency cap.

    Mirrors TS runToolsConcurrently() exactly.

    Note: all_() is used instead of yield* because Python async generators
    don't support delegation syntax like JS. Each tool runs as an independent
    generator wrapped by run_single_tool().
    """
    # Capture context at start for use in nested function
    initial_context = tool_use_context

    async def run_single_tool(
        tool_use: ToolUseBlockParam,
    ) -> AsyncGenerator[MessageUpdateLazy, None]:
        """Wrap run_tool_use for a single tool use, managing in-progress state."""
        tool_use_id = tool_use["id"]

        # Mark as in-progress
        _add_to_in_progress(initial_context, tool_use_id)

        # Find matching assistant message
        assistant_msg = _find_assistant_message_for_tool_use(
            assistant_messages, tool_use_id,
        )

        async for update_dict in run_tool_use(
            tool_use,
            assistant_msg,
            can_use_tool,
            initial_context,
        ):
            yield MessageUpdateLazy(
                message=update_dict.get("message"),
                new_context=update_dict.get("newContext"),
                context_modifier=update_dict.get("contextModifier"),
            )

        # Mark as complete
        mark_tool_use_as_complete(initial_context, tool_use_id)

    # Build list of generators
    generators = [run_single_tool(block) for block in tool_use_messages]

    # Run concurrently using all_()
    concurrency = get_max_tool_use_concurrency()
    async for update in all_(generators, concurrency):
        yield update


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

async def run_tools(
    tool_use_messages: List[ToolUseBlockParam],
    assistant_messages: List[AssistantMessage],
    can_use_tool: Callable,
    tool_use_context: ToolUseContext,
) -> AsyncGenerator[MessageUpdate, None]:
    """
    Top-level tool orchestration.

    Partitions tool calls into concurrency-safe batches:
      - Safe batches: executed concurrently (parallel)
      - Unsafe batches: executed serially (one at a time)

    Yields MessageUpdate objects with new messages and updated context.

    Mirrors TS runTools() exactly.
    """
    current_context = tool_use_context

    for batch in partition_tool_calls(tool_use_messages, current_context):
        if batch.is_concurrency_safe:
            # ---- Concurrent (read-only) batch ----
            queued_context_modifiers: Dict[
                str, List[Callable[[ToolUseContext], ToolUseContext]]
            ] = {}

            async for update in run_tools_concurrently(
                batch.blocks,
                assistant_messages,
                can_use_tool,
                current_context,
            ):
                if update.context_modifier:
                    tool_use_id = _get_tool_use_id_from_message(update.message)
                    if tool_use_id:
                        if tool_use_id not in queued_context_modifiers:
                            queued_context_modifiers[tool_use_id] = []
                        queued_context_modifiers[tool_use_id].append(
                            update.context_modifier,
                        )
                yield MessageUpdate(
                    message=update.message,
                    new_context=current_context,
                )

            # Apply all collected context modifiers in block order
            for block in batch.blocks:
                modifiers = queued_context_modifiers.get(block["id"], [])
                for modifier in modifiers:
                    current_context = modifier(current_context)

            yield MessageUpdate(new_context=current_context)

        else:
            # ---- Serial (non-read-only) batch ----
            async for update in run_tools_serially(
                batch.blocks,
                assistant_messages,
                can_use_tool,
                current_context,
            ):
                if update.new_context:
                    current_context = update.new_context
                yield MessageUpdate(
                    message=update.message,
                    new_context=current_context,
                )


# ============================================================
# UTILITIES
# ============================================================

def _get_tool_use_id_from_message(
    message: Optional[Message],
) -> Optional[str]:
    """
    Extract tool_use_id from a message's tool_use content block.

    Mirrors TS: message?.message?.content?.find(_ => _.type === 'tool_use')?.id
    """
    if not message:
        return None
    content = message.get("message", {}).get("content", [])
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block.get("id")
    return None


__all__ = [
    "run_tools",
    "mark_tool_use_as_complete",
    "partition_tool_calls",
    "MessageUpdate",
    "MessageUpdateLazy",
    "get_max_tool_use_concurrency",
]
