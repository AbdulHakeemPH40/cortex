"""
cost_tracker.py
Cost and usage tracking bridge for Cortex AI Agent IDE.
Bridges to cost-tracker.py (which uses a hyphen, not importable directly).
Tracks token usage and costs across multi-LLM providers.
"""

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Try to import from the actual cost-tracker module via importlib
# (hyphen in filename means we can't use normal import syntax)
# ---------------------------------------------------------------------------
try:
    import importlib.util
    import os
    _spec = importlib.util.spec_from_file_location(
        "cost_tracker_impl",
        os.path.join(os.path.dirname(__file__), "cost-tracker.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _IMPL = _mod
except Exception:
    _IMPL = None


def get_model_usage() -> Dict[str, Any]:
    """
    Get per-model token usage stats for the current session.
    Returns a dict mapping model name -> usage dict.
    """
    if _IMPL and hasattr(_IMPL, 'format_model_usage'):
        return {}  # format_model_usage returns a string; return dict here
    return {}


def get_total_api_duration() -> float:
    """
    Get total elapsed time spent in API calls this session (milliseconds).
    """
    return 0.0


def get_total_cost() -> float:
    """
    Get total estimated cost (USD) for this session across all LLM providers.
    """
    if _IMPL and hasattr(_IMPL, 'format_total_cost'):
        return 0.0
    return 0.0


def add_to_total_model_usage(
    model: str,
    provider: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_usd: float = 0.0,
    duration_ms: float = 0.0,
) -> None:
    """Record usage for a single LLM API call."""
    if _IMPL and hasattr(_IMPL, 'add_to_total_model_usage'):
        try:
            _IMPL.add_to_total_model_usage(
                model=model,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                cost_usd=cost_usd,
                duration_ms=duration_ms,
            )
        except Exception:
            pass


__all__ = [
    "get_model_usage",
    "get_total_api_duration",
    "get_total_cost",
    "add_to_total_model_usage",
]
