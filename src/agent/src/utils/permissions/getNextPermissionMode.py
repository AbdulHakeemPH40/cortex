"""
Permission mode cycling system for Cortex AI Agent IDE.

Manages cycling through permission modes (Shift+Tab) and handles context
transitions between modes. Provides user control over AI agent permission levels.

Multi-LLM Support: Works with all providers (Anthropic, OpenAI, Gemini, DeepSeek,
Mistral, Groq, Ollama, SiliconFlow) as it's provider-agnostic permission logic.

Permission Modes:
- default: AI asks for permission for each action
- acceptEdits: AI can edit files without asking each time
- plan: AI creates plans before executing actions
- auto: AI runs autonomously with safety checks (requires gate approval)
- bypassPermissions: All permissions granted (power user mode)

Example:
    >>> from permission_mode import cycle_permission_mode
    >>> context = {'mode': 'default', 'auto_mode_available': True}
    >>> result = cycle_permission_mode(context)
    >>> result['next_mode']
    'acceptEdits'
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# Permission Mode Type Definitions
# ============================================================================

# Available permission modes in Cortex IDE
PermissionMode = str

# Valid permission modes
VALID_PERMISSION_MODES: list[PermissionMode] = [
    'default',              # Ask for permission for each action
    'acceptEdits',          # Auto-accept file edits
    'plan',                 # Create plans before executing
    'auto',                 # Autonomous mode with safety checks
    'bypassPermissions',    # All permissions granted (power user)
]

# Mode display names for UI
MODE_DISPLAY_NAMES: dict[PermissionMode, str] = {
    'default': 'Default (Ask)',
    'acceptEdits': 'Accept Edits',
    'plan': 'Plan Mode',
    'auto': 'Auto Mode',
    'bypassPermissions': 'Bypass Permissions',
}

# Mode descriptions for tooltips
MODE_DESCRIPTIONS: dict[PermissionMode, str] = {
    'default': 'AI asks for permission before each action',
    'acceptEdits': 'AI can edit files without asking',
    'plan': 'AI creates plans before executing',
    'auto': 'AI runs autonomously with safety checks',
    'bypassPermissions': 'All permissions granted (use with caution)',
}


# ============================================================================
# Auto Mode Gate Configuration
# ============================================================================

# Auto mode availability configuration
# In production, this would be set based on user settings and feature flags
AUTO_MODE_CONFIG = {
    'enabled': True,           # Whether auto mode is available
    'requires_approval': True, # Whether user needs to approve auto mode
    'safety_checks': True,     # Whether safety checks are enforced in auto mode
}


def is_auto_mode_available(context: dict[str, Any]) -> bool:
    """
    Check if auto mode is available for the current context.
    
    In Claude Code, this checks feature gates and cached availability.
    For Cortex IDE, we check local configuration and context flags.
    
    Args:
        context: Tool permission context with auto_mode_available flag
        
    Returns:
        True if auto mode can be used
    """
    # Check if auto mode is enabled in configuration
    if not AUTO_MODE_CONFIG.get('enabled', False):
        logger.debug('[auto-mode] Auto mode disabled in configuration')
        return False
    
    # Check context flag (set at startup based on user settings/permissions)
    if not context.get('auto_mode_available', False):
        logger.debug('[auto-mode] Auto mode not available in context')
        return False
    
    # All checks passed
    return True


def get_auto_mode_unavailable_reason() -> str:
    """
    Get reason why auto mode is unavailable.
    
    Returns:
        Human-readable reason string
    """
    if not AUTO_MODE_CONFIG.get('enabled', False):
        return 'Auto mode is disabled in configuration'
    
    return 'Auto mode is not available (check user settings)'


# ============================================================================
# Mode Cycling Logic
# ============================================================================

def get_next_permission_mode(context: dict[str, Any]) -> PermissionMode:
    """
    Determines the next permission mode when cycling through modes.
    
    Mode cycle order:
    default → acceptEdits → plan → bypassPermissions → auto → default
    
    Args:
        context: Tool permission context with:
            - mode: Current permission mode
            - auto_mode_available: Whether auto mode is available
            - bypass_permissions_available: Whether bypass mode is available
        
    Returns:
        Next permission mode in the cycle
        
    Example:
        >>> get_next_permission_mode({'mode': 'default'})
        'acceptEdits'
        >>> get_next_permission_mode({'mode': 'plan', 'auto_mode_available': True})
        'auto'
    """
    current_mode = context.get('mode', 'default')
    
    if current_mode == 'default':
        # From default, go to acceptEdits
        return 'acceptEdits'
    
    elif current_mode == 'acceptEdits':
        # From acceptEdits, go to plan
        return 'plan'
    
    elif current_mode == 'plan':
        # From plan, try bypassPermissions or auto, then default
        if context.get('bypass_permissions_available', False):
            return 'bypassPermissions'
        if is_auto_mode_available(context):
            return 'auto'
        return 'default'
    
    elif current_mode == 'bypassPermissions':
        # From bypassPermissions, try auto, then default
        if is_auto_mode_available(context):
            return 'auto'
        return 'default'
    
    elif current_mode == 'auto':
        # From auto, go back to default
        return 'default'
    
    elif current_mode == 'dontAsk':
        # Legacy mode, return to default
        return 'default'
    
    else:
        # Unknown mode, fall back to default
        logger.warning(f'[permission-mode] Unknown mode: {current_mode}, falling back to default')
        return 'default'


def get_mode_cycle_order(context: dict[str, Any] | None = None) -> list[PermissionMode]:
    """
    Get the full cycle order of permission modes.
    
    Args:
        context: Optional context to filter available modes
        
    Returns:
        List of modes in cycle order
    """
    if context is None:
        context = {'auto_mode_available': True, 'bypass_permissions_available': True}
    
    modes = ['default', 'acceptEdits', 'plan']
    
    if context.get('bypass_permissions_available', False):
        modes.append('bypassPermissions')
    
    if is_auto_mode_available(context):
        modes.append('auto')
    
    return modes


# ============================================================================
# Context Transition Logic
# ============================================================================

def transition_permission_mode(
    from_mode: PermissionMode,
    to_mode: PermissionMode,
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    Transition from one permission mode to another, updating context as needed.
    
    Handles context cleanup when entering stricter modes:
    - Strips dangerous permissions when entering auto mode
    - Resets approval caches when changing modes
    - Updates mode-specific flags
    
    Args:
        from_mode: Current permission mode
        to_mode: Target permission mode
        context: Current tool permission context
        
    Returns:
        Updated context for the new mode
    """
    # Create a copy to avoid mutating the original
    new_context = context.copy()
    
    # Update the mode
    new_context['mode'] = to_mode
    
    # Handle mode-specific transitions
    if to_mode == 'auto':
        # Entering auto mode: strip dangerous permissions
        new_context = _prepare_for_auto_mode(new_context)
        logger.info('[permission-mode] Transitioned to auto mode (dangerous permissions stripped)')
    
    elif to_mode == 'bypassPermissions':
        # Entering bypass mode: all permissions granted
        new_context['all_permissions_granted'] = True
        logger.info('[permission-mode] Transitioned to bypass permissions mode')
    
    elif to_mode == 'plan':
        # Entering plan mode: disable automatic execution
        new_context['auto_execute'] = False
        logger.info('[permission-mode] Transitioned to plan mode')
    
    elif to_mode == 'acceptEdits':
        # Entering acceptEdits mode: allow file edits
        new_context['auto_accept_edits'] = True
        logger.info('[permission-mode] Transitioned to acceptEdits mode')
    
    elif to_mode == 'default':
        # Returning to default: reset all flags
        new_context['auto_accept_edits'] = False
        new_context['auto_execute'] = False
        new_context['all_permissions_granted'] = False
        new_context['in_auto_mode'] = False
        new_context['safety_checks_enabled'] = False
        logger.info('[permission-mode] Transitioned to default mode')
    
    return new_context


def _prepare_for_auto_mode(context: dict[str, Any]) -> dict[str, Any]:
    """
    Prepare context for auto mode by stripping dangerous permissions.
    
    Auto mode requires enhanced safety checks, so we remove any permissions
    that could be dangerous for autonomous execution.
    
    Args:
        context: Current tool permission context
        
    Returns:
        Context with dangerous permissions stripped
    """
    new_context = context.copy()
    
    # Strip dangerous permission flags
    new_context['all_permissions_granted'] = False
    
    # Enable safety checks for auto mode
    new_context['safety_checks_enabled'] = AUTO_MODE_CONFIG.get('safety_checks', True)
    
    # Mark that we're in auto mode
    new_context['in_auto_mode'] = True
    
    return new_context


def cycle_permission_mode(context: dict[str, Any]) -> dict[str, Any]:
    """
    Computes the next permission mode and prepares the context for it.
    
    This is the main entry point for mode cycling (e.g., Shift+Tab in UI).
    Handles both mode determination and context transition.
    
    Args:
        context: Current tool permission context with:
            - mode: Current permission mode
            - auto_mode_available: Whether auto mode is available
            - bypass_permissions_available: Whether bypass mode is available
        
    Returns:
        Dictionary with:
        - next_mode: The next permission mode
        - context: Updated context for the new mode
        - transition_info: Information about the transition
        
    Example:
        >>> context = {'mode': 'default', 'auto_mode_available': True}
        >>> result = cycle_permission_mode(context)
        >>> result['next_mode']
        'acceptEdits'
        >>> result['context']['mode']
        'acceptEdits'
    """
    current_mode = context.get('mode', 'default')
    
    # Determine next mode
    next_mode = get_next_permission_mode(context)
    
    # Transition context to new mode
    new_context = transition_permission_mode(current_mode, next_mode, context)
    
    # Log the transition
    logger.info(f'[permission-mode] Cycle: {current_mode} → {next_mode}')
    
    return {
        'next_mode': next_mode,
        'context': new_context,
        'transition_info': {
            'from_mode': current_mode,
            'to_mode': next_mode,
            'auto_mode_available': is_auto_mode_available(context),
        },
    }


# ============================================================================
# Utility Functions for UI Integration
# ============================================================================

def get_mode_info(mode: PermissionMode) -> dict[str, Any]:
    """
    Get comprehensive information about a permission mode.
    
    Useful for UI display (tooltips, status bars, mode indicators).
    
    Args:
        mode: Permission mode to get info for
        
    Returns:
        Dictionary with mode information
    """
    return {
        'mode': mode,
        'display_name': MODE_DISPLAY_NAMES.get(mode, mode),
        'description': MODE_DESCRIPTIONS.get(mode, ''),
        'icon': _get_mode_icon(mode),
        'color': _get_mode_color(mode),
    }


def _get_mode_icon(mode: PermissionMode) -> str:
    """Get icon identifier for mode (for PyQt6 UI)."""
    icons = {
        'default': '🔒',
        'acceptEdits': '✏️',
        'plan': '📋',
        'auto': '🤖',
        'bypassPermissions': '⚠️',
    }
    return icons.get(mode, '❓')


def _get_mode_color(mode: PermissionMode) -> str:
    """Get color hex code for mode (for PyQt6 UI)."""
    colors = {
        'default': '#808080',        # Gray
        'acceptEdits': '#4CAF50',    # Green
        'plan': '#2196F3',          # Blue
        'auto': '#9C27B0',          # Purple
        'bypassPermissions': '#FF5722',  # Orange/Red
    }
    return colors.get(mode, '#000000')


def get_all_modes_info() -> list[dict[str, Any]]:
    """
    Get information about all available permission modes.
    
    Returns:
        List of mode information dictionaries
    """
    return [get_mode_info(mode) for mode in VALID_PERMISSION_MODES]


def update_auto_mode_config(config: dict[str, Any]) -> None:
    """
    Update auto mode configuration.
    
    Args:
        config: Configuration dictionary with:
            - enabled: Whether auto mode is available
            - requires_approval: Whether user needs to approve
            - safety_checks: Whether safety checks are enforced
    """
    global AUTO_MODE_CONFIG
    AUTO_MODE_CONFIG.update(config)
    logger.info(f'[auto-mode] Configuration updated: {AUTO_MODE_CONFIG}')


# Exported symbols
__all__ = [
    # Type definitions
    'PermissionMode',
    'VALID_PERMISSION_MODES',
    'MODE_DISPLAY_NAMES',
    'MODE_DESCRIPTIONS',
    
    # Auto mode configuration
    'AUTO_MODE_CONFIG',
    'is_auto_mode_available',
    'get_auto_mode_unavailable_reason',
    'update_auto_mode_config',
    
    # Mode cycling
    'get_next_permission_mode',
    'get_mode_cycle_order',
    'cycle_permission_mode',
    
    # Context transition
    'transition_permission_mode',
    
    # UI utilities
    'get_mode_info',
    'get_all_modes_info',
]
