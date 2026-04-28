#!/usr/bin/env python3
"""Get current Week 2 errors to fix."""
import json
import subprocess

# Generate fresh report
subprocess.run(['python', 'pyright_audit.py', '--json-out', 'pyright_week2.json'], 
               capture_output=True)

# Load report
with open('pyright_week2.json', 'r') as f:
    data = json.load(f)

print(f"Total errors: {data['summary']['errorCount']}")
print(f"Total warnings: {data['summary']['warningCount']}")

# Get errors (skip files we already cleaned)
skip_files = [
    'oauth.py',
    'systemPromptSections.py',
    'agent_context.py',
    'shortcutFormat.py',
    'config.py',
    'deps.py',
    'remember.py',
    'AppStateStore.py',
    'tasks.py'
]

errors = [d for d in data['diagnostics'] if d['severity'] == 'error']
filtered = [e for e in errors if not any(skip in e['file'] for skip in skip_files)]

print(f"\n📝 WEEK 2 - First 15 errors to fix:\n")

for i, error in enumerate(filtered[:15], 1):
    file_path = error['file'].replace('c:\\Users\\Hakeem1\\OneDrive\\Desktop\\Cortex_Ai_Agent\\Cortex\\', '')
    line = error['line']
    rule = error.get('rule', 'unknown')
    message = error['message'][:100]
    
    print(f"❌ Error #{i}:")
    print(f"   File: {file_path}:{line}")
    print(f"   Type: {rule}")
    print(f"   Issue: {message}")
    print()
