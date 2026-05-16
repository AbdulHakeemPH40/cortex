# ------------------------------------------------------------
# cost_tracker.py
# Python conversion of cost-tracker.ts (lines 1-324)
# 
# Cost tracking and usage metrics management including:
# - Session cost accumulation and persistence
# - Model usage tracking (tokens, cache, web search)
# - Cost calculation and formatting
# - FPS metrics integration
# - Advisor tool usage tracking
# - Project config save/restore for session resumption
# ------------------------------------------------------------

from typing import Any, Dict, Optional


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    import chalk
except ImportError:
    class chalk:
        """Stub for chalk library."""
        @staticmethod
        def dim(text: str) -> str:
            return text

try:
    from .bootstrap.state import (
        add_to_total_cost_state,
        add_to_total_lines_changed,
        get_cost_counter,
        get_model_usage,
        get_sdk_betas,
        get_session_id,
        get_token_counter,
        get_total_api_duration,
        get_total_api_duration_without_retries,
        get_total_cache_creation_input_tokens,
        get_total_cache_read_input_tokens,
        get_total_cost_usd,
        get_total_duration,
        get_total_input_tokens,
        get_total_lines_added,
        get_total_lines_removed,
        get_total_output_tokens,
        get_total_tool_duration,
        get_total_web_search_requests,
        get_usage_for_model,
        has_unknown_model_cost,
        reset_cost_state,
        reset_state_for_tests,
        set_cost_state_for_restore,
        set_has_unknown_model_cost,
    )
except ImportError:
    def add_to_total_cost_state(cost: float, model_usage: dict, model: str) -> None:
        pass
    
    def add_to_total_lines_changed(added: int, removed: int) -> None:
        pass
    
    def get_cost_counter():
        return None
    
    def get_model_usage() -> Dict[str, dict]:
        return {}
    
    def get_sdk_betas() -> list:
        return []
    
    def get_session_id() -> str:
        return "default-session"
    
    def get_token_counter():
        return None
    
    def get_total_api_duration() -> float:
        return 0.0
    
    def get_total_api_duration_without_retries() -> float:
        return 0.0
    
    def get_total_cache_creation_input_tokens() -> int:
        return 0
    
    def get_total_cache_read_input_tokens() -> int:
        return 0
    
    def get_total_cost_usd() -> float:
        return 0.0
    
    def get_total_duration() -> float:
        return 0.0
    
    def get_total_input_tokens() -> int:
        return 0
    
    def get_total_lines_added() -> int:
        return 0
    
    def get_total_lines_removed() -> int:
        return 0
    
    def get_total_output_tokens() -> int:
        return 0
    
    def get_total_tool_duration() -> float:
        return 0.0
    
    def get_total_web_search_requests() -> int:
        return 0
    
    def get_usage_for_model(model: str) -> Optional[dict]:
        return None
    
    def has_unknown_model_cost() -> bool:
        return False
    
    def reset_cost_state() -> None:
        pass
    
    def reset_state_for_tests() -> None:
        pass
    
    def set_cost_state_for_restore(data: dict) -> None:
        pass
    
    def set_has_unknown_model_cost(value: bool) -> None:
        pass

try:
    from .entrypoints.agent_sdk_types import ModelUsage
except ImportError:
    class ModelUsage:
        """Type placeholder for ModelUsage."""
        pass

try:
    from .services.analytics.index import log_event
except ImportError:
    def log_event(event_name: str, metadata: dict) -> None:
        pass

try:
    from .utils.advisor import get_advisor_usage
except ImportError:
    def get_advisor_usage(usage: dict) -> list:
        return []

try:
    from .utils.config import get_current_project_config, save_current_project_config
except ImportError:
    def get_current_project_config() -> dict:
        return {}
    
    def save_current_project_config(updater) -> None:
        pass

try:
    from .utils.context import get_context_window_for_model, get_model_max_output_tokens
except ImportError:
    def get_context_window_for_model(model: str, betas: list) -> int:
        return 0
    
    def get_model_max_output_tokens(model: str) -> dict:
        return {"default": 0}

try:
    from .utils.fast_mode import is_fast_mode_enabled
except ImportError:
    def is_fast_mode_enabled() -> bool:
        return False

try:
    from .utils.format import format_duration, format_number
except ImportError:
    def format_duration(seconds: float) -> str:
        return f"{seconds:.1f}s"
    
    def format_number(num: int) -> str:
        return f"{num:,}"

try:
    from .utils.fps_tracker import FpsMetrics
except ImportError:
    class FpsMetrics:
        """Type placeholder for FPS metrics."""
        average_fps: Optional[float] = None
        low_1_pct_fps: Optional[float] = None

try:
    from .utils.model.model import get_canonical_name
except ImportError:
    def get_canonical_name(model: str) -> str:
        return model

try:
    from .utils.model_cost import calculate_usd_cost
except ImportError:
    def calculate_usd_cost(model: str, usage: dict) -> float:
        return 0.0


# ============================================================
# TYPE DEFINITIONS
# ============================================================

StoredCostState = Dict[str, Any]
Usage = Dict[str, Any]  # BetaUsage from Anthropic SDK


# ============================================================
# SESSION COST MANAGEMENT
# ============================================================

def get_stored_session_costs(session_id: str) -> Optional[StoredCostState]:
    """
    Get stored cost state from project config for a specific session.
    
    Returns the cost data if the session ID matches, or None otherwise.
    Use this to read costs BEFORE overwriting the config with save_current_session_costs().
    
    Args:
        session_id: Session ID to look up
    
    Returns:
        Stored cost state or None if session doesn't match
    """
    project_config = get_current_project_config()
    
    # Only return costs if this is the same session that was last saved
    if project_config.get('lastSessionId') != session_id:
        return None
    
    # Build model usage with context windows
    model_usage = None
    if project_config.get('lastModelUsage'):
        model_usage = {
            model: {
                **usage,
                'contextWindow': get_context_window_for_model(model, get_sdk_betas()),
                'maxOutputTokens': get_model_max_output_tokens(model)['default'],
            }
            for model, usage in project_config['lastModelUsage'].items()
        }
    
    return {
        'totalCostUSD': project_config.get('lastCost', 0),
        'totalAPIDuration': project_config.get('lastAPIDuration', 0),
        'totalAPIDurationWithoutRetries': project_config.get('lastAPIDurationWithoutRetries', 0),
        'totalToolDuration': project_config.get('lastToolDuration', 0),
        'totalLinesAdded': project_config.get('lastLinesAdded', 0),
        'totalLinesRemoved': project_config.get('lastLinesRemoved', 0),
        'lastDuration': project_config.get('lastDuration'),
        'modelUsage': model_usage,
    }


def restore_cost_state_for_session(session_id: str) -> bool:
    """
    Restore cost state from project config when resuming a session.
    
    Only restores if the session ID matches the last saved session.
    
    Args:
        session_id: Session ID to restore
    
    Returns:
        True if cost state was restored, False otherwise
    """
    data = get_stored_session_costs(session_id)
    if not data:
        return False
    
    set_cost_state_for_restore(data)
    return True


def save_current_session_costs(fps_metrics: Optional[FpsMetrics] = None) -> None:
    """
    Save the current session's costs to project config.
    
    Call this before switching sessions to avoid losing accumulated costs.
    
    Args:
        fps_metrics: Optional FPS performance metrics
    """
    def update_config(current: dict) -> dict:
        model_usage_data = get_model_usage()
        
        return {
            **current,
            'lastCost': get_total_cost_usd(),
            'lastAPIDuration': get_total_api_duration(),
            'lastAPIDurationWithoutRetries': get_total_api_duration_without_retries(),
            'lastToolDuration': get_total_tool_duration(),
            'lastDuration': get_total_duration(),
            'lastLinesAdded': get_total_lines_added(),
            'lastLinesRemoved': get_total_lines_removed(),
            'lastTotalInputTokens': get_total_input_tokens(),
            'lastTotalOutputTokens': get_total_output_tokens(),
            'lastTotalCacheCreationInputTokens': get_total_cache_creation_input_tokens(),
            'lastTotalCacheReadInputTokens': get_total_cache_read_input_tokens(),
            'lastTotalWebSearchRequests': get_total_web_search_requests(),
            'lastFpsAverage': getattr(fps_metrics, 'average_fps', None) if fps_metrics else None,
            'lastFpsLow1Pct': getattr(fps_metrics, 'low_1_pct_fps', None) if fps_metrics else None,
            'lastModelUsage': {
                model: {
                    'inputTokens': usage['inputTokens'],
                    'outputTokens': usage['outputTokens'],
                    'cacheReadInputTokens': usage['cacheReadInputTokens'],
                    'cacheCreationInputTokens': usage['cacheCreationInputTokens'],
                    'webSearchRequests': usage['webSearchRequests'],
                    'costUSD': usage['costUSD'],
                }
                for model, usage in model_usage_data.items()
            },
            'lastSessionId': get_session_id(),
        }
    
    save_current_project_config(update_config)


# ============================================================
# FORMATTING UTILITIES
# ============================================================

def format_cost(cost: float, max_decimal_places: int = 4) -> str:
    """
    Format cost as USD string with appropriate precision.
    
    Args:
        cost: Cost in USD
        max_decimal_places: Maximum decimal places for small amounts
    
    Returns:
        Formatted cost string (e.g., "$0.0123" or "$1.50")
    """
    if cost > 0.5:
        rounded = round(cost * 100) / 100
        return f"${rounded:.2f}"
    else:
        return f"${cost:.{max_decimal_places}f}"


def format_model_usage() -> str:
    """
    Format model usage breakdown for display.
    
    Groups usage by canonical model name and shows:
    - Input/output tokens
    - Cache read/write tokens
    - Web search requests
    - Cost per model
    
    Returns:
        Formatted usage string
    """
    model_usage_map = get_model_usage()
    
    if not model_usage_map:
        return 'Usage:                 0 input, 0 output, 0 cache read, 0 cache write'
    
    # Accumulate usage by short name
    usage_by_short_name: Dict[str, dict] = {}
    
    for model, usage in model_usage_map.items():
        short_name = get_canonical_name(model)
        
        if short_name not in usage_by_short_name:
            usage_by_short_name[short_name] = {
                'inputTokens': 0,
                'outputTokens': 0,
                'cacheReadInputTokens': 0,
                'cacheCreationInputTokens': 0,
                'webSearchRequests': 0,
                'costUSD': 0,
                'contextWindow': 0,
                'maxOutputTokens': 0,
            }
        
        accumulated = usage_by_short_name[short_name]
        accumulated['inputTokens'] += usage['inputTokens']
        accumulated['outputTokens'] += usage['outputTokens']
        accumulated['cacheReadInputTokens'] += usage['cacheReadInputTokens']
        accumulated['cacheCreationInputTokens'] += usage['cacheCreationInputTokens']
        accumulated['webSearchRequests'] += usage['webSearchRequests']
        accumulated['costUSD'] += usage['costUSD']
    
    result = 'Usage by model:'
    
    for short_name, usage in usage_by_short_name.items():
        usage_string = (
            f"  {format_number(usage['inputTokens'])} input, "
            f"{format_number(usage['outputTokens'])} output, "
            f"{format_number(usage['cacheReadInputTokens'])} cache read, "
            f"{format_number(usage['cacheCreationInputTokens'])} cache write"
        )
        
        if usage['webSearchRequests'] > 0:
            usage_string += f", {format_number(usage['webSearchRequests'])} web search"
        
        usage_string += f" ({format_cost(usage['costUSD'])})"
        
        result += f"\n{short_name + ':':>21}{usage_string}"
    
    return result


def format_total_cost() -> str:
    """
    Format complete cost summary for display.
    
    Includes:
    - Total cost with accuracy warning if needed
    - API and wall duration
    - Code changes (lines added/removed)
    - Per-model usage breakdown
    
    Returns:
        Formatted cost summary string (with dim styling)
    """
    cost_display = format_cost(get_total_cost_usd())
    
    if has_unknown_model_cost():
        cost_display += ' (costs may be inaccurate due to usage of unknown models)'
    
    model_usage_display = format_model_usage()
    
    total_cost_text = f"Total cost:            {cost_display}\n"
    api_duration = f"Total duration (API):  {format_duration(get_total_api_duration())}\n"
    wall_duration = f"Total duration (wall): {format_duration(get_total_duration())}\n"
    
    lines_added = get_total_lines_added()
    lines_removed = get_total_lines_removed()
    
    code_changes = (
        f"Total code changes:    {lines_added} {'line' if lines_added == 1 else 'lines'} added, "
        f"{lines_removed} {'line' if lines_removed == 1 else 'lines'} removed"
    )
    
    return chalk.dim(
        total_cost_text +
        api_duration +
        wall_duration +
        code_changes + "\n" +
        model_usage_display
    )


# ============================================================
# USAGE TRACKING
# ============================================================

def add_to_total_model_usage(
    cost: float,
    usage: Usage,
    model: str,
) -> dict:
    """
    Add usage data to total model usage tracker.
    
    Args:
        cost: Cost in USD for this usage
        usage: Usage object from Anthropic SDK
        model: Model name
    
    Returns:
        Updated model usage object
    """
    model_usage = get_usage_for_model(model) or {
        'inputTokens': 0,
        'outputTokens': 0,
        'cacheReadInputTokens': 0,
        'cacheCreationInputTokens': 0,
        'webSearchRequests': 0,
        'costUSD': 0,
        'contextWindow': 0,
        'maxOutputTokens': 0,
    }
    
    model_usage['inputTokens'] += usage.get('input_tokens', 0)
    model_usage['outputTokens'] += usage.get('output_tokens', 0)
    model_usage['cacheReadInputTokens'] += usage.get('cache_read_input_tokens', 0) or 0
    model_usage['cacheCreationInputTokens'] += usage.get('cache_creation_input_tokens', 0) or 0
    model_usage['webSearchRequests'] += usage.get('server_tool_use', {}).get('web_search_requests', 0) or 0
    model_usage['costUSD'] += cost
    model_usage['contextWindow'] = get_context_window_for_model(model, get_sdk_betas())
    model_usage['maxOutputTokens'] = get_model_max_output_tokens(model)['default']
    
    return model_usage


def add_to_total_session_cost(
    cost: float,
    usage: Usage,
    model: str,
) -> float:
    """
    Add cost and usage to total session tracking.
    
    Updates:
    - Model usage accumulator
    - Total cost state
    - Prometheus counters (cost, tokens)
    - Advisor tool usage (recursive)
    
    Args:
        cost: Cost in USD
        usage: Usage object from Anthropic SDK
        model: Model name
    
    Returns:
        Total cost including advisor usage
    """
    model_usage = add_to_total_model_usage(cost, usage, model)
    add_to_total_cost_state(cost, model_usage, model)
    
    # Determine attributes for metrics
    if is_fast_mode_enabled() and usage.get('speed') == 'fast':
        attrs = {'model': model, 'speed': 'fast'}
    else:
        attrs = {'model': model}
    
    # Update Prometheus counters
    cost_counter = get_cost_counter()
    if cost_counter:
        cost_counter.add(cost, attrs)
    
    token_counter = get_token_counter()
    if token_counter:
        token_counter.add(usage.get('input_tokens', 0), {**attrs, 'type': 'input'})
        token_counter.add(usage.get('output_tokens', 0), {**attrs, 'type': 'output'})
        token_counter.add(usage.get('cache_read_input_tokens', 0) or 0, {**attrs, 'type': 'cacheRead'})
        token_counter.add(usage.get('cache_creation_input_tokens', 0) or 0, {**attrs, 'type': 'cacheCreation'})
    
    # Track advisor tool usage recursively
    total_cost = cost
    
    for advisor_usage in get_advisor_usage(usage):
        advisor_cost = calculate_usd_cost(advisor_usage['model'], advisor_usage)
        
        log_event('tengu_advisor_tool_token_usage', {
            'advisor_model': advisor_usage['model'],
            'input_tokens': advisor_usage['input_tokens'],
            'output_tokens': advisor_usage['output_tokens'],
            'cache_read_input_tokens': advisor_usage.get('cache_read_input_tokens', 0) or 0,
            'cache_creation_input_tokens': advisor_usage.get('cache_creation_input_tokens', 0) or 0,
            'cost_usd_micros': round(advisor_cost * 1_000_000),
        })
        
        total_cost += add_to_total_session_cost(
            advisor_cost,
            advisor_usage,
            advisor_usage['model'],
        )
    
    return total_cost


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    # Session management
    "get_stored_session_costs",
    "restore_cost_state_for_session",
    "save_current_session_costs",
    
    # Formatting
    "format_cost",
    "format_total_cost",
    "format_model_usage",
    
    # Usage tracking
    "add_to_total_session_cost",
    "add_to_total_model_usage",
    
    # Re-exports from bootstrap/state
    "get_total_cost_usd",
    "get_total_duration",
    "get_total_api_duration",
    "get_total_api_duration_without_retries",
    "add_to_total_lines_changed",
    "get_total_lines_added",
    "get_total_lines_removed",
    "get_total_input_tokens",
    "get_total_output_tokens",
    "get_total_cache_read_input_tokens",
    "get_total_cache_creation_input_tokens",
    "get_total_web_search_requests",
    "has_unknown_model_cost",
    "reset_state_for_tests",
    "reset_cost_state",
    "set_has_unknown_model_cost",
    "get_model_usage",
    "get_usage_for_model",
]
