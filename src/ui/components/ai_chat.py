import os
import sys
import json
import platform
import shutil
from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QObject, pyqtSlot, QProcess, QProcessEnvironment, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from src.utils.logger import get_logger

from src.utils.icons import make_icon

log = get_logger("ai_chat")

class ChatBridge(QObject):
    """Bridge for communication between JS and Python."""
    message_submitted = pyqtSignal(str)
    clear_chat_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    run_command_requested = pyqtSignal(str)
    proceed_requested = pyqtSignal()
    generate_plan_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    always_allow_changed = pyqtSignal(bool)
    
    open_file_requested = pyqtSignal(str)
    open_file_at_line_requested = pyqtSignal(str, int)  # file_path, line_number
    show_diff_requested = pyqtSignal(str)
    
    # Terminal Signals
    terminal_input = pyqtSignal(str)
    terminal_output = pyqtSignal(str)
    terminal_resize = pyqtSignal(int, int)
    
    # Navigation
    navigate_to_line = pyqtSignal(str, int)  # file_path, line_number
    
    # Smart paste signal
    smart_paste_check_requested = pyqtSignal(str)  # pasted_text
    search_files_requested = pyqtSignal(str)       # @ mention file search
    
    # Chat persistence signals
    save_chats_requested = pyqtSignal(str, str)  # storage_key, json_data
    load_chats_requested = pyqtSignal(str)       # storage_key
    
    @pyqtSlot(str)
    def on_message_submitted(self, text):
        self.message_submitted.emit(text)
        
    @pyqtSlot()
    def on_clear_chat(self):
        self.clear_chat_requested.emit()

    @pyqtSlot(str)
    def on_run_command(self, command):
        self.run_command_requested.emit(command)

    @pyqtSlot()
    def on_stop(self):
        self.stop_requested.emit()

    @pyqtSlot(str)
    def on_terminal_input(self, data):
        self.terminal_input.emit(data)

    @pyqtSlot(int, int)
    def on_terminal_resize(self, cols, rows):
        self.terminal_resize.emit(cols, rows)

    @pyqtSlot()
    def on_proceed_requested(self):
        self.proceed_requested.emit()

    @pyqtSlot(bool)
    def on_always_allow_changed(self, allowed):
        self.always_allow_changed.emit(allowed)

    @pyqtSlot()
    def on_generate_plan(self):
        self.generate_plan_requested.emit()

    @pyqtSlot(str)
    def on_mode_changed(self, mode):
        self.mode_changed.emit(mode)

    @pyqtSlot(str)
    def on_open_file(self, file_path):
        self.open_file_requested.emit(file_path)

    @pyqtSlot(str, int)
    def on_open_file_at_line(self, file_path, line_number):
        """Open file at specific line number."""
        self.open_file_at_line_requested.emit(file_path, line_number)

    @pyqtSlot(str)
    def on_show_diff(self, file_path):
        self.show_diff_requested.emit(file_path)

    @pyqtSlot(str)
    def on_check_smart_paste(self, pasted_text):
        """Check if pasted text matches current editor selection."""
        self.smart_paste_check_requested.emit(pasted_text)

    @pyqtSlot(bool)
    def handle_permission_response(self, allowed):
        """Handle permission response from JS (Allow/Deny tool execution)."""
        # Emit proceed signal if allowed, otherwise just log
        if allowed:
            self.proceed_requested.emit()
        else:
            log.info("User denied tool execution permission")

    # ── ENHANCEMENT GUIDE: Missing Bridge Slots ──────────────────────

    @pyqtSlot()
    def on_stop_generation(self):
        """Stop AI generation — called from Escape key or stop button in JS."""
        self.stop_requested.emit()

    @pyqtSlot(str)
    def on_search_files(self, query: str):
        """Search project files for @ mention autocomplete."""
        # Emit a signal so AIChatWidget can handle the view.runJavaScript call
        self.search_files_requested.emit(query)

    @pyqtSlot(str)
    def on_add_context_file(self, file_path: str):
        """Add a file to the AI context for this turn."""
        log.info(f'Context file added: {file_path}')
        # Will be picked up by agent's context manager on next message

    @pyqtSlot(str)
    def on_accept_file_edit(self, file_path: str):
        """User accepted a file edit from the card UI."""
        log.info(f'File edit accepted: {file_path}')
        # Notify main window if available
        self.show_diff_requested.emit(file_path)  # reuse existing signal

    @pyqtSlot(str)
    def on_reject_file_edit(self, file_path: str):
        """User rejected a file edit — optionally restore from pre-edit snapshot."""
        log.info(f'File edit rejected: {file_path}')

    @pyqtSlot()
    def on_approve_tools(self):
        """User approved pending tool actions."""
        self.proceed_requested.emit()

    @pyqtSlot()
    def on_deny_tools(self):
        """User denied pending tool actions."""
        log.info('User denied tool execution')

    @pyqtSlot()
    def on_always_allow(self):
        """User enabled always-allow for tools."""
        self.always_allow_changed.emit(True)

    @pyqtSlot()
    def on_undo_action(self):
        """Undo the last AI action."""
        log.info('Undo action requested')
        # Will be routed through main_window to agent tool registry

    @pyqtSlot(str, str)
    def on_insert_code(self, code: str, language: str):
        """Insert code at the editor cursor."""
        log.info(f'Insert code requested: {len(code)} chars, lang={language}')
        # Forwarded to main_window.insert_code_at_cursor via signal

    @pyqtSlot(str)
    def on_js_error(self, error_json: str):
        """Handle JavaScript errors reported from the page."""
        log.warning(f'JS Error: {error_json}')
        
    # ── CHAT PERSISTENCE: File-based storage fallback ─────────────────
    
    @pyqtSlot(str, str, result=str)
    def save_chats_to_file(self, storage_key: str, json_data: str) -> str:
        """
        Save chat data to a JSON file in the .cortex/chats directory.
        This provides a reliable fallback when localStorage doesn't persist.
        Returns: "OK" or error message.
        """
        try:
            # Create .cortex directory if it doesn't exist
            cortex_dir = os.path.join(os.path.expanduser("~"), ".cortex")
            chats_dir = os.path.join(cortex_dir, "chats")
            os.makedirs(chats_dir, exist_ok=True)
            
            # Save to file
            file_path = os.path.join(chats_dir, f"{storage_key}.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(json_data)
            
            log.debug(f'Chats saved to file: {file_path} ({len(json_data)} chars)')
            return "OK"
        except Exception as e:
            log.error(f'Failed to save chats to file: {e}')
            return f"ERROR: {str(e)}"
    
    @pyqtSlot(str, result=str)
    def load_chats_from_file(self, storage_key: str) -> str:
        """
        Load chat data from a JSON file in the .cortex/chats directory.
        Returns: JSON string or empty array if file doesn't exist.
        """
        try:
            chats_dir = os.path.join(os.path.expanduser("~"), ".cortex", "chats")
            file_path = os.path.join(chats_dir, f"{storage_key}.json")
            
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = f.read()
                log.debug(f'Chats loaded from file: {file_path} ({len(data)} chars)')
                return data
            else:
                # Return empty array if file doesn't exist
                return "[]"
        except Exception as e:
            log.error(f'Failed to load chats from file: {e}')
            return "[]"


from PyQt6.QtWebEngineCore import QWebEnginePage

class ConsolePage(QWebEnginePage):
    """Custom page that captures JavaScript console messages."""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # level is an enum: InfoMessageLevel=0, WarningMessageLevel=1, ErrorMessageLevel=2
        level_val = level.value if hasattr(level, 'value') else int(level)
        level_names = {0: 'INFO', 1: 'WARN', 2: 'ERROR'}
        level_name = level_names.get(level_val, 'LOG')
        # Show [CHAT] tagged messages or errors - these are important for debugging
        if '[CHAT]' in message or level_val >= 2:
            # Use bright colors for [CHAT] messages to make them visible
            if '[CHAT]' in message:
                print(f"\033[96m[JS {level_name}] {message}\033[0m")  # Cyan color
            else:
                print(f"[JS {level_name}] {message}")


class AIChatWidget(QWidget):
    """Web-based AI chat widget using QWebEngineView."""
    message_sent = pyqtSignal(str, str)  # user_message, code_context
    run_command = pyqtSignal(str)
    stop_requested = pyqtSignal()
    proceed_requested = pyqtSignal()
    always_allow_changed = pyqtSignal(bool)
    generate_plan_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    
    open_file_requested = pyqtSignal(str)
    open_file_at_line_requested = pyqtSignal(str, int)  # file_path, line_number
    show_diff_requested = pyqtSignal(str)
    
    # Smart paste signal - emitted when user pastes code, to check if it matches editor selection
    smart_paste_check_requested = pyqtSignal(str)  # pasted_text

    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dark = True
        self._get_code_context = None
        self._terminal_process = None
        self._pty_process = None
        self._project_root = None  # Set via set_project_root() for @ mention search
        self._build_ui()
        self._start_terminal_backend()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # CRITICAL: Configure persistent storage profile for localStorage to survive app restarts
        from PyQt6.QtWebEngineCore import QWebEngineProfile
        from pathlib import Path
        
        # Get or create persistent storage profile
        profile = QWebEngineProfile.defaultProfile()
        
        # Set persistent storage path - THIS IS CRITICAL FOR CHAT PERSISTENCE
        storage_path = str(Path.home() / ".cortex" / "webengine_storage")
        print(f"[WEBVIEW] Setting persistent storage path: {storage_path}")
        
        # These settings ensure data persists across app restarts
        try:
            # Set cache type to disk (not memory)
            profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            print("[WEBVIEW] HTTP cache set to disk")
        except Exception as e:
            print(f"[WEBVIEW] Could not set HTTP cache: {e}")
        
        # Enable persistent storage
        try:
            profile.setPersistentStoragePath(storage_path)
            print(f"[WEBVIEW] Persistent storage path set: {storage_path}")
        except Exception as e:
            print(f"[WEBVIEW] Could not set persistent storage: {e}")
        
        # Web View with custom page for console logging
        self._view = QWebEngineView()
        self._page = ConsolePage(self._view)
        self._view.setPage(self._page)
        
        # Enable standard context menu and selection features
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.JavascriptCanAccessClipboard, True
        )
        # Enable localStorage persistence (critical for chat history)
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.LocalStorageEnabled, True
        )
        
        # Setup Channel
        self._channel = QWebChannel()
        self._bridge = ChatBridge()
        self._bridge.message_submitted.connect(self._on_js_message)
        self._bridge.clear_chat_requested.connect(self.clear_chat)
        self._bridge.stop_requested.connect(self.stop_requested.emit)
        self._bridge.run_command_requested.connect(self.run_command.emit)
        self._bridge.proceed_requested.connect(self.proceed_requested.emit)
        self._bridge.always_allow_changed.connect(self.always_allow_changed.emit)
        self._bridge.generate_plan_requested.connect(self.generate_plan_requested.emit)
        self._bridge.mode_changed.connect(self.mode_changed.emit)
        self._bridge.open_file_requested.connect(self.open_file_requested.emit)
        self._bridge.open_file_at_line_requested.connect(self.open_file_at_line_requested.emit)
        self._bridge.show_diff_requested.connect(self.show_diff_requested.emit)
        self._bridge.search_files_requested.connect(self._on_search_files)
        self._channel.registerObject("bridge", self._bridge)

        self._page.setWebChannel(self._channel)
        
        # Load local HTML
        html_path = os.path.join(os.path.dirname(__file__), "..", "html", "ai_chat", "aichat.html")
        self._view.setUrl(QUrl.fromLocalFile(os.path.abspath(html_path)))
        
        layout.addWidget(self._view)
        
    def _on_js_message(self, text):
        """Handle message from JS."""
        context = ""
        if self._get_code_context:
            context = self._get_code_context()
        self.message_sent.emit(text, context)

    def _on_search_files(self, query: str):
        """Handle @ mention file search from JS."""
        try:
            from pathlib import Path
            results = []
            root = getattr(self, '_project_root', None) or '.'
            root_path = Path(root)
            for p in root_path.rglob('*'):
                if p.is_file() and (not query or query.lower() in p.name.lower()):
                    parts = str(p)
                    if not any(skip in parts for skip in ['.git', '__pycache__', 'node_modules', '.pyc']):
                        try:
                            results.append({
                                'name': p.name,
                                'path': str(p),
                                'rel_path': str(p.relative_to(root_path))
                            })
                        except ValueError:
                            results.append({'name': p.name, 'path': str(p), 'rel_path': p.name})
                if len(results) >= 10:
                    break
            safe_results = json.dumps(results)
            self._view.page().runJavaScript(
                f'if(window.populateMentionResults) populateMentionResults({safe_results});'
            )
        except Exception as e:
            log.warning(f'_on_search_files error: {e}')
        
    def on_chunk(self, chunk):
        """Handle AI streaming chunk - async to prevent UI blocking."""
        # Use JSON encoding to properly escape for JavaScript
        safe_chunk = json.dumps(chunk)
        self._view.page().runJavaScript(
            f"if(window.onChunk) window.onChunk({safe_chunk});",
            lambda result: None  # Async callback
        )
        
    def on_complete(self, full_text):
        """Handle AI completion."""
        self._view.page().runJavaScript("if(window.onComplete) window.onComplete();")
        
    def on_error(self, error):
        """Handle error."""
        safe_error = json.dumps(f"❌ Error: {error}")
        self._view.page().runJavaScript(f"if(window.appendMessage) window.appendMessage({safe_error}, 'assistant', false);")
        
    def clear_chat(self):
        """Clear chat."""
        # This will be handled by the clear_chat_requested signal in JS, 
        # but if called from Python, we use the correct ID:
        self._view.page().runJavaScript("const msg = document.getElementById('chatMessages'); if(msg) msg.innerHTML = '';")
        
    def set_theme(self, is_dark):
        """Update theme."""
        self._is_dark = is_dark
        self._view.page().runJavaScript(f"if(window.setTheme) window.setTheme({str(is_dark).lower()});")
        
    def focus_input(self):
        """Focus the input field in web view."""
        self._view.page().runJavaScript("const input = document.getElementById('chatInput'); if(input) input.focus();")
        
    def add_system_message(self, text):
        """Add a system message."""
        safe_text = json.dumps(text)
        self._view.page().runJavaScript(f"if(window.appendMessage) window.appendMessage({safe_text}, 'assistant', false);")

    def _add_ai_bubble_streaming(self):
        """Start a new AI streaming message bubble."""
        self._view.page().runJavaScript("if(window.startStreaming) window.startStreaming();")
    
    def show_tool_activity(self, tool_type: str, info: str, status: str = "running"):
        """Show tool activity card in the chat UI and track for completion summary."""
        safe_info = json.dumps(info)
        # Track this activity for the completion summary
        self._view.page().runJavaScript(
            f"if(window.trackActivity) window.trackActivity('{tool_type}', {safe_info}, '{status}');",
            lambda result: None
        )
        # Show tool activity card
        self._view.page().runJavaScript(
            f"if(window.showToolActivity) window.showToolActivity('{tool_type}', {safe_info}, '{status}');",
            lambda result: None
        )
    
    def show_directory_contents(self, path: str, contents: str):
        """Show directory contents in the chat UI with file/folder icons."""
        import json
        print(f"[DIR-DEBUG] Python: show_directory_contents called path={path}, content_len={len(contents) if contents else 0}")
        safe_path = json.dumps(path)
        safe_contents = json.dumps(contents)
        js = f"console.log('[DIR-DEBUG] JS: showDirectoryContents called'); if(window.showDirectoryContents) {{ window.showDirectoryContents({safe_path}, {safe_contents}); console.log('[DIR-DEBUG] JS: showDirectoryContents executed'); }} else {{ console.error('[DIR-DEBUG] JS: showDirectoryContents NOT FOUND'); }}"
        self._view.page().runJavaScript(js, lambda result: None)

    def clear_tool_activity(self):
        """Clear tool activity cards."""
        self._view.page().runJavaScript("if(window.clearToolActivity) window.clearToolActivity();")
    
    def show_thinking(self):
        """Show thinking indicator."""
        self._view.page().runJavaScript("if(window.showThinking) window.showThinking();")
    
    def hide_thinking(self):
        """Hide thinking indicator and show duration."""
        self._view.page().runJavaScript("if(window.hideThinking) window.hideThinking();")
    
    def update_todos(self, todos: list, main_task: str = ""):
        """Update the TODO list in the UI."""
        todos_json = json.dumps(todos)
        main_task_safe = json.dumps(main_task)
        self._view.page().runJavaScript(
            f"if(window.updateTodos) window.updateTodos({todos_json}, {main_task_safe});"
        )
    
    def clear_todos(self):
        """Clear the TODO list from the UI."""
        self._view.page().runJavaScript("if(window.clearTodos) window.clearTodos();")

    def on_file_edited_diff(self, path: str, original: str, new_content: str):
        """
        Called when the agent edits a file.
        Calculates +/- diff line counts and updates the Changed Files panel in JS.
        Connect to agent.file_edited_diff signal (or call directly).
        """
        import difflib
        orig_lines = original.splitlines()
        new_lines  = new_content.splitlines()
        diff = list(difflib.ndiff(orig_lines, new_lines))
        added   = sum(1 for l in diff if l.startswith('+ '))
        removed = sum(1 for l in diff if l.startswith('- '))
        p = json.dumps(path)
        self._view.page().runJavaScript(
            f"if(window.addChangedFile) addChangedFile({p}, {added}, {removed}, 'M');"
        )
        log.debug(f'File edited diff: {path} +{added} -{removed}')

    def set_code_context_callback(self, callback):
        self._get_code_context = callback

    def set_project_root(self, root_path: str):
        """Set project root for @ mention file search."""
        self._project_root = root_path

    def set_project_info(self, name: str, path: str = ""):
        """Update the project indicator in the chat header and switch to project-specific chat history."""
        import json
        safe_name = json.dumps(name)
        safe_path = json.dumps(path)
        print(f"[PYTHON] set_project_info called: {name}, {path}")
        
        # Set the path immediately in Python so saveChats can use it
        self._current_project_path = path
        
        # Wait longer for WebView to fully load before calling JS
        from PyQt6.QtCore import QTimer
        # Try calling once after a longer delay
        QTimer.singleShot(3000, lambda: self._actually_call_set_project_info(safe_name, safe_path))
    
    def _actually_call_set_project_info(self, safe_name: str, safe_path: str):
        """Actually call the JS function after waiting."""
        # First, load the chat data from file on the Python side
        import hashlib
        
        # Generate storage key using same logic as JavaScript
        if self._current_project_path:
            normalized_path = self._current_project_path.replace('\\', '/').lower().strip()
            hash_val = 0
            for char in normalized_path:
                hash_val = ((hash_val << 5) - hash_val) + ord(char)
                # JavaScript's `hash & hash` is equivalent to just keeping the value
                # but ensuring it stays within 32-bit signed integer range
                hash_val = hash_val & 0xFFFFFFFF
                # Convert to signed 32-bit if needed
                if hash_val > 0x7FFFFFFF:
                    hash_val = hash_val - 0x100000000
            # Convert to hex to match JavaScript's toString(16)
            hash_str = format(abs(hash_val), 'x')
            storage_key = f"cortex_chats_{hash_str}"
            
            # Load chats from file
            chats_data = self._bridge.load_chats_from_file(storage_key)
            log.info(f"Loading chats for key {storage_key}: {len(chats_data)} chars")
            
            # Push both project info AND chat data to JavaScript
            safe_chats = json.dumps(chats_data)
            self._page.runJavaScript(
                f"""
                if(window.setProjectInfoWithChats) {{
                    console.log('[CHAT] Python calling setProjectInfoWithChats');
                    window.setProjectInfoWithChats({safe_name}, {safe_path}, {safe_chats});
                }} else if(window.setProjectInfo) {{
                    console.log('[CHAT] Python calling setProjectInfo (old method)');
                    window.setProjectInfo({safe_name}, {safe_path});
                }} else {{
                    console.log('[CHAT] setProjectInfo still not ready');
                }}
                """
            )
        else:
            # No project path, just set the info
            self._page.runJavaScript(
                f"if(window.setProjectInfo) {{ console.log('[CHAT] Python calling setProjectInfo'); window.setProjectInfo({safe_name}, {safe_path}); }} else {{ console.log('[CHAT] setProjectInfo still not ready'); }}"
            )

    def clear_project_info(self):
        """Hide the project indicator."""
        self._page.runJavaScript("if(window.clearProjectInfo) window.clearProjectInfo();")

    def _start_terminal_backend(self):
        """Initialize the backend shell process (PowerShell by default on Windows)."""
        shell = "powershell.exe" if platform.system() == "Windows" else "bash"
        
        try:
            import winpty
            self._pty_process = winpty.PtyProcess.spawn(shell)
            
            from PyQt6.QtCore import QThread
            class Reader(QThread):
                data = pyqtSignal(str)
                def __init__(self, pty):
                    super().__init__()
                    self.pty = pty
                def run(self):
                    while self.pty.isalive():
                        try:
                            d = self.pty.read()
                            if d: self.data.emit(d)
                        except EOFError: break
                        except: pass
            
            self._reader = Reader(self._pty_process)
            self._reader.data.connect(lambda d: self._bridge.terminal_output.emit(d))
            self._reader.start()
            
            self._bridge.terminal_input.connect(lambda d: self._pty_process.write(d))
            self._bridge.terminal_resize.connect(lambda c, r: self._pty_process.setwinsize(r, c) if self._pty_process else None)
            
        except Exception as e:
            log.warning(f"Could not start winpty for AI chat terminal: {e}. Falling back to QProcess.")
            self._terminal_process = QProcess(self)
            self._terminal_process.readyReadStandardOutput.connect(self._on_stdout)
            self._terminal_process.start(shell)
            self._bridge.terminal_input.connect(lambda d: self._terminal_process.write(d.encode()))

    def _on_stdout(self):
        if self._terminal_process:
            data = self._terminal_process.readAllStandardOutput().data().decode(errors="replace")
            self._bridge.terminal_output.emit(data)

    def closeEvent(self, event):
        if self._pty_process:
            self._pty_process.terminate()
        if self._terminal_process:
            self._terminal_process.terminate()
        super().closeEvent(event)

