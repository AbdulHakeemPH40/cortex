"""
paths - Auto-memory path resolution and validation for Cortex IDE.

Handles path computation for persistent memory storage with:
- Security validation (reject dangerous paths like ~/, UNC, null bytes)
- Environment variable overrides (CORTEX_REMOTE_MEMORY_DIR, CORTEX_MEMORY_PATH_OVERRIDE)
- Settings.json integration (autoMemoryDirectory from trusted sources)
- Git root canonicalization (worktree support)
- Daily log path generation
"""

import os
import subprocess
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from ..bootstrap.state import getIsNonInteractiveSession, getProjectRoot
except ImportError:
    from ..bootstrap.state import getProjectRoot, get_is_non_interactive_session

    def getIsNonInteractiveSession():
        return get_is_non_interactive_session()
from ..utils.settings.settings import getInitialSettings, getSettingsForSource


def isEnvTruthy(env_val: Optional[str]) -> bool:
    if not env_val:
        return False
    return env_val.strip().lower() in ("1", "true", "yes", "on")


def isEnvDefinedFalsy(env_val: Optional[str]) -> bool:
    if env_val is None:
        return False
    return env_val.strip().lower() in ("0", "false", "no", "off")


def sanitizePath(path: str) -> str:
    sanitized = path.replace(":", "_").replace("\\", "_").replace("/", "_")
    sanitized = sanitized.strip("_ ")
    return sanitized or "project"


def getCortexConfigHomeDir() -> str:
    config_dir = os.environ.get("CORTEX_CONFIG_DIR")
    if config_dir:
        return config_dir
    return str(Path.home() / ".cortex")


def findCanonicalGitRoot(start_path: str) -> Optional[str]:
    """
    Return canonical git root for current repository.
    For worktrees, use git common-dir to map all worktrees to one root.
    """
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not top:
            return None

        common_dir = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=start_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        if common_dir:
            parent = os.path.dirname(common_dir)
            if os.path.isdir(parent):
                return parent
        return top if os.path.isdir(top) else None
    except Exception:
        return None


def getFeatureValue_CACHED_MAY_BE_STALE(_feature: str, default: bool) -> bool:
    """
    Optional feature gate hook.
    Replace with analytics/growthbook import if available in your build.
    """
    return default


def isAutoMemoryEnabled() -> bool:
    """
    Whether auto-memory features are enabled.
    Priority:
      1. CORTEX_DISABLE_AUTO_MEMORY
      2. CORTEX_SIMPLE
      3. CORTEX_REMOTE without CORTEX_REMOTE_MEMORY_DIR
      4. settings.autoMemoryEnabled
      5. default True
    """
    env_val = os.environ.get("CORTEX_DISABLE_AUTO_MEMORY")
    if isEnvTruthy(env_val):
        return False
    if isEnvDefinedFalsy(env_val):
        return True

    if isEnvTruthy(os.environ.get("CORTEX_SIMPLE")):
        return False

    if isEnvTruthy(os.environ.get("CORTEX_REMOTE")) and not os.environ.get(
        "CORTEX_REMOTE_MEMORY_DIR"
    ):
        return False

    settings = getInitialSettings()
    if isinstance(settings, dict):
        if "autoMemoryEnabled" in settings and settings["autoMemoryEnabled"] is not None:
            return bool(settings["autoMemoryEnabled"])
    else:
        val = getattr(settings, "autoMemoryEnabled", None)
        if val is not None:
            return bool(val)

    return True


def isExtractModeActive() -> bool:
    if not getFeatureValue_CACHED_MAY_BE_STALE("tengu_passport_quail", False):
        return False
    return (
        not getIsNonInteractiveSession()
        or getFeatureValue_CACHED_MAY_BE_STALE("tengu_slate_thimble", False)
    )


def getMemoryBaseDir() -> str:
    """
    Base directory resolution:
      1. CORTEX_REMOTE_MEMORY_DIR
      2. ~/.cortex
    """
    remote_dir = (
        os.environ.get("CORTEX_REMOTE_MEMORY_DIR")
        or os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR")
    )
    if remote_dir:
        return remote_dir
    return getCortexConfigHomeDir()


AUTO_MEM_DIRNAME = "memory"
AUTO_MEM_ENTRYPOINT_NAME = "MEMORY.md"


def _validateMemoryPath(raw: Optional[str], expandTilde: bool) -> Optional[str]:
    if not raw:
        return None

    candidate = raw
    if expandTilde and (candidate.startswith("~/") or candidate.startswith("~\\")):
        rest = candidate[2:]
        rest_norm = os.path.normpath(rest or ".")
        if rest_norm in (".", ".."):
            return None
        candidate = os.path.join(str(Path.home()), rest)

    normalized = os.path.normpath(candidate).rstrip("/\\")
    if (
        not os.path.isabs(normalized)
        or len(normalized) < 3
        or (len(normalized) == 2 and normalized[1] == ":")
        or normalized.startswith("\\\\")
        or normalized.startswith("//")
        or "\0" in normalized
    ):
        return None

    return normalized + os.sep


def _getAutoMemPathOverride() -> Optional[str]:
    return _validateMemoryPath(os.environ.get("CORTEX_MEMORY_PATH_OVERRIDE"), False)


def _getAutoMemPathSetting() -> Optional[str]:
    """
    Trusted settings sources only. Project settings intentionally excluded.
    """
    def _src(name: str) -> dict:
        value = getSettingsForSource(name)
        return value if isinstance(value, dict) else {}

    dir_val = (
        _src("policySettings").get("autoMemoryDirectory")
        or _src("flagSettings").get("autoMemoryDirectory")
        or _src("localSettings").get("autoMemoryDirectory")
        or _src("userSettings").get("autoMemoryDirectory")
    )
    return _validateMemoryPath(dir_val, True)


def hasAutoMemPathOverride() -> bool:
    return _getAutoMemPathOverride() is not None


def _getAutoMemBase() -> str:
    return findCanonicalGitRoot(getProjectRoot()) or getProjectRoot()


@lru_cache(maxsize=None)
def getAutoMemPath() -> str:
    """
    Full auto-memory directory path:
      1. CORTEX_MEMORY_PATH_OVERRIDE
      2. autoMemoryDirectory setting
      3. <base>/projects/<sanitized-git-root>/memory/
    """
    override = _getAutoMemPathOverride() or _getAutoMemPathSetting()
    if override:
        return override

    projects_dir = os.path.join(getMemoryBaseDir(), "projects")
    base_path = os.path.join(projects_dir, sanitizePath(_getAutoMemBase()), AUTO_MEM_DIRNAME)
    return base_path + os.sep


def getAutoMemDailyLogPath(date_obj: Optional[date] = None) -> str:
    if date_obj is None:
        date_obj = date.today()

    yyyy = str(date_obj.year)
    mm = str(date_obj.month).zfill(2)
    dd = str(date_obj.day).zfill(2)
    return os.path.join(getAutoMemPath(), "logs", yyyy, mm, f"{yyyy}-{mm}-{dd}.md")


def getAutoMemEntrypoint() -> str:
    return os.path.join(getAutoMemPath(), AUTO_MEM_ENTRYPOINT_NAME)


def isAutoMemPath(absolutePath: str) -> bool:
    normalized_path = os.path.normpath(absolutePath)
    auto_root = os.path.normpath(getAutoMemPath())
    return normalized_path == auto_root or normalized_path.startswith(auto_root + os.sep)


def getGlobalMemPath() -> str:
    return os.path.join(getMemoryBaseDir(), "global", AUTO_MEM_DIRNAME) + os.sep


def getGlobalMemEntrypoint() -> str:
    return os.path.join(getGlobalMemPath(), AUTO_MEM_ENTRYPOINT_NAME)


def getGlobalRulesDir() -> str:
    return os.path.join(getMemoryBaseDir(), "rules")


def getProjectRulesDir() -> str:
    return os.path.join(getProjectRoot(), ".cortex", "rules")


# snake_case aliases for compatibility with converted imports
is_auto_memory_enabled = isAutoMemoryEnabled
is_extract_mode_active = isExtractModeActive
get_memory_base_dir = getMemoryBaseDir
has_auto_mem_path_override = hasAutoMemPathOverride
get_auto_mem_path = getAutoMemPath
get_auto_mem_daily_log_path = getAutoMemDailyLogPath
get_auto_mem_entrypoint = getAutoMemEntrypoint
is_auto_mem_path = isAutoMemPath
get_global_mem_path = getGlobalMemPath
get_global_mem_entrypoint = getGlobalMemEntrypoint
get_global_rules_dir = getGlobalRulesDir
get_project_rules_dir = getProjectRulesDir
