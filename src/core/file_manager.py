"""
File Manager — handles reading, writing, and watching files.
"""

import os
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from src.utils.helpers import detect_language
from src.utils.logger import get_logger

log = get_logger("file_manager")


class FileManager(QObject):
    file_changed_on_disk = pyqtSignal(str)  # path of changed file

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open_files: dict[str, str] = {}  # path -> content

    def read(self, filepath: str) -> str | None:
        """Read a text file, auto-detecting encoding."""
        path = Path(filepath)
        if not path.exists():
            log.warning(f"File not found: {filepath}")
            return None
        try:
            import chardet
            raw = path.read_bytes()
            detected = chardet.detect(raw)
            enc = detected.get("encoding") or "utf-8"
            content = raw.decode(enc, errors="replace")
            self._open_files[str(path.resolve())] = content
            return content
        except Exception as e:
            log.error(f"Cannot read {filepath}: {e}")
            return None

    def write(self, filepath: str, content: str) -> bool:
        """Write content to file."""
        try:
            Path(filepath).write_text(content, encoding="utf-8")
            self._open_files[str(Path(filepath).resolve())] = content
            log.info(f"Saved: {filepath}")
            return True
        except Exception as e:
            log.error(f"Cannot write {filepath}: {e}")
            return False

    def is_binary(self, filepath: str) -> bool:
        """Detect if a file is binary (not suitable for text editing)."""
        try:
            with open(filepath, "rb") as f:
                chunk = f.read(8192)
            return b"\x00" in chunk
        except Exception:
            return True

    def language(self, filepath: str) -> str:
        return detect_language(filepath)

    def new_file(self, folder: str, name: str) -> str | None:
        """Create a new empty file."""
        path = Path(folder) / name
        try:
            path.touch(exist_ok=False)
            return str(path)
        except FileExistsError:
            log.warning(f"File already exists: {path}")
            return None
        except Exception as e:
            log.error(f"Cannot create file: {e}")
            return None

    def rename(self, old_path: str, new_name: str) -> str | None:
        old = Path(old_path)
        new = old.parent / new_name
        try:
            old.rename(new)
            return str(new)
        except Exception as e:
            log.error(f"Cannot rename: {e}")
            return None

    def delete(self, filepath: str) -> bool:
        try:
            path = Path(filepath)
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                import shutil
                shutil.rmtree(path)
            return True
        except Exception as e:
            log.error(f"Cannot delete {filepath}: {e}")
            return False
