"""
Path validation and permission enforcement for Cortex AI Agent IDE.

Validates file system paths before allowing read/write/create operations.
Provides security gatekeeping between AI commands and actual file system access.

Multi-LLM Support: Works with all providers (Anthropic, OpenAI, Gemini, DeepSeek,
Mistral, Groq, Ollama, SiliconFlow) as it's provider-agnostic security logic.

Key Security Features:
- Shell expansion detection ($VAR, %VAR%, ${cmd})
- Glob pattern validation and restrictions
- Dangerous removal path protection (rm -rf /)
- UNC path blocking (Windows network paths)
- Tilde expansion security
- Operation type handling (read/write/create)
- Integration with filesystem_security.py and permission_mode.py

Example:
    >>> from pathValidation import validate_path
    >>> result = validate_path('/home/user/project/file.txt', '/home/user/project', 'read', context)
    >>> result['allowed']
    True
"""

import logging
import os
import re
from os.path import expanduser, isabs, join, normpath
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

# ============================================================================
# Constants and Type Definitions
# ============================================================================

# Maximum directories to list in error messages
MAX_DIRS_TO_LIST = 5

# Glob pattern detection regex
GLOB_PATTERN_REGEX = re.compile(r'[*?[\]{}]')

# File operation types
FileOperationType = str  # 'read' | 'write' | 'create'

# Path check result structure
PathCheckResult = dict[str, Any]
ResolvedPathCheckResult = dict[str, Any]

# Windows drive root patterns
WINDOWS_DRIVE_ROOT_REGEX = re.compile(r'^[A-Za-z]:\\?$')
WINDOWS_DRIVE_CHILD_REGEX = re.compile(r'^[A-Za-z]:[/\\][^/\\]+$')


# ============================================================================
# Utility Functions
# ============================================================================

def format_directory_list(directories: list[str]) -> str:
    """
    Format directory list for error messages.
    
    Args:
        directories: List of directory paths
        
    Returns:
        Formatted string for display
        
    Example:
        >>> format_directory_list(['/home', '/tmp', '/var'])
        "'/home', '/tmp', '/var'"
        >>> format_directory_list(['/a', '/b', '/c', '/d', '/e', '/f'])
        "'/a', '/b', '/c', '/d', '/e', and 1 more"
    """
    dir_count = len(directories)
    
    if dir_count <= MAX_DIRS_TO_LIST:
        return ', '.join(f"'{dir}'" for dir in directories)
    
    first_dirs = ', '.join(f"'{dir}'" for dir in directories[:MAX_DIRS_TO_LIST])
    return f"{first_dirs}, and {dir_count - MAX_DIRS_TO_LIST} more"


def get_glob_base_directory(path: str) -> str:
    """
    Extracts the base directory from a glob pattern for validation.
    
    For example: "/path/to/*.txt" returns "/path/to"
    
    Args:
        path: Path that may contain glob patterns
        
    Returns:
        Base directory path before glob characters
    """
    glob_match = GLOB_PATTERN_REGEX.search(path)
    if not glob_match:
        return path
    
    # Get everything before the first glob character
    before_glob = path[:glob_match.start()]
    
    # Find the last directory separator
    last_sep_index = max(before_glob.rfind('/'), before_glob.rfind('\\'))
    if last_sep_index == -1:
        return '.'
    
    return before_glob[:last_sep_index] or '/'


def expand_tilde(path: str) -> str:
    """
    Expands tilde (~) at the start of a path to the user's home directory.
    
    Note: ~username expansion is not supported for security reasons.
    
    Args:
        path: Path that may start with ~
        
    Returns:
        Path with ~ expanded to home directory
    """
    if path == '~' or path.startswith('~/') or path.startswith('~\\'):
        return expanduser(path)
    return path


# ============================================================================
# Dangerous Removal Path Detection
# ============================================================================

def is_dangerous_removal_path(resolved_path: str) -> bool:
    """
    Checks if a resolved path is dangerous for removal operations (rm/rmdir).
    
    Dangerous paths are:
    - Wildcard '*' (removes all files in directory)
    - Any path ending with '/*' or '\*' (e.g., /path/to/dir/*, C:\\foo\\*)
    - Root directory (/)
    - Home directory (~)
    - Direct children of root (/usr, /tmp, /etc, etc.)
    - Windows drive root (C:\\, D:\\) and direct children (C:\\Windows, C:\\Users)
    
    Args:
        resolved_path: Fully resolved absolute path
        
    Returns:
        True if path is dangerous for removal
        
    Example:
        >>> is_dangerous_removal_path('/')
        True
        >>> is_dangerous_removal_path('*')
        True
        >>> is_dangerous_removal_path('/home/user/project')
        False
    """
    # Normalize to forward slashes
    forward_slashed = resolved_path.replace('\\', '/')
    
    # Check wildcards
    if forward_slashed == '*' or forward_slashed.endswith('/*'):
        return True
    
    # Normalize path (remove trailing slash except for root)
    normalized_path = forward_slashed if forward_slashed == '/' else forward_slashed.rstrip('/')
    
    # Check root directory
    if normalized_path == '/':
        return True
    
    # Check Windows drive root
    if WINDOWS_DRIVE_ROOT_REGEX.match(normalized_path):
        return True
    
    # Check home directory
    normalized_home = expanduser('~').replace('\\', '/')
    if normalized_path == normalized_home:
        return True
    
    # Check direct children of root (/usr, /tmp, /etc)
    # Use string manipulation instead of Path for cross-platform compatibility
    parts = normalized_path.split('/')
    if len(parts) == 2 and parts[0] == '':
        # Path like /usr, /tmp, etc. (exactly one level deep from root)
        return True
    
    # Check Windows drive children (C:\\Windows, C:\\Users)
    if WINDOWS_DRIVE_CHILD_REGEX.match(normalized_path):
        return True
    
    return False


# ============================================================================
# Path Validation Core Logic
# ============================================================================

def _import_path_safety_functions():
    """
    Import path safety functions from filesystem_security.py.
    
    This is done lazily to avoid circular imports.
    
    Returns:
        Tuple of (check_path_safety_for_auto_edit, check_editable_internal_path, check_readable_internal_path, is_path_in_working_directories)
    """
    try:
        from filesystem_security import (
            check_path_safety_for_auto_edit,
            check_editable_internal_path,
            check_readable_internal_path,
            is_path_in_working_directories,
        )
        return (
            check_path_safety_for_auto_edit,
            check_editable_internal_path,
            check_readable_internal_path,
            is_path_in_working_directories,
        )
    except ImportError as e:
        logger.error(f'[path-validation] Failed to import filesystem_security: {e}')
        # Return dummy functions that deny everything (fail-safe)
        def deny_all(*args, **kwargs):
            return {'safe': False, 'reason': 'import_error'}
        
        def deny_access(*args, **kwargs):
            return {'behavior': 'ask', 'reason': 'import_error'}
        
        def check_working_dirs(*args, **kwargs):
            return False
        
        return deny_all, deny_access, deny_access, check_working_dirs


def is_path_allowed(
    resolved_path: str,
    context: dict[str, Any],
    operation_type: FileOperationType,
) -> PathCheckResult:
    """
    Checks if a resolved path is allowed for the given operation type.
    
    Validation order:
    1. Deny rules (highest priority)
    2. Internal editable paths (for write/create)
    3. Safety checks (Windows patterns, dangerous files)
    4. Working directory allowance (respects acceptEdits mode)
    5. Internal readable paths (for read operations)
    6. Allow rules
    
    Args:
        resolved_path: Fully resolved absolute path
        context: Tool permission context with:
            - mode: Current permission mode
            - working_directories: List of allowed working directories
            - deny_rules: Explicit deny patterns
            - allow_rules: Explicit allow patterns
        operation_type: One of 'read', 'write', 'create'
        
    Returns:
        Dictionary with:
        - allowed: bool
        - decision_reason: str (optional, why allowed/denied)
    """
    # Import safety functions
    (check_safety, check_editable, check_readable, check_working) = _import_path_safety_functions()
    
    # Determine permission type
    permission_type = 'read' if operation_type == 'read' else 'edit'
    
    # 1. Check deny rules first (they take precedence)
    deny_rules = context.get('deny_rules', [])
    for rule in deny_rules:
        pattern = rule.get('pattern') or rule.get('path')
        if pattern and pattern in resolved_path:
            return {
                'allowed': False,
                'decision_reason': f"Denied by rule: {rule}",
            }
    
    # 2. For write/create operations, check internal editable paths
    # This MUST come before safety checks since .claude is a dangerous directory
    # and internal editable paths live under ~/.claude/
    if operation_type != 'read':
        internal_edit_result = check_editable(resolved_path)
        if internal_edit_result.get('behavior') == 'allow':
            return {
                'allowed': True,
                'decision_reason': internal_edit_result.get('reason', 'Internal editable path'),
            }
    
    # 3. For write/create operations, check comprehensive safety validations
    # This MUST come before checking working directory to prevent bypass via acceptEdits mode
    if operation_type != 'read':
        safety_check = check_safety(resolved_path)
        if not safety_check.get('safe', False):
            return {
                'allowed': False,
                'decision_reason': f"Safety check failed: {safety_check.get('reason', 'unknown')}",
            }
    
    # 4. Check if path is in allowed working directory
    # For write/create operations, require acceptEdits mode to auto-allow
    working_dirs = context.get('working_directories', [])
    is_in_working_dir = check_working(resolved_path, working_dirs)
    
    if is_in_working_dir:
        if operation_type == 'read' or context.get('mode') == 'acceptEdits':
            return {'allowed': True, 'decision_reason': 'In working directory'}
        # Write/create without acceptEdits mode falls through to check allow rules
    
    # 5. For read operations, check internal readable paths
    if operation_type == 'read':
        internal_read_result = check_readable(resolved_path)
        if internal_read_result.get('behavior') == 'allow':
            return {
                'allowed': True,
                'decision_reason': internal_read_result.get('reason', 'Internal readable path'),
            }
    
    # 6. Check allow rules
    allow_rules = context.get('allow_rules', [])
    for rule in allow_rules:
        pattern = rule.get('pattern') or rule.get('path')
        if pattern and pattern in resolved_path:
            return {
                'allowed': True,
                'decision_reason': f"Allowed by rule: {rule}",
            }
    
    # 7. Path is not allowed
    return {'allowed': False}


def validate_glob_pattern(
    clean_path: str,
    cwd: str,
    context: dict[str, Any],
    operation_type: FileOperationType,
) -> ResolvedPathCheckResult:
    """
    Validates a glob pattern by checking its base directory.
    
    Returns the validation result for the base path where the glob would expand.
    
    Args:
        clean_path: Path with glob patterns (quotes removed)
        cwd: Current working directory
        context: Tool permission context
        operation_type: One of 'read', 'write', 'create'
        
    Returns:
        Dictionary with:
        - allowed: bool
        - resolved_path: str (the resolved base directory)
        - decision_reason: str (optional)
    """
    # For paths with traversal, resolve the full path
    if '..' in clean_path.split(os.sep):
        absolute_path = clean_path if isabs(clean_path) else join(cwd, clean_path)
        resolved_path = os.path.realpath(absolute_path)
        result = is_path_allowed(resolved_path, context, operation_type)
        return {
            'allowed': result['allowed'],
            'resolved_path': resolved_path,
            'decision_reason': result.get('decision_reason'),
        }
    
    # Get base directory and validate it
    base_path = get_glob_base_directory(clean_path)
    absolute_base_path = base_path if isabs(base_path) else join(cwd, base_path)
    resolved_path = os.path.realpath(absolute_base_path)
    
    result = is_path_allowed(resolved_path, context, operation_type)
    return {
        'allowed': result['allowed'],
        'resolved_path': resolved_path,
        'decision_reason': result.get('decision_reason'),
    }


def validate_path(
    path: str,
    cwd: str,
    context: dict[str, Any],
    operation_type: FileOperationType,
) -> ResolvedPathCheckResult:
    """
    Validates a file system path, handling tilde expansion and glob patterns.
    
    Returns whether the path is allowed and the resolved path for error messages.
    
    Args:
        path: File path to validate (may contain quotes, tilde, globs)
        cwd: Current working directory
        context: Tool permission context with:
            - mode: Current permission mode
            - working_directories: List of allowed working directories
            - deny_rules: Explicit deny patterns
            - allow_rules: Explicit allow patterns
        operation_type: One of 'read', 'write', 'create'
        
    Returns:
        Dictionary with:
        - allowed: bool
        - resolved_path: str
        - decision_reason: str (optional)
        
    Example:
        >>> context = {
        ...     'mode': 'acceptEdits',
        ...     'working_directories': ['/home/user/project'],
        ...     'deny_rules': [],
        ...     'allow_rules': [],
        ... }
        >>> validate_path('/home/user/project/file.txt', '/home/user/project', context, 'write')
        {'allowed': True, 'resolved_path': '/home/user/project/file.txt'}
    """
    # Remove surrounding quotes if present
    clean_path = expand_tilde(path.strip("'\""))
    
    # SECURITY: Block UNC paths that could leak credentials
    if clean_path.startswith('\\\\') or clean_path.startswith('//'):
        return {
            'allowed': False,
            'resolved_path': clean_path,
            'decision_reason': 'UNC network paths require manual approval',
        }
    
    # SECURITY: Reject tilde variants (~user, ~+, ~-, ~N) that expand_tilde doesn't handle.
    # expand_tilde resolves ~ and ~/ to $HOME, but ~root, ~+, ~- etc. are left as literal
    # text and resolved as relative paths. The shell expands these differently, creating
    # a TOCTOU gap.
    if clean_path.startswith('~'):
        return {
            'allowed': False,
            'resolved_path': clean_path,
            'decision_reason': 'Tilde expansion variants (~user, ~+, ~-) in paths require manual approval',
        }
    
    # SECURITY: Reject paths containing ANY shell expansion syntax
    # - $VAR (Unix environment variables like $HOME, $PWD)
    # - ${VAR} (brace expansion)
    # - $(cmd) (command substitution)
    # - %VAR% (Windows environment variables like %TEMP%, %USERPROFILE%)
    # - =cmd (Zsh equals expansion, e.g. =rg expands to /usr/bin/rg)
    # All of these are preserved as literal strings during validation but expanded
    # by the shell during execution, creating a TOCTOU vulnerability
    if '$' in clean_path or '%' in clean_path or clean_path.startswith('='):
        return {
            'allowed': False,
            'resolved_path': clean_path,
            'decision_reason': 'Shell expansion syntax in paths requires manual approval',
        }
    
    # SECURITY: Block glob patterns in write/create operations
    # Write tools don't expand globs - they use paths literally.
    # Allowing globs in write operations could bypass security checks.
    if GLOB_PATTERN_REGEX.search(clean_path):
        if operation_type in ('write', 'create'):
            return {
                'allowed': False,
                'resolved_path': clean_path,
                'decision_reason': 'Glob patterns are not allowed in write operations. Please specify an exact file path.',
            }
        
        # For read operations, validate the base directory where the glob would expand
        return validate_glob_pattern(clean_path, cwd, context, operation_type)
    
    # Resolve path
    absolute_path = clean_path if isabs(clean_path) else join(cwd, clean_path)
    resolved_path = os.path.realpath(absolute_path)
    
    # Check permission
    result = is_path_allowed(resolved_path, context, operation_type)
    
    return {
        'allowed': result['allowed'],
        'resolved_path': resolved_path,
        'decision_reason': result.get('decision_reason'),
    }


# ============================================================================
# Exported Symbols
# ============================================================================

__all__ = [
    # Type definitions
    'FileOperationType',
    'PathCheckResult',
    'ResolvedPathCheckResult',
    
    # Utility functions
    'format_directory_list',
    'get_glob_base_directory',
    'expand_tilde',
    
    # Dangerous removal detection
    'is_dangerous_removal_path',
    
    # Core path validation
    'is_path_allowed',
    'validate_glob_pattern',
    'validate_path',
]
