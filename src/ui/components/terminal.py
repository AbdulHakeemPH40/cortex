"""
Terminal Widget — an embedded pseudo-terminal using QProcess.
"""

import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QLineEdit, QPushButton, QLabel
from PyQt6.QtCore import Qt, QProcess, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat
from src.utils.logger import get_logger

log = get_logger("terminal")

# ANSI simple color map
ANSI_COLORS = {
    "30": "#1e1e1e", "31": "#f48771", "32": "#4ec9b0",
    "33": "#d7ba7d", "34": "#569cd6", "35": "#c586c0",
    "36": "#9cdcfe", "37": "#d4d4d4",
}


class TerminalWidget(QWidget):
    """Simple embedded terminal using QProcess."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: QProcess | None = None
        self._cwd = os.path.expanduser("~")
        
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_buffers)
        self._render_timer.start(30)
        
        self._build_ui()
        self._start_shell()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet("background:#2d2d30; border-bottom:1px solid #3e3e42;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(10, 0, 8, 0)
        lbl = QLabel("⚡ Terminal")
        lbl.setStyleSheet("font-size:12px; font-weight:bold;")
        hlay.addWidget(lbl)
        hlay.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(50, 22)
        clear_btn.setStyleSheet("font-size:11px;")
        clear_btn.clicked.connect(self._clear)
        hlay.addWidget(clear_btn)
        restart_btn = QPushButton("↺")
        restart_btn.setFixedSize(30, 22)
        restart_btn.setStyleSheet("font-size:13px;")
        restart_btn.setToolTip("Restart terminal")
        restart_btn.clicked.connect(self._restart)
        hlay.addWidget(restart_btn)
        layout.addWidget(header)

        # Output display
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(2000)
        font = QFont("Courier New", 12)
        font.setFixedPitch(True)
        self._output.setFont(font)
        self._output.setStyleSheet("background:#0c0c0c; color:#cccccc; border:none; padding:4px;")
        layout.addWidget(self._output)

        # Input row
        input_row = QWidget()
        input_row.setFixedHeight(32)
        input_row.setStyleSheet("background:#0c0c0c; border-top:1px solid #3e3e42;")
        ilay = QHBoxLayout(input_row)
        ilay.setContentsMargins(8, 2, 8, 2)
        ilay.setSpacing(6)

        self._prompt_label = QLabel("$")
        self._prompt_label.setStyleSheet("color:#4ec9b0; font-family:'Courier New'; font-size:12px;")
        ilay.addWidget(self._prompt_label)

        self._input = QLineEdit()
        self._input.setStyleSheet("background:transparent; color:#cccccc; border:none; "
                                   "font-family:'Courier New'; font-size:12px;")
        self._input.returnPressed.connect(self._send_command)
        ilay.addWidget(self._input)
        layout.addWidget(input_row)

        # Command history
        self._history: list[str] = []
        self._history_idx = -1

    def _start_shell(self):
        """Start PowerShell or cmd."""
        self._process = QProcess(self)
        self._process.setWorkingDirectory(self._cwd)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_process_finished)

        # Choose shell
        import platform
        if platform.system() == "Windows":
            shell = "powershell.exe"
            args = ["-NoLogo", "-NonInteractive", "-Command", "-"]
        else:
            shell = "/bin/bash"
            args = ["--norc", "-i"]

        self._process.start(shell, args)
        if not self._process.waitForStarted(3000):
            self._append("[ Failed to start shell. Using command mode. ]\n", "#f48771")

    def _send_command(self):
        cmd = self._input.text().strip()
        if not cmd:
            return
        self._history.insert(0, cmd)
        self._history_idx = -1
        self._append(f"$ {cmd}\n", "#4ec9b0")
        self._input.clear()

        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self._process.write((cmd + "\n").encode())
        else:
            # Fallback: run via Python subprocess and capture
            import subprocess
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    cwd=self._cwd, timeout=30
                )
                if result.stdout:
                    self._append(result.stdout, "#cccccc")
                if result.stderr:
                    self._append(result.stderr, "#f48771")
            except Exception as e:
                self._append(f"Error: {e}\n", "#f48771")

    def _on_stdout(self):
        if self._process:
            self._stdout_buffer.extend(self._process.readAllStandardOutput().data())

    def _on_stderr(self):
        if self._process:
            self._stderr_buffer.extend(self._process.readAllStandardError().data())

    def _render_buffers(self):
        if self._stdout_buffer:
            text = self._stdout_buffer.decode("utf-8", errors="replace")
            self._stdout_buffer.clear()
            self._safe_append(text, "#cccccc")
        if self._stderr_buffer:
            text = self._stderr_buffer.decode("utf-8", errors="replace")
            self._stderr_buffer.clear()
            self._safe_append(text, "#f48771")

    def _on_process_finished(self):
        self._safe_append("[ Process exited ]\n", "#858585")

    def _safe_append(self, text: str, color: str = "#cccccc"):
        """Append text safely — guards against deleted C++ widget on close."""
        try:
            self._append(text, color)
        except RuntimeError:
            pass  # Widget already destroyed, ignore silently

    def _append(self, text: str, color: str = "#cccccc"):
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _clear(self):
        self._output.clear()

    def _restart(self):
        if self._process:
            self._process.kill()
            self._process.waitForFinished(2000)
            self._process = None
        self._clear()
        self._start_shell()

    def closeEvent(self, event):
        """Kill shell process cleanly before widget is destroyed."""
        self._kill_process()
        super().closeEvent(event)

    def _kill_process(self):
        """Terminate the shell process and disconnect all signals."""
        if self._process:
            try:
                self._process.finished.disconnect()
                self._process.readyReadStandardOutput.disconnect()
                self._process.readyReadStandardError.disconnect()
                self._process.kill()
                self._process.waitForFinished(1000)
            except Exception:
                pass
            self._process = None

    def _send_command_direct(self, cmd: str):
        """Programmatically run a command (used by main window Run action)."""
        self._input.setText(cmd)
        self._send_command()

    def set_cwd(self, path: str):
        self._cwd = path
        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self._process.write(f"cd \"{path}\"\n".encode())

    def keyPressEvent(self, event):
        # Arrow up/down for history
        if event.key() == Qt.Key.Key_Up and self._history:
            self._history_idx = min(self._history_idx + 1, len(self._history) - 1)
            self._input.setText(self._history[self._history_idx])
        elif event.key() == Qt.Key.Key_Down:
            self._history_idx = max(self._history_idx - 1, -1)
            self._input.setText(self._history[self._history_idx] if self._history_idx >= 0 else "")
        else:
            super().keyPressEvent(event)
