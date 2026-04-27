"""
General string utility functions and classes for safe string accumulation.
"""

import re
from typing import Union


def escapeRegExp(s: str) -> str:
    """Escapes special regex characters in a string so it can be used as a literal pattern."""
    return re.sub(r'[.*+?^${}()|[\]\\]', r'\\$&', s)


def capitalize(s: str) -> str:
    """Uppercases the first character of a string, leaving the rest unchanged.
    
    Unlike lodash `capitalize`, this does NOT lowercase the remaining characters.
    
    Examples:
        capitalize('fooBar') → 'FooBar'
        capitalize('hello world') → 'Hello world'
    """
    if not s:
        return s
    return s[0].upper() + s[1:]


def plural(n: int, word: str, plural_word: str = None) -> str:
    """Returns the singular or plural form of a word based on count.
    
    Replaces the inline `word${n === 1 ? '' : 's'}` idiom.
    
    Examples:
        plural(1, 'file') → 'file'
        plural(3, 'file') → 'files'
        plural(2, 'entry', 'entries') → 'entries'
    """
    if plural_word is None:
        plural_word = word + 's'
    return word if n == 1 else plural_word


def firstLineOf(s: str) -> str:
    """Returns the first line of a string without allocating a split array.
    
    Used for shebang detection in diff rendering.
    """
    nl = s.find('\n')
    return s if nl == -1 else s[:nl]


def countCharInString(str_obj: Union[str, bytes], char: str, start: int = 0) -> int:
    """Counts occurrences of `char` in `str` using indexOf jumps instead of per-character iteration.
    
    Structurally typed so Buffer works too (Buffer.indexOf accepts string needles).
    """
    count = 0
    i = str_obj.find(char.encode() if isinstance(str_obj, bytes) and len(char) == 1 else char, start)
    while i != -1:
        count += 1
        i = str_obj.find(char.encode() if isinstance(str_obj, bytes) and len(char) == 1 else char, i + 1)
    return count


def normalizeFullWidthDigits(input_str: str) -> str:
    """Normalize full-width (zenkaku) digits to half-width digits.
    
    Useful for accepting input from Japanese/CJK IMEs.
    """
    def replace_char(ch):
        return chr(ord(ch) - 0xFEE0)
    
    return re.sub(r'[０-９]', replace_char, input_str)


def normalizeFullWidthSpace(input_str: str) -> str:
    """Normalize full-width (zenkaku) space to half-width space.
    
    Useful for accepting input from Japanese/CJK IMEs (U+3000 → U+0020).
    """
    return input_str.replace('\u3000', ' ')


# Keep in-memory accumulation modest to avoid blowing up RSS.
# Overflow beyond this limit is spilled to disk by ShellCommand.
MAX_STRING_LENGTH = 2 ** 25


def safeJoinLines(lines: list, delimiter: str = ',', max_size: int = MAX_STRING_LENGTH) -> str:
    """Safely joins an array of strings with a delimiter, truncating if the result exceeds maxSize.
    
    Args:
        lines: Array of strings to join
        delimiter: Delimiter to use between strings (default: ',')
        max_size: Maximum size of the resulting string
    
    Returns:
        The joined string, truncated if necessary
    """
    truncation_marker = '...[truncated]'
    result = ''

    for line in lines:
        delimiter_to_add = delimiter if result else ''
        full_addition = delimiter_to_add + line

        if len(result) + len(full_addition) <= max_size:
            # The full line fits
            result += full_addition
        else:
            # Need to truncate
            remaining_space = max_size - len(result) - len(delimiter_to_add) - len(truncation_marker)

            if remaining_space > 0:
                # Add delimiter and as much of the line as will fit
                result += delimiter_to_add + line[:remaining_space] + truncation_marker
            else:
                # No room for any of this line, just add truncation marker
                result += truncation_marker
            return result
    
    return result


class EndTruncatingAccumulator:
    """A string accumulator that safely handles large outputs by truncating from the end
    when a size limit is exceeded. This prevents RangeError crashes while preserving
    the beginning of the output.
    """
    
    def __init__(self, max_size: int = MAX_STRING_LENGTH):
        """Creates a new EndTruncatingAccumulator
        
        Args:
            max_size: Maximum size in characters before truncation occurs
        """
        self._max_size = max_size
        self._content = ''
        self._is_truncated = False
        self._total_bytes_received = 0

    def append(self, data: Union[str, bytes]) -> None:
        """Appends data to the accumulator. If the total size exceeds max_size,
        the end is truncated to maintain the size limit.
        
        Args:
            data: The string data to append
        """
        if isinstance(data, bytes):
            str_data = data.decode('utf-8', errors='replace')
        else:
            str_data = data
            
        self._total_bytes_received += len(str_data)

        # If already at capacity and truncated, don't modify content
        if self._is_truncated and len(self._content) >= self._max_size:
            return

        # Check if adding the string would exceed the limit
        if len(self._content) + len(str_data) > self._max_size:
            # Only append what we can fit
            remaining_space = self._max_size - len(self._content)
            if remaining_space > 0:
                self._content += str_data[:remaining_space]
            self._is_truncated = True
        else:
            self._content += str_data

    def toString(self) -> str:
        """Returns the accumulated string, with truncation marker if truncated."""
        if not self._is_truncated:
            return self._content

        truncated_bytes = self._total_bytes_received - self._max_size
        truncated_kb = round(truncated_bytes / 1024)
        return f"{self._content}\n... [output truncated - {truncated_kb}KB removed]"

    def clear(self) -> None:
        """Clears all accumulated data."""
        self._content = ''
        self._is_truncated = False
        self._total_bytes_received = 0

    @property
    def length(self) -> int:
        """Returns the current size of accumulated data."""
        return len(self._content)

    @property
    def truncated(self) -> bool:
        """Returns whether truncation has occurred."""
        return self._is_truncated

    @property
    def totalBytes(self) -> int:
        """Returns total bytes received (before truncation)."""
        return self._total_bytes_received


def truncateToLines(text: str, max_lines: int) -> str:
    """Truncates text to a maximum number of lines, adding an ellipsis if truncated.
    
    Args:
        text: The text to truncate
        max_lines: Maximum number of lines to keep
    
    Returns:
        The truncated text with ellipsis if truncated
    """
    lines = text.split('\n')
    if len(lines) <= max_lines:
        return text
    return '\n'.join(lines[:max_lines]) + '…'
