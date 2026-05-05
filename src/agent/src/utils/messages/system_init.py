"""
utils/messages/system_init.py
Python conversion of utils/messages/systemInit.ts (97 lines)

Builds the system/init SDK message — the first message on the SDK stream,
carrying session metadata (cwd, tools, model, commands, etc.) that remote
clients use to render pickers and gate UI.

Key functions:
  build_system_init_message(inputs)  - Build the init SDKMessage
  sdk_compat_tool_name(name)         - Remap legacy tool name (Task → Agent)
"""

from __future__ import annotations

import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Legacy tool name mapping (mirrors TS sdkCompatToolName).
# The wire name was renamed Task → Agent; old SDK consumers expect 'Task'.
_AGENT_TOOL_NAME  = "Agent"
_LEGACY_TOOL_NAME = "Task"


def sdk_compat_tool_name(name: str) -> str:
    """
    Map internal tool names to the SDK-compatible wire name.
    Keeps 'Agent' → 'Task' for backward compatibility with older SDK consumers.
    Mirrors TS sdkCompatToolName().
    """
    return _LEGACY_TOOL_NAME if name == _AGENT_TOOL_NAME else name


def build_system_init_message(
    tools:           List[Dict[str, Any]],
    mcp_clients:     List[Dict[str, Any]],
    model:           str,
    permission_mode: str,
    commands:        List[Dict[str, Any]],
    agents:          List[Dict[str, Any]],
    skills:          List[Dict[str, Any]],
    plugins:         List[Dict[str, Any]],
    fast_mode:       Optional[bool]        = None,
    session_id:      str                   = "",
    cwd:             str                   = "",
    api_key_source:  str                   = "unknown",
    betas:           Optional[List[str]]   = None,
    version:         str                   = "0.0.0",
    output_style:    str                   = "default",
) -> Dict[str, Any]:
    """
    Build the system/init SDKMessage — the first message on the SDK stream.

    Mirrors TS buildSystemInitMessage() exactly.

    Called from two paths that must produce identical shapes:
      - QueryEngine (spawn-bridge / print-mode / SDK)
      - ReplBridge (REPL Remote Control)

    Args:
        tools:           List of dicts with 'name' key
        mcp_clients:     List of dicts with 'name' and 'type' keys
        model:           Active model ID string
        permission_mode: 'default' | 'acceptEdits' | 'bypassPermissions' | 'plan'
        commands:        List of slash-command dicts with 'name' and optional 'userInvocable'
        agents:          List of agent dicts with 'agentType' key
        skills:          List of skill dicts with 'name' and optional 'userInvocable'
        plugins:         List of plugin dicts with 'name', 'path', 'source'
        fast_mode:       Whether fast mode is active (None = unknown)
        session_id:      Current session ID
        cwd:             Current working directory
        api_key_source:  'env' | 'bedrock' | 'vertex' | 'oauth' | 'unknown'
        betas:           Active Anthropic beta feature flags
        version:         claude-code version string
        output_style:    UI output style name

    Returns:
        Dict matching the SDK SDKMessage/system/init schema
    """
    message: Dict[str, Any] = {
        "type":             "system",
        "subtype":          "init",
        "cwd":              cwd,
        "session_id":       session_id,
        "tools":            [sdk_compat_tool_name(t["name"]) for t in tools],
        "mcp_servers": [
            {"name": c["name"], "status": c.get("type", "connected")}
            for c in mcp_clients
        ],
        "model":            model,
        "permissionMode":   permission_mode,
        "slash_commands": [
            c["name"]
            for c in commands
            if c.get("userInvocable", True) is not False
        ],
        "apiKeySource":     api_key_source,
        "betas":            betas or [],
        "claude_code_version": version,
        "output_style":     output_style,
        "agents":           [a["agentType"] for a in agents],
        "skills": [
            s["name"]
            for s in skills
            if s.get("userInvocable", True) is not False
        ],
        "plugins": [
            {"name": p["name"], "path": p.get("path", ""), "source": p.get("source", "")}
            for p in plugins
        ],
        "uuid": str(_uuid_mod.uuid4()),
    }

    # Fast mode state — mirrors getFastModeState() logic stub
    if fast_mode is not None:
        message["fast_mode_state"] = {
            "enabled": fast_mode,
            "available": True,
        }

    return message
