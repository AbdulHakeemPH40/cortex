import re

path = 'c:\\Users\\Hakeem1\\OneDrive\\Desktop\\Cortex_Ai_Agent\\Cortex\\src\\ui\\html\\ai_chat\\script.js'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# The corrupted pattern: regex literal has a real newline between '/' and '{4,}'
# e.g.:  text.replace(/\n{4,}/g, '\n\n\n')
# where \n is an actual newline byte, not a two-character escape sequence

# Fix pattern 1: at line ~5791 (inside if block)
# Match: text = text.replace(/<LF>{4,}/g, '<LF><LF><LF>');
pattern1 = r"text = text\.replace\(/\s*\n\s*\{4,\}/g,\s*'\s*\n\s*\n\s*\n\s*'\);"
replacement1 = "text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"
new_content = re.sub(pattern1, replacement1, content)
if new_content != content:
    content = new_content
    print("Fixed pattern 1")
else:
    print("Pattern 1 not found")

# Fix pattern 2: at line ~5913 (outside if block, has leading spaces)
pattern2 = r"    text = text\.replace\(/\s*\n\s*\{4,\}/g,\s*'\s*\n\s*\n\s*\n\s*'\);"
replacement2 = "    text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"
new_content = re.sub(pattern2, replacement2, content)
if new_content != content:
    content = new_content
    print("Fixed pattern 2")
else:
    print("Pattern 2 not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
