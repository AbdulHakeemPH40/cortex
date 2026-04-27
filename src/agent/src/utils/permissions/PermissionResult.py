"""
Compatibility permission result models used across converted agent modules.

Several files import `utils.permissions.PermissionResult` and expect objects
that behave like both dicts and attribute-based records (`result.behavior`).
This module provides that bridge.
"""

from __future__ import annotations

from typing import Any, Optional


class PermissionDict(dict):
    """Dict with attribute-style access for compatibility."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class PermissionDecisionReason(PermissionDict):
    """Reason metadata for a permission decision."""

    def __init__(self, type: str, **kwargs: Any) -> None:
        super().__init__(type=type, **kwargs)


class PermissionResult(PermissionDict):
    """Base permission result."""

    def __init__(
        self,
        behavior: str,
        message: Optional[str] = None,
        updatedInput: Any = None,
        decisionReason: Optional[PermissionDecisionReason] = None,
        **kwargs: Any,
    ) -> None:
        payload = {"behavior": behavior}
        if message is not None:
            payload["message"] = message
        if updatedInput is not None:
            payload["updatedInput"] = updatedInput
        if decisionReason is not None:
            payload["decisionReason"] = decisionReason
        payload.update(kwargs)
        super().__init__(payload)


class PermissionDecision(PermissionResult):
    """General permission decision."""


class PermissionAskDecision(PermissionDecision):
    """Permission decision with ask behavior."""

    def __init__(self, message: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(behavior="ask", message=message, **kwargs)


class PermissionDenyDecision(PermissionDecision):
    """Permission decision with deny behavior."""

    def __init__(self, message: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(behavior="deny", message=message, **kwargs)


def getRuleBehaviorDescription(behavior: str) -> str:
    """Human-friendly description for permission rule behavior."""

    mapping = {
        "allow": "allowed by permission rule",
        "deny": "blocked by permission rule",
        "ask": "requires user approval",
    }
    return mapping.get(behavior, behavior)

