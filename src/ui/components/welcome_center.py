"""
Welcome Center Widget - Codex-style initial screen
2-panel layout: Sidebar | Welcome Center
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QSizePolicy, QScrollArea, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QPalette


class SuggestionChip(QFrame):
    """Clickable suggestion chip with icon and text."""
    
    clicked = pyqtSignal(str)
    
    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        
        # Icon
        self._icon_label = QLabel(icon)
        self._icon_label.setStyleSheet("font-size: 14px; color: #666666;")
        layout.addWidget(self._icon_label)
        
        # Text
        self._text_label = QLabel(text)
        self._text_label.setWordWrap(True)
        self._text_label.setStyleSheet("font-size: 13px; color: #aaaaaa;")
        layout.addWidget(self._text_label, 1)
        
        self.setStyleSheet("""
            SuggestionChip {
                background: transparent;
                border-bottom: 1px solid #2a2a2a;
            }
            SuggestionChip:hover {
                background: transparent;
            }
            SuggestionChip:hover QLabel {
                color: #ffffff;
            }
        """)
    
    def mousePressEvent(self, event):
        self.clicked.emit(self._text)
        super().mousePressEvent(event)
    
    def enterEvent(self, event):
        self._icon_label.setStyleSheet("font-size: 14px; color: #4d78cc;")
        self._text_label.setStyleSheet("font-size: 13px; color: #ffffff;")
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        self._icon_label.setStyleSheet("font-size: 14px; color: #666666;")
        self._text_label.setStyleSheet("font-size: 13px; color: #aaaaaa;")
        super().leaveEvent(event)


class ContextPill(QPushButton):
    """Pill-style dropdown button for context selection."""
    
    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(parent)
        self.setText(f"{icon} {text}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            ContextPill {
                background-color: #252525;
                border: 1px solid #3a3a3a;
                border-radius: 20px;
                padding: 4px 12px;
                font-size: 13px;
                color: #cccccc;
            }
            ContextPill:hover {
                border-color: #555555;
                background-color: #2d2d2d;
            }
            ContextPill:pressed {
                background-color: #1e1e1e;
            }
        """)


class WelcomeCenter(QWidget):
    """
    Codex-style Welcome Center panel.
    Shows when no chat is active - the initial/new chat state.
    """
    
    # Signals
    send_message = pyqtSignal(str)  # User sent a message
    suggestion_clicked = pyqtSignal(str)  # User clicked a suggestion chip
    project_changed = pyqtSignal(str)  # User changed project
    environment_changed = pyqtSignal(str)  # User changed environment
    branch_changed = pyqtSignal(str)  # User changed branch
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._apply_theme()
    
    def _setup_ui(self):
        """Build the welcome center UI."""
        self.setObjectName("welcomeCenter")
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        # Content container
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.setSpacing(20)
        container_layout.setContentsMargins(40, 60, 40, 40)
        
        # === ONBOARDING TOOLTIP (dismissable) ===
        self._onboarding = QFrame()
        self._onboarding.setObjectName("onboardingTooltip")
        onboarding_layout = QHBoxLayout(self._onboarding)
        onboarding_layout.setContentsMargins(16, 12, 12, 12)
        onboarding_layout.setSpacing(12)
        
        # NEW badge + text
        onboarding_text = QLabel(
            '<span style="background:#1d4ed8; color:#fff; padding:2px 6px; '
            'border-radius:4px; font-size:11px; font-weight:bold;">NEW</span> '
            '<span style="color:#fff; font-weight:600;">Try Plugins and Skills</span> '
            '<span style="color:#e0e0e0;">Use Plugins to connect Cortex to your favorite tools</span>'
        )
        onboarding_text.setWordWrap(True)
        onboarding_layout.addWidget(onboarding_text, 1)
        
        # Dismiss button
        dismiss_btn = QPushButton("×")
        dismiss_btn.setFixedSize(24, 24)
        dismiss_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #fff;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.2);
                border-radius: 4px;
            }
        """)
        dismiss_btn.clicked.connect(self._hide_onboarding)
        onboarding_layout.addWidget(dismiss_btn)
        
        self._onboarding.setStyleSheet("""
            QFrame#onboardingTooltip {
                background-color: #3b82f6;
                border-radius: 12px;
                max-width: 400px;
            }
        """)
        
        container_layout.addWidget(self._onboarding, alignment=Qt.AlignmentFlag.AlignCenter)
        container_layout.addSpacing(40)
        
        # === HERO HEADING ===
        self._hero = QLabel("What should we build today?")
        self._hero.setObjectName("heroHeading")
        self._hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_font = QFont()
        hero_font.setPointSize(28)
        hero_font.setWeight(QFont.Weight.DemiBold)
        self._hero.setFont(hero_font)
        self._hero.setStyleSheet("color: #ffffff; margin: 20px 0;")
        container_layout.addWidget(self._hero)
        
        container_layout.addSpacing(30)
        
        # === INPUT BOX ===
        input_container = QFrame()
        input_container.setObjectName("inputContainer")
        input_container.setMaximumWidth(700)
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(16, 16, 16, 16)
        input_layout.setSpacing(12)
        
        # Text input
        self._input = QTextEdit()
        self._input.setObjectName("welcomeInput")
        self._input.setPlaceholderText("Ask Cortex anything. @ to use plugins or use files")
        self._input.setMaximumHeight(120)
        self._input.setMinimumHeight(52)
        self._input.setStyleSheet("""
            QTextEdit#welcomeInput {
                background-color: #1a1a1a;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                color: #ffffff;
            }
            QTextEdit#welcomeInput QScrollBar {
                background: transparent;
                width: 8px;
            }
            QTextEdit#welcomeInput QScrollBar::handle {
                background: #3e3e42;
                border-radius: 4px;
            }
        """)
        input_layout.addWidget(self._input)
        
        # Input toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)
        
        # Left side: Attach, Permissions
        self._attach_btn = QPushButton("+")
        self._attach_btn.setToolTip("Attach file/context")
        self._attach_btn.setFixedSize(28, 28)
        self._attach_btn.setStyleSheet(self._icon_button_style())
        toolbar_layout.addWidget(self._attach_btn)
        
        self._permissions_btn = QPushButton("⚙ Default permissions ▾")
        self._permissions_btn.setStyleSheet(self._toolbar_button_style())
        toolbar_layout.addWidget(self._permissions_btn)
        
        toolbar_layout.addStretch()
        
        # Right side: Model, Context, Mic, Send
        self._model_btn = QPushButton("Claude 3.5 Sonnet ▾")
        self._model_btn.setStyleSheet(self._toolbar_button_style())
        toolbar_layout.addWidget(self._model_btn)
        
        self._context_btn = QPushButton("Medium ▾")
        self._context_btn.setStyleSheet(self._toolbar_button_style())
        toolbar_layout.addWidget(self._context_btn)
        
        self._mic_btn = QPushButton("🎤")
        self._mic_btn.setToolTip("Voice input")
        self._mic_btn.setFixedSize(28, 28)
        self._mic_btn.setStyleSheet(self._icon_button_style())
        toolbar_layout.addWidget(self._mic_btn)
        
        self._send_btn = QPushButton("→")
        self._send_btn.setToolTip("Send message")
        self._send_btn.setFixedSize(32, 32)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4d78cc;
                border: none;
                border-radius: 16px;
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a85d9;
            }
            QPushButton:pressed {
                background-color: #3d68bc;
            }
        """)
        self._send_btn.clicked.connect(self._on_send)
        toolbar_layout.addWidget(self._send_btn)
        
        input_layout.addLayout(toolbar_layout)
        
        input_container.setStyleSheet("""
            QFrame#inputContainer {
                background-color: #252525;
                border: 1px solid #3a3a3a;
                border-radius: 12px;
            }
        """)
        
        container_layout.addWidget(input_container, alignment=Qt.AlignmentFlag.AlignCenter)
        
        container_layout.addSpacing(20)
        
        # === CONTEXT PILLS ===
        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(8)
        pills_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._project_pill = ContextPill("⎇", "Cortex ▾")
        self._project_pill.clicked.connect(lambda: self.project_changed.emit(""))
        pills_layout.addWidget(self._project_pill)
        
        self._env_pill = ContextPill("🖥", "Work locally ▾")
        self._env_pill.clicked.connect(lambda: self.environment_changed.emit(""))
        pills_layout.addWidget(self._env_pill)
        
        self._branch_pill = ContextPill("⎇", "main ▾")
        self._branch_pill.clicked.connect(lambda: self.branch_changed.emit(""))
        pills_layout.addWidget(self._branch_pill)
        
        container_layout.addLayout(pills_layout)
        
        container_layout.addSpacing(30)
        
        # === SUGGESTION CHIPS ===
        suggestions_label = QLabel("Suggestions")
        suggestions_label.setStyleSheet("font-size: 11px; color: #555555; text-transform: uppercase; letter-spacing: 0.8px;")
        suggestions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(suggestions_label)
        
        suggestions_container = QFrame()
        suggestions_container.setMaximumWidth(600)
        suggestions_layout = QVBoxLayout(suggestions_container)
        suggestions_layout.setContentsMargins(0, 0, 0, 0)
        suggestions_layout.setSpacing(0)
        
        suggestions = [
            ("⎇", "Review my recent commits for correctness risks and maintainability concerns"),
            ("⊙", "Unblock my most recent open PR"),
            ("⠿", "Connect your favorite apps to Cortex"),
        ]
        
        for icon, text in suggestions:
            chip = SuggestionChip(icon, text)
            chip.clicked.connect(self._on_suggestion_clicked)
            suggestions_layout.addWidget(chip)
        
        container_layout.addWidget(suggestions_container, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Add stretch to center content
        container_layout.addStretch()
        
        scroll.setWidget(container)
        main_layout.addWidget(scroll)
        
        # Store references
        self._scroll_area = scroll
        self._container = container
    
    def _icon_button_style(self) -> str:
        """Style for icon-only buttons."""
        return """
            QPushButton {
                background: transparent;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                color: #888888;
                font-size: 13px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.05);
                border-color: #555555;
                color: #ffffff;
            }
        """
    
    def _toolbar_button_style(self) -> str:
        """Style for toolbar text buttons."""
        return """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
                color: #888888;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.05);
                color: #ffffff;
            }
        """
    
    def _apply_theme(self):
        """Apply dark theme to the widget."""
        self.setStyleSheet("""
            WelcomeCenter {
                background-color: #1a1a1a;
            }
        """)
    
    def _hide_onboarding(self):
        """Hide the onboarding tooltip."""
        self._onboarding.hide()
    
    def _on_send(self):
        """Handle send button click."""
        text = self._input.toPlainText().strip()
        if text:
            self.send_message.emit(text)
            self._input.clear()
    
    def _on_suggestion_clicked(self, text: str):
        """Handle suggestion chip click."""
        self._input.setPlainText(text)
        self._input.setFocus()
        self.suggestion_clicked.emit(text)
    
    def set_project_name(self, name: str):
        """Update the project pill text."""
        self._project_pill.setText(f"⎇ {name} ▾")
        self._hero.setText(f"What should we build in {name}?")
    
    def set_branch_name(self, name: str):
        """Update the branch pill text."""
        self._branch_pill.setText(f"⎇ {name} ▾")
    
    def get_input_text(self) -> str:
        """Get the current input text."""
        return self._input.toPlainText()
    
    def clear_input(self):
        """Clear the input field."""
        self._input.clear()
    
    def focus_input(self):
        """Focus the input field."""
        self._input.setFocus()
