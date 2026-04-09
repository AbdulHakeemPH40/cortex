# AI AGENTIC IDE — Full Implementation Guide
> PyQt6 + Monaco Editor + Dracula Theme + AI Agent Loop

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Monaco Editor Integration](#3-monaco-editor-integration)
4. [Dracula Theme Implementation](#4-dracula-theme-implementation)
5. [Language & Framework Syntax Highlight](#5-language--framework-syntax-highlight)
6. [Full Monaco HTML Template](#6-full-monaco-html-template)
7. [AI Agent Loop](#7-ai-agent-loop)
8. [File Tree Panel](#8-file-tree-panel)
9. [Terminal Panel](#9-terminal-panel)
10. [Main Window Layout](#10-main-window-layout)
11. [pip Install Support](#11-pip-install-support)
12. [Migration Checklist](#12-migration-checklist)
13. [Key Notes & Pitfalls](#13-key-notes--pitfalls)

---

## 1. Project Overview

You are building a **standalone AI Agentic IDE** — not a VS Code fork, not a plugin. The AI agent is the core of the IDE. It writes, reads, edits, and deletes code files autonomously based on your instructions.

### Core Pillars
- **Monaco Editor** — embedded in QWebEngineView for professional code editing
- **Dracula Theme** — full custom color scheme across editor + UI
- **Syntax Highlighting** — all languages, frameworks, mixed code, Markdown
- **AI Agent Loop** — plan → write → run → observe → fix autonomously
- **File System Control** — agent reads, creates, edits, deletes project files
- **Terminal Integration** — execute code, capture output, feed back to agent

---

## 2. Architecture

The IDE is split into three layers that communicate bidirectionally:

| Layer | Technology | Responsibility |
|---|---|---|
| UI Shell | PyQt6 QMainWindow | Window, layout, panels, toolbar |
| Editor Core | Monaco via QWebEngineView | Code editing, syntax highlight, themes |
| Python Bridge | QWebChannel | Two-way Python ↔ JavaScript comms |
| AI Agent | Claude API / OpenAI API | Autonomous code writing and editing |
| File System | Python pathlib / os | Read, write, delete project files |
| Terminal | subprocess / QProcess | Run code, capture output |
| Chat Panel | QWebEngineView HTML | User ↔ Agent conversation UI |

---

## 3. Monaco Editor Integration

Monaco is the same editor engine that powers VS Code. It runs as a web page inside `QWebEngineView`. You communicate with it from Python using `runJavaScript()` and `QWebChannel`.

### 3.1 Python Setup

```python
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QObject, pyqtSlot

class EditorBridge(QObject):
    @pyqtSlot(str)
    def on_code_change(self, code):
        # Called every time user types in Monaco
        self.current_code = code

class MonacoWidget(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = EditorBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.setHtml(self.build_html())
```

### 3.2 Get / Set Code from Python

```python
# Get code from Monaco
def get_code(self, callback):
    self.page().runJavaScript("editor.getValue()", callback)

# Set code in Monaco
def set_code(self, code):
    escaped = code.replace("`", "\\`").replace("$", "\\$")
    self.page().runJavaScript(f"editor.setValue(`{escaped}`)")
```

### 3.3 Change Language Mode (per file type)

```python
def set_language(self, lang):
    self.page().runJavaScript(
        f"monaco.editor.setModelLanguage(editor.getModel(), '{lang}')"
    )
```

### 3.4 Open File (combines set_code + set_language)

```python
def open_file(self, filepath: str):
    lang = detect_language(filepath)
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    self.set_language(lang)
    self.set_code(code)
    self.current_file = filepath
```

---

## 4. Dracula Theme Implementation

Monaco does not ship with Dracula built-in. You define it using `monaco.editor.defineTheme()` **before** creating the editor instance.

### 4.1 Color Reference

| Token | Hex | Usage |
|---|---|---|
| Background | `#282a36` | Editor background |
| Foreground | `#f8f8f2` | Default text |
| Comments | `#6272a4` | Comments (italic) |
| Keywords | `#ff79c6` | if, def, class, return... |
| Strings | `#f1fa8c` | "hello", 'world' |
| Numbers | `#bd93f9` | 42, 3.14 |
| Functions | `#50fa7b` | function names |
| Types / Cyan | `#8be9fd` | type names, params |
| Operators | `#ff79c6` | =, +, -, ==... |
| Orange Accent | `#ffb86c` | decorators, regex |
| Selection | `#44475a` | selected text bg |
| Line Highlight | `#44475a` | current line bg |

### 4.2 Full defineTheme() JavaScript

```javascript
monaco.editor.defineTheme('dracula', {
    base: 'vs-dark',
    inherit: true,
    rules: [
        { token: 'comment',             foreground: '6272a4', fontStyle: 'italic' },
        { token: 'keyword',             foreground: 'ff79c6' },
        { token: 'string',              foreground: 'f1fa8c' },
        { token: 'number',              foreground: 'bd93f9' },
        { token: 'type',                foreground: '8be9fd' },
        { token: 'class',               foreground: '8be9fd', fontStyle: 'bold' },
        { token: 'function',            foreground: '50fa7b' },
        { token: 'variable',            foreground: 'f8f8f2' },
        { token: 'operator',            foreground: 'ff79c6' },
        { token: 'tag',                 foreground: 'ff79c6' },
        { token: 'attribute.name',      foreground: '50fa7b' },
        { token: 'attribute.value',     foreground: 'f1fa8c' },
        { token: 'delimiter',           foreground: 'f8f8f2' },
        { token: 'regexp',              foreground: 'ffb86c' },
        { token: 'constant',            foreground: 'bd93f9' },
        { token: 'decorator',           foreground: 'ffb86c', fontStyle: 'italic' },
        { token: 'metatag',             foreground: 'ff79c6' },
        { token: 'annotation',          foreground: 'ffb86c' },
        { token: 'invalid',             foreground: 'ff5555', fontStyle: 'underline' },
    ],
    colors: {
        'editor.background':                '#282a36',
        'editor.foreground':                '#f8f8f2',
        'editorLineNumber.foreground':      '#6272a4',
        'editorLineNumber.activeForeground':'#f8f8f2',
        'editor.selectionBackground':       '#44475a',
        'editor.lineHighlightBackground':   '#44475a50',
        'editorCursor.foreground':          '#f8f8f2',
        'editor.findMatchBackground':       '#ffb86c50',
        'editor.findMatchHighlightBackground': '#ffb86c30',
        'editorIndentGuide.background':     '#44475a',
        'editorBracketMatch.background':    '#44475a',
        'editorBracketMatch.border':        '#bd93f9',
        'scrollbarSlider.background':       '#44475a80',
        'scrollbarSlider.hoverBackground':  '#6272a4',
        'scrollbarSlider.activeBackground': '#bd93f9',
        'minimap.background':               '#21222c',
        'editorWidget.background':          '#21222c',
        'editorWidget.border':              '#44475a',
        'input.background':                 '#282a36',
        'input.foreground':                 '#f8f8f2',
        'input.border':                     '#6272a4',
        'focusBorder':                      '#bd93f9',
        'editorGutter.background':          '#282a36',
    }
});
```

### 4.3 Apply Theme When Creating Editor

```javascript
window.editor = monaco.editor.create(
    document.getElementById('editor'), {
        value: '',
        language: 'python',
        theme: 'dracula',            // your defined theme
        fontSize: 14,
        fontFamily: 'JetBrains Mono, Fira Code, Consolas, monospace',
        fontLigatures: true,
        lineNumbers: 'on',
        minimap: { enabled: true },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        tabSize: 4,
        insertSpaces: true,
        autoIndent: 'full',
        formatOnType: true,
        formatOnPaste: true,
        bracketPairColorization: { enabled: true },
        guides: {
            indentation: true,
            bracketPairs: true,
            bracketPairsHorizontal: true,
        },
        suggest: { showIcons: true },
        quickSuggestions: true,
        parameterHints: { enabled: true },
        hover: { enabled: true },
        renderWhitespace: 'selection',
        smoothScrolling: true,
        cursorBlinking: 'smooth',
        cursorSmoothCaretAnimation: 'on',
    }
);
```

---

## 5. Language & Framework Syntax Highlight

### 5.1 Built-in Language Map (Python side)

```python
import os

LANGUAGE_MAP = {
    # Python
    '.py':          'python',
    '.pyw':         'python',
    '.pyi':         'python',
    # Web
    '.html':        'html',       # auto handles embedded JS + CSS
    '.htm':         'html',
    '.css':         'css',
    '.scss':        'scss',
    '.sass':        'scss',
    '.less':        'less',
    # JavaScript / TypeScript
    '.js':          'javascript',
    '.jsx':         'javascript',  # React JSX — Monaco colors tags
    '.ts':          'typescript',
    '.tsx':         'typescript',  # React TSX
    '.mjs':         'javascript',
    '.cjs':         'javascript',
    # Frameworks (html mode covers template syntax well enough)
    '.vue':         'html',        # Vue SFC
    '.svelte':      'html',        # Svelte
    '.astro':       'html',        # Astro
    '.njk':         'html',        # Nunjucks
    '.jinja':       'html',        # Jinja2
    '.jinja2':      'html',        # Jinja2 / Django templates
    '.twig':        'html',        # Twig (PHP)
    '.blade':       'html',        # Laravel Blade
    '.erb':         'html',        # Ruby ERB
    # Data / Config
    '.json':        'json',
    '.jsonc':       'json',
    '.json5':       'json',
    '.yaml':        'yaml',
    '.yml':         'yaml',
    '.toml':        'ini',
    '.env':         'ini',
    '.ini':         'ini',
    '.cfg':         'ini',
    # Markup / Docs
    '.md':          'markdown',
    '.mdx':         'markdown',
    '.rst':         'markdown',
    '.xml':         'xml',
    '.svg':         'xml',
    '.xaml':        'xml',
    # Systems
    '.go':          'go',
    '.rs':          'rust',
    '.rb':          'ruby',
    '.php':         'php',
    '.java':        'java',
    '.cs':          'csharp',
    '.cpp':         'cpp',
    '.cc':          'cpp',
    '.cxx':         'cpp',
    '.c':           'c',
    '.h':           'cpp',
    '.hpp':         'cpp',
    '.swift':       'swift',
    '.kt':          'kotlin',
    '.dart':        'dart',
    '.r':           'r',
    # Shell / DevOps
    '.sh':          'shell',
    '.bash':        'shell',
    '.zsh':         'shell',
    '.fish':        'shell',
    '.ps1':         'powershell',
    '.dockerfile':  'dockerfile',
    # Database / Query
    '.sql':         'sql',
    '.graphql':     'graphql',
    '.gql':         'graphql',
    # Other
    '.tf':          'hcl',         # Terraform
    '.proto':       'proto',       # Protobuf
    '.tex':         'latex',       # LaTeX
}

def detect_language(filepath: str) -> str:
    """Detect Monaco language mode from file extension."""
    name = os.path.basename(filepath).lower()
    # Special filenames
    if name == 'dockerfile':
        return 'dockerfile'
    if name == 'makefile':
        return 'makefile'
    ext = os.path.splitext(filepath)[1].lower()
    return LANGUAGE_MAP.get(ext, 'plaintext')
```

### 5.2 Mixed Code in One File

Monaco handles these automatically — **zero extra config needed**:

| File | What Monaco does |
|---|---|
| `.html` | Colors HTML tags + `<style>` as CSS + `<script>` as JS |
| `.jsx` | Colors JS normally + JSX tags like HTML |
| `.tsx` | Colors TS normally + JSX tags like HTML |
| `.vue` | Colors template/script/style blocks (html mode) |
| `.php` | Colors PHP + embedded HTML |

```python
# Example: open an HTML file with embedded JS and CSS
editor.open_file("index.html")
# Monaco automatically highlights all three languages in one file
# No extra setup needed — just set language to 'html'
```

### 5.3 Indentation & Code Block Settings

```javascript
editor.updateOptions({
    tabSize: 4,                         // Python PEP8 standard
    insertSpaces: true,                 // spaces not tabs
    autoIndent: 'full',                 // smart context-aware indentation
    formatOnType: true,                 // auto-format while typing
    formatOnPaste: true,                // auto-format on paste
    foldingStrategy: 'indentation',     // code folding by indent level
    showFoldingControls: 'always',      // always show fold arrows
    renderIndentGuides: true,           // indent guide lines
    guides: {
        indentation: true,
        bracketPairs: true,
        bracketPairsHorizontal: true,
    }
});
```

---

## 6. Full Monaco HTML Template

Complete HTML to pass into `QWebEngineView.setHtml()`. Copy this, fill in the Dracula theme from Section 4.2.

```python
MONACO_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #282a36; overflow: hidden; }
  #editor { width: 100vw; height: 100vh; }
</style>
</head>
<body>
<div id="editor"></div>

<!-- QWebChannel bridge script -->
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>

<!-- Monaco loader -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/loader.min.js"></script>

<script>
require.config({
    paths: {
        vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs'
    }
});

require(['vs/editor/editor.main'], function() {

    // ── 1. Define Dracula Theme ──────────────────────────────────
    monaco.editor.defineTheme('dracula', {
        // paste full theme from Section 4.2 here
    });

    // ── 2. Create Editor ─────────────────────────────────────────
    window.editor = monaco.editor.create(
        document.getElementById('editor'), {
            value: '',
            language: 'python',
            theme: 'dracula',
            fontSize: 14,
            fontFamily: 'JetBrains Mono, Fira Code, Consolas, monospace',
            fontLigatures: true,
            lineNumbers: 'on',
            minimap: { enabled: true },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            tabSize: 4,
            insertSpaces: true,
            autoIndent: 'full',
            formatOnType: true,
            formatOnPaste: true,
            bracketPairColorization: { enabled: true },
            guides: { indentation: true, bracketPairs: true },
            smoothScrolling: true,
            cursorBlinking: 'smooth',
        }
    );

    // ── 3. Connect QWebChannel Bridge ───────────────────────────
    new QWebChannel(qt.webChannelTransport, function(channel) {
        window.bridge = channel.objects.bridge;

        // Send code changes to Python
        editor.onDidChangeModelContent(function() {
            bridge.on_code_change(editor.getValue());
        });

        // Notify Python editor is ready
        bridge.on_editor_ready();
    });

    // ── 4. Auto-resize with window ───────────────────────────────
    window.addEventListener('resize', function() {
        editor.layout();
    });

});
</script>
</body>
</html>
"""
```

> **Note:** `qrc:///qtwebchannel/qwebchannel.js` is the built-in Qt resource path. It works automatically in PyQt6 — no manual file needed.

---

## 7. AI Agent Loop

### 7.1 Agent States

| State | What Happens | Next State |
|---|---|---|
| IDLE | Waiting for user input | PLANNING |
| PLANNING | Agent breaks task into steps | WRITING |
| WRITING | Agent writes/edits code files | RUNNING |
| RUNNING | Code is executed in terminal | OBSERVING |
| OBSERVING | Output read, errors checked | FIXING or DONE |
| FIXING | Agent fixes errors autonomously | RUNNING |
| DONE | Task complete, report to user | IDLE |

### 7.2 Agent Loop Code

```python
import subprocess
import os
from pathlib import Path
from anthropic import Anthropic

client = Anthropic()

SYSTEM_PROMPT = """You are an AI coding agent inside an IDE.
You have tools to read, write, delete files and run terminal commands.
When the user gives you a task:
1. Plan what files need to be created or modified
2. Write the code using write_file tool
3. Run it using run_command tool
4. If errors occur, fix them and run again
5. Report completion to the user

Always write clean, well-commented code.
Always run the code after writing to verify it works.
"""

class AgentLoop:
    def __init__(self, project_path: str, editor_widget, chat_widget, terminal_widget):
        self.project_path = project_path
        self.editor = editor_widget
        self.chat = chat_widget
        self.terminal = terminal_widget
        self.history = []

    def run(self, user_instruction: str):
        """Start agent loop with user instruction."""
        self.history.append({
            "role": "user",
            "content": user_instruction
        })
        self.chat.add_agent_message("Thinking...")

        while True:
            response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=8096,
                system=SYSTEM_PROMPT,
                messages=self.history,
                tools=self.get_tools()
            )

            if response.stop_reason == "end_turn":
                # Agent finished
                final_text = next(
                    (b.text for b in response.content if hasattr(b, 'text')), 
                    "Done."
                )
                self.chat.add_agent_message(final_text)
                break

            if response.stop_reason == "tool_use":
                # Execute tools and continue loop
                tool_results = self.handle_tools(response.content)
                self.history.append({
                    "role": "assistant",
                    "content": response.content
                })
                self.history.append({
                    "role": "user",
                    "content": tool_results
                })
```

### 7.3 Agent Tools Definition

```python
def get_tools(self):
    return [
        {
            "name": "read_file",
            "description": "Read the contents of a file in the project",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from project root e.g. src/main.py"
                    }
                },
                "required": ["path"]
            }
        },
        {
            "name": "write_file",
            "description": "Write or overwrite a file with new content",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path e.g. src/utils.py"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write"
                    }
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "edit_file",
            "description": "Replace a specific section of a file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "description": "Exact text to find"},
                    "new_text": {"type": "string", "description": "Text to replace with"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        },
        {
            "name": "delete_file",
            "description": "Delete a file from the project",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "run_command",
            "description": "Run a terminal command in the project directory",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command e.g. python main.py or pip install flask"
                    }
                },
                "required": ["command"]
            }
        },
        {
            "name": "list_files",
            "description": "List all files in the project directory tree",
            "input_schema": {
                "type": "object",
                "properties": {}
            }
        }
    ]
```

### 7.4 Tool Execution Handler

```python
def handle_tools(self, content_blocks) -> list:
    results = []

    for block in content_blocks:
        if block.type != "tool_use":
            continue

        name = block.name
        inp  = block.input
        result = ""

        try:
            if name == "read_file":
                path = os.path.join(self.project_path, inp["path"])
                with open(path, 'r', encoding='utf-8') as f:
                    result = f.read()
                self.chat.add_system_message(f"📖 Reading: {inp['path']}")

            elif name == "write_file":
                path = os.path.join(self.project_path, inp["path"])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(inp["content"])
                self.editor.open_file(path)  # show in Monaco editor
                result = f"Written: {inp['path']}"
                self.chat.add_system_message(f"✏️ Wrote: {inp['path']}")

            elif name == "edit_file":
                path = os.path.join(self.project_path, inp["path"])
                with open(path, 'r', encoding='utf-8') as f:
                    original = f.read()
                updated = original.replace(inp["old_text"], inp["new_text"], 1)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(updated)
                self.editor.open_file(path)
                result = f"Edited: {inp['path']}"
                self.chat.add_system_message(f"✏️ Edited: {inp['path']}")

            elif name == "delete_file":
                path = os.path.join(self.project_path, inp["path"])
                os.remove(path)
                result = f"Deleted: {inp['path']}"
                self.chat.add_system_message(f"🗑️ Deleted: {inp['path']}")

            elif name == "run_command":
                self.chat.add_system_message(f"▶ Running: {inp['command']}")
                proc = subprocess.run(
                    inp["command"],
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=self.project_path,
                    timeout=60
                )
                result = proc.stdout
                if proc.stderr:
                    result += "\nSTDERR:\n" + proc.stderr
                self.terminal.append_output(f"$ {inp['command']}\n{result}")

            elif name == "list_files":
                files = [
                    str(p.relative_to(self.project_path))
                    for p in Path(self.project_path).rglob("*")
                    if p.is_file() and '.git' not in p.parts
                ]
                result = "\n".join(files)

        except Exception as e:
            result = f"ERROR: {str(e)}"
            self.chat.add_system_message(f"❌ Error in {name}: {e}")

        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": result
        })

    return results
```

---

## 8. File Tree Panel

```python
from PyQt6.QtWidgets import QTreeView, QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtCore import Qt

class FileTreePanel(QWidget):
    def __init__(self, root_path: str, editor_widget):
        super().__init__()
        self.editor = editor_widget
        self.root_path = root_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header label
        header = QLabel("  EXPLORER")
        header.setStyleSheet("""
            background: #21222c;
            color: #6272a4;
            font-size: 11px;
            font-weight: bold;
            padding: 8px 4px;
            letter-spacing: 1px;
        """)
        layout.addWidget(header)

        # File tree
        self.model = QFileSystemModel()
        self.model.setRootPath(root_path)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(root_path))
        self.tree.hideColumn(1)  # size
        self.tree.hideColumn(2)  # type
        self.tree.hideColumn(3)  # date
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("""
            QTreeView {
                background: #21222c;
                color: #f8f8f2;
                border: none;
                font-size: 13px;
                font-family: Segoe UI;
            }
            QTreeView::item:hover { background: #44475a; }
            QTreeView::item:selected { background: #44475a; color: #f8f8f2; }
            QTreeView::branch { background: #21222c; }
        """)
        self.tree.clicked.connect(self.on_click)
        layout.addWidget(self.tree)

    def on_click(self, index):
        path = self.model.filePath(index)
        if os.path.isfile(path):
            self.editor.open_file(path)

    def refresh(self):
        self.model.setRootPath(self.root_path)
```

---

## 9. Terminal Panel

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLineEdit, QLabel
import subprocess

class TerminalPanel(QWidget):
    def __init__(self, project_path: str):
        super().__init__()
        self.project_path = project_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QLabel("  TERMINAL")
        header.setStyleSheet("""
            background: #21222c;
            color: #6272a4;
            font-size: 11px;
            font-weight: bold;
            padding: 6px 4px;
            letter-spacing: 1px;
        """)
        layout.addWidget(header)

        # Output area
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("""
            QTextEdit {
                background: #1e1e2e;
                color: #f8f8f2;
                font-family: JetBrains Mono, Consolas, monospace;
                font-size: 13px;
                border: none;
                padding: 8px;
            }
        """)
        layout.addWidget(self.output)

        # Input line
        self.input = QLineEdit()
        self.input.setPlaceholderText("$ Enter command...")
        self.input.setStyleSheet("""
            QLineEdit {
                background: #282a36;
                color: #f8f8f2;
                font-family: JetBrains Mono, Consolas, monospace;
                font-size: 13px;
                border: none;
                border-top: 1px solid #44475a;
                padding: 6px 10px;
            }
        """)
        self.input.returnPressed.connect(self.run_user_command)
        layout.addWidget(self.input)

    def run_user_command(self):
        command = self.input.text().strip()
        if not command:
            return
        self.input.clear()
        self.run_command(command)

    def run_command(self, command: str) -> str:
        self.append_output(f"$ {command}")
        try:
            proc = subprocess.run(
                command, shell=True,
                capture_output=True, text=True,
                cwd=self.project_path, timeout=60
            )
            if proc.stdout:
                self.append_output(proc.stdout)
            if proc.stderr:
                self.append_output(proc.stderr, error=True)
            return proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            self.append_output("Command timed out.", error=True)
            return "timeout"

    def append_output(self, text: str, error: bool = False):
        color = '#ff5555' if error else '#f8f8f2'
        self.output.append(
            f'<span style="color:{color}; white-space:pre;">{text}</span>'
        )
        # Auto-scroll to bottom
        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
```

---

## 10. Main Window Layout

```python
from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QWidget, QVBoxLayout,
    QHBoxLayout, QToolBar, QStatusBar
)
from PyQt6.QtCore import Qt

class MainWindow(QMainWindow):
    def __init__(self, project_path: str):
        super().__init__()
        self.project_path = project_path
        self.setWindowTitle("AI Agentic IDE")
        self.resize(1400, 900)
        self.setStyleSheet("background: #282a36;")

        # ── Widgets ──────────────────────────────────────────────
        self.editor   = MonacoWidget()
        self.terminal = TerminalPanel(project_path)
        self.filetree = FileTreePanel(project_path, self.editor)
        self.chat     = ChatWidget()
        self.agent    = AgentLoop(project_path, self.editor, self.chat, self.terminal)

        # ── Center split: Editor (top) + Terminal (bottom) ───────
        center_split = QSplitter(Qt.Orientation.Vertical)
        center_split.addWidget(self.editor)
        center_split.addWidget(self.terminal)
        center_split.setSizes([700, 200])

        # ── Main split: FileTree | Center | Chat ─────────────────
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.addWidget(self.filetree)
        main_split.addWidget(center_split)
        main_split.addWidget(self.chat)
        main_split.setSizes([220, 820, 360])

        self.setCentralWidget(main_split)

        # ── Status bar ───────────────────────────────────────────
        self.status = QStatusBar()
        self.status.setStyleSheet("background:#21222c; color:#6272a4; font-size:12px;")
        self.setStatusBar(self.status)
        self.status.showMessage(f"Project: {project_path}")

        # ── Connect chat to agent ─────────────────────────────────
        self.chat.message_sent.connect(self.agent.run)
```

---

## 11. pip Install Support

The agent installs packages automatically via `run_command`. You can also detect missing imports and auto-install:

```python
def handle_import_error(self, error_output: str, command_run: str):
    """Auto-detect and install missing packages from error output."""
    import re
    # Detect: ModuleNotFoundError: No module named 'flask'
    match = re.search(r"No module named '([^']+)'", error_output)
    if match:
        package = match.group(1).split('.')[0]  # get root package
        self.chat.add_system_message(f"📦 Auto-installing: {package}")
        self.terminal.run_command(f"pip install {package}")
        # Re-run original command after install
        self.terminal.run_command(command_run)

# In handle_tools → run_command section, add:
if "ModuleNotFoundError" in result or "No module named" in result:
    self.handle_import_error(result, inp["command"])
```

**Manual install button in UI:**
```python
def install_package(self, package_name: str):
    self.terminal.run_command(f"pip install {package_name}")
```

---

## 12. Migration Checklist

Follow this order when integrating into your existing PyQt6 project:

| Step | Action |
|---|---|
| 1 | Replace existing editor widget with `MonacoWidget` class |
| 2 | Add `QWebChannel` bridge — register `EditorBridge`, wire `on_code_change` |
| 3 | Add `defineTheme('dracula')` — paste full theme from Section 4.2 |
| 4 | Add `LANGUAGE_MAP` dict + `detect_language()` function to Python side |
| 5 | Wire `open_file()` → calls `set_language()` + `set_code()` |
| 6 | Add `FileTreePanel` — `QTreeView` + `QFileSystemModel` |
| 7 | Add `TerminalPanel` — output `QTextEdit` + input `QLineEdit` |
| 8 | Update layout to `QSplitter` — FileTree \| Editor+Terminal \| Chat |
| 9 | Add `AgentLoop` class with all tools |
| 10 | Connect Chat widget `message_sent` signal → `agent.run()` |
| 11 | ✅ Test: open `.py` file → Dracula colors appear |
| 12 | ✅ Test: open `.html` file → JS + CSS highlighted in same file |
| 13 | ✅ Test: open `.jsx` → React JSX tags colored like HTML inside JS |
| 14 | ✅ Test: tell agent "create a Flask hello world app" → watch it work |

---

## 13. Key Notes & Pitfalls

### qwebchannel.js
Use `qrc:///qtwebchannel/qwebchannel.js` — this is built into PyQt6 automatically. No need to manually copy or serve this file.

### Monaco CDN vs Local
Use CDN during development. For production or offline use, download Monaco and serve locally:
```python
# Option: serve Monaco from local path
base_url = QUrl.fromLocalFile("/path/to/monaco/")
self.page().setHtml(html, base_url)
```

### Escape Code Before setValue()
Always escape before passing code into Monaco via `runJavaScript`:
```python
escaped = code.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
js = f"editor.setValue(`{escaped}`)"
self.page().runJavaScript(js)
```

### Agent Context Limit
For large projects, don't send all files in every API call. Only include files the agent has opened or recently modified. Build a simple context tracker:
```python
self.open_files = []  # track which files agent has touched
# Only include these in system prompt context
```

### Auto-save
Hook Monaco's change event to auto-save with a debounce:
```javascript
let saveTimer;
editor.onDidChangeModelContent(function() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function() {
        bridge.save_file(editor.getValue());
    }, 500);
});
```

### Thread Safety
Run `AgentLoop` in a `QThread` to avoid freezing the UI during long agent runs:
```python
from PyQt6.QtCore import QThread, pyqtSignal

class AgentThread(QThread):
    message_ready = pyqtSignal(str)

    def run(self):
        # run agent loop here
        # emit signals to update UI
        self.message_ready.emit("Agent response here")
```

### Vue / Svelte Advanced Highlighting
If you need perfect Vue or Svelte syntax highlighting beyond what `html` mode gives, add `monaco-textmate` + `vscode-oniguruma` to your JS bundle. This gives identical highlighting to VS Code for every framework.

---

*End of Document — AI Agentic IDE Implementation Guide*
