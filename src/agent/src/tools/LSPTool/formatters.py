"""
LSPTool result formatters.

Formats LSP responses into human-readable strings for display to users.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Defensive imports
try:
    from ...utils.debug import logForDebugging
except ImportError:
    def logForDebugging(msg, **kwargs):
        pass

try:
    from ...utils.errors import errorMessage
except ImportError:
    def errorMessage(error):
        return str(error)

try:
    from ...utils.stringUtils import plural
except ImportError:
    def plural(count, singular, plural_form=None):
        if count == 1:
            return singular
        return plural_form or f'{singular}s'


def formatUri(uri: Optional[str], cwd: Optional[str] = None) -> str:
    """
    Formats a URI by converting it to a relative path if possible.
    Handles URI decoding and gracefully falls back to un-decoded path if malformed.
    Only uses relative paths when shorter and not starting with ../../
    """
    # Handle undefined/null URIs - this indicates malformed LSP data
    if not uri:
        logForDebugging(
            'formatUri called with undefined URI - indicates malformed LSP server response',
            {'level': 'warn'},
        )
        return '<unknown location>'

    # Remove file:// protocol if present
    # On Windows, file:///C:/path becomes /C:/path after replacing file://
    # We need to strip the leading slash for Windows drive-letter paths
    file_path = uri.replace('file://', '')
    import re
    if re.match(r'^\/[A-Za-z]:', file_path):
        file_path = file_path[1:]

    # Decode URI encoding - handle malformed URIs gracefully
    try:
        from urllib.parse import unquote
        file_path = unquote(file_path)
    except Exception as error:
        # Log for debugging but continue with un-decoded path
        error_msg = errorMessage(error)
        logForDebugging(
            f'Failed to decode URI {uri}: {error_msg}',
            {'level': 'warn'},
        )

    # Convert to relative path if possible and beneficial
    if cwd:
        try:
            rel_path = os.path.relpath(file_path, cwd)
            # Only use relative path if it's shorter and doesn't start with ../../
            if len(rel_path) < len(file_path) and not rel_path.startswith('../'):
                file_path = rel_path
        except Exception:
            pass  # Keep absolute path if relpath fails

    return file_path


def formatLocation(location: Dict[str, Any], cwd: Optional[str] = None) -> str:
    """Format a Location object."""
    uri = location.get('uri')
    range_obj = location.get('range', {})
    start = range_obj.get('start', {})
    
    file_path = formatUri(uri, cwd)
    line = start.get('line', 0) + 1  # Convert to 1-based
    character = start.get('character', 0) + 1
    
    return f'{file_path}:{line}:{character}'


def formatGoToDefinitionResult(
    result: Union[Dict, List, None],
    cwd: Optional[str] = None,
) -> str:
    """Format goToDefinition result."""
    if not result:
        return 'No definition found.'
    
    # Result can be Location, Location[], or LocationLink[]
    if isinstance(result, list):
        if len(result) == 0:
            return 'No definition found.'
        
        locations = [formatLocation(loc, cwd) for loc in result]
        if len(locations) == 1:
            return f'Definition found at:\n{locations[0]}'
        
        return f'Found {len(locations)} definitions:\n' + '\n'.join(
            f'{i+1}. {loc}' for i, loc in enumerate(locations)
        )
    
    # Single location
    location = formatLocation(result, cwd)
    return f'Definition found at:\n{location}'


def formatFindReferencesResult(
    result: Union[List[Dict], None],
    cwd: Optional[str] = None,
) -> str:
    """Format findReferences result."""
    if not result or len(result) == 0:
        return 'No references found.'
    
    locations = [formatLocation(loc, cwd) for loc in result]
    count = len(locations)
    
    header = f'Found {count} {plural(count, "reference")}:'
    return header + '\n' + '\n'.join(
        f'{i+1}. {loc}' for i, loc in enumerate(locations)
    )


def formatHoverResult(result: Union[Dict, None]) -> str:
    """Format hover result."""
    if not result:
        return 'No hover information available.'
    
    contents = result.get('contents')
    if not contents:
        return 'No hover information available.'
    
    # Contents can be MarkedString, MarkupContent, or array
    if isinstance(contents, list):
        text_parts = []
        for item in contents:
            if isinstance(item, dict):
                if 'value' in item:
                    text_parts.append(item['value'])
                elif isinstance(item, dict):
                    text_parts.append(str(item))
            else:
                text_parts.append(str(item))
        return '\n'.join(text_parts)
    
    if isinstance(contents, dict):
        if 'value' in contents:
            return contents['value']
        return str(contents)
    
    return str(contents)


def formatDocumentSymbolResult(
    result: Union[List[Dict], None],
    cwd: Optional[str] = None,
) -> str:
    """Format documentSymbol result."""
    if not result or len(result) == 0:
        return 'No symbols found in document.'
    
    symbols = []
    for symbol in result:
        name = symbol.get('name', '<unknown>')
        kind = symbol.get('kind', 0)
        location = symbol.get('location', {})
        range_obj = location.get('range', {})
        start = range_obj.get('start', {})
        
        file_path = formatUri(location.get('uri'), cwd)
        line = start.get('line', 0) + 1
        
        symbol_kind_name = getSymbolKindName(kind)
        symbols.append(f'{symbol_kind_name}: {name} ({file_path}:{line})')
    
    count = len(symbols)
    header = f'Found {count} {plural(count, "symbol")}:'
    return header + '\n' + '\n'.join(
        f'{i+1}. {sym}' for i, sym in enumerate(symbols)
    )


def formatWorkspaceSymbolResult(
    result: Union[List[Dict], None],
    cwd: Optional[str] = None,
) -> str:
    """Format workspaceSymbol result."""
    if not result or len(result) == 0:
        return 'No symbols found in workspace.'
    
    symbols = []
    for symbol in result:
        name = symbol.get('name', '<unknown>')
        kind = symbol.get('kind', 0)
        location = symbol.get('location', {})
        
        file_path = formatUri(location.get('uri'), cwd)
        range_obj = location.get('range', {})
        start = range_obj.get('start', {})
        line = start.get('line', 0) + 1
        
        symbol_kind_name = getSymbolKindName(kind)
        container = symbol.get('containerName', '')
        container_info = f' (in {container})' if container else ''
        symbols.append(f'{symbol_kind_name}: {name}{container_info} ({file_path}:{line})')
    
    count = len(symbols)
    header = f'Found {count} {plural(count, "symbol")} in workspace:'
    return header + '\n' + '\n'.join(
        f'{i+1}. {sym}' for i, sym in enumerate(symbols)
    )


def formatPrepareCallHierarchyResult(
    result: Union[Dict, List, None],
    cwd: Optional[str] = None,
) -> str:
    """Format prepareCallHierarchy result."""
    if not result:
        return 'No call hierarchy item found at this position.'
    
    # Result is CallHierarchyItem or CallHierarchyItem[]
    items = result if isinstance(result, list) else [result]
    
    formatted = []
    for item in items:
        name = item.get('name', '<unknown>')
        kind = item.get('kind', 0)
        uri = item.get('uri')
        range_obj = item.get('range', {})
        start = range_obj.get('start', {})
        
        file_path = formatUri(uri, cwd)
        line = start.get('line', 0) + 1
        
        symbol_kind_name = getSymbolKindName(kind)
        detail = item.get('detail', '')
        detail_info = f' - {detail}' if detail else ''
        formatted.append(f'{symbol_kind_name}: {name}{detail_info} ({file_path}:{line})')
    
    if len(formatted) == 1:
        return f'Call hierarchy item:\n{formatted[0]}'
    
    return f'Found {len(formatted)} call hierarchy items:\n' + '\n'.join(
        f'{i+1}. {item}' for i, item in enumerate(formatted)
    )


def formatIncomingCallsResult(
    result: Union[List[Dict], None],
    cwd: Optional[str] = None,
) -> str:
    """Format incomingCalls result."""
    if not result or len(result) == 0:
        return 'No incoming calls found.'
    
    calls = []
    for call in result:
        from_item = call.get('from', {})
        name = from_item.get('name', '<unknown>')
        kind = from_item.get('kind', 0)
        uri = from_item.get('uri')
        range_obj = from_item.get('range', {})
        start = range_obj.get('start', {})
        
        file_path = formatUri(uri, cwd)
        line = start.get('line', 0) + 1
        
        symbol_kind_name = getSymbolKindName(kind)
        calls.append(f'{symbol_kind_name}: {name} ({file_path}:{line})')
    
    count = len(calls)
    header = f'Found {count} {plural(count, "caller")}:'
    return header + '\n' + '\n'.join(
        f'{i+1}. {call}' for i, call in enumerate(calls)
    )


def formatOutgoingCallsResult(
    result: Union[List[Dict], None],
    cwd: Optional[str] = None,
) -> str:
    """Format outgoingCalls result."""
    if not result or len(result) == 0:
        return 'No outgoing calls found.'
    
    calls = []
    for call in result:
        to_item = call.get('to', {})
        name = to_item.get('name', '<unknown>')
        kind = to_item.get('kind', 0)
        uri = to_item.get('uri')
        range_obj = to_item.get('range', {})
        start = range_obj.get('start', {})
        
        file_path = formatUri(uri, cwd)
        line = start.get('line', 0) + 1
        
        symbol_kind_name = getSymbolKindName(kind)
        calls.append(f'{symbol_kind_name}: {name} ({file_path}:{line})')
    
    count = len(calls)
    header = f'Found {count} {plural(count, "callee")}:'
    return header + '\n' + '\n'.join(
        f'{i+1}. {call}' for i, call in enumerate(calls)
    )


def getSymbolKindName(kind: int) -> str:
    """Convert LSP SymbolKind number to human-readable name."""
    kinds = {
        1: 'File',
        2: 'Module',
        3: 'Namespace',
        4: 'Package',
        5: 'Class',
        6: 'Method',
        7: 'Property',
        8: 'Field',
        9: 'Constructor',
        10: 'Enum',
        11: 'Interface',
        12: 'Function',
        13: 'Variable',
        14: 'Constant',
        15: 'String',
        16: 'Number',
        17: 'Boolean',
        18: 'Array',
        19: 'Object',
        20: 'Key',
        21: 'Null',
        22: 'EnumMember',
        23: 'Struct',
        24: 'Event',
        25: 'Operator',
        26: 'TypeParameter',
    }
    return kinds.get(kind, f'Symbol({kind})')
