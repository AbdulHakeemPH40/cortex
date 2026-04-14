"""
AppState - Application state management stub
This was originally a React context provider in TypeScript.
For Python integration, this provides a simple state container.
"""

from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class AppState:
    """Simple application state container for Python bridge."""
    
    # Tool permissions
    permission_mode: str = "auto"  # auto, accept-all, deny-all
    bypass_permissions: bool = False
    
    # Session info
    session_id: Optional[str] = None
    cwd: str = ""
    
    # Model settings
    model: str = "claude-sonnet-4-20250514"
    
    # Conversation state
    messages: list = field(default_factory=list)
    
    # Tool context
    tool_permission_context: Dict[str, Any] = field(default_factory=dict)
    
    # Speculation state
    speculation: Dict[str, Any] = field(default_factory=dict)
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


# Type alias for state updater function
StateUpdater = Callable[[AppState], AppState]


class AppStateStore:
    """Simple state store for Python bridge."""
    
    _instance: Optional['AppStateStore'] = None
    _state: AppState = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._state = AppState()
        return cls._instance
    
    @classmethod
    def get_state(cls) -> AppState:
        return cls._state
    
    @classmethod
    def set_state(cls, updater: StateUpdater) -> None:
        cls._state = updater(cls._state)


# Convenience functions
def use_app_state(selector: Callable[[AppState], Any] = None) -> Any:
    """Get current app state or a selected portion."""
    state = AppStateStore.get_state()
    return selector(state) if selector else state


def use_set_app_state() -> Callable[[StateUpdater], None]:
    """Get state setter function."""
    return AppStateStore.set_state
