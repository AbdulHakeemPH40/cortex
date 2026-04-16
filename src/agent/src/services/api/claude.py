"""
services/api/claude.py
API usage accumulation and tracking for Cortex AI Agent IDE.
Handles multi-LLM token usage tracking across providers.
"""

from typing import Any, Dict, Optional


def accumulate_usage(total: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accumulate API usage totals across multiple LLM calls.
    Merges current usage into running total by summing numeric fields.
    """
    result = dict(total)
    for key, value in current.items():
        if isinstance(value, (int, float)):
            result[key] = result.get(key, 0) + value
        else:
            result[key] = value
    return result


def update_usage(current: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update current usage with a delta update.
    Merges delta values into current usage snapshot.
    """
    result = dict(current)
    for key, value in delta.items():
        if isinstance(value, (int, float)):
            result[key] = result.get(key, 0) + value
        else:
            result[key] = value
    return result


__all__ = [
    "accumulate_usage",
    "update_usage",
]
