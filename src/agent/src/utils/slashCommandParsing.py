# ------------------------------------------------------------
# slashCommandParsing.py
# Python conversion of utils/slashCommandParsing.ts
#
# Centralized utilities for parsing slash commands from raw input.
# Handles command name, arguments, and MCP prefix detection.
# ------------------------------------------------------------

from typing import Optional

__all__ = ["parse_slash_command", "ParsedSlashCommand"]


class ParsedSlashCommand:
    """
    Result of parsing a slash command input string.

    Mirrors TS ParsedSlashCommand type exactly.
    """

    def __init__(
        self,
        command_name: str,
        args: str,
        is_mcp: bool,
    ) -> None:
        self.command_name = command_name
        self.args = args
        self.is_mcp = is_mcp

    def __repr__(self) -> str:
        return (
            f"ParsedSlashCommand("
            f"command_name={self.command_name!r}, "
            f"args={self.args!r}, "
            f"is_mcp={self.is_mcp!r})"
        )


def parse_slash_command(input_str: str) -> Optional[ParsedSlashCommand]:
    """
    Parse a slash command input string into its component parts.

    Mirrors TS parseSlashCommand() exactly.

    Args:
        input_str: The raw input string (should start with '/')

    Returns:
        ParsedSlashCommand with command_name, args, and is_mcp flag,
        or None if the input is not a valid slash command.

    Examples:
        >>> parse_slash_command('/search foo bar')
        ParsedSlashCommand(command_name='search', args='foo bar', is_mcp=False)
        >>> parse_slash_command('/mcp:tool (MCP) arg1 arg2')
        ParsedSlashCommand(command_name='mcp:tool (MCP)', args='arg1 arg2', is_mcp=True)
    """
    trimmed = input_str.strip()

    if not trimmed.startswith("/"):
        return None

    # Remove the leading '/' and split by whitespace
    without_slash = trimmed[1:]
    words = without_slash.split(" ")

    if not words[0]:
        return None

    command_name = words[0]
    is_mcp = False
    args_start_index = 1

    # Check for MCP commands (second word is '(MCP)')
    if len(words) > 1 and words[1] == "(MCP)":
        command_name = f"{command_name} (MCP)"
        is_mcp = True
        args_start_index = 2

    # Extract arguments (everything after command name)
    args = " ".join(words[args_start_index:])

    return ParsedSlashCommand(
        command_name=command_name,
        args=args,
        is_mcp=is_mcp,
    )
