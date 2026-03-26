"""
Edit Tool - OpenCode-style precise file editing
Search/replace editing with occurrence validation.
Based on packages/opencode/src/tool/edit.ts
"""

import time
from pathlib import Path
from typing import Dict, Any

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class EditTool(BaseTool):
    """
    Precise search/replace editing tool.
    
    Features:
    - Find and replace text in files
    - Occurrence count validation (prevents accidental mass edits)
    - Context-aware matching
    - Detailed error messages with line numbers
    - Diff statistics
    
    Safety:
    - Requires user confirmation
    - Validates uniqueness of search text
    - Shows all match locations if multiple found
    """
    
    name = "edit_file"
    description = "Surgical find-and-replace. old_string MUST be UNIQUE (include 3+ lines of context). If not unique, the error message will show all match line numbers."
    requires_confirmation = True
    is_safe = False
    
    parameters = [
        ToolParameter("path", "string", "Path to the file to edit", required=True),
        ToolParameter("old_string", "string", "Exact text to find (include 3+ lines of context for uniqueness)", required=True),
        ToolParameter("new_string", "string", "Replacement text", required=True),
        ToolParameter("expected_occurrences", "integer", "Error if matches != this count (default: 1)", required=False, default=1),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            # Extract parameters
            path = params.get("path")
            if not path:
                return error_result("Missing required parameter: path")
            
            old_string = params.get("old_string")
            if not old_string:
                return error_result("Missing required parameter: old_string")
            
            new_string = params.get("new_string")
            if new_string is None:
                return error_result("Missing required parameter: new_string")
            
            expected_occurrences = params.get("expected_occurrences", 1)
            
            # Resolve path
            file_path = self._resolve_path(path)
            str_path = str(file_path)
            
            # PERFORMANCE & SAFETY: Use PreciseEditor if available
            if self.precise_editor and hasattr(self.precise_editor, 'edit'):
                result = self.precise_editor.edit(
                    str_path, 
                    old_string, 
                    new_string, 
                    expected_count=expected_occurrences
                )
                
                duration_ms = (time.time() - start_time) * 1000
                
                if result.success:
                    # Sync cache to prevent "disappearing" files or stale reads
                    self._sync_file_cache(str_path)
                    
                    return success_result(
                        result=f"Successfully edited file: {path} ({result.delta} lines delta)",
                        duration_ms=duration_ms,
                        metadata={
                            'file_path': str_path,
                            'lines_added': result.lines_added,
                            'lines_removed': result.lines_removed,
                            'delta': result.delta,
                            'using_editor': True
                        }
                    )
                else:
                    err_msg = result.error
                    if result.action:
                        err_msg += f"\nHINT: {result.action}"
                    return error_result(f"Edit failed: {err_msg}", duration_ms)
            
            # Fallback to direct synchronous implementation (legacy/standalone)
            if not file_path.exists():
                return error_result(f"File not found: {file_path}")
            
            if not file_path.is_file():
                return error_result(f"Not a file: {file_path}")
            
            # Read content
            try:
                content = file_path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                return error_result("Cannot edit binary file")
            
            # Find all occurrences
            occurrences = []
            start_idx = 0
            while True:
                idx = content.find(old_string, start_idx)
                if idx == -1:
                    break
                occurrences.append(idx)
                start_idx = idx + 1
            
            total_occurrences = len(occurrences)
            
            # Validate occurrence count
            if total_occurrences == 0:
                # Try to provide helpful error with similar matches
                return error_result(
                    f"Text not found in file. "
                    f"Make sure the text matches exactly (including whitespace and indentation). "
                    f"Include more context (3+ lines) for better matching."
                )
            
            if total_occurrences != expected_occurrences:
                # Found wrong number of occurrences - show line numbers
                line_numbers = []
                for idx in occurrences:
                    line_num = content[:idx].count('\n') + 1
                    line_numbers.append(line_num)
                
                error_msg = (
                    f"Expected {expected_occurrences} occurrence(s), but found {total_occurrences}. "
                    f"Found at line(s): {', '.join(map(str, line_numbers))}. "
                    f"\n\nTo fix this:\n"
                    f"1. Include more context in old_string (3+ lines)\n"
                    f"2. Make the search text more specific\n"
                    f"3. Or set expected_occurrences={total_occurrences} if you want to replace all"
                )
                return error_result(error_msg)
            
            # Perform replacement
            # Replace ALL occurrences if expected_occurrences matches total found
            # Otherwise replace only the specified number
            if expected_occurrences == total_occurrences:
                # Replace all occurrences
                new_content = content.replace(old_string, new_string)
            else:
                # Replace only first N occurrences
                new_content = content.replace(old_string, new_string, expected_occurrences)
            
            # Write back
            file_path.write_text(new_content, encoding='utf-8')
            
            # Sync cache to prevent stale reads
            self._sync_file_cache(str_path, new_content)
            
            # Calculate diff stats
            old_lines = old_string.count('\n') + 1
            new_lines = new_string.count('\n') + 1
            lines_changed = new_lines - old_lines
            
            old_chars = len(old_string)
            new_chars = len(new_string)
            chars_changed = new_chars - old_chars
            
            # Calculate stats
            duration_ms = (time.time() - start_time) * 1000
            
            return success_result(
                result=f"Successfully edited file: {file_path}",
                duration_ms=duration_ms,
                metadata={
                    'file_path': str(file_path),
                    'replacements_made': expected_occurrences,
                    'lines_added': max(0, lines_changed),
                    'lines_removed': abs(min(0, lines_changed)),
                    'chars_added': max(0, chars_changed),
                    'chars_removed': abs(min(0, chars_changed)),
                    'operation': 'edit',
                    'using_editor': False
                }
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Failed to edit file: {str(e)}", duration_ms)
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Enhanced validation for edit operations."""
        is_valid, message = super().validate_params(params)
        
        if not is_valid:
            return False, message
        
        # Check that old_string is different from new_string
        old_str = params.get("old_string", "")
        new_str = params.get("new_string", "")
        
        if old_str == new_str:
            return False, "old_string and new_string are identical - no changes would be made"
        
        # Recommend including context
        if old_str.count('\n') < 2:
            # Only 1 line or less - recommend more context
            pass  # Warning only, not an error
        
        return True, "OK"
