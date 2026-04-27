# ------------------------------------------------------------
# toolUseSummaryGenerator.py
# Python conversion of services/toolUseSummary/toolUseSummaryGenerator.ts (lines 1-113)
#
# Generates human-readable summaries of completed tool batches using Haiku.
# Used by the SDK to provide high-level progress updates to clients.
# ------------------------------------------------------------

from typing import Any, Dict, List, Optional

# ============================================================
# DEPS — defensive fallbacks for unconverted cross-modules
# ============================================================

try:
    from ...constants.errorIds import E_TOOL_USE_SUMMARY_GENERATION_FAILED
except ImportError:
    E_TOOL_USE_SUMMARY_GENERATION_FAILED = 344

try:
    from ...utils.errors import to_error
except ImportError:
    def to_error(e: Any) -> Exception:
        """Stub - normalizes error to Exception"""
        return e if isinstance(e, Exception) else Exception(str(e))

try:
    from ...utils.log import log_error
except ImportError:
    def log_error(error: Exception) -> None:
        """Stub - logs error"""
        print(f"[ERROR] {error}", flush=True)

try:
    from ...utils.slowOperations import json_stringify
except ImportError:
    import json
    def json_stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, default=str)

try:
    from ...utils.systemPromptType import as_system_prompt
except ImportError:
    def as_system_prompt(value: List[str]) -> List[str]:
        return list(value)

try:
    from ...services.api.cortex import query_haiku
except ImportError:
    async def query_haiku(**kwargs) -> Dict[str, Any]:
        """Stub - queries Haiku model"""
        raise NotImplementedError("query_haiku not implemented")


# ============================================================
# CONSTANTS
# ============================================================

TOOL_USE_SUMMARY_SYSTEM_PROMPT = """Write a short summary label describing what these tool calls accomplished. It appears as a single-line row in a mobile app and truncates around 30 characters, so think git-commit-subject, not sentence.

Keep the verb in past tense and the most distinctive noun. Drop articles, connectors, and long location context first.

Examples:
- Searched in auth/
- Fixed NPE in UserService
- Created signup endpoint
- Read config.json
- Ran failing tests"""


# ============================================================
# TYPE DEFINITIONS
# ============================================================

class ToolInfo:
    """Represents information about a single tool execution."""
    def __init__(
        self,
        name: str,
        input: Any,
        output: Any,
    ):
        self.name = name
        self.input = input
        self.output = output


class GenerateToolUseSummaryParams:
    """Parameters for generating a tool use summary."""
    def __init__(
        self,
        tools: List[Dict[str, Any]],
        signal: Optional[Any] = None,
        is_non_interactive_session: bool = False,
        last_assistant_text: Optional[str] = None,
    ):
        self.tools = tools
        self.signal = signal
        self.is_non_interactive_session = is_non_interactive_session
        self.last_assistant_text = last_assistant_text


# ============================================================
# MAIN FUNCTION
# ============================================================

async def generate_tool_use_summary(
    tools: List[Dict[str, Any]],
    signal: Optional[Any] = None,
    is_non_interactive_session: bool = False,
    last_assistant_text: Optional[str] = None,
) -> Optional[str]:
    """
    Generates a human-readable summary of completed tools.

    Mirrors TS generateToolUseSummary() exactly.

    Args:
        tools: List of tool info dicts with 'name', 'input', and 'output' keys
        signal: Optional abort signal for cancellation
        is_non_interactive_session: Whether this is a non-interactive session
        last_assistant_text: Optional text from assistant's last message for context

    Returns:
        A brief summary string, or None if generation fails
    """
    if not tools or len(tools) == 0:
        return None

    try:
        # Build a concise representation of what tools did
        tool_summaries = []
        for tool in tools:
            input_str = _truncate_json(tool.get("input"), 300)
            output_str = _truncate_json(tool.get("output"), 300)
            tool_summaries.append(
                f"Tool: {tool['name']}\nInput: {input_str}\nOutput: {output_str}"
            )
        tool_summaries_str = "\n\n".join(tool_summaries)

        # Add user intent context if available
        context_prefix = ""
        if last_assistant_text:
            truncated_intent = last_assistant_text[:200]
            context_prefix = f"User's intent (from assistant's last message): {truncated_intent}\n\n"

        # Call Haiku to generate summary
        response = await query_haiku(
            system_prompt=as_system_prompt([TOOL_USE_SUMMARY_SYSTEM_PROMPT]),
            user_prompt=f"{context_prefix}Tools completed:\n\n{tool_summaries_str}\n\nLabel:",
            signal=signal,
            options={
                "querySource": "tool_use_summary_generation",
                "enablePromptCaching": True,
                "agents": [],
                "isNonInteractiveSession": is_non_interactive_session,
                "hasAppendSystemPrompt": False,
                "mcpTools": [],
            },
        )

        # Extract text content from response
        message_content = response.get("message", {}).get("content", [])
        text_blocks = [
            block.get("text", "")
            for block in message_content
            if block.get("type") == "text"
        ]
        summary = "".join(text_blocks).strip()

        return summary if summary else None

    except Exception as error:
        # Log but don't fail - summaries are non-critical
        err = to_error(error)
        err.cause = {"errorId": E_TOOL_USE_SUMMARY_GENERATION_FAILED}  # type: ignore[attr-defined]
        log_error(err)
        return None


# ============================================================
# HELPERS
# ============================================================

def _truncate_json(value: Any, max_length: int) -> str:
    """
    Truncates a JSON value to a maximum length for the prompt.

    Mirrors TS truncateJson() exactly.
    """
    try:
        json_str = json_stringify(value)
        if len(json_str) <= max_length:
            return json_str
        return json_str[:max_length - 3] + "..."
    except Exception:
        return "[unable to serialize]"


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "generate_tool_use_summary",
    "ToolInfo",
    "GenerateToolUseSummaryParams",
    "TOOL_USE_SUMMARY_SYSTEM_PROMPT",
]
