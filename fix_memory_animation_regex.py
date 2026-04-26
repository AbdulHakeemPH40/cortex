import re

file_path = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the broken regex patterns - replace actual newlines with \n escape
# Pattern 1: Around line 5121
content = content.replace(
    "text = text.replace(/\r\n/g, '\\n');\n        text = text.replace(/\n{4,}/g, '\n\n\n');",
    "text = text.replace(/\\r\\n/g, '\\n');\n        text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"
)

# Pattern 2: Around line 5242  
content = content.replace(
    "// Limit blank lines.\n    text = text.replace(/\n{4,}/g, '\n\n\n');",
    "// Limit blank lines.\n    text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed regex patterns in script.js")
