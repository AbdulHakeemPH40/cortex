"""
Cortex Project Indexer — Builds both symbol index (AST) and semantic index (embeddings).

Usage: python index_project.py [--force] [--symbols-only] [--semantic-only]
"""
import sys
import os
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env for API keys
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[indexer] Loaded .env from {env_path}")
    else:
        print("[indexer] WARNING: No .env file found — semantic index will use hash fallback")
except ImportError:
    print("[indexer] WARNING: python-dotenv not installed — semantic index may use hash fallback")


def run_symbol_index(project_root: str, force: bool = False):
    """Run AST-based codebase symbol index."""
    print("\n" + "=" * 60)
    print("🔍 CODEBASE SYMBOL INDEX (AST)")
    print("=" * 60)

    from src.core.codebase_index import CodebaseIndex

    t0 = time.time()
    idx = CodebaseIndex(project_root)
    num_files = idx.index_project(force_rebuild=force)
    elapsed = time.time() - t0

    stats = idx.get_project_stats()
    print(f"  Files indexed : {stats['files_indexed']}")
    print(f"  Total symbols : {stats['total_symbols']}")
    for sym_type, count in stats['symbols_by_type'].items():
        if count > 0:
            print(f"    {sym_type:12s}: {count}")
    print(f"  Time elapsed  : {elapsed:.1f}s")
    print("✅ Symbol index complete.\n")
    return idx


def run_semantic_index(project_root: str, force: bool = False):
    """Run SiliconFlow-embeddings semantic index."""
    print("\n" + "=" * 60)
    print("🧠 SEMANTIC INDEX (SiliconFlow Embeddings)")
    print("=" * 60)

    from src.core.semantic_search import SemanticSearch

    t0 = time.time()
    searcher = SemanticSearch(project_root)

    model_info = searcher.embeddings_provider.get_model_info()
    mode = "Cloud API" if model_info['has_api_key'] else "Hash fallback (no API key)"
    print(f"  Model         : {model_info['model_name']} ({model_info['dimensions']}d)")
    print(f"  Mode          : {mode}")

    stats = searcher.index_project(force=force)
    elapsed = time.time() - t0

    print(f"  Files indexed : {stats['indexed']}")
    print(f"  Skipped       : {stats['skipped']}")
    print(f"  Errors        : {stats['errors']}")
    print(f"  Total tokens  : {stats['total_tokens']:,}")
    print(f"  Time elapsed  : {elapsed:.1f}s")
    print("✅ Semantic index complete.\n")
    return searcher


def main():
    force = "--force" in sys.argv
    symbols_only = "--symbols-only" in sys.argv
    semantic_only = "--semantic-only" in sys.argv
    run_both = not symbols_only and not semantic_only

    project_root = str(PROJECT_ROOT)
    print(f"📂 Project root: {project_root}")
    print(f"   Force rebuild: {force}")

    if run_both or symbols_only:
        run_symbol_index(project_root, force=force)

    if run_both or semantic_only:
        run_semantic_index(project_root, force=force)

    print("🏁 All indexing complete.")


if __name__ == "__main__":
    main()
