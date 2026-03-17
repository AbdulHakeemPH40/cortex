"""
Example: Diff Viewer Integration with AI Chat
Shows how file edits appear in chat with DIFF buttons
"""

# Example usage in main_window.py

"""
### In your main_window.py setup:

from src.ui.components.diff_viewer import DiffWindow
from src.ai.enhanced_agent_with_diff import get_enhanced_ai_agent_with_diff
from src.ui.components.enhanced_ai_chat import EnhancedAIChatWidget

class MainWindow:
    def __init__(self):
        # ... existing setup ...
        
        # Setup AI Agent with Diff support
        self._ai_agent = get_enhanced_ai_agent_with_diff(self)
        
        # Setup Diff Window
        self._diff_window = DiffWindow(self)
        self._diff_window.file_accepted.connect(self._on_file_accepted)
        self._diff_window.file_rejected.connect(self._on_file_rejected)
        self._diff_window.file_opened.connect(self._on_file_opened)
        
        # Connect AI agent signals
        self._ai_agent.show_diff_requested.connect(self._on_show_diff)
        self._ai_agent.file_accepted.connect(self._on_edit_accepted)
        self._ai_agent.file_rejected.connect(self._on_edit_rejected)
        
        # When AI edits a file, show it in chat
        self._ai_agent.file_edit_created.connect(self._on_file_edit_created)
    
    def _on_file_edit_created(self, file_path: str, original: str, modified: str):
        '''Called when AI creates a file edit'''
        file_name = file_path.split('/')[-1].split('\\')[-1]
        
        # Show in chat with DIFF button
        self._ai_chat.add_file_edit_message(file_path, file_name)
        
        # Show diff window
        self._diff_window.show_diff(file_path, original, modified)
    
    def _on_show_diff(self, file_path: str, original: str, modified: str):
        '''Show diff window'''
        self._diff_window.show_diff(file_path, original, modified)
    
    def _on_file_accepted(self, file_path: str, content: str):
        '''User accepted changes in diff window'''
        self._ai_agent.accept_file_edit(file_path)
        self._ai_chat.mark_file_accepted(file_path)
    
    def _on_file_rejected(self, file_path: str):
        '''User rejected changes in diff window'''
        self._ai_agent.reject_file_edit(file_path)
        self._ai_chat.mark_file_rejected(file_path)
    
    def _on_file_opened(self, file_path: str):
        '''Open file in editor'''
        self.open_file(file_path)
"""


# Example JavaScript for showing file edits in chat
JS_FILE_EDIT_DISPLAY = """
// Add this to script_enhanced.js

function addFileEditMessage(filePath, fileName) {
    const container = document.getElementById('chatMessages');
    
    const editDiv = document.createElement('div');
    editDiv.className = 'file-edit-message';
    editDiv.id = 'edit-' + filePath.replace(/[^a-zA-Z0-9]/g, '-');
    
    editDiv.innerHTML = `
        <div class="file-edit-header">
            <span class="file-edit-icon">📄</span>
            <span class="file-edit-name">Edited \`${fileName}\`</span>
        </div>
        <div class="file-edit-actions">
            <button class="diff-btn" onclick="showDiff('${filePath}')">
                <span class="diff-badge">DIFF</span>
                <span>View Changes</span>
            </button>
            <button class="open-file-btn" onclick="openFile('${filePath}')">
                <span>Open File</span>
            </button>
        </div>
        <div class="file-edit-status" id="status-${filePath.replace(/[^a-zA-Z0-9]/g, '-')}">
            <span class="status-pending">⏳ Pending review...</span>
        </div>
    `;
    
    container.appendChild(editDiv);
    scrollToBottom();
}

function showDiff(filePath) {
    if (bridge) {
        bridge.on_show_diff(filePath);
    }
}

function openFile(filePath) {
    if (bridge) {
        bridge.on_open_file(filePath);
    }
}

function markFileAccepted(filePath) {
    const statusId = 'status-' + filePath.replace(/[^a-zA-Z0-9]/g, '-');
    const statusEl = document.getElementById(statusId);
    if (statusEl) {
        statusEl.innerHTML = '<span class="status-accepted">✅ Changes accepted and applied</span>';
    }
}

function markFileRejected(filePath) {
    const statusId = 'status-' + filePath.replace(/[^a-zA-Z0-9]/g, '-');
    const statusEl = document.getElementById(statusId);
    if (statusEl) {
        statusEl.innerHTML = '<span class="status-rejected">❌ Changes rejected</span>';
    }
}
"""


# CSS for file edit display in chat
CSS_FILE_EDIT = """
/* File Edit Message Styles */
.file-edit-message {
    margin: 16px 0;
    padding: 12px 16px;
    background: #252526;
    border: 1px solid #3e3e42;
    border-radius: 8px;
    font-family: 'Segoe UI', sans-serif;
}

.file-edit-header {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
}

.file-edit-icon {
    font-size: 16px;
    margin-right: 8px;
}

.file-edit-name {
    font-size: 14px;
    font-weight: 500;
    color: #cccccc;
}

.file-edit-actions {
    display: flex;
    gap: 8px;
    margin-bottom: 8px;
}

.diff-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: #238636;
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
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
    font-size: 10px;
    font-weight: 700;
}

.open-file-btn {
    padding: 6px 12px;
    background: #3c3c3c;
    color: #cccccc;
    border: none;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
}

.open-file-btn:hover {
    background: #4c4c4c;
}

.file-edit-status {
    font-size: 12px;
    padding-top: 8px;
    border-top: 1px solid #3e3e42;
}

.status-pending {
    color: #d29922;
}

.status-accepted {
    color: #3fb950;
}

.status-rejected {
    color: #f85149;
}
"""


# Example of how it appears in chat
EXAMPLE_CHAT_FLOW = """
## Example Chat Flow with File Edit:

User: "Add email configuration to settings.py"

AI: "I'll help you add email configuration to settings.py. Let me create the necessary changes."

[AI thinks and creates edit]

📄 File Edit Created:
┌─────────────────────────────────────┐
│ 📄 Edited `settings.py`             │
│                                     │
│ [DIFF] [Open File]                  │
│                                     │
│ ⏳ Pending review...                │
└─────────────────────────────────────┘

[Diff Window Opens showing:]
┌─────────────────────────────────────┐
│ Edited `settings.py`                │
│ [Open File] [Reject] [Accept]       │
├──────────────────┬──────────────────┤
│ Original         │ Modified         │
│ (Red bg)         │ (Green bg)       │
│                  │                  │
│ 87  DATABASES = {│ 87  DATABASES = {│
│ ...              │ ...              │
│                  │ 88  # Email      │
│                  │     config       │
│                  │ 89  EMAIL_...    │
├──────────────────┴──────────────────┤
│ 📊 8 lines added, 0 removed         │
└─────────────────────────────────────┘

User clicks [Accept]

📄 File Edit Updated:
┌─────────────────────────────────────┐
│ 📄 Edited `settings.py`             │
│                                     │
│ [DIFF] [Open File]                  │
│                                     │
│ ✅ Changes accepted and applied     │
└─────────────────────────────────────┘

AI: "✅ Email configuration has been added to settings.py. 
     The changes include SMTP settings and default from email."
"""


# Integration with existing tools.py
TOOL_INTEGRATION = """
### Modify src/ai/tools.py to use diff viewer:

class ToolExecutor:
    def __init__(self, agent):
        self.agent = agent
    
    def edit_file(self, file_path: str, new_content: str) -> dict:
        '''Edit a file with diff preview'''
        
        # Read original content
        try:
            with open(file_path, 'r') as f:
                original = f.read()
        except:
            original = ""
        
        # Create edit (don't write yet)
        edit = self.agent.process_file_edit(file_path, original, new_content)
        
        return {
            "status": "pending_review",
            "file": file_path,
            "message": f"File edit created for {file_path}. Review the diff to accept or reject."
        }
    
    def create_file(self, file_path: str, content: str) -> dict:
        '''Create a new file with diff preview'''
        
        edit = self.agent.process_file_edit(
            file_path, 
            "",  # Original is empty for new file
            content,
            edit_type="create"
        )
        
        return {
            "status": "pending_review",
            "file": file_path,
            "message": f"New file created: {file_path}. Review to accept or reject."
        }
"""


print("=" * 60)
print("Diff Viewer Integration Example")
print("=" * 60)
print("\n1. JavaScript for Chat Display:")
print(JS_FILE_EDIT_DISPLAY[:500] + "...")
print("\n2. CSS Styles:")
print(CSS_FILE_EDIT[:300] + "...")
print("\n3. Example Flow:")
print(EXAMPLE_CHAT_FLOW)
print("\n" + "=" * 60)
print("Integration complete!")
print("=" * 60)
