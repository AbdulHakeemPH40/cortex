"""
LSPTool symbol context extraction.

Extracts the symbol/word at a specific position in a file for display in tool messages.
"""

import os
from pathlib import Path
from typing import Optional

# Defensive imports
try:
    from ...utils.debug import logForDebugging
except ImportError:
    def logForDebugging(msg, **kwargs):
        pass

try:
    from ...utils.format import truncate
except ImportError:
    def truncate(text, max_length):
        if len(text) <= max_length:
            return text
        return text[:max_length] + '...'

try:
    from ...utils.fsOperations import getFsImplementation
except ImportError:
    def getFsImplementation():
        class MockFS:
            def readSync(self, path, options=None):
                with open(path, 'rb') as f:
                    length = options.get('length') if options else None
                    data = f.read(length) if length else f.read()
                    from types import SimpleNamespace
                    return SimpleNamespace(buffer=data, bytesRead=len(data))
        return MockFS()

try:
    from ...utils.path import expandPath
except ImportError:
    def expandPath(path):
        return os.path.expanduser(os.path.expandvars(path))


MAX_READ_BYTES = 64 * 1024  # 64 KB


def getSymbolAtPosition(
    file_path: str,
    line: int,
    character: int,
) -> Optional[str]:
    """
    Extracts the symbol/word at a specific position in a file.
    Used to show context in tool use messages.

    Args:
        file_path: The file path (absolute or relative)
        line: 0-indexed line number
        character: 0-indexed character position on the line

    Note: This uses synchronous file I/O because it is called from
    renderToolUseMessage (a synchronous React render function). The read is
    wrapped in try/catch so ENOENT and other errors fall back gracefully.

    Returns:
        The symbol at that position, or None if extraction fails
    """
    try:
        fs = getFsImplementation()
        absolute_path = expandPath(file_path)

        # Read only the first 64KB instead of the whole file. Most LSP hover/goto
        # targets are near recent edits; 64KB covers ~1000 lines of typical code.
        # If the target line is past this window we fall back to None (the UI
        # already handles that by showing `position: line:char`).
        result = fs.readSync(absolute_path, {'length': MAX_READ_BYTES})
        buffer = result.buffer
        bytes_read = result.bytesRead
        
        content = buffer.decode('utf-8', errors='replace')
        lines = content.split('\n')

        if line < 0 or line >= len(lines):
            return None
        
        # If we filled the full buffer the file continues past our window,
        # so the last split element may be truncated mid-line.
        if bytes_read == MAX_READ_BYTES and line == len(lines) - 1:
            return None

        line_content = lines[line]
        if not line_content or character < 0 or character >= len(line_content):
            return None

        # Extract the word/symbol at the character position
        # Pattern matches:
        # - Standard identifiers: alphanumeric + underscore + dollar
        # - Rust lifetimes: 'a, 'static
        # - Rust macros: macro_name!
        # - Operators and special symbols: +, -, *, etc.
        # This is more inclusive to handle various programming languages
        import re
        symbol_pattern = re.compile(r"[\w$'!]+|[+\-*/%&|^~<>=]+")
        
        for match in symbol_pattern.finditer(line_content):
            start = match.start()
            end = match.end()

            # Check if the character position falls within this match
            if character >= start and character < end:
                symbol = match.group(0)
                # Limit length to 30 characters to avoid overly long symbols
                return truncate(symbol, 30)

        return None
    
    except Exception as error:
        # Log unexpected errors for debugging (permission issues, encoding problems, etc.)
        # Use logForDebugging since this is a display enhancement, not a critical error
        if isinstance(error, Exception):
            logForDebugging(
                f'Symbol extraction failed for {file_path}:{line}:{character}: {str(error)}',
                {'level': 'warn'},
            )
        # Still return None for graceful fallback to position display
        return None
