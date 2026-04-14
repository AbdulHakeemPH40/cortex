# ------------------------------------------------------------
# UI.py
# Python conversion of RemoteTriggerTool/UI.ts (if it existed)
# 
# UI rendering functions for RemoteTriggerTool.
# ------------------------------------------------------------

from typing import Any, Dict


def renderToolUseMessage(input_data: Dict[str, Any]) -> str:
    """Renders a tool use message for display."""
    action = input_data.get('action', 'unknown')
    trigger_id = input_data.get('trigger_id')
    
    if trigger_id:
        return f"Remote trigger {action} for {trigger_id}"
    else:
        return f"Remote trigger {action}"


def renderToolResultMessage(output: Any) -> str:
    """Renders a tool result message for display."""
    # Handle both dataclass and dict output formats
    if hasattr(output, 'status'):
        status = output.status
    elif isinstance(output, dict):
        status = output.get('status', 'unknown')
    else:
        status = 'unknown'
    
    return f"Remote trigger API returned HTTP {status}"
