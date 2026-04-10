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
    Cursor IDE prefers: Berkeley Mono, Geist Mono
    """
    # Industry-standard programming fonts (priority order)
    # Tier 1: Cursor IDE fonts (Berkeley/Geist Mono)
    # Tier 2: Modern purpose-built coding fonts
    # Tier 3: Classic reliable system fonts
    # Tier 4: Universal fallbacks
    preferred_fonts = [
        # Tier 1: Cursor IDE Premium Fonts (per cursor-ide-design-tokens.md)
        "Berkeley Mono",       # Cursor's marketing font - premium
        "Geist Mono",          # Vercel's font - free alternative to Berkeley
        
        # Tier 2: Premium Programming Fonts (Best for syntax highlighting)
        "JetBrains Mono",      # Best overall - designed for IDEs
        "Fira Code",           # Best ligatures support
        "Source Code Pro",     # Adobe's professional font
        "Cascadia Code",       # Microsoft's modern terminal font
        "Hack",                # Optimized for readability
        
        # Tier 3: Classic Programming Fonts
        "Consolas",            # Windows standard (excellent ClearType)
        "Monaco",              # macOS classic
        "SF Mono",             # Apple's modern system font
        "Roboto Mono",         # Google's material design font
        
        # Tier 4: Reliable Fallbacks
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
    # CURSOR IDE THEME - Anysphere Dark
    # Matches cursor-ide-design-tokens.md §5 exactly
    # Works perfectly with: Python, JS/TS, HTML, CSS, Java, C/C++, Rust, Go, SQL, etc.
    DARK_COLORS = {
        # ============================================
        # CURSOR IDE ANYSPHERE DARK - cursor-ide-design-tokens.md §5
        # Background: #181818, Foreground: #d6d6dd
        # Syntax ref: keyword=#83d6c5, string=#e394dc, function=#efb080,
        #            number=#efb080, class=#87c3ff, attribute=#aaa0fa,
        #            comment=#6d6d6d, operator=#83d6c5, variable=#d6d6dd
        # ============================================
        
        # Keywords - Cursor Teal (#83d6c5)
        Token.Keyword:            ("#83d6c5", False, False),     # Teal - if, def, class, return
        Token.Keyword.Constant:   ("#efb080", False, False),     # Orange - True, False, None (constants)
        Token.Keyword.Declaration:("#83d6c5", False, False),     # Teal - var, let, const declarations
        Token.Keyword.Namespace:  ("#83d6c5", False, False),     # Teal - import, export, package
        Token.Keyword.Reserved:   ("#83d6c5", False, False),     # Teal - reserved words
        Token.Keyword.Type:       ("#87c3ff", False, False),     # Light blue - int, void, string, bool (types)
        
        # Variables & Names
        Token.Name:               ("#d6d6dd", False, False),     # Primary text - default variable names
        Token.Name.Builtin:       ("#87c3ff", False, False),     # Light blue - built-ins (len, print, console)
        Token.Name.Builtin.Pseudo:("#efb080", False, False),     # Orange - self, this, super
        Token.Name.Class:         ("#87c3ff", False, False),     # Light blue - class names (NO bold per Cursor)
        Token.Name.Decorator:     ("#efb080", False, True),      # Orange ITALIC - @decorators
        Token.Name.Entity:        ("#efb080", False, False),     # Orange - HTML entities
        Token.Name.Exception:     ("#f14c4c", False, False),     # Red - exceptions (terminal.ansiRed)
        Token.Name.Function:      ("#efb080", False, False),     # Orange - function names
        Token.Name.Function.Magic:("#efb080", False, False),     # Orange - __magic__ methods
        Token.Name.Label:         ("#87c3ff", False, False),     # Light blue - labels
        Token.Name.Namespace:     ("#87c3ff", False, False),     # Light blue - namespaces
        Token.Name.Other:         ("#87c3ff", False, False),     # Light blue - JS/CSS identifiers
        Token.Name.Property:      ("#d6d6dd", False, False),     # Primary text - object property access
        Token.Name.Tag:           ("#87c3ff", False, False),     # Light blue - HTML/XML tags
        Token.Name.Variable:      ("#d6d6dd", False, False),     # Primary text - variable names
        Token.Name.Variable.Class:("#d6d6dd", False, False),     # Primary text - class vars
        Token.Name.Variable.Global:("#d6d6dd", False, False),    # Primary text - global vars
        Token.Name.Variable.Instance:("#d6d6dd", False, False),  # Primary text - instance vars
        Token.Name.Constant:      ("#efb080", False, False),     # Orange - constants
        Token.Name.Attribute:     ("#aaa0fa", False, False),     # Purple - HTML/JSX attribute.name
        
        # Strings - Cursor Pink (#e394dc)
        Token.String:             ("#e394dc", False, False),     # Pink - all strings
        Token.String.Affix:       ("#83d6c5", False, False),     # Teal - f"", r"", b"" prefixes
        Token.String.Backtick:    ("#e394dc", False, False),     # Pink - `template literals`
        Token.String.Char:        ("#e394dc", False, False),     # Pink - char literals
        Token.String.Delimiter:   ("#e394dc", False, False),     # Pink - quote marks
        Token.String.Doc:         ("#6d6d6d", False, True),      # Gray ITALIC - docstrings (comments)
        Token.String.Double:      ("#e394dc", False, False),     # Pink - "double quoted"
        Token.String.Escape:      ("#efb080", False, False),     # Orange - \n, \t, \\ (escape sequences)
        Token.String.Heredoc:     ("#e394dc", False, False),     # Pink - heredocs
        Token.String.Interpol:    ("#e394dc", False, False),     # Pink - ${expr} interpolations
        Token.String.Other:       ("#e394dc", False, False),     # Pink - other strings
        Token.String.Regex:       ("#efb080", False, False),     # Orange - /regex/
        Token.String.Single:      ("#e394dc", False, False),     # Pink - 'single quoted'
        Token.String.Symbol:      ("#efb080", False, False),     # Orange - symbols
        
        # Numbers - Cursor Orange (#efb080)
        Token.Number:             ("#efb080", False, False),     # Orange - all numbers
        Token.Number.Bin:         ("#efb080", False, False),     # Orange - 0b1010
        Token.Number.Float:       ("#efb080", False, False),     # Orange - 3.14
        Token.Number.Hex:         ("#efb080", False, False),     # Orange - 0xFF
        Token.Number.Integer:     ("#efb080", False, False),     # Orange - 42
        Token.Number.Integer.Long:("#efb080", False, False),     # Orange - long ints
        Token.Number.Oct:         ("#efb080", False, False),     # Orange - 0o777
        
        # Operators - Cursor Teal (#83d6c5)
        Token.Operator:           ("#83d6c5", False, False),     # Teal - =, +, -, == operators
        Token.Operator.Word:      ("#83d6c5", False, False),     # Teal - and, or, not
        
        # Punctuation / Delimiters - Cursor Primary Text (#d6d6dd)
        Token.Punctuation:        ("#d6d6dd", False, False),     # Primary text - brackets, parens, braces
        Token.Punctuation.Marker: ("#d6d6dd", False, False),     # Primary text - semicolons, commas
        
        # Comments - Cursor Gray (#6d6d6d) ITALIC
        Token.Comment:            ("#6d6d6d", False, True),      # Gray ITALIC - comments
        Token.Comment.Hashbang:   ("#6d6d6d", False, True),      # Gray ITALIC - shebang
        Token.Comment.Multiline:  ("#6d6d6d", False, True),      # Gray ITALIC - /* */
        Token.Comment.Preproc:    ("#6d6d6d", False, True),      # Gray ITALIC - #pragma
        Token.Comment.PreprocFile:("#6d6d6d", False, True),      # Gray ITALIC - includes
        Token.Comment.Single:     ("#6d6d6d", False, True),      # Gray ITALIC - // or #
        Token.Comment.Special:    ("#6d6d6d", False, True),      # Gray ITALIC - special
        
        # Errors / Invalid - Cursor Red (#f14c4c) - terminal.ansiRed
        Token.Error:              ("#f14c4c", False, False),     # Red - syntax errors
        
        # Types/Classes - Cursor Light Blue (#87c3ff)
        Token.Type:               ("#87c3ff", False, False),     # Light blue - type names
        
        # Markup - For HTML/XML/Markdown
        Token.Generic:            ("#d6d6dd", False, False),     # Primary text - generic markup
        Token.Generic.Deleted:    ("#f14c4c", False, False),     # Red - deleted text
        Token.Generic.Emph:       ("#e394dc", False, True),      # Pink ITALIC - emphasis
        Token.Generic.Error:      ("#f14c4c", False, False),     # Red - errors
        Token.Generic.Heading:    ("#87c3ff", False, False),     # Light blue - headings (NO bold per Cursor)
        Token.Generic.Inserted:   ("#15ac91", False, False),     # Green - inserted text (terminal.ansiGreen)
        Token.Generic.Output:     ("#6d6d6d", False, False),     # Gray - program output
        Token.Generic.Prompt:       ("#15ac91", False, False),     # Green - shell prompt (terminal.ansiGreen)
        Token.Generic.Strong:       ("#efb080", False, False),     # Orange - strong (NO bold per Cursor)
        Token.Generic.Subheading:   ("#aaa0fa", False, False),     # Purple - subheadings
        Token.Generic.Traceback:    ("#f14c4c", False, False),     # Red - tracebacks (terminal.ansiRed)
        
        # Literals
        Token.Literal:              ("#efb080", False, False),     # Orange - literal values
        Token.Literal.Date:         ("#87c3ff", False, True),      # Light blue ITALIC - dates
        Token.Literal.Number:       ("#efb080", False, False),     # Orange - numbers (embedded JS/CSS)
        Token.Literal.Number.Bin:   ("#efb080", False, False),     # Orange - 0b1010
        Token.Literal.Number.Float: ("#efb080", False, False),     # Orange - 3.14 (embedded JS)
        Token.Literal.Number.Hex:   ("#efb080", False, False),     # Orange - CSS hex colors
        Token.Literal.Number.Integer:   ("#efb080", False, False),  # Orange - CSS values
        Token.Literal.Number.Integer.Long:("#efb080", False, False), # Orange - long ints
        Token.Literal.Number.Oct:   ("#efb080", False, False),     # Orange - 0o777
        Token.Literal.String:       ("#e394dc", False, False),     # Pink - strings (embedded JS)
        Token.Literal.String.Affix: ("#83d6c5", False, False),     # Teal - string prefixes
        Token.Literal.String.Backtick:("#e394dc", False, False),    # Pink - template literals
        Token.Literal.String.Char:  ("#e394dc", False, False),     # Pink - char literals
        Token.Literal.String.Delimiter:("#e394dc", False, False),  # Pink - quote marks
        Token.Literal.String.Doc:   ("#6d6d6d", False, True),      # Gray ITALIC - docstrings (comments)
        Token.Literal.String.Double:("#e394dc", False, False),       # Pink - "double"
        Token.Literal.String.Escape:("#efb080", False, False),      # Orange - escape chars
        Token.Literal.String.Heredoc:("#e394dc", False, False),    # Pink - heredocs
        Token.Literal.String.Interpol:("#e394dc", False, False),    # Pink - interpolation
        Token.Literal.String.Other: ("#e394dc", False, False),      # Pink - other strings
        Token.Literal.String.Regex: ("#efb080", False, False),      # Orange - regex
        Token.Literal.String.Single:("#e394dc", False, False),     # Pink - 'single'
        Token.Literal.String.Symbol:("#efb080", False, False),     # Orange - symbols
        
        # Text
        Token.Text:                 ("#d6d6dd", False, False),     # Primary text - plain text (foreground)
        Token.Text.Whitespace:    ("#163761", False, False),     # Selection bg - whitespace markers
        
        # HTML / XML specific
        Token.Name.Doctype:         ("#83d6c5", False, False),     # Teal - <!DOCTYPE html> (metatag)
    }
    
    # Light theme (VS Code Light+) — Full coverage for all token types
    LIGHT_COLORS = {
        # Keywords
        Token.Keyword:            ("#0000FF", False, False),     # Blue - keywords
        Token.Keyword.Constant:   ("#0000FF", False, False),     # Blue - True, False, None
        Token.Keyword.Declaration:("#0000FF", False, False),     # Blue - var, let, const
        Token.Keyword.Namespace:  ("#0000FF", False, False),     # Blue - import, export
        Token.Keyword.Reserved:   ("#0000FF", False, False),     # Blue - reserved words
        Token.Keyword.Type:       ("#267F99", False, False),     # Teal - int, void, string
        
        # Names
        Token.Name:               ("#001080", False, False),     # Dark Blue - names
        Token.Name.Builtin:       ("#267F99", False, False),     # Teal - built-ins
        Token.Name.Builtin.Pseudo:("#0000FF", False, False),     # Blue - self, this
        Token.Name.Class:         ("#267F99", True, False),      # Teal BOLD - classes
        Token.Name.Decorator:     ("#795E26", False, True),      # Brown ITALIC - decorators
        Token.Name.Entity:        ("#795E26", False, False),     # Brown - entities
        Token.Name.Exception:     ("#A31515", False, False),     # Red - exceptions
        Token.Name.Function:      ("#795E26", False, False),     # Brown - functions
        Token.Name.Function.Magic:("#795E26", False, False),     # Brown - __magic__
        Token.Name.Label:         ("#001080", False, False),     # Dark Blue - labels
        Token.Name.Namespace:     ("#267F99", False, False),     # Teal - namespaces
        Token.Name.Other:         ("#267F99", False, False),     # Teal - JS/CSS identifiers in embedded code
        Token.Name.Property:      ("#795E26", False, False),     # Brown - object property access
        Token.Name.Tag:           ("#800000", False, False),     # Maroon - HTML/XML tags
        Token.Name.Variable:      ("#001080", False, False),     # Dark Blue - variables
        Token.Name.Constant:      ("#0000FF", False, False),     # Blue - constants
        Token.Name.Attribute:     ("#FF0000", False, False),     # Red - attribute.name
        Token.Name.Doctype:       ("#800000", False, False),     # Maroon - DOCTYPE
        
        # Strings
        Token.String:             ("#A31515", False, False),     # Red - strings
        Token.String.Affix:       ("#0000FF", False, False),     # Blue - f"", r""
        Token.String.Doc:         ("#008000", False, True),      # Green ITALIC - docstrings
        Token.String.Escape:      ("#EE0000", False, False),     # Bright Red - escape chars
        Token.String.Regex:       ("#811F3F", False, False),     # Dark Red - regex
        Token.String.Interpol:    ("#001080", False, False),     # Dark Blue - interpolation
        
        # Numbers
        Token.Number:             ("#098658", False, False),     # Green - numbers
        
        # Operators & Punctuation
        Token.Operator:           ("#000000", False, False),     # Black - operators
        Token.Operator.Word:      ("#0000FF", False, False),     # Blue - and, or, not
        Token.Punctuation:        ("#000000", False, False),     # Black - punctuation
        
        # Comments
        Token.Comment:            ("#008000", False, True),      # Green ITALIC - comments
        Token.Comment.Preproc:    ("#808080", False, False),     # Gray - preprocessor
        
        # Errors
        Token.Error:              ("#FF0000", False, False),     # Red - errors
        
        # Types
        Token.Type:               ("#267F99", False, False),     # Teal - type names
        
        # Markup / Markdown
        Token.Generic:            ("#000000", False, False),     # Black - generic
        Token.Generic.Deleted:    ("#A31515", False, False),     # Red - deleted
        Token.Generic.Emph:       ("#000000", False, True),      # Black ITALIC - emphasis
        Token.Generic.Error:      ("#FF0000", False, False),     # Red - errors
        Token.Generic.Heading:    ("#0000FF", True, False),      # Blue BOLD - headings
        Token.Generic.Inserted:   ("#098658", False, False),     # Green - inserted
        Token.Generic.Output:     ("#808080", False, False),     # Gray - output
        Token.Generic.Prompt:     ("#098658", False, False),     # Green - prompt
        Token.Generic.Strong:     ("#000000", True, False),      # Black BOLD - strong
        Token.Generic.Subheading: ("#267F99", True, False),      # Teal BOLD - subheadings
        Token.Generic.Traceback:  ("#FF0000", False, False),     # Red - tracebacks
        
        # Literals & Text
        Token.Literal:            ("#098658", False, False),     # Green - literals
        Token.Literal.Number:     ("#098658", False, False),     # Green - numbers (embedded JS/CSS)
        Token.Literal.Number.Float:("#098658", False, False),    # Green - 3.14
        Token.Literal.Number.Hex: ("#098658", False, False),     # Green - hex colors
        Token.Literal.Number.Integer:("#098658", False, False),  # Green - integers
        Token.Literal.String:     ("#A31515", False, False),     # Red - string literals
        Token.Literal.String.Double:("#A31515", False, False),   # Red - "double"
        Token.Literal.String.Single:("#A31515", False, False),   # Red - 'single'
        Token.Literal.String.Backtick:("#A31515", False, False), # Red - `template`
        Token.Literal.String.Escape:("#EE0000", False, False),   # Bright Red - escape chars
        Token.Text:               ("#000000", False, False),     # Black - plain text
    }
    
    def __init__(self, document, language: str = "python", is_dark: bool = True):
        super().__init__(document)
        self._language = language
        self._is_dark = is_dark
        
        # Set premium programming font
        if is_dark:
            # Cursor IDE theme font settings - 12px editor font
            font_name = get_preferred_programming_font()  # Use module-level function
            self._base_format = QTextCharFormat()
            self._base_format.setFont(QFont(font_name, 12))
        
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
                from pygments.lexers.javascript import TypeScriptLexer
                return TypeScriptLexer()
            elif language.lower() == "css":
                from pygments.lexers.css import CssLexer
                return CssLexer()
            elif language.lower() == "json":
                from pygments.lexers.data import JsonLexer
                return JsonLexer()
            elif language.lower() == "markdown":
                from pygments.lexers.markup import MarkdownLexer
                return MarkdownLexer()
            
            # Fallback to generic lookup (handles all other languages: Java, C++, Go, Rust, etc.)
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
        # Get previous state FIRST (before any early returns)
        prev_state = self.previousBlockState()
        
        if not text:
            # Preserve state through empty lines inside <script>/<style> blocks
            self.setCurrentBlockState(prev_state if prev_state in (0, 1, 2) else 0)
            return
            
        # Performance safety: skip highlighting for extremely long lines (e.g. minified JS)
        if len(text) > 5000:
            # Preserve state even for long lines
            self.setCurrentBlockState(prev_state if prev_state in (0, 1, 2) else 0)
            return
        
        try:
            # For HTML/Vue/JSX with embedded content, use stateful lexing (returns 3-tuples)
            if self._language.lower() in ('html', 'vue', 'jsx', 'tsx'):
                tokens = self._lex_html_with_state(text, prev_state)
                next_state = tokens[-1][2] if tokens else 0
            else:
                # Non-HTML: plain 2-tuple tokens, no state needed
                raw_tokens = list(lex(text, self._lexer))
                tokens = [(t[0], t[1]) for t in raw_tokens]
                next_state = 0
        except Exception:
            self.setCurrentBlockState(0)
            return
        
        pos = 0
        
        for token_entry in tokens:
            token_type = token_entry[0]
            value = token_entry[1]
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
            pos += length
        
        # Store state for next line (1 = inside script, 2 = inside style, 0 = normal)
        self.setCurrentBlockState(next_state)
    
    def _lex_html_with_state(self, text: str, prev_state: int):
        """
        Stateful HTML lexer that properly handles embedded JS/CSS across lines.
        Returns list of (token_type, value, new_state) tuples.
        
        State: 0 = normal HTML, 1 = inside <script>, 2 = inside <style>
        """
        from pygments.lexers.html import HtmlLexer
        from pygments.lexers.javascript import JavascriptLexer
        from pygments.lexers.css import CssLexer
        from pygments import lex
        
        state = prev_state if prev_state in (0, 1, 2) else 0
        text_lower = text.lower()
        
        # Detect state transitions for NEXT line
        new_state = state
        if state == 0:
            # Normal HTML: watch for opening script/style tags
            if '<script' in text_lower:
                # Same-line open+close: <script src="..."></script> — stays HTML
                new_state = 0 if '</script>' in text_lower else 1
            elif '<style' in text_lower:
                new_state = 0 if '</style>' in text_lower else 2
        elif state == 1:
            # Inside <script>: watch for closing tag
            if '</script>' in text_lower:
                new_state = 0
        elif state == 2:
            # Inside <style>: watch for closing tag
            if '</style>' in text_lower:
                new_state = 0
        
        # Determine if this is a transition line (contains opening/closing tags)
        # Transition lines use HtmlLexer so the tag itself is colored correctly.
        # Pure content lines inside script/style always use their own lexer,
        # even if the line contains '<' (e.g. innerHTML template strings).
        is_transition = (
            (state == 0 and ('<script' in text_lower or '<style' in text_lower)) or
            (state == 1 and '</script>' in text_lower) or
            (state == 2 and '</style>' in text_lower)
        )
        
        if state == 1 and not is_transition:
            # Pure JS line inside <script> block — always use JS lexer
            # (even if line contains '<span>' in a template string)
            tokens = list(lex(text, JavascriptLexer()))
        elif state == 2 and not is_transition:
            # Pure CSS line inside <style> block — always use CSS lexer
            tokens = list(lex(text, CssLexer()))
        else:
            # HTML context: opening/closing tags, attributes, or normal markup
            tokens = list(lex(text, HtmlLexer()))
        
        return [(t[0], t[1], new_state) for t in tokens]


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
        
        # Cursor IDE Anysphere Dark theme — matches cursor-ide-design-tokens.md
        bg_color = QColor("#181818")      # editor.background - Cursor IDE dark
        fg_color = QColor("#d6d6dd")      # editor.foreground - Cursor IDE primary text
        
        # CRITICAL: Force Qt to use palette colors
        self.setAutoFillBackground(True)
        
        # Set widget colors via palette (highest priority)
        palette = QPalette()  # Create fresh palette
        palette.setColor(QPalette.ColorRole.Window, bg_color)
        palette.setColor(QPalette.ColorRole.WindowText, fg_color)
        palette.setColor(QPalette.ColorRole.Base, bg_color)      # Text edit background
        palette.setColor(QPalette.ColorRole.Text, fg_color)       # Text color
        palette.setColor(QPalette.ColorRole.AlternateBase, bg_color)  # Alternating rows
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#163761"))  # editor.selectionBackground - Cursor blue
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))  # Selected text - white
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
            
            # Show Java setup notification for first-time Java users
            if language.lower() == 'java':
                self._check_java_setup()
        
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
        gutter_bg = QColor("#181818") if self._is_dark else QColor("#f1f3f4")  # editor.background - Cursor dark
        num_color = QColor("#505050") if self._is_dark else QColor("#6c757d")  # editorLineNumber.foreground
        cur_color = QColor("#ffffff") if self._is_dark else QColor("#212529")  # editorLineNumber.activeForeground

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
                    # Pick highest severity color (Cursor IDE terminal colors)
                    if any(e.severity == "error" for e in line_errs):
                        color = QColor("#f14c4c") # terminal.ansiRed - Error
                    elif any(e.severity == "warning" for e in line_errs):
                        color = QColor("#e5b95c") # terminal.ansiYellow - Warning
                    else:
                        color = QColor("#4c9df3") # terminal.ansiBlue - Info
                        
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
            
            # Map severity to color (Cursor IDE terminal colors)
            color = QColor("#f14c4c") # terminal.ansiRed - Error
            if err.severity == "warning": color = QColor("#e5b95c") # terminal.ansiYellow
            elif err.severity == "info": color = QColor("#4c9df3") # terminal.ansiBlue
                
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
            color = QColor("#292929") if self._is_dark else QColor("#f1f3f4")  # editor.lineHighlightBackground - Cursor
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
        
        # Guide line color — editorIndentGuide.background
        guide_color = QColor("#2a2a2a") if self._is_dark else QColor("#e0e0e0")  # sideBar.border - subtle
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

    def _check_java_setup(self):
        """Check if Java LSP is available and show setup notification if not."""
        import shutil
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication
        
        # Check if jdtls is available in PATH
        jdtls_available = shutil.which("jdtls") is not None
        
        if not jdtls_available:
            # Create custom dialog with selectable text
            dialog = QDialog(self)
            dialog.setWindowTitle("Java Support Required")
            dialog.setMinimumWidth(500)
            
            layout = QVBoxLayout(dialog)
            
            # Title label
            title_label = QLabel("Java language features require setup.")
            title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            layout.addWidget(title_label)
            
            # Instruction label
            inst_label = QLabel("Run these commands in CMD or PowerShell:")
            layout.addWidget(inst_label)
            
            # Warning box for winget not found
            warn_label = QLabel("⚠ If 'winget' not found, run this first:")
            warn_label.setStyleSheet("color: #ff9800; font-size: 12px; font-weight: bold;")
            layout.addWidget(warn_label)
            
            fix_text = QLabel('$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")')
            fix_text.setStyleSheet("background-color: #2d2d2d; padding: 8px; border-radius: 4px; font-family: Consolas, monospace; border-left: 3px solid #ff9800;")
            fix_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(fix_text)
            
            fix_btn = QPushButton("Copy")
            fix_btn.clicked.connect(lambda: QApplication.clipboard().setText('$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")'))
            layout.addWidget(fix_btn)
            
            layout.addSpacing(15)
            
            # Command 1: Java JDK
            cmd1_label = QLabel("1. Install Java 21+ JDK (required by jdtls):")
            layout.addWidget(cmd1_label)
            
            cmd1_text = QLabel("winget install EclipseAdoptium.Temurin.21.JDK")
            cmd1_text.setStyleSheet("background-color: #2d2d2d; padding: 8px; border-radius: 4px; font-family: Consolas, monospace;")
            cmd1_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(cmd1_text)
            
            cmd1_btn = QPushButton("Copy")
            cmd1_btn.clicked.connect(lambda: QApplication.clipboard().setText("winget install EclipseAdoptium.Temurin.21.JDK"))
            layout.addWidget(cmd1_btn)
            
            # Manual download note
            manual_label = QLabel("If winget fails, download from adoptium.net and install manually.")
            manual_label.setStyleSheet("color: #888; font-size: 11px;")
            layout.addWidget(manual_label)
            
            layout.addSpacing(10)
            
            # Command 2: Install Scoop (if not installed)
            cmd2_label = QLabel("2. Install Scoop (package manager):")
            layout.addWidget(cmd2_label)
            
            cmd2_text = QLabel("iwr -useb get.scoop.sh | iex")
            cmd2_text.setStyleSheet("background-color: #2d2d2d; padding: 8px; border-radius: 4px; font-family: Consolas, monospace;")
            cmd2_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(cmd2_text)
            
            cmd2_btn = QPushButton("Copy")
            cmd2_btn.clicked.connect(lambda: QApplication.clipboard().setText("iwr -useb get.scoop.sh | iex"))
            layout.addWidget(cmd2_btn)
            
            layout.addSpacing(10)
            
            # Command 3: Refresh PATH (needed after scoop install)
            cmd3_label = QLabel("3. Refresh PATH (so scoop command works):")
            layout.addWidget(cmd3_label)
            
            cmd3_text = QLabel('$env:Path = [Environment]::GetEnvironmentVariable("Path", "User")')
            cmd3_text.setStyleSheet("background-color: #2d2d2d; padding: 8px; border-radius: 4px; font-family: Consolas, monospace;")
            cmd3_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(cmd3_text)
            
            cmd3_btn = QPushButton("Copy")
            cmd3_btn.clicked.connect(lambda: QApplication.clipboard().setText('$env:Path = [Environment]::GetEnvironmentVariable("Path", "User")'))
            layout.addWidget(cmd3_btn)
            
            layout.addSpacing(10)
            
            # Command 4: JDTLS
            cmd4_label = QLabel("4. Install Eclipse JDT Language Server:")
            layout.addWidget(cmd4_label)
            
            cmd4_text = QLabel("scoop install jdtls")
            cmd4_text.setStyleSheet("background-color: #2d2d2d; padding: 8px; border-radius: 4px; font-family: Consolas, monospace;")
            cmd4_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(cmd4_text)
            
            cmd4_btn = QPushButton("Copy")
            cmd4_btn.clicked.connect(lambda: QApplication.clipboard().setText("scoop install jdtls"))
            layout.addWidget(cmd4_btn)
            
            layout.addSpacing(10)
            
            # Troubleshooting section
            troubleshoot_title = QLabel("Troubleshooting:")
            troubleshoot_title.setStyleSheet("color: #ff9800; font-size: 12px; font-weight: bold;")
            layout.addWidget(troubleshoot_title)
            
            troubleshoot_text = QLabel(
                "• If 'java -version' shows old version → Close & reopen terminal\n"
                "• If 'scoop' not found → Run step 3 (Refresh PATH)\n"
                "• If 'jdtls' not found → Reinstall: scoop uninstall jdtls && scoop install jdtls"
            )
            troubleshoot_text.setStyleSheet("color: #aaa; font-size: 11px;")
            layout.addWidget(troubleshoot_text)
            
            layout.addSpacing(15)
            
            # Complete Guide section
            guide_title = QLabel("Complete Setup Guide:")
            guide_title.setStyleSheet("color: #2196F3; font-size: 12px; font-weight: bold;")
            layout.addWidget(guide_title)
            
            guide_text = QLabel(
                "If PATH is broken (commands not found):\n"
                "$env:Path = [System.Environment]::GetEnvironmentVariable(\"Path\", \"Machine\") + \";\" + [System.Environment]::GetEnvironmentVariable(\"Path\", \"User\")\n\n"
                "Fix Python for scoop (if jdtls install fails):\n"
                "$env:Path = \"C:\\Users\\$env:USERNAME\\OneDrive\\Desktop\\black_box\\venv\\Scripts;$env:Path\"\n\n"
                "Quick Install (copy all at once):\n"
                "1. winget install EclipseAdoptium.Temurin.21.JDK\n"
                "2. iwr -useb get.scoop.sh | iex\n"
                "3. $env:Path = [Environment]::GetEnvironmentVariable(\"Path\", \"User\")\n"
                "4. scoop install jdtls\n"
                "5. Restart IDE"
            )
            guide_text.setStyleSheet("color: #888; font-size: 10px; font-family: Consolas, monospace;")
            guide_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(guide_text)
            
            layout.addSpacing(10)
            
            # Step 5
            step5_label = QLabel("5. Restart Cortex IDE, then open any .java file")
            layout.addWidget(step5_label)
            
            # OK button
            ok_btn = QPushButton("OK")
            ok_btn.clicked.connect(dialog.close)
            layout.addWidget(ok_btn)
            
            dialog.exec()
    
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
