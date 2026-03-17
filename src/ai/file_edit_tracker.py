"""
File Edit Tracker for AI Chat
Handles file edits without showing full diff in chat
"""

from PyQt6.QtCore import QObject, pyqtSignal
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class FileEditInfo:
    """Information about a file edit"""
    file_path: str
    file_name: str
    original_content: str
    new_content: str
    edit_type: str = "modify"  # 'create', 'modify', 'delete'
    accepted: bool = False
    rejected: bool = False


class FileEditTracker(QObject):
    """
    Tracks file edits made by AI
    Shows only filename in chat, opens diff in separate window when clicked
    """
    
    # Signals
    show_diff_requested = pyqtSignal(str)  # file_path
    open_file_requested = pyqtSignal(str)  # file_path
    file_accepted = pyqtSignal(str)  # file_path
    file_rejected = pyqtSignal(str)  # file_path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._edits: Dict[str, FileEditInfo] = {}
        self._completed_edits: List[FileEditInfo] = []
    
    def add_edit(self, file_path: str, original_content: str, new_content: str, 
                 edit_type: str = "modify") -> str:
        """
        Add a file edit to track
        
        Returns:
            edit_id: Unique identifier for this edit
        """
        import os
        file_name = os.path.basename(file_path)
        
        edit_info = FileEditInfo(
            file_path=file_path,
            file_name=file_name,
            original_content=original_content,
            new_content=new_content,
            edit_type=edit_type
        )
        
        self._edits[file_path] = edit_info
        
        # Return HTML for chat display
        return self._generate_chat_html(file_path, file_name)
    
    def _generate_chat_html(self, file_path: str, file_name: str) -> str:
        """Generate HTML to show in chat"""
        return f"""
<div class="file-edit-card" id="edit-{self._escape_id(file_path)}">
    <div class="file-edit-header">
        <span class="file-icon">📄</span>
        <span class="edit-label">Edited</span>
        <code class="file-name" onclick="openFile('{file_path}')">`{file_name}`</code>
    </div>
    <div class="file-edit-actions">
        <button class="diff-btn" onclick="showDiff('{file_path}')">
            <span class="diff-badge">DIFF</span>
        </button>
        <span class="file-path">{file_path}</span>
    </div>
    <div class="file-status" id="status-{self._escape_id(file_path)}">
        <span class="pending">⏳ Pending review</span>
    </div>
</div>
"""
    
    def _escape_id(self, file_path: str) -> str:
        """Escape file path for use in HTML ID"""
        return file_path.replace('/', '-').replace('\\', '-').replace('.', '-')
    
    def get_edit(self, file_path: str) -> Optional[FileEditInfo]:
        """Get edit info by file path"""
        return self._edits.get(file_path)
    
    def get_all_edits(self) -> List[FileEditInfo]:
        """Get all tracked edits"""
        return list(self._edits.values())
    
    def accept_edit(self, file_path: str):
        """Mark edit as accepted"""
        if file_path in self._edits:
            edit = self._edits[file_path]
            edit.accepted = True
            self._completed_edits.append(edit)
            del self._edits[file_path]
            self.file_accepted.emit(file_path)
            return True
        return False
    
    def reject_edit(self, file_path: str):
        """Mark edit as rejected"""
        if file_path in self._edits:
            edit = self._edits[file_path]
            edit.rejected = True
            self._completed_edits.append(edit)
            del self._edits[file_path]
            self.file_rejected.emit(file_path)
            return True
        return False
    
    def generate_summary_html(self) -> str:
        """Generate summary of all edits for task completion"""
        if not self._completed_edits:
            return ""
        
        html_parts = ["<div class=\"file-edit-summary\">"]
        html_parts.append("<h4>📁 Files Modified</h4>")
        html_parts.append("<ul>")
        
        for edit in self._completed_edits:
            status_icon = "✅" if edit.accepted else "❌"
            html_parts.append(f'<li>{status_icon} <code>{edit.file_name}</code></li>')
        
        html_parts.append("</ul>")
        html_parts.append("</div>")
        
        return "\n".join(html_parts)
    
    def has_pending_edits(self) -> bool:
        """Check if there are pending edits"""
        return len(self._edits) > 0
    
    def clear(self):
        """Clear all edits"""
        self._edits.clear()
        self._completed_edits.clear()


# CSS for file edit display in chat (add to style.css)
FILE_EDIT_CSS = """
/* File Edit Card in Chat */
.file-edit-card {
    background: #252526;
    border: 1px solid #3e3e42;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 12px 0;
    font-family: 'Segoe UI', sans-serif;
}

.file-edit-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
}

.file-icon {
    font-size: 14px;
}

.edit-label {
    color: #858585;
    font-size: 13px;
}

.file-name {
    color: #4ec9b0;
    font-size: 13px;
    cursor: pointer;
    text-decoration: underline;
}

.file-name:hover {
    color: #6adbc5;
}

.file-edit-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
}

.diff-btn {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    background: #238636;
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
}

.diff-btn:hover {
    background: #2ea043;
}

.diff-badge {
    background: rgba(255,255,255,0.2);
    padding: 2px 6px;
    border-radius: 3px;
}

.file-path {
    color: #6e6e6e;
    font-size: 11px;
    font-family: monospace;
}

.file-status {
    font-size: 12px;
    padding-top: 8px;
    border-top: 1px solid #3e3e42;
}

.file-status .pending {
    color: #d29922;
}

.file-status .accepted {
    color: #3fb950;
}

.file-status .rejected {
    color: #f85149;
}

/* File Edit Summary */
.file-edit-summary {
    background: #1e1e1e;
    border: 1px solid #3e3e42;
    border-radius: 6px;
    padding: 12px;
    margin: 12px 0;
}

.file-edit-summary h4 {
    margin: 0 0 8px 0;
    color: #cccccc;
    font-size: 13px;
}

.file-edit-summary ul {
    margin: 0;
    padding-left: 20px;
}

.file-edit-summary li {
    color: #d4d4d4;
    font-size: 12px;
    margin: 4px 0;
}

.file-edit-summary code {
    background: #252526;
    padding: 2px 4px;
    border-radius: 3px;
    color: #4ec9b0;
}
"""


# JavaScript handlers (add to script.js)
JS_FILE_EDIT_HANDLERS = """
// File edit handlers
function openFile(filePath) {
    if (bridge) {
        bridge.on_open_file(filePath);
    }
}

function showDiff(filePath) {
    if (bridge) {
        bridge.on_show_diff(filePath);
    }
}

function markFileAccepted(filePath) {
    const statusEl = document.getElementById('status-' + filePath.replace(/[^a-zA-Z0-9]/g, '-'));
    if (statusEl) {
        statusEl.innerHTML = '<span class="accepted">✅ Changes accepted and applied</span>';
    }
}

function markFileRejected(filePath) {
    const statusEl = document.getElementById('status-' + filePath.replace(/[^a-zA-Z0-9]/g, '-'));
    if (statusEl) {
        statusEl.innerHTML = '<span class="rejected">❌ Changes rejected</span>';
    }
}
"""


# Example usage in main_window.py
MAIN_WINDOW_INTEGRATION = """
# In main_window.py:

from src.ui.components.diff_viewer import DiffWindow
from src.ai.file_edit_tracker import FileEditTracker

class MainWindow:
    def __init__(self):
        # ... existing setup ...
        
        # Setup file edit tracking
        self._file_tracker = FileEditTracker(self)
        self._file_tracker.show_diff_requested.connect(self._on_show_diff)
        self._file_tracker.open_file_requested.connect(self._on_open_file)
        
        # Setup diff window (popup)
        self._diff_window = DiffWindow(self)
        self._diff_window.file_accepted.connect(self._on_file_accepted)
        self._diff_window.file_rejected.connect(self._on_file_rejected)
    
    def _on_show_diff(self, file_path: str):
        '''Show diff in separate window'''
        edit_info = self._file_tracker.get_edit(file_path)
        if edit_info:
            self._diff_window.show_diff(
                file_path,
                edit_info.original_content,
                edit_info.new_content
            )
    
    def _on_open_file(self, file_path: str):
        '''Open actual file in editor'''
        self.open_file(file_path)
    
    def _on_file_accepted(self, file_path: str, content: str):
        '''User accepted changes in diff window'''
        # Write file
        with open(file_path, 'w') as f:
            f.write(content)
        
        # Update tracker
        self._file_tracker.accept_edit(file_path)
        
        # Update chat UI
        self._ai_chat.mark_file_accepted(file_path)
    
    def _on_file_rejected(self, file_path: str):
        '''User rejected changes'''
        self._file_tracker.reject_edit(file_path)
        self._ai_chat.mark_file_rejected(file_path)
    
    def on_ai_edit_file(self, file_path: str, original: str, new_content: str):
        '''Called when AI edits a file'''
        # Add to tracker
        html = self._file_tracker.add_edit(file_path, original, new_content)
        
        # Show in chat (just the filename, not the diff)
        self._ai_chat.append_html(html)
"""
