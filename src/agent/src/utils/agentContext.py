"""
Agent Context Management - Handles agent identity tracking across async operations.
TypeScript source: utils/agentContext.ts (179 lines)
Provides context isolation for concurrent agents using contextvars (Python's AsyncLocalStorage equivalent).

Supports two agent types:
1. Subagents (Agent tool): Run in-process for quick, delegated tasks
2. In-process teammates: Part of a swarm with team coordination

WHY contextvars (not global state):
When agents are backgrounded, multiple agents can run concurrently in the same process.
Global state would be overwritten, causing Agent A's events to incorrectly use Agent B's context.
contextvars isolates each async execution chain, so concurrent agents don't interfere.
"""

import os
from typing import Optional, Dict, Any, Literal, Union, TypedDict
from contextvars import ContextVar

# ============================================================
# PHASE 1: Imports & Type Definitions
# ============================================================

try:
    from utils.agentSwarmsEnabled import isAgentSwarmsEnabled
except ImportError:
    def isAgentSwarmsEnabled() -> bool:
        """Stub - checks if agent swarms are enabled"""
        return False


# ============================================================
# Type Definitions (TypedDict for TypeScript interface compatibility)
# ============================================================

class SubagentContext(TypedDict, total=False):
    """
    Context for subagents (Agent tool agents).
    Subagents run in-process for quick, delegated tasks.
    """
    # The subagent's UUID (from createAgentId())
    agentId: str
    # The team lead's session ID (from CLAUDE_CODE_PARENT_SESSION_ID env var)
    parentSessionId: Optional[str]
    # Agent type - 'subagent' for Agent tool agents
    agentType: Literal['subagent']
    # The subagent's type name (e.g., "Explore", "Bash", "code-reviewer")
    subagentName: Optional[str]
    # Whether this is a built-in agent (vs user-defined custom agent)
    isBuiltIn: Optional[bool]
    # The request_id in the invoking agent that spawned or resumed this agent
    invokingRequestId: Optional[str]
    # Whether this invocation is the initial spawn or a subsequent resume
    invocationKind: Optional[Literal['spawn', 'resume']]
    # Mutable flag: has this invocation's edge been emitted to telemetry yet?
    invocationEmitted: Optional[bool]


class TeammateAgentContext(TypedDict, total=False):
    """
    Context for in-process teammates.
    Teammates are part of a swarm and have team coordination.
    """
    # Full agent ID, e.g., "researcher@my-team"
    agentId: str
    # Display name, e.g., "researcher"
    agentName: str
    # Team name this teammate belongs to
    teamName: str
    # UI color assigned to this teammate
    agentColor: Optional[str]
    # Whether teammate must enter plan mode before implementing
    planModeRequired: bool
    # The team lead's session ID for transcript correlation
    parentSessionId: str
    # Whether this agent is the team lead
    isTeamLead: bool
    # Agent type - 'teammate' for swarm teammates
    agentType: Literal['teammate']
    # The request_id in the invoking agent that spawned or resumed this teammate
    invokingRequestId: Optional[str]
    # Whether this invocation is the initial spawn or a subsequent resume
    invocationKind: Optional[Literal['spawn', 'resume']]
    # Mutable flag: has this invocation's edge been emitted to telemetry yet?
    invocationEmitted: Optional[bool]


# Discriminated union for agent context
# Use agentType to distinguish between subagent and teammate contexts
AgentContext = Union[SubagentContext, TeammateAgentContext]

# Analytics metadata type alias
AnalyticsMetadata = str


# ============================================================
# PHASE 2: Context Storage (AsyncLocalStorage equivalent)
# ============================================================

# Python's contextvars.ContextVar is the equivalent of Node.js AsyncLocalStorage
# It provides async-context-local storage that isolates data per async task
_agent_context_var: ContextVar[Optional[AgentContext]] = ContextVar(
    'agent_context',
    default=None
)


# ============================================================
# PHASE 3: Core Context Functions
# ============================================================

def getAgentContext() -> Optional[AgentContext]:
    """
    Get the current agent context, if any.
    
    Returns None if not running within an agent context (subagent or teammate).
    Use type guards isSubagentContext() or isTeammateAgentContext() to narrow the type.
    
    TS lines 100-102
    """
    return _agent_context_var.get()


def runWithAgentContext(context: AgentContext, fn) -> Any:
    """
    Run an async function with the given agent context.
    All async operations within the function will have access to this context.
    
    This is the equivalent of TypeScript's agentContextStorage.run(context, fn).
    In Python, we use contextvars.ContextVar.set() to establish the context.
    
    TS lines 108-110
    """
    # Set the context for the current async task
    token = _agent_context_var.set(context)
    try:
        # Execute the function
        result = fn()
        # If it's a coroutine, we need to handle it differently
        import asyncio
        if asyncio.iscoroutine(result):
            raise TypeError(
                "runWithAgentContext doesn't support async functions directly. "
                "Use 'async with agent_context_manager(context):' instead."
            )
        return result
    finally:
        # Restore the previous context
        _agent_context_var.reset(token)


class AgentContextManager:
    """
    Async context manager for agent context.
    Use this for async functions that need agent context.
    
    Example:
        async def my_async_function():
            async with AgentContextManager(context):
                # Your async code here
                pass
    """
    def __init__(self, context: AgentContext):
        self.context = context
        self._token = None
    
    async def __aenter__(self):
        self._token = _agent_context_var.set(self.context)
        return self.context
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._token is not None:
            _agent_context_var.reset(self._token)
        return False


# ============================================================
# PHASE 4: Type Guards
# ============================================================

def isSubagentContext(context: Optional[AgentContext]) -> bool:
    """
    Type guard to check if context is a SubagentContext.
    
    TS lines 115-119
    """
    if context is None:
        return False
    return context.get('agentType') == 'subagent'


def isTeammateAgentContext(context: Optional[AgentContext]) -> bool:
    """
    Type guard to check if context is a TeammateAgentContext.
    
    TS lines 124-131
    """
    if isAgentSwarmsEnabled():
        if context is None:
            return False
        return context.get('agentType') == 'teammate'
    return False


# ============================================================
# PHASE 5: Utility Functions
# ============================================================

def getSubagentLogName() -> Optional[AnalyticsMetadata]:
    """
    Get the subagent name suitable for analytics logging.
    Returns the agent type name for built-in agents, "user-defined" for custom agents,
    or None if not running within a subagent context.
    
    Safe for analytics metadata: built-in agent names are code constants,
    and custom agents are always mapped to the literal "user-defined".
    
    TS lines 141-151
    """
    context = getAgentContext()
    if not isSubagentContext(context) or not context.get('subagentName'):
        return None
    
    # Type narrowing: context is guaranteed to be SubagentContext here
    # but we still use .get() for safety with TypedDict
    if context.get('isBuiltIn'):
        return context.get('subagentName')
    else:
        return 'user-defined'


def consumeInvokingRequestId() -> Optional[Dict[str, Any]]:
    """
    Get the invoking request_id for the current agent context — once per
    invocation. Returns the id on the first call after a spawn/resume, then
    None until the next boundary. Also None on the main thread or
    when the spawn path had no request_id.
    
    Sparse edge semantics: invokingRequestId appears on exactly one
    tengu_api_success/error per invocation, so a non-NULL value downstream
    marks a spawn/resume boundary.
    
    TS lines 163-178
    """
    context = getAgentContext()
    
    # Check if context exists and has invokingRequestId
    if context is None:
        return None
    
    invoking_request_id = context.get('invokingRequestId')
    invocation_emitted = context.get('invocationEmitted', False)
    
    if not invoking_request_id or invocation_emitted:
        return None
    
    # Mark as emitted (mutable state)
    context['invocationEmitted'] = True
    
    return {
        'invokingRequestId': invoking_request_id,
        'invocationKind': context.get('invocationKind'),
    }


# ============================================================
# Module Exports
# ============================================================

__all__ = [
    # Types
    'SubagentContext',
    'TeammateAgentContext',
    'AgentContext',
    'AnalyticsMetadata',
    
    # Core functions
    'getAgentContext',
    'runWithAgentContext',
    'AgentContextManager',
    
    # Type guards
    'isSubagentContext',
    'isTeammateAgentContext',
    
    # Utility functions
    'getSubagentLogName',
    'consumeInvokingRequestId',
]
