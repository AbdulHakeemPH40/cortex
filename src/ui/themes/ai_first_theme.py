"""
AI-First Futuristic Theme for Cortex IDE
Modern, glassmorphic design with gradient accents
"""

# AI-First Theme Color Palette
AI_FIRST_DARK_THEME = {
    # Background colors - Deep space dark
    "background_primary": "#0a0a0f",      # Main background
    "background_secondary": "#12121a",     # Panels
    "background_tertiary": "#1a1a24",      # Inputs, cards
    "background_hover": "#1e1e2e",         # Hover states
    
    # Accent colors - Purple/Indigo gradient
    "accent_primary": "#6366f1",           # Primary indigo
    "accent_secondary": "#8b5cf6",         # Secondary purple
    "accent_tertiary": "#a78bfa",          # Light purple
    "accent_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6)",
    
    # Text colors
    "text_primary": "#f8fafc",             # Main text
    "text_secondary": "#94a3b8",           # Secondary text
    "text_muted": "#64748b",               # Muted text
    "text_accent": "#6366f1",              # Accent text
    
    # Border colors
    "border_primary": "rgba(255, 255, 255, 0.08)",
    "border_accent": "rgba(99, 102, 241, 0.3)",
    "border_focus": "#6366f1",
    
    # Status colors
    "success": "#10b981",                  # Green
    "warning": "#f59e0b",                  # Amber
    "error": "#ef4444",                    # Red
    "info": "#3b82f6",                     # Blue
    
    # Shadows
    "shadow_sm": "0 2px 8px rgba(0, 0, 0, 0.3)",
    "shadow_md": "0 4px 16px rgba(0, 0, 0, 0.4)",
    "shadow_lg": "0 8px 32px rgba(0, 0, 0, 0.5)",
    "shadow_glow": "0 0 20px rgba(99, 102, 241, 0.3)",
}

# Light theme variant (for future use)
AI_FIRST_LIGHT_THEME = {
    "background_primary": "#ffffff",
    "background_secondary": "#f8fafc",
    "background_tertiary": "#f1f5f9",
    "background_hover": "#e2e8f0",
    
    "accent_primary": "#6366f1",
    "accent_secondary": "#8b5cf6",
    
    "text_primary": "#0f172a",
    "text_secondary": "#475569",
    "text_muted": "#94a3b8",
    
    "border_primary": "rgba(0, 0, 0, 0.08)",
    "border_accent": "rgba(99, 102, 241, 0.3)",
}


def get_ai_first_stylesheet(theme_type="dark") -> str:
    """
    Generate complete stylesheet for AI-First theme
    
    Args:
        theme_type: "dark" or "light"
    
    Returns:
        Complete Qt stylesheet string
    """
    theme = AI_FIRST_DARK_THEME if theme_type == "dark" else AI_FIRST_LIGHT_THEME
    
    stylesheet = f"""
    /* ========================================
       CORTEX AI-FIRST FUTURISTIC THEME
       ======================================== */
    
    /* Global Styles */
    QWidget {{
        background-color: {theme['background_primary']};
        color: {theme['text_primary']};
        font-family: "Inter", "Segoe UI", sans-serif;
        font-size: 14px;
    }}
    
    /* Main Window */
    QMainWindow {{
        background-color: {theme['background_primary']};
    }}
    
    /* Panels and Containers */
    QFrame {{
        background-color: {theme['background_secondary']};
        border: 1px solid {theme['border_primary']};
        border-radius: 8px;
    }}
    
    /* Buttons */
    QPushButton {{
        background-color: {theme['background_tertiary']};
        color: {theme['text_primary']};
        border: 1px solid {theme['border_primary']};
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: 500;
    }}
    
    QPushButton:hover {{
        background-color: {theme['background_hover']};
        border-color: {theme['accent_primary']};
        color: {theme['accent_primary']};
    }}
    
    QPushButton:pressed {{
        background-color: {theme['accent_primary']};
        color: #ffffff;
    }}
    
    /* Primary Action Buttons */
    QPushButton#primaryButton {{
        background: {theme['accent_gradient']};
        color: #ffffff;
        border: none;
        font-weight: 600;
    }}
    
    QPushButton#primaryButton:hover {{
        opacity: 0.9;
    }}
    
    /* Icon Buttons */
    QPushButton#iconButton {{
        background-color: transparent;
        border: 1px solid {theme['border_primary']};
        border-radius: 6px;
        padding: 6px;
    }}
    
    QPushButton#iconButton:hover {{
        background-color: rgba(99, 102, 241, 0.15);
        border-color: {theme['accent_primary']};
    }}
    
    /* Text Inputs */
    QTextEdit, QLineEdit {{
        background-color: {theme['background_tertiary']};
        color: {theme['text_primary']};
        border: 2px solid {theme['border_primary']};
        border-radius: 8px;
        padding: 8px 12px;
        selection-background-color: {theme['accent_primary']};
    }}
    
    QTextEdit:focus, QLineEdit:focus {{
        border-color: {theme['accent_primary']};
    }}
    
    /* Labels */
    QLabel {{
        color: {theme['text_primary']};
        background: transparent;
    }}
    
    QLabel#secondary {{
        color: {theme['text_secondary']};
    }}
    
    QLabel#muted {{
        color: {theme['text_muted']};
    }}
    
    /* Scrollbars */
    QScrollBar:vertical {{
        background-color: {theme['background_secondary']};
        width: 8px;
        border-radius: 4px;
    }}
    
    QScrollBar::handle:vertical {{
        background-color: {theme['text_muted']};
        border-radius: 4px;
        min-height: 20px;
    }}
    
    QScrollBar::handle:vertical:hover {{
        background-color: {theme['text_secondary']};
    }}
    
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0;
    }}
    
    /* Tabs */
    QTabWidget::pane {{
        border: 1px solid {theme['border_primary']};
        border-radius: 8px;
        background-color: {theme['background_secondary']};
    }}
    
    QTabBar::tab {{
        background-color: {theme['background_tertiary']};
        color: {theme['text_secondary']};
        padding: 8px 16px;
        margin-right: 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
    }}
    
    QTabBar::tab:selected {{
        background-color: {theme['background_secondary']};
        color: {theme['text_primary']};
        border-bottom: 2px solid {theme['accent_primary']};
    }}
    
    QTabBar::tab:hover {{
        background-color: {theme['background_hover']};
        color: {theme['text_primary']};
    }}
    
    /* Combo Boxes */
    QComboBox {{
        background-color: {theme['background_tertiary']};
        color: {theme['text_primary']};
        border: 1px solid {theme['border_primary']};
        border-radius: 6px;
        padding: 6px 12px;
    }}
    
    QComboBox:hover {{
        border-color: {theme['accent_primary']};
    }}
    
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    
    /* Splitter Handles */
    QSplitter::handle {{
        background-color: {theme['border_primary']};
    }}
    
    QSplitter::handle:hover {{
        background-color: {theme['accent_primary']};
    }}
    
    /* Status Indicators */
    QLabel#success {{
        color: {theme['success']};
    }}
    
    QLabel#warning {{
        color: {theme['warning']};
    }}
    
    QLabel#error {{
        color: {theme['error']};
    }}
    
    /* Tool Tips */
    QToolTip {{
        background-color: {theme['background_tertiary']};
        color: {theme['text_primary']};
        border: 1px solid {theme['border_primary']};
        border-radius: 4px;
        padding: 6px;
    }}
    
    /* Progress Bars */
    QProgressBar {{
        background-color: {theme['background_tertiary']};
        border: 1px solid {theme['border_primary']};
        border-radius: 4px;
        text-align: center;
    }}
    
    QProgressBar::chunk {{
        background: {theme['accent_gradient']};
        border-radius: 3px;
    }}
    
    /* Check Boxes */
    QCheckBox {{
        color: {theme['text_primary']};
        spacing: 8px;
    }}
    
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {theme['border_primary']};
        border-radius: 4px;
        background-color: {theme['background_tertiary']};
    }}
    
    QCheckBox::indicator:checked {{
        background-color: {theme['accent_primary']};
        border-color: {theme['accent_primary']};
    }}
    
    /* Radio Buttons */
    QRadioButton {{
        color: {theme['text_primary']};
        spacing: 8px;
    }}
    
    QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {theme['border_primary']};
        border-radius: 9px;
        background-color: {theme['background_tertiary']};
    }}
    
    QRadioButton::indicator:checked {{
        background-color: {theme['accent_primary']};
        border-color: {theme['accent_primary']};
    }}
    """
    
    return stylesheet


def apply_ai_first_theme(app, theme_type="dark"):
    """
    Apply AI-First theme to Qt application
    
    Args:
        app: QApplication instance
        theme_type: "dark" or "light"
    """
    stylesheet = get_ai_first_stylesheet(theme_type)
    app.setStyleSheet(stylesheet)
