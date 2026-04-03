import os
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result
from src.utils.logger import get_logger

log = get_logger("CheckSyntaxTool")

class CheckSyntaxTool(BaseTool):
    """
    Check syntax of a file for errors.
    Supports multi-language syntax checking (Python, JS, HTML, etc.)
    """
    name = "check_syntax"
    description = "Check syntax of a file for errors. Use this before finished with a task to ensure no bugs were introduced."
    
    parameters = [
        ToolParameter("path", "string", "Path to the file to check (or use 'file' or 'file_path')", required=False)
    ]
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        if "file" in params and "path" not in params:
            params["path"] = params["file"]
        elif "file_path" in params and "path" not in params:
            params["path"] = params["file_path"]
            
        if "path" not in params:
            return False, "Missing required parameter: path"
            
        return super().validate_params(params)
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        file_path = params.get("path") or params.get("file") or params.get("file_path")
        
        if not file_path:
            return error_result("Missing 'path' parameter")
            
        try:
            from src.core.syntax_checker import get_syntax_checker
            
            resolved_path = self._resolve_path(file_path)
            
            if not resolved_path.exists():
                return error_result(f"File not found: {file_path}")
            
            checker = get_syntax_checker()
            content = resolved_path.read_text(encoding='utf-8', errors='ignore')
            result = checker.check_file(str(resolved_path), content)
            
            duration_ms = (time.time() - start_time) * 1000
            
            if result.success:
                return success_result(
                    f"✅ No syntax errors in {file_path} ({result.language})",
                    duration_ms=duration_ms,
                    metadata={"language": result.language}
                )
            
            # Format errors for AI consumption
            output_lines = [f"## Syntax Errors in {file_path}\n"]
            output_lines.append(f"Language: {result.language}\n")
            
            for i, error in enumerate(result.errors, 1):
                severity_icon = "❌" if error.severity == "error" else "⚠️" if error.severity == "warning" else "ℹ️"
                output_lines.append(f"{i}. {severity_icon} Line {error.line}:{error.column}")
                output_lines.append(f"   {error.message}")
                if error.code:
                    output_lines.append(f"   Code: {error.code}")
                if error.source:
                    output_lines.append(f"   Source: {error.source}")
                output_lines.append("")
            
            return success_result(
                "\n".join(output_lines),
                duration_ms=duration_ms,
                metadata={
                    "language": result.language,
                    "error_count": len(result.errors)
                }
            )
            
        except Exception as e:
            log.error(f"Failed to check syntax: {e}")
            return error_result(f"Failed to check syntax: {e}")
