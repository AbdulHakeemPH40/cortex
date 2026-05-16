"""
PowerShell shell provider for Cortex IDE.

Provides PowerShell command execution via asyncio subprocess.
Handles PowerShell discovery (pwsh vs powershell.exe) and edition detection.
"""

from __future__ import annotations

import os
import platform
import shutil
from typing import List, Optional

from .shellProvider import ShellProvider


class PowerShellProvider(ShellProvider):
    """PowerShell shell execution provider."""

    name = "powershell"

    def __init__(self) -> None:
        self._ps_path: Optional[str] = None
        self._edition: Optional[str] = None

    async def is_available(self) -> bool:
        if platform.system() != "Windows":
            return False
        path = self.get_shell_path()
        return path is not None

    def get_shell_path(self) -> Optional[str]:
        if self._ps_path is not None:
            return self._ps_path

        # Prefer pwsh (PowerShell Core) over powershell.exe (Windows PowerShell)
        self._ps_path = shutil.which("pwsh")
        if self._ps_path is None:
            self._ps_path = shutil.which("powershell")
        return self._ps_path

    def get_powershell_edition(self) -> Optional[str]:
        """Detect PowerShell edition: 'Core' (pwsh) or 'Desktop' (powershell.exe)."""
        if self._edition is not None:
            return self._edition

        path = self.get_shell_path()
        if path is None:
            return None

        basename = os.path.basename(path).lower()
        self._edition = "Core" if basename == "pwsh.exe" or basename == "pwsh" else "Desktop"
        return self._edition

    def _shell_args(self) -> List[str]:
        path = self.get_shell_path()
        if path and "pwsh" in os.path.basename(path).lower():
            return ["-NoProfile", "-Command"]
        return ["-NoProfile", "-Command"]


# Singleton instance
powershell_provider = PowerShellProvider()


__all__ = ["PowerShellProvider", "powershell_provider"]
