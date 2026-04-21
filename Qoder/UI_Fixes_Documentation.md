# Cortex AI Agent UI Fixes Documentation

## Overview
This document tracks all UI styling fixes applied to `aichat.html` to match the reference designs in `test_aichat.html` and `new_aichat.html`.

---

## 1. File Tree Card (dir-tree-card)

### Problem
The directory listing card was not styled properly - the expand/collapse functionality used inline JavaScript styles that didn't match the CSS expectations.

### Solution
**JavaScript Changes** (`script.js`):
- Changed from inline `style.display`/`style.transform` to `classList.toggle('expanded')`
- Card starts with `className = 'dir-tree-card expanded'`

**CSS Changes** (`features.css`):
```css
/* Expanded state for dir-tree-card */
.dir-tree-card.expanded .card-chevron {
    transform: rotate(90deg);
}

.dir-tree-card.expanded .card-body {
    display: block;
    animation: slideDown 0.2s ease;
}

.dir-tree-card .card-body {
    display: none;
    border-top: 1px solid var(--border);
    background: #141414;
    max-height: 300px;
    overflow-y: auto;
}
```

### Enhanced (v2)
- Added gradient backgrounds and improved shadows
- Added smooth slideDown animation with cubic-bezier easing
- Added file type specific styling with colored icons
- Added nested directory indentation support
- Added left border indicator on hover

---

## 2. Activity Operation Badges (activity-op)

### Problem
Activity items showed plain text like "Working", "Creating", "Editing" without the animated mode-indicator style from the reference designs.

### Solution
**JavaScript** (`script.js`):
- Added `getActivityOpBadge(type)` function that returns colored badges:
  - `Read` → Blue
  - `Edit` → Red (Dive style)
  - `Create` → Green
  - `Delete` → Orange
  - `Explore` → Green
  - `Search` → Cyan
  - `Run` → Yellow
  - `Think` → Purple

**CSS** (`features.css`):
```css
.activity-item.running .activity-op {
    display: inline-flex;
    align-items: center;
    padding: 2px 9px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    animation: opGlow 1.4s ease-in-out infinite;
}

@keyframes opGlow {
    0%, 100% { opacity: 0.65; filter: brightness(0.9); }
    50%       { opacity: 1;    filter: brightness(1.35); }
}
```

**Note**: Uses `filter: brightness()` instead of `box-shadow` because PyQt6 WebEngine doesn't render box-shadow animations properly.

### Enhanced (v2)
- Added gradient backgrounds to operation badges
- Added left border pulse animation for running items
- Improved completed state dimming
- Added box-shadow glow effect

---

## 3. Python Dict Parsing for Activity Labels

### Problem
Activity items showed raw Python dict strings like `{'PATH': {'path': 'sample_file_2.txt'}}` instead of just the filename.

### Solution
**JavaScript** (`script.js` in `formatActivityLabel()`):
```javascript
// Parse JSON/Python-dict args to extract human-readable display info
var parsed = null;
try {
    // First: try standard JSON parse
    parsed = JSON.parse(info);
} catch(e1) {
    try {
        // Second: convert Python dict repr (single quotes) to JSON
        var jsonStr = info
            .replace(/'/g, '"')
            .replace(/True/g, 'true')
            .replace(/False/g, 'false')
            .replace(/None/g, 'null');
        parsed = JSON.parse(jsonStr);
    } catch(e2) {
        // Not parseable - use raw string
    }
}
```

---

## 4. Thought Timer Styling

### Problem
DeepSeek reasoning output like `⊙Thought · 11s` appeared as plain text without styling.

### Solution
**JavaScript** (`script.js` in message rendering):
```javascript
// Style ⊙Thought · Xs patterns from DeepSeek reasoning output
content.innerHTML = content.innerHTML.replace(
    /([⊙]Thought\s*[·]\s*\d+s)/g,
    '<span class="thought-timer">$1</span>'
);
```

**CSS** (`style.css`):
```css
.thought-timer {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 500;
    color: rgba(139, 92, 246, 0.7);
    background: rgba(139, 92, 246, 0.08);
    border: 1px solid rgba(139, 92, 246, 0.2);
    padding: 2px 10px 2px 8px;
    border-radius: 20px;
    font-family: var(--font-mono);
    animation: modePulse 2s ease-in-out infinite;
}
```

---

## 5. Code Block Header Buttons

### Problem
Copy/Insert/Run buttons in code blocks had bright pink/magenta Dracula theme colors.

### Solution
**CSS** (`syntax-highlighting.css`):
Changed from pink/magenta to neutral dark:
```css
.code-header .code-copy-btn,
.code-header .code-insert-btn,
.code-header .code-run-btn {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.5);
}
```

Also fixed `.code-lang` class to match `.lang-label` styling.

---

## 6. Terminal Cards (Enhanced)

### Problem
Terminal output cards lacked visual feedback and animations for different states.

### Solution
**CSS Changes** (`features.css`):
```css
/* Running state - animated pulsing border */
.term-card.term-running {
    border-color: rgba(59, 130, 246, 0.3);
    animation: termRunningPulse 2s ease-in-out infinite;
}

@keyframes termRunningPulse {
    0%, 100% { 
        border-color: rgba(59, 130, 246, 0.2); 
        box-shadow: 0 2px 12px rgba(59, 130, 246, 0.1);
    }
    50% { 
        border-color: rgba(59, 130, 246, 0.5); 
        box-shadow: 0 4px 24px rgba(59, 130, 246, 0.2);
    }
}

/* Success state */
.term-card.term-success {
    border-color: rgba(34, 197, 94, 0.25);
    box-shadow: 0 2px 12px rgba(34, 197, 94, 0.1);
}

/* Error state */
.term-card.term-error {
    border-color: rgba(248, 113, 113, 0.25);
    box-shadow: 0 2px 12px rgba(248, 113, 113, 0.1);
}
```

### Features Added
- Gradient header backgrounds
- Animated status icon pulse
- State-specific color theming (running/success/error)
- Enhanced command display with syntax highlighting classes
- View Output button styling

---

## 7. Todo Section (Enhanced)

### Problem
Todo section lacked visual polish and animations.

### Solution
**CSS Changes** (`features.css`):
```css
.todo-section {
    background: linear-gradient(135deg, rgba(28, 28, 32, 0.98), rgba(24, 24, 28, 0.98));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
}

.todo-icon-progress::after {
    content: '';
    width: 10px;
    height: 10px;
    border: 2px solid transparent;
    border-top-color: var(--accent-primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    position: absolute;
}
```

### Features Added
- Gradient backgrounds with purple accent
- In-progress item left border animation
- Enhanced todo icon circles with gradients
- Improved status text animations

---

## 8. Changed Files Section (Enhanced)

### Problem
Changed files section styling was basic and lacked visual feedback.

### Solution
**CSS Changes** (`features.css`):
```css
.cfs-section {
    background: linear-gradient(135deg, rgba(28, 28, 32, 0.98), rgba(24, 24, 28, 0.98));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
}

.cfs-row.cfs-accepted::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--green);
}
```

### Features Added
- Gradient backgrounds with green accent
- Status indicators (accepted/rejected/pending) with left border
- Enhanced badge styling with borders
- Improved button hover effects

---

## Files Modified

| File | Lines Changed | Description |
|------|---------------|-------------|
| `features.css` | ~+1200 lines | Terminal cards, file execution cards, activity sections, directory tree cards, tool summary cards, todo section, changed files section |
| `script.js` | ~+50 lines | Fixed class toggling, added parsing logic, added badge generation |
| `syntax-highlighting.css` | ~+20 lines | Fixed code header button colors |
| `style.css` | ~+20 lines | Added thought-timer styling |

---

## Reference Designs

- `test_aichat.html` - Card-container pattern, collapsible headers
- `new_aichat.html` - Cursor-like panel design with `expanded` class toggle

---

## CSS Animation Patterns Used

### opGlow (Activity Badges)
Brightness/opacity pulse for running operation badges - PyQt6 compatible.

### termRunningPulse (Terminal Cards)
Border color and box-shadow pulse for running terminal commands.

### slideDown (Card Bodies)
Smooth expand animation with opacity and transform.

### spin (Todo Progress)
Rotating border animation for in-progress todo items.

### itemBorderPulse (Activity Items)
Left border pulse animation for running activity items.

---

## Color Palette (Cursor Theme)

| Type | Color | Usage |
|------|--------|-------|
| Think | `#a78bfa` (purple) | Reasoning operations |
| Read | `#60a5fa` (blue) | File read operations |
| Edit | `#f87171` (red) | File write operations |
| Create | `#4ade80` (green) | File/directory creation |
| Delete | `#fb923c` (orange) | File deletion |
| Search | `#22d3ee` (cyan) | Search/grep operations |
| Run | `#fbbf24` (yellow) | Terminal commands |
| Success | `#4ade80` (green) | Completion states |
| Error | `#f87171` (red) | Error states |
