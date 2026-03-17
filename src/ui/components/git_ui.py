"""
Git UI Components for Cortex AI Agent IDE
Includes diff view, commit dialog, and branch management
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QListWidget, QListWidgetItem, QLineEdit,
    QComboBox, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget, QMessageBox, QInputDialog, QMenu,
    QCheckBox, QPlainTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat
from typing import List, Optional
from src.core.git_manager import GitManager, GitFile, GitStatus


class DiffViewWidget(QWidget):
    """Widget for viewing file diffs."""
    
    file_staged = pyqtSignal(str)  # file_path
    file_unstaged = pyqtSignal(str)  # file_path
    
    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self._current_file = None
        self._is_dark = True
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header with file info
        header = QWidget()
        header.setFixedHeight(35)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        self.file_label = QLabel("Select a file to view diff")
        self.file_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self.file_label)
        header_layout.addStretch()
        
        self.stage_btn = QPushButton("Stage")
        self.stage_btn.clicked.connect(self._stage_file)
        header_layout.addWidget(self.stage_btn)
        
        layout.addWidget(header)
        
        # Diff display
        self.diff_text = QPlainTextEdit()
        self.diff_text.setReadOnly(True)
        self.diff_text.setFont(QFont("Courier New", 11))
        
        layout.addWidget(self.diff_text)
        
        self._update_style()
        
    def _update_style(self):
        """Update styling based on theme."""
        if self._is_dark:
            self.diff_text.setStyleSheet("""
                QPlainTextEdit {
                    background-color: #1e1e1e;
                    color: #d4d4d4;
                    border: none;
                }
            """)
        else:
            self.diff_text.setStyleSheet("""
                QPlainTextEdit {
                    background-color: #ffffff;
                    color: #24292e;
                    border: none;
                }
            """)
            
    def show_diff(self, file_path: str):
        """Show diff for a file."""
        self._current_file = file_path
        self.file_label.setText(f"📄 {file_path}")
        
        # Get diff
        diff = self.git.get_diff(file_path)
        
        if not diff:
            self.diff_text.setPlainText("No changes to display.")
            return
            
        # Format and display diff with syntax highlighting
        self._display_colored_diff(diff)
        
    def _display_colored_diff(self, diff: str):
        """Display diff with colors."""
        self.diff_text.clear()
        cursor = self.diff_text.textCursor()
        
        for line in diff.split('\n'):
            # Determine line type
            if line.startswith('+'):
                color = QColor("#4ec9b0") if self._is_dark else QColor("#22863a")
            elif line.startswith('-'):
                color = QColor("#f48771") if self._is_dark else QColor("#cb2431")
            elif line.startswith('@@'):
                color = QColor("#569cd6") if self._is_dark else QColor("#032f62")
            elif line.startswith('diff') or line.startswith('index') or line.startswith('---') or line.startswith('+++'):
                color = QColor("#858585") if self._is_dark else QColor("#6a737d")
            else:
                color = QColor("#d4d4d4") if self._is_dark else QColor("#24292e")
                
            # Insert with color
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.insertText(line + '\n', fmt)
            
        self.diff_text.setTextCursor(cursor)
        
    def _stage_file(self):
        """Stage the current file."""
        if self._current_file:
            self.file_staged.emit(self._current_file)
            
    def set_theme(self, is_dark: bool):
        """Update theme."""
        self._is_dark = is_dark
        self._update_style()


class CommitDialog(QDialog):
    """Dialog for creating commits."""
    
    commit_requested = pyqtSignal(str, bool)  # message, amend
    
    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self.setWindowTitle("Commit Changes")
        self.setMinimumSize(500, 400)
        self._build_ui()
        self._load_staged_files()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Staged files list
        layout.addWidget(QLabel("Staged Files:"))
        self.files_list = QListWidget()
        self.files_list.setMaximumHeight(150)
        layout.addWidget(self.files_list)
        
        # Commit message
        layout.addWidget(QLabel("Commit Message:"))
        self.message_edit = QTextEdit()
        self.message_edit.setMaximumHeight(100)
        self.message_edit.setPlaceholderText("Enter commit message...")
        layout.addWidget(self.message_edit)
        
        # Amend checkbox
        self.amend_check = QCheckBox("Amend previous commit")
        layout.addWidget(self.amend_check)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_commit = QPushButton("Commit")
        self.btn_commit.setDefault(True)
        self.btn_commit.clicked.connect(self._on_commit)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_commit)
        
        layout.addLayout(btn_layout)
        
    def _load_staged_files(self):
        """Load staged files."""
        files = self.git.get_status()
        for f in files:
            if f.staged:
                self.files_list.addItem(f"✅ {f.path}")
                
    def _on_commit(self):
        """Handle commit button."""
        message = self.message_edit.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "Error", "Please enter a commit message.")
            return
            
        amend = self.amend_check.isChecked()
        self.commit_requested.emit(message, amend)
        self.accept()


class BranchManagerDialog(QDialog):
    """Dialog for managing branches."""
    
    branch_created = pyqtSignal(str, bool)  # branch_name, checkout
    branch_deleted = pyqtSignal(str)  # branch_name
    branch_checked_out = pyqtSignal(str)  # branch_name
    branch_merged = pyqtSignal(str, str)  # source, target
    
    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self.setWindowTitle("Branch Manager")
        self.setMinimumSize(500, 500)
        self._build_ui()
        self._load_branches()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Current branch label
        self.current_branch_label = QLabel()
        layout.addWidget(self.current_branch_label)
        
        # Branch list
        layout.addWidget(QLabel("Branches:"))
        self.branch_list = QListWidget()
        self.branch_list.itemClicked.connect(self._on_branch_selected)
        layout.addWidget(self.branch_list)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_new = QPushButton("New Branch")
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
        """Load branches."""
        self.branch_list.clear()
        
        current = self.git.get_branch()
        self.current_branch_label.setText(f"Current: 📍 {current}")
        
        branches = self.git.get_branches()
        for branch in branches:
            if branch.startswith('*'):
                item_text = f"📍 {branch[2:]}"
            else:
                item_text = f"  {branch}"
            self.branch_list.addItem(item_text)
            
    def _on_branch_selected(self, item: QListWidgetItem):
        """Handle branch selection."""
        branch = item.text().strip().lstrip('📍').strip()
        current = self.git.get_branch()
        
        is_current = branch == current
        self.btn_checkout.setEnabled(not is_current)
        self.btn_delete.setEnabled(not is_current)
        self.btn_merge.setEnabled(not is_current)
        
    def _create_branch(self):
        """Create new branch."""
        name, ok = QInputDialog.getText(self, "New Branch", "Branch name:")
        if ok and name:
            checkout, ok = QInputDialog.question(
                self, "Checkout", "Checkout the new branch?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            self.branch_created.emit(name, checkout == QMessageBox.StandardButton.Yes)
            self._load_branches()
            
    def _checkout_branch(self):
        """Checkout selected branch."""
        item = self.branch_list.currentItem()
        if item:
            branch = item.text().strip().lstrip('📍').strip()
            self.branch_checked_out.emit(branch)
            self._load_branches()
            
    def _delete_branch(self):
        """Delete selected branch."""
        item = self.branch_list.currentItem()
        if item:
            branch = item.text().strip().lstrip('📍').strip()
            reply = QMessageBox.question(
                self, "Delete Branch",
                f"Are you sure you want to delete '{branch}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.branch_deleted.emit(branch)
                self._load_branches()
                
    def _merge_branch(self):
        """Merge selected branch into current."""
        item = self.branch_list.currentItem()
        if item:
            source = item.text().strip().lstrip('📍').strip()
            target = self.git.get_branch()
            reply = QMessageBox.question(
                self, "Merge Branch",
                f"Merge '{source}' into '{target}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.branch_merged.emit(source, target)
                QMessageBox.information(self, "Success", f"Merged '{source}' into '{target}'")


class GitPanelWidget(QWidget):
    """Main Git panel with status, diff, and commit."""
    
    refresh_requested = pyqtSignal()
    
    def __init__(self, git_manager: GitManager, parent=None):
        super().__init__(parent)
        self.git = git_manager
        self._is_dark = True
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(35)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        self.branch_label = QLabel("No repository")
        self.branch_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self.branch_label)
        
        header_layout.addStretch()
        
        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setFixedSize(28, 28)
        self.btn_refresh.setToolTip("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        
        self.btn_commit = QPushButton("Commit")
        self.btn_commit.clicked.connect(self._show_commit_dialog)
        
        self.btn_branch = QPushButton("Branches")
        self.btn_branch.clicked.connect(self._show_branch_manager)
        
        self.btn_push = QPushButton("Push")
        self.btn_push.clicked.connect(self._push)
        
        self.btn_pull = QPushButton("Pull")
        self.btn_pull.clicked.connect(self._pull)
        
        header_layout.addWidget(self.btn_refresh)
        header_layout.addWidget(self.btn_commit)
        header_layout.addWidget(self.btn_branch)
        header_layout.addWidget(self.btn_push)
        header_layout.addWidget(self.btn_pull)
        
        layout.addWidget(header)
        
        # Tab widget for different views
        self.tabs = QTabWidget()
        
        # Status tab
        self.status_widget = self._create_status_view()
        self.tabs.addTab(self.status_widget, "Changes")
        
        # Diff tab
        self.diff_view = DiffViewWidget(self.git)
        self.diff_view.file_staged.connect(self._stage_file)
        self.tabs.addTab(self.diff_view, "Diff")
        
        # History tab
        self.history_widget = self._create_history_view()
        self.tabs.addTab(self.history_widget, "History")
        
        layout.addWidget(self.tabs)
        
        self._update_style()
        
    def _create_status_view(self) -> QWidget:
        """Create the status view with staged/unstaged files."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Staged files
        layout.addWidget(QLabel("📦 Staged:"))
        self.staged_list = QListWidget()
        self.staged_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.staged_list.customContextMenuRequested.connect(self._show_staged_context_menu)
        layout.addWidget(self.staged_list)
        
        # Unstaged files
        layout.addWidget(QLabel("📝 Unstaged:"))
        self.unstaged_list = QListWidget()
        self.unstaged_list.itemClicked.connect(self._on_unstaged_clicked)
        self.unstaged_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.unstaged_list.customContextMenuRequested.connect(self._show_unstaged_context_menu)
        layout.addWidget(self.unstaged_list)
        
        return widget
        
    def _create_history_view(self) -> QWidget:
        """Create the commit history view."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        self.history_list = QListWidget()
        layout.addWidget(self.history_list)
        
        return widget
        
    def _update_style(self):
        """Update styling."""
        if self._is_dark:
            style = """
                QListWidget {
                    background-color: #1e1e1e;
                    color: #d4d4d4;
                    border: 1px solid #3e3e42;
                }
                QListWidget::item {
                    padding: 4px 8px;
                }
                QListWidget::item:hover {
                    background-color: #2a2d2e;
                }
                QListWidget::item:selected {
                    background-color: #094771;
                }
            """
        else:
            style = """
                QListWidget {
                    background-color: #ffffff;
                    color: #24292e;
                    border: 1px solid #e1e4e8;
                }
                QListWidget::item {
                    padding: 4px 8px;
                }
                QListWidget::item:hover {
                    background-color: #f6f8fa;
                }
                QListWidget::item:selected {
                    background-color: #e1e4e8;
                }
            """
            
        self.staged_list.setStyleSheet(style)
        self.unstaged_list.setStyleSheet(style)
        self.history_list.setStyleSheet(style)
        
    def refresh(self):
        """Refresh git status."""
        if not self.git.is_repo():
            self.branch_label.setText("Not a git repository")
            return
            
        # Update branch label
        branch = self.git.get_branch()
        self.branch_label.setText(f"🌿 {branch}")
        
        # Update file lists
        self._update_file_lists()
        
        # Update history
        self._update_history()
        
    def _update_file_lists(self):
        """Update staged and unstaged file lists."""
        self.staged_list.clear()
        self.unstaged_list.clear()
        
        files = self.git.get_status()
        
        for f in files:
            icon = self._get_status_icon(f.status)
            text = f"{icon} {f.path}"
            
            if f.staged:
                self.staged_list.addItem(text)
            else:
                self.unstaged_list.addItem(text)
                
    def _update_history(self):
        """Update commit history."""
        self.history_list.clear()
        
        commits = self.git.get_commits(20)
        for commit in commits:
            text = f"{commit.short_hash} - {commit.message[:50]}"
            if len(commit.message) > 50:
                text += "..."
            text += f"\n   {commit.author} • {commit.date}"
            self.history_list.addItem(text)
            
    def _get_status_icon(self, status: GitStatus) -> str:
        """Get icon for git status."""
        icons = {
            GitStatus.MODIFIED: "📝",
            GitStatus.ADDED: "➕",
            GitStatus.DELETED: "🗑️",
            GitStatus.RENAMED: "📛",
            GitStatus.UNTRACKED: "❓",
        }
        return icons.get(status, "📄")
        
    def _on_unstaged_clicked(self, item: QListWidgetItem):
        """Show diff for unstaged file."""
        text = item.text()
        # Extract filename (remove icon and status)
        file_path = text[2:]  # Skip icon and space
        self.diff_view.show_diff(file_path)
        self.tabs.setCurrentWidget(self.diff_view)
        
    def _stage_file(self, file_path: str):
        """Stage a file."""
        self.git.stage_file(file_path)
        self.refresh()
        
    def _unstage_file(self, file_path: str):
        """Unstage a file."""
        self.git.unstage_file(file_path)
        self.refresh()
        
    def _discard_changes(self, file_path: str):
        """Discard changes in a file."""
        reply = QMessageBox.question(
            self, "Discard Changes",
            f"Are you sure you want to discard changes in {file_path}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.git.discard_changes(file_path)
            self.refresh()
            
    def _show_commit_dialog(self):
        """Show commit dialog."""
        dialog = CommitDialog(self.git, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            
    def _show_branch_manager(self):
        """Show branch manager."""
        dialog = BranchManagerDialog(self.git, self)
        dialog.exec()
        self.refresh()
        
    def _push(self):
        """Push to remote."""
        success, message = self.git.push()
        if success:
            QMessageBox.information(self, "Success", "Pushed successfully!")
        else:
            QMessageBox.warning(self, "Error", f"Push failed:\n{message}")
        self.refresh()
        
    def _pull(self):
        """Pull from remote."""
        success, message = self.git.pull()
        if success:
            QMessageBox.information(self, "Success", "Pulled successfully!")
        else:
            QMessageBox.warning(self, "Error", f"Pull failed:\n{message}")
        self.refresh()
        
    def _show_staged_context_menu(self, position):
        """Show context menu for staged files."""
        menu = QMenu(self)
        action_unstage = menu.addAction("Unstage")
        
        item = self.staged_list.itemAt(position)
        action = menu.exec(self.staged_list.viewport().mapToGlobal(position))
        
        if action == action_unstage and item:
            file_path = item.text()[2:]  # Skip icon
            self._unstage_file(file_path)
            
    def _show_unstaged_context_menu(self, position):
        """Show context menu for unstaged files."""
        menu = QMenu(self)
        action_stage = menu.addAction("Stage")
        action_discard = menu.addAction("Discard Changes")
        
        item = self.unstaged_list.itemAt(position)
        action = menu.exec(self.unstaged_list.viewport().mapToGlobal(position))
        
        if item:
            file_path = item.text()[2:]  # Skip icon
            if action == action_stage:
                self._stage_file(file_path)
            elif action == action_discard:
                self._discard_changes(file_path)
                
    def set_theme(self, is_dark: bool):
        """Update theme."""
        self._is_dark = is_dark
        self._update_style()
        self.diff_view.set_theme(is_dark)
