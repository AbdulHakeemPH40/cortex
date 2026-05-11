# IDE Crash Fix Plan — QWebChannel/Monaco Crash on Startup

**Date:** 2026-05-09/11  
**Status:** Fix implemented — warmup queue blocks all file opens for 60s

---

## Crash Pattern

IDE crashes silently ~22-42 seconds after startup on Windows 25H2. The `_on_render_crash` handler never fires — Chromium's render process exits before Qt can deliver the signal.

### Terminal.log Timeline
```
23:02:23 → IDE starts
23:02:27 → 12 files restored via sequential queue (1.5s each)
23:02:34 → LSP pyright ready, diagnostics arrive for 8 files
23:02:59 → Delayed session-restore: "Opening file: test_full.py"
23:03:02 → Delayed session-restore: "Opening file: test.html"  
23:03:09 → "File already open, switching: test_full.py" + "Opening: test_item_platform.py"
         → CRASH (shell returns immediately)
```

---

## Final Root Cause (Confirmed)

**QWebChannel IPC + Monaco `model.setValue()` crashes Chromium's render process during the startup warmup phase.**

Testing proved:
- `monaco.editor.setModelMarkers()` is NOT the primary trigger (warmup marker suppression alone didn't fix)
- `model.setValue()` with ANY file size during the first ~60s can crash Chromium
- Even a 5-second JS guard (`isSettingContent`) between successive `setValue()` calls wasn't enough
- **Only blocking ALL QWebChannel file opens for 60s prevents the crash**

---

## Implemented Fix: Startup Warmup Queue

### Python side (`src/main_window.py`)

1. **`import time`** at module level (was local in `__init__`)
2. **`self._start_time`** tracked in `__init__`
3. **Warmup guard in `_open_file`**: All files during first 60s are queued instead of opened
4. **`_flush_warmup_queue()`**: After 60s, opens all queued files through normal pipeline

### JavaScript side (`src/assets/editor.html`)

1. **`STARTUP_WARMUP_MS = 60000`** — suppress markers for 60s
2. **`isSettingContent` guard** — prevents overlapping `model.setValue()` calls (5s hold)
3. **`SET_CONTENT_DEBOUNCE = 500ms`** — debounce between content flushes
4. **`MONACO_LOAD_TIME`** — set when Monaco initializes, used by warmup guard

---

## All Fixes Applied (Chronological)

| # | Fix | File | Purpose |
|---|-----|------|---------|
| 1 | `setEditorContent` debounce (50ms) | editor.html | Collapse rapid model.setValue() bursts |
| 2 | Don't clear model on close-all | editor.html | Prevent empty→content tokenization wave |
| 3 | Gate `bridge.onFileClosed` with `isSwitchingFile` | editor.html | Reduce QWebChannel traffic |
| 4 | `closeAllFiles()` JS + Python | editor.html, webview_panel.py | Bulk close without per-file bridge calls |
| 5 | `isSwitchingFile` gate on `_lspDiagnosticsResult` | editor.html | Suppress markers during tab switches |
| 6 | `isRenderingMarkers` + `setTimeout(0)` + `setTimeout(300)` | editor.html | Prevent scroll→diagnostics→marker cascade |
| 7 | `SWITCH_STOP_MS=2000ms` | editor.html | Keep isSwitchingFile during entire dispatch |
| 8 | `LSP_STARTUP_DELAY=25s` | lsp_manager.py | Defer pyright spawn until files dispatched |
| 9 | Sequential queue 1500ms/file | webview_panel.py | One file at a time through QWebChannel |
| 10 | Disabled git periodic refresh | main_window.py | Ruled out git subprocess as crash trigger |
| 11 | `close_fds=True` on all subprocess.Popen | multiple files | Prevent fd inheritance |
| 12 | `STARTUP_WARMUP_MS=60s` marker suppression | editor.html | Suppress LSP markers during startup |
| 13 | `isSettingContent` guard (5s hold) | editor.html | Prevent overlapping model.setValue() |
| 14 | `SET_CONTENT_DEBOUNCE=500ms` | editor.html | Debounce content flushes |
| 15 | **Warmup queue: block ALL file opens for 60s** | main_window.py | **THE FIX** — prevents QWebChannel IPC during startup |

---

## How It Works

1. IDE starts, `self._start_time` is recorded in `__init__`
2. Any `_open_file()` call within first 60s → file queued to `_warmup_queued_files`, NOT sent to webview
3. No QWebChannel IPC, no `model.setValue()`, no Monaco tokenizer activity during Chromium startup
4. After 60s, `_flush_warmup_queue()` fires → opens all queued files through normal pipeline
5. Chromium is now stable; files load normally
6. LSP markers also suppressed during warmup (JS side); diagnostics flush after warmup

## Test Results

| Test | Configuration | Result |
|------|--------------|--------|
| Baseline | No warmup guard, large files present | Crash at ~22s |
| Marker suppression only | STARTUP_WARMUP_MS=60s, markers suppressed | Crash at ~34s |
| isSettingContent + 5s guard | JS-side setValue guard | Crash at ~34s |
| **All-file-block 60s** | **Warmup queue — NO files opened** | **NO crash** |

**Conclusion:** The crash is caused by ANY QWebChannel IPC + Monaco interaction during Chromium's first ~60s of startup. Blocking all file opens during this period is the only reliable fix.
