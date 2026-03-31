import os
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result
from src.utils.logger import get_logger

log = get_logger("GetProblemsTool")

class GetProblemsTool(BaseTool):
    """
    Get a list of linting problems for a set of files.
    """
    name = "get_problems"
    description = "Get a list of linting problems for a set of files. Use to check for errors across multiple files."
    
    parameters = [
        ToolParameter("paths", "array", "List of file paths to check (or use 'files')", required=False)
    ]
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        # Handle single path instead of array
        if "path" in params and "paths" not in params:
            params["paths"] = params["path"] if isinstance(params["path"], list) else [params["path"]]
                
        # Handle 'files' alias
        elif "files" in params and "paths" not in params:
            params["paths"] = params["files"] if isinstance(params["files"], list) else [params["files"]]
                
        if "paths" not in params:
            return False, "Missing required parameter: paths (array of file paths)"
            
        return super().validate_params(params)
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        file_paths = params.get("paths", [])
        
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        
        if not file_paths:
            return error_result("Missing 'paths' parameter")
            
        try:
            from src.core.syntax_checker import get_syntax_checker
            
            checker = get_syntax_checker()
            all_errors = []
            
            for path in file_paths:
                resolved_path = self._resolve_path(path)
                if resolved_path.exists():
                    content = resolved_path.read_text(encoding='utf-8', errors='ignore')
                    result = checker.check_file(str(resolved_path), content)
                    if not result.success:
                        all_errors.append(result)
            
            duration_ms = (time.time() - start_time) * 1000
            
            if not all_errors:
                return success_result(
                    "✅ No syntax errors found in the specified files.",
                    duration_ms=duration_ms
                )
            
            # Format combined errors
            output_lines = [f"## Problems found in {len(all_errors)} file(s)\n"]
            
            for result in all_errors:
                output_lines.append(f"### {result.file_path} ({result.language})")
                for i, error in enumerate(result.errors, 1):
                    severity_icon = "❌" if error.severity == "error" else "⚠️" if error.severity == "warning" else "ℹ️"
                    output_lines.append(f"  {i}. {severity_icon} Line {error.line}:{error.column} - {error.message}")
                output_lines.append("")
            
            return success_result(
                "\n".join(output_lines),
                duration_ms=duration_ms,
                metadata={
                    "files_with_errors": len(all_errors)
                }
            )
            
        except Exception as e:
            log.error(f"Failed to get problems: {e}")
            return error_result(f"Failed to get problems: {e}")
