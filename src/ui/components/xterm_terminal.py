import os
import sys
import platform
import shutil
from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QComboBox
)
from PyQt6.QtCore import Qt, QProcess, QProcessEnvironment, pyqtSignal, QTimer, QObject, pyqtSlot, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from src.utils.logger import get_logger
from .windows_terminal import PathResolverThread

log = get_logger("xterm_terminal")

# We will try to use pywinpty on Windows for true PTY support (ANSI, arrows, etc), 
# otherwise fallback to QProcess (which doesn't support interactive terminal apps like vim or python repl well)
try:
    import winpty
    WINPTY_AVAILABLE = True
except ImportError:
    WINPTY_AVAILABLE = False
    log.warning("winpty not available. Interactive terminal apps may not work correctly.")


class TerminalBridge(QObject):
    """Bridge object that connects JS xterm events with Python."""
    send_output = pyqtSignal(str)   # Python -> JS (write to terminal)
    update_theme = pyqtSignal(bool) # Python -> JS (update colors)
    
    # Signals for when JS sends data to Python
    data_received = pyqtSignal(str)
    resize_requested = pyqtSignal(int, int)
    ready_received = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)

    @pyqtSlot(str)
    def receive_input(self, data):
        """Called by JS when user types in xterm.js"""
        self.data_received.emit(data)

    @pyqtSlot(str)
    def copy_to_clipboard(self, text):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    @pyqtSlot()
    def paste_from_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text()
        if text:
            # Emit the pasted text as if the user typed it
            self.data_received.emit(text)
        
    @pyqtSlot(int, int)
    def resize(self, cols, rows):
        """Called by JS when terminal resizes"""
        self.resize_requested.emit(cols, rows)
        
    @pyqtSlot()
    def ready(self):
        """Called by JS when xterm is fully loaded"""
        self.ready_received.emit()


class XTermWidget(QWidget):
    """
    A true VT100/ANSI compatible terminal powered by xterm.js and QWebEngineView.
    Provides an exact VS Code terminal experience in PyQt.
    """
    
    command_executed = pyqtSignal(str, int)  # command, exit_code
    terminal_output_received = pyqtSignal(str) # For AI to listen to
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cwd = os.getcwd()
        self._is_dark = True
        self._process = None # QProcess fallback
        self._pty_process = None # winpty
        self._terminal_buffer = [] # Store last lines for AI
        self._max_buffer = 1000
        
        # Buffer to hold text if xterm.js isn't loaded yet
        self._output_buffer = ""
        self._is_ready = False
        
        self._build_ui()
        self._update_header_style()
        self._shell_started = False
        
        # For QProcess delayed rendering
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_buffers)
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header with shell selector (Borrowed from WindowsTerminalWidget)
        self._header = QWidget()
        self._header.setFixedHeight(35)
        hlay = QHBoxLayout(self._header)
        hlay.setContentsMargins(10, 0, 8, 0)
        
        self._shell_combo = QComboBox()
        self._shell_combo.addItems(["PowerShell", "Command Prompt", "Git Bash"])
        if not WINPTY_AVAILABLE:
            self._shell_combo.setToolTip("Install 'pywinpty' for better interacting shell support.")
        self._shell_combo.currentTextChanged.connect(self._on_shell_changed)
        self._shell_combo.setFixedWidth(120)
        
        self._shell_label = QLabel("Shell:")
        hlay.addWidget(self._shell_label)
        hlay.addWidget(self._shell_combo)
        
        self._title_label = QLabel("⚡ Terminal")
        self._title_label.setStyleSheet("font-size:12px; font-weight:bold; margin-left: 20px;")
        hlay.addWidget(self._title_label)
        hlay.addStretch()
        
        self._kill_btn = QPushButton("✕")
        self._kill_btn.setFixedSize(30, 22)
        self._kill_btn.setToolTip("Kill Process")
        self._kill_btn.clicked.connect(self._kill_process)
        hlay.addWidget(self._kill_btn)
        
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedSize(50, 22)
        self._clear_btn.setToolTip("Clear terminal")
        self._clear_btn.clicked.connect(self._clear)
        hlay.addWidget(self._clear_btn)
        
        self._restart_btn = QPushButton("↺")
        self._restart_btn.setFixedSize(30, 22)
        self._restart_btn.setToolTip("Restart terminal")
        self._restart_btn.clicked.connect(self._restart)
        hlay.addWidget(self._restart_btn)
        
        layout.addWidget(self._header)
        
        # Web View for xterm.js
        self._webview = QWebEngineView()
        
        # Disable web view context menu and other browser features
        settings = self._webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        
        self._webview.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        
        # Setup the QWebChannel Bridge
        self._bridge = TerminalBridge(self)
        self._bridge.data_received.connect(self._on_js_input)
        self._bridge.resize_requested.connect(self._on_js_resize)
        self._bridge.ready_received.connect(self._on_js_ready)
        
        self._channel = QWebChannel(self)
        self._channel.registerObject("pyTerminal", self._bridge)
        self._webview.page().setWebChannel(self._channel)
        
        # Load terminal.html
        html_path = os.path.join(os.path.dirname(__file__), "terminal.html")
        self._webview.setUrl(QUrl.fromLocalFile(html_path))
        
        layout.addWidget(self._webview)
        
    def _on_js_ready(self):
        """Called when xterm.js is initialized and ready in the browser."""
        self._is_ready = True
        self._bridge.update_theme.emit(self._is_dark)
        
        if self._output_buffer:
            self._bridge.send_output.emit(self._output_buffer)
            self._output_buffer = ""
            
    def _on_js_input(self, data: str):
        """Called when user types in xterm.js"""
        if self._pty_process:
            try:
                self._pty_process.write(data)
            except Exception as e:
                log.error(f"Failed to write to pty: {e}")
        elif self._process and self._process.state() == QProcess.ProcessState.Running:
            # QProcess isn't a real PTY, so it expects full lines ending in \n. 
            # Interactive chars won't work well, but we send them anyway.
            self._process.write(data.encode('utf-8'))
            
    def _on_js_resize(self, cols: int, rows: int):
        """Called when xterm.js resizes its grid"""
        if self._pty_process:
            try:
                self._pty_process.setwinsize(rows, cols)
            except Exception as e:
                log.error(f"Failed to resize pty: {e}")
                
    def _write_to_terminal(self, text: str):
        """Send text to xterm.js to be rendered on screen."""
        # Store in buffer for AI feedback (clean ANSI codes first)
        clean_text = self._clean_ansi(text)
        if clean_text:
            self._terminal_buffer.extend(clean_text.splitlines())
            if len(self._terminal_buffer) > self._max_buffer:
                self._terminal_buffer = self._terminal_buffer[-self._max_buffer:]
            self.terminal_output_received.emit(clean_text)

        if self._is_ready:
            self._bridge.send_output.emit(text)
        else:
            self._output_buffer += text

    def _clean_ansi(self, text: str) -> str:
        """Remove ANSI escape sequences."""
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def get_last_output(self, lines: int = 50) -> str:
        """Return the last N lines of terminal output."""
        return "\n".join(self._terminal_buffer[-lines:])
            
    def _start_shell(self):
        """Resolve PATH and start the backend process."""
        self._write_to_terminal("\r\n\x1b[90m[ Resolving terminal environment... ]\x1b[0m\r\n")
        
        self._path_thread = PathResolverThread(QProcessEnvironment.systemEnvironment().value("PATH", ""))
        self._path_thread.resolved.connect(self._on_path_resolved)
        self._path_thread.start()
        
    def _on_path_resolved(self, resolved_path: str):
        self._write_to_terminal("\x1bc") # xterm.js reset sequence (clears screen)
        
        env = dict(os.environ)
        env["PATH"] = resolved_path
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        
        shell = self._shell_combo.currentText()
        
        if WINPTY_AVAILABLE:
            # --- START WINPTY (REAL TERMINAL) ---
            try:
                cmd = "powershell.exe -NoLogo"
                if shell == "Command Prompt":
                    cmd = "cmd.exe"
                elif shell == "Git Bash":
                    # Locate git bash
                    bash_path = shutil.which("bash.exe")
                    git_bin = None
                    if bash_path and "Git" in bash_path:
                        git_bin = os.path.dirname(bash_path)
                    else:
                        potential_paths = [
                            r"C:\Program Files\Git\bin", 
                            r"C:\Program Files\Git\usr\bin",
                            r"C:\Program Files (x86)\Git\bin",
                            os.path.expandvars(r"%LocalAppData%\Programs\Git\bin"),
                            os.path.expandvars(r"%LocalAppData%\Programs\Git\usr\bin")
                        ]
                        for p in potential_paths:
                            if os.path.exists(os.path.join(p, "bash.exe")):
                                git_bin = p
                                break
                    
                    if git_bin:
                        env["PATH"] = git_bin + os.pathsep + env.get("PATH", "")
                        cmd = "bash.exe --login -i"
                    else:
                        cmd = "bash.exe --login -i" # Fallback and hope it is in PATH
                            
                self._pty_process = winpty.PtyProcess.spawn(
                    cmd,
                    cwd=self._cwd,
                    env=env,
                    dimensions=(24, 80) # Default size, will be resized by JS
                )
                
                # Start background thread to read from PTY
                from PyQt6.QtCore import QThread
                class WinptyReader(QThread):
                    data_received = pyqtSignal(str)
                    def __init__(self, pty):
                        super().__init__()
                        self.pty = pty
                        self.running = True
                    def run(self):
                        while self.running and self.pty.isalive():
                            try:
                                data = self.pty.read()
                                if data:
                                    self.data_received.emit(data)
                            except EOFError:
                                break
                            except Exception:
                                pass
                                
                self._pty_reader = WinptyReader(self._pty_process)
                self._pty_reader.data_received.connect(self._write_to_terminal)
                self._pty_reader.start()
                
            except Exception as e:
                self._write_to_terminal(f"\r\n\x1b[31m[ Failed to start winpty: {e} ]\x1b[0m\r\n")
                log.error(f"Winpty Error: {e}")
            
        else:
            # --- START QPROCESS (FALLBACK) ---
            # QProcess does not provide a true PTY, meaning no interactive REPLs (like python or node)
            # and no rich CLI apps (like vim, nano, htop).
            self._write_to_terminal("\r\n\x1b[33m[ Warning: 'pywinpty' not installed. Interactive terminal apps and REPLs may not function correctly. ]\x1b[0m\r\n")
            
            self._process = QProcess(self)
            self._process.setWorkingDirectory(self._cwd)
            
            qenv = QProcessEnvironment.systemEnvironment()
            qenv.insert("PATH", resolved_path)
            qenv.insert("TERM", "xterm-256color")
            self._process.setProcessEnvironment(qenv)
            
            self._process.readyReadStandardOutput.connect(self._on_stdout)
            self._process.readyReadStandardError.connect(self._on_stderr)
            self._process.finished.connect(self._on_process_finished)
            
            if shell == "PowerShell":
                self._process.start("powershell.exe", ["-NoLogo"])
            elif shell == "Command Prompt":
                self._process.start("cmd.exe", ["/K", "prompt", "$P$G"])
            elif shell == "Git Bash":
                 bash_path = shutil.which("bash.exe")
                 if bash_path and "Git" in bash_path:
                     self._process.start(bash_path, ["--login", "-i"])
                 else:
                     found = False
                     paths = [
                         r"C:\Program Files\Git\bin\bash.exe", 
                         r"C:\Program Files\Git\usr\bin\bash.exe",
                         r"C:\Program Files (x86)\Git\bin\bash.exe",
                         os.path.expandvars(r"%LocalAppData%\Programs\Git\bin\bash.exe")
                     ]
                     for p in paths:
                         if os.path.exists(p):
                             self._process.start(p, ["--login", "-i"])
                             found = True
                             break
                     if not found:
                         self._process.start("bash.exe", ["--login", "-i"])
                         
            self._render_timer.start(30)
            
    def showEvent(self, event):
        super().showEvent(event)
        if not self._shell_started:
            self._shell_started = True
            QTimer.singleShot(200, self._start_shell)
            
    def _on_stdout(self):
        if self._process:
            self._stdout_buffer.extend(self._process.readAllStandardOutput().data())
            
    def _on_stderr(self):
        if self._process:
            self._stderr_buffer.extend(self._process.readAllStandardError().data())
            
    def _render_buffers(self):
        """Render any buffered stdout/stderr text for QProcess."""
        if self._stdout_buffer:
            text = self._stdout_buffer.decode("utf-8", errors="replace")
            # Convert simple \n to \r\n for xterm.js if needed
            if "\n" in text and "\r\n" not in text:
                text = text.replace("\n", "\r\n")
            self._stdout_buffer.clear()
            self._write_to_terminal(text)
            
        if self._stderr_buffer:
            text = self._stderr_buffer.decode("utf-8", errors="replace")
            if "\n" in text and "\r\n" not in text:
                text = text.replace("\n", "\r\n")
            self._stderr_buffer.clear()
            # Wrap stderr in ansi red
            self._write_to_terminal(f"\x1b[31m{text}\x1b[0m")
            
    def _on_process_finished(self):
        self._write_to_terminal("\r\n\x1b[90m[ Process exited ]\x1b[0m\r\n")
        
    def _clear(self):
        self._write_to_terminal("\x1bc") # xterm.js reset sequence (clears screen)
        # Re-emit Enter to get the prompt back
        if self._pty_process:
            self._pty_process.write("\r\n")
        elif self._process:
            self._process.write(b"\r\n")
            
    def _restart(self):
        self._kill_process()
        self._clear()
        self._start_shell()
        
    def _kill_process(self):
        if self._pty_process:
            try:
                if hasattr(self, '_pty_reader'):
                    self._pty_reader.running = False
                self._pty_process.terminate()
            except Exception:
                pass
            self._pty_process = None
            
        if self._process:
            try:
                self._process.finished.disconnect()
                self._process.readyReadStandardOutput.disconnect()
                self._process.readyReadStandardError.disconnect()
                self._process.terminate()
                self._process.waitForFinished(1000)
                if self._process.state() != QProcess.ProcessState.NotRunning:
                    self._process.kill()
                    self._process.waitForFinished(1000)
            except Exception:
                pass
            self._process = None
            
    def _on_shell_changed(self, shell_name: str):
        if self._shell_started:
            self._restart()
            
    def execute_command(self, cmd: str):
        if self._pty_process:
            self._pty_process.write(f"{cmd}\r\n")
        elif self._process and self._process.state() == QProcess.ProcessState.Running:
            self._process.write(f"{cmd}\r\n".encode())
            
    def set_cwd(self, path: str):
        self._cwd = path
        # Try to change dir dynamically without restarting if possible
        shell = self._shell_combo.currentText()
        if shell == "PowerShell":
             self.execute_command(f'Set-Location -Path "{path}"')
        elif shell == "Command Prompt":
             # In CMD, we need /D to change drive as well
             self.execute_command(f'cd /D "{path}"')
        else: # Git Bash or others
             # Git Bash uses Unix-style paths essentially, but usually handles quoted Windows paths too
             self.execute_command(f'cd "{path}"')
             
    def activate_virtual_env(self, venv_path: str):
        if sys.platform == "win32":
            activate_script = os.path.join(venv_path, "Scripts", "Activate.ps1")
            if os.path.exists(activate_script):
                self.execute_command(f"& '{activate_script}'")
        else:
            activate_script = os.path.join(venv_path, "bin", "activate")
            if os.path.exists(activate_script):
                self.execute_command(f"source {activate_script}")
                
    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
        self._update_header_style()
        if self._is_ready:
            self._bridge.update_theme.emit(is_dark)
            
    def _update_header_style(self):
        if self._is_dark:
            self._header.setStyleSheet("""
                QWidget {
                    background-color: #2d2d30;
                    border-bottom: 1px solid #3e3e42;
                }
                QLabel { color: #cccccc; font-size: 12px; }
                QPushButton {
                    background-color: #3c3c3c; color: #cccccc;
                    border: 1px solid #3e3e42; border-radius: 3px; padding: 2px 8px;
                }
                QPushButton:hover { background-color: #4c4c4c; }
                QComboBox {
                    background-color: #3c3c3c; color: #cccccc;
                    border: 1px solid #3e3e42; border-radius: 3px; padding: 2px 8px;
                }
                QComboBox::drop-down { border: none; }
                QComboBox QAbstractItemView {
                    background-color: #3c3c3c; color: #cccccc;
                    selection-background-color: #094771;
                }
            """)
        else:
            self._header.setStyleSheet("""
                QWidget {
                    background-color: #f3f3f3;
                    border-bottom: 1px solid #e0e0e0;
                }
                QLabel { color: #333333; font-size: 12px; }
                QPushButton {
                    background-color: #ffffff; color: #333333;
                    border: 1px solid #d0d0d0; border-radius: 3px; padding: 2px 8px;
                }
                QPushButton:hover { background-color: #e0e0e0; }
                QComboBox {
                    background-color: #ffffff; color: #333333;
                    border: 1px solid #d0d0d0; border-radius: 3px; padding: 2px 8px;
                }
                QComboBox::drop-down { border: none; }
                QComboBox QAbstractItemView {
                    background-color: #ffffff; color: #333333;
                    selection-background-color: #cce5ff;
                }
            """)
            
    def closeEvent(self, event):
        self._kill_process()
        super().closeEvent(event)
