filepath = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\script.js'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Second corrupted pattern (5-space indent): split across 5 lines
corrupted = (
    '     text = text.replace(/\n'
    '{4,}/g, \'\n'
    '\n'
    '\n'
    '\');'
)
correct = "     text = text.replace(/\\n{4,}/g, '\\n\\n\\n');"

if corrupted in content:
    content = content.replace(corrupted, correct)
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    print('Fixed second occurrence!')
else:
    print('Pattern not found - checking first char of each line...')
    # Debug: find the location
    idx = content.find('     text = text.replace(/\n{4,}')
    print(f'Found at index: {idx}')
    if idx >= 0:
        print(repr(content[idx:idx+80]))
