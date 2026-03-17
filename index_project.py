#!/usr/bin/env python3
"""Script to index the Cortex project."""

import sys
sys.path.insert(0, r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex')

from src.core.codebase_index import get_codebase_index

project_root = r'c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex'
idx = get_codebase_index(project_root)
count = idx.index_project(force_rebuild=True)
stats = idx.get_project_stats()

print(f"Indexed {count} files")
print(f"Total symbols: {stats['total_symbols']}")
print("Symbols by type:")
for t, c in stats['symbols_by_type'].items():
    if c > 0:
        print(f"  {t}: {c}")

# Show some sample symbols
print("\nSample classes found:")
from src.core.codebase_index import SymbolType
classes = idx.find_symbols(sym_type=SymbolType.CLASS)
for cls in classes[:10]:
    print(f"  - {cls.name} at {cls.file_path}:{cls.line}")

print("\nSample functions found:")
functions = idx.find_symbols(sym_type=SymbolType.FUNCTION)
for func in functions[:10]:
    print(f"  - {func.name} at {func.file_path}:{func.line}")
