"""
commands.py
Slash command and skill loader for Cortex AI Agent IDE.
Loads all available AI commands/skills from plugins and built-in sources.
"""

from typing import Any, Dict, List, Optional


async def get_slash_command_tool_skills(cwd: str) -> List[Dict[str, Any]]:
    """
    Load all slash command tool skills available in the current workspace.
    Returns a list of skill/command definitions for use by the AI agent.
    """
    try:
        from utils.plugins.loadPluginCommands import load_plugin_commands
        commands = await load_plugin_commands()
        return [cmd.to_dict() for cmd in commands]
    except Exception:
        return []


async def get_commands(cwd: str = "") -> List[Dict[str, Any]]:
    """
    Get all available commands (slash commands + built-in skills).
    """
    return await get_slash_command_tool_skills(cwd)


async def get_skill_tool_commands(cwd: str = "") -> List[Dict[str, Any]]:
    """
    Get commands available as skill tools.
    """
    return await get_slash_command_tool_skills(cwd)


def get_command_name(command: Dict[str, Any]) -> str:
    """Get the display name for a command."""
    return command.get('name', command.get('userFacingName', ''))


__all__ = [
    "get_slash_command_tool_skills",
    "get_commands",
    "get_skill_tool_commands",
    "get_command_name",
]
