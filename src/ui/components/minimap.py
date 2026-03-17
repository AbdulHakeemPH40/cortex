"""
Code Minimap for Cortex AI Agent IDE
Shows a zoomed-out view of the entire code with current viewport highlighted
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QTextCursor


class MinimapWidget(QWidget):
    """Minimap widget showing overview of code."""
    
    jump_to_line = pyqtSignal(int)  # Emitted when user clicks to jump
    
    def __init__(self, parent=None, editor=None):
        super().__init__(parent)
        self.editor = editor
        self._is_dark = True
        self._scale = 0.15  # Scale factor for minimap
        self._line_height = 2  # Height per line in pixels
        self._viewport_color = QColor(0, 122, 204, 100)  # Blue semi-transparent
        
        self.setFixedWidth(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if editor:
            # Connect to editor signals
            editor.verticalScrollBar().valueChanged.connect(self.update)
            editor.textChanged.connect(self.update)
            
    def set_dark(self, is_dark: bool):
        """Update theme."""
        self._is_dark = is_dark
        self.update()
        
    def paintEvent(self, event):
        """Paint the minimap."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background
        bg_color = QColor("#1e1e1e") if self._is_dark else QColor("#ffffff")
        painter.fillRect(event.rect(), bg_color)
        
        if not self.editor:
            return
            
        # Get document content
        document = self.editor.document()
        content = self.editor.toPlainText()
        lines = content.split('\n')
        
        # Calculate dimensions
        font = QFont("Courier New", 1)
        painter.setFont(font)
        
        # Draw lines
        char_width = 0.8  # Approximate width per character
        max_chars = self.width() / char_width / self._scale
        
        for i, line in enumerate(lines):
            y = i * self._line_height
            
            # Skip if outside visible area
            if y > self.height():
                break
                
            # Truncate long lines
            display_line = line[:int(max_chars)]
            
            # Simple syntax coloring based on content
            color = self._get_line_color(display_line)
            
            # Draw line
            x = 2
            for char in display_line:
                if char.strip():  # Only draw non-whitespace for performance
                    painter.setPen(color)
                    painter.drawPoint(int(x), int(y + self._line_height / 2))
                x += char_width
                
        # Draw viewport indicator
        self._draw_viewport(painter)
        
    def _get_line_color(self, line: str) -> QColor:
        """Get color for a line based on simple heuristics."""
        if self._is_dark:
            # Dark theme colors
            if line.strip().startswith(('#', '//', '/*', '*')):
                return QColor("#6A9955")  # Comment green
            elif any(kw in line for kw in ['def ', 'class ', 'function', 'if ', 'for ', 'while ']):
                return QColor("#569CD6")  # Keyword blue
            elif '"' in line or "'" in line:
                return QColor("#CE9178")  # String orange
            else:
                return QColor("#505050")  # Default gray
        else:
            # Light theme colors
            if line.strip().startswith(('#', '//', '/*', '*')):
                return QColor("#6A737D")  # Comment gray
            elif any(kw in line for kw in ['def ', 'class ', 'function', 'if ', 'for ', 'while ']):
                return QColor("#D73A49")  # Keyword red
            elif '"' in line or "'" in line:
                return QColor("#032F62")  # String blue
            else:
                return QColor("#c0c0c0")  # Default gray
                
    def _draw_viewport(self, painter: QPainter):
        """Draw current viewport indicator."""
        if not self.editor:
            return
            
        # Calculate viewport position
        scrollbar = self.editor.verticalScrollBar()
        viewport_height = self.editor.viewport().height()
        document_height = self.editor.document().size().height()
        
        if document_height > 0:
            # Calculate visible area
            scroll_ratio = scrollbar.value() / scrollbar.maximum() if scrollbar.maximum() > 0 else 0
            viewport_top = scroll_ratio * self.height()
            viewport_height_scaled = (viewport_height / document_height) * self.height()
            
            # Draw viewport rectangle
            painter.fillRect(
                QRect(0, int(viewport_top), self.width(), int(viewport_height_scaled)),
                self._viewport_color
            )
            
    def mousePressEvent(self, event):
        """Handle click to jump to line."""
        if not self.editor:
            return
            
        # Calculate line from click position
        y = event.pos().y()
        line = int(y / self._line_height)
        
        # Emit signal
        self.jump_to_line.emit(line)
        
    def sizeHint(self) -> QSize:
        """Suggest size based on document."""
        if self.editor:
            lines = self.editor.document().blockCount()
            height = lines * self._line_height
            return QSize(120, min(height, 600))
        return QSize(120, 400)
