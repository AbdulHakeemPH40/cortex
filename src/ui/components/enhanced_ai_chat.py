"""
Enhanced AI Chat Widget with Task Queue Integration
Provides progress tracking, completion status, and queue management
"""

import os
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QObject, pyqtSlot, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

from src.utils.logger import get_logger
from src.ai.enhanced_agent import get_enhanced_ai_agent, EnhancedAIAgent

log = get_logger("enhanced_ai_chat")


class EnhancedChatBridge(QObject):
    """Enhanced bridge for communication between JS and Python"""
    
    # Existing signals
    message_submitted = pyqtSignal(str)
    clear_chat_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    run_command_requested = pyqtSignal(str)
    proceed_requested = pyqtSignal()
    generate_plan_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    always_allow_changed = pyqtSignal(bool)
    
    # New signals for task management
    task_status_requested = pyqtSignal()
    cancel_task_requested = pyqtSignal(str)
    confirm_step_requested = pyqtSignal(str, bool)  # task_id, confirmed
    
    # Terminal Signals
    terminal_input = pyqtSignal(str)
    terminal_output = pyqtSignal(str)
    terminal_resize = pyqtSignal(int, int)
    
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
    
    # New slots for task management
    @pyqtSlot()
    def on_get_task_status(self):
        self.task_status_requested.emit()
    
    @pyqtSlot(str)
    def on_cancel_task(self, task_id):
        self.cancel_task_requested.emit(task_id)
    
    @pyqtSlot(str, bool)
    def on_confirm_step(self, task_id, confirmed):
        self.confirm_step_requested.emit(task_id, confirmed)


class EnhancedAIChatWidget(QWidget):
    """
    Enhanced AI chat widget with task queue integration
    
    Features:
    - Task progress visualization
    - Queue status display
    - Step-by-step progress tracking
    - Completion status
    - Stop/Pause/Resume functionality
    """
    
    message_sent = pyqtSignal(str, str)  # user_message, code_context
    run_command = pyqtSignal(str)
    stop_requested = pyqtSignal()
    proceed_requested = pyqtSignal()
    always_allow_changed = pyqtSignal(bool)
    generate_plan_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._is_dark = True
        self._get_code_context = None
        self._bridge = None
        self._ai_agent = None
        
        self._build_ui()
        self._setup_ai_agent()
    
    def _build_ui(self):
        """Build the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Web View
        self._view = QWebEngineView()
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.JavascriptCanAccessClipboard, True
        )
        
        # Setup WebChannel
        self._channel = QWebChannel()
        self._bridge = EnhancedChatBridge()
        self._setup_bridge_signals()
        self._channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        
        # Load HTML
        html_path = os.path.join(
            os.path.dirname(__file__), "..", "html", "ai_chat", "aichat.html"
        )
        self._view.setUrl(QUrl.fromLocalFile(os.path.abspath(html_path)))
        
        layout.addWidget(self._view)
    
    def _setup_bridge_signals(self):
        """Setup bridge signal connections"""
        # Existing connections
        self._bridge.message_submitted.connect(self._on_js_message)
        self._bridge.clear_chat_requested.connect(self.clear_chat)
        self._bridge.stop_requested.connect(self._on_stop_requested)
        self._bridge.run_command_requested.connect(self.run_command.emit)
        self._bridge.proceed_requested.connect(self.proceed_requested.emit)
        self._bridge.always_allow_changed.connect(self.always_allow_changed.emit)
        self._bridge.generate_plan_requested.connect(self.generate_plan_requested.emit)
        self._bridge.mode_changed.connect(self.mode_changed.emit)
        
        # New task management connections
        self._bridge.task_status_requested.connect(self._on_task_status_requested)
        self._bridge.cancel_task_requested.connect(self._on_cancel_task)
        self._bridge.confirm_step_requested.connect(self._on_confirm_step)
    
    def _setup_ai_agent(self):
        """Setup AI agent connections"""
        self._ai_agent = get_enhanced_ai_agent(self)
        
        # Connect to AI agent signals
        self._ai_agent.response_chunk.connect(self.on_chunk)
        self._ai_agent.response_complete.connect(self.on_complete)
        self._ai_agent.request_error.connect(self.on_error)
        self._ai_agent.file_generated.connect(self._on_file_generated)
        
        # Connect to new signals
        self._ai_agent.task_progress.connect(self._on_task_progress)
        self._ai_agent.task_step_completed.connect(self._on_task_step_completed)
        self._ai_agent.task_completed.connect(self._on_task_completed)
        self._ai_agent.task_failed.connect(self._on_task_failed)
        self._ai_agent.task_cancelled.connect(self._on_task_cancelled)
        self._ai_agent.queue_status_changed.connect(self._on_queue_status_changed)
        self._ai_agent.current_task_changed.connect(self._on_current_task_changed)
    
    def _on_js_message(self, text):
        """Handle message from JS"""
        context = ""
        if self._get_code_context:
            context = self._get_code_context()
        
        self.message_sent.emit(text, context)
        
        # Send to AI agent
        if self._ai_agent:
            self._ai_agent.chat(text, context)
    
    def _on_stop_requested(self):
        """Handle stop request"""
        self.stop_requested.emit()
        if self._ai_agent:
            self._ai_agent.stop_current_task(graceful=True)
    
    def on_chunk(self, chunk: str):
        """Handle AI streaming chunk"""
        # Escape for JS
        safe_chunk = chunk.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        self._view.page().runJavaScript(
            f"if(window.onChunk) window.onChunk('{safe_chunk}');"
        )
    
    def on_complete(self, full_text: str):
        """Handle AI completion"""
        self._view.page().runJavaScript("if(window.onComplete) window.onComplete();")
    
    def on_error(self, error: str):
        """Handle error"""
        safe_error = error.replace("'", "\\'")
        self._view.page().runJavaScript(
            f"if(window.appendMessage) window.appendMessage('❌ Error: {safe_error}', 'assistant', false);"
        )
    
    def clear_chat(self):
        """Clear chat"""
        self._view.page().runJavaScript(
            "const msg = document.getElementById('chatMessages'); if(msg) msg.innerHTML = '';"
        )
    
    def set_theme(self, is_dark: bool):
        """Update theme"""
        self._is_dark = is_dark
        self._view.page().runJavaScript(
            f"if(window.setTheme) window.setTheme({str(is_dark).lower()});"
        )
    
    def focus_input(self):
        """Focus the input field"""
        self._view.page().runJavaScript(
            "const input = document.getElementById('chatInput'); if(input) input.focus();"
        )
    
    def add_system_message(self, text: str):
        """Add a system message"""
        safe_text = text.replace("'", "\\'")
        self._view.page().runJavaScript(
            f"if(window.appendMessage) window.appendMessage('{safe_text}', 'assistant', false);"
        )
    
    def set_code_context_callback(self, callback):
        """Set callback for getting code context"""
        self._get_code_context = callback
    
    def set_project_root(self, project_root: str):
        """Set project root for AI agent"""
        if self._ai_agent:
            self._ai_agent.set_project_root(project_root)
    
    def _on_file_generated(self, file_path: str):
        """Handle file generation"""
        # Emit signal or handle file opening
        log.info(f"File generated: {file_path}")
    
    # Task Management Handlers
    
    def _on_task_progress(self, task_id: str, step_name: str, percentage: int):
        """Handle task progress updates"""
        js_code = f"""
        if(window.onTaskProgress) {{
            window.onTaskProgress('{task_id}', '{step_name}', {percentage});
        }}
        """
        self._view.page().runJavaScript(js_code)
    
    def _on_task_step_completed(self, task_id: str, step_name: str, result: str):
        """Handle step completion"""
        safe_result = result.replace("'", "\\'")
        js_code = f"""
        if(window.onTaskStepCompleted) {{
            window.onTaskStepCompleted('{task_id}', '{step_name}', '{safe_result}');
        }}
        """
        self._view.page().runJavaScript(js_code)
    
    def _on_task_completed(self, task_id: str, summary: str):
        """Handle task completion"""
        safe_summary = summary.replace("'", "\\'").replace("\n", "\\n")
        js_code = f"""
        if(window.onTaskCompleted) {{
            window.onTaskCompleted('{task_id}', '{safe_summary}');
        }}
        """
        self._view.page().runJavaScript(js_code)
    
    def _on_task_failed(self, task_id: str, error: str):
        """Handle task failure"""
        safe_error = error.replace("'", "\\'")
        js_code = f"""
        if(window.onTaskFailed) {{
            window.onTaskFailed('{task_id}', '{safe_error}');
        }}
        """
        self._view.page().runJavaScript(js_code)
    
    def _on_task_cancelled(self, task_id: str):
        """Handle task cancellation"""
        js_code = f"""
        if(window.onTaskCancelled) {{
            window.onTaskCancelled('{task_id}');
        }}
        """
        self._view.page().runJavaScript(js_code)
    
    def _on_queue_status_changed(self, queue_length: int):
        """Handle queue status changes"""
        js_code = f"""
        if(window.onQueueStatusChanged) {{
            window.onQueueStatusChanged({queue_length});
        }}
        """
        self._view.page().runJavaScript(js_code)
    
    def _on_current_task_changed(self, task_id: str):
        """Handle current task changes"""
        safe_id = task_id or ""
        js_code = f"""
        if(window.onCurrentTaskChanged) {{
            window.onCurrentTaskChanged('{safe_id}');
        }}
        """
        self._view.page().runJavaScript(js_code)
    
    def _on_task_status_requested(self):
        """Handle task status request from UI"""
        if self._ai_agent:
            status = self._ai_agent.get_queue_status()
            # Send status to UI
            import json
            status_json = json.dumps(status)
            js_code = f"""
            if(window.updateTaskStatus) {{
                window.updateTaskStatus({status_json});
            }}
            """
            self._view.page().runJavaScript(js_code)
    
    def _on_cancel_task(self, task_id: str):
        """Handle task cancellation request"""
        if self._ai_agent:
            self._ai_agent._task_queue.cancel_task(task_id)
    
    def _on_confirm_step(self, task_id: str, confirmed: bool):
        """Handle step confirmation"""
        if self._ai_agent:
            task = self._ai_agent._task_queue.get_task(task_id)
            if task and task.current_step:
                task.current_step.confirmed = confirmed
                if confirmed:
                    # Continue execution
                    self._ai_agent._execute_task_step(task)
                else:
                    # Cancel the task
                    self._ai_agent._task_queue.cancel_task(task_id)
    
    def trigger_project_warmup(self):
        """Trigger project warmup manually"""
        if self._ai_agent:
            self._ai_agent._handle_project_warmup()
    
    def is_busy(self) -> bool:
        """Check if agent is busy"""
        if self._ai_agent:
            return self._ai_agent.is_busy()
        return False
