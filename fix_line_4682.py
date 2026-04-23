# Fix the broken regex on line 4682

file_path = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show current line 4682 (index 4681)
print(f"Before: {repr(lines[4681])}")

# Replace with correct regex
# Old: text = text.replace(/{4,}/g, '');
# New: text = text.replace(/\n{4,}/g, '\n\n\n');
lines[4681] = "        text = text.replace(/\\n{4,}/g, '\\n\\n\\n');\n"

print(f"After:  {repr(lines[4681])}")

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("✅ Line 4682 fixed!")
