# ------------------------------------------------------------
# commentLabel.py
# Python conversion of commentLabel.ts (lines 1-14)
# 
# Extracts bash comment labels from commands for UI display.
# If the first line of a bash command is a `# comment` (not a 
# `#!` shebang), returns the comment text stripped of the `#` 
# prefix. Otherwise returns None.
# 
# Under fullscreen mode this is the non-verbose tool-use label 
# AND the collapse-group hint — it's what Claude wrote for the 
# human to read.
# ------------------------------------------------------------

from typing import Optional


def extract_bash_comment_label(command: str) -> Optional[str]:
    """
    Extract bash comment label from command for UI display.
    
    If the first line of a bash command is a `# comment` (not a `#!` shebang),
    return the comment text stripped of the `#` prefix. Otherwise return None.
    
    Under fullscreen mode this is the non-verbose tool-use label AND the
    collapse-group hint — it's what Claude wrote for the human to read.
    
    Args:
        command: The bash command string
    
    Returns:
        Comment text without # prefix, or None if no comment found
    """
    # Find first newline
    nl = command.find('\n')
    # Extract first line
    first_line = command[:nl].strip() if nl != -1 else command.strip()
    
    # Must start with # but not #!
    if not first_line.startswith('#') or first_line.startswith('#!'):
        return None
    
    # Strip leading # characters and whitespace
    result = first_line.lstrip('#').lstrip()
    
    # Return None if empty after stripping
    return result if result else None


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "extract_bash_comment_label",
]
