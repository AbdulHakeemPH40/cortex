# AI Chat Logic Extraction: `chat.html` (Django) -> Cortex Desktop

## Scope

This document compares:

- Browser template source: `src/ui/html/ai_chat/chat.html` (Django/Jinja page)
- Desktop target: `src/ui/html/ai_chat/aichat.html` + `src/ui/html/ai_chat/script.js`

Primary focus requested:

- AI chat rendering and streaming logic
- Code block rendering and syntax highlighting
- Math/LaTeX handling
- Mermaid/diagram handling
- Missing logic that should be ported to desktop without changing Cortex desktop design

---

## Is `chat.html` Django?

Yes. `chat.html` is a Django template, not the desktop WebView page.

Evidence:

- `{% extends 'visualizer/base.html' %}`
- `{% block content %}`
- Django CSRF usage in fetch calls (`X-CSRFToken`)
- API routes such as `/aichat/api/...`

These are browser/server flow patterns and are not directly portable to the Qt desktop bridge model.

---

## Extraction Matrix

### 1) Markdown + Code Block Rendering

Status: **Mostly already in desktop**

Already present in desktop (`script.js`):

- `marked` custom renderer pipeline
- code block wrappers with headers/buttons
- highlight.js integration
- table wrapper cleanup
- specialized wrappers (email/social/creative/accounting/math)

Notes:

- Browser and desktop both have complex duplicate rendering paths (multiple init/renderer sections).
- Desktop should consolidate to one renderer entrypoint to reduce regressions.

---

### 2) Math/LaTeX Robustness

Status: **Already present (strong parity)**

Already in desktop (`script.js`):

- `sanitizeTeX()`
- `balanceBraces()`
- `protectMath()` / `restoreMath()`
- `fixLatexInCodeTags()`
- URL/path/math conflict mitigation (`cleanBrokenWindowsPaths()`, `cleanMarkdownUrls()`, `cleanRenderedUrls()`)
- final MathJax typeset pass

This means the core math extraction from browser template has effectively already been ported.

---

### 3) Mermaid Rendering

Status: **Already present**

Already in desktop:

- Mermaid block rendering in markdown pipeline
- deferred render via `data-mermaid-pending`
- fallback when CDN fails
- copy/download helpers

No major missing extraction here.

---

### 4) Streaming UX Logic

Status: **Partially present**

Desktop has:

- chunk accumulation
- throttled streaming render
- thinking indicators
- post-stream finalization and persistence
- tag-aware filtering (`<task_summary>`, `<exploration>`, etc.)

Potentially missing from browser logic:

- explicit cutoff continuation flow based on finish reason:
  - browser has `finish_reason` handling and `Continue` button for truncation
  - desktop currently has no equivalent end-of-stream "continue generation" UX exposed

Recommendation:

- Add optional desktop `continue generation` action if backend exposes finish reason/cutoff metadata via bridge.

---

### 5) Reasoning Content Display

Status: **Different, not strictly missing**

Browser logic has explicit `reasoning_content` stream channel and display region.
Desktop uses thinking/activity/tool cards and thought-duration summary.

Recommendation:

- Keep current desktop design.
- Optionally map `reasoning_content` channel into existing activity/timeline card rather than adding browser-style reasoning panel.

---

### 6) Browser-only Logic (Do Not Port As-Is)

Status: **Not applicable to desktop**

Do not port directly:

- Django template blocks and inheritance
- CSRF/cookie request flows
- `/aichat/api/...` fetch conversation CRUD logic
- guest localStorage history tied to web auth mode
- mobile keyboard/browser viewport heuristics
- dark-mode lock/hijack for browser theme switch

Desktop already uses bridge events and local app state patterns.

---

## Important Gaps/Issues Found in Current Desktop Files

These are not extraction gaps from browser logic, but quality issues in desktop implementation:

1. Unsanitized HTML insertion risk in markdown render path (`innerHTML` after `marked.parse`) should be hardened.
2. Multiple `DOMContentLoaded` handlers and duplicated helper definitions in `script.js` increase maintenance risk.
3. Conflicting duplicated selectors/keyframes in `style.css` create brittle styling behavior.
4. `aichat.html` has malformed completion popup markup (`resizer` nested incorrectly).

---

## Recommended Port Plan (Design-safe)

### Phase 1 (Safe parity + reliability)

- Add optional finish-reason continuation UX in desktop:
  - bridge emits finish reason
  - if cutoff, show compact "Continue" action in current desktop message action area

### Phase 2 (Stability cleanup)

- Consolidate markdown renderer setup in `script.js` into one authoritative function
- Remove duplicate helper definitions where possible (`escapeHtml`, duplicate init blocks)

### Phase 3 (Security hardening)

- Sanitize rendered markdown HTML before `innerHTML` assignment (allowlist-based sanitizer)
- Keep code block/math rendering intact via token pipeline before final sanitization

### Phase 4 (Style consistency)

- Flatten duplicate CSS blocks in `style.css` (`#header`, `#input-area`, `#input-container`, `.primary-btn`, repeated `@keyframes fadeIn`)
- Preserve visual output while removing order-dependent conflicts

---

## Conclusion

Most "core AI chat logic" from Django `chat.html` for code blocks, math/latex, and mermaid is already present in desktop `aichat.html`/`script.js`.

What remains is mainly:

- selective UX parity (`continue generation on cutoff`)
- technical debt cleanup (duplicate init/render/style paths)
- render safety hardening

This keeps Cortex desktop design intact while improving correctness and maintainability.
