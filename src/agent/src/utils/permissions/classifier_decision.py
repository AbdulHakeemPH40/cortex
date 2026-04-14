"""
Tool safety classification for Cortex AI Agent IDE.

Defines which tools are safe to run in autonomous mode without
user confirmation, and which require explicit approval.

Safety levels:
  - ALLOW: Safe to run without confirmation (read-only, metadata)
  - ASK: Requires user confirmation (file writes, bash commands)
  - DENY: Blocked entirely (dangerous operations)

This is used by the autonomous mode classifier to skip unnecessary
permission checks for safe tools, improving performance and UX.
"""

from typing import Set

# ---------------------------------------------------------------------------
# Safe tools - no confirmation needed (read-only, metadata, coordination)
# ---------------------------------------------------------------------------

SAFE_AUTONOMOUS_TOOLS: Set[str] = {
    # Read-only file operations
    'FileReadTool',
    'GlobTool',
    'GrepTool',
    
    # Code intelligence (read-only)
    'LSPTool',
    'ToolSearchTool',
    
    # MCP resources (read-only)
    'ListMcpResourcesTool',
    'ReadMcpResourceTool',
    
    # Task management (metadata only)
    'TodoWriteTool',
    'TaskCreateTool',
    'TaskGetTool',
    'TaskUpdateTool',
    'TaskListTool',
    'TaskStopTool',
    'TaskOutputTool',
    
    # Plan mode / UI interaction
    'AskUserQuestionTool',
    'EnterPlanModeTool',
    'ExitPlanModeTool',
    
    # Worktree management
    'EnterWorktreeTool',
    'ExitWorktreeTool',
    
    # Agent coordination (teammates have their own permission checks)
    'SendMessageTool',
    'TeamCreateTool',
    'TeamDeleteTool',
    
    # Configuration
    'ConfigTool',
    
    # Misc safe operations
    'SleepTool',
    
    # Brief/documentation (read-only)
    'BriefTool',
}

# ---------------------------------------------------------------------------
# Tools requiring user confirmation (potentially destructive or costly)
# ---------------------------------------------------------------------------

REQUIRES_CONFIRMATION: Set[str] = {
    # File modifications
    'FileEditTool',
    'FileWriteTool',
    'NotebookEditTool',
    
    # Shell execution (can be dangerous)
    'BashTool',
    'PowerShellTool',
    'REPLTool',
    
    # Network access (privacy/cost concerns)
    'WebFetchTool',
    'WebSearchTool',
    
    # MCP tool execution (external integrations)
    'MCPTool',
    'McpAuthTool',
    
    # Skill execution (may have side effects)
    'SkillTool',
    
    # Remote operations
    'RemoteTriggerTool',
}

# ---------------------------------------------------------------------------
# Interpreters and code execution entry points (can run arbitrary code)
# ---------------------------------------------------------------------------

INTERPRETER_PATTERNS: Set[str] = {
    # Python
    'python',
    'python3',
    'python2',
    # JavaScript/TypeScript
    'node',
    'deno',
    'tsx',
    # Other interpreters
    'ruby',
    'perl',
    'php',
    'lua',
}

# ---------------------------------------------------------------------------
# Package runners (can execute arbitrary scripts)
# ---------------------------------------------------------------------------

PACKAGE_RUNNERS: Set[str] = {
    # Node.js runners
    'npx',
    'bunx',
    'npm run',
    'yarn run',
    'pnpm run',
    'bun run',
}

# ---------------------------------------------------------------------------
# Shells (can bypass restrictions)
# ---------------------------------------------------------------------------

SHELL_PATTERNS: Set[str] = {
    'bash',
    'sh',
    'zsh',
    'fish',
}

# ---------------------------------------------------------------------------
# Code execution wrappers
# ---------------------------------------------------------------------------

EXEC_PATTERNS: Set[str] = {
    'eval',
    'exec',
    'xargs',
    'ssh',  # Remote code execution
}

# ---------------------------------------------------------------------------
# Dangerous tools - blocked or require explicit admin approval
# ---------------------------------------------------------------------------

DANGEROUS_TOOLS: Set[str] = {
    # Add dangerous tools here if your IDE has any
    # Examples:
    # 'DeleteAllFilesTool',
    # 'FormatDiskTool',
    # 'DeployToProductionTool',
}

# ---------------------------------------------------------------------------
# Safe bash command patterns (for BashTool/PowerShellTool)
# ---------------------------------------------------------------------------

SAFE_BASH_PATTERNS: Set[str] = {
    # Navigation
    'ls', 'dir', 'pwd', 'cd',
    
    # File reading
    'cat', 'head', 'tail', 'less', 'more',
    
    # Search
    'grep', 'find', 'which', 'where', 'whereis',
    
    # Git (read-only)
    'git status', 'git log', 'git diff', 'git branch', 'git tag',
    'git remote -v', 'git stash list',
    
    # System info
    'python --version', 'node --version', 'npm --version',
    'pip list', 'pip show',
    
    # Environment
    'echo', 'printenv', 'env',
}

# ---------------------------------------------------------------------------
# Dangerous bash patterns (always require confirmation)
# Merged from dangerousPatterns.ts for comprehensive coverage
# ---------------------------------------------------------------------------

DANGEROUS_BASH_PATTERNS: Set[str] = {
    # Interpreters (can run arbitrary code)
    *INTERPRETER_PATTERNS,
    
    # Package runners (can execute arbitrary scripts)
    *PACKAGE_RUNNERS,
    
    # Shells (can bypass restrictions)
    *SHELL_PATTERNS,
    
    # Code execution wrappers
    *EXEC_PATTERNS,
    
    # Destructive file operations
    'rm -rf', 'rm -f', 'del /f', 'del /s',
    
    # System destruction
    'sudo rm', 'dd if=/dev/zero', 'mkfs', 'fdisk',
    
    # Fork bombs
    ':(){ :|:& };:',
    
    # Overwrite system files
    '> /etc/passwd', '> /etc/shadow', '> /etc/sudoers',
    
    # Pipe to shell (security risk)
    'curl | bash', 'curl | sh', 'wget | sh', 'wget | bash',
    
    # Privilege escalation
    'sudo', 'sudo su', 'sudo -i', 'su root',
    
    # Dangerous permission changes
    'chmod 777', 'chmod -R 777',
    
    # Force push (destructive git)
    'git push --force', 'git push -f',
    
    # Environment manipulation
    'env',
}


# ---------------------------------------------------------------------------
# Core classification functions
# ---------------------------------------------------------------------------

def is_safe_for_autonomous_mode(tool_name: str) -> bool:
    """
    Check if a tool is safe to run in autonomous mode without confirmation.
    
    Args:
        tool_name: Name of the tool to check
        
    Returns:
        True if tool can run without user confirmation
        
    Example:
        is_safe_for_autonomous_mode('FileReadTool') → True
        is_safe_for_autonomous_mode('BashTool') → False
    """
    return tool_name in SAFE_AUTONOMOUS_TOOLS


def get_tool_safety_level(tool_name: str) -> str:
    """
    Get safety level for a tool.
    
    Args:
        tool_name: Name of the tool to classify
        
    Returns:
        'allow' - Safe to run without confirmation
        'ask' - Requires user confirmation
        'deny' - Blocked entirely
        
    Example:
        get_tool_safety_level('FileReadTool') → 'allow'
        get_tool_safety_level('FileEditTool') → 'ask'
    """
    if tool_name in SAFE_AUTONOMOUS_TOOLS:
        return 'allow'
    if tool_name in REQUIRES_CONFIRMATION:
        return 'ask'
    if tool_name in DANGEROUS_TOOLS:
        return 'deny'
    # Default: require confirmation for unknown tools
    return 'ask'


def is_bash_command_safe(command: str) -> bool:
    """
    Check if a bash command is safe to run without confirmation.
    
    Args:
        command: Bash command to check
        
    Returns:
        True if command is safe
        
    Example:
        is_bash_command_safe('ls -la') → True
        is_bash_command_safe('rm -rf /tmp/test') → False
    """
    command_lower = command.lower().strip()
    
    # Check if it matches any dangerous pattern (case-insensitive)
    for pattern in DANGEROUS_BASH_PATTERNS:
        if pattern.lower() in command_lower:
            return False
    
    # Check if it matches safe patterns (case-insensitive)
    for pattern in SAFE_BASH_PATTERNS:
        if command_lower.startswith(pattern.lower()):
            return True
    
    # Default: require confirmation for unknown commands
    return False


def get_bash_command_risk_level(command: str) -> str:
    """
    Get risk level for a bash command.
    
    Args:
        command: Bash command to classify
        
    Returns:
        'safe' - Can run without confirmation
        'caution' - Should show warning
        'dangerous' - Requires explicit approval
    """
    command_lower = command.lower().strip()
    
    # Check dangerous patterns first
    for pattern in DANGEROUS_BASH_PATTERNS:
        if pattern in command_lower:
            return 'dangerous'
    
    # Check safe patterns
    for pattern in SAFE_BASH_PATTERNS:
        if command_lower.startswith(pattern):
            return 'safe'
    
    # Default: caution for unknown commands
    return 'caution'


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def get_safe_tools_list() -> list[str]:
    """Get sorted list of all safe tools for autonomous mode"""
    return sorted(SAFE_AUTONOMOUS_TOOLS)


def get_restricted_tools_list() -> list[str]:
    """Get sorted list of all tools requiring confirmation"""
    return sorted(REQUIRES_CONFIRMATION)


def get_dangerous_tools_list() -> list[str]:
    """Get sorted list of all dangerous/blocked tools"""
    return sorted(DANGEROUS_TOOLS)


def get_tool_safety_summary() -> dict:
    """
    Get summary of tool safety classification.
    
    Returns:
        Dict with counts and lists for each safety level
    """
    return {
        'safe_count': len(SAFE_AUTONOMOUS_TOOLS),
        'requires_confirmation_count': len(REQUIRES_CONFIRMATION),
        'dangerous_count': len(DANGEROUS_TOOLS),
        'safe_tools': get_safe_tools_list(),
        'restricted_tools': get_restricted_tools_list(),
        'dangerous_tools': get_dangerous_tools_list(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Safety sets
    'SAFE_AUTONOMOUS_TOOLS',
    'REQUIRES_CONFIRMATION',
    'DANGEROUS_TOOLS',
    'SAFE_BASH_PATTERNS',
    'DANGEROUS_BASH_PATTERNS',
    
    # Pattern categories (for customization)
    'INTERPRETER_PATTERNS',
    'PACKAGE_RUNNERS',
    'SHELL_PATTERNS',
    'EXEC_PATTERNS',
    
    # Core functions
    'is_safe_for_autonomous_mode',
    'get_tool_safety_level',
    'is_bash_command_safe',
    'get_bash_command_risk_level',
    
    # Utility functions
    'get_safe_tools_list',
    'get_restricted_tools_list',
    'get_dangerous_tools_list',
    'get_tool_safety_summary',
]
