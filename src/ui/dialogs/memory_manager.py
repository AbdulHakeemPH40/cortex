"""
Memory Manager Dialog for Cortex IDE
=====================================
Shows all project-scoped persistent memories the AI has saved, exactly like
the Qoder / Cursor "Settings → Memories" panel.

Features:
  • Collapsible memory cards with type badges
  • Scope / Keywords / Content sections per item
  • Memory age staleness indicator (yellow if >7 days)
  • Delete individual memories
  • Clear all memories
  • Enable / disable automatic memory generation toggle
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint, QSize, pyqtProperty, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ─────────────────────────── colour tokens ───────────────────────────────────

_BG           = "#1e1e1e"
_BG_CARD      = "#252526"
_BG_CARD_H    = "#2d2d30"
_BG_HEADER    = "#181818"
_BG_ELEVATED  = "#2a2a2a"
_BORDER       = "#3e3e42"
_BORDER_LIGHT = "#4e4e52"
_FG           = "#d4d4d4"
_FG_DIM       = "#808080"
_FG_MUTED     = "#6e6e6e"
_ACCENT       = "#0078d4"
_ACCENT_HOVER = "#1177bb"
_TOGGLE_ON    = "#4CAF50"
_TOGGLE_OFF   = "#3e3e42"

_TYPE_COLORS = {
    "user":      ("#1e3a5f", "#64b5f6"),   # blue
    "feedback":  ("#3d2914", "#ffb74d"),   # amber
    "project":   ("#1b3a1b", "#81c784"),   # green
    "reference": ("#2d1b3d", "#ce93d8"),   # purple
    "skill":     ("#3d2815", "#ffcc80"),   # orange
    "default":   ("#2d2d30", "#9e9e9e"),   # gray
}
_TYPE_DEFAULT = ("#2d2d30", "#9e9e9e")


# ─────────────────────────── animated toggle switch ──────────────────────────

class AnimatedToggle(QWidget):
    """Modern animated toggle switch like Qoder's."""
    
    toggled = pyqtSignal(bool)
    
    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self._checked = checked
        self._thumb_pos = 1.0 if checked else 0.0
        self._animation = QPropertyAnimation(self, b"thumb_pos")
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def get_thumb_pos(self):
        return self._thumb_pos
    
    def set_thumb_pos(self, pos):
        self._thumb_pos = pos
        self.update()
    
    # Register as Qt property for animation using pyqtProperty
    thumb_pos = pyqtProperty(float, get_thumb_pos, set_thumb_pos)
    
    def isChecked(self):
        return self._checked
    
    def setChecked(self, checked):
        if self._checked != checked:
            self._checked = checked
            self._animate_to(1.0 if checked else 0.0)
            self.toggled.emit(checked)
    
    def _animate_to(self, target):
        self._animation.stop()
        self._animation.setStartValue(self._thumb_pos)
        self._animation.setEndValue(target)
        self._animation.start()
    
    def mousePressEvent(self, event):
        self.setChecked(not self._checked)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background
        bg_color = QColor(_TOGGLE_ON if self._checked else _TOGGLE_OFF)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 48, 26, 13, 13)
        
        # Thumb shadow
        shadow_color = QColor(0, 0, 0, 40)
        painter.setBrush(QBrush(shadow_color))
        thumb_x = 3 + self._thumb_pos * 22
        painter.drawEllipse(int(thumb_x) + 1, 4, 18, 18)
        
        # Thumb
        thumb_color = QColor("#ffffff")
        painter.setBrush(QBrush(thumb_color))
        painter.drawEllipse(int(thumb_x), 3, 20, 20)


# ─────────────────────────── frontmatter parser ──────────────────────────────

def _parse_frontmatter(content: str):
    """Return (frontmatter_dict, body_text)."""
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body    = content[end + 4:].strip()
    fm: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] in ('"', "'") and v[-1] == v[0]:
                v = v[1:-1]
            fm[k] = v
    return fm, body


# ─────────────────────────── memory loader ───────────────────────────────────

def _compute_memory_dir(project_root: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\0]', "_", project_root).strip("_ ")
    if len(sanitized) > 60:
        h = hashlib.md5(project_root.encode()).hexdigest()[:8]
        sanitized = sanitized[-52:].lstrip("_") + "_" + h
    return os.path.join(os.path.expanduser("~"), ".cortex", "projects", sanitized, "memory")


def _age_label(mtime: float) -> str:
    days = int((time.time() - mtime) / 86400)
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _load_memories(memory_dir: str) -> List[dict]:
    """Walk memory_dir and return a list of parsed memory dicts."""
    memories = []
    if not os.path.isdir(memory_dir):
        return memories
    for root, _dirs, files in os.walk(memory_dir):
        for fname in files:
            if not fname.endswith(".md") or fname == "MEMORY.md":
                continue
            fpath = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(fpath)
                with open(fpath, encoding="utf-8") as fh:
                    raw = fh.read()
                fm, body = _parse_frontmatter(raw)
                memories.append({
                    "path":        fpath,
                    "filename":    os.path.relpath(fpath, memory_dir),
                    "name":        fm.get("name") or os.path.splitext(fname)[0],
                    "description": fm.get("description", ""),
                    "type":        fm.get("type", ""),
                    "body":        body,
                    "mtime":       mtime,
                    "age":         _age_label(mtime),
                    "stale":       int((time.time() - mtime) / 86400) > 7,
                })
            except Exception:
                pass
    memories.sort(key=lambda m: m["mtime"], reverse=True)
    return memories


# ─────────────────────────── collapsible card ────────────────────────────────

class _MemoryCard(QFrame):
    """One collapsible row per memory file — redesigned to match Qoder's style."""

    delete_requested = pyqtSignal(str)          # emits file path

    def __init__(self, memory: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._memory   = memory
        self._expanded = False
        self._build()

    # ── build ──────────────────────────────────────────────────────────────
    def _build(self):
        mem  = self._memory
        mtype = mem["type"].lower() if mem["type"] else "default"
        bg_badge, fg_badge = _TYPE_COLORS.get(mtype, _TYPE_DEFAULT)

        self.setObjectName("MemCard")
        self.setStyleSheet(f"""
            QFrame#MemCard {{
                background: {_BG_CARD};
                border: 1px solid {_BORDER};
                border-radius: 10px;
            }}
            QFrame#MemCard:hover {{
                border-color: {_BORDER_LIGHT};
                background: {_BG_CARD_H};
            }}
        """)
        
        # Add subtle shadow effect
        self._shadow_anim = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header row ───────────────────────────────────────────────────
        header_w = QWidget()
        header_w.setCursor(Qt.CursorShape.PointingHandCursor)
        header_w.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border-radius: 8px;
            }}
        """)
        header_row = QHBoxLayout(header_w)
        header_row.setContentsMargins(14, 12, 14, 12)
        header_row.setSpacing(10)

        self._chevron = QLabel("›")
        self._chevron.setStyleSheet(f"color: {_FG_DIM}; font-size: 16px; font-weight: bold;")
        self._chevron.setFixedWidth(12)
        header_row.addWidget(self._chevron)

        # title
        title_lbl = QLabel(mem["name"])
        title_lbl.setStyleSheet(f"color: {_FG}; font-size: 14px; font-weight: 500;")
        title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_row.addWidget(title_lbl)

        # scope badge (pill style)
        scope_display = mtype.capitalize() if mtype else "General"
        badge = QLabel(scope_display)
        badge.setStyleSheet(f"""
            QLabel {{
                background: {bg_badge};
                color: {fg_badge};
                border-radius: 10px;
                font-size: 10px;
                padding: 3px 10px;
                font-weight: 600;
            }}
        """)
        header_row.addWidget(badge)

        # age indicator
        if mem["stale"]:
            age_lbl = QLabel(f"⚠ {mem['age']}")
            age_lbl.setStyleSheet("color: #ffb74d; font-size: 11px; margin-left: 8px;")
        else:
            age_lbl = QLabel(mem["age"])
            age_lbl.setStyleSheet(f"color: {_FG_MUTED}; font-size: 11px; margin-left: 8px;")
        header_row.addWidget(age_lbl)

        # delete button
        del_btn = QToolButton()
        del_btn.setText("✕")
        del_btn.setToolTip("Delete this memory")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(f"""
            QToolButton {{
                color: {_FG_DIM};
                border: none;
                background: transparent;
                font-size: 13px;
                padding: 4px 8px;
                border-radius: 4px;
            }}
            QToolButton:hover {{
                color: #f48771;
                background: rgba(244, 135, 113, 0.1);
            }}
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._memory["path"]))
        header_row.addWidget(del_btn)

        outer.addWidget(header_w)

        # ── expandable body ──────────────────────────────────────────────
        self._body_w = QWidget()
        self._body_w.setVisible(False)

        body_layout = QVBoxLayout(self._body_w)
        body_layout.setContentsMargins(36, 0, 16, 16)
        body_layout.setSpacing(14)

        # Keywords as tags
        if mem.get("description"):
            kw_container = QWidget()
            kw_layout = QHBoxLayout(kw_container)
            kw_layout.setContentsMargins(0, 0, 0, 0)
            kw_layout.setSpacing(6)
            kw_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            
            # Parse keywords (comma-separated or whole description)
            keywords = [k.strip() for k in mem["description"].split(",") if k.strip()]
            if len(keywords) == 1 and len(mem["description"]) > 30:
                keywords = [mem["description"][:50] + "..." if len(mem["description"]) > 50 else mem["description"]]
            
            for kw in keywords[:5]:  # Limit to 5 tags
                tag = QLabel(kw)
                tag.setStyleSheet(f"""
                    QLabel {{
                        background: {_BG_ELEVATED};
                        color: {_FG_DIM};
                        border-radius: 4px;
                        font-size: 11px;
                        padding: 4px 10px;
                    }}
                """)
                kw_layout.addWidget(tag)
            
            kw_layout.addStretch()
            body_layout.addWidget(kw_container)

        # File path
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_icon = QLabel("📄")
        file_icon.setStyleSheet("font-size: 12px;")
        file_val = QLabel(mem["filename"])
        file_val.setStyleSheet(f"color: {_ACCENT}; font-size: 12px; font-family: 'Consolas', monospace;")
        file_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        file_row.addWidget(file_icon)
        file_row.addWidget(file_val)
        file_row.addStretch()
        body_layout.addLayout(file_row)

        # Content
        if mem.get("body"):
            content_browser = QTextBrowser()
            content_browser.setReadOnly(True)
            content_browser.setOpenExternalLinks(False)
            font = QFont("Consolas", 12)
            content_browser.setFont(font)
            content_browser.setStyleSheet(f"""
                QTextBrowser {{
                    background: {_BG};
                    color: {_FG};
                    border: 1px solid {_BORDER};
                    border-radius: 6px;
                    padding: 12px;
                }}
                QScrollBar:vertical {{ 
                    width: 8px; 
                    background: {_BG}; 
                    border-radius: 4px;
                }}
                QScrollBar::handle:vertical {{ 
                    background: #555; 
                    border-radius: 4px;
                    min-height: 30px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background: #666;
                }}
            """)
            content_browser.setMinimumHeight(100)
            content_browser.setMaximumHeight(300)
            content_browser.setHtml(self._body_to_html(mem["body"]))
            body_layout.addWidget(content_browser)

        outer.addWidget(self._body_w)

        # ── click to expand ──────────────────────────────────────────────
        header_w.mousePressEvent = lambda _: self._toggle()

    def _toggle(self):
        # Prevent rapid clicking during animation
        if hasattr(self, '_animating') and self._animating:
            return
        
        self._expanded = not self._expanded
        self._animating = True
        
        # Rotate chevron
        self._chevron.setText("⌄" if self._expanded else "›")
        
        # Smooth height animation
        if self._expanded:
            self._body_w.setVisible(True)
            # Calculate target height
            target_height = self._body_w.sizeHint().height()
            self._body_w.setMaximumHeight(0)
            
            # Animate opening
            self._animate_height(0, target_height, 250)
        else:
            # Animate closing
            current_height = self._body_w.height()
            self._animate_height(current_height, 0, 200)
    
    def _animate_height(self, start, end, duration):
        """Animate the body widget height change."""
        self._height_anim = QPropertyAnimation(self._body_w, b"maximumHeight")
        self._height_anim.setDuration(duration)
        self._height_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._height_anim.setStartValue(start)
        self._height_anim.setEndValue(end)
        
        def on_finished():
            self._animating = False
            if not self._expanded:
                self._body_w.setVisible(False)
            self._body_w.setMaximumHeight(16777215)  # Reset to unlimited
        
        self._height_anim.finished.connect(on_finished)
        self._height_anim.start()

    @staticmethod
    def _body_to_html(text: str) -> str:
        """Convert minimal markdown to HTML for content display."""
        import html as _html
        lines  = text.split("\n")
        result = []
        in_code = False
        for line in lines:
            if line.startswith("```"):
                if not in_code:
                    result.append(
                        f'<pre style="background:#1a1a1a;padding:6px 8px;'
                        f'border-radius:4px;color:#ce9178;margin:4px 0;">'
                    )
                    in_code = True
                else:
                    result.append("</pre>")
                    in_code = False
                continue
            esc = _html.escape(line)
            if in_code:
                result.append(esc + "\n")
            elif line.startswith("## "):
                result.append(f"<b style='color:#4ec9b0'>{esc[3:]}</b><br>")
            elif line.startswith("**") and line.endswith("**"):
                result.append(f"<b>{esc[2:-2]}</b><br>")
            elif line.startswith("- ") or line.startswith("* "):
                result.append(f"&nbsp;&nbsp;• {esc[2:]}<br>")
            elif esc.strip():
                result.append(f"{esc}<br>")
            else:
                result.append("<br>")
        if in_code:
            result.append("</pre>")
        return (
            f'<div style="font-family:Consolas,monospace;font-size:12px;'
            f'color:{_FG};line-height:1.5;">' + "".join(result) + "</div>"
        )


# ─────────────────────────── main dialog ─────────────────────────────────────

class MemoryManagerDialog(QDialog):
    """
    Memory Manager — mirrors Qoder / Cursor "Settings → Memories" panel.

    Reads memory files from ~/.cortex/projects/<project>/memory/
    Allows expand-to-inspect, delete, clear-all, and toggle auto-generation.
    """

    def __init__(self, project_root: str, settings=None, parent=None):
        super().__init__(parent)
        self._project_root = project_root or os.getcwd()
        self._settings     = settings          # optional Settings instance
        self._memory_dir   = _compute_memory_dir(self._project_root)
        self._memories: List[dict] = []
        self._cards:   List[_MemoryCard] = []

        self.setWindowTitle("Memory Manager — Cortex IDE")
        self.setMinimumSize(820, 600)
        self.resize(900, 660)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet(f"""
            QDialog {{
                background: {_BG};
                color: {_FG};
            }}
            QLabel {{
                color: {_FG};
            }}
            QScrollArea {{
                border: none;
                background: {_BG};
            }}
            QScrollBar:vertical {{
                width: 8px;
                background: {_BG};
            }}
            QScrollBar::handle:vertical {{
                background: #555;
                border-radius: 4px;
            }}
        """)

        self._build_ui()
        self._load()

    # ── layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ─────────────────────────────────────────────────────
        top_bar = QWidget()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet(f"background: {_BG_HEADER}; border-bottom: 1px solid {_BORDER};")
        top_row = QHBoxLayout(top_bar)
        top_row.setContentsMargins(24, 0, 24, 0)

        title_lbl = QLabel("Memory Manager")
        title_lbl.setStyleSheet(f"color: {_FG}; font-size: 18px; font-weight: 600;")
        top_row.addWidget(title_lbl)
        top_row.addStretch()

        self._refresh_btn = QPushButton("⟳ Refresh")
        self._refresh_btn.setFixedHeight(32)
        self._refresh_btn.setStyleSheet(self._btn_style())
        self._refresh_btn.clicked.connect(self._load)
        top_row.addWidget(self._refresh_btn)

        root.addWidget(top_bar)

        # ── body ─────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background: {_BG};")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(28, 20, 28, 20)
        body_lay.setSpacing(16)

        # ── enable toggle row ────────────────────────────────────────────
        toggle_frame = QFrame()
        toggle_frame.setStyleSheet(f"""
            QFrame {{
                background: {_BG_CARD};
                border: 1px solid {_BORDER};
                border-radius: 10px;
            }}
        """)
        toggle_lay = QHBoxLayout(toggle_frame)
        toggle_lay.setContentsMargins(20, 18, 20, 18)

        toggle_info = QVBoxLayout()
        toggle_info.setSpacing(4)
        toggle_title = QLabel("Enable Automatic Generation")
        toggle_title.setStyleSheet(f"color: {_FG}; font-size: 14px; font-weight: 600;")
        toggle_desc = QLabel(
            "Automatically build memories based on your preferences and projects as you use it"
        )
        toggle_desc.setStyleSheet(f"color: {_FG_MUTED}; font-size: 12px;")
        toggle_info.addWidget(toggle_title)
        toggle_info.addWidget(toggle_desc)
        toggle_lay.addLayout(toggle_info, 1)

        enabled = True
        if self._settings:
            enabled = self._settings.get("memory", "enabled", default=True)
        self._enable_toggle = AnimatedToggle(checked=enabled)
        self._enable_toggle.toggled.connect(self._on_enable_toggled)
        toggle_lay.addWidget(self._enable_toggle)
        body_lay.addWidget(toggle_frame)

        # ── memory list header ───────────────────────────────────────────
        list_header = QHBoxLayout()
        list_header.setSpacing(12)
        mem_list_lbl = QLabel("Memory List")
        mem_list_lbl.setStyleSheet(f"color: {_FG}; font-size: 15px; font-weight: 600;")
        list_header.addWidget(mem_list_lbl)
        list_header.addStretch()

        self._count_lbl = QLabel("0 memories")
        self._count_lbl.setStyleSheet(f"color: {_FG_MUTED}; font-size: 13px;")
        list_header.addWidget(self._count_lbl)

        clear_btn = QPushButton("🗑 Clear All")
        clear_btn.setFixedHeight(30)
        clear_btn.setStyleSheet(self._btn_style(danger=True))
        clear_btn.clicked.connect(self._clear_all)
        list_header.addWidget(clear_btn)
        body_lay.addLayout(list_header)

        # ── scroll area for cards ────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: {_BG};
            }}
            QScrollBar:vertical {{
                width: 10px;
                background: {_BG};
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: #444;
                border-radius: 5px;
                min-height: 40px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #555;
            }}
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet(f"background: {_BG};")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_widget)
        body_lay.addWidget(self._scroll, 1)

        # ── empty state widget ───────────────────────────────────────────
        self._empty_widget = QWidget()
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(16)
        
        # Icon
        icon_lbl = QLabel("🧠")
        icon_lbl.setStyleSheet("font-size: 48px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(icon_lbl)
        
        # Title
        empty_title = QLabel("No memories saved yet")
        empty_title.setStyleSheet(f"color: {_FG}; font-size: 16px; font-weight: 500;")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        
        # Description
        empty_desc = QLabel(
            "The AI will save memories automatically as you work, or you can ask it:"
        )
        empty_desc.setStyleSheet(f"color: {_FG_MUTED}; font-size: 13px;")
        empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_desc)
        
        # Example prompts
        examples_widget = QWidget()
        examples_layout = QVBoxLayout(examples_widget)
        examples_layout.setSpacing(8)
        examples_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        examples = [
            '"Remember that I prefer pytest over unittest"',
            '"Save a memory: this project uses Django 4.2"'
        ]
        for ex in examples:
            ex_lbl = QLabel(ex)
            ex_lbl.setStyleSheet(f"""
                color: {_FG_DIM};
                font-size: 12px;
                font-family: 'Consolas', monospace;
                background: {_BG_CARD};
                padding: 8px 16px;
                border-radius: 6px;
            """)
            ex_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            examples_layout.addWidget(ex_lbl)
        
        empty_layout.addWidget(examples_widget)
        empty_layout.addStretch()
        
        self._empty_widget.setVisible(False)
        body_lay.addWidget(self._empty_widget, 1)

        # ── memory dir path label ────────────────────────────────────────
        dir_lbl = QLabel(f"Memory dir: {self._memory_dir}")
        dir_lbl.setStyleSheet(
            f"color: {_FG_MUTED}; font-size: 11px; font-family: 'Consolas', monospace;"
        )
        dir_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_lay.addWidget(dir_lbl)

        # ── close button ─────────────────────────────────────────────────
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(36)
        close_btn.setMinimumWidth(100)
        close_btn.setStyleSheet(self._btn_style())
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        body_lay.addLayout(close_row)

        root.addWidget(body, 1)

    # ── loading ─────────────────────────────────────────────────────────────

    def _load(self):
        """Reload memories from disk and rebuild the card list."""
        self._memories = _load_memories(self._memory_dir)

        # Clear existing cards
        for card in self._cards:
            card.setParent(None)
        self._cards.clear()
        # Remove stretch
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._memories:
            self._count_lbl.setText("0 memories")
            self._scroll.setVisible(False)
            self._empty_widget.setVisible(True)
            return

        self._scroll.setVisible(True)
        self._empty_widget.setVisible(False)
        self._count_lbl.setText(f"{len(self._memories)} memor{'y' if len(self._memories)==1 else 'ies'}")

        # Add cards with stagger animation delay
        for index, mem in enumerate(self._memories):
            card = _MemoryCard(mem, self._list_widget)
            card.delete_requested.connect(self._delete_memory)
            
            # Set up entrance animation
            card.setGraphicsEffect(None)
            card._opacity_effect = QGraphicsOpacityEffect(card)
            card._opacity_effect.setOpacity(0)
            card.setGraphicsEffect(card._opacity_effect)
            
            self._list_layout.addWidget(card)
            self._cards.append(card)
            
            # Staggered fade-in animation
            QTimer.singleShot(index * 80, lambda c=card: self._animate_card_entrance(c))

        self._list_layout.addStretch()
    
    def _animate_card_entrance(self, card):
        """Animate card fade-in."""
        card._opacity_anim = QPropertyAnimation(card._opacity_effect, b"opacity")
        card._opacity_anim.setDuration(300)
        card._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        card._opacity_anim.setStartValue(0)
        card._opacity_anim.setEndValue(1)
        card._opacity_anim.start()

    # ── actions ─────────────────────────────────────────────────────────────

    def _delete_memory(self, path: str):
        name = os.path.basename(path)
        reply = QMessageBox.question(
            self, "Delete Memory",
            f"Delete memory file:\n{name}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
        except OSError as e:
            QMessageBox.warning(self, "Delete Failed", str(e))
            return
        self._remove_from_index(name)
        self._load()

    def _remove_from_index(self, filename: str):
        """Remove the pointer line from MEMORY.md if it references filename."""
        index_path = os.path.join(self._memory_dir, "MEMORY.md")
        if not os.path.exists(index_path):
            return
        try:
            with open(index_path, encoding="utf-8") as fh:
                lines = fh.readlines()
            stem = os.path.splitext(filename)[0]
            new_lines = [l for l in lines if stem not in l and filename not in l]
            with open(index_path, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
        except Exception:
            pass

    def _clear_all(self):
        if not self._memories:
            return
        reply = QMessageBox.question(
            self, "Clear All Memories",
            f"Delete ALL {len(self._memories)} memory files for this project?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for mem in self._memories:
            try:
                os.remove(mem["path"])
            except OSError as e:
                errors.append(str(e))
        # Also clear MEMORY.md
        index_path = os.path.join(self._memory_dir, "MEMORY.md")
        try:
            if os.path.exists(index_path):
                os.remove(index_path)
        except OSError:
            pass
        if errors:
            QMessageBox.warning(self, "Some Deletions Failed", "\n".join(errors))
        self._load()

    def _on_enable_toggled(self, checked: bool):
        if self._settings:
            self._settings.set("memory", "enabled", checked)

    # ── style helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _btn_style(danger: bool = False) -> str:
        if danger:
            return f"""
                QPushButton {{
                    color: #f48771;
                    background: transparent;
                    border: 1px solid #5a3a3a;
                    border-radius: 6px;
                    padding: 6px 14px;
                    font-size: 13px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: rgba(244, 135, 113, 0.15);
                    border-color: #7a4a4a;
                }}
            """
        return f"""
            QPushButton {{
                color: {_FG};
                background: {_BG_CARD};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: {_BG_CARD_H};
                border-color: {_BORDER_LIGHT};
            }}
        """
