# ------------------------------------------------------------
# GrepTool.py
# Python conversion of GrepTool.ts (lines 1-578)
# 
# A tool for searching file contents with regex using ripgrep.
# ------------------------------------------------------------

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Literal, TypedDict
import asyncio
import subprocess

# ============================================================
# LOCAL IMPORTS
# ============================================================

try:
    from .prompt import GREP_TOOL_NAME, get_description
except ImportError:
    GREP_TOOL_NAME = "Grep"
    def get_description():
        return "Search for text patterns in files using ripgrep."


# ============================================================
# CONSTANTS
# ============================================================

# Version control system directories to exclude from searches
VCS_DIRECTORIES_TO_EXCLUDE = [
    '.git',
    '.svn',
    '.hg',
    '.bzr',
    '.jj',
    '.sl',
]

# Default cap on grep results when head_limit is unspecified
DEFAULT_HEAD_LIMIT = 250


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def get_cwd() -> str:
    """Get current working directory."""
    return os.getcwd()

def is_enoent(exc: Exception) -> bool:
    """Check if exception is FileNotFoundError."""
    return isinstance(exc, FileNotFoundError)

def plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    """Return plural form if n != 1."""
    if n == 1:
        return singular
    return plural or (singular + 's')

def check_read_permission_for_tool(tool_name: str, input_: Any, ctx: Any) -> bool:
    """Check read permission for tool."""
    return True  # Stub - replace with real implementation

def match_wildcard_pattern(pattern: str, text: str) -> bool:
    """Match wildcard pattern against text."""
    import fnmatch
    return fnmatch.fnmatch(text, pattern)

def normalize_patterns_to_path(patterns: List[str], cwd: str) -> List[str]:
    """Normalize ignore patterns to path."""
    return patterns  # Stub - replace with real implementation

def get_file_read_ignore_patterns(ctx: Any) -> List[str]:
    """Get file read ignore patterns."""
    return []  # Stub - replace with real implementation

async def get_glob_exclusions_for_plugin_cache(absolute_path: str) -> List[str]:
    """Get glob exclusions for plugin cache."""
    return []  # Stub - replace with real implementation

def suggest_path_under_cwd(path: str) -> Optional[str]:
    """Suggest path under current working directory."""
    return None  # Stub - replace with real implementation

FILE_NOT_FOUND_CWD_NOTE = "Make sure the file path is correct."


class AsyncFS:
    """Async filesystem operations."""
    
    async def stat(self, p: str) -> Dict[str, Any]:
        """Get file stats."""
        st = os.stat(p)
        return {
            "size": st.st_size,
            "mtimeMs": st.st_mtime * 1000,
        }

def get_fs_implementation() -> AsyncFS:
    """Return async filesystem implementation."""
    return AsyncFS()


async def ripgrep(args: List[str], cwd: str, signal: Optional[asyncio.Event] = None) -> List[str]:
    """
    Execute ripgrep command and return results.
    
    Args:
        args: Command line arguments for ripgrep
        cwd: Working directory
        signal: Optional cancellation signal
        
    Returns:
        List of output lines
        
    Raises:
        RipgrepTimeoutError: If search times out
    """
    try:
        # Build full command
        cmd = ['rg'] + args
        
        # Execute ripgrep
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        
        # Wait for completion with optional timeout/cancellation
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0  # 30 second timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            raise RipgrepTimeoutError(f"Ripgrep timed out after 30s: {' '.join(cmd)}")
        
        # Check for errors
        if process.returncode != 0 and process.returncode != 1:  # 1 = no matches found
            error_msg = stderr.decode('utf-8', errors='ignore')
            if error_msg:
                raise RuntimeError(f"Ripgrep error: {error_msg}")
        
        # Parse and return results
        output = stdout.decode('utf-8', errors='ignore')
        if not output:
            return []
        
        return output.rstrip('\n').split('\n')
    
    except FileNotFoundError:
        raise RuntimeError(
            "ripgrep (rg) not found. Please install ripgrep: "
            "https://github.com/BurntSushi/ripgrep#installation"
        )


class RipgrepTimeoutError(Exception):
    """Exception raised when ripgrep times out."""
    pass


# ============================================================
# TYPE DEFINITIONS
# ============================================================

OutputMode = Literal['content', 'files_with_matches', 'count']


class GrepInput(TypedDict, total=False):
    """Grep tool input type."""
    pattern: str
    path: Optional[str]
    glob: Optional[str]
    output_mode: OutputMode
    before_context: Optional[int]
    after_context: Optional[int]
    context_lines: Optional[int]
    context: Optional[int]
    show_line_numbers: bool
    case_insensitive: bool
    type: Optional[str]
    head_limit: Optional[int]
    offset: int
    multiline: bool


class GrepOutput(TypedDict, total=False):
    """Grep tool output type."""
    mode: OutputMode
    numFiles: int
    filenames: List[str]
    content: Optional[str]
    numLines: Optional[int]
    numMatches: Optional[int]
    appliedLimit: Optional[int]
    appliedOffset: Optional[int]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def apply_head_limit(
    items: List[Any],
    limit: Optional[int],
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Apply head limit and offset to items list.
    
    Args:
        items: List of items to limit
        limit: Maximum number of items to return (0 = unlimited)
        offset: Number of items to skip
        
    Returns:
        Dictionary with 'items' and 'appliedLimit'
    """
    # Explicit 0 = unlimited escape hatch
    if limit == 0:
        return {"items": items[offset:], "appliedLimit": None}
    
    effective_limit = limit if limit is not None else DEFAULT_HEAD_LIMIT
    sliced = items[offset:offset + effective_limit]
    
    # Only report appliedLimit when truncation actually occurred
    was_truncated = len(items) - offset > effective_limit
    applied_limit = effective_limit if was_truncated else None
    
    return {
        "items": sliced,
        "appliedLimit": applied_limit,
    }


def format_limit_info(applied_limit: Optional[int], applied_offset: Optional[int]) -> str:
    """
    Format limit/offset information for display.
    
    Args:
        applied_limit: Limit that was applied
        applied_offset: Offset that was applied
        
    Returns:
        Formatted string with limit/offset info
    """
    parts = []
    if applied_limit is not None:
        parts.append(f"limit: {applied_limit}")
    if applied_offset:
        parts.append(f"offset: {applied_offset}")
    return ', '.join(parts)


# ============================================================
# GREP TOOL CLASS
# ============================================================

class GrepTool:
    """Python equivalent of the TypeScript GrepTool."""
    
    name = GREP_TOOL_NAME
    search_hint = "search file contents with regex (ripgrep)"
    max_result_size_chars = 20_000  # 20K chars - tool result persistence threshold
    strict = True
    
    # ------------------------------------------------------------------
    # Public metadata helpers
    # ------------------------------------------------------------------
    
    @staticmethod
    async def description() -> str:
        return get_description()
    
    @staticmethod
    def user_facing_name() -> str:
        return "Search"
    
    # ------------------------------------------------------------------
    # Input / output schemas (used by the surrounding framework)
    # ------------------------------------------------------------------
    
    @staticmethod
    def input_schema() -> type:
        return GrepInput
    
    @staticmethod
    def output_schema() -> type:
        return GrepOutput
    
    # ------------------------------------------------------------------
    # Concurrency and access mode
    # ------------------------------------------------------------------
    
    @staticmethod
    def is_concurrency_safe() -> bool:
        """Check if tool is safe to run concurrently."""
        return True
    
    @staticmethod
    def is_read_only() -> bool:
        """Check if tool is read-only."""
        return True
    
    # ------------------------------------------------------------------
    # Helper for auto-classification (used by the LLM routing layer)
    # ------------------------------------------------------------------
    
    @staticmethod
    def to_auto_classifier_input(inp: Dict) -> str:
        path = inp.get("path", "")
        pattern = inp.get("pattern", "")
        return f"{pattern} in {path}" if path else pattern
    
    # ------------------------------------------------------------------
    # Search/read command classification
    # ------------------------------------------------------------------
    
    @staticmethod
    def is_search_or_read_command() -> Dict[str, bool]:
        return {"isSearch": True, "isRead": False}
    
    # ------------------------------------------------------------------
    # Path handling
    # ------------------------------------------------------------------
    
    @staticmethod
    def get_path(inp: Dict) -> str:
        return inp.get("path") or get_cwd()
    
    # ------------------------------------------------------------------
    # Permission matcher
    # ------------------------------------------------------------------
    
    @staticmethod
    async def prepare_permission_matcher(pattern: str):
        """Create permission matcher function."""
        def match_rule(rule_pattern: str) -> bool:
            return match_wildcard_pattern(rule_pattern, pattern)
        return match_rule
    
    # ------------------------------------------------------------------
    # Core validation logic - mirrors validateInput in TS
    # ------------------------------------------------------------------
    
    @staticmethod
    async def validate_input(inp: Dict) -> Dict[str, Any]:
        """Validate grep input."""
        path = inp.get("path")
        
        # If path is provided, validate that it exists
        if path:
            fs = get_fs_implementation()
            absolute_path = expand_path(path)
            
            # SECURITY: Skip filesystem operations for UNC paths
            if absolute_path.startswith("\\\\") or absolute_path.startswith("//"):
                return {"result": True}
            
            try:
                await fs.stat(absolute_path)
            except Exception as e:
                if is_enoent(e):
                    cwd_suggestion = suggest_path_under_cwd(absolute_path)
                    message = f"Path does not exist: {path}. {FILE_NOT_FOUND_CWD_NOTE} {get_cwd()}."
                    if cwd_suggestion:
                        message += f" Did you mean {cwd_suggestion}?"
                    return {
                        "result": False,
                        "message": message,
                        "errorCode": 1,
                    }
                raise
        
        return {"result": True}
    
    # ------------------------------------------------------------------
    # Permission validation
    # ------------------------------------------------------------------
    
    @staticmethod
    async def check_permissions(inp: Dict, context: Any) -> bool:
        """Check permissions for grep."""
        app_state = context.get_app_state()
        return check_read_permission_for_tool(
            GrepTool.name, inp, app_state.tool_permission_context
        )
    
    # ------------------------------------------------------------------
    # Core grep operation - mirrors call
    # ------------------------------------------------------------------
    
    @staticmethod
    async def call(
        inp: Dict,
        context: Any,
    ) -> Dict[str, Any]:
        """Execute grep search."""
        pattern = inp.get("pattern", "")
        path = inp.get("path")
        glob_pattern = inp.get("glob")
        file_type = inp.get("type")
        output_mode = inp.get("output_mode", "files_with_matches")
        context_before = inp.get("before_context")
        context_after = inp.get("after_context")
        context_c = inp.get("context_lines")
        context = inp.get("context")
        show_line_numbers = inp.get("show_line_numbers", True)
        case_insensitive = inp.get("case_insensitive", False)
        head_limit = inp.get("head_limit")
        offset = inp.get("offset", 0)
        multiline = inp.get("multiline", False)
        
        absolute_path = expand_path(path) if path else get_cwd()
        args = ['--hidden']
        
        # --------------------------------------------------------------
        # Exclude VCS directories to avoid noise
        # --------------------------------------------------------------
        for dir_name in VCS_DIRECTORIES_TO_EXCLUDE:
            args.extend(['--glob', f'!{dir_name}'])
        
        # --------------------------------------------------------------
        # Limit line length to prevent clutter
        # --------------------------------------------------------------
        args.extend(['--max-columns', '500'])
        
        # --------------------------------------------------------------
        # Apply multiline flags only when explicitly requested
        # --------------------------------------------------------------
        if multiline:
            args.extend(['-U', '--multiline-dotall'])
        
        # --------------------------------------------------------------
        # Add optional flags
        # --------------------------------------------------------------
        if case_insensitive:
            args.append('-i')
        
        # --------------------------------------------------------------
        # Add output mode flags
        # --------------------------------------------------------------
        if output_mode == 'files_with_matches':
            args.append('-l')
        elif output_mode == 'count':
            args.append('-c')
        
        # --------------------------------------------------------------
        # Add line numbers if requested
        # --------------------------------------------------------------
        if show_line_numbers and output_mode == 'content':
            args.append('-n')
        
        # --------------------------------------------------------------
        # Add context flags (-C/context takes precedence)
        # --------------------------------------------------------------
        if output_mode == 'content':
            if context is not None:
                args.extend(['-C', str(context)])
            elif context_c is not None:
                args.extend(['-C', str(context_c)])
            else:
                if context_before is not None:
                    args.extend(['-B', str(context_before)])
                if context_after is not None:
                    args.extend(['-A', str(context_after)])
        
        # --------------------------------------------------------------
        # Handle patterns starting with dash
        # --------------------------------------------------------------
        if pattern.startswith('-'):
            args.extend(['-e', pattern])
        else:
            args.append(pattern)
        
        # --------------------------------------------------------------
        # Add type filter if specified
        # --------------------------------------------------------------
        if file_type:
            args.extend(['--type', file_type])
        
        # --------------------------------------------------------------
        # Add glob patterns
        # --------------------------------------------------------------
        if glob_pattern:
            # Split on commas and spaces, preserve brace patterns
            glob_patterns = []
            raw_patterns = glob_pattern.split()
            
            for raw_pattern in raw_patterns:
                if '{' in raw_pattern and '}' in raw_pattern:
                    glob_patterns.append(raw_pattern)
                else:
                    glob_patterns.extend([p for p in raw_pattern.split(',') if p])
            
            for gp in filter(None, glob_patterns):
                args.extend(['--glob', gp])
        
        # --------------------------------------------------------------
        # Add ignore patterns
        # --------------------------------------------------------------
        # Note: Would need actual implementations of these functions
        # For now, skipping ignore patterns
        # In real implementation:
        # app_state = context.get_app_state()
        # ignore_patterns = normalize_patterns_to_path(
        #     get_file_read_ignore_patterns(app_state.tool_permission_context),
        #     get_cwd()
        # )
        # for ignore_pattern in ignore_patterns:
        #     rg_ignore = f"!{ignore_pattern}" if ignore_pattern.startswith('/') else f"!**/{ignore_pattern}"
        #     args.extend(['--glob', rg_ignore])
        
        # --------------------------------------------------------------
        # Exclude orphaned plugin version directories
        # --------------------------------------------------------------
        # In real implementation:
        # for exclusion in await get_glob_exclusions_for_plugin_cache(absolute_path):
        #     args.extend(['--glob', exclusion])
        
        # --------------------------------------------------------------
        # Execute ripgrep
        # --------------------------------------------------------------
        # WSL has severe performance penalty for file reads
        # Timeout handled by ripgrep function itself
        abort_controller = getattr(context, "abort_controller", None)
        signal = getattr(abort_controller, "signal", None) if abort_controller else None
        
        results = await ripgrep(args, absolute_path, signal)
        
        # --------------------------------------------------------------
        # Process results based on output mode
        # --------------------------------------------------------------
        if output_mode == 'content':
            # Apply head_limit first
            limited_result = apply_head_limit(results, head_limit, offset)
            limited_results = limited_result["items"]
            applied_limit = limited_result["appliedLimit"]
            
            # Convert absolute paths to relative paths
            final_lines = []
            for line in limited_results:
                colon_index = line.find(':')
                if colon_index > 0:
                    file_path = line[:colon_index]
                    rest = line[colon_index:]
                    final_lines.append(to_relative_path(file_path) + rest)
                else:
                    final_lines.append(line)
            
            output = {
                "mode": "content",
                "numFiles": 0,
                "filenames": [],
                "content": '\n'.join(final_lines),
                "numLines": len(final_lines),
            }
            
            if applied_limit is not None:
                output["appliedLimit"] = applied_limit
            if offset > 0:
                output["appliedOffset"] = offset
            
            return {"data": output}
        
        elif output_mode == 'count':
            # Apply head_limit first
            limited_result = apply_head_limit(results, head_limit, offset)
            limited_results = limited_result["items"]
            applied_limit = limited_result["appliedLimit"]
            
            # Convert absolute paths to relative paths
            final_count_lines = []
            for line in limited_results:
                colon_index = line.rfind(':')
                if colon_index > 0:
                    file_path = line[:colon_index]
                    count_str = line[colon_index:]
                    final_count_lines.append(to_relative_path(file_path) + count_str)
                else:
                    final_count_lines.append(line)
            
            # Parse count output to extract total matches and file count
            total_matches = 0
            file_count = 0
            for line in final_count_lines:
                colon_index = line.rfind(':')
                if colon_index > 0:
                    count_str = line[colon_index + 1:]
                    try:
                        count = int(count_str)
                        total_matches += count
                        file_count += 1
                    except ValueError:
                        pass
            
            output = {
                "mode": "count",
                "numFiles": file_count,
                "filenames": [],
                "content": '\n'.join(final_count_lines),
                "numMatches": total_matches,
            }
            
            if applied_limit is not None:
                output["appliedLimit"] = applied_limit
            if offset > 0:
                output["appliedOffset"] = offset
            
            return {"data": output}
        
        else:  # files_with_matches mode (default)
            # Get file stats for sorting
            fs = get_fs_implementation()
            stats = await asyncio.gather(
                *[fs.stat(f) for f in results],
                return_exceptions=True
            )
            
            # Sort by modification time (most recent first)
            def get_mtime(i: int) -> float:
                stat_result = stats[i]
                if isinstance(stat_result, Exception):
                    return 0
                return stat_result.get("mtimeMs", 0) if isinstance(stat_result, dict) else 0
            
            sorted_matches = sorted(
                enumerate(results),
                key=lambda x: get_mtime(x[0]),
                reverse=True
            )
            
            # Extract just the filenames in sorted order
            sorted_filenames = [filename for _, filename in sorted_matches]
            
            # Apply head_limit to sorted file list
            limited_result = apply_head_limit(sorted_filenames, head_limit, offset)
            final_matches = limited_result["items"]
            applied_limit = limited_result["appliedLimit"]
            
            # Convert absolute paths to relative paths
            relative_matches = [to_relative_path(f) for f in final_matches]
            
            output = {
                "mode": "files_with_matches",
                "filenames": relative_matches,
                "numFiles": len(relative_matches),
            }
            
            if applied_limit is not None:
                output["appliedLimit"] = applied_limit
            if offset > 0:
                output["appliedOffset"] = offset
            
            return {"data": output}
    
    # ------------------------------------------------------------------
    # Mapping to the LLM-compatible block format
    # ------------------------------------------------------------------
    
    @staticmethod
    def map_tool_result_to_block(data: Dict, tool_use_id: str) -> Dict[str, Any]:
        """Map tool result to LLM block format."""
        mode = data.get("mode", "files_with_matches")
        num_files = data.get("numFiles", 0)
        filenames = data.get("filenames", [])
        content = data.get("content")
        num_matches = data.get("numMatches", 0)
        applied_limit = data.get("appliedLimit")
        applied_offset = data.get("appliedOffset")
        
        limit_info = format_limit_info(applied_limit, applied_offset)
        
        if mode == 'content':
            result_content = content or 'No matches found'
            final_content = f"{result_content}\n\n[Showing results with pagination = {limit_info}]" if limit_info else result_content
            
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": final_content,
            }
        
        elif mode == 'count':
            raw_content = content or 'No matches found'
            files = num_files
            summary = f"\n\nFound {num_matches} total {plural(num_matches, 'occurrence', 'occurrences')} across {files} {plural(files, 'file')}."
            if limit_info:
                summary = summary[:-1] + f" with pagination = {limit_info}"
            
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": raw_content + summary,
            }
        
        else:  # files_with_matches
            if num_files == 0:
                return {
                    "tool_use_id": tool_use_id,
                    "type": "tool_result",
                    "content": "No files found",
                }
            
            result = f"Found {num_files} {plural(num_files, 'file')}"
            if limit_info:
                result += f" {limit_info}"
            result += '\n' + '\n'.join(filenames)
            
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": result,
            }


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "GrepTool",
    "GREP_TOOL_NAME",
    "GrepInput",
    "GrepOutput",
    "ripgrep",
    "RipgrepTimeoutError",
]
