# P2 Inline Style Extraction Plan

## Scope Analysis

**File:** `aichat.html`
**Inline `<style>` block:** Lines 390-2682 (**~2292 lines**)

This is **TOO LARGE** to extract in one session. Here's the strategic breakdown:

---

## Inline Style Sections (by line number)

| Section | Lines | ~Size | Target CSS File | Priority |
|---------|-------|-------|-----------------|----------|
| **Viewport/Container fixes** | 390-412 | 22 lines | KEEP INLINE (PyQt6 loading order) | 🔴 Keep |
| **AI Activity Panel** (duplicate already removed) | 414-479 | 65 lines | features.css | 🟢 Done |
| **Message Bubbles** (user/assistant) | 1450-1577 | 127 lines | style.css | 🔴 Critical |
| **Thinking Animation** (orb, timer) | 1579-1696 | 117 lines | style.css | 🔴 Critical |
| **Action Button Container** | 1697-1724 | 27 lines | style.css | 🟡 High |
| **Stop Button** | 1726-1790 | 64 lines | style.css | 🔴 Critical |
| **Code Completion Popup** | 1792-1950 | 158 lines | features.css | 🟡 High |
| **Inline Diff Container** | 1952-2100 | 148 lines | features.css | 🟡 High |
| **Permission Card** (full version) | 2102-2350 | 248 lines | features.css | 🔴 Critical |
| **Terminal Inline Styles** | 2352-2450 | 98 lines | features.css | 🟡 High |
| **Tool Summary Card** | 2452-2550 | 98 lines | features.css | 🟢 Medium |
| **Section Headers/Items** | 2552-2620 | 68 lines | features.css | 🟢 Medium |
| **Autogen Toggle** | 2622-2682 | 60 lines | style.css | 🟢 Medium |

---

## Recommended Extraction Order

### **Batch 1: Critical UI (style.css)** ~335 lines
1. Message bubbles (user/assistant) - 127 lines
2. Thinking animation (orb, timer) - 117 lines
3. Action button container - 27 lines
4. Stop button + animation - 64 lines

**Target:** Append to `style.css` after light mode section (line 4072)

### **Batch 2: Card Components (features.css)** ~612 lines
1. Permission card (full) - 248 lines
2. Code completion popup - 158 lines
3. Inline diff container - 148 lines
4. Terminal inline styles - 98 lines
5. Tool summary card - 98 lines
6. Section headers/items - 68 lines

**Target:** Append to `features.css` after agent recovery section

### **Batch 3: Utility Styles (style.css)** ~60 lines
1. Autogen toggle + banner - 60 lines

**Target:** Append to `style.css` after Batch 1

---

## What MUST Stay Inline in aichat.html

According to v2 plan section 2.2, ONLY these 2 blocks are allowed:

1. **`<style id="hljs-fallback-styles">`** (line 86-106) - Syntax fallback
2. **PyQt6 viewport fix** (line 390-412) - Must stay inline for PyQt loading order:
   ```css
   html, body { height: 100%; margin: 0; padding: 0; overflow: hidden; }
   #app-container { height: 100%; display: flex; }
   #chat-container { height: 100%; display: flex; flex-direction: column; flex: 1; min-width: 0; }
   #chatMessages { flex: 1; overflow-y: auto; min-height: 0; ... }
   ```

---

## Extraction Strategy

### Manual Extraction Steps:

1. **Copy section from aichat.html** (lines X-Y)
2. **Remove `!important` where possible** (v2 plan section 5.2)
3. **Replace hardcoded colors with tokens** (use new unified tokens from P0)
4. **Append to target CSS file**
5. **Delete from aichat.html**
6. **Test UI** to ensure no regressions

### Token Replacements Needed:

| Hardcoded Value | Replace With |
|----------------|--------------|
| `#161618` | `var(--bg-surface)` |
| `#1e1e1e` | `var(--bg-elevated)` |
| `#2A2A2A` | `var(--bg-elevated)` |
| `#3b82f6` | `var(--accent-primary)` |
| `#a855f7` | `var(--purple)` |
| `#ef4444` | `var(--red)` |
| `#f87171` | `var(--red)` |
| `#666` | `var(--text-dim)` |
| `#a3a3a3` | `var(--text-secondary)` |
| `rgba(255, 255, 255, 0.07)` | `var(--border)` |

---

## Estimated Effort

| Batch | Lines to Move | Files to Edit | Time Estimate |
|-------|---------------|---------------|---------------|
| Batch 1 | ~335 lines | aichat.html, style.css | 15-20 min |
| Batch 2 | ~612 lines | aichat.html, features.css | 25-30 min |
| Batch 3 | ~60 lines | aichat.html, style.css | 5-10 min |
| **TOTAL** | **~1007 lines** | **3 files** | **45-60 min** |

---

## Next Action

**Should I proceed with Batch 1 (Critical UI - message bubbles + thinking + stop button)?**

This will:
- Extract ~335 lines from aichat.html (lines 1450-1790)
- Append to style.css after light mode section
- Replace hardcoded colors with unified tokens
- Remove excessive `!important` where possible
