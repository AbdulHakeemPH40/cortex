"""
Lock file whose mtime IS lastConsolidatedAt. Body is the holder's PID.

Lives inside the memory dir (getAutoMemPath) so it keys on git-root
like memory does, and so it's writable even when the memory path comes
from an env/settings override whose parent may not be.
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Optional, List

from ...bootstrap.state import get_original_cwd
from ...memdir.paths import get_auto_mem_path

LOCK_FILE = '.consolidate-lock'

# Stale past this even if the PID is live (PID reuse guard).
HOLDER_STALE_MS = 60 * 60 * 1000  # 1 hour


def _lock_path() -> str:
    """Get the full path to the lock file."""
    return str(Path(get_auto_mem_path(), LOCK_FILE))


async def read_last_consolidated_at() -> float:
    """
    mtime of the lock file = lastConsolidatedAt. 0 if absent.
    Per-turn cost: one stat.
    
    Returns:
        Last consolidation timestamp in milliseconds, or 0 if no lock file
    """
    try:
        path = Path(_lock_path())
        stat_result = await asyncio.to_thread(path.stat)
        return stat_result.st_mtime * 1000  # Convert seconds to milliseconds
    except (FileNotFoundError, OSError):
        return 0


async def try_acquire_consolidation_lock() -> Optional[float]:
    """
    Acquire: write PID → mtime = now. Returns the pre-acquire mtime
    (for rollback), or null if blocked / lost a race.
    
    Success → do nothing. mtime stays at now.
    Failure → rollback_consolidation_lock(prior_mtime) rewinds mtime.
    Crash   → mtime stuck, dead PID → next process reclaims.
    
    Returns:
        Prior mtime (for rollback) or None if lock acquisition failed
    """
    path = Path(_lock_path())
    
    mtime_ms: Optional[float] = None
    holder_pid: Optional[int] = None
    
    try:
        # Read existing lock file stats and content
        stat_result = await asyncio.to_thread(path.stat)
        mtime_ms = stat_result.st_mtime * 1000  # Convert to milliseconds
        
        content = await asyncio.to_thread(path.read_text, encoding='utf-8')
        parsed = int(content.strip())
        holder_pid = parsed if isinstance(parsed, int) else None
    except (FileNotFoundError, OSError, ValueError):
        # ENOENT — no prior lock.
        pass
    
    # Check if lock is held by a live process
    if mtime_ms is not None and (time.time() * 1000 - mtime_ms) < HOLDER_STALE_MS:
        if holder_pid is not None and is_process_running(holder_pid):
            log_for_debugging(
                f"[autoDream] lock held by live PID {holder_pid} "
                f"(mtime {round((time.time() * 1000 - mtime_ms) / 1000)}s ago)"
            )
            return None
        # Dead PID or unparseable body — reclaim.
    
    # Memory dir may not exist yet.
    auto_mem_path = Path(get_auto_mem_path())
    await asyncio.to_thread(auto_mem_path.mkdir, parents=True, exist_ok=True)
    
    # Write our PID to the lock file
    await asyncio.to_thread(path.write_text, str(os.getpid()), encoding='utf-8')
    
    # Two reclaimers both write → last wins the PID. Loser bails on re-read.
    try:
        verify = await asyncio.to_thread(path.read_text, encoding='utf-8')
    except (FileNotFoundError, OSError):
        return None
    
    if int(verify.strip()) != os.getpid():
        return None
    
    return mtime_ms if mtime_ms is not None else 0.0


async def rollback_consolidation_lock(prior_mtime: float) -> None:
    """
    Rewind mtime to pre-acquire after a failed fork. Clears the PID body —
    otherwise our still-running process would look like it's holding.
    
    Args:
        prior_mtime: Previous mtime in milliseconds. 0 → unlink (restore no-file).
    """
    path = Path(_lock_path())
    try:
        if prior_mtime == 0:
            # Remove lock file
            await asyncio.to_thread(path.unlink, missing_ok=True)
            return
        
        # Clear the PID body
        await asyncio.to_thread(path.write_text, '', encoding='utf-8')
        
        # Restore previous mtime (utimes wants seconds, not milliseconds)
        t = prior_mtime / 1000
        await asyncio.to_thread(os.utime, path, (t, t))
    except OSError as e:
        log_for_debugging(
            f"[autoDream] rollback failed: {e.strerror} — next trigger delayed to minHours"
        )


async def list_sessions_touched_since(since_ms: float) -> List[str]:
    """
    Session IDs with mtime after since_ms. list_candidates handles UUID
    validation (excludes agent-*.jsonl) and parallel stat.
    
    Uses mtime (sessions TOUCHED since), not birthtime (0 on ext4).
    Caller excludes the current session. Scans per-cwd transcripts — it's
    a skip-gate, so undercounting worktree sessions is safe.
    
    Args:
        since_ms: Timestamp in milliseconds to filter sessions after
        
    Returns:
        List of session IDs that were touched after the given timestamp
    """
    dir_path = get_project_dir(get_original_cwd())
    candidates = await list_candidates(dir_path, True)
    return [c.session_id for c in candidates if c.mtime > since_ms]


async def record_consolidation() -> None:
    """
    Stamp from manual /dream. Optimistic — fires at prompt-build time,
    no post-skill completion hook. Best-effort.
    """
    try:
        # Memory dir may not exist yet (manual /dream before any auto-trigger).
        auto_mem_path = Path(get_auto_mem_path())
        await asyncio.to_thread(auto_mem_path.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            Path(_lock_path()).write_text,
            str(os.getpid()),
            encoding='utf-8'
        )
    except OSError as e:
        log_for_debugging(
            f"[autoDream] recordConsolidation write failed: {e.strerror}"
        )
