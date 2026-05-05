"""
Categorize import errors into 3 types:
1. FILE_NOT_EXISTS - Target file doesn't exist (need to CREATE)
2. FILE_EXISTS_MISSING_FUNC - File exists but function/class is missing (need to ADD)
3. NAME_MISMATCH - camelCase vs snake_case issue (need to FIX name)
"""

import os
import re
from pathlib import Path
from collections import defaultdict

SRC_DIR = Path(__file__).parent

def check_file_and_function(file_path: str, function_name: str = None) -> dict:
    """
    Check if file exists and if function exists in it.
    Returns: {'file_exists': bool, 'func_exists': bool, 'func_names': list}
    """
    full_path = SRC_DIR / file_path
    
    if not full_path.exists():
        return {'file_exists': False, 'func_exists': False, 'func_names': []}
    
    # File exists - check for function
    if function_name:
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find all function/class definitions
            func_pattern = r'^(?:def |class |async def )(\w+)'
            found_names = re.findall(func_pattern, content, re.MULTILINE)
            found_names_lower = [n.lower() for n in found_names]
            
            # Check exact match
            exact_match = function_name in found_names
            
            # Check snake_case version
            snake_version = re.sub(r'([A-Z])', r'_\1', function_name).lower().lstrip('_')
            snake_match = snake_version in found_names_lower
            
            # Check camelCase version  
            camel_version = ''.join(word.capitalize() for word in function_name.split('_'))
            camel_match = camel_version in found_names
            
            return {
                'file_exists': True,
                'func_exists': exact_match,
                'func_names': found_names[:20],  # First 20 for reference
                'snake_match': snake_match,
                'camel_match': camel_match,
                'snake_version': snake_version,
                'camel_version': camel_version
            }
        except Exception as e:
            return {'file_exists': True, 'func_exists': False, 'error': str(e), 'func_names': []}
    
    return {'file_exists': True, 'func_exists': None, 'func_names': []}


def analyze_import_errors():
    """Parse import_errors_report.txt and categorize each error."""
    report_file = SRC_DIR / 'import_errors_report.txt'
    
    with open(report_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    file_not_exists = []        # Need to CREATE the file
    file_exists_missing_func = []  # Need to ADD function
    name_mismatch = []          # Need to FIX name (camelCase vs snake_case)
    
    current_file = None
    
    for line in lines:
        line = line.rstrip()
        
        if line.startswith('[FILE] '):
            current_file = line.replace('[FILE] ', '').strip()
            continue
        
        # Parse: [MISSING NAME] 'func_name' not found in path\file.py
        # or: [MISSING MODULE] .module.path
        if '[MISSING NAME]' in line:
            # Extract function name and file path
            match = re.search(r"'([^']+)' not found in (.+)$", line)
            if match:
                func_name = match.group(1)
                file_path = match.group(2).strip().replace('\\', '/')
                
                result = check_file_and_function(file_path, func_name)
                
                if not result['file_exists']:
                    file_not_exists.append({
                        'file': current_file,
                        'missing_file': file_path,
                        'func_name': func_name,
                        'error_line': line
                    })
                elif result.get('snake_match') or result.get('camel_match'):
                    name_mismatch.append({
                        'file': current_file,
                        'target_file': file_path,
                        'imported_name': func_name,
                        'actual_name': result.get('snake_version') if result.get('snake_match') else result.get('camel_version'),
                        'existing_names': result.get('func_names', [])[:5],
                        'error_line': line
                    })
                else:
                    file_exists_missing_func.append({
                        'file': current_file,
                        'target_file': file_path,
                        'func_name': func_name,
                        'existing_names': result.get('func_names', [])[:5],
                        'error_line': line
                    })
        
        elif '[MISSING MODULE]' in line:
            # Extract module path
            match = re.search(r'\[MISSING MODULE\] (.+)$', line)
            if match:
                module_path = match.group(1).strip()
                # Convert module to file path
                file_path = module_path.lstrip('.').replace('.', '/') + '.py'
                
                result = check_file_and_function(file_path)
                
                if not result['file_exists']:
                    file_not_exists.append({
                        'file': current_file,
                        'missing_file': file_path,
                        'func_name': '(entire module)',
                        'error_line': line
                    })
    
    return file_not_exists, file_exists_missing_func, name_mismatch


def main():
    print("[SCAN] Categorizing import errors by type...")
    
    file_not_exists, file_exists_missing_func, name_mismatch = analyze_import_errors()
    
    total = len(file_not_exists) + len(file_exists_missing_func) + len(name_mismatch)
    
    print(f"\n[RESULTS]")
    print(f"  1. FILE NOT EXISTS (need to CREATE):     {len(file_not_exists)}")
    print(f"  2. FILE EXISTS, MISSING FUNC (need ADD): {len(file_exists_missing_func)}")
    print(f"  3. NAME MISMATCH (need to FIX):          {len(name_mismatch)}")
    print(f"  TOTAL:                                   {total}")
    
    # Write categorized report
    output_file = SRC_DIR / 'import_errors_by_type.txt'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("IMPORT ERRORS BY TYPE - CLEAR BREAKDOWN\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"SUMMARY:\n")
        f.write(f"  1. FILE NOT EXISTS (CREATE file):        {len(file_not_exists)}\n")
        f.write(f"  2. FILE EXISTS, MISSING FUNC (ADD func): {len(file_exists_missing_func)}\n")
        f.write(f"  3. NAME MISMATCH (FIX name):             {len(name_mismatch)}\n")
        f.write(f"  TOTAL:                                   {total}\n\n")
        
        # CATEGORY 1: Files that need to be CREATED
        f.write("=" * 80 + "\n")
        f.write("CATEGORY 1: FILES TO CREATE (file doesn't exist)\n")
        f.write("=" * 80 + "\n\n")
        
        missing_files = defaultdict(list)
        for item in file_not_exists:
            missing_files[item['missing_file']].append(item)
        
        for missing_file, items in sorted(missing_files.items()):
            f.write(f"\n[CREATE] {missing_file}\n")
            f.write(f"  Needed by {len(items)} file(s):\n")
            for item in items[:5]:
                f.write(f"    - {item['file']} (needs: {item['func_name']})\n")
            if len(items) > 5:
                f.write(f"    ... and {len(items) - 5} more\n")
        
        # CATEGORY 2: Functions to ADD (file exists but missing function)
        f.write("\n\n" + "=" * 80 + "\n")
        f.write("CATEGORY 2: FUNCTIONS TO ADD (file exists but function missing)\n")
        f.write("=" * 80 + "\n\n")
        
        missing_funcs = defaultdict(list)
        for item in file_exists_missing_func:
            key = (item['target_file'], item['func_name'])
            missing_funcs[key].append(item)
        
        for (target_file, func_name), items in sorted(missing_funcs.items()):
            f.write(f"\n[ADD TO] {target_file}\n")
            f.write(f"  Missing: {func_name}\n")
            f.write(f"  Existing functions: {items[0].get('existing_names', [])}\n")
            f.write(f"  Needed by: {items[0]['file']}\n")
        
        # CATEGORY 3: Name mismatches (camelCase vs snake_case)
        f.write("\n\n" + "=" * 80 + "\n")
        f.write("CATEGORY 3: NAME MISMATCHES (camelCase vs snake_case)\n")
        f.write("=" * 80 + "\n\n")
        
        for item in name_mismatch:
            f.write(f"\n[NAME FIX] {item['target_file']}\n")
            f.write(f"  Imported as: {item['imported_name']}\n")
            f.write(f"  Actual name: {item['actual_name']}\n")
            f.write(f"  In file: {item['file']}\n")
    
    print(f"\n[REPORT] Written to: {output_file}")
    
    # Print top missing files
    print(f"\n[TOP FILES TO CREATE]")
    missing_files = defaultdict(int)
    for item in file_not_exists:
        missing_files[item['missing_file']] += 1
    for i, (fname, count) in enumerate(sorted(missing_files.items(), key=lambda x: x[1], reverse=True)[:15], 1):
        print(f"  {i:2d}. {fname} (needed by {count} imports)")
    
    print(f"\n[TOP FUNCTIONS TO ADD]")
    missing_funcs = defaultdict(int)
    for item in file_exists_missing_func:
        missing_funcs[(item['target_file'], item['func_name'])] += 1
    for i, ((fname, func), count) in enumerate(sorted(missing_funcs.items(), key=lambda x: x[1], reverse=True)[:15], 1):
        print(f"  {i:2d}. {fname} -> {func} (needed {count}x)")


if __name__ == '__main__':
    main()
