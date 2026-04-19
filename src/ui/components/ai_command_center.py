"""
AI Command Center - Enhanced chat interface for AI-first interaction
Replaces traditional AI chat with a more prominent, command-focused interface
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QScrollArea, QFrame, QSizePolicy, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QKeyEvent


class QuickActionButtons(QWidget):
    """Quick action buttons for common AI commands"""
    
    action_triggered = pyqtSignal(str)  # action_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(6)
        
        actions = [
            ("💡 Explain", "explain"),
            ("✨ Refactor", "refactor"),
            ("🐛 Debug", "debug"),
            ("🧪 Tests", "tests"),
            ("📝 Create File", "create_file"),
            ("🔍 Search", "search"),
        ]
        
        for label, action in actions:
            btn = QPushButton(label)
            btn.setFont(QFont("Inter", 10))
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, a=action: self.action_triggered.emit(a))
            btn.setObjectName("quickActionButton")
            layout.addWidget(btn)
        
        layout.addStretch()
        
        self.setStyleSheet("""
            #quickActionButton {
                background-color: #1a1a24;
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 0 12px;
            }
            
            #quickActionButton:hover {
                background-color: rgba(99, 102, 241, 0.2);
                border-color: #6366f1;
                color: #6366f1;
            }
            
            #quickActionButton:pressed {
                background-color: rgba(99, 102, 241, 0.3);
            }
        """)


class CommandInput(QTextEdit):
    """Large, prominent text input for AI commands"""
    
    command_submitted = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Ask AI to write, edit, or explain code... (Press Enter to send)")
        self.setMinimumHeight(80)
        self.setMaximumHeight(200)
        self.setFont(QFont("Inter", 12))
        self.setObjectName("commandInput")
        
        # Enable rich text but keep it simple
        self.setAcceptRichText(False)
        
        self.apply_theme()
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle key presses"""
        # Enter without Shift sends the command
        if event.key() == Qt.Key.Key_Return and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            event.accept()
            text = self.toPlainText().strip()
            if text:
                self.command_submitted.emit(text)
                self.clear()
        else:
            super().keyPressEvent(event)
    
    def apply_theme(self):
        self.setStyleSheet("""
            #commandInput {
                background-color: #1a1a24;
                color: #f8fafc;
                border: 2px solid rgba(99, 102, 241, 0.3);
                border-radius: 12px;
                padding: 12px 16px;
                selection-background-color: #6366f1;
            }
            
            #commandInput:focus {
                border-color: #6366f1;
                background-color: #1e1e2e;
            }
            
            #commandInput:hover {
                border-color: rgba(99, 102, 241, 0.5);
            }
        """)


class AgentModeSelector(QWidget):
    """Selector for AI agent mode (Chat, Agent, Performance, Ultimate)"""
    
    mode_changed = pyqtSignal(str)  # mode_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 4)
        layout.setSpacing(8)
        
        label = QLabel("Mode:")
        label.setFont(QFont("Inter", 10))
        label.setObjectName("modeLabel")
        layout.addWidget(label)
        
        self.mode_combo = QComboBox()
        self.mode_combo.setFont(QFont("Inter", 10))
        self.mode_combo.setFixedHeight(28)
        self.mode_combo.addItems(["Chat", "Agent", "Performance", "Ultimate"])
        self.mode_combo.currentTextChanged.connect(self.mode_changed.emit)
        self.mode_combo.setObjectName("modeCombo")
        layout.addWidget(self.mode_combo)
        
        layout.addStretch()
        
        self.setStyleSheet("""
            #modeLabel {
                color: #94a3b8;
                background: transparent;
            }
            
            #modeCombo {
                background-color: #1a1a24;
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 0 8px;
            }
            
            #modeCombo:hover {
                border-color: #6366f1;
            }
        """)


class AICommandCenter(QWidget):
    """
    Main AI Command Center widget
    Replaces traditional chat with a more command-focused interface
    """
    
    # Signals
    command_submitted = pyqtSignal(str)  # user command
    quick_action_triggered = pyqtSignal(str)  # action name
    mode_changed = pyqtSignal(str)  # agent mode
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the command center UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # === TOP: Agent Mode Selector ===
        self.mode_selector = AgentModeSelector()
        self.mode_selector.mode_changed.connect(self.mode_changed.emit)
        main_layout.addWidget(self.mode_selector)
        
        # === MIDDLE: Chat/Response Display (existing AI chat will be embedded here) ===
        # This is a placeholder - the actual AIChatWidget will be integrated
        self.chat_display_placeholder = QWidget()
        self.chat_display_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        main_layout.addWidget(self.chat_display_placeholder, 1)
        
        # === BOTTOM: Quick Actions + Command Input ===
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 8)
        bottom_layout.setSpacing(4)
        
        # Quick action buttons
        self.quick_actions = QuickActionButtons()
        self.quick_actions.action_triggered.connect(self.quick_action_triggered.emit)
        bottom_layout.addWidget(self.quick_actions)
        
        # Command input
        self.command_input = CommandInput()
        self.command_input.command_submitted.connect(self.command_submitted.emit)
        bottom_layout.addWidget(self.command_input)
        
        main_layout.addWidget(bottom_widget)
    
    def set_chat_widget(self, chat_widget):
        """Set the actual AI chat widget to display"""
        # Remove placeholder
        if self.chat_display_placeholder:
            self.layout().removeWidget(self.chat_display_placeholder)
            self.chat_display_placeholder.deleteLater()
        
        # Add actual chat widget
        self.layout().insertWidget(1, chat_widget, 1)
    
    def focus_input(self):
        """Focus the command input"""
        self.command_input.setFocus()
    
    def clear_input(self):
        """Clear the command input"""
        self.command_input.clear()
