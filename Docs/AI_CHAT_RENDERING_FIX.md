# AI Chat HTML Rendering Fix

This document tracks fixes for broken Markdown rendering in the Cortex AI Chat UI.

## Symptoms
- Markdown tables show as raw `| ... |` text and the separator row (`---`) leaks into output.
- Some responses show literal `\n` / `\t` sequences instead of real newlines/tabs.
- Code blocks sometimes do not get the header (Copy button) because they never become real `<pre><code>` blocks.

## Root Causes
- Some streamed chunks arrive with *literal* escape sequences (e.g. `\n`) rather than real newlines, so Markdown parsers can't recognize block structure (tables, lists, code fences).
- Some table outputs arrive with table rows concatenated onto one line, which breaks GFM table detection.

## Fixes Applied (2026-04-23)
- `src/ui/html/ai_chat/script.js`
  - Added `unescapeLikelyEscapes()` to de-escape literal `\n` / `\t` / `\r` *only when the message has no real newlines*.
  - Added `splitLikelyConcatenatedTableLines()` and applied it before table-block normalization.

- `src/ui/html/ai_chat/table_test.html`
  - Added `marked.setOptions({ breaks: true, gfm: true, ... })` so it behaves like the real chat page.

## How To Validate
1. Open `src/ui/html/ai_chat/table_test.html` in the embedded webview or a browser.
2. Confirm the output section renders an actual `<table>` for the test cases.
3. In the AI chat panel, ask the model for a Markdown table + fenced code block and confirm:
   - The table becomes a real table.
   - The code block shows the Copy header.
