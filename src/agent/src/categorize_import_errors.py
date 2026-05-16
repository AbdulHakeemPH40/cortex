"""
Categorize import errors into:
1. ALREADY_CONVERTED_BUT_BROKEN - File exists as .py but wrong import path/function name
2. NOT_YET_CONVERTED - File doesn't exist as .py yet (needs TypeScript conversion)
"""

import os
from pathlib import Path

SRC_DIR = Path(__file__).parent

def is_py_file_exists(module_path: str) -> bool:
    """Check if a .py file exists for the given module path."""
    # Convert module path to file path
    parts = module_path.replace('\\', '/').split('/')
    
    # Try different extensions
    base_path = SRC_DIR / '/'.join(parts)
    
    # Check if it's a module (directory with __init__.py)
    if (base_path / '__init__.py').exists():
        return True
    
    # Check if it's a direct .py file
    if base_path.with_suffix('.py').exists():
        return True
    
    # Handle nested paths like "tools/AgentTool/load_agents_dir"
    # The last part might be the filename
    if len(parts) > 1:
        dir_path = SRC_DIR / '/'.join(parts[:-1])
        file_name = parts[-1] + '.py'
        if (dir_path / file_name).exists():
            return True
    
    return False


def analyze_import_errors():
    """Parse import_errors_report.txt and categorize each error."""
    report_file = SRC_DIR / 'import_errors_report.txt'
    
    with open(report_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    already_converted_broken = []  # File exists but import is wrong
    not_yet_converted = []         # File doesn't exist yet
    
    current_file = None
    
    for line in lines:
        line = line.rstrip()
        
        # Track current file being analyzed
        if line.startswith('[FILE] '):
            current_file = line.replace('[FILE] ', '').strip()
            continue
        
        # Look for [MISSING MODULE] or [MISSING NAME] errors
        if '[MISSING MODULE]' in line or '[MISSING NAME]' in line:
            # Extract the file path from "not found in <path>"
            if 'not found in ' in line:
                # Format: [MISSING NAME] 'func' not found in utils\config.py
                module_path = line.split('not found in ')[1].strip()
                
                # Convert to file path (handle both backslash and forward slash)
                file_path_str = module_path.replace('\\', '/')
                
                # Check if the .py file exists
                full_path = SRC_DIR / file_path_str
                
                if full_path.exists():
                    # File exists - import is broken
                    already_converted_broken.append({
                        'file': current_file,
                        'module': module_path,
                        'error_line': line.strip()
                    })
                else:
                    # File doesn't exist - needs conversion
                    not_yet_converted.append({
                        'file': current_file,
                        'module': module_path,
                        'error_line': line.strip()
                    })
    
    return already_converted_broken, not_yet_converted


def main():
    print("[SCAN] Analyzing import errors...")
    
    already_broken, not_converted = analyze_import_errors()
    
    print(f"\n[RESULTS]")
    print(f"  Already converted but BROKEN imports: {len(already_broken)}")
    print(f"  Not yet converted (need .py file):    {len(not_converted)}")
    
    # Write categorized report
    output_file = SRC_DIR / 'import_errors_categorized.txt'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("CATEGORIZED IMPORT ERRORS\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"Total already-converted-but-broken: {len(already_broken)}\n")
        f.write(f"Total not-yet-converted: {len(not_converted)}\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("CATEGORY 1: ALREADY CONVERTED BUT BROKEN IMPORTS\n")
        f.write("(File exists as .py but import path or function name is wrong)\n")
        f.write("=" * 80 + "\n\n")
        
        current_file = None
        for item in already_broken:
            if item['file'] != current_file:
                current_file = item['file']
                f.write(f"\n[FILE] {current_file}\n")
            f.write(f"  {item['error_line']}\n")
        
        f.write("\n\n" + "=" * 80 + "\n")
        f.write("CATEGORY 2: NOT YET CONVERTED\n")
        f.write("(Need TypeScript to Python conversion)\n")
        f.write("=" * 80 + "\n\n")
        
        current_file = None
        for item in not_converted:
            if item['file'] != current_file:
                current_file = item['file']
                f.write(f"\n[FILE] {current_file}\n")
            f.write(f"  {item['error_line']}\n")
    
    print(f"\n[REPORT] Written to: {output_file}")
    
    # Print top broken files for quick action
    print(f"\n[TOP BROKEN FILES TO FIX NOW]")
    broken_by_file = {}
    for item in already_broken:
        if item['file'] not in broken_by_file:
            broken_by_file[item['file']] = 0
        broken_by_file[item['file']] += 1
    
    sorted_files = sorted(broken_by_file.items(), key=lambda x: x[1], reverse=True)
    for i, (fname, count) in enumerate(sorted_files[:20], 1):
        print(f"  {i:2d}. {fname} ({count} broken imports)")


if __name__ == '__main__':
    main()
