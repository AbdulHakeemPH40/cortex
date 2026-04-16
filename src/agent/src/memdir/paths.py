"""
paths - Auto-memory path resolution and validation.

Handles path computation for persistent memory storage with:
- Security validation (reject dangerous paths like ~/, UNC, null bytes)
- Environment variable overrides (CLAUDE_CODE_REMOTE_MEMORY_DIR, CLAUDE_COWORK_MEMORY_PATH_OVERRIDE)
- Settings.json integration (autoMemoryDirectory from trusted sources)
- Git root canonicalization (worktree support)
- Daily log path generation (KAIROS mode)
"""

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..bootstrap.state import getProjectRoot, getIsNonInteractiveSession
from ..utils.settings.settings import (
    getInitialSettings,
    getSettingsForSource,
)


def isAutoMemoryEnabled() -> bool:
    """
    Whether auto-memory features are enabled (memdir, agent memory, past session search).
    Enabled by default. Priority chain (first defined wins):
      1. CLAUDE_CODE_DISABLE_AUTO_MEMORY env var (1/true → OFF, 0/false → ON)
      2. CLAUDE_CODE_SIMPLE (--bare) → OFF
      3. CCR without persistent storage → OFF (no CLAUDE_CODE_REMOTE_MEMORY_DIR)
      4. autoMemoryEnabled in settings.json (supports project-level opt-out)
      5. Default: enabled
    """
    envVal = os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY')
    if isEnvTruthy(envVal):
        return False
    if isEnvDefinedFalsy(envVal):
        return True
    # --bare / SIMPLE: prompts.py already drops the memory section from the
    # system prompt via its SIMPLE early-return; this gate stops the other half
    # (extractMemories turn-end fork, autoDream, /remember, /dream, team sync).
    if isEnvTruthy(os.environ.get('CLAUDE_CODE_SIMPLE')):
        return False
    if (
        isEnvTruthy(os.environ.get('CLAUDE_CODE_REMOTE'))
        and not os.environ.get('CLAUDE_CODE_REMOTE_MEMORY_DIR')
    ):
        return False
    settings = getInitialSettings()
    if 'autoMemoryEnabled' in settings and settings['autoMemoryEnabled'] is not None:
        return settings['autoMemoryEnabled']
    return True


def isExtractModeActive() -> bool:
    """
    Whether the extract-memories background agent will run this session.

    The main agent's prompt always has full save instructions regardless of
    this gate — when the main agent writes memories, the background agent
    skips that range (hasMemoryWritesSince in extractMemories.py); when it
    doesn't, the background agent catches anything missed.

    Callers must also gate on feature('EXTRACT_MEMORIES') — that check cannot
    live inside this helper because feature() only tree-shakes when used
    directly in an `if` condition.
    """
    if not getFeatureValue_CACHED_MAY_BE_STALE('tengu_passport_quail', False):
        return False
    return (
        not getIsNonInteractiveSession()
        or getFeatureValue_CACHED_MAY_BE_STALE('tengu_slate_thimble', False)
    )


def getMemoryBaseDir() -> str:
    """
    Returns the base directory for persistent memory storage.
    Resolution order:
      1. CLAUDE_CODE_REMOTE_MEMORY_DIR env var (explicit override, set in CCR)
      2. ~/.claude (default config home)
    """
    remote_dir = os.environ.get('CLAUDE_CODE_REMOTE_MEMORY_DIR')
    if remote_dir:
        return remote_dir
    return getClaudeConfigHomeDir()


AUTO_MEM_DIRNAME = 'memory'
AUTO_MEM_ENTRYPOINT_NAME = 'MEMORY.md'


def _validateMemoryPath(raw: Optional[str], expandTilde: bool) -> Optional[str]:
    """
    Normalize and validate a candidate auto-memory directory path.

    SECURITY: Rejects paths that would be dangerous as a read-allowlist root
    or that normalize() doesn't fully resolve:
    - relative (!isAbsolute): "../foo" — would be interpreted relative to CWD
    - root/near-root (length < 3): "/" → "" after strip; "/a" too short
    - Windows drive-root (C: regex): "C:\\" → "C:" after strip
    - UNC paths (\\\\server\\share): network paths — opaque trust boundary
    - null byte: survives normalize(), can truncate in syscalls

    Returns the normalized path with exactly one trailing separator,
    or None if the path is unset/empty/rejected.
    """
    if not raw:
        return None
    
    candidate = raw
    # Settings.json paths support ~/ expansion (user-friendly). The env var
    # override does not (it's set programmatically by Cowork/SDK, which should
    # always pass absolute paths). Bare "~", "~/", "~/.", "~/..", etc. are NOT
    # expanded — they would make isAutoMemPath() match all of $HOME or its
    # parent (same class of danger as "/" or "C:\\").
    if expandTilde and (candidate.startswith('~/') or candidate.startswith('~\\')):
        rest = candidate[2:]
        # Reject trivial remainders that would expand to $HOME or an ancestor.
        # normalize('') = '.', normalize('.') = '.', normalize('foo/..') = '.',
        # normalize('..') = '..', normalize('foo/../..') = '..'
        restNorm = os.path.normpath(rest or '.')
        if restNorm == '.' or restNorm == '..':
            return None
        candidate = os.path.join(Path.home(), rest)
    
    # normpath may preserve a trailing separator; strip before adding
    # exactly one to match the trailing-sep contract of getAutoMemPath()
    normalized = os.path.normpath(candidate).rstrip('/\\')
    
    if (
        not os.path.isabs(normalized)
        or len(normalized) < 3
        or (len(normalized) == 2 and normalized[1] == ':')  # Windows drive letter
        or normalized.startswith('\\\\')
        or normalized.startswith('//')
        or '\0' in normalized
    ):
        return None
    
    return (normalized + os.sep).encode().decode('utf-8')


def _getAutoMemPathOverride() -> Optional[str]:
    """
    Direct override for the full auto-memory directory path via env var.
    When set, getAutoMemPath()/getAutoMemEntrypoint() return this path directly
    instead of computing `{base}/projects/{sanitized-cwd}/memory/`.

    Used by Cowork to redirect memory to a space-scoped mount where the
    per-session cwd (which contains the VM process name) would otherwise
    produce a different project-key for every session.
    """
    return _validateMemoryPath(
        os.environ.get('CLAUDE_COWORK_MEMORY_PATH_OVERRIDE'),
        False,
    )


def _getAutoMemPathSetting() -> Optional[str]:
    """
    Settings.json override for the full auto-memory directory path.
    Supports ~/ expansion for user convenience.

    SECURITY: projectSettings (.claude/settings.json committed to the repo) is
    intentionally excluded — a malicious repo could otherwise set
    autoMemoryDirectory: "~/.ssh" and gain silent write access to sensitive
    directories via the filesystem.py write carve-out (which fires when
    isAutoMemPath() matches and hasAutoMemPathOverride() is false). This follows
    the same pattern as hasSkipDangerousModePermissionPrompt() etc.
    """
    dir_val = (
        getSettingsForSource('policySettings').get('autoMemoryDirectory')
        or getSettingsForSource('flagSettings').get('autoMemoryDirectory')
        or getSettingsForSource('localSettings').get('autoMemoryDirectory')
        or getSettingsForSource('userSettings').get('autoMemoryDirectory')
    )
    return _validateMemoryPath(dir_val, True)


def hasAutoMemPathOverride() -> bool:
    """
    Check if CLAUDE_COWORK_MEMORY_PATH_OVERRIDE is set to a valid override.
    Use this as a signal that the SDK caller has explicitly opted into
    the auto-memory mechanics — e.g. to decide whether to inject the
    memory prompt when a custom system prompt replaces the default.
    """
    return _getAutoMemPathOverride() is not None


def _getAutoMemBase() -> str:
    """
    Returns the canonical git repo root if available, otherwise falls back to
    the stable project root. Uses findCanonicalGitRoot so all worktrees of the
    same repo share one auto-memory directory (anthropics/claude-code#24382).
    """
    return findCanonicalGitRoot(getProjectRoot()) or getProjectRoot()


@lru_cache(maxsize=None)
def getAutoMemPath() -> str:
    """
    Returns the auto-memory directory path.

    Resolution order:
      1. CLAUDE_COWORK_MEMORY_PATH_OVERRIDE env var (full-path override, used by Cowork)
      2. autoMemoryDirectory in settings.json (trusted sources only: policy/local/user)
      3. <memoryBase>/projects/<sanitized-git-root>/memory/
         where memoryBase is resolved by getMemoryBaseDir()

    Memoized: render-path callers (collapseReadSearchGroups → isAutoManagedMemoryFile)
    fire per tool-use message per Messages re-render; each miss costs
    getSettingsForSource × 4 → parseSettingsFile (realpathSync + readFileSync).
    Keyed on projectRoot so tests that change its mock mid-block recompute;
    env vars / settings.json / CLAUDE_CONFIG_DIR are session-stable in
    production and covered by per-test cache.clear.
    """
    override = _getAutoMemPathOverride() or _getAutoMemPathSetting()
    if override:
        return override
    
    projectsDir = os.path.join(getMemoryBaseDir(), 'projects')
    base_path = os.path.join(projectsDir, sanitizePath(_getAutoMemBase()), AUTO_MEM_DIRNAME)
    return (base_path + os.sep).encode().decode('utf-8')


def getAutoMemDailyLogPath(date_obj: Optional[date] = None) -> str:
    """
    Returns the daily log file path for the given date (defaults to today).
    Shape: <autoMemPath>/logs/YYYY/MM/YYYY-MM-DD.md

    Used by assistant mode (feature('KAIROS')): rather than maintaining
    MEMORY.md as a live index, the agent appends to a date-named log file
    as it works. A separate nightly /dream skill distills these logs into
    topic files + MEMORY.md.
    """
    if date_obj is None:
        date_obj = date.today()
    
    yyyy = str(date_obj.year)
    mm = str(date_obj.month).zfill(2)
    dd = str(date_obj.day).zfill(2)
    return os.path.join(getAutoMemPath(), 'logs', yyyy, mm, f'{yyyy}-{mm}-{dd}.md')


def getAutoMemEntrypoint() -> str:
    """
    Returns the auto-memory entrypoint (MEMORY.md inside the auto-memory dir).
    Follows the same resolution order as getAutoMemPath().
    """
    return os.path.join(getAutoMemPath(), AUTO_MEM_ENTRYPOINT_NAME)


def isAutoMemPath(absolutePath: str) -> bool:
    """
    Check if an absolute path is within the auto-memory directory.

    When CLAUDE_COWORK_MEMORY_PATH_OVERRIDE is set, this matches against the
    env-var override directory. Note that a true return here does NOT imply
    write permission in that case — the filesystem.py write carve-out is gated
    on !hasAutoMemPathOverride() (it exists to bypass DANGEROUS_DIRECTORIES).

    The settings.json autoMemoryDirectory DOES get the write carve-out: it's the
    user's explicit choice from a trusted settings source (projectSettings is
    excluded — see getAutoMemPathSetting), and hasAutoMemPathOverride() remains
    false for it.
    """
    # SECURITY: Normalize to prevent path traversal bypasses via .. segments
    normalizedPath = os.path.normpath(absolutePath)
    return normalizedPath.startswith(getAutoMemPath())
