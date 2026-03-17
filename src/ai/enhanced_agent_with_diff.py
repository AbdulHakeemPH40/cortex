"""
Enhanced AI Agent with Diff Viewer Integration
Tracks file changes and shows diff viewer for edited files
"""

import os
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from PyQt6.QtCore import QObject, pyqtSignal

from src.ai.agent import AIAgent
from src.ai.task_queue import TaskQueue, Task, TaskStatus, TaskPriority, get_task_queue, TaskStep
from src.ai.project_analyzer import ProjectAnalyzer, get_project_analyzer
from src.utils.logger import get_logger

log = get_logger("enhanced_agent_with_diff")


class FileEdit:
    """Represents a file edit operation"""
    def __init__(self, file_path: str, original_content: str, new_content: str, 
                 edit_type: str = "modify"):
        self.file_path = file_path
        self.original_content = original_content
        self.new_content = new_content
        self.edit_type = edit_type  # 'create', 'modify', 'delete'
        self.accepted = False
        self.rejected = False


class EnhancedAIAgentWithDiff(AIAgent):
    """
    Enhanced AI Agent with Diff Viewer support
    Tracks file changes and shows diffs before applying
    """
    
    # New signals for file editing
    file_edit_created = pyqtSignal(str, str, str)  # file_path, original, modified
    show_diff_requested = pyqtSignal(str, str, str)  # file_path, original, modified
    file_accepted = pyqtSignal(str, str)  # file_path, content
    file_rejected = pyqtSignal(str)  # file_path
    file_open_requested = pyqtSignal(str)  # file_path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # File edit tracking
        self._pending_edits: Dict[str, FileEdit] = {}
        self._completed_edits: List[FileEdit] = []
        
        # Task queue integration
        self._task_queue = get_task_queue(self)
        
        log.info("Enhanced AI Agent with Diff support initialized")
    
    def process_file_edit(self, file_path: str, original_content: str, 
                         new_content: str, edit_type: str = "modify") -> FileEdit:
        """
        Process a file edit - stores it and emits signal to show diff
        
        Args:
            file_path: Path to the file
            original_content: Original file content
            new_content: New file content
            edit_type: Type of edit (create, modify, delete)
            
        Returns:
            FileEdit object
        """
        edit = FileEdit(file_path, original_content, new_content, edit_type)
        self._pending_edits[file_path] = edit
        
        # Emit signal to show diff
        self.show_diff_requested.emit(file_path, original_content, new_content)
        
        log.info(f"File edit created for: {file_path}")
        return edit
    
    def accept_file_edit(self, file_path: str):
        """Accept a pending file edit"""
        if file_path in self._pending_edits:
            edit = self._pending_edits[file_path]
            edit.accepted = True
            
            # Write the file
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(edit.new_content)
                
                # Move to completed
                self._completed_edits.append(edit)
                del self._pending_edits[file_path]
                
                # Emit signal
                self.file_accepted.emit(file_path, edit.new_content)
                
                log.info(f"File edit accepted and applied: {file_path}")
                return True
            except Exception as e:
                log.error(f"Error applying file edit: {e}")
                return False
        return False
    
    def reject_file_edit(self, file_path: str):
        """Reject a pending file edit"""
        if file_path in self._pending_edits:
            edit = self._pending_edits[file_path]
            edit.rejected = True
            
            # Move to completed (rejected)
            self._completed_edits.append(edit)
            del self._pending_edits[file_path]
            
            # Emit signal
            self.file_rejected.emit(file_path)
            
            log.info(f"File edit rejected: {file_path}")
            return True
        return False
    
    def open_file(self, file_path: str):
        """Request to open a file in the editor"""
        self.file_open_requested.emit(file_path)
        log.info(f"File open requested: {file_path}")
    
    def get_pending_edits(self) -> List[FileEdit]:
        """Get list of pending file edits"""
        return list(self._pending_edits.values())
    
    def get_completed_edits(self) -> List[FileEdit]:
        """Get list of completed file edits"""
        return self._completed_edits
    
    def has_pending_edits(self) -> bool:
        """Check if there are pending edits"""
        return len(self._pending_edits) > 0
    
    def accept_all_edits(self):
        """Accept all pending edits"""
        for file_path in list(self._pending_edits.keys()):
            self.accept_file_edit(file_path)
    
    def reject_all_edits(self):
        """Reject all pending edits"""
        for file_path in list(self._pending_edits.keys()):
            self.reject_file_edit(file_path)
    
    def generate_file_edit_summary(self) -> str:
        """Generate a summary of file edits for display in chat"""
        if not self._completed_edits:
            return ""
        
        lines = ["### 📁 Files Modified", ""]
        
        for edit in self._completed_edits:
            file_name = Path(edit.file_path).name
            status_icon = "✅" if edit.accepted else "❌"
            lines.append(f"{status_icon} `{file_name}`")
        
        return "\n".join(lines)


# Singleton instance
_enhanced_agent_with_diff = None


def get_enhanced_ai_agent_with_diff(parent=None) -> EnhancedAIAgentWithDiff:
    """Get singleton enhanced AI agent with diff support"""
    global _enhanced_agent_with_diff
    if _enhanced_agent_with_diff is None:
        _enhanced_agent_with_diff = EnhancedAIAgentWithDiff(parent)
    return _enhanced_agent_with_diff
