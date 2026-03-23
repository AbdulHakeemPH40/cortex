"""
Project Indexing Script for Cortex AI Agent IDE.
Indexes all Python files in the project for fast symbol lookup.
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from core.codebase_index import get_codebase_index, SymbolType

def main():
    """Index the entire project."""
    project_root = Path(__file__).parent
    
    print("=" * 60)
    print("Cortex Project Indexer")
    print("=" * 60)
    print(f"\nProject root: {project_root}")
    print("\nStarting indexing process...")
    
    # Get or create index
    index = get_codebase_index(str(project_root))
    
    # Index all files
    files_indexed = index.index_project(force_rebuild=True)
    
    # Get statistics
    stats = index.get_project_stats()
    
    print("\n✅ Indexing complete!")
    print("\n📊 Statistics:")
    print(f"   Files indexed: {stats['files_indexed']}")
    print(f"   Total symbols: {stats['total_symbols']}")
    print("\n   Symbols by type:")
    for sym_type, count in stats['symbols_by_type'].items():
        print(f"      - {sym_type.capitalize()}: {count}")
    
    # Show some examples
    print("\n🔍 Sample indexed symbols:")
    
    # Find classes
    classes = index.find_symbols(sym_type=SymbolType.CLASS)
    if classes:
        print("\n   Classes (first 10):")
        for cls in classes[:10]:
            print(f"      • {cls.name} in {Path(cls.file_path).name}:{cls.line}")
    
    # Find functions
    functions = index.find_symbols(sym_type=SymbolType.FUNCTION)
    if functions:
        print("\n   Functions (first 10):")
        for func in functions[:10]:
            print(f"      • {func.name} in {Path(func.file_path).name}:{func.line}")
    
    print("\n" + "=" * 60)
    print("Index is ready for use by plugins and AI features!")
    print("=" * 60)

if __name__ == "__main__":
    main()
