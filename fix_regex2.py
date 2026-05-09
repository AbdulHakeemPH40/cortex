import re

filepath = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# The corrupted pattern: literal newlines inside the regex and replacement
# Pattern: text = text.replace(/\n{4,}/g, '\n\n\n');
# Bug: the \n escape sequences got turned into actual newlines

# Fix: replace actual-newline-split pattern with proper \n escapes
# Match multi-line corrupted form and replace with proper single line

corrupted1 = '        text = text.replace(/\n{4,}/g, \'\n\n\n\');\n'
correct1 = '        text = text.replace(/\\n{4,}/g, \'\\n\\n\\n\');\n'

corrupted2 = '     text = text.replace(/\n{4,}/g, \'\n\n\n\');\n'
correct2 = '     text = text.replace(/\\n{4,}/g, \'\\n\\n\\n\');\n'

count = content.count(corrupted1)
print(f'Found corrupted1: {count} times')
if count > 0:
    content = content.replace(corrupted1, correct1)

count = content.count(corrupted2)
print(f'Found corrupted2: {count} times')
if count > 0:
    content = content.replace(corrupted2, correct2)

with open(filepath, 'w', encoding='utf-8', newline='') as f:
    f.write(content)

print('Fixed!')
