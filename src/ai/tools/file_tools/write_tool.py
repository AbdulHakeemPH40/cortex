"""
Write Tool - OpenCode-style file writing
Safe file creation and overwriting with validation.
Based on packages/opencode/src/tool/write.ts
"""

import time
from pathlib import Path
from typing import Dict, Any

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class WriteTool(BaseTool):
    """
    File writing tool.
    
    Features:
    - Create new files or overwrite existing ones
    - Automatic directory creation
    - Path resolution relative to project root
    - Size validation
    - Backup warning for overwrites
    
    Safety:
    - Requires user confirmation (destructive operation)
    - Warns about overwriting existing files
    - Validates content size before writing
    """
    
    name = "write_file"
    description = "Write content to a file. Creates new file or overwrites existing one."
    requires_confirmation = True
    is_safe = False
    
    parameters = [
        ToolParameter("path", "string", "Path to the file (relative or absolute)", required=True),
        ToolParameter("content", "string", "Content to write to the file", required=True),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            # Extract parameters
            path = params.get("path")
            if not path:
                return error_result("Missing required parameter: path")
            
            content = params.get("content")
            if content is None:
                return error_result("Missing required parameter: content")
            
            # Resolve path
            file_path = self._resolve_path(path)
            str_path = str(file_path)
            
            # Check if trying to write to project root itself
            if file_path == Path(self.project_root or ""):
                return error_result("Cannot write to project root directory")
            
            # Validate content size
            MAX_SIZE = 1024 * 1024  # 1MB limit
            content_bytes = content.encode('utf-8')
            if len(content_bytes) > MAX_SIZE:
                return error_result(f"Content too large ({len(content_bytes):,} bytes). Max: 1MB.")
            
            # PERFORMANCE & SAFETY: Use PreciseEditor if available
            if self.precise_editor and hasattr(self.precise_editor, 'write'):
                result = self.precise_editor.write(str_path, content)
                duration_ms = (time.time() - start_time) * 1000
                
                if result.success:
                    # Sync cache to prevent "disappearing" files in AI loop
                    self._sync_file_cache(str_path, content)
                    
                    # Check if actually written or just idempotent success
                    msg = f"Successfully written file: {path}"
                    if result.error and "NO_CHANGE" in result.error:
                        msg = f"ℹ️ No changes needed: {path} already contains this exact content."
                    
                    return success_result(
                        result=msg,
                        duration_ms=duration_ms,
                        metadata={
                            'file_path': str_path,
                            'lines': result.lines_after,
                            'using_editor': True,
                            'written': "NO_CHANGE" not in (result.error or "")
                        }
                    )
                else:
                    return error_result(f"Write failed: {result.error}", duration_ms)
            
            # Check if file already exists (for warning)
            file_exists = file_path.exists()
            
            # Create parent directories
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write content
            file_path.write_text(content, encoding='utf-8')
            
            # Sync cache to prevent stale reads
            self._sync_file_cache(str_path, content)
            
            # Calculate stats
            duration_ms = (time.time() - start_time) * 1000
            file_size = file_path.stat().st_size
            line_count = content.count('\n') + 1
            
            return success_result(
                result=f"Successfully {'overwritten' if file_exists else 'created'} file: {path}",
                duration_ms=duration_ms,
                metadata={
                    'file_path': str_path,
                    'file_size_bytes': file_size,
                    'line_count': line_count,
                    'was_existing': file_exists,
                    'using_editor': False
                }
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Failed to write file: {str(e)}", duration_ms)
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Enhanced validation for write operations."""
        is_valid, message = super().validate_params(params)
        
        if not is_valid:
            return False, message
        
        # Additional checks
        path = params.get("path", "")
        if not path:
            return False, "Path cannot be empty"
        
        # Prevent writing to dangerous locations
        dangerous_paths = ['/', '\\', 'C:\\', 'C:/', '/root', '/home']
        if path in dangerous_paths or path.rstrip('/\\') in dangerous_paths:
            return False, "Cannot write to system root directory"
        
        return True, "OK"
