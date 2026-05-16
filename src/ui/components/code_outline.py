"""
Code Outline Panel for Cortex AI Agent IDE
Shows symbols (functions, classes, imports) in the current file
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QMenu, QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from pathlib import Path
from src.utils.language_detector import get_language_detector


class OutlineWidget(QWidget):
    """Code outline panel showing symbols."""
    
    symbol_selected = pyqtSignal(str, int)  # file_path, line_number
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_file = None
        self._is_dark = True
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(30)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 6, 0)
        
        title = QLabel("OUTLINE")
        title.setStyleSheet("font-size:10px; font-weight:bold; letter-spacing:1.2px; color:#858585;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # Refresh button
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setToolTip("Refresh outline")
        refresh_btn.setStyleSheet("border:none; background:transparent; font-size:12px;")
        refresh_btn.clicked.connect(self.refresh)
        header_layout.addWidget(refresh_btn)
        
        layout.addWidget(header)
        
        # Search/filter
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter symbols...")
        self.filter_input.textChanged.connect(self._filter_symbols)
        layout.addWidget(self.filter_input)
        
        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIndentation(12)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        
        # Styling
        self._update_tree_style()
        
        layout.addWidget(self.tree)
        
    def _update_tree_style(self):
        """Update tree styling based on theme."""
        if self._is_dark:
            self.tree.setStyleSheet("""
                QTreeWidget {
                    background-color: #1e1e1e;
                    border: none;
                    outline: 0;
                }
                QTreeWidget::item {
                    color: #d4d4d4;
                    padding: 2px 4px;
                }
                QTreeWidget::item:hover {
                    background-color: #2a2d2e;
                }
                QTreeWidget::item:selected {
                    background-color: #094771;
                }
            """)
        else:
            self.tree.setStyleSheet("""
                QTreeWidget {
                    background-color: #ffffff;
                    border: none;
                    outline: 0;
                }
                QTreeWidget::item {
                    color: #1a1a1a;
                    padding: 2px 4px;
                }
                QTreeWidget::item:hover {
                    background-color: #e8f0fe;
                }
                QTreeWidget::item:selected {
                    background-color: #cce5ff;
                }
            """)
            
    def set_file(self, file_path: str, content: str = None):
        """Set the current file to analyze."""
        self._current_file = file_path
        
        if content is None and file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except:
                content = ""
                
        self._update_outline(file_path, content)
        
    def _update_outline(self, file_path: str, content: str):
        """Update the outline tree with symbols from content."""
        self.tree.clear()
        
        if not content:
            return
            
        # Detect language and extract symbols
        detector = get_language_detector()
        lang_id = detector.detect(file_path, content)
        symbols = detector.extract_symbols(content, lang_id)
        
        # Emit event for cross-component communication (NEW)
        try:
            from src.core.event_bus import get_event_bus, EventType, OutlineEventData
            event_bus = get_event_bus()
            event_bus.publish(
                EventType.OUTLINE_UPDATED,
                OutlineEventData(
                    source_component="code_outline",
                    file_path=file_path,
                    symbols=symbols,
                    classes=symbols.get('classes', []),
                    functions=symbols.get('functions', [])
                )
            )
        except Exception as e:
            pass  # Don't break functionality if event bus fails
        
        # Add classes
        if symbols.get('classes'):
            classes_item = QTreeWidgetItem(self.tree)
            classes_item.setText(0, "📦 Classes")
            classes_item.setExpanded(True)
            
            for cls in symbols['classes']:
                item = QTreeWidgetItem(classes_item)
                item.setText(0, f"   {cls['name']}")
                item.setData(0, Qt.ItemDataRole.UserRole, cls.get('line', 0))
                
        # Add functions
        if symbols.get('functions'):
            functions_item = QTreeWidgetItem(self.tree)
            functions_item.setText(0, "⚡ Functions")
            functions_item.setExpanded(True)
            
            for func in symbols['functions']:
                item = QTreeWidgetItem(functions_item)
                sig = func.get('signature', '')
                if sig:
                    # Truncate long signatures
                    sig = sig[:60] + "..." if len(sig) > 60 else sig
                    item.setText(0, f"   {sig}")
                else:
                    item.setText(0, f"   {func['name']}()")
                item.setData(0, Qt.ItemDataRole.UserRole, func.get('line', 0))
                
        # Add imports
        if symbols.get('imports'):
            imports_item = QTreeWidgetItem(self.tree)
            imports_item.setText(0, "📥 Imports")
            
            for imp in symbols['imports']:
                item = QTreeWidgetItem(imports_item)
                item.setText(0, f"   {imp['name']}")
                item.setData(0, Qt.ItemDataRole.UserRole, imp.get('line', 0))
                
        # Add variables
        if symbols.get('variables'):
            vars_item = QTreeWidgetItem(self.tree)
            vars_item.setText(0, "🔤 Variables")
            
            for var in symbols['variables']:
                item = QTreeWidgetItem(vars_item)
                item.setText(0, f"   {var['name']}")
                item.setData(0, Qt.ItemDataRole.UserRole, var.get('line', 0))
                
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click - jump to symbol."""
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if line is not None and self._current_file:
            self.symbol_selected.emit(self._current_file, line)
            
    def _filter_symbols(self, text: str):
        """Filter symbols based on search text."""
        if not text:
            # Show all
            self._restore_visibility(self.tree.invisibleRootItem())
            return
            
        text = text.lower()
        self._filter_tree(self.tree.invisibleRootItem(), text)
        
    def _filter_tree(self, parent: QTreeWidgetItem, text: str) -> bool:
        """Recursively filter tree items."""
        has_visible_child = False
        
        for i in range(parent.childCount()):
            child = parent.child(i)
            
            # Check if this item matches
            item_text = child.text(0).lower()
            matches = text in item_text
            
            # Check children
            child_has_match = self._filter_tree(child, text)
            
            # Show/hide based on match or children
            if matches or child_has_match:
                child.setHidden(False)
                has_visible_child = True
            else:
                child.setHidden(True)
                
        return has_visible_child
        
    def _restore_visibility(self, parent: QTreeWidgetItem):
        """Restore visibility of all items."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setHidden(False)
            self._restore_visibility(child)
            
    def refresh(self):
        """Refresh the outline."""
        if self._current_file:
            self.set_file(self._current_file)
            
    def set_theme(self, is_dark: bool):
        """Update theme."""
        self._is_dark = is_dark
        self._update_tree_style()
        
    def _show_context_menu(self, position):
        """Show context menu."""
        menu = QMenu(self)
        
        action_refresh = menu.addAction("Refresh")
        action_collapse = menu.addAction("Collapse All")
        action_expand = menu.addAction("Expand All")
        
        action = menu.exec(self.tree.viewport().mapToGlobal(position))
        
        if action == action_refresh:
            self.refresh()
        elif action == action_collapse:
            self.tree.collapseAll()
        elif action == action_expand:
            self.tree.expandAll()
