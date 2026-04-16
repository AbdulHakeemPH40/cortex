# ------------------------------------------------------------
# sedEditParser.py
# Python conversion of sedEditParser.ts (lines 1-323)
# 
# Parser for sed edit commands (-i flag substitutions).
# Extracts file paths and substitution patterns to enable
# file-edit-style rendering.
# ------------------------------------------------------------

import re
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from crypto import random_bytes
except ImportError:
    import os
    def random_bytes(n: int) -> bytes:
        """Stub: Generate random bytes using os.urandom."""
        return os.urandom(n)

try:
    from ...utils.bash.shell_quote import try_parse_shell_command
except ImportError:
    def try_parse_shell_command(command: str) -> Dict[str, Any]:
        """Stub: Parse shell command into tokens."""
        # Simple tokenization for stub
        return {
            "success": True,
            "tokens": command.split(),
        }


# ============================================================
# TYPE DEFINITIONS
# ============================================================

class SedEditInfo:
    """Information extracted from a sed in-place edit command."""
    
    def __init__(
        self,
        file_path: str,
        pattern: str,
        replacement: str,
        flags: str,
        extended_regex: bool,
    ):
        self.file_path = file_path
        self.pattern = pattern
        self.replacement = replacement
        self.flags = flags
        self.extended_regex = extended_regex
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for compatibility."""
        return {
            "filePath": self.file_path,
            "pattern": self.pattern,
            "replacement": self.replacement,
            "flags": self.flags,
            "extendedRegex": self.extended_regex,
        }


# ============================================================
# PLACEHOLDER CONSTANTS FOR BRE→ERE CONVERSION
# ============================================================

# Null-byte sentinels - never appear in user input
BACKSLASH_PLACEHOLDER = '\x00BACKSLASH\x00'
PLUS_PLACEHOLDER = '\x00PLUS\x00'
QUESTION_PLACEHOLDER = '\x00QUESTION\x00'
PIPE_PLACEHOLDER = '\x00PIPE\x00'
LPAREN_PLACEHOLDER = '\x00LPAREN\x00'
RPAREN_PLACEHOLDER = '\x00RPAREN\x00'

BACKSLASH_PLACEHOLDER_RE = re.compile(BACKSLASH_PLACEHOLDER)
PLUS_PLACEHOLDER_RE = re.compile(PLUS_PLACEHOLDER)
QUESTION_PLACEHOLDER_RE = re.compile(QUESTION_PLACEHOLDER)
PIPE_PLACEHOLDER_RE = re.compile(PIPE_PLACEHOLDER)
LPAREN_PLACEHOLDER_RE = re.compile(LPAREN_PLACEHOLDER)
RPAREN_PLACEHOLDER_RE = re.compile(RPAREN_PLACEHOLDER)


# ============================================================
# MAIN PARSING FUNCTIONS
# ============================================================

def is_sed_in_place_edit(command: str) -> bool:
    """
    Check if a command is a sed in-place edit command.
    
    Returns True only for simple sed -i 's/pattern/replacement/flags' file commands.
    
    Args:
        command: Command string to check
        
    Returns:
        True if command is a valid sed in-place edit
    """
    info = parse_sed_edit_command(command)
    return info is not None


def parse_sed_edit_command(command: str) -> Optional[SedEditInfo]:
    """
    Parse a sed edit command and extract the edit information.
    
    Args:
        command: Full sed command string
        
    Returns:
        SedEditInfo object if valid, None otherwise
    """
    trimmed = command.strip()
    
    # Must start with sed
    sed_match = re.match(r'^\s*sed\s+', trimmed)
    if not sed_match:
        return None
    
    without_sed = trimmed[sed_match.end():]
    parse_result = try_parse_shell_command(without_sed)
    
    if not parse_result.get("success"):
        return None
    
    tokens = parse_result.get("tokens", [])
    
    # Extract string tokens only
    args: List[str] = []
    for token in tokens:
        if isinstance(token, str):
            args.append(token)
        elif isinstance(token, dict) and token.get("op") == "glob":
            # Glob patterns are too complex for this simple parser
            return None
    
    # Parse flags and arguments
    has_in_place_flag = False
    extended_regex = False
    expression: Optional[str] = None
    file_path: Optional[str] = None
    
    i = 0
    while i < len(args):
        arg = args[i]
        
        # Handle -i flag (with or without backup suffix)
        if arg in ['-i', '--in-place']:
            has_in_place_flag = True
            i += 1
            # On macOS, -i requires a suffix argument (even if empty string)
            # Check if next arg looks like a backup suffix (empty, or starts with dot)
            # Don't consume flags (-E, -r) or sed expressions (starting with s, y, d)
            if i < len(args):
                next_arg = args[i]
                # If next arg is empty string or starts with dot, it's a backup suffix
                if isinstance(next_arg, str) and not next_arg.startswith('-') and (next_arg == '' or next_arg.startswith('.')):
                    i += 1  # Skip the backup suffix
            continue
        
        if arg.startswith('-i'):
            # -i.bak or similar (inline suffix)
            has_in_place_flag = True
            i += 1
            continue
        
        # Handle extended regex flags
        if arg in ['-E', '-r', '--regexp-extended']:
            extended_regex = True
            i += 1
            continue
        
        # Handle -e flag with expression
        if arg in ['-e', '--expression']:
            if i + 1 < len(args) and isinstance(args[i + 1], str):
                # Only support single expression
                if expression is not None:
                    return None
                expression = args[i + 1]
                i += 2
                continue
            return None
        
        if arg.startswith('--expression='):
            if expression is not None:
                return None
            expression = arg[len('--expression='):]
            i += 1
            continue
        
        # Skip other flags we don't understand
        if arg.startswith('-'):
            # Unknown flag - not safe to parse
            return None
        
        # Non-flag argument
        if expression is None:
            # First non-flag arg is the expression
            expression = arg
        elif file_path is None:
            # Second non-flag arg is the file path
            file_path = arg
        else:
            # More than one file - not supported for simple rendering
            return None
        
        i += 1
    
    # Must have -i flag, expression, and file path
    if not has_in_place_flag or not expression or not file_path:
        return None
    
    # Parse the substitution expression: s/pattern/replacement/flags
    # Only support / as delimiter for simplicity
    subst_match = re.match(r'^s//', expression)
    if not subst_match:
        return None
    
    rest = expression[2:]  # Skip 's/'
    
    # Find pattern and replacement by tracking escaped characters
    pattern = ''
    replacement = ''
    flags = ''
    state: str = 'pattern'
    j = 0
    
    while j < len(rest):
        char = rest[j]
        
        if char == '\\' and j + 1 < len(rest):
            # Escaped character
            if state == 'pattern':
                pattern += char + rest[j + 1]
            elif state == 'replacement':
                replacement += char + rest[j + 1]
            else:
                flags += char + rest[j + 1]
            j += 2
            continue
        
        if char == '/':
            if state == 'pattern':
                state = 'replacement'
            elif state == 'replacement':
                state = 'flags'
            else:
                # Extra delimiter in flags - unexpected
                return None
            j += 1
            continue
        
        if state == 'pattern':
            pattern += char
        elif state == 'replacement':
            replacement += char
        else:
            flags += char
        j += 1
    
    # Must have found all three parts (pattern, replacement delimiter, and optional flags)
    if state != 'flags':
        return None
    
    # Validate flags - only allow safe substitution flags
    valid_flags = re.compile(r'^[gpimIM1-9]*$')
    if not valid_flags.match(flags):
        return None
    
    return SedEditInfo(
        file_path=file_path,
        pattern=pattern,
        replacement=replacement,
        flags=flags,
        extended_regex=extended_regex,
    )


# ============================================================
# SUBSTITUTION APPLICATION
# ============================================================

def apply_sed_substitution(content: str, sed_info: SedEditInfo) -> str:
    """
    Apply a sed substitution to file content.
    
    Args:
        content: Original file content
        sed_info: SedEditInfo with pattern, replacement, and flags
        
    Returns:
        New content after applying the substitution
    """
    # Convert sed substitution flags to JavaScript/Python regex flags
    regex_flags = ''
    
    # Handle global flag
    if 'g' in sed_info.flags:
        regex_flags += 'g'
    
    # Handle case-insensitive flag (i or I in sed)
    if 'i' in sed_info.flags or 'I' in sed_info.flags:
        regex_flags += 'i'
    
    # Handle multiline flag (m or M in sed)
    if 'm' in sed_info.flags or 'M' in sed_info.flags:
        regex_flags += 'm'
    
    # Convert sed pattern to JavaScript/Python regex pattern
    js_pattern = sed_info.pattern.replace('\\/', '/')
    
    # In BRE mode (no -E flag), metacharacters have opposite escaping:
    # BRE: \+ means "one or more", + is literal
    # ERE/JS: + means "one or more", \+ is literal
    # We need to convert BRE escaping to ERE for JavaScript/Python regex
    if not sed_info.extended_regex:
        # Step 1: Protect literal backslashes (\\) first - in both BRE and ERE, \\ is literal backslash
        js_pattern = js_pattern.replace('\\\\', BACKSLASH_PLACEHOLDER)
        
        # Step 2: Replace escaped metacharacters with placeholders (these should become unescaped in JS)
        js_pattern = js_pattern.replace('\\+', PLUS_PLACEHOLDER)
        js_pattern = js_pattern.replace('\\?', QUESTION_PLACEHOLDER)
        js_pattern = js_pattern.replace('\\|', PIPE_PLACEHOLDER)
        js_pattern = js_pattern.replace('\\(', LPAREN_PLACEHOLDER)
        js_pattern = js_pattern.replace('\\)', RPAREN_PLACEHOLDER)
        
        # Step 3: Escape unescaped metacharacters (these are literal in BRE)
        js_pattern = js_pattern.replace('+', r'\+')
        js_pattern = js_pattern.replace('?', r'\?')
        js_pattern = js_pattern.replace('|', r'\|')
        js_pattern = js_pattern.replace('(', r'\(')
        js_pattern = js_pattern.replace(')', r'\)')
        
        # Step 4: Replace placeholders with their JS equivalents
        js_pattern = BACKSLASH_PLACEHOLDER_RE.sub('\\\\', js_pattern)
        js_pattern = PLUS_PLACEHOLDER_RE.sub('+', js_pattern)
        js_pattern = QUESTION_PLACEHOLDER_RE.sub('?', js_pattern)
        js_pattern = PIPE_PLACEHOLDER_RE.sub('|', js_pattern)
        js_pattern = LPAREN_PLACEHOLDER_RE.sub('(', js_pattern)
        js_pattern = RPAREN_PLACEHOLDER_RE.sub(')', js_pattern)
    
    # Unescape sed-specific escapes in replacement
    # Convert & to $& (match), etc.
    # Use a unique placeholder with random salt to prevent injection attacks
    salt = random_bytes(8).hex()
    ESCAPED_AMP_PLACEHOLDER = f'___ESCAPED_AMPERSAND_{salt}___'
    
    js_replacement = sed_info.replacement.replace('\\/', '/')
    # First escape \& to a placeholder
    js_replacement = js_replacement.replace('\\&', ESCAPED_AMP_PLACEHOLDER)
    # Convert & to $& (full match) - use $$& to get literal $& in output
    js_replacement = js_replacement.replace('&', '$$&')
    # Convert placeholder back to literal &
    js_replacement = re.sub(re.escape(ESCAPED_AMP_PLACEHOLDER), '&', js_replacement)
    
    try:
        regex = re.compile(js_pattern, flags=_parse_regex_flags(regex_flags))
        return regex.sub(js_replacement, content)
    except re.error:
        # If regex is invalid, return original content
        return content


def _parse_regex_flags(flags: str) -> int:
    """
    Convert regex flag string to re module constants.
    
    Args:
        flags: Flag string (e.g., 'gim')
        
    Returns:
        Combined re flag constants
    """
    import re
    
    result = 0
    
    # Note: Python doesn't have a global flag for re.sub - it's always global
    # So we ignore the 'g' flag
    
    if 'i' in flags:
        result |= re.IGNORECASE
    
    if 'm' in flags:
        result |= re.MULTILINE
    
    return result


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "SedEditInfo",
    "is_sed_in_place_edit",
    "parse_sed_edit_command",
    "apply_sed_substitution",
]
