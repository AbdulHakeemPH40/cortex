"""
Cortex AI Agent IDE — Main Window
Full 3-panel layout: Sidebar | Editor Tabs | AI Chat + Terminal
"""

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QTabWidget, QLabel, QPushButton, QStatusBar, QFileDialog,
    QToolBar, QMenuBar, QMessageBox, QInputDialog, QTabBar,
    QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QRect, QProcessEnvironment
from PyQt6.QtGui import (QAction, QKeySequence, QIcon, QFont, QPainter, QColor, 
                         QMouseEvent, QCloseEvent, QPixmap)

from src.config.settings import get_settings
from src.config.theme_manager import get_theme_manager
from src.core.project_manager import ProjectManager
from src.core.file_manager import FileManager
from src.core.session_manager import SessionManager
from src.core.codebase_index import get_codebase_index
from src.ai.agent import AIAgent
from src.ai.code_analyzer import CodeAnalyzer
from src.ai.file_edit_tracker import FileEditTracker
from src.ui.components.sidebar import SidebarWidget
from src.ui.components.editor import CodeEditor
from src.ui.components.ai_chat import AIChatWidget
from src.ui.components.xterm_terminal import XTermWidget
from src.ui.dialogs.diff_viewer import DiffWindow
from src.utils.icons import make_icon
from src.utils.helpers import detect_language, shorten_path
from src.utils.logger import get_logger

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
        # Colour palette
        col_sel_bg    = QColor("#1e1e1e") if d else QColor("#ffffff")
        col_hover_bg  = QColor("#2a2a2d") if d else QColor("#e0e0e0")
        col_normal_bg = QColor("#2d2d30") if d else QColor("#ececec")
        col_accent    = QColor("#007acc") if d else QColor("#0d6efd")
        col_divider   = QColor("#3e3e42") if d else QColor("#d0d0d0")
        col_sel_fg    = QColor("#ffffff") if d else QColor("#1a1a1a")
        col_hover_fg  = QColor("#cccccc") if d else QColor("#333333")
        col_normal_fg = QColor("#969696") if d else QColor("#6c757d")
        col_close     = QColor("#cccccc") if d else QColor("#666666")

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
            close_w = 22
            
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
            
            # Icon Color Mapping
            colors = {
                "python":   "#c678dd", "html": "#e06c75", "css": "#61afef",
                "javascript": "#d19a66", "typescript": "#61afef", "markdown": "#61afef",
                "json": "#d19a66", "java": "#e06c75", "rust": "#d19a66", "go": "#61afef",
                "sql": "#e5c07b", "ai": "#98c379", "terminal": "#858585"
            }
            icon_color = colors.get(icon_name, "#abb2bf")
            
            # Using a fallback if terminal icon not found, or use the shell icon
            icon_pixmap = make_icon(icon_name, icon_color, icon_size).pixmap(icon_size, icon_size)
            painter.drawPixmap(icon_x, rect.y() + (rect.height() - icon_size)//2, icon_pixmap)
            
            # Label
            label_x = icon_x + icon_size + 8
            label_rect = QRect(label_x, rect.y(), rect.width() - (label_x - rect.x()) - close_w - 4, rect.height())
            painter.save()
            fg = col_sel_fg if is_selected else (col_hover_fg if is_hovered else col_normal_fg)
            painter.setPen(fg)
            f = painter.font()
            f.setPointSize(9)
            painter.setFont(f)
            painter.drawText(label_rect,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             text)
            painter.restore()

            # × close button — only on hovered or selected tab
            if is_hovered or is_selected:
                btn_size = 16
                btn_x = rect.right() - btn_size - 4
                btn_y = rect.y() + (rect.height() - btn_size) // 2
                btn_rect = QRect(btn_x, btn_y, btn_size, btn_size)

                # Subtle highlight when cursor is over the × itself
                cursor_pos = self.mapFromGlobal(self.cursor().pos())
                if btn_rect.contains(cursor_pos):
                    painter.save()
                    a = 35 if d else 30
                    painter.setBrush(QColor(0, 0, 0, a) if not d else QColor(255, 255, 255, a))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRoundedRect(btn_rect, 3, 3)
                    painter.restore()

                painter.save()
                painter.setPen(col_close)
                xf = painter.font()
                xf.setPointSize(10)
                painter.setFont(xf)
                painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "×")
                painter.restore()

        painter.end()

    def mousePressEvent(self, event):
        """Handle × button click to close the tab."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QMouseEvent
        i = self.tabAt(event.pos())
        if i >= 0:
            rect = self.tabRect(i)
            btn_size = 16
            btn_x = rect.right() - btn_size - 4
            btn_y = rect.y() + (rect.height() - btn_size) // 2
            from PyQt6.QtCore import QRect
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

    def open_file(self, filepath: str, content: str, language: str) -> int:
        """Open a file in a new tab (or switch to existing)."""
        # Check if already open
        for idx, fp in self._files.items():
            if fp == filepath:
                self.setCurrentIndex(idx)
                return idx
        # Create editor
        editor = CodeEditor(language=language)
        editor.set_content(content, language)
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
        self._modified.add(filepath)
        for idx, fp in self._files.items():
            if fp == filepath:
                name = Path(fp).name
                self.setTabText(idx, f"● {name}")
                break

    def _close_tab(self, index: int):
        widget = self.widget(index)
        filepath = self._files.get(index)
        
        # If it's a code editor with unsaved changes, we might want to prompt (omitting for now as per previous code)
        
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
        editor = self.current_editor()
        fp = self.current_filepath()
        if not editor or not fp:
            return False
        content = editor.get_all_text()
        ok = file_manager.write(fp, content)
        if ok:
            self._modified.discard(fp)
            self.setTabText(self.currentIndex(), Path(fp).name)
        return ok

    def get_open_files(self) -> list[str]:
        return list(self._files.values())

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
        self._ai_agent = AIAgent()
        self._file_tracker = FileEditTracker(self)
        self._diff_window = DiffWindow(self)
        self._codebase_index = None
        
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
        self._heartbeat_timer.timeout.connect(lambda: log.debug("LOOP HEARTBEAT"))
        self._heartbeat_timer.start(2000)

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
        self._sidebar = SidebarWidget()
        self._sidebar.setMinimumWidth(44)
        self._sidebar.setMaximumWidth(320)
        self._main_splitter.addWidget(self._sidebar)

        # --- Center: Editor + Terminal stacked vertically ---
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._center_splitter = QSplitter(Qt.Orientation.Vertical)

        # Editor tabs
        self._editor_tabs = EditorTabWidget()
        self._editor_tabs.setMinimumSize(400, 300)
        self._editor_tabs.show()
        self._center_splitter.addWidget(self._editor_tabs)

        # Terminal tabs
        self._terminal_tabs = QTabWidget()
        self._terminal_tabs.setTabBar(CleanTabBar(self._terminal_tabs))
        self._terminal_tabs.setTabsClosable(True)
        self._terminal_tabs.setDocumentMode(True)
        self._terminal_tabs.setMovable(True)
        self._terminal_tabs.setVisible(False)
        self._terminal_tabs.setMinimumHeight(150)
        self._terminal_tabs.tabCloseRequested.connect(self._close_terminal_tab)
        
        # Add a placeholder/first terminal
        self._new_terminal()
        
        self._center_splitter.addWidget(self._terminal_tabs)

        self._center_splitter.setSizes([700, 200])
        center_layout.addWidget(self._center_splitter, 1)
        self._main_splitter.addWidget(center_widget)

        # --- Right Panel: AI Chat ---
        self._right_panel = QWidget()
        self._right_panel.setMinimumWidth(280)
        right_layout = QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._ai_chat = AIChatWidget()
        self._ai_chat.run_command.connect(self._on_ai_run_command)
        self._ai_chat.stop_requested.connect(self._on_ai_stop_requested)
        self._ai_chat.open_file_requested.connect(self._open_file)
        self._ai_chat.accept_file_edit_requested.connect(self._on_accept_file_edit)
        self._ai_chat.reject_file_edit_requested.connect(self._on_reject_file_edit)
        self._ai_chat.set_code_context_callback(self._get_code_context)
        right_layout.addWidget(self._ai_chat)
        self._main_splitter.addWidget(self._right_panel)

        # Splitter sizes for 3 panels: sidebar | editor | AI chat
        sidebar_w = self._settings.get("window", "sidebar_width") or 220
        right_w = self._settings.get("window", "right_panel_width") or 350
        total_w = (self._settings.get("window", "width") or 1400)
        center_w = max(400, total_w - sidebar_w - right_w)
        self._main_splitter.setSizes([sidebar_w, center_w, right_w])
        self._main_splitter.setHandleWidth(1)
        
        # Limit AI chat panel max width to prevent it from getting too wide
        self._right_panel.setMaximumWidth(480)

        root_layout.addWidget(self._main_splitter, 1)

        # Welcome tab
        self._show_welcome()

    def _show_welcome(self):
        """Show a welcome screen in the editor tabs."""
        self._welcome_widget = QWidget()
        welcome = self._welcome_widget
        wlay = QVBoxLayout(welcome)
        wlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlay.setSpacing(20)

        title = QLabel("🧠 Cortex AI Agent")
        title.setStyleSheet("font-size:32px; font-weight:bold; color:#007acc;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlay.addWidget(title)

        self._welcome_subtitle = QLabel("Your AI-powered development environment")
        self._welcome_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlay.addWidget(self._welcome_subtitle)

        self._welcome_sep = QFrame()
        self._welcome_sep.setFrameShape(QFrame.Shape.HLine)
        wlay.addWidget(self._welcome_sep)

        # Dynamic Project Info
        self._welcome_project_info = QLabel()
        self._welcome_project_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_project_info.setStyleSheet("font-size:14px; color:#c678dd; margin: 10px 0;")
        wlay.addWidget(self._welcome_project_info)
        self._welcome_hints = []
        self._update_welcome_project_info()



        hints = [
            ("📂 Open Project", "File → Open Folder  or  Ctrl+O"),
            ("✨ New Project", "File → New Project"),
            ("📝 New File", "File → New File  or  Ctrl+N"),
            ("🎨 Toggle Theme", "View → Toggle Theme  or  Ctrl+Shift+T"),
            ("⚡ Terminal", "View → Toggle Terminal  or  Ctrl+`"),
            ("🤖 AI Chat", "Type a question in the right panel"),
        ]
        for icon_title, shortcut in hints:
            row = ClickableLabel(f"<b>{icon_title}</b>   <span class='shortcut'>{shortcut}</span>")
            row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Connect actions
            if icon_title == "✨ New Project":
                row.clicked.connect(self._new_project)
            elif icon_title == "📂 Open Project":
                row.clicked.connect(self._open_folder_dialog)
            elif icon_title == "📝 New File":
                row.clicked.connect(self._new_file)
            elif icon_title == "🎨 Toggle Theme":
                row.clicked.connect(self._toggle_theme)
            elif icon_title == "⚡ Terminal":
                row.clicked.connect(self._toggle_terminal)
                
            wlay.addWidget(row)
            self._welcome_hints.append(row)


        idx = self._editor_tabs.addTab(welcome, "Welcome")
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

        self._welcome_widget.setStyleSheet(
            f"background-color:{bg}; color:{fg};"
        )
        if hasattr(self, '_welcome_subtitle'):
            self._welcome_subtitle.setStyleSheet(f"font-size:16px; color:{subtitle_color};")
        if hasattr(self, '_welcome_sep'):
            self._welcome_sep.setStyleSheet(f"color:{sep_color}; margin:10px 80px;")
        if hasattr(self, '_welcome_hints'):
            for row in self._welcome_hints:
                row.setStyleSheet(f"font-size:14px; color:{hint_fg};")
        if hasattr(self, '_welcome_project_info') and self._welcome_project_info:
            project_color = "#c678dd" if is_dark else "#9b30ff"
            self._welcome_project_info.setStyleSheet(f"font-size:14px; color:{project_color}; margin: 10px 0;")


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
        self._add_action(edit_menu, "Undo", lambda: self._current_editor_action("undo"), "Ctrl+Z")
        self._add_action(edit_menu, "Redo", lambda: self._current_editor_action("redo"), "Ctrl+Y")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Cut", lambda: self._current_editor_action("cut"), "Ctrl+X")
        self._add_action(edit_menu, "Copy", lambda: self._current_editor_action("copy"), "Ctrl+C")
        self._add_action(edit_menu, "Paste", lambda: self._current_editor_action("paste"), "Ctrl+V")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Select All", lambda: self._current_editor_action("selectAll"), "Ctrl+A")

        # View
        view_menu = mb.addMenu("View")
        self._add_action(view_menu, "Toggle Theme", self._toggle_theme, "Ctrl+Shift+T")
        self._add_action(view_menu, "Toggle Terminal", self._toggle_terminal, "Ctrl+`")
        view_menu.addSeparator()
        self._add_action(view_menu, "Toggle Sidebar", self._toggle_sidebar, "Ctrl+B")

        # AI
        ai_menu = mb.addMenu("AI")
        self._add_action(ai_menu, "Explain Code", lambda: self._ai_action("explain"), "Ctrl+Shift+E")
        self._add_action(ai_menu, "Refactor Code", lambda: self._ai_action("refactor"), "Ctrl+Shift+R")
        self._add_action(ai_menu, "Write Tests", lambda: self._ai_action("tests"), "Ctrl+Shift+U")
        self._add_action(ai_menu, "Debug Help", lambda: self._ai_action("debug"), "Ctrl+Shift+D")
        ai_menu.addSeparator()
        self._add_action(ai_menu, "Clear Chat", self._ai_chat.clear_chat, "")

        # Terminal
        term_menu = mb.addMenu("Terminal")
        self._add_action(term_menu, "New Terminal", self._new_terminal, "Ctrl+Shift+`")
        self._add_action(term_menu, "Kill Terminal", self._kill_current_terminal, "")
        term_menu.addSeparator()
        self._add_action(term_menu, "Toggle Terminal Panel", self._toggle_terminal, "Ctrl+`")

        # Help
        help_menu = mb.addMenu("Help")
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

        actions = [
            ("📂", "Open Folder (Ctrl+O)", self._open_folder_dialog),
            ("💾", "Save (Ctrl+S)",         self._save_current),
            ("▶️", "Run File",              self._run_file),
            ("➕", "New Terminal",          self._new_terminal),
            ("⚡", "Toggle Terminal (Ctrl+`)", self._toggle_terminal),
        ]
        for icon, tip, slot in actions:
            btn = QPushButton(icon)
            btn.setToolTip(tip)
            btn.setFixedSize(44, 40)
            btn.clicked.connect(slot)
            self._toolbar_btns.append(btn)
            tb.addWidget(btn)

        tb.addWidget(self._make_spacer())

        # Theme toggle button
        self._theme_btn = QPushButton("🌙")
        self._theme_btn.setToolTip("Toggle Dark/Light Theme (Ctrl+Shift+T)")
        self._theme_btn.setFixedSize(44, 40)
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
        
        btn_style = f"""
            QPushButton {{
                font-size: 22px;
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
            btn.setStyleSheet(btn_style)


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

        sb.addPermanentWidget(QLabel("  Cortex AI Agent v1.0  "))

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

    # ------------------------------------------------------------------
    # Signal Connections
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # Sidebar signals
        self._sidebar.file_opened.connect(self._open_file)
        self._sidebar.file_search_opened.connect(self._open_file_at_line)
        self._sidebar.ai_action_requested.connect(self._ai_action)
        
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

        # AI chat - ONLY connect signals here to avoid duplicates
        self._ai_chat.message_sent.connect(self._on_ai_chat_message)
        self._ai_agent.response_chunk.connect(self._ai_chat.on_chunk)
        self._ai_agent.response_complete.connect(self._ai_chat.on_complete)
        self._ai_agent.request_error.connect(self._ai_chat.on_error)
        self._ai_agent.file_generated.connect(self._open_file)
        self._ai_agent.file_edited_diff.connect(self._file_tracker.add_edit)
        self._ai_agent.file_edited_diff.connect(self._on_file_edited_diff_for_js)
        self._ai_agent.tool_activity.connect(self._ai_chat.show_tool_activity)
        self._ai_agent.directory_contents.connect(self._ai_chat.show_directory_contents)
        self._ai_agent.directory_contents.connect(self._on_directory_contents_for_tree)
        self._ai_agent.thinking_started.connect(self._ai_chat.show_thinking)
        self._ai_agent.thinking_stopped.connect(self._ai_chat.hide_thinking)
        self._ai_agent.todos_updated.connect(self._ai_chat.update_todos)
        
        # New interaction signals
        self._ai_chat.generate_plan_requested.connect(self._on_generate_plan)
        self._ai_chat.mode_changed.connect(self._ai_agent.set_interaction_mode)
        self._ai_chat.open_file_requested.connect(self._open_file)
        self._ai_chat.open_file_at_line_requested.connect(self._open_file_at_line)
        self._ai_chat.show_diff_requested.connect(self._on_show_diff)
        self._ai_chat.smart_paste_check_requested.connect(self._on_smart_paste_check)

        # Terminal tab changes
        self._terminal_tabs.currentChanged.connect(self._on_terminal_tab_changed)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _new_file(self):
        editor = CodeEditor(language="python")
        idx = self._editor_tabs.addTab(editor, "untitled.py")
        self._editor_tabs.setCurrentIndex(idx)
        editor.cursor_position_changed.connect(self._update_status_cursor)

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open File",
                                               str(self._project_manager.root or Path.home()))
        if path:
            self._open_file(path)
    
    def _find_file_in_project(self, filename: str) -> str | None:
        """Search for a file by name in the project directory (recursive)."""
        if not self._project_manager.root:
            return None
        
        root = Path(self._project_manager.root)
        
        # Search recursively for the file
        for file_path in root.rglob(filename):
            if file_path.is_file():
                return str(file_path)
        
        return None

    def _open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Folder",
                                                   str(Path.home()))
        if folder:
            self._project_manager.open(folder)

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
                
            log.info(f"Content read ({len(content)} chars). Detecting language...")
            language = detect_language(filepath)
            log.info(f"Language detected: {language}. Opening index in tabs...")
            
            idx = self._editor_tabs.open_file(filepath, content, language)
            
            # Connect cursor signal for the new editor
            editor = self._editor_tabs.widget(idx)
            if isinstance(editor, CodeEditor):
                editor.cursor_position_changed.connect(self._update_status_cursor)
                
            self._update_status_file(filepath)
            is_dark = self._theme_manager.is_dark
            if isinstance(editor, CodeEditor):
                editor.set_theme(is_dark)
            log.info(f"File opened successfully: {filepath}")
        except Exception as e:
            log.error(f"Error opening file {filepath}: {e}", exc_info=True)

    def _on_show_diff(self, file_path: str):
        """Show diff in separate window"""
        edit_info = self._file_tracker.get_edit(file_path)
        if edit_info:
            # For newly created files (type "C"), show the full content as added
            if edit_info.edit_type == "C":
                self._diff_window.show_diff(
                    file_path,
                    "",  # Empty original for new files
                    edit_info.new_content
                )
            else:
                self._diff_window.show_diff(
                    file_path,
                    edit_info.original_content,
                    edit_info.new_content
                )
        else:
            log.warning(f"No edit info found for {file_path}")

    def _on_file_edited_diff_for_js(self, file_path: str, original: str, new_content: str):
        """
        Send diff data to aichat.html JavaScript for the diff viewer overlay.
        Called when agent emits file_edited_diff signal.
        """
        import json
        try:
            # Get the chat page
            page = self._ai_chat._view.page()
            if not page:
                return

            # Truncate very large files to avoid JSON size issues
            MAX_CHARS = 200_000
            orig_safe = original[:MAX_CHARS] if len(original) > MAX_CHARS else original
            new_safe = new_content[:MAX_CHARS] if len(new_content) > MAX_CHARS else new_content

            # Escape for JavaScript
            path_js = json.dumps(file_path)
            orig_js = json.dumps(orig_safe)
            new_js = json.dumps(new_safe)

            # Call JavaScript storeDiffData function
            page.runJavaScript(f"storeDiffData({path_js}, {orig_js}, {new_js})")
            log.debug(f"Sent diff data to JS for: {file_path}")
            
            # Add to sidebar changed files panel
            edit_type = "C" if not original else "M"
            self._sidebar.add_changed_file(file_path, edit_type)
        except Exception as e:
            log.warning(f"Failed to send diff data to JS: {e}")

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
        """Handle user accepting a file edit from the chat UI."""
        if file_path == "__ALL__":
            self._on_accept_all_files()
            return
        # Normalize path (convert forward slashes to backslashes on Windows)
        file_path = os.path.normpath(file_path)
        log.info(f"User accepted file edit: {file_path}")
        
        # For new files (type "C"), we need to create them first
        edit_info = self._file_tracker.get_edit(file_path)
        if edit_info and edit_info.edit_type == "C":
            # This is a newly created file - write it to disk first
            from pathlib import Path
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.write_text(edit_info.new_content, encoding="utf-8")
                log.info(f"Created new file: {file_path}")
            except Exception as e:
                log.error(f"Failed to create file: {e}")
                self.statusBar().showMessage(f"✗ Failed to create {path.name}", 3000)
                return
        
        # Open the file in editor
        self._open_file(file_path)
        # Future: Could add to git staging or show success notification
        self.statusBar().showMessage(f"✓ Accepted changes to {Path(file_path).name}", 3000)
        # Remove from sidebar panel
        self._sidebar.remove_changed_file(file_path)

    def _on_reject_file_edit(self, file_path: str):
        """Handle user rejecting a file edit from the chat UI."""
        if file_path == "__ALL__":
            self._on_reject_all_files()
            return
        # Normalize path (convert forward slashes to backslashes on Windows)
        file_path = os.path.normpath(file_path)
        log.info(f"User rejected file edit: {file_path}")
        # Open the file in editor for review
        self._open_file(file_path)
        # Future: Could restore from pre-edit snapshot
        self.statusBar().showMessage(f"✗ Rejected changes to {Path(file_path).name} - review file", 5000)
        # Remove from sidebar panel
        self._sidebar.remove_changed_file(file_path)

    def _on_accept_all_files(self):
        """Handle user accepting all pending file edits."""
        log.info("User accepted all file edits")
        self.statusBar().showMessage("✓ Accepted all changes", 3000)
        self._sidebar.clear_changed_files()

    def _on_reject_all_files(self):
        """Handle user rejecting all pending file edits."""
        log.info("User rejected all file edits")
        self.statusBar().showMessage("✗ Rejected all changes - review files", 5000)
        self._sidebar.clear_changed_files()

    def _on_smart_paste_check(self, pasted_text: str):
        """Check if pasted text matches current editor selection. Send result to chat."""
        try:
            # Get current editor
            editor = self._editor_tabs.currentWidget()
            if not isinstance(editor, CodeEditor):
                # No editor open, just paste normally
                self._ai_chat._view.page().runJavaScript(
                    f"handleSmartPasteResult({{isMatch: false}});"
                )
                return
            
            # Get selected text from editor
            selected_text = editor.selectedText()
            
            # Normalize texts for comparison (remove extra whitespace)
            def normalize(text):
                return '\n'.join(line.strip() for line in text.strip().split('\n') if line.strip())
            
            pasted_normalized = normalize(pasted_text)
            selected_normalized = normalize(selected_text)
            
            # Check if they match (allowing for minor differences)
            is_match = (pasted_normalized == selected_normalized or 
                       pasted_normalized in selected_normalized or 
                       selected_normalized in pasted_normalized)
            
            if is_match:
                # Get file path and line numbers
                file_path = self._editor_tabs.current_filepath()
                if file_path:
                    # Get selection range
                    start_line, _ = editor.getSelectionStart()
                    end_line, _ = editor.getSelectionEnd()
                    
                    # Convert to 1-indexed
                    start_line += 1
                    end_line += 1
                    
                    # Build line range string
                    if start_line == end_line:
                        line_range = f"{start_line}"
                    else:
                        line_range = f"{start_line}-{end_line}"
                    
                    # Escape the file path for JavaScript
                    import json
                    file_path_js = json.dumps(file_path)
                    
                    # Send result to JavaScript
                    self._ai_chat._view.page().runJavaScript(
                        f"handleSmartPasteResult({{isMatch: true, filePath: {file_path_js}, lineRange: '{line_range}'}});"
                    )
                    log.info(f"Smart paste: matched selection in {file_path} lines {line_range}")
                else:
                    # No file path, paste normally
                    self._ai_chat._view.page().runJavaScript(
                        f"handleSmartPasteResult({{isMatch: false}});"
                    )
            else:
                # No match, paste normally
                self._ai_chat._view.page().runJavaScript(
                    f"handleSmartPasteResult({{isMatch: false}});"
                )
                
        except Exception as e:
            log.error(f"Smart paste check error: {e}")
            # On error, paste normally
            self._ai_chat._view.page().runJavaScript(
                f"handleSmartPasteResult({{isMatch: false}});"
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
        self._save_current()
        
        self._terminal_tabs.setVisible(True)
        term = self._current_terminal()
        if not term:
            term = self._new_terminal()
        
        term.setFocus()
        lang = detect_language(fp)
        if lang == "python":
            term.execute_command(f'python "{fp}"')
        else:
            QMessageBox.information(self, "Run", f"Running {lang} is not yet supported.")

    def _new_terminal(self) -> XTermWidget:
        term = XTermWidget()
        term.set_theme(self._theme_manager.is_dark)
        
        # Initialize with current project directory if available
        if self._project_manager.root:
            term.set_cwd(str(self._project_manager.root))
            
        idx = self._terminal_tabs.addTab(term, f"Terminal {self._terminal_tabs.count() + 1}")
        self._terminal_tabs.setCurrentIndex(idx)
        
        # Link to AI Agent immediately
        self._ai_agent.set_terminal(term)
        
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


    def _toggle_terminal(self):
        self._terminal_tabs.setVisible(not self._terminal_tabs.isVisible())
        if self._terminal_tabs.isVisible():
            if self._terminal_tabs.count() == 0:
                self._new_terminal()
            term = self._current_terminal()
            if term:
                term.setFocus()

    def _toggle_sidebar(self):
        visible = self._sidebar.isVisible()
        self._sidebar.setVisible(not visible)

    def _current_editor_action(self, action: str):
        editor = self._editor_tabs.current_editor()
        if editor and hasattr(editor, action):
            getattr(editor, action)()

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
        self._ai_agent.chat(message, full_context)

    def _on_ai_stop_requested(self):
        """Handle stop request from AI (via web bridge)."""
        self._ai_agent.stop()

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
    def _on_project_opened(self, folder_path: str):
        log.info(f"Project opened: {folder_path}")
        
        # Set project root FIRST (this loads project-specific context)
        self._ai_agent.set_project_root(folder_path)
        
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
        
        # Update project indicator in AI chat (this triggers project-specific chat loading)
        self._ai_chat.set_project_info(project_name, folder_path)
        
        # Update welcome tab if it exists
        self._update_welcome_project_info()
        
        # Auto-detect and activate virtual environment
        self._check_and_activate_venv(folder_path)

    def _on_project_closed(self):
        self._update_welcome_project_info()
        self.setWindowTitle("Cortex AI Agent")
        self._ai_chat.clear_project_info()

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
        # Restore last project 
        log.info("Restoring last session project...")
        self._project_manager.restore_last()
        
        # Restore open files 
        session = self._session_manager.load()
        if session:
            log.info(f"Restoring {len(session.get('open_files', []))} files...")
            for fp in session.get("open_files", []):
                if Path(fp).exists():
                    self._open_file(fp)
                    
        # Focus the active file
        active = session.get("active_file")
        if active and Path(active).exists():
            # Find the tab and select it
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

    def closeEvent(self, event: QCloseEvent):
        """Save session on close and kill terminal process cleanly."""
        fps = self._editor_tabs.get_open_files()
        active = self._editor_tabs.current_filepath()
        # Collect expanded folder paths from the file tree
        expanded = self._sidebar.get_expanded_paths()
        self._session_manager.save(fps, active, {"expanded_paths": expanded})
        self._settings.set("window", "maximized", self.isMaximized())
        if not self.isMaximized():
            self._settings.set("window", "width", self.width())
            self._settings.set("window", "height", self.height())
        # Save splitter panel widths so they restore correctly on next open
        sizes = self._main_splitter.sizes()
        if len(sizes) == 3:
            self._settings.set("window", "sidebar_width", sizes[0])
            self._settings.set("window", "right_panel_width", sizes[2])
        # Kill all terminal shells before Qt destroys the widgets
        for i in range(self._terminal_tabs.count()):
            term = self._terminal_tabs.widget(i)
            if isinstance(term, XTermWidget):
                term._kill_process()
        event.accept()


def QApplication_instance():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance()
