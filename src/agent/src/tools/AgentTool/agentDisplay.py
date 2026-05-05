# agent_display.py
"""
Shared utilities for displaying agent information in Cortex IDE.

Used by both the AI agent `cortex agents` handler and the interactive `/agents` command.
"""

from typing import List, Optional, TypedDict
from ...utils.model.agent import get_default_subagent_model
from ...utils.settings import (
    get_source_display_name,
    SettingSource,
)
from .loadAgentsDir import AgentDefinition

AgentSource = SettingSource


class AgentSourceGroup(TypedDict):
    """Agent source group for display."""
    label: str
    source: AgentSource


# Ordered list of agent source groups for display.
# Both the AI agent and interactive UI should use this to ensure consistent ordering.
AGENT_SOURCE_GROUPS: List[AgentSourceGroup] = [
    {"label": "User agents", "source": "userSettings"},
    {"label": "Project agents", "source": "projectSettings"},
    {"label": "Local agents", "source": "localSettings"},
    {"label": "Managed agents", "source": "policySettings"},
    {"label": "Plugin agents", "source": "plugin"},
    {"label": "AI agent arg agents", "source": "flagSettings"},
    {"label": "Built-in agents", "source": "built-in"},
]


class ResolvedAgent(TypedDict, total=False):
    """Agent definition with override information."""
    agent_type: str
    when_to_use: str
    tools: List[str]
    source: str
    base_dir: str
    model: Optional[str]
    get_system_prompt: callable
    overridden_by: Optional[AgentSource]


def resolve_agent_overrides(
    all_agents: List[AgentDefinition],
    active_agents: List[AgentDefinition],
) -> List[ResolvedAgent]:
    """
    Annotate agents with override information by comparing against the active
    (winning) agent list. An agent is "overridden" when another agent with the
    same type from a higher-priority source takes precedence.
    
    Also deduplicates by (agent_type, source) to handle git worktree duplicates
    where the same agent file is loaded from both the worktree and main repo.
    """
    active_map = {agent.agent_type: agent for agent in active_agents}
    
    seen = set()
    resolved = []
    
    # Iterate all_agents, annotating each with override info from active_agents.
    # Deduplicate by (agent_type, source) to handle git worktree duplicates.
    for agent in all_agents:
        key = f"{agent.agent_type}:{agent.source}"
        if key in seen:
            continue
        seen.add(key)
        
        active = active_map.get(agent.agent_type)
        overridden_by = (
            active.source if active and active.source != agent.source else None
        )
        
        resolved_agent = agent.copy()
        resolved_agent["overridden_by"] = overridden_by
        resolved.append(resolved_agent)
    
    return resolved


def resolve_agent_model_display(agent: AgentDefinition) -> Optional[str]:
    """
    Resolve the display model string for an agent.
    Returns the model alias or 'inherit' for display purposes.
    """
    model = agent.get("model") or get_default_subagent_model()
    if not model:
        return None
    return "inherit" if model == "inherit" else model


def get_override_source_label(source: AgentSource) -> str:
    """
    Get a human-readable label for the source that overrides an agent.
    Returns lowercase, e.g. "user", "project", "managed".
    """
    return get_source_display_name(source).lower()


def compare_agents_by_name(
    a: AgentDefinition,
    b: AgentDefinition,
) -> int:
    """
    Compare agents alphabetically by name (case-insensitive).
    """
    return a.agent_type.casefold().compare(b.agent_type.casefold())
