"""
Advanced Terminal with Tabs, Profiles, and ANSI Colors for Cortex AI Agent IDE
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QLineEdit, 
    QPushButton, QLabel, QTabWidget, QComboBox, QMenu, QInputDialog,
    QMessageBox, QSplitter, QFrame
)
from PyQt6.QtCore import Qt, QProcess, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat, QAction
from typing import Dict, List, Optional
import re
import os
from dataclasses import dataclass


@dataclass
class TerminalProfile:
    """Terminal profile configuration."""
    name: str
    shell: str
    shell_args: List[str]
    font_family: str
    font_size: int
    background_color: str
    text_color: str
    cursor_style: str  # 'block', 'line', 'bar'


# ANSI color codes
ANSI_COLORS = {
    # Standard colors (30-37, 40-47)
    '30': '#000000', '31': '#cd3131', '32': '#0dbc79', '33': '#e5e510',
    '34': '#2472c8', '35': '#bc3fbc', '36': '#11a8cd', '37': '#e5e5e5',
    # Bright colors (90-97, 100-107)
    '90': '#666666', '91': '#f14c4c', '92': '#23d18b', '93': '#f5f543',
    '94': '#3b8eea', '95': '#d670d6', '96': '#29b8db', '97': '#ffffff',
    # Background colors
    '40': '#000000', '41': '#cd3131', '42': '#0dbc79', '43': '#e5e510',
    '44': '#2472c8', '45': '#bc3fbc', '46': '#11a8cd', '47': '#e5e5e5',
}


def parse_ansi(text: str) -> List[tuple]:
    """Parse ANSI escape sequences and return list of (text, format_dict) tuples."""
    result = []
    current_format = {
        'fg': None,
        'bg': None,
        'bold': False,
        'italic': False,
        'underline': False
    }
    
    # Pattern to match ANSI escape sequences
    ansi_pattern = re.compile(r'\x1b\[([0-9;]*)m')
    
    pos = 0
    for match in ansi_pattern.finditer(text):
        # Add text before this escape sequence
        if match.start() > pos:
            result.append((text[pos:match.start()], dict(current_format)))
        
        # Parse the escape sequence
        codes = match.group(1).split(';')
        
        for code in codes:
            if code == '':
                code = '0'
            try:
                code = int(code)
            except:
                continue
                
            if code == 0:  # Reset
                current_format = {
                    'fg': None, 'bg': None,
                    'bold': False, 'italic': False, 'underline': False
                }
            elif code == 1:  # Bold
                current_format['bold'] = True
            elif code == 3:  # Italic
                current_format['italic'] = True
            elif code == 4:  # Underline
                current_format['underline'] = True
            elif 30 <= code <= 37:  # Foreground color
                current_format['fg'] = ANSI_COLORS.get(str(code))
            elif 40 <= code <= 47:  # Background color
                current_format['bg'] = ANSI_COLORS.get(str(code))
            elif 90 <= code <= 97:  # Bright foreground
                current_format['fg'] = ANSI_COLORS.get(str(code))
            elif 100 <= code <= 107:  # Bright background
                current_format['bg'] = ANSI_COLORS.get(str(code))
        
        pos = match.end()
    
    # Add remaining text
    if pos < len(text):
        result.append((text[pos:], dict(current_format)))
    
    return result


class TerminalTab(QWidget):
    """Individual terminal tab."""
    
    closed = pyqtSignal(object)  # Emits self
    title_changed = pyqtSignal(str)
    
    def __init__(self, profile: TerminalProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.process: Optional[QProcess] = None
        self.cwd = os.path.expanduser("~")
        self.history: List[str] = []
        self.history_idx = -1
        self._build_ui()
        self._start_shell()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Terminal output
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        font = QFont(self.profile.font_family, self.profile.font_size)
        font.setFixedPitch(True)
        self.output.setFont(font)
        self._update_colors()
        layout.addWidget(self.output)
        
        # Input row
        input_row = QWidget()
        input_row.setFixedHeight(30)
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(4, 2, 4, 2)
        input_layout.setSpacing(4)
        
        self.prompt_label = QLabel("$")
        self.prompt_label.setFont(font)
        input_layout.addWidget(self.prompt_label)
        
        self.input = QLineEdit()
        self.input.setFont(font)
        self.input.returnPressed.connect(self._send_command)
        input_layout.addWidget(self.input)
        
        layout.addWidget(input_row)
        
    def _update_colors(self):
        """Update terminal colors."""
        self.output.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {self.profile.background_color};
                color: {self.profile.text_color};
                border: none;
                padding: 4px;
            }}
        """)
        
    def _start_shell(self):
        """Start the shell process."""
        self.process = QProcess(self)
        self.process.setWorkingDirectory(self.cwd)
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        
        # Start shell with profile settings
        self.process.start(self.profile.shell, self.profile.shell_args)
        
        if not self.process.waitForStarted(3000):
            self._append_text("[Failed to start shell]\n", "#ff0000")
            
    def _send_command(self):
        """Send command to shell."""
        cmd = self.input.text().strip()
        if not cmd:
            return
            
        self.history.insert(0, cmd)
        self.history_idx = -1
        self._append_text(f"$ {cmd}\n", self.profile.text_color)
        self.input.clear()
        
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.write((cmd + "\n").encode())
            
    def _on_stdout(self):
        """Handle stdout with ANSI parsing."""
        if self.process:
            data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
            self._append_ansi_text(data)
            
    def _on_stderr(self):
        """Handle stderr."""
        if self.process:
            data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
            self._append_text(data, "#f48771")
            
    def _on_finished(self):
        """Handle process finish."""
        self._append_text("[Process exited]\n", "#858585")
        
    def _append_text(self, text: str, color: str = None):
        """Append plain text."""
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        fmt = QTextCharFormat()
        if color:
            fmt.setForeground(QColor(color))
        
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()
        
    def _append_ansi_text(self, text: str):
        """Append text with ANSI color codes."""
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        # Parse ANSI codes
        parts = parse_ansi(text)
        
        for part_text, fmt_dict in parts:
            fmt = QTextCharFormat()
            
            if fmt_dict['fg']:
                fmt.setForeground(QColor(fmt_dict['fg']))
            else:
                fmt.setForeground(QColor(self.profile.text_color))
                
            if fmt_dict['bg']:
                fmt.setBackground(QColor(fmt_dict['bg']))
                
            if fmt_dict['bold']:
                fmt.setFontWeight(700)
            if fmt_dict['italic']:
                fmt.setFontItalic(True)
            if fmt_dict['underline']:
                fmt.setFontUnderline(True)
                
            cursor.setCharFormat(fmt)
            cursor.insertText(part_text)
        
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()
        
    def execute_command(self, cmd: str):
        """Execute a command programmatically."""
        self.input.setText(cmd)
        self._send_command()
        
    def set_cwd(self, path: str):
        """Set current working directory."""
        self.cwd = path
        if self.process:
            self.process.write(f'cd "{path}"\n'.encode())
            
    def clear(self):
        """Clear terminal output."""
        self.output.clear()
        
    def restart(self):
        """Restart the terminal."""
        if self.process:
            self.process.kill()
            self.process.waitForFinished(2000)
        self.clear()
        self._start_shell()
        
    def close_terminal(self):
        """Close this terminal tab."""
        if self.process:
            self.process.kill()
            self.process.waitForFinished(1000)
        self.closed.emit(self)


class AdvancedTerminalWidget(QWidget):
    """Advanced terminal with tabs and profiles."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tabs: List[TerminalTab] = []
        self._profiles: Dict[str, TerminalProfile] = {}
        self._current_profile = None
        self._is_dark = True
        self._setup_default_profiles()
        self._build_ui()
        self._create_new_tab()  # Create initial tab
        
    def _setup_default_profiles(self):
        """Setup default terminal profiles."""
        import platform
        
        if platform.system() == "Windows":
            default_shell = "powershell.exe"
            default_args = ["-NoLogo", "-NonInteractive"]
        else:
            default_shell = "/bin/bash"
            default_args = ["--norc", "-i"]
            
        # Default profile
        self._profiles["Default"] = TerminalProfile(
            name="Default",
            shell=default_shell,
            shell_args=default_args,
            font_family="Courier New",
            font_size=12,
            background_color="#0c0c0c",
            text_color="#cccccc",
            cursor_style="block"
        )
        
        # PowerShell profile (Windows)
        if platform.system() == "Windows":
            self._profiles["PowerShell"] = TerminalProfile(
                name="PowerShell",
                shell="powershell.exe",
                shell_args=["-NoLogo"],
                font_family="Consolas",
                font_size=12,
                background_color="#012456",
                text_color="#ffffff",
                cursor_style="line"
            )
            
        # Bash profile
        self._profiles["Bash"] = TerminalProfile(
            name="Bash",
            shell="/bin/bash",
            shell_args=["--norc", "-i"],
            font_family="Monaco",
            font_size=12,
            background_color="#1e1e1e",
            text_color="#d4d4d4",
            cursor_style="block"
        )
        
        # Zsh profile
        self._profiles["Zsh"] = TerminalProfile(
            name="Zsh",
            shell="/bin/zsh",
            shell_args=["-i"],
            font_family="Monaco",
            font_size=12,
            background_color="#1e1e1e",
            text_color="#d4d4d4",
            cursor_style="block"
        )
        
        self._current_profile = self._profiles["Default"]
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(35)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        # Profile selector
        toolbar_layout.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(self._profiles.keys()))
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        toolbar_layout.addWidget(self.profile_combo)
        
        toolbar_layout.addStretch()
        
        # Buttons
        btn_new = QPushButton("+ New Tab")
        btn_new.clicked.connect(self._create_new_tab)
        toolbar_layout.addWidget(btn_new)
        
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_current_tab)
        toolbar_layout.addWidget(btn_clear)
        
        btn_restart = QPushButton("Restart")
        btn_restart.clicked.connect(self._restart_current_tab)
        toolbar_layout.addWidget(btn_restart)
        
        layout.addWidget(toolbar)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        layout.addWidget(self.tab_widget)
        
    def _create_new_tab(self):
        """Create a new terminal tab."""
        tab = TerminalTab(self._current_profile)
        tab.closed.connect(self._on_tab_closed)
        
        self._tabs.append(tab)
        idx = self.tab_widget.addTab(tab, f"Terminal {len(self._tabs)}")
        self.tab_widget.setCurrentIndex(idx)
        
    def _on_tab_close(self, index: int):
        """Handle tab close button."""
        if 0 <= index < len(self._tabs):
            tab = self._tabs[index]
            tab.close_terminal()
            
    def _on_tab_closed(self, tab):
        """Handle tab closed signal."""
        if tab in self._tabs:
            idx = self._tabs.index(tab)
            self._tabs.remove(tab)
            self.tab_widget.removeTab(idx)
            tab.deleteLater()
            
    def _on_tab_changed(self, index: int):
        """Handle tab change."""
        pass
        
    def _on_profile_changed(self, profile_name: str):
        """Handle profile change."""
        if profile_name in self._profiles:
            self._current_profile = self._profiles[profile_name]
            
    def _clear_current_tab(self):
        """Clear current tab."""
        current = self.tab_widget.currentWidget()
        if isinstance(current, TerminalTab):
            current.clear()
            
    def _restart_current_tab(self):
        """Restart current tab."""
        current = self.tab_widget.currentWidget()
        if isinstance(current, TerminalTab):
            current.restart()
            
    def execute_command(self, cmd: str):
        """Execute command in current terminal."""
        current = self.tab_widget.currentWidget()
        if isinstance(current, TerminalTab):
            current.execute_command(cmd)
            
    def set_cwd(self, path: str):
        """Set working directory for all terminals."""
        for tab in self._tabs:
            tab.set_cwd(path)
            
    def get_tab_count(self) -> int:
        """Get number of terminal tabs."""
        return len(self._tabs)
        
    def close_all_tabs(self):
        """Close all terminal tabs."""
        for tab in self._tabs[:]:
            tab.close_terminal()
