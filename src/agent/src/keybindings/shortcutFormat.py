"""
Auto-converted from shortcutFormat.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


# Type definition
class KeybindingContextName(str, Enum):
    """Keybinding context names."""
    GLOBAL = "global"
    EDITOR = "editor"
    TERMINAL = "terminal"


def getShortcutDisplay(action: str, context: KeybindingContextName, fallback: str) -> str:
    """Get shortcut display for an action."""
    # TODO: Implement actual shortcut lookup
    return fallback



__all__ = ['getShortcutDisplay']