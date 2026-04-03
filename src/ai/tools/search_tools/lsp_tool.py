"""
LSP Tool - Language Server Protocol integration
Code intelligence: go-to-definition, find references, hover info.
Based on packages/opencode/src/tool/lsp.ts
"""

import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class LspTool(BaseTool):
    """
    Language Server Protocol tool.
    
    Features:
    - Go to definition
    - Find references
    - Symbol information
    - Code navigation
    
    Integration:
    - Uses existing codebase_index if available
    - Falls back to text search if LSP not available
    - Works with multiple languages
    """
    
    name = "lsp"
    description = "Language Server Protocol operations: go to definition, find references, get symbol info. Use for code navigation and understanding."
    requires_confirmation = False
    is_safe = True
    
    parameters = [
        ToolParameter("operation", "string", "Operation: 'find_references', 'go_to_definition', 'symbol_info'", required=True),
        ToolParameter("symbol", "string", "Symbol name to look up", required=True),
        ToolParameter("file_path", "string", "File containing the symbol", required=False, default=None),
        ToolParameter("line", "integer", "Line number (1-based) where symbol appears", required=False, default=None),
        ToolParameter("character", "integer", "Character position (1-based)", required=False, default=None),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            operation = params.get("operation")
            if not operation:
                return error_result("Missing required parameter: operation")
            
            symbol = params.get("symbol")
            if not symbol:
                return error_result("Missing required parameter: symbol")
            
            # Route to appropriate operation
            if operation == "find_references":
                return self._find_references(symbol, params, start_time)
            elif operation == "go_to_definition":
                return self._go_to_definition(symbol, params, start_time)
            elif operation == "symbol_info":
                return self._get_symbol_info(symbol, params, start_time)
            else:
                return error_result(f"Unknown LSP operation: {operation}")
                
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"LSP operation failed: {str(e)}", duration_ms)
    
    def _find_references(self, symbol: str, params: Dict, start_time: float) -> ToolResult:
        """Find all references to a symbol."""
        try:
            file_path = params.get("file_path")
            line = params.get("line")
            character = params.get("character")
            
            # Try using codebase_index if available
            if hasattr(self, 'file_manager') and self.file_manager:
                # Use semantic search if available
                try:
                    from src.core.codebase_index import get_codebase_index
                    project_root = self.project_root or ""
                    indexer = get_codebase_index(project_root)
                    
                    results = indexer.find_symbol(symbol)
                    if results:
                        duration_ms = (time.time() - start_time) * 1000
                        return success_result(
                            result=results,
                            duration_ms=duration_ms,
                            metadata={'count': len(results), 'operation': 'find_references'}
                        )
                except (ImportError, AttributeError):
                    pass  # Fall back to grep
            
            # Fallback: use grep to find symbol
            from src.ai.tools.search_tools import GrepTool
            grep_tool = GrepTool()
            grep_tool.project_root = self.project_root
            
            result = grep_tool.execute({
                "pattern": f"\\b{re.escape(symbol)}\\b",
                "include": "*.py"
            })
            
            duration_ms = (time.time() - start_time) * 1000
            return success_result(
                result=result.result if result.success else [],
                duration_ms=duration_ms,
                metadata={'count': len(result.result) if result.success else 0, 'operation': 'find_references', 'fallback': 'grep'}
            )
            
        except Exception as e:
            return error_result(f"Find references failed: {str(e)}")
    
    def _go_to_definition(self, symbol: str, params: Dict, start_time: float) -> ToolResult:
        """Go to symbol definition."""
        try:
            # Try codebase_index first
            if hasattr(self, 'file_manager') and self.file_manager:
                try:
                    from src.core.codebase_index import get_codebase_index
                    project_root = self.project_root or ""
                    indexer = get_codebase_index(project_root)
                    
                    definition = indexer.find_definition(symbol)
                    if definition:
                        duration_ms = (time.time() - start_time) * 1000
                        return success_result(
                            result=definition,
                            duration_ms=duration_ms,
                            metadata={'operation': 'go_to_definition'}
                        )
                except (ImportError, AttributeError):
                    pass
            
            # Fallback: search for symbol definition
            return error_result(f"Definition for '{symbol}' not found. Try using grep to search manually.")
            
        except Exception as e:
            return error_result(f"Go to definition failed: {str(e)}")
    
    def _get_symbol_info(self, symbol: str, params: Dict, start_time: float) -> ToolResult:
        """Get symbol information."""
        try:
            # Basic implementation - can be enhanced with actual LSP
            info = {
                'name': symbol,
                'type': 'unknown',
                'description': f'Symbol: {symbol}'
            }
            
            duration_ms = (time.time() - start_time) * 1000
            return success_result(
                result=info,
                duration_ms=duration_ms,
                metadata={'operation': 'symbol_info'}
            )
            
        except Exception as e:
            return error_result(f"Get symbol info failed: {str(e)}")


# Need to import re at module level
import re
