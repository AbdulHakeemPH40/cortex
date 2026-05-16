import re

filepath = r"C:\Users\Hakeem1\ OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js"

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix corrupted regex pattern: literal newline followed by {4,} should be \n{4,}
# Pattern 1: in the large text guard
content = content.replace(
    'text = text.replace(/\n{4,}/g, \'\n\n\n\');',
    "text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"
)

# Pattern 2: in the blank line limiter
content = content.replace(
    ' text = text.replace(/\n{4,}/g, \'\n\n\n\');',
    " text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed corrupted regex patterns in script.js")
