# ------------------------------------------------------------
# context.py
# Python conversion of context.ts (lines 1-190)
# 
# Context generation for conversations including:
# - System prompt injection for cache breaking
# - Git status snapshot (branch, commits, changes)
# - System context (git status + cache breaker)
# - User context (CLAUDE.md files + current date)
# - Memoized caching with invalidation on injection changes
# ------------------------------------------------------------

import asyncio
from datetime import datetime
from functools import lru_cache
from typing import Dict, Optional


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from bun.bundle import feature
except ImportError:
    def feature(feature_name: str) -> bool:
        """Stub: Check if a feature flag is enabled."""
        return False

try:
    from .bootstrap.state import (
        get_additional_directories_for_claude_md,
        set_cached_claude_md_content,
    )
except ImportError:
    def get_additional_directories_for_claude_md() -> list:
        return []
    
    def set_cached_claude_md_content(content: Optional[str]) -> None:
        pass

try:
    from .constants.common import get_local_iso_date
except ImportError:
    def get_local_iso_date() -> str:
        return datetime.now().isoformat()

try:
    from .utils.claudemd import (
        filter_injected_memory_files,
        get_claude_mds,
        get_memory_files,
    )
except ImportError:
    async def get_memory_files() -> list:
        return []
    
    def filter_injected_memory_files(files: list) -> list:
        return files
    
    def get_claude_mds(files: list) -> Optional[str]:
        return None

try:
    from .utils.diag_logs import log_for_diagnostics_no_pii
except ImportError:
    def log_for_diagnostics_no_pii(level: str, message: str, data: Optional[dict] = None) -> None:
        pass

try:
    from .utils.env_utils import is_bare_mode, is_env_truthy
except ImportError:
    def is_bare_mode() -> bool:
        return False
    
    def is_env_truthy(value: Optional[str]) -> bool:
        return value and value.lower() in ["true", "1", "yes"]

try:
    from .utils.exec_file_no_throw import exec_file_no_throw
except ImportError:
    async def exec_file_no_throw(cmd: str, args: list, options: Optional[dict] = None) -> dict:
        return {"stdout": "", "stderr": ""}

try:
    from .utils.git import get_branch, get_default_branch, get_is_git, git_exe
except ImportError:
    async def get_is_git() -> bool:
        return False
    
    async def get_branch() -> Optional[str]:
        return None
    
    async def get_default_branch() -> Optional[str]:
        return None
    
    def git_exe() -> str:
        return "git"

try:
    from .utils.git_settings import should_include_git_instructions
except ImportError:
    def should_include_git_instructions() -> bool:
        return True

try:
    from .utils.log import log_error
except ImportError:
    def log_error(error: Exception) -> None:
        print(f"Error: {error}")


# ============================================================
# CONSTANTS
# ============================================================

MAX_STATUS_CHARS = 2000


# ============================================================
# SYSTEM PROMPT INJECTION (Cache Breaking)
# ============================================================

# System prompt injection for cache breaking (ant-only, ephemeral debugging state)
_system_prompt_injection: Optional[str] = None


def get_system_prompt_injection() -> Optional[str]:
    """Get the current system prompt injection value."""
    return _system_prompt_injection


def set_system_prompt_injection(value: Optional[str]) -> None:
    """
    Set system prompt injection and clear context caches immediately.
    
    Used for cache breaking in ant-only debugging scenarios.
    
    Args:
        value: Injection string or None to clear
    """
    global _system_prompt_injection
    _system_prompt_injection = value
    
    # Clear context caches immediately when injection changes
    get_user_context.cache_clear()
    get_system_context.cache_clear()


# ============================================================
# GIT STATUS GENERATION
# ============================================================

@lru_cache(maxsize=1)
async def get_git_status() -> Optional[str]:
    """
    Get git repository status as a formatted string.
    
    Includes:
    - Current branch
    - Main branch (for PRs)
    - Git user name
    - Short status (truncated to 2000 chars)
    - Recent 5 commits
    
    Memoized for performance - clears when system prompt injection changes.
    
    Returns:
        Formatted git status string or None if not in git repo
    """
    import os
    if os.environ.get('NODE_ENV') == 'test':
        # Avoid cycles in tests
        return None
    
    start_time = asyncio.get_running_loop().time() * 1000
    log_for_diagnostics_no_pii('info', 'git_status_started')
    
    is_git_start = asyncio.get_running_loop().time() * 1000
    is_git = await get_is_git()
    log_for_diagnostics_no_pii('info', 'git_is_git_check_completed', {
        'duration_ms': (asyncio.get_running_loop().time() * 1000) - is_git_start,
        'is_git': is_git,
    })
    
    if not is_git:
        log_for_diagnostics_no_pii('info', 'git_status_skipped_not_git', {
            'duration_ms': (asyncio.get_running_loop().time() * 1000) - start_time,
        })
        return None
    
    try:
        git_cmds_start = asyncio.get_running_loop().time() * 1000
        
        # Run all git commands in parallel
        branch, main_branch, status_result, log_result, user_name_result = await asyncio.gather(
            get_branch(),
            get_default_branch(),
            exec_file_no_throw(
                git_exe(),
                ['--no-optional-locks', 'status', '--short'],
                {'preserveOutputOnError': False},
            ),
            exec_file_no_throw(
                git_exe(),
                ['--no-optional-locks', 'log', '--oneline', '-n', '5'],
                {'preserveOutputOnError': False},
            ),
            exec_file_no_throw(
                git_exe(),
                ['config', 'user.name'],
                {'preserveOutputOnError': False},
            ),
        )
        
        # Extract stdout from results
        status = status_result['stdout'].strip()
        log = log_result['stdout'].strip()
        user_name = user_name_result['stdout'].strip()
        
        log_for_diagnostics_no_pii('info', 'git_commands_completed', {
            'duration_ms': (asyncio.get_running_loop().time() * 1000) - git_cmds_start,
            'status_length': len(status),
        })
        
        # Check if status exceeds character limit
        if len(status) > MAX_STATUS_CHARS:
            truncated_status = (
                status[:MAX_STATUS_CHARS] +
                '\n... (truncated because it exceeds 2k characters. If you need more information, run "git status" using BashTool)'
            )
        else:
            truncated_status = status
        
        log_for_diagnostics_no_pii('info', 'git_status_completed', {
            'duration_ms': (asyncio.get_running_loop().time() * 1000) - start_time,
            'truncated': len(status) > MAX_STATUS_CHARS,
        })
        
        # Build status sections
        sections = [
            'This is the git status at the start of the conversation. Note that this status is a snapshot in time, and will not update during the conversation.',
            f'Current branch: {branch}',
            f'Main branch (you will usually use this for PRs): {main_branch}',
        ]
        
        if user_name:
            sections.append(f'Git user: {user_name}')
        
        sections.append(f'Status:\n{truncated_status or "(clean)"}')
        sections.append(f'Recent commits:\n{log}')
        
        return '\n\n'.join(sections)
    
    except Exception as error:
        log_for_diagnostics_no_pii('error', 'git_status_failed', {
            'duration_ms': (asyncio.get_running_loop().time() * 1000) - start_time,
        })
        log_error(error)
        return None


# ============================================================
# SYSTEM CONTEXT
# ============================================================

@lru_cache(maxsize=1)
async def get_system_context() -> Dict[str, str]:
    """
    Get system context prepended to each conversation.
    
    Includes:
    - Git status (unless in CCR or git instructions disabled)
    - Cache breaker injection (if BREAK_CACHE_COMMAND feature enabled)
    
    Memoized for the duration of the conversation. Clears when
    system prompt injection changes.
    
    Returns:
        Dictionary with gitStatus and/or cacheBreaker keys
    """
    import os
    
    start_time = asyncio.get_running_loop().time() * 1000
    log_for_diagnostics_no_pii('info', 'system_context_started')
    
    # Skip git status in CCR (unnecessary overhead on resume) or when git instructions are disabled
    if (is_env_truthy(os.environ.get('CLAUDE_CODE_REMOTE')) or
        not should_include_git_instructions()):
        git_status = None
    else:
        git_status = await get_git_status()
    
    # Include system prompt injection if set (for cache breaking, ant-only)
    injection = get_system_prompt_injection() if feature('BREAK_CACHE_COMMAND') else None
    
    log_for_diagnostics_no_pii('info', 'system_context_completed', {
        'duration_ms': (asyncio.get_running_loop().time() * 1000) - start_time,
        'has_git_status': git_status is not None,
        'has_injection': injection is not None,
    })
    
    result = {}
    
    if git_status:
        result['gitStatus'] = git_status
    
    if feature('BREAK_CACHE_COMMAND') and injection:
        result['cacheBreaker'] = f'[CACHE_BREAKER: {injection}]'
    
    return result


# ============================================================
# USER CONTEXT
# ============================================================

@lru_cache(maxsize=1)
async def get_user_context() -> Dict[str, str]:
    """
    Get user context prepended to each conversation.
    
    Includes:
    - CLAUDE.md files from project directories
    - Current date in ISO format
    
    Memoized for the duration of the conversation. Clears when
    system prompt injection changes.
    
    Returns:
        Dictionary with claudeMd and currentDate keys
    """
    import os
    
    start_time = asyncio.get_running_loop().time() * 1000
    log_for_diagnostics_no_pii('info', 'user_context_started')
    
    # CLAUDE_CODE_DISABLE_CLAUDE_MDS: hard off, always.
    # --bare: skip auto-discovery (cwd walk), BUT honor explicit --add-dir.
    # --bare means "skip what I didn't ask for", not "ignore what I asked for".
    should_disable_claude_md = (
        is_env_truthy(os.environ.get('CLAUDE_CODE_DISABLE_CLAUDE_MDS')) or
        (is_bare_mode() and len(get_additional_directories_for_claude_md()) == 0)
    )
    
    # Await the async I/O (readFile/readdir directory walk) so the event
    # loop yields naturally at the first fs.readFile.
    if should_disable_claude_md:
        claude_md = None
    else:
        memory_files = await get_memory_files()
        filtered_files = filter_injected_memory_files(memory_files)
        claude_md = get_claude_mds(filtered_files)
    
    # Cache for the auto-mode classifier (yoloClassifier.py reads this
    # instead of importing claudemd.py directly, which would create a
    # cycle through permissions/filesystem → permissions → yolo_classifier).
    set_cached_claude_md_content(claude_md)
    
    log_for_diagnostics_no_pii('info', 'user_context_completed', {
        'duration_ms': (asyncio.get_running_loop().time() * 1000) - start_time,
        'claudemd_length': len(claude_md) if claude_md else 0,
        'claudemd_disabled': bool(should_disable_claude_md),
    })
    
    result = {
        'currentDate': f"Today's date is {get_local_iso_date()}.",
    }
    
    if claude_md:
        result['claudeMd'] = claude_md
    
    return result


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "get_system_prompt_injection",
    "set_system_prompt_injection",
    "get_git_status",
    "get_system_context",
    "get_user_context",
]
