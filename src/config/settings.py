"""
Settings Manager for Cortex AI Agent IDE
Handles loading and saving user preferences to ~/.cortex/settings.json
"""

import json
import os
from pathlib import Path


DEFAULT_SETTINGS = {
    "theme": "dark",
    "editor": {
        "font_family": "Courier New",
        "font_size": 13,
        "tab_size": 4,
        "word_wrap": False,
        "line_numbers": True,
        "highlight_current_line": True,
        "auto_indent": True,
    },
    "ai": {
        "model": "deepseek-chat",
        "temperature": 0.7,
        "max_tokens": 4096,
        "provider": "deepseek",  # openai | anthropic | deepseek | mock
    },
    "window": {
        "width": 1400,
        "height": 900,
        "sidebar_width": 260,
        "right_panel_width": 320,
        "maximized": False,
    },
    "recent_projects": [],
    "last_project": None,
}


class Settings:
    """Manages persistent application settings stored as JSON."""

    def __init__(self):
        self._config_dir = Path.home() / ".cortex"
        self._config_file = self._config_dir / "settings.json"
        self._data = {}
        self._load()

    def _load(self):
        """Load settings from disk, merging with defaults."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if self._config_file.exists():
            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                self._data = self._merge(DEFAULT_SETTINGS, stored)
            except (json.JSONDecodeError, OSError):
                self._data = dict(DEFAULT_SETTINGS)
        else:
            self._data = json.loads(json.dumps(DEFAULT_SETTINGS))
            self._save()

    def _merge(self, defaults: dict, overrides: dict) -> dict:
        """Deep-merge overrides into defaults."""
        result = dict(defaults)
        for key, val in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self._merge(result[key], val)
            else:
                result[key] = val
        return result

    def _save(self):
        """Persist settings to disk."""
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            print(f"[Settings] Could not save settings: {e}")

    def get(self, *keys, default=None):
        """Get a value by dot-path keys, e.g. get('editor', 'font_size')."""
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def set(self, *keys_and_value):
        """Set a value by dot-path keys + value, e.g. set('editor', 'font_size', 14)."""
        *keys, value = keys_and_value
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self._save()

    def add_recent_project(self, path: str):
        """Add a project path to recent list (max 10)."""
        recents = self._data.setdefault("recent_projects", [])
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._data["recent_projects"] = recents[:10]
        self._save()

    def get_recent_projects(self) -> list:
        return self._data.get("recent_projects", [])

    @property
    def theme(self) -> str:
        return self._data.get("theme", "dark")

    @theme.setter
    def theme(self, value: str):
        self._data["theme"] = value
        self._save()

    def all(self) -> dict:
        return self._data


# Singleton instance
_settings = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
