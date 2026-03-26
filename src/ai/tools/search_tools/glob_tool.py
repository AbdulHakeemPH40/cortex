"""
Glob Tool - OpenCode-style file pattern matching
Find files by glob patterns with recursive search.
Based on packages/opencode/src/tool/glob.ts
"""

import time
from pathlib import Path
from typing import Dict, Any, List

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class GlobTool(BaseTool):
    """
    File pattern matching tool.
    
    Features:
    - Glob pattern matching (** for recursive)
    - Automatic exclusion of venv/node_modules
    - Recursive directory traversal
    - File type filtering
    
    Performance:
    - Skips excluded directories automatically
    - Limits result count to prevent overflow
    - Fast path resolution
    """
    
    name = "glob"
    description = "Find files by glob pattern. Use ** for recursive search (e.g., '**/*.py' finds all Python files)."
    requires_confirmation = False
    is_safe = True
    
    # Directories to skip
    EXCLUDE_DIRS = {
        'venv', '.venv', 'node_modules', '.git', '__pycache__',
        '.tox', '.eggs', '*.egg-info', 'dist', 'build',
        '.next', '.nuxt', 'coverage', '.mypy_cache'
    }
    
    parameters = [
        ToolParameter("pattern", "string", "Glob pattern (e.g., '**/*.py', 'src/**/*.js')", required=True),
        ToolParameter("exclude_dirs", "array", "Directories to exclude", required=False, default=None),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            pattern = params.get("pattern")
            if not pattern:
                return error_result("Missing required parameter: pattern")
            
            exclude_dirs = set(params.get("exclude_dirs", []) or [])
            exclude_dirs.update(self.EXCLUDE_DIRS)
            
            if not self.project_root:
                return error_result("Project root not set")
            
            project_path = Path(self.project_root)
            matched_files: List[str] = []
            
            # Handle ** (recursive) patterns
            if '**' in pattern:
                # Remove ** and search recursively
                base_pattern = pattern.replace('**/', '').replace('**', '')
                
                for file_path in project_path.rglob(base_pattern):
                    if not file_path.is_file():
                        continue
                    
                    # Skip excluded directories
                    rel_path = file_path.relative_to(project_path)
                    if any(excl in rel_path.parts for excl in exclude_dirs):
                        continue
                    
                    matched_files.append(str(rel_path))
                    
                    # Limit results
                    if len(matched_files) >= 500:
                        break
            else:
                # Simple glob pattern
                for file_path in project_path.glob(pattern):
                    if not file_path.is_file():
                        continue
                    
                    rel_path = file_path.relative_to(project_path)
                    if any(excl in rel_path.parts for excl in exclude_dirs):
                        continue
                    
                    matched_files.append(str(rel_path))
            
            duration_ms = (time.time() - start_time) * 1000
            
            return success_result(
                result=matched_files,
                duration_ms=duration_ms,
                metadata={
                    'count': len(matched_files),
                    'pattern': pattern,
                    'truncated': len(matched_files) >= 500
                }
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Glob failed: {str(e)}", duration_ms)
