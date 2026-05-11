"""
WebviewPanel — Monaco Editor webview panel for Cortex IDE.
Replaces the PyQt6 QPlainTextEdit-based CodeEditor with VS Code-quality editing.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

log = logging.getLogger(__name__)


class _LoggingWebEnginePage(QWebEnginePage):
    """Capture JS console output in Python logs for crash/debug visibility."""

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        try:
            lvl = int(level)
        except Exception:
            lvl = 0
        level_name = {0: "INFO", 1: "WARN", 2: "ERROR"}.get(lvl, str(level))
        log.warning(f"[WebviewPanel][JS {level_name}] {source_id}:{line_number} {message}")


class _EditorBridge(QObject):
    """QWebChannel bridge — JS calls slots on this object."""

    content_changed = pyqtSignal(str, str)       # file_path, content
    file_closed = pyqtSignal(str)                 # file_path
    cursor_changed = pyqtSignal(str, int, int)    # file_path, line, column
    editor_ready = pyqtSignal()

    # LSP request signals — handled asynchronously (lsp_manager callbacks → runJavaScript)
    lsp_completions_requested = pyqtSignal(str, str, str, int, int)  # request_id, file_path, language, line, col
    lsp_hover_requested = pyqtSignal(str, str, str, int, int)
    lsp_definition_requested = pyqtSignal(str, str, str, int, int)
    lsp_diagnostics_requested = pyqtSignal(str, str, str)  # request_id, file_path, language
    lsp_content_changed = pyqtSignal(str, str, str)  # file_path, content, language

    def __init__(self, webview_panel: 'WebviewPanel' = None):
        super().__init__()
        self._panel = webview_panel

    @pyqtSlot(str, str)
    def onContentChanged(self, file_path: str, content: str):
        self.content_changed.emit(file_path, content)

    @pyqtSlot(str)
    def onFileClosed(self, file_path: str):
        self.file_closed.emit(file_path)

    @pyqtSlot(str, int, int)
    def onCursorChanged(self, file_path: str, line: int, column: int):
        self.cursor_changed.emit(file_path, line, column)

    @pyqtSlot()
    def onEditorReady(self):
        self.editor_ready.emit()

    # ---- LSP Bridge Slots (called from JS) ----

    @pyqtSlot(str, str, str, int, int)
    def requestCompletions(self, request_id: str, file_path: str, language: str,
                           line: int, column: int):
        """JS requests autocomplete suggestions."""
        self.lsp_completions_requested.emit(request_id, file_path, language, line, column)

    @pyqtSlot(str, str, str, int, int)
    def requestHover(self, request_id: str, file_path: str, language: str,
                     line: int, column: int):
        """JS requests hover documentation."""
        self.lsp_hover_requested.emit(request_id, file_path, language, line, column)

    @pyqtSlot(str, str, str, int, int)
    def requestDefinition(self, request_id: str, file_path: str, language: str,
                          line: int, column: int):
        """JS requests go-to-definition."""
        self.lsp_definition_requested.emit(request_id, file_path, language, line, column)

    @pyqtSlot(str, str, str)
    def requestDiagnostics(self, request_id: str, file_path: str, language: str):
        """JS requests current diagnostics for a file."""
        self.lsp_diagnostics_requested.emit(request_id, file_path, language)

    @pyqtSlot(str, str, str)
    def notifyContentChanged(self, file_path: str, content: str, language: str):
        """JS notifies that document content changed (didChange)."""
        self.lsp_content_changed.emit(file_path, content, language)


class WebviewPanel(QWidget):
    """
    Monaco Editor webview panel with tab management.

    Usage:
        panel = WebviewPanel()
        panel.open_file("/path/to/file.py", "print('hello')", "python")
        panel.set_theme(is_dark=True)
    """

    # Signals — mirror CodeEditor API where possible
    file_opened = pyqtSignal(str)                   # file_path
    file_content_changed = pyqtSignal(str, str)     # file_path, new_content
    file_closed = pyqtSignal(str)                    # file_path
    cursor_position_changed = pyqtSignal(int, int)   # line, column
    active_file_changed = pyqtSignal(str)            # file_path (or empty)
    editor_ready = pyqtSignal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._init_time = time.time()  # track startup for warmup delay
        self._open_files: dict[str, dict] = {}      # path → {path, language, content}
        self._active_file_path: str = ""
        self._page_loaded = False
        self._pending_opens: list[tuple] = []        # queued until page loads
        self._pending_theme: Optional[bool] = None
        self._lsp_manager = None

        # Lazy-init LSP manager
        try:
            from src.core.lsp_manager import get_lsp_manager
            self._lsp_manager = get_lsp_manager()
            log.info("[WebviewPanel] LSP manager connected")
        except Exception as e:
            log.warning(f"[WebviewPanel] LSP manager unavailable: {e}")

        self._build_ui()
        self._wire_lsp_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Persistent storage profile for Monaco settings
        profile = QWebEngineProfile.defaultProfile()
        try:
            storage_path = str(Path.home() / ".cortex" / "webengine_storage")
            profile.setPersistentStoragePath(storage_path)
        except Exception:
            pass

        self._view = QWebEngineView()
        self._page = _LoggingWebEnginePage(self._view)
        self._view.setPage(self._page)

        # Enable localStorage + clipboard + cross-directory file access
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.LocalStorageEnabled, True
        )
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.JavascriptCanAccessClipboard, True
        )
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.LocalContentCanAccessFileUrls, True
        )

        # QWebChannel bridge
        self._channel = QWebChannel()
        self._bridge = _EditorBridge(webview_panel=self)
        self._bridge.content_changed.connect(self._on_js_content_changed)
        self._bridge.file_closed.connect(self._on_js_file_closed)
        self._bridge.cursor_changed.connect(self._on_js_cursor_changed)
        self._bridge.editor_ready.connect(self._on_editor_ready)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)

        # Inline Monaco loader.js + inject file:/// vs/ path → write temp file → load.
        # Inlining loader.js avoids <script src="file:///..."> cross-directory loading
        # issues in QWebEngineView. Dynamic script/XHR fetches from file:/// URIs
        # work correctly with LocalContentCanAccessFileUrls enabled.
        _project_root = Path(__file__).parent.parent.parent.parent
        editor_html = Path(__file__).parent.parent.parent / "assets" / "editor.html"
        _monaco_loader = _project_root / "node_modules" / "monaco-editor" / "min" / "vs" / "loader.js"
        _monaco_vs_dir = _project_root / "node_modules" / "monaco-editor" / "min" / "vs"

        if not editor_html.exists():
            log.error(f"[WebviewPanel] editor.html not found at: {editor_html}")
            self._view.setHtml("<h3>editor.html not found</h3>")
        elif not _monaco_loader.exists():
            log.error("[WebviewPanel] Monaco loader not found - run: npm install monaco-editor")
            self._view.setHtml("<h3>Monaco loader.js missing. Run: npm install monaco-editor</h3>")
        else:
            import tempfile, atexit
            html_content = editor_html.read_text(encoding="utf-8")
            loader_js = _monaco_loader.read_text(encoding="utf-8")
            html_content = html_content.replace("__MONACO_LOADER_INLINE__", loader_js)
            html_content = html_content.replace("__MONACO_VS_PATH__", _monaco_vs_dir.as_uri())

            _tmp_dir = Path(tempfile.gettempdir()) / "cortex_webview"
            _tmp_dir.mkdir(parents=True, exist_ok=True)
            self._tmp_html = _tmp_dir / "editor_resolved.html"
            self._tmp_html.write_text(html_content, encoding="utf-8")
            log.info(f"[WebviewPanel] Monaco loader inlined -> {self._tmp_html} ({len(html_content)} chars)")

            def _cleanup_tmp():
                try:
                    if self._tmp_html.exists():
                        self._tmp_html.unlink()
                except Exception:
                    pass
            atexit.register(_cleanup_tmp)

            self._view.load(QUrl.fromLocalFile(str(self._tmp_html.resolve())))

        self._view.loadFinished.connect(self._on_page_loaded)
        
        # Catch Chromium render process crashes
        self._view.page().renderProcessTerminated.connect(self._on_render_crash)
        
        layout.addWidget(self._view)

    # ---- Page lifecycle ---------------------------------------------------

    def _on_page_loaded(self, ok: bool):
        if not ok:
            log.error("[WebviewPanel] Page failed to load")
            return
        self._page_loaded = True
        log.info(f"[WebviewPanel] editor.html loaded, pending opens: {len(self._pending_opens)}")

        # Apply pending theme
        if self._pending_theme is not None:
            self._set_theme_js(self._pending_theme)
            self._pending_theme = None

        # Small delay to ensure QWebChannel transport is ready

        def _process_pending():
            # Process pending file opens
            pending = list(self._pending_opens)
            self._pending_opens.clear()
            for args in pending:
                log.info(f"[WebviewPanel] Processing pending open: {args[0]}")
                self._open_file_js(*args, priority=False)

        QTimer.singleShot(200, _process_pending)

    def _on_editor_ready(self):
        """Monaco Editor fully initialized in JS."""
        log.info("[WebviewPanel] Monaco Editor ready")
        self.editor_ready.emit()

    def _on_render_crash(self, termination_status, exit_code):
        """Chromium render process crashed — log details for debugging."""
        # termination_status: QWebEnginePage.RenderProcessTerminationStatus enum
        #   NormalTerminationStatus=0, AbnormalTerminationStatus=1, CrashedTerminationStatus=2,
        #   KilledTerminationStatus=3
        status_names = {0: "Normal", 1: "Abnormal", 2: "Crashed", 3: "Killed"}
        status_name = status_names.get(int(termination_status), f"Unknown({termination_status})")
        log.critical(f"[WebviewPanel] RENDER PROCESS CRASHED: status={status_name}, exit_code={exit_code}")
        print(f"\n💥 [WebviewPanel] Chromium render process CRASHED (status={status_name}, code={exit_code})\n",
              flush=True)
        # Mark page dead so we stop sending JS. Future opens will queue until reload.
        self._page_loaded = False

    # ---- Public API -------------------------------------------------------

    def _safe_run_js(self, js: str, callback=None):
        """Run JavaScript safely — catches crashes from dead/destroyed webview."""
        try:
            def _invoke():
                try:
                    page = self._view.page() if self._view else None
                    if not page:
                        return
                    if callback:
                        page.runJavaScript(js, callback)
                    else:
                        page.runJavaScript(js)
                except Exception as e:
                    log.debug(f"[WebviewPanel] runJavaScript failed (webview may be dead): {e}")

            # Always schedule onto the Qt GUI thread (safe even if already on it).
            QTimer.singleShot(0, _invoke)
        except Exception as e:
            log.debug(f"[WebviewPanel] runJavaScript scheduling failed: {e}")

    # ---- Public API -------------------------------------------------------

    def open_file(self, file_path: str, content: str, language: str = "plaintext", *, priority: bool = True):
        """Open a file in the editor (creates/switches to tab).

        priority=True is meant for user-initiated clicks (show the file now).
        priority=False is meant for bulk/session restore (throttle during startup).
        """
        log.info(f"[WebviewPanel] open_file: {file_path} (lang={language}, len={len(content)}, page_loaded={self._page_loaded})")
        self._open_files[file_path] = {
            "path": file_path,
            "language": language,
            "content": content,
        }
        self._active_file_path = file_path
        self.file_opened.emit(file_path)

        if self._page_loaded:
            self._open_file_js(file_path, content, language, priority=priority)
        else:
            self._pending_opens.append((file_path, content, language))
            log.debug(f"[WebviewPanel] Queued open for: {file_path}")

    def switch_to_file(self, file_path: str):
        """Switch the editor tab to an already-open file WITHOUT re-sending content.
        
        This avoids a model.setValue() call through QWebChannel, which is the
        primary crash trigger during Chromium's startup warmup phase.
        
        If the file is still in the open queue (pending JS delivery), the content
        is flushed IMMEDIATELY so the JS side has it before switchToFile runs.
        Without this, switchToFile silently fails (openFiles[path] is undefined)
        and the editor keeps showing the previous file's content.
        """
        if file_path not in self._open_files:
            log.warning(f"[WebviewPanel] switch_to_file: {file_path} not in _open_files")
            return
        self._active_file_path = file_path
        self.file_opened.emit(file_path)

        # If file content is still pending in the open queue, flush it NOW.
        # Bumping alone doesn't help — JS switchToFile needs openFiles[path]
        # to exist, which only happens after openFile() delivers the content.
        if hasattr(self, '_open_queue') and file_path in self._open_queue:
            args = self._open_queue.pop(file_path)
            fp, content, language = args
            safe_path = json.dumps(fp)
            safe_content = json.dumps(content)
            safe_lang = json.dumps(language)
            js_open = f"openFile({safe_path}, {safe_content}, {safe_lang}, true);"
            self._safe_run_js(js_open)
            log.info(f"[WebviewPanel] switch_to_file: flushed pending content for {file_path}")

        if self._page_loaded:
            safe_path = json.dumps(file_path)
            js = f"switchToFile({safe_path});"
            self._safe_run_js(js)

    def _open_file_js(self, file_path: str, content: str, language: str, *, priority: bool = True):
        """Send openFile() to JS — heavily throttled during first 60s warmup.
        
        QWebChannel IPC + Monaco model.setValue() crashes Chromium's render
        process on Windows 25H2 when too many files are opened rapidly during
        the first ~40-60s of startup. Testing proved that 3s spacing still
        crashes after ~12 files accumulate. With 10s spacing, only ~6 files
        load in 60s — safely under the crash threshold while keeping the IDE
        usable (first file opens immediately so the user sees content).
        """
        _WARMUP_SECS = 60
        _elapsed = time.time() - self._init_time
        # 10s spacing during warmup (safe: max 6 files in 60s), 1.5s after
        _delay_ms = 10000 if _elapsed < _WARMUP_SECS else 1500

        if not hasattr(self, '_open_queue'):
            self._open_queue: dict[str, tuple] = {}
        if not hasattr(self, '_open_timer'):
            self._open_timer: Optional[QTimer] = None

        def _run_open_now(fp: str, c: str, lang: str, activate: bool):
            safe_path = json.dumps(fp)
            safe_lang = json.dumps(lang)

            # Large-file optimization: avoid shipping huge strings through Qt's
            # runJavaScript IPC. Instead let the webview fetch the file from disk.
            # This prevents UI freezes and reduces "wrong file content" races.
            _LARGE_CHAR_THRESHOLD = 200_000
            try:
                if fp and Path(fp).exists() and len(c) > _LARGE_CHAR_THRESHOLD:
                    file_uri = Path(fp).as_uri()
                    safe_uri = json.dumps(file_uri)
                    self._safe_run_js(
                        f"openFileFromUri({safe_path}, {safe_lang}, {safe_uri}, {'true' if activate else 'false'});"
                    )
                    return
            except Exception:
                # Fall back to direct content if URI generation or exists() fails
                pass

            safe_content = json.dumps(c)
            self._safe_run_js(
                f"openFile({safe_path}, {safe_content}, {safe_lang}, {'true' if activate else 'false'});"
            )

        # Dedupe: keep only the latest call per file
        if file_path:
            self._open_queue[file_path] = (file_path, content, language)

        # User-initiated opens must show immediately. Warmup throttling is only
        # for restore/bulk opens; delaying the clicked file causes "wrong file"
        # content (previous tab stays visible) and feels laggy.
        if priority and file_path:
            try:
                # Stop any running pump so we can front-run the clicked file.
                if self._open_timer is not None:
                    try:
                        self._open_timer.stop()
                    except Exception:
                        pass
                    self._open_timer = None

                args = self._open_queue.pop(file_path, None)
                if args:
                    _run_open_now(args[0], args[1], args[2], True)
            except Exception as e:
                log.error(f"[WebviewPanel] Priority openFile failed for {file_path}: {e}")

            # Restart a throttled pump for any remaining queued files.
            if self._open_queue and self._open_timer is None:
                def _flush_one_priority_tail():
                    if not self._open_queue:
                        self._open_timer = None
                        return
                    fp, args2 = next(iter(self._open_queue.items()))
                    del self._open_queue[fp]
                    try:
                        _run_open_now(fp, args2[1], args2[2], False)
                    except Exception as e:
                        log.error(f"[WebviewPanel] JS openFile failed for {fp}: {e}")
                    if self._open_queue:
                        self._open_timer = QTimer(self)
                        self._open_timer.setSingleShot(True)
                        self._open_timer.timeout.connect(_flush_one_priority_tail)
                        _elapsed2 = time.time() - self._init_time
                        _d2 = 10000 if _elapsed2 < _WARMUP_SECS else 1500
                        self._open_timer.start(_d2)
                    else:
                        self._open_timer = None

                self._open_timer = QTimer(self)
                self._open_timer.setSingleShot(True)
                self._open_timer.timeout.connect(_flush_one_priority_tail)
                self._open_timer.start(_delay_ms)
            return

        if self._open_timer is None:
            # Use a QTimer for ALL files, including the first.
            # The first file fires at 0ms (next event-loop iteration),
            # subsequent files are spaced by _delay_ms (10s warmup / 1.5s normal).
            #
            # CRITICAL: Using a timer (even 0ms) instead of calling _flush_one()
            # synchronously ensures _open_timer remains set during batch opens
            # (e.g. _process_pending loop). Without this, each _open_file_js()
            # resets _open_timer=None after flushing, so the next call creates
            # another immediate flush — completely bypassing the warmup delay.
            def _flush_one():
                if not self._open_queue:
                    self._open_timer = None
                    return
                fp, args = next(iter(self._open_queue.items()))
                del self._open_queue[fp]
                try:
                    c, lang = args[1], args[2]
                    _run_open_now(fp, c, lang, False)
                except Exception as e:
                    log.error(f"[WebviewPanel] JS openFile failed for {fp}: {e}")
                if self._open_queue:
                    self._open_timer = QTimer(self)
                    self._open_timer.setSingleShot(True)
                    self._open_timer.timeout.connect(_flush_one)
                    _elapsed2 = time.time() - self._init_time
                    _d2 = 10000 if _elapsed2 < _WARMUP_SECS else 1500
                    self._open_timer.start(_d2)
                else:
                    self._open_timer = None

            self._open_timer = QTimer(self)
            self._open_timer.setSingleShot(True)
            self._open_timer.timeout.connect(_flush_one)
            self._open_timer.start(0)  # fire on next event-loop iteration

    def close_file(self, file_path: str):
        """Close a file tab."""
        log.info(f"[WebviewPanel] close_file: {file_path} (was in _open_files: {file_path in self._open_files})")
        self._open_files.pop(file_path, None)
        if self._active_file_path == file_path:
            self._active_file_path = ""
        if self._page_loaded:
            safe = json.dumps(file_path)
            self._safe_run_js(f"closeFile({safe});")

    def close_all_files(self):
        """Close all file tabs in one shot — avoids per-file runJavaScript flood."""
        count = len(self._open_files)
        log.info(f"[WebviewPanel] close_all_files: clearing {count} files")
        self._open_files.clear()
        self._active_file_path = ""
        if self._page_loaded:
            self._safe_run_js("closeAllFiles();")

    def get_content(self, file_path: str) -> str:
        """Get current editor content for a file (async — returns cached content)."""
        return self._open_files.get(file_path, {}).get("content", "")

    def get_active_file(self) -> str:
        """Get the currently active file path."""
        return self._active_file_path

    def set_theme(self, is_dark: bool):
        """Apply dark or light theme to the editor."""
        if self._page_loaded:
            self._set_theme_js(is_dark)
        else:
            self._pending_theme = is_dark

    def _set_theme_js(self, is_dark: bool):
        js = "setTheme(true);"  # dark-only
        self._safe_run_js(js)

    def mark_modified(self, file_path: str, modified: bool = True):
        """Show/hide the modified indicator dot on a tab."""
        if self._page_loaded:
            safe = json.dumps(file_path)
            js = f"markModified({safe}, {'true' if modified else 'false'});"
            self._safe_run_js(js)

    def get_cursor_position(self, callback=None):
        """Get the cursor position (line, column) asynchronously via callback."""
        if not self._page_loaded:
            if callback:
                callback(1, 1)
            return
        def _handle_result(result):
            if callback and result:
                callback(result.get("line", 1), result.get("column", 1))
        self._safe_run_js("getCursorPosition();", _handle_result)

    # ---- JS → Python signal handlers --------------------------------------

    def _on_js_content_changed(self, file_path: str, content: str):
        """JS notified us that file content changed (debounced)."""
        if file_path in self._open_files:
            self._open_files[file_path]["content"] = content
        self.file_content_changed.emit(file_path, content)

    def _on_js_file_closed(self, file_path: str):
        """JS notified us that a file tab was closed."""
        if file_path == '__ALL__':
            # Bulk close — clear all tracked files
            count = len(self._open_files)
            self._open_files.clear()
            self._active_file_path = ''
            log.info(f"[WebviewPanel] _on_js_file_closed: __ALL__ (cleared {count} files)")
            self.file_closed.emit('__ALL__')
            return
        was_present = file_path in self._open_files
        self._open_files.pop(file_path, None)
        log.info(f"[WebviewPanel] _on_js_file_closed: {file_path} (was_present={was_present}, remaining={len(self._open_files)})")
        self.file_closed.emit(file_path)

    def _on_js_cursor_changed(self, file_path: str, line: int, column: int):
        """JS notified us of cursor position change."""
        self._active_file_path = file_path
        self.active_file_changed.emit(file_path)
        self.cursor_position_changed.emit(line, column)

    # ---- LSP Integration --------------------------------------------------

    def _wire_lsp_signals(self):
        """Connect bridge LSP signals to lsp_manager handlers."""
        self._bridge.lsp_completions_requested.connect(self._on_lsp_completions)
        self._bridge.lsp_hover_requested.connect(self._on_lsp_hover)
        self._bridge.lsp_definition_requested.connect(self._on_lsp_definition)
        self._bridge.lsp_diagnostics_requested.connect(self._on_lsp_diagnostics)
        self._bridge.lsp_content_changed.connect(self._on_lsp_content_changed)

    def _js_callback(self, function_name: str, *args):
        """Safely invoke a JS callback with JSON-serialized arguments."""
        if not self._page_loaded:
            return
        json_args = ', '.join(json.dumps(a) for a in args)
        js = f"if(window.{function_name}) window.{function_name}({json_args});"
        self._safe_run_js(js)

    def _on_lsp_completions(self, request_id: str, file_path: str, language: str,
                            line: int, column: int):
        """Handle LSP completion request from JS."""
        if not self._lsp_manager:
            self._js_callback('_lspCompletionsResult', request_id, [])
            return

        def on_result(result, error):
            if error or not result:
                self._js_callback('_lspCompletionsResult', request_id, [])
                return

            items = result.get('items', []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
            is_incomplete = result.get('isIncomplete', False) if isinstance(result, dict) else False

            suggestions = []
            for item in items[:100]:  # limit to 100 for performance
                if not isinstance(item, dict):
                    continue
                label = item.get('label', '')
                kind = item.get('kind', 0)
                detail = item.get('detail', '')
                documentation = item.get('documentation', '')
                insert_text = item.get('insertText', item.get('label', ''))
                insert_text_format = item.get('insertTextFormat', 1)  # 1=Plain, 2=Snippet
                sort_text = item.get('sortText', label)
                filter_text = item.get('filterText', label)

                # LSP CompletionItemKind → Monaco CompletionItemKind mapping
                lsp_to_monaco_kind = {
                    1: 9, 2: 9, 3: 9,      # Text/ Method/ Function → Method
                    4: 4,                    # Function → Function
                    5: 4,                    # Field → Field
                    6: 4,                    # Variable → Variable
                    7: 5,                    # Class → Class
                    8: 7,                    # Interface → Interface
                    9: 6,                    # Module → Module
                    10: 4,                   # Property → Property
                    11: 19,                  # Unit → Unit
                    12: 19,                  # Value → Value
                    13: 20,                  # Enum → Enum
                    14: 13,                  # Keyword → Keyword
                    15: 11,                  # Snippet → Snippet
                    16: 1,                   # Color → Color
                    17: 1,                   # File → File
                    18: 1,                   # Reference → Reference
                    21: 17,                  # Constant → Constant
                    22: 15,                  # Struct → Struct
                    23: 18,                  # Event → Event
                    24: 16,                  # Operator → Operator
                    25: 22,                  # TypeParameter → TypeParameter
                }
                monaco_kind = lsp_to_monaco_kind.get(kind, 1)

                suggestions.append({
                    'label': label,
                    'kind': monaco_kind,
                    'detail': detail,
                    'documentation': documentation if isinstance(documentation, str) else (
                        documentation.get('value', '') if isinstance(documentation, dict) else ''
                    ),
                    'insertText': insert_text,
                    'insertTextFormat': insert_text_format,
                    'sortText': sort_text,
                    'filterText': filter_text,
                })

            self._js_callback('_lspCompletionsResult', request_id, suggestions, is_incomplete)

        self._lsp_manager.get_completions(file_path, line, column, language, on_result)

    def _on_lsp_hover(self, request_id: str, file_path: str, language: str,
                      line: int, column: int):
        """Handle LSP hover request from JS."""
        if not self._lsp_manager:
            self._js_callback('_lspHoverResult', request_id, None)
            return

        def on_result(result, error):
            if error or not result:
                self._js_callback('_lspHoverResult', request_id, None)
                return

            contents = result.get('contents', '')
            if isinstance(contents, list):
                text = '\n\n'.join(
                    c.get('value', str(c)) if isinstance(c, dict) else str(c)
                    for c in contents
                )
            elif isinstance(contents, dict):
                text = contents.get('value', str(contents))
            else:
                text = str(contents) if contents else ''

            hover_range = result.get('range')
            self._js_callback('_lspHoverResult', request_id, text, hover_range)

        self._lsp_manager.get_hover(file_path, line, column, language, on_result)

    def _on_lsp_definition(self, request_id: str, file_path: str, language: str,
                           line: int, column: int):
        """Handle LSP go-to-definition request from JS."""
        if not self._lsp_manager:
            self._js_callback('_lspDefinitionResult', request_id, [])
            return

        def on_result(locations):
            if not locations:
                self._js_callback('_lspDefinitionResult', request_id, [])
                return

            parsed = []
            for loc in locations:
                uri = loc.get('uri', '')
                rng = loc.get('range', {})
                start = rng.get('start', {})
                parsed.append({
                    'uri': uri,
                    'range': {
                        'startLineNumber': (start.get('line', 0) + 1),
                        'startColumn': (start.get('character', 0) + 1),
                        'endLineNumber': (rng.get('end', {}).get('line', 0) + 1),
                        'endColumn': (rng.get('end', {}).get('character', 0) + 1),
                    }
                })
            self._js_callback('_lspDefinitionResult', request_id, parsed)

        self._lsp_manager.get_definition(file_path, line, column, language, on_result)

    def _on_lsp_diagnostics(self, request_id: str, file_path: str, language: str):
        """Handle LSP diagnostics request from JS (returns cached)."""
        if not self._lsp_manager:
            self._js_callback('_lspDiagnosticsResult', request_id, [])
            return

        raw = self._lsp_manager.get_diagnostics(file_path)
        markers = []
        for d in raw:
            rng = d.get('range', {})
            start = rng.get('start', {})
            end = rng.get('end', {})
            severity = d.get('severity', 2)  # 1=Error, 2=Warning, 3=Info, 4=Hint
            monaco_severity = {1: 8, 2: 4, 3: 2, 4: 1}.get(severity, 2)  # Monaco MarkerSeverity

            markers.append({
                'startLineNumber': start.get('line', 0) + 1,
                'startColumn': start.get('character', 0) + 1,
                'endLineNumber': end.get('line', 0) + 1,
                'endColumn': end.get('character', 0) + 1,
                'message': d.get('message', ''),
                'severity': monaco_severity,
                'source': d.get('source', ''),
                'code': str(d.get('code', '') or ''),
            })
        self._js_callback('_lspDiagnosticsResult', request_id, markers)

    def _on_lsp_content_changed(self, file_path: str, content: str, language: str):
        """Handle content change notification from JS → send to LSP server."""
        if not self._lsp_manager:
            return
        try:
            self._lsp_manager.notify_changed(file_path, content, language)
        except Exception as e:
            log.debug(f"[LSP] notify_changed failed: {e}")

    # ---- File count -------------------------------------------------------

    @property
    def open_file_count(self) -> int:
        return len(self._open_files)

    def has_file(self, file_path: str) -> bool:
        return file_path in self._open_files
