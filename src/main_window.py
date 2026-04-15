"""
Cortex AI Agent IDE — Main Window
Full 3-panel layout: Sidebar | Editor Tabs | AI Chat + Terminal
"""

import os
import sys
import platform
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QTabWidget, QLabel, QPushButton, QStatusBar, QFileDialog,
    QToolBar, QMenuBar, QMessageBox, QInputDialog, QTabBar,
    QFrame, QSizePolicy, QApplication
)
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import Qt, QSize, pyqtSignal, pyqtSlot, QTimer, QRect, QProcessEnvironment, QSignalBlocker, QEventLoop
from PyQt6.QtGui import (QAction, QKeySequence, QIcon, QFont, QPainter, QColor, 
                         QMouseEvent, QCloseEvent, QPixmap)

from src.config.settings import get_settings
from src.config.theme_manager import get_theme_manager
from src.core.project_manager import ProjectManager
from src.core.file_manager import FileManager
from src.core.session_manager import SessionManager
from src.core.codebase_index import get_codebase_index
# Agent bridge - connects Cortex to agent module
try:
    from src.ai.agent_bridge import get_agent_bridge as AIAgent
    HAS_AGENT_BRIDGE = True
except ImportError:
    from src.ai.stub_agent import get_stub_agent as AIAgent  # Fallback stub
    HAS_AGENT_BRIDGE = False


class CodeAnalyzer:
    """Simple prompt builder for AI code actions."""

    def build_explain_prompt(self, code: str, language: str) -> str:
        return f"Explain this {language} code in detail. Break down what each part does and why:\n\n```{language}\n{code}\n```"

    def build_refactor_prompt(self, code: str, language: str) -> str:
        return f"Refactor this {language} code to be cleaner, more efficient, and follow best practices. Explain your changes:\n\n```{language}\n{code}\n```"

    def build_test_prompt(self, code: str, language: str) -> str:
        return f"Write comprehensive unit tests for this {language} code. Include edge cases and error handling:\n\n```{language}\n{code}\n```"

    def build_debug_prompt(self, code: str, error: str, language: str) -> str:
        return f"Help me debug this {language} code. Error: {error}\n\n```{language}\n{code}\n```\n\nWhat's causing this error and how do I fix it?"
# from src.ai.file_edit_tracker import FileEditTracker
from src.core.git_manager import GitManager
from src.ui.components.sidebar import SidebarWidget
from src.ui.components.editor import CodeEditor
from src.ui.components.ai_chat import AIChatWidget
from src.ui.components.xterm_terminal import XTermWidget
from src.ui.components.find_replace import FindReplaceDialog
from src.ui.dialogs.diff_viewer import DiffWindow
from src.utils.icons import make_icon
from src.core.live_server import LiveServer
from src.utils.helpers import detect_language, shorten_path
from src.utils.logger import get_logger
from src.utils.notifications import show_task_complete_notification

try:
    from src.ui.syntax_highlighting_config import (
        UniversalCodeColorizer,
        MarkdownColorizer, 
        DRACULA_COLORS,
        FONTS
    )
    HAS_SYNTAX_HIGHLIGHTING = True
except ImportError:
    HAS_SYNTAX_HIGHLIGHTING = False
    log.warning("Syntax highlighting module not available")

log = get_logger("main_window")


class CleanTabBar(QTabBar):
    """Tab bar that draws a clean × close button instead of Qt's default box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._hovered_tab = -1
        # Inherit theme from parent window if possible
        from src.config.theme_manager import get_theme_manager
        self._is_dark = get_theme_manager().is_dark


    def set_dark(self, is_dark: bool):
        self._is_dark = is_dark
        self.update()

    def mouseMoveEvent(self, event):
        idx = self.tabAt(event.pos())
        if idx != self._hovered_tab:
            self._hovered_tab = idx
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered_tab = -1
        self.update()
        super().leaveEvent(event)

    def tabSizeHint(self, index):
        s = super().tabSizeHint(index)
        s.setHeight(34)
        return s

    def paintEvent(self, event):
        """Draw tabs with a clean × button — theme-aware."""
        from PyQt6.QtGui import QPainter, QColor
        from PyQt6.QtCore import QRect, Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        d = self._is_dark
        # Cursor IDE Anysphere Dark Theme - Tab Colors
        col_sel_bg    = QColor("#181818") if d else QColor("#fafafa")  # editor.background
        col_hover_bg  = QColor("#1f1f1f") if d else QColor("#f0f0f0")  # tab.hoverBackground
        col_normal_bg = QColor("#141414") if d else QColor("#f3f3f3")  # tab.inactiveBackground
        col_accent    = QColor("#228df2") if d else QColor("#0078d4")  # cursor.accent
        col_divider   = QColor("#2a2a2a") if d else QColor("#e5e5e5")  # sideBar.border
        col_sel_fg    = QColor("#ffffff") if d else QColor("#2c2c2c")  # tab.activeForeground
        col_hover_fg  = QColor("#d6d6dd") if d else QColor("#333333")  # editor.foreground
        col_normal_fg = QColor("#6d6d6d") if d else QColor("#616161")  # tab.inactiveForeground
        col_close     = QColor("#f14c4c") if d else QColor("#d73a49")  # RED close button
        col_close_hover = QColor("#ff6b6b") if d else QColor("#ff4444")  # Brighter red on hover

        for i in range(self.count()):
            rect = self.tabRect(i)
            is_selected = (i == self.currentIndex())
            is_hovered  = (i == self._hovered_tab)

            # Background
            if is_selected:
                painter.fillRect(rect, col_sel_bg)
            elif is_hovered:
                painter.fillRect(rect, col_hover_bg)
            else:
                painter.fillRect(rect, col_normal_bg)

            # Accent top border on active tab
            if is_selected:
                painter.fillRect(QRect(rect.x(), rect.y(), rect.width(), 2), col_accent)

            # Right divider
            painter.fillRect(QRect(rect.right(), rect.y() + 4, 1, rect.height() - 8), col_divider)

            # Tab label
            text = self.tabText(i)
            
            # ── Premium Tab Icon ───────────────────────────────────────────────
            icon_x = rect.x() + 10
            icon_size = 14
            
            # Determine icon based on file extension
            filepath = None
            if hasattr(self.parent(), '_files'):
                filepath = self.parent()._files.get(i)
            
            from src.ui.components.sidebar import _get_icon_name
            icon_name = _get_icon_name(filepath) if filepath else "files"
            if text == "Welcome": icon_name = "ai"
            if "Terminal" in text: icon_name = "terminal"
            
            # Cursor IDE Syntax Colors for File Icons
            colors = {
                "python":   "#83d6c5",  # teal - keyword
                "html":     "#87c3ff",  # light blue - class/tag
                "css":      "#87c3ff",  # light blue - class
                "javascript": "#e394dc", # pink - string
                "typescript": "#87c3ff", # light blue - class
                "markdown": "#d6d6dd", # primary text
                "json":     "#efb080",  # orange - number
                "java":     "#83d6c5",  # teal
                "rust":     "#efb080",  # orange
                "go":       "#87c3ff",  # light blue
                "sql":      "#83d6c5",  # teal
                "ai":       "#228df2",  # accent blue
                "terminal": "#6d6d6d"   # muted
            }
            icon_color = colors.get(icon_name, "#abb2bf")
            
            # Using a fallback if terminal icon not found, or use the shell icon
            icon_pixmap = make_icon(icon_name, icon_color, icon_size).pixmap(icon_size, icon_size)
            painter.drawPixmap(icon_x, rect.y() + (rect.height() - icon_size)//2, icon_pixmap)
            
            # Reserve space for close button (14px + 2px right padding)
            btn_reserved = 16  # 14 + 2px right margin
            
            # Label - leave space for close button
            label_x = icon_x + icon_size + 6
            label_width = rect.width() - (label_x - rect.x()) - btn_reserved - 2
            label_rect = QRect(label_x, rect.y(), max(0, label_width), rect.height())
            
            # Draw label with eliding to prevent overflow
            painter.save()
            fg = col_sel_fg if is_selected else (col_hover_fg if is_hovered else col_normal_fg)
            painter.setPen(fg)
            f = painter.font()
            f.setPointSize(9)
            painter.setFont(f)
            # Use elided text to prevent overflow into button area
            from PyQt6.QtGui import QFontMetrics
            fm = QFontMetrics(f)
            elided_text = fm.elidedText(text, Qt.TextElideMode.ElideRight, label_width)
            painter.drawText(label_rect,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             elided_text)
            painter.restore()

            # × close button — ONLY show on hovered or selected tabs
            if is_hovered or is_selected:
                # Fixed position from right edge - 2px padding
                btn_size = 14
                btn_x = rect.right() - btn_size - 2
                btn_y = rect.y() + (rect.height() - btn_size) // 2
                btn_rect = QRect(btn_x, btn_y, btn_size, btn_size)
                
                # Check if cursor is over the × button
                cursor_pos = self.mapFromGlobal(self.cursor().pos())
                is_close_hovered = btn_rect.contains(cursor_pos)

                # Determine colors
                if is_close_hovered:
                    bg_color = QColor("#f14c4c") if d else QColor("#d73a49")  # Red
                    x_color = QColor("#ffffff")  # White X
                else:
                    bg_color = QColor(255, 255, 255, 40) if d else QColor(0, 0, 0, 30)
                    x_color = QColor("#f14c4c") if d else QColor("#d73a49")  # Red X
                
                # CRITICAL: Fill button area with tab background color first
                bg_fill = col_sel_bg if is_selected else col_hover_bg
                painter.fillRect(btn_rect, bg_fill)
                
                # Draw button background
                painter.setBrush(bg_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(btn_rect, 2, 2)
                
                # Draw X centered
                painter.setPen(x_color)
                font = painter.font()
                font.setPointSize(10)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "×")

        painter.end()

    def mousePressEvent(self, event):
        """Handle × button click to close the tab."""
        from PyQt6.QtCore import Qt, QRect
        from PyQt6.QtGui import QMouseEvent
        i = self.tabAt(event.pos())
        if i >= 0:
            # Only check if tab is hovered or selected (matching paint logic)
            is_selected = (i == self.currentIndex())
            is_hovered = (i == self._hovered_tab)
            if is_hovered or is_selected:
                rect = self.tabRect(i)
                btn_size = 14
                btn_x = rect.right() - btn_size - 2  # Match paintEvent
                btn_y = rect.y() + (rect.height() - btn_size) // 2
                btn_rect = QRect(btn_x, btn_y, btn_size, btn_size)
                if btn_rect.contains(event.pos()):
                    self.tabCloseRequested.emit(i)
                    return
        super().mousePressEvent(event)


class ClickableLabel(QLabel):
    """A label that behaves like a button — supports RichText and hover cursor."""
    clicked = pyqtSignal()
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setTextFormat(Qt.TextFormat.RichText)
        
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)



class EditorTabWidget(QTabWidget):
    """Central editor area with tabs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(CleanTabBar(self))
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._close_tab)
        self._files: dict[int, str] = {}   # tab_index -> filepath
        self._modified: set[str] = set()

    def open_diff_tab(self, file_path: str, original: str, modified: str, is_dark: bool = True):
        """Open a read-only diff tab next to the file tab. Tab name: '⟷ filename'."""
        import difflib
        from PyQt6.QtWidgets import QTextBrowser
        from PyQt6.QtGui import QFont
        from pathlib import Path as _P

        file_name = _P(file_path).name
        tab_label = f'⟷ {file_name}'

        # If a diff tab for this file already exists, switch to it
        for idx in range(self.count()):
            if self.tabText(idx) == tab_label:
                self.setCurrentIndex(idx)
                return

        # Build unified diff HTML
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile='Original',
            tofile='Modified',
            n=3
        ))

        bg   = '#1e1e1e' if is_dark else '#ffffff'
        fg   = '#cccccc' if is_dark else '#333333'
        add_bg = 'rgba(46,160,67,0.2)'  if is_dark else 'rgba(46,160,67,0.15)'
        add_fg = '#56d364'              if is_dark else '#1a7f37'
        rem_bg = 'rgba(248,81,73,0.2)' if is_dark else 'rgba(255,129,130,0.15)'
        rem_fg = '#f85149'              if is_dark else '#cf222e'
        info_fg = '#8b949e'             if is_dark else '#6e7781'

        def esc(t): return t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

        parts = [f"<div style='background:{bg};color:{fg};white-space:pre;"
                 f"font-family:\"Cascadia Code\",Consolas,monospace;font-size:13px;line-height:1.5;padding:10px;'>"]

        if not diff_lines:
            parts.append(f"<div style='color:{info_fg};padding:20px;'>No changes detected.</div>")
        else:
            for line in diff_lines:
                line = line.rstrip('\n')
                s = esc(line)
                if line.startswith('+++') or line.startswith('---'):
                    parts.append(f"<div style='color:{info_fg};font-weight:bold;background:rgba(128,128,128,0.1);padding-left:6px;'>{s}</div>")
                elif line.startswith('@@'):
                    parts.append(f"<div style='color:{info_fg};padding-left:6px;margin-top:6px;'>{s}</div>")
                elif line.startswith('+'):
                    parts.append(f"<div style='color:{add_fg};background:{add_bg};padding-left:6px;'>{s}</div>")
                elif line.startswith('-'):
                    parts.append(f"<div style='color:{rem_fg};background:{rem_bg};padding-left:6px;'>{s}</div>")
                else:
                    parts.append(f"<div style='color:{fg};padding-left:6px;'>{s}</div>")
        parts.append('</div>')

        browser = QTextBrowser()
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(False)
        font = QFont('Cascadia Code', 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        browser.setFont(font)
        browser.setStyleSheet(f'background:{bg};border:none;')
        browser.setHtml(''.join(parts))

        idx = self.addTab(browser, tab_label)
        self.setCurrentIndex(idx)

    def open_file(self, filepath: str, content: str, language: str, is_dark: bool = True) -> int:
        """Open a file in a new tab (or switch to existing)."""
        # Check if already open
        for idx, fp in self._files.items():
            if fp == filepath:
                # File already open - check if content matches, if not update it
                editor = self.widget(idx)
                if isinstance(editor, CodeEditor):
                    current_content = editor.toPlainText()
                    if current_content != content:
                        # Content changed, reload it
                        with QSignalBlocker(editor.document()):
                            editor.set_content(content, language, filepath)
                        print(f"[EditorTabs] Updated content for already-open file: {filepath}")
                    else:
                        print(f"[EditorTabs] File already open with same content: {filepath}")
                self.setCurrentIndex(idx)
                return idx
        
        # Create editor
        editor = CodeEditor(language=language)
        
        # Apply current theme to the new editor
        editor.set_theme(is_dark)
        
        # Disconnect the internal document→editor connection temporarily
        # Use blockSignals instead of disconnect to avoid errors
        with QSignalBlocker(editor.document()):
            editor.set_content(content, language, filepath)
        
        # NOW connect OUR handler - anything after this is a user edit
        editor.content_modified.connect(lambda: self._mark_modified(filepath))

        name = Path(filepath).name
        idx = self.addTab(editor, name)
        self._files[idx] = filepath
        self.setCurrentIndex(idx)
        self.setTabToolTip(idx, filepath)
        
        # Set file type icon on tab
        self._set_tab_icon(idx, filepath)
        
        return idx
    
    def _set_tab_icon(self, idx: int, filepath: str):
        """Set the tab icon based on file extension."""
        from PyQt6.QtGui import QIcon, QPixmap
        from pathlib import Path
        
        ext = Path(filepath).suffix.lower()
        icon_map = {
            '.py': 'python.png',
            '.js': 'javascript.png',
            '.ts': 'typescript.png',
            '.jsx': 'javascript.png',
            '.tsx': 'typescript.png',
            '.html': 'html.png',
            '.htm': 'html.png',
            '.css': 'css.png',
            '.json': 'json.png',
            '.md': 'markdown.png',
            '.java': 'java.png',
            '.rs': 'rust.png',
            '.csv': 'csv.png',
            '.env': 'env.png',
        }
        
        icon_file = icon_map.get(ext)
        if icon_file:
            icon_path = Path(__file__).parent / 'assets' / 'icons' / icon_file
            if icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                if not pixmap.isNull():
                    # Scale to appropriate size for tab (16x16)
                    scaled = pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.setTabIcon(idx, QIcon(scaled))

    def _mark_modified(self, filepath: str):
        """Mark file as modified and update tab with white dot."""
        self._modified.add(filepath)
        for idx, fp in self._files.items():
            if fp == filepath:
                name = Path(fp).name
                # Set tab text with white dot (●) prefix
                self.setTabText(idx, f"● {name}")
                # Set tab tooltip to show modified status
                self.setTabToolTip(idx, f"{filepath} (Modified)")
                break
    
    def _mark_saved(self, filepath: str):
        """Mark file as saved and remove dot from tab."""
        self._modified.discard(filepath)
        for idx, fp in self._files.items():
            if fp == filepath:
                name = Path(fp).name
                # Remove dot and restore normal tab text
                self.setTabText(idx, name)
                # Restore normal tooltip
                self.setTabToolTip(idx, filepath)
                break

    def _close_tab(self, index: int):
        """Close tab with save confirmation if modified."""
        widget = self.widget(index)
        filepath = self._files.get(index)
        
        # Check if file has unsaved changes
        if filepath and filepath in self._modified:
            from PyQt6.QtWidgets import QMessageBox
            
            reply = QMessageBox.question(
                self,
                "Save Changes?",
                f"Do you want to save the changes to '{Path(filepath).name}'?",
                QMessageBox.StandardButton.Save | 
                QMessageBox.StandardButton.Discard | 
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                return  # User cancelled - don't close tab
            elif reply == QMessageBox.StandardButton.Save:
                # Save the file before closing
                editor = self.current_editor() if index == self.currentIndex() else None
                if editor:
                    content = editor.get_all_text()
                    try:
                        Path(filepath).write_text(content, encoding='utf-8')
                        self._mark_saved(filepath)
                    except Exception as e:
                        from PyQt6.QtWidgets import QMessageBox
                        QMessageBox.critical(self, "Save Error", f"Failed to save file: {e}")
                        return  # Don't close tab on save error
        
        # Proceed with closing tab
        self.removeTab(index)
        
        # Cleanup files mapping
        new_files = {}
        for old_idx, fp in self._files.items():
            if old_idx == index:
                continue
            new_idx = old_idx if old_idx < index else old_idx - 1
            new_files[new_idx] = fp
        self._files = new_files
        
        if filepath:
            self._modified.discard(filepath)
            
        # If no tabs left, we could show welcome again or just keep it empty
        if self.count() == 0:
            # Maybe tell parent to show welcome? 
            # For now just let it be empty to match VS Code behavior
            pass

    def current_editor(self) -> CodeEditor | None:
        w = self.currentWidget()
        return w if isinstance(w, CodeEditor) else None

    def current_filepath(self) -> str | None:
        return self._files.get(self.currentIndex())

    def save_current(self, file_manager: FileManager) -> bool:
        """Save current file and remove modified indicator."""
        editor = self.current_editor()
        fp = self.current_filepath()
        if not editor or not fp:
            return False
        content = editor.get_all_text()
        ok = file_manager.write(fp, content)
        if ok:
            # Use _mark_saved to properly update tab text and tooltip
            self._mark_saved(fp)
        return ok
    
    def save_file(self, filepath: str, content: str) -> bool:
        """Save a specific file and update its modified state."""
        from pathlib import Path as _Path
        try:
            _Path(filepath).write_text(content, encoding='utf-8')
            self._mark_saved(filepath)
            return True
        except Exception as e:
            print(f"Save error: {e}")
            return False

    def get_open_files(self) -> list[str]:
        return list(self._files.values())

    def close_current_tab(self):
        """Close the currently active tab."""
        current_idx = self.currentIndex()
        if current_idx >= 0:
            self._close_tab(current_idx)

    def close_all_tabs(self):
        """Close all open tabs."""
        while self.count() > 0:
            self._close_tab(0)

    def update_theme(self, is_dark: bool):
        # Update tab bar colours
        if isinstance(self.tabBar(), CleanTabBar):
            self.tabBar().set_dark(is_dark)

        # Update individual editor widgets
        for i in range(self.count()):
            w = self.widget(i)
            if isinstance(w, CodeEditor):
                w.set_theme(is_dark)


class CortexMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        log.info("MainWindow: __init__ START")
        log.info("MainWindow: Initializing managers...")
        self._settings = get_settings()
        self._theme_manager = get_theme_manager()
        self._project_manager = ProjectManager()
        self._file_manager = FileManager()
        self._session_manager = SessionManager()
        self._live_server: Optional[LiveServer] = None  # built-in HTML Live Server
        # Git manager for source control integration
        self._git_manager = GitManager()
        log.info("[GIT] GitManager initialized")
        
        # Agent bridge connects Cortex to agent module
        self._ai_agent = AIAgent(file_manager=self._file_manager)
        if HAS_AGENT_BRIDGE:
            log.info("[AGENT] Agent bridge initialized - full integration active")
        else:
            log.info("[AGENT] Stub agent initialized - bridge not available")
        
        # Phase 1, 2, 3 Integration: TEMPORARILY DISABLED
        # log.info("[INIT] Initializing Phase 1, 2, 3 components...")
        # self._title_generator = get_title_generator(self._ai_agent)
        # self._session_db = get_session_schema_manager()
        # log.info("[OK] Phase 1, 2, 3 components initialized")
        
        # Phase 4 Integration: TEMPORARILY DISABLED
        # log.info("[INIT] Initializing Phase 4 components...")
        # self._todo_manager = get_todo_manager()
        # self._permission_evaluator = get_permission_evaluator()
        # self._github_agent = get_github_agent()
        # log.info("[OK] Phase 4 components initialized")
        
        # NEW: OpenCode Enhancement Integration - TEMPORARILY DISABLED
        # log.info("[INIT] Initializing OpenCode Enhancement Integration...")
        # self._ai_integration = get_ai_integration_layer()
        # log.info("[OK] OpenCode Enhancement Integration initialized")
        
        log.info("[INIT] Legacy AI components disabled - awaiting OpenHands SDK")
        
        # TEMPORARILY DISABLED - FileEditTracker was part of deleted agentic code
        # self._file_tracker = FileEditTracker(self)
        self._file_tracker = None
        
        # Keep diff window (it's UI, not agentic)
        self._diff_window = DiffWindow(self)
        self._codebase_index = None
        self._inline_edit_context = None
        
        # Initialize UI components to None to prevent theme application crashes if build fails
        self._toolbar = None
        self._toolbar_sep = None
        self._toolbar_logo = None
        self._toolbar_btns = []

        try:
            log.info("MainWindow: Building UI...")
            self._build_ui()
            log.info("MainWindow: Building Menu...")
            self._build_menu()
            log.info("MainWindow: Building Toolbar...")
            self._build_toolbar()
            log.info("MainWindow: Building Status Bar...")
            self._build_status_bar()
        except Exception as e:
            log.error(f"UI Build Error: {e}", exc_info=True)
            print(f"UI Build Error: {e}")
            raise  # Re-raise to stop execution

        log.info("MainWindow: Connecting signals...")
        self._connect_signals()
        log.info("MainWindow: Applying initial theme...")
        self._apply_initial_theme()
        log.info("MainWindow: Restoring session...")
        self._restore_session()
        log.info("MainWindow: Initialization complete.")
        log.info("MainWindow: Initialization complete.")

        # Heartbeat to check for event loop hang
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(lambda: None)  # keep event loop alive, no logging
        self._heartbeat_timer.start(2000)

        # Enable drag and drop of folders/files onto the main window
        self.setAcceptDrops(True)

        # Set Window Icon (Title Bar + Taskbar) - BEFORE show() to prevent flash
        # Uses pre-generated taskbar_rounded.png (run generate_icons.py once)
        if getattr(sys, 'frozen', False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_dir = os.path.join(base, "src", "assets", "logo")
        if not os.path.isdir(logo_dir):
            # Fallback: try exe directory
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
            logo_dir = os.path.join(exe_dir, "src", "assets", "logo")
        if not os.path.isdir(logo_dir):
            # Fallback: try _internal directory (PyInstaller onedir)
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
            logo_dir = os.path.join(exe_dir, "_internal", "src", "assets", "logo")
        if not os.path.isdir(logo_dir):
            logo_dir = os.path.join(os.getcwd(), "src", "assets", "logo")

        icon_candidates = [
            os.path.join(logo_dir, "taskbar_rounded.png"),
            os.path.join(logo_dir, "taskbar.png"),
            os.path.join(logo_dir, "taskbar.ico"),
        ]

        icon = QIcon()
        for candidate in icon_candidates:
            if os.path.exists(candidate):
                from PyQt6.QtGui import QPixmap
                from PyQt6.QtCore import Qt
                pm = QPixmap(candidate)
                if not pm.isNull():
                    for sz in [16, 32, 48, 64, 128, 256]:
                        icon.addPixmap(pm.scaled(sz, sz, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    break

        if not icon.isNull():
            self.setWindowIcon(icon)
            # Also set app-level icon for taskbar grouping
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().setWindowIcon(icon)

        # Window geometry
        w = self._settings.get("window", "width") or 1400
        h = self._settings.get("window", "height") or 900
        self.resize(w, h)
        self.setGeometry(100, 100, w, h)
        if self._settings.get("window", "maximized"):
            self.showMaximized()
        else:
            self.show()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.setWindowTitle("Cortex AI Agent")
        central = QWidget()
        self._central = central
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Main horizontal splitter
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left Sidebar ---
        self._sidebar = SidebarWidget(self._file_manager, git_manager=self._git_manager)
        self._sidebar.setMinimumWidth(44)
        self._sidebar.setMaximumWidth(700)
        self._main_splitter.addWidget(self._sidebar)

        # --- Center: Editor + Terminal stacked vertically ---
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 2)  # 2px bottom gap above status bar
        center_layout.setSpacing(0)

        self._center_splitter = QSplitter(Qt.Orientation.Vertical)

        # Editor tabs
        self._editor_tabs = EditorTabWidget()
        self._editor_tabs.setMinimumSize(200, 150)
        self._editor_tabs.show()
        self._center_splitter.addWidget(self._editor_tabs)

        # Terminal tabs
        self._terminal_tabs = QTabWidget()
        self._terminal_tabs.setTabBar(CleanTabBar(self._terminal_tabs))
        self._terminal_tabs.setTabsClosable(True)
        self._terminal_tabs.setDocumentMode(True)
        self._terminal_tabs.setMovable(True)
        self._terminal_tabs.setVisible(True)
        self._terminal_tabs.setMinimumHeight(120)
        self._terminal_tabs.tabCloseRequested.connect(self._close_terminal_tab)
        
        # Add a single terminal (VISIBLE on startup)
        self._new_terminal(show_panel=True)
        
        self._center_splitter.addWidget(self._terminal_tabs)

        self._center_splitter.setSizes([700, 275])
        center_layout.addWidget(self._center_splitter, 1)
        self._main_splitter.addWidget(center_widget)

        # --- Right Panel: AI Chat ---
        self._right_panel = QWidget()
        self._right_panel.setMinimumWidth(50)  # Allow collapsing small
        right_layout = QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._ai_chat = AIChatWidget()
        self._ai_chat.run_command.connect(self._on_ai_run_command)
        self._ai_chat.stop_requested.connect(self._on_ai_stop_requested)
        self._ai_chat.open_file_requested.connect(self._open_file)
        self._ai_chat.accept_file_edit_requested.connect(self._on_accept_file_edit)
        self._ai_chat.reject_file_edit_requested.connect(self._on_reject_file_edit)
        self._ai_chat.open_terminal_requested.connect(self._show_terminal_panel)
        self._ai_chat.run_in_terminal_requested.connect(self._show_terminal_and_run)
        self._ai_chat.set_code_context_callback(self._get_code_context)
        # load_full_chat_requested is handled internally by AIChatWidget now
        self._ai_chat.toggle_autogen_requested.connect(self._on_toggle_autogen)
        right_layout.addWidget(self._ai_chat)
        self._main_splitter.addWidget(self._right_panel)
        
        # Find/Replace Dialog
        self._find_replace_dialog = FindReplaceDialog(self)
        self._find_replace_dialog.find_requested.connect(self._on_find_requested)
        self._find_replace_dialog.replace_requested.connect(self._on_replace_requested)
        self._find_replace_dialog.replace_all_requested.connect(self._on_replace_all_requested)

        # Splitter sizes for 3 panels: sidebar | editor | AI chat
        # VS Code-like defaults: sidebar ~300, AI chat ~350, editor gets the rest
        sidebar_w = 300
        right_w = 475
        total_w = (self._settings.get("window", "width") or 1400)
        center_w = max(300, total_w - sidebar_w - right_w)
        self._main_splitter.setSizes([sidebar_w, center_w, right_w])
        self._main_splitter.setHandleWidth(1)
        # Editor gets most extra space; sidebar and chat grow slowly
        self._main_splitter.setStretchFactor(0, 0)  # sidebar: fixed
        self._main_splitter.setStretchFactor(1, 1)  # editor: stretches
        self._main_splitter.setStretchFactor(2, 0)  # AI chat: fixed
        
        # Limit AI chat panel max width — much more flexible now
        self._right_panel.setMaximumWidth(1200)

        root_layout.addWidget(self._main_splitter, 1)

        # Welcome tab
        self._show_welcome()

    def _show_welcome(self):
        """Show a VS Code-like welcome screen in the editor tabs."""
        from PyQt6.QtWidgets import QScrollArea
        
        # Remove existing welcome tab if present
        for i in range(self._editor_tabs.count()):
            tab_text = self._editor_tabs.tabText(i)
            if tab_text == "Welcome":
                widget = self._editor_tabs.widget(i)
                self._editor_tabs.removeTab(i)
                if widget:
                    widget.deleteLater()
                break
        
        self._welcome_scroll = QScrollArea()
        self._welcome_scroll.setWidgetResizable(True)
        self._welcome_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._welcome_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self._welcome_widget = QWidget()
        welcome = self._welcome_widget
        wlay = QVBoxLayout(welcome)
        wlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlay.setSpacing(20)
        wlay.setContentsMargins(40, 40, 40, 40)

        # Logo and Title
        self._welcome_title = QLabel("🧠 Cortex AI Agent")
        self._welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_title.setObjectName("welcome_title")
        wlay.addWidget(self._welcome_title)

        self._welcome_subtitle = QLabel("Your AI-powered development environment")
        self._welcome_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_subtitle.setObjectName("welcome_subtitle")
        wlay.addWidget(self._welcome_subtitle)

        self._welcome_sep = QFrame()
        self._welcome_sep.setFrameShape(QFrame.Shape.HLine)
        self._welcome_sep.setObjectName("welcome_sep")
        wlay.addWidget(self._welcome_sep)

        # Dynamic Project Info
        self._welcome_project_info = QLabel()
        self._welcome_project_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_project_info.setObjectName("welcome_project_info")
        wlay.addWidget(self._welcome_project_info)
        self._welcome_hints = []
        self._update_welcome_project_info()

        # Quick Actions Section
        quick_actions_label = QLabel("Quick Actions")
        quick_actions_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        quick_actions_label.setObjectName("quick_actions_label")
        wlay.addWidget(quick_actions_label)
        
        hints = [
            ("📂 Open Folder", "File → Open Folder  or  Ctrl+O"),
            ("✨ New Project", "File → New Project"),
            ("📝 New File", "File → New File  or  Ctrl+N"),
        ]
        for icon_title, shortcut in hints:
            row = ClickableLabel(f"<b>{icon_title}</b>   <span class='shortcut'>{shortcut}</span>")
            row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            row.setObjectName("welcome_hint")
            
            # Connect actions
            if icon_title == "✨ New Project":
                row.clicked.connect(self._new_project)
            elif icon_title == "📂 Open Folder":
                row.clicked.connect(self._open_folder_dialog)
            elif icon_title == "📝 New File":
                row.clicked.connect(self._new_file)
                
            wlay.addWidget(row)
            self._welcome_hints.append(row)

        # Recent Projects Section (placeholder for future)
        recent_label = QLabel("Recent")
        recent_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        recent_label.setObjectName("recent_label")
        wlay.addWidget(recent_label)
        
        self._recent_projects_list = QLabel("No recent projects")
        self._recent_projects_list.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._recent_projects_list.setObjectName("recent_projects")
        wlay.addWidget(self._recent_projects_list)

        # Help & Tips Section
        help_label = QLabel("Help & Tips")
        help_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        help_label.setObjectName("help_label")
        wlay.addWidget(help_label)
        
        help_hints = [
            ("🎨 Toggle Theme", "View → Toggle Theme  or  Ctrl+Shift+T"),
            ("⚡ Terminal", "View → Toggle Terminal  or  Ctrl+`"),
            ("🤖 AI Chat", "Type a question in the right panel"),
        ]
        for icon_title, shortcut in help_hints:
            row = ClickableLabel(f"<b>{icon_title}</b>   <span class='shortcut'>{shortcut}</span>")
            row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            row.setObjectName("welcome_hint")
            
            if icon_title == "🎨 Toggle Theme":
                row.clicked.connect(self._toggle_theme)
            elif icon_title == "⚡ Terminal":
                row.clicked.connect(self._toggle_terminal)
                
            wlay.addWidget(row)
            self._welcome_hints.append(row)

        # Add stretch to center content vertically
        wlay.addStretch()

        self._welcome_scroll.setWidget(self._welcome_widget)
        idx = self._editor_tabs.addTab(self._welcome_scroll, "Welcome")
        self._editor_tabs.setCurrentIndex(idx)
        # Apply background immediately so no white flash at startup
        self._apply_welcome_theme(self._theme_manager.is_dark)

    def _apply_welcome_theme(self, is_dark: bool):
        """Style the welcome widget to match the current theme."""
        if not hasattr(self, '_welcome_widget') or self._welcome_widget is None:
            return
        bg = "#1e1e1e" if is_dark else "#ffffff"
        fg = "#d4d4d4" if is_dark else "#1a1a1a"
        hint_fg = "#cccccc" if is_dark else "#333333"
        shortcut_color = "#858585" if is_dark else "#6c757d"
        sep_color = "#3e3e42" if is_dark else "#dee2e6"
        subtitle_color = "#858585" if is_dark else "#6c757d"

        # Base stylesheet with responsive sizing
        sw = self.width()
        # Scale fonts based on window width (min 800, max 1920)
        scale = min(max(sw / 1920.0, 0.6), 1.0)
        title_size = max(int(32 * scale), 18)
        subtitle_size = max(int(16 * scale), 12)
        hint_size = max(int(14 * scale), 11)
        project_size = max(int(14 * scale), 11)

        self._welcome_widget.setStyleSheet(
            f"background-color:{bg}; color:{fg};"
        )
        
        # Use object names for centralized styling
        styles = f"""
            QLabel#welcome_title {{
                font-size: {title_size}px;
                font-weight: bold;
                color: #007acc;
                margin-bottom: 8px;
            }}
            QLabel#welcome_subtitle {{
                font-size: {subtitle_size}px;
                color: {subtitle_color};
                margin-bottom: 12px;
            }}
            QFrame#welcome_sep {{
                color: {sep_color};
                margin: 10px 20%;
            }}
            QLabel#welcome_project_info {{
                font-size: {project_size}px;
                color: {'#c678dd' if is_dark else '#9b30ff'};
                margin: 8px 0 16px 0;
            }}
            QLabel#quick_actions_label,
            QLabel#recent_label,
            QLabel#help_label {{
                font-size: {hint_size + 1}px;
                font-weight: bold;
                color: {fg};
                margin-top: 16px;
                margin-bottom: 8px;
            }}
            ClickableLabel#welcome_hint {{
                font-size: {hint_size}px;
                color: {hint_fg};
                padding: 6px 12px;
                border-radius: 4px;
            }}
            ClickableLabel#welcome_hint:hover {{
                background-color: {'#3e3e42' if is_dark else '#e9ecef'};
            }}
            QLabel#recent_projects {{
                font-size: {hint_size - 1}px;
                color: {subtitle_color};
                padding: 4px 12px;
                font-style: italic;
            }}
        """
        
        if hasattr(self, '_welcome_scroll') and self._welcome_scroll:
            self._welcome_scroll.setStyleSheet(f"background-color:{bg};")
        
        if hasattr(self, '_welcome_title'):
            self._welcome_title.setStyleSheet(f"font-size:{title_size}px; font-weight:bold; color:#007acc;")
        if hasattr(self, '_welcome_subtitle'):
            self._welcome_subtitle.setStyleSheet(f"font-size:{subtitle_size}px; color:{subtitle_color};")
        if hasattr(self, '_welcome_sep'):
            self._welcome_sep.setStyleSheet(f"color:{sep_color}; margin:10px 20%;")
        if hasattr(self, '_welcome_hints'):
            for row in self._welcome_hints:
                row.setStyleSheet(f"font-size:{hint_size}px; color:{hint_fg}; padding:6px 12px; border-radius:4px;")
        if hasattr(self, '_welcome_project_info') and self._welcome_project_info:
            self._welcome_project_info.setStyleSheet(f"font-size:{project_size}px; color:{'#c678dd' if is_dark else '#9b30ff'}; margin: 8px 0;")


    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def _build_menu(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        self._add_action(file_menu, "New File", self._new_file, "Ctrl+N")
        self._add_action(file_menu, "New Project...", self._new_project, "")
        self._add_action(file_menu, "Open File...", self._open_file_dialog, "Ctrl+Shift+O")
        self._add_action(file_menu, "Open Folder...", self._open_folder_dialog, "Ctrl+O")
        file_menu.addSeparator()
        self._add_action(file_menu, "Save", self._save_current, "Ctrl+S")
        self._add_action(file_menu, "Save All", self._save_all, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", self.close, "Alt+F4")

        # Edit
        edit_menu = mb.addMenu("Edit")
        self._add_action(edit_menu, "Undo", self._undo, "Ctrl+Z")
        self._add_action(edit_menu, "Redo", self._redo, "Ctrl+Y")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Cut", lambda: self._current_editor_action("cut"), "Ctrl+X")
        self._add_action(edit_menu, "Copy", lambda: self._current_editor_action("copy"), "Ctrl+C")
        self._add_action(edit_menu, "Paste", lambda: self._current_editor_action("paste"), "Ctrl+V")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Select All", lambda: self._current_editor_action("selectAll"), "Ctrl+A")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Find...", self._show_find, "Ctrl+F")
        self._add_action(edit_menu, "Find and Replace...", self._show_find_replace, "Ctrl+H")
        self._add_action(edit_menu, "Find in Files...", self._find_in_files, "Ctrl+Shift+F")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Rename...", self._rename_file, "F2")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Go to Line...", self._go_to_line, "Ctrl+G")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Toggle Comment", self._toggle_comment, "Ctrl+/")
        self._add_action(edit_menu, "Delete Line", self._delete_line, "Ctrl+Shift+K")
        self._add_action(edit_menu, "Duplicate Line", self._duplicate_line, "Ctrl+Shift+D")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Indent", self._indent_line, "Ctrl+]")
        self._add_action(edit_menu, "Outdent", self._outdent_line, "Ctrl+[")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Move Line Up", self._move_line_up, "Alt+Up")
        self._add_action(edit_menu, "Move Line Down", self._move_line_down, "Alt+Down")

        # Navigation
        nav_menu = mb.addMenu("Navigation")
        self._add_action(nav_menu, "Quick Open File...", self._quick_open, "Ctrl+P")
        self._add_action(nav_menu, "Go to Symbol...", self._go_to_symbol, "Ctrl+Shift+O")
        nav_menu.addSeparator()
        self._add_action(nav_menu, "Close Tab", self._close_current_tab, "Ctrl+W")
        self._add_action(nav_menu, "Close All Tabs", self._close_all_tabs, "Ctrl+Shift+W")
        nav_menu.addSeparator()
        self._add_action(nav_menu, "Next Tab", self._next_tab, "Ctrl+Tab")
        self._add_action(nav_menu, "Previous Tab", self._prev_tab, "Ctrl+Shift+Tab")
        nav_menu.addSeparator()
        self._add_action(nav_menu, "Keyboard Shortcuts Help", self._show_shortcuts_help, "Ctrl+Alt+K")

        # View
        view_menu = mb.addMenu("View")
        self._add_action(view_menu, "Toggle Theme", self._toggle_theme, "Ctrl+Shift+T")
        self._add_action(view_menu, "Toggle Terminal", self._toggle_terminal, "Ctrl+`")
        view_menu.addSeparator()
        self._add_action(view_menu, "Toggle Sidebar", self._toggle_sidebar, "Ctrl+B")
        view_menu.addSeparator()
        self._add_action(view_menu, "Zoom In", self._zoom_in, "Ctrl+=")
        self._add_action(view_menu, "Zoom Out", self._zoom_out, "Ctrl+-")
        self._add_action(view_menu, "Reset Zoom", self._zoom_reset, "Ctrl+0")

        # AI
        ai_menu = mb.addMenu("AI")
        self._add_action(ai_menu, "Explain Code", lambda: self._ai_action("explain"), "Ctrl+Shift+E")
        self._add_action(ai_menu, "Refactor Code", lambda: self._ai_action("refactor"), "Ctrl+Shift+R")
        self._add_action(ai_menu, "Write Tests", lambda: self._ai_action("tests"), "Ctrl+Shift+U")
        self._add_action(ai_menu, "Debug Help", lambda: self._ai_action("debug"), "Ctrl+Shift+D")
        ai_menu.addSeparator()
        
        # Phase 1, 2, 3 Integration: Agent Mode submenu
        mode_menu = ai_menu.addMenu("Agent Mode")
        self._add_action(mode_menu, "Build Mode", lambda: self._set_agent_mode("build"), "")
        self._add_action(mode_menu, "Explore Mode", lambda: self._set_agent_mode("explore"), "")
        self._add_action(mode_menu, "Debug Mode", lambda: self._set_agent_mode("debug"), "")
        self._add_action(mode_menu, "Plan Mode", lambda: self._set_agent_mode("plan"), "")
        ai_menu.addSeparator()
        
        # Phase 3 Integration: Skills and MCP
        self._add_action(ai_menu, "Browse Skills...", self._show_skills_browser, "")
        self._add_action(ai_menu, "MCP Connections...", self._show_mcp_connections, "")
        ai_menu.addSeparator()
        
        # Phase 4 Integration: TODO, Permission, and GitHub
        todo_menu = ai_menu.addMenu("Tasks & TODOs")
        self._add_action(todo_menu, "View Tasks...", self._show_todo_manager, "")
        self._add_action(todo_menu, "Add Task...", self._add_todo_task, "")
        todo_menu.addSeparator()
        self._add_action(todo_menu, "Complete Task", self._complete_todo_task, "")
        
        self._add_action(ai_menu, "Permission Settings...", self._show_permission_settings, "")
        self._add_action(ai_menu, "GitHub Integration...", self._show_github_integration, "")
        ai_menu.addSeparator()
        
        self._add_action(ai_menu, "AI Chat Focus", self._focus_ai_chat, "Ctrl+Shift+A")
        
        # Command Palette
        self._add_action(file_menu, "Command Palette...", self._command_palette, "Ctrl+Shift+P")
        ai_menu.addSeparator()
        self._add_action(ai_menu, "Clear Chat", self._ai_chat.clear_chat, "")

        # Terminal
        term_menu = mb.addMenu("Terminal")
        self._add_action(term_menu, "New Terminal", lambda: self._new_terminal(show_panel=True), "Ctrl+Shift+`")
        self._add_action(term_menu, "Kill Terminal", self._kill_current_terminal, "")
        term_menu.addSeparator()
        self._add_action(term_menu, "Toggle Terminal Panel", self._toggle_terminal, "Ctrl+`")

        # Help
        help_menu = mb.addMenu("Help")
        self._add_action(help_menu, "Keyboard Shortcuts", self._show_keyboard_shortcuts, "F1")
        self._add_action(help_menu, "About Cortex", self._show_about, "")

    def _add_action(self, menu, text, slot, shortcut=""):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        self._toolbar = self.addToolBar("Main")
        tb = self._toolbar
        tb.setMovable(False)
        tb.setIconSize(QSize(28, 28))
        tb.setFixedHeight(50)

        # Logo label
        self._toolbar_logo = QLabel("  🧠  <b style='font-size:16px'>Cortex AI</b>  ")
        self._toolbar_logo.setStyleSheet("font-size:17px; padding:0 10px; letter-spacing:0.5px;")
        tb.addWidget(self._toolbar_logo)

        self._toolbar_sep = QFrame()
        self._toolbar_sep.setFrameShape(QFrame.Shape.VLine)
        self._toolbar_sep.setFixedHeight(30)
        tb.addWidget(self._toolbar_sep)

        self._toolbar_btns = []

        # 1. File / Build Controls
        actions = [
            ("📂", "Open Folder\nCtrl+O",   self._open_folder_dialog),
            ("💾", "Save File\nCtrl+S",     self._save_current),
            ("▶️", "Run Current File  (HTML → Live Server)",      self._run_file),
            ("➕", "New Terminal",          lambda: self._new_terminal(show_panel=True)),
        ]
        for icon, tip, slot in actions:
            btn = QPushButton(icon)
            btn.setToolTip(tip)
            btn.setFixedSize(40, 40)
            btn.clicked.connect(slot)
            self._toolbar_btns.append(btn)
            tb.addWidget(btn)

        tb.addWidget(self._make_spacer())

        # 2. Layout Toggle Controls (VS Code Style) - On the right side
        layout_actions = [
            ("◧", "Toggle Left Sidebar\nCtrl+B", self._toggle_sidebar),
            ("⬒", "Toggle Bottom Panel\nCtrl+`", self._toggle_terminal),
            ("◨", "Toggle AI Chat", self._toggle_ai_chat),
        ]
        for icon, tip, slot in layout_actions:
            btn = QPushButton(icon)
            btn.setToolTip(tip)
            btn.setFixedSize(40, 40)
            btn.clicked.connect(slot)
            # Custom font size for layout icons to make them clear
            btn.setObjectName("layout_btn")
            self._toolbar_btns.append(btn)
            tb.addWidget(btn)

        self._toolbar_sep2 = QFrame()
        self._toolbar_sep2.setFrameShape(QFrame.Shape.VLine)
        self._toolbar_sep2.setFixedHeight(30)
        tb.addWidget(self._toolbar_sep2)

        # 3. Theme toggle button
        self._theme_btn = QPushButton("🌙")
        self._theme_btn.setToolTip("Toggle Theme\nCtrl+Shift+T")
        self._theme_btn.setFixedSize(40, 40)
        self._theme_btn.clicked.connect(self._toggle_theme)
        self._toolbar_btns.append(self._theme_btn)
        tb.addWidget(self._theme_btn)

    def _apply_toolbar_theme(self, is_dark: bool):
        """Apply theme-aware styles to toolbar elements."""
        if not self._toolbar:
            return
            
        border_color = "#3e3e42" if is_dark else "#dee2e6"
        hover_bg = "rgba(255,255,255,0.10)" if is_dark else "rgba(0,0,0,0.06)"
        
        self._toolbar.setStyleSheet(f"""
            QToolBar {{
                spacing: 6px;
                padding: 4px 6px;
                border-bottom: 1px solid {border_color};
            }}
        """)
        self._toolbar_sep.setStyleSheet(f"color:{border_color};")
        self._toolbar_sep2.setStyleSheet(f"color:{border_color};")
        
        fg_color = "#dcdcdc" if is_dark else "#1a1a1a"
        
        btn_style = f"""
            QPushButton {{
                font-size: 22px;
                color: {fg_color};
                border-radius: 6px;
                background: transparent;
                border: none;
                padding: 2px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
            QPushButton:pressed {{
                background: rgba(0,122,204,0.35);
            }}
        """
        for btn in self._toolbar_btns:
            style = btn_style
            if btn.objectName() == "layout_btn":
                style += f" QPushButton {{ font-size: 24px; color: {fg_color}; }}"
            btn.setStyleSheet(style)


    def _make_spacer(self) -> QWidget:
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return spacer

    # ------------------------------------------------------------------
    # Status Bar
    # ------------------------------------------------------------------
    def _build_status_bar(self):
        sb = self.statusBar()
        self._status_file = QLabel("  No file open")
        self._status_cursor = QLabel("Ln 1, Col 1")
        self._status_lang = QLabel("Plain Text")
        self._status_ai = QLabel("AI: Ready")

        for lbl in [self._status_file, self._status_cursor, self._status_lang, self._status_ai]:
            sb.addWidget(lbl)

        sb.addPermanentWidget(QLabel("  Cortex AI Agent v1.0.13  "))

    def _update_status_cursor(self, line: int, col: int):
        self._status_cursor.setText(f"Ln {line}, Col {col}")

    def _update_status_file(self, filepath: str = None):
        if filepath:
            self._status_file.setText(f"  {shorten_path(filepath)}")
            self._status_lang.setText(detect_language(filepath).title())
        else:
            self._status_file.setText("  No file open")
            self._status_lang.setText("Plain Text")

    def _apply_initial_theme(self):
        """Apply the saved (or default) theme to all panels at startup."""
        from PyQt6.QtWidgets import QApplication as _App
        saved = self._settings.theme if hasattr(self._settings, 'theme') else "dark"
        theme_name = saved if isinstance(saved, str) and saved in ("dark", "light") else "dark"
        # Apply theme
        self._theme_manager.apply(theme_name, _App.instance())
        is_dark = theme_name == "dark"
        # Propagate to all panels
        self._ai_chat.set_theme(is_dark)
        self._sidebar.set_theme(is_dark)
        self._apply_welcome_theme(is_dark)
        self._apply_toolbar_theme(is_dark)
        # Theme button label
        if hasattr(self, '_theme_btn') and self._theme_btn:
            self._theme_btn.setText("☀️" if not is_dark else "🌙")
        
        # Apply to editor tabs
        self._editor_tabs.update_theme(is_dark)
        
        # Apply to terminal tab bar
        if isinstance(self._terminal_tabs.tabBar(), CleanTabBar):
            self._terminal_tabs.tabBar().set_dark(is_dark)
        
        # Style the tab widget panels
        tab_bg = "#1e1e1e" if is_dark else "#ffffff"
        tab_border = "#3e3e42" if is_dark else "#dee2e6"
        tab_style = f"""
            QTabWidget::pane {{ border: 1px solid {tab_border}; background: {tab_bg}; }}
            QTabWidget::tab-bar {{ left: 0px; }}
        """
        self._editor_tabs.setStyleSheet(tab_style)
        self._terminal_tabs.setStyleSheet(tab_style)
        
        # Apply to all terminal widgets
        for i in range(self._terminal_tabs.count()):
            term = self._terminal_tabs.widget(i)
            if isinstance(term, XTermWidget):
                term.set_theme(is_dark)
        
        # Apply global syntax highlighting fonts and colors
        self._apply_syntax_highlighting_fonts()

    def _apply_syntax_highlighting_fonts(self):
        """Apply Dracula-themed fonts and colors globally to code displays."""
        if not HAS_SYNTAX_HIGHLIGHTING:
            return
        
        try:
            # Initialize global code colorizer
            self._code_colorizer = UniversalCodeColorizer()
            
            # Apply monospace font (for code editors, terminal)
            mono_fonts = FONTS['mono']
            
            # Apply sans-serif font (for UI elements)
            sans_fonts = FONTS['sans']
            
            # Apply to all code editors
            if hasattr(self, '_code_editor') and self._code_editor:
                code_font = QFont()
                code_font.setFamily(mono_fonts[0])  # Use first preferred monospace font
                code_font.setPointSize(10)
                code_font.setFixedPitch(True)
                self._code_editor.setFont(code_font)
                log.info(f"[FONTS] Applied monospace font to editor: {mono_fonts[0]}")
            
            # Apply to terminal if available
            if hasattr(self, '_terminal') and self._terminal:
                term_font = QFont()
                term_font.setFamily(mono_fonts[0])
                term_font.setPointSize(9)
                term_font.setFixedPitch(True)
                self._terminal.setFont(term_font)
                log.info(f"[FONTS] Applied terminal font: {mono_fonts[0]}")
            
            # Log Dracula theme application
            log.info(f"[COLORS] Dracula theme applied with {len(DRACULA_COLORS)} color definitions")
            log.info(f"[LANGUAGES] 100+ programming languages supported")
            log.info(f"[FRAMEWORKS] React, Vue, Angular, Django, Flask, FastAPI, and 20+ frameworks")
            log.info(f"[MARKDOWN] Blue headings (#0047AB), White text (#ffffff)")
            
            # Display font stack information
            mono_stack = " -> ".join(mono_fonts)
            sans_stack = " -> ".join(sans_fonts)
            log.info(f"[FONT_STACK_MONO] {mono_stack}")
            log.info(f"[FONT_STACK_SANS] {sans_stack}")
            
        except Exception as e:
            log.warning(f"Error applying syntax highlighting fonts: {e}")
    
    def colorize_code(self, code, language='plaintext'):
        """
        Public method to colorize code with Dracula theme.
        Every language gets colors - NO white text fallback.
        """
        if not HAS_SYNTAX_HIGHLIGHTING or not hasattr(self, '_code_colorizer'):
            return code
        
        try:
            return self._code_colorizer.colorize(code, language)
        except Exception as e:
            log.warning(f"Error colorizing code for language '{language}': {e}")
            return code
    
    def colorize_markdown(self, markdown_text):
        """
        Public method to colorize Markdown with blue headings and white text.
        """
        if not HAS_SYNTAX_HIGHLIGHTING:
            return markdown_text
        
        try:
            return MarkdownColorizer.colorize(markdown_text)
        except Exception as e:
            log.warning(f"Error colorizing markdown: {e}")
            return markdown_text

    # ------------------------------------------------------------------
    # Signal Connections
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # Sidebar signals
        self._sidebar.file_opened.connect(self._open_file)
        self._sidebar.file_search_opened.connect(self._open_file_at_line)
        self._sidebar.ai_action_requested.connect(self._ai_action)
        self._sidebar.file_renamed.connect(self._on_sidebar_file_renamed)
        self._sidebar.file_deleted.connect(self._on_sidebar_file_deleted)
        
        # Changed files panel signals
        self._sidebar.file_accepted.connect(self._on_accept_file_edit)
        self._sidebar.file_rejected.connect(self._on_reject_file_edit)
        self._sidebar.accept_all_requested.connect(self._on_accept_all_files)
        self._sidebar.reject_all_requested.connect(self._on_reject_all_files)

        # Project manager
        self._project_manager.project_opened.connect(self._on_project_opened)
        self._project_manager.project_closed.connect(self._on_project_closed)


        # Editor tab changes
        self._editor_tabs.currentChanged.connect(self._on_tab_changed)
        
        # File manager undo/redo signals
        if hasattr(self, '_file_manager'):
            self._file_manager.file_deleted.connect(self._on_file_deleted_for_undo)
            self._file_manager.file_restored.connect(self._on_file_restored_for_redo)

        # AI chat - ONLY connect signals here to avoid duplicates
        self._ai_chat.message_sent.connect(self._on_ai_chat_message)
        self._ai_chat.model_changed.connect(self._on_model_changed)
        self._ai_agent.response_chunk.connect(self._ai_chat.on_chunk)
        self._ai_agent.response_complete.connect(self._ai_chat.on_complete)
        self._ai_agent.response_complete.connect(self._on_ai_task_complete)
        self._ai_agent.request_error.connect(self._ai_chat.on_error)
        self._ai_agent.file_generated.connect(self._open_file)
        # TEMPORARILY DISABLED - file_tracker was part of deleted agentic code
        # self._ai_agent.file_edited_diff.connect(self._file_tracker.add_edit)
        self._ai_agent.file_edited_diff.connect(self._on_file_edited_diff_for_js)
        self._ai_agent.file_edited_diff.connect(self._on_inline_edit_diff)
        self._ai_agent.file_edited_diff.connect(self._ai_chat.on_file_edited_diff)  # populate Changed Files panel with +/- counts
        self._ai_agent.file_edited_diff.connect(self._ai_chat.show_diff_card)       # show diff viewer card in chat
        # File operation cards — animated create/edit cards
        self._ai_agent.file_creating_started.connect(self._on_file_creating_started)
        self._ai_agent.file_editing_started.connect(self._on_file_editing_started)
        self._ai_agent.file_operation_completed.connect(self._on_file_operation_completed)
        self._ai_agent.tool_activity.connect(self._ai_chat.show_tool_activity)
        self._ai_agent.directory_contents.connect(self._ai_chat.show_directory_contents)
        self._ai_agent.directory_contents.connect(self._on_directory_contents_for_tree)
        self._ai_agent.thinking_started.connect(self._ai_chat.show_thinking)
        self._ai_agent.thinking_stopped.connect(self._ai_chat.hide_thinking)
        self._ai_agent.todos_updated.connect(self._ai_chat.update_todos)
        self._ai_agent.tool_summary_ready.connect(self._ai_chat.show_tool_summary)
        # Permission gate: agent → chat UI shows card; user response → agent continues
        self._ai_agent.permission_requested.connect(self._ai_chat._on_permission_request)
        self._ai_chat.permission_decided.connect(self._ai_agent.on_permission_respond)
        
        # Phase 4: TEMPORARILY DISABLED - todo_manager, title_generator were deleted
        # self._todo_manager.task_added.connect(self._on_todo_task_added)
        # self._todo_manager.task_completed.connect(self._on_todo_task_completed)
        # self._todo_manager.task_updated.connect(self._on_todo_task_updated)
        
        # Phase 4: TEMPORARILY DISABLED - title_generator was deleted
        # self._title_generator.title_generated.connect(self._on_title_generated)
        
        # New interaction signals
        self._ai_chat.generate_plan_requested.connect(self._on_generate_plan)
        # TEMPORARILY DISABLED - set_interaction_mode doesn't exist on stub agent
        # self._ai_chat.mode_changed.connect(self._ai_agent.set_interaction_mode)
        self._ai_chat.open_file_requested.connect(self._open_file)
        self._ai_chat.open_file_at_line_requested.connect(self._open_file_at_line)
        log.info(f"[Diff-Debug] Connecting show_diff_requested to _on_show_diff. Signal exists: {hasattr(self._ai_chat, 'show_diff_requested')}")
        self._ai_chat.show_diff_requested.connect(self._on_show_diff)
        self._ai_chat.answer_question_requested.connect(self._ai_agent.user_responded)
        self._ai_chat.smart_paste_check_requested.connect(self._on_smart_paste_check)
        # TEMPORARILY DISABLED - set_always_allowed doesn't exist on stub agent
        # self._ai_chat.always_allow_changed.connect(self._ai_agent.set_always_allowed)
        
        # NEW: TEMPORARILY DISABLED - AI Integration Layer was deleted
        # self._ai_integration.intent_classified.connect(self._on_intent_classified)
        # self._ai_integration.agent_selected.connect(self._on_agent_selected)
        # self._ai_integration.tools_selected.connect(self._on_tools_selected)
        # self._ai_integration.permission_requested.connect(self._on_permission_requested)
        # self._ai_integration.permission_granted.connect(self._on_permission_granted)
        # self._ai_integration.permission_denied.connect(self._on_permission_denied)
        # self._ai_integration.user_denied_workflow.connect(self._on_user_denied_workflow)
        
        # NEW: TEMPORARILY DISABLED - Testing Workflow was deleted
        # self._ai_integration.testing_decision.connect(self._on_testing_decision)
        # self._ai_integration.test_tools_selected.connect(self._on_test_tools_selected)
        # self._ai_integration.test_execution_started.connect(self._on_test_execution_started)
        # self._ai_integration.test_execution_completed.connect(self._on_test_execution_completed)
        # self._ai_integration.test_analysis_ready.connect(self._on_test_analysis_ready)
        
        # NEW: Connect AI Chat permission response signals
        self._ai_chat.permission_response.connect(self._on_chat_permission_response)
        
        # NEW: Connect Todo toggle from UI to TodoManager
        self._ai_chat.toggle_todo_requested.connect(self._on_toggle_todo)
        
        # Connect AI Agent back to UI for interactive questions
        self._ai_agent.user_question_requested.connect(self._on_ai_question_requested)

        # ========== CortexDiffBridge: wire accept/reject signals ==========
        # This connects useDiffInIDE.py's CortexDiffBridge to Cortex's FEC card
        # accept/reject signals so the agent can await user confirmation of edits.
        try:
            import importlib as _il
            _diff_ide_mod = _il.import_module("agent.src.hooks.useDiffInIDE")
            _cdb = _diff_ide_mod.CortexDiffBridge.instance()
            _cdb.register_accept_signal(self._ai_chat.accept_file_edit_requested)
            _cdb.register_reject_signal(self._ai_chat.reject_file_edit_requested)
            log.info("[CortexDiffBridge] Accept/Reject signals wired")
        except Exception as _cdb_err:
            log.warning(f"[CortexDiffBridge] Signal wiring skipped: {_cdb_err}")

        # Terminal tab changes
        self._terminal_tabs.currentChanged.connect(self._on_terminal_tab_changed)
        
        # ========== PERMISSION SYSTEM CONNECTION (NEW) ==========
        # Connect AI agent to UI for permission dialogs
        self._ai_agent.set_ui_parent(self)
        log.info("Permission system initialized and connected to main window")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _new_file(self):
        # Get current theme state and apply it to the new editor
        is_dark = self._theme_manager.is_dark
        editor = CodeEditor(language="python")
        if is_dark:
            editor.apply_dark_theme()
        else:
            editor.apply_light_theme()
        idx = self._editor_tabs.addTab(editor, "untitled.py")
        self._editor_tabs.setCurrentIndex(idx)
        editor.cursor_position_changed.connect(self._update_status_cursor)
        editor.inline_edit_submitted.connect(self._on_inline_edit_submitted)
        editor.inline_edit_cancelled.connect(self._on_inline_edit_cancelled)
        editor.inline_diff_requested.connect(self._on_inline_diff_requested)
        editor.code_copied.connect(self._on_code_copied)

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open File",
                                               str(self._project_manager.root or Path.home()))
        if path:
            self._open_file(path)
    
    def _find_file_in_project(self, filename: str) -> str | None:
        """Search for a file by name in the project directory (recursive)."""
        if not self._project_manager.root:
            return None
        
        # Extract just the filename (remove any directory components)
        from pathlib import Path as PathLib
        clean_filename = PathLib(filename).name
        
        root = Path(self._project_manager.root)
        
        # Search recursively for the file
        try:
            for file_path in root.rglob(clean_filename):
                if file_path.is_file():
                    return str(file_path)
        except Exception:
            pass
        
        return None

    def _open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Folder",
                                                   str(Path.home()))
        if folder:
            self._open_folder_programmatic(folder)

    def _open_folder_programmatic(self, folder: str):
        """Open a folder as the active project (no dialog, usable from argv/drag-drop)."""
        self._project_manager.open(folder)
        try:
            from src.core.lsp_manager import get_lsp_manager
            get_lsp_manager().set_project_root(folder)
        except Exception:
            pass

    def _new_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder for New Project",
                                                   str(Path.home()))
        if folder:
            # For now, just open it as a project. 
            # Could add a template/scaffolding step here later.
            self._project_manager.open(folder)

    def _open_file(self, filepath: str):
        # Normalize path (convert forward slashes to backslashes on Windows)
        filepath = os.path.normpath(filepath)
        path = Path(filepath)
        log.info(f"Opening file: {filepath}")
        
        # If file doesn't exist, try to find it in the project
        if not path.exists() or not path.is_file():
            # Try searching in project directory
            found_path = self._find_file_in_project(path.name)
            if found_path:
                log.info(f"Found file in project: {found_path}")
                path = Path(found_path)
                filepath = str(found_path)
            else:
                log.warning(f"File skip (not found or dir): {filepath}")
                return
        
        # Check file extension for images and documents
        file_ext = path.suffix.lower()
        
        # Handle image files
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.ico', '.tiff', '.tif'}
        if file_ext in image_extensions:
            self._open_image_file(filepath)
            return
        
        # Handle PDF files
        if file_ext == '.pdf':
            self._open_pdf_file(filepath)
            return
        
        # Handle Office documents
        office_extensions = {'.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}
        if file_ext in office_extensions:
            self._open_office_file(filepath)
            return
            
        # Initialize file snapshots dict for diff generation
        if not hasattr(self, '_file_snapshots'):
            self._file_snapshots = {}
        
        if self._file_manager.is_binary(filepath):
            log.info(f"File skip (binary): {filepath}")
            QMessageBox.information(self, "Binary File",
                                    f"'{path.name}' is a binary file and cannot be edited.")
            return
            
        try:
            content = self._file_manager.read(filepath)
            if content is None:
                log.error(f"Failed to read content: {filepath}")
                return
            
            # Store original snapshot for diff generation (only if not already stored)
            # This preserves the FIRST version opened, allowing multiple diffs
            if filepath not in self._file_snapshots:
                self._file_snapshots[filepath] = content
                log.info(f"[Snapshot] Stored initial snapshot: {filepath} ({len(content)} chars)")
            else:
                log.info(f"[Snapshot] Keeping existing snapshot for: {filepath}")
                
            log.info(f"Content read ({len(content)} chars). Detecting language...")
            language = detect_language(filepath)
            log.info(f"Language detected: {language}. Opening index in tabs...")
            
            # Get current theme state and pass it to the editor
            is_dark = self._theme_manager.is_dark
            idx = self._editor_tabs.open_file(filepath, content, language, is_dark)
            
            # Connect cursor signal for the new editor
            editor = self._editor_tabs.widget(idx)
            if isinstance(editor, CodeEditor):
                editor.cursor_position_changed.connect(self._update_status_cursor)
                editor.inline_edit_submitted.connect(self._on_inline_edit_submitted)
                editor.inline_edit_cancelled.connect(self._on_inline_edit_cancelled)
                editor.inline_diff_requested.connect(self._on_inline_diff_requested)
                editor.code_copied.connect(self._on_code_copied)

            self._update_status_file(filepath)
            is_dark = self._theme_manager.is_dark
            if isinstance(editor, CodeEditor):
                # Block content_modified signal during theme set (rehighlight triggers it)
                from PyQt6.QtCore import QSignalBlocker
                with QSignalBlocker(editor.document()):
                    editor.set_theme(is_dark)
            log.info(f"File opened successfully: {filepath}")
        except Exception as e:
            log.error(f"Error opening file {filepath}: {e}", exc_info=True)

    def _open_image_file(self, filepath: str):
        """Open an image file in a viewer tab, scaled to fit window."""
        from PyQt6.QtWidgets import QLabel, QScrollArea
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QPixmap
        
        try:
            log.info(f"Opening image file: {filepath}")
            path = Path(filepath)
            
            # Load image
            pixmap = QPixmap(filepath)
            
            if pixmap.isNull():
                log.error(f"Failed to load image: {filepath}")
                QMessageBox.warning(self, "Error", f"Could not load image: {path.name}")
                return
            
            # Get available size (tab widget size minus some padding)
            tab_size = self._editor_tabs.size()
            max_width = max(tab_size.width() - 40, 400)  # Min 400px width
            max_height = max(tab_size.height() - 80, 300)  # Min 300px height
            
            # Scale image to fit while maintaining aspect ratio
            scaled_pixmap = pixmap.scaled(
                max_width, 
                max_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Create label with scaled image
            image_label = QLabel()
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Create scroll area
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll_area.setWidget(image_label)
            
            # Add to tabs
            idx = self._editor_tabs.addTab(scroll_area, path.name)
            self._editor_tabs.setTabToolTip(idx, filepath)
            self._editor_tabs.setCurrentIndex(idx)
            
            self._update_status_file(filepath)
            log.info(f"Image file opened successfully: {filepath} (scaled to {scaled_pixmap.width()}x{scaled_pixmap.height()})")
            
        except Exception as e:
            log.error(f"Error opening image file {filepath}: {e}", exc_info=True)
            QMessageBox.warning(self, "Error", f"Could not open image: {e}")

    def _open_pdf_file(self, filepath: str):
        """Open a PDF file by rendering pages as images."""
        from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QPixmap, QImage
        import fitz  # PyMuPDF
        
        try:
            log.info(f"Opening PDF file: {filepath}")
            path = Path(filepath)
            
            # Open PDF with PyMuPDF
            doc = fitz.open(filepath)
            
            # Store page count immediately
            total_pages = doc.page_count
            
            if total_pages == 0:
                QMessageBox.warning(self, "Error", "PDF has no pages")
                return
            
            # Create scrollable container for all pages
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setSpacing(10)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Get available width
            tab_width = self._editor_tabs.width() - 60
            
            # Render each page as an image
            for page_num in range(min(total_pages, 50)):  # Limit to 50 pages
                page = doc[page_num]
                
                # Calculate zoom to fit width
                zoom = tab_width / page.rect.width
                mat = fitz.Matrix(zoom, zoom)
                
                # Render page to pixmap
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to QImage
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(img)
                
                # Create label for page
                label = QLabel()
                label.setPixmap(pixmap)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setStyleSheet("background-color: white; border: 1px solid #ccc;")
                
                layout.addWidget(label)
            
            doc.close()
            
            # Create scroll area
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(container)
            scroll.setStyleSheet("background-color: #f0f0f0;")
            
            # Add to tabs
            idx = self._editor_tabs.addTab(scroll, path.name)
            self._editor_tabs.setTabToolTip(idx, f"{filepath} ({total_pages} pages)")
            self._editor_tabs.setCurrentIndex(idx)
            
            self._update_status_file(filepath)
            log.info(f"PDF file opened successfully: {filepath} ({total_pages} pages)")
            
        except ImportError:
            log.error("PyMuPDF (fitz) not installed")
            QMessageBox.warning(self, "Error", "PyMuPDF not installed. Run: pip install PyMuPDF")
        except Exception as e:
            log.error(f"Error opening PDF file {filepath}: {e}", exc_info=True)
            QMessageBox.warning(self, "Error", f"Could not open PDF: {e}")

    def _open_office_file(self, filepath: str):
        """Open Office documents (Word, Excel, PowerPoint) inside the IDE as formatted text."""
        from PyQt6.QtWidgets import QTextEdit
        from PyQt6.QtCore import Qt
        
        try:
            log.info(f"Opening Office file: {filepath}")
            path = Path(filepath)
            file_ext = path.suffix.lower()
            
            # Create text viewer
            text_viewer = QTextEdit()
            text_viewer.setReadOnly(True)
            text_viewer.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            
            content_html = ""
            
            if file_ext in ['.docx']:
                # Read Word document
                try:
                    from docx import Document
                    doc = Document(filepath)
                    
                    content_html = f"<h2>{path.name}</h2><hr>"
                    
                    for para in doc.paragraphs:
                        if para.text.strip():
                            # Check if it's a heading based on style
                            if para.style.name.startswith('Heading'):
                                content_html += f"<h3>{para.text}</h3>"
                            else:
                                content_html += f"<p>{para.text}</p>"
                    
                    # Add tables
                    for table in doc.tables:
                        content_html += "<table border='1' cellpadding='5'>"
                        for row in table.rows:
                            content_html += "<tr>"
                            for cell in row.cells:
                                content_html += f"<td>{cell.text}</td>"
                            content_html += "</tr>"
                        content_html += "</table><br>"
                    
                except ImportError:
                    content_html = f"<p style='color:red'>Error: python-docx library not installed.<br>Install with: pip install python-docx</p>"
                    log.error("python-docx library not installed")
                except Exception as e:
                    content_html = f"<p style='color:red'>Error reading document: {e}</p>"
                    log.error(f"Error reading docx: {e}")
            
            elif file_ext in ['.xlsx', '.xls']:
                # Read Excel document
                try:
                    if file_ext == '.xlsx':
                        import openpyxl
                        wb = openpyxl.load_workbook(filepath, data_only=True)
                        sheetnames = wb.sheetnames
                        
                        content_html = f"<h2>{path.name}</h2><hr>"
                        
                        for sheet_name in sheetnames:
                            sheet = wb[sheet_name]
                            content_html += f"<h3>Sheet: {sheet_name}</h3>"
                            content_html += "<table border='1' cellpadding='5' style='border-collapse:collapse'>"
                            
                            # Read first 100 rows max
                            row_count = 0
                            for row in sheet.iter_rows(max_row=100):
                                content_html += "<tr>"
                                for cell in row:
                                    value = cell.value if cell.value is not None else ""
                                    content_html += f"<td>{value}</td>"
                                content_html += "</tr>"
                                row_count += 1
                                if row_count >= 100:
                                    content_html += "<tr><td colspan='100'>... (showing first 100 rows)</td></tr>"
                                    break
                            
                            content_html += "</table><br>"
                    
                    elif file_ext == '.xls':
                        import xlrd
                        wb = xlrd.open_workbook(filepath)
                        
                        content_html = f"<h2>{path.name}</h2><hr>"
                        
                        for sheet_idx in range(wb.nsheets):
                            sheet = wb.sheet_by_index(sheet_idx)
                            content_html += f"<h3>Sheet: {sheet.name}</h3>"
                            content_html += "<table border='1' cellpadding='5' style='border-collapse:collapse'>"
                            
                            # Read first 100 rows max
                            for row_idx in range(min(sheet.nrows, 100)):
                                content_html += "<tr>"
                                for col_idx in range(sheet.ncols):
                                    value = sheet.cell_value(row_idx, col_idx)
                                    content_html += f"<td>{value}</td>"
                                content_html += "</tr>"
                            
                            if sheet.nrows > 100:
                                content_html += "<tr><td colspan='100'>... (showing first 100 rows)</td></tr>"
                            
                            content_html += "</table><br>"
                    
                except ImportError as e:
                    content_html = f"<p style='color:red'>Error: Required library not installed.<br>Install with: pip install openpyxl xlrd</p>"
                    log.error(f"Library not installed: {e}")
                except Exception as e:
                    content_html = f"<p style='color:red'>Error reading spreadsheet: {e}</p>"
                    log.error(f"Error reading xlsx/xls: {e}")
            
            elif file_ext == '.doc':
                # Old Word format - try to extract text
                try:
                    # Try using textract if available
                    import textract
                    text = textract.process(filepath).decode('utf-8', errors='ignore')
                    content_html = f"<h2>{path.name}</h2><hr>"
                    content_html += f"<pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>{text}</pre>"
                except ImportError:
                    content_html = f"""<p style='color:orange'>
                        <b>Old Word Format (.doc)</b><br><br>
                        This file uses the older .doc format which requires additional libraries.<br><br>
                        <b>Options:</b><br>
                        1. Convert to .docx format (open in Word and Save As .docx)<br>
                        2. Install textract: <code>pip install textract</code><br>
                        3. Open externally with Microsoft Word
                    </p>"""
                    log.warning(f"Old .doc format not supported without textract: {filepath}")
                except Exception as e:
                    content_html = f"<p style='color:red'>Error reading .doc file: {e}</p>"
                    log.error(f"Error reading doc: {e}")
            
            else:
                content_html = f"<p>File type '{file_ext}' is not supported for internal viewing.</p>"
            
            # Set content with styling
            text_viewer.setHtml(f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; padding: 20px; line-height: 1.6; }}
                    h2 {{ color: #333; border-bottom: 2px solid #0078d4; padding-bottom: 10px; }}
                    h3 {{ color: #555; margin-top: 20px; }}
                    table {{ margin: 10px 0; border: 1px solid #ddd; }}
                    td {{ padding: 8px; border: 1px solid #ddd; }}
                    p {{ margin: 10px 0; }}
                </style>
            </head>
            <body>
                {content_html}
            </body>
            </html>
            """)
            
            # Add to tabs
            idx = self._editor_tabs.addTab(text_viewer, path.name)
            self._editor_tabs.setTabToolTip(idx, filepath)
            self._editor_tabs.setCurrentIndex(idx)
            
            self._update_status_file(filepath)
            log.info(f"Office file opened internally: {filepath}")
            
        except Exception as e:
            log.error(f"Error opening Office file {filepath}: {e}", exc_info=True)
            QMessageBox.warning(self, "Error", f"Could not open document: {e}")


    def _diff_cache_path(self):
        try:
            from pathlib import Path
            return Path.home() / ".cortex" / "diff_cache.json"
        except Exception:
            return None

    def _load_diff_cache(self):
        if hasattr(self, '_diff_cache'):
            return self._diff_cache
        self._diff_cache = {}
        try:
            cache_path = self._diff_cache_path()
            if cache_path and cache_path.exists():
                import json
                self._diff_cache = json.loads(cache_path.read_text(encoding='utf-8')) or {}
        except Exception:
            self._diff_cache = {}
        return self._diff_cache

    def _save_diff_cache(self):
        try:
            cache_path = self._diff_cache_path()
            if not cache_path:
                return
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            cache_path.write_text(json.dumps(self._diff_cache), encoding='utf-8')
        except Exception:
            pass

    def _on_show_diff(self, file_path: str):
        """Show diff in Qt dialog window — triggered by Diff button click in chat."""
        log.info(f"[Diff] _on_show_diff called with: {file_path}")
        original, modified = '', ''

        # 1. Try the Python diff data store (most reliable)
        import os
        import subprocess
        from pathlib import Path
        normalized_requested = os.path.normcase(os.path.normpath(file_path))
        
        if hasattr(self, '_diff_data_store'):
            # Direct check
            if file_path in self._diff_data_store:
                original, modified = self._diff_data_store[file_path]
                log.info(f"[Diff] Found in _diff_data_store (direct): {file_path}")
            else:
                # Iterative normalized check
                log.debug(f"[Diff] Checking normalized path for: {normalized_requested}")
                for k, v in self._diff_data_store.items():
                    if os.path.normcase(os.path.normpath(k)) == normalized_requested:
                        original, modified = v
                        log.info(f"[Diff] Found in _diff_data_store (normalized): {k}")
                        break

        # 2b. Fallback to persisted diff cache
        if not modified:
            cache = self._load_diff_cache()
            cached = None
            if cache:
                norm = os.path.normcase(os.path.normpath(file_path))
                cached = cache.get(file_path) or cache.get(norm)
                if not cached:
                    # try to find by normalized keys
                    for k, v in cache.items():
                        if os.path.normcase(os.path.normpath(k)) == norm:
                            cached = v
                            break
            if cached:
                original = cached.get('original', '')
                modified = cached.get('modified', '')
                log.info(f"[Diff] Found in diff cache: {file_path}")
        # 3. Fallback to file_tracker
        if not modified:
            edit_info = self._file_tracker.get_edit(file_path)
            if edit_info:
                original = edit_info.original_content if edit_info.edit_type != 'C' else ''
                modified = edit_info.new_content
                log.info(f"[Diff] Found in file_tracker: {file_path}")

        if not modified:
            # Fallback: try Git diff against HEAD if repository available
            try:
                project_root = getattr(self, '_project_manager', None).root if hasattr(self, '_project_manager') else None
                if project_root and os.path.isdir(os.path.join(project_root, '.git')) and os.path.exists(file_path):
                    rel_path = os.path.relpath(file_path, project_root)
                    # Try to load original from HEAD (tracked files)
                    git_show = subprocess.run(
                        ['git', '-C', project_root, 'show', f'HEAD:{rel_path}'],
                        capture_output=True, text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    if git_show.returncode == 0:
                        original = git_show.stdout
                        modified = Path(file_path).read_text(encoding='utf-8', errors='replace')
                        log.info(f"[Diff] Loaded diff via git for: {file_path}")
                    else:
                        # If untracked, treat original as empty
                        git_ls = subprocess.run(
                            ['git', '-C', project_root, 'ls-files', '--error-unmatch', rel_path],
                            capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        if git_ls.returncode != 0:
                            original = ''
                            modified = Path(file_path).read_text(encoding='utf-8', errors='replace')
                            log.info(f"[Diff] Loaded diff for untracked file: {file_path}")
            except Exception as _ge:
                log.debug(f"[Diff] Git fallback failed: {_ge}")

        # Final fallback: Use file snapshot taken when opened
        if not modified and hasattr(self, '_file_snapshots') and file_path in self._file_snapshots:
            original = self._file_snapshots[file_path]
            try:
                modified = Path(file_path).read_text(encoding='utf-8', errors='replace')
                if original != modified:
                    log.info(f"[Diff] Using file snapshot for diff: {file_path}")
                else:
                    log.info(f"[Diff] File unchanged since opened: {file_path}")
                    original = ''
                    modified = ''
            except Exception as e:
                log.warning(f"[Diff] Failed to read current file content: {e}")
                original = ''
                modified = ''

        if not modified:
            log.warning(f"[Diff] No diff data found for {file_path}")
            log.debug(f"[Diff] _diff_data_store keys: {list(getattr(self, '_diff_data_store', {}).keys())}")
            if hasattr(self, '_ai_chat'):
                import os
                filename = os.path.basename(file_path)
                self._ai_chat.add_system_message(f"⚠️ No diff data available for {filename}. It was not edited in this session.")
            return

        log.info(f"[Diff] Opening diff tab for {file_path} (+{len(modified)} chars)")
        is_dark = self._theme_manager.is_dark
        self._editor_tabs.open_diff_tab(file_path, original, modified, is_dark)

    def _on_inline_edit_submitted(self, prompt: str, selection_text: str, line_range: tuple):
        editor = self._editor_tabs.currentWidget()
        if not isinstance(editor, CodeEditor):
            self._ai_chat.add_system_message("Open a file to use inline edit.")
            return

        file_path = self._editor_tabs.current_filepath()
        if not file_path:
            self._ai_chat.add_system_message("Open a file to use inline edit.")
            return

        start_line, end_line = line_range
        if start_line == end_line:
            line_range_text = f"{start_line}"
        else:
            line_range_text = f"{start_line}-{end_line}"

        rel_path = file_path
        project_root = self._project_manager.root
        if project_root:
            try:
                rel_path = str(Path(file_path).resolve().relative_to(Path(project_root).resolve()))
            except Exception:
                rel_path = file_path

        self._inline_edit_context = {
            "file_path": os.path.normpath(file_path),
            "relative_path": rel_path,
            "line_range": line_range,
            "selection_text": selection_text,
            "editor": editor,
            "diff": None,
        }

        self._ai_chat.add_system_message(
            f"Inline edit: `{rel_path}` lines {line_range_text}"
        )
        self._ai_chat._add_ai_bubble_streaming()

        inline_prompt = (
            "Inline edit request.\n"
            f"File (project-relative): {rel_path}\n"
            f"Selection lines: {line_range_text}\n"
            "Selected code:\n"
            "```\n"
            f"{selection_text}\n"
            "```\n"
            "Instruction:\n"
            f"{prompt}\n\n"
            "Constraints:\n"
            "- Apply changes only within the selection unless absolutely required.\n"
            "- Use file editing tools (prefer replace_lines) to update the file.\n"
            "- Do not modify other files.\n"
            "- Use the project-relative path above.\n"
        )
        self._ai_agent.chat(inline_prompt)

    def _on_inline_edit_cancelled(self):
        self._inline_edit_context = None

    def _on_inline_diff_requested(self):
        context = self._inline_edit_context or {}
        file_path = context.get("file_path")
        if not file_path:
            return

        diff_pair = context.get("diff")
        if diff_pair:
            original, modified = diff_pair
            is_dark = self._theme_manager.is_dark
            self._editor_tabs.open_diff_tab(file_path, original, modified, is_dark)
            return

        self._on_show_diff(file_path)

    def _on_inline_edit_diff(self, file_path: str, original: str, new_content: str):
        context = self._inline_edit_context
        if not context:
            return

        target = context.get("file_path")
        if not target:
            return

        if os.path.normcase(os.path.normpath(file_path)) != os.path.normcase(os.path.normpath(target)):
            return

        editor = context.get("editor")
        if not isinstance(editor, CodeEditor):
            return

        import difflib

        diff_lines = list(difflib.unified_diff(
            original.splitlines(),
            new_content.splitlines(),
            fromfile="Original",
            tofile="Modified",
            lineterm=""
        ))
        if not diff_lines:
            diff_text = "No changes detected."
        else:
            max_lines = 200
            if len(diff_lines) > max_lines:
                diff_lines = diff_lines[:max_lines]
                diff_lines.append("... (diff truncated)")
            diff_text = "\n".join(diff_lines)

        context["diff"] = (original, new_content)
        editor.show_inline_diff(diff_text)

    def _on_file_edited_diff_for_js(self, file_path: str, original: str, new_content: str):
        """Store diff data in Python dict for the Qt dialog viewer."""
        if not hasattr(self, '_diff_data_store'):
            self._diff_data_store = {}
        norm_path = os.path.normcase(os.path.normpath(file_path))
        self._diff_data_store[file_path] = (original, new_content)
        self._diff_data_store[norm_path] = (original, new_content)
        # Persist to diff cache for cross-session diff viewing
        cache = self._load_diff_cache()
        cache[file_path] = {
            'original': original,
            'modified': new_content,
            'ts': int(__import__('time').time())
        }
        # Prune cache to last 100 entries
        if len(cache) > 100:
            items = sorted(cache.items(), key=lambda kv: kv[1].get('ts', 0), reverse=True)
            self._diff_cache = dict(items[:100])
        else:
            self._diff_cache = cache
        self._save_diff_cache()
        log.info(f"[Diff] Stored diff data for: {file_path} (original: {len(original)} chars, new: {len(new_content)} chars)")
        log.debug(f"[Diff] _diff_data_store now has {len(self._diff_data_store)} entries")

        # Update sidebar changed files panel
        try:
            edit_type = "C" if not original else "M"
            self._sidebar.add_changed_file(file_path, edit_type)
        except Exception as e:
            log.debug(f"Sidebar update skipped: {e}")

    # ============================================================
    # FILE OPERATION CARDS (Create/Edit with animation)
    # ============================================================
    
    def _on_file_creating_started(self, file_path: str):
        """Show 'Creating file...' card with pulse animation."""
        try:
            card_id = self._ai_chat.show_file_creating_card(file_path)
            if not hasattr(self, '_file_op_cards'):
                self._file_op_cards = {}
            self._file_op_cards[file_path] = card_id
            log.debug(f"[FileOp] Started creating card ({card_id}) for: {file_path}")
        except Exception as e:
            log.debug(f"[FileOp] Failed to show creating card: {e}")

    def _on_file_editing_started(self, file_path: str):
        """Show 'Editing file...' card with pulse animation."""
        try:
            card_id = self._ai_chat.show_file_editing_card(file_path)
            if not hasattr(self, '_file_op_cards'):
                self._file_op_cards = {}
            self._file_op_cards[file_path] = card_id
            log.debug(f"[FileOp] Started editing card ({card_id}) for: {file_path}")
        except Exception as e:
            log.debug(f"[FileOp] Failed to show editing card: {e}")

    def _on_file_operation_completed(self, _unused_card_id: str, file_path: str, content: str, op_type: str):
        """Transform operation card to show completed file."""
        try:
            # Use the card_id stored when the card was first created (from show_file_*_card)
            # The card_id from agent_bridge is different — it was generated before the JS card was made.
            real_card_id = getattr(self, '_file_op_cards', {}).get(file_path)
            if not real_card_id:
                log.debug(f"[FileOp] No stored card_id for {file_path}, skipping completion")
                return
            if op_type == "create":
                self._ai_chat.complete_file_creating_card(real_card_id, file_path, content)
            else:
                original = ""
                if hasattr(self, '_diff_data_store') and file_path in self._diff_data_store:
                    original, _ = self._diff_data_store[file_path]
                self._ai_chat.complete_file_editing_card(real_card_id, file_path, original, content)
            # Clean up stored card_id
            self._file_op_cards.pop(file_path, None)
            log.debug(f"[FileOp] Completed {op_type} card for: {file_path}")
        except Exception as e:
            log.debug(f"[FileOp] Failed to complete operation card: {e}")

    def _on_ai_question_requested(self, tool_call_id: str, question: str, metadata: dict):
        """Handle AI asking a question that requires user response in chat."""
        log.info(f"AI requested user input: {question[:50]}...")
        # Structuring the question info for the JS UI
        # CRITICAL: Use permission_request_id if available (for permission cards),
        # otherwise fall back to tool_call_id (for general questions)
        request_id = metadata.get("permission_request_id", tool_call_id)
        info = {
            "id": request_id,
            "text": question,
            "type": metadata.get("type", "text"),
            "choices": metadata.get("choices", []),
            "default": metadata.get("default", ""),
            "details": metadata.get("details", "")
        }
        self._ai_chat.show_question(info)

    def _open_file_at_line(self, file_path: str, line_number: int):
        """Open file and navigate to specific line."""
        # First open the file
        self._open_file(file_path)
        
        # Get the current editor
        editor = self._editor_tabs.currentWidget()
        if isinstance(editor, CodeEditor):
            # Navigate to line (0-indexed in Scintilla, but 1-indexed for users)
            line_index = max(0, line_number - 1)
            editor.setCursorPosition(line_index, 0)
            editor.ensureLineVisible(line_index)
            log.info(f"Navigated to line {line_number} in {file_path}")

    def _on_accept_file_edit(self, file_path: str):
        """Accept AI edit — the file is already written to disk, just acknowledge."""
        if file_path == "__ALL__":
            self._on_accept_all_files()
            return
        file_path = os.path.normpath(file_path)
        log.info(f"[Accept] User accepted edit: {file_path}")

        # Open/refresh the file in the editor so the user sees the accepted state
        self._open_file(file_path)
        self.statusBar().showMessage(f"✓ Accepted changes to {Path(file_path).name}", 3000)

        # Clean up tracking state
        if hasattr(self, '_diff_data_store'):
            norm = os.path.normcase(file_path)
            self._diff_data_store.pop(file_path, None)
            self._diff_data_store.pop(norm, None)
        if hasattr(self, '_file_snapshots'):
            self._file_snapshots.pop(file_path, None)

        self._sidebar.remove_changed_file(file_path)

    def _on_reject_file_edit(self, file_path: str):
        """Reject AI edit — write original content back to disk and reload editor."""
        if file_path == "__ALL__":
            self._on_reject_all_files()
            return
        file_path = os.path.normpath(file_path)
        log.info(f"[Reject] User rejected edit: {file_path}")

        original = self._get_original_content(file_path)

        if original is not None:
            try:
                Path(file_path).write_text(original, encoding='utf-8')
                log.info(f"[Reject] Reverted {file_path} ({len(original)} chars)")
            except Exception as e:
                log.error(f"[Reject] Failed to revert {file_path}: {e}")
                self.statusBar().showMessage(f"✗ Revert failed for {Path(file_path).name}: {e}", 5000)
                return

            # Reload in editor so editor shows the reverted content
            self._open_file(file_path)
            self.statusBar().showMessage(f"↩ Reverted {Path(file_path).name} to original", 3000)
        else:
            # No original found — just open the file so user can review manually
            log.warning(f"[Reject] No original content for {file_path} — opening for review")
            self._open_file(file_path)
            self.statusBar().showMessage(
                f"⚠ No original content found for {Path(file_path).name} — review manually", 5000
            )

        # Clean up tracking state
        if hasattr(self, '_diff_data_store'):
            norm = os.path.normcase(file_path)
            self._diff_data_store.pop(file_path, None)
            self._diff_data_store.pop(norm, None)
        if hasattr(self, '_file_snapshots'):
            self._file_snapshots.pop(file_path, None)

        self._sidebar.remove_changed_file(file_path)

    def _get_original_content(self, file_path: str) -> Optional[str]:
        """
        Look up the original (pre-AI-edit) content for a file.
        Priority: _diff_data_store → _file_snapshots → diff_cache.json
        """
        norm = os.path.normcase(os.path.normpath(file_path))

        # 1. In-memory diff store (most reliable — set by _on_file_edited_diff_for_js)
        if hasattr(self, '_diff_data_store'):
            for key, (original, _modified) in self._diff_data_store.items():
                if os.path.normcase(os.path.normpath(key)) == norm:
                    if original:  # empty string means new file
                        return original

        # 2. File snapshot taken when file was first opened
        if hasattr(self, '_file_snapshots'):
            for key, content in self._file_snapshots.items():
                if os.path.normcase(os.path.normpath(key)) == norm:
                    return content

        # 3. Persisted diff cache
        try:
            cache = self._load_diff_cache()
            for key, entry in cache.items():
                if os.path.normcase(os.path.normpath(key)) == norm:
                    orig = entry.get('original', '')
                    if orig:
                        return orig
        except Exception:
            pass

        return None
    
    def _on_load_full_chat_requested(self, conversation_id: str):
        """Load full chat messages from SQLite database."""
        log.info(f"Loading full chat: {conversation_id}")
        
        try:
            # Load from SQLite via bridge
            full_chat_json_str = self._ai_chat.load_full_chat_from_sqlite(conversation_id)
            
            if full_chat_json_str and full_chat_json_str != "[]":
                log.info(f"Loaded {len(full_chat_json_str)} chars of chat data")
                # Send back to JavaScript
                self._ai_chat._view.page().runJavaScript(
                    f"window.handleFullChatLoad('{conversation_id}', {full_chat_json_str});"
                )
                self.statusBar().showMessage(f"✓ Loaded chat history", 2000)
            else:
                log.warning(f"No chat data found for: {conversation_id}")
                self._ai_chat._view.page().runJavaScript(
                    f"window.handleFullChatLoad('{conversation_id}', null);"
                )
        except Exception as e:
            log.error(f"Failed to load full chat: {e}")
            self._ai_chat._view.page().runJavaScript(
                f"window.handleFullChatLoad('{conversation_id}, null);"
            )

    def _on_accept_all_files(self):
        """Accept all pending AI edits — files already on disk, just clean up state."""
        log.info("[Accept All] User accepted all file edits")
        # Refresh each tracked file in editor
        for file_path in list(getattr(self, '_diff_data_store', {}).keys()):
            try:
                norm = os.path.normpath(file_path)
                if os.path.isfile(norm):
                    self._open_file(norm)
            except Exception:
                pass
        if hasattr(self, '_diff_data_store'):
            self._diff_data_store.clear()
        if hasattr(self, '_file_snapshots'):
            self._file_snapshots.clear()
        self.statusBar().showMessage("✓ Accepted all changes", 3000)
        self._sidebar.clear_changed_files()

    def _on_reject_all_files(self):
        """Reject all pending AI edits — revert each file to its original content."""
        log.info("[Reject All] User rejected all file edits")
        reverted, failed = 0, 0
        for file_path in list(getattr(self, '_diff_data_store', {}).keys()):
            try:
                norm = os.path.normpath(file_path)
                original = self._get_original_content(norm)
                if original is not None and os.path.isfile(norm):
                    Path(norm).write_text(original, encoding='utf-8')
                    self._open_file(norm)
                    reverted += 1
                    log.info(f"[Reject All] Reverted {norm}")
                else:
                    failed += 1
            except Exception as e:
                log.error(f"[Reject All] Failed to revert {file_path}: {e}")
                failed += 1
        if hasattr(self, '_diff_data_store'):
            self._diff_data_store.clear()
        if hasattr(self, '_file_snapshots'):
            self._file_snapshots.clear()
        msg = f"↩ Reverted {reverted} file(s)"
        if failed:
            msg += f" ({failed} could not be reverted)"
        self.statusBar().showMessage(msg, 5000)
        self._sidebar.clear_changed_files()

    def _on_code_copied(self, text: str, file_path: str, start_line: int, end_line: int):
        """Store copy metadata so smart paste can use it after focus changes."""
        self._last_copy_info = {
            'text': text,
            'file_path': file_path,
            'start_line': start_line,
            'end_line': end_line,
        }

    def _on_smart_paste_check(self, pasted_text: str):
        """Check if pasted text matches last editor copy. Send result to chat."""
        try:
            import json as _json

            # Use stored copy metadata (captured at Ctrl+C time, before focus changed)
            copy_info = getattr(self, '_last_copy_info', None)
            if not copy_info or not copy_info.get('text'):
                self._ai_chat._view.page().runJavaScript(
                    "handleSmartPasteResult({isMatch: false});"
                )
                return

            def normalize(text):
                return '\n'.join(line.strip() for line in text.strip().split('\n') if line.strip())

            pasted_norm = normalize(pasted_text)
            copied_norm = normalize(copy_info['text'])

            if not copied_norm or not pasted_norm:
                self._ai_chat._view.page().runJavaScript(
                    "handleSmartPasteResult({isMatch: false});"
                )
                return

            is_match = (pasted_norm == copied_norm or
                        pasted_norm in copied_norm or
                        copied_norm in pasted_norm)

            if is_match and copy_info.get('file_path'):
                file_path  = copy_info['file_path']
                start_line = copy_info['start_line']
                end_line   = copy_info['end_line']
                file_name  = os.path.basename(file_path)
                ext        = os.path.splitext(file_path)[1].lstrip('.')
                line_range = str(start_line) if start_line == end_line else f"{start_line}-{end_line}"

                self._ai_chat._view.page().runJavaScript(
                    f"handleSmartPasteResult({{isMatch: true, "
                    f"filePath: {_json.dumps(file_path)}, "
                    f"fileName: {_json.dumps(file_name)}, "
                    f"lineRange: {_json.dumps(line_range)}, "
                    f"code: {_json.dumps(pasted_text)}, "
                    f"language: {_json.dumps(ext)}}});"
                )
                log.info(f"Smart paste matched: {file_name} lines {line_range}")
                # Clear after use so next paste starts fresh
                self._last_copy_info = None
                return

            self._ai_chat._view.page().runJavaScript(
                "handleSmartPasteResult({isMatch: false});"
            )

        except Exception as e:
            log.error(f"Smart paste check error: {e}")
            self._ai_chat._view.page().runJavaScript(
                "handleSmartPasteResult({isMatch: false});"
            )

    # ============================================================================
    # NEW: OpenCode Enhancement Integration Handlers
    # ============================================================================
    
    def _on_intent_classified(self, message: str, intent: str, confidence: float):
        """Handle intent classification from AI Integration Layer."""
        log.info(f"[Intent] {intent} (confidence: {confidence:.2f}): {message[:50]}...")
        # Could update UI to show detected intent
        
    def _on_agent_selected(self, agent_type: str, reason: str, confidence: float):
        """Handle agent selection from AI Integration Layer."""
        log.info(f"[Agent] Selected {agent_type} (confidence: {confidence:.2f}): {reason}")
        # Could show agent indicator in UI
        
    def _on_tools_selected(self, tool_names: list):
        """Handle tool selection from AI Integration Layer."""
        log.info(f"[Tools] Selected: {', '.join(tool_names)}")
        # Could show tool indicators in UI
        
    def _on_permission_requested(self, request_id: str, html_card: str):
        """Handle permission request - show permission card in chat."""
        log.info(f"[Permission] Request {request_id} - showing permission card")
        
        # Show permission card in AI chat
        if hasattr(self._ai_chat, 'show_permission_card'):
            self._ai_chat.show_permission_card(request_id, html_card)
        else:
            # Fallback: add as system message
            self._ai_chat.add_system_message("🔒 Permission required. Please check the chat interface.")
            
    def _on_permission_granted(self, request_id: str, scope: str):
        """Handle permission grant."""
        log.info(f"[Permission] Granted {request_id} with scope {scope}")
        
        # Retry the AI processing now that permission is granted
        # Get the last user message and retry
        if hasattr(self._ai_chat, '_last_user_message'):
            message = self._ai_chat._last_user_message
            context = []
            
            if self._project_manager.root:
                context.append(f"Project path: {self._project_manager.root}")
            
            editor = self._editor_tabs.current_editor()
            if editor:
                fp = self._editor_tabs.current_filepath()
                if fp:
                    name = Path(fp).name
                    content = editor.get_all_text()
                    if len(content) > 5000:
                        content = content[:5000] + "... (truncated)"
                    context.append(f"Current file ({name}):\n```\n{content}\n```")
            
            full_context = "\n\n".join(context)
            
            # NEW: Check if we have enhancement data stored
            enhancement_data = self._ai_agent.get_last_enhancement_data()
            if enhancement_data.get("intent"):
                log.info("Retrying with chat_with_enhancement after permission grant")
                self._ai_agent.chat_with_enhancement(
                    message,
                    intent=enhancement_data["intent"],
                    route=enhancement_data["route"],
                    tools=enhancement_data["tools"],
                    code_context=full_context
                )
            else:
                self._ai_agent.chat(message, full_context)
            
    def _on_permission_denied(self, request_id: str, reason: str):
        """Handle permission denial."""
        log.info(f"[Permission] Denied {request_id}: {reason}")
        self._ai_chat.add_system_message(f"❌ Permission denied: {reason}")
        
    def _on_chat_permission_response(self, request_id: str, approved: bool, scope: str = "session", remember: bool = False):
        """Handle permission response from chat UI."""
        log.info(f"Chat permission response: {request_id}, approved={approved}, scope={scope}, remember={remember}")
        
        # Convert permission_request_id to tool_call_id format for agent.user_responded
        # The request_id from permission card is actually the permission_request_id (UUID)
        # But agent.user_responded expects tool_call_id
        # We need to find which pending tool this belongs to by searching _pending_tool_results
        tool_call_id_match = None
        if hasattr(self._ai_agent, '_pending_tool_results'):
            for res in self._ai_agent._pending_tool_results:
                # Check if this result's metadata has the matching permission_request_id
                metadata = res.get("metadata", {})
                if metadata.get("permission_request_id") == request_id:
                    tool_call_id_match = res.get("tool_call_id")
                    log.info(f"Matched permission {request_id} to tool_call_id {tool_call_id_match}")
                    break
        
        if approved:
            # Use _ai_agent instead of removed _ai_integration
            if hasattr(self._ai_agent, 'grant_permission'):
                self._ai_agent.grant_permission(request_id, scope, remember)
            
            # If we found the matching tool_call_id, trigger user_responded with "allow"
            if tool_call_id_match:
                response_str = f"allow:{scope}" if scope else "allow"
                if remember:
                    response_str = f"always:{scope}" if scope else "always"
                log.info(f"Auto-responding to pending tool: {tool_call_id_match} with {response_str}")
                self._ai_agent.user_responded(response_str)
        else:
            # Use _ai_agent instead of removed _ai_integration
            if hasattr(self._ai_agent, 'deny_permission'):
                self._ai_agent.deny_permission(request_id, "User denied via UI")
            
            # If we found the matching tool_call_id, trigger user_responded with "deny"
            if tool_call_id_match:
                log.info(f"Auto-responding to pending tool: {tool_call_id_match} with deny")
                self._ai_agent.user_responded(tool_call_id_match, "deny")
    
    def _on_user_denied_workflow(self, tool_name: str):
        """Handle user denying workflow twice - stop AI agent."""
        log.warning(f"User denied {tool_name} twice - stopping AI agent")
        
        # Stop the AI agent immediately
        self._ai_agent.stop()
        
        # Add system message explaining what happened
        self._ai_chat.add_system_message(
            f"⏹️ **Workflow Stopped**\n\n"
            f"You denied `{tool_name}` twice. The AI agent has stopped its current work.\n\n"
            f"If you'd like to continue with a different approach, please send a new message."
        )
        
        # Hide thinking indicator
        self._ai_chat.hide_thinking()
        
        # Reset UI - show send button again
        self._view.page().runJavaScript("if(window._onGenerationComplete) window._onGenerationComplete();")

    # ========== TESTING WORKFLOW HANDLERS (NEW) ==========
    
    def _on_testing_decision(self, decision: str, priority: str, trigger: str):
        """Handle testing decision signal."""
        log.info(f"[Testing] Decision: {decision} (priority: {priority}, trigger: {trigger})")
        
        # Show UI notification based on decision
        if decision == 'write_tests':
            self._ai_chat.add_system_message(
                f"🧪 **Testing Mode Activated**\n"
                f"Priority: {priority.upper()} | Trigger: {trigger}\n"
                f"The AI will analyze your code and suggest appropriate tests."
            )
        elif decision == 'skip_tests':
            log.debug("Testing skipped - no triggers detected")
    
    def _on_test_tools_selected(self, tools: list):
        """Handle test tools selection signal."""
        log.info(f"[Testing] Tools selected: {tools}")
        
        if tools:
            self._ai_chat.add_system_message(
                f"🔧 **Test Framework:** {', '.join(tools)}"
            )
    
    def _on_test_execution_started(self, test_type: str):
        """Handle test execution start signal."""
        log.info(f"[Testing] Execution started: {test_type}")
        self._ai_chat.add_system_message(f"▶️ Running {test_type} tests...")
    
    def _on_test_execution_completed(self, all_passed: bool, passed_count: int, failed_count: int):
        """Handle test execution completion signal."""
        log.info(f"[Testing] Execution completed: {passed_count} passed, {failed_count} failed")
        
        if all_passed:
            self._ai_chat.add_system_message(
                f"✅ **All Tests Passed!** ({passed_count} tests)"
            )
        else:
            self._ai_chat.add_system_message(
                f"⚠️ **Tests Completed:** {passed_count} passed, {failed_count} failed"
            )
    
    def _on_test_analysis_ready(self, analysis: dict):
        """Handle test analysis results signal."""
        log.info(f"[Testing] Analysis ready: {analysis.get('all_passed', False)}")
        
        # Display failure patterns if any
        patterns = analysis.get('patterns', [])
        if patterns:
            pattern_text = '\n'.join([f"- {p.get('type', 'unknown')}: {p.get('description', '')}" 
                                     for p in patterns[:3]])
            self._ai_chat.add_system_message(
                f"📊 **Failure Analysis:**\n{pattern_text}"
            )

    def _open_file_at_line_duplicate(self, filepath: str, line: int):
        self._open_file(filepath)
        editor = self._editor_tabs.current_editor()
        if editor:
            # Move cursor to line
            cursor = editor.textCursor()
            block = editor.document().findBlockByLineNumber(line - 1)
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.centerCursor()

    def _save_current(self):
        ok = self._editor_tabs.save_current(self._file_manager)
        if ok:
            self._status_file.setText(f"  Saved ✓  {self._status_file.text().strip()}")
            QTimer.singleShot(2000, lambda: self._update_status_file(
                self._editor_tabs.current_filepath()))

    def _save_all(self):
        for i in range(self._editor_tabs.count()):
            editor = self._editor_tabs.widget(i)
            fp = self._editor_tabs._files.get(i)
            if isinstance(editor, CodeEditor) and fp:
                content = editor.get_all_text()
                self._file_manager.write(fp, content)

    def _run_file(self):
        fp = self._editor_tabs.current_filepath()
        if not fp or not Path(fp).exists():
            return
        # HTML files → built-in Live Server (no terminal needed)
        if Path(fp).suffix.lower() in {".html", ".htm"}:
            self._save_current()
            self._run_live_server(fp)
            return
        self._save_current()
        
        self._terminal_tabs.setVisible(True)
        term = self._current_terminal()
        if not term:
            term = self._new_terminal()
        
        term.setFocus()
        lang = detect_language(fp)
        command = self._build_run_command(fp, lang)
        if command:
            term.execute_command(command)
        else:
            QMessageBox.information(self, "Run", f"Running {lang} is not yet supported.")

    def _run_live_server(self, file_path: str):
        """Start (or restart) the built-in Live Server for an HTML file."""
        # Restart if already running
        if self._live_server and self._live_server.is_running:
            self._live_server.stop()

        root = str(Path(file_path).parent)
        try:
            self._live_server = LiveServer(root, file_path)
            port = self._live_server.start()
            url  = self._live_server.get_url(file_path)
        except Exception as e:
            QMessageBox.warning(self, "Live Server", f"Could not start Live Server:\n{e}")
            return

        import webbrowser
        webbrowser.open(url)

        # Show status in status bar
        if hasattr(self, '_statusbar_label'):
            self._statusbar_label.setText(
                f"Live Server  \u25cf  http://localhost:{port}   —   click \u25b6 to restart"
            )

    def _build_run_command(self, file_path: str, lang: str) -> str | None:
        """Build a run command for the current file based on language."""
        is_windows = platform.system() == "Windows"
        root = self._project_manager.root or str(Path(file_path).parent)
        build_dir = os.path.join(root, ".cortex_build")
        stem = Path(file_path).stem

        if is_windows:
            quote = lambda p: f'"{p}"'
            mkdir_cmd = f'New-Item -ItemType Directory -Force -Path {quote(build_dir)} | Out-Null'
        else:
            import shlex
            quote = shlex.quote
            mkdir_cmd = f'mkdir -p {quote(build_dir)}'

        if lang == "python":
            return f'python {quote(file_path)}'
        if lang in {"javascript", "jsx"}:
            return f'node {quote(file_path)}'
        if lang in {"typescript", "tsx"}:
            # Compile with tsc and run with node (faster than npx ts-node)
            js_out = os.path.join(build_dir, stem + ".js")
            if is_windows:
                return f'tsc {quote(file_path)} --outDir {quote(build_dir)}; if ($LASTEXITCODE -eq 0) {{ node {quote(js_out)} }}'
            else:
                return f'tsc {quote(file_path)} --outDir {quote(build_dir)} && node {quote(js_out)}'
        if lang == "bash":
            return f'bash {quote(file_path)}'
        if lang == "batch":
            return f'& {quote(file_path)}' if is_windows else None
        if lang == "powershell":
            return f'& {quote(file_path)}' if is_windows else f'pwsh {quote(file_path)}'
        if lang == "ruby":
            return f'ruby {quote(file_path)}'
        if lang == "php":
            return f'php {quote(file_path)}'
        if lang == "go":
            return f'go run {quote(file_path)}'
        if lang == "rust":
            exe_path = os.path.join(build_dir, stem + (".exe" if is_windows else ""))
            compile_cmd = f'rustc {quote(file_path)} -o {quote(exe_path)}'
            run_cmd = f'& {quote(exe_path)}' if is_windows else f'{quote(exe_path)}'
            return f'{mkdir_cmd}; {compile_cmd}; if ($LASTEXITCODE -eq 0) {{ {run_cmd} }}' if is_windows else f'{mkdir_cmd} && {compile_cmd} && {run_cmd}'
        if lang == "c":
            exe_path = os.path.join(build_dir, stem + (".exe" if is_windows else ""))
            compile_cmd = f'gcc {quote(file_path)} -o {quote(exe_path)}'
            run_cmd = f'& {quote(exe_path)}' if is_windows else f'{quote(exe_path)}'
            return f'{mkdir_cmd}; {compile_cmd}; if ($LASTEXITCODE -eq 0) {{ {run_cmd} }}' if is_windows else f'{mkdir_cmd} && {compile_cmd} && {run_cmd}'
        if lang == "cpp":
            exe_path = os.path.join(build_dir, stem + (".exe" if is_windows else ""))
            compile_cmd = f'g++ {quote(file_path)} -o {quote(exe_path)}'
            run_cmd = f'& {quote(exe_path)}' if is_windows else f'{quote(exe_path)}'
            return f'{mkdir_cmd}; {compile_cmd}; if ($LASTEXITCODE -eq 0) {{ {run_cmd} }}' if is_windows else f'{mkdir_cmd} && {compile_cmd} && {run_cmd}'
        if lang == "java":
            package_name = ""
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("package ") and line.endswith(";"):
                            package_name = line[len("package "):-1].strip()
                            break
            except Exception:
                package_name = ""
            class_name = f"{package_name}.{stem}" if package_name else stem
            compile_cmd = f'javac -d {quote(build_dir)} {quote(file_path)}'
            run_cmd = f'java -cp {quote(build_dir)} {class_name}'
            return f'{mkdir_cmd}; {compile_cmd}; if ($LASTEXITCODE -eq 0) {{ {run_cmd} }}' if is_windows else f'{mkdir_cmd} && {compile_cmd} && {run_cmd}'
        return None

    def _new_terminal(self, show_panel: bool = True) -> XTermWidget:
        # If call comes from a signal (like clicked), show_panel might be the 'checked' state (False usually)
        # So we force it to True if it's not explicitly False from our internal calls
        if not isinstance(show_panel, bool): show_panel = True
        
        term = XTermWidget()
        term.set_theme(self._theme_manager.is_dark)
        
        # Initialize with current project directory if available
        if self._project_manager.root:
            term.set_cwd(str(self._project_manager.root))
            
        idx = self._terminal_tabs.addTab(term, f"Terminal {self._terminal_tabs.count() + 1}")
        self._terminal_tabs.setCurrentIndex(idx)
        
        if show_panel:
            self._terminal_tabs.setVisible(True)
            term.setFocus()
            
        # Hook up "New Terminal" button from within the terminal
        term.new_terminal_requested.connect(lambda: self._new_terminal(show_panel=True))
        
       
       
        # Connect file operations to AI chat
        term.file_operation_detected.connect(self._on_terminal_file_operation)
        
        return term
        
    def _on_terminal_file_operation(self, operation_type: str, file_path: str, status: str):
        """Handle file operations from terminal and show in AI chat."""
        # Map operation types to display format
        op_labels = {
            'create': 'Creating file',
            'create_dir': 'Creating directory',
            'delete': 'Deleting file',
            'delete_dir': 'Deleting directory',
            'move': 'Moving file',
            'copy': 'Copying file',
            'rename': 'Renaming file'
        }
        
        label = op_labels.get(operation_type, operation_type)
        display_info = f"{label}: {file_path}"
        
        # Show in AI chat as tool activity
        self._ai_chat.show_tool_activity('terminal_' + operation_type, display_info, status)

    def _on_terminal_tab_changed(self, index: int):
        """Update AI agent when active terminal changes."""
        term = self._terminal_tabs.widget(index)
        if isinstance(term, XTermWidget):
            self._ai_agent.set_terminal(term)

    def _close_terminal_tab(self, index: int):
        term = self._terminal_tabs.widget(index)
        if isinstance(term, XTermWidget):
            term._kill_process()
        self._terminal_tabs.removeTab(index)
        if self._terminal_tabs.count() == 0:
            self._terminal_tabs.setVisible(False)

    def _kill_current_terminal(self):
        idx = self._terminal_tabs.currentIndex()
        if idx >= 0:
            self._close_terminal_tab(idx)

    def _current_terminal(self) -> XTermWidget | None:
        w = self._terminal_tabs.currentWidget()
        return w if isinstance(w, XTermWidget) else None

    def _toggle_theme(self):
        new_theme = self._theme_manager.toggle(QApplication_instance())
        self._settings.theme = new_theme
        is_dark = self._theme_manager.is_dark
        self._theme_btn.setText("☀️" if not is_dark else "🌙")
        self._editor_tabs.update_theme(is_dark)
        if isinstance(self._terminal_tabs.tabBar(), CleanTabBar):
            self._terminal_tabs.tabBar().set_dark(is_dark)
        
        self._ai_chat.set_theme(is_dark)
        self._sidebar.set_theme(is_dark)
        if hasattr(self, '_diff_window'):
            self._diff_window.set_theme(is_dark)
        
        # Style the tab widget panels
        tab_bg = "#1e1e1e" if is_dark else "#ffffff"
        tab_border = "#3e3e42" if is_dark else "#dee2e6"
        tab_style = f"""
            QTabWidget::pane {{ border: 1px solid {tab_border}; background: {tab_bg}; }}
            QTabWidget::tab-bar {{ left: 0px; }}
        """
        self._editor_tabs.setStyleSheet(tab_style)
        self._terminal_tabs.setStyleSheet(tab_style)

        # Update all terminal tabs
        for i in range(self._terminal_tabs.count()):
            term = self._terminal_tabs.widget(i)
            if isinstance(term, XTermWidget):
                term.set_theme(is_dark)
        self._apply_welcome_theme(is_dark)
        self._apply_toolbar_theme(is_dark)


    def _show_terminal_panel(self):
        """Show terminal panel (called from AI chat 'View in terminal' button)."""
        self._terminal_tabs.setVisible(True)
        if self._terminal_tabs.count() == 0:
            self._new_terminal()
        term = self._current_terminal()
        if term:
            term.setFocus()

    def _show_terminal_and_run(self, command: str):
        """Show terminal panel and execute command (called from 'View in terminal' with a command)."""
        self._terminal_tabs.setVisible(True)
        if self._terminal_tabs.count() == 0:
            self._new_terminal()
        # Ensure the terminal panel has a visible height
        sizes = self._center_splitter.sizes()
        if len(sizes) > 1 and sizes[1] < 40:
            self._center_splitter.setSizes([max(100, sizes[0]), 220])
        term = self._current_terminal()
        if term:
            term.setFocus()
            if command and command.strip():
                term.execute_command(command.strip())

    def _toggle_terminal(self):
        visible = self._terminal_tabs.isVisible()
        sizes = self._center_splitter.sizes()
        # If already visible but dragged to be hidden (tiny size), just restore the size
        if visible and len(sizes) > 1 and sizes[1] < 40:
            self._center_splitter.setSizes([sizes[0], 200])
            self._terminal_tabs.setFocus()
            return
            
        self._terminal_tabs.setVisible(not visible)
        if self._terminal_tabs.isVisible():
            if self._terminal_tabs.count() == 0:
                self._new_terminal()
            
            # Ensure it has a non-zero height if it was collapsed
            new_sizes = self._center_splitter.sizes()
            if len(new_sizes) > 1 and new_sizes[1] < 40:
                self._center_splitter.setSizes([max(100, new_sizes[0]), 200])
                
            term = self._current_terminal()
            if term:
                term.setFocus()

    def _toggle_sidebar(self):
        visible = self._sidebar.isVisible()
        sizes = self._main_splitter.sizes()
        # If visible but tiny (dragged hidden), restore size instead of toggling 
        if visible and sizes[0] < 40:
            self._main_splitter.setSizes([260, sizes[1], sizes[2]])
            self._sidebar.setFocus()
            return
            
        self._sidebar.setVisible(not visible)
        if self._sidebar.isVisible():
            new_sizes = self._main_splitter.sizes()
            if new_sizes[0] < 40:
                 self._main_splitter.setSizes([200, new_sizes[1], new_sizes[2]])
            self._sidebar.setFocus()

    def _toggle_ai_chat(self):
        visible = self._right_panel.isVisible()
        sizes = self._main_splitter.sizes()
        # If visible but tiny (dragged hidden), restore size
        if visible and len(sizes) > 2 and sizes[2] < 40:
            self._main_splitter.setSizes([sizes[0], sizes[1], 300])
            return
            
        self._right_panel.setVisible(not visible)
        if self._right_panel.isVisible():
            new_sizes = self._main_splitter.sizes()
            if len(new_sizes) > 2 and new_sizes[2] < 40:
                 self._main_splitter.setSizes([new_sizes[0], new_sizes[1], 300])

    def _zoom_in(self):
        """Zoom in (Ctrl+=)."""
        editor = self._editor_tabs.current_editor()
        if editor:
            zoom = editor.zoomIn() + 1
            editor.setZoom(zoom)

    def _zoom_out(self):
        """Zoom out (Ctrl+-)."""
        editor = self._editor_tabs.current_editor()
        if editor:
            zoom = max(0, editor.zoomIn() - 1)
            editor.setZoom(zoom)

    def _zoom_reset(self):
        """Reset zoom (Ctrl+0)."""
        editor = self._editor_tabs.current_editor()
        if editor:
            editor.setZoom(0)

    def _focus_ai_chat(self):
        """Focus AI Chat input (Ctrl+Shift+A)."""
        self._ai_chat.focus_input()
        self._ai_chat.raise_()
        self._ai_chat.activateWindow()

    def _command_palette(self):
        """Show Command Palette (Ctrl+Shift+P)."""
        # For now, show a quick open style dialog with commands
        from PyQt6.QtWidgets import QInputDialog
        commands = [
            "File: New File",
            "File: Open File...",
            "File: Save",
            "Edit: Find",
            "Edit: Replace",
            "View: Toggle Terminal",
            "View: Toggle Sidebar",
            "View: Toggle Theme"
        ]
        cmd, ok = QInputDialog.getItem(
            self, 
            "Command Palette", 
            "Type a command:",
            commands, 
            0, 
            False
        )
        if ok and cmd:
            self._status_bar.showMessage(f"Command: {cmd}", 2000)
            # TODO: Implement full command palette

    def _current_editor_action(self, action: str):
        """Focus-aware edit action handler (supports Editor, AI Chat, and Terminal)."""
        focused = QApplication.focusWidget()
        log.debug(f"Action {action} requested. Current focus: {focused}")

        # Map generic action strings to QWebEnginePage.WebAction enums
        web_action_map = {
            "copy": QWebEnginePage.WebAction.Copy,
            "paste": QWebEnginePage.WebAction.Paste,
            "cut": QWebEnginePage.WebAction.Cut,
            "selectAll": QWebEnginePage.WebAction.SelectAll,
            "undo": QWebEnginePage.WebAction.Undo,
            "redo": QWebEnginePage.WebAction.Redo
        }

        # Determine which "logical" component has focus
        logical_focused = None
        widget = focused
        max_depth = 10
        while widget and max_depth > 0:
            if hasattr(self, '_ai_chat') and (widget == self._ai_chat or widget == self._ai_chat._view):
                logical_focused = "ai_chat"
                break
            
            # Check if this widget belongs to a terminal tab
            term = self._current_terminal()
            if term and (widget == term or widget == term._webview):
                logical_focused = "terminal"
                break
            
            widget = widget.parentWidget()
            max_depth -= 1

        # 1. Route to AI Chat
        if logical_focused == "ai_chat":
            if action in web_action_map:
                log.debug(f"Routing {action} to AI Chat WebEngineView")
                self._ai_chat._view.page().triggerAction(web_action_map[action])
                return

        # 2. Route to Terminal
        if logical_focused == "terminal":
            term = self._current_terminal()
            if action == "copy":
                term.copy()
                return
            elif action == "paste":
                term.paste()
                return
            elif action == "selectAll":
                term.select_all()
                return
            elif action == "cut":
                term.cut()
                return
            
            if action in web_action_map:
                term._webview.page().triggerAction(web_action_map[action])
                return

        # 3. Route to Sidebar explicitly (if focused)
        if hasattr(self, '_sidebar') and self._sidebar.is_explorer_focused():
            log.debug(f"Action {action} ignored globally: Sidebar handles it locally")
            return

        # 4. Fallback to Editor (current tab)
        editor = self._editor_tabs.current_editor()
        if editor:
            log.debug(f"Routing {action} to Code Editor")
            if action == "selectAll":
                if hasattr(editor, "selectAll"): editor.selectAll()
                elif hasattr(editor, "select_all"): editor.select_all()
                return
            if hasattr(editor, action):
                getattr(editor, action)()

    # ------------------------------------------------------------------
    # VS Code Style Keyboard Shortcuts
    # ------------------------------------------------------------------
    def _show_find(self):
        """Show Find dialog (Ctrl+F)."""
        editor = self._editor_tabs.current_editor()
        if editor:
            selected = editor.get_selected_text()
            if selected:
                self._find_replace_dialog.set_find_text(selected)
            self._find_replace_dialog.show_find_only()
            self._find_replace_dialog.show()
            self._find_replace_dialog.raise_()
            self._find_replace_dialog.activateWindow()

    def _show_find_replace(self):
        """Show Find & Replace dialog (Ctrl+H)."""
        editor = self._editor_tabs.current_editor()
        if editor:
            selected = editor.get_selected_text()
            if selected:
                self._find_replace_dialog.set_find_text(selected)
            self._find_replace_dialog.show_find_replace()
            self._find_replace_dialog.show()
            self._find_replace_dialog.raise_()
            self._find_replace_dialog.activateWindow()

    def _rename_file(self):
        """Rename file (F2)."""
        if self._sidebar.is_explorer_focused():
            if self._sidebar.rename_selected_item():
                return
            return

        current_file = self._editor_tabs.current_filepath()
        if not current_file:
            return
        
        from PyQt6.QtWidgets import QInputDialog
        from pathlib import Path
        
        old_name = Path(current_file).name
        new_name, ok = QInputDialog.getText(
            self, 
            "Rename File", 
            f"New name for '{old_name}':",
            text=old_name
        )
        
        if ok and new_name and new_name != old_name:
            try:
                old_path = Path(current_file)
                new_path = old_path.parent / new_name
                
                # Rename file on disk
                old_path.rename(new_path)
                
                # Close current tab and open renamed file
                index = self._editor_tabs.currentIndex()
                self._editor_tabs.removeTab(index)
                self._open_file(str(new_path))
                
                self._status_bar.showMessage(f"Renamed to {new_name}", 3000)
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Rename Failed", f"Could not rename file: {e}")

    def _on_sidebar_file_renamed(self, old_path: str, new_path: str):
        old_norm = os.path.normpath(old_path)
        new_norm = os.path.normpath(new_path)
        updated = False

        for idx, fp in list(self._editor_tabs._files.items()):
            if os.path.normcase(fp) != os.path.normcase(old_norm):
                continue

            self._editor_tabs._files[idx] = new_norm
            name = Path(new_norm).name
            if fp in self._editor_tabs._modified:
                self._editor_tabs._modified.discard(fp)
                self._editor_tabs._modified.add(new_norm)
                self._editor_tabs.setTabText(idx, f"ƒ-? {name}")
                self._editor_tabs.setTabToolTip(idx, f"{new_norm} (Modified)")
            else:
                self._editor_tabs.setTabText(idx, name)
                self._editor_tabs.setTabToolTip(idx, new_norm)

            self._editor_tabs._set_tab_icon(idx, new_norm)
            updated = True

            if idx == self._editor_tabs.currentIndex():
                self._update_status_file(new_norm)
                if hasattr(self, '_ai_agent'):
                    self._ai_agent.set_active_file(new_norm)

        if updated:
            log.info(f"Updated open tabs for rename: {old_norm} -> {new_norm}")
    
    def _on_sidebar_file_deleted(self, path: str):
        """Handle file/folder deletion from sidebar."""
        import os
        from pathlib import Path
        
        norm_path = os.path.normpath(path)
        
        # Close tab if file is open
        for idx, fp in list(self._editor_tabs._files.items()):
            if os.path.normcase(fp) == os.path.normcase(norm_path):
                self._editor_tabs._close_tab(idx)
                break
        
        # Refresh sidebar to reflect deletion
        self._sidebar.refresh()
        
        # Refresh project context for AI agent
        if hasattr(self, '_ai_agent') and self._ai_agent:
            project_root = str(self._project_manager.root) if self._project_manager.root else None
            if project_root:
                self._ai_agent.set_project_root(project_root)
        
        log.info(f"File deleted: {path}")
    
    def _on_file_deleted_for_undo(self, original_path: str):
        """Track file deletion for undo functionality."""
        log.debug(f"Undo tracking: File moved to trash: {original_path}")
    
    def _on_file_restored_for_redo(self, restored_path: str):
        """Track file restoration for redo functionality."""
        log.debug(f"Redo tracking: File restored: {restored_path}")
        # Refresh sidebar to show restored file
        QTimer.singleShot(100, self._sidebar.refresh)
    
    def _undo(self):
        """Handle undo - prioritize editor undo, then file restore."""
        # Try editor undo first
        editor = self._editor_tabs.current_editor()
        if editor and editor.document().isUndoAvailable():
            editor.undo()
            return
        
        # If no editor or no undo available, try file restore
        if hasattr(self, '_file_manager') and self._file_manager.can_undo():
            restored_path = self._file_manager.undo_operation()
            if restored_path:
                log.info(f"Restored file: {restored_path}")
                self.statusBar().showMessage(f"Restored: {Path(restored_path).name}", 3000)
    
    def _redo(self):
        """Handle redo - prioritize editor redo, then file re-delete."""
        # Try editor redo first
        editor = self._editor_tabs.current_editor()
        if editor and editor.document().isRedoAvailable():
            editor.redo()
            return
        
        if hasattr(self, '_file_manager') and self._file_manager.can_redo():
            deleted_path = self._file_manager.redo_operation()
            if deleted_path:
                log.info(f"Re-deleted file: {deleted_path}")
                self.statusBar().showMessage(f"Deleted: {Path(deleted_path).name}", 3000)

    def _find_in_files(self):
        """Find in files (Ctrl+Shift+F)."""
        self._ai_chat.add_system_message("🔍 Find in Files: Type your search query in the AI chat.")
        self._ai_chat.set_input_text("Search in files for: ")

    def _go_to_line(self):
        """Go to line (Ctrl+G)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        from PyQt6.QtWidgets import QInputDialog
        line, ok = QInputDialog.getInt(self, "Go to Line", "Line number:", min=1, max=editor.blockCount())
        if ok:
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            for _ in range(line - 1):
                cursor.movePosition(cursor.MoveOperation.Down)
            editor.setTextCursor(cursor)
            editor.setFocus()

    def _toggle_comment(self):
        """Toggle comment on selected lines (Ctrl+/)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        start_line = cursor.blockNumber()
        
        # Get selected text range
        if cursor.hasSelection():
            end_cursor = editor.textCursor()
            end_cursor.setPosition(cursor.selectionEnd())
            end_line = end_cursor.blockNumber()
        else:
            end_line = start_line
        
        # Toggle comments for each line
        for line_num in range(start_line, end_line + 1):
            block = editor.document().findBlockByNumber(line_num)
            text = block.text()
            
            if text.strip().startswith("# "):
                # Remove comment
                new_text = text.replace("# ", "", 1)
            elif text.strip().startswith("#"):
                # Remove comment
                new_text = text.replace("#", "", 1)
            else:
                # Add comment
                new_text = "# " + text
            
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.insertText(new_text)

    def _delete_line(self):
        """Delete current line (Ctrl+Shift+K)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.deleteChar()  # Remove the newline

    def _duplicate_line(self):
        """Duplicate current line (Ctrl+Shift+D)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        line = cursor.block().text()
        cursor.movePosition(cursor.MoveOperation.EndOfLine)
        cursor.insertText("\n" + line)

    def _indent_line(self):
        """Indent selected lines (Ctrl+])."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        
        cursor.beginEditBlock()
        cursor.setPosition(start)
        while cursor.position() <= end:
            cursor.movePosition(cursor.MoveOperation.StartOfLine)
            cursor.insertText("    ")  # 4 spaces
            cursor.movePosition(cursor.MoveOperation.Down)
            if cursor.atEnd():
                break
        cursor.endEditBlock()

    def _outdent_line(self):
        """Outdent selected lines (Ctrl+[)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        
        cursor.beginEditBlock()
        cursor.setPosition(start)
        while cursor.position() <= end:
            cursor.movePosition(cursor.MoveOperation.StartOfLine)
            line_text = cursor.block().text()
            if line_text.startswith("    "):
                cursor.deleteChar()
                cursor.deleteChar()
                cursor.deleteChar()
                cursor.deleteChar()
            elif line_text.startswith("\t"):
                cursor.deleteChar()
            cursor.movePosition(cursor.MoveOperation.Down)
            if cursor.atEnd():
                break
        cursor.endEditBlock()

    def _move_line_up(self):
        """Move current line up (Alt+Up)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        line_num = cursor.blockNumber()
        
        if line_num == 0:
            return  # Already at top
        
        # Get current line and previous line
        current_block = cursor.block()
        prev_block = current_block.previous()
        
        current_text = current_block.text()
        prev_text = prev_block.text()
        
        # Swap lines
        cursor.beginEditBlock()
        cursor.movePosition(cursor.MoveOperation.Start)
        for _ in range(line_num - 1):
            cursor.movePosition(cursor.MoveOperation.Down)
        cursor.movePosition(cursor.MoveOperation.StartOfLine)
        cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
        cursor.movePosition(cursor.MoveOperation.EndOfLine, cursor.MoveMode.KeepAnchor)
        cursor.insertText(current_text + "\n" + prev_text)
        cursor.endEditBlock()

    def _move_line_down(self):
        """Move current line down (Alt+Down)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        line_num = cursor.blockNumber()
        total_lines = editor.blockCount()
        
        if line_num >= total_lines - 1:
            return  # Already at bottom
        
        # Get current line and next line
        current_block = cursor.block()
        next_block = current_block.next()
        
        current_text = current_block.text()
        next_text = next_block.text()
        
        # Swap lines
        cursor.beginEditBlock()
        cursor.movePosition(cursor.MoveOperation.StartOfLine)
        cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor)
        cursor.movePosition(cursor.MoveOperation.EndOfLine, cursor.MoveMode.KeepAnchor)
        cursor.insertText(next_text + "\n" + current_text)
        cursor.endEditBlock()

    def _quick_open(self):
        """Quick open file (Ctrl+P) - Opens file dialog."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open File", 
            str(self._project_manager.root) if self._project_manager.root else "",
            "All Files (*.*)"
        )
        if filepath:
            self._open_file(filepath)

    def _go_to_symbol(self):
        """Go to symbol in file (Ctrl+Shift+O)."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        text = editor.get_all_text()
        # Find function/class definitions
        import re
        symbols = []
        for match in re.finditer(r'^(def|class|function|const|let|var)\s+(\w+)', text, re.MULTILINE):
            line_num = text[:match.start()].count('\n') + 1
            symbols.append(f"{match.group(1)} {match.group(2)} (line {line_num})")
        
        if symbols:
            self._ai_chat.add_system_message("📍 Symbols in file:\n" + "\n".join(symbols[:20]))
        else:
            self._ai_chat.add_system_message("No symbols found in current file.")

    def _close_current_tab(self):
        """Close current tab (Ctrl+W)."""
        self._editor_tabs.close_current_tab()

    def _close_all_tabs(self):
        """Close all tabs (Ctrl+Shift+W)."""
        self._editor_tabs.close_all_tabs()

    def _next_tab(self):
        """Go to next tab (Ctrl+Tab)."""
        current = self._editor_tabs.currentIndex()
        count = self._editor_tabs.count()
        if count > 0:
            self._editor_tabs.setCurrentIndex((current + 1) % count)

    def _prev_tab(self):
        """Go to previous tab (Ctrl+Shift+Tab)."""
        current = self._editor_tabs.currentIndex()
        count = self._editor_tabs.count()
        if count > 0:
            self._editor_tabs.setCurrentIndex((current - 1) % count)

    def _show_shortcuts_help(self):
        """Show keyboard shortcuts help dialog."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard Shortcuts Reference")
        dialog.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(dialog)
        
        shortcuts_html = """
        <html>
        <head>
            <style>
                body { font-family: 'Segoe UI', sans-serif; background: #1e1e1e; color: #f5f5f5; }
                h2 { color: #3b82f6; margin-top: 20px; }
                table { width: 100%; border-collapse: collapse; margin: 10px 0; }
                th, td { padding: 10px; text-align: left; border-bottom: 1px solid #3a3a3a; }
                th { background: #2d2d2d; color: #3b82f6; font-weight: 600; }
                tr:hover { background: #2a2a2a; }
                kbd { 
                    background: #2d2d2d; 
                    border: 1px solid #3a3a3a; 
                    border-radius: 4px; 
                    padding: 2px 6px; 
                    font-family: 'Consolas', monospace;
                    color: #3b82f6;
                }
            </style>
        </head>
        <body>
            <h2>📝 Editing</h2>
            <table>
                <tr><th>Shortcut</th><th>Action</th></tr>
                <tr><td><kbd>Tab</kbd></td><td>Indent (inserts 4 spaces)</td></tr>
                <tr><td><kbd>Shift</kbd>+<kbd>Tab</kbd></td><td>Outdent selected lines</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Z</kbd></td><td>Undo (current file only)</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Y</kbd></td><td>Redo (current file only)</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>A</kbd></td><td>Select All</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>C</kbd></td><td>Copy</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>X</kbd></td><td>Cut</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>V</kbd></td><td>Paste</td></tr>
            </table>
            
            <h2>🔍 Find & Replace</h2>
            <table>
                <tr><th>Shortcut</th><th>Action</th></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>F</kbd></td><td>Find</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>H</kbd></td><td>Find and Replace</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd></td><td>Find in Files</td></tr>
                <tr><td><kbd>F3</kbd></td><td>Find Next</td></tr>
                <tr><td><kbd>Shift</kbd>+<kbd>F3</kbd></td><td>Find Previous</td></tr>
            </table>
            
            <h2>📑 File & Tab Navigation</h2>
            <table>
                <tr><th>Shortcut</th><th>Action</th></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Tab</kbd></td><td>Next Tab</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Tab</kbd></td><td>Previous Tab</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>W</kbd></td><td>Close Current Tab</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>W</kbd></td><td>Close All Tabs</td></tr>
                <tr><td><kbd>F2</kbd></td><td>Rename File</td></tr>
            </table>
            
            <h2>🚀 Quick Open</h2>
            <table>
                <tr><th>Shortcut</th><th>Action</th></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>P</kbd></td><td>Quick Open File</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>O</kbd></td><td>Go to Symbol</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>G</kbd></td><td>Go to Line</td></tr>
            </table>
            
            <h2>🎨 View & Tools</h2>
            <table>
                <tr><th>Shortcut</th><th>Action</th></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>B</kbd></td><td>Toggle Sidebar</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>`</kbd></td><td>Toggle Terminal</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>=</kbd></td><td>Zoom In</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>-</kbd></td><td>Zoom Out</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>0</kbd></td><td>Reset Zoom</td></tr>
                <tr><td><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd></td><td>Command Palette</td></tr>
            </table>
        </body>
        </html>
        """
        
        label = QLabel(shortcuts_html)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        dialog.exec()

    # ------------------------------------------------------------------
    # Find/Replace Handlers
    # ------------------------------------------------------------------
    def _on_find_requested(self, text: str, options: dict):
        """Handle find request from dialog."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        
        # Search options
        case_sensitive = options.get('case_sensitive', False)
        whole_word = options.get('whole_word', False)
        use_regex = options.get('use_regex', False)
        wrap_around = options.get('wrap_around', True)
        search_forward = options.get('forward', True)
        
        # Build search flags
        flags = 0
        if case_sensitive:
            flags |= 0x00010  # QTextDocument.FindFlag.FindCaseSensitively
        
        # Perform search
        from PyQt6.QtGui import QTextDocument
        find_flags = QTextDocument.FindFlag(flags)
        
        if search_forward:
            found = editor.find(text, find_flags)
        else:
            found = editor.find(text, find_flags | QTextDocument.FindFlag.FindBackward)
        
        if not found and wrap_around:
            # Wrap around
            cursor.movePosition(cursor.MoveOperation.Start if search_forward else cursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            if search_forward:
                found = editor.find(text, find_flags)
            else:
                found = editor.find(text, find_flags | QTextDocument.FindFlag.FindBackward)
    
    def _on_replace_requested(self, find_text: str, replace_text: str, options: dict):
        """Handle replace request from dialog."""
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        
        # Check if there's selected text matching find_text
        selected = cursor.selectedText()
        if selected == find_text:
            cursor.insertText(replace_text)
        
        # Find next
        self._on_find_requested(find_text, options)
    
    def _on_replace_all_requested(self, find_text: str, replace_text: str, options: dict):
        """Handle replace all request from dialog."""
        import re
        editor = self._editor_tabs.current_editor()
        if not editor:
            return
        
        document = editor.document()
        cursor = editor.textCursor()
        
        count = 0
        case_sensitive = options.get('case_sensitive', False)
        whole_word = options.get('whole_word', False)
        use_regex = options.get('use_regex', False)
        
        if use_regex:
            # Regex replace all
            try:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(find_text, flags)
                content = editor.toPlainText()
                new_content, count = pattern.subn(replace_text, content)
                
                if count > 0:
                    cursor.beginEditBlock()
                    cursor.select(cursor.SelectionType.Document)
                    cursor.insertText(new_content)
                    cursor.endEditBlock()
                    
            except re.error as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Regex Error", f"Invalid regular expression: {e}")
                return
        else:
            # Simple replace all
            cursor.beginEditBlock()
            
            # Save original position
            original_position = cursor.position()
            
            # Move to start of document
            cursor.setPosition(0)
            
            # Find and replace all occurrences
            while True:
                found = document.find(find_text, cursor, 
                                    QTextDocument.FindFlag.FindCaseSensitively if case_sensitive else QTextDocument.FindFlag(0))
                
                if found.isNull():
                    break
                
                # Check whole word if needed
                if whole_word:
                    # Verify it's a whole word
                    start = found.selectionStart()
                    end = found.selectionEnd()
                    text = editor.toPlainText()
                    
                    # Check character before
                    if start > 0 and (text[start-1].isalnum() or text[start-1] == '_'):
                        cursor.setPosition(end)
                        continue
                    
                    # Check character after
                    if end < len(text) and (text[end].isalnum() or text[end] == '_'):
                        cursor.setPosition(end)
                        continue
                
                # Replace
                found.insertText(replace_text)
                count += 1
            
            cursor.endEditBlock()
        
        from PyQt6.QtWidgets import QMessageBox
        if count > 0:
            QMessageBox.information(self, "Replace All", f"Replaced {count} occurrence(s).")
        else:
            QMessageBox.information(self, "Replace All", f"No occurrences of '{find_text}' found.")
        
        # Restore cursor position
        cursor.setPosition(original_position)
        editor.setTextCursor(cursor)

    # ------------------------------------------------------------------
    # AI Actions
    # ------------------------------------------------------------------
    def _on_ai_run_command(self, command: str):
        """Execute command from AI in active terminal."""
        self._terminal_tabs.setVisible(True)
        term = self._current_terminal()
        if not term:
            term = self._new_terminal()
        term.setFocus()
        term.execute_command(command)
        # Ensure terminal is visible
        self._terminal_tabs.setCurrentIndex(self._terminal_tabs.indexOf(term))

    def _on_directory_contents_for_tree(self, path: str, contents: str):
        """Handle directory contents for project tree card display."""
        self._ai_chat.emit_directory_tree(path, contents)

    def _on_ai_chat_message(self, message: str):
        """Handle user message from AI chat with project context."""
        # FAST PATH: Check if this is a simple query that doesn't need AIIntegrationLayer
        simple_patterns = [
            r'^hi$', r'^hello$', r'^hey$', r'^greetings$', r'^sup$', r'^yo$',
            r'^how are you', r'^what.*your name', r'^what can you do',
            r'^thanks?$', r'^thank you$', r'^ok$', r'^okay$', r'^got it$',
            r'^bye$', r'^goodbye$', r'^see you$'
        ]
        
        stripped = message.strip().lower()
        is_simple = any(__import__('re').match(pattern, stripped) for pattern in simple_patterns)
        
        if is_simple:
            # Fast path: Skip AIIntegrationLayer, go directly to AI agent
            log.info(f"Fast path: Simple query '{message}' - skipping AIIntegrationLayer")
            context = []
            if self._project_manager.root:
                context.append(f"Project path: {self._project_manager.root}")
            full_context = "\n\n".join(context)
            self._ai_agent.chat(message, full_context)
            return
        
        # NORMAL PATH: Full processing for complex queries
        context = []

        # 1. Project Root Info
        if self._project_manager.root:
            context.append(f"Project path: {self._project_manager.root}")

        # 2. Current File Context
        editor = self._editor_tabs.current_editor()
        if editor:
            fp = self._editor_tabs.current_filepath()
            if fp:
                name = Path(fp).name
                content = editor.get_all_text()
                # Limit context size
                if len(content) > 5000:
                    content = content[:5000] + "... (truncated)"
                context.append(f"Current file ({name}):\n```\n{content}\n```")

        full_context = "\n\n".join(context)
        
        # NOTE: _ai_integration was removed - using _ai_agent directly
        # session_id = getattr(self._ai_chat, '_current_conversation_id', 'default-session')
        # self._ai_integration.set_session(...)  # Removed - not needed
        
        # Start AI processing immediately for responsiveness
        # But wait - we need to see if enhancement layer (Intent/Routing) is fast enough
        # Optimization: start AI chat, and if enhancement layer finds a special tool/route, 
        # we can inject that context later or stop/restart. 
        # For now, let's just fix the DUPLICATE problem by only calling it ONCE.
        
        conv_id = getattr(self._ai_chat, '_current_conversation_id', None) if hasattr(self._ai_chat, '_current_conversation_id') else None
        
        if conv_id and not self._title_generator.get_cached_title(conv_id):
            title = self._ai_agent.generate_chat_title(message, conv_id)
            if title:
                log.info(f"Generated chat title: {title}")
                if hasattr(self._ai_chat, 'update_conversation_title'):
                    self._ai_chat.update_conversation_title(conv_id, title)
        
        if conv_id:
            try:
                sessions = self._session_db.list_sessions(self._project_manager.root, limit=1)
                if not sessions:
                    title = self._title_generator.get_cached_title(conv_id) or "New Chat"
                    self._session_db.create_session(
                        conv_id, 
                        title, 
                        self._project_manager.root or "", 
                        self._ai_agent._settings.get("ai", "model", default="deepseek-chat")
                    )
                import uuid
                self._session_db.add_message(
                    conv_id,
                    str(uuid.uuid4()),
                    "user",
                    message,
                    len(message) // 4
                )
            except Exception as e:
                log.debug(f"Could not store message in database: {e}")
        
        # FIX: Initialize enhancement_result to None (not yet implemented in async flow)
        enhancement_result = None
        if enhancement_result and enhancement_result.get("intent"):
            if enhancement_result.get("testing_decision") and \
               enhancement_result["testing_decision"].decision == 'write_tests':
                log.info("Using chat_with_testing with testing workflow")
                self._ai_agent.chat_with_testing(
                    message,
                    code_changes=[],
                    code_context=full_context
                )
            else:
                log.info("Using chat_with_enhancement with intent classification data")
                self._ai_agent.chat_with_enhancement(
                    message, 
                    intent=enhancement_result["intent"],
                    route=enhancement_result["route"],
                    tools=enhancement_result["tools"],
                    code_context=full_context
                )
        else:
            self._ai_agent.chat(message, full_context)

    def _on_model_changed(self, model_id: str, perf: str, cost: str):
        """Handle model selection change from AI chat."""
        # Determine provider from model_id
        log.info(f"[MainWindow] DEBUG: model_id='{model_id}', starts_with_mistral={model_id.startswith('mistral-')}, starts_with_codestral={model_id.startswith('codestral-')}")
        
        if model_id.startswith("deepseek-") and "/" not in model_id:
            # Native DeepSeek models (without /)
            provider = "deepseek"
        elif model_id.startswith("mistral-") or model_id.startswith("codestral-"):
            # Mistral AI models
            provider = "mistral"
        elif "/" in model_id:
            # Vendor models via SiliconFlow
            provider = "siliconflow"
        else:
            provider = "deepseek"  # Default to DeepSeek
        
        log.info(f"[MainWindow] Model changed to: {model_id} (provider: {provider})")
        self._ai_agent.update_settings(provider=provider, model_id=model_id)

    def _on_ai_stop_requested(self):
        """Handle stop request from AI (via web bridge)."""
        self._ai_agent.stop()
    
    def _on_toggle_autogen(self):
        """Toggle AutoGen multi-agent mode."""
        # Get current status
        status = self._ai_agent.get_autogen_status()
        current_enabled = status.get('enabled', False)
        
        # Toggle
        new_state = not current_enabled
        self._ai_agent.enable_autogen(new_state)
        
        log.info(f"AutoGen {'enabled' if new_state else 'disabled'} via UI toggle")

    def _on_generate_plan(self):
        log.info("MainWindow: Automated plan generation triggered")
        self._ai_agent.chat("__GENERATE_PLAN__")

    def _ai_action(self, action: str):
        editor = self._editor_tabs.current_editor()
        if not editor:
            self._ai_chat.add_system_message("Open a file first to use AI actions.")
            return

        code = editor.get_selected_text() or editor.get_all_text()
        language = editor.language
        analyzer = CodeAnalyzer()

        prompts = {
            "explain":   analyzer.build_explain_prompt(code, language),
            "refactor":  analyzer.build_refactor_prompt(code, language),
            "tests":     analyzer.build_test_prompt(code, language),
            "debug":     analyzer.build_debug_prompt(code, "unknown error", language),
            "docstring": f"Add comprehensive docstrings to this {language} code:\n\n```{language}\n{code}\n```",
        }

        prompt = prompts.get(action, f"Help me with this {language} code:\n\n```{language}\n{code}\n```")
        self._ai_chat.add_system_message(f"🤖 Running: {action.title()} Code…")
        self._ai_chat._add_ai_bubble_streaming()
        self._ai_agent.chat(prompt)

    def _get_selected_code(self) -> str:
        editor = self._editor_tabs.current_editor()
        if editor:
            return editor.get_selected_text() or editor.get_all_text()
        return ""

    def _get_code_context(self) -> str:
        """Alias for _get_selected_code to satisfy WebAIChatWidget callback."""
        return self._get_selected_code()

    # ------------------------------------------------------------------
    # Project & Events
    # ------------------------------------------------------------------

    def _cleanup_old_project(self):
        """Clean up all state from the old project before opening a new one."""
        # Only cleanup if we have a previous project loaded
        if not hasattr(self, '_current_project_path') or not self._current_project_path:
            log.info("🆕 First project load - skipping cleanup")
            return
            
        log.info("🧹 Cleaning up old project state...")
        
        # 1. Close all editor tabs
        self._editor_tabs.close_all_tabs()
        log.info("   ✓ Closed all editor tabs")
        
        # 2. Clear file snapshots (diff data)
        if hasattr(self, '_file_snapshots'):
            self._file_snapshots.clear()
            log.info("   ✓ Cleared file snapshots")
        
        # 3. Clear diff cache
        if hasattr(self, '_diff_data_store'):
            self._diff_data_store.clear()
            log.info("   ✓ Cleared diff data store")
        
        # 4. Clear file tracker
        if hasattr(self, '_file_tracker'):
            if hasattr(self._file_tracker, '_edits'):
                self._file_tracker._edits.clear()
            log.info("   ✓ Cleared file edit history")
        
        # 5. Clear AI agent context
        self._ai_agent.clear_active_file()
        log.info("   ✓ Cleared AI agent active file")
        
        # 6. Clear codebase index
        self._codebase_index = None
        log.info("   ✓ Cleared codebase index")
        
        # 7. Prepare terminals for new project (will set CWD after cleanup)
        log.info("   ✓ Prepared terminals for new project")
        
        # 8. Todo list is session-based, no need to clear
        # Todos are tied to chat sessions, not projects
        log.info("   ✓ Skipped todo cleanup (session-based)")
        
        # 9. Clear search results
        if hasattr(self, '_search_results'):
            self._search_results.clear()
            log.info("   ✓ Cleared search results")
        
        log.info("✅ Old project cleanup complete!")
    
    def _on_project_opened(self, folder_path: str):
        log.info(f"Project opened: {folder_path}")
        
        # Clean up old project state BEFORE loading new one (only if switching)
        self._cleanup_old_project()
        
        # Set project root FIRST (this loads project-specific context)
        self._ai_agent.set_project_root(folder_path)
        self._current_project_path = folder_path  # Track current project
        
        # Update LSP manager workspace root so completions/diagnostics work
        try:
            from src.core.lsp_manager import get_lsp_manager
            get_lsp_manager().set_project_root(folder_path)
        except Exception:
            pass
        
        # Reset codebase index for new project
        self._codebase_index = None
        
        # Note: Chat history is now per-project, so we don't clear it.
        # The AI chat will automatically load the history for this project.
        self._ai_agent.clear_active_file()
        
        self._sidebar.set_project(folder_path)
        # Update all current terminal tabs to the new project directory
        for i in range(self._terminal_tabs.count()):
            term = self._terminal_tabs.widget(i)
            if isinstance(term, XTermWidget):
                term.set_cwd(folder_path)
                
        project_name = Path(folder_path).name
        self.setWindowTitle(f"Cortex AI Agent — {project_name}")
        self._ai_chat.add_system_message(f"📂 Opened: {folder_path}")
        
        # Load existing chats for this project from SQLite BEFORE setting project info
        try:
            chats_json = self._ai_chat.load_chats_for_project(folder_path)
        except Exception as e:
            log.warning(f"Failed to load chats for project {folder_path}: {e}")
            chats_json = "[]"
        
        # Update project indicator in AI chat (this triggers project-specific chat loading)
        self._ai_chat.set_project_info(project_name, folder_path, chats_json)
        
        # Update welcome tab if it exists
        self._update_welcome_project_info()
        
        # Auto-detect and activate virtual environment
        self._check_and_activate_venv(folder_path)
        
        # Start background project context scan
        self._start_project_context_scan(folder_path)
    
    def _start_project_context_scan(self, folder_path: str):
        """Start background project scanning for instant AI awareness."""
        from src.ai.project_context import build_project_context
        
        # Show indexing status in chat
        self._ai_chat.show_indexing_status("Indexing project...")
        
        def on_context_ready(ctx):
            """Called when background scan finishes."""
            from PyQt6.QtCore import QMetaObject, Qt
            # Must update UI from main thread
            QMetaObject.invokeMethod(
                self, "_on_project_context_ready",
                Qt.ConnectionType.QueuedConnection,
            )
            # Store context in agent
            self._ai_agent.set_project_context(ctx)
        
        self._context_builder = build_project_context(folder_path, on_context_ready)
    
    @pyqtSlot()
    def _on_project_context_ready(self):
        """Called on main thread when project indexing finishes."""
        from src.ai.project_context import get_project_context
        ctx = get_project_context(self._ai_agent._project_root)
        if ctx:
            self._ai_chat.hide_indexing_status()
            # Show ready indicator  
            self._ai_chat.show_indexing_status(
                f"✓ Indexed {ctx.source_file_count} files ({ctx.build_time_ms:.0f}ms)",
                auto_hide=True
            )

    def _on_project_closed(self):
        """Handle project close - show welcome page and clean up."""
        log.info("Project closed - showing welcome page")

        # Stop Live Server if running
        if self._live_server and self._live_server.is_running:
            self._live_server.stop()
            self._live_server = None

        # Clear all state
        self._current_project_path = None
        self.setWindowTitle("Cortex AI Agent")
        self._ai_chat.clear_project_info()
        
        # Close all editor tabs
        if hasattr(self, '_editor_tabs'):
            self._editor_tabs.close_all_tabs()
        
        # Clear file snapshots and caches
        if hasattr(self, '_file_snapshots'):
            self._file_snapshots.clear()
        if hasattr(self, '_diff_data_store'):
            self._diff_data_store.clear()
        if hasattr(self, '_file_tracker') and hasattr(self._file_tracker, '_edits'):
            self._file_tracker._edits.clear()
        if hasattr(self, '_search_results'):
            self._search_results.clear()
        
        # Clear AI agent context
        self._ai_agent.clear_active_file()
        self._codebase_index = None
        
        # Update welcome page
        self._update_welcome_project_info()
        
        # Show welcome page if not already visible
        self._show_welcome()

    def _update_welcome_project_info(self):
        if not hasattr(self, '_welcome_project_info') or self._welcome_project_info is None:
            return
        if self._project_manager.root:
            name = self._project_manager.root.name
            path = str(self._project_manager.root)
            self._welcome_project_info.setText(f"Project: <b>{name}</b><br/><span style='font-size:11px; color:#858585;'>{path}</span>")
        else:
            self._welcome_project_info.setText("No project opened")


    def _check_and_activate_venv(self, project_path: str):
        """Check for and activate Python virtual environment."""
        import os
        
        venv_names = ["venv", ".venv", "env", ".env", "virtualenv"]
        
        for venv_name in venv_names:
            venv_path = os.path.join(project_path, venv_name)
            if os.path.exists(venv_path):
                # Activate in all terminal tabs
                for i in range(self._terminal_tabs.count()):
                    term = self._terminal_tabs.widget(i)
                    if isinstance(term, XTermWidget):
                        term.activate_virtual_env(venv_path)
                
                # Show notification in chat
                self._ai_chat.add_system_message(f"🐍 Virtual environment detected: {venv_name}")
                
                # Update status bar
                self.statusBar().showMessage(f"Virtual environment: {venv_name}", 5000)
                break

    def _on_tab_changed(self, index: int):
        fp = self._editor_tabs._files.get(index)
        self._update_status_file(fp)
        
        # Update AI agent with active file for context injection
        if fp and hasattr(self, '_ai_agent'):
            try:
                editor = self._editor_tabs.widget(index)
                cursor_pos = None
                if hasattr(editor, 'getCursorPosition'):
                    line, col = editor.getCursorPosition()
                    cursor_pos = (line + 1, col)  # Convert to 1-indexed
                self._ai_agent.set_active_file(fp, cursor_pos)
                log.debug(f"Active file updated for AI: {fp} at {cursor_pos}")
            except Exception as e:
                log.warning(f"Could not update active file for AI: {e}")

    # def _apply_initial_theme(self):
    #     from PyQt6.QtWidgets import QApplication
    #     app = QApplication.instance()
    #     theme = self._settings.theme
    #     self._theme_manager.apply(theme, app)
    #     self._theme_btn.setText("☀️" if theme == "light" else "🌙")

    def _restore_session(self):
        # Restore last project — skip if it no longer exists (blank state)
        log.info("Restoring last session project...")
        restored = self._project_manager.restore_last()

        if not restored:
            # No valid project to restore — show clean blank state, no stale tabs
            log.info("No project to restore — showing blank start state.")
            # Remove any tabs that sneak in during build (stale welcome)
            self._show_welcome()
            return

        # Restore open files only if project was successfully restored
        session = self._session_manager.load()
        if session:
            log.info(f"Restoring {len(session.get('open_files', []))} files...")
            for fp in session.get("open_files", []):
                if Path(fp).exists():
                    self._open_file(fp)

        # Focus the active file
        if session:
            active = session.get("active_file")
            if active and Path(active).exists():
                for i in range(self._editor_tabs.count()):
                    if self._editor_tabs._files.get(i) == active:
                        self._editor_tabs.setCurrentIndex(i)
                        break



    @property
    def codebase_index(self):
        """Get the codebase index, creating it if needed."""
        if self._codebase_index is None:
            if self._project_manager.root:
                self._codebase_index = get_codebase_index(str(self._project_manager.root))
                self._codebase_index.index_project()
            else:
                # No project open, return a dummy index?
                raise RuntimeError("No project open for indexing")
        return self._codebase_index

    def _show_about(self):
        QMessageBox.about(self, "About Cortex AI Agent",
                          "<h2>🧠 Cortex AI Agent</h2>"
                          "<p>A modern AI-powered IDE built with Python and PyQt6.</p>"
                          "<p>Features: Multi-file editor · Syntax highlighting · "
                          "AI chat · File explorer · Terminal</p>"
                          "<p><b>Version:</b> 1.0.0</p>")

    def _show_keyboard_shortcuts(self):
        """Show keyboard shortcuts reference dialog (F1)."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard Shortcuts Reference")
        dialog.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(dialog)
        
        # Create a text edit for displaying shortcuts
        shortcuts_text = QTextEdit()
        shortcuts_text.setReadOnly(True)
        shortcuts_text.setFontFamily("Consolas")
        shortcuts_text.setFontPointSize(10)
        
        # Build shortcuts HTML - Simple dark theme
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    background-color: #1e1e1e;
                    color: #ffffff;
                    padding: 30px;
                    margin: 0;
                }
                h1 {
                    color: #4CAF50;
                    text-align: center;
                    font-size: 32px;
                    margin-bottom: 10px;
                }
                .subtitle {
                    text-align: center;
                    color: #9cdcfe;
                    margin-bottom: 30px;
                    font-size: 16px;
                }
                .section {
                    background-color: #252526;
                    border-left: 4px solid #4CAF50;
                    padding: 20px;
                    margin-bottom: 25px;
                    border-radius: 5px;
                }
                .section h2 {
                    color: #4CAF50;
                    margin: 0 0 15px 0;
                    font-size: 20px;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    background-color: #2d2d30;
                }
                th {
                    background-color: #3e3e42;
                    color: #ffffff;
                    padding: 12px;
                    text-align: left;
                    font-weight: 600;
                    border: 1px solid #555;
                }
                td {
                    padding: 10px 12px;
                    border: 1px solid #555;
                    color: #cccccc;
                }
                tr:nth-child(even) {
                    background-color: #333337;
                }
                tr:hover {
                    background-color: #3e3e42;
                }
                .shortcut {
                    font-family: 'Consolas', monospace;
                    background-color: #1e1e1e;
                    padding: 5px 10px;
                    border-radius: 4px;
                    font-weight: bold;
                    color: #9cdcfe;
                    display: inline-block;
                    min-width: 110px;
                    text-align: center;
                }
                .status {
                    color: #4CAF50;
                    font-weight: bold;
                }
                .tip {
                    background-color: #264f78;
                    padding: 15px;
                    border-radius: 5px;
                    margin-top: 25px;
                    border-left: 4px solid #007acc;
                }
                .tip strong {
                    color: #9cdcfe;
                }
                .tip p {
                    margin: 8px 0 0 0;
                    color: #cccccc;
                }
            </style>
        </head>
        <body>
            <h1>⌨️ Keyboard Shortcuts Reference</h1>
            <p class="subtitle">Quick reference for all Cortex IDE shortcuts</p>
            
            <!-- File Operations -->
            <div class="section">
                <h2>📁 File Operations</h2>
                <table>
                    <tr><th>Action</th><th>Shortcut</th><th>Status</th></tr>
                    <tr><td>New File</td><td><span class="shortcut">Ctrl+N</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Open Folder</td><td><span class="shortcut">Ctrl+O</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Open File</td><td><span class="shortcut">Ctrl+Shift+O</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Save</td><td><span class="shortcut">Ctrl+S</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Save All</td><td><span class="shortcut">Ctrl+Shift+S</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Close Tab</td><td><span class="shortcut">Ctrl+W</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Close All Tabs</td><td><span class="shortcut">Ctrl+Shift+W</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Rename File</td><td><span class="shortcut">F2</span></td><td class="status">✅ Ready</td></tr>
                </table>
            </div>
            
            <!-- Edit Operations -->
            <div class="section">
                <h2>✏️ Edit Operations</h2>
                <table>
                    <tr><th>Action</th><th>Shortcut</th><th>Status</th></tr>
                    <tr><td>Undo</td><td><span class="shortcut">Ctrl+Z</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Redo</td><td><span class="shortcut">Ctrl+Y</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Cut</td><td><span class="shortcut">Ctrl+X</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Copy</td><td><span class="shortcut">Ctrl+C</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Paste</td><td><span class="shortcut">Ctrl+V</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Select All</td><td><span class="shortcut">Ctrl+A</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Toggle Comment</td><td><span class="shortcut">Ctrl+/</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Delete Line</td><td><span class="shortcut">Ctrl+Shift+K</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Indent Selection</td><td><span class="shortcut">Tab</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Outdent Selection</td><td><span class="shortcut">Shift+Tab</span></td><td class="status">✅ Ready</td></tr>
                </table>
            </div>
            
            <!-- Find & Replace -->
            <div class="section">
                <h2>🔍 Find & Replace</h2>
                <table>
                    <tr><th>Action</th><th>Shortcut</th><th>Status</th></tr>
                    <tr><td>Find</td><td><span class="shortcut">Ctrl+F</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Find & Replace</td><td><span class="shortcut">Ctrl+H</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Replace All</td><td><span class="shortcut">In Dialog</span></td><td class="status">✅ Ready</td></tr>
                </table>
            </div>
            
            <!-- Navigation -->
            <div class="section">
                <h2>🧭 Navigation</h2>
                <table>
                    <tr><th>Action</th><th>Shortcut</th><th>Status</th></tr>
                    <tr><td>Next Tab</td><td><span class="shortcut">Ctrl+Tab</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Previous Tab</td><td><span class="shortcut">Ctrl+Shift+Tab</span></td><td class="status">✅ Ready</td></tr>
                </table>
            </div>
            
            <!-- View -->
            <div class="section">
                <h2>👁️ View</h2>
                <table>
                    <tr><th>Action</th><th>Shortcut</th><th>Status</th></tr>
                    <tr><td>Toggle Theme</td><td><span class="shortcut">Ctrl+Shift+T</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Toggle Terminal</td><td><span class="shortcut">Ctrl+`</span></td><td class="status">✅ Ready</td></tr>
                    <tr><td>Toggle Sidebar</td><td><span class="shortcut">Ctrl+B</span></td><td class="status">✅ Ready</td></tr>
                </table>
            </div>
            
            <!-- Tip -->
            <div class="tip">
                <strong>💡 Tip:</strong>
                <p>Press <span class="shortcut" style="min-width: 50px;">F1</span> anytime to open this reference!</p>
            </div>
        </body>
        </html>
        """
        
        shortcuts_text.setHtml(html_content)
        layout.addWidget(shortcuts_text)
        
        dialog.exec()

    def closeEvent(self, event: QCloseEvent):
        """Save session on close, prompt for unsaved files, and kill terminals."""
        # 1. Check for unsaved files
        modified_files = self._editor_tabs._modified
        if modified_files:
            from PyQt6.QtWidgets import QMessageBox
            file_names = [os.path.basename(f) for f in modified_files]
            files_str = ", ".join(file_names[:3]) + ("..." if len(file_names) > 3 else "")
            
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"You have unsaved changes in: {files_str}\n\nDo you want to save them before closing?",
                QMessageBox.StandardButton.SaveAll | 
                QMessageBox.StandardButton.Discard | 
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.StandardButton.SaveAll:
                # Save all modified files
                for filepath in list(modified_files):
                    idx = -1
                    for i, fp in self._editor_tabs._files.items():
                        if fp == filepath:
                            idx = i
                            break
                    
                    if idx >= 0:
                        editor = self._editor_tabs.widget(idx)
                        if isinstance(editor, CodeEditor):
                            content = editor.toPlainText()
                            try:
                                with open(filepath, 'w', encoding='utf-8') as f:
                                    f.write(content)
                                self._editor_tabs._mark_saved(filepath)
                            except Exception as e:
                                log.error(f"Failed to auto-save {filepath}: {e}")
        
        # 2. Force AI Chat persistence
        if hasattr(self, '_ai_chat') and self._ai_chat:
            log.info("Persisting AI chat history before close...")
            # Create a localized event loop to wait for the chat persistence to finish
            loop = QEventLoop()
            save_success = [False]
            
            def on_save_done(status):
                log.info(f"AI chat persistence finished with status: {status}")
                save_success[0] = (status == "OK")
                loop.quit()
                
            # Connect the bridge response signal
            self._ai_chat.save_finished.connect(on_save_done)
            
            # Start timer for timeout (3s max)
            QTimer.singleShot(3000, loop.quit)
            
            # Trigger JS to save its logic to SQLite
            self._ai_chat.run_javascript("if(window.saveProjectChats) saveProjectChats(window.chats);")
            
            # Wait for save or timeout
            loop.exec()
            
            if not save_success[0]:
                log.warning("AI chat persistence timed out or failed before close.")
            else:
                log.info("AI chat persistence confirmed.")
        
        # 3. Save IDE UI state
        fps = self._editor_tabs.get_open_files()
        active = self._editor_tabs.current_filepath()
        expanded = self._sidebar.get_expanded_paths()
        self._session_manager.save(fps, active, {"expanded_paths": expanded})
        self._settings.set("window", "maximized", self.isMaximized())
        if not self.isMaximized():
            self._settings.set("window", "width", self.width())
            self._settings.set("window", "height", self.height())
        
        # Save splitter panel widths
        sizes = self._main_splitter.sizes()
        if len(sizes) == 3:
            self._settings.set("window", "sidebar_width", sizes[0])
            self._settings.set("window", "right_panel_width", sizes[2])
            
        # 4. Clean up terminals
        for i in range(self._terminal_tabs.count()):
            term = self._terminal_tabs.widget(i)
            if isinstance(term, XTermWidget):
                term._kill_process()

        # 5. Stop Live Server if running
        if self._live_server and self._live_server.is_running:
            self._live_server.stop()
                
        event.accept()

    def dragEnterEvent(self, event):
        """Accept drag of folders or files from Explorer onto the window."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Handle drop of folders/files — open as project or file."""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self._open_folder_programmatic(path)
                event.acceptProposedAction()
                return
            elif os.path.isfile(path):
                self._open_file(path)
                event.acceptProposedAction()
                return

    def resizeEvent(self, event):
        """Handle window resize — responsive layout + welcome font scaling.

        VS Code behaviour:
        - All three panels stay visible and simply shrink proportionally.
        - Only at very small widths (<700px) does the AI chat auto-hide.
        - Sidebar keeps its width; editor absorbs most resize delta.
        """
        super().resizeEvent(event)
        w = event.size().width()

        if hasattr(self, '_main_splitter'):
            sizes = self._main_splitter.sizes()
            sidebar_w = sizes[0] if sizes else 300
            right_w   = sizes[2] if len(sizes) > 2 else 350

            if w < 700:
                # Very small window: collapse AI chat only, keep sidebar
                self._main_splitter.setSizes([sidebar_w, max(150, w - sidebar_w), 0])
            elif right_w == 0 and w >= 700:
                # Restore AI chat when window grows back above threshold
                restore_right = 350
                self._main_splitter.setSizes([sidebar_w, max(200, w - sidebar_w - restore_right), restore_right])

        if hasattr(self, '_welcome_widget') and self._welcome_widget is not None:
            self._apply_welcome_theme(self._theme_manager.is_dark)

    # Phase 1, 2, 3 Integration Methods
    def _set_agent_mode(self, mode: str):
        """
        Set AI agent mode (Phase 1 Integration).
        
        Args:
            mode: One of 'build', 'explore', 'debug', 'plan'
        """
        self._ai_agent.set_mode(mode)
        mode_names = {
            'build': '🏗️ Build',
            'explore': '🔍 Explore', 
            'debug': '🐛 Debug',
            'plan': '📋 Plan'
        }
        self._statusbar.showMessage(f"Agent mode: {mode_names.get(mode, mode)}", 3000)
        log.info(f"Agent mode switched to: {mode}")
    
    def _show_skills_browser(self):
        """Show skills browser dialog (Phase 3 Integration)."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QLabel, QPushButton, QTextEdit
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Skills Browser")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel("<h2>🛠️ Available Skills</h2>")
        layout.addWidget(title)
        
        # Skills list
        skills_list = QListWidget()
        skills = self._ai_agent.get_available_skills()
        
        for skill in skills:
            item_text = f"{skill['name']} ({skill['id']})"
            skills_list.addItem(item_text)
        
        layout.addWidget(skills_list)
        
        # Description
        desc_label = QLabel("Select a skill to view capabilities")
        layout.addWidget(desc_label)
        
        # Capability display
        capability_text = QTextEdit()
        capability_text.setReadOnly(True)
        capability_text.setPlaceholderText("Skill capabilities will appear here...")
        layout.addWidget(capability_text)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.exec()
        log.info("Skills browser opened")
    
    def _show_mcp_connections(self):
        """Show MCP connections dialog (Phase 3 Integration)."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit, QListWidget
        
        dialog = QDialog(self)
        dialog.setWindowTitle("MCP Connections")
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel("<h2>🔗 MCP Server Connections</h2>")
        layout.addWidget(title)
        
        # Connected servers
        servers_label = QLabel("Connected Servers:")
        layout.addWidget(servers_label)
        
        servers_list = QListWidget()
        servers = self._ai_agent._mcp_manager.list_servers()
        if servers:
            for server in servers:
                servers_list.addItem(server)
        else:
            servers_list.addItem("No servers connected")
        
        layout.addWidget(servers_list)
        
        # Connect new server section
        layout.addWidget(QLabel("Connect New Server:"))
        
        name_input = QLineEdit()
        name_input.setPlaceholderText("Server name (e.g., github)")
        layout.addWidget(name_input)
        
        url_input = QLineEdit()
        url_input.setPlaceholderText("Server URL (e.g., https://mcp.github.com)")
        layout.addWidget(url_input)
        
        def connect_server():
            name = name_input.text().strip()
            url = url_input.text().strip()
            if name and url:
                success = self._ai_agent.connect_mcp_server(name, url)
                if success:
                    servers_list.addItem(name)
                    name_input.clear()
                    url_input.clear()
        
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(connect_server)
        layout.addWidget(connect_btn)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.exec()
        log.info("MCP connections dialog opened")

    # Phase 4 Integration Methods
    def _show_todo_manager(self):
        """Show TODO manager dialog (Phase 4 Integration)."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QListWidget, QInputDialog
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Tasks & TODOs")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel("<h2>✅ Task Manager</h2>")
        layout.addWidget(title)
        
        # Get current session ID
        session_id = getattr(self._ai_chat, '_current_conversation_id', 'default')
        
        # Tasks list
        tasks_label = QLabel("Current Tasks:")
        layout.addWidget(tasks_label)
        
        tasks_list = QListWidget()
        tasks = self._todo_manager.get_session_tasks(session_id)
        
        if tasks:
            for task in tasks:
                status_icon = "✓" if task.status.value == "completed" else "○"
                priority_icon = "🔴" if task.priority == 1 else "🟡" if task.priority == 2 else "🟢"
                item_text = f"{status_icon} {priority_icon} {task.description[:50]}"
                tasks_list.addItem(item_text)
        else:
            tasks_list.addItem("No tasks yet")
        
        layout.addWidget(tasks_list)
        
        # Stats
        stats = self._todo_manager.get_task_stats(session_id)
        stats_text = f"Pending: {stats.get('pending', 0)} | In Progress: {stats.get('in_progress', 0)} | Completed: {stats.get('completed', 0)}"
        stats_label = QLabel(stats_text)
        layout.addWidget(stats_label)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.exec()
        log.info("TODO manager dialog opened")
    
    def _add_todo_task(self):
        """Add a new TODO task."""
        from PyQt6.QtWidgets import QInputDialog
        
        text, ok = QInputDialog.getText(self, "Add Task", "Task description:")
        if ok and text:
            session_id = getattr(self._ai_chat, '_current_conversation_id', 'default')
            task_id = self._todo_manager.add_task(session_id, text)
            self._statusbar.showMessage(f"Task added: {text[:30]}...", 3000)
            log.info(f"Added todo task: {text}")
    
    def _complete_todo_task(self):
        """Complete a TODO task."""
        from PyQt6.QtWidgets import QInputDialog
        
        session_id = getattr(self._ai_chat, '_current_conversation_id', 'default')
        tasks = self._todo_manager.get_pending_tasks(session_id)
        
        if not tasks:
            self._statusbar.showMessage("No pending tasks", 3000)
            return
        
        task_descriptions = [f"{i+1}. {t.description[:40]}" for i, t in enumerate(tasks)]
        text, ok = QInputDialog.getItem(self, "Complete Task", "Select task:", task_descriptions, 0, False)
        
        if ok and text:
            idx = int(text.split(".")[0]) - 1
            if 0 <= idx < len(tasks):
                task_id = tasks[idx].id
                self._todo_manager.complete_task(task_id)
                self._statusbar.showMessage("Task completed!", 3000)
    
    def _show_permission_settings(self):
        """Show permission settings dialog (Phase 4 Integration)."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Permission Settings")
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel("<h2>🔒 Permission System</h2>")
        layout.addWidget(title)
        
        # Info
        info = QLabel("Permission system is active and monitoring tool usage.")
        layout.addWidget(info)
        
        # Cache info
        cache_size = len(self._permission_evaluator._permission_cache)
        cache_label = QLabel(f"Cached decisions: {cache_size}")
        layout.addWidget(cache_label)
        
        # Clear cache button
        def clear_cache():
            self._permission_evaluator.clear_cache()
            cache_label.setText("Cached decisions: 0")
        
        clear_btn = QPushButton("Clear Permission Cache")
        clear_btn.clicked.connect(clear_cache)
        layout.addWidget(clear_btn)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.exec()
        log.info("Permission settings dialog opened")
    
    def _show_github_integration(self):
        """Show GitHub integration dialog (Phase 4 Integration)."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit, QInputDialog
        
        dialog = QDialog(self)
        dialog.setWindowTitle("GitHub Integration")
        dialog.setMinimumSize(500, 300)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel("<h2>🐙 GitHub Automation</h2>")
        layout.addWidget(title)
        
        # Repository info
        if self._github_agent.repo_owner and self._github_agent.repo_name:
            repo_text = f"Repository: {self._github_agent.repo_owner}/{self._github_agent.repo_name}"
        else:
            repo_text = "No repository configured"
        repo_label = QLabel(repo_text)
        layout.addWidget(repo_label)
        
        # Set repository button
        def set_repo():
            owner, ok1 = QInputDialog.getText(self, "GitHub Repository", "Repository owner:")
            if ok1 and owner:
                repo, ok2 = QInputDialog.getText(self, "GitHub Repository", "Repository name:")
                if ok2 and repo:
                    self._github_agent.set_repository(owner, repo)
                    repo_label.setText(f"Repository: {owner}/{repo}")
        
        set_repo_btn = QPushButton("Set Repository")
        set_repo_btn.clicked.connect(set_repo)
        layout.addWidget(set_repo_btn)
        
        # Analyze PR button
        def analyze_pr():
            pr_number, ok = QInputDialog.getInt(self, "Analyze PR", "PR number:")
            if ok:
                result = self._github_agent.analyze_pr(pr_number)
                if result:
                    msg = f"PR Analysis: {result.get('summary', {}).get('files_changed', 0)} files changed"
                    self._statusbar.showMessage(msg, 5000)
        
        analyze_btn = QPushButton("Analyze PR...")
        analyze_btn.clicked.connect(analyze_pr)
        layout.addWidget(analyze_btn)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.exec()
        log.info("GitHub integration dialog opened")

    # Phase 4: Real-time UI Update Handlers
    def _on_todo_task_added(self, task_id: str):
        """Handle new todo task - update chat UI in real-time."""
        task = self._todo_manager.get_task(task_id)
        if task and hasattr(self, '_ai_chat'):
            # Convert to dict and update chat UI
            task_dict = task.to_dict()
            self._ai_chat.update_todos([task_dict])
            log.info(f"Todo task added to UI: {task.description[:30]}")

    def _on_toggle_todo(self, task_id: str, completed: bool):
        """Handle todo toggle from UI - complete or reopen a task."""
        if completed:
            self._todo_manager.complete_task(task_id)
            log.info(f"Todo completed via UI: {task_id}")
        else:
            self._todo_manager.start_task(task_id)
            log.info(f"Todo reopened via UI: {task_id}")

    def _on_todo_task_completed(self, task_id: str):
        """Handle completed todo - update chat UI."""
        task = self._todo_manager.get_task(task_id)
        if task and hasattr(self, '_ai_chat'):
            # Update the todo status in chat UI
            task_dict = task.to_dict()
            self._ai_chat.update_todos([task_dict])
            log.info(f"Todo task completed in UI: {task.description[:30]}")

    def _on_todo_task_updated(self, task_id: str):
        """Handle updated todo - refresh chat UI."""
        session_id = getattr(self._ai_chat, '_current_conversation_id', 'default')
        tasks = self._todo_manager.get_session_tasks(session_id)
        if hasattr(self, '_ai_chat'):
            # Refresh all todos in chat UI
            tasks_list = [t.to_dict() for t in tasks]
            self._ai_chat.update_todos(tasks_list)

    def _on_ai_task_complete(self, response: str):
        """Show Windows toast notification when AI task completes."""
        try:
            if response and len(response) > 10:
                summary = response[:150].replace('\n', ' ').strip()
                show_task_complete_notification(summary)
        except Exception:
            pass

    def _on_title_generated(self, conversation_id: str, title: str):
        """Handle auto-generated title - update chat tab and UI."""
        # Update the chat tab title via JavaScript bridge
        if hasattr(self, '_ai_chat') and hasattr(self._ai_chat, '_view'):
            safe_title = title.replace('"', '\\"').replace("'", "\\'")
            js_code = f"if(window.updateChatTitle) window.updateChatTitle('{conversation_id}', '{safe_title}');"
            self._ai_chat._view.page().runJavaScript(js_code)
            log.info(f"Chat title updated in UI: {title}")
        
        # Also update window title if this is current chat
        current_id = getattr(self._ai_chat, '_current_conversation_id', None)
        if current_id == conversation_id and title:
            self.setWindowTitle(f"Cortex - {title}")


def QApplication_instance():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance()
