#!/usr/bin/env python3
"""
Cortex Project Indexer
======================
Indexes the codebase for fast semantic search and symbol lookup.

Two-phase indexing:
  1. AST Indexing  -> Symbol extraction (classes, functions, imports, variables)
  2. Embeddings    -> Semantic chunk embeddings via SiliconFlow API (optional)

Usage:
  python index_project.py                        # Full index (AST + embeddings)
  python index_project.py --skip-embeddings       # AST symbols only (fast)
  python index_project.py --force                 # Clear cache & reindex everything
  python index_project.py --path ./src            # Index a specific directory
  python index_project.py --model Qwen/Qwen3-Embedding-8B   # Use larger model

Environment:
  SILICONFLOW_API_KEY  -- Required for embeddings (set in .env)
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any

# -- Ensure the project root is on sys.path ---------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# -- Load .env if present ----------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on system env vars

# -- Project imports ---------------------------------------------------------
from src.core.codebase_index import (
    CodebaseIndex,
    get_codebase_index,
    Symbol,
    SymbolType,
)
from src.core.embeddings import EmbeddingsGenerator
from src.core.semantic_search import SemanticSearch
from src.core.code_chunker import CodeChunker
from src.utils.logger import get_logger

log = get_logger("index_project")


# ============================================================================
#  Phase 1 -- AST Symbol Indexing
# ============================================================================

def index_symbols(project_root: Path, force: bool = False) -> Dict[str, Any]:
    """Run AST-based symbol indexing via CodebaseIndex."""
    print("\n" + "-" * 60)
    print("  [*] Phase 1: AST Symbol Indexing")
    print("-" * 60)

    index = get_codebase_index(str(project_root))
    start = time.time()

    files_indexed = index.index_project(force_rebuild=force)

    elapsed = time.time() - start
    stats = index.get_project_stats()

    print(f"  OK {files_indexed} files indexed successfully")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Stats: {stats['total_symbols']:,} symbols found")
    for sym_type, count in sorted(stats.get("symbols_by_type", {}).items()):
        if count:
            print(f"     - {sym_type}: {count}")

    return stats


# ============================================================================
#  Phase 2 -- Semantic Embedding Indexing
# ============================================================================

def index_embeddings(
    project_root: Path,
    model_name: str = "Qwen/Qwen3-Embedding-4B",
    force: bool = False,
) -> Dict[str, Any]:
    """Run semantic embedding indexing via CodeChunker + EmbeddingsGenerator."""
    print("\n" + "-" * 60)
    print("  [*] Phase 2: Semantic Embedding Indexing")
    print("-" * 60)

    # Check API key
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        print("  WARN SILICONFLOW_API_KEY not set -- skipping embeddings")
        print("       Set it in .env or as an environment variable")
        return {"skipped": True, "reason": "missing_api_key"}

    chunker = CodeChunker()
    generator = EmbeddingsGenerator(model_name=model_name)
    searcher = SemanticSearch(project_root=str(project_root))

    start = time.time()

    # Collect all supported source files
    supported_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx",
        ".java", ".go", ".rs", ".cpp", ".c", ".h", ".hpp",
    }
    source_files = []
    for ext in supported_extensions:
        source_files.extend(project_root.rglob(f"*{ext}"))

    source_files = [
        f for f in source_files
        if not any(part.startswith((".", "__pycache__", "node_modules", "venv"))
                   for part in f.parts)
    ]

    print(f"  Found: {len(source_files)} source files to chunk")

    # Phase 2a -- Chunk all files
    all_chunks = []
    chunk_failures = 0
    for i, file_path in enumerate(source_files):
        try:
            chunks = chunker.chunk_file(str(file_path))
            all_chunks.extend(chunks)
        except Exception as e:
            chunk_failures += 1
            log.debug(f"Chunk failed for {file_path}: {e}")

        if (i + 1) % 20 == 0 or (i + 1) == len(source_files):
            print(
                f"  ... Chunking: {i + 1}/{len(source_files)} files "
                f"-> {len(all_chunks)} chunks",
                end="\r",
            )

    print(f"\n  Chunks: {len(all_chunks)} semantic chunks created "
          f"({chunk_failures} failures)")

    if not all_chunks:
        print("  WARN No chunks to embed -- skipping")
        return {"skipped": True, "reason": "no_chunks"}

    # Phase 2b -- Generate embeddings in batches
    BATCH_SIZE = 32
    total_tokens = 0
    embedded_count = 0
    embed_failures = 0

    batches = [
        all_chunks[i:i + BATCH_SIZE]
        for i in range(0, len(all_chunks), BATCH_SIZE)
    ]

    for batch_idx, batch in enumerate(batches):
        try:
            texts = [chunk.code for chunk in batch]
            results = generator.embed_batch(texts)

            for chunk, result in zip(batch, results):
                if result.success:
                    searcher.add_embedding(
                        chunk=chunk,
                        embedding=result.embedding,
                    )
                    embedded_count += 1
                    total_tokens += result.tokens_used
                else:
                    embed_failures += 1

        except Exception as e:
            log.error(f"Batch {batch_idx} failed: {e}")
            embed_failures += len(batch)

        progress = min((batch_idx + 1) * BATCH_SIZE, len(all_chunks))
        print(
            f"  ... Embedding: {progress}/{len(all_chunks)} chunks "
            f"-> {embedded_count} ok",
            end="\r",
        )

    elapsed = time.time() - start
    print(f"\n  OK {embedded_count}/{len(all_chunks)} chunks embedded "
          f"({embed_failures} failures)")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Tokens: {total_tokens:,} used")

    return {
        "chunks": len(all_chunks),
        "embedded": embedded_count,
        "failures": embed_failures,
        "tokens": total_tokens,
        "time": elapsed,
    }


# ============================================================================
#  Main CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Cortex Project Indexer -- AST symbols + semantic embeddings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python index_project.py                         # Full index
  python index_project.py --skip-embeddings        # Symbols only (fast)
  python index_project.py --force                  # Clear cache & reindex
  python index_project.py --path ./src             # Specific directory
  python index_project.py --model Qwen/Qwen3-Embedding-8B
        """,
    )
    parser.add_argument(
        "--path", type=str, default=None,
        help="Project root directory (default: current directory)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force reindex even if cache exists",
    )
    parser.add_argument(
        "--skip-ast", action="store_true",
        help="Skip AST symbol indexing (Phase 1)",
    )
    parser.add_argument(
        "--skip-embeddings", action="store_true",
        help="Skip semantic embedding indexing (Phase 2)",
    )
    parser.add_argument(
        "--model", type=str, default="Qwen/Qwen3-Embedding-4B",
        choices=[
            "Qwen/Qwen3-Embedding-0.6B",
            "Qwen/Qwen3-Embedding-4B",
            "Qwen/Qwen3-Embedding-8B",
        ],
        help="SiliconFlow embedding model (default: Qwen3-Embedding-4B)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show debug-level logging",
    )

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    project_root = Path(args.path).resolve() if args.path else PROJECT_ROOT

    print("=" * 60)
    print("  [CORTEX] PROJECT INDEXER")
    print("=" * 60)
    print(f"  Path   : {project_root}")
    print(f"  Force  : {'yes' if args.force else 'no'}")
    print(f"  AST    : {'skip' if args.skip_ast else 'enabled'}")
    print(f"  Embeds : "
          f"{'skip' if args.skip_embeddings else f'enabled ({args.model})'}")

    overall_start = time.time()
    results: Dict[str, Any] = {}

    # -- Phase 1: AST Symbols -------------------------------------------------
    if not args.skip_ast:
        try:
            results["ast"] = index_symbols(project_root, force=args.force)
        except Exception as e:
            print(f"\n  ERROR AST indexing failed: {e}")
            log.exception("AST indexing error")
            results["ast"] = {"error": str(e)}

    # -- Phase 2: Semantic Embeddings -----------------------------------------
    if not args.skip_embeddings:
        try:
            results["embeddings"] = index_embeddings(
                project_root,
                model_name=args.model,
                force=args.force,
            )
        except Exception as e:
            print(f"\n  ERROR Embedding indexing failed: {e}")
            log.exception("Embedding indexing error")
            results["embeddings"] = {"error": str(e)}

    # -- Summary --------------------------------------------------------------
    total_elapsed = time.time() - overall_start
    print("\n" + "=" * 60)
    print("  [OK] INDEXING COMPLETE")
    print("=" * 60)
    print(f"  Total time: {total_elapsed:.2f}s")

    ast_stats = results.get("ast", {})
    if isinstance(ast_stats, dict) and "total_symbols" in ast_stats:
        print(f"  Symbols indexed: {ast_stats['total_symbols']:,} "
              f"across {ast_stats.get('files_indexed', 0)} files")

    emb_stats = results.get("embeddings", {})
    if isinstance(emb_stats, dict) and emb_stats.get("embedded"):
        print(f"  Chunks embedded: {emb_stats['embedded']:,} "
              f"({emb_stats['tokens']:,} tokens)")

    print()

    return 0 if "error" not in str(results) else 1


if __name__ == "__main__":
    sys.exit(main())
