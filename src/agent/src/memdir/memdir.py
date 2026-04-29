"""
Auto-generated stub for memdir.memdir.
TODO: Implement based on requirements.
"""
from typing import Any, Dict, List, Optional
import os


__all__ = ["buildMemoryPrompt"]


def buildMemoryPrompt(options: Dict[str, Any]) -> str:
    """
    Build a memory system prompt from the memory directory.

    Args:
        options: Dict with keys:
            - displayName: str — human-readable name for the memory system
            - memoryDir: str — absolute path to the memory directory

    Returns:
        A markdown string describing the memory system, or empty string if not available.
    """
    memory_dir = options.get("memoryDir", "")
    display_name = options.get("displayName", "Memory")

    if not memory_dir or not os.path.isdir(memory_dir):
        return ""

    index_path = os.path.join(memory_dir, "MEMORY.md")
    if not os.path.isfile(index_path):
        return ""

    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
    except OSError:
        return ""

    if not content:
        return ""

    return (
        f"# {display_name}\n\n"
        f"Memory directory: `{memory_dir}`\n\n"
        f"## MEMORY.md Index\n\n{content}"
    )
