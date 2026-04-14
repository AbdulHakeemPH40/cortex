# ------------------------------------------------------------
# streamingToolExecutor.py
# Python conversion of services/tools/StreamingToolExecutor.ts (lines 1-531)
#
# Executes tools as they stream in with concurrency control:
# - Concurrent-safe tools run in parallel
# - Non-concurrent tools run alone (exclusive access)
# - Results buffered and emitted in order received
# ------------------------------------------------------------

import asyncio
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, Generator, List, Optional, Set,
)

from ...agent_types.message import (
    AssistantMessage, Message, Tool, Tools,
    ToolUseBlockParam, ToolUseContext, find_tool_by_name,
)
from ...services.tools.toolExecution import run_tool_use
from ...utils.abortController import (
    AbortController, create_child_abort_controller,
)
from ...utils.messages import (
    REJECT_MESSAGE, with_memory_correction_hint, create_user_message,
)


# ============================================================
# TYPE DEFINITIONS
# ============================================================

ToolStatus = str  # 'queued' | 'executing' | 'completed' | 'yielded'


@dataclass
class TrackedTool:
    """
    Tracks a single tool's execution state.
    Mirrors TS TrackedTool type exactly.
    """
    id: str
    block: ToolUseBlockParam
    assistant_message: AssistantMessage
    status: ToolStatus
    is_concurrency_safe: bool
    promise: Optional["asyncio.Future[None]"] = None
    results: Optional[List[Message]] = None
    pending_progress: List[Message] = field(default_factory=list)
    context_modifiers: Optional[List[Callable[[ToolUseContext], ToolUseContext]]] = None


@dataclass
class MessageUpdate:
    """Mirrors TS MessageUpdate."""
    message: Optional[Message] = None
    new_context: Optional[ToolUseContext] = None


# ============================================================
# STREAMING TOOL EXECUTOR
# ============================================================

class StreamingToolExecutor:
    """
    Executes tools as they stream in with concurrency control.

    Mirrors TS StreamingToolExecutor class exactly.

    Key behaviors:
    - Concurrent-safe tools can execute in parallel with other concurrent-safe tools
    - Non-concurrent tools must execute alone (exclusive access)
    - Results are buffered and emitted in the order tools were received
    """

    def __init__(
        self,
        tool_definitions: Tools,
        can_use_tool: Callable,
        tool_use_context: ToolUseContext,
    ) -> None:
        self.tools: List[TrackedTool] = []
        self.tool_definitions = tool_definitions
        self.tool_use_context = tool_use_context
        self.can_use_tool = can_use_tool  # Store the callback directly
        self.has_errored = False
        self.errored_tool_description = ""

        # Resolve parent abort controller (try both Python and TS naming conventions)
        parent_abort: Optional[AbortController] = None
        for attr in ("abort_controller", "abortController"):
            if hasattr(tool_use_context, attr):
                parent_abort = getattr(tool_use_context, attr)
                if parent_abort is not None:
                    break
        if parent_abort is None and hasattr(tool_use_context, "get"):
            parent_abort = tool_use_context.get("abortController")  # type: ignore[union-attr]

        if parent_abort:
            self.sibling_abort_controller: AbortController = create_child_abort_controller(parent_abort)
        else:
            self.sibling_abort_controller = create_child_abort_controller(AbortController())

        self.discarded = False
        # Event to signal progress availability (initialized lazily in event loop)
        self._progress_event: Optional[asyncio.Event] = None

        # Track tool interrupt behavior for quick lookup
        self._interrupt_behavior_cache: Dict[str, str] = {}

    # ========================================================
    # PUBLIC API
    # ========================================================

    def discard(self) -> None:
        """
        Discard all pending and in-progress tools.
        Called when streaming fallback occurs and results from the
        failed attempt should be abandoned.
        Queued tools won't start, and in-progress tools will receive
        synthetic errors.
        """
        self.discarded = True
        if self._progress_event is not None:
            self._progress_event.set()

    def _ensure_progress_event(self) -> asyncio.Event:
        """Lazily create the asyncio.Event in the current event loop."""
        if self._progress_event is None:
            self._progress_event = asyncio.Event()
        return self._progress_event

    def add_tool(
        self,
        block: ToolUseBlockParam,
        assistant_message: AssistantMessage,
    ) -> None:
        """
        Add a tool to the execution queue.
        Will start executing immediately if conditions allow.

        Mirrors TS addTool() exactly.
        """
        tool_definition = find_tool_by_name(self.tool_definitions, block["name"])

        if not tool_definition:
            self.tools.append(TrackedTool(
                id=block["id"],
                block=block,
                assistant_message=assistant_message,
                status="completed",
                is_concurrency_safe=True,
                pending_progress=[],
                results=[
                    create_user_message(
                        content=[
                            {
                                "type": "tool_result",
                                "content": f"<tool_use_error>Error: No such tool available: {block['name']}</tool_use_error>",
                                "is_error": True,
                                "tool_use_id": block["id"],
                            }
                        ],
                        tool_use_result=f"Error: No such tool available: {block['name']}",
                        source_tool_assistant_uuid=assistant_message.get("uuid"),
                    ),
                ],
            ))
            return

        # Check concurrency safety
        parsed_input = self._safe_parse_input(tool_definition, block["input"])
        is_concurrency_safe = False
        if parsed_input.get("success"):
            is_safe_fn = getattr(tool_definition, "is_concurrency_safe", None)
            if is_safe_fn:
                try:
                    is_concurrency_safe = bool(is_safe_fn(parsed_input["data"]))
                except Exception:
                    is_concurrency_safe = False

        self.tools.append(TrackedTool(
            id=block["id"],
            block=block,
            assistant_message=assistant_message,
            status="queued",
            is_concurrency_safe=is_concurrency_safe,
            pending_progress=[],
        ))

        # Start processing in background (fire-and-forget)
        asyncio.create_task(self.process_queue())

    def get_completed_results(self) -> Generator[MessageUpdate, None, None]:
        """
        Get any completed results that haven't been yielded yet (non-blocking).
        Maintains order where necessary. Also yields any pending progress
        messages immediately.

        Mirrors TS *getCompletedResults() — sync generator.
        """
        if self.discarded:
            return

        for tool in self.tools:
            # Always yield pending progress messages immediately
            while tool.pending_progress:
                progress_message = tool.pending_progress.pop(0)
                yield MessageUpdate(
                    message=progress_message,
                    new_context=self.tool_use_context,
                )

            if tool.status == "yielded":
                continue

            if tool.status == "completed" and tool.results is not None:
                tool.status = "yielded"
                for message in tool.results:
                    yield MessageUpdate(
                        message=message,
                        new_context=self.tool_use_context,
                    )
                self._mark_tool_use_as_complete(tool.id)
            elif tool.status == "executing" and not tool.is_concurrency_safe:
                # Don't yield partial results for non-concurrent tools
                # until they're fully done (preserve ordering)
                break

    async def get_remaining_results(self) -> "AsyncGenerator[MessageUpdate, None]":
        """
        Wait for remaining tools and yield their results as they complete.
        Also yields progress messages as they become available.

        Mirrors TS async *getRemainingResults() exactly.
        """
        if self.discarded:
            return

        while self._has_unfinished_tools():
            await self.process_queue()

            for result in self.get_completed_results():
                yield result

            # If we still have executing tools but nothing completed,
            # wait for any to complete OR for progress to become available
            if (
                self._has_executing_tools()
                and not self._has_completed_results()
                and not self._has_pending_progress()
            ):
                executing_tools = [
                    t for t in self.tools
                    if t.status == "executing" and t.promise is not None
                ]

                if executing_tools:
                    tool_promises = [t.promise for t in executing_tools if t.promise]

                    # Also wait for progress to become available
                    progress_task = asyncio.create_task(
                        self._wait_for_progress()
                    )

                    # Race between tool completion and progress
                    done, _ = await asyncio.wait(
                        [*tool_promises, progress_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

        # Final yield of any remaining completed results
        for result in self.get_completed_results():
            yield result

    def get_updated_context(self) -> ToolUseContext:
        """Get the current tool use context (may have been modified)."""
        return self.tool_use_context

    # ========================================================
    # INTERNAL: TOOL EXECUTION
    # ========================================================

    def _safe_parse_input(
        self, tool: Tool, input_data: Dict,
    ) -> Dict[str, Any]:
        """Validate tool input against the tool's inputSchema."""
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

    def _can_execute_tool(self, is_concurrency_safe: bool) -> bool:
        """
        Check if a tool can execute based on current concurrency state.

        Mirrors TS canExecuteTool() exactly.
        """
        executing = [t for t in self.tools if t.status == "executing"]
        return (
            len(executing) == 0
            or (is_concurrency_safe and all(t.is_concurrency_safe for t in executing))
        )

    async def process_queue(self) -> None:
        """
        Process the queue, starting tools when concurrency conditions allow.

        Mirrors TS processQueue() exactly.
        """
        for tool in self.tools:
            if tool.status != "queued":
                continue

            if self._can_execute_tool(tool.is_concurrency_safe):
                await self._execute_tool(tool)
            else:
                # Can't execute this tool yet, and since we need to maintain
                # order for non-concurrent tools, stop here
                if not tool.is_concurrency_safe:
                    break

    async def _execute_tool(self, tool: TrackedTool) -> None:
        """
        Execute a tool and collect its results.

        Mirrors TS executeTool() exactly.
        """
        tool.status = "executing"
        self._add_to_in_progress(tool.id)
        self._update_interruptible_state()

        messages: List[Message] = []
        context_modifiers: List[Callable[[ToolUseContext], ToolUseContext]] = []

        async def collect_results() -> None:
            """Collect all results from run_tool_use() async generator."""
            nonlocal messages, context_modifiers

            # If already aborted, generate synthetic error instead of running
            initial_abort_reason = self._get_abort_reason(tool)
            if initial_abort_reason:
                messages.append(self._create_synthetic_error_message(
                    tool.id,
                    initial_abort_reason,
                    tool.assistant_message,
                ))
                tool.results = messages
                tool.context_modifiers = context_modifiers
                tool.status = "completed"
                self._update_interruptible_state()
                return

            # Per-tool child abort controller. Lets siblingAbortController kill
            # running subprocesses (Bash spawns listen to this signal) when
            # a Bash error cascades.
            tool_abort_controller = create_child_abort_controller(
                self.sibling_abort_controller,
            )

            # Bubble up abort to query controller so the query loop's post-tool
            # abort check ends the turn.
            # Resolve abort_controller with both naming conventions
            parent_abort_ctrl: Optional[AbortController] = None
            for attr in ("abort_controller", "abortController"):
                if hasattr(self.tool_use_context, attr):
                    parent_abort_ctrl = getattr(self.tool_use_context, attr, None)
                    break
            if parent_abort_ctrl is None and hasattr(self.tool_use_context, "get"):
                parent_abort_ctrl = self.tool_use_context.get("abortController")

            def on_tool_abort() -> None:
                if (
                    tool_abort_controller.signal.reason != "sibling_error"
                    and not self.discarded
                    and parent_abort_ctrl is not None
                    and not parent_abort_ctrl.signal.aborted
                ):
                    parent_abort_ctrl.abort(
                        tool_abort_controller.signal.reason,
                    )

            tool_abort_controller.signal.addEventListener("abort", on_tool_abort)

            # Build context with tool's abort controller merged in
            # Note: we need to handle both dict-style and dataclass-style context
            if hasattr(self.tool_use_context, "get"):
                # Dict-like context
                exec_context: Dict[str, Any] = {
                    **self.tool_use_context,  # type: ignore[arg-type, misc]
                    "abortController": tool_abort_controller,
                }
            elif hasattr(self.tool_use_context, "abort_controller"):
                # Dataclass context
                exec_context = self.tool_use_context
                exec_context.abort_controller = tool_abort_controller  # type: ignore[union-attr]
            else:
                exec_context = self.tool_use_context  # type: ignore[assignment]

            # Track if THIS tool produced an error (to avoid duplicate sibling error)
            this_tool_errored = False

            try:
                async for update in run_tool_use(
                    tool.block,
                    tool.assistant_message,
                    self.can_use_tool,
                    exec_context,
                ):
                    # Check if aborted by sibling error or user interruption
                    abort_reason = self._get_abort_reason(tool)
                    if abort_reason and not this_tool_errored:
                        messages.append(self._create_synthetic_error_message(
                            tool.id,
                            abort_reason,
                            tool.assistant_message,
                        ))
                        break

                    # Check if this tool produced an error result
                    is_error_result = self._is_error_result(update)
                    if is_error_result:
                        this_tool_errored = True
                        # Only Bash errors cancel siblings
                        if tool.block["name"] == BASH_TOOL_NAME:
                            self.has_errored = True
                            self.errored_tool_description = (
                                self._get_tool_description(tool)
                            )
                            self.sibling_abort_controller.abort("sibling_error")

                    if update.get("message"):
                        msg = update["message"]
                        # Progress messages go to pendingProgress for immediate yielding
                        if isinstance(msg, dict) and msg.get("type") == "progress":
                            tool.pending_progress.append(msg)
                            self._ensure_progress_event().set()
                        else:
                            messages.append(msg)
                    if update.get("contextModifier"):
                        modifier = update["contextModifier"]
                        if callable(modifier):
                            context_modifiers.append(modifier)
            except Exception:
                # Any exception during iteration — tool failed
                this_tool_errored = True
                if tool.block["name"] == BASH_TOOL_NAME:
                    self.has_errored = True
                    self.errored_tool_description = self._get_tool_description(tool)
                    self.sibling_abort_controller.abort("sibling_error")

            tool.results = messages
            tool.context_modifiers = context_modifiers
            tool.status = "completed"
            self._update_interruptible_state()

            # Apply context modifiers for non-concurrent tools
            if not tool.is_concurrency_safe and context_modifiers:
                for modifier in context_modifiers:
                    self.tool_use_context = modifier(self.tool_use_context)

        # Schedule the collection and chain process_queue on completion
        # Use get_running_loop() instead of deprecated get_event_loop()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        future: asyncio.Future[None] = loop.create_future()

        async def run_and_chain() -> None:
            try:
                await collect_results()
                future.set_result(None)
            except Exception as e:
                future.set_exception(e)

        asyncio.create_task(run_and_chain())
        tool.promise = future

        # Process more queue when done
        future.add_done_callback(
            lambda _: asyncio.create_task(self.process_queue())
        )

    # ========================================================
    # INTERNAL: STATE QUERIES
    # ========================================================

    def _has_completed_results(self) -> bool:
        return any(t.status == "completed" for t in self.tools)

    def _has_executing_tools(self) -> bool:
        return any(t.status == "executing" for t in self.tools)

    def _has_unfinished_tools(self) -> bool:
        return any(t.status != "yielded" for t in self.tools)

    def _has_pending_progress(self) -> bool:
        return any(len(t.pending_progress) > 0 for t in self.tools)

    async def _wait_for_progress(self) -> None:
        """Wait until progress becomes available."""
        event = self._ensure_progress_event()
        event.clear()
        try:
            await asyncio.wait_for(
                event.wait(),
                timeout=300.0,
            )
        except asyncio.TimeoutError:
            pass

    # ========================================================
    # INTERNAL: ERROR MESSAGES
    # ========================================================

    def _create_synthetic_error_message(
        self,
        tool_use_id: str,
        reason: str,
        assistant_message: AssistantMessage,
    ) -> Message:
        """
        Create a synthetic error message for a cancelled/aborted tool.

        Mirrors TS createSyntheticErrorMessage() exactly.
        """
        # For user interruptions (ESC to reject), use REJECT_MESSAGE
        if reason == "user_interrupted":
            return create_user_message(
                content=[
                    {
                        "type": "tool_result",
                        "content": with_memory_correction_hint(REJECT_MESSAGE),
                        "is_error": True,
                        "tool_use_id": tool_use_id,
                    }
                ],
                tool_use_result="User rejected tool use",
                source_tool_assistant_uuid=assistant_message.get("uuid"),
            )

        if reason == "streaming_fallback":
            return create_user_message(
                content=[
                    {
                        "type": "tool_result",
                        "content": "<tool_use_error>Error: Streaming fallback - tool execution discarded</tool_use_error>",
                        "is_error": True,
                        "tool_use_id": tool_use_id,
                    }
                ],
                tool_use_result="Streaming fallback - tool execution discarded",
                source_tool_assistant_uuid=assistant_message.get("uuid"),
            )

        desc = self.errored_tool_description
        msg = (
            f"Cancelled: parallel tool call {desc} errored"
            if desc
            else "Cancelled: parallel tool call errored"
        )
        return create_user_message(
            content=[
                {
                    "type": "tool_result",
                    "content": f"<tool_use_error>{msg}</tool_use_error>",
                    "is_error": True,
                    "tool_use_id": tool_use_id,
                }
            ],
            tool_use_result=msg,
            source_tool_assistant_uuid=assistant_message.get("uuid"),
        )

    # ========================================================
    # INTERNAL: ABORT REASON
    # ========================================================

    def _get_abort_reason(
        self,
        tool: TrackedTool,
    ) -> Optional[str]:
        """
        Determine why a tool should be cancelled.

        Returns: 'sibling_error' | 'user_interrupted' | 'streaming_fallback' | None
        Mirrors TS getAbortReason() exactly.
        """
        if self.discarded:
            return "streaming_fallback"
        if self.has_errored:
            return "sibling_error"

        # Try Python attr first, then TS naming, then dict-style
        abort_ctrl: Optional[AbortController] = None
        ctx = self.tool_use_context
        if hasattr(ctx, "get"):
            abort_ctrl = ctx.get("abortController")
        else:
            for attr in ("abort_controller", "abortController"):
                if hasattr(ctx, attr):
                    abort_ctrl = getattr(ctx, attr, None)
                    break
        if abort_ctrl and abort_ctrl.signal.aborted:
            reason = abort_ctrl.signal.reason
            if reason == "interrupt":
                return (
                    "user_interrupted"
                    if self._get_tool_interrupt_behavior(tool) == "cancel"
                    else None
                )
            return "user_interrupted"
        return None

    def _get_tool_interrupt_behavior(self, tool: TrackedTool) -> str:
        """
        Get interrupt behavior ('cancel' | 'block') for a tool.

        Mirrors TS getToolInterruptBehavior() exactly.
        """
        # Check cache first
        if tool.id in self._interrupt_behavior_cache:
            return self._interrupt_behavior_cache[tool.id]

        definition = find_tool_by_name(self.tool_definitions, tool.block["name"])
        behavior = "block"
        if definition:
            interrupt_fn = getattr(definition, "interrupt_behavior", None)
            if interrupt_fn:
                try:
                    behavior = interrupt_fn() or "block"
                except Exception:
                    behavior = "block"

        self._interrupt_behavior_cache[tool.id] = behavior
        return behavior

    # ========================================================
    # INTERNAL: TOOL DESCRIPTION
    # ========================================================

    def _get_tool_description(self, tool: TrackedTool) -> str:
        """
        Build a short description string for a tool (for error messages).

        Mirrors TS getToolDescription() exactly.
        """
        input_data: Optional[Dict[str, Any]] = tool.block.get("input")
        summary = (
            input_data.get("command")
            or input_data.get("file_path")  # type: ignore[assignment]
            or input_data.get("pattern")  # type: ignore[assignment]
            or ""
        )
        if isinstance(summary, str) and summary:
            truncated = (
                summary[:40] + "\u2026"
                if len(summary) > 40
                else summary
            )
            return f"{tool.block['name']}({truncated})"
        return tool.block["name"]

    # ========================================================
    # INTERNAL: INTERRUPTIBLE STATE
    # ========================================================

    def _update_interruptible_state(self) -> None:
        """
        Update the has_interruptible_tool_in_progress state.

        Mirrors TS updateInterruptibleState() exactly.
        """
        setter = getattr(self.tool_use_context, "set_has_interruptible_tool_in_progress", None)
        if not setter:
            return

        executing = [t for t in self.tools if t.status == "executing"]
        can_interrupt = (
            len(executing) > 0
            and all(
                self._get_tool_interrupt_behavior(t) == "cancel"
                for t in executing
            )
        )
        setter(can_interrupt)

    # ========================================================
    # INTERNAL: TOOL PROGRESS TRACKING
    # ========================================================

    def _is_error_result(self, update: Dict) -> bool:
        """Check if an update contains an error tool_result."""
        msg = update.get("message")
        if not isinstance(msg, dict):
            return False
        if msg.get("type") != "user":
            return False
        content = msg.get("message", {}).get("content", [])
        if not isinstance(content, list):
            return False
        return any(
            isinstance(b, dict)
            and b.get("type") == "tool_result"
            and b.get("is_error")
            for b in content
        )

    # ========================================================
    # INTERNAL: IN-PROGRESS TRACKING
    # ========================================================

    def _add_to_in_progress(self, tool_use_id: str) -> None:
        """Mark a tool use ID as in-progress."""
        setter = getattr(self.tool_use_context, "set_in_progress_tool_use_ids", None)
        if setter:
            def updater(prev: Set[str]) -> Set[str]:
                return set(prev) | {tool_use_id}
            setter(updater)

    def _mark_tool_use_as_complete(self, tool_use_id: str) -> None:
        """Remove a tool use ID from the in-progress set."""
        setter = getattr(self.tool_use_context, "set_in_progress_tool_use_ids", None)
        if setter:
            def updater(prev: Set[str]) -> Set[str]:
                next_set = set(prev)
                next_set.discard(tool_use_id)
                return next_set
            setter(updater)

    # ========================================================
    # CONTEXT ACCESS HELPERS
    # ========================================================

    def __getattr__(self, name: str) -> Any:
        """Forward unknown attrs to tool_use_context for compatibility."""
        return getattr(self.tool_use_context, name)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style access for tool_use_context fields."""
        return getattr(self.tool_use_context, key, default)


# ============================================================
# STANDALONE HELPER (mirrors TS markToolUseAsComplete at file level)
# ============================================================

def mark_tool_use_as_complete(
    tool_use_context: ToolUseContext,
    tool_use_id: str,
) -> None:
    """
    Remove a tool use ID from the in-progress set.

    Mirrors TS markToolUseAsComplete() exactly.
    """
    setter = getattr(tool_use_context, "set_in_progress_tool_use_ids", None)
    if setter:
        def updater(prev: Set[str]) -> Set[str]:
            next_set = set(prev)
            next_set.discard(tool_use_id)
            return next_set
        setter(updater)


__all__ = [
    "StreamingToolExecutor",
    "TrackedTool",
    "MessageUpdate",
    "mark_tool_use_as_complete",
]
