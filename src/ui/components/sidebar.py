"""
Left Sidebar Component — File explorer, Search, Git, and AI Tools panels.
"""

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTreeView, QLineEdit, QListWidget, QListWidgetItem,
    QLabel, QMenu, QInputDialog, QMessageBox, QFrame,
    QSizePolicy, QComboBox, QSlider, QStyledItemDelegate, QStyle,
    QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QDir, QModelIndex, QSize, QRect, QTimer
from PyQt6.QtGui import (
    QIcon, QAction, QFont, QFileSystemModel, QColor, QPainter,
    QFontMetrics, QPalette
)
from src.utils.helpers import detect_language
from src.utils.logger import get_logger
from src.utils.icons import make_icon, make_button_icon

log = get_logger("sidebar")

def _get_icon_name(path: str) -> str:
    """Map file extension to icon factory name."""
    p = Path(path)
    if p.is_dir():
        return "folder"
    suffix = p.suffix.lower()
    mapping = {
        # Python
        ".py": "python", ".pyw": "python", ".pyi": "python",
        # JavaScript/TypeScript
        ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "react", ".jsx": "react",
        # Web
        ".html": "html", ".htm": "html",
        ".css": "css", ".scss": "scss", ".sass": "scss", ".less": "scss",
        # Java/Kotlin
        ".java": "java", ".jar": "java", ".groovy": "java",
        ".kt": "java", ".kts": "java",
        # C/C++
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".h": "c", ".hpp": "cpp",
        # C#
        ".cs": "csharp",
        # Rust
        ".rs": "rust",
        # Go
        ".go": "go",
        # PHP
        ".php": "php",
        # Ruby
        ".rb": "ruby", ".erb": "ruby", ".rake": "ruby",
        # Shell
        ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".bat": "shell", ".cmd": "shell", ".ps1": "shell",
        # Data/Config
        ".json": "json", ".json5": "json",
        ".yaml": "yaml", ".yml": "yaml",
        ".toml": "config", ".ini": "config", ".cfg": "config", ".env": "config",
        ".xml": "config",
        # SQL
        ".sql": "sql", ".sqlite": "sql",
        # Markdown
        ".md": "markdown", ".mdx": "markdown", ".markdown": "markdown",
        # Git
        ".git": "git", ".gitignore": "git",
        # Docker
        ".dockerfile": "docker", ".dockerignore": "docker",
        # Vue/Svelte
        ".vue": "vue",
        ".svelte": "svelte",
        # Images
        ".pdf": "pdf",
        ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".svg": "image",
        ".doc": "word", ".docx": "word",
        ".xlsx": "excel", ".xls": "excel",
        ".pptx": "powerpoint", ".ppt": "powerpoint",
        ".csv": "csv",
        ".log": "files",
        ".txt": "files"
    }
    return mapping.get(suffix, "default")


# ── Custom delegate for VS Code-style rows ─────────────────────────────────────
class FileTreeDelegate(QStyledItemDelegate):
    """Draws each tree row with a colored icon + filename."""

    def __init__(self, model: QFileSystemModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._is_dark = True

    def set_dark(self, is_dark: bool):
        self._is_dark = is_dark

    def paint(self, painter: QPainter, option, index: QModelIndex):
        self.initStyleOption(option, index)

        filepath = self._model.filePath(index)
        name = Path(filepath).name
        is_dir = Path(filepath).is_dir()

        # Row background
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered  = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.fillRect(option.rect, QColor("#094771" if self._is_dark else "#cce5ff"))
        elif hovered:
            painter.fillRect(option.rect, QColor("#2a2d2e" if self._is_dark else "#f0f4ff"))

        x = option.rect.left() + 2  # running x cursor

        # ── Chevron arrow for directories ──────────────────────────────────
        if is_dir:
            view = option.widget
            expanded = view.isExpanded(index) if (view and hasattr(view, 'isExpanded')) else False
            chevron = "▼" if expanded else "▶"
            chevron_rect = QRect(x, option.rect.top(), 14, option.rect.height())
            painter.save()
            arrow_color = "#cccccc" if self._is_dark else "#555555"
            painter.setPen(QColor(arrow_color))
            f0 = painter.font()
            f0.setPointSize(8)
            painter.setFont(f0)
            painter.drawText(chevron_rect,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             chevron)
            painter.restore()
            x += 14  # shift rest right

        # ── VS Code-style SVG Icons ───────────────────────────────
        icon_name = _get_icon_name(filepath)
        
        # Use 18px size for better visibility
        icon_size = 18
        icon = make_icon(icon_name, "", icon_size)
        pixmap = icon.pixmap(icon_size, icon_size)
        
        icon_rect = QRect(x, option.rect.top() + (option.rect.height() - icon_size) // 2, icon_size, icon_size)
        painter.drawPixmap(icon_rect, pixmap)
        x += icon_size + 6

        # ── Filename ───────────────────────────────────────────────────────
        text_rect = QRect(x, option.rect.top(),
                          option.rect.right() - x - 2,
                          option.rect.height())
        fg = "#d4d4d4" if self._is_dark else "#1a1a1a"
        if selected:
            fg = "#ffffff" if self._is_dark else "#003d80"

        painter.save()
        painter.setPen(QColor(fg))
        f2 = painter.font()
        f2.setPointSize(11)
        f2.setBold(is_dir)
        painter.setFont(f2)
        fm = QFontMetrics(f2)
        elided = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(text_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         elided)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(120, 24)


# ── Tree View with VS Code-style QSS ──────────────────────────────────────────
TREE_QSS_DARK = """
QTreeView {
    background: #1e1e1e;
    border: none;
    outline: 0;
    font-size: 12px;
}
QTreeView::item {
    height: 24px;
    border-radius: 3px;
    padding-left: 2px;
}
QTreeView::item:hover      { background: #2a2d2e; }
QTreeView::item:selected   { background: #094771; color: #ffffff; }
QTreeView::branch {
    background: #1e1e1e;
}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {
    image: none;
    border-image: none;
}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings  {
    image: none;
    border-image: none;
}
"""

TREE_QSS_LIGHT = """
QTreeView {
    background: #ffffff;
    border: none;
    outline: 0;
    font-size: 12px;
    color: #1a1a1a;
}
QTreeView::item {
    height: 24px;
    border-radius: 3px;
    padding-left: 2px;
}
QTreeView::item:hover      { background: #e8f0fe; }
QTreeView::item:selected   { background: #cce5ff; color: #003d80; }
QTreeView::branch {
    background: #ffffff;
}
"""

SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv',
             '.idea', '.vs', 'build', 'dist', '.tox'}


class VsCodeFileTree(QTreeView):
    """QTreeView subclass: single-click expands folders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setExpandsOnDoubleClick(False)  # we handle manually

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            model = self.model()
            if hasattr(model, 'filePath'):
                path = model.filePath(index)
                if Path(path).is_dir():
                    # Call super first so selection + model loading fires
                    super().mousePressEvent(event)
                    if self.isExpanded(index):
                        self.collapse(index)
                    else:
                        self.expand(index)
                    # Force icon repaint for open/closed folder icon
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(50, self.viewport().update)
                    return
        super().mousePressEvent(event)


# ── Main File Explorer Panel ───────────────────────────────────────────────────
class FileExplorerPanel(QWidget):
    """VS Code-style file explorer panel."""
    file_opened  = pyqtSignal(str)
    file_created = pyqtSignal(str)
    file_deleted = pyqtSignal(str)
    file_renamed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_path: str | None = None
        self._is_dark = True
        self._tree_collapsed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Section header ─────────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(30)
        hlay = QHBoxLayout(self._header)
        hlay.setContentsMargins(10, 0, 6, 0)

        self._section_title = QLabel("EXPLORER")
        self._section_title.setStyleSheet(
            "font-size:10px; font-weight:bold; letter-spacing:1.2px; color:#858585;"
        )
        hlay.addWidget(self._section_title)
        hlay.addStretch()

        collapse_btn = QPushButton()
        collapse_btn.setIcon(make_button_icon("collapse", self._is_dark, 18))
        collapse_btn.setFixedSize(24, 24)
        collapse_btn.setToolTip("Collapse All")
        collapse_btn.setStyleSheet("QPushButton { border:none; background:transparent; } QPushButton:hover { background: #3e3e42; border-radius:3px; }")
        collapse_btn.clicked.connect(self._collapse_all)
        hlay.addWidget(collapse_btn)
        layout.addWidget(self._header)

        # ── Folder title row (like VS Code's "CORTEX ∨") ─────────────────
        self._folder_row = QWidget()
        self._folder_row.setFixedHeight(26)
        flay = QHBoxLayout(self._folder_row)
        flay.setContentsMargins(6, 0, 4, 0)
        flay.setSpacing(4)

        self._folder_arrow = QLabel("▶")
        self._folder_arrow.setStyleSheet("font-size:9px; color:#cccccc;")
        self._folder_arrow.setFixedWidth(12)
        flay.addWidget(self._folder_arrow)

        self._folder_name = QLabel("NO FOLDER OPENED")
        self._folder_name.setStyleSheet(
            "font-size:11px; font-weight:bold; color:#cccccc; letter-spacing:0.5px;"
        )
        flay.addWidget(self._folder_name)
        flay.addStretch()

        # Action Toolbar
        self._action_toolbar = QWidget()
        athay = QHBoxLayout(self._action_toolbar)
        athay.setContentsMargins(0, 0, 0, 0)
        athay.setSpacing(2)

        self._btn_new_file = QPushButton()
        self._btn_new_file.setIcon(make_button_icon("new_file", self._is_dark, 18))
        self._btn_new_file.setFixedSize(26, 26)
        self._btn_new_file.setToolTip("New File")
        self._btn_new_file.clicked.connect(self._new_file)
        
        self._btn_new_folder = QPushButton()
        self._btn_new_folder.setIcon(make_button_icon("new_folder", self._is_dark, 18))
        self._btn_new_folder.setFixedSize(26, 26)
        self._btn_new_folder.setToolTip("New Folder")
        self._btn_new_folder.clicked.connect(self._new_folder)

        self._btn_refresh = QPushButton()
        self._btn_refresh.setIcon(make_button_icon("refresh", self._is_dark, 18))
        self._btn_refresh.setFixedSize(26, 26)
        self._btn_refresh.setToolTip("Refresh Explorer")
        self._btn_refresh.clicked.connect(self._refresh_explorer)

        for btn in [self._btn_new_file, self._btn_new_folder, self._btn_refresh]:
            btn.setStyleSheet("QPushButton { border:none; background:transparent; } QPushButton:hover { background: #3e3e42; border-radius:3px; }")
            athay.addWidget(btn)

        flay.addWidget(self._action_toolbar)

        # self._folder_row.mousePressEvent = self._toggle_tree # Handled by click on the row but buttons should intercept
        layout.addWidget(self._folder_row)

        # ── File system model ──────────────────────────────────────────────
        self._model = QFileSystemModel()
        self._model.setReadOnly(False)
        self._model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
        )
        # hide common noise dirs
        self._model.setNameFilterDisables(False)

        # ── Tree view ──────────────────────────────────────────────────────
        self._tree = VsCodeFileTree()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        for col in (1, 2, 3):
            self._tree.setColumnHidden(col, True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(14)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.doubleClicked.connect(self._on_double_click)
        # Repaint after expand/collapse so open-folder icon updates
        self._tree.expanded.connect(self._on_expanded)
        self._tree.collapsed.connect(self._on_collapsed)
        # Repaint when async directory listing finishes loading
        self._model.directoryLoaded.connect(lambda _: self._tree.viewport().update())

        # Custom delegate
        self._delegate = FileTreeDelegate(self._model)
        self._tree.setItemDelegate(self._delegate)
        self._tree.setStyleSheet(TREE_QSS_DARK)
        # Disable inline rename — double-click should only open the file
        from PyQt6.QtWidgets import QAbstractItemView
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        layout.addWidget(self._tree)
        self._tree_visible = True

    # ── Public ────────────────────────────────────────────────────────────────
    def set_project(self, folder_path: str):
        self._root_path = folder_path
        name = Path(folder_path).name.upper()
        self._folder_name.setText(name)
        self._folder_arrow.setText("▼")
        self._tree_collapsed = False
        idx = self._model.setRootPath(folder_path)
        self._tree.setRootIndex(idx)
        self._tree.setVisible(True)
        # NO auto-expand — user expands manually; call restore_expanded_paths() after

    def get_expanded_paths(self) -> list[str]:
        """Return list of currently expanded folder paths (for session save)."""
        expanded = []
        root_idx = self._tree.rootIndex()
        def _walk(parent_idx):
            for row in range(self._model.rowCount(parent_idx)):
                idx = self._model.index(row, 0, parent_idx)
                if self._tree.isExpanded(idx):
                    path = self._model.filePath(idx)
                    expanded.append(path)
                    _walk(idx)
        _walk(root_idx)
        return expanded

    def restore_expanded_paths(self, paths: list[str]):
        """Expand the given folder paths (called after model finishes loading)."""
        if not paths:
            return
        from PyQt6.QtCore import QTimer

        def _do_restore():
            path_set = set(paths)
            root_idx = self._tree.rootIndex()
            def _walk(parent_idx):
                for row in range(self._model.rowCount(parent_idx)):
                    idx = self._model.index(row, 0, parent_idx)
                    fp = self._model.filePath(idx)
                    if fp in path_set:
                        self._tree.expand(idx)
                        _walk(idx)
            _walk(root_idx)
            self._tree.viewport().update()

        # Give the model time to populate (async directory listing)
        QTimer.singleShot(400, _do_restore)


    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
        self._delegate.set_dark(is_dark)
        self._tree.setStyleSheet(TREE_QSS_DARK if is_dark else TREE_QSS_LIGHT)
        # header/folder row colours
        fg = "#cccccc" if is_dark else "#1a1a1a"
        bg = "#1e1e1e" if is_dark else "#f3f3f3"
        self._header.setStyleSheet(f"background:{bg};")
        self._folder_row.setStyleSheet(
            f"background:{bg}; border-bottom:1px solid "
            f"{'#3e3e42' if is_dark else '#dcdcdc'};"
        )
        self._folder_name.setStyleSheet(
            f"font-size:11px; font-weight:bold; color:{fg}; letter-spacing:0.5px;"
        )
        self._folder_arrow.setStyleSheet(f"font-size:9px; color:{fg};")
        
        # Update toolbar icons
        self._btn_new_file.setIcon(make_button_icon("new_file", is_dark, 18))
        self._btn_new_folder.setIcon(make_button_icon("new_folder", is_dark, 18))
        self._btn_refresh.setIcon(make_button_icon("refresh", is_dark, 18))
        
        btn_qss = f"""
            QPushButton {{ 
                border:none; 
                background:transparent; 
            }} 
            QPushButton:hover {{ 
                background: {"#3e3e42" if is_dark else "#e5e5e5"}; 
                border-radius:3px; 
            }}
        """
        for btn in [self._btn_new_file, self._btn_new_folder, self._btn_refresh]:
            btn.setStyleSheet(btn_qss)

        self._tree.viewport().update()

    # ── Private ───────────────────────────────────────────────────────────────
    def _on_expanded(self, index: QModelIndex):
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, self._tree.viewport().update)

    def _on_collapsed(self, index: QModelIndex):
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, self._tree.viewport().update)

    def _toggle_tree(self, _event=None):
        """Collapse/expand all items in tree (like VS Code's root arrow)."""
        if self._tree_collapsed:
            # Restore to expanded state
            self._tree.expandToDepth(0)  # expand first level only
            self._folder_arrow.setText("▼")
            self._tree_collapsed = False
        else:
            self._tree.collapseAll()
            self._folder_arrow.setText("▶")
            self._tree_collapsed = True

    def _collapse_all(self):
        self._tree.collapseAll()
        self._folder_arrow.setText("▶")
        self._tree_collapsed = True

    def _new_file(self):
        """Create a new file in the currently selected directory or root."""
        from PyQt6.QtWidgets import QInputDialog
        target_dir = self._get_selected_dir()
        if not target_dir:
            return
            
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            new_path = Path(target_dir) / name
            try:
                new_path.touch()
                self._refresh_explorer()
                self.file_created.emit(str(new_path))
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Could not create file: {e}")

    def _new_folder(self):
        """Create a new folder in the currently selected directory or root."""
        from PyQt6.QtWidgets import QInputDialog
        target_dir = self._get_selected_dir()
        if not target_dir:
            return
            
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            new_path = Path(target_dir) / name
            try:
                new_path.mkdir(parents=True, exist_ok=True)
                self._refresh_explorer()
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Could not create folder: {e}")

    def _refresh_explorer(self):
        """Force a refresh of the file system model."""
        if self._root_path:
            # QFileSystemModel monitors automatically, but we can force it
            self._model.setRootPath("")
            self._model.setRootPath(self._root_path)
            self._tree.viewport().update()

    def _get_selected_dir(self) -> str | None:
        """Helper to find target directory for new items."""
        index = self._tree.currentIndex()
        if index.isValid():
            path = self._model.filePath(index)
            if Path(path).is_dir():
                return path
            else:
                return str(Path(path).parent)
        return self._root_path

    def _on_double_click(self, index: QModelIndex):
        path = self._model.filePath(index)
        if Path(path).is_file():
            self.file_opened.emit(path)

    def _show_context_menu(self, pos):
        index = self._tree.indexAt(pos)
        path = self._model.filePath(index) if index.isValid() else self._root_path
        if not path:
            return

        menu = QMenu(self)
        is_dir = Path(path).is_dir()
        if is_dir:
            act_new_file   = menu.addAction("📄  New File")
            act_new_folder = menu.addAction("📁  New Folder")
            menu.addSeparator()

        act_rename = menu.addAction("✏️  Rename")
        act_delete = menu.addAction("🗑️  Delete")
        menu.addSeparator()
        act_copy_path = menu.addAction("📋  Copy Path")

        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if not action:
            return

        if is_dir and action.text().strip().endswith("New File"):
            name, ok = QInputDialog.getText(self, "New File", "File name:")
            if ok and name:
                new_path = str(Path(path) / name)
                Path(new_path).touch()
                self.file_created.emit(new_path)

        elif is_dir and action.text().strip().endswith("New Folder"):
            name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
            if ok and name:
                (Path(path) / name).mkdir(exist_ok=True)

        elif action == act_rename:
            name, ok = QInputDialog.getText(self, "Rename", "New name:", text=Path(path).name)
            if ok and name:
                new_path = str(Path(path).parent / name)
                Path(path).rename(new_path)
                self.file_renamed.emit(path, new_path)

        elif action == act_delete:
            reply = QMessageBox.question(
                self, "Delete", f"Delete '{Path(path).name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                import shutil
                if Path(path).is_dir():
                    shutil.rmtree(path)
                else:
                    Path(path).unlink()
                self.file_deleted.emit(path)

        elif action == act_copy_path:
            QApplication.clipboard().setText(str(path))



class SearchPanel(QWidget):
    file_opened = pyqtSignal(str, int)  # path, line number

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._header = QLabel("SEARCH")
        layout.addWidget(self._header)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search in files...")
        self._search_input.returnPressed.connect(self._do_search)
        layout.addWidget(self._search_input)

        self._results = QListWidget()
        self._results.itemDoubleClicked.connect(self._open_result)
        layout.addWidget(self._results)

        self._status = QLabel("")
        layout.addWidget(self._status)
        self.set_theme(True)

    def set_theme(self, is_dark: bool):
        color = "#858585" if is_dark else "#666666"
        self._header.setStyleSheet(f"font-size:10px; font-weight:bold; color:{color}; letter-spacing:1px;")
        self._status.setStyleSheet(f"font-size:11px; color:{color};")

    def set_root(self, root: str):
        self._root = root

    def _do_search(self):
        query = self._search_input.text().strip()
        if not query or not self._root:
            return
        self._results.clear()
        found = 0
        for dirpath, _, files in os.walk(self._root):
            if any(skip in dirpath for skip in ['.git', '__pycache__', 'node_modules', 'venv', '.venv']):
                continue
            for fname in files:
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        for lineno, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                rel = os.path.relpath(fpath, self._root)
                                item = QListWidgetItem(f"{rel}:{lineno}  {line.strip()[:60]}")
                                item.setData(Qt.ItemDataRole.UserRole, (fpath, lineno))
                                self._results.addItem(item)
                                found += 1
                                if found >= 200:
                                    break
                except Exception:
                    pass
                if found >= 200:
                    break
        self._status.setText(f"{found} result(s)" + (" (limited)" if found >= 200 else ""))

    def _open_result(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.file_opened.emit(data[0], data[1])


class AIToolsPanel(QWidget):
    """AI quick-action panel in the sidebar."""
    action_requested = pyqtSignal(str)  # action name

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._header = QLabel("AI TOOLS")
        layout.addWidget(self._header)

        layout.addWidget(self._make_separator())

        self.set_theme(True)

        layout.addWidget(self._make_separator())

        actions = [
            ("💡 Explain Code", "explain"),
            ("🔧 Refactor", "refactor"),
            ("🧪 Write Tests", "tests"),
            ("🐛 Debug Help", "debug"),
            ("📝 Add Docstrings", "docstring"),
        ]
        for label, action in actions:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, a=action: self.action_requested.emit(a))
            btn.setStyleSheet("text-align: left; padding: 6px 10px;")
            layout.addWidget(btn)

        layout.addStretch()

    def set_theme(self, is_dark: bool):
        color = "#858585" if is_dark else "#666666"
        self._header.setStyleSheet(f"font-size:10px; font-weight:bold; color:{color}; letter-spacing:1px;")

    def get_model(self) -> str:
        from src.config.settings import get_settings
        return get_settings().get("ai", "model") or "gpt-4o-mini"

    def get_provider(self) -> str:
        from src.config.settings import get_settings
        return get_settings().get("ai", "provider") or "openai"

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def get_temperature(self) -> float:
        from src.config.settings import get_settings
        return float(get_settings().get("ai", "temperature") or 0.7)


class SidebarWidget(QWidget):
    """
    Full left sidebar with icon strip + stacked panels.
    """
    file_opened = pyqtSignal(str)
    file_search_opened = pyqtSignal(str, int)
    ai_action_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Icon strip (vertical)
        self._icon_strip = QWidget()
        self._icon_strip.setObjectName("icon_strip")
        self._icon_strip.setFixedWidth(56)
        icon_layout = QVBoxLayout(self._icon_strip)
        icon_layout.setContentsMargins(4, 12, 4, 8)
        icon_layout.setSpacing(6)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._icon_buttons: list[QPushButton] = []
        self._panels_info = [("files", "Explorer", 0), ("search", "Search", 1), ("ai", "AI Tools", 2)]
        for icon_name, tooltip, idx in self._panels_info:
            btn = QPushButton()
            btn.setIconSize(QSize(24, 24))
            btn.setToolTip(tooltip)
            btn.setFixedSize(46, 46)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=idx: self._switch_panel(i))
            icon_layout.addWidget(btn)
            self._icon_buttons.append(btn)

        icon_layout.addStretch()
        layout.addWidget(self._icon_strip)

        # Stacked panels
        self._stack = QStackedWidget()
        self._explorer = FileExplorerPanel()
        self._search = SearchPanel()
        self._ai_tools = AIToolsPanel()

        self._stack.addWidget(self._explorer)
        self._stack.addWidget(self._search)
        self._stack.addWidget(self._ai_tools)
        layout.addWidget(self._stack)

        # Connect signals
        self._explorer.file_opened.connect(self.file_opened)
        self._search.file_opened.connect(self.file_search_opened)
        self._ai_tools.action_requested.connect(self.ai_action_requested)

        self.set_theme(True)

        # Start on explorer
        self._switch_panel(0)

    def _switch_panel(self, index: int):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._icon_buttons):
            btn.setChecked(i == index)

    def set_project(self, folder_path: str):
        self._explorer.set_project(folder_path)
        self._search.set_root(folder_path)

    def set_theme(self, is_dark: bool):
        self._explorer.set_theme(is_dark)
        self._search.set_theme(is_dark)
        self._ai_tools.set_theme(is_dark)
        
        icon_color = "#cccccc" if is_dark else "#555555"
        hover_bg = "rgba(255,255,255,0.10)" if is_dark else "rgba(0,0,0,0.06)"
        checked_bg = "rgba(0,122,204,0.30)" if is_dark else "rgba(0,122,204,0.15)"
        
        btn_style = f"""
            QPushButton {{
                border-radius: 8px;
                background: transparent;
                border: none;
                padding: 2px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
            QPushButton:checked {{
                background: {checked_bg};
                border-left: 3px solid #007acc;
            }}
        """
        for i, btn in enumerate(self._icon_buttons):
            icon_name = self._panels_info[i][0]
            btn.setIcon(make_icon(icon_name, icon_color, 24))
            btn.setStyleSheet(btn_style)

    def get_expanded_paths(self) -> list[str]:
        return self._explorer.get_expanded_paths()

    def restore_expanded_paths(self, paths: list[str]):
        self._explorer.restore_expanded_paths(paths)


    def get_ai_model(self) -> str:
        return self._ai_tools.get_model()

    def get_ai_provider(self) -> str:
        return self._ai_tools.get_provider()

    def get_ai_temperature(self) -> float:
        return self._ai_tools.get_temperature()
