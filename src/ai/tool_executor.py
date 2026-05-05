"""
tool_executor.py
----------------
Handles the tool execution batching logic extracted from agent_bridge.py.

Responsible for:
  - Classifying tools as read-only (parallel-safe) vs mutating (sequential)
  - Grouping consecutive read-only tools into parallel batches
  - Applying circuit breaker filtering per batch
  - Executing batches (single or parallel via asyncio.gather)
  - Consecutive same-readonly-tool detection with nudge injection
"""

from typing import Any, Dict, List, Optional, Set, Tuple, Callable
import asyncio
import logging

from src.ai.circuit_breaker import ToolCircuitBreaker

log = logging.getLogger("tool_executor")

# Tools that can be safely run in parallel (no side effects)
_READ_ONLY_TOOLS: Set[str] = {"Read", "Glob", "Grep", "LS"}

# Maximum consecutive turns with the same read-only tool before nudging
_CONSECUTIVE_READONLY_LIMIT = 2

# Tool name → activity name mapping for UI cards
_TOOL_TO_ACTIVITY: Dict[str, str] = {
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "edit_file",
    "Glob": "glob",
    "Grep": "grep",
    "Bash": "run_command",
    "LS": "list_directory",
    "WebFetch": "web_fetch",
    "WebSearch": "web_search",
    "TaskCreate": "task_create",
    "TaskUpdate": "task_update",
    "TaskList": "task_list",
    "TaskGet": "task_get",
    "TaskStop": "task_stop",
    "AskUserQuestion": "ask_user",
    "TodoWrite": "todo_write",
    "MCP": "mcp_tool",
    "TeamCreate": "team_create",
    "TeamDelete": "team_delete",
}

ParsedToolCall = Tuple[str, str, Any]  # (tool_name, tool_id, args)


class ToolExecutionEngine:
    """
    Orchestrates tool execution with parallel-read / sequential-mutation batching.

    Usage:
        engine = ToolExecutionEngine(circuit_breaker)
        await engine.execute_turn(pending_calls, execute_fn, messages, PCM, limits)
    """

    def __init__(self, circuit_breaker: ToolCircuitBreaker) -> None:
        self._cb = circuit_breaker

        # Consecutive same read-only tool tracking
        self._last_tool_name: Optional[str] = None
        self._consecutive_same_tool: int = 0

    # ── Main entry ─────────────────────────────────────────────────

    async def execute_turn(
        self,
        parsed_calls: List[ParsedToolCall],
        execute_fn: Callable[..., Any],
        messages: List[Any],
        PCM: type,
        limits: Any,
    ) -> List[str]:
        """
        Execute a single turn's worth of tool calls.

        Args:
            parsed_calls: List of (tool_name, tool_id, args) tuples from the LLM.
            execute_fn: Async callable for executing one tool. Will be called
                        as execute_fn(tool_name, tool_id, args, messages, PCM, limits).
            messages: The conversation message list (will be appended to).
            PCM: The message constructor (e.g. ChatMessage or dataclass).
            limits: The ToolLimitsLike instance for this turn.

        Returns:
            List of nudge messages to inject into the conversation (empty if none).
        """
        nudges: List[str] = []
        tool_messages = []

        # ── Detect consecutive same read-only tool ─────────────────
        _turn_tool_names: Set[str] = set(t[0] for t in parsed_calls)
        if len(_turn_tool_names) == 1:
            _single_name = next(iter(_turn_tool_names))
            if _single_name in _READ_ONLY_TOOLS:
                if _single_name == self._last_tool_name:
                    self._consecutive_same_tool += 1
                else:
                    self._last_tool_name = _single_name
                    self._consecutive_same_tool = 1

                if self._consecutive_same_tool >= _CONSECUTIVE_READONLY_LIMIT:
                    log.warning(
                        f"[BRIDGE] Consecutive read-only tool: {_single_name} "
                        f"called {self._consecutive_same_tool} turns in a row. Injecting nudge."
                    )
                    nudges.append(
                        f"WARNING: You have called {_single_name} "
                        f"{self._consecutive_same_tool} turns in a row without writing any code. "
                        f"Stop searching and START IMPLEMENTING. Use Write or Edit tools "
                        f"to create/modify files. Summarize what you know and take action NOW."
                    )
            else:
                self._last_tool_name = _single_name
                self._consecutive_same_tool = 0
        else:
            self._last_tool_name = None
            self._consecutive_same_tool = 0

        # ── Build execution batches ────────────────────────────────
        batches = self._build_batches(parsed_calls)

        for batch in batches:
            # ── Circuit breaker: filter disabled tools ───────────
            filtered_batch = self._filter_batch(batch, messages, PCM)

            if not filtered_batch:
                continue

            # ── Execute batch ────────────────────────────────────
            if len(filtered_batch) == 1:
                t_name, t_id, t_args = filtered_batch[0]
                result_msg = await execute_fn(t_name, t_id, t_args, messages, PCM, limits)
                if result_msg:
                    tool_messages.append(result_msg)
            else:
                log.info(
                    f"[BRIDGE] Running {len(filtered_batch)} tools in parallel: "
                    + ", ".join(b[0] for b in filtered_batch)
                )
                tasks = [
                    execute_fn(t_name, t_id, t_args, messages, PCM, limits)
                    for t_name, t_id, t_args in filtered_batch
                ]
                results = await asyncio.gather(*tasks)
                for r in results:
                    if r:
                        tool_messages.append(r)

        return nudges

    # ── Batch building ─────────────────────────────────────────────

    def _build_batches(self, parsed_calls: List[ParsedToolCall]) -> List[List[ParsedToolCall]]:
        """
        Group tool calls into execution batches.

        Consecutive read-only tools are grouped into a single parallel batch.
        Each mutating tool gets its own sequential batch.
        """
        batches: List[List[ParsedToolCall]] = []
        current_parallel: List[ParsedToolCall] = []

        for call in parsed_calls:
            if call[0] in _READ_ONLY_TOOLS:
                current_parallel.append(call)
            else:
                if current_parallel:
                    batches.append(current_parallel)
                    current_parallel = []
                batches.append([call])

        if current_parallel:
            batches.append(current_parallel)

        return batches

    # ── Circuit breaker filtering ──────────────────────────────────

    def _filter_batch(
        self,
        batch: List[ParsedToolCall],
        messages: List[Any],
        PCM: type,
    ) -> List[ParsedToolCall]:
        """
        Filter a batch through the circuit breaker, appending error messages
        for disabled or over-limit tools. Returns the list of allowed calls.
        """
        filtered: List[ParsedToolCall] = []

        for t_name, t_id, t_args in batch:
            # Read should never stay blocked across loop retries
            if t_name == "Read" and self._cb.is_disabled("Read"):
                # Clear read from disabled — it was likely a transient issue
                pass  # handled by the check below

            err = self._cb.check_and_increment_total(t_name)
            if err is not None:
                log.warning(
                    f"[BRIDGE] Circuit breaker: {t_name} blocked: {err[:80]}"
                )
                messages.append(
                    PCM(role="tool", content=err, tool_call_id=t_id)
                )
            else:
                filtered.append((t_name, t_id, t_args))

        return filtered

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def get_activity_name(tool_name: str) -> str:
        """Return the UI activity card name for a tool."""
        return _TOOL_TO_ACTIVITY.get(tool_name, tool_name.lower())

    @staticmethod
    def is_read_only(tool_name: str) -> bool:
        """Return True if the tool is safe to run in parallel."""
        return tool_name in _READ_ONLY_TOOLS
