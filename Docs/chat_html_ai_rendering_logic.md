# chat.html — AI Response Rendering Logic (Full Documentation)

> Source: `src/ui/html/ai_chat/chat.html` (7,802 lines)
> Project: Logic-Practice Assistant (Django web app, browser-based)
> This is NOT the PyQt6 desktop app (Cortex) — it's a separate Django template.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Streaming Pipeline](#streaming-pipeline)
3. [formatMessage() — Core Rendering Engine](#formatmessage--core-rendering-engine)
4. [Content Type Detection](#content-type-detection)
5. [Specialized Content Renderers](#specialized-content-renderers)
6. [Code Block Rendering (marked.js + highlight.js)](#code-block-rendering)
7. [Math/LaTeX Rendering (MathJax)](#mathlatex-rendering)
8. [Diagram Rendering (Mermaid.js)](#diagram-rendering)
9. [Path Cleaning & Sanitization](#path-cleaning--sanitization)
10. [Post-Render Actions](#post-render-actions)
11. [Cutoff & Continue Generation](#cutoff--continue-generation)
12. [Error Handling](#error-handling)
13. [Helper Functions Reference](#helper-functions-reference)
14. [HTML Rendering & Display Logic](#html-rendering--display-logic)
15. [Table Rendering Design](#table-rendering-design)
16. [Code Block Design System](#code-block-design-system)

---

## Architecture Overview

```
User sends message
       ↓
sendMessage() — Main entry point
       ↓
fetch() SSE stream to Django backend
       ↓
Stream chunks arrive (SSE format)
       ↓
┌──────────────────────────────────────┐
│  Per-chunk processing:               │
│  A) reasoning_content → <details>    │
│  B) content → aiFullText accumulator │
│  C) done → finalize                  │
└──────────────────────────────────────┘
       ↓
formatMessage(aiFullText) — Core renderer
       ↓
detectContentType() → Route to specialized renderer
       ↓
DOM update + MathJax + Mermaid + hljs
       ↓
Post-render: Copy/Export/Continue buttons
```

**Key difference from Cortex desktop:**
- `chat.html` uses **HTTP fetch/SSE** to Django backend
- `aichat.html` uses **QWebChannel bridge** to PyQt6 Python

---

## Streaming Pipeline

### sendMessage() — Main Function (line ~5800)

The `sendMessage()` function handles the entire streaming lifecycle:

```javascript
async function sendMessage() {
    // 1. Input validation & UI setup
    // 2. Create AbortController for cancellation
    // 3. Build request payload (model, messages, deep research flag)
    // 4. fetch() to Django SSE endpoint
    // 5. Process SSE stream chunks
    // 6. Finalize rendering
}
```

### Stream Chunk Processing (lines ~5900-6080)

Each SSE chunk is parsed and dispatched:

```javascript
// A) Reasoning/Thinking Content
if (payload.reasoning_content) {
    reasoningFullText += payload.reasoning_content;
    // Display in collapsible <details> element
    // Basic HTML escape + line break preservation
    const safeReasoning = reasoningFullText
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
    reasoningTextSpan.innerHTML = safeReasoning;
}

// B) Main Content — Throttled Markdown rendering
if (payload.content) {
    aiFullText += payload.content;

    // PERFORMANCE: Throttle to max 10 renders/sec
    const now = Date.now();
    if (now - lastRenderTime > 100) {
        lastRenderTime = now;
        const formattedHtml = formatMessage(aiFullText);
        contentDiv.innerHTML = formattedHtml + cursorSpan;

        // Real-time MathJax processing
        requestAnimationFrame(() => {
            MathJax.typesetPromise([contentDiv]).catch(e => {});
        });
    }
}

// C) Done Signal
if (payload.done) {
    if (payload.final_text && payload.final_text.trim().length > 0) {
        aiFullText = payload.final_text;  // Use backend's cleaned version
    }
}
```

### Final Render (lines ~6081-6102)

After stream ends:

```javascript
// 1. Remove typing cursor
document.getElementById('typing-cursor')?.remove();

// 2. Final Markdown render
contentDiv.innerHTML = formatMessage(aiFullText);

// 3. Final MathJax typeset (critical for complete rendering)
MathJax.typesetPromise([contentDiv]);

// 4. Final Mermaid diagram render
renderMermaidDiagrams(contentDiv);
```

---

## formatMessage() — Core Rendering Engine

**Location:** Line 6810
**Signature:** `function formatMessage(text, isUser = false)`

This is the **heart of AI content rendering**. It:

1. Cleans broken Windows paths
2. Detects content type
3. Routes to specialized renderer OR falls through to marked.js
4. Returns fully formatted HTML string

```javascript
function formatMessage(text, isUser = false) {
    if (!text) return '';

    // Step 1: Clean corrupt Windows paths (AI output artifact)
    if (!isUser) {
        text = cleanBrokenWindowsPaths(text);
    }

    // Step 2: User messages — simple HTML escape + line breaks
    if (isUser) {
        msgMarkdown = escapeHtml(msgMarkdown);
        return `<p>${msgMarkdown.replace(/\n/g, '<br>')}</p>`;
    }

    // Step 3: Detect content type for AI messages
    const contentType = detectContentType(msgMarkdown);

    // Step 4: Route to specialized renderer
    // (email, whatsapp, social, creative, accounting, equation, calculation)
    // OR fall through to standard marked.js rendering

    // Step 5: Standard rendering via marked.js
    let htmlContent = marked.parse(msgMarkdown);
    // Post-process: clean URLs, add target="_blank", etc.
    return htmlContent;
}
```

---

## Content Type Detection

**Function:** `detectContentType(text)` (line ~6750)

Analyzes AI response text to determine if it needs specialized rendering:

| Type | Detection Criteria | Renderer |
|------|-------------------|----------|
| `email` | Subject/To/From/Dear/Regards patterns | Email wrapper with copy |
| `whatsapp` | WhatsApp-style formatting cues | WhatsApp green wrapper |
| `social` | Hashtags, @mentions, social patterns | Blue social wrapper |
| `creative` | Story/poem/narrative patterns | Serif font creative wrapper |
| `accounting` | Currency, balance, debit/credit patterns | Monospace finance wrapper |
| `equation` | Pure LaTeX/math expressions | MathJax equation wrapper |
| `calculation` | Step-by-step math work | Calculation wrapper |
| `default` | None of the above | Standard marked.js |

---

## Specialized Content Renderers

### Email Renderer (lines 6830-6894)

```javascript
// Separates email body from citation references
// Strips Markdown bold/italic artifacts for clean email text
// Auto-links URLs with target="_blank"
// Renders citations separately below the email box

Output HTML structure:
<div class="code-block-container email-wrapper">
    <div class="code-header">
        <span class="code-lang">📧 EMAIL DRAFT</span>
        <button class="copy-code-btn">Copy</button>
    </div>
    <div class="email-content-display">
        {cleaned, linked email text}
    </div>
</div>
<div class="email-citations">
    {rendered citation references}
</div>
```

### WhatsApp Renderer (lines 6895-6911)

```javascript
// Renders WhatsApp-style *bold* formatting
// Light background (#e5ddd5) with dark text

Output HTML structure:
<div class="code-block-container whatsapp-wrapper">
    <div class="code-header" style="background: #075e54;">
        <span class="code-lang">💬 WHATSAPP / MESSAGE</span>
    </div>
    <div class="whatsapp-display" style="background: #e5ddd5; color: #111;">
        {formatted text with *bold* support}
    </div>
</div>
```

### Social Post Renderer (lines 6912-6947)

```javascript
// Full marked.js rendering for hashtags, links, bold
// Blue header (#1da1f2) style

Output HTML structure:
<div class="code-block-container social-wrapper">
    <div class="code-header" style="background: #1da1f2;">
        <span class="code-lang"># SOCIAL POST</span>
    </div>
    <div class="social-display">
        {full markdown rendered content}
    </div>
</div>
```

### Creative Writing Renderer (lines 6948-6969)

```javascript
// Full marked.js rendering (headings, bold, italic, etc.)
// Serif font (Georgia), larger line-height for readability

Output HTML structure:
<div class="code-block-container creative-wrapper">
    <div class="code-header">
        <span class="code-lang">📖 CREATIVE WRITING</span>
    </div>
    <div class="creative-display" style="font-family: Georgia, serif; line-height: 1.8;">
        {full markdown rendered content}
    </div>
</div>
```

### Accounting/Finance Renderer (lines 6970-6986)

```javascript
// Escapes $ symbols to prevent MathJax interference
// Monospace font (Consolas) for numeric alignment

Output HTML structure:
<div class="code-block-container accounting-wrapper">
    <div class="code-header">
        <span class="code-lang">💰 ACCOUNTING / FINANCE</span>
    </div>
    <div class="accounting-display" style="font-family: Consolas, monospace;">
        {escaped text with preserved line breaks}
    </div>
</div>
```

### Equation Renderer (lines 6987-7005)

```javascript
// Sanitizes TeX, auto-wraps in $$ delimiters if missing
// MathJax renders the equation

Output HTML structure:
<div class="code-block-container equation-wrapper">
    <div class="code-header">
        <span class="code-lang">📐 EQUATION</span>
    </div>
    <div class="equation-display">
        {$$sanitized_latex$$}
    </div>
</div>
```

### Calculation Renderer (lines 7006+)

```javascript
// Step-by-step math work display
// Preserves calculation steps with clear formatting
```

---

## Code Block Rendering

### marked.js Custom Renderer (lines 182-246)

The `renderer.code` function intercepts ALL code blocks from Markdown:

```javascript
renderer.code = function(code, language) {
    // Handle marked v4 object form: { text, lang }
    let codeText, langRaw;
    if (code && typeof code === 'object') {
        codeText = code.text ?? '';
        langRaw = code.lang ?? language;
    } else {
        codeText = String(code ?? '');
        langRaw = language;
    }
    const lang = (langRaw || 'text').toLowerCase();

    // Route 1: MERMAID diagrams
    if (lang === 'mermaid') {
        return `<div class="mermaid-wrapper">
            <div class="mermaid-header">Architecture Diagram</div>
            <div class="mermaid-container" data-mermaid-pending="true" data-mermaid-code="${enc}">
                <div class="mermaid-loading">Rendering diagram...</div>
            </div>
        </div>`;
    }

    // Route 2: MATH/LATEX
    if (lang === 'math' || lang === 'latex' || lang === 'tex') {
        return `<div class="math-display" data-math-pending="true">$$${mathCode}$$</div>`;
    }

    // Route 3: Regular code blocks
    // Clean markdown fence artifacts
    codeText = codeText.replace(/^```[a-z]*\s*\n?/i, '').replace(/\n?```\s*$/i, '');

    // Highlight with hljs
    const validLang = hljs.getLanguage(lang) ? lang : 'plaintext';
    processedCode = hljs.highlight(cleanCode, { language: validLang }).value;

    return `<div class="code-block-container">
        <div class="code-header">
            <span class="code-lang">${lang.toUpperCase()}</span>
            <button class="copy-code-btn" onclick="copyCode(this)">Copy</button>
        </div>
        <pre><code class="language-${lang} hljs">${processedCode}</code></pre>
    </div>`;
};

marked.setOptions({ renderer: renderer, breaks: true, gfm: true });
```

---

## Math/LaTeX Rendering

### MathJax Configuration (lines 76-101)

```javascript
window.MathJax = {
    options: {
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
        ignoreHtmlClass: 'no-mathjax|file-path'
    },
    tex: {
        inlineMath: [['$', '$'], ['\\(', '\\)']],
        displayMath: [['$$', '$$'], ['\\[', '\\]']],
        processEscapes: true,
        packages: { '[+]': ['ams', 'noerrors', 'noundefined'] },
        tags: 'ams'
    },
    svg: { fontCache: 'global' },
    chtml: { scale: 1.15, minScale: 0.6, matchFontHeight: true }
};
```

### Rendering Flow

1. **During streaming:** `requestAnimationFrame(() => MathJax.typesetPromise([contentDiv]))` — throttled with content updates
2. **After stream ends:** `MathJax.typesetPromise([contentDiv])` — final complete render
3. **LaTeX code blocks** (` ```math `, ` ```latex `): Rendered via MathJax instead of hljs
4. **Equation content type:** Auto-wrapped in `$$` delimiters before typesetting

### TeX Sanitization

```javascript
function sanitizeTeX(latex) {
    // Balance unclosed braces so MathJax doesn't choke
    // e.g., "\sum_{i" → "\sum_{i\cdots}"
}

function balanceBraces(latex) {
    let depth = 0;
    for (let i = 0; i < latex.length; i++) {
        if (latex[i] === '\\') { i++; continue; }  // skip escaped chars
        if (latex[i] === '{') depth++;
        else if (latex[i] === '}') depth--;
    }
    if (depth > 0) {
        latex += '\\cdots' + '}'.repeat(depth);
    }
    return latex;
}

function escapeCurrencyDollars(text) {
    // Escape $ in accounting text to prevent MathJax interference
    // e.g., "$1,000" → "\$1,000"
}
```

---

## Diagram Rendering

### Mermaid.js Configuration (lines 106-143)

```javascript
mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    themeVariables: {
        primaryColor: '#D4622B',        // Brand orange
        primaryTextColor: '#fff',
        primaryBorderColor: '#e8773d',
        lineColor: '#888',
        secondaryColor: '#1a1a2e',
        tertiaryColor: '#16213e',
        fontFamily: '"Inter", "Segoe UI", sans-serif',
        fontSize: '13px'
    },
    securityLevel: 'loose',
    flowchart: { curve: 'basis', padding: 10, htmlLabels: true }
});
```

### renderMermaidDiagrams() (lines 146-173)

```javascript
async function renderMermaidDiagrams(parentEl) {
    const containers = parentEl.querySelectorAll('.mermaid-container[data-mermaid-pending]');
    for (const container of containers) {
        const code = container.getAttribute('data-mermaid-code');
        const diagramId = 'mermaid-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        try {
            const { svg } = await mermaid.render(diagramId, code);
            container.innerHTML = svg;
            container.removeAttribute('data-mermaid-pending');
            container.classList.add('mermaid-rendered');
            // Make SVG responsive
            svgEl.style.maxWidth = 'min(100%, 700px)';
            svgEl.style.height = 'auto';
            svgEl.style.maxHeight = '460px';
        } catch (err) {
            // Fallback: show raw code
            container.innerHTML = `<pre class="mermaid-error"><code>${escapeHtml(code)}</code></pre>
                <div class="mermaid-error-msg">Diagram render failed</div>`;
        }
    }
}
```

### Mermaid Actions

- **Copy:** `copyMermaidCode(btn)` — Copies raw mermaid source code
- **Download SVG:** `downloadMermaidSVG(btn)` — Exports rendered diagram as `.svg` file

---

## Path Cleaning & Sanitization

### cleanBrokenWindowsPaths() (lines 6632-6695)

AI models often output fragmented Windows paths. This function fixes them:

```javascript
function cleanBrokenWindowsPaths(text) {
    // Step 0: Hide fenced code blocks and inline code (don't modify code)
    //   Replace ```...``` and `...` with placeholders

    // Step 1: Fix "C : \" gaps → "C:\"
    t = t.replace(/([A-Z])\s+:\s+\\/g, '$1:\\');

    // Step 2: Fix fragmented paths "\ P ath \ T o" → "\Path\To"
    t = t.replace(/\\([A-Z])\s+([a-z]+)/g, '\\$1$2');

    // Step 3: Fix fragmented filenames "L astD ay" → "LastDay"
    t = t.replace(/([a-zA-Z]:\\[\w\s\\.]+)/g, (match) => {
        return match.replace(/([A-Z])\s+([a-z]{2,})/g, '$1$2')
            .replace(/([a-z])\s+([a-z]{3,})/g, '$1$2');
    });

    // Step 4: Wrap file paths in backticks: C:\Path\To\File.ext
    t = t.replace(/(?<!`)\b([a-zA-Z]:\\[\w\\.]+\.\w+)\b(?!`)/g, '`$1`');

    // Step 5: Wrap directory paths (no extension) in backticks
    t = t.replace(/(?<!`)\b([a-zA-Z]:\\(?:[\w.-]+\\){1,}[\w.-]+)\b(?!`)/g, '`$1`');

    // Step 5b: Wrap env var paths: %SystemRoot%\Temp
    t = t.replace(/(%[a-zA-Z]+%\\[\w.-]+)/g, '`$1`');

    // Step 6: Wrap Unix paths: /home/user/path (skip URLs)
    t = t.replace(/(\/(?:[\w.-]+\/){1,}[\w.-]+)/g, function(match, path, offset, fullStr) {
        const before = fullStr.substring(Math.max(0, offset - 200), offset);
        if (/https?:\/\/\S*$/.test(before)) return match;  // Inside URL — skip
        return '`' + path + '`';
    });

    // Final: Restore hidden code blocks from placeholders
    return t;
}
```

---

## Post-Render Actions

### Action Buttons (lines 6106-6130)

After AI response completes, these buttons are added:

```javascript
const actionsHtml = `
    <button class="msg-action-btn" onclick="copyMessage(this)">Copy</button>
    <button class="msg-action-btn word" onclick="exportSingleMessage(this, 'word')">Word</button>
    <button class="msg-action-btn md" onclick="exportSingleMessage(this, 'md')">MD</button>
`;
```

- **Copy** — Copies raw message text to clipboard
- **Word** — Exports as `.docx` via html2pdf.js
- **MD** — Exports as `.md` Markdown file

### Token Usage Display (lines 6000-6009)

```javascript
if (payload.usage) {
    const inTokens = payload.usage.prompt_tokens || 0;
    const outTokens = payload.usage.completion_tokens || 0;
    inputDisplay.textContent = inTokens.toLocaleString();
    outputDisplay.textContent = outTokens.toLocaleString();
}
```

---

## Cutoff & Continue Generation

### Detection (lines 6119-6128)

```javascript
// If AI hit max token limit, show continue button
if (finishReason === 'length' || finishReason === 'max_tokens') {
    actionsHtml += `
        <button class="msg-action-btn continue-btn" onclick="continueGeneration(this)">
            <i class="fas fa-forward"></i> Continue
        </button>
    `;
    // Visual indicator
    contentDiv.innerHTML += `<div class="text-warning">
        <i class="fas fa-cut"></i> Content truncated. Click "Continue" to finish.
    </div>`;
}
```

### continueGeneration() (lines 6179-6189)

```javascript
function continueGeneration(btn) {
    if (btn) btn.remove();                    // Remove button to prevent double-click
    chatInput.value = "continue";             // Set input to "continue"
    sendMessage();                            // Re-send with context
}
```

### stopGeneration() (lines 6192+)

```javascript
function stopGeneration() {
    if (chatAbortController) {
        chatAbortController.abort();           // Cancel the fetch stream
    }
    // Remove optimistic user message from UI
}
```

---

## Error Handling

### Stream Error Handling (lines 6147-6175)

```javascript
try {
    // ... streaming logic ...
} catch (error) {
    stopDeepResearchAnimation();
    document.getElementById('loadingDots')?.remove();

    if (error.name === 'AbortError') {
        console.log('Chat generation stopped by user');
    } else {
        // Remove failed guest message from history
        if (!IS_AUTHENTICATED) {
            guestHistory.pop();
            localStorage.setItem('guest_history', JSON.stringify(guestHistory));
        }
        // Show error bubble in chat
        chatMessages.innerHTML += `
            <div class="message-bubble">
                <div class="message-content" style="border-color: #ff6b6b;">
                    <i class="fas fa-exclamation-triangle"></i>
                    ${error.message || 'Network error. Please try again.'}
                </div>
            </div>
        `;
    }
} finally {
    isLoading = false;
    chatAbortController = null;
    document.getElementById('sendBtn').style.display = 'flex';
    document.getElementById('stopBtn').style.display = 'none';
}
```

---

## Helper Functions Reference

| Function | Line | Purpose |
|----------|------|---------|
| `formatMessage(text, isUser)` | 6810 | Core rendering engine — routes to specialized renderers |
| `detectContentType(text)` | ~6750 | Classifies AI response (email, social, equation, etc.) |
| `escapeHtml(text)` | 7261 | HTML entity escaping via DOM textContent |
| `escapeHtmlForCode(text)` | 6614 | Simple string-based HTML escape for code blocks |
| `escapeCurrencyDollars(text)` | ~6720 | Escapes `$` to `\$` for accounting content |
| `sanitizeTeX(latex)` | ~6989 | Cleans LaTeX for MathJax consumption |
| `balanceBraces(latex)` | 6699 | Closes unclosed `{` in truncated LaTeX |
| `cleanBrokenWindowsPaths(text)` | 6632 | Fixes fragmented Windows/Unix paths from AI output |
| `renderInlineCode(tokenData)` | 6624 | Renders `inline code` spans |
| `copyCode(btn)` | 7361 | Copies code block content to clipboard |
| `copyMermaidCode(btn)` | 7380 | Copies mermaid diagram source |
| `downloadMermaidSVG(btn)` | 7398 | Downloads mermaid diagram as SVG |
| `copyMessage(btn)` | ~7340 | Copies full message text |
| `exportSingleMessage(btn, format)` | ~7410 | Exports message as Word/MD |
| `continueGeneration(btn)` | 6179 | Continues truncated AI response |
| `stopGeneration()` | 6192 | Aborts streaming via AbortController |
| `renderMermaidDiagrams(parentEl)` | 146 | Renders all pending mermaid diagrams |
| `updateModelSelectStyle(sel)` | 3989 | Updates model selector visual state |
| `toggleDeepResearch()` | 4278 | Toggles deep research mode |
| `animateDeepResearchStatus()` | 4293 | Animates research progress steps |
| `showErrorModal(message)` | 4358 | Shows Bootstrap error modal |
| `showGuestLimitModal()` | 4364 | Shows guest message limit modal |

---

## HTML Rendering & Display Logic

### Normal Content Rendering Pipeline (lines 7073-7257)

When `detectContentType()` returns `default`, the full marked.js pipeline runs:

```javascript
// STEP 0: Fix broken URLs — AI wraps URLs in backticks
// e.g. [Title](`https://example.com`) → [Title](https://example.com)
msgMarkdown = cleanMarkdownUrls(msgMarkdown);

// STEP 1: Protect all math from marked.js
let protectedMarkdown = protectMath(msgMarkdown);

// STEP 2: Parse with marked.js (custom renderer)
htmlContent = marked.parse(protectedMarkdown);

// STEP 3: Restore math after markdown processing
htmlContent = restoreMath(htmlContent);

// STEP 4: Fix LaTeX inside <code> tags (MathJax skips <code>)
htmlContent = fixLatexInCodeTags(htmlContent);

// STEP 5: Add target="_blank" to all links
htmlContent = htmlContent.replace(/<a href=/g, '<a target="_blank" href=');

// STEP 6: Fix backtick-corrupted URLs in rendered <a> tags
htmlContent = cleanRenderedUrls(htmlContent);

// STEP 7: Extract GitHub repo cards from table rows
// Pattern: | PROJECT | name | desc | install_cmd | snippet |
repoItems.forEach(item => {
    htmlContent = htmlContent.replace(repoRegex, cardHtml);
});
```

### Math Protection Pipeline — protectMath() (lines 6409-6583)

**Critical:** marked.js destroys LaTeX syntax (`\sum`, `_`, `^`). Math must be hidden before parsing and restored after.

```javascript
function protectMath(text) {
    // FIX 0: Ensure $$ has whitespace separation
    // AI: "Formula:$$ x=1 $$" → "Formula:\n\n$$\n\nx=1 $$"
    text = text.replace(/([^\s$])\$\$/g, (_, g1) => g1 + '\n\n$$');
    text = text.replace(/\$\$([^\s$])/g, (_, g1) => '$$\n\n' + g1);

    // FIX 1: Close unclosed $$ blocks (AI truncation)
    // Count $$ — if odd, auto-close the last orphaned opening $$
    const ddCount = (text.match(/\$\$/g) || []).length;
    if (ddCount % 2 === 1) {
        // Insert closing $$ after next newline
    }

    // Hide Code Blocks FIRST (so their $variables aren't touched)
    // 1. Fenced code blocks: ```...``` → <!--PH_CODE_0-->
    // 2. Inline code: `...` → <!--PH_CODE_1-->

    // Protect bare Windows paths (backslashes = LaTeX to MathJax)
    // C:\Users\Name\file.js → `C:\Users\Name\file.js`
    // %UserProfile%\AppData → `%UserProfile%\AppData`

    // Protect Display Math ($$...$$) → <!--LPTOKEN:MATHDISP:0-->
    // Protect Inline Math ($...$) → <!--LPTOKEN:MATHINLINE:1-->

    // Detect LaTeX commands in prose (e.g., \sum_{i=1}^{n})
    // Complex regex with English word lookahead to avoid wrapping prose
    // Skips Windows dir names: \AppData, \Windows, \System32, etc.

    // Restore Code Blocks
    codePlaceholders.forEach((code, id) => {
        processed = processed.replace(`<!--PH_CODE_${id}-->`, () => code);
    });

    return processed;
}
```

### Math Restoration — restoreMath()

After marked.js processes the protected markdown:

```javascript
function restoreMath(htmlContent) {
    // Replace each <!--LPTOKEN:MATHDISP:N--> with $$content$$
    // Replace each <!--LPTOKEN:MATHINLINE:N--> with $content$
    // MathJax will then typeset these on next typesetPromise() call
}
```

### fixLatexInCodeTags() — LaTeX Inside `<code>`

marked.js sometimes wraps LaTeX in `<code>` tags. MathJax **skips** `<code>` elements by config. This function extracts LaTeX from `<code>` wrappers:

```javascript
// Before: <code>\sum_{i=1}^{n} x_i</code>
// After:  \sum_{i=1}^{n} x_i  (raw, MathJax can process)
```

### cleanMarkdownUrls() — Fix AI URL Artifacts

AI models often wrap URLs in backticks inside markdown links:

```javascript
// Fix: [Title](`https://example.com`) → [Title](https://example.com)
// Fix: [`Title`](`url`) → [Title](url)
// Fix: bare `https://url` in text → https://url
```

### cleanRenderedUrls() — Fix Rendered URL Artifacts

After marked.js renders, backtick artifacts may persist in `<a>` href attributes:

```javascript
// Fix: <a href="`https://example.com`"> → <a href="https://example.com">
// Fix: <a href="https://example.com`"> → <a href="https://example.com">
```

### GitHub Repo Card Extraction (lines 7233-7255)

AI responses containing repo tables get converted to styled cards:

```javascript
// Pattern: | PROJECT | name | desc | install_cmd | snippet |
// Extracted into repoItems array, then rendered as:

<div class="repo-container">
    <div class="repo-header">
        <span class="repo-id">{id}</span>
        <span class="repo-name">{name}</span>
    </div>
    <div class="repo-desc">{description}</div>
    <div class="repo-section-title">Installation</div>
    <pre class="repo-pre"><code>{install_cmd}</code></pre>
    <div class="repo-section-title">Usage / Example</div>
    <pre class="repo-pre"><code>{snippet}</code></pre>
</div>
```

---

## Table Rendering Design

### Custom Table Renderer (lines 4546-4591 & 7165-7200)

marked.js `renderer.table` is overridden to add responsive wrapping and cleanup:

```javascript
renderer.table = function(header, body) {
    let tableHtml = '';

    // Handle marked v4+ (header can be object or string)
    if (typeof header === 'string') {
        tableHtml = `<table><thead>${header}</thead><tbody>${body}</tbody></table>`;
    } else {
        // Use default renderer for token objects
        tableHtml = marked.Renderer.prototype.table.call(this, header, body);
    }

    // CLEANUP: Remove spacer/empty rows (AI sometimes generates empty table rows)
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = tableHtml;
    const rows = tempDiv.querySelectorAll('tr');
    rows.forEach((row, index) => {
        if (index === 0) return;  // Skip header row
        const text = (row.textContent || '').trim();
        const hasData = /[a-zA-Z0-9\u00C0-\u017F]/.test(text);
        if (!hasData && text.length > 0) {
            row.remove();  // Remove empty spacer rows
        }
    });
    tableHtml = tempDiv.innerHTML;

    // Wrap in scrollable container for responsiveness
    return `<div class="table-wrapper">${tableHtml}</div>`;
};
```

### Table CSS Design System (lines 1742-1865)

#### Container — `.table-wrapper`

```css
.table-wrapper {
    width: 100%;
    overflow-x: auto;                    /* Horizontal scroll on narrow screens */
    -webkit-overflow-scrolling: touch;    /* Smooth scroll on iOS */
    margin: 20px 0;
    border-radius: 10px;
    border: 1px solid rgba(102, 126, 234, 0.2);  /* Indigo border */
    scrollbar-width: thin;
    scrollbar-color: rgba(102, 126, 234, 0.5) transparent;
}

.table-wrapper::-webkit-scrollbar { height: 4px; }
.table-wrapper::-webkit-scrollbar-thumb {
    background: rgba(102, 126, 234, 0.5);
    border-radius: 10px;
}
```

#### Table — `.message-content table`

```css
.message-content table {
    display: table;
    width: 100%;
    min-width: 500px;                    /* Forces horizontal scroll on mobile */
    border-collapse: separate;           /* Enables rounded corners */
    border-spacing: 0;
    font-size: 14px;
    table-layout: auto;                  /* Content-driven column widths */
    background: rgba(30, 41, 59, 0.5);  /* Slate background */
    border: 1px solid rgba(102, 126, 234, 0.2);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}
```

#### Cells — `th` / `td`

```css
.message-content th,
.message-content td {
    padding: 14px 18px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    border-right: 1px solid rgba(255, 255, 255, 0.05);
    text-align: left;
    vertical-align: top;
    white-space: normal;                 /* Allow wrapping */
    word-break: normal;                  /* Don't break words */
    overflow-wrap: break-word;           /* Only break long unbroken strings */
    line-height: 1.6;
    min-width: 100px;                    /* Prevent column collapse */
    transition: all 0.2s ease;
}
```

#### Header — `th`

```css
.message-content th {
    background: rgba(102, 126, 234, 0.2) !important;  /* Indigo tint */
    color: #a5b4fc;                                     /* Light indigo text */
    font-weight: 700;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 1px;
    border-bottom: 2px solid rgba(102, 126, 234, 0.3) !important;
}
```

#### Zebra Striping & Hover

```css
/* Hover highlight */
.message-content tr:hover td {
    background: rgba(102, 126, 234, 0.08);  /* Subtle indigo on hover */
}

/* Even row tinting */
.message-content tbody tr:nth-child(even) {
    background: rgba(255, 255, 255, 0.02);
}
```

#### Column Width Strategy

```css
/* First column — labels/keys (bold, wider) */
.message-content th:first-child,
.message-content td:first-child {
    font-weight: 600;
    color: #e2e8f0;
    min-width: 120px;
}

/* Second column — descriptions */
.message-content td:nth-child(2) {
    min-width: 150px;
}

/* Last column — often code/commands (most space) */
.message-content td:last-child {
    min-width: 200px;
}
```

#### Code Inside Tables

```css
.message-content td code {
    padding: 4px 10px !important;
    border-radius: 4px !important;
    font-family: 'Fira Code', monospace !important;
    border: 1px solid rgba(59, 130, 246, 0.2) !important;
    display: inline-block;
    margin: 2px 0;
    font-size: 12.5px !important;
}
```

#### Edge Cleanup

```css
/* Remove bottom border from last row */
.message-content tr:last-child td { border-bottom: none; }

/* Remove right border from last column */
.message-content tr td:last-child { border-right: none; }
```

#### Assistant Bubble Expansion for Tables

```css
/* Tables need full width — override the 85% max-width */
.message-bubble.assistant:has(table) {
    max-width: 100%;
}
```

---

## Code Block Design System

### HTML Structure (3 Renderer Instances)

Code blocks are rendered by **3 separate** `renderer.code` definitions in chat.html:

| Instance | Location | Purpose |
|----------|----------|---------|
| Renderer 1 | Lines 182-246 | DOMContentLoaded head config |
| Renderer 2 | Lines 4502-4542 | `configureMarked()` — main runtime |
| Renderer 3 | Lines 7089-7162 | `formatMessage()` default route |

All produce the same HTML structure:

```html
<div class="code-block-container">
    <div class="code-header">
        <span class="code-lang">PYTHON</span>
        <button class="copy-code-btn" onclick="copyCode(this)">
            <i class="fas fa-copy"></i> Copy
        </button>
    </div>
    <pre><code class="language-python hljs">{highlighted code}</code></pre>
</div>
```

### Code Block CSS Design (lines 497-573)

#### Container — `.code-block-container`

```css
.code-block-container {
    background: #0d1117;              /* GitHub dark bg */
    border-radius: 8px;
    margin: 1.5rem 0;
    overflow: hidden;
    border: 1px solid #30363d;       /* GitHub border */
}
```

#### Header — `.code-header`

```css
.code-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #161b22;              /* Slightly lighter than body */
    padding: 8px 16px;
    border-bottom: 1px solid #30363d;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 0.8rem;
    color: #8b949e;
}
```

#### Language Label — `.code-lang`

```css
.code-lang {
    font-weight: 600;
    color: #c9d1d9;                   /* Bright grey — stands out */
}
```

#### Copy Button — `.copy-code-btn`

```css
.copy-code-btn {
    background: transparent;
    border: none;
    color: #8b949e;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.8rem;
    padding: 4px 8px;
    border-radius: 4px;
    transition: all 0.2s;
}

.copy-code-btn:hover {
    color: #58a6ff;                   /* GitHub blue */
    background: rgba(88, 166, 255, 0.1);
}

.copy-code-btn.copied {
    color: #3fb950;                   /* GitHub green */
}

.copy-code-btn.copied i {
    color: #3fb950;
}
```

#### Pre/Code Body

```css
.code-block-container pre {
    margin: 0;
    padding: 16px;
    overflow-x: auto;
    background: #0d1117 !important;
    border-radius: 0 0 8px 8px;
    white-space: pre !important;      /* Preserve indentation */
}

.code-block-container code.hljs {
    background: transparent !important;  /* No double bg */
    padding: 0;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 14.5px;                  /* Industry standard (OpenAI/DeepSeek) */
    line-height: 1.6;
    white-space: pre !important;
    word-wrap: normal !important;       /* Don't break words */
}
```

### Code Block Rendering Flow

```
AI outputs: ```python\ndef hello():\n    print("hi")\n```
       │
       ↓
renderer.code() intercepts
       │
       ├─ Is it mermaid? → Mermaid diagram wrapper
       ├─ Is it math/latex/tex? → MathJax $$ wrapper
       └─ Regular code:
              │
              ↓
        Clean fence artifacts:
        codeText.replace(/^```[a-z]*\s*\n?/i, '')
        codeText.replace(/\n?```\s*$/i, '')
              │
              ↓
        Highlight with hljs:
        hljs.getLanguage(lang)
          ? hljs.highlight(code, { language: lang })
          : hljs.highlightAuto(code)
              │
              ↓
        Generate HTML:
        <div class="code-block-container">
          <div class="code-header">
            <span class="code-lang">PYTHON</span>
            <button class="copy-code-btn">Copy</button>
          </div>
          <pre><code class="language-python hljs">
            {syntax-highlighted HTML}
          </code></pre>
        </div>
```

### Inline Code Rendering

```javascript
function renderInlineCode(tokenData) {
    const code = tokenData.code || '';
    const escaped = escapeHtmlForCode(code);
    return `<code class="inline-code">${escaped}</code>`;
}
```

Inline code CSS (in base styles):

```css
code.inline-code {
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Fira Code', monospace;
    background: rgba(255, 255, 255, 0.1);
    font-size: 0.9em;
}
```

### Copy Code Logic — copyCode() (lines 7361-7377)

```javascript
function copyCode(btn) {
    // 1. Find closest .code-block-container
    const container = btn.closest('.code-block-container');
    const codeEl = container.querySelector('code');
    const text = codeEl.innerText || codeEl.textContent;

    // 2. Copy to clipboard
    navigator.clipboard.writeText(text).then(() => {
        // 3. Visual feedback: "Copy" → "Copied!" (green)
        btn.classList.add('copied');
        btn.innerHTML = '<i class="fas fa-check"></i> Copied!';

        // 4. Revert after 2 seconds
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = '<i class="fas fa-copy"></i> Copy';
        }, 2000);
    });
}
```

### Universal Content Copy — copyContent() (lines 7342-7358)

Used by specialized renderers (email, whatsapp, etc.) that have an `id` on their content div:

```javascript
function copyContent(elementId, btn) {
    const el = document.getElementById(elementId);
    const text = el.innerText || el.textContent;
    navigator.clipboard.writeText(text).then(() => {
        btn.classList.add('copied');
        btn.innerHTML = '<i class="fas fa-check"></i> Copied!';
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = originalContent;
        }, 2000);
    });
}
```

### Code Block White-space Preservation (lines 1566-1590)

Critical CSS overrides to prevent code wrapping/indentation loss:

```css
pre code,
pre code.hljs,
.code-block-container pre code,
.code-block-container code,
.message-content .code-block-container pre code,
.chat-page .message-content pre code {
    white-space: pre !important;       /* Preserve ALL whitespace */
    word-wrap: normal !important;      /* Don't wrap long lines */
}

pre,
.code-block-container pre,
.message-content pre,
.message-content .code-block-container pre {
    white-space: pre !important;
    word-wrap: normal !important;
    overflow-wrap: normal !important;
}
```

### Code Inside Tables

Tables with code cells get special styling:

```css
.message-content td code {
    padding: 4px 10px !important;
    border-radius: 4px !important;
    font-family: 'Fira Code', monospace !important;
    border: 1px solid rgba(59, 130, 246, 0.2) !important;
    display: inline-block;
    margin: 2px 0;
    font-size: 12.5px !important;      /* Smaller than standalone code */
}
```

---

## Rendering Pipeline Summary

```
AI Stream Chunk
       │
       ├─ reasoning_content ──→ <details><summary>Thinking</summary> escaped HTML
       │
       └─ content ──→ aiFullText accumulator
                         │
                    formatMessage(aiFullText)
                         │
                    cleanBrokenWindowsPaths()
                         │
                    detectContentType()
                         │
              ┌──────────┼──────────┐──────────┐──────────┐──────────┐──────────┐
              │          │          │          │          │          │          │
           email    whatsapp    social    creative   accounting  equation  default
              │          │          │          │          │          │          │
           Specialized wrappers with icons, copy buttons, themed styles
              │
           (default route)
              │
         marked.parse() ──→ renderer.code()
              │                      │
              │              ┌───────┼───────┐
              │              │       │       │
              │          mermaid   math/   regular
              │          diagram   latex   code
              │              │       │       │
              │          mermaid   $$..$$  hljs.highlight()
              │          render    MathJax  + copy btn
              │              │       │       │
              └──────────────┴───────┴───────┘
                             │
                        DOM Update
                             │
                    ┌────────┼────────┐
                    │        │        │
               MathJax   Mermaid   Action
              typeset    render   buttons
              Promise   Diagrams  (Copy/Word/MD/Continue)
```
