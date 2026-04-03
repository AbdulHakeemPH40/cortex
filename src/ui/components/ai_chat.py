import os
import sys
import json
import platform
import shutil
import re
import difflib
from typing import Optional, Callable
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QObject, pyqtSlot, QProcess, QProcessEnvironment, QTimer, QThread, QMutex
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from src.utils.logger import get_logger

from src.utils.icons import make_icon

log = get_logger("ai_chat")


class VisionWorker(QObject):
    """Worker for processing vision requests in background thread."""
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, task: Callable):
        super().__init__()
        self._task = task
    
    def run(self):
        try:
            self._task()
        except Exception as e:
            self.error_occurred.emit(str(e))


class FileSearchWorker(QThread):
    """Background worker for file search to avoid blocking UI."""
    results_ready = pyqtSignal(list)
    
    def __init__(self, project_root: str, query: str, max_results: int = 10):
        super().__init__()
        self._project_root = project_root
        self._query = query
        self._max_results = max_results
    
    def run(self):
        try:
            results = []
            count = 0
            for root, dirs, files in os.walk(self._project_root):
                if '.git' in dirs: dirs.remove('.git')
                if 'node_modules' in dirs: dirs.remove('node_modules')
                if '__pycache__' in dirs: dirs.remove('__pycache__')
                if 'venv' in dirs: dirs.remove('venv')
                if '.venv' in dirs: dirs.remove('.venv')
                
                for file in files:
                    if self._query.lower() in file.lower():
                        rel_path = os.path.relpath(os.path.join(root, file), self._project_root)
                        results.append(rel_path.replace("\\", "/"))
                        count += 1
                        if count >= self._max_results:
                            self.results_ready.emit(results)
                            return
                if count >= self._max_results:
                    break
            
            self.results_ready.emit(results)
        except Exception as e:
            log.error(f"FileSearchWorker error: {e}")
            self.results_ready.emit([])


class ChatBridge(QObject):
    """Bridge for communication between JS and Python."""
    def __init__(self, view, parent_widget=None):
        super().__init__()
        self._view = view
        self._parent_widget = parent_widget  # Reference to AIChatWidget for accessing _current_project_path
    message_submitted = pyqtSignal(str)
    message_with_images = pyqtSignal(str, str)  # text, image_data_json
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
    show_diff_requested = pyqtSignal(str)
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
    
    # Vision response signal
    _vision_response_received = pyqtSignal(str)  # response text
    
    # Chat persistence signals
    save_chats_requested = pyqtSignal(str, str)  # storage_key, json_data
    load_chats_requested = pyqtSignal(str)       # storage_key
    load_full_chat_requested = pyqtSignal(str)   # conversation_id (lazy load full chat)
    save_finished = pyqtSignal(str)              # status
    
    # Permission system signal (NEW!)
    on_permission_response = pyqtSignal(bool, bool)  # approved, remember
    answer_question_requested = pyqtSignal(str, str) # tool_call_id, answer
    
    # NEW: Permission response from chat UI (OpenCode enhancement)
    permission_response = pyqtSignal(str, bool, str, bool)  # request_id, approved, scope, remember
    
    # Code Completion signals (OpenCode-style)
    code_completion_requested = pyqtSignal(dict)  # {code, language, cursorPosition}
    
    # Todo Management signals
    toggle_todo_requested = pyqtSignal(str, bool)  # task_id, completed
    code_completion_selected = pyqtSignal(dict)   # {requestId, index, completion}
    code_completion_accepted = pyqtSignal(dict)   # {requestId, completedCode}
    code_completion_dismissed = pyqtSignal(dict)  # {requestId}
    
    # Inline Diff Viewer signals (OpenCode-style)
    diff_line_accepted = pyqtSignal(dict)   # {filePath, lineNumber}
    diff_line_rejected = pyqtSignal(dict)   # {filePath, lineNumber}
    diff_line_commented = pyqtSignal(dict)  # {filePath, lineNumber, comment}
    
    @pyqtSlot(str, str, str)
    def on_model_changed(self, model_id, perf, cost):
        self.model_changed.emit(model_id, perf, cost)
    
    @pyqtSlot(str)
    def on_message_submitted(self, text):
        self.message_submitted.emit(text)
    
    @pyqtSlot(str, str)
    def on_message_with_images(self, text, image_data):
        self.message_with_images.emit(text, image_data)
        
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

    def show_question(self, question_info: dict):
        """Send a question to the JS chat UI for user response."""
        js_data = json.dumps(question_info)
        self._view.page().runJavaScript(f"if(window.showQuestionCard) window.showQuestionCard({js_data});")

    @pyqtSlot(str, str)
    def on_answer_question(self, tool_call_id, answer):
        """User answered a pending question from the AI."""
        self.answer_question_requested.emit(tool_call_id, answer)

    @pyqtSlot(str)
    def on_show_diff(self, file_path):
        log.info(f"[Diff-Debug] on_show_diff called with: {file_path}")
        log.info(f"[Diff-Debug] show_diff_requested signal exists: {hasattr(self, 'show_diff_requested')}")
        self.show_diff_requested.emit(file_path)
        log.info(f"[Diff-Debug] show_diff_requested.emit() called")

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
    
    @pyqtSlot()
    def on_toggle_autogen(self):
        """Toggle AutoGen multi-agent mode."""
        from src.ai.agent import AIAgent
        # Find the AI agent instance and toggle AutoGen
        # This will be handled by main_window
        self.toggle_autogen_requested.emit()
    
    # Add new signal for AutoGen toggle
    toggle_autogen_requested = pyqtSignal()

    @pyqtSlot(bool)
    def handle_permission_response(self, allowed):
        """Handle permission response from JS (Allow/Deny tool execution)."""
        # Emit proceed signal if allowed, otherwise just log
        if allowed:
            self.proceed_requested.emit()
        else:
            log.info("User denied tool execution permission")

    @pyqtSlot(str, bool, str, bool)
    def on_permission_card_response(self, request_id: str, approved: bool, scope: str, remember: bool = False):
        """Handle permission card response from JS (OpenCode enhancement)."""
        log.info(f"Permission card response: {request_id} - approved={approved}, scope={scope}, remember={remember}")
        self.permission_response.emit(request_id, approved, scope, remember)

    # â”€â”€ CODE COMPLETION SLOTS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    @pyqtSlot(dict)
    def on_request_code_completion(self, data: dict):
        """Handle code completion request from JS."""
        log.info(f"Code completion requested for {data.get('language', 'python')}")
        self.code_completion_requested.emit(data)
    
    @pyqtSlot(dict)
    def on_code_completion_selected(self, data: dict):
        """Handle code completion selection from JS."""
        log.info(f"Code completion selected: {data.get('index', 0)}")
        self.code_completion_selected.emit(data)
    
    @pyqtSlot(dict)
    def on_code_completion_accepted(self, data: dict):
        """Handle code completion acceptance from JS."""
        log.info(f"Code completion accepted: {data.get('requestId', 'unknown')}")
        self.code_completion_accepted.emit(data)
    
    @pyqtSlot(dict)
    def on_code_completion_dismissed(self, data: dict):
        """Handle code completion dismissal from JS."""
        log.info(f"Code completion dismissed: {data.get('requestId', 'unknown')}")
        self.code_completion_dismissed.emit(data)
    
    # â”€â”€ INLINE DIFF VIEWER SLOTS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    @pyqtSlot(dict)
    def on_diff_line_accepted(self, data: dict):
        """Handle diff line acceptance from JS."""
        log.info(f"Diff line accepted: {data.get('filePath')}:{data.get('lineNumber')}")
        self.diff_line_accepted.emit(data)
    
    @pyqtSlot(dict)
    def on_diff_line_rejected(self, data: dict):
        """Handle diff line rejection from JS."""
        log.info(f"Diff line rejected: {data.get('filePath')}:{data.get('lineNumber')}")
        self.diff_line_rejected.emit(data)
    
    @pyqtSlot(dict)
    def on_diff_line_commented(self, data: dict):
        """Handle diff line comment from JS."""
        log.info(f"Diff line commented: {data.get('filePath')}:{data.get('lineNumber')}")
        self.diff_line_commented.emit(data)

    # â”€â”€ ENHANCEMENT GUIDE: Missing Bridge Slots â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @pyqtSlot(str, bool)
    def on_toggle_todo(self, task_id: str, completed: bool):
        """User toggled a todo item in the UI."""
        log.info(f"Todo toggled: {task_id} -> {'completed' if completed else 'pending'}")
        self.toggle_todo_requested.emit(task_id, completed)

    @pyqtSlot()
    def on_stop_generation(self):
        """Stop AI generation â€” called from Escape key or stop button in JS."""
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
    
    # ========== PERMISSION DIALOG BRIDGE (NEW) ==========
    
    # Signal to request permission from user
    permission_requested = pyqtSignal(str, str, object)  # tool_name, details_html, callback
    
    @pyqtSlot(str, str)
    def request_permission(self, tool_name: str, details_html: str):
        """
        Request permission from user via web dialog.
        Called by ToolRegistry when tool requires confirmation.
        
        Args:
            tool_name: Name of the tool (e.g., 'edit_file', 'write_file')
            details_html: HTML content showing what will be changed
        """
        log.info(f"Permission requested for: {tool_name}")
        # Emit signal with callback to handle response
        self.permission_requested.emit(tool_name, details_html, self._handle_permission_response)
    
    def _handle_permission_response(self, approved: bool, remember: bool):
        """
        Handle permission response from user.
        This is called by JavaScript when user clicks Approve/Deny.
        
        Args:
            approved: True if user approved, False if denied
            remember: True if user wants to remember choice
        """
        log.info(f"Permission response: approved={approved}, remember={remember}")
        # Store response for ToolRegistry to pick up
        # This will be handled by a waiting mechanism in ToolRegistry

    @pyqtSlot(str)
    def on_reject_file_edit(self, file_path: str):
        """User rejected a file edit â€” optionally restore from pre-edit snapshot."""
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

    @pyqtSlot(str)
    def delete_chat_from_sqlite(self, conversation_id: str):
        """Delete a conversation from SQLite."""
        try:
            from src.core.chat_history import get_chat_history
            history = get_chat_history()
            history.delete_conversation(conversation_id)
            log.info(f"âœ“ Deleted conversation {conversation_id} from SQLite")
        except Exception as e:
            log.error(f"âœ— Failed to delete conversation {conversation_id}: {e}")

    @pyqtSlot(str)
    def load_full_chat(self, conversation_id: str):
        """Trigger loading of full chat messages for a specific conversation."""
        try:
            # This will be handled by the signal connection in AIChatWidget
            self.load_full_chat_requested.emit(conversation_id)
            log.debug(f"Requested full chat load for {conversation_id}")
        except Exception as e:
            log.error(f"Failed to request full chat {conversation_id}: {e}")

    # â”€â”€ THREE FEATURES: Project Tree, Terminal, Todo Bridge Slots â”€â”€â”€â”€â”€

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

    # â”€â”€ CHAT PERSISTENCE: File-based storage fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    @pyqtSlot(str, str, result=str)
    def save_single_chat_to_sqlite(self, storage_key: str, json_data: str) -> str:
        """
        Save a SINGLE chat's data to SQLite database.
        This provides high-performance persistent storage without full-history payload overhead.
        """
        try:
            from src.core.chat_history import get_chat_history
            chat = json.loads(json_data)
            history = get_chat_history()
            
            if not isinstance(chat, dict):
                return "ERROR: Invalid chat data"
                
            conversation_id = str(chat.get('id', storage_key))
            
            # Use actual project path from parent widget's _current_project_path
            if self._parent_widget and hasattr(self._parent_widget, '_current_project_path'):
                project_path = self._parent_widget._current_project_path or f"project_{storage_key}"
            else:
                project_path = f"project_{storage_key}"
            
            title = chat.get('title', f"Chat {conversation_id[:8]}")
            messages = chat.get('messages', [])
            
            # Skip saving if no messages
            if not messages:
                log.debug(f"Skipping save for empty conversation {conversation_id}")
                return "OK - Skipped empty"
                
            # Create conversation if not exists
            history.create_conversation(project_path, title, conversation_id=conversation_id)

            total_messages = len(messages)
            existing_count = history.db.get_message_count(conversation_id)
            if existing_count > total_messages:
                history.clear_conversation_messages(conversation_id)
                existing_count = 0
            
            if existing_count == total_messages:
                log.debug(f"Skipping save for conversation {conversation_id} (no new messages)")
                return "OK - No new messages"
            
            # Add only new messages
            for msg in messages[existing_count:]:
                # Handle both 'content' (new) and 'text' (legacy) keys
                msg_content = msg.get('content') or msg.get('text', '')
                msg_role = msg.get('role') or msg.get('sender') or 'user'
                history.add_message(
                    conversation_id=conversation_id,
                    role=msg_role,
                    content=msg_content,
                    files_accessed=msg.get('files_accessed', []),
                    tools_used=msg.get('tools_used', [])
                )
            
            log.debug(f'âœ“ Saved single chat {conversation_id} to SQLite (storage_key: {storage_key})')
            return "OK"
            
        except Exception as e:
            log.error(f'âœ— Failed to save single chat to SQLite: {e}')
            return f"ERROR: {str(e)}"

    @pyqtSlot(str, str, result=str)
    def save_chats_to_sqlite(self, storage_key: str, json_data: str) -> str:
        """
        Save ALL chat data to SQLite database. (Legacy full-sync fallback)
        Returns: "OK" or error message.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            # Parse JSON data
            chats = json.loads(json_data)
            history = get_chat_history()
            
            # Save each conversation
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                
                conversation_id = str(chat.get('id', storage_key))
                
                # Use actual project path from parent widget's _current_project_path
                if self._parent_widget and hasattr(self._parent_widget, '_current_project_path'):
                    project_path = self._parent_widget._current_project_path or f"project_{storage_key}"
                else:
                    project_path = f"project_{storage_key}"
                
                title = chat.get('title', f"Chat {conversation_id[:8]}")
                messages = chat.get('messages', [])
                
                # Create conversation if not exists
                history.create_conversation(project_path, title, conversation_id=conversation_id)

                total_messages = len(messages)
                existing_count = history.db.get_message_count(conversation_id)
                if existing_count > total_messages:
                    history.clear_conversation_messages(conversation_id)
                    existing_count = 0
                
                if existing_count == total_messages:
                    continue
                
                # Add only new messages
                for msg in messages[existing_count:]:
                    history.add_message(
                        conversation_id=conversation_id,
                        role=msg.get('role', msg.get('sender', 'user')),
                        content=msg.get('content', msg.get('text', '')),
                        files_accessed=msg.get('files_accessed', []),
                        tools_used=msg.get('tools_used', [])
                    )
            
            log.debug(f'âœ“ Saved {len(chats)} chats to SQLite (storage_key: {storage_key})')
            return "OK"
            
        except Exception as e:
            log.error(f'âœ— Failed to save chats to SQLite: {e}')
            return f"ERROR: {str(e)}"
    
    @pyqtSlot(str)
    def on_save_finished(self, status: str):
        """Called by JS when save process is completed (success or error)."""
        log.info(f"JS Save finished signal received from bridge: {status}")
        # Emit signal to notify waiting components (like MainWindow.closeEvent)
        self.save_finished.emit(status)
    
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
            
            # OPTIMIZATION 1: Return only metadata (id, title, created_at) - NOT full messages
            # Full messages loaded on-demand when user clicks a chat
            
            # OPTIMIZATION 2: Limit to recent 50 chats for performance
            MAX_CHATS_DISPLAY = 50
            if len(conversations) > MAX_CHATS_DISPLAY:
                conversations = conversations[:MAX_CHATS_DISPLAY]
                log.info(f'âš¡ Limited to {MAX_CHATS_DISPLAY} most recent chats for performance')
            
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
            log.debug(f'âœ“ Loaded {len(result)} chat metadata ({len(json_result)} chars)')
            return json_result
            
        except Exception as e:
            log.error(f'âœ— Failed to load chats from SQLite: {e}')
            return "[]"
    
    @pyqtSlot(str, result=str)
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
            log.debug(f'âœ“ Loaded full chat {conversation_id} ({len(json_result)} chars)')
            return json_result
            
        except Exception as e:
            log.error(f'âœ— Failed to load full chat: {e}')
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
    answer_question_requested = pyqtSignal(str, str)   # tool_call_id, answer
    show_diff_requested = pyqtSignal(str)
    
    # Permission response signal (forwarded from bridge)
    permission_response = pyqtSignal(str, bool, str)  # request_id, approved, scope

    # File edit accept/reject signals
    accept_file_edit_requested = pyqtSignal(str)  # file_path
    reject_file_edit_requested = pyqtSignal(str)  # file_path
    
    # Vision processing signal
    _vision_response_received = pyqtSignal(str)

    # Terminal panel signal
    open_terminal_requested = pyqtSignal()  # Request main window to open terminal panel

    # Smart paste signal - emitted when user pastes code, to check if it matches editor selection
    smart_paste_check_requested = pyqtSignal(str)  # pasted_text
    
    # AutoGen multi-agent toggle signal
    toggle_autogen_requested = pyqtSignal()
    
    # Load full chat from database signal
    load_full_chat_requested = pyqtSignal(str)  # conversation_id
    save_finished = pyqtSignal(str)             # status
    
    # Todo management signal
    toggle_todo_requested = pyqtSignal(str, bool)  # task_id, completed
    
    def show_question(self, info: dict):
        """Show a question card in the chat UI."""
        self._bridge.show_question(info)

    def show_indexing_status(self, message: str, auto_hide: bool = False):
        """Show indexing status in the chat UI."""
        js_bool = 'true' if auto_hide else 'false'
        safe_message = json.dumps(message)
        self._view.page().runJavaScript(f"if(window.showIndexingStatus) window.showIndexingStatus({safe_message}, {js_bool});")

    def hide_indexing_status(self):
        """Hide indexing status in the chat UI."""
        self._view.page().runJavaScript("if(window.hideIndexingStatus) window.hideIndexingStatus();")

    def clear_project_info(self):
        """Clear project-specific info from the chat UI."""
        self._current_project_path = ""
        self._view.page().runJavaScript("if(window.clearProjectInfo) window.clearProjectInfo();")

    def _add_ai_bubble_streaming(self):
        """Pre-emptively show assistant thinking/bubble for streaming."""
        self.show_thinking()
    
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
        self._vision_thread = None
        self._vision_worker = None
        # Connect vision response signal
        self._vision_response_received.connect(self._on_vision_response)
        
        # Terminal state
        self._terminal_output_buffer = ""
        self._terminal_last_emit = 0
        self._terminal_emit_interval = 0.05
        self._current_project_path = ""
        
        # NEW: Store last user message for permission retry (OpenCode enhancement)
        self._last_user_message = ""
        
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
        self._bridge = ChatBridge(self._view, parent_widget=self)
        self._bridge.message_submitted.connect(self._on_js_message)
        self._bridge.message_with_images.connect(self._on_js_message_with_images)
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
        self._bridge.answer_question_requested.connect(self.answer_question_requested.emit)
        
        # Connect permission response signal from bridge
        self._bridge.permission_response.connect(self.permission_response.emit)
        
        # Connect code completion signals from bridge
        self._bridge.code_completion_requested.connect(self._on_code_completion_requested)
        self._bridge.code_completion_selected.connect(self._on_code_completion_selected)
        self._bridge.code_completion_accepted.connect(self._on_code_completion_accepted)
        self._bridge.code_completion_dismissed.connect(self._on_code_completion_dismissed)
        
        # Connect inline diff viewer signals from bridge
        self._bridge.diff_line_accepted.connect(self._on_diff_line_accepted)
        self._bridge.diff_line_rejected.connect(self._on_diff_line_rejected)
        self._bridge.diff_line_commented.connect(self._on_diff_line_commented)
        
        self._bridge.save_finished.connect(self.save_finished.emit)
        
        # NEW: Lazy load full chat when JS requests it
        self._bridge.load_full_chat_requested.connect(self._on_load_full_chat_requested)
        
        # NEW: Connect todo toggle from bridge to widget
        self._bridge.toggle_todo_requested.connect(self.toggle_todo_requested.emit)
        
        # Terminal signals
        self._bridge.terminal_input.connect(lambda d: self._pty_process.write(d) if self._pty_process else (self._terminal_process.write(d.encode()) if self._terminal_process else None))
        self._bridge.terminal_resize.connect(lambda c, r: self._pty_process.setwinsize(r, c) if self._pty_process else None)
        
        # Connect vision response signal
        self._bridge._vision_response_received.connect(self._on_vision_response)
        
        self._channel.registerObject("bridge", self._bridge)

        self._page.setWebChannel(self._channel)
        
        # Load local HTML
        html_path = os.path.join(os.path.dirname(__file__), "..", "html", "ai_chat", "aichat.html")
        self._view.setUrl(QUrl.fromLocalFile(os.path.abspath(html_path)))

        # Apply initial theme once the page has finished loading
        self._view.loadFinished.connect(self._on_page_loaded)
        self._page_loaded = False
        self._pending_project_info = None
        layout.addWidget(self._view)
        
    def run_javascript(self, script: str):
        """Execute JavaScript in the chat context."""
        if hasattr(self, '_view') and self._view.page():
            self._view.page().runJavaScript(script)
        
    def _on_page_loaded(self, ok):
        """Apply the current theme immediately after the page finishes loading."""
        if ok:
            self._page_loaded = True
            js_bool = 'true' if self._is_dark else 'false'
            self._view.page().runJavaScript(f"if(window.setTheme) window.setTheme({js_bool});")
            # Apply pending project info after page load
            if self._pending_project_info:
                name, path, chats_json = self._pending_project_info
                self._apply_project_info(name, path, chats_json)

    def on_chunk(self, chunk):
        """Handle AI streaming chunk - async to prevent UI blocking."""
        # Use JSON encoding to properly escape for JavaScript
        safe_chunk = json.dumps(chunk)
        self._view.page().runJavaScript(
            f"if(window.onChunk) window.onChunk({safe_chunk});",
            lambda result: None  # Async callback
        )

    def _on_js_message(self, text):
        """Handle message from JS."""
        # NEW: Store last user message for permission retry
        self._last_user_message = text
        
        context = ""
        if self._get_code_context:
            context = self._get_code_context()
        self.message_sent.emit(text, context)
    
    def _on_js_message_with_images(self, text, image_data_json):
        """Handle message with images - route to SiliconFlow for vision."""
        import json
        import requests
        import os
        from PyQt6.QtCore import QThread
        
        log.info(f"[AIChat] Message with images received, text length: {len(text)}")
        
        # Parse image data
        try:
            images = json.loads(image_data_json) if image_data_json else []
            log.info(f"[AIChat] Number of images: {len(images)}")
        except Exception as e:
            log.error(f"[AIChat] Failed to parse image data: {e}")
            images = []
        
        if not images:
            # No valid images, treat as regular message
            self._on_js_message(text)
            return
        
        # Show thinking indicator
        self._show_thinking_in_js()
        
        # Process in a separate thread to not block UI
        def process_vision():
            try:
                # Build content with images for vision API
                content_parts = [{"type": "text", "text": text}]
                for img in images:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img.get("data", "")}
                    })
                
                messages = [{
                    "role": "user",
                    "content": content_parts
                }]
                
                # Call SiliconFlow API directly with raw requests
                api_key = os.getenv("SILICONFLOW_API_KEY", "")
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": "Qwen/Qwen3-VL-32B-Instruct",
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 4000
                }
                
                response = requests.post(
                    "https://api.siliconflow.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=(30, 180)  # 30s connect, 180s read
                )
                
                if response.status_code == 200:
                    data = response.json()
                    result = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                    self._vision_response_received.emit(result)
                else:
                    error_msg = f"API Error {response.status_code}: {response.text[:200]}"
                    log.error(f"[AIChat] Vision API error: {error_msg}")
                    self._vision_response_received.emit(f"Error: {error_msg}")
                
            except Exception as e:
                log.error(f"[AIChat] Vision processing error: {e}")
                self._vision_response_received.emit(f"Error: {str(e)}")
        
        # Cleanup previous thread if exists and running
        if hasattr(self, '_vision_thread') and self._vision_thread is not None and self._vision_thread.isRunning():
            log.warning("Cleaning up previous vision thread...")
            self._vision_thread.quit()
            self._vision_thread.wait(3000)  # Wait up to 3s
        
        # Create thread for vision processing
        self._vision_thread = QThread()
        self._vision_worker = VisionWorker(process_vision)
        self._vision_worker.response_ready.connect(self._on_vision_response)
        self._vision_worker.error_occurred.connect(self._on_vision_error)
        self._vision_worker.moveToThread(self._vision_thread)
        self._vision_thread.started.connect(self._vision_worker.run)
        self._vision_thread.start()
        log.info("Vision thread started")
    
    def _show_thinking_in_js(self):
        """Show thinking indicator in JS chat."""
        try:
            js_code = "if(window.showThinkingIndicator) window.showThinkingIndicator();"
            self._view.page().runJavaScript(js_code)
        except Exception:
            pass
    
    def _on_vision_response(self, response: str):
        """Handle vision response and display in chat."""
        try:
            # Hide thinking
            js_code = "if(window.hideThinkingIndicator) window.hideThinkingIndicator();"
            self._view.page().runJavaScript(js_code)
            
            # Add response as assistant message
            js_code = f"if(window.appendMessage) window.appendMessage({json.dumps(response)}, 'assistant', true);"
            self._view.page().runJavaScript(js_code)
            
            # Cleanup thread after response
            self._cleanup_vision_thread()
        except Exception:
            pass
    
    def _on_vision_error(self, error: str):
        """Handle vision error."""
        try:
            # Hide thinking
            js_code = "if(window.hideThinkingIndicator) window.hideThinkingIndicator();"
            self._view.page().runJavaScript(js_code)
            
            # Add response as assistant message
            js_code = f"if(window.appendMessage) window.appendMessage({json.dumps('Error: ' + error)}, 'assistant', true);"
            self._view.page().runJavaScript(js_code)
            
            # Cleanup thread after error
            self._cleanup_vision_thread()
        except Exception:
            pass
    
    def _cleanup_vision_thread(self):
        """Cleanup vision thread after worker finishes."""
        if hasattr(self, '_vision_thread') and self._vision_thread:
            log.debug("Cleaning up vision thread...")
            self._vision_thread.quit()
            self._vision_thread.wait(3000)  # Wait up to 3s for thread to finish
    
    def _on_load_full_chat_requested(self, conversation_id: str):
        """Handle lazy load request for full chat messages from JS."""
        try:
            # Load full chat data from SQLite via bridge (returns JSON string)
            full_chat_json_str = self._bridge.load_full_chat_from_sqlite(conversation_id)
            
            # Parse it so we can pass components to the JS function signature: (id, messages)
            import json
            chat_data = json.loads(full_chat_json_str)
            messages = chat_data.get('messages', [])
            
            safe_id = json.dumps(conversation_id)
            safe_msgs = json.dumps(messages)
            
            # Direct function call to JS global
            js_code = f"if(window.chatFullLoadHandler) window.chatFullLoadHandler({safe_id}, {safe_msgs});"
            
            self._view.page().runJavaScript(js_code)
            log.info(f"âœ“ Restored {len(messages)} messages for chat {conversation_id}")
        except Exception as e:
            log.error(f"âœ— Failed to handle chat load for {conversation_id}: {e}")

    def _on_search_files(self, query: str):
        """Search for files matching the query for @ citations."""
        if not self._project_root:
            return
            
        try:
            self._file_search_worker = FileSearchWorker(self._project_root, query, 10)
            self._file_search_worker.results_ready.connect(self._on_file_search_results)
            self._file_search_worker.start()
        except Exception as e:
            log.error(f"Error starting file search: {e}")
    
    def _on_file_search_results(self, results: list):
        """Handle file search results from background thread."""
        js_results = json.dumps(results)
        self._view.page().runJavaScript(f"if(window.onFileSearchResults) window.onFileSearchResults({js_results});")
        if self._file_search_worker:
            self._file_search_worker.deleteLater()
            self._file_search_worker = None

    def set_project_root(self, path: str):
        """Set the project root for file searching."""
        self._project_root = path

    def set_code_context_callback(self, callback):
        """Used by main_window to provide editor code context."""
        self._get_code_context = callback

    def set_theme(self, is_dark: bool):
        """Update the UI theme. Matches MainWindow naming convention."""
        self._is_dark = is_dark
        js_bool = 'true' if is_dark else 'false'
        self._view.page().runJavaScript(f"if(window.setTheme) window.setTheme({js_bool});")

    def update_theme(self, is_dark: bool):
        """Alias for set_theme."""
        self.set_theme(is_dark)

    def on_chunk(self, chunk):
        """Handle AI streaming chunk - supporting both string and dict formats."""
        if not chunk: return
        
        # Proper escaping for JS
        safe_chunk = json.dumps(chunk)
        self._view.page().runJavaScript(
            f"if(window.onChunk) window.onChunk({safe_chunk});",
            lambda result: None
        )

    def on_complete(self, full_response: str):
        """Handle completion of the AI response."""
        self._view.page().runJavaScript("if(window.onComplete) window.onComplete();")

    def on_error(self, error_message: str):
        """Handle an error from the AI agent."""
        safe_error = json.dumps(error_message)
        self._view.page().runJavaScript(f"if(window.onError) window.onError({safe_error});")

    def show_thinking(self):
        """Show the thinking indicator."""
        self._view.page().runJavaScript("if(window.showThinking) window.showThinking();")

    def hide_thinking(self):
        """Hide the thinking indicator."""
        self._view.page().runJavaScript("if(window.hideThinking) window.hideThinking();")

    def update_todos(self, todos: list, main_task: str = ""):
        """Update the todo list in the UI."""
        import logging
        log = logging.getLogger('cortex.chat')
        log.info(f"[TODO] update_todos called with {len(todos)} todos, main_task: '{main_task}'")
        
        status_mapping = {
            'pending': 'PENDING',
            'in_progress': 'IN_PROGRESS',
            'completed': 'COMPLETE',
            'cancelled': 'CANCELLED'
        }
        
        formatted_todos = []
        for todo in todos:
            formatted_todo = {
                'id': todo.get('id', todo.get('description', '')),
                'content': todo.get('content', todo.get('description', '')),
                'status': status_mapping.get(todo.get('status', 'PENDING').lower(), todo.get('status', 'PENDING'))
            }
            formatted_todos.append(formatted_todo)
        
        safe_todos = json.dumps(formatted_todos)
        safe_task = json.dumps(main_task)
        self._view.page().runJavaScript(f"if(window.updateTodos) window.updateTodos({safe_todos}, {safe_task});")

    def show_tool_activity(self, tool_type: str, info: str, status: str):
        """Show tool execution progress.
        
        Args:
            tool_type: Type of tool (e.g., 'read_file', 'write_file')
            info: Tool execution info/details
            status: Status of execution ('running', 'complete', 'error')
        """
        activity = {
            'tool_type': tool_type,
            'info': info,
            'status': status
        }
        safe_activity = json.dumps(activity)
        self._view.page().runJavaScript(f"if(window.showToolActivity) window.showToolActivity({safe_activity});")

    def show_directory_contents(self, data: dict):
        """Show directory contents for the 'ls' command."""
        safe_data = json.dumps(data)
        self._view.page().runJavaScript(f"if(window.showDirectoryContents) window.showDirectoryContents({safe_data});")

    def show_tool_summary(self, summary_data: dict):
        """Show professional tool execution summary.
        
        Args:
            summary_data: Structured dict with file_writes, file_reads, commands, errors, other
        """
        safe_data = json.dumps(summary_data)
        self._view.page().runJavaScript(f"if(window.showToolSummary) window.showToolSummary({safe_data});")

    def add_system_message(self, message: str):
        """Append a system notification message to the chat view."""
        self._view.page().runJavaScript(f"if(window.appendMessage) window.appendMessage({json.dumps(message)}, 'system');")

    def show_permission_card(self, request_id: str, html_card: str):
        """Display a permission card in the chat (OpenCode enhancement)."""
        import json
        safe_request_id = json.dumps(request_id)
        safe_html = json.dumps(html_card)
        self._view.page().runJavaScript(
            f"if(window.showPermissionCard) window.showPermissionCard({safe_request_id}, {safe_html});"
        )

    def show_testing_card(self, test_info: dict):
        """Display a testing status card in the chat."""
        import json
        safe_info = json.dumps(test_info)
        self._view.page().runJavaScript(
            f"if(window.showTestingCard) window.showTestingCard({safe_info});"
        )

    def show_test_results(self, results: dict):
        """Display test results in the chat."""
        import json
        safe_results = json.dumps(results)
        self._view.page().runJavaScript(
            f"if(window.showTestResults) window.showTestResults({safe_results});"
        )

    def _apply_project_info(self, name: str, path: str, chats_json: str = "[]"):
        import json
        safe_name = json.dumps(name)
        safe_path = json.dumps(path)
        log.info(f'?? set_project_info called: name={name}, path={path}, chats_json length={len(chats_json)}')
        # Ensure chats_json is passed correctly to JS (avoid double-stringified data)
        try:
            # Parse it first if it's a string, then JSON-ify properly for the JS call
            chats_data = json.loads(chats_json) if isinstance(chats_json, str) else chats_json
            safe_chats = json.dumps(chats_data)
            log.info(f'? Parsed {len(chats_data) if isinstance(chats_data, list) else 0} chats for JS')
        except Exception as e:
            log.warning(f'Failed to parse chats_json: {e}')
            safe_chats = "[]"
        js_code = (
            f"if(window.trySetProjectInfoWithChats) window.trySetProjectInfoWithChats({safe_name}, {safe_path}, {safe_chats}); "
            f"else if(window.setProjectInfoWithChats) window.setProjectInfoWithChats({safe_name}, {safe_path}, {safe_chats}); "
            f"else if(window.trySetProjectInfo) window.trySetProjectInfo({safe_name}, {safe_path}); "
            f"else window._pendingProjectInfoWithChats = {{ name: {safe_name}, path: {safe_path}, chatsJson: {safe_chats} }};"
        )
        log.info(f'?? Calling JavaScript: trySetProjectInfoWithChats(...)')
        self._view.page().runJavaScript(js_code)

        # Retry once after the webview is fully initialized
        QTimer.singleShot(800, lambda: self._view.page().runJavaScript(js_code))

    def clear_chat(self):
        """Clear the chat window."""
        self._view.page().runJavaScript("if(window.clearChat) window.clearChat();")

    def set_project_info(self, name: str, path: str, chats_json: str = "[]"):
        """Initialize chat with project details and history."""
        # Always remember latest project info in case the page isn't loaded yet
        self._pending_project_info = (name, path, chats_json)
        self._current_project_path = path
        if not getattr(self, '_page_loaded', False):
            log.info('Chat page not loaded yet; deferring project info')
            return
        self._apply_project_info(name, path, chats_json)

    def load_chats_for_project(self, project_path: str) -> str:
        """
        Load all chat metadata for a specific project path.
        Returns: JSON string array of chat metadata or empty array.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            history = get_chat_history()
            conversations = history.get_conversations(project_path)
            
            log.info(f'ðŸ“¥ Found {len(conversations) if conversations else 0} conversations for project {project_path}')
            
            if not conversations:
                log.warning(f'No chats found in database for project {project_path}')
                return "[]"
            
            # Convert to format expected by JS
            result = []
            for conv in conversations:
                result.append({
                    'id': conv.get('conversation_id') or conv.get('id'),
                    'title': conv.get('title'),
                    'created_at': conv.get('created_at'),
                    'message_count': conv.get('message_count', 0),
                    'messages': [],  # Empty - lazy loaded
                    'loaded': False
                })
            
            json_result = json.dumps(result)
            log.info(f'âœ… Loaded {len(result)} chat(s) for project {project_path} ({len(json_result)} chars)')
            return json_result
            
        except Exception as e:
            log.error(f'âŒ Failed to load chats for project {project_path}: {e}')
            import traceback
            log.error(traceback.format_exc())
            return "[]"

    def on_file_edited_diff(self, path: str, original: str, new_content: str):
        """Called when the agent edits a file to show +/- diff line counts."""
        import difflib
        orig_lines = original.splitlines()
        new_lines  = new_content.splitlines()
        diff = list(difflib.ndiff(orig_lines, new_lines))
        added   = sum(1 for l in diff if l.startswith('+ '))
        removed = sum(1 for l in diff if l.startswith('- '))
        p = json.dumps(path)
        self._view.page().runJavaScript(f"if(window.addChangedFile) addChangedFile({p}, {added}, {removed}, 'M');")

    def emit_directory_tree(self, root_path: str, listing_text: str):
        """Send hierarchical tree data to JS for tree card rendering."""
        items = self._parse_listing(root_path, listing_text)
        root_js  = json.dumps(root_path)
        items_js = json.dumps(items)
        self._view.page().runJavaScript(f"if(window.showDirectoryTree) window.showDirectoryTree({root_js}, {items_js});")

    def _parse_listing(self, root_path: str, text: str) -> list:
        """Convert list_directory output to hierarchical tree structure."""
        import re
        lines = [l for l in text.split('\n') if l.strip()]
        items = []
        root = root_path.rstrip('/\\')
        sep = '\\' if '\\' in root else '/'
        parent_stack = [root]

        for i, line in enumerate(lines):
            leading = len(line) - len(line.lstrip())
            depth = leading // 2
            stripped = line.strip()
            if not stripped: continue

            is_dir = stripped.startswith('ðŸ“') or stripped.endswith('/')
            name = stripped
            for prefix in ['â”œâ”€â”€', 'â””â”€â”€', 'â”‚']:
                name = name.replace(prefix, '')
            name = name.lstrip('ðŸ“ðŸ“„').strip()

            size = ''
            desc = ''
            m = re.match(r'^(.*?)\s*\(([^)]+)\)\s*(?:-\s*(.+))?$', name)
            if m:
                name = m.group(1).strip().rstrip('/')
                size = m.group(2)
                desc = m.group(3) or ''
            else:
                name = name.rstrip('/')

            while len(parent_stack) > depth + 1:
                parent_stack.pop()
            current_path = sep.join(parent_stack) + sep + name

            is_last = True
            if i < len(lines) - 1:
                next_leading = len(lines[i + 1]) - len(lines[i + 1].lstrip())
                if (next_leading // 2) >= depth: is_last = False

            items.append({'name': name, 'path': current_path, 'size': size, 'description': desc, 'isDir': is_dir, 'isLast': is_last, 'depth': depth})
            if is_dir:
                if len(parent_stack) <= depth + 1: parent_stack.append(name)
                else: parent_stack[depth + 1] = name
        return items

    def emit_terminal_result(self, card_id: str, output: str, exit_code: int):
        """Update terminal card with result."""
        self._view.page().runJavaScript(f"if(window.setTerminalOutput) window.setTerminalOutput({json.dumps(card_id)}, {json.dumps(output[:3000])}, {exit_code});")

    def _ensure_terminal_backend(self):
        """Lazy initialization of terminal backend."""
        if self._pty_process is not None or self._terminal_process is not None: return
        shell = "powershell.exe" if platform.system() == "Windows" else "bash"
        try:
            import winpty
            import time
            from PyQt6.QtCore import Qt, QThread, pyqtSignal
            self._pty_process = winpty.PtyProcess.spawn(shell, dimensions=(24, 80), backend=winpty.Backend.WinPTY)
            class Reader(QThread):
                data = pyqtSignal(str)
                def __init__(self, pty):
                    super().__init__(); self.pty = pty; self._running = True
                def run(self):
                    while self._running and self.pty.isalive():
                        try:
                            d = self.pty.read(timeout=0.05)
                            if d: self.data.emit(d)
                        except: time.sleep(0.01)
                def stop(self): self._running = False; self.wait(500)
            self._terminal_reader = Reader(self._pty_process)
            def _emit_terminal_data(data):
                self._terminal_output_buffer += data
                if len(self._terminal_output_buffer) > 2048:
                    self._bridge.terminal_output.emit(self._terminal_output_buffer)
                    self._terminal_output_buffer = ""
            self._terminal_reader.data.connect(_emit_terminal_data, Qt.ConnectionType.QueuedConnection)
            self._terminal_reader.start()
        except Exception as e:
            log.warning(f"WinPTY not available ({e}), falling back to QProcess")
            self._terminal_process = QProcess(self)
            self._terminal_process.readyReadStandardOutput.connect(self._on_terminal_output)
            self._terminal_process.start(shell)

    def _on_terminal_output(self):
        """Handle output from terminal process."""
        if self._terminal_process:
            data = self._terminal_process.readAllStandardOutput().data().decode(errors="replace")
            if data: self._bridge.terminal_output.emit(data)

    # â”€â”€ CODE COMPLETION HANDLERS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    def _on_code_completion_requested(self, data: dict):
        """Handle code completion request from bridge."""
        log.info(f"Code completion requested for {data.get('language', 'python')}")
        # Forward to main window for processing
        self._view.page().runJavaScript(f"window.showCompletionIndicator && window.showCompletionIndicator();")
    
    def _on_code_completion_selected(self, data: dict):
        """Handle code completion selection from bridge."""
        log.info(f"Code completion selected: index {data.get('index', 0)}")
        # Forward to main window
    
    def _on_code_completion_accepted(self, data: dict):
        """Handle code completion acceptance from bridge."""
        log.info(f"Code completion accepted: {data.get('requestId', 'unknown')}")
        # Hide indicator
        self._view.page().runJavaScript(f"window.hideCompletionIndicator && window.hideCompletionIndicator();")
    
    def _on_code_completion_dismissed(self, data: dict):
        """Handle code completion dismissal from bridge."""
        log.info(f"Code completion dismissed: {data.get('requestId', 'unknown')}")
        # Hide indicator and popup
        self._view.page().runJavaScript(f"window.hideCompletionIndicator && window.hideCompletionIndicator();")
        self._view.page().runJavaScript(f"window.dismissCodeCompletion && window.dismissCodeCompletion();")
    
    def show_code_completion_popup(self, completions: list, request_id: str):
        """Show code completion popup in chat UI."""
        import json
        completions_json = json.dumps(completions)
        js_code = f"""
            if (window.showCodeCompletionPopup) {{
                window.showCodeCompletionPopup({completions_json}, '{request_id}');
            }}
        """
        self._view.page().runJavaScript(js_code)
    
    def show_code_completion_card(self, completion_data: dict):
        """Show code completion card in chat."""
        import json
        data_json = json.dumps(completion_data)
        js_code = f"""
            if (window.showCodeCompletionCard) {{
                window.showCodeCompletionCard({data_json});
            }}
        """
        self._view.page().runJavaScript(js_code)
    
    def hide_code_completion(self):
        """Hide code completion popup."""
        self._view.page().runJavaScript("window.dismissCodeCompletion && window.dismissCodeCompletion();")
    
    # â”€â”€ INLINE DIFF VIEWER HANDLERS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    def _on_diff_line_accepted(self, data: dict):
        """Handle diff line acceptance from bridge."""
        log.info(f"Diff line accepted: {data.get('filePath')}:{data.get('lineNumber')}")
        # Forward to main window for processing
        # This allows per-line acceptance in the future
        self.accept_file_edit_requested.emit(data.get('filePath'))
    
    def _on_diff_line_rejected(self, data: dict):
        """Handle diff line rejection from bridge."""
        log.info(f"Diff line rejected: {data.get('filePath')}:{data.get('lineNumber')}")
        # Forward to main window for processing
        # This allows per-line rejection in the future
        self.reject_file_edit_requested.emit(data.get('filePath'))
    
    def _on_diff_line_commented(self, data: dict):
        """Handle diff line comment from bridge."""
        log.info(f"Diff line commented: {data.get('filePath')}:{data.get('lineNumber')}")
        # Store comment for future use
        # TODO: Implement comment storage and display
    
    def show_inline_diff(self, diff_data: dict):
        """Show inline diff in chat UI."""
        import json
        data_json = json.dumps(diff_data)
        js_code = f"""
            if (window.showInlineDiff) {{
                window.showInlineDiff({data_json});
            }}
        """
        self._view.page().runJavaScript(js_code)

    def closeEvent(self, event):
        """Cleanup on close."""
        self._cleanup_vision_thread()
        if self._pty_process:
            self._pty_process.terminate()
        if self._terminal_process:
            self._terminal_process.terminate()
        super().closeEvent(event)











