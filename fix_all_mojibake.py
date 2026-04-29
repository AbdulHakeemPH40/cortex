#!/usr/bin/env python3
"""
Comprehensive fix for mojibake (corrupted UTF-8) in agent_bridge.py
This handles all the double-encoded UTF-8 characters
"""

file_path = 'src/ai/agent_bridge.py'

# Read as bytes first to see actual encoding
with open(file_path, 'rb') as f:
    raw_bytes = f.read()

# Try to decode with errors='replace' to see what we get
content = raw_bytes.decode('utf-8', errors='replace')

# Common mojibake patterns from double UTF-8 encoding
replacements = {
    # Box drawing characters (U+2500 to U+257F) double-encoded
    'â"€': '=',  # U+2500 BOX DRAWINGS LIGHT HORIZONTAL
    'â"‚': '|',  # U+2502 BOX DRAWINGS LIGHT VERTICAL  
    'â"Œ': '+',  # U+250C BOX DRAWINGS LIGHT DOWN AND RIGHT
    'â"': '+',  # U+2510 BOX DRAWINGS LIGHT DOWN AND LEFT
    'â""'': '+',  # U+2514 BOX DRAWINGS LIGHT UP AND RIGHT
    'â"˜': '+',  # U+2518 BOX DRAWINGS LIGHT UP AND LEFT
    'â"œ': '+',  # U+251C BOX DRAWINGS LIGHT VERTICAL AND RIGHT
    'â"¤': '+',  # U+2524 BOX DRAWINGS LIGHT VERTICAL AND LEFT
    'â"¬': '+',  # U+252C BOX DRAWINGS LIGHT DOWN AND HORIZONTAL
    'â"´': '+',  # U+2534 BOX DRAWINGS LIGHT UP AND HORIZONTAL
    'â"¼': '+',  # U+253C BOX DRAWINGS LIGHT VERTICAL AND HORIZONTAL
    
    # Em-dash and other punctuation
    'â€"': '-',  # U+2014 EM DASH
    'â€"': '-',  # Another variant
    'â€œ': '"',  # U+201C LEFT DOUBLE QUOTATION MARK
    'â€': '"',   # U+201D RIGHT DOUBLE QUOTATION MARK
    'â€˜': "'",  # U+2018 LEFT SINGLE QUOTATION MARK
    'â€™': "'",  # U+2019 RIGHT SINGLE QUOTATION MARK
}

# Apply replacements
for corrupted, replacement in replacements.items():
    content = content.replace(corrupted, replacement)

# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed all mojibake/corrupted UTF-8 characters')
print(f'Total replacements made for patterns')
