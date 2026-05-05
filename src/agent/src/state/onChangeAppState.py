"""
onChangeAppState - State change observer for app state synchronization.

Handles permission mode sync, model settings persistence, UI state persistence,
and auth cache clearing when app state changes.

Converted from TypeScript: state/onChangeAppState.ts
"""

import os
from typing import Any, Callable, Dict, Optional

# Defensive imports for state management
try:
    from ..bootstrap.state import set_main_loop_model_override
except ImportError:
    def set_main_loop_model_override(model: Optional[str]) -> None:
        """Fallback: no-op"""
        pass

try:
    from ..utils.auth import (
        clear_api_key_helper_cache,
        clear_aws_credentials_cache,
        clear_gcp_credentials_cache,
    )
except ImportError:
    def clear_api_key_helper_cache() -> None:
        pass
    def clear_aws_credentials_cache() -> None:
        pass
    def clear_gcp_credentials_cache() -> None:
        pass

try:
    from ..utils.config import get_global_config, save_global_config
except ImportError:
    def get_global_config() -> Dict[str, Any]:
        return {}
    def save_global_config(updater: Callable) -> None:
        pass

try:
    from ..utils.errors import to_error
except ImportError:
    def to_error(error: Any) -> Exception:
        return error if isinstance(error, Exception) else Exception(str(error))

try:
    from ..utils.log import log_error
except ImportError:
    def log_error(error: Exception) -> None:
        pass

try:
    from ..utils.managed_env import apply_config_environment_variables
except ImportError:
    def apply_config_environment_variables() -> None:
        pass

try:
    from ..utils.permissions.PermissionMode import (
        permission_mode_from_string,
        to_external_permission_mode,
    )
except ImportError:
    def permission_mode_from_string(mode: str) -> str:
        return mode
    def to_external_permission_mode(mode: str) -> str:
        return mode

try:
    from ..utils.sessionState import (
        notify_permission_mode_changed,
        notify_session_metadata_changed,
    )
except ImportError:
    def notify_permission_mode_changed(mode: str) -> None:
        pass
    def notify_session_metadata_changed(metadata: Dict[str, Any]) -> None:
        pass

try:
    from ..utils.settings.settings import update_settings_for_source
except ImportError:
    def update_settings_for_source(source: str, updates: Dict[str, Any]) -> None:
        pass


# Type aliases for clarity
AppState = Dict[str, Any]
SessionExternalMetadata = Dict[str, Any]


def external_metadata_to_app_state(
    metadata: SessionExternalMetadata,
) -> Callable[[AppState], AppState]:
    """
    Convert external session metadata to app state updater.
    
    Inverse of the push to external metadata — restore on worker restart.
    
    Args:
        metadata: External session metadata with permission_mode and is_ultraplan_mode
        
    Returns:
        Function that updates AppState from metadata
    """
    def updater(prev: AppState) -> AppState:
        updated = {**prev}
        
        # Apply permission mode if present
        if 'permission_mode' in metadata and isinstance(metadata['permission_mode'], str):
            updated['toolPermissionContext'] = {
                **prev.get('toolPermissionContext', {}),
                'mode': permission_mode_from_string(metadata['permission_mode']),
            }
        
        # Apply ultraplan mode if present
        if 'is_ultraplan_mode' in metadata and isinstance(metadata['is_ultraplan_mode'], bool):
            updated['isUltraplanMode'] = metadata['is_ultraplan_mode']
        
        return updated
    
    return updater


def on_change_app_state(
    new_state: AppState,
    old_state: AppState,
) -> None:
    """
    React to app state changes and trigger side effects.
    
    This is the central choke point for state change notifications:
    - Permission mode sync to CCR/SDK
    - Model settings persistence
    - UI state persistence
    - Auth cache clearing
    
    Args:
        new_state: New app state
        old_state: Previous app state
    """
    # =========================================================================
    # Permission Mode Sync
    # =========================================================================
    # Single choke point for CCR/SDK mode sync.
    #
    # Prior to this block, mode changes were relayed to CCR by only 2 of 8+
    # mutation paths. Every other path mutated AppState without telling CCR,
    # leaving external_metadata.permission_mode stale.
    #
    # Hooking the diff here means ANY setAppState call that changes the mode
    # notifies CCR and the SDK status stream.
    
    prev_mode = old_state.get('toolPermissionContext', {}).get('mode')
    new_mode = new_state.get('toolPermissionContext', {}).get('mode')
    
    if prev_mode != new_mode:
        # CCR external_metadata must not receive internal-only mode names
        # (bubble, ungated auto). Externalize first.
        prev_external = to_external_permission_mode(prev_mode)
        new_external = to_external_permission_mode(new_mode)
        
        if prev_external != new_external:
            # Ultraplan = first plan cycle only. The initial control_request
            # sets mode and isUltraplanMode atomically.
            is_ultraplan = (
                True
                if (
                    new_external == 'plan'
                    and new_state.get('isUltraplanMode')
                    and not old_state.get('isUltraplanMode')
                )
                else None  # null per RFC 7396 (removes the key)
            )
            
            notify_session_metadata_changed({
                'permission_mode': new_external,
                'is_ultraplan_mode': is_ultraplan,
            })
        
        notify_permission_mode_changed(new_mode)
    
    # =========================================================================
    # Model Settings Persistence
    # =========================================================================
    
    # mainLoopModel: remove it from settings?
    if (
        new_state.get('mainLoopModel') != old_state.get('mainLoopModel')
        and new_state.get('mainLoopModel') is None
    ):
        # Remove from settings
        update_settings_for_source('userSettings', {'model': None})
        set_main_loop_model_override(None)
    
    # mainLoopModel: add it to settings?
    if (
        new_state.get('mainLoopModel') != old_state.get('mainLoopModel')
        and new_state.get('mainLoopModel') is not None
    ):
        # Save to settings
        update_settings_for_source(
            'userSettings',
            {'model': new_state['mainLoopModel']},
        )
        set_main_loop_model_override(new_state['mainLoopModel'])
    
    # =========================================================================
    # UI State Persistence
    # =========================================================================
    
    # expandedView → persist as showExpandedTodos + showSpinnerTree
    if new_state.get('expandedView') != old_state.get('expandedView'):
        show_expanded_todos = new_state.get('expandedView') == 'tasks'
        show_spinner_tree = new_state.get('expandedView') == 'teammates'
        
        current_config = get_global_config()
        if (
            current_config.get('showExpandedTodos') != show_expanded_todos
            or current_config.get('showSpinnerTree') != show_spinner_tree
        ):
            def update_expanded_view(current: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    **current,
                    'showExpandedTodos': show_expanded_todos,
                    'showSpinnerTree': show_spinner_tree,
                }
            
            save_global_config(update_expanded_view)
    
    # verbose
    if (
        new_state.get('verbose') != old_state.get('verbose')
        and get_global_config().get('verbose') != new_state.get('verbose')
    ):
        verbose = new_state.get('verbose', False)
        
        def update_verbose(current: Dict[str, Any]) -> Dict[str, Any]:
            return {**current, 'verbose': verbose}
        
        save_global_config(update_verbose)
    
    # tungstenPanelVisible (ant-only tmux panel sticky toggle)
    if os.environ.get('USER_TYPE') == 'ant':
        if (
            new_state.get('tungstenPanelVisible') != old_state.get('tungstenPanelVisible')
            and new_state.get('tungstenPanelVisible') is not None
            and get_global_config().get('tungstenPanelVisible') != new_state.get('tungstenPanelVisible')
        ):
            tungsten_visible = new_state['tungstenPanelVisible']
            
            def update_tungsten(current: Dict[str, Any]) -> Dict[str, Any]:
                return {**current, 'tungstenPanelVisible': tungsten_visible}
            
            save_global_config(update_tungsten)
    
    # =========================================================================
    # Auth Cache Management
    # =========================================================================
    
    # Clear auth-related caches when settings change
    # This ensures apiKeyHelper and AWS/GCP credential changes take effect immediately
    if new_state.get('settings') != old_state.get('settings'):
        try:
            clear_api_key_helper_cache()
            clear_aws_credentials_cache()
            clear_gcp_credentials_cache()
            
            # Re-apply environment variables when settings.env changes
            # This is additive-only: new vars are added, existing may be overwritten
            old_settings = old_state.get('settings', {})
            new_settings = new_state.get('settings', {})
            
            if isinstance(old_settings, dict) and isinstance(new_settings, dict):
                if old_settings.get('env') != new_settings.get('env'):
                    apply_config_environment_variables()
        except Exception as error:
            log_error(to_error(error))
