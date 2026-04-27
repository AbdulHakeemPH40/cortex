# ------------------------------------------------------------
# awaySummary.py
# Python conversion of services/awaySummary.ts (lines 1-75)
#
# Generates a short session recap for the "while you were away" card.
# Uses LLM to summarize recent conversation context with session memory.
# Multi-LLM compatible: supports Claude, OpenAI, Gemini, etc.
# ------------------------------------------------------------

from typing import Any, Dict, List, Optional

# ============================================================
# DEFS — defensive fallbacks for unconverted cross-modules
# ============================================================

try:
    from ..utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(message: str) -> None:
        """Stub - logs debug message"""
        pass

try:
    from ..utils.errors import is_abort_error
except ImportError:
    def is_abort_error(e: Any) -> bool:
        """Stub - checks if error is abort error"""
        return (
            isinstance(e, Exception) and
            getattr(e, '__class__', None).__name__ in ('AbortError', 'APIUserAbortError')
        )

try:
    from ..utils.messages import (
        create_user_message,
        get_assistant_message_text,
    )
except ImportError:
    def create_user_message(**kwargs) -> Dict[str, Any]:
        """Stub - creates user message dict"""
        return {"type": "user", **kwargs}
    
    def get_assistant_message_text(response: Dict[str, Any]) -> str:
        """Stub - extracts text from assistant message"""
        content = response.get("message", {}).get("content", [])
        for block in content:
            if block.get("type") == "text":
                return block.get("text", "")
        return ""

try:
    from ..utils.model.model import get_small_fast_model
except ImportError:
    def get_small_fast_model() -> str:
        """Stub - returns default small fast model"""
        return "claude-3-5-haiku-4-20250514"

try:
    from ..utils.systemPromptType import as_system_prompt
except ImportError:
    def as_system_prompt(value: List[str]) -> List[str]:
        return list(value)

try:
    from ..services.api.cortex import query_model_without_streaming
except ImportError:
    async def query_model_without_streaming(**kwargs) -> Dict[str, Any]:
        """Stub - queries model without streaming"""
        raise NotImplementedError("query_model_without_streaming not implemented")

try:
    from ..services.SessionMemory.sessionMemoryUtils import get_session_memory_content
except ImportError:
    async def get_session_memory_content() -> Optional[str]:
        """Stub - returns session memory content"""
        return None


# ============================================================
# CONSTANTS
# ============================================================

# Recap only needs recent context — truncate to avoid "prompt too long" on
# large sessions. 30 messages ≈ ~15 exchanges, plenty for "where we left off."
RECENT_MESSAGE_WINDOW = 30


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def build_away_summary_prompt(memory: Optional[str]) -> str:
    """
    Build the prompt for generating an away summary.
    
    Mirrors TS buildAwaySummaryPrompt() exactly.
    
    Args:
        memory: Optional session memory content for broader context
    
    Returns:
        Formatted prompt string
    """
    memory_block = ""
    if memory:
        memory_block = f"Session memory (broader context):\n{memory}\n\n"
    
    return (
        f"{memory_block}"
        "The user stepped away and is coming back. Write exactly 1-3 short sentences. "
        "Start by stating the high-level task — what they are building or debugging, "
        "not implementation details. Next: the concrete next step. "
        "Skip status reports and commit recaps."
    )


# ============================================================
# MAIN FUNCTION
# ============================================================

async def generate_away_summary(
    messages: List[Dict[str, Any]],
    signal: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Generates a short session recap for the "while you were away" card.
    
    Mirrors TS generateAwaySummary() exactly.
    Multi-LLM compatible: works with any model provider configured in Cortex IDE.
    
    Args:
        messages: List of conversation messages (user/assistant/tool)
        signal: Optional abort signal dict with 'aborted' key
    
    Returns:
        A brief summary string, or None on abort, empty transcript, or error
    """
    if not messages or len(messages) == 0:
        return None

    try:
        # Get session memory for broader context
        memory = await get_session_memory_content()
        
        # Take only recent messages to avoid prompt overflow
        recent = messages[-RECENT_MESSAGE_WINDOW:]
        
        # Append the away summary prompt as a user message
        recent.append(create_user_message({
            "content": build_away_summary_prompt(memory),
        }))
        
        # Query the model (non-streaming for summary generation)
        response = await query_model_without_streaming(
            messages=recent,
            system_prompt=as_system_prompt([]),
            thinking_config={"type": "disabled"},
            tools=[],
            signal=signal,
            options={
                "getToolPermissionContext": lambda: {"mode": "default"},
                "model": get_small_fast_model(),
                "toolChoice": None,
                "isNonInteractiveSession": False,
                "hasAppendSystemPrompt": False,
                "agents": [],
                "querySource": "away_summary",
                "mcpTools": [],
                "skipCacheWrite": True,
            },
        )
        
        # Check for API error response
        if response.get("isApiErrorMessage"):
            log_for_debugging(
                f"[awaySummary] API error: {get_assistant_message_text(response)}"
            )
            return None
        
        # Extract and return the assistant's response text
        return get_assistant_message_text(response)
        
    except Exception as err:
        # Handle abort scenarios (mirrors TS: err instanceof APIUserAbortError || signal.aborted)
        if is_abort_error(err) or (signal and signal.get("aborted")):
            return None
        
        # Log other errors
        log_for_debugging(f"[awaySummary] generation failed: {err}")
        return None


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "generate_away_summary",
    "build_away_summary_prompt",
    "RECENT_MESSAGE_WINDOW",
]
