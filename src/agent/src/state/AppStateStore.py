"""
Auto-converted from AppStateStore.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class AppState:
    """Application state."""
    is_running: bool = False
    current_project: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)


def getDefaultAppState() -> AppState:
    """Get default application state."""
    return AppState()



__all__ = ['getDefaultAppState']