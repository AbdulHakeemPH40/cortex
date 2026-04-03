"""
Permission System for Cortex IDE
Industry-standard permission dialogs for tool execution
Inspired by OpenCode's permission architecture
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTextEdit, QCheckBox, QWidget)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class PermissionDialog(QDialog):
    """
    Permission dialog for destructive operations.
    Shows what the AI wants to do and asks for user confirmation.
    """
    
    def __init__(self, tool_name: str, description: str, details: str, 
                 parent=None, remember_option: bool = True):
        super().__init__(parent)
        
        self.setWindowTitle(f"Permission Request: {tool_name}")
        self.setMinimumWidth(500)
        self.setModal(True)
        
        # Result
        self.approved = False
        self.remember_choice = False
        
        self._setup_ui(tool_name, description, details, remember_option)
    
    def _setup_ui(self, tool_name: str, description: str, details: str, 
                  remember_option: bool):
        """Setup the permission dialog UI."""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # Header with icon
        header_layout = QHBoxLayout()
        
        # Warning icon
        warning_label = QLabel("⚠️")
        warning_label.setFont(QFont("Segoe UI", 24))
        header_layout.addWidget(warning_label)
        
        # Title
        title_label = QLabel(f"<b>{tool_name}</b>")
        title_label.setFont(QFont("Segoe UI", 14))
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Description
        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setFont(QFont("Segoe UI", 10))
        layout.addWidget(desc_label)
        
        # Details (what will be changed)
        if details:
            details_label = QLabel("<b>What will be changed:</b>")
            layout.addWidget(details_label)
            
            details_text = QTextEdit()
            details_text.setPlainText(details)
            details_text.setReadOnly(True)
            details_text.setMaximumHeight(150)
            details_text.setFont(QFont("Consolas", 9))
            layout.addWidget(details_text)
        
        # Remember choice checkbox
        if remember_option:
            self.remember_checkbox = QCheckBox("Remember my choice for this session")
            self.remember_checkbox.setFont(QFont("Segoe UI", 9))
            layout.addWidget(self.remember_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Deny button
        deny_btn = QPushButton("❌ Deny")
        deny_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        deny_btn.clicked.connect(self._on_deny)
        button_layout.addWidget(deny_btn)
        
        # Approve button
        approve_btn = QPushButton("✅ Approve")
        approve_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        approve_btn.clicked.connect(self._on_approve)
        button_layout.addWidget(approve_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _on_approve(self):
        """Handle approve button click."""
        self.approved = True
        if hasattr(self, 'remember_checkbox'):
            self.remember_choice = self.remember_checkbox.isChecked()
        self.accept()
    
    def _on_deny(self):
        """Handle deny button click."""
        self.approved = False
        if hasattr(self, 'remember_checkbox'):
            self.remember_choice = self.remember_checkbox.isChecked()
        self.reject()


class PermissionManager:
    """
    Manages tool execution permissions.
    Tracks user choices and can auto-approve/deny based on preferences.
    """
    
    def __init__(self):
        # Session-based permission cache
        self._approved_tools = set()  # Tools approved for this session
        self._denied_tools = set()    # Tools denied for this session
        self._remembered_decisions = {}  # Tool -> bool (True=approve, False=deny)
    
    def is_auto_approved(self, tool_name: str) -> bool:
        """Check if tool is auto-approved (safe operations)."""
        # These tools never need permission
        safe_tools = {
            'read_file', 'opencode_read',
            'list_directory', 'opencode_list_dir',
            'glob', 'opencode_glob',
            'grep', 'opencode_grep',
            'search_code', 'search_codebase',
            'semantic_search',
            'get_file_outline', 'analyze_file',
            'find_usages', 'find_function', 'find_class',
            'check_syntax', 'get_problems', 'check_layout',
            'lsp_find_references', 'lsp_go_to_definition',
            'search_memory'
        }
        return tool_name in safe_tools
    
    def is_auto_denied(self, tool_name: str) -> bool:
        """Check if tool should be auto-denied (dangerous operations)."""
        # These tools are always denied
        dangerous_tools = {
            'format_system',  # Never allow formatting entire system
            'delete_all',     # Never allow mass deletion
        }
        return tool_name in dangerous_tools
    
    def check_permission(self, tool_name: str, params: dict = None) -> tuple[bool, str]:
        """
        Check if tool can be executed.
        
        Returns:
            (allowed: bool, reason: str)
        """
        # Check auto-approve list
        if self.is_auto_approved(tool_name):
            return True, "Auto-approved (safe operation)"
        
        # Check auto-deny list
        if self.is_auto_denied(tool_name):
            return False, "Auto-denied (dangerous operation)"
        
        # Check session cache
        if tool_name in self._approved_tools:
            return True, "Approved for this session"
        
        if tool_name in self._denied_tools:
            return False, "Denied for this session"
        
        # Check remembered decisions
        if tool_name in self._remembered_decisions:
            if self._remembered_decisions[tool_name]:
                return True, "Remembered approval"
            else:
                return False, "Remembered denial"
        
        # Needs user confirmation
        return None, "Requires user confirmation"
    
    def remember_decision(self, tool_name: str, approved: bool):
        """Remember a permission decision."""
        self._remembered_decisions[tool_name] = approved
    
    def add_session_approval(self, tool_name: str):
        """Add tool to session-approved list."""
        self._approved_tools.add(tool_name)
    
    def add_session_denial(self, tool_name: str):
        """Add tool to session-denied list."""
        self._denied_tools.add(tool_name)
    
    def clear_session(self):
        """Clear session-based permissions."""
        self._approved_tools.clear()
        self._denied_tools.clear()
    
    def get_permission_stats(self) -> dict:
        """Get statistics about permission usage."""
        return {
            'session_approved': len(self._approved_tools),
            'session_denied': len(self._denied_tools),
            'remembered_decisions': len(self._remembered_decisions)
        }


# Global permission manager instance
_permission_manager = None

def get_permission_manager() -> PermissionManager:
    """Get or create global permission manager."""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager()
    return _permission_manager


def show_permission_dialog(tool_name: str, description: str, details: str,
                           parent=None, remember_option: bool = True) -> tuple[bool, bool]:
    """
    Show permission dialog and return result.
    
    Args:
        tool_name: Name of the tool requesting permission
        description: What the tool will do
        details: Specific changes (e.g., file paths, diff preview)
        parent: Parent widget for modal dialog
        remember_option: Whether to show "remember choice" checkbox
    
    Returns:
        (approved: bool, remember: bool) - User's decision
    """
    dialog = PermissionDialog(tool_name, description, details, parent, remember_option)
    dialog.exec()
    
    return dialog.approved, dialog.remember_choice
