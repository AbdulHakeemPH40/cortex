"""
Debug Panel for Cortex AI Agent IDE
Provides debugging capabilities with breakpoints, variable inspection, and call stack
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QTabWidget,
    QComboBox, QLineEdit, QHeaderView, QSplitter, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum


class BreakpointState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass
class Breakpoint:
    """Represents a breakpoint."""
    file_path: str
    line: int
    state: BreakpointState
    condition: str = ""  # Optional condition
    hit_count: int = 0


@dataclass
class StackFrame:
    """Represents a stack frame."""
    function: str
    file_path: str
    line: int
    column: int
    locals: Dict[str, str]


@dataclass
class Variable:
    """Represents a variable."""
    name: str
    value: str
    type: str
    children: List['Variable'] = None


class DebugPanel(QWidget):
    """Debug panel with breakpoints, call stack, and variables."""
    
    breakpoint_toggled = pyqtSignal(str, int, bool)  # file, line, enabled
    breakpoint_removed = pyqtSignal(str, int)  # file, line
    frame_selected = pyqtSignal(str, int)  # file, line
    step_over_requested = pyqtSignal()
    step_into_requested = pyqtSignal()
    step_out_requested = pyqtSignal()
    continue_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dark = True
        self._breakpoints: List[Breakpoint] = []
        self._stack_frames: List[StackFrame] = []
        self._variables: List[Variable] = []
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header with controls
        header = QWidget()
        header.setFixedHeight(40)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 6, 0)
        
        title = QLabel("🐛 DEBUG")
        title.setStyleSheet("font-size:10px; font-weight:bold; letter-spacing:1.2px; color:#858585;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # Debug controls
        self.btn_continue = QPushButton("▶️")
        self.btn_continue.setToolTip("Continue (F5)")
        self.btn_continue.setFixedSize(28, 28)
        self.btn_continue.clicked.connect(self.continue_requested.emit)
        
        self.btn_pause = QPushButton("⏸️")
        self.btn_pause.setToolTip("Pause")
        self.btn_pause.setFixedSize(28, 28)
        self.btn_pause.clicked.connect(self.pause_requested.emit)
        
        self.btn_step_over = QPushButton("⤴️")
        self.btn_step_over.setToolTip("Step Over (F10)")
        self.btn_step_over.setFixedSize(28, 28)
        self.btn_step_over.clicked.connect(self.step_over_requested.emit)
        
        self.btn_step_into = QPushButton("⤵️")
        self.btn_step_into.setToolTip("Step Into (F11)")
        self.btn_step_into.setFixedSize(28, 28)
        self.btn_step_into.clicked.connect(self.step_into_requested.emit)
        
        self.btn_step_out = QPushButton("⤴️")
        self.btn_step_out.setToolTip("Step Out (Shift+F11)")
        self.btn_step_out.setFixedSize(28, 28)
        self.btn_step_out.clicked.connect(self.step_out_requested.emit)
        
        self.btn_stop = QPushButton("⏹️")
        self.btn_stop.setToolTip("Stop (Shift+F5)")
        self.btn_stop.setFixedSize(28, 28)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        
        header_layout.addWidget(self.btn_continue)
        header_layout.addWidget(self.btn_pause)
        header_layout.addWidget(self.btn_step_over)
        header_layout.addWidget(self.btn_step_into)
        header_layout.addWidget(self.btn_step_out)
        header_layout.addWidget(self.btn_stop)
        
        layout.addWidget(header)
        
        # Tab widget for different views
        self.tabs = QTabWidget()
        
        # Breakpoints tab
        self.breakpoints_widget = self._create_breakpoints_view()
        self.tabs.addTab(self.breakpoints_widget, "Breakpoints")
        
        # Call Stack tab
        self.stack_widget = self._create_stack_view()
        self.tabs.addTab(self.stack_widget, "Call Stack")
        
        # Variables tab
        self.variables_widget = self._create_variables_view()
        self.tabs.addTab(self.variables_widget, "Variables")
        
        # Watch tab
        self.watch_widget = self._create_watch_view()
        self.tabs.addTab(self.watch_widget, "Watch")
        
        layout.addWidget(self.tabs)
        self._update_style()
        
    def _create_breakpoints_view(self) -> QWidget:
        """Create the breakpoints view."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Breakpoints list
        self.breakpoints_list = QListWidget()
        self.breakpoints_list.itemClicked.connect(self._on_breakpoint_clicked)
        self.breakpoints_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.breakpoints_list.customContextMenuRequested.connect(self._show_breakpoint_context_menu)
        
        layout.addWidget(self.breakpoints_list)
        
        # Remove all button
        btn_remove_all = QPushButton("Remove All Breakpoints")
        btn_remove_all.clicked.connect(self.clear_breakpoints)
        layout.addWidget(btn_remove_all)
        
        return widget
        
    def _create_stack_view(self) -> QWidget:
        """Create the call stack view."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        self.stack_list = QListWidget()
        self.stack_list.itemClicked.connect(self._on_stack_frame_clicked)
        
        layout.addWidget(self.stack_list)
        return widget
        
    def _create_variables_view(self) -> QWidget:
        """Create the variables view."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        self.variables_tree = QTreeWidget()
        self.variables_tree.setHeaderLabels(["Name", "Value", "Type"])
        self.variables_tree.header().setStretchLastSection(True)
        
        layout.addWidget(self.variables_tree)
        return widget
        
    def _create_watch_view(self) -> QWidget:
        """Create the watch view."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Add watch expression
        add_layout = QHBoxLayout()
        self.watch_input = QLineEdit()
        self.watch_input.setPlaceholderText("Enter expression to watch...")
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._add_watch_expression)
        add_layout.addWidget(self.watch_input)
        add_layout.addWidget(btn_add)
        layout.addLayout(add_layout)
        
        # Watch list
        self.watch_list = QTreeWidget()
        self.watch_list.setHeaderLabels(["Expression", "Value", "Type"])
        self.watch_list.header().setStretchLastSection(True)
        
        layout.addWidget(self.watch_list)
        return widget
        
    def _update_style(self):
        """Update widget styling."""
        if self._is_dark:
            style = """
                QListWidget, QTreeWidget {
                    background-color: #1e1e1e;
                    border: none;
                    outline: 0;
                    color: #d4d4d4;
                }
                QListWidget::item, QTreeWidget::item {
                    padding: 4px 8px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover {
                    background-color: #2a2d2e;
                }
                QListWidget::item:selected, QTreeWidget::item:selected {
                    background-color: #094771;
                }
            """
        else:
            style = """
                QListWidget, QTreeWidget {
                    background-color: #ffffff;
                    border: none;
                    outline: 0;
                    color: #1a1a1a;
                }
                QListWidget::item, QTreeWidget::item {
                    padding: 4px 8px;
                }
                QListWidget::item:hover, QTreeWidget::item:hover {
                    background-color: #e8f0fe;
                }
                QListWidget::item:selected, QTreeWidget::item:selected {
                    background-color: #cce5ff;
                }
            """
            
        self.breakpoints_list.setStyleSheet(style)
        self.stack_list.setStyleSheet(style)
        self.variables_tree.setStyleSheet(style)
        self.watch_list.setStyleSheet(style)
        
    def add_breakpoint(self, file_path: str, line: int, condition: str = ""):
        """Add a breakpoint."""
        bp = Breakpoint(
            file_path=file_path,
            line=line,
            state=BreakpointState.ENABLED,
            condition=condition
        )
        self._breakpoints.append(bp)
        self._refresh_breakpoints()
        self.breakpoint_toggled.emit(file_path, line, True)
        
    def remove_breakpoint(self, file_path: str, line: int):
        """Remove a breakpoint."""
        self._breakpoints = [
            bp for bp in self._breakpoints 
            if not (bp.file_path == file_path and bp.line == line)
        ]
        self._refresh_breakpoints()
        self.breakpoint_removed.emit(file_path, line)
        
    def toggle_breakpoint(self, file_path: str, line: int) -> bool:
        """Toggle a breakpoint. Return True if breakpoint is now set."""
        for bp in self._breakpoints:
            if bp.file_path == file_path and bp.line == line:
                self.remove_breakpoint(file_path, line)
                return False
                
        self.add_breakpoint(file_path, line)
        return True
        
    def has_breakpoint(self, file_path: str, line: int) -> bool:
        """Check if a breakpoint exists."""
        return any(
            bp.file_path == file_path and bp.line == line 
            for bp in self._breakpoints
        )
        
    def clear_breakpoints(self):
        """Remove all breakpoints."""
        for bp in self._breakpoints:
            self.breakpoint_removed.emit(bp.file_path, bp.line)
        self._breakpoints.clear()
        self._refresh_breakpoints()
        
    def _refresh_breakpoints(self):
        """Refresh the breakpoints list."""
        self.breakpoints_list.clear()
        
        for bp in self._breakpoints:
            item = QListWidgetItem()
            icon = "🔴" if bp.state == BreakpointState.ENABLED else "⚪"
            text = f"{icon} {bp.file_path}:{bp.line}"
            if bp.condition:
                text += f" [when: {bp.condition}]"
            item.setText(text)
            item.setData(Qt.ItemDataRole.UserRole, bp)
            self.breakpoints_list.addItem(item)
            
    def _refresh_stack(self):
        """Refresh the call stack."""
        self.stack_list.clear()
        
        for i, frame in enumerate(self._stack_frames):
            item = QListWidgetItem()
            prefix = "▶️" if i == 0 else "  "
            text = f"{prefix} {frame.function} at {frame.file_path}:{frame.line}"
            item.setText(text)
            item.setData(Qt.ItemDataRole.UserRole, frame)
            self.stack_list.addItem(item)
            
    def _refresh_variables(self):
        """Refresh the variables view."""
        self.variables_tree.clear()
        
        for var in self._variables:
            self._add_variable_to_tree(var, self.variables_tree)
            
    def _add_variable_to_tree(self, var: Variable, parent):
        """Add a variable to the tree."""
        if isinstance(parent, QTreeWidget):
            item = QTreeWidgetItem(parent)
        else:
            item = QTreeWidgetItem(parent)
            
        item.setText(0, var.name)
        item.setText(1, var.value)
        item.setText(2, var.type)
        
        if var.children:
            for child in var.children:
                self._add_variable_to_tree(child, item)
                
    def _on_breakpoint_clicked(self, item: QListWidgetItem):
        """Handle breakpoint click."""
        bp = item.data(Qt.ItemDataRole.UserRole)
        if bp:
            self.frame_selected.emit(bp.file_path, bp.line)
            
    def _on_stack_frame_clicked(self, item: QListWidgetItem):
        """Handle stack frame click."""
        frame = item.data(Qt.ItemDataRole.UserRole)
        if frame:
            self.frame_selected.emit(frame.file_path, frame.line)
            
    def _show_breakpoint_context_menu(self, position):
        """Show context menu for breakpoint."""
        menu = QMenu(self)
        
        action_remove = menu.addAction("Remove Breakpoint")
        action_remove_all = menu.addAction("Remove All")
        menu.addSeparator()
        action_edit_condition = menu.addAction("Edit Condition...")
        
        item = self.breakpoints_list.itemAt(position)
        action = menu.exec(self.breakpoints_list.viewport().mapToGlobal(position))
        
        if action == action_remove and item:
            bp = item.data(Qt.ItemDataRole.UserRole)
            if bp:
                self.remove_breakpoint(bp.file_path, bp.line)
        elif action == action_remove_all:
            self.clear_breakpoints()
            
    def _add_watch_expression(self):
        """Add a watch expression."""
        expr = self.watch_input.text()
        if expr:
            item = QTreeWidgetItem(self.watch_list)
            item.setText(0, expr)
            item.setText(1, "<not available>")
            item.setText(2, "unknown")
            self.watch_input.clear()
            
    def update_stack(self, frames: List[StackFrame]):
        """Update the call stack."""
        self._stack_frames = frames
        self._refresh_stack()
        
        # Emit event for cross-component communication (NEW)
        try:
            from src.core.event_bus import get_event_bus, EventType, DebugEventData
            event_bus = get_event_bus()
            if frames:
                event_bus.publish(
                    EventType.DEBUG_STACK_FRAME_CHANGED,
                    DebugEventData(
                        source_component="debug_panel",
                        session_id=getattr(self, '_session_id', ''),
                        stack_frames=[{
                            'function': f.function,
                            'file_path': f.file_path,
                            'line': f.line,
                            'column': f.column
                        } for f in frames],
                        is_paused=len(frames) > 0
                    )
                )
        except Exception as e:
            pass  # Don't break functionality if event bus fails
        
    def update_variables(self, variables: List[Variable]):
        """Update the variables."""
        self._variables = variables
        self._refresh_variables()
        
    def set_theme(self, is_dark: bool):
        """Update theme."""
        self._is_dark = is_dark
        self._update_style()
