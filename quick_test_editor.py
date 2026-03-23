"""Quick syntax highlight test."""
from PyQt6.QtWidgets import QApplication
from src.ui.components.editor import CodeEditor
import sys

app = QApplication(sys.argv)

editor = CodeEditor(language="python")
editor.setPlainText("""
def hello():
    name = "World"
    count = 42
    print(f"Hello {name}!")
    
class Test:
    pass
""")

print("\n=== Editor State ===")
print(f"Background: {editor.palette().color(editor.palette().ColorRole.Base).name()}")
print(f"Text: {editor.palette().color(editor.palette().ColorRole.Text).name()}")
print(f"Highlighter formats: {len(editor._highlighter._formats)}")
print(f"Lexer: {editor._highlighter._lexer.__class__.__name__}")

# Show editor window
editor.setWindowTitle("Syntax Highlight Test")
editor.resize(800, 600)
editor.show()

print("\n✅ Editor window opened!")
print("Check if text has colors (not white)")

sys.exit(app.exec())
