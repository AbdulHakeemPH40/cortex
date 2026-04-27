"""
frontmatterParser - YAML frontmatter extraction from markdown files.

Used by memoryScan.py to read memory file headers (name, description, type).
Simple regex-based parser — no external dependencies required.
"""

import re
from typing import Any, Dict


def parseFrontmatter(content: str, file_path: str = '') -> Dict[str, Any]:
    """
    Parse YAML frontmatter from the top of a markdown file.

    Expects content to start with --- (opening fence), followed by key: value
    lines, then a closing --- line.

    Returns:
        {'frontmatter': {key: value, ...}}
        Returns {'frontmatter': {}} if no valid frontmatter is found.
    """
    if not content or not content.startswith('---'):
        return {'frontmatter': {}}

    # Find the closing ---
    end_match = re.search(r'\n---', content[3:])
    if not end_match:
        return {'frontmatter': {}}

    fm_text = content[3 : 3 + end_match.start()].strip()
    frontmatter: Dict[str, Any] = {}

    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            key, _, raw_val = line.partition(':')
            key = key.strip()
            val = raw_val.strip()
            # Strip surrounding quotes
            if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
                val = val[1:-1]
            # Coerce simple booleans / numbers
            if val.lower() == 'true':
                frontmatter[key] = True
            elif val.lower() == 'false':
                frontmatter[key] = False
            else:
                try:
                    frontmatter[key] = int(val)
                except ValueError:
                    try:
                        frontmatter[key] = float(val)
                    except ValueError:
                        frontmatter[key] = val

    return {'frontmatter': frontmatter}
