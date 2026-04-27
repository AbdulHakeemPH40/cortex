"""
Forked agent utilities for Cortex IDE.

Provides functionality for spawning and managing forked sub-agents.
Converted from TypeScript forkedAgent.ts module.
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, AsyncGenerator
from dataclasses import dataclass


@dataclass
class CacheSafeParams:
    """Cache-safe parameters for forked agent execution."""
    system_prompt: Optional[str] = None
    user_context: Optional[Dict] = None
    system_context: Optional[Dict] = None
    tool_use_context: Optional[Dict] = None


async def run_forked_agent(
    prompt_messages: List[Any],
    cache_safe_params: Optional[CacheSafeParams] = None,
    can_use_tool: Optional[Callable] = None,
    query_source: str = 'forked',
    fork_label: str = '',
    skip_transcript: bool = False,
    overrides: Optional[Dict] = None,
    on_message: Optional[Callable] = None,
) -> Any:
    """
    Run a forked sub-agent with isolated context.
    
    Args:
        prompt_messages: Initial messages for the agent
        cache_safe_params: Cached parameters for context
        can_use_tool: Permission checker for tool use
        query_source: Source category for analytics
        fork_label: Label for debugging
        skip_transcript: Whether to skip transcript recording
        overrides: Context overrides
        on_message: Callback for each message
        
    Returns:
        Agent execution result
    """
    # TODO: Implement actual forked agent execution
    raise NotImplementedError("run_forked_agent not yet implemented")


def create_cache_safe_params(context: Any) -> CacheSafeParams:
    """Create cache-safe parameters from a context object."""
    return CacheSafeParams(
        system_prompt=getattr(context, 'system_prompt', None),
        user_context=getattr(context, 'user_context', None),
        system_context=getattr(context, 'system_context', None),
        tool_use_context=getattr(context, 'tool_use_context', None),
    )


__all__ = [
    'CacheSafeParams',
    'run_forked_agent',
    'create_cache_safe_params',
]
