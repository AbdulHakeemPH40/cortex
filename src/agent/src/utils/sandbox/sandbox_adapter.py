"""
Sandbox adapter with Cortex-style behavior for Cortex Python runtime.

This module ports key logic from TS sandbox-adapter:
- settings -> runtime config conversion
- trusted sandbox enable checks
- policy helpers and exclusion helpers
- worktree / bare-git hardening cleanup hooks
- lifecycle methods (initialize/refresh/reset)
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

try:
    from ..settings.settings import (
        getEnabledSettingSources,
        getInitialSettings,
        getManagedSettingsDropInDir,
        getSettings_DEPRECATED,
        getSettingsFilePathForSource,
        getSettingsForSource,
        getSettingsRootPathForSource,
        updateSettingsForSource,
    )
except ImportError:
    def getEnabledSettingSources() -> List[str]:
        return ["userSettings", "projectSettings", "localSettings", "policySettings", "flagSettings"]

    def getInitialSettings() -> Dict[str, Any]:
        return {}

    def getSettings_DEPRECATED() -> Dict[str, Any]:
        return {}

    def getSettingsForSource(_source: str) -> Dict[str, Any]:
        return {}

    def getSettingsRootPathForSource(_source: str) -> str:
        return os.getcwd()

    def getSettingsFilePathForSource(_source: str) -> Optional[str]:
        return None

    def getManagedSettingsDropInDir() -> str:
        return os.path.join(os.path.expanduser("~"), ".cortex", "managed-settings.d")

    def updateSettingsForSource(_source: str, _settings: Dict[str, Any]) -> Dict[str, Any]:
        return {"error": None}

try:
    from ..bootstrap.state import get_additional_directories_for_cortex_md, get_cwd_state, get_original_cwd
except ImportError:
    def get_additional_directories_for_cortex_md() -> List[str]:
        return []

    def get_cwd_state() -> Dict[str, Any]:
        return {"cwd": os.getcwd()}

    def get_original_cwd() -> str:
        return os.getcwd()

try:
    from ..permissions.permissionRuleParser import permission_rule_value_from_string
except ImportError:
    def permission_rule_value_from_string(rule_string: str) -> Dict[str, Optional[str]]:
        match = re.match(r"^([^(]+)\(([^)]+)\)$", rule_string)
        if not match:
            return {"tool_name": rule_string, "rule_content": None}
        return {"tool_name": match.group(1), "rule_content": match.group(2)}

try:
    from ..permissions.filesystem import get_cortex_temp_dir
except ImportError:
    def get_cortex_temp_dir() -> str:
        return os.environ.get("TMPDIR", os.path.join(os.path.expanduser("~"), ".cortex", "tmp"))

try:
    from ...tools.BashTool.toolName import BASH_TOOL_NAME
except ImportError:
    BASH_TOOL_NAME = "Bash"
try:
    from ...tools.FileEditTool.constants import FILE_EDIT_TOOL_NAME
except ImportError:
    FILE_EDIT_TOOL_NAME = "Edit"
try:
    from ...tools.FileReadTool.prompt import FILE_READ_TOOL_NAME
except ImportError:
    FILE_READ_TOOL_NAME = "Read"
try:
    from ...tools.WebFetchTool.prompt import WEB_FETCH_TOOL_NAME
except ImportError:
    WEB_FETCH_TOOL_NAME = "WebFetch"

_SETTING_SOURCES: List[str] = list(getEnabledSettingSources())
_TRUSTED_SANDBOX_SOURCES: List[str] = ["userSettings", "localSettings", "flagSettings", "policySettings"]
_RUNTIME_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_WORKTREE_MAIN_REPO_PATH: Optional[str] = None
_BARE_GIT_REPO_SCRUB_PATHS: List[str] = []
_INITIALIZED: bool = False


def _settings() -> Dict[str, Any]:
    value = getSettings_DEPRECATED()
    return value if isinstance(value, dict) else {}


def _sandbox_settings() -> Dict[str, Any]:
    return (_settings().get("sandbox") or {}) if isinstance(_settings(), dict) else {}


def _platform_name() -> str:
    raw = platform.system().lower()
    if raw == "darwin":
        return "macos"
    if raw == "linux":
        return "linux"
    if raw == "windows":
        return "windows"
    return raw


def _path_expand(pattern: str, source: str) -> str:
    if pattern.startswith("//"):
        return pattern[1:]
    if pattern.startswith("~"):
        return os.path.expanduser(pattern)
    if os.path.isabs(pattern):
        return os.path.normpath(pattern)
    return os.path.normpath(os.path.join(getSettingsRootPathForSource(source), pattern))


def _cwd_from_state() -> str:
    state = get_cwd_state()
    if isinstance(state, dict):
        cwd = state.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    if isinstance(state, str):
        return state
    return os.getcwd()


def _rule_get(rule: Any, key: str) -> Optional[str]:
    if isinstance(rule, dict):
        return rule.get(key)
    if hasattr(rule, key):
        return getattr(rule, key)
    alt = "tool_name" if key == "toolName" else "rule_content"
    if hasattr(rule, alt):
        return getattr(rule, alt)
    if isinstance(rule, dict):
        return rule.get(alt)
    return None


def permission_rule_extract_prefix(permission_rule: str) -> Optional[str]:
    match = re.match(r"^(.+):\*$", permission_rule)
    return match.group(1) if match else None


def resolve_path_pattern_for_sandbox(pattern: str, source: str) -> str:
    if pattern.startswith("//"):
        return pattern[1:]
    if pattern.startswith("/") and not pattern.startswith("//"):
        root = getSettingsRootPathForSource(source)
        return os.path.normpath(os.path.join(root, pattern[1:]))
    return pattern


def resolve_sandbox_filesystem_path(pattern: str, source: str) -> str:
    return _path_expand(pattern, source)


def should_allow_managed_sandbox_domains_only() -> bool:
    policy = getSettingsForSource("policySettings") or {}
    return bool(((policy.get("sandbox") or {}).get("network") or {}).get("allowManagedDomainsOnly") is True)


def should_allow_managed_read_paths_only() -> bool:
    policy = getSettingsForSource("policySettings") or {}
    return bool(((policy.get("sandbox") or {}).get("filesystem") or {}).get("allowManagedReadPathsOnly") is True)


def detect_worktree_main_repo_path(cwd: str) -> Optional[str]:
    git_path = os.path.join(cwd, ".git")
    if not os.path.isfile(git_path):
        return None
    try:
        content = Path(git_path).read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"^gitdir:\s*(.+)$", content, flags=re.MULTILINE)
        if not match:
            return None
        gitdir = os.path.abspath(os.path.join(cwd, match.group(1).strip()))
        marker = f"{os.sep}.git{os.sep}worktrees{os.sep}"
        idx = gitdir.rfind(marker)
        return gitdir[:idx] if idx > 0 else None
    except Exception:
        return None


def scrub_bare_git_repo_files() -> None:
    for p in list(_BARE_GIT_REPO_SCRUB_PATHS):
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def _extract_domains_from_permissions(permission_rules: Iterable[str], target: List[str], kind: str) -> None:
    for rule_string in permission_rules:
        parsed = permission_rule_value_from_string(rule_string)
        tool_name = _rule_get(parsed, "toolName")
        rule_content = _rule_get(parsed, "ruleContent") or ""
        if tool_name == WEB_FETCH_TOOL_NAME and rule_content.startswith("domain:"):
            target.append(rule_content[len("domain:"):])


def convert_to_sandbox_runtime_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    permissions = settings.get("permissions") or {}
    sandbox = settings.get("sandbox") or {}
    allowed_domains: List[str] = []
    denied_domains: List[str] = []

    if should_allow_managed_sandbox_domains_only():
        policy = getSettingsForSource("policySettings") or {}
        allowed_domains.extend((((policy.get("sandbox") or {}).get("network") or {}).get("allowedDomains") or []))
        _extract_domains_from_permissions((policy.get("permissions") or {}).get("allow") or [], allowed_domains, "allow")
    else:
        allowed_domains.extend(((sandbox.get("network") or {}).get("allowedDomains") or []))
        _extract_domains_from_permissions(permissions.get("allow") or [], allowed_domains, "allow")

    _extract_domains_from_permissions(permissions.get("deny") or [], denied_domains, "deny")

    allow_write: List[str] = [".", get_cortex_temp_dir()]
    deny_write: List[str] = []
    deny_read: List[str] = []
    allow_read: List[str] = []

    settings_paths = [getSettingsFilePathForSource(s) for s in _SETTING_SOURCES]
    deny_write.extend([p for p in settings_paths if p])
    deny_write.append(getManagedSettingsDropInDir())

    cwd = _cwd_from_state()
    original_cwd = get_original_cwd()
    if cwd != original_cwd:
        deny_write.extend(
            [
                os.path.join(cwd, ".cortex", "settings.json"),
                os.path.join(cwd, ".cortex", "settings.local.json"),
            ]
        )

    deny_write.append(os.path.join(original_cwd, ".cortex", "skills"))
    if cwd != original_cwd:
        deny_write.append(os.path.join(cwd, ".cortex", "skills"))

    _BARE_GIT_REPO_SCRUB_PATHS.clear()
    bare_git_repo_files = ["HEAD", "objects", "refs", "hooks", "config"]
    for base_dir in [original_cwd] if cwd == original_cwd else [original_cwd, cwd]:
        for entry in bare_git_repo_files:
            p = os.path.join(base_dir, entry)
            if os.path.exists(p):
                deny_write.append(p)
            else:
                _BARE_GIT_REPO_SCRUB_PATHS.append(p)

    if _WORKTREE_MAIN_REPO_PATH and _WORKTREE_MAIN_REPO_PATH != cwd:
        allow_write.append(_WORKTREE_MAIN_REPO_PATH)

    additional_dirs = set((permissions.get("additionalDirectories") or []) + list(get_additional_directories_for_cortex_md()))
    allow_write.extend(additional_dirs)

    for source in _SETTING_SOURCES:
        source_settings = getSettingsForSource(source) or {}
        source_permissions = source_settings.get("permissions") or {}

        for rule_string in source_permissions.get("allow") or []:
            parsed = permission_rule_value_from_string(rule_string)
            if _rule_get(parsed, "toolName") == FILE_EDIT_TOOL_NAME and _rule_get(parsed, "ruleContent"):
                allow_write.append(resolve_path_pattern_for_sandbox(_rule_get(parsed, "ruleContent") or "", source))

        for rule_string in source_permissions.get("deny") or []:
            parsed = permission_rule_value_from_string(rule_string)
            if _rule_get(parsed, "toolName") == FILE_EDIT_TOOL_NAME and _rule_get(parsed, "ruleContent"):
                deny_write.append(resolve_path_pattern_for_sandbox(_rule_get(parsed, "ruleContent") or "", source))
            if _rule_get(parsed, "toolName") == FILE_READ_TOOL_NAME and _rule_get(parsed, "ruleContent"):
                deny_read.append(resolve_path_pattern_for_sandbox(_rule_get(parsed, "ruleContent") or "", source))

        fs = ((source_settings.get("sandbox") or {}).get("filesystem") or {})
        for p in fs.get("allowWrite") or []:
            allow_write.append(resolve_sandbox_filesystem_path(str(p), source))
        for p in fs.get("denyWrite") or []:
            deny_write.append(resolve_sandbox_filesystem_path(str(p), source))
        for p in fs.get("denyRead") or []:
            deny_read.append(resolve_sandbox_filesystem_path(str(p), source))
        if not should_allow_managed_read_paths_only() or source == "policySettings":
            for p in fs.get("allowRead") or []:
                allow_read.append(resolve_sandbox_filesystem_path(str(p), source))

    return {
        "network": {
            "allowedDomains": allowed_domains,
            "deniedDomains": denied_domains,
            "allowUnixSockets": ((sandbox.get("network") or {}).get("allowUnixSockets")),
            "allowAllUnixSockets": ((sandbox.get("network") or {}).get("allowAllUnixSockets")),
            "allowLocalBinding": ((sandbox.get("network") or {}).get("allowLocalBinding")),
            "httpProxyPort": ((sandbox.get("network") or {}).get("httpProxyPort")),
            "socksProxyPort": ((sandbox.get("network") or {}).get("socksProxyPort")),
        },
        "filesystem": {
            "denyRead": deny_read,
            "allowRead": allow_read,
            "allowWrite": allow_write,
            "denyWrite": deny_write,
        },
        "ignoreViolations": sandbox.get("ignoreViolations"),
        "enableWeakerNestedSandbox": sandbox.get("enableWeakerNestedSandbox"),
        "enableWeakerNetworkIsolation": sandbox.get("enableWeakerNetworkIsolation"),
        "ripgrep": sandbox.get("ripgrep"),
    }


class SandboxManager:
    @staticmethod
    async def initialize(sandbox_ask_callback: Optional[Callable[[Any], Any]] = None) -> None:
        del sandbox_ask_callback
        global _RUNTIME_CONFIG_CACHE, _WORKTREE_MAIN_REPO_PATH, _INITIALIZED
        if _INITIALIZED:
            return
        cwd = _cwd_from_state()
        _WORKTREE_MAIN_REPO_PATH = detect_worktree_main_repo_path(cwd)
        _RUNTIME_CONFIG_CACHE = convert_to_sandbox_runtime_config(_settings())
        _INITIALIZED = True

    @staticmethod
    def is_supported_platform() -> bool:
        return _platform_name() in {"macos", "linux"}

    @staticmethod
    def is_platform_in_enabled_list() -> bool:
        try:
            settings = getInitialSettings() or {}
            enabled = ((settings.get("sandbox") or {}).get("enabledPlatforms"))
            if enabled is None:
                return True
            if not isinstance(enabled, list) or len(enabled) == 0:
                return False
            return _platform_name() in [str(p).lower() for p in enabled]
        except Exception:
            return True

    @staticmethod
    def check_dependencies() -> Dict[str, List[str]]:
        errors: List[str] = []
        warnings: List[str] = []
        p = _platform_name()
        if p == "linux":
            if shutil.which("bwrap") is None:
                errors.append("missing dependency: bwrap")
            if shutil.which("rg") is None:
                warnings.append("ripgrep not found; sandbox grep features may be limited")
        elif p == "macos":
            if shutil.which("sandbox-exec") is None:
                warnings.append("sandbox-exec not found; macOS sandbox wrapping may be unavailable")
        else:
            errors.append("unsupported platform")
        return {"errors": errors, "warnings": warnings}

    @staticmethod
    def is_sandbox_enabled_in_settings() -> bool:
        try:
            for source in _TRUSTED_SANDBOX_SOURCES:
                source_settings = getSettingsForSource(source) or {}
                if ((source_settings.get("sandbox") or {}).get("enabled")) is True:
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def is_auto_allow_bash_if_sandboxed_enabled() -> bool:
        return bool(_sandbox_settings().get("autoAllowBashIfSandboxed", True))

    @staticmethod
    def are_unsandboxed_commands_allowed() -> bool:
        return bool(_sandbox_settings().get("allowUnsandboxedCommands", True))

    @staticmethod
    def is_sandbox_required() -> bool:
        return SandboxManager.is_sandbox_enabled_in_settings() and bool(_sandbox_settings().get("failIfUnavailable", False))

    @staticmethod
    def is_sandboxing_enabled() -> bool:
        if not SandboxManager.is_supported_platform():
            return False
        if not SandboxManager.is_platform_in_enabled_list():
            return False
        if SandboxManager.check_dependencies().get("errors"):
            return False
        return SandboxManager.is_sandbox_enabled_in_settings()

    @staticmethod
    def get_sandbox_unavailable_reason() -> Optional[str]:
        if not SandboxManager.is_sandbox_enabled_in_settings():
            return None
        if not SandboxManager.is_supported_platform():
            return f"sandbox.enabled is set but {_platform_name()} is not supported"
        if not SandboxManager.is_platform_in_enabled_list():
            return f"sandbox.enabled is set but {_platform_name()} is not in sandbox.enabledPlatforms"
        deps = SandboxManager.check_dependencies()
        if deps.get("errors"):
            return f"sandbox.enabled is set but dependencies are missing: {', '.join(deps['errors'])}"
        return None

    @staticmethod
    def get_linux_glob_pattern_warnings() -> List[str]:
        if _platform_name() not in {"linux"}:
            return []
        settings = _settings()
        if not ((settings.get("sandbox") or {}).get("enabled")):
            return []
        warnings: List[str] = []
        permissions = settings.get("permissions") or {}
        for rule_string in (permissions.get("allow") or []) + (permissions.get("deny") or []):
            parsed = permission_rule_value_from_string(rule_string)
            tool_name = _rule_get(parsed, "toolName")
            rule_content = _rule_get(parsed, "ruleContent") or ""
            stripped = re.sub(r"/\*\*$", "", rule_content)
            has_globs = bool(re.search(r"[*?\[\]]", stripped))
            if tool_name in {FILE_EDIT_TOOL_NAME, FILE_READ_TOOL_NAME} and has_globs:
                warnings.append(rule_string)
        return warnings

    @staticmethod
    def are_sandbox_settings_locked_by_policy() -> bool:
        for source in ["flagSettings", "policySettings"]:
            settings = getSettingsForSource(source) or {}
            sb = settings.get("sandbox") or {}
            if (
                sb.get("enabled") is not None
                or sb.get("autoAllowBashIfSandboxed") is not None
                or sb.get("allowUnsandboxedCommands") is not None
            ):
                return True
        return False

    @staticmethod
    async def set_sandbox_settings(options: Dict[str, Any]) -> None:
        existing = getSettingsForSource("localSettings") or {}
        sandbox = existing.get("sandbox") or {}
        patch: Dict[str, Any] = {"sandbox": dict(sandbox)}
        for key in ["enabled", "autoAllowBashIfSandboxed", "allowUnsandboxedCommands"]:
            if key in options and options[key] is not None:
                patch["sandbox"][key] = options[key]
        updateSettingsForSource("localSettings", patch)
        SandboxManager.refresh_config()

    @staticmethod
    def get_excluded_commands() -> List[str]:
        settings = _settings()
        return list(((settings.get("sandbox") or {}).get("excludedCommands") or []))

    @staticmethod
    def add_to_excluded_commands(command: str, permission_updates: Optional[List[Dict[str, Any]]] = None) -> str:
        existing = getSettingsForSource("localSettings") or {}
        existing_list = list(((existing.get("sandbox") or {}).get("excludedCommands") or []))
        pattern = command
        if permission_updates:
            for update in permission_updates:
                if update.get("type") != "addRules":
                    continue
                for rule in update.get("rules") or []:
                    if rule.get("toolName") == BASH_TOOL_NAME and rule.get("ruleContent"):
                        pattern = permission_rule_extract_prefix(rule["ruleContent"]) or rule["ruleContent"]
                        break
                if pattern != command:
                    break
        if pattern not in existing_list:
            patch = {"sandbox": {**(existing.get("sandbox") or {}), "excludedCommands": [*existing_list, pattern]}}
            updateSettingsForSource("localSettings", patch)
            SandboxManager.refresh_config()
        return pattern

    @staticmethod
    def _runtime_config() -> Dict[str, Any]:
        global _RUNTIME_CONFIG_CACHE
        if _RUNTIME_CONFIG_CACHE is None:
            _RUNTIME_CONFIG_CACHE = convert_to_sandbox_runtime_config(_settings())
        return _RUNTIME_CONFIG_CACHE

    @staticmethod
    def refresh_config() -> None:
        global _RUNTIME_CONFIG_CACHE
        if not SandboxManager.is_sandboxing_enabled():
            return
        _RUNTIME_CONFIG_CACHE = convert_to_sandbox_runtime_config(_settings())

    @staticmethod
    async def reset() -> None:
        global _RUNTIME_CONFIG_CACHE, _WORKTREE_MAIN_REPO_PATH, _INITIALIZED
        _RUNTIME_CONFIG_CACHE = None
        _WORKTREE_MAIN_REPO_PATH = None
        _BARE_GIT_REPO_SCRUB_PATHS.clear()
        _INITIALIZED = False

    @staticmethod
    async def wrap_with_sandbox(
        command: str,
        bin_shell: Optional[str] = None,
        custom_config: Optional[Dict[str, Any]] = None,
        abort_signal: Any = None,
    ) -> str:
        del abort_signal
        if not SandboxManager.is_sandboxing_enabled():
            return command
        if not _INITIALIZED:
            await SandboxManager.initialize()

        runtime = dict(SandboxManager._runtime_config())
        if isinstance(custom_config, dict):
            runtime.update(custom_config)

        shell = bin_shell or "/bin/sh"
        quoted_cmd = shlex.quote(command)
        cwd = _cwd_from_state()

        if _platform_name() == "linux" and shutil.which("bwrap"):
            return (
                "bwrap --unshare-all --die-with-parent --proc /proc --dev /dev "
                "--ro-bind / / "
                f"--chdir {shlex.quote(cwd)} "
                f"{shlex.quote(shell)} -c {quoted_cmd}"
            )

        if _platform_name() == "macos" and shutil.which("sandbox-exec"):
            profile = "(version 1) (allow default)"
            return f"sandbox-exec -p {shlex.quote(profile)} {shlex.quote(shell)} -c {quoted_cmd}"

        # If runtime says sandbox required but platform runtime wrapper is unavailable,
        # let callers enforce policy via is_sandbox_required / allowUnsandboxedCommands.
        return command

    @staticmethod
    def cleanup_after_command() -> None:
        scrub_bare_git_repo_files()

    @staticmethod
    def get_fs_read_config() -> Dict[str, Any]:
        fs = (SandboxManager._runtime_config().get("filesystem") or {})
        return {"denyOnly": list(fs.get("denyRead") or []), "allowWithinDeny": list(fs.get("allowRead") or [])}

    @staticmethod
    def get_fs_write_config() -> Dict[str, Any]:
        fs = (SandboxManager._runtime_config().get("filesystem") or {})
        return {"allowOnly": list(fs.get("allowWrite") or []), "denyWithinAllow": list(fs.get("denyWrite") or [])}

    @staticmethod
    def get_network_restriction_config() -> Optional[Dict[str, Any]]:
        net = (SandboxManager._runtime_config().get("network") or {})
        if not net:
            return None
        return {"allowedHosts": list(net.get("allowedDomains") or []), "deniedHosts": list(net.get("deniedDomains") or [])}

    @staticmethod
    def get_allow_unix_sockets() -> Optional[List[str]]:
        net = (SandboxManager._runtime_config().get("network") or {})
        sockets = net.get("allowUnixSockets")
        return list(sockets) if isinstance(sockets, list) else None

    @staticmethod
    def get_allow_local_binding() -> Optional[bool]:
        return (SandboxManager._runtime_config().get("network") or {}).get("allowLocalBinding")

    @staticmethod
    def get_ignore_violations() -> Optional[Dict[str, List[str]]]:
        value = SandboxManager._runtime_config().get("ignoreViolations")
        return value if isinstance(value, dict) else None

    @staticmethod
    def get_enable_weaker_nested_sandbox() -> Optional[bool]:
        return SandboxManager._runtime_config().get("enableWeakerNestedSandbox")

    @staticmethod
    def get_proxy_port() -> Optional[int]:
        return (SandboxManager._runtime_config().get("network") or {}).get("httpProxyPort")

    @staticmethod
    def get_socks_proxy_port() -> Optional[int]:
        return (SandboxManager._runtime_config().get("network") or {}).get("socksProxyPort")

    @staticmethod
    async def wait_for_network_initialization() -> bool:
        return True

    @staticmethod
    def annotate_stderr_with_sandbox_failures(_command: str, stderr: str) -> str:
        return stderr

    # camelCase aliases
    initialize = initialize
    isSupportedPlatform = is_supported_platform
    isPlatformInEnabledList = is_platform_in_enabled_list
    getSandboxUnavailableReason = get_sandbox_unavailable_reason
    isSandboxingEnabled = is_sandboxing_enabled
    isSandboxEnabledInSettings = is_sandbox_enabled_in_settings
    checkDependencies = check_dependencies
    isAutoAllowBashIfSandboxedEnabled = is_auto_allow_bash_if_sandboxed_enabled
    areUnsandboxedCommandsAllowed = are_unsandboxed_commands_allowed
    isSandboxRequired = is_sandbox_required
    areSandboxSettingsLockedByPolicy = are_sandbox_settings_locked_by_policy
    setSandboxSettings = set_sandbox_settings
    getExcludedCommands = get_excluded_commands
    wrapWithSandbox = wrap_with_sandbox
    cleanupAfterCommand = cleanup_after_command
    getFsReadConfig = get_fs_read_config
    getFsWriteConfig = get_fs_write_config
    getNetworkRestrictionConfig = get_network_restriction_config
    getAllowUnixSockets = get_allow_unix_sockets
    getAllowLocalBinding = get_allow_local_binding
    getIgnoreViolations = get_ignore_violations
    getEnableWeakerNestedSandbox = get_enable_weaker_nested_sandbox
    getProxyPort = get_proxy_port
    getSocksProxyPort = get_socks_proxy_port
    waitForNetworkInitialization = wait_for_network_initialization
    getLinuxGlobPatternWarnings = get_linux_glob_pattern_warnings
    refreshConfig = refresh_config
    reset = reset
    annotateStderrWithSandboxFailures = annotate_stderr_with_sandbox_failures


# module-level aliases mirroring TS exports
convertToSandboxRuntimeConfig = convert_to_sandbox_runtime_config
resolvePathPatternForSandbox = resolve_path_pattern_for_sandbox
resolveSandboxFilesystemPath = resolve_sandbox_filesystem_path
shouldAllowManagedSandboxDomainsOnly = should_allow_managed_sandbox_domains_only
addToExcludedCommands = SandboxManager.add_to_excluded_commands
