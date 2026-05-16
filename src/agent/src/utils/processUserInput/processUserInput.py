# ------------------------------------------------------------
# processUserInput.py
# Python conversion of utils/processUserInput/processUserInput.ts
#
# Central entry point for all user input processing:
# - Slash commands (/search, /model, etc.)
# - Bash mode (! prefix)
# - Regular text prompts
# - Ultraplan keyword detection
# - Image pasting and resizing
# - Attachment loading
# - Bridge-safe command override (mobile/web CCR)
# - UserPromptSubmit hooks (blocking, stop, additional context)
# ------------------------------------------------------------

import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Union,
)

__all__ = ["process_user_input", "ProcessUserInputResult"]


# ============================================================
# Type aliases
# ============================================================

ContentBlockParam = Dict[str, Any]
Message = Dict[str, Any]


# ============================================================
# Result type
# ============================================================

@dataclass
class ProcessUserInputResult:
    """
    Result returned by processUserInput.

    Mirrors TS ProcessUserInputBaseResult exactly.
    """

    messages: List[Message] = field(default_factory=list)
    should_query: bool = False
    allowed_tools: Optional[List[str]] = None
    model: Optional[str] = None
    effort: Optional[Any] = None
    result_text: Optional[str] = None
    next_input: Optional[str] = None
    submit_next_input: bool = False


# ============================================================
# Prompt input modes
# ============================================================

PromptInputMode = str  # Literal: 'prompt' | 'bash' | 'task-notification'


# ============================================================
# Helpers
# ============================================================

def _get_app_state(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract AppState from tool context.

    Handles both dict-style context (from SDK) and dataclass-style context
    (from Python-native code).
    """
    if hasattr(context, "get_app_state"):
        return context.get_app_state()
    if hasattr(context, "getAppState"):
        return context.getAppState()
    if callable(context.get):
        return context.get("appState") or {}
    return getattr(context, "app_state", {})


def _get_permission_mode(context: Dict[str, Any]) -> str:
    """Extract toolPermissionContext.mode from context."""
    app_state = _get_app_state(context)

    # Try dataclass attribute first
    tpc = getattr(app_state, "tool_permission_context", None) or getattr(
        app_state, "toolPermissionContext", None
    )
    if tpc is not None:
        return getattr(tpc, "mode", "agree")

    # Try dict access
    if isinstance(app_state, dict):
        tpc = app_state.get("toolPermissionContext") or app_state.get(
            "tool_permission_context"
        )
        if isinstance(tpc, dict):
            return tpc.get("mode", "agree")

    return "agree"


def _is_non_interactive_session(context: Dict[str, Any]) -> bool:
    """Check if context.options.isNonInteractiveSession is True."""
    # Try options sub-object
    options = getattr(context, "options", None)
    if options is not None:
        val = getattr(options, "is_non_interactive_session", None)
        if val is not None:
            return bool(val)
        val = getattr(options, "isNonInteractiveSession", None)
        if val is not None:
            return bool(val)
        # Dict-style options
        if hasattr(options, "get"):
            return bool(options.get("isNonInteractiveSession"))

    # Fall back to context-level attribute
    val = getattr(context, "is_non_interactive_session", None)
    if val is not None:
        return bool(val)
    return getattr(context, "isNonInteractiveSession", False)


# ============================================================
# apply_truncation
# MAX_HOOK_OUTPUT_LENGTH = 10000
# ============================================================

_MAX_HOOK_OUTPUT_LENGTH = 10_000


def _apply_truncation(content: str) -> str:
    """
    Truncate hook output to MAX_HOOK_OUTPUT_LENGTH.

    Mirrors TS applyTruncation() exactly.
    """
    if len(content) > _MAX_HOOK_OUTPUT_LENGTH:
        return (
            f"{content[:_MAX_HOOK_OUTPUT_LENGTH]}"
            f"\u2026 [output truncated - exceeded {_MAX_HOOK_OUTPUT_LENGTH} characters]"
        )
    return content


# ============================================================
# add_image_metadata_message
# ============================================================

def _add_image_metadata_message(
    result: ProcessUserInputResult,
    image_metadata_texts: List[str],
) -> ProcessUserInputResult:
    """
    Append image dimension metadata as a hidden (isMeta) user message.

    Mirrors TS addImageMetadataMessage() exactly.
    """
    if not image_metadata_texts:
        return result

    from ...utils.messages import create_user_message

    result.messages.append(
        create_user_message(
            content=[{"type": "text", "text": text} for text in image_metadata_texts],
            is_meta=True,
        )
    )
    return result


# ============================================================
# is_valid_image_paste (stub)
# ============================================================

def _is_valid_image_paste(content: Dict[str, Any]) -> bool:
    """
    Check if pasted content is a valid image.

    Stub: mirrors TS isValidImagePaste(). In the Python port this always
    returns False (no image paste support without IDE integration).
    """
    return False


# ============================================================
# process_user_input_base (inner logic)
# ============================================================

async def _process_user_input_base(
    input: Union[str, List[ContentBlockParam]],
    mode: PromptInputMode,
    context: Dict[str, Any],
    pasted_contents: Optional[Dict[int, Dict[str, Any]]] = None,
    ide_selection: Optional[Dict[str, Any]] = None,
    messages: Optional[List[Message]] = None,
    uuid_arg: Optional[str] = None,
    is_already_processing: bool = False,
    query_source: Optional[str] = None,
    can_use_tool: Optional[Callable[..., bool]] = None,
    permission_mode: Optional[str] = None,
    skip_slash_commands: bool = False,
    bridge_origin: bool = False,
    is_meta: bool = False,
    skip_attachments: bool = False,
    pre_expansion_input: Optional[str] = None,
) -> ProcessUserInputResult:
    """
    Core input processing logic (mirrors TS processUserInputBase).

    Handles:
    1. Input normalization (string vs. array, image resize)
    2. Pasted image processing
    3. Bridge-safe slash command override
    4. Ultraplan keyword detection and routing
    5. Attachment loading
    6. Slash command dispatch
    7. Bash mode (! prefix)
    8. Regular text prompt (via processTextPrompt)

    Args:
        input:           Raw user input (string or content blocks)
        mode:            'prompt' | 'bash' | 'task-notification'
        context:         ToolUseContext dict/dataclass
        pasted_contents: Pasted image/attachment data
        ide_selection:   Current IDE text selection
        messages:        Existing conversation messages
        uuid_arg:        Explicit UUID for the prompt
        is_already_processing: True for chained commands
        query_source:    Source of the query
        can_use_tool:    Tool permission checker
        permission_mode: Tool permission mode
        skip_slash_commands: Skip slash command parsing
        bridge_origin:   True if input came from mobile/web CCR
        is_meta:         Hide message from user (show to model only)
        skip_attachments: Skip attachment loading
        pre_expansion_input: Input before [Pasted text #N] expansion

    Returns:
        ProcessUserInputResult with messages, shouldQuery flag, etc.
    """
    input_string: Optional[str] = None
    preceding_input_blocks: List[ContentBlockParam] = []

    # Collect image metadata texts for isMeta message
    image_metadata_texts: List[str] = []

    # Normalized view of input (resized images for API compatibility)
    normalized_input: Union[str, List[ContentBlockParam]] = input

    # ---- String input ----
    if isinstance(input, str):
        input_string = input
    # ---- Array input (content blocks) ----
    elif len(input) > 0:
        processed_blocks: List[ContentBlockParam] = []

        for block in input:
            if block.get("type") == "image":
                # Resize image to fit API limits
                from ...utils.imageResizer import (
                    create_image_metadata_text,
                    maybe_resize_and_downsample_image_block,
                )

                resized = await maybe_resize_and_downsample_image_block(block)

                if resized.get("dimensions"):
                    dims = resized["dimensions"]
                    metadata_text = create_image_metadata_text(dims)
                    if metadata_text:
                        image_metadata_texts.append(metadata_text)

                processed_blocks.append(resized["block"])
            else:
                processed_blocks.append(block)

        normalized_input = processed_blocks

        # Extract text string from the last block for slash-command detection
        last_block = processed_blocks[-1] if processed_blocks else None
        if last_block and last_block.get("type") == "text":
            input_string = last_block.get("text")
            preceding_input_blocks = processed_blocks[:-1]
        else:
            preceding_input_blocks = processed_blocks

    if input_string is None and mode != "prompt":
        raise ValueError(f"Mode: {mode} requires a string input.")

    # ---- Process pasted images ----
    pasted_contents = pasted_contents or {}
    image_contents = [
        v for v in pasted_contents.values() if _is_valid_image_paste(v)
    ]
    image_paste_ids = [img.get("id") for img in image_contents if img.get("id")]

    # Store pasted images to disk (for AI agent tool reference)
    from ...utils.imageStore import store_images

    stored_image_paths = await store_images(pasted_contents)

    # Resize pasted images in parallel
    image_processing_results: List[Dict[str, Any]] = []
    if image_contents:
        from ...utils.imageResizer import (
            create_image_metadata_text,
            maybe_resize_and_downsample_image_block,
        )

        import asyncio

        async def process_one_pasted(pasted_image: Dict[str, Any]) -> Dict[str, Any]:
            image_block: ContentBlockParam = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": pasted_image.get("mediaType") or "image/png",
                    "data": pasted_image.get("content"),
                },
            }

            resized = await maybe_resize_and_downsample_image_block(image_block)

            # Fire-and-forget analytics
            try:
                from ...utils.system_prompt import log_event

                log_event(
                    "tengu_pasted_image_resize_attempt",
                    {"original_size_bytes": len(pasted_image.get("content", ""))},
                )
            except ImportError:
                pass

            source_path = pasted_image.get("sourcePath") or stored_image_paths.get(
                pasted_image.get("id")
            )
            return {
                "resized": resized,
                "original_dimensions": pasted_image.get("dimensions"),
                "source_path": source_path,
            }

        image_processing_results = await asyncio.gather(
            *[process_one_pasted(img) for img in image_contents]
        )

    # Build image content blocks and collect metadata
    image_content_blocks: List[ContentBlockParam] = []
    for result in image_processing_results:
        resized = result["resized"]
        original_dimensions = result["original_dimensions"]
        source_path = result["source_path"]

        if resized.get("dimensions"):
            from ...utils.imageResizer import create_image_metadata_text

            metadata_text = create_image_metadata_text(resized["dimensions"], source_path)
            if metadata_text:
                image_metadata_texts.append(metadata_text)
        elif original_dimensions:
            from ...utils.imageResizer import create_image_metadata_text

            metadata_text = create_image_metadata_text(original_dimensions, source_path)
            if metadata_text:
                image_metadata_texts.append(metadata_text)
        elif source_path:
            image_metadata_texts.append(f"[Image source: {source_path}]")

        image_content_blocks.append(resized["block"])

    # ---- Bridge-safe slash command override ----
    effective_skip_slash = skip_slash_commands
    if bridge_origin and input_string is not None and input_string.startswith("/"):
        from ...utils.slashCommandParsing import parse_slash_command

        parsed = parse_slash_command(input_string)
        if parsed:
            # Resolve command name (stub — commands registry not yet ported)
            cmd = _find_command(parsed.command_name, context)
            if cmd:
                if _is_bridge_safe_command(cmd):
                    effective_skip_slash = False
                else:
                    # Command not available over Remote Control
                    from ...utils.messages import (
                        create_command_input_message,
                        create_user_message,
                    )

                    msg = f"/{parsed.command_name} isn't available over Remote Control."
                    return _add_image_metadata_message(
                        ProcessUserInputResult(
                            messages=[
                                create_user_message(content=input_string, uuid=uuid_arg),
                                create_command_input_message(
                                    f"<local-command-stdout>{msg}</local-command-stdout>"
                                ),
                            ],
                            should_query=False,
                            result_text=msg,
                        ),
                        image_metadata_texts,
                    )

    # ---- Ultraplan keyword routing ----
    # In Python, ultraplan feature is disabled (requires React UI integration)
    # NOTE: feature('ULTRAPLAN') always returns False in Python port.
    # To enable ultraplan in Python, replace this with a config flag check.
    ultraplan_enabled = False
    if (
        ultraplan_enabled
        and mode == "prompt"
        and not _is_non_interactive_session(context)
        and input_string is not None
        and not effective_skip_slash
        and not input_string.startswith("/")
        and not _get_app_state(context).get("ultraplanSessionUrl")
        and not _get_app_state(context).get("ultraplanLaunching")
        and _has_ultraplan_keyword(pre_expansion_input or input_string)
    ):

        log_event("tengu_ultraplan_keyword", {})

        from ...utils.ultraplan.keyword import replace_ultraplan_keyword

        rewritten = replace_ultraplan_keyword(input_string).strip()

        # Dynamic import: processSlashCommand
        from .processSlashCommand import process_slash_command

        slash_result = await process_slash_command(
            f"/ultraplan {rewritten}",
            preceding_input_blocks,
            image_content_blocks,
            [],
            context,
            None,  # setToolJSX
            uuid_arg,
            is_already_processing,
            can_use_tool,
        )
        return _add_image_metadata_message(slash_result, image_metadata_texts)

    # ---- Attachment loading ----
    should_extract_attachments = (
        not skip_attachments
        and input_string is not None
        and (mode != "prompt" or effective_skip_slash or not input_string.startswith("/"))
    )

    attachment_messages: List[Message] = []
    if should_extract_attachments:
        from ...utils.generators import to_array

        async def _gen_attachments() -> AsyncGenerator[Message, None]:
            from ...utils.attachments import get_attachment_messages

            async for msg in get_attachment_messages(
                input_string,
                context,
                ide_selection,
                [],
                messages or [],
                query_source,
            ):
                yield msg

        attachment_messages = await to_array(_gen_attachments())

    # ---- Bash mode ----
    if input_string is not None and mode == "bash":
        from .processBashCommand import process_bash_command

        bash_result = await process_bash_command(
            input_string,
            preceding_input_blocks,
            attachment_messages,
            context,
            None,  # setToolJSX
        )
        return _add_image_metadata_message(bash_result, image_metadata_texts)

    # ---- Slash commands ----
    if (
        input_string is not None
        and not effective_skip_slash
        and input_string.startswith("/")
    ):
        from .processSlashCommand import process_slash_command

        slash_result = await process_slash_command(
            input_string,
            preceding_input_blocks,
            image_content_blocks,
            attachment_messages,
            context,
            None,  # setToolJSX
            uuid_arg,
            is_already_processing,
            can_use_tool,
        )
        return _add_image_metadata_message(slash_result, image_metadata_texts)

    # ---- Agent mention logging ----
    if input_string is not None and mode == "prompt":
        trimmed = input_string.strip()

        agent_mention_msg = next(
            (
                m
                for m in attachment_messages
                if m.get("type") == "attachment"
                and m.get("attachment", {}).get("type") == "agent_mention"
            ),
            None,
        )

        if agent_mention_msg:
            attachment_data = agent_mention_msg.get("attachment", {})
            agent_mention_string = f"@agent-{attachment_data.get('agentType', '')}"
            is_subagent_only = trimmed == agent_mention_string
            is_prefix = trimmed.startswith(agent_mention_string) and not is_subagent_only

            try:
                from ...utils.system_prompt import log_event

                log_event(
                    "tengu_subagent_at_mention",
                    {
                        "is_subagent_only": is_subagent_only,
                        "is_prefix": is_prefix,
                    },
                )
            except ImportError:
                pass

    # ---- Regular user prompt ----
    from .processTextPrompt import process_text_prompt

    text_result = process_text_prompt(
        normalized_input,
        image_content_blocks,
        image_paste_ids,
        attachment_messages,
        uuid_arg=uuid_arg,
        permission_mode=permission_mode,
        is_meta=is_meta,
    )

    result = ProcessUserInputResult(
        messages=text_result.get("messages", []),
        should_query=text_result.get("shouldQuery", True),
    )

    return _add_image_metadata_message(result, image_metadata_texts)


# ============================================================
# Command resolution stubs (stub until full command system is ported)
# ============================================================

def _find_command(name: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Find a command by name from the context's command registry.

    Stub: returns None. Full command registry resolution not yet ported.
    """
    # TODO: integrate with the full command system once it's ported
    return None


def _is_bridge_safe_command(cmd: Dict[str, Any]) -> bool:
    """
    Check if a command is safe to run over Remote Control.

    Stub: returns False for all commands. Full safety check not yet ported.
    """
    return False


# ============================================================
# ultraplan keyword check (stub — imported from ultraplan package)
# ============================================================

def _has_ultraplan_keyword(text: str) -> bool:
    try:
        from ...utils.ultraplan.keyword import has_ultraplan_keyword

        return has_ultraplan_keyword(text)
    except ImportError:
        return False


# ============================================================
# process_user_input (top-level function)
# ============================================================

async def process_user_input(
    *,
    input: Union[str, List[ContentBlockParam]],
    pre_expansion_input: Optional[str] = None,
    mode: PromptInputMode,
    context: Dict[str, Any],
    pasted_contents: Optional[Dict[int, Dict[str, Any]]] = None,
    ide_selection: Optional[Dict[str, Any]] = None,
    messages: Optional[List[Message]] = None,
    set_user_input_on_processing: Optional[Callable[[Optional[str]], None]] = None,
    uuid_arg: Optional[str] = None,
    is_already_processing: bool = False,
    query_source: Optional[str] = None,
    can_use_tool: Optional[Callable[..., bool]] = None,
    skip_slash_commands: bool = False,
    bridge_origin: bool = False,
    is_meta: bool = False,
    skip_attachments: bool = False,
) -> ProcessUserInputResult:
    """
    Process user input and return messages ready for the query loop.

    Mirrors TS processUserInput() exactly.

    Entry point for all user input handling in the Python agentic IDE.
    Coordinates:
    1. Input normalization and image processing (via _process_user_input_base)
    2. setUserInputOnProcessing (shows input while processing)
    3. UserPromptSubmit hooks (blocking, stop, additional context)

    Args:
        input:            Raw user input (string or content blocks)
        pre_expansion_input: Input before [Pasted text #N] expansion
        mode:             'prompt' | 'bash' | 'task-notification'
        context:          ToolUseContext dict/dataclass
        pasted_contents:  Pasted image/attachment data
        ide_selection:    Current IDE text selection
        messages:         Existing conversation messages
        set_user_input_on_processing: Callback to show input while processing
        uuid_arg:         Explicit UUID for the prompt
        is_already_processing: True for chained commands (not the first)
        query_source:     Source of the query
        can_use_tool:     Tool permission checker
        skip_slash_commands: Skip slash command parsing (for CCR input)
        bridge_origin:    True if input came from mobile/web CCR
        is_meta:          Hide message from user (model-visible only)
        skip_attachments: Skip attachment loading (for non-first commands)

    Returns:
        ProcessUserInputResult with messages, shouldQuery, allowedTools, model, etc.
    """
    input_string = input if isinstance(input, str) else None

    # Show user input immediately (skip for isMeta system-generated prompts)
    if mode == "prompt" and input_string is not None and not is_meta:
        set_user_input_on_processing and set_user_input_on_processing(input_string)

    # Get app state for permission mode
    app_state = _get_app_state(context)
    permission_mode = _get_permission_mode(context)

    # Run base processing
    result = await _process_user_input_base(
        input=input,
        mode=mode,
        context=context,
        pasted_contents=pasted_contents,
        ide_selection=ide_selection,
        messages=messages,
        uuid_arg=uuid_arg,
        is_already_processing=is_already_processing,
        query_source=query_source,
        can_use_tool=can_use_tool,
        permission_mode=permission_mode,
        skip_slash_commands=skip_slash_commands,
        bridge_origin=bridge_origin,
        is_meta=is_meta,
        skip_attachments=skip_attachments,
        pre_expansion_input=pre_expansion_input,
    )

    if not result.should_query:
        return result

    # ---- Execute UserPromptSubmit hooks ----
    # Get text from input for hook evaluation
    input_text = _get_input_text(input)

    async def _run_hooks() -> AsyncGenerator[Dict[str, Any], None]:
        from ...utils.hooks import execute_user_prompt_submit_hooks

        async for hook_result in execute_user_prompt_submit_hooks(
            input_text,
            permission_mode,
            context,
            None,  # requestPrompt — not used in stub
        ):
            yield hook_result

    from ...utils.generators import to_array

    hook_results = await to_array(_run_hooks())

    for hook_result in hook_results:
        # Skip progress messages
        if (
            hook_result.get("message")
            and hook_result["message"].get("type") == "progress"
        ):
            continue

        # Blocking error — abort with system message
        if hook_result.get("blocking_error"):
            from ...utils.hooks import get_user_prompt_submit_hook_blocking_message
            from ...utils.messages import create_system_message

            blocking_msg = get_user_prompt_submit_hook_blocking_message(
                hook_result["blocking_error"]
            )

            # Resolve input text for the warning
            input_display = input_text or ""

            return ProcessUserInputResult(
                messages=[
                    create_system_message(
                        f"{blocking_msg}\n\nOriginal prompt: {input_display}",
                        level="warning",
                    ),
                ],
                should_query=False,
                allowed_tools=result.allowed_tools,
            )

        # Prevent continuation (hook stopped the operation)
        if hook_result.get("prevent_continuation"):
            from ...utils.messages import create_user_message

            stop_reason = hook_result.get("stop_reason")
            msg_text = (
                f"Operation stopped by hook: {stop_reason}"
                if stop_reason
                else "Operation stopped by hook"
            )

            result.messages.append(
                create_user_message(content=[{"type": "text", "text": msg_text}])
            )
            result.should_query = False
            return result

        # Additional contexts from hook
        additional_contexts = hook_result.get("additional_contexts")
        if additional_contexts and len(additional_contexts) > 0:
            from ...utils.attachments import create_attachment_message

            hook_msg = hook_result.get("message")
            if hook_msg and hook_msg.get("type") == "attachment":
                attachment = hook_msg.get("attachment", {})
                hook_type = attachment.get("type")

                if hook_type == "hook_success":
                    hook_content = attachment.get("content")
                    if hook_content:
                        result.messages.append(
                            {
                                **hook_msg,
                                "attachment": {
                                    **attachment,
                                    "content": _apply_truncation(hook_content),
                                },
                            }
                        )
                    # Skip if no content
                else:
                    result.messages.append(hook_msg)

    return result


# ============================================================
# _get_input_text — extract text string from input
# ============================================================

def _get_input_text(input: Union[str, List[ContentBlockParam]]) -> str:
    """Extract text string from input for hook evaluation."""
    if isinstance(input, str):
        return input
    for block in reversed(input):
        if block.get("type") == "text":
            return block.get("text", "")
    return ""
