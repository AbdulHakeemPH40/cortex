#!/usr/bin/env python3
"""Fix corrupted Unicode box-drawing characters in agent_bridge.py"""
import re

file_path = 'src/ai/agent_bridge.py'

with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Replace box-drawing character sequences with ASCII
content = re.sub(r'â"[€\u2500-\u257F]+â"[€\u2500-\u257F]*', '==========', content)
content = re.sub(r'â"[€\u2500-\u257F]+', '==========', content)

# Replace em-dash with regular dash
content = content.replace('\u2014', '-')
content = content.replace('â€"', '-')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed all corrupted Unicode characters')
