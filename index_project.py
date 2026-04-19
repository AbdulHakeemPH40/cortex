#!/usr/bin/env python3
"""
Standalone script to index the Cortex AI Agent project.
"""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.codebase_index import get_codebase_index
from src.utils.logger import get_logger

log = get_logger("index_project")

def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    log.info(f"Indexing project: {project_root}")
    
    # Create/get codebase index
    index = get_codebase_index(project_root)
    
    # Index the project (force rebuild)
    count = index.index_project(force_rebuild=True)
    
    # Get stats
    stats = index.get_project_stats()
    
    print(f"\n{'='*50}")
    print(f"Indexing Complete!")
    print(f"{'='*50}")
    print(f"Files indexed: {stats['files_indexed']}")
    print(f"Total symbols: {stats['total_symbols']}")
    print(f"\nSymbols by type:")
    for sym_type, count in stats['symbols_by_type'].items():
        if count > 0:
            print(f"  - {sym_type}: {count}")
    print(f"{'='*50}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
