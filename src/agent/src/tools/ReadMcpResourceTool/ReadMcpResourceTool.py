# ------------------------------------------------------------
# ReadMcpResourceTool.py
# Python conversion of ReadMcpResourceTool/ReadMcpResourceTool.ts
# 
# MCP Resource Reader Tool for AI Agent IDE.
# Enables AI to read resources from MCP servers (text and binary).
# ------------------------------------------------------------

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import asyncio
import time
import random
import string
import base64
import json

# Import dependencies
try:
    from ...services.mcp.client import ensureConnectedClient
except ImportError:
    async def ensureConnectedClient(client):
        raise NotImplementedError("ensureConnectedClient not available")

try:
    from ...utils.mcpOutputStorage import (
        getBinaryBlobSavedMessage,
        persistBinaryContent,
    )
except ImportError:
    def getBinaryBlobSavedMessage(filepath, mime_type, size, prefix=''):
        return f"[Resource] Saved to: {filepath}"
    
    async def persistBinaryContent(content, mime_type, persist_id):
        # Fallback: return error since storage not available
        return {'error': 'Binary storage not available'}

try:
    from ...utils.slowOperations import jsonStringify
except ImportError:
    def jsonStringify(obj: Any) -> str:
        return json.dumps(obj, default=str)

try:
    from ...utils.terminal import isOutputLineTruncated
except ImportError:
    def isOutputLineTruncated(text: str) -> bool:
        return False

try:
    from ...Tool import buildTool, ToolDef
except ImportError:
    def buildTool(**kwargs):
        return kwargs

from .prompt import DESCRIPTION, PROMPT


# ============================================================
# Schema Definitions
# ============================================================

# Input schema: server name + resource URI
INPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'string',
            'description': 'The MCP server name',
        },
        'uri': {
            'type': 'string',
            'description': 'The resource URI to read',
        },
    },
    'required': ['server', 'uri'],
}

# Output schema: array of resource contents
OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'contents': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'uri': {
                        'type': 'string',
                        'description': 'Resource URI',
                    },
                    'mimeType': {
                        'type': 'string',
                        'description': 'MIME type of the content',
                    },
                    'text': {
                        'type': 'string',
                        'description': 'Text content of the resource',
                    },
                    'blobSavedTo': {
                        'type': 'string',
                        'description': 'Path where binary blob content was saved',
                    },
                },
            },
        },
    },
}


@dataclass
class ReadMcpResourceOutput:
    """Output type for ReadMcpResourceTool."""
    contents: List[Dict[str, Any]] = field(default_factory=list)


def userFacingName() -> str:
    """Returns the user-facing name for display."""
    return 'Read MCP Resource'


def renderToolUseMessage(input_data: Dict[str, Any]) -> str:
    """Renders a tool use message for display."""
    server = input_data.get('server', 'unknown')
    uri = input_data.get('uri', 'unknown')
    return f"Reading resource from MCP server '{server}': {uri}"


def renderToolResultMessage(output: Any) -> str:
    """Renders a tool result message for display."""
    # Handle both dataclass and dict output formats
    if hasattr(output, 'contents'):
        contents = output.contents
    elif isinstance(output, dict):
        contents = output.get('contents', [])
    else:
        contents = []
    
    content_count = len(contents)
    if content_count == 0:
        return "No content found"
    
    uris = [c.get('uri', 'unknown') for c in contents]
    return f"Read {content_count} resource(s): {', '.join(uris[:3])}"


async def _call_read_mcp_resource(
    input_data: Dict[str, Any],
    context: Any,
) -> Dict[str, Any]:
    """
    Call the ReadMcpResourceTool.
    
    Args:
        input_data: Dict with 'server' and 'uri' keys
        context: Tool context with options (mcpClients, etc.)
    
    Returns:
        Dict with 'data' key containing the resource contents
    """
    server_name = input_data.get('server')
    uri = input_data.get('uri')
    
    # Find the MCP client by name
    mcp_clients = context.options.mcpClients if hasattr(context, 'options') else []
    client = next((c for c in mcp_clients if c.name == server_name), None)
    
    if not client:
        available = ', '.join(c.name for c in mcp_clients)
        raise ValueError(
            f'Server "{server_name}" not found. Available servers: {available}'
        )
    
    # Check if client is connected
    if client.type != 'connected':
        raise ValueError(f'Server "{server_name}" is not connected')
    
    # Check if client supports resources
    if not getattr(client, 'capabilities', None) or not client.capabilities.get('resources'):
        raise ValueError(f'Server "{server_name}" does not support resources')
    
    # Ensure client is connected and make the request
    connected_client = await ensureConnectedClient(client)
    
    # MCP protocol request: resources/read
    result = await connected_client.client.request(
        {
            'method': 'resources/read',
            'params': {'uri': uri},
        },
        # Schema validation would go here
    )
    
    # Process resource contents
    # Intercept any blob fields: decode, write raw bytes to disk with a
    # mime-derived extension, and replace with a path. Otherwise the base64
    # would be stringified straight into the context.
    contents = await asyncio.gather(*[
        _process_content(c, i, server_name)
        for i, c in enumerate(result.get('contents', []))
    ])
    
    return {
        'data': {'contents': contents},
    }


# ============================================================
# Tool Definition
# ============================================================

ReadMcpResourceTool = buildTool(
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda: True,
    toAutoClassifierInput=lambda input_data: f"{input_data.get('server', '')} {input_data.get('uri', '')}",
    shouldDefer=True,
    name='ReadMcpResourceTool',
    searchHint='read a specific MCP resource by URI',
    maxResultSizeChars=100_000,
    description=DESCRIPTION,
    prompt=PROMPT,
    inputSchema=INPUT_SCHEMA,
    outputSchema=OUTPUT_SCHEMA,
    call=_call_read_mcp_resource,
    renderToolUseMessage=renderToolUseMessage,
    userFacingName=userFacingName,
    renderToolResultMessage=renderToolResultMessage,
    isResultTruncated=lambda output: isOutputLineTruncated(jsonStringify(output)),
    mapToolResultToToolResultBlockParam=lambda content, toolUseID: {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': jsonStringify(content),
    },
)


async def _process_content(
    content: Dict[str, Any],
    index: int,
    server_name: str,
) -> Dict[str, Any]:
    """
    Process a single resource content item.
    
    Handles both text and binary (blob) content.
    Binary blobs are decoded, saved to disk, and replaced with file paths.
    """
    # Text content - return as-is
    if 'text' in content:
        return {
            'uri': content.get('uri'),
            'mimeType': content.get('mimeType'),
            'text': content.get('text'),
        }
    
    # Binary content (blob)
    if 'blob' in content and isinstance(content.get('blob'), str):
        # Generate unique persist ID
        persist_id = f"mcp-resource-{int(time.time() * 1000)}-{index}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
        
        # Decode base64 blob and persist to disk
        blob_data = base64.b64decode(content['blob'])
        persisted = await persistBinaryContent(
            blob_data,
            content.get('mimeType'),
            persist_id,
        )
        
        # Handle persistence errors
        if 'error' in persisted:
            return {
                'uri': content.get('uri'),
                'mimeType': content.get('mimeType'),
                'text': f"Binary content could not be saved to disk: {persisted['error']}",
            }
        
        # Return with file path reference
        return {
            'uri': content.get('uri'),
            'mimeType': content.get('mimeType'),
            'blobSavedTo': persisted.get('filepath'),
            'text': getBinaryBlobSavedMessage(
                persisted.get('filepath'),
                content.get('mimeType'),
                persisted.get('size', 0),
                f'[Resource from {server_name} at {content.get("uri")}] ',
            ),
        }
    
    # Unknown content type
    return {
        'uri': content.get('uri'),
        'mimeType': content.get('mimeType'),
    }
