"""
Git UI Components for Cortex AI Agent IDE — VS Code-quality design.
Includes source control panel, diff view, commit dialog, and branch management.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem, QLineEdit,
    QComboBox, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget, QMessageBox, QInputDialog, QMenu,
    QCheckBox, QPlainTextEdit, QFrame, QScrollArea, QToolButton,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QIcon, QPainter, QPen, QBrush, QKeyEvent
from typing import List, Optional
from src.core.git_manager import GitManager, GitFile, GitStatus

# ── Status badge colors (VS Code standard) ──────────────────────────
_STATUS_COLORS = {
    GitStatus.MODIFIED:  "#E2C08D",   # M – yellow/gold
    GitStatus.ADDED:     "#73C991",   # A – green
    GitStatus.DELETED:   "#C74E39",   # D – red
    GitStatus.RENAMED:   "#73C991",   # R – green
    GitStatus.UNTRACKED: "#73C991",   # U – green
}
_STATUS_LETTERS = {
    GitStatus.MODIFIED:  "M",
    GitStatus.ADDED:     "A",
    GitStatus.DELETED:   "D",
    GitStatus.RENAMED:   "R",
    GitStatus.UNTRACKED: "U",
}

# ── Shared dark-theme stylesheet fragments ───────────────────────────
_DARK_BG         = "#1e1e1e"
_DARK_BG_SIDEBAR = "#252526"
_DARK_BORDER     = "#3e3e42"
_DARK_HOVER      = "#2a2d2e"
_DARK_SELECT     = "#094771"
_DARK_FG         = "#cccccc"
_DARK_FG_DIM     = "#858585"
_DARK_ACCENT     = "#0078d4"

_TOOL_BTN_STYLE = """
    QToolButton {
        background: transparent;
        border: none;
        border-radius: 4px;
        color: #cccccc;
        font-size: 14px;
        padding: 3px;
    }
    QToolButton:hover {
        background: #3e3e42;
    }
    QToolButton:pressed {
        background: #094771;
    }
"""

_SECTION_HEADER_STYLE = f"""
    QWidget {{
        background: transparent;
    }}
    QLabel {{
        color: {_DARK_FG};
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
    }}
"""


class _CommitMessageEdit(QTextEdit):
    """QTextEdit that emits commit_triggered on Ctrl+Enter."""
    commit_triggered = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commit_triggered.emit()
            return
        super().keyPressEvent(event)


class _FileItemWidget(QWidget):
    """Single file row: icon + filename + status badge (VS Code style)."""

    def __init__(self, filename: str, status: GitStatus, parent=None):
        super().__init__(parent)
        self.file_path = filename
        self.status = status

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 2, 8, 2)
        layout.setSpacing(6)

        # File name (just the basename, with path dimmed)
        import os
        base = os.path.basename(filename)
        directory = os.path.dirname(filename)

        name_label = QLabel(base)
        name_label.setStyleSheet(f"color: {_DARK_FG}; font-size: 13px;")
        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(name_label)

        if directory:
            dir_label = QLabel(directory)
            dir_label.setStyleSheet(f"color: {_DARK_FG_DIM}; font-size: 11px;")
            layout.addWidget(dir_label)

        # Status letter badge
        letter = _STATUS_LETTERS.get(status, "?")
        color = _STATUS_COLORS.get(status, _DARK_FG_DIM)
        badge = QLabel(letter)
        badge.setFixedWidth(18)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"""
            color: {color};
            font-size: 12px;
            font-weight: bold;
            font-family: 'Consolas', 'Courier New', monospace;
        """)
        layout.addWidget(badge)

        self.setFixedHeight(24)
        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border-radius: 3px;
            }}
            QWidget:hover {{
                background: {_DARK_HOVER};
            }}
        """)


class DiffViewWidget(QWidget):
    """Widget for viewing file diffs — clean VS Code style."""

    file_staged = pyqtSignal(str)
    file_unstaged = pyqtSignal(str)

    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self._current_file = None
        self._is_dark = True
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QFrame()
        header.setFixedHeight(32)
        header.setStyleSheet(f"background: {_DARK_BG_SIDEBAR}; border-bottom: 1px solid {_DARK_BORDER};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 8, 0)

        self.file_label = QLabel("Select a file to view diff")
        self.file_label.setStyleSheet(f"color: {_DARK_FG}; font-size: 12px;")
        hl.addWidget(self.file_label)
        hl.addStretch()

        self.stage_btn = QToolButton()
        self.stage_btn.setText("+")
        self.stage_btn.setToolTip("Stage this file")
        self.stage_btn.setStyleSheet(_TOOL_BTN_STYLE)
        self.stage_btn.setFixedSize(24, 24)
        self.stage_btn.clicked.connect(self._stage_file)
        hl.addWidget(self.stage_btn)

        layout.addWidget(header)

        # Diff display
        self.diff_text = QPlainTextEdit()
        self.diff_text.setReadOnly(True)
        self.diff_text.setFont(QFont("Consolas", 11))
        self.diff_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {_DARK_BG};
                color: {_DARK_FG};
                border: none;
                selection-background-color: {_DARK_SELECT};
            }}
        """)
        layout.addWidget(self.diff_text)

    def show_diff(self, file_path: str):
        self._current_file = file_path
        self.file_label.setText(file_path)
        diff = self.git.get_diff(file_path)
        if not diff:
            self.diff_text.setPlainText("No changes to display.")
            return
        self._display_colored_diff(diff)

    def _display_colored_diff(self, diff: str):
        self.diff_text.clear()
        cursor = self.diff_text.textCursor()
        for line in diff.split('\n'):
            if line.startswith('+'):
                color = QColor("#4ec9b0")
            elif line.startswith('-'):
                color = QColor("#f48771")
            elif line.startswith('@@'):
                color = QColor("#569cd6")
            elif line.startswith('diff') or line.startswith('index') or line.startswith('---') or line.startswith('+++'):
                color = QColor("#858585")
            else:
                color = QColor("#d4d4d4")
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.insertText(line + '\n', fmt)
        self.diff_text.setTextCursor(cursor)

    def _stage_file(self):
        if self._current_file:
            self.file_staged.emit(self._current_file)

    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark


class CommitDialog(QDialog):
    """Dialog for creating commits — clean dark theme."""

    commit_requested = pyqtSignal(str, bool)

    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self.setWindowTitle("Commit Changes")
        self.setMinimumSize(460, 360)
        self._build_ui()
        self._load_staged_files()

    def _build_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: {_DARK_BG_SIDEBAR};
                color: {_DARK_FG};
            }}
            QLabel {{
                color: {_DARK_FG};
                font-size: 12px;
            }}
            QListWidget {{
                background: {_DARK_BG};
                color: {_DARK_FG};
                border: 1px solid {_DARK_BORDER};
                border-radius: 4px;
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 3px 8px;
            }}
            QTextEdit {{
                background: {_DARK_BG};
                color: {_DARK_FG};
                border: 1px solid {_DARK_BORDER};
                border-radius: 4px;
                font-size: 12px;
            }}
            QCheckBox {{
                color: {_DARK_FG};
                font-size: 12px;
            }}
            QPushButton {{
                background: {_DARK_ACCENT};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: #1a8ad4;
            }}
            QPushButton#cancelBtn {{
                background: transparent;
                border: 1px solid {_DARK_BORDER};
                color: {_DARK_FG};
            }}
            QPushButton#cancelBtn:hover {{
                background: {_DARK_HOVER};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(QLabel("Staged Files"))
        self.files_list = QListWidget()
        self.files_list.setMaximumHeight(140)
        layout.addWidget(self.files_list)

        layout.addWidget(QLabel("Commit Message"))
        self.message_edit = QTextEdit()
        self.message_edit.setMaximumHeight(90)
        self.message_edit.setPlaceholderText("Enter commit message...")
        layout.addWidget(self.message_edit)

        self.amend_check = QCheckBox("Amend previous commit")
        layout.addWidget(self.amend_check)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("cancelBtn")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_commit = QPushButton("  Commit  ")
        self.btn_commit.setDefault(True)
        self.btn_commit.clicked.connect(self._on_commit)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_commit)
        layout.addLayout(btn_layout)

    def _load_staged_files(self):
        files = self.git.get_status()
        for f in files:
            if f.staged:
                letter = _STATUS_LETTERS.get(f.status, "?")
                self.files_list.addItem(f"{letter}  {f.path}")

    def _on_commit(self):
        message = self.message_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "Error", "Please enter a commit message.")
            return
        self.commit_requested.emit(message, self.amend_check.isChecked())
        self.accept()


class BranchManagerDialog(QDialog):
    """Dialog for managing branches — clean dark theme."""

    branch_created = pyqtSignal(str, bool)
    branch_deleted = pyqtSignal(str)
    branch_checked_out = pyqtSignal(str)
    branch_merged = pyqtSignal(str, str)

    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self.setWindowTitle("Branch Manager")
        self.setMinimumSize(460, 420)
        self._build_ui()
        self._load_branches()

    def _build_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: {_DARK_BG_SIDEBAR};
                color: {_DARK_FG};
            }}
            QLabel {{
                color: {_DARK_FG};
                font-size: 12px;
            }}
            QListWidget {{
                background: {_DARK_BG};
                color: {_DARK_FG};
                border: 1px solid {_DARK_BORDER};
                border-radius: 4px;
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 4px 10px;
            }}
            QListWidget::item:hover {{
                background: {_DARK_HOVER};
            }}
            QListWidget::item:selected {{
                background: {_DARK_SELECT};
            }}
            QPushButton {{
                background: transparent;
                border: 1px solid {_DARK_BORDER};
                border-radius: 4px;
                color: {_DARK_FG};
                padding: 5px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {_DARK_HOVER};
            }}
            QPushButton:disabled {{
                color: {_DARK_FG_DIM};
                border-color: {_DARK_BG};
            }}
            QPushButton#primaryBtn {{
                background: {_DARK_ACCENT};
                border: none;
                color: white;
            }}
            QPushButton#primaryBtn:hover {{
                background: #1a8ad4;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self.current_branch_label = QLabel()
        self.current_branch_label.setStyleSheet(f"color: {_DARK_FG}; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.current_branch_label)

        layout.addWidget(QLabel("Branches"))
        self.branch_list = QListWidget()
        self.branch_list.itemClicked.connect(self._on_branch_selected)
        layout.addWidget(self.branch_list)

        btn_layout = QHBoxLayout()
        self.btn_new = QPushButton("New Branch")
        self.btn_new.setObjectName("primaryBtn")
        self.btn_new.clicked.connect(self._create_branch)
        self.btn_checkout = QPushButton("Checkout")
        self.btn_checkout.clicked.connect(self._checkout_branch)
        self.btn_checkout.setEnabled(False)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self._delete_branch)
        self.btn_delete.setEnabled(False)
        self.btn_merge = QPushButton("Merge")
        self.btn_merge.clicked.connect(self._merge_branch)
        self.btn_merge.setEnabled(False)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_new)
        btn_layout.addWidget(self.btn_checkout)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_merge)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

    def _load_branches(self):
        self.branch_list.clear()
        current = self.git.get_branch()
        self.current_branch_label.setText(f"Current branch:  {current}")
        branches = self.git.get_branches()
        for branch in branches:
            name = branch[2:] if branch.startswith('*') else branch.strip()
            item = QListWidgetItem(name)
            if name == current:
                item.setForeground(QColor(_DARK_ACCENT))
                item.setText(f"* {name}")
            self.branch_list.addItem(item)

    def _on_branch_selected(self, item: QListWidgetItem):
        branch = item.text().lstrip('* ').strip()
        current = self.git.get_branch()
        is_current = branch == current
        self.btn_checkout.setEnabled(not is_current)
        self.btn_delete.setEnabled(not is_current)
        self.btn_merge.setEnabled(not is_current)

    def _create_branch(self):
        name, ok = QInputDialog.getText(self, "New Branch", "Branch name:")
        if ok and name:
            self.branch_created.emit(name, True)
            self._load_branches()

    def _checkout_branch(self):
        item = self.branch_list.currentItem()
        if item:
            branch = item.text().lstrip('* ').strip()
            self.branch_checked_out.emit(branch)
            self._load_branches()

    def _delete_branch(self):
        item = self.branch_list.currentItem()
        if item:
            branch = item.text().lstrip('* ').strip()
            reply = QMessageBox.question(
                self, "Delete Branch",
                f"Delete branch '{branch}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.branch_deleted.emit(branch)
                self._load_branches()

    def _merge_branch(self):
        item = self.branch_list.currentItem()
        if item:
            source = item.text().lstrip('* ').strip()
            target = self.git.get_branch()
            reply = QMessageBox.question(
                self, "Merge Branch",
                f"Merge '{source}' into '{target}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.branch_merged.emit(source, target)


class _HistoryItemWidget(QWidget):
    """Single commit row for history view."""

    def __init__(self, short_hash: str, message: str, author: str, date: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        # Hash badge
        hash_label = QLabel(short_hash)
        hash_label.setFixedWidth(60)
        hash_label.setStyleSheet(f"""
            color: {_DARK_ACCENT};
            font-family: 'Consolas', monospace;
            font-size: 11px;
        """)
        layout.addWidget(hash_label)

        # Message + meta
        right = QVBoxLayout()
        right.setSpacing(1)
        msg = QLabel(message[:60] + ("..." if len(message) > 60 else ""))
        msg.setStyleSheet(f"color: {_DARK_FG}; font-size: 12px;")
        right.addWidget(msg)

        meta = QLabel(f"{author}  ·  {date}")
        meta.setStyleSheet(f"color: {_DARK_FG_DIM}; font-size: 10px;")
        right.addWidget(meta)

        layout.addLayout(right, 1)

        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
            }}
        """)


class GitPanelWidget(QWidget):
    """Main Git Source Control panel — VS Code-quality design.

    Layout:
    ┌─────────────────────────────────┐
    │  ⎇ branch-name   ↻  ✓  ⋯      │  ← compact header
    ├─────────────────────────────────┤
    │  [Commit message input........] │  ← inline commit input
    │  [  Commit  ]                   │
    ├─────────────────────────────────┤
    │  ▸ STAGED CHANGES (n)           │  ← collapsible section
    │     filename.py           M     │
    ├─────────────────────────────────┤
    │  ▸ CHANGES (n)                  │  ← collapsible section
    │     filename.py           U     │
    └─────────────────────────────────┘
    """

    refresh_requested = pyqtSignal()

    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self._is_dark = True
        self._staged_files: list[GitFile] = []
        self._unstaged_files: list[GitFile] = []
        self._build_ui()

    # ── Build ────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setStyleSheet(f"background: {_DARK_BG_SIDEBAR};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ──────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(36)
        header.setStyleSheet(f"""
            QFrame {{
                background: {_DARK_BG_SIDEBAR};
                border-bottom: 1px solid {_DARK_BORDER};
            }}
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 6, 0)
        hl.setSpacing(4)

        # Branch icon + name
        self.branch_label = QLabel("SOURCE CONTROL")
        self.branch_label.setStyleSheet(f"""
            color: {_DARK_FG};
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        """)
        hl.addWidget(self.branch_label)
        hl.addStretch()

        # Action buttons (icon-only)
        for text, tip, slot in [
            ("\u21BB", "Refresh", self.refresh),          # ↻
            ("\u2026", "More Actions...", self._show_more_menu),  # …
        ]:
            btn = QToolButton()
            btn.setText(text)
            btn.setToolTip(tip)
            btn.setFixedSize(26, 26)
            btn.setStyleSheet(_TOOL_BTN_STYLE)
            btn.clicked.connect(slot)
            hl.addWidget(btn)

        root.addWidget(header)

        # ── Scrollable body ─────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: {_DARK_BG_SIDEBAR};
            }}
            QScrollBar:vertical {{
                width: 8px;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: #5a5a5a;
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        body = QWidget()
        body.setStyleSheet(f"background: {_DARK_BG_SIDEBAR};")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)

        # ── Commit input area ───────────────────────────────────────
        commit_area = QWidget()
        cl = QVBoxLayout(commit_area)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)

        self.commit_input = _CommitMessageEdit()
        self.commit_input.setPlaceholderText("Message (press Ctrl+Enter to commit)")
        self.commit_input.commit_triggered.connect(self._do_commit)
        self.commit_input.setMaximumHeight(60)
        self.commit_input.setStyleSheet(f"""
            QTextEdit {{
                background: {_DARK_BG};
                color: {_DARK_FG};
                border: 1px solid {_DARK_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QTextEdit:focus {{
                border-color: {_DARK_ACCENT};
            }}
        """)
        cl.addWidget(self.commit_input)

        self.commit_btn = QPushButton("Commit")
        self.commit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.commit_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_DARK_ACCENT};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 0;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #1a8ad4;
            }}
            QPushButton:pressed {{
                background: #005a9e;
            }}
        """)
        self.commit_btn.clicked.connect(self._do_commit)
        cl.addWidget(self.commit_btn)

        self._body_layout.addWidget(commit_area)

        # ── Staged section ──────────────────────────────────────────
        self._staged_section = self._make_section("STAGED CHANGES")
        self._staged_container = QVBoxLayout()
        self._staged_container.setContentsMargins(0, 0, 0, 0)
        self._staged_container.setSpacing(0)
        self._staged_section["content_layout"].addLayout(self._staged_container)
        self._body_layout.addWidget(self._staged_section["widget"])

        # ── Changes (unstaged) section ──────────────────────────────
        self._changes_section = self._make_section("CHANGES")
        self._changes_container = QVBoxLayout()
        self._changes_container.setContentsMargins(0, 0, 0, 0)
        self._changes_container.setSpacing(0)
        self._changes_section["content_layout"].addLayout(self._changes_container)
        self._body_layout.addWidget(self._changes_section["widget"])

        self._body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll)

    def _make_section(self, title: str) -> dict:
        """Create a collapsible section with a header and content area."""
        widget = QWidget()
        widget.setStyleSheet(f"background: {_DARK_BG_SIDEBAR};")
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Section header
        header_widget = QWidget()
        header_widget.setFixedHeight(26)
        header_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        header_widget.setStyleSheet(f"""
            QWidget {{
                background: {_DARK_BG_SIDEBAR};
            }}
            QWidget:hover {{
                background: {_DARK_HOVER};
            }}
        """)
        hl = QHBoxLayout(header_widget)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(4)

        arrow = QLabel("\u25B8")  # ▸
        arrow.setFixedWidth(12)
        arrow.setStyleSheet(f"color: {_DARK_FG}; font-size: 10px;")
        hl.addWidget(arrow)

        label = QLabel(title)
        label.setStyleSheet(f"color: {_DARK_FG}; font-size: 11px; font-weight: 600;")
        hl.addWidget(label)

        count_label = QLabel("0")
        count_label.setStyleSheet(f"color: {_DARK_FG_DIM}; font-size: 11px;")
        hl.addWidget(count_label)

        hl.addStretch()

        # Stage all / Unstage all button
        action_btn = QToolButton()
        action_btn.setFixedSize(20, 20)
        action_btn.setStyleSheet(_TOOL_BTN_STYLE + "QToolButton { font-size: 12px; }")
        hl.addWidget(action_btn)

        outer.addWidget(header_widget)

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        outer.addWidget(content)

        # Store references
        section = {
            "widget": widget,
            "arrow": arrow,
            "label": label,
            "count": count_label,
            "content": content,
            "content_layout": content_layout,
            "action_btn": action_btn,
            "collapsed": False,
        }

        # Toggle collapse
        def toggle(event=None, s=section):
            s["collapsed"] = not s["collapsed"]
            s["content"].setVisible(not s["collapsed"])
            s["arrow"].setText("\u25B8" if s["collapsed"] else "\u25BE")  # ▸ or ▾

        header_widget.mousePressEvent = toggle

        return section

    # ── More menu ────────────────────────────────────────────────────
    def _show_more_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {_DARK_BG_SIDEBAR};
                color: {_DARK_FG};
                border: 1px solid {_DARK_BORDER};
                padding: 4px 0;
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 5px 20px;
            }}
            QMenu::item:selected {{
                background: {_DARK_SELECT};
            }}
            QMenu::separator {{
                height: 1px;
                background: {_DARK_BORDER};
                margin: 4px 8px;
            }}
        """)
        menu.addAction("Commit", self._do_commit)
        menu.addAction("Commit (Amend)", self._do_amend_commit)
        menu.addSeparator()
        menu.addAction("Stage All", self._stage_all)
        menu.addAction("Unstage All", self._unstage_all)
        menu.addSeparator()
        menu.addAction("Push", self._push)
        menu.addAction("Pull", self._pull)
        menu.addSeparator()
        menu.addAction("Branch Manager...", self._show_branch_manager)

        sender = self.sender()
        if sender:
            menu.exec(sender.mapToGlobal(sender.rect().bottomLeft()))

    # ── Refresh ──────────────────────────────────────────────────────
    def refresh(self):
        if not self.git.is_repo():
            self.branch_label.setText("No repository")
            return

        branch = self.git.get_branch()
        self.branch_label.setText(f"SOURCE CONTROL  —  {branch}")

        # Get file status
        files = self.git.get_status()
        self._staged_files = [f for f in files if f.staged]
        self._unstaged_files = [f for f in files if not f.staged]

        # Update staged section
        self._clear_layout(self._staged_container)
        for f in self._staged_files:
            item = _FileItemWidget(f.path, f.status)
            item.mousePressEvent = lambda e, fp=f.path: self._on_staged_clicked(fp)
            item.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            item.customContextMenuRequested.connect(lambda pos, fp=f.path: self._staged_ctx(pos, fp))
            self._staged_container.addWidget(item)
        self._staged_section["count"].setText(str(len(self._staged_files)))
        self._staged_section["action_btn"].setText("\u2212")  # −
        self._staged_section["action_btn"].setToolTip("Unstage All")
        try:
            self._staged_section["action_btn"].clicked.disconnect()
        except Exception:
            pass
        self._staged_section["action_btn"].clicked.connect(self._unstage_all)

        # Update changes section
        self._clear_layout(self._changes_container)
        for f in self._unstaged_files:
            item = _FileItemWidget(f.path, f.status)
            item.mousePressEvent = lambda e, fp=f.path: self._on_unstaged_clicked(fp)
            item.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            item.customContextMenuRequested.connect(lambda pos, fp=f.path: self._unstaged_ctx(pos, fp))
            self._changes_container.addWidget(item)
        self._changes_section["count"].setText(str(len(self._unstaged_files)))
        self._changes_section["action_btn"].setText("+")
        self._changes_section["action_btn"].setToolTip("Stage All")
        try:
            self._changes_section["action_btn"].clicked.disconnect()
        except Exception:
            pass
        self._changes_section["action_btn"].clicked.connect(self._stage_all)

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # ── File interaction ─────────────────────────────────────────────
    def _on_staged_clicked(self, file_path: str):
        pass  # Could show diff of staged

    def _on_unstaged_clicked(self, file_path: str):
        pass  # Could show diff of unstaged in future embedded diff

    def _staged_ctx(self, pos, file_path: str):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {_DARK_BG_SIDEBAR};
                color: {_DARK_FG};
                border: 1px solid {_DARK_BORDER};
                font-size: 12px;
            }}
            QMenu::item {{ padding: 5px 20px; }}
            QMenu::item:selected {{ background: {_DARK_SELECT}; }}
        """)
        action = menu.addAction("Unstage")
        result = menu.exec(self.mapToGlobal(pos))
        if result == action:
            self.git.unstage_file(file_path)
            self.refresh()

    def _unstaged_ctx(self, pos, file_path: str):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {_DARK_BG_SIDEBAR};
                color: {_DARK_FG};
                border: 1px solid {_DARK_BORDER};
                font-size: 12px;
            }}
            QMenu::item {{ padding: 5px 20px; }}
            QMenu::item:selected {{ background: {_DARK_SELECT}; }}
        """)
        a_stage = menu.addAction("Stage")
        a_discard = menu.addAction("Discard Changes")
        result = menu.exec(self.mapToGlobal(pos))
        if result == a_stage:
            self.git.stage_file(file_path)
            self.refresh()
        elif result == a_discard:
            reply = QMessageBox.question(
                self, "Discard Changes",
                f"Discard changes in {file_path}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.git.discard_changes(file_path)
                self.refresh()

    # ── Actions ──────────────────────────────────────────────────────
    def _do_commit(self):
        msg = self.commit_input.toPlainText().strip()
        if not msg:
            self.commit_input.setFocus()
            self.commit_input.setStyleSheet(self.commit_input.styleSheet().replace(
                f"border: 1px solid {_DARK_BORDER}",
                "border: 1px solid #f44747"
            ))
            return
        # Reset border
        self.commit_input.setStyleSheet(self.commit_input.styleSheet().replace(
            "border: 1px solid #f44747",
            f"border: 1px solid {_DARK_BORDER}"
        ))
        success, error = self.git.commit(msg)
        if success:
            self.commit_input.clear()
            self.refresh()
        else:
            QMessageBox.warning(self, "Commit Failed", error)

    def _do_amend_commit(self):
        msg = self.commit_input.toPlainText().strip()
        if not msg:
            QMessageBox.warning(self, "Error", "Enter a commit message first.")
            return
        success, error = self.git.commit(msg, amend=True)
        if success:
            self.commit_input.clear()
            self.refresh()
        else:
            QMessageBox.warning(self, "Amend Failed", error)

    def _stage_all(self):
        for f in self._unstaged_files:
            self.git.stage_file(f.path)
        self.refresh()

    def _unstage_all(self):
        for f in self._staged_files:
            self.git.unstage_file(f.path)
        self.refresh()

    def _push(self):
        success, message = self.git.push()
        if success:
            QMessageBox.information(self, "Push", "Pushed successfully!")
        else:
            QMessageBox.warning(self, "Push Failed", message)

    def _pull(self):
        success, message = self.git.pull()
        if success:
            QMessageBox.information(self, "Pull", "Pulled successfully!")
        else:
            QMessageBox.warning(self, "Pull Failed", message)

    def _show_branch_manager(self):
        dialog = BranchManagerDialog(self.git, self)
        dialog.exec()
        self.refresh()

    def _show_commit_dialog(self):
        dialog = CommitDialog(self.git, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def set_theme(self, is_dark: bool):
        self._is_dark = is_dark
