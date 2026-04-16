# ------------------------------------------------------------
# projectOnboardingState.py
# Python conversion of projectOnboardingState.ts (lines 1-84)
# 
# Project onboarding state management including:
# - Onboarding step tracking (workspace setup, CLAUDE.md creation)
# - Completion detection with filesystem checks
# - Memoized visibility logic to avoid redundant FS calls
# - Seen count tracking to limit onboarding display frequency
# ------------------------------------------------------------

import os
from functools import lru_cache
from typing import List


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from .utils.config import get_current_project_config, save_current_project_config
except ImportError:
    def get_current_project_config():
        return {
            'hasCompletedProjectOnboarding': False,
            'projectOnboardingSeenCount': 0,
        }
    
    def save_current_project_config(updater):
        pass

try:
    from .utils.cwd import get_cwd
except ImportError:
    def get_cwd() -> str:
        return os.getcwd()

try:
    from .utils.file import is_dir_empty
except ImportError:
    def is_dir_empty(path: str) -> bool:
        if not os.path.exists(path):
            return True
        try:
            return len(os.listdir(path)) == 0
        except OSError:
            return True

try:
    from .utils.fs_operations import get_fs_implementation
except ImportError:
    class FsImplementation:
        @staticmethod
        def exists_sync(path: str) -> bool:
            return os.path.exists(path)
    
    def get_fs_implementation():
        return FsImplementation()


# ============================================================
# TYPE DEFINITIONS
# ============================================================

class Step:
    """Represents an onboarding step."""
    
    def __init__(
        self,
        key: str,
        text: str,
        is_complete: bool,
        is_completable: bool,
        is_enabled: bool,
    ):
        self.key = key
        self.text = text
        self.is_complete = is_complete
        self.is_completable = is_completable
        self.is_enabled = is_enabled
    
    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            'key': self.key,
            'text': self.text,
            'isComplete': self.is_complete,
            'isCompletable': self.is_completable,
            'isEnabled': self.is_enabled,
        }


# ============================================================
# ONBOARDING STEP MANAGEMENT
# ============================================================

def get_steps() -> List[Step]:
    """
    Get the list of onboarding steps with their current completion status.
    
    Checks filesystem for:
    - Whether workspace directory is empty
    - Whether CLAUDE.md file exists
    
    Returns:
        List of Step objects representing onboarding progress
    """
    fs = get_fs_implementation()
    cwd = get_cwd()
    
    has_claude_md = fs.exists_sync(os.path.join(cwd, 'CLAUDE.md'))
    is_workspace_dir_empty = is_dir_empty(cwd)
    
    return [
        Step(
            key='workspace',
            text='Ask Claude to create a new app or clone a repository',
            is_complete=False,
            is_completable=True,
            is_enabled=is_workspace_dir_empty,
        ),
        Step(
            key='claudemd',
            text='Run /init to create a CLAUDE.md file with instructions for Claude',
            is_complete=has_claude_md,
            is_completable=True,
            is_enabled=not is_workspace_dir_empty,
        ),
    ]


def is_project_onboarding_complete() -> bool:
    """
    Check if all completable and enabled onboarding steps are complete.
    
    Returns:
        True if all relevant steps are complete, False otherwise
    """
    steps = get_steps()
    
    # Filter to only completable and enabled steps
    relevant_steps = [
        step for step in steps
        if step.is_completable and step.is_enabled
    ]
    
    # All relevant steps must be complete
    return all(step.is_complete for step in relevant_steps)


def maybe_mark_project_onboarding_complete() -> None:
    """
    Mark project onboarding as complete if all steps are done.
    
    Short-circuits on cached config — is_project_onboarding_complete() hits
    the filesystem, and this may be called frequently (e.g., on every prompt submit).
    """
    project_config = get_current_project_config()
    
    # Short-circuit if already marked complete
    if project_config.get('hasCompletedProjectOnboarding'):
        return
    
    # Check if onboarding is actually complete
    if is_project_onboarding_complete():
        save_current_project_config(lambda current: {
            **current,
            'hasCompletedProjectOnboarding': True,
        })


# ============================================================
# MEMOIZED VISIBILITY CHECK
# ============================================================

@lru_cache(maxsize=1)
def should_show_project_onboarding() -> bool:
    """
    Determine if project onboarding should be shown to the user.
    
    Memoized to avoid redundant filesystem calls during first render.
    Short-circuits on cached config before checking filesystem.
    
    Returns:
        True if onboarding should be displayed, False otherwise
    
    Conditions that hide onboarding:
    - Already completed
    - Seen 4+ times (user dismissed it repeatedly)
    - Running in demo mode (IS_DEMO env var set)
    - All steps are complete
    """
    project_config = get_current_project_config()
    
    # Short-circuit on cached config before filesystem check
    if (project_config.get('hasCompletedProjectOnboarding') or
        project_config.get('projectOnboardingSeenCount', 0) >= 4 or
        os.environ.get('IS_DEMO')):
        return False
    
    return not is_project_onboarding_complete()


def increment_project_onboarding_seen_count() -> None:
    """
    Increment the counter tracking how many times onboarding has been shown.
    
    Used to limit onboarding display frequency — after 4 views, it stops showing.
    """
    save_current_project_config(lambda current: {
        **current,
        'projectOnboardingSeenCount': current.get('projectOnboardingSeenCount', 0) + 1,
    })


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "Step",
    "get_steps",
    "is_project_onboarding_complete",
    "maybe_mark_project_onboarding_complete",
    "should_show_project_onboarding",
    "increment_project_onboarding_seen_count",
]
