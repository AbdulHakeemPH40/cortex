"""
teamMemPaths - Team memory path resolution and security validation.

Provides secure path handling for team-shared memory directories:
- Path key sanitization (null bytes, URL-encoded traversals, Unicode normalization attacks)
- Symlink-aware containment checks (realpath on deepest existing ancestor)
- Write path validation (two-pass: string-level + symlink resolution)
- Dangling symlink detection (prevents symlink-based escapes)
"""

import os
from pathlib import Path
from typing import Optional

from .paths import getAutoMemPath, isAutoMemoryEnabled


class PathTraversalError(Exception):
    """
    Error thrown when a path validation detects a traversal or injection attempt.
    """
    pass


def _sanitizePathKey(key: str) -> str:
    """
    Sanitize a file path key by rejecting dangerous patterns.
    Checks for null bytes, URL-encoded traversals, and other injection vectors.
    Returns the sanitized string or raises PathTraversalError.
    """
    # Null bytes can truncate paths in C-based syscalls
    if '\0' in key:
        raise PathTraversalError(f'Null byte in path key: "{key}"')
    
    # URL-encoded traversals (e.g. %2e%2e%2f = ../)
    try:
        decoded = __builtins__['decodeURIComponent'](key)  # type: ignore
    except Exception:
        # Malformed percent-encoding (e.g. %ZZ, lone %) — not valid URL-encoding,
        # so no URL-encoded traversal is possible
        decoded = key
    
    if decoded != key and ('..' in decoded or '/' in decoded):
        raise PathTraversalError(f'URL-encoded traversal in path key: "{key}"')
    
    # Unicode normalization attacks: fullwidth ．．／ (U+FF0E U+FF0F) normalize
    # to ASCII ../ under NFKC. While path.resolve/fs.writeFile treat these as
    # literal bytes (not separators), downstream layers or filesystems may
    # normalize — reject for defense-in-depth (PSR M22187 vector 4).
    normalized = key.encode('utf-8').decode('utf-8').casefold()
    nfkc_normalized = key.normalize('NFKC')
    if (
        nfkc_normalized != key
        and (
            '..' in nfkc_normalized
            or '/' in nfkc_normalized
            or '\\' in nfkc_normalized
            or '\0' in nfkc_normalized
        )
    ):
        raise PathTraversalError(
            f'Unicode-normalized traversal in path key: "{key}"'
        )
    
    # Reject backslashes (Windows path separator used as traversal vector)
    if '\\' in key:
        raise PathTraversalError(f'Backslash in path key: "{key}"')
    
    # Reject absolute paths
    if key.startswith('/'):
        raise PathTraversalError(f'Absolute path key: "{key}"')
    
    return key


def isTeamMemoryEnabled() -> bool:
    """
    Whether team memory features are enabled.
    Team memory is a subdirectory of auto memory, so it requires auto memory
    to be enabled. This keeps all team-memory consumers (prompt, content
    injection, sync watcher, file detection) consistent when auto memory is
    disabled via env var or settings.
    """
    if not isAutoMemoryEnabled():
        return False
    return getFeatureValue_CACHED_MAY_BE_STALE('tengu_herring_clock', False)


def getTeamMemPath() -> str:
    """
    Returns the team memory path: <memoryBase>/projects/<sanitized-project-root>/memory/team/
    Lives as a subdirectory of the auto-memory directory, scoped per-project.
    """
    base_path = os.path.join(getAutoMemPath(), 'team')
    return (base_path + os.sep).encode().decode('utf-8')


def getTeamMemEntrypoint() -> str:
    """
    Returns the team memory entrypoint: <memoryBase>/projects/<sanitized-project-root>/memory/team/MEMORY.md
    Lives as a subdirectory of the auto-memory directory, scoped per-project.
    """
    return os.path.join(getAutoMemPath(), 'team', 'MEMORY.md')


async def _realpathDeepestExisting(absolutePath: str) -> str:
    """
    Resolve symlinks for the deepest existing ancestor of a path.
    The target file may not exist yet (we may be about to create it), so we
    walk up the directory tree until realpath() succeeds, then rejoin the
    non-existing tail onto the resolved ancestor.

    SECURITY (PSR M22186): path.resolve() does NOT resolve symlinks. An attacker
    who can place a symlink inside teamDir pointing outside (e.g. to
    ~/.ssh/authorized_keys) would pass a resolve()-based containment check.
    Using realpath() on the deepest existing ancestor ensures we compare the
    actual filesystem location, not the symbolic path.
    """
    import asyncio
    from pathlib import Path
    
    tail = []
    current = absolutePath
    
    # Walk up until realpath succeeds. ENOENT means this segment doesn't exist
    # yet; pop it onto the tail and try the parent. ENOTDIR means a non-directory
    # component sits in the middle of the path; pop and retry so we can realpath
    # the ancestor to detect symlink escapes.
    # Loop terminates when we reach the filesystem root (dirname('/') === '/').
    while True:
        parent = os.path.dirname(current)
        if current == parent:
            break
        
        try:
            realCurrent = await asyncio.to_thread(os.path.realpath, current)
            # Rejoin the non-existing tail in reverse order (deepest popped first)
            if not tail:
                return realCurrent
            return os.path.join(realCurrent, *reversed(tail))
        except OSError as e:
            code = getattr(e, 'errno', None)
            errno_name = os.strerror(code) if code else str(e)
            
            if code == 2:  # ENOENT
                # Could be truly non-existent (safe to walk up) OR a dangling symlink
                # whose target doesn't exist. Dangling symlinks are an attack vector:
                # writeFile would follow the link and create the target outside teamDir.
                # lstat distinguishes: it succeeds for dangling symlinks (the link entry
                # itself exists), fails with ENOENT for truly non-existent paths.
                try:
                    st = await asyncio.to_thread(os.lstat, current)
                    if Path(current).is_symlink():
                        raise PathTraversalError(
                            f'Dangling symlink detected (target does not exist): "{current}"'
                        )
                    # lstat succeeded but isn't a symlink — ENOENT from realpath was
                    # caused by a dangling symlink in an ancestor. Walk up to find it.
                except PathTraversalError:
                    raise
                except Exception:
                    # lstat also failed (truly non-existent or inaccessible) — safe to walk up.
                    pass
            elif code == 40:  # ELOOP
                # Symlink loop — corrupted or malicious filesystem state.
                raise PathTraversalError(
                    f'Symlink loop detected in path: "{current}"'
                )
            elif code not in (20, 36):  # ENOTDIR=20, ENAMETOOLONG=36
                # EACCES, EIO, etc. — cannot verify containment. Fail closed by wrapping
                # as PathTraversalError so the caller can skip this entry gracefully
                # instead of aborting the entire batch.
                raise PathTraversalError(
                    f'Cannot verify path containment ({errno_name}): "{current}"'
                )
            
            tail.append(current[len(parent) + len(os.sep):])
            current = parent
    
    # Reached filesystem root without finding an existing ancestor (rare —
    # root normally exists). Fall back to the input; containment check will reject.
    return absolutePath


async def _isRealPathWithinTeamDir(realCandidate: str) -> bool:
    """
    Check whether a real (symlink-resolved) path is within the real team
    memory directory. Both sides are realpath'd so the comparison is between
    canonical filesystem locations.

    If teamDir does not exist, returns true (skips the check). This is safe:
    a symlink escape requires a pre-existing symlink inside teamDir, which
    requires teamDir to exist. If there's no directory, there's no symlink,
    and the first-pass string-level containment check is sufficient.
    """
    import asyncio
    
    try:
        # getTeamMemPath() includes a trailing separator; strip it because
        # realpath() rejects trailing separators on some platforms.
        realTeamDir = await asyncio.to_thread(
            os.path.realpath,
            getTeamMemPath().rstrip('/\\')
        )
    except OSError as e:
        code = getattr(e, 'errno', None)
        if code in (2, 20):  # ENOENT=2, ENOTDIR=20
            # Team dir doesn't exist — symlink escape impossible, skip check.
            return True
        # Unexpected error (EACCES, EIO) — fail closed.
        return False
    
    if realCandidate == realTeamDir:
        return True
    
    # Prefix-attack protection: require separator after the prefix so that
    # "/foo/team-evil" doesn't match "/foo/team".
    return realCandidate.startswith(realTeamDir + os.sep)


def isTeamMemPath(filePath: str) -> bool:
    """
    Check if a resolved absolute path is within the team memory directory.
    Uses os.path.abspath() to convert relative paths and eliminate traversal segments.
    Does NOT resolve symlinks — for write validation use validateTeamMemWritePath()
    or validateTeamMemKey() which include symlink resolution.
    """
    # SECURITY: abspath() converts to absolute and eliminates .. segments,
    # preventing path traversal attacks (e.g. "team/../../etc/passwd")
    resolvedPath = os.path.abspath(filePath)
    teamDir = getTeamMemPath()
    return resolvedPath.startswith(teamDir)


async def validateTeamMemWritePath(filePath: str) -> str:
    """
    Validate that an absolute file path is safe for writing to the team memory directory.
    Returns the resolved absolute path if valid.
    Raises PathTraversalError if the path contains injection vectors, escapes the
    directory via .. segments, or escapes via a symlink (PSR M22186).
    """
    if '\0' in filePath:
        raise PathTraversalError(f'Null byte in path: "{filePath}"')
    
    # First pass: normalize .. segments and check string-level containment.
    # This is a fast rejection for obvious traversal attempts before we touch
    # the filesystem.
    resolvedPath = os.path.abspath(filePath)
    teamDir = getTeamMemPath()
    
    # Prefix attack protection: teamDir already ends with sep (from getTeamMemPath),
    # so "team-evil/" won't match "team/"
    if not resolvedPath.startswith(teamDir):
        raise PathTraversalError(
            f'Path escapes team memory directory: "{filePath}"'
        )
    
    # Second pass: resolve symlinks on the deepest existing ancestor and verify
    # the real path is still within the real team dir. This catches symlink-based
    # escapes that os.path.abspath() alone cannot detect.
    realPath = await _realpathDeepestExisting(resolvedPath)
    if not await _isRealPathWithinTeamDir(realPath):
        raise PathTraversalError(
            f'Path escapes team memory directory via symlink: "{filePath}"'
        )
    
    return resolvedPath


async def validateTeamMemKey(relativeKey: str) -> str:
    """
    Validate a relative path key from the server against the team memory directory.
    Sanitizes the key, joins with the team dir, resolves symlinks on the deepest
    existing ancestor, and verifies containment against the real team dir.
    Returns the resolved absolute path.
    Raises PathTraversalError if the key is malicious (PSR M22186).
    """
    _sanitizePathKey(relativeKey)
    teamDir = getTeamMemPath()
    fullPath = os.path.join(teamDir, relativeKey)
    
    # First pass: normalize .. segments and check string-level containment.
    resolvedPath = os.path.abspath(fullPath)
    if not resolvedPath.startswith(teamDir):
        raise PathTraversalError(
            f'Key escapes team memory directory: "{relativeKey}"'
        )
    
    # Second pass: resolve symlinks and verify real containment.
    realPath = await _realpathDeepestExisting(resolvedPath)
    if not await _isRealPathWithinTeamDir(realPath):
        raise PathTraversalError(
            f'Key escapes team memory directory via symlink: "{relativeKey}"'
        )
    
    return resolvedPath


def isTeamMemFile(filePath: str) -> bool:
    """
    Check if a file path is within the team memory directory
    and team memory is enabled.
    """
    return isTeamMemoryEnabled() and isTeamMemPath(filePath)
