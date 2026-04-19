"""
Command Palette for AI-First Cortex IDE
Quick access to commands via keyboard shortcut (Ctrl+K / Cmd+K)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QLabel, QFrame, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QKeySequence, QShortcut


class CommandPalette(QWidget):
    """
    Command Palette - VS Code/Cursor style command launcher
    Opens with Ctrl+K and provides quick access to AI commands
    """
    
    command_selected = pyqtSignal(str, dict)  # command_name, command_data
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(500, 400)
        self.setMaximumSize(600, 500)
        self.setup_ui()
        self.setup_shortcuts()
        self.populate_commands()
    
    def setup_ui(self):
        """Setup command palette UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Top section with title
        header = QFrame()
        header.setObjectName("paletteHeader")
        header.setFixedHeight(50)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        
        title = QLabel("⚡ Command Palette")
        title.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        title.setObjectName("paletteTitle")
        header_layout.addWidget(title)
        
        layout.addWidget(header)
        
        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type a command or ask AI...")
        self.search_input.setFont(QFont("Inter", 13))
        self.search_input.setFixedHeight(45)
        self.search_input.setObjectName("commandSearch")
        self.search_input.textChanged.connect(self.filter_commands)
        layout.addWidget(self.search_input)
        
        # Command list
        self.command_list = QListWidget()
        self.command_list.setFont(QFont("Inter", 11))
        self.command_list.setObjectName("commandList")
        self.command_list.itemClicked.connect(self.on_command_selected)
        self.command_list.itemActivated.connect(self.on_command_selected)
        layout.addWidget(self.command_list)
        
        # Bottom hint
        footer = QFrame()
        footer.setObjectName("paletteFooter")
        footer.setFixedHeight(30)
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 4, 16, 4)
        
        hint = QLabel("↑↓ Navigate  •  Enter to select  •  Esc to close")
        hint.setFont(QFont("Inter", 9))
        hint.setObjectName("paletteHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addWidget(hint)
        
        layout.addWidget(footer)
        
        # Apply styling
        self.apply_theme()
        
        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(10)
        shadow.setColor(Qt.GlobalColor.black)
        self.setGraphicsEffect(shadow)
    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        # Close on Escape
        close_shortcut = QShortcut(QKeySequence("Escape"), self)
        close_shortcut.activated.connect(self.hide)
    
    def populate_commands(self):
        """Populate the command list with available commands"""
        self.commands = [
            # AI Commands
            {"name": "✨ Explain Code", "category": "AI", "action": "explain_code", "icon": "💡"},
            {"name": "✨ Refactor Code", "category": "AI", "action": "refactor_code", "icon": "🔄"},
            {"name": "✨ Debug Code", "category": "AI", "action": "debug_code", "icon": "🐛"},
            {"name": "✨ Generate Tests", "category": "AI", "action": "generate_tests", "icon": "🧪"},
            {"name": "✨ Create New File", "category": "AI", "action": "create_file", "icon": "📝"},
            {"name": "✨ Search Codebase", "category": "AI", "action": "search_codebase", "icon": "🔍"},
            {"name": "✨ Optimize Code", "category": "AI", "action": "optimize_code", "icon": "⚡"},
            
            # File Commands
            {"name": "📁 Open File", "category": "File", "action": "open_file", "icon": "📂"},
            {"name": "📁 Save File", "category": "File", "action": "save_file", "icon": "💾"},
            {"name": "📁 Close File", "category": "File", "action": "close_file", "icon": "❌"},
            
            # View Commands
            {"name": "👁 Toggle Terminal", "category": "View", "action": "toggle_terminal", "icon": "⌨"},
            {"name": "👁 Toggle Sidebar", "category": "View", "action": "toggle_sidebar", "icon": "📊"},
            {"name": "👁 Toggle Theme", "category": "View", "action": "toggle_theme", "icon": "🎨"},
            
            # Settings
            {"name": "⚙ Settings", "category": "Settings", "action": "open_settings", "icon": "⚙"},
            {"name": "⚙ AI Settings", "category": "Settings", "action": "ai_settings", "icon": "🤖"},
            
            # Git
            {"name": "🔀 Git Commit", "category": "Git", "action": "git_commit", "icon": "📦"},
            {"name": "🔀 Git Push", "category": "Git", "action": "git_push", "icon": "⬆"},
            {"name": "🔀 Git Pull", "category": "Git", "action": "git_pull", "icon": "⬇"},
        ]
        
        self.refresh_command_list()
    
    def refresh_command_list(self):
        """Refresh the command list widget"""
        self.command_list.clear()
        
        for cmd in self.commands:
            item = QListWidgetItem(f"{cmd['icon']} {cmd['name']}")
            item.setData(Qt.ItemDataRole.UserRole, cmd)
            self.command_list.addItem(item)
    
    def filter_commands(self, text: str):
        """Filter commands based on search text"""
        text = text.lower().strip()
        
        self.command_list.clear()
        
        for cmd in self.commands:
            if not text or text in cmd["name"].lower() or text in cmd["action"].lower():
                item = QListWidgetItem(f"{cmd['icon']} {cmd['name']}")
                item.setData(Qt.ItemDataRole.UserRole, cmd)
                self.command_list.addItem(item)
    
    def on_command_selected(self, item: QListWidgetItem):
        """Handle command selection"""
        command_data = item.data(Qt.ItemDataRole.UserRole)
        if command_data:
            self.command_selected.emit(command_data["action"], command_data)
            self.hide()
    
    def show_palette(self):
        """Show the command palette"""
        # Position in center of parent
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.center().x() - self.width() // 2
            y = parent_rect.center().y() - self.height() // 2
            self.move(x, y)
        
        self.show()
        self.search_input.setFocus()
        self.search_input.clear()
        self.refresh_command_list()
    
    def apply_theme(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a24;
                color: #f8fafc;
            }
            
            #paletteHeader {
                background-color: #12121a;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            
            #paletteTitle {
                color: #f8fafc;
            }
            
            #commandSearch {
                background-color: #0a0a0f;
                color: #f8fafc;
                border: none;
                border-bottom: 2px solid rgba(99, 102, 241, 0.3);
                padding: 0 16px;
            }
            
            #commandSearch:focus {
                border-bottom-color: #6366f1;
            }
            
            #commandList {
                background-color: #1a1a24;
                color: #e2e8f0;
                border: none;
                outline: none;
            }
            
            #commandList::item {
                padding: 10px 16px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            }
            
            #commandList::item:hover {
                background-color: rgba(99, 102, 241, 0.15);
                color: #6366f1;
            }
            
            #commandList::item:selected {
                background-color: rgba(99, 102, 241, 0.25);
                color: #6366f1;
            }
            
            #paletteFooter {
                background-color: #12121a;
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
            
            #paletteHint {
                color: #64748b;
            }
        """)
