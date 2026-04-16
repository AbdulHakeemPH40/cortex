# utils/shell/shell_tool_utils.py
# Python conversion of shellToolUtils.ts
# Shell tool utilities

import os
import platform


SHELL_TOOL_NAMES = ["Bash", "PowerShell"]


def is_power_shell_tool_enabled() -> bool:
    """
    Runtime gate for PowerShellTool. Windows-only (the permission engine uses
    Win32-specific path normalizations). Ant defaults on (opt-out via env=0);
    external defaults off (opt-in via env=1).
    
    Used by tools.ts (tool-list visibility), processBashCommand (! routing),
    and promptShellExecution (skill frontmatter routing) so the gate is
    consistent across all paths that invoke PowerShellTool.call().
    """
    if platform.system() != 'Windows':
        return False
    
    from ..env_utils import is_env_truthy, is_env_defined_falsy
    
    if os.environ.get('USER_TYPE') == 'ant':
        return not is_env_defined_falsy(os.environ.get('CLAUDE_CODE_USE_POWERSHELL_TOOL'))
    else:
        return is_env_truthy(os.environ.get('CLAUDE_CODE_USE_POWERSHELL_TOOL'))


__all__ = ['SHELL_TOOL_NAMES', 'is_power_shell_tool_enabled']
