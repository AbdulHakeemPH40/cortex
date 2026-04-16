"""
Index the Cortex AI Agent project.
This script initializes the codebase index and indexes all Python files.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.core.codebase_index import get_codebase_index, SymbolType
from src.core.semantic_search import SemanticSearch

def index_codebase():
    """Index the project codebase."""
    print("=" * 60)
    print("Cortex AI Agent - Project Indexing")
    print("=" * 60)
    print()
    
    # Get the project root
    project_path = str(project_root)
    print(f"Project path: {project_path}")
    print()
    
    # Initialize and build symbol index
    print("Step 1: Building symbol index (AST-based)...")
    print("-" * 60)
    error_files = []
    try:
        index = get_codebase_index(project_path)
        
        # Monkey patch to collect errors
        original_index_file = index._index_file
        def patched_index_file(file_path):
            result = original_index_file(file_path)
            if not result:
                error_files.append(str(file_path))
            return result
        index._index_file = patched_index_file
        
        count = index.index_project(force_rebuild=True)
        print(f"✓ Symbol indexing complete: {count} files indexed")
        
        # Show stats
        stats = index.get_project_stats()
        print(f"  - Files indexed: {stats['files_indexed']}")
        print(f"  - Total symbols: {stats['total_symbols']}")
        print(f"  - Symbols by type:")
        for sym_type, count in stats['symbols_by_type'].items():
            if count > 0:
                print(f"    • {sym_type}: {count}")
        
        # Show error files
        if error_files:
            print(f"\n  ✗ Files with errors ({len(error_files)}):")
            for err_file in error_files:
                print(f"    - {err_file}")
    except Exception as e:
        print(f"✗ Symbol indexing failed: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # Initialize semantic search (optional - requires API key)
    print("Step 2: Building semantic search index (embeddings-based)...")
    print("-" * 60)
    try:
        semantic_search = SemanticSearch(project_path)
        stats = semantic_search.index_project(force=True)
        print(f"✓ Semantic indexing complete:")
        print(f"  - Files indexed: {stats['indexed']}")
        print(f"  - Files skipped: {stats['skipped']}")
        print(f"  - Errors: {stats['errors']}")
        print(f"  - Total tokens: {stats['total_tokens']}")
    except Exception as e:
        print(f"⚠ Semantic indexing skipped: {e}")
        print("  (This is optional and requires SiliconFlow API key)")
    
    print()
    print("=" * 60)
    print("Indexing Complete!")
    print("=" * 60)
    print()
    print("The project is now indexed and ready for:")
    print("  • Symbol search and navigation")
    print("  • Code completion and suggestions")
    print("  • Semantic code search (if embeddings indexed)")
    print("  • AI-powered code understanding")
    print()

if __name__ == "__main__":
    index_codebase()
