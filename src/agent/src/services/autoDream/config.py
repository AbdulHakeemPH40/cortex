"""
Leaf config module — intentionally minimal imports so UI components
can read the auto-dream enabled state without dragging in the forked
agent / task registry / message builder chain that autoDream.py pulls in.
"""

from typing import Any, Optional, Dict

from ...utils.settings.settings import get_initial_settings


def is_auto_dream_enabled() -> bool:
    """
    Whether background memory consolidation should run. User setting
    (auto_dream_enabled in settings.json) overrides the GrowthBook default
    when explicitly set; otherwise falls through to tengu_onyx_plover.
    
    Returns:
        True if auto-dream (background memory consolidation) is enabled
    """
    setting = get_initial_settings().auto_dream_enabled
    if setting is not None:
        return setting
    
    gb = get_feature_value_cached_may_be_stale[Optional[Dict[str, Any]]](
        'tengu_onyx_plover',
        None,
    )
    return gb is not None and gb.get('enabled') is True
