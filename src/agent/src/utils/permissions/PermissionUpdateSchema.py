"""
Permission update schemas for Cortex AI Agent IDE.

Zod schemas converted to Pydantic models for permission updates.
This file is intentionally minimal with no complex dependencies
to avoid circular imports.

Multi-LLM Support: Works with all providers as it's provider-agnostic
permission update types.
"""

from typing import Literal, Union
from pydantic import BaseModel

from .PermissionRule import (
    PermissionBehavior,
    PermissionRuleValue,
)


# ============================================================================
# Type Definitions
# ============================================================================

PermissionUpdateDestination = Literal[
    'userSettings',    # User settings (global)
    'projectSettings', # Project settings (shared per-directory)
    'localSettings',   # Local settings (gitignored)
    'session',         # In-memory for current session only
    'cliArg',          # From command line arguments
]


# ============================================================================
# Permission Update Models (Discriminated Union)
# ============================================================================

class PermissionUpdateAddRules(BaseModel):
    """Permission update to add rules."""
    
    type: Literal['addRules']
    rules: list[PermissionRuleValue]
    behavior: PermissionBehavior
    destination: PermissionUpdateDestination


class PermissionUpdateReplaceRules(BaseModel):
    """Permission update to replace all rules for a destination."""
    
    type: Literal['replaceRules']
    rules: list[PermissionRuleValue]
    behavior: PermissionBehavior
    destination: PermissionUpdateDestination


class PermissionUpdateRemoveRules(BaseModel):
    """Permission update to remove rules."""
    
    type: Literal['removeRules']
    rules: list[PermissionRuleValue]
    behavior: PermissionBehavior
    destination: PermissionUpdateDestination


class PermissionUpdateSetMode(BaseModel):
    """Permission update to set permission mode."""
    
    type: Literal['setMode']
    mode: PermissionMode
    destination: PermissionUpdateDestination


class PermissionUpdateAddDirectories(BaseModel):
    """Permission update to add working directories."""
    
    type: Literal['addDirectories']
    directories: list[str]
    destination: PermissionUpdateDestination


class PermissionUpdateRemoveDirectories(BaseModel):
    """Permission update to remove working directories."""
    
    type: Literal['removeDirectories']
    directories: list[str]
    destination: PermissionUpdateDestination


# Discriminated union of all update types
PermissionUpdate = Union[
    PermissionUpdateAddRules,
    PermissionUpdateReplaceRules,
    PermissionUpdateRemoveRules,
    PermissionUpdateSetMode,
    PermissionUpdateAddDirectories,
    PermissionUpdateRemoveDirectories,
]


# ============================================================================
# Exported Symbols
# ============================================================================

__all__ = [
    'PermissionUpdateDestination',
    'PermissionUpdate',
    'PermissionUpdateAddRules',
    'PermissionUpdateReplaceRules',
    'PermissionUpdateRemoveRules',
    'PermissionUpdateSetMode',
    'PermissionUpdateAddDirectories',
    'PermissionUpdateRemoveDirectories',
]
