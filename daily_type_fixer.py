#!/usr/bin/env python3
"""
Daily type fixing helper.
Shows 5 easiest errors to fix today.
"""
import json
import random
from pathlib import Path
from collections import Counter

def get_easiest_errors(report_path='pyright_report_new.json', count=5):
    """Get the easiest errors to fix (sorted by simplicity)."""
    
    with open(report_path, 'r') as f:
        data = json.load(f)
    
    errors = [d for d in data['diagnostics'] if d['severity'] == 'error']
    
    # Priority order (easiest first)
    priority_rules = [
        'reportMissingImports',      # Create stub (easy)
        'reportUndefinedVariable',   # Add import/definition
        'reportOptionalMemberAccess', # Add None check
        'reportAssignmentType',      # Fix type hint
        'reportReturnType',          # Add return type
    ]
    
    # Group by rule
    by_rule = {}
    for error in errors:
        rule = error.get('rule', 'unknown')
        if rule not in by_rule:
            by_rule[rule] = []
        by_rule[rule].append(error)
    
    # Get easiest errors
    easiest = []
    for rule in priority_rules:
        if rule in by_rule and len(easiest) < count:
            easiest.extend(by_rule[rule][:count - len(easiest)])
    
    return easiest[:count]


def show_daily_tasks():
    """Show today's type fixing tasks."""
    
    print("=" * 70)
    print("📝 TODAY'S TYPE FIXING TASKS (15 minutes)")
    print("=" * 70)
    
    try:
        errors = get_easiest_errors()
    except FileNotFoundError:
        print("\n⚠️  Run: python pyright_audit.py --json-out pyright_report_new.json")
        return
    
    print(f"\n🎯 Fix these {len(errors)} errors today:\n")
    
    for i, error in enumerate(errors, 1):
        file_path = error['file'].replace('c:\\Users\\Hakeem1\\OneDrive\\Desktop\\Cortex_Ai_Agent\\Cortex\\', '')
        line = error['line']
        rule = error.get('rule', 'unknown')
        message = error['message'][:100]
        
        print(f"❌ Error #{i}:")
        print(f"   File: {file_path}:{line}")
        print(f"   Type: {rule}")
        print(f"   Issue: {message}")
        
        # Suggest fix
        if 'reportMissingImports' in rule:
            print(f"   💡 Fix: Create stub file or add import")
        elif 'reportUndefinedVariable' in rule:
            print(f"   💡 Fix: Add import or define variable")
        elif 'reportOptionalMemberAccess' in rule:
            print(f"   💡 Fix: Add None check before accessing attribute")
        elif 'reportAssignmentType' in rule:
            print(f"   💡 Fix: Correct type annotation")
        elif 'reportReturnType' in rule:
            print(f"   💡 Fix: Add correct return type hint")
        
        print()
    
    print("=" * 70)
    print("💡 TIP: Fix one error, test, commit. Repeat!")
    print("=" * 70)


def track_progress():
    """Show progress over time."""
    
    reports = [
        'pyright_report.json',
        'pyright_report_final.json',
        'pyright_report_v2.json',
        'pyright_report_new.json'
    ]
    
    print("=" * 70)
    print("📊 TYPE FIXING PROGRESS")
    print("=" * 70)
    print()
    
    for report in reports:
        path = Path(report)
        if path.exists():
            data = json.load(open(path))
            errors = data['summary']['errorCount']
            print(f"✓ {report:30s} {errors:5d} errors")
    
    print()
    print("=" * 70)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--progress':
        track_progress()
    else:
        show_daily_tasks()
