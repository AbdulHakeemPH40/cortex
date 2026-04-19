"""
Web-based Memory Manager dialog for Cortex IDE.

Hosts a QWebEngineView that renders the memory manager UI from
src/ui/html/memory_manager/memory_management.html and exposes a small
QWebChannel bridge for memory CRUD actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import List

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QVBoxLayout
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from src.utils.logger import get_logger

log = get_logger("memory_manager")


def _parse_frontmatter(content: str):
    """Return (frontmatter_dict, body_text)."""
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body = content[end + 4 :].strip()
    fm: dict = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        fm[key] = value
    return fm, body


def _compute_memory_dir(project_root: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\0]', "_", project_root).strip("_ ")
    if len(sanitized) > 60:
        digest = hashlib.md5(project_root.encode("utf-8")).hexdigest()[:8]
        sanitized = sanitized[-52:].lstrip("_") + "_" + digest
    return os.path.join(os.path.expanduser("~"), ".cortex", "projects", sanitized, "memory")

def _compute_global_memory_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".cortex", "global", "memory")


def _compute_project_rules_dir(project_root: str) -> str:
    return os.path.join(project_root, ".cortex", "rules")


def _compute_global_rules_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".cortex", "rules")


def _age_label(mtime: float) -> str:
    days = int((time.time() - mtime) / 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _load_memories(memory_dir: str) -> List[dict]:
    memories: List[dict] = []
    if not os.path.isdir(memory_dir):
        return memories

    for root, _dirs, files in os.walk(memory_dir):
        for fname in files:
            if not fname.endswith(".md") or fname == "MEMORY.md":
                continue
            fpath = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(fpath)
                with open(fpath, encoding="utf-8") as handle:
                    raw = handle.read()
                fm, body = _parse_frontmatter(raw)
                mem_type = fm.get("type", "").strip()
                description = fm.get("description", "").strip()
                memories.append(
                    {
                        "path": fpath,
                        "filename": os.path.relpath(fpath, memory_dir).replace("\\", "/"),
                        "name": fm.get("name") or os.path.splitext(fname)[0],
                        "description": description,
                        "type": mem_type,
                        "body": body,
                        "mtime": mtime,
                        "age": _age_label(mtime),
                        "stale": int((time.time() - mtime) / 86400) > 7,
                        "keywords": [part.strip() for part in description.split(",") if part.strip()],
                    }
                )
            except Exception as exc:
                log.warning(f"Failed to parse memory file {fpath}: {exc}")

    memories.sort(key=lambda item: item["mtime"], reverse=True)
    return memories


class _MemoryPage(QWebEnginePage):
    """Capture JS console messages for easier debugging."""

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        level_value = level.value if hasattr(level, "value") else int(level)
        if level_value >= 1 or "[MEMORY]" in message:
            log.info(f"[MEMORY_JS] {message} ({source_id}:{line_number})")


class MemoryManagerBridge(QObject):
    data_changed = pyqtSignal(str)
    toast_requested = pyqtSignal(str, str)

    def __init__(self, project_root: str, settings=None, parent=None):
        super().__init__(parent)
        self._project_root = project_root or os.getcwd()
        self._settings = settings
        self._project_memory_dir = _compute_memory_dir(self._project_root)
        self._global_memory_dir = _compute_global_memory_dir()
        self._project_rules_dir = _compute_project_rules_dir(self._project_root)
        self._global_rules_dir = _compute_global_rules_dir()
        if self._settings:
            self._enabled = bool(self._settings.get("memory", "enabled", default=True))
            self._active_scope = str(self._settings.get("memory", "ui_scope", default="project") or "project")
        else:
            self._enabled = True
            self._active_scope = "project"

        if self._active_scope not in ("project", "global"):
            self._active_scope = "project"

    def _get_scope_dir(self, scope: str) -> str:
        return self._global_memory_dir if scope == "global" else self._project_memory_dir

    def _serialize_state(self) -> str:
        payload = {
            "enabled": self._enabled,
            "activeScope": self._active_scope,
            "scopes": {
                "project": {
                    "name": "Current Project",
                    "memoryDir": self._project_memory_dir,
                    "rulesDir": self._project_rules_dir,
                    "memories": _load_memories(self._project_memory_dir),
                },
                "global": {
                    "name": "Global",
                    "memoryDir": self._global_memory_dir,
                    "rulesDir": self._global_rules_dir,
                    "memories": _load_memories(self._global_memory_dir),
                },
            },
        }
        return json.dumps(payload)

    def _emit_refresh(self):
        payload = self._serialize_state()
        self.data_changed.emit(payload)
        return payload

    def _remove_from_index(self, memory_dir: str, filename: str):
        index_path = os.path.join(memory_dir, "MEMORY.md")
        if not os.path.exists(index_path):
            return
        try:
            with open(index_path, encoding="utf-8") as handle:
                lines = handle.readlines()
            stem = os.path.splitext(filename)[0]
            new_lines = [line for line in lines if stem not in line and filename not in line]
            with open(index_path, "w", encoding="utf-8") as handle:
                handle.writelines(new_lines)
        except Exception as exc:
            log.warning(f"Failed to update memory index {index_path}: {exc}")

    @pyqtSlot(result=str)
    def loadInitialData(self):
        return self._serialize_state()

    @pyqtSlot(result=str)
    def refresh(self):
        return self._emit_refresh()

    @pyqtSlot(str, result=str)
    def setActiveScope(self, scope: str):
        scope = (scope or "").strip().lower()
        if scope not in ("project", "global"):
            return self._emit_refresh()
        self._active_scope = scope
        if self._settings:
            self._settings.set("memory", "ui_scope", scope)
        return self._emit_refresh()

    @pyqtSlot(object, result=str)
    def setMemoryEnabled(self, checked):
        self._enabled = bool(checked)
        if self._settings:
            self._settings.set("memory", "enabled", self._enabled)
        log.info(f"Memory enabled set to {self._enabled}")
        self.toast_requested.emit("success", "Memory generation updated")
        return self._emit_refresh()

    @pyqtSlot(str, str, result=str)
    def deleteMemory(self, scope: str, path: str):
        scope = (scope or "").strip().lower()
        if scope not in ("project", "global"):
            scope = self._active_scope
        memory_dir = self._get_scope_dir(scope)
        name = os.path.basename(path or "")
        try:
            os.remove(path)
            self._remove_from_index(memory_dir, name)
            self.toast_requested.emit("success", f"Deleted {name}")
        except OSError as exc:
            self.toast_requested.emit("error", f"Delete failed: {exc}")
        return self._emit_refresh()

    @pyqtSlot(str, result=str)
    def clearAll(self, scope: str):
        scope = (scope or "").strip().lower()
        if scope not in ("project", "global"):
            scope = self._active_scope
        memory_dir = self._get_scope_dir(scope)
        errors = []
        for memory in _load_memories(memory_dir):
            try:
                os.remove(memory["path"])
            except OSError as exc:
                errors.append(str(exc))

        index_path = os.path.join(memory_dir, "MEMORY.md")
        try:
            if os.path.exists(index_path):
                os.remove(index_path)
        except OSError as exc:
            errors.append(str(exc))

        if errors:
            self.toast_requested.emit("error", errors[0])
        else:
            self.toast_requested.emit("success", f"Cleared {scope} memories")
        return self._emit_refresh()


class MemoryManagerDialog(QDialog):
    """WebEngine-backed memory manager dialog."""

    def __init__(self, project_root: str, settings=None, parent=None):
        super().__init__(parent)
        self._bridge = MemoryManagerBridge(project_root, settings=settings, parent=self)
        self._page_loaded = False

        self.setWindowTitle("Memory Manager - Cortex IDE")
        self.setMinimumSize(980, 720)
        self.resize(1120, 780)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = QWebEngineView(self)
        self._page = _MemoryPage(self._view)
        self._view.setPage(self._page)

        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)

        self._channel = QWebChannel(self)
        self._channel.registerObject("memoryBridge", self._bridge)
        self._page.setWebChannel(self._channel)

        self._view.loadFinished.connect(self._on_page_loaded)
        self._bridge.data_changed.connect(self._push_state_to_page)
        self._bridge.toast_requested.connect(self._show_toast)

        layout.addWidget(self._view)
        self._load_page()

    def _load_page(self):
        html_path = (
            Path(__file__).resolve().parent.parent / "html" / "memory_manager" / "memory_management.html"
        )
        if not html_path.exists():
            QMessageBox.critical(self, "Memory Manager", f"Missing UI file:\n{html_path}")
            return

        url = QUrl.fromLocalFile(str(html_path))
        url.setQuery(f"v={int(time.time())}")
        self._view.setUrl(url)

    def _on_page_loaded(self, ok: bool):
        self._page_loaded = ok
        if not ok:
            QMessageBox.warning(self, "Memory Manager", "Failed to load memory management page.")
            return
        self._push_state_to_page(self._bridge.loadInitialData())

    def _push_state_to_page(self, payload: str):
        if not self._page_loaded:
            return
        safe_payload = json.dumps(payload)
        self._view.page().runJavaScript(
            f"window.receiveMemoryState && window.receiveMemoryState(JSON.parse({safe_payload}));"
        )

    def _show_toast(self, level: str, message: str):
        if not self._page_loaded:
            return
        safe_level = json.dumps(level)
        safe_message = json.dumps(message)
        self._view.page().runJavaScript(
            f"window.showToast && window.showToast({safe_level}, {safe_message});"
        )
