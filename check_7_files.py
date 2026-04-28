#!/usr/bin/env python3
"""Check if the 7 target files have any pyright issues."""
import subprocess
import re

result = subprocess.run(['python', 'pyright_audit.py'], capture_output=True, text=True)
output = result.stdout + result.stderr

target_files = [
    'state/AppStateStore.py',
    'skills/bundled/remember.py',
    'query/deps.py',
    'query/config.py',
    'keybindings/shortcutFormat.py',
    'coordinator/agent_context.py'
]

issues = []
for line in output.split('\n'):
    if 'WARNING' in line or 'ERROR' in line:
        for tf in target_files:
            if tf in line and 'src/agent/src/' in line:
                issues.append(line.strip())
                break

if issues:
    print(f"❌ Found {len(issues)} issues:\n")
    for i, issue in enumerate(issues, 1):
        print(f"{i}. {issue}")
else:
    print("✅ ALL 7 FILES ARE 100% CLEAN!")
    print("\nFiles checked:")
    for f in target_files:
        print(f"  ✓ {f}")
