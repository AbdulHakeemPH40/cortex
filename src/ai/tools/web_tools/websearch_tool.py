"""
WebSearch Tool - Web search capability
Search the web for information.
Based on packages/opencode/src/tool/websearch.ts
"""

import time
from typing import Dict, Any, List

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class WebSearchTool(BaseTool):
    """
    Web search tool.
    
    Features:
    - Search web for information
    - Return top results
    - Extract snippets and URLs
    
    Use Cases:
    - Look up documentation
    - Find solutions to errors
    - Research topics
    
    Note: Requires DuckDuckGo search API or similar
    """
    
    name = "websearch"
    description = "Search the web for information. Use to find documentation, solutions, research topics, etc."
    requires_confirmation = False
    is_safe = True
    
    parameters = [
        ToolParameter("query", "string", "Search query", required=True),
        ToolParameter("num_results", "integer", "Number of results (default: 5)", required=False, default=5),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            query = params.get("query")
            if not query:
                return error_result("Missing required parameter: query")
            
            num_results = min(params.get("num_results", 5), 10)  # Max 10 results
            
            # Try DuckDuckGo HTML scraping (no API key needed)
            try:
                import requests
                from bs4 import BeautifulSoup
                
                # DuckDuckGo search
                url = "https://html.duckduckgo.com/html/"
                payload = {'q': query}
                headers = {'User-Agent': 'Mozilla/5.0'}
                
                response = requests.post(url, data=payload, headers=headers, timeout=10)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                results = []
                for result in soup.select('.result')[:num_results]:
                    title_elem = result.select_one('.result__title')
                    snippet_elem = result.select_one('.result__snippet')
                    url_elem = result.select_one('.result__url')
                    
                    if title_elem and snippet_elem:
                        title = title_elem.get_text(strip=True)
                        snippet = snippet_elem.get_text(strip=True)
                        url = url_elem.get('href') if url_elem else ''
                        
                        results.append({
                            'title': title,
                            'snippet': snippet,
                            'url': url
                        })
                
                if not results:
                    return error_result("No search results found")
                
                duration_ms = (time.time() - start_time) * 1000
                
                return success_result(
                    result=results,
                    duration_ms=duration_ms,
                    metadata={
                        'query': query,
                        'count': len(results),
                        'source': 'DuckDuckGo'
                    }
                )
                
            except ImportError as e:
                missing_lib = str(e).split("'")[1] if "'" in str(e) else "unknown"
                return error_result(f"Required library not installed: {missing_lib}. Run: pip install {missing_lib}")
            except Exception as e:
                return error_result(f"Search failed: {str(e)}")
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"WebSearch failed: {str(e)}", duration_ms)
