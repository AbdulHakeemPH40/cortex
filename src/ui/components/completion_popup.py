"""
Auto-Completion Popup for Cortex AI Agent IDE
Provides code completion with AI-powered suggestions
"""

from PyQt6.QtWidgets import (
    QListWidget, QListWidgetItem, QWidget, QVBoxLayout,
    QLabel, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QKeyEvent
from typing import List, Dict, Optional


class CompletionItem:
    """Represents a completion suggestion."""
    def __init__(self, label: str, kind: str, detail: str = "", 
                 insert_text: str = None, documentation: str = ""):
        self.label = label
        self.kind = kind  # 'class', 'function', 'variable', 'keyword', etc.
        self.detail = detail
        self.insert_text = insert_text or label
        self.documentation = documentation


class CompletionPopup(QListWidget):
    """Popup widget for code completion suggestions."""
    
    item_selected = pyqtSignal(str)  # insert_text
    cancelled = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dark = True
        self._completions: List[CompletionItem] = []
        self._prefix = ""
        
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMaximumHeight(300)
        self.setMinimumWidth(250)
        
        self.itemClicked.connect(self._on_item_clicked)
        self._update_style()
        
    def _update_style(self):
        """Update popup styling."""
        if self._is_dark:
            self.setStyleSheet("""
                QListWidget {
                    background-color: #252526;
                    border: 1px solid #454545;
                    border-radius: 4px;
                    outline: 0;
                    padding: 2px;
                }
                QListWidget::item {
                    color: #d4d4d4;
                    padding: 6px 10px;
                    border-radius: 3px;
                }
                QListWidget::item:hover {
                    background-color: #2a2d2e;
                }
                QListWidget::item:selected {
                    background-color: #094771;
                    color: #ffffff;
                }
            """)
        else:
            self.setStyleSheet("""
                QListWidget {
                    background-color: #ffffff;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    outline: 0;
                    padding: 2px;
                }
                QListWidget::item {
                    color: #212529;
                    padding: 6px 10px;
                    border-radius: 3px;
                }
                QListWidget::item:hover {
                    background-color: #e8f0fe;
                }
                QListWidget::item:selected {
                    background-color: #cce5ff;
                    color: #003d80;
                }
            """)
            
    def set_completions(self, completions: List[CompletionItem], prefix: str = ""):
        """Set completion items."""
        self._completions = completions
        self._prefix = prefix
        
        self.clear()
        
        for item in completions:
            list_item = QListWidgetItem()
            
            # Icon based on kind
            icon = self._get_icon_for_kind(item.kind)
            
            # Format display
            display_text = f"{icon} {item.label}"
            if item.detail:
                display_text += f"  —  {item.detail}"
                
            list_item.setText(display_text)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            
            self.addItem(list_item)
            
        # Select first item
        if self.count() > 0:
            self.setCurrentRow(0)
            
    def _get_icon_for_kind(self, kind: str) -> str:
        """Get icon for completion kind."""
        icons = {
            'class': '📦',
            'function': '⚡',
            'method': '🔧',
            'variable': '🔤',
            'property': '📋',
            'keyword': '🔑',
            'module': '📁',
            'import': '📥',
            'snippet': '✂️',
            'text': '📝',
            'file': '📄',
            'folder': '📂',
            'enum': '🔢',
            'interface': '🔌',
            'type': '🔠',
        }
        return icons.get(kind.lower(), '•')
        
    def _on_item_clicked(self, item: QListWidgetItem):
        """Handle item selection."""
        completion = item.data(Qt.ItemDataRole.UserRole)
        if completion:
            self.item_selected.emit(completion.insert_text)
            self.hide()
            
    def select_next(self):
        """Select next item."""
        current = self.currentRow()
        if current < self.count() - 1:
            self.setCurrentRow(current + 1)
            
    def select_previous(self):
        """Select previous item."""
        current = self.currentRow()
        if current > 0:
            self.setCurrentRow(current - 1)
            
    def accept_current(self):
        """Accept current selection."""
        item = self.currentItem()
        if item:
            self._on_item_clicked(item)
        else:
            self.cancelled.emit()
            self.hide()
            
    def set_theme(self, is_dark: bool):
        """Update theme."""
        self._is_dark = is_dark
        self._update_style()


class AutoCompletionManager:
    """Manages auto-completion for the editor."""
    
    def __init__(self, editor, ai_agent=None):
        self.editor = editor
        self.ai_agent = ai_agent
        self.popup = CompletionPopup(editor.parent())
        self.popup.item_selected.connect(self._insert_completion)
        self.popup.cancelled.connect(self._cancel_completion)
        
        self._enabled = True
        self._trigger_chars = ['.', '::', '->']
        self._min_chars = 2  # Minimum characters before showing completions
        
    def show_completions(self, completions: List[CompletionItem], prefix: str = ""):
        """Show completion popup."""
        if not completions or not self._enabled:
            return
            
        self.popup.set_completions(completions, prefix)
        
        # Position popup at cursor
        cursor = self.editor.textCursor()
        rect = self.editor.cursorRect(cursor)
        pos = self.editor.mapToGlobal(rect.bottomLeft())
        
        self.popup.move(pos)
        self.popup.show()
        self.popup.raise_()
        
    def hide_completions(self):
        """Hide completion popup."""
        self.popup.hide()
        
    def _insert_completion(self, text: str):
        """Insert selected completion."""
        cursor = self.editor.textCursor()
        
        # Remove the prefix that was already typed
        if self.popup._prefix:
            for _ in range(len(self.popup._prefix)):
                cursor.deletePreviousChar()
                
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        
    def _cancel_completion(self):
        """Handle completion cancellation."""
        pass
        
    def trigger_completion(self):
        """Manually trigger completion."""
        # Get context
        cursor = self.editor.textCursor()
        line = cursor.block().text()
        column = cursor.columnNumber()
        
        # Get prefix
        prefix = self._get_prefix(line, column)
        
        # Get completions from various sources
        completions = self._get_completions(prefix)
        
        if completions:
            self.show_completions(completions, prefix)
            
    def _get_prefix(self, line: str, column: int) -> str:
        """Get the word prefix before cursor."""
        if column == 0:
            return ""
            
        text = line[:column]
        
        # Find word boundary
        for i, char in enumerate(reversed(text)):
            if not (char.isalnum() or char == '_'):
                return text[-i:]
                
        return text
        
    def _get_completions(self, prefix: str) -> List[CompletionItem]:
        """Get completion suggestions."""
        completions = []
        
        # 1. Language keywords
        completions.extend(self._get_keyword_completions(prefix))
        
        # 2. Symbols from current file
        completions.extend(self._get_symbol_completions(prefix))
        
        # 3. AI-powered completions (if AI agent available)
        if self.ai_agent and len(prefix) >= self._min_chars:
            ai_completions = self._get_ai_completions(prefix)
            completions.extend(ai_completions)
            
        # Filter by prefix
        if prefix:
            completions = [c for c in completions 
                         if c.label.lower().startswith(prefix.lower())]
            
        # Remove duplicates
        seen = set()
        unique = []
        for c in completions:
            if c.label not in seen:
                seen.add(c.label)
                unique.append(c)
                
        return unique[:20]  # Limit to 20 suggestions
        
    def _get_keyword_completions(self, prefix: str) -> List[CompletionItem]:
        """Get keyword completions for the current language."""
        from src.utils.language_detector import detect_language
        from src.utils.language_detector import get_language_info
        
        # Get current file
        filepath = getattr(self.editor, '_filepath', '')
        lang_id = detect_language(filepath)
        info = get_language_info(lang_id)
        
        if not info or not info.keywords:
            return []
            
        return [
            CompletionItem(kw, 'keyword', f'{info.name} keyword')
            for kw in info.keywords
            if kw.lower().startswith(prefix.lower())
        ]
        
    def _get_symbol_completions(self, prefix: str) -> List[CompletionItem]:
        """Get symbol completions from current file."""
        from src.utils.language_detector import get_language_detector
        
        content = self.editor.toPlainText()
        detector = get_language_detector()
        
        # Detect language and extract symbols
        # This is a simplified version - you'd want to cache this
        lang_id = detector.detect('', content)
        symbols = detector.extract_symbols(content, lang_id)
        
        completions = []
        
        for func in symbols.get('functions', []):
            completions.append(CompletionItem(
                func['name'],
                'function',
                func.get('signature', '')
            ))
            
        for cls in symbols.get('classes', []):
            completions.append(CompletionItem(
                cls['name'],
                'class'
            ))
            
        return completions
        
    def _get_ai_completions(self, prefix: str) -> List[CompletionItem]:
        """Get AI-powered completions."""
        # This would typically make an async call to the AI agent
        # For now, return empty list
        return []
        
    def handle_key_press(self, event) -> bool:
        """Handle key press event. Return True if handled."""
        if not self.popup.isVisible():
            return False
            
        key = event.key()
        
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self.popup.select_next()
            return True
        elif key == Qt.Key.Key_Up:
            self.popup.select_previous()
            return True
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.popup.accept_current()
            return True
        elif key == Qt.Key.Key_Escape:
            self.hide_completions()
            return True
            
        return False
