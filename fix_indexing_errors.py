"""
Fix indexing errors in the project.
1. Remove BOM from Python files
2. Identify and fix semantic indexing errors
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def fix_bom_issues():
    """Remove UTF-8 BOM from Python files."""
    print("=" * 60)
    print("Fix 1: Removing UTF-8 BOM from Python files")
    print("=" * 60)
    print()
    
    bom_count = 0
    # Find all Python files
    for py_file in project_root.rglob("*.py"):
        # Skip excluded directories
        exclude_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'build', 'dist'}
        if any(exclude in str(py_file) for exclude in exclude_dirs):
            continue
            
        try:
            with open(py_file, 'rb') as f:
                content = f.read()
            
            # Check for BOM
            if content.startswith(b'\xef\xbb\xbf'):
                # Remove BOM
                with open(py_file, 'wb') as f:
                    f.write(content[3:])
                print(f"  ✓ Removed BOM from: {py_file.relative_to(project_root)}")
                bom_count += 1
        except Exception as e:
            print(f"  ✗ Error processing {py_file}: {e}")
    
    print()
    print(f"Total files fixed: {bom_count}")
    print()
    return bom_count

def identify_semantic_errors():
    """Identify files that failed semantic indexing."""
    print("=" * 60)
    print("Fix 2: Identifying semantic indexing errors")
    print("=" * 60)
    print()
    
    from src.core.semantic_search import SemanticSearch
    
    project_path = str(project_root)
    semantic_search = SemanticSearch(project_path)
    
    # Find all files that should be indexed
    files_to_check = []
    for ext in ['*.py', '*.js', '*.ts', '*.java', '*.go', '*.rs']:
        files_to_check.extend(project_root.rglob(ext))
    
    # Filter out excluded directories
    exclude_dirs = {
        '.git', '__pycache__', 'node_modules', 'venv', '.venv',
        'build', 'dist', '.tox', '.pytest_cache', '.mypy_cache'
    }
    
    error_files = []
    checked = 0
    
    for file_path in files_to_check:
        # Skip excluded directories
        if any(exclude in str(file_path) for exclude in exclude_dirs):
            continue
        
        # Try to index this file
        try:
            result = semantic_search.index_file(str(file_path), force=True)
            if not result:
                error_files.append(str(file_path))
                print(f"  ✗ Failed: {file_path.relative_to(project_root)}")
        except Exception as e:
            error_files.append(str(file_path))
            print(f"  ✗ Exception: {file_path.relative_to(project_root)} - {e}")
        
        checked += 1
    
    print()
    print(f"Checked: {checked} files")
    print(f"Errors: {len(error_files)} files")
    print()
    
    return error_files

def fix_empty_init_files():
    """Add minimal content to empty __init__.py files so they can be indexed."""
    print("=" * 60)
    print("Fix 3: Adding content to empty __init__.py files")
    print("=" * 60)
    print()
    
    fixed_count = 0
    
    # Find all __init__.py files
    for init_file in project_root.rglob("__init__.py"):
        # Skip excluded directories
        exclude_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'build', 'dist'}
        if any(exclude in str(init_file) for exclude in exclude_dirs):
            continue
        
        try:
            with open(init_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            # If file is empty or just whitespace, add module docstring
            if not content:
                # Get relative path for the docstring
                rel_path = init_file.relative_to(project_root)
                module_name = str(rel_path).replace('/', '.').replace('\\', '.').replace('.__init__.py', '')
                
                # Add a simple docstring
                docstring = f'"""{module_name} module."""\n'
                
                with open(init_file, 'w', encoding='utf-8') as f:
                    f.write(docstring)
                
                print(f"  ✓ Added content to: {rel_path}")
                fixed_count += 1
        except Exception as e:
            print(f"  ✗ Error processing {init_file}: {e}")
    
    # Also fix test.py if it's empty
    test_file = project_root / "test.py"
    if test_file.exists():
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if not content:
                with open(test_file, 'w', encoding='utf-8') as f:
                    f.write('# Test file for Cortex AI Agent\n')
                print(f"  ✓ Added content to: test.py")
                fixed_count += 1
        except Exception as e:
            print(f"  ✗ Error processing test.py: {e}")
    
    print()
    print(f"Total files fixed: {fixed_count}")
    print()
    return fixed_count

def main():
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "Cortex AI Agent - Error Fixer" + " " * 19 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    # Fix 1: BOM issues
    bom_fixed = fix_bom_issues()
    
    # Fix 2: Empty init files
    empty_fixed = fix_empty_init_files()
    
    # Fix 3: Identify remaining semantic errors
    error_files = identify_semantic_errors()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print()
    print(f"BOM issues fixed: {bom_fixed}")
    print(f"Empty files fixed: {empty_fixed}")
    print(f"Remaining semantic indexing errors: {len(error_files)}")
    
    if error_files:
        print()
        print("Remaining error files:")
        for ef in error_files[:20]:  # Show first 20
            print(f"  - {ef}")
        if len(error_files) > 20:
            print(f"  ... and {len(error_files) - 20} more")
    
    print()
    if not error_files:
        print("All indexing errors have been fixed!")
    else:
        print("Run index_project.py again to verify fixes")
    print()

if __name__ == "__main__":
    main()
