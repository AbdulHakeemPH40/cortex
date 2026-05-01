"""
Bash shell provider for Cortex IDE.

Provides bash command execution via asyncio subprocess.
Wraps commands with bash -lc for login shell behavior.
"""

from __future__ import annotations

import shutil
from typing import List, Optional

from .shellProvider import ShellProvider


class BashProvider(ShellProvider):
    """Bash shell execution provider."""

    name = "bash"

    def __init__(self) -> None:
        self._bash_path: Optional[str] = None

    async def is_available(self) -> bool:
        path = self.get_shell_path()
        return path is not None

    def get_shell_path(self) -> Optional[str]:
        if self._bash_path is None:
            self._bash_path = shutil.which("bash")
        return self._bash_path

    def _shell_args(self) -> List[str]:
        return ["-lc"]


# Singleton instance
bash_provider = BashProvider()


__all__ = ["BashProvider", "bash_provider"]
