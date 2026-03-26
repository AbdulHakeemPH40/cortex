"""
Read Tool - OpenCode-style file reading
Smart file reading with path resolution, caching, and metadata.
Based on packages/opencode/src/tool/read.ts
"""

import time
from pathlib import Path
from typing import Dict, Any

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result
from src.utils.logger import get_logger

log = get_logger("ReadTool")


class ReadTool(BaseTool):
    """
    Smart file reading tool.
    
    Features:
    - Automatic path resolution (relative to project root)
    - Optional line range selection
    - Line number formatting option
    - File size and line count metadata
    - Encoding detection
    - Fast-fail on missing files
    """
    
    name = "read_file"
    description = "Read file content with optional line numbers and range. Use range for large files."
    requires_confirmation = False
    is_safe = True
    
    parameters = [
        ToolParameter("path", "string", "Path to the file (relative or absolute)", required=True),
        ToolParameter("start_line", "integer", "First line to read (1-indexed)", required=False, default=1),
        ToolParameter("end_line", "integer", "Last line to read (inclusive)", required=False, default=None),
        ToolParameter("numbered", "boolean", "Include line numbers in output", required=False, default=True),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            # Extract parameters
            path = params.get("path")
            if not path:
                return error_result("Missing required parameter: path")
            
            start_line = params.get("start_line", 1)
            end_line = params.get("end_line")
            numbered = params.get("numbered", True)
            
            # Resolve path
            file_path = self._resolve_path(path)
            str_path = str(file_path)
            
            # Check if file exists
            if not file_path.exists():
                error_msg = f"File not found: {file_path}"
                
                # Try to find similar files to suggest
                suggestions = self._find_similar_files(path)
                if suggestions:
                    error_msg += f"\n\nDid you mean one of these?\n"
                    for s in suggestions[:5]:
                        error_msg += f"  • {s}\n"
                    error_msg += f"\nUse list_directory('.') to see the actual project structure."
                
                return error_result(error_msg)
            
            if not file_path.is_file():
                return error_result(f"Not a file: {file_path}")
            
            # PERFORMANCE: Use FileManager if available
            if self.file_manager and hasattr(self.file_manager, 'read_range'):
                # Handle auto-detection of end_line
                if end_line is None:
                    # Estimate or read full size if needed
                    file_size = file_path.stat().st_size
                    if file_size > 500 * 1024:  # >500KB — suggest range
                        # Get first 400 lines as default viewport
                        end_line = start_line + 399
                        log.info(f"🎯 Auto-limiting read for large file: {path}")
                    else:
                        # Small file, read it all
                        end_line = 1000000  # Large enough
                
                output = self.file_manager.read_range(str_path, start_line, end_line)
                
                if output is None:
                    # Fallback to direct read if FileManager fails
                    content = file_path.read_text(encoding='utf-8', errors='replace')
                    lines = content.splitlines()
                    selected_lines = lines[start_line - 1:end_line]
                    output = '\n'.join(selected_lines)
            else:
                # Direct read fallback
                content = file_path.read_text(encoding='utf-8', errors='replace')
                lines = content.splitlines()
                total_lines = len(lines)
                
                if start_line < 1: start_line = 1
                if end_line is None: end_line = total_lines
                else: end_line = min(end_line, total_lines)
                
                selected_lines = lines[start_line - 1:end_line]
                output = '\n'.join(selected_lines)
            
            # Post-process for line numbers
            if numbered:
                lines = output.splitlines()
                numbered_lines = []
                for i, line in enumerate(lines, start=start_line):
                    numbered_lines.append(f"{i:6d} | {line}")
                output = '\n'.join(numbered_lines)
            
            # Calculate stats
            duration_ms = (time.time() - start_time) * 1000
            file_size = file_path.stat().st_size
            
            return success_result(
                result=output,
                duration_ms=duration_ms,
                metadata={
                    'file_path': str_path,
                    'start_line': start_line,
                    'end_line': end_line,
                    'file_size_bytes': file_size,
                    'using_manager': self.file_manager is not None
                }
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Failed to read file: {str(e)}", duration_ms)
            
    def _find_similar_files(self, path: str) -> list:
        """Find files with similar names in the project to suggest correct paths."""
        try:
            if not self.project_root:
                return []
            
            root = Path(self.project_root)
            if not root.exists():
                return []
            
            filename = Path(path).name.lower()
            basename = Path(path).stem.lower()
            
            # Extensions to search
            search_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', 
                                '.json', '.md', '.txt', '.vue', '.svelte', '.go', '.rs'}
            
            similar = []
            seen = set()
            
            # Limited recursive search for performance
            count = 0
            for file_path in root.rglob('*'):
                count += 1
                if count > 1000: break # Safety limit
                
                if file_path.is_dir() or file_path.suffix.lower() not in search_extensions:
                    continue
                
                rel_path = str(file_path.relative_to(root))
                file_name = file_path.name.lower()
                file_stem = file_path.stem.lower()
                
                if (file_name == filename or (basename and basename in file_stem)) and rel_path not in seen:
                    similar.append(rel_path)
                    seen.add(rel_path)
                
                if len(similar) >= 5:
                    break
            
            return similar
        except:
            return []
