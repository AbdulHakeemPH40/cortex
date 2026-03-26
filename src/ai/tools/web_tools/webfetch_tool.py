"""
WebFetch Tool - Web content fetching
Fetch and extract content from URLs.
Based on packages/opencode/src/tool/webfetch.ts
"""

import time
from typing import Dict, Any

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class WebFetchTool(BaseTool):
    """
    Web content fetching tool.
    
    Features:
    - Fetch web page content
    - Extract main text content
    - Handle redirects
    - Timeout protection
    
    Use Cases:
    - Read documentation
    - Fetch API responses
    - Get web resources
    """
    
    name = "webfetch"
    description = "Fetch content from a URL. Use to read web pages, documentation, API responses, etc."
    requires_confirmation = False
    is_safe = True
    
    parameters = [
        ToolParameter("url", "string", "URL to fetch", required=True),
        ToolParameter("timeout", "integer", "Timeout in seconds (default: 30)", required=False, default=30),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            url = params.get("url")
            if not url:
                return error_result("Missing required parameter: url")
            
            timeout = params.get("timeout", 30)
            
            # Validate URL
            if not url.startswith(('http://', 'https://')):
                return error_result("URL must start with http:// or https://")
            
            # Fetch content
            try:
                import requests
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Cortex IDE AI Assistant)'
                }
                
                response = requests.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                
                duration_ms = (time.time() - start_time) * 1000
                
                # Try to extract text content
                content = response.text
                
                # Basic HTML stripping (simple version)
                if '<' in content and '>' in content:
                    import re
                    # Remove script and style tags
                    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    # Remove all tags
                    content = re.sub(r'<[^>]+>', ' ', content)
                    # Clean whitespace
                    content = re.sub(r'\s+', ' ', content).strip()
                
                return success_result(
                    result=content[:10000],  # Limit to first 10KB
                    duration_ms=duration_ms,
                    metadata={
                        'url': url,
                        'status_code': response.status_code,
                        'content_length': len(content),
                        'truncated': len(content) > 10000
                    }
                )
                
            except ImportError:
                return error_result("requests library not installed. Run: pip install requests")
            except requests.Timeout:
                return error_result(f"Request timed out after {timeout} seconds")
            except requests.RequestException as e:
                return error_result(f"Failed to fetch URL: {str(e)}")
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"WebFetch failed: {str(e)}", duration_ms)
