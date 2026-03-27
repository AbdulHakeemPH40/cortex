"""
Code Editor Component — QPlainTextEdit with line numbers, syntax highlighting,
current-line highlight, and auto-indent.
"""

import ast
import os
from PyQt6.QtWidgets import (
    QPlainTextEdit, QWidget, QTextEdit, QApplication,
    QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout
)
from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal, QSignalBlocker, QPoint, QTimer
from PyQt6.QtGui import (
    QColor, QPainter, QTextFormat, QFont, QSyntaxHighlighter,
    QTextCharFormat, QKeyEvent, QFontMetrics, QTextOption, QPen, QPalette, QTextCursor
)
from pygments import lex
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.token import Token
from src.config.settings import get_settings
from src.core.syntax_checker import get_syntax_checker, SyntaxError as DiagnosticError
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
    # VS Code Dark+ Exact Clone - Industry Standard Theme
    # Matches VS Code's "Dark+ (default dark)" theme exactly
    # Based on official VS Code color tokens
    # Works perfectly with: Python, JS/TS, HTML, CSS, Java, C/C++, Rust, Go, SQL, etc.
    DARK_COLORS = {
        # ============================================
        # VS CODE DARK+ EXACT COLORS
        # Background: #1E1E1E, Foreground: #D4D4D4
        # ============================================
        
        # Keywords - VS Code Blue (#569CD6)
        Token.Keyword:            ("#569CD6", False, False),     # Blue - def, class, if, for
        Token.Keyword.Constant:   ("#569CD6", False, False),     # Blue - True, False, None
        Token.Keyword.Declaration:("#569CD6", False, False),     # Blue - declarations
        Token.Keyword.Namespace:  ("#569CD6", False, False),     # Blue - import, export, package
        Token.Keyword.Reserved:   ("#569CD6", False, False),     # Blue - reserved words
        Token.Keyword.Type:       ("#569CD6", False, False),     # Blue - int, void, string, bool
        
        # Variables - VS Code Light Blue (#9CDCFE)
        Token.Name:               ("#9CDCFE", False, False),     # Light Blue - variables
        Token.Name.Builtin:       ("#4EC9B0", False, False),     # Teal - built-ins (len, print)
        Token.Name.Builtin.Pseudo:("#9CDCFE", False, False),     # Light Blue - self, this
        Token.Name.Class:         ("#4EC9B0", False, False),     # Teal - class names
        Token.Name.Decorator:     ("#DCDCAA", False, False),     # Yellow - @decorators
        Token.Name.Entity:        ("#CE9178", False, False),     # Orange - entities
        Token.Name.Exception:     ("#F44747", False, False),     # Red - exceptions
        Token.Name.Function:      ("#DCDCAA", False, False),     # Yellow - function calls
        Token.Name.Function.Magic:("#DCDCAA", False, False),     # Yellow - __magic__
        Token.Name.Label:         ("#569CD6", False, False),     # Blue - labels
        Token.Name.Namespace:     ("#4EC9B0", False, False),     # Teal - namespaces
        Token.Name.Tag:           ("#569CD6", False, False),     # Blue - HTML/XML tags
        Token.Name.Variable:      ("#9CDCFE", False, False),     # Light Blue - variables
        Token.Name.Variable.Class:("#9CDCFE", False, False),     # Light Blue - class vars
        Token.Name.Variable.Global:("#9CDCFE", False, False),    # Light Blue - global vars
        Token.Name.Variable.Instance:("#9CDCFE", False, False),  # Light Blue - instance vars
        Token.Name.Constant:      ("#569CD6", False, False),     # Blue - constants
        Token.Name.Attribute:     ("#9CDCFE", False, False),     # Light Blue - attributes
        
        # Strings - VS Code Orange (#CE9178)
        Token.String:             ("#CE9178", False, False),     # Orange - all strings
        Token.String.Affix:       ("#CE9178", False, False),     # Orange - f"", r"", b""
        Token.String.Backtick:    ("#CE9178", False, False),     # Orange - `template`
        Token.String.Char:        ("#CE9178", False, False),     # Orange - char literals
        Token.String.Delimiter:   ("#CE9178", False, False),     # Orange - quotes
        Token.String.Doc:         ("#6A9955", True, True),       # Green ITALIC - docstrings
        Token.String.Double:      ("#CE9178", False, False),     # Orange - "strings"
        Token.String.Escape:      ("#D7BA7D", False, False),     # Light Orange - \n, \t
        Token.String.Heredoc:     ("#CE9178", False, False),     # Orange - heredocs
        Token.String.Interpol:    ("#CE9178", False, False),     # Orange - ${expr}
        Token.String.Other:       ("#CE9178", False, False),     # Orange - other strings
        Token.String.Regex:       ("#D16969", False, False),     # Red-Orange - regex
        Token.String.Single:      ("#CE9178", False, False),     # Orange - 'strings'
        Token.String.Symbol:      ("#569CD6", False, False),     # Blue - symbols
        
        # Numbers - VS Code Light Green (#B5CEA8)
        Token.Number:             ("#B5CEA8", False, False),     # Light Green - all numbers
        Token.Number.Bin:         ("#B5CEA8", False, False),     # Light Green - 0b1010
        Token.Number.Float:       ("#B5CEA8", False, False),     # Light Green - 3.14
        Token.Number.Hex:         ("#B5CEA8", False, False),     # Light Green - 0xFF
        Token.Number.Integer:     ("#B5CEA8", False, False),     # Light Green - 42
        Token.Number.Integer.Long:("#B5CEA8", False, False),     # Light Green - long ints
        Token.Number.Oct:         ("#B5CEA8", False, False),     # Light Green - 0o777
        
        # Operators - VS Code White (#D4D4D4)
        Token.Operator:           ("#D4D4D4", False, False),     # White - + - * / %
        Token.Operator.Word:      ("#569CD6", False, False),     # Blue - and, or, not
        
        # Punctuation - VS Code White (#D4D4D4)
        Token.Punctuation:        ("#D4D4D4", False, False),     # White - brackets, parens
        Token.Punctuation.Marker: ("#D4D4D4", False, False),     # White - semicolons, commas
        
        # Comments - VS Code Green (#6A9955)
        Token.Comment:            ("#6A9955", False, True),      # Green ITALIC - comments
        Token.Comment.Hashbang:   ("#6A9955", False, True),      # Green ITALIC - shebang
        Token.Comment.Multiline:  ("#6A9955", False, True),      # Green ITALIC - /* */
        Token.Comment.Preproc:    ("#6A9955", False, True),      # Green ITALIC - #pragma
        Token.Comment.PreprocFile:("#6A9955", False, True),      # Green ITALIC - includes
        Token.Comment.Single:     ("#6A9955", False, True),      # Green ITALIC - // or #
        Token.Comment.Special:    ("#6A9955", False, True),      # Green ITALIC - special
        
        # Errors - VS Code Red (#F44747)
        Token.Error:              ("#F44747", False, False),     # Red - syntax errors
        
        # Types/Classes - VS Code Teal (#4EC9B0)
        Token.Name.Class:         ("#4EC9B0", False, False),     # Teal - class names
        Token.Name.Decorator:     ("#DCDCAA", False, False),     # Yellow - decorators
        
        # Functions - VS Code Yellow (#DCDCAA)
        Token.Name.Function:      ("#DCDCAA", False, False),     # Yellow - function definitions
        Token.Name.Function.Magic:("#DCDCAA", False, False),     # Yellow - magic methods
        
        # Markup - For HTML/XML/Markdown
        Token.Generic:            ("#D4D4D4", False, False),     # White - generic markup
        Token.Generic.Deleted:    ("#F44747", False, False),     # Red - deleted text
        Token.Generic.Emph:       ("#CE9178", False, True),      # Orange ITALIC - emphasis
        Token.Generic.Error:      ("#F44747", False, False),     # Red - errors
        Token.Generic.Heading:    ("#4EC9B0", False, False),     # Teal - headings
        Token.Generic.Inserted:   ("#4EC9B0", False, False),     # Teal - inserted text
        Token.Generic.Output:     ("#6A9955", False, False),     # Green - program output
        Token.Generic.Prompt:     ("#569CD6", False, False),     # Blue - shell prompt
        Token.Generic.Strong:     ("#D4D4D4", True, False),      # White BOLD - strong
        Token.Generic.Subheading: ("#569CD6", False, False),     # Blue - subheadings
        Token.Generic.Traceback:  ("#F44747", False, False),     # Red - tracebacks
        
        # Literals
        Token.Literal:            ("#569CD6", False, False),     # Blue - literal values
        Token.Literal.Date:       ("#4EC9B0", False, True),      # Teal ITALIC - dates
        Token.Literal.Number:     ("#B5CEA8", False, False),     # Light Green - numbers
        Token.Literal.String:     ("#CE9178", False, False),     # Orange - strings
        
        # Text
        Token.Text:               ("#D4D4D4", False, False),     # White - plain text
        Token.Text.Whitespace:    ("#D4D4D4", False, False),     # White - whitespace
        
        # HTML SPECIFIC - VS Code Colors
        Token.Name.Doctype:       ("#569CD6", False, False),     # Blue - <!DOCTYPE html>
        Token.Name.Entity:        ("#569CD6", False, False),     # Blue - &nbsp; &amp;
        
        # CSS INSIDE <style> - VS Code Colors (Embedded CSS)
        Token.Name.Builtin:       ("#9CDCFE", False, False),     # Light Blue - CSS properties
        Token.Name.Class:         ("#D7BA7D", False, False),     # Yellow-Orange - .class selectors
        Token.Name.Constant:      ("#569CD6", False, False),     # Blue - #id selectors
        Token.Name.Decorator:     ("#D7BA7D", False, False),     # Yellow-Orange - :pseudo-classes
        Token.Name.Function:      ("#DCDCAA", False, False),     # Yellow - calc(), var()
        Token.String:             ("#CE9178", False, False),     # Orange - CSS strings
        Token.String.Other:       ("#CE9178", False, False),     # Orange - url() strings
        Token.Number:             ("#B5CEA8", False, False),     # Light Green - CSS numbers
        Token.Number.Integer:     ("#B5CEA8", False, False),     # Light Green - CSS integers
        Token.Number.Float:       ("#B5CEA8", False, False),     # Light Green - CSS floats
        Token.Operator:           ("#D4D4D4", False, False),     # White - CSS operators
        Token.Punctuation:        ("#D4D4D4", False, False),     # White - CSS punctuation
        
        # JAVASCRIPT INSIDE <script> - VS Code Colors (Embedded JS)
        Token.Name.Builtin:       ("#4EC9B0", False, False),     # Teal - console, window, document
        Token.Name.Function:      ("#DCDCAA", False, False),     # Yellow - function calls
        Token.Name.Variable:      ("#9CDCFE", False, False),     # Light Blue - variables
        Token.String:             ("#CE9178", False, False),     # Orange - JS strings
        Token.String.Regex:       ("#D16969", False, False),     # Red-Orange - /regex/
        Token.Number:             ("#B5CEA8", False, False),     # Light Green - JS numbers
        Token.Number.Integer:     ("#B5CEA8", False, False),     # Light Green - JS integers
        Token.Number.Float:       ("#B5CEA8", False, False),     # Light Green - JS floats
        Token.Operator:           ("#D4D4D4", False, False),     # White - JS operators
        Token.Punctuation:        ("#D4D4D4", False, False),     # White - JS punctuation
        Token.Keyword:            ("#569CD6", False, False),     # Blue - var, let, const, function
        Token.Keyword.Declaration:("#569CD6", False, False),     # Blue - var, let, const
        Token.Keyword.Reserved:   ("#569CD6", False, False),     # Blue - reserved words
        
        # Additional embedded language support
        Token.Name.Exception:     ("#F44747", False, False),     # Red - Error objects (JS)
        Token.Name.Label:         ("#569CD6", False, False),     # Blue - statement labels
        Token.Literal.String.Other: ("#CE9178", False, False),   # Orange - other strings
        Token.Comment:            ("#6A9955", False, True),      # Green Italic - comments
        Token.Comment.Single:     ("#6A9955", False, True),      # Green Italic - single line
        Token.Comment.Multiline:  ("#6A9955", False, True),      # Green Italic - multi-line
        
        # FALLBACK MAPPINGS - Catch-all for any unmapped tokens
        Token.Name.Attribute:     ("#9CDCFE", False, False),     # Light Blue - attributes/properties
        Token.Name.Namespace:     ("#4EC9B0", False, False),     # Teal - namespaces
        Token.Name.Entity:        ("#DCDCAA", False, False),     # Yellow - entities
        Token.Operator.Word:      ("#569CD6", False, False),     # Blue - word operators (and, or)
        Token.Punctuation.Marker: ("#D4D4D4", False, False),     # White - punctuation markers
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
        
        # DEBUG: Print how many formats we're building
        print(f"[Highlighter] Building {len(palette)} format rules for {'dark' if self._is_dark else 'light'} theme")
        
        # Get base font format if available
        base_format = getattr(self, '_base_format', None)
        if base_format:
            base_font = base_format.font()
            print(f"[DEBUG] Base font: {base_font.family()}, size {base_font.pointSize()}")
        
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
            
            # DEBUG: Verify color was set correctly
            if token_type == Token.Keyword:
                print(f"[DEBUG] Keyword format: color={color}, actual_foreground={fmt.foreground().color().name()}, font={fmt.font().family()}")
            
            self._formats[token_type] = fmt
        
        # DEBUG: Verify formats were created
        print(f"[Highlighter] Created formats for {len(self._formats)} token types")
        
        # DEBUG: Show sample of created formats
        if Token.Keyword in self._formats:
            kw_fmt = self._formats[Token.Keyword]
            print(f"[DEBUG] Keyword format stored: {kw_fmt.foreground().color().name()}, font: {kw_fmt.font().family()}")
        if Token.String in self._formats:
            str_fmt = self._formats[Token.String]
            print(f"[DEBUG] String format stored: {str_fmt.foreground().color().name()}, font: {str_fmt.font().family()}")
        
        if len(self._formats) == 0:
            print("[ERROR] No formats created! Check DARK_COLORS dictionary!")

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
        
        # DEBUG: First time only - print lexer info
        if not hasattr(self, '_debug_printed'):
            print(f"\n[Highlighter] === FIRST BLOCK HIGHLIGHTING ===")
            print(f"[Highlighter] Using lexer: {self._lexer.__class__.__name__}")
            print(f"[Highlighter] Language: {self._language}")
            print(f"[Highlighter] Formats available: {len(self._formats)}")
            
            # Show first few token mappings
            print("[DEBUG] Sample token mappings:")
            for i, (tok, fmt) in enumerate(list(self._formats.items())[:3]):
                fg = fmt.foreground()
                color = fg.color().name() if fg else "NO COLOR"
                print(f"  {tok} -> {color}")
            
            self._debug_printed = True
        
        # Performance optimization: cache lexer results
        try:
            tokens = list(lex(text, self._lexer))
            if len(tokens) > 0 and len(text.strip()) > 0:
                print(f"[Highlighter] Tokenized '{text[:40]}...' -> {len(tokens)} tokens")
        except Exception as e:
            # Fallback to plain text if lexing fails
            print(f"[Highlighter] Lex error: {e}")
            return
        
        pos = 0
        tokens_applied = 0
        formats_used = set()
        
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
                # CRITICAL DEBUG: Verify format before applying
                fg = fmt.foreground()
                if not fg or not fg.color():
                    print(f"[ERROR] Format for {token_type} has NO foreground color!")
                else:
                    fg_color = fg.color().name()
                    block_count = getattr(self, '_debug_block_count', 0)
                    if block_count < 3 and token_type == Token.Keyword:
                        print(f"[DEBUG] Applying format: {token_type} -> {fg_color} to text: '{value}'")
                
                # Check if format has font set
                if not fmt.font().family():
                    print(f"[WARNING] Format for {token_type} has no font family!")
                
                self.setFormat(pos, length, fmt)
                tokens_applied += 1
                if fg and fg.color():
                    formats_used.add(fg.color().name())
                else:
                    formats_used.add("NO COLOR")
            pos += length
        
        # DEBUG: Print stats on first few blocks
        if hasattr(self, '_debug_block_count'):
            self._debug_block_count += 1
        else:
            self._debug_block_count = 0
        
        if self._debug_block_count < 10 and len(text.strip()) > 0:
            if tokens_applied == 0:
                print(f"[WARNING] Block {self._debug_block_count}: 0 tokens applied to '{text[:50]}...'")
            else:
                print(f"[DEBUG] Block {self._debug_block_count}: Applied {tokens_applied} tokens, {len(formats_used)} unique colors")
                if self._debug_block_count < 3:
                    print(f"  Colors used: {list(formats_used)[:5]}")
        
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
        
        # DEBUG: Check if viewport has correct colors
        if hasattr(self, 'viewport'):
            vp = self.viewport()
            print(f"[Editor] Viewport Base: {vp.palette().color(QPalette.ColorRole.Base).name()}")
            print(f"[Editor] Viewport Text: {vp.palette().color(QPalette.ColorRole.Text).name()}")

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
        
        # DEBUG: Verify highlighter is active
        print(f"[Editor] Highlighter created: {self._highlighter is not None}")
        print(f"[Editor] Highlighter document: {self._highlighter.document() is not None}")
        print(f"[Editor] Document blocks: {self.document().blockCount()}")

        # Line wrap off
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        
        # DEBUG: Verify colors are actually visible
        print(f"[Editor] After init - Background: {self.palette().color(self.palette().ColorRole.Base).name()}")
        print(f"[Editor] After init - Text: {self.palette().color(self.palette().ColorRole.Text).name()}")

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
        self._lint_timer = QTimer()
        self._lint_timer.setSingleShot(True)
        self._lint_timer.timeout.connect(self._run_linting)
        self.document().contentsChanged.connect(lambda: self._lint_timer.start(800))

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
                
                # Draw Syntax Error Marker (Red Dot)
                error_lines = [e.line for e in self._syntax_errors]
                if line_idx + 1 in error_lines:
                    # Find highest severity error for this line
                    line_errors = [e for e in self._syntax_errors if e.line == line_idx + 1]
                    severity = "error"
                    if any(e.severity == "error" for e in line_errors):
                        color = QColor("#f44747")
                    elif any(e.severity == "warning" for e in line_errors):
                        color = QColor("#cca700")
                        severity = "warning"
                    else:
                        color = QColor("#75beff")
                        severity = "info"
                        
                    painter.setPen(QPen(color, 5))
                    painter.drawPoint(6, top + (self.fontMetrics().height() // 2))

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())

    def _run_linting(self):
        """Analyze code for syntax errors and draw visual markers using core SyntaxChecker."""
        # Determine effective path and language for checking
        path = self._file_path or f"virtual_file.{self._language or 'py'}"
        content = self.toPlainText()
        
        # Run core syntax checker
        result = self._syntax_checker.check_file(path, content)
        self._syntax_errors = result.errors
        
        # DEBUG LOG: Let the user see it's working in the console
        if self._syntax_errors:
            log.info(f"Diagnostics: Found {len(self._syntax_errors)} errors in {path}")
        
        # Clear old lint squiggles while preserving current line highlight
        sels = [s for s in self.extraSelections() if not getattr(s, '_lint', False)]
        
        for err in self._syntax_errors:
            # Create diagnostic squiggle
            s = QTextEdit.ExtraSelection()
            s._lint = True
            fmt = QTextCharFormat()
            
            # Map severity to color
            if err.severity == "error":
                color = QColor("#f44747")
            elif err.severity == "warning":
                color = QColor("#cca700")
            else:
                color = QColor("#75beff")
                
            fmt.setUnderlineColor(color)
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            s.format = fmt
            
            # Use Block-based cursor positioning (more reliable than MoveOperation.Down)
            # Note: line index is 1-based in diagnostics, findBlockByNumber is 0-based
            block = self.document().findBlockByNumber(max(0, err.line - 1))
            if block.isValid():
                cur = QTextCursor(block)
                # Select the specific column or the entire line
                col = max(0, err.column - 1) if err.column > 0 else 0
                
                if col > 0:
                    cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, col)
                    # If it's a syntax error, typically selecting the word under the offset is best
                    cur.select(QTextCursor.SelectionType.WordUnderCursor)
                else:
                    cur.select(QTextCursor.SelectionType.LineUnderCursor)
                
                s.cursor = cur
                sels.append(s)
            
        self.setExtraSelections(sels)
        # FORCE update of both the gutter and the main text area
        self._line_number_area.update()
        self.viewport().update()

    def _highlight_current_line(self):
        extra = []
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

        # Inline edit (Ctrl/Cmd + K)
        if key == Qt.Key.Key_K and (modifiers & Qt.KeyboardModifier.ControlModifier or
                                    modifiers & Qt.KeyboardModifier.MetaModifier):
            self._show_inline_overlay()
            return
        if key == Qt.Key.Key_Escape and self._inline_overlay.isVisible():
            self._hide_inline_overlay()
            return
        
        # Auto-indent on Enter
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
        
        # Tab handling - VS Code style
        if key == Qt.Key.Key_Tab:
            tab_size = self._settings.get("editor", "tab_size") or 4
            
            # Shift+Tab - Outdent
            if modifiers == Qt.KeyboardModifier.ShiftModifier:
                self._outdent_selection(tab_size)
                return
            
            # Tab with selection - Indent multiple lines
            cursor = self.textCursor()
            if cursor.hasSelection():
                self._indent_selection(tab_size)
                return
            
            # No selection - Insert tab as spaces
            self.insertPlainText(" " * tab_size)
            return
        
        super().keyPressEvent(event)
    
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

    def event(self, event):
        """Handle tooltips for syntax errors."""
        from PyQt6.QtWidgets import QToolTip
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.ToolTip:
            # Get line under mouse
            pos = self.viewport().mapFromGlobal(event.globalPos())
            cursor = self.cursorForPosition(pos)
            line_idx = cursor.blockNumber() + 1
            
            # Find errors on this line
            line_errors = [e for e in self._syntax_errors if e.line == line_idx]
            if line_errors:
                tooltip_parts = []
                for err in line_errors:
                    sev_color = "#f44747" if err.severity == "error" else "#cca700"
                    if err.severity == "info": sev_color = "#75beff"
                    
                    header = f"<b style='color:{sev_color}'>{err.severity.upper()}</b>"
                    source = f"<span style='color:#888'> [{err.source}]</span>" if err.source else ""
                    tooltip_parts.append(f"{header}{source}<br/>{err.message}")
                
                QToolTip.showText(event.globalPos(), "<br/><hr/>".join(tooltip_parts), self)
                return True
        return super().event(event)

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
