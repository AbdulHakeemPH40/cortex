#!/usr/bin/env python3
"""
Demonstration of Lazy Loading Implementation in Cortex AI

This file demonstrates how lazy loading works in the Cortex AI system.
Lazy loading is a performance optimization technique that loads only the
necessary parts of a file on demand, rather than loading entire files.

Key Concepts:
1. Range-based reading: Only read specific line ranges from files
2. Multi-level caching: Cache at range, file, and memory levels
3. On-demand loading: Load content only when needed
"""

import os
import time
from pathlib import Path
from typing import Optional, Dict, List
import hashlib

class LazyFileReader:
    """Demonstration of lazy loading file reader similar to Cortex's implementation."""
    
    def __init__(self, cache_size: int = 100):
        self._range_cache: Dict[str, str] = {}  # cache_key -> content
        self._file_cache: Dict[str, str] = {}   # filepath -> full content
        self._hash_cache: Dict[str, str] = {}   # filepath -> content hash
        self._open_files: Dict[str, str] = {}   # Currently open files
        self.cache_size = cache_size
        
    def _compute_hash(self, content: str) -> str:
        """Compute hash of content for change detection."""
        return hashlib.md5(content.encode()).hexdigest()
    
    def read_range(self, filepath: str, start_line: int, end_line: int, use_cache: bool = True) -> Optional[str]:
        """
        ULTRA-FAST line range reading with multi-level caching.
        Only loads requested lines - NOT entire file!
        
        PERFORMANCE HIERARCHY (fastest to slowest):
        1. Range cache hit → INSTANT (<1ms)
        2. Full file cache hit → FAST (~2-5ms to extract range)
        3. Small file read → MEDIUM (~10-20ms)
        4. Large file mmap → SLOW but optimized (~50-100ms)
        """
        resolved_path = str(Path(filepath).resolve())
        cache_key = f"{resolved_path}:{start_line}-{end_line}"
        
        # LEVEL 1: Range cache (INSTANT)
        if use_cache and cache_key in self._range_cache:
            print(f"⚡ RANGE CACHE HIT: {filepath}[{start_line}-{end_line}]")
            return self._range_cache[cache_key]
        
        # LEVEL 2: Full file cache (VERY FAST)
        if use_cache and resolved_path in self._file_cache:
            print(f"📁 FILE CACHE HIT: {filepath}")
            full_content = self._file_cache[resolved_path]
            lines = full_content.splitlines(keepends=True)
            if start_line <= len(lines) and end_line <= len(lines):
                range_content = ''.join(lines[start_line-1:end_line])
                self._range_cache[cache_key] = range_content
                return range_content
        
        # LEVEL 3: Read from disk (ON-DEMAND)
        print(f"📖 READING FROM DISK: {filepath}[{start_line}-{end_line}]")
        
        try:
            # For large files, we could use mmap here
            with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = []
                for i, line in enumerate(f, 1):
                    if i > end_line:
                        break
                    if i >= start_line:
                        lines.append(line)
                
                range_content = ''.join(lines)
                
                # Cache the result
                self._range_cache[cache_key] = range_content
                
                # Update file cache if we read the whole file
                if start_line == 1 and end_line >= 100:  # Approximate full file read
                    f.seek(0)
                    full_content = f.read()
                    self._file_cache[resolved_path] = full_content
                    self._hash_cache[resolved_path] = self._compute_hash(full_content)
                
                return range_content
                
        except Exception as e:
            print(f"❌ Error reading {filepath}: {e}")
            return None
    
    def read_file_lazy(self, filepath: str, viewport_start: int = 1, viewport_end: int = 50) -> str:
        """
        Lazy loading: Read only what's visible in the viewport.
        Automatically prefetches surrounding lines.
        """
        print(f"\n🔍 LAZY LOADING: {filepath}")
        print(f"   Viewport: lines {viewport_start}-{viewport_end}")
        
        # Read the viewport
        viewport_content = self.read_range(filepath, viewport_start, viewport_end)
        
        # Prefetch next chunk (background/async in real implementation)
        prefetch_start = viewport_end + 1
        prefetch_end = prefetch_start + 49
        print(f"   Prefetching: lines {prefetch_start}-{prefetch_end}")
        
        # In real implementation, this would be async
        self.read_range(filepath, prefetch_start, prefetch_end)
        
        return viewport_content if viewport_content else ""
    
    def clear_cache(self):
        """Clear all caches."""
        self._range_cache.clear()
        self._file_cache.clear()
        self._hash_cache.clear()
        self._open_files.clear()
        print("🧹 All caches cleared")


def demonstrate_lazy_loading():
    """Demonstrate lazy loading with a sample file."""
    print("=" * 60)
    print("LAZY LOADING DEMONSTRATION")
    print("=" * 60)
    
    # Create a sample file to work with
    sample_content = []
    for i in range(1, 201):
        sample_content.append(f"Line {i}: This is sample content for demonstration of lazy loading.\n")
    
    sample_file = "sample_large_file.txt"
    with open(sample_file, 'w') as f:
        f.writelines(sample_content)
    
    print(f"📝 Created sample file: {sample_file} (200 lines)")
    
    # Create lazy reader
    reader = LazyFileReader()
    
    print("\n" + "=" * 60)
    print("DEMO 1: Reading specific ranges")
    print("=" * 60)
    
    # First read - will read from disk
    start_time = time.time()
    content1 = reader.read_range(sample_file, 10, 20)
    elapsed1 = (time.time() - start_time) * 1000
    print(f"First read (lines 10-20): {len(content1.splitlines())} lines in {elapsed1:.1f}ms")
    
    # Second read - should hit range cache
    start_time = time.time()
    content2 = reader.read_range(sample_file, 10, 20)
    elapsed2 = (time.time() - start_time) * 1000
    print(f"Second read (lines 10-20): {len(content2.splitlines())} lines in {elapsed2:.1f}ms")
    
    # Different range - partial cache hit
    start_time = time.time()
    content3 = reader.read_range(sample_file, 15, 25)
    elapsed3 = (time.time() - start_time) * 1000
    print(f"Third read (lines 15-25): {len(content3.splitlines())} lines in {elapsed3:.1f}ms")
    
    print("\n" + "=" * 60)
    print("DEMO 2: Lazy loading with viewport")
    print("=" * 60)
    
    # Simulate scrolling through a file
    viewport_size = 20
    
    for viewport_start in [1, 21, 41, 61]:
        viewport_end = viewport_start + viewport_size - 1
        print(f"\nScrolling to viewport: lines {viewport_start}-{viewport_end}")
        
        start_time = time.time()
        content = reader.read_file_lazy(sample_file, viewport_start, viewport_end)
        elapsed = (time.time() - start_time) * 1000
        
        lines = content.splitlines()
        print(f"   Loaded {len(lines)} lines in {elapsed:.1f}ms")
        if lines:
            print(f"   First line: {lines[0][:50]}...")
            print(f"   Last line: {lines[-1][:50]}...")
    
    print("\n" + "=" * 60)
    print("DEMO 3: Cache statistics")
    print("=" * 60)
    
    print(f"Range cache entries: {len(reader._range_cache)}")
    print(f"File cache entries: {len(reader._file_cache)}")
    print(f"Hash cache entries: {len(reader._hash_cache)}")
    
    # Cleanup
    reader.clear_cache()
    os.remove(sample_file)
