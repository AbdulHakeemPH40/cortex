# Cursor IDE — Design Tokens
> Anysphere Dark theme · Use these in Cortex IDE

---

## Color Palette

### Backgrounds

| Token | Hex | Role |
|---|---|---|
| `editor.background` | `#181818` | Main editor area |
| `activityBar.background` | `#141414` | Left icon bar |
| `sideBar.background` | `#141414` | File explorer panel |
| `tab.activeBackground` | `#1a1a1a` | Active tab |
| `tab.inactiveBackground` | `#141414` | Inactive tabs |
| `terminal.background` | `#141414` | Integrated terminal |
| `statusBar.background` | `#141414` | Bottom status bar |
| `editor.lineHighlightBackground` | `#292929` | Current line highlight |
| `editor.selectionBackground` | `#163761` | Text selection |

### Text & Foreground

| Token | Hex | Role |
|---|---|---|
| `editor.foreground` | `#d6d6dd` | Main editor text |
| `statusBar.foreground` | `#d6d6dd` | Status bar text |
| `terminal.foreground` | `#d6d6dd` | Terminal text |
| `tab.activeForeground` | `#ffffff` | Active tab label |
| `tab.inactiveForeground` | `#6d6d6d` | Inactive tab label |
| `editorLineNumber.foreground` | `#505050` | Line numbers |
| `editorLineNumber.activeForeground` | `#ffffff` | Active line number |
| `comment` | `#6d6d6d` | Code comments |

### Accent & Interactive

| Token | Hex | Role |
|---|---|---|
| `cursor.accent` | `#228df2` | Primary blue — AI accent |
| `editorCursor.foreground` | `#228df2` | Blinking text cursor |
| `tab.activeBorder` | `#228df2` | Active tab underline |
| `activityBarBadge.background` | `#228df2` | Notification badges |
| `statusBarItem.remoteBackground` | `#228df2` | Remote indicator |
| `sideBar.border` | `#2a2a2a` | Panel dividers |

---

## Syntax Highlighting

> All syntax tokens use the **same font size as the editor (16px)**.  
> Differentiation is done via **color only** — no size variation, no bold.  
> The only style exception is comments, which use `font-style: italic`.

| Token | Hex | Font Size | Style | Sample |
|---|---|---|---|---|
| Keyword | `#83d6c5` | 16px | normal | `const` · `return` · `if` |
| String | `#e394dc` | 16px | normal | `"hello world"` |
| Function name | `#efb080` | 16px | normal | `fetchData()` |
| Class / Type | `#87c3ff` | 16px | normal | `ChatWidget` |
| HTML/JSX attribute | `#aaa0fa` | 16px | normal | `className=` |
| Comment | `#6d6d6d` | 16px | **italic** | `// AI-powered` |
| Variable | `#d6d6dd` | 16px | normal | `myVariable` |
| Number | `#efb080` | 16px | normal | `42` · `3.14` |
| Operator | `#83d6c5` | 16px | normal | `=` · `+` · `===` |
| Tag name | `#87c3ff` | 16px | normal | `<div>` · `<span>` |

---

## Terminal ANSI Colors

| Token | Hex | Color name |
|---|---|---|
| `terminal.ansiBlack` | `#676767` | Black |
| `terminal.ansiRed` | `#f14c4c` | Red |
| `terminal.ansiGreen` | `#15ac91` | Green |
| `terminal.ansiYellow` | `#e5b95c` | Yellow |
| `terminal.ansiBlue` | `#4c9df3` | Blue |
| `terminal.ansiMagenta` | `#e567dc` | Magenta |
| `terminal.ansiCyan` | `#75d3ba` | Cyan |
| `terminal.ansiWhite` | `#d6d6dd` | White |

---

## Typography

### Editor & Code Font

| Font | Type | Notes |
|---|---|---|
| **Berkeley Mono** | Monospace | Cursor's marketing font · premium paid |
| **Geist Mono** | Monospace | Free alternative by Vercel · closest match |
| **JetBrains Mono** | Monospace | Free · excellent ligature support |

### UI Font (Sidebar, Chat, Menus)

| Font | Type | Notes |
|---|---|---|
| **Geist Sans** | Sans-serif | Used in Cursor's chat panel & UI menus · free |

---

## Font Sizes

| Size | Role |
|---|---|
| `11px` | Inactive tab labels, hints |
| `12px` | Status bar, breadcrumbs |
| `13px` | File explorer, tree labels |
| `14px` | Chat UI body text, tooltips |
| `15px` | Sidebar section headers |
| `16px` | **Editor default — syntax tokens inherit this** |
| `18px` | Chat response headings |
| `22px` | Welcome / onboarding titles |

---

## CSS Custom Properties (Cortex IDE)

```css
:root {
  /* ── backgrounds ── */
  --cx-bg-editor:        #181818;
  --cx-bg-sidebar:       #141414;
  --cx-bg-tab-active:    #1a1a1a;
  --cx-bg-selection:     #163761;
  --cx-bg-line-hl:       #292929;

  /* ── text ── */
  --cx-fg-primary:       #d6d6dd;
  --cx-fg-muted:         #6d6d6d;
  --cx-fg-line-num:      #505050;
  --cx-fg-line-active:   #ffffff;

  /* ── accent ── */
  --cx-accent:           #228df2;
  --cx-border:           #2a2a2a;

  /* ── syntax ── */
  --cx-syn-string:       #e394dc;
  --cx-syn-keyword:      #83d6c5;
  --cx-syn-function:     #efb080;
  --cx-syn-class:        #87c3ff;
  --cx-syn-attribute:    #aaa0fa;
  --cx-syn-comment:      #6d6d6d;

  /* ── fonts ── */
  --cx-font-editor: 'Berkeley Mono', 'Geist Mono', 'JetBrains Mono', monospace;
  --cx-font-ui:     'Geist Sans', 'Inter', sans-serif;

  /* ── font sizes ── */
  --cx-fs-xs:   11px;  /* hints, inactive tabs */
  --cx-fs-sm:   12px;  /* status bar */
  --cx-fs-tree: 13px;  /* file explorer */
  --cx-fs-chat: 14px;  /* chat body */
  --cx-fs-base: 16px;  /* editor + all syntax tokens */
  --cx-fs-h2:   18px;  /* chat headings */
}
```

---

## Key Rules

- Syntax tokens **never** change font size — only color and font-style differ
- Comments are the **only** token with `font-style: italic`
- No syntax token uses `font-weight: bold`
- The single accent color `#228df2` handles all interactive/AI UI elements
- Background depth: editor (`#181818`) is slightly lighter than sidebar (`#141414`), creating subtle panel separation
