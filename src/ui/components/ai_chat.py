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
    model_changed = pyqtSignal(str, str, str)  # model_id, perf, cost
    
    open_file_requested = pyqtSignal(str)
    open_file_at_line_requested = pyqtSignal(str, int)  # file_path, line number
    show_diff_requested = pyqtSignal(object)  # list of file changes
    accept_file_edit_requested = pyqtSignal(object)
    reject_file_edit_requested = pyqtSignal(object)
    open_terminal_requested = pyqtSignal()
    search_files_requested = pyqtSignal(str)
    load_full_chat_requested = pyqtSignal(str)  # conversation_id - NEW!
    show_diff_requested = pyqtSignal(str)
    
    # File edit accept/reject signals
    accept_file_edit_requested = pyqtSignal(str)  # file_path
    reject_file_edit_requested = pyqtSignal(str)  # file_path
    
    # Terminal Signals
    terminal_input = pyqtSignal(str)
    terminal_output = pyqtSignal(str)
    terminal_resize = pyqtSignal(int, int)
    open_terminal_requested = pyqtSignal()  # Request to open terminal panel
    
    # Navigation
    navigate_to_line = pyqtSignal(str, int)  # file_path, line_number
    
    # Smart paste signal
    smart_paste_check_requested = pyqtSignal(str)  # pasted_text
    search_files_requested = pyqtSignal(str)       # @ mention file search
    
    # Chat persistence signals
    save_chats_requested = pyqtSignal(str, str)  # storage_key, json_data
    load_chats_requested = pyqtSignal(str)       # storage_key
    
    @pyqtSlot(str, str, str)
    def on_model_changed(self, model_id, perf, cost):
        self.model_changed.emit(model_id, perf, cost)
    
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
    def on_request_diff_data(self, file_path):
        """Request diff data for a file - called when JS needs diff content."""
        log.debug(f"Diff data requested for: {file_path}")
        # Emit signal to main_window to provide diff data
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
        # Open file in editor and emit accept signal
        self.open_file_requested.emit(file_path)
        self.accept_file_edit_requested.emit(file_path)

    @pyqtSlot(str)
    def on_reject_file_edit(self, file_path: str):
        """User rejected a file edit — optionally restore from pre-edit snapshot."""
        log.info(f'File edit rejected: {file_path}')
        # Open file in editor for review and emit reject signal
        self.open_file_requested.emit(file_path)
        self.reject_file_edit_requested.emit(file_path)

    @pyqtSlot()
    def on_accept_all_files(self):
        """User accepted all pending file edits."""
        log.info('Accept all files requested')
        # Signal to main_window to accept all pending edits
        # This will be handled by the sidebar's changed files panel
        self.accept_file_edit_requested.emit("__ALL__")

    @pyqtSlot()
    def on_reject_all_files(self):
        """User rejected all pending file edits."""
        log.info('Reject all files requested')
        # Signal to main_window to reject all pending edits
        self.reject_file_edit_requested.emit("__ALL__")

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

    # ── THREE FEATURES: Project Tree, Terminal, Todo Bridge Slots ─────

    @pyqtSlot(str)
    def on_open_folder(self, folder_path: str):
        """Open folder in OS file explorer."""
        try:
            if sys.platform == 'win32':
                import subprocess
                subprocess.Popen(['explorer', folder_path])
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', folder_path])
            else:
                import subprocess
                subprocess.Popen(['xdg-open', folder_path])
        except Exception as e:
            log.error(f"Cannot open folder: {e}")

    @pyqtSlot()
    def on_open_terminal(self):
        """Open terminal panel."""
        log.info("Open terminal requested from chat")
        self.open_terminal_requested.emit()

    # ── CHAT PERSISTENCE: File-based storage fallback ─────────────────
    
    @pyqtSlot(str, str, result=str)
    def save_chats_to_sqlite(self, storage_key: str, json_data: str) -> str:
        """
        Save chat data to SQLite database.
        This provides high-performance persistent storage.
        Returns: "OK" or error message.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            # Parse JSON data
            chats = json.loads(json_data)
            
            # Get chat history manager
            history = get_chat_history()
            
            # Save each conversation
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                
                conversation_id = chat.get('id', storage_key)
                project_path = f"project_{storage_key}"
                title = chat.get('title', f"Chat {conversation_id[:8]}")
                messages = chat.get('messages', [])
                
                # Create conversation if not exists
                history.create_conversation(project_path, title)
                
                # Add all messages
                for msg in messages:
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    files_accessed = msg.get('files_accessed', [])
                    tools_used = msg.get('tools_used', [])
                    
                    history.add_message(
                        conversation_id=conversation_id,
                        role=role,
                        content=content,
                        files_accessed=files_accessed,
                        tools_used=tools_used
                    )
            
            log.debug(f'✓ Saved {len(chats)} chats to SQLite (storage_key: {storage_key})')
            return "OK"
            
        except Exception as e:
            log.error(f'✗ Failed to save chats to SQLite: {e}')
            return f"ERROR: {str(e)}"
    
    @pyqtSlot(str, result=str)
    def load_chats_from_sqlite(self, storage_key: str) -> str:
        """
        Load ONLY chat metadata (not full messages) for fast sidebar rendering.
        Returns: JSON string with conversation list or empty array.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            # Get chat history manager
            history = get_chat_history()
            
            # Get project path
            project_path = f"project_{storage_key}"
            
            # Get all conversations for this project
            conversations = history.get_conversations(project_path)
            
            if not conversations:
                log.debug(f'No chats found in SQLite for storage_key: {storage_key}')
                return "[]"
            
            # OPTIMIZATION: Return only metadata (id, title, created_at) - NOT full messages
            # Full messages loaded on-demand when user clicks a chat
            result = []
            for conv in conversations:
                chat_data = {
                    'id': conv['conversation_id'],
                    'title': conv['title'],
                    'created_at': conv.get('created_at'),
                    'message_count': conv.get('message_count', 0)  # Just count, not content
                }
                result.append(chat_data)
            
            json_result = json.dumps(result)
            log.debug(f'✓ Loaded {len(result)} chat metadata ({len(json_result)} chars)')
            return json_result
            
        except Exception as e:
            log.error(f'✗ Failed to load chats from SQLite: {e}')
            return "[]"
    
    def load_full_chat_from_sqlite(self, conversation_id: str) -> str:
        """
        Load full chat messages for a specific conversation (on-demand).
        Returns: JSON string with complete conversation or empty object.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            history = get_chat_history()
            messages = history.get_messages(conversation_id)
            
            if not messages:
                return "{}"
            
            result = {
                'id': conversation_id,
                'messages': messages
            }
            
            json_result = json.dumps(result)
            log.debug(f'✓ Loaded full chat {conversation_id} ({len(json_result)} chars)')
            return json_result
            
        except Exception as e:
            log.error(f'✗ Failed to load full chat: {e}')
            return "{}"


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
            try:
                if '[CHAT]' in message:
                    print(f"\033[96m[JS {level_name}] {message}\033[0m")  # Cyan color
                else:
                    print(f"[JS {level_name}] {message}")
            except UnicodeEncodeError:
                # Fallback for Windows console encoding issues
                safe_message = message.encode('ascii', 'ignore').decode('ascii')
                if '[CHAT]' in message:
                    print(f"[JS {level_name}] {safe_message}")
                else:
                    print(f"[JS {level_name}] {safe_message}")


class AIChatWidget(QWidget):
    """Web-based AI chat widget using QWebEngineView."""
    message_sent = pyqtSignal(str, str)  # user_message, code_context
    run_command = pyqtSignal(str)
    stop_requested = pyqtSignal()
    proceed_requested = pyqtSignal()
    always_allow_changed = pyqtSignal(bool)
    generate_plan_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    model_changed = pyqtSignal(str, str, str)  # model_id, perf, cost
    
    open_file_requested = pyqtSignal(str)
    open_file_at_line_requested = pyqtSignal(str, int)  # file_path, line_number
    show_diff_requested = pyqtSignal(str)

    # File edit accept/reject signals
    accept_file_edit_requested = pyqtSignal(str)  # file_path
    reject_file_edit_requested = pyqtSignal(str)  # file_path

    # Terminal panel signal
    open_terminal_requested = pyqtSignal()  # Request main window to open terminal panel

    # Smart paste signal - emitted when user pastes code, to check if it matches editor selection
    smart_paste_check_requested = pyqtSignal(str)  # pasted_text

    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Initialize with actual current theme from theme manager
        try:
            from src.config.theme_manager import get_theme_manager
            self._is_dark = get_theme_manager().is_dark
        except Exception:
            self._is_dark = True  # fallback to dark
        self._get_code_context = None
        self._terminal_process = None
        self._pty_process = None
        self._terminal_reader = None
        self._project_root = None  # Set via set_project_root() for @ mention search
        self._build_ui()
        # Terminal backend starts lazily when first requested
        
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
        self._bridge.model_changed.connect(self.model_changed.emit)
        self._bridge.open_file_requested.connect(self.open_file_requested.emit)
        self._bridge.open_file_at_line_requested.connect(self.open_file_at_line_requested.emit)
        self._bridge.show_diff_requested.connect(self.show_diff_requested.emit)
        self._bridge.accept_file_edit_requested.connect(self.accept_file_edit_requested.emit)
        self._bridge.reject_file_edit_requested.connect(self.reject_file_edit_requested.emit)
        self._bridge.open_terminal_requested.connect(self.open_terminal_requested.emit)
        self._bridge.search_files_requested.connect(self._on_search_files)
        
        # NEW: Lazy load full chat when JS requests it
        self._bridge.load_full_chat_requested.connect(self._on_load_full_chat_requested)
        
        self._channel.registerObject("bridge", self._bridge)

        self._page.setWebChannel(self._channel)
        
        # Load local HTML
        html_path = os.path.join(os.path.dirname(__file__), "..", "html", "ai_chat", "aichat.html")
        self._view.setUrl(QUrl.fromLocalFile(os.path.abspath(html_path)))

        # Apply initial theme once the page has finished loading
        self._view.loadFinished.connect(self._on_page_loaded)
        
        layout.addWidget(self._view)
        
    def _on_page_loaded(self, ok):
        """Apply the current theme immediately after the page finishes loading."""
        if ok:
            js_bool = 'true' if self._is_dark else 'false'
            self._view.page().runJavaScript(f"if(window.setTheme) window.setTheme({js_bool});")

    def _on_js_message(self, text):
        """Handle message from JS."""
        context = ""
        if self._get_code_context:
            context = self._get_code_context()
        self.message_sent.emit(text, context)
    
    def _on_load_full_chat_requested(self, conversation_id: str):
        """Handle lazy load request for full chat messages from JS."""
        try:
            # Load full chat data from SQLite
            full_chat_json = self.load_full_chat_from_sqlite(conversation_id)
            
            # Send back to JS via custom event
            escaped_json = full_chat_json.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')
            js_code = f"""
            (function() {{
                var event = new CustomEvent('chatFullLoadHandler', {{ detail: "{escaped_json}" }});
                window.dispatchEvent(event);
            }})();
            """
            self._view.page().runJavaScript(js_code)
            
            log.debug(f"Sent full chat {conversation_id} to JS ({len(full_chat_json)} chars)")
        except Exception as e:
            log.error(f"Failed to load full chat {conversation_id}: {e}")

    def _on_search_files(self, query: str):
        """Handle @ mention file search from JS - OPTIMIZED."""
        try:
            from pathlib import Path
            results = []
            root = getattr(self, '_project_root', None) or '.'
            root_path = Path(root)
            
            # Performance optimization: limit to top 2 levels and 10 results
            for level in range(2):
                for p in root_path.glob("*/" * level + "*"):
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
        """Update theme — called from main_window toggle and on page load."""
        self._is_dark = is_dark
        # Python True/False must become JS true/false (lowercase)
        js_bool = 'true' if is_dark else 'false'
        self._view.page().runJavaScript(f"if(window.setTheme) window.setTheme({js_bool});")
        
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

    # ── THREE FEATURES: Project Tree Card, Terminal Card, Todo Updates ─

    def emit_directory_tree(self, root_path: str, listing_text: str):
        """
        Parse listing_text from list_directory tool result
        and send structured data to JS for tree card rendering.
        """
        items = self._parse_listing(root_path, listing_text)
        root_js  = json.dumps(root_path)
        items_js = json.dumps(items)
        self._view.page().runJavaScript(
            f"if(window.showDirectoryTree) window.showDirectoryTree({root_js}, {items_js});"
        )

    def _parse_listing(self, root_path: str, text: str) -> list:
        """Convert list_directory output to hierarchical tree structure [{name, path, size, isDir, isLast, depth, parentIdx}]"""
        lines = [l for l in text.split('\n') if l.strip()]
        items = []
        root = root_path.rstrip('/\\')
        sep = '\\' if '\\' in root else '/'

        # Stack to track parent paths at each depth level
        parent_stack = [root]

        for i, line in enumerate(lines):
            # Calculate depth by counting leading spaces or tree characters
            leading = len(line) - len(line.lstrip())
            depth = leading // 2  # Assume 2 spaces per indent level

            # Remove tree branch characters and get clean name
            stripped = line.strip()
            if not stripped:
                continue

            # Check for tree branch characters
            is_dir = stripped.startswith('📁') or stripped.endswith('/')
            
            # Remove tree branch characters (├──, └──, │, etc.)
            name = stripped
            for prefix in ['├──', '└──', '│', '├──', '└──']:
                name = name.replace(prefix, '')
            name = name.lstrip('📁📄').strip()

            size = ''
            desc = ''

            # Parse "(4KB) - description" pattern
            import re
            m = re.match(r'^(.*?)\s*\(([^)]+)\)\s*(?:-\s*(.+))?$', name)
            if m:
                name = m.group(1).strip().rstrip('/')
                size = m.group(2)
                desc = m.group(3) or ''
            else:
                name = name.rstrip('/')

            # Adjust parent stack based on depth
            while len(parent_stack) > depth + 1:
                parent_stack.pop()

            # Build full path
            current_path = sep.join(parent_stack) + sep + name

            # Check if next item is at same depth (to determine isLast)
            is_last = True
            if i < len(lines) - 1:
                next_line = lines[i + 1]
                next_leading = len(next_line) - len(next_line.lstrip())
                next_depth = next_leading // 2
                # If next item is at same depth, this one is not last
                if next_depth == depth:
                    is_last = False
                # If next item is deeper, this one has children (so not last in its group)
                elif next_depth > depth:
                    is_last = False

            items.append({
                'name':        name,
                'path':        current_path,
                'size':        size,
                'description': desc,
                'isDir':       is_dir,
                'isLast':      is_last,
                'depth':       depth,
                'hasChildren': False  # Will be set in second pass
            })

            # If this is a directory, add it to parent stack for children
            if is_dir:
                if len(parent_stack) <= depth + 1:
                    parent_stack.append(name)
                else:
                    parent_stack[depth + 1] = name

        # Second pass: mark which items have children
        for i, item in enumerate(items):
            for j in range(i + 1, len(items)):
                if items[j]['depth'] == item['depth'] + 1:
                    item['hasChildren'] = True
                    break
                elif items[j]['depth'] <= item['depth']:
                    break

        return items

    def emit_terminal_result(self, card_id: str, output: str, exit_code: int):
        """Update the terminal card in chat with result."""
        self._view.page().runJavaScript(
            f"if(window.setTerminalOutput) window.setTerminalOutput({json.dumps(card_id)}, "
            f"{json.dumps(output[:3000])}, {exit_code});"
        )

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
            
            # Load chats from SQLite
            chats_data = self._bridge.load_chats_from_sqlite(storage_key)
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

    def show_indexing_status(self, message: str, auto_hide: bool = False):
        """Show project indexing status bar."""
        import json
        safe_msg = json.dumps(message)
        safe_hide = 'true' if auto_hide else 'false'
        self._view.page().runJavaScript(
            f"if(window.showIndexingStatus) showIndexingStatus({safe_msg}, {safe_hide});"
        )

    def hide_indexing_status(self):
        """Hide project indexing status bar."""
        self._view.page().runJavaScript(
            "if(window.hideIndexingStatus) hideIndexingStatus();"
        )

    def _ensure_terminal_backend(self):
        """Lazy initialization of terminal backend - only starts when first requested."""
        if self._pty_process is not None or self._terminal_process is not None:
            return  # Already started
            
        shell = "powershell.exe" if platform.system() == "Windows" else "bash"
        
        try:
            import winpty
            # Configure winpty with larger buffer for better performance
            self._pty_process = winpty.PtyProcess.spawn(
                shell,
                dimensions=(24, 80),
                backend=winpty.Backend.WinPTY  # Use WinPTY for better performance
            )
            
            from PyQt6.QtCore import QThread, QMutex
            import threading

            class Reader(QThread):
                data = pyqtSignal(str)

                def __init__(self, pty):
                    super().__init__()
                    self.pty = pty
                    self._running = True
                    self._buffer = ""
                    self._buffer_mutex = QMutex()
                    self._max_buffer_size = 8192
                    self._read_timeout = 0.05  # 50ms max wait per read

                def run(self):
                    """Non-blocking read loop with periodic flushing."""
                    import time
                    last_flush = time.time()
                    flush_interval = 0.1  # Flush every 100ms max

                    while self._running and self.pty.isalive():
                        try:
                            # Non-blocking read with small chunk size
                            d = None
                            if self.pty.isalive():
                                try:
                                    # Check if data available without blocking
                                    d = self.pty.read(timeout=self._read_timeout)
                                except Exception:
                                    pass

                            if d:
                                self._buffer_mutex.lock()
                                self._buffer += d
                                should_flush = len(self._buffer) > self._max_buffer_size
                                self._buffer_mutex.unlock()

                                if should_flush:
                                    self._flush_buffer()
                                    last_flush = time.time()

                            # Periodic flush for small data
                            current_time = time.time()
                            if current_time - last_flush > flush_interval:
                                self._flush_buffer()
                                last_flush = current_time

                            # Small sleep to prevent CPU spinning
                            time.sleep(0.01)

                        except EOFError:
                            break
                        except Exception:
                            time.sleep(0.01)

                    # Final flush on exit
                    self._flush_buffer()

                def _flush_buffer(self):
                    """Emit buffered data safely."""
                    self._buffer_mutex.lock()
                    data_to_emit = self._buffer if self._buffer else None
                    self._buffer = ""
                    self._buffer_mutex.unlock()

                    if data_to_emit:
                        self.data.emit(data_to_emit)

                def stop(self):
                    self._running = False
                    self.wait(500)  # Wait up to 500ms for clean shutdown
            
            self._terminal_reader = Reader(self._pty_process)

            # Rate-limited emitter to prevent UI freezing
            self._terminal_output_buffer = ""
            self._terminal_last_emit = 0
            self._terminal_emit_interval = 0.05  # 50ms minimum between emits

            def _emit_terminal_data(data):
                import time
                now = time.time()
                self._terminal_output_buffer += data

                # Emit if enough time passed or buffer is large
                if (now - self._terminal_last_emit > self._terminal_emit_interval or
                    len(self._terminal_output_buffer) > 2048):
                    if self._terminal_output_buffer:
                        self._bridge.terminal_output.emit(self._terminal_output_buffer)
                        self._terminal_output_buffer = ""
                        self._terminal_last_emit = now

            self._terminal_reader.data.connect(
                _emit_terminal_data,
                Qt.ConnectionType.QueuedConnection
            )
            self._terminal_reader.start()
            
            self._bridge.terminal_input.connect(lambda d: self._pty_process.write(d) if self._pty_process else None)
            self._bridge.terminal_resize.connect(lambda c, r: self._pty_process.setwinsize(r, c) if self._pty_process else None)
            
        except Exception as e:
            log.warning(f"Could not start winpty for AI chat terminal: {e}. Falling back to QProcess.")
            self._terminal_process = QProcess(self)
            self._terminal_process.readyReadStandardOutput.connect(self._on_stdout)
            self._terminal_process.start(shell)
            self._bridge.terminal_input.connect(lambda d: self._terminal_process.write(d.encode()) if self._terminal_process else None)

    def _on_stdout(self):
        if self._terminal_process:
            data = self._terminal_process.readAllStandardOutput().data().decode(errors="replace")
            if data:
                self._bridge.terminal_output.emit(data)

    def closeEvent(self, event):
        # Flush any pending terminal output before closing
        if hasattr(self, '_terminal_output_buffer') and self._terminal_output_buffer:
            self._bridge.terminal_output.emit(self._terminal_output_buffer)
            self._terminal_output_buffer = ""
        if self._pty_process:
            self._pty_process.terminate()
        if self._terminal_process:
            self._terminal_process.terminate()
        super().closeEvent(event)

