"""Lightweight sandbox adapter used by desktop runtime."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


class SandboxManager:
    """Compatibility sandbox facade for UI/tool integrations."""

    _settings: Dict[str, Any] = {"enabled": False}

    @staticmethod
    def is_sandbox_enabled_in_settings() -> bool:
        return bool(SandboxManager._settings.get("enabled", False))

    @staticmethod
    def are_sandbox_settings_locked_by_policy() -> bool:
        return os.environ.get("CORTEX_SANDBOX_SETTINGS_LOCKED", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def is_sandboxing_enabled() -> bool:
        if not SandboxManager.is_sandbox_enabled_in_settings():
            return False
        return SandboxManager.get_sandbox_unavailable_reason() is None

    @staticmethod
    def get_sandbox_unavailable_reason() -> Optional[str]:
        # Windows sandboxing backend is not wired in this desktop build.
        if os.name == "nt" and SandboxManager.is_sandbox_enabled_in_settings():
            return "Sandbox runtime backend is unavailable on this build."
        return None

    @staticmethod
    async def set_sandbox_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
        if SandboxManager.are_sandbox_settings_locked_by_policy():
            return {"ok": False, "locked": True}
        if "enabled" in settings:
            SandboxManager._settings["enabled"] = bool(settings.get("enabled"))
        return {"ok": True, "locked": False}

    @staticmethod
    def is_auto_allow_bash_if_sandboxed_enabled() -> bool:
        return os.environ.get("CORTEX_SANDBOX_AUTO_ALLOW_BASH", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def get_fs_read_config() -> Dict[str, Any]:
        return {"denyOnly": [], "allowWithinDeny": []}

    @staticmethod
    def get_fs_write_config() -> Dict[str, Any]:
        return {"allowOnly": [], "denyWithinAllow": []}

    @staticmethod
    def get_network_restriction_config() -> Optional[Dict[str, Any]]:
        return None

    @staticmethod
    def get_allow_unix_sockets() -> Optional[List[str]]:
        return None

    @staticmethod
    def get_ignore_violations() -> Optional[List[str]]:
        return None

    @staticmethod
    def are_unsandboxed_commands_allowed() -> bool:
        # Keep permissive default to avoid command regressions.
        return True

    @staticmethod
    async def wrap_with_sandbox(command: str, *_args, **_kwargs) -> str:
        # No runtime wrapper yet; return the original command.
        return command

    # camelCase compatibility methods used by older translated modules
    @staticmethod
    def isSandboxingEnabled() -> bool:
        return SandboxManager.is_sandboxing_enabled()

    @staticmethod
    def isAutoAllowBashIfSandboxedEnabled() -> bool:
        return SandboxManager.is_auto_allow_bash_if_sandboxed_enabled()

    @staticmethod
    async def setSandboxSettings(settings: Dict[str, Any]) -> Dict[str, Any]:
        return await SandboxManager.set_sandbox_settings(settings)


__all__ = ["SandboxManager"]

