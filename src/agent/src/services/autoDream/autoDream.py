"""
Background memory consolidation. Fires the /dream prompt as a forked
subagent when time-gate passes AND enough sessions have accumulated.

Gate order (cheapest first):
  1. Time: hours since last_consolidated_at >= min_hours (one stat)
  2. Sessions: transcript count with mtime > last_consolidated_at >= min_sessions
  3. Lock: no other process mid-consolidation

State is closure-scoped inside init_auto_dream() rather than module-level
(tests call init_auto_dream() in beforeEach for a fresh closure).
"""

import asyncio
import time
from typing import Any, Callable, Optional, Dict, List

from ...utils.hooks.post_sampling_hooks import REPLHookContext
from ...utils.forked_agent import (
    create_cache_safe_params,
    run_forked_agent,
)
from ...utils.messages import (
    create_user_message,
    create_memory_saved_message,
)
from ...agent_types.message import Message
from ...memdir.paths import is_auto_memory_enabled, get_auto_mem_path
from ..autoDream.config import is_auto_dream_enabled
from ...bootstrap.state import (
    get_original_cwd,
    get_kairos_active,
    get_is_remote_mode,
    get_session_id,
)
from ..extractMemories.extractMemories import create_auto_mem_can_use_tool
from ..autoDream.consolidationPrompt import build_consolidation_prompt
from ..autoDream.consolidationLock import (
    read_last_consolidated_at,
    list_sessions_touched_since,
    try_acquire_consolidation_lock,
    rollback_consolidation_lock,
)
from ..autoDream.dreamRegistry import (
    register_dream_task,
    add_dream_turn,
    complete_dream_task,
    fail_dream_task,
    is_dream_task,
)
from ...tools.FileEditTool.constants import FILE_EDIT_TOOL_NAME
from ...tools.FileWriteTool.prompt import FILE_WRITE_TOOL_NAME

# Scan throttle: when time-gate passes but session-gate doesn't, the lock
# mtime doesn't advance, so the time-gate keeps passing every turn.
SESSION_SCAN_INTERVAL_MS = 10 * 60 * 1000  # 10 minutes


class AutoDreamConfig:
    """Configuration for auto-dream scheduling."""
    min_hours: int
    min_sessions: int
    
    def __init__(self, min_hours: int, min_sessions: int):
        self.min_hours = min_hours
        self.min_sessions = min_sessions


DEFAULTS = AutoDreamConfig(min_hours=24, min_sessions=5)


def _get_config() -> AutoDreamConfig:
    """
    Thresholds from tengu_onyx_plover. The enabled gate lives in config.py
    (is_auto_dream_enabled); this returns only the scheduling knobs. Defensive
    per-field validation since GB cache can return stale wrong-type values.
    """
    raw = get_feature_value_cached_may_be_stale[Optional[Dict[str, Any]]](
        'tengu_onyx_plover',
        None,
    )
    
    min_hours = DEFAULTS.min_hours
    if (
        raw is not None
        and 'minHours' in raw
        and isinstance(raw['minHours'], (int, float))
        and raw['minHours'] > 0
    ):
        min_hours = int(raw['minHours'])
    
    min_sessions = DEFAULTS.min_sessions
    if (
        raw is not None
        and 'minSessions' in raw
        and isinstance(raw['minSessions'], (int, float))
        and raw['minSessions'] > 0
    ):
        min_sessions = int(raw['minSessions'])
    
    return AutoDreamConfig(min_hours=min_hours, min_sessions=min_sessions)


def _is_gate_open() -> bool:
    """Check if auto-dream gates are open."""
    if get_kairos_active():
        return False  # KAIROS mode uses disk-skill dream
    if get_is_remote_mode():
        return False
    if not is_auto_memory_enabled():
        return False
    return is_auto_dream_enabled()


def _is_forced() -> bool:
    """
    Ant-build-only test override. Bypasses enabled/time/session gates but NOT
    the lock (so repeated turns don't pile up dreams) or the memory-dir
    precondition. Still scans sessions so the prompt's session-hint is populated.
    """
    return False


# Type alias for append_system_message function
AppendSystemMessageFn = Callable[[dict], None]

# Runner closure
_runner: Optional[Callable] = None


def _make_dream_progress_watcher(
    task_id: str,
    set_app_state: Any,
) -> Callable[[Message], None]:
    """
    Watch the forked agent's messages. For each assistant turn, extracts any
    text blocks (the agent's reasoning/summary — what the user wants to see)
    and collapses tool_use blocks to a count. Edit/Write file_paths are
    collected for phase-flip + the inline completion message.
    """
    def watcher(msg: Message) -> None:
        if msg.type != 'assistant':
            return
        
        text = ''
        tool_use_count = 0
        touched_paths = []
        
        for block in msg.message.content:
            if block.type == 'text':
                text += block.text
            elif block.type == 'tool_use':
                tool_use_count += 1
                if (
                    block.name == FILE_EDIT_TOOL_NAME
                    or block.name == FILE_WRITE_TOOL_NAME
                ):
                    input_data = block.input
                    if isinstance(input_data, dict) and 'file_path' in input_data:
                        file_path = input_data['file_path']
                        if isinstance(file_path, str):
                            touched_paths.append(file_path)
        
        add_dream_turn(
            task_id,
            {'text': text.strip(), 'tool_use_count': tool_use_count},
            touched_paths,
            set_app_state,
        )
    
    return watcher


def init_auto_dream() -> None:
    """
    Call once at startup (from background_housekeeping alongside
    init_extract_memories), or per-test in beforeEach for a fresh closure.
    """
    global _runner
    
    last_session_scan_at = 0
    
    async def run_auto_dream(
        context: REPLHookContext,
        append_system_message: Optional[AppendSystemMessageFn] = None,
    ) -> None:
        nonlocal last_session_scan_at
        
        cfg = _get_config()
        force = _is_forced()
        
        if not force and not _is_gate_open():
            return
        
        # --- Time gate ---
        try:
            last_at = await read_last_consolidated_at()
        except Exception as e:
            log_for_debugging(f"[autoDream] read_last_consolidated_at failed: {e}")
            return
        
        hours_since = (time.time() * 1000 - last_at) / 3_600_000
        if not force and hours_since < cfg.min_hours:
            return
        
        # --- Scan throttle ---
        since_scan_ms = (time.time() * 1000) - last_session_scan_at
        if not force and since_scan_ms < SESSION_SCAN_INTERVAL_MS:
            log_for_debugging(
                f"[autoDream] scan throttle — time-gate passed but last scan was "
                f"{round(since_scan_ms / 1000)}s ago"
            )
            return
        
        last_session_scan_at = time.time() * 1000
        
        # --- Session gate ---
        try:
            session_ids = await list_sessions_touched_since(last_at)
        except Exception as e:
            log_for_debugging(f"[autoDream] list_sessions_touched_since failed: {e}")
            return
        
        # Exclude the current session (its mtime is always recent).
        current_session = get_session_id()
        session_ids = [sid for sid in session_ids if sid != current_session]
        
        if not force and len(session_ids) < cfg.min_sessions:
            log_for_debugging(
                f"[autoDream] skip — {len(session_ids)} sessions since last consolidation, "
                f"need {cfg.min_sessions}"
            )
            return
        
        # --- Lock ---
        # Under force, skip acquire entirely — use the existing mtime so
        # kill's rollback is a no-op (rewinds to where it already is).
        # The lock file stays untouched; next non-force turn sees it as-is.
        if force:
            prior_mtime = last_at
        else:
            try:
                prior_mtime = await try_acquire_consolidation_lock()
            except Exception as e:
                log_for_debugging(f"[autoDream] lock acquire failed: {e}")
                return
            
            if prior_mtime is None:
                return
        
        log_for_debugging(
            f"[autoDream] firing — {hours_since:.1f}h since last, "
            f"{len(session_ids)} sessions to review"
        )
        log_event('tengu_auto_dream_fired', {
            'hours_since': round(hours_since),
            'sessions_since': len(session_ids),
        })
        
        set_app_state = (
            context.tool_use_context.set_app_state_for_tasks
            or context.tool_use_context.set_app_state
        )
        abort_controller = asyncio.Event()  # Simplified for Python
        task_id = register_dream_task(set_app_state, {
            'sessions_reviewing': len(session_ids),
            'prior_mtime': prior_mtime,
            'abort_controller': abort_controller,
        })
        
        try:
            memory_root = get_auto_mem_path()
            transcript_dir = get_project_dir(get_original_cwd())
            
            # Tool constraints note goes in `extra`, not the shared prompt body —
            # manual /dream runs in the main loop with normal permissions and this
            # would be misleading there.
            extra = f"""

**Tool constraints for this run:** Bash is restricted to read-only commands (`ls`, `find`, `grep`, `cat`, `stat`, `wc`, `head`, `tail`, and similar). Anything that writes, redirects to a file, or modifies state will be denied. Plan your exploration with this in mind — no need to probe.

Sessions since last consolidation ({len(session_ids)}):
{chr(10).join(f'- {sid}' for sid in session_ids)}"""
            
            prompt = build_consolidation_prompt(memory_root, transcript_dir, extra)
            
            result = await run_forked_agent(
                prompt_messages=[create_user_message(content=prompt)],
                cache_safe_params=create_cache_safe_params(context),
                can_use_tool=create_auto_mem_can_use_tool(memory_root),
                query_source='auto_dream',
                fork_label='auto_dream',
                skip_transcript=True,
                overrides={'abort_controller': abort_controller},
                on_message=_make_dream_progress_watcher(task_id, set_app_state),
            )
            
            complete_dream_task(task_id, set_app_state)
            
            # Inline completion summary in the main transcript (same surface as
            # extract_memories's "Saved N memories" message).
            dream_state = context.tool_use_context.get_app_state().tasks.get(task_id)
            if (
                append_system_message
                and is_dream_task(dream_state)
                and len(dream_state.files_touched) > 0
            ):
                append_system_message({
                    **create_memory_saved_message(dream_state.files_touched),
                    'verb': 'Improved',
                })
            
            log_for_debugging(
                f"[autoDream] completed — cache: read={result.total_usage.cache_read_input_tokens} "
                f"created={result.total_usage.cache_creation_input_tokens}"
            )
            log_event('tengu_auto_dream_completed', {
                'cache_read': result.total_usage.cache_read_input_tokens,
                'cache_created': result.total_usage.cache_creation_input_tokens,
                'output': result.total_usage.output_tokens,
                'sessions_reviewed': len(session_ids),
            })
        except Exception as e:
            # If the user killed from the bg-tasks dialog, DreamTask.kill already
            # aborted, rolled back the lock, and set status=killed. Don't overwrite
            # or double-rollback.
            if abort_controller.is_set():
                log_for_debugging('[autoDream] aborted by user')
                return
            
            log_for_debugging(f"[autoDream] fork failed: {e}")
            log_event('tengu_auto_dream_failed', {})
            fail_dream_task(task_id, set_app_state)
            
            # Rewind mtime so time-gate passes again. Scan throttle is the backoff.
            await rollback_consolidation_lock(prior_mtime)
    
    _runner = run_auto_dream


async def execute_auto_dream(
    context: REPLHookContext,
    append_system_message: Optional[AppendSystemMessageFn] = None,
) -> None:
    """
    Entry point from stop_hooks. No-op until init_auto_dream() has been called.
    Per-turn cost when enabled: one GB cache read + one stat.
    """
    if _runner is not None:
        await _runner(context, append_system_message)
