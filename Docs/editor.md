You are working inside Py Cortex IDE — a PyQt6-based desktop IDE.

## Task
Build a self-contained WebviewPanel system that displays an HTML-based code 
editor (editor.html) inside a QWebEngineView panel, similar to VS Code's 
WebviewPanel API.

## What to build

1. **editor.html** — A standalone HTML file that:
   - Loads Monaco Editor from CDN (https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs)
   - Accepts a file path + content via QWebChannel (window.qt.webChannelTransport)
   - Renders the code with correct language syntax highlighting
   - Sends back changes to Python via QWebChannel when content is edited

2. **webview_panel.py** — A Python class `WebviewPanel(QWidget)` that:
   - Contains a QWebEngineView loading editor.html
   - Exposes a QWebChannel bridge object with these methods:
     - `open_file(path: str, content: str, language: str)` — loads file into editor
     - `get_content() -> str` — returns current editor content
   - Can be docked as a right-side panel inside the main QSplitter in main_window.py

3. **Wire it into main_window.py**:
   - Add `self._webview_panel = WebviewPanel()` alongside existing panels
   - Add it to the main QSplitter as the rightmost pane
   - Expose a method `open_in_webview(path, content, language)` on CortexMainWindow

## Constraints
- PyQt6 only — no PyQt5 or PySide
- QWebEngineView + QWebChannel for Python-JS bridge
- Monaco Editor via CDN, no npm build step
- editor.html must be a file on disk, loaded via QWebEngineView.load(QUrl.fromLocalFile(...))
- Follow the existing code style in main_window.py (self._ prefix for private attrs)
- Do not break existing panels (sidebar, review panel, chat history)

## Files to read first
- src/main_window.py — to understand the QSplitter layout and existing panel wiring
- src/sidebar.py — to see how existing panels are structured

## Deliverables
- editor.html (in src/assets/ or src/)
- src/webview_panel.py
- Patch to main_window.py showing exactly where/how to wire it in