"""
Helper utilities for Cortex AI Agent IDE
"""
import os
from pathlib import Path


LANGUAGE_MAP = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".jsx":  "jsx",
    ".tsx":  "tsx",
    ".html": "html",
    ".css":  "css",
    ".json": "json",
    ".md":   "markdown",
    ".yml":  "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".sh":   "bash",
    ".bat":  "batch",
    ".ps1":  "powershell",
    ".cpp":  "cpp",
    ".c":    "c",
    ".h":    "c",
    ".rs":   "rust",
    ".go":   "go",
    ".java": "java",
    ".rb":   "ruby",
    ".php":  "php",
    ".sql":  "sql",
    ".xml":  "xml",
    ".txt":  "text",
    ".env":  "bash",
    ".ini":  "ini",
    ".cfg":  "ini",
}

FILE_ICONS = {
    ".py":   "🐍",
    ".js":   "📜",
    ".ts":   "📘",
    ".html": "🌐",
    ".css":  "🎨",
    ".json": "📋",
    ".md":   "📝",
    ".yml":  "⚙️",
    ".yaml": "⚙️",
    ".txt":  "📄",
    ".env":  "🔑",
    ".git":  "🔀",
    "dir":   "📁",
}


def detect_language(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    return LANGUAGE_MAP.get(ext, "text")


def file_icon(filepath: str, is_dir: bool = False) -> str:
    if is_dir:
        return FILE_ICONS["dir"]
    ext = Path(filepath).suffix.lower()
    return FILE_ICONS.get(ext, "📄")


def human_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def shorten_path(path: str, max_len: int = 50) -> str:
    p = Path(path)
    s = str(p)
    if len(s) <= max_len:
        return s
    return "…/" + "/".join(p.parts[-2:])
