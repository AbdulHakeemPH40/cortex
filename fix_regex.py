import sys

# Fix the broken regex on line 4795
file_path = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix line 4795 (index 4794)
old_line = lines[4794]
print(f'Before: {repr(old_line)}')

# Replace with correct regex: /\n{4,}/g replacing with \n\n\n
lines[4794] = "    text = text.replace(/\\n{4,}/g, '\\n\\n\\n');\n"

print(f'After:  {repr(lines[4794])}')

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('✅ Fixed line 4795 - regex now properly escapes newlines')
