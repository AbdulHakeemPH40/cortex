"""
Semantic Search Tools for Cortex AI Agent
Provides deep-search capabilities using vector embeddings and codebase indexing.
Corrected to use the real engine in src/core/semantic_search.py.
"""

from typing import Any, Dict, List, Optional
from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result
from src.utils.logger import get_logger

log = get_logger("SemanticSearchTool")

class CodebaseSearchTool(BaseTool):
    """
    Semantic code search - find code by meaning/intent, not just text.
    Use when you don't know exact function names or want to understand how something works.
    """
    name = "search_codebase"
    description = "Semantic code search - find code by meaning/intent, not just text. Use when you don't know exact function names or want to understand how something works."
    parameters = [
        ToolParameter("query", "string", "What you're looking for (e.g., 'authentication logic', 'how payments work', 'database connection')", required=True),
        ToolParameter("target_directories", "array", "Specific directories to search (optional)", required=False, default=None)
    ]

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        query = params.get("query")
        
        try:
            # FIX: Use the real core semantic searcher
            from src.core.semantic_search import get_semantic_searcher
            
            project_root = self.project_root
            if not project_root:
                return error_result("Project root must be set for semantic search.")
                
            searcher = get_semantic_searcher(project_root)
            if not searcher:
                return error_result("Could not initialize semantic searcher.")
            
            # Perform semantic search
            results = searcher.search(query, top_k=10)
            
            if not results:
                return success_result(f"No semantic matches found for '{query}'. Make sure the project is indexed via AI -> Rebuild Index.")
            
            # Format results
            output_lines = [f"## Semantic Search Results for: {query}\n"]
            for i, result in enumerate(results, 1):
                # result is a SearchResult object from src/core/semantic_search.py
                file_rel = result.file_path
                if project_root in file_rel:
                    import os
                    file_rel = os.path.relpath(file_rel, project_root)
                    
                output_lines.append(f"{i}. {file_rel} (Similarity: {result.similarity:.2f})")
                snippet = result.content_snippet[:250] + "..." if len(result.content_snippet) > 250 else result.content_snippet
                output_lines.append(f"   {snippet}")
                output_lines.append("")
            
            return success_result("\n".join(output_lines))
            
        except ImportError as e:
            log.error(f"Import error: {e}")
            return error_result("Semantic search core (src.core.semantic_search) not available.")
        except Exception as e:
            log.error(f"Search error: {e}")
            return error_result(f"Failed to search codebase: {str(e)}")


class SemanticSearchTool(BaseTool):
    """
    Deep semantic code search using embeddings. Finds code by meaning, not keywords.
    Best for finding similar implementations or understanding code concepts.
    """
    name = "semantic_search"
    description = "Deep semantic code search using embeddings. Finds code by meaning, not keywords. Best for finding similar implementations or understanding code concepts."
    parameters = [
        ToolParameter("query", "string", "Natural language query describing what you're looking for", required=True),
        ToolParameter("limit", "integer", "Maximum number of results", required=False, default=10),
        ToolParameter("min_similarity", "string", "Minimum similarity threshold (0.0 to 1.0)", required=False, default="0.3")
    ]

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        query = params.get("query")
        limit = params.get("limit", 10)
        try:
            min_sim = float(params.get("min_similarity", 0.3))
        except:
            min_sim = 0.3
        
        try:
            from src.core.semantic_search import get_semantic_searcher
            
            project_root = self.project_root
            if not project_root:
                return error_result("Project root must be set for semantic search.")
                
            searcher = get_semantic_searcher(project_root)
            if not searcher:
                return error_result("Could not initialize semantic searcher.")
            
            # Perform search using the real engine
            results = searcher.search(query, top_k=limit, min_similarity=min_sim)
            
            if not results:
                return success_result(f"No deep semantic matches found for '{query}'.")
            
            # Format results
            output_lines = [f"## Deep Semantic Search Results for: {query}\n"]
            for i, result in enumerate(results, 1):
                file_rel = result.file_path
                if project_root in file_rel:
                    import os
                    file_rel = os.path.relpath(file_rel, project_root)
                    
                output_lines.append(f"{i}. {file_rel} (Score: {result.similarity:.2f})")
                snippet = result.content_snippet[:250] + "..." if len(result.content_snippet) > 250 else result.content_snippet
                output_lines.append(f"   {snippet}")
                output_lines.append("")
                
            return success_result("\n".join(output_lines))
            
        except Exception as e:
            return error_result(f"Failed to perform semantic search: {str(e)}")
