# Cortex IDE — AI Chat Frontend Enhancement Plan v2
### Based on Full Codebase Audit (aichat.html · style.css · features.css · script.js · syntax-highlighting.css · model_selector.css · permission_support.js)

---

## 0. What Was Actually Read & Found

All 7 files were fully read before writing this plan. Key findings that differ from assumptions:

- `aichat.html` contains **~1800 lines of inline `<style>`** covering: `.permission-card`, `.ai-activity-panel`, `.message-bubble`, `.stop-btn`, `.thinking-*`, `.code-completion-*`, `.inline-diff-*`, `.toolbar-btn`, `.terminal-inline-*` — all of these must move to CSS files
- `script.js` line 7877: terminal cards are built with `isExpanded = true` (default expanded) — **must change to collapsed**
- `script.js` line 9328+: `toggleTerminalToolCard()` sets `scrollable.style.display = 'block'` on expand — no height cap, needs CSS enforcement
- Two distinct terminal card systems coexist: **`.tool-operation-card.terminal`** (new, used in `buildTerminalCard()`) and **`.term-card`** (legacy, still used in `buildTerminalCommandCard()` around line 8504) — both need the 40px restriction
- `.ai-activity-panel` + `simulateAIActivity()` + `initAIActivityPanel()` — mock data panel with duplicate CSS defined twice in the inline styles (literally copy-pasted twice starting at lines ~490 and ~530)
- `features.css` has `.pulse-timer`, `.status-tag`, `.text-add/.text-mod/.text-del`, `.list-row` all **declared twice** (once in the original card section, once in a "FILE OPERATION CARDS from new_aichat.html" section at the bottom)
- `syntax-highlighting.css` uses `!important` on `font-family` for all code elements — conflicts with any future font token changes
- `model_selector.css` is clean and self-contained — minimal changes needed
- `permission_support.js` functions (`grantPermission`, `denyPermission` etc.) are standalone but the full permission card HTML is a `<template>` in `aichat.html` — the two systems need to be aligned
- Icon system is split: tool operation cards in `script.js` use inline SVG strings; the HTML template uses inline SVGs; `features.css` uses CSS `content:` for some indicators; `aichat.html` inline styles use emoji for `.summary-icon`, `.section-icon`, `.item-icon`, `.tool-badge-icon`

---

## 1. Unified Design Token System

### 1.1 Consolidate `:root` Declarations

Currently there are **3 separate `:root` blocks**:
- `style.css` lines 1–38 (base tokens)
- `syntax-highlighting.css` lines 1–8 (font tokens only, conflicts with style.css)
- Dozens of inline `var()` calls referencing undefined variables like `--bg-tertiary`, `--border-secondary`, `--accent-green`, `--bg-secondary`, `--bg-color-1`, `--bg-color-2`, `--bg-color-3`, `--border-color`, `--text-main`, `--text-dim`, `--accent-primary`, `--green`, `--green-bright`, `--green-bg`, `--red`, `--red-bg`, `--yellow`

**Action:** Merge into one `:root` in `style.css`. Define every variable used anywhere. Remove the `:root` block from `syntax-highlighting.css` and import the shared tokens.

### 1.2 Complete Token Set

Replace all scattered hardcoded hex values with this single set:

```
/* Backgrounds */
--bg-void:      #0c0c0e
--bg-base:      #111113
--bg-surface:   #161618      ← matches current #161618 in features.css
--bg-elevated:  #1c1c1f      ← replaces #1e1e2e, #1a1a1a, #1a1a1e scattered values
--bg-float:     #222226      ← dropdowns, tooltips
--bg-hover:     #27272c
--bg-card:      #161618      ← unifies var(--bg-card) references
--bg-code:      #0a0a0a      ← terminal/code blocks

/* Borders */
--border:         rgba(255,255,255,0.06)   ← replaces #2a2a2a, rgba(255,255,255,0.07)
--border-light:   rgba(255,255,255,0.10)
--border-strong:  rgba(255,255,255,0.16)

/* Text */
--text-main:      #f0f0f2    ← replaces #e2e8f0, #f5f5f5, #e5e7eb
--text-primary:   #f0f0f2
--text-secondary: #9a9aa8    ← replaces #a0a0a8, #a3a3a3, #9ca3af
--text-dim:       #606068    ← replaces #6b7280, #777, #888
--text-faint:     #363640    ← replaces #444, #555

/* Accent */
--accent-primary: #63a0f6   ← replaces #3b82f6, #228df2 (unified blue)
--accent-dim:     rgba(99,160,246,0.12)
--accent-border:  rgba(99,160,246,0.28)

/* Semantic */
--green:          #22c55e
--green-bright:   #4ade80
--green-bg:       rgba(34,197,94,0.10)
--red:            #f87171
--red-bg:         rgba(248,113,113,0.10)
--yellow:         #fbbf24
--yellow-bg:      rgba(251,191,36,0.10)
--purple:         #a78bfa
--purple-bg:      rgba(167,139,250,0.12)
--cyan:           #22d3ee

/* Typography */
--font-ui:    'Inter', system-ui, sans-serif     ← consistent, Geist loads as fallback
--font-mono:  'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace

/* Radii */
--radius-sm:  4px
--radius-md:  6px
--radius-lg:  8px
--radius-xl:  12px

/* Card sizing */
--card-header-height: 36px
--terminal-header-height: 32px
```

---

## 2. Deduplication — Exact Locations to Remove

### 2.1 Duplicate CSS Classes (confirmed by full read)

| Class | Duplicate Locations | Keep | Remove |
|---|---|---|---|
| `.pulse-timer` + `@keyframes pulse` | `features.css:~220` AND `features.css:~2620` | First occurrence | Second "FILE OPERATION CARDS" section copy |
| `.status-tag` | `features.css:~240` AND `features.css:~2650` | First | Second |
| `.text-add / .text-mod / .text-del` | `features.css:~250` AND `features.css:~2660` | First | Second |
| `.list-row` | `features.css:~200` AND `features.css:~2640` | First | Second |
| `.ai-activity-panel` + all its children | `aichat.html` inline style — **declared twice back-to-back** (copy-paste error) | Keep first | Delete the second copy (starts ~line 530) |
| `.thinking-dots @keyframes dotsWave` | `features.css:~1720` AND `features.css:~1760` | First | Second |
| `@keyframes spin` | `features.css:~120` AND `features.css:~2000` via `.todo-icon-progress::after` | First | Remove from `.todo-icon-progress::after`, reference shared keyframe |
| `.summary-header / .summary-icon / .summary-title / .summary-count` | `features.css:~2480` AND `aichat.html` inline `<style>` (~line 745) | `features.css` | Remove from `aichat.html` inline |
| `.section-header / .section-icon / .section-items` | Same split as above | `features.css` | Remove from `aichat.html` inline |
| `.item-icon / .item-name / .item-meta` | Same split | `features.css` | Remove from `aichat.html` inline |
| `.permission-btn` | Defined as simple button in `style.css` AND redefined with full animation in `aichat.html` inline | `aichat.html` version (richer) | Remove `style.css` version |
| Scrollbar styles (`::-webkit-scrollbar*`) | 6 separate locations across `features.css` (`.diff-content`, `.activity-list`, `.ptree-list`, `.term-output-body`, `.todo-body`, `.cfs-body`) | One shared utility rule | Remove individual declarations |

### 2.2 Inline `<style>` Blocks in `aichat.html` — Full Removal List

Move ALL of these to CSS files and delete from `aichat.html`:

- **Keep in `aichat.html`** (2 allowed blocks only):
  - `<style id="hljs-fallback-styles">` — syntax fallback
  - The PyQt6 viewport fix block (`html,body { height:100% }` etc.) — must stay inline for PyQt loading order

- **Move to `style.css`**: `.inline-code*`, `.indexing-bar`, `#autogen-toggle`, `.autogen-status-banner`, `.autogen-toggle-switch`, `.switch-knob`, `.message-bubble.user`, `.message-bubble.assistant`, `.message-avatar`, `.thinking-message`, `.thinking-orb*`, `.thinking-title`, `.thinking-timer`, `.stop-btn`, `@keyframes stopBtnPulse`, `.action-btn-container`

- **Move to `features.css`**: `.tool-summary-card`, `.summary-header`, `.summary-*`, `.section-*`, `.item-icon`, `.item-name`, `.item-meta`, `.permission-card` (full version), `.permission-header`, `.permission-icon.*`, `.permission-path`, `.permission-actions`, `.permission-btn.*`, `.scope-btn`, `.permission-card-footer`, `.remember-toggle`, `.toggle-slider`, `.terminal-inline*`, `.code-completion-popup`, `.completion-*`, `.inline-diff-container`, `.inline-diff-*`, `.diff-row`, `.diff-line-*`, `.semantic-badge*`

- **Move to `aichat.html` `<script>` or remove entirely**: The mock `initAIActivityPanel()`, `simulateAIActivity()`, `updateActivityUI()`, `updateFileTree()` functions — full removal (these are dead mock code)

### 2.3 Icon System Duplicates

Current state — icons rendered 4 different ways:

| Location | Method | Fix |
|---|---|---|
| `aichat.html` `.summary-icon`, `.section-icon`, `.tool-badge-icon`, `.completion-card-icon` | Emoji text (`AUTO`, `TOOL`, emoji chars) | Replace with SVG |
| `features.css` `.term-title::before` | CSS `content: '>'` pseudo-element | Keep (it's decorative prompt prefix, acceptable) |
| `script.js` `ICONS` object in Tool Operation Card Controller | Inline SVG strings in JS | Keep (already SVG, good) |
| `aichat.html` HTML body | Inline SVG (good) | Keep |
| `permission_support.js` | No icons (JS logic only) | No change needed |

**Specific emoji to replace with SVG:**
- `.summary-icon` in `tool-summary-card` — currently text badge `"TOOL"`, replace with SVG
- `.completion-card-icon` — currently text `"AUTO"`, replace with SVG brain/sparkle icon
- `.tool-badge-icon` — currently `font-size: 16px; filter: drop-shadow(...)` on emoji — replace with SVG shield or wrench

---

## 3. Card Width Unification

### 3.1 The Real Problem (Found in Code)

`.perm-card` has `max-width: 460px` — breaks full-width layout.
`.interaction-card` in `style.css` has `max-width: 92%` — inconsistent.
`.permission-card` in `aichat.html` inline has `width: 100%; box-sizing: border-box` — correct, but overrides are elsewhere.
`.tool-summary-card` and `.code-completion-card` have `backdrop-filter: blur(10px)` and `box-shadow: 0 4px 20px` — adds floating effect, inconsistent with grounded card style.

### 3.2 Universal Card Width Rule

Apply this to ALL card types listed below:

```css
.card-container,
.term-card,
.tool-operation-card,
.activity-section,
.fec-group,
.ptree-card,
.dir-tree-card,
.task-completion-card,
.tool-summary-card,
.perm-card,
.permission-card,
.interaction-card,
.diff-group-container,
.fileop-group-container,
.diff-viewer-card,
.code-completion-card,
.inline-diff-container,
.todo-section,
.cfs-section,
.msg-queue-bar {
    width: 100%;
    box-sizing: border-box;
    max-width: none;        /* remove all max-width overrides */
}
```

Remove `max-width: 460px` from `.perm-card`, `max-width: 92%` from `.interaction-card`, and `backdrop-filter` + heavy `box-shadow` from floating card styles.

### 3.3 Card Header Standardization

All card headers must use the same base height and structure. Currently card headers use mixed padding: `10px 14px` (most), `8px 14px` (diff cards), `14px 18px` (tool-summary), `10px 12px` (perm-card). Standardize:

```
Standard card header:  padding: 9px 14px  (gives ~36px height)
Terminal card header:  padding: 7px 12px  (gives ~32px height)
```

All card header backgrounds use the same `rgba(255,255,255,0.025)` tint, hover at `rgba(255,255,255,0.04)`.

---

## 4. Terminal Card — Collapsed Default + 40px Body Cap

### 4.1 JavaScript Change (script.js line 7877)

```
CURRENT:  var isExpanded = true; // Default expanded for terminal
CHANGE TO: var isExpanded = false; // Always start collapsed
```

This one line change makes all new terminal cards start collapsed. Existing cards built by the legacy `buildTerminalCommandCard()` function (line 8504 area) also need `card.className` to default to `collapsed`, not `expanded`.

### 4.2 CSS Enforcement — Both Card Systems

Both `.tool-operation-card.terminal` (new) and `.term-card` (legacy) must enforce the 40px body limit. The following rules apply to the **expanded body** of terminal cards only:

```css
/* NEW system — tool-operation-card */
.tool-operation-card.terminal.expanded .tool-card-scrollable,
.tool-operation-card.terminal.expanded .tool-card-terminal {
    max-height: 40px !important;
    overflow-y: scroll;
    overflow-x: auto;
}

/* LEGACY system — term-card */
.term-card .term-command,
.term-card .term-output-body {
    max-height: 40px !important;
    overflow-y: scroll;
}
```

The `!important` is specifically allowed here because `script.js` sets `scrollable.style.display = 'block'` in `toggleTerminalToolCard()` but does not set height — so `!important` only needs to override any inherited `max-height: none` from `.terminal-viewport.expanded` in `features.css` line 178.

### 4.3 Remove Conflicting Rule

`features.css` line 178–181:
```css
.terminal-viewport.expanded {
    max-height: none;    ← REMOVE THIS LINE
}
```

`.terminal-viewport.collapsed { max-height: 120px }` — change `120px` to `40px` to be consistent.

### 4.4 Scrollbar Always Visible

Use `overflow-y: scroll` (not `auto`) in terminal bodies. This prevents layout shift when content switches between short and long output.

---

## 5. Streaming Text & Message Layout

### 5.1 Current Issues Found in Code

In `aichat.html` inline styles, `.message-bubble.user` has:
```css
background: transparent !important;
max-width: 85% !important;
```
And `.message-bubble.user .message-content` has:
```css
background: var(--bg-elevated, #2A2A2A) !important;
border-radius: 18px 18px 4px 18px !important;
```
This is correct directionally. The issue: it uses `!important` on 11 properties to fight against base styles. The base `.message-bubble` styles from `style.css` need to be changed so user/assistant overrides work without needing `!important`.

### 5.2 Message Bubble Fix

Remove `!important` from `.message-bubble.user` and `.message-bubble.assistant` styles. Instead make the base `.message-bubble` rule non-specific enough that variants override naturally:

Base `.message-bubble` should only define: `font-size`, `line-height`, `box-sizing`, `display`. All visual appearance (background, border, padding, radius) is applied only by `.message-bubble.user` and `.message-bubble.assistant` — not the base.

### 5.3 AI Message Full-Width Alignment

`.message-bubble.assistant .message-content` is `transparent`, `width: 100%`, `padding: 0` — this is already correct. The issue is that AI streaming text inside `.markdown-body` or `.md-content` gets `background: var(--dracula-bg)` from `syntax-highlighting.css` line 65. This must be scoped only to code blocks, not the prose container:

```css
/* syntax-highlighting.css — SCOPE THIS MORE TIGHTLY */
/* Change: */
html body .markdown-body { background: var(--dracula-bg) !important; }
/* To: */
html body .markdown-body pre,
html body .markdown-body .code-block-container { background: var(--dracula-bg) !important; }
/* Remove background from .markdown-body itself */
```

### 5.4 Streaming Cursor

Add a blinking cursor element after the last streaming token. Currently there is a `thinking-indicator-bar` with `thinking-dots-ani` (3 dots animation) that shows while waiting. This is separate from the streaming cursor. Both are needed:

- **Waiting state** (before first token): keep the existing `#thinking-indicator-bar` with the orb animation
- **Streaming state** (tokens arriving): add inline cursor `<span class="cx-stream-cursor">` appended after each token, removed on stream end

The streaming cursor CSS:
```css
.cx-stream-cursor {
    display: inline-block;
    width: 2px;
    height: 0.85em;
    background: var(--accent-primary);
    margin-left: 1px;
    vertical-align: text-bottom;
    animation: cursorBlink 900ms step-end infinite;
}
@keyframes cursorBlink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
}
```

---

## 6. Strictly Prohibited — Remove These Completely

### 6.1 Dead Mock Code — Full Removal

These functions in `aichat.html` are mock/simulation code and must be deleted entirely:

```javascript
// DELETE these from aichat.html <script> blocks:
function initAIActivityPanel()     // line ~99 — creates mock panel
function updateActivityUI()        // line ~115 — updates mock UI  
function updateFileTree()          // line ~125 — mock file tree
function simulateAIActivity()      // line ~139 — fake progress simulation

// DELETE the DOMContentLoaded listener that calls them:
document.addEventListener('DOMContentLoaded', () => {
    initAIActivityPanel();    // DELETE
    simulateAIActivity();     // DELETE
});
```

These create a fake "AI Agent Live Activity" panel injected into `#chatMessages` on every page load with mock file paths (`ai_chat.py`, `script.js`) and a fake progress bar. It runs `setInterval` forever.

### 6.2 CSS Anti-Patterns — Remove

- All `backdrop-filter: blur(10px)` on card bodies — IDE cards should not be frosted glass
- All `box-shadow: 0 4px 20px rgba(0,0,0,0.3)` on inline cards (`.tool-summary-card`, `.code-completion-card`, `.inline-diff-container`) — cards are grounded, not floating
- `linear-gradient(135deg, rgba(30,30,35,0.95), rgba(25,25,30,0.95))` backgrounds on cards — use flat `var(--bg-surface)` instead
- `filter: drop-shadow(0 0 4px rgba(59,130,246,0.5))` on `.tool-badge-icon` — excessive glow effect
- `z-index: 10000` and `z-index: 10001` on `.permission-card` and `.permission-tool-badge` — unnecessary, permission cards are inline in chat flow, not modals
- `position: fixed` on `.permission-backdrop` — permission cards are inline, no backdrop needed
- The `composes: permission-card` line in `.permission-card.cursor-style` — `composes` is CSS Modules syntax, it does nothing in plain CSS, remove it
- `animation: badgePulse 2.6s ease-in-out infinite` on `.section-icon`, `.item-icon`, `.tcc-stat`, `.tool-icon`, `.tool-badge-icon` (from `aichat.html` inline) — pulsing every static icon is excessive and distracting

### 6.3 JavaScript Anti-Patterns — Remove

- `Tailwind CSS CDN` script tag — loads entire Tailwind parser on every page load unnecessarily. Features using Tailwind utilities (`flex`, `items-center`, `gap-3`, `p-3`, `w-4`, `h-4`) already have equivalents defined at the bottom of `features.css`. Remove the CDN script.
- `simulateAIActivity()` `setInterval` — leaks memory, runs forever
- Any `.style.maxHeight = ''` or `.style.maxHeight = 'none'` applied to terminal card elements — guard with a type check: `if (!card.classList.contains('terminal')) { ... }`

---

## 7. Component Enhancement Specs

### 7.1 Terminal Card (Both Systems)

The two terminal card systems must look identical:

**Header (32px):**
```
[>_ icon] [command preview, truncated 60 chars] ... [status badge] [copy btn] [chevron ▶]
```

Header left-border color by status:
- Running: `2px solid rgba(99,160,246,0.5)` (blue)
- Success: `2px solid rgba(74,222,128,0.35)` (green)
- Error: `2px solid rgba(248,113,113,0.35)` (red)
- Stopped: `2px solid rgba(148,163,184,0.25)` (gray)

**Body (max 40px when expanded):**
- Background: `#050505` (near-black)
- Font: `var(--font-mono)`, 11px, line-height 1.5
- Overflow: `scroll` both axes
- Padding: `6px 10px`
- Prompt coloring: bash `$` = `#4ade80`, PowerShell `PS>` = `#63a0f6`, errors = `#f87171`

**Collapsed state (default):**
- Only header visible (32px total)
- Chevron points right (→)
- Command text truncated with `…`

### 7.2 Todo Section (Already Well-Designed — Minor Polish Only)

Current implementation is good. Changes:
- Margins: `margin: 0 16px 10px` — make responsive: `margin: 0 0 8px` when inside `#chatMessages` as a card (already handled by `#todo-card-container.todo-section` rule, keep it)
- The in-progress todo item's `::before` gradient (`var(--accent-primary)` to `rgba(147,51,234,0.8)`) — simplify to solid `var(--accent-primary)` for consistency
- `.todo-icon-done` uses `linear-gradient(135deg, var(--green), var(--green-bright))` with box-shadow — acceptable, keep

### 7.3 Changed Files Section (Already Well-Designed — Minor Polish Only)

Current implementation is good. Changes:
- `.cfs-file-icon` uses raw `font-size: 14px` with color `var(--text-secondary)` — it expects a Font Awesome icon class. Replace with the inline SVG approach used elsewhere for the file icon, or ensure Font Awesome loads correctly (it's loaded at `aichat.html` line ~2777)
- `.cfs-reject-btn` is 22×22 icon-only button — add `title="Reject change"` attribute via JS for accessibility

### 7.4 Permission Card (Two Systems — Align Them)

There are currently **two permission card systems** that must be unified:

**System A** — `.permission-card` (full featured, in `aichat.html` inline style): has scope selector, `deny/allow/always` buttons, remember toggle — this is the right one to keep

**System B** — `.perm-card` in `features.css`: simpler, for dangerous command confirmation — keep this for terminal command permission only (rm, git reset --hard, etc.)

The `.interaction-card` in `style.css` is a third, generic interaction card used for `AskUserQuestion` tool — keep it separate.

All three must share `width: 100%; box-sizing: border-box` and the same header height token.

### 7.5 Message Queue Bar (`#msg-queue-bar`)

Currently uses custom `.mq-*` classes that are not defined in any CSS file — they are missing entirely. Add to `features.css`:

```css
.msg-queue-bar — background var(--bg-surface), border var(--border), rounded, collapsed by default
.mq-header     — same pattern as other card headers
.mq-label      — font-weight 600, text-main
.mq-count      — same style as .todo-count
.mq-list       — list of queued messages, each a small row
```

### 7.6 Agent Mode Indicator (`#agent-mode-indicator`)

The 8-mode grid (Think/Read/Search/Grep/Find/Explore/Surf/Dive) has HTML but no CSS. The `.mode-indicator` and `.agent-mode-container` classes are undefined. Add to `features.css`:

```css
.agent-mode-container — flex row, gap 6px, padding 8px 16px, overflow-x auto
.mode-indicator       — flex column, align center, gap 4px, padding 6px 8px
                        border-radius var(--radius-md), cursor pointer
                        background transparent, border 1px solid var(--border)
                        font-size 10px, color var(--text-dim)
.mode-indicator.active — border-color var(--accent-border), color var(--accent-primary)
                         background var(--accent-dim)
.mode-indicator.completed — opacity 0.4, border-color var(--border)
.mode-icon             — width 20px, height 20px, color inherit
```

---

## 8. Input Area Polish

No major restructuring needed — the existing layout is correct. Targeted improvements:

### 8.1 Textarea
- Current `max-height: 280px` (set in JS lines 1409 and 1428) — reduce to `160px` for IDE feel
- Placeholder text is too long ("Plan and build, @ for context, / for commands...") — shorten to "Ask, plan, or build..." with the shortcuts on a second line or as tooltip

### 8.2 Mode Selector Dropdown
- Currently defined in `aichat.html` inline styles via `.custom-dropdown` and shares styles with the model selector — these are undefined in CSS files. Add `.custom-dropdown` base styles to `style.css`

### 8.3 Stop Button
The `.stop-btn` uses `animation: stopBtnPulse 1.5s ease-in-out infinite` which creates a glowing pulsing border. This is already good — keep it. The `@keyframes stopBtnPulse` is defined in `aichat.html` inline — move to `style.css`.

---

## 9. File Organization — Final Responsibility Map

| File | Owns | Does Not Own |
|---|---|---|
| `style.css` | `:root` tokens, body reset, `.message-bubble.*`, `.thinking-*`, `.stop-btn`, `.action-btn-container`, `.toolbar-btn`, `.interaction-card`, `.inline-code*`, `.indexing-bar`, `#autogen-toggle`, scrollbar utility class, light-mode token overrides | Card components, syntax highlighting |
| `features.css` | All card components: `.card-container`, `.term-card`, `.tool-operation-card`, `.fec-*`, `.activity-section`, `.ptree-card`, `.dir-tree-card`, `.diff-*`, `.todo-section`, `.cfs-section`, `.msg-queue-bar`, `.agent-mode-indicator`, `.perm-card`, `.permission-card`, `.code-completion-*`, `.inline-diff-*`, `.semantic-badge*`, file icon system, `.tcc-*` | Syntax colors, token definitions |
| `model_selector.css` | Model dropdown only | Everything else |
| `syntax-highlighting.css` | HLJS Dracula theme, code block fonts/colors, `.code-header`, copy/run buttons | Must NOT set background on `.markdown-body` root (only on `pre`/`code`) |
| `aichat.html` | Two allowed `<style>` blocks (HLJS fallback + viewport fix), HTML structure, JS logic | All other CSS — zero additional `<style>` blocks |
| `script.js` | All interaction logic, bridge calls | No inline CSS strings — use `classList.add/remove` only |

---

## 10. Light Mode

`style.css` uses `.light-mode` class (set via Python bridge). `syntax-highlighting.css` uses `body.light-mode`. The model selector uses `body.light`.

**Unify to `.light-mode` on `body` throughout.** Remove `body.light` variant from `model_selector.css` and replace with `body.light-mode`.

Light mode surface palette (matches the dark system at inverted luminance):

```
--bg-void:      #f4f4f6
--bg-base:      #f0f0f2
--bg-surface:   #ffffff
--bg-elevated:  #f0f0f3
--bg-float:     #e8e8ec
--bg-hover:     #e4e4e8
--border:       rgba(0,0,0,0.07)
--border-light: rgba(0,0,0,0.11)
--text-main:    #1a1a1e
--text-primary: #1a1a1e
--text-secondary: #52525a
--text-dim:     #909098
--bg-code:      #1a1a1e   ← code blocks stay dark always
--bg-card:      #ffffff
```

Accent, semantic (green/red/yellow/purple), and code block colors stay the same in light mode.

---

## 11. Implementation Order

Execute in this sequence to avoid regressions:

1. **Token migration** — merge all `:root` blocks into `style.css`, define every variable, do a global search-replace of hardcoded hex values
2. **Deduplication pass** — remove duplicate CSS classes in `features.css` (second "FILE OPERATION CARDS" section), remove duplicate `.ai-activity-panel` in `aichat.html` inline, consolidate scrollbar rules
3. **Inline style extraction** — move all `<style>` content from `aichat.html` into appropriate CSS files (except the 2 allowed blocks)
4. **Dead code removal** — delete `initAIActivityPanel`, `simulateAIActivity`, mock data, remove Tailwind CDN script
5. **Card width pass** — add `width: 100%; max-width: none` to all card selectors, remove `.perm-card max-width: 460px`
6. **Terminal enforcement** — change `isExpanded = true` to `false` in script.js line 7877, add `max-height: 40px !important` CSS rules for both terminal card systems, remove conflicting `max-height: none` rule in `.terminal-viewport.expanded`
7. **Missing CSS addition** — add `.msg-queue-bar`, `.mq-*`, `.mode-indicator`, `.agent-mode-container` which currently have no CSS definitions
8. **Icon cleanup** — replace emoji badges (`AUTO`, `TOOL`, etc.) with SVG in card templates
9. **Streaming cursor** — add `.cx-stream-cursor` CSS and the JS insertion/removal logic
10. **Light mode unification** — normalize `body.light` → `body.light-mode` across all files
11. **QA pass** — verify: terminal cards start collapsed, all cards are same width, no `<style>` blocks in HTML, no Tailwind CDN, no mock activity panel on load, streaming cursor appears/disappears correctly

---

## 12. Files Changed Summary

| File | Change Type | Scope |
|---|---|---|
| `style.css` | Major — new token system, extract from HTML | Significant rewrite of `:root`, add many moved classes |
| `features.css` | Medium — remove duplicates, add missing classes, unify | Remove ~150 duplicate lines, add ~80 lines for missing components |
| `aichat.html` | Major — remove 1800 lines of inline CSS, remove dead JS | Destructive removal, keep only 2 style blocks |
| `script.js` | Small — 2 JS changes | Line 7877 `isExpanded = false`; guard `maxHeight` resets |
| `model_selector.css` | Small — `body.light` → `body.light-mode` | 8 selectors |
| `syntax-highlighting.css` | Small — remove `:root` block, unscope background | 10 lines changed |

---

*End of Enhancement Plan — Cortex IDE AI Chat Frontend v2*
*Based on full read of: aichat.html (3959 lines) · style.css (3954 lines) · features.css (3494 lines) · script.js (11356 lines) · syntax-highlighting.css (572 lines) · model_selector.css (339 lines) · permission_support.js (172 lines)*
