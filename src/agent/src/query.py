# ------------------------------------------------------------
# query.py
# Python conversion of query.ts (lines 1-1730)
# 
# Core query engine for multi-LLM orchestration supporting:
# - Cortex (Anthropic), OpenAI, Gemini, DeepSeek, Minimax, Grok
# - Streaming API calls with fallback models
# - Tool execution orchestration (streaming and batch modes)
# - Auto-compaction, reactive compaction, context collapse
# - Token budget tracking and max output recovery
# - Stop hooks, post-sampling hooks, attachment processing
# - Memory prefetch, skill discovery, command queue management
# - Multi-turn conversation loops with state management
# ------------------------------------------------------------

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple, Union


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from .hooks.use_can_use_tool import CanUseToolFn
except ImportError:
    CanUseToolFn = Any

try:
    from .services.api.with_retry import FallbackTriggeredError
except ImportError:
    class FallbackTriggeredError(Exception):
        def __init__(self, original_model: str, fallback_model: str):
            self.original_model = original_model
            self.fallback_model = fallback_model
            super().__init__(f"Fallback triggered: {original_model} -> {fallback_model}")

try:
    from .services.compact.auto_compact import (
        calculate_token_warning_state,
        is_auto_compact_enabled,
        AutoCompactTrackingState,
    )
except ImportError:
    def calculate_token_warning_state(token_count: int, model: str) -> dict:
        return {'isAtBlockingLimit': False}
    
    def is_auto_compact_enabled() -> bool:
        return False
    
    AutoCompactTrackingState = Optional[Dict[str, Any]]

try:
    from .services.compact.compact import build_post_compact_messages
except ImportError:
    def build_post_compact_messages(compaction_result: dict) -> List[dict]:
        return []

try:
    from .utils.image_validation import ImageSizeError
except ImportError:
    class ImageSizeError(Exception):
        pass

try:
    from .utils.image_resizer import ImageResizeError
except ImportError:
    class ImageResizeError(Exception):
        pass

try:
    from .Tool import find_tool_by_name, ToolUseContext
except ImportError:
    def find_tool_by_name(tools: list, name: str):
        return None
    
    ToolUseContext = Dict[str, Any]

try:
    from .utils.system_prompt_type import as_system_prompt, SystemPrompt
except ImportError:
    def as_system_prompt(prompt: str) -> str:
        return prompt
    
    SystemPrompt = str

try:
    from .agent_types.message import (
        AssistantMessage,
        AttachmentMessage,
        Message,
        RequestStartEvent,
        StreamEvent,
        ToolUseSummaryMessage,
        UserMessage,
        TombstoneMessage,
    )
except ImportError:
    AssistantMessage = Dict[str, Any]
    AttachmentMessage = Dict[str, Any]
    Message = Dict[str, Any]
    RequestStartEvent = Dict[str, Any]
    StreamEvent = Dict[str, Any]
    ToolUseSummaryMessage = Dict[str, Any]
    UserMessage = Dict[str, Any]
    TombstoneMessage = Dict[str, Any]

try:
    from .utils.log import log_error
except ImportError:
    def log_error(error: Exception) -> None:
        print(f"ERROR: {error}")

try:
    from .services.api.errors import (
        PROMPT_TOO_LONG_ERROR_MESSAGE,
        is_prompt_too_long_message,
    )
except ImportError:
    PROMPT_TOO_LONG_ERROR_MESSAGE = "Prompt too long"
    
    def is_prompt_too_long_message(msg: dict) -> bool:
        return msg.get('apiError') == 'prompt_too_long'

try:
    from .utils.debug import log_ant_error, log_for_debugging
except ImportError:
    def log_ant_error(context: str, error: Exception) -> None:
        log_error(error)
    
    def log_for_debugging(message: str) -> None:
        pass

try:
    from .utils.messages import (
        create_user_message,
        create_user_interruption_message,
        normalize_messages_for_api,
        create_system_message,
        create_assistant_api_error_message,
        get_messages_after_compact_boundary,
        create_tool_use_summary_message,
        create_microcompact_boundary_message,
        strip_signature_blocks,
    )
except ImportError:
    def create_user_message(**kwargs):
        return {'type': 'user', **kwargs}
    
    def create_user_interruption_message(**kwargs):
        return {'type': 'user', 'interruption': True, **kwargs}
    
    def normalize_messages_for_api(messages, tools):
        return messages
    
    def create_system_message(content: str, level: str = 'info'):
        return {'type': 'system', 'content': content, 'level': level}
    
    def create_assistant_api_error_message(**kwargs):
        return {'type': 'assistant', 'isApiErrorMessage': True, **kwargs}
    
    def get_messages_after_compact_boundary(messages):
        return messages
    
    def create_tool_use_summary_message(summary: str, tool_ids: list):
        return {'type': 'tool_use_summary', 'summary': summary}
    
    def create_microcompact_boundary_message(trigger: str, input_tokens: int, deleted_tokens: int, deleted_tool_ids: list, tool_ids: list):
        return {'type': 'microcompact_boundary'}
    
    def strip_signature_blocks(messages):
        return messages

try:
    from .services.tool_use_summary.tool_use_summary_generator import generate_tool_use_summary
except ImportError:
    async def generate_tool_use_summary(**kwargs):
        return None

try:
    from .utils.api import prepend_user_context, append_system_context
except ImportError:
    def prepend_user_context(messages: list, user_context: dict) -> list:
        return messages
    
    def append_system_context(system_prompt: str, system_context: dict) -> str:
        return system_prompt

try:
    from .utils.attachments import (
        create_attachment_message,
        filter_duplicate_memory_attachments,
        get_attachment_messages,
        start_relevant_memory_prefetch,
    )
except ImportError:
    def create_attachment_message(attachment: dict) -> dict:
        return {'type': 'attachment', 'attachment': attachment}
    
    def filter_duplicate_memory_attachments(attachments: list, file_state: dict) -> list:
        return attachments
    
    async def get_attachment_messages(*args, **kwargs):
        for item in []:
            yield item
    
    def start_relevant_memory_prefetch(messages: list, tool_context: dict):
        class DummyPrefetch:
            settled_at = None
            consumed_on_iteration = -1
            promise = asyncio.Future()
        return DummyPrefetch()

try:
    from .utils.message_queue_manager import (
        remove as remove_from_queue,
        get_commands_by_max_priority,
        is_slash_command,
    )
except ImportError:
    def remove_from_queue(commands):
        pass
    
    def get_commands_by_max_priority(mode: str) -> list:
        return []
    
    def is_slash_command(cmd: dict) -> bool:
        return False

try:
    from .utils.command_lifecycle import notify_command_lifecycle
except ImportError:
    def notify_command_lifecycle(uuid: str, status: str) -> None:
        pass

try:
    from .utils.headless_profiler import headless_profiler_checkpoint
except ImportError:
    def headless_profiler_checkpoint(label: str) -> None:
        pass

try:
    from .utils.model.model import get_runtime_main_loop_model, render_model_name
except ImportError:
    def get_runtime_main_loop_model(**kwargs) -> str:
        return "cortex-3-5-sonnet"
    
    def render_model_name(model: str) -> str:
        return model

try:
    from .utils.tokens import (
        does_most_recent_assistant_message_exceed_200k,
        final_context_tokens_from_last_response,
        token_count_with_estimation,
    )
except ImportError:
    def does_most_recent_assistant_message_exceed_200k(messages: list) -> bool:
        return False
    
    def final_context_tokens_from_last_response(messages: list) -> int:
        return 0
    
    def token_count_with_estimation(messages: list) -> int:
        return 0

try:
    from .utils.context import ESCALATED_MAX_TOKENS
except ImportError:
    ESCALATED_MAX_TOKENS = 64000

try:
    from .services.analytics.growthbook import get_feature_value_cached_may_be_stale
except ImportError:
    def get_feature_value_cached_may_be_stale(key: str, default: Any) -> Any:
        return default

try:
    from .tools.SleepTool.prompt import SLEEP_TOOL_NAME
except ImportError:
    SLEEP_TOOL_NAME = "sleep"

try:
    from .utils.hooks.post_sampling_hooks import execute_post_sampling_hooks
except ImportError:
    async def execute_post_sampling_hooks(*args, **kwargs):
        pass

try:
    from .utils.hooks import execute_stop_failure_hooks
except ImportError:
    async def execute_stop_failure_hooks(message: dict, tool_context: dict):
        pass

try:
    from .constants.query_source import QuerySource
except ImportError:
    QuerySource = str

try:
    from .services.api.dump_prompts import create_dump_prompts_fetch
except ImportError:
    def create_dump_prompts_fetch(agent_id: str):
        return None

try:
    from .services.tools.streaming_tool_executor import StreamingToolExecutor
except ImportError:
    class StreamingToolExecutor:
        def __init__(self, *args, **kwargs):
            pass
        
        def add_tool(self, tool_block: dict, message: dict):
            pass
        
        def get_completed_results(self):
            return []
        
        async def get_remaining_results(self):
            for item in []:
                yield item
        
        def discard(self):
            pass

try:
    from .utils.query_profiler import query_checkpoint
except ImportError:
    def query_checkpoint(label: str) -> None:
        pass

try:
    from .services.tools.tool_orchestration import run_tools
except ImportError:
    async def run_tools(tool_blocks: list, assistant_messages: list, can_use_tool, tool_context: dict):
        for item in []:
            yield item

try:
    from .utils.tool_result_storage import apply_tool_result_budget
except ImportError:
    async def apply_tool_result_budget(messages: list, replacement_state, persist_func, excluded_tools: set):
        return messages

try:
    from .utils.session_storage import record_content_replacement
except ImportError:
    async def record_content_replacement(records: list, agent_id: str):
        pass

try:
    from .query.stop_hooks import handle_stop_hooks
except ImportError:
    async def handle_stop_hooks(*args, **kwargs):
        return {'preventContinuation': False, 'blockingErrors': []}

try:
    from .query.config import build_query_config
except ImportError:
    def build_query_config():
        class DummyConfig:
            gates = type('Gates', (), {
                'streamingToolExecution': False,
                'fastModeEnabled': False,
                'isAnt': False,
                'emitToolUseSummaries': False,
            })()
            sessionId = "default-session"
        return DummyConfig()

try:
    from .query.deps import production_deps, QueryDeps
except ImportError:
    def production_deps():
        class DummyDeps:
            def uuid(self):
                import uuid
                return str(uuid.uuid4())
            
            async def call_model(self, **kwargs):
                for item in []:
                    yield item
            
            async def microcompact(self, messages, tool_context, query_source):
                return {'messages': messages, 'compactionInfo': None}
            
            async def autocompact(self, messages, tool_context, cache_params, query_source, tracking, snip_tokens_freed):
                return {'compactionResult': None, 'consecutiveFailures': None}
        return DummyDeps()
    
    QueryDeps = Any

try:
    from .query.transitions import Terminal, Continue
except ImportError:
    Terminal = Dict[str, Any]
    Continue = Dict[str, Any]

try:
    from .bootstrap.state import (
        get_current_turn_token_budget,
        get_turn_output_tokens,
        increment_budget_continuation_count,
    )
except ImportError:
    def get_current_turn_token_budget() -> int:
        return 0
    
    def get_turn_output_tokens() -> int:
        return 0
    
    def increment_budget_continuation_count():
        pass

try:
    from .query.token_budget import create_budget_tracker, check_token_budget
except ImportError:
    def create_budget_tracker():
        return None
    
    def check_token_budget(tracker, agent_id, budget, output_tokens):
        return {'action': 'complete'}

try:
    from .utils.array import count
except ImportError:
    def count(items: list, predicate) -> int:
        return sum(1 for item in items if predicate(item))


# ============================================================
# CONSTANTS
# ============================================================

MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3


# ============================================================
# TYPE DEFINITIONS
# ============================================================

QueryParams = Dict[str, Any]
State = Dict[str, Any]


class QueryTerminal(Exception):
    """
    Sentinel exception used to carry terminal state out of async generators.

    Python async generators cannot use `return value` — only bare `return`.
    Instead, `query_loop()` raises QueryTerminal(value) to signal completion,
    and `query()` catches it and returns the terminal dict normally.
    """

    def __init__(self, terminal: Dict[str, Any]):
        super().__init__(f"query ended: {terminal}")
        self.terminal = terminal


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def yield_missing_tool_result_blocks(
    assistant_messages: List[AssistantMessage],
    error_message: str,
) -> List[UserMessage]:
    """
    Generate interruption messages for tool uses without results.
    
    When streaming fails or is aborted, any tool_use blocks that don't have
    matching tool_result blocks need synthetic error results.
    
    Args:
        assistant_messages: Assistant messages that may contain tool_use blocks
        error_message: Error message to include in tool_result
    
    Returns:
        List of user messages with tool_result blocks
    """
    result_messages = []
    
    for assistant_message in assistant_messages:
        # Extract all tool use blocks from this assistant message
        tool_use_blocks = [
            content for content in assistant_message.get('message', {}).get('content', [])
            if content.get('type') == 'tool_use'
        ]
        
        # Emit an interruption message for each tool use
        for tool_use in tool_use_blocks:
            result_messages.append(create_user_message(
                content=[{
                    'type': 'tool_result',
                    'content': error_message,
                    'is_error': True,
                    'tool_use_id': tool_use['id'],
                }],
                toolUseResult=error_message,
                sourceToolAssistantUUID=assistant_message.get('uuid'),
            ))
    
    return result_messages


def is_withheld_max_output_tokens(msg: Optional[Union[Message, StreamEvent]]) -> bool:
    """
    Check if this is a max_output_tokens error message that should be withheld.
    
    If so, the streaming loop should withhold it from SDK callers until we know
    whether the recovery loop can continue. Yielding early leaks an intermediate
    error to SDK callers (e.g. cowork/desktop) that terminate the session on any
    `error` field — the recovery loop keeps running but nobody is listening.
    
    Mirrors reactiveCompact.isWithheldPromptTooLong.
    
    Args:
        msg: Message or stream event to check
    
    Returns:
        True if this is a withheld max_output_tokens error
    """
    return (
        msg is not None and
        msg.get('type') == 'assistant' and
        msg.get('apiError') == 'max_output_tokens'
    )


# ============================================================
# MAIN QUERY GENERATOR
# ============================================================

async def query(params: QueryParams) -> AsyncGenerator[
    Union[StreamEvent, RequestStartEvent, Message, TombstoneMessage, ToolUseSummaryMessage],
    Terminal
]:
    """
    Main query generator that orchestrates the entire conversation loop.
    
    Supports multiple LLM providers:
    - Cortex (Anthropic)
    - OpenAI (GPT-4, GPT-3.5)
    - Google Gemini
    - DeepSeek
    - Minimax
    - Grok (xAI)
    
    The query loop handles:
    1. Context preparation (compaction, collapse, snip)
    2. API streaming with fallback support
    3. Tool execution (streaming or batch mode)
    4. Turn management and continuation logic
    5. Token budget enforcement
    6. Stop hook evaluation
    7. Attachment processing (memory, skills, commands)
    
    Args:
        params: Query parameters including:
            - messages: Conversation history
            - systemPrompt: System prompt
            - userContext: User-provided context
            - systemContext: System-provided context
            - canUseTool: Permission check function
            - toolUseContext: Tool execution context
            - fallbackModel: Model to fall back to on errors
            - querySource: Source identifier (repl, sdk, agent, etc.)
            - maxOutputTokensOverride: Override max tokens
            - maxTurns: Maximum number of turns
            - skipCacheWrite: Skip cache writes
            - taskBudget: API task budget
            - deps: Dependency overrides
    
    Yields:
        Stream events, messages, tombstones, and summaries
    
    Returns:
        Terminal state indicating why the query ended
    """
    consumed_command_uuids: List[str] = []
    
    try:
        async for _ in query_loop(params, consumed_command_uuids):
            pass  # all events yielded inline by query_loop
        terminal: Dict[str, Any] = {}
    except QueryTerminal as e:
        terminal = e.terminal

    for uuid in consumed_command_uuids:
        notify_command_lifecycle(uuid, 'completed')

    return terminal



async def query_loop(
    params: QueryParams,
    consumed_command_uuids: List[str],
) -> AsyncGenerator[
    Union[StreamEvent, RequestStartEvent, Message, TombstoneMessage, ToolUseSummaryMessage],
    Terminal
]:
    """
    Core query loop implementation.
    
    This is the main iteration loop that processes turns until completion,
    abortion, or error. Each iteration represents one turn of the conversation.
    
    The loop handles:
    - Context preparation and optimization
    - API calls with streaming
    - Tool execution
    - Continuation decisions
    - State management across turns
    
    Args:
        params: Query parameters (immutable)
        consumed_command_uuids: List to track consumed command UUIDs
    
    Yields:
        Stream events, messages, tombstones, and summaries
    
    Returns:
        Terminal state
    """
    # Immutable params — never reassigned during the query loop.
    system_prompt = params['systemPrompt']
    user_context = params['userContext']
    system_context = params['systemContext']
    can_use_tool = params['canUseTool']
    fallback_model = params.get('fallbackModel')
    query_source = params['querySource']
    max_turns = params.get('maxTurns')
    skip_cache_write = params.get('skipCacheWrite', False)
    
    deps = params.get('deps') or production_deps()
    
    # Mutable cross-iteration state. The loop body destructures this at the top
    # of each iteration so reads stay bare-name (`messages`, `toolUseContext`).
    # Continue sites write `state = { ... }` instead of 9 separate assignments.
    state: State = {
        'messages': params['messages'],
        'toolUseContext': params['toolUseContext'],
        'maxOutputTokensOverride': params.get('maxOutputTokensOverride'),
        'autoCompactTracking': None,
        'stopHookActive': None,
        'maxOutputTokensRecoveryCount': 0,
        'hasAttemptedReactiveCompact': False,
        'turnCount': 1,
        'pendingToolUseSummary': None,
        'transition': None,
    }
    
    budget_tracker = create_budget_tracker()
    
    # task_budget.remaining tracking across compaction boundaries. Undefined
    # until first compact fires — while context is uncompacted the server can
    # see the full history and handles the countdown from {total} itself. After
    # a compact, the server sees only the summary and would under-count spend;
    # remaining tells it the pre-compact final window that got summarized away.
    # Cumulative across multiple compacts: each subtracts the final context at
    # that compact's trigger point. Loop-local (not on State) to avoid touching
    # the 7 continue sites.
    task_budget_remaining: Optional[int] = None
    
    # Snapshot immutable env/statsig/session state once at entry. See QueryConfig
    # for what's included and why feature() gates are intentionally excluded.
    config = build_query_config()
    
    # Fired once per user turn — the prompt is invariant across loop iterations,
    # so per-iteration firing would ask sideQuery the same question N times.
    # Consume point polls settledAt (never blocks). `using` disposes on all
    # generator exit paths — see MemoryPrefetch for dispose/telemetry semantics.
    pending_memory_prefetch = start_relevant_memory_prefetch(
        state['messages'],
        state['toolUseContext'],
    )
    
    # Main loop - continues until termination condition
    while True:
        # Destructure state at the top of each iteration. toolUseContext alone
        # is reassigned within an iteration (queryTracking, messages updates);
        # the rest are read-only between continue sites.
        tool_use_context = state['toolUseContext']
        messages = state['messages']
        auto_compact_tracking = state['autoCompactTracking']
        max_output_tokens_recovery_count = state['maxOutputTokensRecoveryCount']
        has_attempted_reactive_compact = state['hasAttemptedReactiveCompact']
        max_output_tokens_override = state['maxOutputTokensOverride']
        pending_tool_use_summary = state['pendingToolUseSummary']
        stop_hook_active = state['stopHookActive']
        turn_count = state['turnCount']
        
        # Skill discovery prefetch — per-iteration (uses findWritePivot guard
        # that returns early on non-write iterations). Discovery runs while the
        # model streams and tools execute; awaited post-tools alongside the
        # memory prefetch consume. Replaces the blocking assistant_turn path
        # that ran inside getAttachmentMessages (97% of those calls found
        # nothing in prod). Turn-0 user-input discovery still blocks in
        # userInputAttachments — that's the one signal where there's no prior
        # work to hide under.
        # Note: skill_prefetch module may not exist
        pending_skill_prefetch = None
        
        yield {'type': 'stream_request_start'}
        
        query_checkpoint('query_fn_entry')
        
        # Record query start for headless latency tracking (skip for subagents)
        if not tool_use_context.get('agentId'):
            headless_profiler_checkpoint('query_started')
        
        # Initialize or increment query chain tracking
        query_tracking = tool_use_context.get('queryTracking')
        if query_tracking:
            query_tracking = {
                'chainId': query_tracking['chainId'],
                'depth': query_tracking['depth'] + 1,
            }
        else:
            query_tracking = {
                'chainId': deps.uuid(),
                'depth': 0,
            }
        
        query_chain_id_for_analytics = query_tracking['chainId']
        
        tool_use_context = {
            **tool_use_context,
            'queryTracking': query_tracking,
        }
        
        messages_for_query = list(get_messages_after_compact_boundary(messages))
        
        tracking = auto_compact_tracking
        
        # Enforce per-message budget on aggregate tool result size. Runs BEFORE
        # microcompact — cached MC operates purely by tool_use_id (never inspects
        # content), so content replacement is invisible to it and the two compose
        # cleanly. No-ops when contentReplacementState is undefined (feature off).
        # Persist only for querySources that read records back on resume: agentId
        # routes to sidechain file (AgentTool resume) or session file (/resume).
        # Ephemeral runForkedAgent callers (agent_summary etc.) don't persist.
        persist_replacements = (
            query_source.startswith('agent:') or
            query_source.startswith('repl_main_thread')
        )
        
        messages_for_query = await apply_tool_result_budget(
            messages_for_query,
            tool_use_context.get('contentReplacementState'),
            (lambda records: asyncio.ensure_future(
                record_content_replacement(records, tool_use_context.get('agentId'))
            ).add_done_callback(lambda f: f.exception() and log_error(f.exception())))
            if persist_replacements else None,
            set(
                t['name'] for t in tool_use_context['options']['tools']
                if not isinstance(t.get('maxResultSizeChars'), (int, float))
            ),
        )
        
        # Apply snip before microcompact (both may run — they are not mutually exclusive).
        # snipTokensFreed is plumbed to autocompact so its threshold check reflects
        # what snip removed; tokenCountWithEstimation alone can't see it (reads usage
        # from the protected-tail assistant, which survives snip unchanged).
        snip_tokens_freed = 0
        
        # Apply microcompact before autocompact
        query_checkpoint('query_microcompact_start')
        microcompact_result = await deps.microcompact(
            messages_for_query,
            tool_use_context,
            query_source,
        )
        messages_for_query = microcompact_result['messages']
        pending_cache_edits = microcompact_result.get('compactionInfo', {}).get('pendingCacheEdits')
        query_checkpoint('query_microcompact_end')
        
        # Project the collapsed context view and maybe commit more collapses.
        # Runs BEFORE autocompact so that if collapse gets us under the
        # autocompact threshold, autocompact is a no-op and we keep granular
        # context instead of a single summary.
        # Nothing is yielded — the collapsed view is a read-time projection
        # over the REPL's full history. Summary messages live in the collapse
        # store, not the REPL array. This is what makes collapses persist
        # across turns: projectView() replays the commit log on every entry.
        # Within a turn, the view flows forward via state.messages at the
        # continue site, and the next projectView() no-ops because the archived
        # messages are already gone from its input.
        
        full_system_prompt = as_system_prompt(
            append_system_context(system_prompt, system_context)
        )
        
        query_checkpoint('query_autocompact_start')
        compaction_data = await deps.autocompact(
            messages_for_query,
            tool_use_context,
            {
                'systemPrompt': system_prompt,
                'userContext': user_context,
                'systemContext': system_context,
                'toolUseContext': tool_use_context,
                'forkContextMessages': messages_for_query,
            },
            query_source,
            tracking,
            snip_tokens_freed,
        )
        compaction_result = compaction_data.get('compactionResult')
        consecutive_failures = compaction_data.get('consecutiveFailures')
        query_checkpoint('query_autocompact_end')
        
        if compaction_result:
            pre_compact_token_count = compaction_result['preCompactTokenCount']
            post_compact_token_count = compaction_result['postCompactTokenCount']
            true_post_compact_token_count = compaction_result['truePostCompactTokenCount']
            compaction_usage = compaction_result.get('compactionUsage')
            
            # Log compaction success
            # Note: log_event would go here
            
            # task_budget: capture pre-compact final context window before
            # messagesForQuery is replaced with postCompactMessages below.
            # iterations[-1] is the authoritative final window (post server tool
            # loops); see #304930.
            if params.get('taskBudget'):
                pre_compact_context = final_context_tokens_from_last_response(messages_for_query)
                task_budget_remaining = max(
                    0,
                    (task_budget_remaining or params['taskBudget']['total']) - pre_compact_context,
                )
            
            # Reset on every compact so turnCounter/turnId reflect the MOST RECENT
            # compact. recompactionInfo already captured the old values for
            # turnsSincePreviousCompact/previousCompactTurnId before the call.
            tracking = {
                'compacted': True,
                'turnId': deps.uuid(),
                'turnCounter': 0,
                'consecutiveFailures': 0,
            }
            
            post_compact_messages = build_post_compact_messages(compaction_result)
            
            for message in post_compact_messages:
                yield message
            
            # Continue on with the current query call using the post compact messages
            messages_for_query = post_compact_messages
        
        elif consecutive_failures is not None:
            # Autocompact failed — propagate failure count so the circuit breaker
            # can stop retrying on the next iteration.
            tracking = {
                **(tracking or {'compacted': False, 'turnId': '', 'turnCounter': 0}),
                'consecutiveFailures': consecutive_failures,
            }
        
        # Update toolUseContext.messages
        tool_use_context = {
            **tool_use_context,
            'messages': messages_for_query,
        }
        
        assistant_messages: List[AssistantMessage] = []
        tool_results: List[Union[UserMessage, AttachmentMessage]] = []
        tool_use_blocks: List[dict] = []
        needs_follow_up = False
        
        query_checkpoint('query_setup_start')
        use_streaming_tool_execution = config.gates.streamingToolExecution
        streaming_tool_executor = (
            StreamingToolExecutor(
                tool_use_context['options']['tools'],
                can_use_tool,
                tool_use_context,
            )
            if use_streaming_tool_execution
            else None
        )
        
        app_state = tool_use_context['getAppState']()
        permission_mode = app_state['toolPermissionContext']['mode']
        current_model = get_runtime_main_loop_model(
            permissionMode=permission_mode,
            mainLoopModel=tool_use_context['options']['mainLoopModel'],
            exceeds200kTokens=(
                permission_mode == 'plan' and
                does_most_recent_assistant_message_exceed_200k(messages_for_query)
            ),
        )
        
        query_checkpoint('query_setup_end')
        
        # Create fetch wrapper once per query session to avoid memory retention.
        # Each call to createDumpPromptsFetch creates a closure that captures the request body.
        # Creating it once means only the latest request body is retained (~700KB),
        # instead of all request bodies from the session (~500MB for long sessions).
        dump_prompts_fetch = (
            create_dump_prompts_fetch(tool_use_context.get('agentId') or config.sessionId)
            if config.gates.isAnt
            else None
        )
        
        # Block if we've hit the hard blocking limit (only applies when auto-compact is OFF)
        # This reserves space so users can still run /compact manually
        # Skip this check if compaction just happened - the compaction result is already
        # validated to be under the threshold.
        collapse_owns_it = False
        
        if (
            not compaction_result and
            query_source not in ('compact', 'session_memory') and
            not collapse_owns_it
        ):
            token_count = token_count_with_estimation(messages_for_query) - snip_tokens_freed
            warning_state = calculate_token_warning_state(token_count, tool_use_context['options']['mainLoopModel'])
            
            if warning_state['isAtBlockingLimit']:
                yield create_assistant_api_error_message(
                    content=PROMPT_TOO_LONG_ERROR_MESSAGE,
                    error='invalid_request',
                )
                return  # StopAsyncIteration carries terminal as .value
        
        attempt_with_fallback = True
        
        query_checkpoint('query_api_loop_start')
        try:
            while attempt_with_fallback:
                attempt_with_fallback = False
                try:
                    streaming_fallback_occurred = False
                    query_checkpoint('query_api_streaming_start')
                    
                    async for message in deps.call_model(
                        messages=prepend_user_context(messages_for_query, user_context),
                        systemPrompt=full_system_prompt,
                        thinkingConfig=tool_use_context['options'].get('thinkingConfig'),
                        tools=tool_use_context['options']['tools'],
                        signal=tool_use_context['abortController']['signal'],
                        options={
                            'model': current_model,
                            'toolChoice': None,
                            'isNonInteractiveSession': tool_use_context['options'].get('isNonInteractiveSession'),
                            'fallbackModel': fallback_model,
                            'onStreamingFallback': lambda: setattr(streaming_fallback_occurred, 'value', True),
                            'querySource': query_source,
                            'agents': tool_use_context['options']['agentDefinitions'].get('activeAgents', []),
                            'allowedAgentTypes': tool_use_context['options']['agentDefinitions'].get('allowedAgentTypes'),
                            'hasAppendSystemPrompt': bool(tool_use_context['options'].get('appendSystemPrompt')),
                            'maxOutputTokensOverride': max_output_tokens_override,
                            'fetchOverride': dump_prompts_fetch,
                            'mcpTools': app_state['mcp']['tools'],
                            'hasPendingMcpServers': any(
                                c['type'] == 'pending'
                                for c in app_state['mcp']['clients']
                            ),
                            'queryTracking': query_tracking,
                            'effortValue': app_state.get('effortValue'),
                            'advisorModel': app_state.get('advisorModel'),
                            'skipCacheWrite': skip_cache_write,
                            'agentId': tool_use_context.get('agentId'),
                            'addNotification': tool_use_context.get('addNotification'),
                            **(
                                {
                                    'taskBudget': {
                                        'total': params['taskBudget']['total'],
                                        **({'remaining': task_budget_remaining} if task_budget_remaining is not None else {}),
                                    }
                                }
                                if params.get('taskBudget')
                                else {}
                            ),
                        },
                    ):
                        # We won't use the tool_calls from the first attempt
                        # We could.. but then we'd have to merge assistant messages
                        # with different ids and double up on full the tool_results
                        if streaming_fallback_occurred:
                            # Yield tombstones for orphaned messages so they're removed from UI and transcript.
                            # These partial messages (especially thinking blocks) have invalid signatures
                            # that would cause "thinking blocks cannot be modified" API errors.
                            for msg in assistant_messages:
                                yield {'type': 'tombstone', 'message': msg}
                            
                            assistant_messages.clear()
                            tool_results.clear()
                            tool_use_blocks.clear()
                            needs_follow_up = False
                            
                            # Discard pending results from the failed streaming attempt and create
                            # a fresh executor. This prevents orphan tool_results (with old tool_use_ids)
                            # from being yielded after the fallback response arrives.
                            if streaming_tool_executor:
                                streaming_tool_executor.discard()
                                streaming_tool_executor = StreamingToolExecutor(
                                    tool_use_context['options']['tools'],
                                    can_use_tool,
                                    tool_use_context,
                                )
                        
                        # Backfill tool_use inputs on a cloned message before yield so
                        # SDK stream output and transcript serialization see legacy/derived
                        # fields. The original `message` is left untouched for
                        # assistantMessages.push below — it flows back to the API and
                        # mutating it would break prompt caching (byte mismatch).
                        yield_message = message
                        
                        if message.get('type') == 'assistant':
                            cloned_content = None
                            for i, block in enumerate(message['message']['content']):
                                if (
                                    block.get('type') == 'tool_use' and
                                    isinstance(block.get('input'), dict) and
                                    block['input'] is not None
                                ):
                                    tool = find_tool_by_name(
                                        tool_use_context['options']['tools'],
                                        block['name'],
                                    )
                                    
                                    if tool and hasattr(tool, 'backfill_observable_input'):
                                        original_input = block['input']
                                        input_copy = dict(original_input)
                                        tool.backfill_observable_input(input_copy)
                                        
                                        # Only yield a clone when backfill ADDED fields; skip if
                                        # it only OVERWROTE existing ones (e.g. file tools
                                        # expanding file_path). Overwrites change the serialized
                                        # transcript and break VCR fixture hashes on resume,
                                        # while adding nothing the SDK stream needs.
                                        added_fields = any(k not in original_input for k in input_copy)
                                        
                                        if added_fields:
                                            if cloned_content is None:
                                                cloned_content = list(message['message']['content'])
                                            cloned_content[i] = {**block, 'input': input_copy}
                            
                            if cloned_content:
                                yield_message = {
                                    **message,
                                    'message': {**message['message'], 'content': cloned_content},
                                }
                        
                        # Withhold recoverable errors (prompt-too-long, max-output-tokens)
                        # until we know whether recovery can succeed. Still pushed to
                        # assistantMessages so the recovery checks below find them.
                        withheld = False
                        
                        if is_withheld_max_output_tokens(message):
                            withheld = True
                        
                        if not withheld:
                            yield yield_message
                        
                        if message.get('type') == 'assistant':
                            assistant_messages.append(message)
                            
                            msg_tool_use_blocks = [
                                content for content in message['message']['content']
                                if content.get('type') == 'tool_use'
                            ]
                            
                            if msg_tool_use_blocks:
                                tool_use_blocks.extend(msg_tool_use_blocks)
                                needs_follow_up = True
                            
                            if streaming_tool_executor and not tool_use_context['abortController']['signal'].get('aborted'):
                                for tool_block in msg_tool_use_blocks:
                                    streaming_tool_executor.add_tool(tool_block, message)
                        
                        if streaming_tool_executor and not tool_use_context['abortController']['signal'].get('aborted'):
                            for result in streaming_tool_executor.get_completed_results():
                                if result.get('message'):
                                    yield result['message']
                                    tool_results.extend([
                                        m for m in normalize_messages_for_api(
                                            [result['message']],
                                            tool_use_context['options']['tools'],
                                        )
                                        if m.get('type') == 'user'
                                    ])
                    
                    query_checkpoint('query_api_streaming_end')
                    
                    # Yield deferred microcompact boundary message using actual API-reported
                    # token deletion count instead of client-side estimates.
                    if pending_cache_edits:
                        last_assistant = assistant_messages[-1] if assistant_messages else None
                        usage = last_assistant['message'].get('usage') if last_assistant else None
                        cumulative_deleted = (
                            (usage or {}).get('cache_deleted_input_tokens', 0)
                            if usage
                            else 0
                        )
                        deleted_tokens = max(
                            0,
                            cumulative_deleted - pending_cache_edits['baselineCacheDeletedTokens'],
                        )
                        
                        if deleted_tokens > 0:
                            yield create_microcompact_boundary_message(
                                pending_cache_edits['trigger'],
                                0,
                                deleted_tokens,
                                pending_cache_edits['deletedToolIds'],
                                [],
                            )
                
                except FallbackTriggeredError as inner_error:
                    if fallback_model:
                        # Fallback was triggered - switch model and retry
                        current_model = fallback_model
                        attempt_with_fallback = True
                        
                        # Clear assistant messages since we'll retry the entire request
                        for msg in yield_missing_tool_result_blocks(assistant_messages, 'Model fallback triggered'):
                            yield msg
                        
                        assistant_messages.clear()
                        tool_results.clear()
                        tool_use_blocks.clear()
                        needs_follow_up = False
                        
                        # Discard pending results from the failed attempt and create a
                        # fresh executor. This prevents orphan tool_results (with old
                        # tool_use_ids) from leaking into the retry.
                        if streaming_tool_executor:
                            streaming_tool_executor.discard()
                            streaming_tool_executor = StreamingToolExecutor(
                                tool_use_context['options']['tools'],
                                can_use_tool,
                                tool_use_context,
                            )
                        
                        # Update tool use context with new model
                        tool_use_context['options']['mainLoopModel'] = fallback_model
                        
                        # Thinking signatures are model-bound: replaying a protected-thinking
                        # block to an unprotected fallback 400s. Strip before retry.
                        import os
                        if os.environ.get('USER_TYPE') == 'ant':
                            messages_for_query = strip_signature_blocks(messages_for_query)
                        
                        # Log the fallback event
                        # Note: log_event would go here
                        
                        # Yield system message about fallback
                        yield create_system_message(
                            f"Switched to {render_model_name(inner_error.fallback_model)} due to high demand for {render_model_name(inner_error.original_model)}",
                            'warning',
                        )
                        
                        continue
                
                raise
        
        except Exception as error:
            log_error(error)
            error_message = str(error) if isinstance(error, Exception) else str(error)
            
            # Note: log_event would go here
            
            # Handle image size/resize errors with user-friendly messages
            if isinstance(error, (ImageSizeError, ImageResizeError)):
                yield create_assistant_api_error_message(content=str(error))
                raise QueryTerminal({'reason': 'image_error'})
            
            # Generally queryModelWithStreaming should not throw errors but instead
            # yield them as synthetic assistant messages. However if it does throw
            # due to a bug, we may end up in a state where we have already emitted
            # a tool_use block but will stop before emitting the tool_result.
            for msg in yield_missing_tool_result_blocks(assistant_messages, error_message):
                yield msg
            
            # Surface the real error instead of a misleading "[Request interrupted
            # by user]" — this path is a model/runtime failure, not a user action.
            yield create_assistant_api_error_message(content=error_message)
            
            # To help track down bugs, log loudly for ants
            log_ant_error('Query error', error)
            raise QueryTerminal({'reason': 'model_error', 'error': error})
        
        # Execute post-sampling hooks after model response is complete
        if assistant_messages:
            asyncio.ensure_future(execute_post_sampling_hooks(
                [*messages_for_query, *assistant_messages],
                system_prompt,
                user_context,
                system_context,
                tool_use_context,
                query_source,
            ))
        
        # We need to handle a streaming abort before anything else.
        # When using streamingToolExecutor, we must consume getRemainingResults() so the
        # executor can generate synthetic tool_result blocks for queued/in-progress tools.
        # Without this, tool_use blocks would lack matching tool_result blocks.
        if tool_use_context['abortController']['signal'].get('aborted'):
            if streaming_tool_executor:
                # Consume remaining results - executor generates synthetic tool_results for
                # aborted tools since it checks the abort signal in executeTool()
                async for update in streaming_tool_executor.get_remaining_results():
                    if update.get('message'):
                        yield update['message']
            else:
                for msg in yield_missing_tool_result_blocks(assistant_messages, 'Interrupted by user'):
                    yield msg
            
            # Skip the interruption message for submit-interrupts — the queued
            # user message that follows provides sufficient context.
            if tool_use_context['abortController']['signal'].get('reason') != 'interrupt':
                yield create_user_interruption_message(toolUse=False)
            
            raise QueryTerminal({'reason': 'aborted_streaming'})
        
        # Yield tool use summary from previous turn — haiku (~1s) resolved during model streaming (5-30s)
        if pending_tool_use_summary:
            summary = await pending_tool_use_summary
            if summary:
                yield summary
        
        if not needs_follow_up:
            last_message = assistant_messages[-1] if assistant_messages else None
            
            # Prompt-too-long recovery: the streaming loop withheld the error.
            # Try reactive compact. Single-shot on each — if a retry still 413's,
            # the next stage handles it or the error surfaces.
            is_withheld_413 = (
                last_message and
                last_message.get('type') == 'assistant' and
                last_message.get('isApiErrorMessage') and
                is_prompt_too_long_message(last_message)
            )
            
            if is_withheld_413:
                # No recovery — surface the withheld error and exit. Do NOT fall
                # through to stop hooks: the model never produced a valid response,
                # so hooks have nothing meaningful to evaluate. Running stop hooks
                # on prompt-too-long creates a death spiral: error → hook blocking
                # → retry → error → … (the hook injects more tokens each cycle).
                yield last_message
                asyncio.ensure_future(execute_stop_failure_hooks(last_message, tool_use_context))
                raise QueryTerminal({'reason': 'prompt_too_long'})
            
            # Check for max_output_tokens and inject recovery message. The error
            # was withheld from the stream above; only surface it if recovery
            # exhausts.
            if is_withheld_max_output_tokens(last_message):
                # Escalating retry: if we used the capped 8k default and hit the
                # limit, retry the SAME request at 64k — no meta message, no
                # multi-turn dance. This fires once per turn (guarded by the
                # override check), then falls through to multi-turn recovery if
                # 64k also hits the cap.
                cap_enabled = get_feature_value_cached_may_be_stale('tengu_otk_slot_v1', False)
                
                if (
                    cap_enabled and
                    max_output_tokens_override is None and
                    not os.environ.get('CORTEX_CODE_MAX_OUTPUT_TOKENS')
                ):
                    # Note: log_event would go here
                    
                    state = {
                        'messages': messages_for_query,
                        'toolUseContext': tool_use_context,
                        'autoCompactTracking': tracking,
                        'maxOutputTokensRecoveryCount': max_output_tokens_recovery_count,
                        'hasAttemptedReactiveCompact': has_attempted_reactive_compact,
                        'maxOutputTokensOverride': ESCALATED_MAX_TOKENS,
                        'pendingToolUseSummary': None,
                        'stopHookActive': None,
                        'turnCount': turn_count,
                        'transition': {'reason': 'max_output_tokens_escalate'},
                    }
                    continue
                
                if max_output_tokens_recovery_count < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT:
                    recovery_message = create_user_message(
                        content=(
                            "Output token limit hit. Resume directly — no apology, no recap of what you were doing. "
                            "Pick up mid-thought if that is where the cut happened. Break remaining work into smaller pieces."
                        ),
                        isMeta=True,
                    )
                    
                    state = {
                        'messages': [*messages_for_query, *assistant_messages, recovery_message],
                        'toolUseContext': tool_use_context,
                        'autoCompactTracking': tracking,
                        'maxOutputTokensRecoveryCount': max_output_tokens_recovery_count + 1,
                        'hasAttemptedReactiveCompact': has_attempted_reactive_compact,
                        'maxOutputTokensOverride': None,
                        'pendingToolUseSummary': None,
                        'stopHookActive': None,
                        'turnCount': turn_count,
                        'transition': {
                            'reason': 'max_output_tokens_recovery',
                            'attempt': max_output_tokens_recovery_count + 1,
                        },
                    }
                    continue
                
                # Recovery exhausted — surface the withheld error now.
                yield last_message
            
            # Skip stop hooks when the last message is an API error (rate limit,
            # prompt-too-long, auth failure, etc.). The model never produced a
            # real response — hooks evaluating it create a death spiral.
            if last_message and last_message.get('isApiErrorMessage'):
                asyncio.ensure_future(execute_stop_failure_hooks(last_message, tool_use_context))
                raise QueryTerminal({'reason': 'completed'})
            
            stop_hook_result = await handle_stop_hooks(
                messages_for_query,
                assistant_messages,
                system_prompt,
                user_context,
                system_context,
                tool_use_context,
                query_source,
                stop_hook_active,
            )
            
            if stop_hook_result['preventContinuation']:
                raise QueryTerminal({'reason': 'stop_hook_prevented'})
            
            if stop_hook_result['blockingErrors']:
                state = {
                    'messages': [*messages_for_query, *assistant_messages, *stop_hook_result['blockingErrors']],
                    'toolUseContext': tool_use_context,
                    'autoCompactTracking': tracking,
                    'maxOutputTokensRecoveryCount': 0,
                    'hasAttemptedReactiveCompact': has_attempted_reactive_compact,
                    'maxOutputTokensOverride': None,
                    'pendingToolUseSummary': None,
                    'stopHookActive': True,
                    'turnCount': turn_count,
                    'transition': {'reason': 'stop_hook_blocking'},
                }
                continue
            
            # Token budget check
            if budget_tracker:
                decision = check_token_budget(
                    budget_tracker,
                    tool_use_context.get('agentId'),
                    get_current_turn_token_budget(),
                    get_turn_output_tokens(),
                )
                
                if decision['action'] == 'continue':
                    increment_budget_continuation_count()
                    log_for_debugging(
                        f"Token budget continuation: {decision['pct']}% ({decision['turnTokens']:,} / {decision['budget']:,})"
                    )
                    
                    state = {
                        'messages': [
                            *messages_for_query,
                            *assistant_messages,
                            create_user_message(
                                content=decision['nudgeMessage'],
                                isMeta=True,
                            ),
                        ],
                        'toolUseContext': tool_use_context,
                        'autoCompactTracking': tracking,
                        'maxOutputTokensRecoveryCount': 0,
                        'hasAttemptedReactiveCompact': False,
                        'maxOutputTokensOverride': None,
                        'pendingToolUseSummary': None,
                        'stopHookActive': None,
                        'turnCount': turn_count,
                        'transition': {'reason': 'token_budget_continuation'},
                    }
                    continue
                
                if decision.get('completionEvent'):
                    if decision['completionEvent'].get('diminishingReturns'):
                        log_for_debugging(
                            f"Token budget early stop: diminishing returns at {decision['completionEvent']['pct']}%"
                        )
                    # Note: log_event would go here
            
            raise QueryTerminal({'reason': 'completed'})
        
        should_prevent_continuation = False
        updated_tool_use_context = tool_use_context
        
        query_checkpoint('query_tool_execution_start')
        
        if streaming_tool_executor:
            # Note: log_event would go here
            pass
        else:
            # Note: log_event would go here
            pass
        
        tool_updates = (
            streaming_tool_executor.get_remaining_results()
            if streaming_tool_executor
            else run_tools(tool_use_blocks, assistant_messages, can_use_tool, tool_use_context)
        )
        
        async for update in tool_updates:
            if update.get('message'):
                yield update['message']
                
                if (
                    update['message'].get('type') == 'attachment' and
                    update['message']['attachment'].get('type') == 'hook_stopped_continuation'
                ):
                    should_prevent_continuation = True
                
                tool_results.extend([
                    m for m in normalize_messages_for_api(
                        [update['message']],
                        tool_use_context['options']['tools'],
                    )
                    if m.get('type') == 'user'
                ])
            
            if update.get('newContext'):
                updated_tool_use_context = {
                    **update['newContext'],
                    'queryTracking': query_tracking,
                }
        
        query_checkpoint('query_tool_execution_end')
        
        # Generate tool use summary after tool batch completes — passed to next recursive call
        next_pending_tool_use_summary = None
        
        if (
            config.gates.emitToolUseSummaries and
            tool_use_blocks and
            not tool_use_context['abortController']['signal'].get('aborted') and
            not tool_use_context.get('agentId')  # subagents don't surface in mobile UI
        ):
            # Extract the last assistant text block for context
            last_assistant_message = assistant_messages[-1] if assistant_messages else None
            last_assistant_text = None
            
            if last_assistant_message:
                text_blocks = [
                    block for block in last_assistant_message['message']['content']
                    if block.get('type') == 'text'
                ]
                
                if text_blocks:
                    last_text_block = text_blocks[-1]
                    if 'text' in last_text_block:
                        last_assistant_text = last_text_block['text']
            
            # Collect tool info for summary generation
            tool_use_ids = [block['id'] for block in tool_use_blocks]
            tool_info_for_summary = []
            
            for block in tool_use_blocks:
                # Find the corresponding tool result
                tool_result = next(
                    (
                        result for result in tool_results
                        if (
                            result.get('type') == 'user' and
                            isinstance(result.get('message', {}).get('content'), list) and
                            any(
                                content.get('type') == 'tool_result' and
                                content.get('tool_use_id') == block['id']
                                for content in result['message']['content']
                            )
                        )
                    ),
                    None,
                )
                
                result_content = (
                    next(
                        (
                            c for c in tool_result['message']['content']
                            if c.get('type') == 'tool_result' and c.get('tool_use_id') == block['id']
                        ),
                        None,
                    )
                    if tool_result and tool_result.get('type') == 'user' and isinstance(tool_result.get('message', {}).get('content'), list)
                    else None
                )
                
                tool_info_for_summary.append({
                    'name': block['name'],
                    'input': block['input'],
                    'output': result_content.get('content') if result_content and 'content' in result_content else None,
                })
            
            # Fire off summary generation without blocking the next API call
            next_pending_tool_use_summary = asyncio.ensure_future(
                generate_tool_use_summary(
                    tools=tool_info_for_summary,
                    signal=tool_use_context['abortController']['signal'],
                    isNonInteractiveSession=tool_use_context['options'].get('isNonInteractiveSession'),
                    lastAssistantText=last_assistant_text,
                )
                .then(lambda summary: create_tool_use_summary_message(summary, tool_use_ids) if summary else None)
                .catch(lambda _: None)
            )
        
        # We were aborted during tool calls
        if tool_use_context['abortController']['signal'].get('aborted'):
            # Skip the interruption message for submit-interrupts — the queued
            # user message that follows provides sufficient context.
            if tool_use_context['abortController']['signal'].get('reason') != 'interrupt':
                yield create_user_interruption_message(toolUse=True)
            
            # Check maxTurns before returning when aborted
            next_turn_count_on_abort = turn_count + 1
            if max_turns and next_turn_count_on_abort > max_turns:
                yield create_attachment_message({
                    'type': 'max_turns_reached',
                    'maxTurns': max_turns,
                    'turnCount': next_turn_count_on_abort,
                })
            
            raise QueryTerminal({'reason': 'aborted_tools'})
        
        # If a hook indicated to prevent continuation, stop here
        if should_prevent_continuation:
            raise QueryTerminal({'reason': 'hook_stopped'})
        
        if tracking and tracking.get('compacted'):
            tracking['turnCounter'] += 1
            # Note: log_event would go here
        
        # Be careful to do this after tool calls are done, because the API
        # will error if we interleave tool_result messages with regular user messages.
        
        # Instrumentation: Track message count before attachments
        # Note: log_event would go here
        
        # Get queued commands snapshot before processing attachments.
        # These will be sent as attachments so Cortex can respond to them in the current turn.
        sleep_ran = any(b['name'] == SLEEP_TOOL_NAME for b in tool_use_blocks)
        is_main_thread = query_source.startswith('repl_main_thread') or query_source == 'sdk'
        current_agent_id = tool_use_context.get('agentId')
        
        queued_commands_snapshot = [
            cmd for cmd in get_commands_by_max_priority('later' if sleep_ran else 'next')
            if not is_slash_command(cmd) and (
                (is_main_thread and cmd.get('agentId') is None) or
                (cmd.get('mode') == 'task-notification' and cmd.get('agentId') == current_agent_id)
            )
        ]
        
        async for attachment in get_attachment_messages(
            None,
            updated_tool_use_context,
            None,
            queued_commands_snapshot,
            [*messages_for_query, *assistant_messages, *tool_results],
            query_source,
        ):
            yield attachment
            tool_results.append(attachment)
        
        # Memory prefetch consume: only if settled and not already consumed on
        # an earlier iteration. If not settled yet, skip (zero-wait) and retry
        # next iteration — the prefetch gets as many chances as there are loop
        # iterations before the turn ends. readFileState filters out memories
        # the model already Read/Wrote/Edited.
        if (
            pending_memory_prefetch and
            pending_memory_prefetch.settled_at is not None and
            pending_memory_prefetch.consumed_on_iteration == -1
        ):
            memory_attachments = filter_duplicate_memory_attachments(
                await pending_memory_prefetch.promise,
                tool_use_context.get('readFileState', {}),
            )
            
            for mem_attachment in memory_attachments:
                msg = create_attachment_message(mem_attachment)
                yield msg
                tool_results.append(msg)
            
            pending_memory_prefetch.consumed_on_iteration = turn_count - 1
        
        # Inject prefetched skill discovery.
        if pending_skill_prefetch:
            skill_attachments = await pending_skill_prefetch
            for att in skill_attachments:
                msg = create_attachment_message(att)
                yield msg
                tool_results.append(msg)
        
        # Remove only commands that were actually consumed as attachments.
        consumed_commands = [
            cmd for cmd in queued_commands_snapshot
            if cmd.get('mode') in ('prompt', 'task-notification')
        ]
        
        if consumed_commands:
            for cmd in consumed_commands:
                if cmd.get('uuid'):
                    consumed_command_uuids.append(cmd['uuid'])
                    notify_command_lifecycle(cmd['uuid'], 'started')
            
            remove_from_queue(consumed_commands)
        
        # Instrumentation: Track file change attachments after they're added
        file_change_attachment_count = count(
            tool_results,
            lambda tr: tr.get('type') == 'attachment' and tr['attachment'].get('type') == 'edited_text_file',
        )
        
        # Note: log_event would go here
        
        # Refresh tools between turns so newly-connected MCP servers become available
        if updated_tool_use_context['options'].get('refreshTools'):
            refreshed_tools = updated_tool_use_context['options']['refreshTools']()
            if refreshed_tools is not updated_tool_use_context['options']['tools']:
                updated_tool_use_context = {
                    **updated_tool_use_context,
                    'options': {
                        **updated_tool_use_context['options'],
                        'tools': refreshed_tools,
                    },
                }
        
        tool_use_context_with_query_tracking = {
            **updated_tool_use_context,
            'queryTracking': query_tracking,
        }
        
        # Each time we have tool results and are about to recurse, that's a turn
        next_turn_count = turn_count + 1
        
        # Periodic task summary for `cortex ps` — fires mid-turn so a
        # long-running agent still refreshes what it's working on.
        
        # Check if we've reached the max turns limit
        if max_turns and next_turn_count > max_turns:
            yield create_attachment_message({
                'type': 'max_turns_reached',
                'maxTurns': max_turns,
                'turnCount': next_turn_count,
            })
            raise QueryTerminal({'reason': 'max_turns', 'turnCount': next_turn_count})
        
        query_checkpoint('query_recursive_call')
        
        state = {
            'messages': [*messages_for_query, *assistant_messages, *tool_results],
            'toolUseContext': tool_use_context_with_query_tracking,
            'autoCompactTracking': tracking,
            'turnCount': next_turn_count,
            'maxOutputTokensRecoveryCount': 0,
            'hasAttemptedReactiveCompact': False,
            'pendingToolUseSummary': next_pending_tool_use_summary,
            'maxOutputTokensOverride': None,
            'stopHookActive': stop_hook_active,
            'transition': {'reason': 'next_turn'},
        }


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "query",
    "yield_missing_tool_result_blocks",
    "is_withheld_max_output_tokens",
]
