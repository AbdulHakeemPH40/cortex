import json
import time
from typing import Dict, Any, Optional
from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result
from src.utils.logger import get_logger

log = get_logger("SurgicalInjectionTool")

class SurgicalInjectionTool(BaseTool):
    """
    Surgically inject code into a specific placeholder (comment block).
    This is ideal for large files where you want to create a skeleton first
    and then fill in the CSS or JS blocks.
    """
    name = "inject_into_placeholder"
    description = (
        "Surgically inject code into a specific placeholder like '/* CSS_PLACEHOLDER */' or '// JS_PLACEHOLDER'. "
        "Use this for large-scale files (1000+ lines) to avoid truncation and ensure surgical precision. "
        "The tool automatically detects common comment styles around your placeholder name."
    )
    
    parameters = [
        ToolParameter("path", "string", "Path to the file to edit", required=True),
        ToolParameter("placeholder", "string", "The placeholder name (e.g., 'JS_LOGIC') or exact comment string", required=True),
        ToolParameter("content", "string", "The code block to inject into the placeholder's location", required=True)
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        path = params.get("path")
        placeholder = params.get("placeholder")
        content = params.get("content")
        
        if not all([path, placeholder, content]):
            return error_result("Missing required parameters: path, placeholder, and content are all required.")
            
        try:
            if not self.precise_editor:
                from src.ai.precise_editor import get_editor
                self.precise_editor = get_editor(self.project_root)
            
            result = self.precise_editor.replace_placeholder(path, placeholder, content)
            
            duration_ms = (time.time() - start_time) * 1000
            
            if result.success:
                msg = f"✅ Successfully injected content into placeholder '{placeholder}' in {path}."
                if result.diff_preview:
                    msg += f"\n\nDiff:\n{result.diff_preview}"
                
                return success_result(
                    msg,
                    duration_ms=duration_ms,
                    metadata={
                        "path": path,
                        "placeholder": placeholder,
                        "added_lines": result.lines_added,
                        "removed_lines": result.lines_removed
                    }
                )
            else:
                return error_result(f"Injection failed: {result.error}\nAction: {result.action}")
                
        except Exception as e:
            log.error(f"Surgical injection failed: {e}")
            return error_result(f"An unexpected error occurred during injection: {str(e)}")
