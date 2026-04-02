"""
Code Editor Component — QPlainTextEdit with line numbers, syntax highlighting,
current-line highlight, and auto-indent.
"""
import ast
import os
import sys
from typing import cast, List, Dict, Optional, Tuple, Any

from PyQt6.QtWidgets import (
    QPlainTextEdit, QWidget, QTextEdit, QApplication,
    QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QToolTip, QListWidget
)
from PyQt6.QtCore import (
    Qt, QRect, QSize, pyqtSignal, QSignalBlocker, QPoint, QTimer,
    QEvent
)
from PyQt6.QtGui import (
    QColor, QPainter, QTextFormat, QFont, QSyntaxHighlighter,
    QTextCharFormat, QKeyEvent, QFontMetrics, QTextOption, QPen, QPalette, 
    QTextCursor, QHelpEvent
)
from pygments import lex
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.token import Token
from src.config.settings import get_settings
from src.core.syntax_checker import get_syntax_checker, DiagnosticError
from src.core.lsp_manager import get_lsp_manager
from src.utils.logger import get_logger


log = get_logger("editor")


# ---------------------------------------------------------------------------
# Pygments-based syntax highlighter
# ---------------------------------------------------------------------------
def get_preferred_programming_font() -> str:
    """Get industry-standard programming font family.
    
    Uses comprehensive font detection for best available monospace font
    commonly used in professional IDEs and code editors.
    """
    # Industry-standard programming fonts (priority order)
    # Tier 1: Modern purpose-built coding fonts
    # Tier 2: Classic reliable system fonts
    # Tier 3: Universal fallbacks
    preferred_fonts = [
        # Tier 1: Premium Programming Fonts (Best for syntax highlighting)
        "JetBrains Mono",      # Best overall - designed for IDEs
        "Fira Code",           # Best ligatures support
        "Source Code Pro",     # Adobe's professional font
        "Cascadia Code",       # Microsoft's modern terminal font
        "Hack",                # Optimized for readability
        
        # Tier 2: Classic Programming Fonts
        "Consolas",            # Windows standard (excellent ClearType)
        "Monaco",              # macOS classic
        "SF Mono",             # Apple's modern system font
        "Roboto Mono",         # Google's material design font
        
        # Tier 3: Reliable Fallbacks
        "Inconsolata",         # High-quality open source
        "DejaVu Sans Mono",    # Extended character support
        "Lucida Console",      # Windows legacy
        "Courier New"          # Universal fallback
    ]
    
    # Try each font in priority order
    for font_name in preferred_fonts:
        font = QFont(font_name)
        if font.exactMatch():
            print(f"[Editor] Using font: {font_name}")
            return font_name
    
    # Ultimate fallback
    print("[Editor] Using default monospace font")
    return ""  # Empty string uses system default monospace


class PygmentsSyntaxHighlighter(QSyntaxHighlighter):
    # DRACULA THEME - Industry Standard Dark Theme
    # Matches ai_chat.html syntax highlighting exactly
    # Works perfectly with: Python, JS/TS, HTML, CSS, Java, C/C++, Rust, Go, SQL, etc.
    DARK_COLORS = {
        # ============================================
        # DRACULA THEME - EXACT COLORS FROM syntax_highlighting_config.py
        # Background: #282a36, Foreground: #f8f8f2
        # EVERY ELEMENT COLORED - NO WHITE TEXT ALLOWED
        # ============================================
        
        # Keywords - Dracula Purple (#bd93f9)
        Token.Keyword:            ("#bd93f9", False, False),     # Purple - def, class, if, for, return
        Token.Keyword.Constant:   ("#bd93f9", False, False),     # Purple - True, False, None
        Token.Keyword.Declaration:("#bd93f9", False, False),     # Purple - declarations
        Token.Keyword.Namespace:  ("#bd93f9", False, False),     # Purple - import, export, package
        Token.Keyword.Reserved:   ("#bd93f9", False, False),     # Purple - reserved words
        Token.Keyword.Type:       ("#bd93f9", False, False),     # Purple - int, void, string, bool
        
        # Variables & Names - Dracula Colors (NO WHITE)
        Token.Name:               ("#f1fa8c", False, False),     # Yellow - variables (NOT white)
        Token.Name.Builtin:       ("#8be9fd", False, False),     # Cyan - built-ins (len, print, console)
        Token.Name.Builtin.Pseudo:("#ff5555", False, False),     # Red - self, this, super
        Token.Name.Class:         ("#8be9fd", False, False),     # Cyan - class names
        Token.Name.Decorator:     ("#ffb86c", False, False),     # Orange - @decorators
        Token.Name.Entity:        ("#ffb86c", False, False),     # Orange - entities
        Token.Name.Exception:     ("#ff5555", False, False),     # Red - exceptions
        Token.Name.Function:      ("#ffb86c", False, False),     # Orange - function definitions/calls
        Token.Name.Function.Magic:("#ffb86c", False, False),     # Orange - __magic__ methods
        Token.Name.Label:         ("#bd93f9", False, False),     # Purple - labels
        Token.Name.Namespace:     ("#8be9fd", False, False),     # Cyan - namespaces
        Token.Name.Tag:           ("#ff79c6", False, False),     # Pink - HTML/XML tags
        Token.Name.Variable:      ("#ff5555", False, False),     # Red - variable names
        Token.Name.Variable.Class:("#f1fa8c", False, False),     # Yellow - class vars (NOT white)
        Token.Name.Variable.Global:("#f1fa8c", False, False),    # Yellow - global vars (NOT white)
        Token.Name.Variable.Instance:("#f1fa8c", False, False),  # Yellow - instance vars (NOT white)
        Token.Name.Constant:      ("#f1fa8c", False, False),     # Yellow - constants
        Token.Name.Attribute:     ("#50fa7b", False, False),     # Green - attributes/properties
        
        # Strings - Dracula Green (#50fa7b)
        Token.String:             ("#50fa7b", False, False),     # Green - all strings
        Token.String.Affix:       ("#50fa7b", False, False),     # Green - f"", r"", b"" prefixes
        Token.String.Backtick:    ("#50fa7b", False, False),     # Green - `template literals`
        Token.String.Char:        ("#50fa7b", False, False),     # Green - char literals
        Token.String.Delimiter:   ("#50fa7b", False, False),     # Green - quote marks
        Token.String.Doc:         ("#6272a4", False, True),      # Blue-gray ITALIC - docstrings
        Token.String.Double:      ("#50fa7b", False, False),     # Green - "double quoted"
        Token.String.Escape:      ("#f1fa8c", False, False),     # Yellow - \n, \t, \\
        Token.String.Heredoc:     ("#50fa7b", False, False),     # Green - heredocs
        Token.String.Interpol:    ("#50fa7b", False, False),     # Green - ${expr} interpolations
        Token.String.Other:       ("#50fa7b", False, False),     # Green - other strings
        Token.String.Regex:       ("#ff5555", False, False),     # Red - /regex/ patterns
        Token.String.Single:      ("#50fa7b", False, False),     # Green - 'single quoted'
        Token.String.Symbol:      ("#bd93f9", False, False),     # Purple - symbols
        
        # Numbers - Dracula Purple (#bd93f9)
        Token.Number:             ("#bd93f9", False, False),     # Purple - all numbers
        Token.Number.Bin:         ("#bd93f9", False, False),     # Purple - 0b1010
        Token.Number.Float:       ("#bd93f9", False, False),     # Purple - 3.14
        Token.Number.Hex:         ("#bd93f9", False, False),     # Purple - 0xFF
        Token.Number.Integer:     ("#bd93f9", False, False),     # Purple - 42
        Token.Number.Integer.Long:("#bd93f9", False, False),     # Purple - long ints
        Token.Number.Oct:         ("#bd93f9", False, False),     # Purple - 0o777
        
        # Operators - Dracula Purple (#bd93f9) - NOT WHITE
        Token.Operator:           ("#bd93f9", False, False),     # Purple - + - * / % operators
        Token.Operator.Word:      ("#bd93f9", False, False),     # Purple - and, or, not
        
        # Punctuation - Dracula Cyan (#8be9fd) - NOT WHITE
        Token.Punctuation:        ("#8be9fd", False, False),     # Cyan - brackets [], parens (), braces {}
        Token.Punctuation.Marker: ("#8be9fd", False, False),     # Cyan - semicolons, commas
        
        # Comments - Dracula Blue-gray (#6272a4)
        Token.Comment:            ("#6272a4", False, True),      # Blue-gray ITALIC - comments
        Token.Comment.Hashbang:   ("#6272a4", False, True),      # Blue-gray ITALIC - shebang
        Token.Comment.Multiline:  ("#6272a4", False, True),      # Blue-gray ITALIC - /* */
        Token.Comment.Preproc:    ("#6272a4", False, True),      # Blue-gray ITALIC - #pragma
        Token.Comment.PreprocFile:("#6272a4", False, True),      # Blue-gray ITALIC - includes
        Token.Comment.Single:     ("#6272a4", False, True),      # Blue-gray ITALIC - // or #
        Token.Comment.Special:    ("#6272a4", False, True),      # Blue-gray ITALIC - special
        
        # Errors - Dracula Red (#ff5555)
        Token.Error:              ("#ff5555", False, False),     # Red - syntax errors
        
        # Types/Classes - Dracula Cyan (#8be9fd)
        Token.Type:               ("#8be9fd", False, False),     # Cyan - type names
        
        # Functions - Dracula Orange (#ffb86c)
        Token.Name.Function:      ("#ffb86c", False, False),     # Orange - function definitions
        Token.Name.Function.Magic:("#ffb86c", False, False),     # Orange - magic methods
        
        # Markup - For HTML/XML/Markdown - ALL COLORED
        Token.Generic:            ("#f1fa8c", False, False),     # Yellow - generic markup (NOT white)
        Token.Generic.Deleted:    ("#ff5555", False, False),     # Red - deleted text
        Token.Generic.Emph:       ("#50fa7b", False, True),      # Green ITALIC - emphasis
        Token.Generic.Error:      ("#ff5555", False, False),     # Red - errors
        Token.Generic.Heading:    ("#8be9fd", False, False),     # Cyan - headings
        Token.Generic.Inserted:   ("#50fa7b", False, False),     # Green - inserted text
        Token.Generic.Output:     ("#6272a4", False, False),     # Blue-gray - program output
        Token.Generic.Prompt:     ("#bd93f9", False, False),     # Purple - shell prompt
        Token.Generic.Strong:     ("#f1fa8c", False, True),      # Yellow BOLD - strong (NOT white)
        Token.Generic.Subheading: ("#bd93f9", False, False),     # Purple - subheadings
        Token.Generic.Traceback:  ("#ff5555", False, False),     # Red - tracebacks
        
        # Literals
        Token.Literal:            ("#bd93f9", False, False),     # Purple - literal values
        Token.Literal.Date:       ("#8be9fd", False, True),      # Cyan ITALIC - dates
        Token.Literal.Number:     ("#bd93f9", False, False),     # Purple - numbers
        Token.Literal.String:     ("#50fa7b", False, False),     # Green - strings
        
        # Text - Yellow (NOT WHITE)
        Token.Text:               ("#f1fa8c", False, False),     # Yellow - plain text (NOT white)
        Token.Text.Whitespace:    ("#6272a4", False, False),     # Blue-gray - whitespace (NOT white)
        
        # HTML SPECIFIC - Dracula Colors
        Token.Name.Doctype:       ("#bd93f9", False, False),     # Purple - <!DOCTYPE html>
        Token.Name.Entity:        ("#bd93f9", False, False),     # Purple - &nbsp; &amp;
        
        # CSS INSIDE <style> - Dracula Colors (Embedded CSS)
        Token.Name.Builtin:       ("#f1fa8c", False, False),     # Yellow - CSS properties
        Token.Name.Class:         ("#ffb86c", False, False),     # Orange - .class selectors
        Token.Name.Constant:      ("#bd93f9", False, False),     # Purple - #id selectors
        Token.Name.Decorator:     ("#ffb86c", False, False),     # Orange - :pseudo-classes
        Token.Name.Function:      ("#ffb86c", False, False),     # Orange - calc(), var()
        Token.String:             ("#50fa7b", False, False),     # Green - CSS strings
        Token.String.Other:       ("#50fa7b", False, False),     # Green - url() strings
        Token.Number:             ("#bd93f9", False, False),     # Purple - CSS numbers
        Token.Number.Integer:     ("#bd93f9", False, False),     # Purple - CSS integers
        Token.Number.Float:       ("#bd93f9", False, False),     # Purple - CSS floats
        Token.Operator:           ("#bd93f9", False, False),     # Purple - CSS operators
        Token.Punctuation:        ("#8be9fd", False, False),     # Cyan - CSS punctuation
        
        # JAVASCRIPT INSIDE <script> - Dracula Colors (Embedded JS)
        Token.Name.Builtin:       ("#8be9fd", False, False),     # Cyan - console, window, document
        Token.Name.Function:      ("#ffb86c", False, False),     # Orange - function calls
        Token.Name.Variable:      ("#ff5555", False, False),     # Red - variables
        Token.String:             ("#50fa7b", False, False),     # Green - JS strings
        Token.String.Regex:       ("#ff5555", False, False),     # Red - /regex/
        Token.Number:             ("#bd93f9", False, False),     # Purple - JS numbers
        Token.Number.Integer:     ("#bd93f9", False, False),     # Purple - JS integers
        Token.Number.Float:       ("#bd93f9", False, False),     # Purple - JS floats
        Token.Operator:           ("#bd93f9", False, False),     # Purple - JS operators
        Token.Punctuation:        ("#8be9fd", False, False),     # Cyan - JS punctuation
        Token.Keyword:            ("#bd93f9", False, False),     # Purple - var, let, const, function
        Token.Keyword.Declaration:("#bd93f9", False, False),     # Purple - var, let, const
        Token.Keyword.Reserved:   ("#bd93f9", False, False),     # Purple - reserved words
        
        # Additional embedded language support
        Token.Name.Exception:     ("#ff5555", False, False),     # Red - Error objects (JS)
        Token.Name.Label:         ("#bd93f9", False, False),     # Purple - statement labels
        Token.Literal.String.Other: ("#50fa7b", False, False),   # Green - other strings
        Token.Comment:            ("#6272a4", False, True),      # Blue-gray Italic - comments
        Token.Comment.Single:     ("#6272a4", False, True),      # Blue-gray Italic - single line
        Token.Comment.Multiline:  ("#6272a4", False, True),      # Blue-gray Italic - multi-line
        
        # FALLBACK MAPPINGS - Catch-all for any unmapped tokens - ALL COLORED
        Token.Name.Attribute:     ("#50fa7b", False, False),     # Green - attributes/properties
        Token.Name.Namespace:     ("#8be9fd", False, False),     # Cyan - namespaces
        Token.Name.Entity:        ("#ffb86c", False, False),     # Orange - entities
        Token.Operator.Word:      ("#bd93f9", False, False),     # Purple - word operators (and, or)
        Token.Punctuation.Marker: ("#8be9fd", False, False),     # Cyan - punctuation markers
    }
    
    # Light theme (VS Code Light+)
    LIGHT_COLORS = {
        Token.Keyword:            ("#0000FF", False, False),     # Blue - keywords
        Token.Keyword.Type:       ("#0000FF", False, False),     # Blue - types
        Token.Name:               ("#001080", False, False),     # Dark Blue - names
        Token.Name.Function:      ("#795E26", False, False),     # Brown - functions
        Token.Name.Class:         ("#267F99", False, False),     # Teal - classes
        Token.Name.Tag:           ("#800000", False, False),     # Maroon - tags
        Token.String:             ("#A31515", False, False),     # Red - strings
        Token.Number:             ("#098658", False, False),     # Green - numbers
        Token.Comment:            ("#008000", False, True),      # Green ITALIC - comments
        Token.Operator:           ("#000000", False, False),     # Black - operators
        Token.Punctuation:        ("#000000", False, False),     # Black - punctuation
        Token.Error:              ("#FF0000", False, False),     # Red - errors
    }
    
    def __init__(self, document, language: str = "python", is_dark: bool = True):
        super().__init__(document)
        self._language = language
        self._is_dark = is_dark
        
        # Set premium programming font
        if is_dark:
            # Dracula theme font settings
            font_name = get_preferred_programming_font()  # Use module-level function
            self._base_format = QTextCharFormat()
            self._base_format.setFont(QFont(font_name, 11))
        
        self._lexer = self._get_lexer(language)
        self._formats: dict = {}
        self._build_formats()
    
    def _get_lexer(self, language: str):
        try:
            # For HTML, use standard HTML lexer (fastest option)
            if language.lower() == "html":
                from pygments.lexers.html import HtmlLexer
                return HtmlLexer()
            
            # Direct lookup for common languages (faster than get_lexer_by_name)
            if language.lower() == "python":
                from pygments.lexers.python import PythonLexer
                return PythonLexer()
            elif language.lower() in ("javascript", "js"):
                from pygments.lexers.javascript import JavascriptLexer
                return JavascriptLexer()
            elif language.lower() in ("typescript", "ts"):
                from pygments.lexers.javascript import TypescriptLexer
                return TypescriptLexer()
            elif language.lower() == "css":
                from pygments.lexers.css import CssLexer
                return CssLexer()
            elif language.lower() == "json":
                from pygments.lexers.data import JsonLexer
                return JsonLexer()
            
            # Fallback to generic lookup
            return get_lexer_by_name(language, stripall=False)
        except Exception:
            return TextLexer()

    def _build_formats(self):
        palette = self.DARK_COLORS if self._is_dark else self.LIGHT_COLORS
        self._formats.clear()
        
        # Get base font format if available
        base_format = getattr(self, '_base_format', None)
        if base_format:
            base_font = base_format.font()
        
        for token_type, (color, bold, italic) in palette.items():
            fmt = QTextCharFormat()
            
            # Inherit font from base format if available
            if base_format:
                fmt.setFont(base_font)
            
            color_obj = QColor(color)
            fmt.setForeground(color_obj)
            
            # Override weight and italic based on token
            if bold:
                fmt.setFontWeight(700)  # Bold
            if italic:
                fmt.setFontItalic(True)
            
            self._formats[token_type] = fmt

    def set_language(self, language: str):
        """Set language with optimized re-highlighting."""
        if self._language == language:
            return  # Skip if same language
            
        self._language = language
        self._lexer = self._get_lexer(language)
        self.rehighlight()
        
    def set_dark(self, is_dark: bool):
        """Switch theme with optimized refresh."""
        if self._is_dark == is_dark:
            return  # Skip if same theme
            
        self._is_dark = is_dark
        self._build_formats()
        self.rehighlight()

    def highlightBlock(self, text: str):
        if not text:
            self.setCurrentBlockState(0)
            return
            
        # Performance safety: skip highlighting for extremely long lines (e.g. minified JS)
        if len(text) > 5000:
            return
            
        combined = self.previousBlockState()
        
        # Performance optimization: cache lexer results
        try:
            tokens = list(lex(text, self._lexer))
        except Exception as e:
            # Fallback to plain text if lexing fails
            return
        
        pos = 0
        tokens_applied = 0
        
        for token_type, value in tokens:
            length = len(value)
            
            # Fast path: direct lookup first
            fmt = self._formats.get(token_type)
            
            # Slow path: walk hierarchy only if direct lookup fails
            if not fmt:
                t = token_type.parent if hasattr(token_type, 'parent') else Token
                while t is not Token and not fmt:
                    fmt = self._formats.get(t)
                    t = t.parent if hasattr(t, 'parent') else Token
            
            if fmt:
                self.setFormat(pos, length, fmt)
                tokens_applied += 1
            pos += length
        
        self.setCurrentBlockState(0)


# ---------------------------------------------------------------------------
# Line number gutter
# ---------------------------------------------------------------------------
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)


# ---------------------------------------------------------------------------
# Inline edit overlay
# ---------------------------------------------------------------------------
class InlineEditOverlay(QFrame):
    submitted = pyqtSignal(str)
    cancelled = pyqtSignal()
    diff_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inline_edit_overlay")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self._title = QLabel("Inline Edit (Ctrl+K)")
        self._status = QLabel("")
        self._status.setStyleSheet("color: #9aa0a6;")
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._status)
        layout.addLayout(header)

        self._selection_info = QLabel("")
        self._selection_info.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        layout.addWidget(self._selection_info)

        self._prompt = QTextEdit()
        self._prompt.setPlaceholderText("Describe the change to apply to the selection...")
        self._prompt.setFixedHeight(60)
        layout.addWidget(self._prompt)

        self._preview_label = QLabel("Preview")
        self._preview_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        self._preview_label.hide()
        layout.addWidget(self._preview_label)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFixedHeight(120)
        self._preview.hide()
        layout.addWidget(self._preview)

        btn_row = QHBoxLayout()
        self._diff_btn = QPushButton("Open Diff Tab")
        self._diff_btn.setEnabled(False)
        self._send_btn = QPushButton("Send")
        self._cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(self._diff_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._send_btn)
        layout.addLayout(btn_row)

        self._send_btn.clicked.connect(self._on_send)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._diff_btn.clicked.connect(self.diff_requested.emit)

        self.setStyleSheet(
            "#inline_edit_overlay {"
            "background: #1f1f1f; border: 1px solid #3e3e42; border-radius: 6px;}"
            "QTextEdit { background: #111; color: #e5e5e5; border: 1px solid #333; }"
            "QPushButton { padding: 4px 10px; }"
        )

    def set_selection_info(self, text: str):
        self._selection_info.setText(text)

    def set_pending(self, pending: bool):
        self._send_btn.setEnabled(not pending)
        self._status.setText("Working..." if pending else "")

    def set_preview(self, diff_text: str):
        self._preview_label.show()
        self._preview.show()
        self._preview.setPlainText(diff_text)
        self._diff_btn.setEnabled(True)
        self._status.setText("Preview ready")

    def reset(self):
        self._prompt.clear()
        self._preview.clear()
        self._preview.hide()
        self._preview_label.hide()
        self._status.setText("")
        self._diff_btn.setEnabled(False)
        self.set_pending(False)

    def focus_prompt(self):
        self._prompt.setFocus()

    def _on_send(self):
        text = self._prompt.toPlainText().strip()
        if text:
            self.submitted.emit(text)

    def _on_cancel(self):
        self.cancelled.emit()


# ---------------------------------------------------------------------------
# Autocomplete Sidebar/Overlay
# ---------------------------------------------------------------------------
class CompletionWidget(QWidget):
    """A floating autocomplete selection widget (VS Code Style)."""
    item_selected = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.list = QListWidget()
        self.list.setStyleSheet("""
            QListWidget {
                background-color: #252526;
                color: #cccccc;
                border: 1px solid #454545;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
            QListWidget::item:selected {
                background-color: #094771;
                color: white;
            }
        """)
        layout.addWidget(self.list)
        self.setFixedSize(250, 150)
        self.list.itemActivated.connect(self._on_activated)

    def set_items(self, items: List[Dict]):
        self.list.clear()
        self._raw_items = items
        for item in items:
            label = item.get("label", "")
            # Add icon based on kind
            kind = item.get("kind", 1)
            icons = {1: "📝", 2: "🔧", 3: "📦", 5: "🏷️", 6: "🎨"}
            self.list.addItem(f"{icons.get(kind, '🔹')} {label}")
        self.list.setCurrentRow(0)

    def _on_activated(self, item):
        idx = self.list.row(item)
        if 0 <= idx < len(self._raw_items):
            self.item_selected.emit(self._raw_items[idx])
            self.hide()

# ---------------------------------------------------------------------------
# Main Code Editor
# ---------------------------------------------------------------------------
class CodeEditor(QPlainTextEdit):
    cursor_position_changed = pyqtSignal(int, int)  # line, col
    content_modified = pyqtSignal()
    inline_edit_submitted = pyqtSignal(str, str, tuple)  # prompt, selection_text, (start, end)
    inline_edit_cancelled = pyqtSignal()
    inline_diff_requested = pyqtSignal()

    def _get_preferred_programming_font(self) -> str:
        """Get best available programming font."""
        preferred_fonts = [
            "JetBrains Mono",     # Best for coding
            "Fira Code",          # Great ligatures
            "Source Code Pro",    # Adobe's programming font
            "Consolas",           # Windows classic
            "Monaco",             # macOS classic
            "Courier New"         # Universal fallback
        ]
        for font_name in preferred_fonts:
            font = QFont(font_name)
            if font.exactMatch():
                return font_name
        return "Consolas"
    
    def _apply_editor_theme(self):
        """Apply dark theme colors to editor widget background and text."""
        if not self._is_dark:
            print("[Editor] Skipping theme - light mode")
            return
        
        # Dracula theme exact colors
        bg_color = QColor("#1E1E1E")      # VS Code Dark+ background
        fg_color = QColor("#D4D4D4")      # VS Code Dark+ foreground
        
        # CRITICAL: Force Qt to use palette colors
        self.setAutoFillBackground(True)
        
        # Set widget colors via palette (highest priority)
        palette = QPalette()  # Create fresh palette
        palette.setColor(QPalette.ColorRole.Window, bg_color)
        palette.setColor(QPalette.ColorRole.WindowText, fg_color)
        palette.setColor(QPalette.ColorRole.Base, bg_color)      # Text edit background
        palette.setColor(QPalette.ColorRole.Text, fg_color)       # Text color
        palette.setColor(QPalette.ColorRole.AlternateBase, bg_color)  # Alternating rows
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#264F78"))  # Selection background
        palette.setColor(QPalette.ColorRole.HighlightedText, fg_color)  # Selection text
        self.setPalette(palette)
        
        # CRITICAL: Ensure viewport also uses the palette
        if hasattr(self, 'viewport'):
            viewport = self.viewport()
            viewport.setAutoFillBackground(True)
            viewport.setPalette(palette)
        
        # Force update to ensure colors are applied immediately
        self.update()
        
        print(f"[Editor] ✅ Applied dark theme: bg={bg_color.name()}, fg={fg_color.name()}")
        print(f"[Editor] Palette Base: {palette.color(QPalette.ColorRole.Base).name()}")
        print(f"[Editor] Palette Text: {palette.color(QPalette.ColorRole.Text).name()}")

    def __init__(self, parent=None, language: str = "python"):
        super().__init__(parent)
        self._settings = get_settings()
        self._language = language
        self._file_path = ""
        self._is_dark = True
        self._syntax_checker = get_syntax_checker()
        
        # CRITICAL: Apply dark theme FIRST before any other setup
        self._apply_editor_theme()

        # Enable mouse tracking for tooltips
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        # Font - Premium programming fonts (Dracula theme style)
        font_family = self._get_preferred_programming_font()
        font_size = max(8, int(self._settings.get("editor", "font_size") or 12))
        font = QFont(font_family)
        font.setPointSize(font_size)
        font.setFixedPitch(True)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

        # Tab stop
        metrics = QFontMetrics(font)
        self.setTabStopDistance(
            metrics.horizontalAdvance(' ') * (self._settings.get("editor", "tab_size") or 4)
        )

        # Line number area
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_changed)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.document().contentsChanged.connect(self.content_modified)

        self._update_line_number_area_width(0)
        self._highlight_current_line()

        # Syntax highlighter
        self._highlighter = PygmentsSyntaxHighlighter(
            self.document(), language=language, is_dark=True
        )

        # Line wrap off
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # Inline edit overlay
        self._inline_overlay = InlineEditOverlay(self.viewport())
        self._inline_overlay.hide()
        self._inline_overlay.submitted.connect(self._on_inline_submit)
        self._inline_overlay.cancelled.connect(self._hide_inline_overlay)
        self._inline_overlay.diff_requested.connect(self.inline_diff_requested.emit)
        self._inline_selection_text = ""
        self._inline_selection_range = (0, 0)
        
        # Syntax Error Detection
        self._syntax_errors: List[DiagnosticError] = []
        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.timeout.connect(self._run_linting)
        self.document().contentsChanged.connect(lambda: self._lint_timer.start(350))

        # REACTIVE: Diagnostic Hover Timer (Fast Tooltips)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_hover_diagnostic)
        self._last_hover_pos = QPoint(-1, -1)

        # REACTIVE: Dynamic response to LSP background results
        get_lsp_manager().diagnostics_updated.connect(self._handle_lsp_update)

        # Completion Widget & Debounce Timer
        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.timeout.connect(self._trigger_completion)
        self._completion_widget = CompletionWidget(self.viewport())
        self._completion_widget.hide()
        self._completion_widget.item_selected.connect(self._insert_completion)

    def set_content(self, text: str, language: str = None, file_path: str = ""):
        """Set editor content and file context."""
        if file_path:
            self._file_path = file_path
        if language:
            self._language = language
            # Only set highlighter language if it exists (during init, it doesn't)
            if hasattr(self, '_highlighter'):
                self._highlighter.set_language(language)
        
        # CRITICAL: Allow highlighter to run by NOT blocking document signals
        # Only prevent content_modified from firing
        try:
            # Temporarily disconnect content_modified
            self.document().contentsChanged.disconnect(self.content_modified)
        except (TypeError, RuntimeError):
            # Wasn't connected
            pass
        
        # Set text - this WILL trigger highlightBlock() because we're not blocking
        self.setPlainText(text)
        self.moveCursor(self.textCursor().MoveOperation.Start)
        
        # Reconnect content_modified
        try:
            self.document().contentsChanged.connect(self.content_modified)
        except (TypeError, RuntimeError):
            pass
        
        print(f"[Editor] set_content: {len(text)} chars, triggering highlighting")
        
        # Trigger syntax highlighting via rehighlight() - this is the proper Qt way
        if hasattr(self, '_highlighter'):
            self._highlighter.rehighlight()
            
        # Initial Diagnostic check (No delay needed on load)
        QTimer.singleShot(500, self._run_linting)

    def set_theme(self, is_dark: bool):
        """Set theme and refresh font family."""
        self._is_dark = is_dark
        
        # Update syntax highlighter colors
        self._highlighter.set_dark(is_dark)
        
        # CRITICAL: Update widget background and text colors
        self._apply_editor_theme()
        
        # Refresh font family (in case user installed new fonts)
        if is_dark:
            # Re-apply premium programming font for dark theme
            font_family = get_preferred_programming_font()  # ← Use module-level function
            current_size = self.font().pointSize()
            new_font = QFont(font_family, current_size)
            new_font.setFixedPitch(True)
            new_font.setStyleHint(QFont.StyleHint.Monospace)
            self.setFont(new_font)
            
            # Update tab stop distance for new font metrics
            metrics = QFontMetrics(new_font)
            tab_size = 4  # Default tab width
            self.setTabStopDistance(metrics.horizontalAdvance(' ') * tab_size)
        
        # Update line highlight
        self._highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        char_w = self.fontMetrics().horizontalAdvance('9')
        return char_w * digits + 20

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        # Fix scrolling drift: using update() instead of scroll() for better sync
        self._line_number_area.update()
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event):
        gutter_bg = QColor("#2d2d30") if self._is_dark else QColor("#f1f3f4")
        num_color = QColor("#858585") if self._is_dark else QColor("#6c757d")
        cur_color = QColor("#c6c6c6") if self._is_dark else QColor("#212529")

        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), gutter_bg)
        painter.setFont(self.font())

        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_idx = block.blockNumber()
                num = str(line_idx + 1)
                if line_idx == current_line:
                    painter.setPen(cur_color)
                else:
                    painter.setPen(num_color)
                painter.drawText(
                    0, top,
                    self._line_number_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, num
                )
                
                # Draw Syntax Error Marker (Gutter Dot)
                line_errs = [e for e in self._syntax_errors if e.line == line_idx + 1]
                if line_errs:
                    # Pick highest severity color
                    if any(e.severity == "error" for e in line_errs):
                        color = QColor("#f44747") # Error Red
                    elif any(e.severity == "warning" for e in line_errs):
                        color = QColor("#cca700") # Warning Gold
                    else:
                        color = QColor("#75beff") # Info Blue
                        
                    painter.setPen(QPen(color, 5))
                    # Center the dot in the gutter area left of the line numbers
                    painter.drawPoint(8, top + (self.fontMetrics().height() // 2))

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())

    def _run_linting(self):
        """Request a fresh syntax check from the engine."""
        if not self._syntax_checker: return
        
        path = self._file_path or f"virtual_file.{self._language or 'py'}"
        content = self.toPlainText()
        
        # Notify LSP of the latest content change
        get_lsp_manager().notify_changed(path, content, self._language)
        
        # Run core syntax checker (Hybrid: LSP + Local)
        # Note: Local errors appear immediately, LSP ones usually arrive via signal
        result = self._syntax_checker.check_file(path, content)
        self._render_diagnostics(result.errors)

    def _render_diagnostics(self, errors: List[DiagnosticError]):
        """Pure visual rendering of provided diagnostic errors."""
        self._syntax_errors = errors
        
        # 1. Clear old lint markers but keep other selections (like current line highlight)
        sels = [s for s in self.extraSelections() if not getattr(s, '_lint', False)]
        
        # 2. Create precise squiggles
        new_sels = []
        for err in self._syntax_errors:
            s = QTextEdit.ExtraSelection()
            s._lint = True
            fmt = QTextCharFormat()
            
            # Map severity to color
            color = QColor("#f44747") # Default error red
            if err.severity == "warning": color = QColor("#cca700")
            elif err.severity == "info": color = QColor("#75beff")
                
            fmt.setUnderlineColor(color)
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            s.format = fmt
            
            # Use Precise Word Positioning
            block = self.document().findBlockByNumber(max(0, err.line - 1))
            if block.isValid():
                cur = QTextCursor(block)
                # Ensure we don't move past the end of the block
                start_col = min(block.length() - 1, max(0, err.column - 1))
                cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, start_col)
                
                # Highlight length
                length = (err.end_column - err.column) if (err.end_column > err.column) else 0
                if length > 0:
                    cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, length)
                # Smart selection: try word, but fallback to single char to avoid line overflows
                cur.select(QTextCursor.SelectionType.WordUnderCursor)
                # If word selection is empty or spans multiple blocks, fallback
                if cur.selectedText().strip() == "" or cur.blockNumber() != block.blockNumber():
                    cur.setPosition(block.position() + start_col)
                    cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                
                # Enhancing visibility with a subtle background tint
                bg_color = QColor(color)
                bg_color.setAlpha(35) # Very subtle (max 255)
                fmt.setBackground(bg_color)
                
                s.cursor = cur
                new_sels.append(s)
        
        # Combine with non-lint selections (like current line highlight)
        self.setExtraSelections(sels + new_sels)
        
        # Forced update of gutter and viewport for instant feedback
        if hasattr(self, '_line_number_area'):
            self._line_number_area.update()
        self.viewport().update()

    def _handle_lsp_update(self, file_path: str, raw_diagnostics: List[Dict]):
        """Reactive handler for LSP background results."""
        if not self._file_path: return
        
        # Only process if it matches our file
        # Use normpath to ensure cross-platform match (LSP might send / vs \)
        my_path = os.path.normcase(os.path.normpath(self._file_path))
        inc_path = os.path.normcase(os.path.normpath(file_path))
        
        if my_path != inc_path:
            return
            
        # Convert raw LSP dicts to DiagnosticError objects
        processed_errors = []
        for d in raw_diagnostics:
            processed_errors.append(DiagnosticError(
                file_path=file_path,
                message=d.get("message", ""),
                line=d.get("range", {}).get("start", {}).get("line", 0) + 1,
                column=d.get("range", {}).get("start", {}).get("character", 0) + 1,
                severity=d.get("severity_label", "error").lower(),
                source="LSP",
                code=str(d.get("code", "")),
                end_column=d.get("range", {}).get("end", {}).get("character", 0) + 1
            ))
            
        # Render ONLY. Do NOT call _run_linting here to avoid infinite loops.
        self._render_diagnostics(processed_errors)

    def _highlight_current_line(self):
        # Keep existing lint selections
        extra = [s for s in self.extraSelections() if getattr(s, '_lint', False)]
        
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            color = QColor("#2a2d2e") if self._is_dark else QColor("#f1f3f4")
            sel.format.setBackground(color)
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.append(sel)
            
        self.setExtraSelections(extra)
    
    def paintEvent(self, event):
        """Paint editor with indentation guide lines."""
        super().paintEvent(event)
        
        # Draw indentation guide lines
        self._draw_indent_guides()
    
    def _draw_indent_guides(self):
        """Draw vertical indentation guide lines like VS Code."""
        painter = QPainter(self.viewport())
        
        # Guide line color (very subtle gray)
        guide_color = QColor("#3a3a3a") if self._is_dark else QColor("#e0e0e0")
        painter.setPen(QPen(guide_color, 1, Qt.PenStyle.DotLine))
        
        # Get horizontal offset and char width
        offset_x = self.horizontalScrollBar().value()
        char_w = self.fontMetrics().horizontalAdvance(' ')
        # VS Code style: draw lines at 4, 8, 12... spaces
        indent_char_count = 4 
        
        block = self.firstVisibleBlock()
        while block.isValid():
            top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
            bottom = top + int(self.blockBoundingRect(block).height())
            
            if block.isVisible() and bottom >= 0 and top <= self.viewport().height():
                text = block.text()
                indent = 0
                for char in text:
                    if char == ' ': indent += 1
                    elif char == '\t': indent += 4
                    else: break
                
                if indent >= indent_char_count:
                    for i in range(indent_char_count, indent + 1, indent_char_count):
                        x = (i * char_w) - offset_x
                        if 0 <= x < self.viewport().width():
                            painter.drawLine(x, top, x, bottom)
            
            block = block.next()
            if top > self.viewport().height(): break
        
        painter.end()

    def _on_cursor_changed(self):
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.cursor_position_changed.emit(line, col)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()

        # 1. IntelliSense Navigation (Up/Down/Enter/Tab)
        if self._completion_widget.isVisible():
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                row = self._completion_widget.list.currentRow()
                count = self._completion_widget.list.count()
                if count > 0:
                    if key == Qt.Key.Key_Up:
                        self._completion_widget.list.setCurrentRow((row - 1) % count)
                    else:
                        self._completion_widget.list.setCurrentRow((row + 1) % count)
                return
            elif key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
                current = self._completion_widget.list.currentItem()
                if current:
                    self._completion_widget._on_activated(current)
                return
            elif key == Qt.Key.Key_Escape:
                self._completion_widget.hide()
                return

        # 2. Inline edit (Ctrl/Cmd + K)
        if key == Qt.Key.Key_K and (modifiers & Qt.KeyboardModifier.ControlModifier or
                                    modifiers & Qt.KeyboardModifier.MetaModifier):
            self._show_inline_overlay()
            return
        if key == Qt.Key.Key_Escape and self._inline_overlay.isVisible():
            self._hide_inline_overlay()
            return

        # 3. Auto-indent on Enter
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor = self.textCursor()
            block = cursor.block()
            indent = ""
            for ch in block.text():
                if ch in (" ", "\t"):
                    indent += ch
                else:
                    break
            # Extra indent after colon (Python)
            text = block.text().rstrip()
            if text.endswith(":"):
                indent += "    "
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return

        # 4. Tab handling - VS Code style
        if key == Qt.Key.Key_Tab:
            tab_size = self._settings.get("editor", "tab_size") or 4
            if modifiers == Qt.KeyboardModifier.ShiftModifier:
                self._outdent_selection(tab_size)
                return
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_selection(tab_size)
                return
            self.insertPlainText(" " * tab_size)
            return

        # 5. Default edit + IntelliSense trigger (Debounced)
        super().keyPressEvent(event)
        if event.text().isalnum() or event.text() in (".", "_"):
            self._completion_timer.start(100) # 100ms delay to prevent flood

    def mouseMoveEvent(self, event):
        """Track mouse for instant diagnostic tooltips."""
        super().mouseMoveEvent(event)
        
        pos = event.pos()
        if pos == self._last_hover_pos:
            return
        self._last_hover_pos = pos
        
        # Check if mouse is over an error
        cursor = self.cursorForPosition(pos)
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        
        found_err = False
        for err in self._syntax_errors:
            if err.line == line:
                # Small 2-char buffer for visibility
                end = err.end_column if err.end_column > err.column else err.column + 2
                if err.column <= col <= end:
                    found_err = True
                    break
        
        if found_err:
            self._hover_timer.start(200) # Fast 200ms hover detection
        else:
            self._hover_timer.stop()
            QToolTip.hideText()

    def _show_hover_diagnostic(self):
        """Triggered by _hover_timer to show tooltip near mouse."""
        pos = self._last_hover_pos
        cursor = self.cursorForPosition(pos)
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        
        for err in self._syntax_errors:
            if err.line == line:
                end = err.end_column if err.end_column > err.column else err.column + 2
                if err.column <= col <= end:
                    icon = "❌" if err.severity == "error" else "⚠️"
                    text = f"<div style='background-color:#1e1e1e; color:#cccccc; border:1px solid #3c3c3c; padding:5px;'>"
                    text += f"<b style='color:#f44747'>{icon} {err.severity.capitalize()}</b>: {err.message}"
                    if err.code:
                        text += f"<br/><i style='color:#888'>({err.source}: {err.code})</i>"
                    text += "</div>"
                    
                    QToolTip.showText(self.viewport().mapToGlobal(pos), text, self.viewport())
                    return
    
    def _indent_selection(self, tab_size: int):
        """Indent selected lines (VS Code style)."""
        cursor = self.textCursor()
        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()
        
        # Get selected text
        selected_text = cursor.selectedText()
        lines = selected_text.split("\n")
        
        # Indent each line
        indented_lines = []
        for line in lines:
            indented_lines.append(" " * tab_size + line)
        
        # Replace selection
        new_text = "\n".join(indented_lines)
        cursor.insertText(new_text)
        
        # Restore selection
        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos + (len(indented_lines) * tab_size), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
    
    def _outdent_selection(self, tab_size: int):
        """Outdent selected lines (remove leading spaces)."""
        cursor = self.textCursor()
        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()
        
        # Get selected text
        selected_text = cursor.selectedText()
        lines = selected_text.split("\n")
        
        # Outdent each line
        outdented_lines = []
        removed_count = 0
        for line in lines:
            original_len = len(line)
            # Remove up to tab_size spaces from start
            stripped = line.lstrip(' ')
            spaces_removed = original_len - len(stripped)
            actual_remove = min(spaces_removed, tab_size)
            outdented_lines.append(line[actual_remove:])
            removed_count += actual_remove
        
        # Replace selection
        new_text = "\n".join(outdented_lines)
        cursor.insertText(new_text)
        
        # Restore selection
        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos - removed_count, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _show_inline_overlay(self):
        selection_text, line_range = self._get_selection_info()
        self._inline_selection_text = selection_text
        self._inline_selection_range = line_range

        start_line, end_line = line_range
        if start_line == end_line:
            info = f"Line {start_line}"
        else:
            info = f"Lines {start_line}-{end_line}"
        self._inline_overlay.set_selection_info(info)
        self._inline_overlay.reset()

        # Size and position near cursor
        overlay_width = min(480, max(320, self.viewport().width() - 40))
        self._inline_overlay.setFixedWidth(overlay_width)
        self._inline_overlay.adjustSize()
        rect = self.cursorRect()
        x = rect.left() + 10
        y = rect.bottom() + 10
        if x + overlay_width > self.viewport().width():
            x = max(10, self.viewport().width() - overlay_width - 10)
        if y + self._inline_overlay.height() > self.viewport().height():
            y = max(10, rect.top() - self._inline_overlay.height() - 10)
        self._inline_overlay.move(QPoint(x, y))

        self._inline_overlay.show()
        self._inline_overlay.raise_()
        self._inline_overlay.focus_prompt()


    def _trigger_completion(self):
        """Request completions from LSP Manager."""
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        
        def on_results(res, err):
            if err or not res: return
            items = res.get("items", []) if isinstance(res, dict) else res
            if not items: return
            
            # Show on main thread
            QTimer.singleShot(0, lambda: self._show_completions(items))
            
        get_lsp_manager().get_completions(self._file_path, line, col, self._language, on_results)

    def _show_completions(self, items: List[Dict]):
        """Display the completion widget near the cursor with boundary checks."""
        if not items:
            self._completion_widget.hide()
            return
            
        self._completion_widget.set_items(items[:50]) # Limit to top 50
        
        # Calculate position
        cursor_rect = self.cursorRect()
        global_pos = self.viewport().mapToGlobal(cursor_rect.bottomLeft())
        
        # Boundary Check: Keep on screen
        screen = QApplication.primaryScreen().geometry()
        widget_height = self._completion_widget.height()
        
        # If it goes off the bottom, flip to top
        if global_pos.y() + widget_height > screen.height():
            global_pos = self.viewport().mapToGlobal(cursor_rect.topLeft())
            global_pos -= QPoint(0, widget_height + 5)
        else:
            global_pos += QPoint(0, 5)
            
        self._completion_widget.move(global_pos)
        self._completion_widget.show()
        self._completion_widget.raise_()

    def _insert_completion(self, item: Dict):
        """Insert the selected completion text into the editor."""
        text = item.get("insertText") or item.get("label")
        cursor = self.textCursor()
        # Backtrack to the start of the word
        cursor.movePosition(QTextCursor.MoveOperation.StartOfWord, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.setFocus()

    def _hide_inline_overlay(self):
        if self._inline_overlay.isVisible():
            self._inline_overlay.hide()
            self.inline_edit_cancelled.emit()

    def _on_inline_submit(self, prompt: str):
        self._inline_overlay.set_pending(True)
        self.inline_edit_submitted.emit(
            prompt,
            self._inline_selection_text,
            self._inline_selection_range
        )

    def show_inline_diff(self, diff_text: str):
        if self._inline_overlay:
            self._inline_overlay.set_pending(False)
            self._inline_overlay.set_preview(diff_text)

    def _get_selection_info(self) -> tuple[str, tuple]:
        cursor = self.textCursor()
        if cursor.hasSelection():
            selection_text = cursor.selectedText().replace("\u2029", "\n")
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
        else:
            selection_text = cursor.block().text()
            start_pos = cursor.position()
            end_pos = cursor.position()

        start_cursor = QTextCursor(self.document())
        start_cursor.setPosition(start_pos)
        end_cursor = QTextCursor(self.document())
        end_cursor.setPosition(end_pos)

        start_line = start_cursor.blockNumber() + 1
        end_line = end_cursor.blockNumber() + 1

        return selection_text, (start_line, end_line)

    def get_selected_text(self) -> str:
        return self.textCursor().selectedText().replace("\u2029", "\n")

    def get_all_text(self) -> str:
        return self.toPlainText()

    @property
    def language(self) -> str:
        return self._language

    def toggle_word_wrap(self):
        """Toggle word wrap mode."""
        current = self.lineWrapMode()
        if current == QPlainTextEdit.LineWrapMode.NoWrap:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def set_word_wrap(self, enabled: bool):
        """Set word wrap mode."""
        if enabled:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def is_word_wrap_enabled(self) -> bool:
        """Check if word wrap is enabled."""
        return self.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap
