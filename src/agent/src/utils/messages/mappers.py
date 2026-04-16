"""
utils/messages/mappers.py
Python conversion of utils/messages/mappers.ts (291 lines)

Provides SDK-to-internal and internal-to-SDK message conversion utilities.
The TypeScript version used @anthropic-ai/sdk types; the Python version
uses plain dicts (matching the rest of the Python codebase).

Key functions:
  to_internal_messages()              - SDK messages → internal Message dicts
  to_sdk_messages()                   - internal Message dicts → SDK format
  to_sdk_compact_metadata()           - CompactMetadata → SDK wire format
  from_sdk_compact_metadata()         - SDK wire format → CompactMetadata
  to_sdk_rate_limit_info()            - ClaudeAILimits → SDKRateLimitInfo
  local_command_output_to_sdk_assistant_message()
"""

from __future__ import annotations

import re
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import create_assistant_message


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_uuid() -> str:
    return str(_uuid_mod.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text. Mirrors strip-ansi npm package."""
    ansi_re = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_re.sub('', text)


# ─── SDK ↔ Internal conversion ───────────────────────────────────────────────

def to_internal_messages(sdk_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert SDK-format messages to internal Message dicts.
    Mirrors TS toInternalMessages().

    Handles:
      - assistant  → internal assistant message
      - user       → internal user message
      - system/compact_boundary → internal system message with compactMetadata
    """
    result: List[Dict[str, Any]] = []
    for message in sdk_messages:
        mtype = message.get("type", "")

        if mtype == "assistant":
            result.append({
                "type": "assistant",
                "message": message.get("message", {}),
                "uuid": message.get("uuid", _make_uuid()),
                "requestId": None,
                "timestamp": _now_iso(),
            })

        elif mtype == "user":
            result.append({
                "type": "user",
                "message": message.get("message", {}),
                "uuid": message.get("uuid") or _make_uuid(),
                "timestamp": message.get("timestamp") or _now_iso(),
                "isMeta": message.get("isSynthetic", False),
            })

        elif mtype == "system":
            subtype = message.get("subtype", "")
            if subtype == "compact_boundary":
                result.append({
                    "type": "system",
                    "content": "Conversation compacted",
                    "level": "info",
                    "subtype": "compact_boundary",
                    "compactMetadata": from_sdk_compact_metadata(
                        message.get("compact_metadata", {})
                    ),
                    "uuid": message.get("uuid", _make_uuid()),
                    "timestamp": _now_iso(),
                })
            # Other system subtypes (init, etc.) are not converted to internal

    return result


def to_sdk_messages(messages: List[Dict[str, Any]], session_id: str = "") -> List[Dict[str, Any]]:
    """
    Convert internal Message dicts to SDK-format messages.
    Mirrors TS toSDKMessages().
    """
    result: List[Dict[str, Any]] = []
    for message in messages:
        mtype = message.get("type", "")

        if mtype == "assistant":
            result.append({
                "type": "assistant",
                "message": _normalize_assistant_message_for_sdk(message),
                "session_id": session_id,
                "parent_tool_use_id": None,
                "uuid": message.get("uuid", _make_uuid()),
                "error": message.get("error"),
            })

        elif mtype == "user":
            entry: Dict[str, Any] = {
                "type": "user",
                "message": message.get("message", {}),
                "session_id": session_id,
                "parent_tool_use_id": None,
                "uuid": message.get("uuid", _make_uuid()),
                "timestamp": message.get("timestamp", _now_iso()),
                "isSynthetic": (
                    message.get("isMeta", False)
                    or message.get("isVisibleInTranscriptOnly", False)
                ),
            }
            if message.get("toolUseResult") is not None:
                entry["tool_use_result"] = message["toolUseResult"]
            result.append(entry)

        elif mtype == "system":
            subtype = message.get("subtype", "")
            if subtype == "compact_boundary" and message.get("compactMetadata"):
                result.append({
                    "type": "system",
                    "subtype": "compact_boundary",
                    "session_id": session_id,
                    "uuid": message.get("uuid", _make_uuid()),
                    "compact_metadata": to_sdk_compact_metadata(
                        message["compactMetadata"]
                    ),
                })
            elif subtype == "local_command":
                content = message.get("content", "")
                LOCAL_STDOUT = "local-command-stdout"
                LOCAL_STDERR = "local-command-stderr"
                if (
                    f"<{LOCAL_STDOUT}>" in content
                    or f"<{LOCAL_STDERR}>" in content
                ):
                    result.append(
                        local_command_output_to_sdk_assistant_message(
                            content,
                            message.get("uuid", _make_uuid()),
                            session_id=session_id,
                        )
                    )

    return result


# ─── CompactMetadata conversion ───────────────────────────────────────────────

def to_sdk_compact_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert internal CompactMetadata to SDK wire format.
    Mirrors TS toSDKCompactMetadata().
    """
    result: Dict[str, Any] = {
        "trigger": meta.get("trigger"),
        "pre_tokens": meta.get("preTokens", 0),
    }
    seg = meta.get("preservedSegment")
    if seg:
        result["preserved_segment"] = {
            "head_uuid":   seg.get("headUuid"),
            "anchor_uuid": seg.get("anchorUuid"),
            "tail_uuid":   seg.get("tailUuid"),
        }
    return result


def from_sdk_compact_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert SDK wire format to internal CompactMetadata.
    Mirrors TS fromSDKCompactMetadata().
    """
    result: Dict[str, Any] = {
        "trigger":   meta.get("trigger"),
        "preTokens": meta.get("pre_tokens", 0),
    }
    seg = meta.get("preserved_segment")
    if seg:
        result["preservedSegment"] = {
            "headUuid":   seg.get("head_uuid"),
            "anchorUuid": seg.get("anchor_uuid"),
            "tailUuid":   seg.get("tail_uuid"),
        }
    return result


# ─── Rate-limit info ─────────────────────────────────────────────────────────

def to_sdk_rate_limit_info(
    limits: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Map internal ClaudeAILimits to the SDK-facing SDKRateLimitInfo type.
    Strips internal-only fields.
    Mirrors TS toSDKRateLimitInfo().
    """
    if not limits:
        return None
    result: Dict[str, Any] = {"status": limits.get("status")}
    for field in (
        "resetsAt", "rateLimitType", "utilization",
        "overageStatus", "overageResetsAt", "overageDisabledReason",
        "isUsingOverage", "surpassedThreshold",
    ):
        if limits.get(field) is not None:
            result[field] = limits[field]
    return result


# ─── Local command output → SDK assistant message ─────────────────────────────

def local_command_output_to_sdk_assistant_message(
    raw_content: str,
    msg_uuid: str,
    session_id: str = "",
) -> Dict[str, Any]:
    """
    Convert local command output to a well-formed SDK assistant message.
    Strips ANSI, unwraps <local-command-stdout/stderr> XML tags.
    Mirrors TS localCommandOutputToSDKAssistantMessage().

    Emits as 'assistant' for SDK compatibility (mobile apps / ingress converters
    don't know about local_command_output system subtype).
    """
    LOCAL_STDOUT = "local-command-stdout"
    LOCAL_STDERR = "local-command-stderr"

    clean = _strip_ansi(raw_content)
    clean = re.sub(
        rf'<{LOCAL_STDOUT}>([\s\S]*?)</{LOCAL_STDOUT}>', r'\1', clean
    )
    clean = re.sub(
        rf'<{LOCAL_STDERR}>([\s\S]*?)</{LOCAL_STDERR}>', r'\1', clean
    )
    clean = clean.strip()

    # createAssistantMessage builds a complete synthetic message
    synthetic = create_assistant_message(content=clean)

    return {
        "type": "assistant",
        "message": synthetic["message"],
        "parent_tool_use_id": None,
        "session_id": session_id,
        "uuid": msg_uuid,
    }


# ─── Internal normalization helper ───────────────────────────────────────────

def _normalize_assistant_message_for_sdk(
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize tool inputs in assistant message content for SDK consumption.
    Injects plan content into ExitPlanModeV2 tool inputs.
    Mirrors TS normalizeAssistantMessageForSDK().
    """
    # EXIT_PLAN_MODE_V2 tool name constant
    EXIT_PLAN_MODE_V2_TOOL_NAME = "exit_plan_mode"

    inner = message.get("message", {})
    content = inner.get("content", [])
    if not isinstance(content, list):
        return inner

    normalized = []
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == EXIT_PLAN_MODE_V2_TOOL_NAME
        ):
            # Attempt to inject plan text from plans module if available
            try:
                from ...utils.plans import get_plan
                plan = get_plan()
                if plan:
                    block = dict(block)
                    block["input"] = {**(block.get("input") or {}), "plan": plan}
            except (ImportError, Exception):
                pass
        normalized.append(block)

    if normalized == content:
        return inner

    result = dict(inner)
    result["content"] = normalized
    return result
