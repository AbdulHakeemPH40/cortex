"""
Inline Diff Editor for Cortex AI
Shows file changes directly in the main editor with red/green highlighting
Similar to VS Code's inline diff view
"""

from PyQt6.QtWidgets import QTextEdit, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor, QSyntaxHighlighter
import difflib
from typing import List, Tuple
from src.utils.logger import get_logger

log = get_logger("inline_diff_editor")


class InlineDiffEditor(QTextEdit):
    """
    Editor widget that shows diff inline with red/green highlighting
    Like VS Code's diff view
    """
    
    accept_changes = pyqtSignal(str, str)  # file_path, content
    reject_changes = pyqtSignal(str)  # file_path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path: str = ""
        self._original_content: str = ""
        self._modified_content: str = ""
        self._is_diff_mode: bool = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the editor"""
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFont("Consolas", 11))
        
        # Dark theme colors
        self._colors = {
            'removed_bg': QColor(80, 30, 30),      # Dark red background
            'removed_fg': QColor(255, 120, 120),   # Light red text
            'added_bg': QColor(30, 80, 30),        # Dark green background
            'added_fg': QColor(120, 255, 120),     # Light green text
            'unchanged_bg': QColor(30, 30, 30),    # Dark gray background
            'unchanged_fg': QColor(200, 200, 200), # Light gray text
            'header_bg': QColor(50, 50, 50),       # Header background
            'header_fg': QColor(150, 150, 150),    # Header text
        }
    
    def show_diff(self, file_path: str, original_content: str, modified_content: str):
        """
        Show diff inline in the editor
        
        Args:
            file_path: Path to the file being edited
            original_content: Original file content
            modified_content: Modified file content
        """
        self._file_path = file_path
        self._original_content = original_content
        self._modified_content = modified_content
        self._is_diff_mode = True
        
        self.clear()
        
        # Calculate diff
        diff_lines = self._calculate_diff(original_content, modified_content)
        
        # Display with highlighting
        self._display_diff(diff_lines)
        
        log.info(f"Showing inline diff for: {file_path}")
    
    def _calculate_diff(self, original: str, modified: str) -> List[Tuple[str, str, int]]:
        """
        Calculate unified diff
        
        Returns:
            List of (line_type, content, line_num) tuples
            line_type: 'header', 'removed', 'added', 'unchanged'
        """
        original_lines = original.splitlines(keepends=False)
        modified_lines = modified.splitlines(keepends=False)
        
        diff = list(difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile='Original',
            tofile='Modified',
            lineterm=''
        ))
        
        result = []
        line_num = 0
        
        for line in diff:
            if line.startswith('---') or line.startswith('+++'):
                result.append(('header', line, 0))
            elif line.startswith('@@'):
                result.append(('header', line, 0))
                # Parse line number from hunk header
                import re
                match = re.match(r'@@ -(\d+)', line)
                if match:
                    line_num = int(match.group(1)) - 1
            elif line.startswith('-'):
                line_num += 1
                result.append(('removed', line[1:], line_num))
            elif line.startswith('+'):
                result.append(('added', line[1:], 0))
            elif line.startswith(' '):
                line_num += 1
                result.append(('unchanged', line[1:], line_num))
            else:
                line_num += 1
                result.append(('unchanged', line, line_num))
        
        return result
    
    def _display_diff(self, diff_lines: List[Tuple[str, str, int]]):
        """Display diff with inline highlighting"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        
        for line_type, content, line_num in diff_lines:
            # Create format based on line type
            fmt = QTextCharFormat()
            
            if line_type == 'header':
                fmt.setBackground(self._colors['header_bg'])
                fmt.setForeground(self._colors['header_fg'])
                cursor.insertText(f"  {content}\n", fmt)
            
            elif line_type == 'removed':
                # Red background, red text with minus sign
                fmt.setBackground(self._colors['removed_bg'])
                fmt.setForeground(self._colors['removed_fg'])
                line_text = f"{line_num:4d} - {content}\n"
                cursor.insertText(line_text, fmt)
            
            elif line_type == 'added':
                # Green background, green text with plus sign
                fmt.setBackground(self._colors['added_bg'])
                fmt.setForeground(self._colors['added_fg'])
                line_text = f"     + {content}\n"
                cursor.insertText(line_text, fmt)
            
            else:  # unchanged
                fmt.setBackground(self._colors['unchanged_bg'])
                fmt.setForeground(self._colors['unchanged_fg'])
                line_text = f"{line_num:4d}   {content}\n"
                cursor.insertText(line_text, fmt)
    
    def accept_changes(self):
        """Accept the changes and write to file"""
        if self._file_path and self._modified_content:
            self.accept_changes.emit(self._file_path, self._modified_content)
            log.info(f"Changes accepted for: {self._file_path}")
    
    def reject_changes(self):
        """Reject the changes"""
        if self._file_path:
            self.reject_changes.emit(self._file_path)
            log.info(f"Changes rejected for: {self._file_path}")
    
    def get_file_path(self) -> str:
        """Get the file path"""
        return self._file_path
    
    def get_modified_content(self) -> str:
        """Get the modified content"""
        return self._modified_content


class DiffEditorTab(QWidget):
    """
    Tab widget containing the diff editor with action buttons
    """
    
    accept_changes = pyqtSignal(str, str)
    reject_changes = pyqtSignal(str)
    close_tab = pyqtSignal()
    
    def __init__(self, file_path: str, original: str, modified: str, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        
        self._setup_ui()
        self._editor.show_diff(file_path, original, modified)
    
    def _setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header with info and buttons
        header = QWidget()
        header.setStyleSheet("""
            QWidget {
                background-color: #252526;
                border-bottom: 1px solid #3e3e42;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        
        # File info
        file_name = self._file_path.split('/')[-1].split('\\')[-1]
        info_label = QLabel(f"📄 Diff View: <b>{file_name}</b>")
        info_label.setStyleSheet("color: #cccccc; font-size: 13px;")
        header_layout.addWidget(info_label)
        
        header_layout.addStretch()
        
        # Stats
        self._stats_label = QLabel()
        self._stats_label.setStyleSheet("color: #858585; font-size: 11px;")
        header_layout.addWidget(self._stats_label)
        
        header_layout.addStretch()
        
        # Action buttons
        reject_btn = QPushButton("❌ Reject")
        reject_btn.setStyleSheet("""
            QPushButton {
                background-color: #f85149;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #ff6b6b;
            }
        """)
        reject_btn.clicked.connect(self._on_reject)
        header_layout.addWidget(reject_btn)
        
        accept_btn = QPushButton("✅ Accept Changes")
        accept_btn.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)
        accept_btn.clicked.connect(self._on_accept)
        header_layout.addWidget(accept_btn)
        
        close_btn = QPushButton("✕")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #858585;
                border: none;
                padding: 4px 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #c75450;
            }
        """)
        close_btn.clicked.connect(self.close_tab.emit)
        header_layout.addWidget(close_btn)
        
        layout.addWidget(header)
        
        # Diff editor
        self._editor = InlineDiffEditor()
        self._editor.accept_changes.connect(self.accept_changes)
        self._editor.reject_changes.connect(self.reject_changes)
        layout.addWidget(self._editor)
        
        # Update stats
        self._update_stats()
    
    def _update_stats(self):
        """Update statistics label"""
        # This would be calculated based on actual diff
        self._stats_label.setText("📊 Changes: +12 lines, -5 lines")
    
    def _on_accept(self):
        """Handle accept button"""
        self._editor.accept_changes()
        self.close_tab.emit()
    
    def _on_reject(self):
        """Handle reject button"""
        self._editor.reject_changes()
        self.close_tab.emit()


# Integration with main_window.py
"""
# In main_window.py:

from src.ui.components.inline_diff_editor import DiffEditorTab

class MainWindow:
    def show_file_diff(self, file_path: str, original: str, modified: str):
        '''Show diff in a new editor tab'''
        diff_tab = DiffEditorTab(file_path, original, modified)
        diff_tab.accept_changes.connect(self._on_diff_accepted)
        diff_tab.reject_changes.connect(self._on_diff_rejected)
        
        # Add as new tab in editor
        index = self._editor_tabs.addTab(diff_tab, f"📊 {os.path.basename(file_path)}")
        self._editor_tabs.setCurrentIndex(index)
    
    def _on_diff_accepted(self, file_path: str, content: str):
        '''User accepted changes in diff view'''
        # Write to actual file
        with open(file_path, 'w') as f:
            f.write(content)
        
        # Update chat
        self._ai_chat.mark_file_accepted(file_path)
        
        # Open the actual file (not diff view)
        self.open_file(file_path)
    
    def _on_diff_rejected(self, file_path: str):
        '''User rejected changes'''
        self._ai_chat.mark_file_rejected(file_path)
"""
