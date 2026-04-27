"""
Memory Semantic Search - Vector-based memory retrieval.

Uses embeddings to find memories semantically similar to user queries,
replacing the LLM-based selection with fast cosine similarity search.
"""

import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from src.utils.logger import get_logger

log = get_logger("memory_search")

# Import embedding system
try:
    from src.core.embeddings import get_embedding_generator, EmbeddingsGenerator
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False
    log.warning("Embeddings module not available, falling back to keyword search")


@dataclass
class MemorySearchResult:
    """Result from semantic memory search."""
    file_path: str
    filename: str
    title: str
    description: str
    similarity_score: float
    memory_type: str  # user, feedback, project, reference
    content_preview: str
    mtime: float  # modification time for freshness


class MemoryIndex:
    """
    Semantic index for memory files.
    
    Maintains embeddings for all memory files and provides
    fast similarity search using vector embeddings.
    """
    
    def __init__(self, memory_dir: str, embeddings_generator: EmbeddingsGenerator = None):
        """
        Initialize memory index.
        
        Args:
            memory_dir: Path to memory directory (contains MEMORY.md)
            embeddings_generator: Optional embeddings generator instance
        """
        self.memory_dir = memory_dir
        self.index_path = os.path.join(memory_dir, ".memory_index.json")
        self.embeddings = embeddings_generator or (
            get_embedding_generator() if HAS_EMBEDDINGS else None
        )
        self._index: Dict[str, Dict] = {}  # filename -> metadata + embedding
        self._loaded = False
    
    def build_index(self, force_rebuild: bool = False) -> int:
        """
        Build or rebuild the memory index.
        
        Scans all .md files in memory directory, extracts metadata,
        and generates embeddings for semantic search.
        
        Args:
            force_rebuild: If True, rebuild even if index exists
            
        Returns:
            Number of memories indexed
        """
        if not force_rebuild and self._load_index():
            log.info(f"[MemoryIndex] Loaded existing index with {len(self._index)} entries")
            return len(self._index)
        
        log.info(f"[MemoryIndex] Building new index for {self.memory_dir}")
        self._index.clear()
        
        # Scan memory directory
        if not os.path.exists(self.memory_dir):
            log.warning(f"[MemoryIndex] Memory directory not found: {self.memory_dir}")
            return 0
        
        memories_indexed = 0
        
        for root, dirs, files in os.walk(self.memory_dir):
            # Skip hidden directories and auto-generated files
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'auto']
            
            for filename in files:
                if not filename.endswith('.md') or filename == 'MEMORY.md':
                    continue
                
                file_path = os.path.join(root, filename)
                try:
                    metadata = self._extract_metadata(file_path)
                    if metadata:
                        # Generate embedding for semantic search
                        if self.embeddings:
                            embedding_text = f"{metadata['title']} {metadata['description']} {metadata.get('content_preview', '')}"
                            result = self.embeddings.generate_embedding(embedding_text)
                            
                            if result.success:
                                metadata['embedding'] = result.embedding
                                metadata['embedding_model'] = result.model_name
                        else:
                            log.debug(f"[MemoryIndex] No embeddings available for {filename}")
                        
                        # Store relative path as key
                        rel_path = os.path.relpath(file_path, self.memory_dir)
                        self._index[rel_path] = metadata
                        memories_indexed += 1
                        
                except Exception as e:
                    log.error(f"[MemoryIndex] Failed to index {filename}: {e}")
        
        # Save index
        self._save_index()
        self._loaded = True
        
        log.info(f"[MemoryIndex] Indexed {memories_indexed} memories")
        return memories_indexed
    
    def search(self, query: str, top_k: int = 5, min_score: float = 0.3) -> List[MemorySearchResult]:
        """
        Search memories using semantic similarity.
        
        Args:
            query: User query text
            top_k: Number of results to return
            min_score: Minimum similarity score threshold
            
        Returns:
            List of search results sorted by similarity
        """
        if not self._loaded:
            self.build_index()
        
        if not self._index:
            log.warning("[MemorySearch] No memories in index")
            return []
        
        # Generate query embedding
        if self.embeddings:
            query_result = self.embeddings.generate_embedding(query)
            if not query_result.success:
                log.error("[MemorySearch] Failed to generate query embedding")
                return self._fallback_keyword_search(query, top_k)
            
            query_embedding = query_result.embedding
        else:
            return self._fallback_keyword_search(query, top_k)
        
        # Calculate similarities
        results = []
        for rel_path, metadata in self._index.items():
            if 'embedding' not in metadata:
                continue
            
            # Calculate cosine similarity
            similarity = self.embeddings.cosine_similarity(
                query_embedding,
                metadata['embedding']
            )
            
            if similarity >= min_score:
                results.append(MemorySearchResult(
                    file_path=os.path.join(self.memory_dir, rel_path),
                    filename=metadata.get('filename', os.path.basename(rel_path)),
                    title=metadata.get('title', 'Untitled'),
                    description=metadata.get('description', ''),
                    similarity_score=similarity,
                    memory_type=metadata.get('type', 'project'),
                    content_preview=metadata.get('content_preview', ''),
                    mtime=metadata.get('mtime', 0)
                ))
        
        # Sort by similarity (descending)
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        
        # Return top_k results
        return results[:top_k]
    
    def _fallback_keyword_search(self, query: str, top_k: int) -> List[MemorySearchResult]:
        """Fallback keyword-based search when embeddings unavailable."""
        log.info("[MemorySearch] Using fallback keyword search")
        
        query_lower = query.lower()
        query_terms = set(query_lower.split())
        
        results = []
        for rel_path, metadata in self._index.items():
            # Calculate keyword overlap score
            text = f"{metadata.get('title', '')} {metadata.get('description', '')} {metadata.get('content_preview', '')}".lower()
            text_terms = set(text.split())
            
            if not text_terms:
                continue
            
            overlap = len(query_terms & text_terms) / len(query_terms)
            
            if overlap > 0:
                results.append(MemorySearchResult(
                    file_path=os.path.join(self.memory_dir, rel_path),
                    filename=metadata.get('filename', os.path.basename(rel_path)),
                    title=metadata.get('title', 'Untitled'),
                    description=metadata.get('description', ''),
                    similarity_score=overlap,
                    memory_type=metadata.get('type', 'project'),
                    content_preview=metadata.get('content_preview', ''),
                    mtime=metadata.get('mtime', 0)
                ))
        
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        return results[:top_k]
    
    def _extract_metadata(self, file_path: str) -> Optional[Dict]:
        """Extract metadata from memory file."""
        try:
            content = Path(file_path).read_text(encoding='utf-8', errors='ignore')
            
            # Parse YAML frontmatter
            metadata = {
                'filename': os.path.basename(file_path),
                'mtime': os.path.getmtime(file_path),
                'title': '',
                'description': '',
                'type': 'project',
                'content_preview': ''
            }
            
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = parts[1].strip()
                    body = parts[2].strip()
                    
                    # Parse simple YAML fields
                    for line in frontmatter.split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip().lower()
                            value = value.strip().strip('"').strip("'")
                            
                            if key == 'name':
                                metadata['title'] = value
                            elif key == 'description':
                                metadata['description'] = value
                            elif key == 'type':
                                metadata['type'] = value
                    
                    # Extract content preview (first 200 chars)
                    metadata['content_preview'] = body[:200]
            else:
                # No frontmatter, use first 200 chars
                metadata['content_preview'] = content[:200]
                metadata['title'] = os.path.basename(file_path).replace('.md', '')
            
            return metadata
            
        except Exception as e:
            log.error(f"[MemoryIndex] Failed to extract metadata from {file_path}: {e}")
            return None
    
    def _load_index(self) -> bool:
        """Load index from disk if it exists."""
        try:
            if not os.path.exists(self.index_path):
                return False
            
            index_data = json.loads(Path(self.index_path).read_text(encoding='utf-8'))
            
            # Check if index is stale (any file modified after index creation)
            index_mtime = index_data.get('created_at', 0)
            stale = False
            
            for rel_path, metadata in index_data.get('memories', {}).items():
                file_path = os.path.join(self.memory_dir, rel_path)
                if not os.path.exists(file_path):
                    stale = True
                    break
                
                current_mtime = os.path.getmtime(file_path)
                if current_mtime > metadata.get('mtime', 0):
                    stale = True
                    break
            
            if stale:
                log.info("[MemoryIndex] Index is stale, rebuilding")
                return False
            
            self._index = index_data.get('memories', {})
            return True
            
        except Exception as e:
            log.error(f"[MemoryIndex] Failed to load index: {e}")
            return False
    
    def _save_index(self):
        """Save index to disk."""
        try:
            index_data = {
                'created_at': __import__('time').time(),
                'memory_dir': self.memory_dir,
                'memories': self._index
            }
            
            # Remove embeddings before saving (too large)
            # They'll be regenerated on load if needed
            for metadata in index_data['memories'].values():
                metadata.pop('embedding', None)
            
            Path(self.index_path).write_text(
                json.dumps(index_data, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            
        except Exception as e:
            log.error(f"[MemoryIndex] Failed to save index: {e}")


class SemanticMemorySearcher:
    """
    High-level API for semantic memory search.
    
    Integrates with the memdir system to provide
    embedding-based memory retrieval.
    """
    
    def __init__(self, memory_dir: str = None):
        """
        Initialize semantic memory searcher.
        
        Args:
            memory_dir: Optional memory directory path
        """
        self.memory_dir = memory_dir
        self._index: Optional[MemoryIndex] = None
    
    def search_memories(self, query: str, memory_dir: str = None, top_k: int = 5) -> List[MemorySearchResult]:
        """
        Search for memories semantically similar to query.
        
        Args:
            query: User query or conversation context
            memory_dir: Optional memory directory override
            top_k: Number of results to return
            
        Returns:
            List of relevant memories
        """
        mem_dir = memory_dir or self.memory_dir
        if not mem_dir:
            log.error("[SemanticSearch] No memory directory specified")
            return []
        
        # Initialize index
        if self._index is None or self._index.memory_dir != mem_dir:
            self._index = MemoryIndex(mem_dir)
            self._index.build_index()
        
        # Perform search
        results = self._index.search(query, top_k=top_k)
        
        log.info(f"[SemanticSearch] Query: '{query[:50]}...' -> {len(results)} results")
        for i, result in enumerate(results[:3], 1):
            log.debug(f"  {i}. {result.title} (score: {result.similarity_score:.3f})")
        
        return results
    
    def format_results_for_prompt(self, results: List[MemorySearchResult]) -> str:
        """Format search results for injection into AI agent prompt."""
        if not results:
            return ""
        
        sections = ["## Relevant Memories (Semantic Search)\n"]
        
        for i, result in enumerate(results, 1):
            sections.append(f"### Memory {i}: {result.title}")
            sections.append(f"**Type:** {result.memory_type}")
            sections.append(f"**Relevance:** {result.similarity_score:.1%}")
            sections.append(f"**Description:** {result.description}")
            sections.append(f"**Preview:** {result.content_preview[:300]}")
            sections.append(f"**File:** {result.file_path}")
            sections.append("")
        
        sections.append("**Use these memories to inform your response.**")
        
        return "\n".join(sections)


# Global instance
_searcher: Optional[SemanticMemorySearcher] = None


def get_semantic_searcher(memory_dir: str = None) -> SemanticMemorySearcher:
    """Get or create global semantic searcher instance."""
    global _searcher
    if _searcher is None:
        _searcher = SemanticMemorySearcher(memory_dir)
    return _searcher
