# agent_color_manager.py
"""
Agent color management for Cortex IDE.

Handles color assignment and mapping for different agent types.
"""

from typing import Dict, Optional, List, Literal
from ...bootstrap.state import get_agent_color_map

AgentColorName = Literal[
    "red",
    "blue",
    "green",
    "yellow",
    "purple",
    "orange",
    "pink",
    "cyan",
]

AGENT_COLORS: List[AgentColorName] = [
    "red",
    "blue",
    "green",
    "yellow",
    "purple",
    "orange",
    "pink",
    "cyan",
]

AGENT_COLOR_TO_THEME_COLOR: Dict[AgentColorName, str] = {
    "red": "red_FOR_SUBAGENTS_ONLY",
    "blue": "blue_FOR_SUBAGENTS_ONLY",
    "green": "green_FOR_SUBAGENTS_ONLY",
    "yellow": "yellow_FOR_SUBAGENTS_ONLY",
    "purple": "purple_FOR_SUBAGENTS_ONLY",
    "orange": "orange_FOR_SUBAGENTS_ONLY",
    "pink": "pink_FOR_SUBAGENTS_ONLY",
    "cyan": "cyan_FOR_SUBAGENTS_ONLY",
}


def get_agent_color(agent_type: str) -> Optional[str]:
    """
    Get the theme color for an agent type.
    
    Returns None for general-purpose agents or if no color is assigned.
    """
    if agent_type == "general-purpose":
        return None
    
    agent_color_map = get_agent_color_map()
    
    # Check if color already assigned
    existing_color = agent_color_map.get(agent_type)
    if existing_color and existing_color in AGENT_COLORS:
        return AGENT_COLOR_TO_THEME_COLOR[existing_color]
    
    return None


def set_agent_color(
    agent_type: str,
    color: Optional[AgentColorName],
) -> None:
    """
    Set or remove the color for an agent type.
    """
    agent_color_map = get_agent_color_map()
    
    if not color:
        agent_color_map.discard(agent_type)
        return
    
    if color in AGENT_COLORS:
        agent_color_map[agent_type] = color
