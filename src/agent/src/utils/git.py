"""
Git utilities wrapper for Cortex Agent.

Re-exports GitManager from Cortex IDE's core module.
This avoids code duplication and ensures consistency.
"""

import sys
import os
import re
import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Add Cortex src directory to path if not already there
# Current: Cortex/src/agent/src/utils/git.py
# Target:  Cortex/src/core/git_manager.py
_cortex_src = Path(__file__).parent.parent.parent.parent  # Cortex/src
if _cortex_src.exists() and str(_cortex_src) not in sys.path:
    sys.path.insert(0, str(_cortex_src))

# Import from Cortex IDE's GitManager
try:
    from core.git_manager import (
        GitManager,
        GitStatus,
        GitFile,
        GitCommit,
    )
except ImportError:
    # Fallback for when running from agent directory standalone
    from dataclasses import dataclass
    from enum import Enum
    from typing import List, Optional, Tuple
    from PyQt6.QtCore import QObject, pyqtSignal

    class GitStatus(Enum):
        MODIFIED = "M"
        ADDED = "A"
        DELETED = "D"
        RENAMED = "R"
        COPIED = "C"
        UPDATED = "U"
        UNTRACKED = "??"
        IGNORED = "!!"

    @dataclass
    class GitFile:
        path: str
        status: GitStatus
        staged: bool
        old_path: Optional[str] = None

    @dataclass
    class GitCommit:
        hash: str
        short_hash: str
        message: str
        author: str
        date: str

    class GitManager(QObject):
        """Fallback GitManager for standalone agent mode."""
        status_changed = pyqtSignal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._repo_path = None

        def set_repository(self, path: str) -> bool:
            self._repo_path = path
            return True

        def is_repo(self) -> bool:
            return self._repo_path is not None

        def get_branch(self) -> str:
            return ""

        def get_status(self) -> List[GitFile]:
            return []

        def get_commits(self, count: int = 20) -> List[GitCommit]:
            return []

        def stage_file(self, file_path: str) -> bool:
            return False

        def commit(self, message: str) -> Tuple[bool, str]:
            return False, "GitManager not available"

        def get_diff(self, file_path: str = None, staged: bool = False) -> str:
            return ""


# ============================================================
# Git Diff Types (required by useDiffData.py)
# ============================================================

@dataclass
class GitDiffStats:
    """Total diff statistics across all files."""
    total_added: int = 0
    total_removed: int = 0
    total_files: int = 0


@dataclass
class StructuredPatchHunk:
    """A structured git diff hunk with line-level context."""
    file_path: str = ""
    old_start: int = 0
    old_lines: int = 0
    new_start: int = 0
    new_lines: int = 0
    lines: List[str] = field(default_factory=list)


@dataclass
class GitDiffResult:
    """
    Result of a full git diff operation.
    per_file_stats[path] = {'added': int, 'removed': int, 'isBinary': bool, 'isUntracked': bool}
    """
    stats: GitDiffStats = field(default_factory=GitDiffStats)
    per_file_stats: Dict[str, dict] = field(default_factory=dict)


async def fetch_git_diff(repo_path: str = None) -> Optional[GitDiffResult]:
    """
    Fetch per-file diff stats using `git diff --numstat HEAD`.
    Also includes untracked files with their line counts.
    Returns GitDiffResult or None if git is unavailable.
    """
    cwd = repo_path or os.getcwd()
    _flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    try:
        loop = asyncio.get_event_loop()

        def _numstat():
            r = subprocess.run(
                ['git', 'diff', '--numstat', 'HEAD'],
                cwd=cwd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', creationflags=_flags
            )
            return r.stdout

        def _untracked():
            r = subprocess.run(
                ['git', 'ls-files', '--others', '--exclude-standard'],
                cwd=cwd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', creationflags=_flags
            )
            return r.stdout

        numstat_out, untracked_out = await asyncio.gather(
            loop.run_in_executor(None, _numstat),
            loop.run_in_executor(None, _untracked),
        )

        per_file: Dict[str, dict] = {}
        total_added = total_removed = 0

        for line in numstat_out.strip().splitlines():
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            a_str, r_str, path = parts[0], parts[1], parts[2]
            is_binary = (a_str == '-' and r_str == '-')
            added   = 0 if is_binary else (int(a_str) if a_str.isdigit() else 0)
            removed = 0 if is_binary else (int(r_str) if r_str.isdigit() else 0)
            per_file[path] = {'added': added, 'removed': removed,
                              'isBinary': is_binary, 'isUntracked': False}
            total_added   += added
            total_removed += removed

        for line in untracked_out.strip().splitlines():
            path = line.strip()
            if not path or path in per_file:
                continue
            try:
                added = len((Path(cwd) / path).read_text(errors='replace').splitlines())
            except Exception:
                added = 0
            per_file[path] = {'added': added, 'removed': 0,
                              'isBinary': False, 'isUntracked': True}
            total_added += added

        return GitDiffResult(
            stats=GitDiffStats(total_added=total_added,
                               total_removed=total_removed,
                               total_files=len(per_file)),
            per_file_stats=per_file,
        )

    except Exception:
        return None


async def fetch_git_diff_hunks(repo_path: str = None) -> Dict[str, List[StructuredPatchHunk]]:
    """
    Fetch structured patch hunks for all changed files using `git diff HEAD`.
    Returns dict: path -> list of StructuredPatchHunk.
    """
    cwd = repo_path or os.getcwd()
    _flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    _DIFF_FILE_RE  = re.compile(r'^diff --git a/.+ b/(.+)$')
    _HUNK_HDR_RE   = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')

    try:
        loop = asyncio.get_event_loop()

        def _run():
            r = subprocess.run(
                ['git', 'diff', 'HEAD', '--unified=3'],
                cwd=cwd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', creationflags=_flags
            )
            return r.stdout

        stdout = await loop.run_in_executor(None, _run)

        hunks: Dict[str, List[StructuredPatchHunk]] = {}
        current_file: Optional[str] = None
        current_hunk: Optional[StructuredPatchHunk] = None

        for line in stdout.splitlines():
            m = _DIFF_FILE_RE.match(line)
            if m:
                if current_hunk and current_file:
                    hunks.setdefault(current_file, []).append(current_hunk)
                    current_hunk = None
                current_file = m.group(1)
                hunks.setdefault(current_file, [])
                continue

            m = _HUNK_HDR_RE.match(line)
            if m and current_file:
                if current_hunk:
                    hunks.setdefault(current_file, []).append(current_hunk)
                current_hunk = StructuredPatchHunk(
                    file_path=current_file,
                    old_start=int(m.group(1)),
                    old_lines=int(m.group(2) or 1),
                    new_start=int(m.group(3)),
                    new_lines=int(m.group(4) or 1),
                    lines=[line],
                )
                continue

            if current_hunk is not None:
                if line.startswith(('-', '+', ' ', '\\')):
                    current_hunk.lines.append(line)
                else:
                    hunks.setdefault(current_file, []).append(current_hunk)
                    current_hunk = None

        if current_hunk and current_file:
            hunks.setdefault(current_file, []).append(current_hunk)

        return hunks

    except Exception:
        return {}


# ============================================================
# Convenience functions for agent use
def get_git_manager() -> GitManager:
    """Get a GitManager instance for the current repository."""
    manager = GitManager()
    cwd = os.getcwd()
    manager.set_repository(cwd)
    return manager


def get_current_branch() -> Optional[str]:
    """Quick function to get current branch."""
    manager = get_git_manager()
    return manager.get_branch() if manager.is_repo() else None


def get_changed_files() -> List[str]:
    """Quick function to get changed files."""
    manager = get_git_manager()
    if not manager.is_repo():
        return []
    return [f.path for f in manager.get_status()]


def is_git_repo(path: str = None) -> bool:
    """Check if path is a git repository."""
    manager = GitManager()
    return manager.set_repository(path or os.getcwd())


__all__ = [
    'GitManager',
    'GitStatus',
    'GitFile',
    'GitCommit',
    # Diff types (required by useDiffData.py)
    'GitDiffStats',
    'GitDiffResult',
    'StructuredPatchHunk',
    'fetch_git_diff',
    'fetch_git_diff_hunks',
    # Convenience helpers
    'get_git_manager',
    'get_current_branch',
    'get_changed_files',
    'is_git_repo',
]
