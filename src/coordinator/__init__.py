"""
Coordinator module for multi-agent orchestration.

Provides system prompts and context builders for coordinating
multiple AI workers using AutoGen/OpenHands in Cortex IDE.
"""

from .coordinator_prompt import (
    get_coordinator_system_prompt,
    get_worker_capabilities_description,
)

from .agent_context import (
    get_worker_tool_context,
    format_worker_prompt,
    create_research_prompt,
    create_implementation_prompt,
    create_verification_prompt,
    should_continue_worker,
)

__all__ = [
    'get_coordinator_system_prompt',
    'get_worker_capabilities_description',
    'get_worker_tool_context',
    'format_worker_prompt',
    'create_research_prompt',
    'create_implementation_prompt',
    'create_verification_prompt',
    'should_continue_worker',
]
