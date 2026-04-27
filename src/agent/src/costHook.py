# ------------------------------------------------------------
# cost_hook.py
# Python conversion of costHook.ts (lines 1-23)
# 
# Cost summary display hook for application shutdown.
# Displays total cost on exit and saves session costs.
# Note: This was originally a React useEffect hook, converted
# to a simple initialization function for PyQt6.
# ------------------------------------------------------------

import atexit
import sys
from typing import Callable, Optional


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from .cost_tracker import format_total_cost, save_current_session_costs
except ImportError:
    def format_total_cost() -> str:
        return ""
    
    def save_current_session_costs(fps_metrics=None) -> None:
        pass

try:
    from .utils.billing import has_console_billing_access
except ImportError:
    def has_console_billing_access() -> bool:
        return False

try:
    from .utils.fps_tracker import FpsMetrics
except ImportError:
    class FpsMetrics:
        """Type placeholder for FPS metrics."""
        pass


# ============================================================
# COST SUMMARY HOOK
# ============================================================

def use_cost_summary(get_fps_metrics: Optional[Callable[[], Optional[FpsMetrics]]] = None) -> None:
    """
    Register cost summary display on application exit.
    
    Originally a React useEffect hook, this function registers
    an exit handler that:
    1. Displays total cost if user has console billing access
    2. Saves current session costs to project config
    
    For PyQt6 applications, call this once during initialization.
    
    Args:
        get_fps_metrics: Optional function that returns current FPS metrics
    """
    def on_exit():
        """Exit handler that displays cost and saves session."""
        if has_console_billing_access():
            # Display cost summary to stdout
            sys.stdout.write('\n' + format_total_cost() + '\n')
        
        # Save session costs (with optional FPS metrics)
        fps_metrics = get_fps_metrics() if get_fps_metrics else None
        save_current_session_costs(fps_metrics)
    
    # Register exit handler using atexit module
    atexit.register(on_exit)


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "use_cost_summary",
]
