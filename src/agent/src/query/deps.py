# ------------------------------------------------------------
# deps.py (query)
# Python conversion of query/deps.ts
#
# I/O dependency injection for query().
#
# `deps` parameter lets tests inject fakes without per-module spy boilerplate.
# The production factory wires in real implementations (Claude API).
# The stub factory returns async generators that yield nothing.
#
# Scope is intentionally narrow (4 deps) to prove the pattern.
# Follow-up PRs can add runTools, handleStopHooks, logEvent, queue ops, etc.
# ------------------------------------------------------------

import asyncio
import uuid as _uuid
from typing import Any, AsyncGenerator, Dict, List

__all__ = ["production_deps", "QueryDeps", "QueryDepsStub"]


# ============================================================
# Type aliases (match TS callModel signature)
# ============================================================

CallModelParams = Dict[str, Any]
StreamEvent = Dict[str, Any]


# ============================================================
# QueryDeps protocol
# ============================================================

class QueryDeps:
    """
    Protocol: I/O dependencies for query().

    Mirrors TS QueryDeps exactly.
    Defines the interface for:
    - callModel: Streaming LLM API call
    - microcompact: Context micro-compaction
    - autocompact: Automatic context compaction when near limit
    - uuid: UUID generator
    """

    def call_model(
        self,
        *,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tools: List[Dict[str, Any]],
        signal: Any,
        options: Dict[str, Any],
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Make a streaming API call to an LLM.

        Yields stream events as they arrive. The caller iterates with
        `async for event in deps.call_model(...)`.

        Args:
            messages: Conversation history
            system_prompt: System prompt
            tools: Tool definitions
            signal: Abort signal
            options: Model and API options

        Yields:
            StreamEvent dicts: assistant messages, tool_use blocks, errors, etc.
        """
        ...

    def microcompact(
        self,
        messages: List[Dict[str, Any]],
        tool_context: Dict[str, Any],
        query_source: str,
    ) -> Dict[str, Any]:
        """
        Apply micro-compaction to messages (prompt caching optimization).

        Returns:
            Dict with 'messages' (compacted) and 'compactionInfo' (optional cache metadata)
        """
        ...

    def autocompact(
        self,
        messages: List[Dict[str, Any]],
        tool_context: Dict[str, Any],
        fork_context: Dict[str, Any],
        query_source: str,
        tracking: Any,
        snip_tokens_freed: int,
    ) -> Dict[str, Any]:
        """
        Run automatic compaction if context is near the limit.

        Returns:
            Dict with 'compactionResult' (if compaction ran) and 'consecutiveFailures'
        """
        ...

    def uuid(self) -> str:
        """Generate a random UUID string."""
        ...


# ============================================================
# Stub implementation (no real API calls)
# ============================================================

class QueryDepsStub(QueryDeps):
    """
    Stub deps that return empty/zero results.

    Use for testing or when API layer is not yet implemented.
    """

    async def call_model(
        self,
        *,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tools: List[Dict[str, Any]],
        signal: Any,
        options: Dict[str, Any],
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Stub: yields nothing. Replace with real multi-LLM provider implementation.
        """
        return
        yield  # type: ignore[unreachable]

    def microcompact(
        self,
        messages: List[Dict[str, Any]],
        tool_context: Dict[str, Any],
        query_source: str,
    ) -> Dict[str, Any]:
        """Stub: returns messages unchanged."""
        return {
            "messages": messages,
            "compactionInfo": None,
        }

    def autocompact(
        self,
        messages: List[Dict[str, Any]],
        tool_context: Dict[str, Any],
        fork_context: Dict[str, Any],
        query_source: str,
        tracking: Any,
        snip_tokens_freed: int,
    ) -> Dict[str, Any]:
        """Stub: returns no compaction result."""
        return {
            "compactionResult": None,
            "consecutiveFailures": None,
        }

    def uuid(self) -> str:
        return str(_uuid.uuid4())


# ============================================================
# Production factory
# ============================================================

def production_deps() -> QueryDeps:
    """
    Create production deps with real implementations.

    Mirrors TS productionDeps() exactly.

    Returns:
        QueryDeps with real (or stub) implementations wired in.

    Note:
        In the Python port, callModel is a stub until the multi-LLM API
        client is implemented. Replace with a real implementation that
        routes to Anthropic Claude / OpenAI / Gemini / DeepSeek etc.
        based on the model identifier in options.
    """
    return QueryDepsStub()


# Alias for compatibility with query.py import
QueryDeps = QueryDepsStub
