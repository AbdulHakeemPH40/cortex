"""
Icon factory — draws clean, thin-stroke VS Code-style icons via QPainter.
Returns QIcon objects ready to use in QPushButton or QAction.
"""
from PyQt6.QtGui import QPixmap, QIcon, QColor, QPainter, QPen, QPainterPath, QFont
from PyQt6.QtCore import Qt, QRectF, QPointF
import os
from pathlib import Path


def _make_pixmap(size: int = 32) -> tuple[QPixmap, QPainter]:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return px, p


def _pen(p: QPainter, color: str, width: float = 1.8):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


# ── Individual icon drawers ───────────────────────────────────────────────────

def _draw_folder(p: QPainter, s: int, color: str):
    """Solid VS Code style folder icon."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    # Main folder body
    p.drawRoundedRect(QRectF(s*0.05, s*0.25, s*0.9, s*0.65), 2, 2)
    # Folder tab
    tab = QPainterPath()
    tab.moveTo(s*0.1, s*0.25)
    tab.lineTo(s*0.1, s*0.15)
    tab.lineTo(s*0.4, s*0.15)
    tab.lineTo(s*0.45, s*0.25)
    p.drawPath(tab)


def _draw_new_file(p: QPainter, s: int, color: str):
    """Solid High-Fidelity New File: Solid sheet with plus overlay."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    # Main Doc
    doc = QPainterPath()
    doc.moveTo(s*0.15, s*0.1)
    doc.lineTo(s*0.55, s*0.1)
    doc.lineTo(s*0.85, s*0.4)
    doc.lineTo(s*0.85, s*0.9)
    doc.lineTo(s*0.15, s*0.9)
    doc.closeSubpath()
    p.drawPath(doc)
    
    # Plus Shape (White overlay for contrast)
    p.setBrush(QColor("#ffffff") if color != "#ffffff" else QColor("#1e1e1e"))
    pw, ph = s*0.08, s*0.25 # Sharp, bold
    p.drawRect(QRectF(s*0.5, s*0.65, ph, pw)) # Horiz
    p.drawRect(QRectF(s*0.5 + ph/2 - pw/2, s*0.65 - (ph-pw)/2, pw, ph)) # Vert
    
    # Fold (Solid cutout)
    p.setBrush(QColor(color).lighter(125))
    fold = QPainterPath()
    fold.moveTo(s*0.55, s*0.1)
    fold.lineTo(s*0.55, s*0.4)
    fold.lineTo(s*0.85, s*0.4)
    fold.closeSubpath()
    p.drawPath(fold)


def _draw_new_folder(p: QPainter, s: int, color: str):
    """Solid High-Fidelity New Folder: Solid folder with plus overlay."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    
    # Body
    p.drawRoundedRect(QRectF(s*0.05, s*0.25, s*0.9, s*0.65), 1.5, 1.5)
    tab = QPainterPath()
    tab.moveTo(s*0.1, s*0.25)
    tab.lineTo(s*0.1, s*0.15)
    tab.lineTo(s*0.4, s*0.15)
    tab.lineTo(s*0.45, s*0.25)
    p.drawPath(tab)
    
    # Plus Shape
    p.setBrush(QColor("#ffffff") if color != "#ffffff" else QColor("#1e1e1e"))
    pw, ph = s*0.08, s*0.25
    p.drawRect(QRectF(s*0.4, s*0.55, ph, pw)) # Horiz
    p.drawRect(QRectF(s*0.4 + ph/2 - pw/2, s*0.55 - (ph-pw)/2, pw, ph)) # Vert


def _draw_refresh(p: QPainter, s: int, color: str):
    """Solid High-Fidelity Refresh: Bold circular arrow with filled head."""
    _pen(p, color, 3.0) # Heavyweight orbit
    rect = QRectF(s*0.2, s*0.2, s*0.6, s*0.6)
    p.drawArc(rect, 40 * 16, 280 * 16)
    # Solid heavy arrow head
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    arrow = QPainterPath()
    arrow.moveTo(s*0.8, s*0.15)
    arrow.lineTo(s*1.0, s*0.4)
    arrow.lineTo(s*0.65, s*0.45)
    arrow.closeSubpath()
    p.drawPath(arrow)


def _draw_collapse(p: QPainter, s: int, color: str):
    """Solid High-Fidelity Collapse icon."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    # Solid background with white cutout line
    p.drawRoundedRect(QRectF(s*0.15, s*0.15, s*0.7, s*0.7), 2, 2)
    p.setBrush(QColor("#ffffff") if color == "#c8c8c8" else QColor("#1e1e1e"))
    p.drawRect(QRectF(s*0.3, s*0.45, s*0.4, s*0.1)) # Horizontal minus cutout


def _draw_save(p: QPainter, s: int, color: str):
    """Save / floppy disk icon."""
    _pen(p, color, 1.8)
    m = s * 0.1
    # Outer square
    p.drawRoundedRect(QRectF(m, m, s - 2*m, s - 2*m), 2, 2)
    # Disk label area (top stripe)
    p.drawRect(QRectF(m + s*0.12, m, s*0.44, s*0.28))
    # Bottom storage area
    p.drawRect(QRectF(m + s*0.18, s*0.55, s*0.64, s*0.3))
    # Write notch (right side of label)
    _pen(p, color, 1.2)
    x = m + s*0.12 + s*0.44 - s*0.12
    p.drawLine(QPointF(x, m), QPointF(x, m + s*0.28))


def _draw_play(p: QPainter, s: int, color: str):
    """Play / run triangle icon."""
    path = QPainterPath()
    m = s * 0.2
    path.moveTo(m, m)
    path.lineTo(s - m, s * 0.5)
    path.lineTo(m, s - m)
    path.closeSubpath()
    pen = QPen(QColor(color))
    pen.setWidthF(1.8)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor(color))
    p.drawPath(path)


def _draw_terminal(p: QPainter, s: int, color: str):
    """>_ terminal prompt icon."""
    _pen(p, color, 2.0)
    m = s * 0.12
    # Outer rectangle
    p.drawRoundedRect(QRectF(m, m, s - 2*m, s - 2*m), 3, 3)
    # Chevron >
    _pen(p, color, 2.0)
    cx, cy = s * 0.28, s * 0.5
    p.drawLine(QPointF(cx - s*0.08, cy - s*0.12), QPointF(cx + s*0.08, cy))
    p.drawLine(QPointF(cx + s*0.08, cy), QPointF(cx - s*0.08, cy + s*0.12))
    # Underscore _
    p.drawLine(QPointF(s*0.48, cy + s*0.13), QPointF(s*0.72, cy + s*0.13))


def _draw_search(p: QPainter, s: int, color: str):
    """Magnifying glass search icon."""
    _pen(p, color, 2.0)
    r = s * 0.28
    cx, cy = s * 0.38, s * 0.38
    p.drawEllipse(QPointF(cx, cy), r, r)
    _pen(p, color, 2.2)
    lx = cx + r * 0.72
    ly = cy + r * 0.72
    p.drawLine(QPointF(lx, ly), QPointF(s * 0.82, s * 0.82))


def _draw_files(p: QPainter, s: int, color: str):
    """Solid document icon."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    # Document base
    p.drawRoundedRect(QRectF(s*0.15, s*0.1, s*0.7, s*0.8), 2, 2)
    # Folded corner
    p.setBrush(QColor("#ffffff" if color != "#ffffff" else "#858585"))
    corner = QPainterPath()
    corner.moveTo(s*0.55, s*0.1)
    corner.lineTo(s*0.85, s*0.1)
    corner.lineTo(s*0.85, s*0.4)
    corner.closeSubpath()
    p.drawPath(corner)


def _draw_ai(p: QPainter, s: int, color: str):
    """Sparkle star / AI icon — 4-point star."""
    cx, cy = s * 0.5, s * 0.5
    path = QPainterPath()
    import math
    outer, inner = s * 0.38, s * 0.14
    for i in range(8):
        angle = math.radians(i * 45 - 90)
        r = outer if i % 2 == 0 else inner
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    pen = QPen(QColor(color))
    pen.setWidthF(1.5)
    p.setPen(pen)
    p.setBrush(QColor(color))
    p.drawPath(path)


def _draw_moon(p: QPainter, s: int, color: str):
    """Crescent moon icon."""
    m = s * 0.1
    # Full circle
    full = QPainterPath()
    full.addEllipse(QRectF(m, m, s - 2*m, s - 2*m))
    # Cutout circle (shifted right+up)
    cut = QPainterPath()
    cut.addEllipse(QRectF(m + s*0.2, m - s*0.05, s - 2*m + s*0.05, s - 2*m + s*0.05))
    crescent = full.subtracted(cut)
    pen = QPen(QColor(color))
    pen.setWidthF(0)
    p.setPen(pen)
    p.setBrush(QColor(color))
    p.drawPath(crescent)


def _draw_sun(p: QPainter, s: int, color: str):
    """Sun icon — circle + rays."""
    cx, cy = s * 0.5, s * 0.5
    _pen(p, color, 1.8)
    # Center circle
    p.drawEllipse(QPointF(cx, cy), s * 0.18, s * 0.18)
    # 8 rays
    import math
    for i in range(8):
        angle = math.radians(i * 45)
        x1 = cx + s * 0.26 * math.cos(angle)
        y1 = cy + s * 0.26 * math.sin(angle)
        x2 = cx + s * 0.4 * math.cos(angle)
        y2 = cy + s * 0.4 * math.sin(angle)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


# ── Language Icons ───────────────────────────────────────────────────────────

def _draw_python(p: QPainter, s: int, color: str):
    """Official Python logo — Multicolor Blue/Yellow snakes."""
    # Top Snake (Blue)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#3776AB"))
    path1 = QPainterPath()
    m = s * 0.1
    path1.moveTo(s*0.5, m)
    path1.lineTo(s*0.3, m)
    path1.arcTo(QRectF(m, m, s*0.4, s*0.4), 90, 180)
    path1.lineTo(s*0.5, s*0.4)
    path1.lineTo(s*0.5, s*0.5)
    path1.lineTo(s*0.7, s*0.5)
    path1.arcTo(QRectF(s*0.5, m, s*0.4, s*0.4), 270, -90)
    path1.lineTo(s*0.5, m)
    p.drawPath(path1)
    
    # Bottom Snake (Yellow)
    p.setBrush(QColor("#FFD43B"))
    path2 = QPainterPath()
    path2.moveTo(s*0.5, s-m)
    path2.lineTo(s*0.7, s-m)
    path2.arcTo(QRectF(s*0.5, s*0.5, s*0.4, s*0.4), 270, 180)
    path2.lineTo(s*0.5, s*0.6)
    path2.lineTo(s*0.5, s*0.5)
    path2.lineTo(s*0.3, s*0.5)
    path2.arcTo(QRectF(m, s*0.5, s*0.4, s*0.4), 90, -90)
    path2.lineTo(s*0.5, s-m)
    p.drawPath(path2)
    
    # Eyes
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QRectF(s*0.22, s*0.2, s*0.08, s*0.08))
    p.drawEllipse(QRectF(s*0.7, s*0.72, s*0.08, s*0.08))


def _draw_js(p: QPainter, s: int, color: str):
    """Official JS icon — Yellow square with black text."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#F7DF1E"))
    p.drawRect(QRectF(0, 0, s, s))
    
    p.setPen(QColor("#000000"))
    font = QFont("Segoe UI", int(s * 0.38))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s-s*0.05), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, "JS ")


def _draw_ts(p: QPainter, s: int, color: str):
    """Official TS icon — Blue square with white text."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#3178C6"))
    p.drawRect(QRectF(0, 0, s, s))
    
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", int(s * 0.38))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s-s*0.05), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, "TS ")


def _draw_js(p: QPainter, s: int, color: str):
    """JS icon — Square with 'JS'."""
    _pen(p, color, 1.5)
    m = s * 0.15
    p.drawRect(QRectF(m, m, s-2*m, s-2*m))
    font = QFont("Segoe UI", int(s * 0.35))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(m, m, s-2*m, s-2*m), Qt.AlignmentFlag.AlignCenter, "JS")


def _draw_html(p: QPainter, s: int, color: str):
    """Official HTML5 icon — Orange shield."""
    p.setPen(Qt.PenStyle.NoPen)
    # Shield base
    p.setBrush(QColor("#E34F26"))
    path = QPainterPath()
    path.moveTo(s*0.1, s*0.05)
    path.lineTo(s*0.9, s*0.05)
    path.lineTo(s*0.82, s*0.85)
    path.lineTo(s*0.5, s*0.95)
    path.lineTo(s*0.18, s*0.85)
    path.closeSubpath()
    p.drawPath(path)
    # Light side
    p.setBrush(QColor("#F06529"))
    path2 = QPainterPath()
    path2.moveTo(s*0.5, s*0.1)
    path2.lineTo(s*0.85, s*0.1)
    path2.lineTo(s*0.78, s*0.88)
    path2.lineTo(s*0.5, s*0.95)
    path2.closeSubpath()
    p.drawPath(path2)
    # White 5
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", int(s * 0.5))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "5")


def _draw_css(p: QPainter, s: int, color: str):
    """Official CSS3 icon — Blue shield."""
    p.setPen(Qt.PenStyle.NoPen)
    # Shield base
    p.setBrush(QColor("#1572B6"))
    path = QPainterPath()
    path.moveTo(s*0.1, s*0.05)
    path.lineTo(s*0.9, s*0.05)
    path.lineTo(s*0.82, s*0.85)
    path.lineTo(s*0.5, s*0.95)
    path.lineTo(s*0.18, s*0.85)
    path.closeSubpath()
    p.drawPath(path)
    # Light side
    p.setBrush(QColor("#33A9DC"))
    path2 = QPainterPath()
    path2.moveTo(s*0.5, s*0.1)
    path2.lineTo(s*0.85, s*0.1)
    path2.lineTo(s*0.78, s*0.88)
    path2.lineTo(s*0.5, s*0.95)
    path2.closeSubpath()
    p.drawPath(path2)
    # White 3
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", int(s * 0.5))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "3")


def _draw_cpp(p: QPainter, s: int, color: str):
    """C++ icon."""
    _pen(p, color, 1.8)
    font = QFont("Segoe UI", int(s * 0.35))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "C++")


def _draw_rust(p: QPainter, s: int, color: str):
    """Rust gear (simplified)."""
    _pen(p, color, 1.5)
    cx, cy = s*0.5, s*0.5
    r = s * 0.3
    p.drawEllipse(QPointF(cx, cy), r, r)
    # R inside
    font = QFont("Consolas", int(s * 0.3))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "R")


def _draw_markdown(p: QPainter, s: int, color: str):
    """Official Markdown icon branding."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#007ACC"))
    p.drawRoundedRect(QRectF(s*0.05, s*0.2, s*0.9, s*0.6), 2, 2)
    
    p.setPen(QColor("#ffffff"))
    _pen(p, "#ffffff", 1.8)
    # M shape
    p.drawPolyline([
        QPointF(s*0.15, s*0.65), QPointF(s*0.15, s*0.35),
        QPointF(s*0.3, s*0.55), QPointF(s*0.45, s*0.35),
        QPointF(s*0.45, s*0.65)
    ])
    # Down arrow
    p.drawLine(QPointF(s*0.7, s*0.35), QPointF(s*0.7, s*0.6))
    p.drawPolyline([QPointF(s*0.6, s*0.5), QPointF(s*0.7, s*0.65), QPointF(s*0.8, s*0.5)])

def _draw_json(p: QPainter, s: int, color: str):
    """JSON icon (curly braces)."""
    _pen(p, color, 2.0)
    # Left {
    p.drawPolyline([
        QPointF(s*0.35, s*0.2), QPointF(s*0.2, s*0.2),
        QPointF(s*0.2, s*0.45), QPointF(s*0.1, s*0.5),
        QPointF(s*0.2, s*0.55), QPointF(s*0.2, s*0.8),
        QPointF(s*0.35, s*0.8)
    ])
    # Right }
    p.drawPolyline([
        QPointF(s*0.65, s*0.2), QPointF(s*0.8, s*0.2),
        QPointF(s*0.8, s*0.45), QPointF(s*0.9, s*0.5),
        QPointF(s*0.8, s*0.55), QPointF(s*0.8, s*0.8),
        QPointF(s*0.65, s*0.8)
    ])

def _draw_java(p: QPainter, s: int, color: str):
    """Official Java icon coffee cup."""
    # Steam (Red/Orange)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ED8B00"))
    p.drawPolyline([QPointF(s*0.4, s*0.3), QPointF(s*0.5, s*0.1), QPointF(s*0.6, s*0.3)])
    p.setBrush(QColor("#E76F51"))
    p.drawPolyline([QPointF(s*0.3, s*0.35), QPointF(s*0.4, s*0.2), QPointF(s*0.5, s*0.35)])
    
    # Cup (Blue)
    p.setBrush(QColor("#0073B7"))
    path = QPainterPath()
    path.moveTo(s*0.2, s*0.4)
    path.lineTo(s*0.8, s*0.4)
    path.cubicTo(s*0.8, s*0.8, s*0.2, s*0.8, s*0.2, s*0.4)
    p.drawPath(path)
    # Handle
    hpath = QPainterPath()
    hpath.addEllipse(QRectF(s*0.7, s*0.45, s*0.2, s*0.2))
    p.drawPath(hpath)
    # Saucer
    p.drawEllipse(QRectF(s*0.2, s*0.8, s*0.6, s*0.1))

def _draw_php(p: QPainter, s: int, color: str):
    """PHP icon."""
    _pen(p, color, 1.8)
    font = QFont("Segoe UI", int(s * 0.4))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "php")

def _draw_ruby(p: QPainter, s: int, color: str):
    """Ruby icon (diamond)."""
    _pen(p, color, 1.8)
    p.drawPolyline([
        QPointF(s*0.5, s*0.2), QPointF(s*0.8, s*0.45),
        QPointF(s*0.5, s*0.85), QPointF(s*0.2, s*0.45),
        QPointF(s*0.5, s*0.2)
    ])
    p.drawLine(QPointF(s*0.2, s*0.45), QPointF(s*0.8, s*0.45))
    p.drawLine(QPointF(s*0.35, s*0.2), QPointF(s*0.35, s*0.45))
    p.drawLine(QPointF(s*0.65, s*0.2), QPointF(s*0.65, s*0.45))

def _draw_database(p: QPainter, s: int, color: str):
    """Database icon (SQL)."""
    _pen(p, color, 1.8)
    p.drawEllipse(QRectF(s*0.2, s*0.2, s*0.6, s*0.2))
    p.drawArc(QRectF(s*0.2, s*0.4, s*0.6, s*0.2), 180 * 16, 180 * 16)
    p.drawArc(QRectF(s*0.2, s*0.6, s*0.6, s*0.2), 180 * 16, 180 * 16)
    p.drawLine(s*0.2, s*0.3, s*0.2, s*0.7)
    p.drawLine(s*0.8, s*0.3, s*0.8, s*0.7)

def _draw_go(p: QPainter, s: int, color: str):
    """Go icon."""
    _pen(p, color, 1.8)
    font = QFont("Segoe UI", int(s * 0.45))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "Go")


# ── Public API ────────────────────────────────────────────────────────────────

_DRAWERS = {
    "folder":   _draw_folder,
    "save":     _draw_save,
    "play":     _draw_play,
    "terminal": _draw_terminal,
    "search":   _draw_search,
    "files":    _draw_files,
    "ai":       _draw_ai,
    "moon":     _draw_moon,
    "sun":      _draw_sun,
    "python":   _draw_python,
    "javascript": _draw_js,
    "typescript": _draw_ts,
    "html":     _draw_html,
    "css":      _draw_css,
    "cpp":      _draw_cpp,
    "rust":     _draw_rust,
    "go":       _draw_go,
    "markdown": _draw_markdown,
    "json":     _draw_json,
    "java":     _draw_java,
    "php":      _draw_php,
    "ruby":     _draw_ruby,
    "sql":      _draw_database,
    "new_file": _draw_new_file,
    "new_folder": _draw_new_folder,
    "refresh":    _draw_refresh,
    "collapse":   _draw_collapse,
}


# Global cache to prevent redundant drawing operations
_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}


def make_icon(name: str, color: str = "#c0c0c0", size: int = 32) -> QIcon:
    """Return a QIcon. Prioritizes official PNG assets, falls back to QPainter with caching."""
    # 0. Check cache first
    cache_key = (name, color, size)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    # 1. Try to load from official assets first
    asset_path = Path(__file__).parent.parent / "assets" / "icons" / f"{name}.png"
    if asset_path.exists():
        icon = QIcon(str(asset_path))
        _ICON_CACHE[cache_key] = icon
        return icon

    # 2. Fallback to programmatic drawing
    px, p = _make_pixmap(size)
    drawer = _DRAWERS.get(name)
    if drawer:
        drawer(p, size, color)
    p.end()
    
    icon = QIcon(px)
    _ICON_CACHE[cache_key] = icon
    return icon


def make_button_icon(name: str, is_dark: bool = True, size: int = 28) -> QIcon:
    """Icon with theme-appropriate default color."""
    color = "#c8c8c8" if is_dark else "#444444"
    return make_icon(name, color, size)
