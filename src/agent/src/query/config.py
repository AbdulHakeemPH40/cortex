# ------------------------------------------------------------
# config.py (query)
# Python conversion of query/config.ts
#
# Build-time config snapshot for a single query() call.
# Immutable gates snapshotted once at entry — not re-checked each iteration.
# Feature() gates are intentionally excluded (must stay inline for
# dead-code elimination in builds).
# ------------------------------------------------------------

import os
from dataclasses import dataclass
from typing import Literal

__all__ = ["build_query_config", "QueryConfig"]


@dataclass
class QueryGates:
    """
    Runtime gates (env/statsig). NOT feature() gates — those must stay
    inline at guarded blocks for tree-shaking.
    """

    streaming_tool_execution: bool = False
    emit_tool_use_summaries: bool = False
    is_ant: bool = False
    fast_mode_enabled: bool = True


@dataclass
class QueryConfig:
    """
    Config snapshot for one query() call.

    Mirrors TS QueryConfig exactly.
    """

    session_id: str
    gates: QueryGates


def _get_session_id() -> str:
    """Get the current session ID."""
    try:
        from ...bootstrap.state import get_session_id

        return get_session_id()
    except ImportError:
        return "default-session"


def _check_statsig_gate(gate_name: str) -> bool:
    """
    Check a Statsig feature gate (cached, may be stale).

    Stub: returns False for all gates.
    Replace with actual Statsig/GrowthBook integration.
    """
    # TODO: integrate with Statsig or GrowthBook for gate evaluation
    return False


def _is_env_truthy(value: str | None) -> bool:
    """Check if an env var is truthy."""
    if value is None:
        return False
    return value.lower() in ("1", "true", "yes")


def build_query_config() -> QueryConfig:
    """
    Build a QueryConfig snapshot for the current session.

    Mirrors TS buildQueryConfig() exactly.

    Returns:
        QueryConfig with sessionId and gate values snapshotted for this call.
    """
    return QueryConfig(
        session_id=_get_session_id(),
        gates=QueryGates(
            streaming_tool_execution=_check_statsig_gate(
                "tengu_streaming_tool_execution2"
            ),
            emit_tool_use_summaries=_is_env_truthy(
                os.environ.get("CORTEX_CODE_EMIT_TOOL_USE_SUMMARIES")
            ),
            is_ant=os.environ.get("USER_TYPE") == "ant",
            fast_mode_enabled=not _is_env_truthy(
                os.environ.get("CORTEX_CODE_DISABLE_FAST_MODE")
            ),
        ),
    )
