

# 🧠 0) Target Outcome

After this integration, Cortex will support:

* real-time diagnostics (errors/warnings)
* hover type info
* autocomplete
* go-to definition (optional next step)

All powered by Pyright via **LSP (Language Server Protocol)**.

---

# 🧱 1) Architecture (final design)

```
Cortex IDE
 ├── Editor (QScintilla / QPlainTextEdit)
 ├── LSP Client (you build this)
 ├── LSP Manager (multi-language ready)
 └── External Server
       └── Pyright (pyright-langserver --stdio)
```

---

# ⚙️ 2) Install + Verify

```bash
npm install -g pyright
```

Test:

```bash
pyright-langserver --stdio
```

If it runs → OK.

---

# 🧩 3) LSP Protocol Basics (minimum you MUST support)

You only need these to start:

| Method                          | Purpose        |
| ------------------------------- | -------------- |
| initialize                      | start session  |
| initialized                     | confirm ready  |
| textDocument/didOpen            | open file      |
| textDocument/didChange          | update text    |
| textDocument/publishDiagnostics | receive errors |
| textDocument/completion         | autocomplete   |
| textDocument/hover              | hover info     |

---

# 🧪 4) Core Implementation (PyQt6)

## 4.1 LSP Client (minimal but real)

```python
import json
import uuid
from PyQt6.QtCore import QProcess, QObject, pyqtSignal


class LSPClient(QObject):
    diagnostics_received = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.process = QProcess()
        self.buffer = b""
        self.id_counter = 0

        self.process.readyReadStandardOutput.connect(self.read_output)

    def start(self):
        self.process.start("pyright-langserver", ["--stdio"])

    def send(self, method, params=None):
        self.id_counter += 1

        message = {
            "jsonrpc": "2.0",
            "id": self.id_counter,
            "method": method,
            "params": params or {}
        }

        body = json.dumps(message)
        header = f"Content-Length: {len(body)}\r\n\r\n"

        self.process.write((header + body).encode())

    def notify(self, method, params):
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }

        body = json.dumps(message)
        header = f"Content-Length: {len(body)}\r\n\r\n"

        self.process.write((header + body).encode())

    def read_output(self):
        self.buffer += self.process.readAllStandardOutput().data()

        while b"\r\n\r\n" in self.buffer:
            header, rest = self.buffer.split(b"\r\n\r\n", 1)
            content_length = int(header.split(b":")[1].strip())

            if len(rest) < content_length:
                return

            body = rest[:content_length]
            self.buffer = rest[content_length:]

            message = json.loads(body.decode())

            if message.get("method") == "textDocument/publishDiagnostics":
                self.diagnostics_received.emit(message["params"])
```

---

## ⚙️ 4.2 Initialize Pyright

```python
def initialize_lsp(client):
    client.send("initialize", {
        "processId": None,
        "rootUri": None,
        "capabilities": {}
    })

    client.notify("initialized", {})
```

---

## 📂 4.3 Open File

```python
def open_file(client, file_path, text):
    client.notify("textDocument/didOpen", {
        "textDocument": {
            "uri": f"file://{file_path}",
            "languageId": "python",
            "version": 1,
            "text": text
        }
    })
```

---

## ✏️ 4.4 Handle Typing (CRITICAL)

```python
def on_text_change(client, file_path, new_text, version):
    client.notify("textDocument/didChange", {
        "textDocument": {
            "uri": f"file://{file_path}",
            "version": version
        },
        "contentChanges": [
            {"text": new_text}
        ]
    })
```

👉 Always increment `version`

---

## ❗ 4.5 Receive Errors

```python
def handle_diagnostics(params):
    uri = params["uri"]
    diagnostics = params["diagnostics"]

    for d in diagnostics:
        print("Error:", d["message"])
```

Connect:

```python
client.diagnostics_received.connect(handle_diagnostics)
```

---

# 🎨 5) Editor Integration (QScintilla)

When diagnostics arrive:

* underline error range
* add marker in margin

Example logic:

```python
line = d["range"]["start"]["line"]
message = d["message"]

# highlight line or range
```

---

# ⚡ 6) Autocomplete

Send request:

```python
client.send("textDocument/completion", {
    "textDocument": {"uri": uri},
    "position": {"line": line, "character": col}
})
```

You’ll receive:

```json
{
  "result": {
    "items": [...]
  }
}
```

Show in dropdown UI.

---

# 🔍 7) Hover

```python
client.send("textDocument/hover", {
    "textDocument": {"uri": uri},
    "position": {"line": line, "character": col}
})
```

---

# 🧱 8) Cortex-Specific Clean Structure

```
cortex/
 ├── lsp/
 │    ├── client.py
 │    ├── manager.py   ← handles multiple languages
 │    ├── pyright.py   ← config
 │
 ├── editor/
 │    ├── python_editor.py
 │
 ├── ui/
 │    ├── completion_popup.py
 │
 └── core/
      ├── document.py
```

---

# 🔥 9) Common Mistakes (avoid these)

❌ Not handling `Content-Length` correctly
❌ Not incrementing version
❌ Sending full file path without `file://`
❌ Blocking UI thread (use async signals)
❌ Not buffering partial messages

---

# 🚀 10) Phase Upgrade Plan

### Phase 1 (NOW)

* diagnostics ✔

### Phase 2

* autocomplete
* hover

### Phase 3

* go-to-definition
* rename symbol

---

# 🧩 11) Multi-language Future

Later plug:

* Python → Pyright
* JS → tsserver
* C++ → clangd

Same LSP client, different server.

---

# 🧠 Final Summary

You are building:

* **LSP Client (core logic)**
* Pyright runs externally as **LSP Server**
* Communication = JSON-RPC over stdio
* Editor reacts to diagnostics + completions

