#!/usr/bin/env python3
"""
Cortex Project Indexer — Builds both symbol index (AST) and semantic index (embeddings).

Usage:
    python index_project.py [--force] [--symbols-only] [--semantic-only]
"""

import argparse
import sys
import time
import traceback
from pathlib import Path
from typing import List, Optional

# Ensure project root is on sys.path before any project imports
_PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(_PROJECT_ROOT))


def _load_environment() -> None:
    """Attempt to load environment variables from a .env file."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        print(
            "[indexer] WARNING: python-dotenv not installed — "
            "semantic index may use hash fallback"
        )
        return

    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[indexer] Loaded .env from {env_path}")
    else:
        print(
            "[indexer] WARNING: No .env file found — "
            "semantic index will use hash fallback"
        )


# Load env at import time so project internals see the variables
_load_environment()


def _print_section(title: str, icon: str = "") -> None:
    """Print a formatted section header to stdout."""
    prefix = f"{icon} " if icon else ""
    print("\n" + "=" * 60)
    print(f"{prefix}{title}")
    print("=" * 60)


def _format_elapsed(start: float) -> str:
    """Return elapsed time since *start* in seconds."""
    return f"{time.perf_counter() - start:.1f}s"


def _verify_src_package() -> None:
    """Raise ImportError early if the src package isn't on sys.path."""
    src_init = _PROJECT_ROOT / "src" / "__init__.py"
    if not src_init.exists():
        raise ImportError(
            f"Cannot find src package at {_PROJECT_ROOT / 'src'}. "
            "Make sure you run this script from the project root."
        )


def run_symbol_index(project_root: Path, *, force: bool = False) -> object:
    """Run the AST-based codebase symbol index.

    Args:
        project_root: Root directory of the project to index.
        force: Force a full rebuild of the symbol index.

    Returns:
        The instantiated ``CodebaseIndex``.

    Raises:
        Exception: Any error raised by the indexing engine is propagated.
    """
    _print_section("CODEBASE SYMBOL INDEX (AST)", "[AST]")
    _verify_src_package()

    # Lazy import avoids heavy dependencies when this phase is skipped.
    from src.core.codebase_index import CodebaseIndex

    start = time.perf_counter()
    indexer = CodebaseIndex(str(project_root))
    indexer.index_project(force_rebuild=force)
    elapsed = _format_elapsed(start)

    stats = indexer.get_project_stats()
    print(f"  Files indexed : {stats.get('files_indexed', 0)}")
    print(f"  Total symbols : {stats.get('total_symbols', 0)}")
    for sym_type, count in stats.get("symbols_by_type", {}).items():
        if count:
            print(f"    {sym_type:12s}: {count}")
    print(f"  Time elapsed  : {elapsed}")
    print("[OK] Symbol index complete.\n")
    return indexer


def run_semantic_index(project_root: Path, *, force: bool = False) -> object:
    """Run the SiliconFlow-embeddings semantic index.

    Args:
        project_root: Root directory of the project to index.
        force: Force a full rebuild of the semantic index.

    Returns:
        The instantiated ``SemanticSearch``.

    Raises:
        Exception: Any error raised by the indexing engine is propagated.
    """
    _print_section("SEMANTIC INDEX (SiliconFlow Embeddings)", "[SEMANTIC]")
    _verify_src_package()

    # Lazy import avoids loading embedding models when this phase is skipped.
    from src.core.semantic_search import SemanticSearch

    start = time.perf_counter()
    searcher = SemanticSearch(str(project_root))

    model_info = searcher.embeddings_provider.get_model_info()
    mode = (
        "Cloud API"
        if model_info.get("has_api_key")
        else "Hash fallback (no API key)"
    )
    print(
        f"  Model         : {model_info.get('model_name', 'unknown')} "
        f"({model_info.get('dimensions', '?')}d)"
    )
    print(f"  Mode          : {mode}")

    stats = searcher.index_project(force=force)
    elapsed = _format_elapsed(start)

    print(f"  Files indexed : {stats.get('indexed', 0)}")
    print(f"  Skipped       : {stats.get('skipped', 0)}")
    print(f"  Errors        : {stats.get('errors', 0)}")
    print(f"  Total tokens  : {stats.get('total_tokens', 0):,}")
    print(f"  Time elapsed  : {elapsed}")
    print("Semantic index complete.\n")
    return searcher


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="index_project.py",
        description=(
            "Build symbol (AST) and/or semantic (embedding) indexes "
            "for the Cortex project."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force a full rebuild of the selected index(es).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--symbols-only",
        action="store_true",
        help="Build only the AST symbol index.",
    )
    mode.add_argument(
        "--semantic-only",
        action="store_true",
        help="Build only the semantic embedding index.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments. When ``None``, ``sys.argv[1:]`` is used.

    Returns:
        Shell exit code (``0`` on success, ``1`` if any stage failed).
    """
    args = parse_args(argv)

    print(f"[Project] Root : {_PROJECT_ROOT}")
    print(f"   Force rebuild: {args.force}")

    success = True

    if not args.semantic_only:
        try:
            run_symbol_index(_PROJECT_ROOT, force=args.force)
        except Exception as exc:
            print(f"\n[ERROR] Symbol indexing failed: {exc}")
            traceback.print_exc()
            success = False

    if not args.symbols_only:
        try:
            run_semantic_index(_PROJECT_ROOT, force=args.force)
        except Exception as exc:
            print(f"\n[ERROR] Semantic indexing failed: {exc}")
            traceback.print_exc()
            success = False

    if success:
        print("All indexing complete.")
        return 0

    print("\nIndexing completed with errors.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
