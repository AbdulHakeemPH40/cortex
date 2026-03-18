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
        self._build_ui()
        self._start_terminal_backend()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Web View
        self._view = QWebEngineView()
        
        # Enable standard context menu and selection features
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.JavascriptCanAccessClipboard, True
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
        self._channel.registerObject("bridge", self._bridge)

        self._view.page().setWebChannel(self._channel)
        
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
        
    def on_chunk(self, chunk):
        """Handle AI streaming chunk."""
        # Use JSON encoding to properly escape for JavaScript
        safe_chunk = json.dumps(chunk)
        self._view.page().runJavaScript(f"if(window.onChunk) window.onChunk({safe_chunk});")
        
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
        """Show tool activity card in the chat UI."""
        safe_info = json.dumps(info)
        self._view.page().runJavaScript(
            f"if(window.showToolActivity) window.showToolActivity('{tool_type}', {safe_info}, '{status}');"
        )
    
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

    def set_code_context_callback(self, callback):
        self._get_code_context = callback

    def set_project_info(self, name: str, path: str = ""):
        """Update the project indicator in the chat header."""
        safe_name = name.replace("'", "\\'").replace("\\", "\\\\")
        safe_path = path.replace("'", "\\'").replace("\\", "\\\\")
        self._view.page().runJavaScript(f"if(window.setProjectInfo) window.setProjectInfo('{safe_name}', '{safe_path}');")

    def clear_project_info(self):
        """Hide the project indicator."""
        self._view.page().runJavaScript("if(window.clearProjectInfo) window.clearProjectInfo();")

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

