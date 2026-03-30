"""
Permission System for Cortex AI Agent
Combines evaluator-based and card-based permission systems
"""

# Existing permission evaluator
from .evaluator import (
    PermissionEvaluator,
    PermissionSchema,
    PermissionRule,
    PermissionLevel,
    ToolArity,
    ToolCategory,
    get_permission_evaluator
)

# New permission manager with cards
from .types import (
    PermissionType,
    PermissionScope,
    PermissionStatus,
    PermissionRequest,
    PermissionGrant,
    PermissionCheckResult,
    PermissionCardData,
    CommandAnalysis,
    CommandSafety,
    PERMISSION_CARD_CONFIGS,
)

from .manager import (
    PermissionManager,
    get_permission_manager,
)

__all__ = [
    # Existing
    'PermissionEvaluator',
    'PermissionSchema',
    'PermissionRule',
    'PermissionLevel',
    'ToolArity',
    'ToolCategory',
    'get_permission_evaluator',
    # New
    'PermissionType',
    'PermissionScope',
    'PermissionStatus',
    'PermissionRequest',
    'PermissionGrant',
    'PermissionCheckResult',
    'PermissionCardData',
    'CommandAnalysis',
    'CommandSafety',
    'PERMISSION_CARD_CONFIGS',
    'PermissionManager',
    'get_permission_manager',
]
