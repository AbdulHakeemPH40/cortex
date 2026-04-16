"""
services/MagicDocs/magicDocs.py
Python conversion of services/MagicDocs/magicDocs.ts (255 lines)

Magic Docs automatically maintains markdown documentation files marked with special headers.
When a file with "# MAGIC DOC: [title]" is read, it runs periodically in the background
using a forked subagent to update the document with new learnings from the conversation.

See docs/magic-docs.md for more information.
"""

import asyncio
import os
from typing import Any, Callable, Dict, List, Optional

from services.MagicDocs.prompts import (
    build_magic_docs_update_prompt,
    detect_magic_doc_header,
    register_magic_doc,
    clear_tracked_magic_docs,
    _tracked_magic_docs,
)


# File edit tool name constant (should match your implementation)
FILE_EDIT_TOOL_NAME = 'Edit'


async def get_magic_docs_agent() -> Dict[str, Any]:
    """
    Create Magic Docs agent definition.
    
    Returns:
        Agent definition dict for the magic-docs subagent
    """
    return {
        'agentType': 'magic-docs',
        'whenToUse': 'Update Magic Docs',
        'tools': [FILE_EDIT_TOOL_NAME],  # Only allow Edit
        'model': 'sonnet',
        'source': 'built-in',
        'baseDir': 'built-in',
        'getSystemPrompt': lambda: '',  # Will use override systemPrompt
    }


async def update_magic_doc(
    doc_info: Dict[str, str],
    context: Dict[str, Any],
) -> None:
    """
    Update a single Magic Doc.
    
    Args:
        doc_info: Magic doc info dict with 'path' key
        context: REPL hook context with messages, systemPrompt, userContext, etc.
    """
    messages = context.get('messages', [])
    system_prompt = context.get('systemPrompt', '')
    user_context = context.get('userContext')
    system_context = context.get('systemContext')
    tool_use_context = context.get('toolUseContext', {})
    
    # Clone the FileStateCache to isolate Magic Docs operations. Delete this
    # doc's entry so FileReadTool's dedup doesn't return a file_unchanged
    # stub — we need the actual content to re-detect the header.
    # NOTE: This requires your fileStateCache implementation
    from services.utils.fileStateCache import clone_file_state_cache
    cloned_read_file_state = clone_file_state_cache(tool_use_context.get('readFileState', {}))
    doc_path = doc_info['path']
    cloned_read_file_state.pop(doc_path, None)
    
    cloned_tool_use_context = {
        **tool_use_context,
        'readFileState': cloned_read_file_state,
    }
    
    # Read the document; if deleted or unreadable, remove from tracking
    current_doc = ''
    try:
        # NOTE: Requires FileReadTool implementation
        from services.tools.fileReadTool import FileReadTool
        result = await FileReadTool.call(
            {'file_path': doc_path},
            cloned_tool_use_context,
        )
        output = result.get('data', {})
        if output.get('type') == 'text':
            current_doc = output.get('file', {}).get('content', '')
    except Exception as e:
        # FileReadTool wraps ENOENT in a plain Error("File does not exist...") with
        # no .code, so check the message in addition to is_fs_inaccessible (EACCES/EPERM).
        error_msg = str(e).lower()
        if is_fs_inaccessible(e) or 'file does not exist' in error_msg:
            _tracked_magic_docs.pop(doc_path, None)
            return
        raise
    
    # Re-detect title and instructions from latest file content
    detected = detect_magic_doc_header(current_doc)
    if detected is None:
        # File no longer has magic doc header, remove from tracking
        _tracked_magic_docs.pop(doc_path, None)
        return
    
    # Build update prompt with latest title and instructions
    user_prompt = await build_magic_docs_update_prompt(
        current_doc,
        doc_path,
        detected.get('title', ''),
        detected.get('instructions'),
    )
    
    # Create a custom canUseTool that only allows Edit for magic doc files
    async def can_use_tool(tool: Any, tool_input: Any) -> Dict[str, Any]:
        tool_name = getattr(tool, 'name', None)
        if (
            tool_name == FILE_EDIT_TOOL_NAME and
            isinstance(tool_input, dict) and
            'file_path' in tool_input
        ):
            file_path = tool_input['file_path']
            if isinstance(file_path, str) and file_path == doc_path:
                return {'behavior': 'allow', 'updatedInput': tool_input}
        
        return {
            'behavior': 'deny',
            'message': f'only {FILE_EDIT_TOOL_NAME} is allowed for {doc_path}',
            'decisionReason': {
                'type': 'other',
                'reason': f'only {FILE_EDIT_TOOL_NAME} is allowed',
            },
        }
    
    # Run Magic Docs update using runAgent with forked context
    # NOTE: Requires runAgent implementation
    from services.tools.agentTool.runAgent import run_agent
    agent_def = await get_magic_docs_agent()
    
    async for _message in run_agent(
        agent_definition=agent_def,
        prompt_messages=[create_user_message(user_prompt)],
        tool_use_context=cloned_tool_use_context,
        can_use_tool=can_use_tool,
        is_async=True,
        fork_context_messages=messages,
        query_source='magic_docs',
        override={
            'systemPrompt': system_prompt,
            'userContext': user_context,
            'systemContext': system_context,
        },
        available_tools=cloned_tool_use_context.get('options', {}).get('tools', []),
    ):
        # Just consume - let it run to completion
        pass


def is_fs_inaccessible(error: Exception) -> bool:
    """Check if filesystem error is EACCES or EPERM."""
    error_msg = str(error).lower()
    return 'permission denied' in error_msg or 'access denied' in error_msg


def create_user_message(content: str) -> Dict[str, str]:
    """Create a user message dict."""
    return {'role': 'user', 'content': content}


def has_tool_calls_in_last_assistant_turn(messages: List[Dict[str, Any]]) -> bool:
    """Check if there are tool calls in the last assistant turn."""
    # Find last assistant message
    for msg in reversed(messages):
        if msg.get('role') == 'assistant':
            # Check if it has tool_calls
            return 'tool_calls' in msg or 'toolCalls' in msg
    return False


# Module-level lock for sequential execution
_sequential_lock = asyncio.Lock()


def sequential(func):
    """
    Decorator to ensure sequential execution of async functions.
    
    Uses a module-level lock to prevent concurrent execution.
    """
    async def wrapper(*args, **kwargs):
        async with _sequential_lock:
            return await func(*args, **kwargs)
    
    return wrapper


# Magic Docs post-sampling hook that updates all tracked Magic Docs
@sequential
async def update_magic_docs(context: Dict[str, Any]) -> None:
    """
    Magic Docs post-sampling hook that updates all tracked Magic Docs.
    Only runs when conversation is idle (no tool calls in last turn).
    """
    messages = context.get('messages', [])
    query_source = context.get('querySource', '')
    
    if query_source != 'repl_main_thread':
        return
    
    # Only update when conversation is idle (no tool calls in last turn)
    has_tool_calls = has_tool_calls_in_last_assistant_turn(messages)
    if has_tool_calls:
        return
    
    doc_count = len(_tracked_magic_docs)
    if doc_count == 0:
        return
    
    for doc_info in list(_tracked_magic_docs.values()):
        await update_magic_doc(doc_info, context)


def register_file_read_listener(callback: Callable[[str, str], None]) -> None:
    """
    Register a listener for file read events.
    
    Args:
        callback: Function called with (file_path, content) when file is read
    """
    # NOTE: This needs to be connected to your file read event system
    # Placeholder - implement based on your architecture
    pass


def register_post_sampling_hook(hook_func: Callable) -> None:
    """
    Register a post-sampling hook.
    
    Args:
        hook_func: Async function to call after sampling completes
    """
    # NOTE: This needs to be connected to your hook system
    # Placeholder - implement based on your architecture
    pass


async def init_magic_docs() -> None:
    """
    Initialize Magic Docs system.
    Only activates if USER_TYPE environment variable is 'ant'.
    """
    if os.environ.get('USER_TYPE') == 'ant':
        # Register listener to detect magic docs when files are read
        def on_file_read(file_path: str, content: str) -> None:
            result = detect_magic_doc_header(content)
            if result is not None:
                register_magic_doc(file_path)
        
        register_file_read_listener(on_file_read)
        register_post_sampling_hook(update_magic_docs)


__all__ = [
    'update_magic_doc',
    'update_magic_docs',
    'init_magic_docs',
    'clear_tracked_magic_docs',
    'detect_magic_doc_header',
    'register_magic_doc',
]
