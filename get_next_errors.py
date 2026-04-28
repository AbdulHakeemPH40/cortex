#!/usr/bin/env python3
"""Get the next 10 easiest errors to fix from the latest report."""
import json
from pathlib import Path

def get_next_errors(report_path='pyright_report_latest.json', count=10):
    """Get the next batch of errors to fix."""
    
    with open(report_path, 'r') as f:
        data = json.load(f)
    
    errors = [d for d in data['diagnostics'] if d['severity'] == 'error']
    
    # Skip the ones we already fixed (oauth.py and systemPromptSections.py)
    skip_files = [
        'oauth.py',
        'systemPromptSections.py'
    ]
    
    filtered_errors = [
        e for e in errors 
        if not any(skip in e['file'] for skip in skip_files)
    ]
    
    # Group by rule type
    by_rule = {}
    for error in filtered_errors:
        rule = error.get('rule', 'unknown')
        if rule not in by_rule:
            by_rule[rule] = []
        by_rule[rule].append(error)
    
    # Priority: undefined variables first (easiest)
    priority_order = [
        'reportUndefinedVariable',
        'reportMissingImports',
        'reportOptionalMemberAccess',
        'reportAssignmentType',
        'reportReturnType',
        'reportCallIssue',
    ]
    
    easiest = []
    for rule in priority_order:
        if rule in by_rule:
            easiest.extend(by_rule[rule])
        if len(easiest) >= count:
            break
    
    return easiest[:count]


def main():
    print("=" * 70)
    print("📝 WEEK 1 - DAY 2 TASKS (Fix remaining 9 errors)")
    print("=" * 70)
    print()
    
    try:
        errors = get_next_errors()
    except FileNotFoundError:
        print("⚠️  Run: python pyright_audit.py --json-out pyright_report_latest.json")
        return
    
    print(f"🎯 Fix these {len(errors)} errors:\n")
    
    for i, error in enumerate(errors, 1):
        file_path = error['file'].replace('c:\\Users\\Hakeem1\\OneDrive\\Desktop\\Cortex_Ai_Agent\\Cortex\\', '')
        line = error['line']
        rule = error.get('rule', 'unknown')
        message = error['message'][:120]
        
        print(f"❌ Error #{i}:")
        print(f"   File: {file_path}:{line}")
        print(f"   Type: {rule}")
        print(f"   Issue: {message}")
        
        # Suggest fix
        if 'reportUndefinedVariable' in rule:
            print(f"   💡 Fix: Add import or define the missing variable/type")
        elif 'reportMissingImports' in rule:
            print(f"   💡 Fix: Create stub file or add the import")
        elif 'reportOptionalMemberAccess' in rule:
            print(f"   💡 Fix: Add None check before accessing attribute")
        elif 'reportAssignmentType' in rule:
            print(f"   💡 Fix: Correct the type annotation")
        elif 'reportReturnType' in rule:
            print(f"   💡 Fix: Add correct return type")
        elif 'reportCallIssue' in rule:
            print(f"   💡 Fix: Check function arguments")
        
        print()
    
    print("=" * 70)
    print("💡 Week 1 Target: Fix 9 more errors to reach 15 total")
    print("=" * 70)


if __name__ == '__main__':
    main()
