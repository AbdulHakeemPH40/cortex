"""
Fix Corrupted Newline Escape Sequences in script.js

This script repairs a specific corruption pattern in a JavaScript file where
literal newline characters were incorrectly inserted into regex patterns and
replacement strings that should have contained ``\\n`` escape sequences.

The bug manifests when a line like::

    text = text.replace(/\\n{4,}/g, '\\n\\n\\n');

is corrupted into actual newlines::

    text = text.replace(/\n{4,}/g, '\n\n\n');

This script detects and repairs both 8-space and 5-space indentation variants
of the corrupted pattern.

Usage:
    Run directly as a standalone script::

        python fix_newline_escapes.py

Author: Cortex AI Agent
"""

import re


def fix_corrupted_newlines(
    filepath: str = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'
) -> None:
    """
    Read a JavaScript file, fix corrupted newline escape sequences, and write it back.

    The function looks for two specific corruption patterns where ``\\n`` escape
    sequences were replaced by literal newline characters inside a
    ``String.prototype.replace()`` call. If found, the corrupted patterns are
    replaced with the correct single-line forms using escaped newlines.

    Args:
        filepath: Absolute or relative path to the ``script.js`` file to repair.
            Defaults to the known path in the Cortex IDE project.

    Returns:
        None. The file is modified in-place.

    Raises:
        FileNotFoundError: If the specified *filepath* does not exist.
        PermissionError: If the script lacks read/write permissions for *filepath*.
        OSError: For other I/O related errors during file read/write.

    Example:
        >>> fix_corrupted_newlines("./src/ui/html/ai_chat/script.js")
        Found corrupted1: 1 times
        Found corrupted2: 0 times
        Fixed!
    """
    # ------------------------------------------------------------------
    # Read the entire file into memory so we can perform exact-string
    # replacements safely. The file is expected to be UTF-8 encoded.
    # ------------------------------------------------------------------
    with open(filepath, 'r', encoding='utf-8') as f:
        content: str = f.read()

    # ------------------------------------------------------------------
    # Define the corruption patterns and their corrected counterparts.
    #
    # Corruption explanation:
    #   The original JavaScript intended to collapse 4+ consecutive "\\n"
    #   (escaped newline characters) down to exactly three "\\n".
    #   A previous transformation mistakenly turned the ``\\n`` text into
    #   literal newline bytes, splitting the single logical line across
    #   multiple physical lines and breaking the regex syntax.
    #
    # We handle two indentation variants because the source may have
    #   been reformatted with different leading whitespace at different
    #   locations or during different edits.
    # ------------------------------------------------------------------

    # Variant 1: 8 leading spaces (typical deeply-nested block indentation)
    corrupted_8space: str = (
        '        text = text.replace(/\n{4,}/g, \'\n\n\n\');\n'
    )
    correct_8space: str = (
        '        text = text.replace(/\\n{4,}/g, \'\\n\\n\\n\');\n'
    )

    # Variant 2: 5 leading spaces (shallower nesting or manual dedent)
    corrupted_5space: str = (
        '     text = text.replace(/\n{4,}/g, \'\n\n\n\');\n'
    )
    correct_5space: str = (
        '     text = text.replace(/\\n{4,}/g, \'\\n\\n\\n\');\n'
    )

    # ------------------------------------------------------------------
    # Apply fixes. We use ``str.count()`` to report how many instances
    # were found, then ``str.replace()`` to perform the substitution.
    # Each variant is processed independently so diagnostics are clear.
    # ------------------------------------------------------------------
    count_8: int = content.count(corrupted_8space)
    print(f'Found corrupted1 (8-space indent): {count_8} times')
    if count_8 > 0:
        content = content.replace(corrupted_8space, correct_8space)

    count_5: int = content.count(corrupted_5space)
    print(f'Found corrupted2 (5-space indent): {count_5} times')
    if count_5 > 0:
        content = content.replace(corrupted_5space, correct_5space)

    # ------------------------------------------------------------------
    # Persist the repaired content back to disk.
    # ``newline=''`` preserves the existing line endings (CRLF or LF)
    # exactly as they were in the original file, preventing accidental
    # line-ending normalisation on Windows.
    # ------------------------------------------------------------------
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        f.write(content)

    print('Fixed!')


if __name__ == '__main__':
    fix_corrupted_newlines()
