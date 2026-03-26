"""
Grep Tool - OpenCode-style code search
Search file contents with regex support.
Based on packages/opencode/src/tool/grep.ts
"""

import re
import time
from pathlib import Path
from typing import Dict, Any, List

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class GrepTool(BaseTool):
    """
    Code content search tool.
    
    Features:
    - Regex pattern matching
    - File type filtering (glob patterns)
    - Automatic exclusion of venv/node_modules
    - Line-by-line matching
    - Context display
    
    Performance:
    - Skips binary files automatically
    - Excludes common dependency directories
    - Limits result count to prevent overflow
    """
    
    name = "grep"
    description = "Search file contents with regex support. Use for finding code patterns, text occurrences, etc."
    requires_confirmation = False
    is_safe = True
    
    # Directories to skip (performance + noise reduction)
    EXCLUDE_DIRS = {
        'venv', '.venv', 'node_modules', '.git', '__pycache__',
        '.tox', '.eggs', '*.egg-info', 'dist', 'build',
        '.next', '.nuxt', 'coverage', '.mypy_cache'
    }
    
    parameters = [
        ToolParameter("pattern", "string", "Regex pattern to search for", required=False),
        ToolParameter("query", "string", "Alternative name for pattern (for legacy compatibility)", required=False),
        ToolParameter("include", "string", "File pattern (e.g., '*.py', '**/*.js')", required=False, default="*"),
        ToolParameter("exclude_dirs", "array", "Directories to exclude", required=False, default=None),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            pattern = params.get("pattern") or params.get("query")
            if not pattern:
                return error_result("Missing required parameter: pattern or query")
            
            include = params.get("include") or params.get("file_pattern") or "*"
            exclude_dirs = set(params.get("exclude_dirs", []) or [])
            exclude_dirs.update(self.EXCLUDE_DIRS)
            
            # Compile regex
            try:
                regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            except re.error as e:
                return error_result(f"Invalid regex pattern: {e}")
            
            # Find matching files
            if not self.project_root:
                return error_result("Project root not set")
            
            project_path = Path(self.project_root)
            matches: List[Dict] = []
            files_searched = 0
            
            # Search all matching files
            for file_path in project_path.rglob(include.replace('**/', '')):
                if not file_path.is_file():
                    continue
                
                # Skip excluded directories
                if any(excl in file_path.parts for excl in exclude_dirs):
                    continue
                
                files_searched += 1
                
                try:
                    content = file_path.read_text(encoding='utf-8')
                    lines = content.splitlines()
                    
                    for line_num, line in enumerate(lines, 1):
                        match = regex.search(line)
                        if match:
                            rel_path = file_path.relative_to(project_path)
                            matches.append({
                                'file': str(rel_path),
                                'line': line_num,
                                'content': line.rstrip(),
                                'match': match.group(0)
                            })
                            
                            # Limit results to prevent overflow
                            if len(matches) >= 200:
                                break
                    
                except (UnicodeDecodeError, PermissionError):
                    continue  # Skip binary files
            
            duration_ms = (time.time() - start_time) * 1000
            
            return success_result(
                result=matches,
                duration_ms=duration_ms,
                metadata={
                    'total_matches': len(matches),
                    'files_searched': files_searched,
                    'pattern': pattern,
                    'include': include,
                    'truncated': len(matches) >= 200
                }
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Grep failed: {str(e)}", duration_ms)
