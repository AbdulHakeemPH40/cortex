file_path = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix lines around 5121-5125 and 5242-5246
fixed_lines = []
skip_next = 0

for i, line in enumerate(lines):
    line_num = i + 1
    
    # Skip the broken lines we're replacing
    if skip_next > 0:
        skip_next -= 1
        continue
    
    # Fix pattern around line 5121
    if line_num == 5121 and "text.replace(/" in line and "{4,}" in line:
        # Replace the broken multi-line pattern
        fixed_lines.append("        text = text.replace(/\\n{4,}/g, '\\n\\n\\n');\n")
        skip_next = 4  # Skip next 4 broken lines
        continue
    
    # Fix pattern around line 5242
    if line_num == 5242 and "text.replace(/" in line and "{4,}" in line:
        fixed_lines.append("    text = text.replace(/\\n{4,}/g, '\\n\\n\\n');\n")
        skip_next = 4  # Skip next 4 broken lines
        continue
    
    fixed_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print(f"✅ Fixed script.js - processed {len(lines)} lines, output {len(fixed_lines)} lines")
