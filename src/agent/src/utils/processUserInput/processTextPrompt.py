# ------------------------------------------------------------
# processTextPrompt.py
# Python conversion of utils/processUserInput/processTextPrompt.ts
#
# Handles regular (non-slash, non-bash) user text prompts.
# - Creates a UserMessage from the input
# - Adds image content blocks if present
# - Emits OTel events and interaction spans
# - Logs analytics (negative/keep-going keyword detection)
# ------------------------------------------------------------

import uuid
from typing import Any, Dict, List, Optional, Union

__all__ = ["process_text_prompt"]


# ============================================================
# Type aliases (match TS types)
# ============================================================

ContentBlockParam = Dict[str, Any]
UserMessage = Dict[str, Any]
AttachmentMessage = Dict[str, Any]
SystemMessage = Dict[str, Any]
Message = Dict[str, Any]

# ============================================================
# process_text_prompt
# ============================================================

def process_text_prompt(
    input: Union[str, List[ContentBlockParam]],
    image_content_blocks: List[ContentBlockParam],
    image_paste_ids: List[int],
    attachment_messages: List[AttachmentMessage],
    uuid_arg: Optional[str] = None,
    permission_mode: Optional[str] = None,
    is_meta: bool = False,
) -> Dict[str, Any]:
    """
    Process a regular text prompt and produce messages ready for the query loop.

    Mirrors TS processTextPrompt() exactly:
    1. Generates a prompt UUID and sets it (for telemetry)
    2. Extracts the user prompt text (for OTel events)
    3. Checks for negative/keep-going keyword patterns
    4. Creates a UserMessage with text + image blocks
    5. Prepends attachment messages
    6. Always returns shouldQuery=True for regular prompts

    Args:
        input:          String or list of content blocks (from user)
        image_content_blocks:  Processed image blocks to include
        image_paste_ids:       IDs of pasted images
        attachment_messages:    Messages from IDE selection / skills / etc.
        uuid_arg:      Explicit UUID for the prompt (optional)
        permission_mode: Permission mode ('agree', 'browse', etc.)
        is_meta:       True if this is a hidden (meta) message

    Returns:
        Dict with:
          - messages: List[Message] (UserMessage + attachment_messages)
          - shouldQuery: bool (always True for regular prompts)
    """
    # Generate prompt UUID (mirrors TS: randomUUID() + setPromptId)
    prompt_id = str(uuid.uuid4())

    # Extract user prompt text for OTel span and event
    user_prompt_text: str
    if isinstance(input, str):
        user_prompt_text = input
    else:
        found = next(
            (b.get("text", "") for b in reversed(input) if b.get("type") == "text"),
            "",
        )
        user_prompt_text = found or ""

    # Note: In Python we skip startInteractionSpan and logOTelEvent.
    # Those require the telemetry/sessionTracing infrastructure which is
    # optional in the Python port. Both are fire-and-forget analytics.

    # Keyword matching for analytics
    # (mirrors TS matchesNegativeKeyword / matchesKeepGoingKeyword)
    try:
        from ...utils.userPromptKeywords import (
            matches_negative_keyword,
            matches_keep_going_keyword,
        )

        is_negative: bool = matches_negative_keyword(user_prompt_text)
        is_keep_going: bool = matches_keep_going_keyword(user_prompt_text)
    except ImportError:
        is_negative = False
        is_keep_going = False

    # Fire-and-forget analytics event
    try:
        from ...utils.system_prompt import log_event

        log_event(
            "tengu_input_prompt",
            {
                "is_negative": is_negative,
                "is_keep_going": is_keep_going,
            },
        )
    except ImportError:
        pass

    # Lazy import to avoid circular refs
    from ...utils.messages import create_user_message

    # Build content: text first, then images
    if image_content_blocks:
        if isinstance(input, str):
            text_content: List[ContentBlockParam] = (
                [{"type": "text", "text": input}]
                if input.strip()
                else []
            )
        else:
            # For array input, include all blocks before images
            text_content = [b for b in input if b.get("type") == "text"]

        user_message = create_user_message(
            content=[*text_content, *image_content_blocks],
            uuid=uuid_arg or prompt_id,
            image_paste_ids=image_paste_ids if image_paste_ids else None,
            permission_mode=permission_mode,
            is_meta=is_meta or None,
        )
    else:
        user_message = create_user_message(
            content=input,
            uuid=uuid_arg or prompt_id,
            permission_mode=permission_mode,
            is_meta=is_meta or None,
        )

    return {
        "messages": [user_message, *attachment_messages],
        "shouldQuery": True,
    }
