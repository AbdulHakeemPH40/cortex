"""
Theme Manager for Cortex AI Agent IDE
Handles light/dark QSS stylesheet loading and live theme switching.
"""

from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal


THEMES_DIR = Path(__file__).parent.parent / "ui" / "themes"


class ThemeManager(QObject):
    theme_changed = pyqtSignal(str)  # emits 'dark' or 'light'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = "dark"

    def apply(self, theme_name: str, app: QApplication = None):
        """Load and apply a QSS theme to the whole application."""
        self._current = theme_name
        qss_file = THEMES_DIR / f"{theme_name}.qss"

        if not qss_file.exists():
            print(f"[ThemeManager] Theme file not found: {qss_file}")
            return

        with open(qss_file, "r", encoding="utf-8") as f:
            stylesheet = f.read()

        target = app or QApplication.instance()
        if target:
            target.setStyleSheet(stylesheet)
            self.theme_changed.emit(theme_name)

    def toggle(self, app: QApplication = None):
        """Toggle between dark and light themes."""
        new_theme = "light" if self._current == "dark" else "dark"
        self.apply(new_theme, app)
        return new_theme

    @property
    def current(self) -> str:
        return self._current

    @property
    def is_dark(self) -> bool:
        return self._current == "dark"


# Singleton
_theme_manager = None


def get_theme_manager() -> ThemeManager:
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager
