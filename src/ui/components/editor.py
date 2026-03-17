"""
Code Editor Component — QPlainTextEdit with line numbers, syntax highlighting,
current-line highlight, and auto-indent.
"""

from PyQt6.QtWidgets import QPlainTextEdit, QWidget, QTextEdit, QApplication
from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal
from PyQt6.QtGui import (
    QColor, QPainter, QTextFormat, QFont, QSyntaxHighlighter,
    QTextCharFormat, QKeyEvent, QFontMetrics, QTextOption
)
from pygments import lex
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.token import Token
from src.config.settings import get_settings


# ---------------------------------------------------------------------------
# Pygments-based syntax highlighter
# ---------------------------------------------------------------------------
class PygmentsSyntaxHighlighter(QSyntaxHighlighter):
    DARK_COLORS = {
        Token.Keyword:            ("#c678dd", True, False),
        Token.Keyword.Namespace:  ("#c678dd", True, False),
        Token.Keyword.Type:       ("#e5c07b", False, False),
        Token.Name.Builtin:       ("#e5c07b", False, False),
        Token.Name.Function:      ("#61afef", False, False),
        Token.Name.Class:         ("#e5c07b", False, False),
        Token.Name.Decorator:     ("#c678dd", False, False),
        Token.Name.Tag:           ("#e06c75", True, False),
        Token.Name.Attribute:     ("#d19a66", False, False),
        Token.Name.Variable:      ("#e06c75", False, False),
        Token.Name.Constant:      ("#d19a66", False, False),
        Token.String:             ("#98c379", False, False),
        Token.String.Doc:         ("#5c6370", False, True),
        Token.Comment:            ("#5c6370", False, True),
        Token.Comment.Single:     ("#5c6370", False, True),
        Token.Number:             ("#d19a66", False, False),
        Token.Number.Integer:     ("#d19a66", False, False),
        Token.Number.Float:       ("#d19a66", False, False),
        Token.Operator:           ("#abb2bf", False, False),
        Token.Punctuation:        ("#abb2bf", False, False),
        Token.Name.Exception:     ("#e06c75", False, False),
        Token.Name.Namespace:     ("#e5c07b", False, False),
        Token.Literal.String.Interpol: ("#98c379", False, False),
        Token.Literal.String.Backtick: ("#98c379", False, False),
    }

    LIGHT_COLORS = {
        Token.Keyword:            ("#D73A49", True, False),
        Token.Keyword.Namespace:  ("#D73A49", True, False),
        Token.Keyword.Type:       ("#005CC5", False, False),
        Token.Name.Builtin:       ("#6F42C1", False, False),
        Token.Name.Function:      ("#6F42C1", False, False),
        Token.Name.Class:         ("#005CC5", False, False),
        Token.Name.Decorator:     ("#6F42C1", False, False),
        Token.Name.Tag:           ("#22863A", True, False),
        Token.Name.Attribute:     ("#6F42C1", False, False),
        Token.Name.Variable:      ("#E36209", False, False),
        Token.String:             ("#032F62", False, False),
        Token.String.Doc:         ("#6A737D", False, True),
        Token.Comment:            ("#6A737D", False, True),
        Token.Comment.Single:     ("#6A737D", False, True),
        Token.Number:             ("#005CC5", False, False),
        Token.Operator:           ("#D73A49", False, False),
        Token.Punctuation:        ("#24292E", False, False),
        Token.Name.Exception:     ("#DC3545", False, False),
        Token.Literal.String.Interpol: ("#032F62", False, False),
    }

    def __init__(self, document, language: str = "python", is_dark: bool = True):
        super().__init__(document)
        self._language = language
        self._is_dark = is_dark
        self._lexer = self._get_lexer(language)
        self._formats: dict = {}
        self._build_formats()

    def _get_lexer(self, language: str):
        try:
            return get_lexer_by_name(language, stripall=False)
        except Exception:
            return TextLexer()

    def _build_formats(self):
        palette = self.DARK_COLORS if self._is_dark else self.LIGHT_COLORS
        self._formats.clear()
        for token_type, (color, bold, italic) in palette.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(700 if bold else 400)
            fmt.setFontItalic(italic)
            self._formats[token_type] = fmt

    def set_language(self, language: str):
        self._language = language
        self._lexer = self._get_lexer(language)
        self.rehighlight()

    def set_dark(self, is_dark: bool):
        self._is_dark = is_dark
        self._build_formats()
        self.rehighlight()

    def highlightBlock(self, text: str):
        # Performance safety: skip highlighting for extremely long lines (e.g. minified JS)
        if len(text) > 5000:
            return
            
        combined = self.previousBlockState()
        tokens = list(lex(text, self._lexer))
        pos = 0
        for token_type, value in tokens:
            length = len(value)
            fmt = None
            # Walk token type hierarchy to find matching format
            t = token_type
            while t is not Token and fmt is None:
                fmt = self._formats.get(t)
                t = t.parent if hasattr(t, 'parent') else Token
            if fmt:
                self.setFormat(pos, length, fmt)
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
# Main Code Editor
# ---------------------------------------------------------------------------
class CodeEditor(QPlainTextEdit):
    cursor_position_changed = pyqtSignal(int, int)  # line, col
    content_modified = pyqtSignal()

    def __init__(self, parent=None, language: str = "python"):
        super().__init__(parent)
        self._settings = get_settings()
        self._language = language
        self._is_dark = True

        # Font — guard against invalid size (None/0/-1 from settings)
        font_family = self._settings.get("editor", "font_family") or "Courier New"
        font_size = max(8, int(self._settings.get("editor", "font_size") or 13))
        font = QFont(font_family)
        font.setPointSize(font_size)
        font.setFixedPitch(True)
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

    def set_content(self, text: str, language: str = None):
        if language:
            self._language = language
            self._highlighter.set_language(language)
        self.setPlainText(text)
        self.moveCursor(self.textCursor().MoveOperation.Start)

    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
        self._highlighter.set_dark(is_dark)
        self._highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        char_w = self.fontMetrics().horizontalAdvance('9')
        return char_w * digits + 20

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(),
                                          self._line_number_area.width(), rect.height())
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
                num = str(block.blockNumber() + 1)
                if block.blockNumber() == current_line:
                    painter.setPen(cur_color)
                else:
                    painter.setPen(num_color)
                painter.drawText(
                    0, top,
                    self._line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, num
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())

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

    def _on_cursor_changed(self):
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.cursor_position_changed.emit(line, col)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
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
        # Tab → spaces
        if key == Qt.Key.Key_Tab:
            tab_size = self._settings.get("editor", "tab_size") or 4
            self.insertPlainText(" " * tab_size)
            return
        super().keyPressEvent(event)

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
