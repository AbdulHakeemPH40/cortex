"""
Cortex IDE Terminology Cleanup Script

Scans entire Python codebase for outdated references and fixes them:
- "AI agent" → "AI agent" / "Cortex IDE"
- "claude-code" → "cortex-ide"
- "cloud"/"claude.ai" → "cloud" (for multi-LLM architecture)
- "runtime arguments" → "runtime arguments"
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Tuple

# Configuration
SRC_DIR = r"C:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\claude-code-main\claude-code-main\src"

# Patterns to find and replace (order matters - more specific first)
REPLACEMENTS = [
    # Multi-LLM architecture updates
    (r"'cloud'", "'cloud'", "Config scope name"),
    (r'"cloud"', '"cloud"', "Config scope name"),
    (r"cloud_ai_", "cloud_ai_", "Cloud AI service prefix"),
    
    # AI agent → AI Agent/Cortex IDE
    (r"Cortex IDE", "Cortex IDE", "Product name"),
    (r"Cortex IDE", "Cortex IDE", "Product name"),
    (r"\bCLI\b", "AI agent", "General AI agent reference (careful!)"),
    (r"AI agent binary", "Cortex IDE distribution", "Binary reference"),
    (r"AI agent session", "agent session", "Session reference"),
    (r"AI agent tool", "AI agent tool", "Tool reference"),
    (r"AI agent context", "AI agent context", "Context reference"),
    (r"AI agent TUI", "GUI interface", "Interface reference"),
    (r"AI agent result", "result", "Result reference"),
    (r"AI agent-managed", "AI agent-managed", "Management reference"),
    (r"AI agent exits", "agent session initializes", "Lifecycle reference"),
    (r"AI agent requires", "Cortex IDE requires", "Requirement reference"),
    (r"AI agent with no editor", "headless AI agent with no editor", "Mode reference"),
    (r"compiled into the AI agent", "included with Cortex IDE", "Distribution reference"),
    (r"ships with the AI agent", "ships with Cortex IDE", "Distribution reference"),
    (r"runtime arguments", "runtime arguments", "Argument reference"),
    (r"runtime", "runtime", "Argument reference"),
    (r"from runtime arguments", "from runtime arguments", "Argument source"),
    
    # Mode tracking
    (r"'mode': 'gui'", "'mode': 'gui'", "Mode enum"),
    (r'"mode": "gui"', '"mode": "gui"', "Mode enum"),
    
    # App identification
    (r"'x-app': 'cortex-ide'", "'x-app': 'cortex-ide'", "API header"),
    (r'"x-app": "cortex-ide"', '"x-app": "cortex-ide"', "API header"),
]

# Patterns to SKIP (valid technical terms)
SKIP_PATTERNS = [
    r"cliArg",  # Valid permission source (means "startup arguments")
    r"llm_client",  # Valid LLM API client
    r"create_process",  # Valid subprocess call
    r"process_id",  # Valid process reference
    r"client_id",  # Valid OAuth client
    r"mobile clients",  # Valid GUI client apps
    r"PushNotificationClient",  # Valid client class
]


def should_skip_line(line: str) -> bool:
    """Check if line contains valid technical terms that shouldn't be changed."""
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def find_python_files(directory: str) -> List[str]:
    """Find all Python files in directory."""
    python_files = []
    for root, dirs, files in os.walk(directory):
        # Skip test files and hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'node_modules']
        
        for file in files:
            if file.endswith('.py') and not file.startswith('test_') and not file.startswith('verify_'):
                python_files.append(os.path.join(root, file))
    
    return sorted(python_files)


def scan_file_for_patterns(file_path: str) -> List[Tuple[int, str, str, str]]:
    """Scan file for patterns that need updating."""
    matches = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            if should_skip_line(line):
                continue
            
            for pattern, replacement, description in REPLACEMENTS:
                if re.search(pattern, line):
                    matches.append((line_num, line.strip(), description, pattern))
                    break  # Only report first match per line
    except Exception as e:
        print(f"  ⚠️  Error reading {file_path}: {e}")
    
    return matches


def fix_file(file_path: str) -> Tuple[int, List[str]]:
    """Fix all patterns in file. Returns (count, changes_made)."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        changes = []
        
        for pattern, replacement, description in REPLACEMENTS:
            if re.search(pattern, content):
                # Count occurrences
                count = len(re.findall(pattern, content))
                content = re.sub(pattern, replacement, content)
                changes.append(f"  ✓ {description}: {count} occurrence(s)")
        
        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return len(changes), changes
        
        return 0, []
    
    except Exception as e:
        print(f"  ❌ Error fixing {file_path}: {e}")
        return 0, []


def main():
    """Main cleanup function."""
    print("="*80)
    print("CORTEX IDE TERMINOLOGY CLEANUP")
    print("="*80)
    print(f"\n📁 Scanning: {SRC_DIR}")
    print(f"🔍 Looking for: AI agent, claude-code, claudeai, runtime references")
    print(f"⏭️  Skipping: cliArg, llm_client, mobile clients (valid terms)")
    print()
    
    # Step 1: Find all Python files
    print("[1/3] Finding Python files...")
    python_files = find_python_files(SRC_DIR)
    print(f"  Found {len(python_files)} Python files")
    print()
    
    # Step 2: Scan for issues
    print("[2/3] Scanning for outdated references...")
    all_issues = {}
    total_issues = 0
    
    for file_path in python_files:
        rel_path = os.path.relpath(file_path, SRC_DIR)
        matches = scan_file_for_patterns(file_path)
        
        if matches:
            all_issues[rel_path] = matches
            total_issues += len(matches)
    
    if total_issues == 0:
        print("  ✅ No outdated references found!")
        print("\n" + "="*80)
        print("CLEANUP COMPLETE - All references are already up-to-date!")
        print("="*80)
        return
    
    print(f"  Found {total_issues} outdated reference(s) in {len(all_issues)} file(s)")
    print()
    
    # Show summary
    print("📋 Issues found:")
    for rel_path, matches in sorted(all_issues.items()):
        print(f"\n  📄 {rel_path}")
        for line_num, line, desc, pattern in matches:
            print(f"    Line {line_num}: [{desc}] {line[:100]}")
    
    print()
    
    # Step 3: Auto-fix (non-interactive mode)
    print("\n[3/3] Fixing outdated references... (non-interactive mode)")
    files_fixed = 0
    total_fixes = 0
    
    for rel_path in sorted(all_issues.keys()):
        file_path = os.path.join(SRC_DIR, rel_path)
        count, changes = fix_file(file_path)
        
        if count > 0:
            files_fixed += 1
            total_fixes += count
            print(f"\n  ✅ {rel_path}")
            for change in changes:
                print(f"    {change}")
    
    # Final summary
    print("\n" + "="*80)
    print(f"✅ CLEANUP COMPLETE!")
    print("="*80)
    print(f"  Files modified: {files_fixed}")
    print(f"  References fixed: {total_fixes}")
    print(f"  Files scanned: {len(python_files)}")
    print()
    print("📝 Summary of changes:")
    print("  • 'AI agent' → 'AI agent' / 'Cortex IDE' (context-aware)")
    print("  • 'cloud' → 'cloud' (multi-LLM architecture)")
    print("  • 'cloud_ai_' → 'cloud_ai_' (service prefix)")
    print("  • 'runtime arguments' → 'runtime arguments'")
    print("  • 'mode: cli' → 'mode: gui'")
    print("  • 'x-app: cli' → 'x-app: cortex-ide'")
    print()
    print("✅ Preserved (valid technical terms):")
    print("  • cliArg (permission source = startup arguments)")
    print("  • llm_client (LLM API client)")
    print("  • mobile clients (GUI client apps)")
    print("="*80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Cleanup interrupted by user")
    except Exception as e:
        print(f"\n❌ Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
