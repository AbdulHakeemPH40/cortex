"""
Split Editor View for Cortex AI Agent IDE
Allows side-by-side or top-bottom split editing
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QPushButton, QLabel, QFrame, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QAction
from .editor import CodeEditor


class SplitEditorWidget(QWidget):
    """Widget that manages split editor views."""
    
    editor_focused = pyqtSignal(object)  # Emits the focused editor
    content_modified = pyqtSignal()  # Content changed in any editor
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._editors = []  # List of editors
        self._current_editor = None
        self._split_orientation = Qt.Orientation.Horizontal
        self._is_split = False
        self._is_dark = True  # Default to dark theme
        self._build_ui()
        
    def _build_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Main splitter
        self.splitter = QSplitter(self._split_orientation)
        self.splitter.setHandleWidth(2)
        
        # Create initial editor
        self._create_editor()
        
        self.layout.addWidget(self.splitter)
        
    def _create_editor(self) -> CodeEditor:
        """Create a new editor and add it to the splitter."""
        editor = CodeEditor(self)
        editor.content_modified.connect(self._on_content_modified)
        editor.cursor_position_changed.connect(self._on_cursor_changed)
        
        # Store reference to file path
        editor._filepath = None
        
        # Apply current theme to new editor
        editor.set_theme(self._is_dark)
        
        self._editors.append(editor)
        self.splitter.addWidget(editor)
        
        # Set equal sizes if split
        if len(self._editors) > 1:
            self._distribute_sizes()
        
        self._current_editor = editor
        return editor
        
    def _distribute_sizes(self):
        """Distribute splitter sizes equally."""
        count = len(self._editors)
        if count > 0:
            sizes = [1000 // count] * count
            self.splitter.setSizes(sizes)
    
    def split_horizontal(self):
        """Split editor horizontally (side by side)."""
        if len(self._editors) >= 2:
            return  # Max 2 editors for now
            
        self._split_orientation = Qt.Orientation.Horizontal
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self._create_editor()
        self._is_split = True
        
    def split_vertical(self):
        """Split editor vertically (top and bottom)."""
        if len(self._editors) >= 2:
            return  # Max 2 editors for now
            
        self._split_orientation = Qt.Orientation.Vertical
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self._create_editor()
        self._is_split = True
        
    def unsplit(self):
        """Remove split and keep only the current editor."""
        if len(self._editors) <= 1:
            return
            
        # Keep only the focused editor
        if self._current_editor and self._current_editor in self._editors:
            for editor in self._editors[:]:
                if editor != self._current_editor:
                    self._editors.remove(editor)
                    editor.deleteLater()
                    
        self._is_split = False
        
    def is_split(self) -> bool:
        """Check if view is split."""
        return self._is_split
        
    def get_current_editor(self) -> CodeEditor:
        """Get the currently focused editor."""
        return self._current_editor
        
    def get_all_editors(self) -> list:
        """Get all editors."""
        return self._editors.copy()
        
    def set_content(self, text: str, language: str = None, file_path: str = None):
        """Set content in the current editor."""
        if self._current_editor:
            self._current_editor.set_content(text, language)
            self._current_editor._filepath = file_path
            
    def get_content(self) -> str:
        """Get content from the current editor."""
        if self._current_editor:
            return self._current_editor.toPlainText()
        return ""
        
    def _on_content_modified(self):
        """Handle content modification."""
        self.content_modified.emit()
        
    def _on_cursor_changed(self, line: int, col: int):
        """Handle cursor position change."""
        sender = self.sender()
        if sender in self._editors:
            self._current_editor = sender
            self.editor_focused.emit(sender)
            
    def set_theme(self, is_dark: bool):
        """Set theme for all editors."""
        self._is_dark = is_dark
        for editor in self._editors:
            editor.set_theme(is_dark)
            
    def toggle_word_wrap(self):
        """Toggle word wrap for all editors."""
        for editor in self._editors:
            editor.toggle_word_wrap()
            
    def open_file_in_new_split(self, file_path: str, content: str, language: str = None):
        """Open a file in a new split view."""
        if not self._is_split:
            self.split_horizontal()
            
        # Get the last editor (newly created)
        if len(self._editors) > 1:
            new_editor = self._editors[-1]
            new_editor.set_content(content, language)
            new_editor._filepath = file_path
            
    def close_current_split(self):
        """Close the current split pane."""
        if len(self._editors) <= 1:
            return
            
        if self._current_editor and self._current_editor in self._editors:
            self._editors.remove(self._current_editor)
            self._current_editor.deleteLater()
            
            # Set focus to remaining editor
            if self._editors:
                self._current_editor = self._editors[0]
                self._current_editor.setFocus()
                
            self._is_split = len(self._editors) > 1
