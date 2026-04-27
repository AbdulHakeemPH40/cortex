"""
Message type definitions for the Cortex AI Agent IDE.

This module defines types for messages passed between the user, assistant,
and tools in the conversation.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

# ============================================================================
# Base Message Types
# ============================================================================

class Message(TypedDict, total=False):
    """
    Base message type for all messages in the conversation.
    """
    type: str
    role: str
    content: Any
    id: str


class UserMessage(TypedDict, total=False):
    """A message from the user."""
    type: Literal['user']
    role: Literal['user']
    content: str
    id: str


class AssistantMessage(TypedDict, total=False):
    """A message from the assistant."""
    type: Literal['assistant']
    role: Literal['assistant']
    content: str
    id: str


class SystemMessage(TypedDict, total=False):
    """A system message."""
    type: Literal['system']
    role: Literal['system']
    content: str
    id: str


class NormalizedUserMessage(TypedDict, total=False):
    """A normalized user message."""
    type: str
    role: str
    content: Any
    id: str


# ============================================================================
# Progress and Status Messages
# ============================================================================

class ProgressMessage(TypedDict, total=False):
    """A progress message for long-running operations."""
    type: Literal['progress']
    role: str
    content: str
    id: str


class StopHookInfo(TypedDict, total=False):
    """Information about a stop hook."""
    type: Literal['stop_hook']
    hook_name: str
    hook_source: Optional[str]


# ============================================================================
# Attachment Messages
# ============================================================================

class AttachmentMessage(TypedDict, total=False):
    """A message containing an attachment."""
    type: Literal['attachment']
    role: str
    content: Dict[str, Any]
    id: str
    attachment: Dict[str, Any]


# ============================================================================
# Stream Events
# ============================================================================

class RequestStartEvent(TypedDict, total=False):
    """Event indicating the start of a request."""
    type: Literal['request_start']
    request_id: str
    timestamp: str


class StreamEvent(TypedDict, total=False):
    """A streaming event from the assistant."""
    type: Literal['stream_event']
    event_type: str
    data: Any
    timestamp: str


# ============================================================================
# System Messages
# ============================================================================

class SystemCompactBoundaryMessage(TypedDict, total=False):
    """A system message marking a compact boundary."""
    type: Literal['system_compact_boundary']
    role: Literal['system']
    content: str
    id: str
    boundary_id: str


class ToolUseSummaryMessage(TypedDict, total=False):
    """A summary of tool usage."""
    type: Literal['tool_use_summary']
    role: str
    content: str
    id: str
    tool_name: str
    tool_input: Dict[str, Any]
    tool_output: Any


class TombstoneMessage(TypedDict, total=False):
    """A tombstone message marking a deleted/compacted message."""
    type: Literal['tombstone']
    role: str
    content: str
    id: str
    original_message_id: str


# ============================================================================
# Union Types
# ============================================================================

# Any message type in the conversation
ConversationMessage = Union[
    UserMessage,
    AssistantMessage,
    SystemMessage,
    ProgressMessage,
    AttachmentMessage,
    SystemCompactBoundaryMessage,
    ToolUseSummaryMessage,
    TombstoneMessage,
]


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# Alias for backward compatibility with existing code
MessageType = Message


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Base types
    'Message',
    'UserMessage',
    'AssistantMessage',
    'SystemMessage',
    'NormalizedUserMessage',
    # Progress and status
    'ProgressMessage',
    'StopHookInfo',
    # Attachments
    'AttachmentMessage',
    # Stream events
    'RequestStartEvent',
    'StreamEvent',
    # System messages
    'SystemCompactBoundaryMessage',
    'ToolUseSummaryMessage',
    'TombstoneMessage',
    # Union types
    'ConversationMessage',
    # Aliases
    'MessageType',
]
