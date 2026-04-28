"""
Application state management for Cortex CLI.

Manages global state including session ID, additional directories,
and other runtime configuration.
"""
from typing import List, Optional
from uuid import uuid4


# Global state storage
class _AppState:
    """Internal application state."""
    
    def __init__(self) -> None:
        self.session_id: str = str(uuid4())
        self.session_project_dir: Optional[str] = None
        self.additional_directories_for_cortex_md: List[str] = []


STATE = _AppState()


def getSessionId() -> str:
    """
    Get the current session ID.
    
    Returns:
        Current session UUID string
    """
    return STATE.session_id


def regenerateSessionId(set_current_as_parent: bool = False) -> str:
    """
    Regenerate the session ID.
    
    Args:
        set_current_as_parent: If True, save current session as parent
        
    Returns:
        New session UUID string
    """
    # In full implementation, would handle parent session
    STATE.session_id = str(uuid4())
    STATE.session_project_dir = None
    return STATE.session_id


def getAdditionalDirectoriesForCortexMd() -> List[str]:
    """
    Get additional directories for CORTEX.md loading.
    
    These are directories specified via --add-dir flag or /add-dir command.
    
    Returns:
        List of directory paths
    """
    return STATE.additional_directories_for_cortex_md


def setAdditionalDirectoriesForCortexMd(directories: List[str]) -> None:
    """
    Set additional directories for CORTEX.md loading.
    
    Args:
        directories: List of directory paths
    """
    STATE.additional_directories_for_cortex_md = directories

