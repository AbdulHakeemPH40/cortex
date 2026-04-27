"""
Branded types for session and agent IDs.
These prevent accidentally mixing up session IDs and agent IDs at runtime.
"""

from typing import NewType

# ============================================================================
# Branded Types
# ============================================================================

#: A session ID uniquely identifies a Claude Code session.
#: Returned by getSessionId().
SessionId = NewType('SessionId', str)

#: An agent ID uniquely identifies a subagent within a session.
#: Returned by createAgentId().
#: When present, indicates the context is a subagent (not the main session).
AgentId = NewType('AgentId', str)

#: A task ID uniquely identifies a task.
TaskId = NewType('TaskId', str)

#: A tool use ID uniquely identifies a tool use.
ToolUseId = NewType('ToolUseId', str)

#: A message ID uniquely identifies a message.
MessageId = NewType('MessageId', str)


# ============================================================================
# Type Casting Functions
# ============================================================================

def as_session_id(id: str) -> SessionId:
    """
    Cast a raw string to SessionId.
    Use sparingly - prefer getSessionId() when possible.
    """
    return SessionId(id)


def as_agent_id(id: str) -> AgentId:
    """
    Cast a raw string to AgentId.
    Use sparingly - prefer createAgentId() when possible.
    """
    return AgentId(id)


#: Pattern for validating agent IDs
#: Matches format: `a` + optional `<label>-` + 16 hex chars
AGENT_ID_PATTERN = r'^a(?:.+-)?[0-9a-f]{16}$'


def to_agent_id(s: str) -> AgentId | None:
    """
    Validate and brand a string as AgentId.
    Matches the format produced by createAgentId(): `a` + optional `<label>-` + 16 hex chars.
    Returns None if the string doesn't match (e.g. teammate names, team-addressing).
    """
    import re
    if re.match(AGENT_ID_PATTERN, s):
        return AgentId(s)
    return None


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# Alias for backward compatibility with existing Python code
asAgentId = as_agent_id
asSessionId = as_session_id


__all__ = [
    # Types
    'SessionId',
    'AgentId',
    'TaskId',
    'ToolUseId',
    'MessageId',
    # Functions
    'as_session_id',
    'as_agent_id',
    'to_agent_id',
    # Aliases
    'asAgentId',
    'asSessionId',
    # Constants
    'AGENT_ID_PATTERN',
]
