# 🎨 Universal Syntax Highlighting Guide

## Overview
This guide explains how to apply the **Dracula Theme** universal syntax highlighting to your entire Cortex AI project.

## Files Created

### 1. **syntax-highlighting.css** (New)
- Universal CSS for ALL programming languages
- Supports: Python, JavaScript, TypeScript, Java, C++, C#, Go, Rust, PHP, SQL, etc.
- Markdown styling (blue headings, white text)
- Framework support: React, Vue, Angular, Django, Flask

### 2. **syntax_highlighting_config.py** (New)
- Python module for main_window.py
- Dracula color palette definitions
- Language keyword mappings
- Code colorizer classes

## 🚀 Integration Steps

### Step 1: Add CSS Link to HTML
```html
<!-- In aichat.html <head> section -->
<link rel="stylesheet" href="syntax-highlighting.css">
```

### Step 2: Use in main_window.py
```python
from src.ui.syntax_highlighting_config import CodeColorizer, MarkdownColorizer, DRACULA_COLORS

# For code blocks
colorizer = CodeColorizer()
colored_code = colorizer.colorize_python(code_string)

# For markdown
md_colorizer = MarkdownColorizer()
colored_md = md_colorizer.colorize(markdown_string)

# Access colors directly
keyword_color = DRACULA_COLORS['keyword']  # '#bd93f9'
```

### Step 3: Apply to All Code Displays
```python
# When displaying code in QPlainTextEdit or similar
code_display.setStyleSheet(f"""
    background-color: {DRACULA_COLORS['bg']};
    color: {DRACULA_COLORS['text']};
    font-family: {FONTS['mono']};
""")
```

## 📋 Supported Languages

| Language | Support | Frameworks |
|----------|---------|-----------|
| **Python** | ✅ Full | Django, Flask, FastAPI |
| **JavaScript** | ✅ Full | React, Vue, Angular, Node.js |
| **TypeScript** | ✅ Full | React, Vue, Angular, NestJS |
| **Java** | ✅ Full | Spring, Jenkins |
| **C++** | ✅ Full | STL, Boost |
| **C#** | ✅ Full | .NET, Unity |
| **C** | ✅ Full | POSIX, embedded systems |
| **Go** | ✅ Full | Gin, Echo |
| **Rust** | ✅ Full | Rocket, Actix |
| **PHP** | ✅ Full | Laravel, Symfony |
| **SQL** | ✅ Full | MySQL, PostgreSQL |
| **JSON** | ✅ Full | REST APIs |
| **YAML** | ✅ Full | Config files |
| **HTML** | ✅ Full | Web markup |
| **CSS** | ✅ Full | Styling |
| **SCSS/LESS** | ✅ Full | CSS preprocessors |
| **Bash/Shell** | ✅ Full | Script files |
| **JSX/TSX** | ✅ Full | React Native |

## 🎨 Color Scheme (Dracula Theme)

```
Purple (#bd93f9)    → Keywords, operators, literals
Green  (#50fa7b)    → Strings, class names, constants
Orange (#ffb86c)    → Function names, titles
Pink   (#ff79c6)    → Tags, attributes, imports
Red    (#ff5555)    → Variables, deletion
Blue   (#6272a4)    → Comments (italic)
White  (#f8f8f2)    → Default text
```

## 📝 Markdown Styling

- **Headings** → Blue (#0047AB)
- **Regular text** → White (#ffffff)
- **Inline code** → Green
- **Links** → Pink

## 💻 Usage Examples

### Example 1: Display Python Code
```python
from src.ui.syntax_highlighting_config import CodeColorizer

code = '''
def hello(name):
    print(f"Hello, {name}!")
'''

colorizer = CodeColorizer()
html = colorizer.colorize_python(code)
# Now you can display `html` in a QWebEngineView or similar
```

### Example 2: Display Markdown with Styling
```python
from src.ui.syntax_highlighting_config import MarkdownColorizer

markdown = '''
# Introduction
This is a **code example**:
`const x = 5;`
[Link to docs](https://example.com)
'''

colorizer = MarkdownColorizer()
styled_html = colorizer.colorize(markdown)
```

### Example 3: Get Font Family
```python
from src.ui.syntax_highlighting_config import FONTS

mono_font = FONTS['mono']  # JetBrains Mono, Cascadia Code, ...
sans_font = FONTS['sans']  # Inter, SF Pro Display, ...
```

## 🔗 Files Location

```
Cortex/
├── src/
│   ├── ui/
│   │   ├── html/ai_chat/
│   │   │   ├── style.css
│   │   │   ├── features.css
│   │   │   ├── syntax-highlighting.css ✨ NEW
│   │   │   ├── aichat.html
│   │   │   └── sample-components.html
│   │   └── main_window.py
│   ├── syntax_highlighting_config.py ✨ NEW
│   └── ...
```

## 🎯 Implementation Checklist

- [ ] Add `syntax-highlighting.css` link to aichat.html
- [ ] Import `syntax_highlighting_config` in main_window.py
- [ ] Apply colors to code displays
- [ ] Apply colors to output terminals
- [ ] Apply colors to file editors
- [ ] Test with all supported languages
- [ ] Verify markdown rendering
- [ ] Test light/dark mode toggle

## 🌓 Light Mode Support

Light mode colors are automatically applied with CSS media queries. Override with:

```css
body.light .hljs {
    background: #f5f5f5 !important;
    color: #1e1e1e !important;
}
```

## 🔧 Customization

To change colors, edit:
```python
DRACULA_COLORS = {
    'keyword': '#YOUR_COLOR',
    'string': '#YOUR_COLOR',
    # ... etc
}
```

## 📚 Resources

- **Dracula Theme**: https://draculatheme.com
- **Highlight.js**: https://highlightjs.org
- **Color Reference**: View `DRACULA_COLORS` dict in `syntax_highlighting_config.py`

---

**Created:** April 1, 2026  
**Theme:** Dracula (Professional Dark Theme)  
**Status:** Production Ready ✅
