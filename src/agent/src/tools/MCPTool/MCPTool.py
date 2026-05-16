"""
MCPTool - Model Context Protocol tool wrapper.

A dynamic tool that represents external MCP (Model Context Protocol) servers.
This is a stub implementation that gets overridden in mcpClient.py with:
- Real MCP tool name and description
- Actual input schema from MCP server
- Tool execution logic
- Permission checks

MCP servers expose custom tools through this interface, allowing the AI
to interact with external systems (databases, APIs, file systems, etc.).
"""

from typing import Any, Dict

from .prompt import DESCRIPTION, PROMPT
from ...utils.messages import (
    render_tool_result_message,
    render_tool_use_message,
    render_tool_use_progress_message,
)


# Allow any input object since MCP tools define their own schemas
input_schema = lazy_schema(lambda: {})  # type: ignore
output_schema = lazy_schema(lambda: str)  # type: ignore


def _is_open_world() -> bool:
    """Overridden in mcpClient.py"""
    return False


async def _description() -> str:
    """Overridden in mcpClient.py"""
    return DESCRIPTION


async def _prompt() -> str:
    """Overridden in mcpClient.py"""
    return PROMPT


async def _call(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Overridden in mcpClient.py"""
    return {'data': ''}


async def _check_permissions(*args: Any, **kwargs: Any) -> PermissionResult:
    """Default permission check for MCP tools."""
    return PermissionResult(
        behavior='passthrough',
        message='MCPTool requires permission.',
    )


def _user_facing_name() -> str:
    """Overridden in mcpClient.py"""
    return 'mcp'


def _is_result_truncated(output: str) -> bool:
    """Check if MCP tool output was truncated."""
    return is_output_line_truncated(output)


def _map_tool_result_to_block(content: Any, tool_use_id: str) -> Dict[str, Any]:
    """Convert tool result to Anthropic API format."""
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': content,
    }


MCPTool = build_tool(
    is_mcp=True,
    is_open_world=_is_open_world,
    name='mcp',
    max_result_size_chars=100_000,
    description=_description,
    prompt=_prompt,
    input_schema=input_schema,
    output_schema=output_schema,
    call=_call,
    check_permissions=_check_permissions,
    render_tool_use_message=render_tool_use_message,
    user_facing_name=_user_facing_name,
    render_tool_use_progress_message=render_tool_use_progress_message,
    render_tool_result_message=render_tool_result_message,
    is_result_truncated=_is_result_truncated,
    map_tool_result_to_tool_result_block_param=_map_tool_result_to_block,
)
