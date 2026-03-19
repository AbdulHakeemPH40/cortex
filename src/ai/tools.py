"""
Tool System for Cortex AI Agent IDE
Allows AI to use tools to interact with the IDE environment
"""

import os
import subprocess
import time
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from pathlib import Path
from src.utils.logger import get_logger

log = get_logger("tool_registry")

# Simple file cache to avoid re-reading same files
_file_cache: Dict[str, tuple[str, float]] = {}
_file_cache_ttl = 5.0  # Cache TTL in seconds

def _get_cached_file(path: str) -> Optional[str]:
    """Get file content from cache if available and not expired."""
    if path in _file_cache:
        content, timestamp = _file_cache[path]
        if time.time() - timestamp < _file_cache_ttl:
            return content
        else:
            del _file_cache[path]
    return None

def _set_cached_file(path: str, content: str):
    """Cache file content with timestamp."""
    _file_cache[path] = (content, time.time())

def _clear_file_cache():
    """Clear the file cache."""
    _file_cache.clear()


@dataclass
class ToolParameter:
    """Parameter definition for a tool."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class ToolResult:
    """Result from tool execution."""
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time: float = 0.0


class Tool:
    """Represents a tool the AI can use."""
    
    def __init__(self, name: str, description: str, parameters: List[ToolParameter], 
                 function: Callable, requires_confirmation: bool = False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.function = function
        self.requires_confirmation = requires_confirmation
        
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate parameters before execution."""
        # Check required parameters
        for param in self.parameters:
            if param.required and param.name not in params:
                return False, f"Missing required parameter: {param.name}"
                
        # Check parameter types (basic validation)
        for param_name, param_value in params.items():
            param_def = next((p for p in self.parameters if p.name == param_name), None)
            if param_def:
                if param_def.type == "int" and not isinstance(param_value, int):
                    try:
                        params[param_name] = int(param_value)
                    except:
                        return False, f"Parameter {param_name} must be an integer"
                elif param_def.type == "bool" and not isinstance(param_value, bool):
                    params[param_name] = str(param_value).lower() in ['true', '1', 'yes']
                    
        return True, None
        
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        """Execute the tool with given parameters."""
        import time
        
        start_time = time.time()
        
        # Validate parameters
        valid, error_msg = self.validate_params(params)
        if not valid:
            return ToolResult(success=False, result=None, error=error_msg)
            
        # Execute tool
        try:
            result = self.function(**params)
            execution_time = time.time() - start_time
            return ToolResult(success=True, result=result, execution_time=execution_time)
        except Exception as e:
            execution_time = time.time() - start_time
            log.error(f"Tool {self.name} execution failed: {e}")
            return ToolResult(success=False, result=None, error=str(e), execution_time=execution_time)
            
    def get_description_for_ai(self) -> str:
        """Get tool description formatted for AI prompt."""
        desc = f"{self.name}: {self.description}"
        if self.parameters:
            params_str = ", ".join([
                f"{p.name} ({p.type}){' [required]' if p.required else ''}"
                for p in self.parameters
            ])
            desc += f" | Parameters: {params_str}"
        return desc


class ToolRegistry:
    """Registry of available tools for the AI."""
    
    def __init__(self, file_manager=None, terminal_widget=None, git_manager=None, project_root=None):
        self.file_manager = file_manager
        self.terminal_widget = terminal_widget
        self.git_manager = git_manager
        self.project_root = project_root
        self.tools: Dict[str, Tool] = {}
        self._register_default_tools()
        
    def _register_default_tools(self):
        """Register the default set of tools."""
        
        # File operations
        self.register_tool(
            name="read_file",
            description="Read the contents of a file",
            parameters=[
                ToolParameter("path", "string", "Path to the file to read", required=True),
                ToolParameter("limit", "int", "Maximum number of characters to read", required=False, default=5000)
            ],
            function=self._read_file
        )
        
        self.register_tool(
            name="write_file",
            description="Write content to a file (creates if doesn't exist)",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("content", "string", "Content to write", required=True)
            ],
            function=self._write_file,
            requires_confirmation=True
        )
        
        self.register_tool(
            name="edit_file",
            description="Edit a specific part of a file using find and replace",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("old_string", "string", "Text to find and replace", required=True),
                ToolParameter("new_string", "string", "Replacement text", required=True)
            ],
            function=self._edit_file,
            requires_confirmation=True
        )

        self.register_tool(
            name="delete_path",
            description="Delete a file or directory (recursively). For bulk delete, use run_command instead.",
            parameters=[
                ToolParameter("path", "string", "Path to the file or directory to delete", required=True),
                ToolParameter("recursive", "bool", "Whether to delete recursively if it's a directory", required=False, default=True)
            ],
            function=self._delete_path,
            requires_confirmation=True  # Ask user for confirmation
        )
        
        self.register_tool(
            name="list_directory",
            description="List files and directories in a path",
            parameters=[
                ToolParameter("path", "string", "Directory path (default: current directory)", required=False, default="."),
                ToolParameter("show_hidden", "bool", "Show hidden files", required=False, default=False)
            ],
            function=self._list_directory
        )
        
        # Terminal operations
        self.register_tool(
            name="run_command",
            description="Run a terminal command",
            parameters=[
                ToolParameter("command", "string", "Command to execute", required=True),
                ToolParameter("timeout", "int", "Timeout in seconds", required=False, default=30)
            ],
            function=self._run_command,
            requires_confirmation=True
        )

        self.register_tool(
            name="read_terminal",
            description="Read the current output of the terminal",
            parameters=[
                ToolParameter("lines", "int", "Number of recent lines to read", required=False, default=50)
            ],
            function=self._read_terminal
        )
        
        # Git operations
        self.register_tool(
            name="git_status",
            description="Get git repository status",
            parameters=[],
            function=self._git_status
        )
        
        self.register_tool(
            name="git_diff",
            description="Show git diff for files",
            parameters=[
                ToolParameter("file_path", "string", "Specific file to diff (optional)", required=False, default=None),
                ToolParameter("staged", "bool", "Show staged changes", required=False, default=False)
            ],
            function=self._git_diff
        )
        
        # Search operations
        self.register_tool(
            name="search_code",
            description="Search for text in the codebase",
            parameters=[
                ToolParameter("query", "string", "Text to search for", required=True),
                ToolParameter("file_pattern", "string", "File pattern to search in (e.g., *.py)", required=False, default="*")
            ],
            function=self._search_code
        )
        
    def register_tool(self, name: str, description: str, parameters: List[ToolParameter], 
                     function: Callable, requires_confirmation: bool = False):
        """Register a new tool."""
        self.tools[name] = Tool(name, description, parameters, function, requires_confirmation)
        log.info(f"Registered tool: {name}")
        
    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self.tools.get(name)
        
    def get_all_tools(self) -> Dict[str, Tool]:
        """Get all registered tools."""
        return self.tools.copy()
        
    def get_tools_for_agent(self, allowed_tools: List[str]) -> Dict[str, Tool]:
        """Get tools filtered by allowed list."""
        return {name: tool for name, tool in self.tools.items() if name in allowed_tools}
        
    def get_tool_descriptions(self, allowed_tools: Optional[List[str]] = None) -> str:
        """Get descriptions of all tools for AI prompt."""
        tools_to_describe = self.tools
        if allowed_tools:
            tools_to_describe = {k: v for k, v in self.tools.items() if k in allowed_tools}
            
        descriptions = []
        for tool in tools_to_describe.values():
            descriptions.append(tool.get_description_for_ai())
            
        return "\n".join(descriptions)
        
    def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name with parameter validation."""
        tool = self.tools.get(tool_name)
        if not tool:
            return ToolResult(success=False, result=None, error=f"Tool '{tool_name}' not found")
        
        # Validate required parameters
        for param in tool.parameters:
            if param.required and (param.name not in params or params[param.name] is None or params[param.name] == ""):
                return ToolResult(
                    success=False, 
                    result=None, 
                    error=f"Missing required parameter: {param.name}. Required params: {[p.name for p in tool.parameters if p.required]}"
                )
            
        return tool.execute(params)
        
    # Tool implementations
    def _read_file(self, path: str, limit: int = 5000) -> str:
        """Read file contents from project directory with caching."""
        try:
            # Resolve path relative to project root (NOT IDE directory)
            working_dir = self.project_root or os.getcwd()
            if not os.path.isabs(path):
                path = os.path.join(working_dir, path)
            
            # Check cache first
            cached = _get_cached_file(path)
            if cached is not None:
                log.debug(f"Cache hit for {path}")
                if len(cached) > limit:
                    return cached[:limit] + "\n... [truncated]"
                return cached
            
            # Read from disk and cache
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                _set_cached_file(path, content)  # Cache full content
                if len(content) > limit:
                    return content[:limit] + "\n... [truncated]"
                return content
        except Exception as e:
            raise Exception(f"Failed to read file: {e}")
            
    def _write_file(self, path: str, content: str) -> str:
        """Write content to file in project directory."""
        try:
            # Resolve path relative to project root (NOT IDE directory)
            working_dir = self.project_root or os.getcwd()
            if not os.path.isabs(path):
                path = os.path.join(working_dir, path)
                
            # Create directory if needed
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Update cache with new content
            _set_cached_file(path, content)
                
            return f"File written successfully: {path}"
        except Exception as e:
            raise Exception(f"Failed to write file: {e}")
            
    def _edit_file(self, path: str, old_string: str, new_string: str) -> str:
        """Edit file by replacing text in project directory."""
        try:
            # Resolve path relative to project root (NOT IDE directory)
            working_dir = self.project_root or os.getcwd()
            if not os.path.isabs(path):
                path = os.path.join(working_dir, path)
                
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if old_string not in content:
                raise Exception(f"Could not find text to replace in {path}")
                
            new_content = content.replace(old_string, new_string, 1)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # Update cache with new content
            _set_cached_file(path, new_content)
                
            return f"File edited successfully: {path}"
        except Exception as e:
            raise Exception(f"Failed to edit file: {e}")

    # PROTECTED PATHS - Cannot be deleted
    PROTECTED_PATHS = [
        # System directories
        "c:\\", "c:/", "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64",
        "/proc", "/root", "/sbin", "/sys", "/usr", "/var",
        "c:\\windows", "c:\\program files", "c:\\program files (x86)",
        "c:\\programdata", "c:\\users", "c:\\system32",
        # Common user directories
        "~", "~/", os.path.expanduser("~"),
        os.path.expanduser("~/documents"),
        os.path.expanduser("~/downloads"),
        os.path.expanduser("~/desktop"),
        os.path.expanduser("~/pictures"),
        os.path.expanduser("~/videos"),
        os.path.expanduser("~/music"),
    ]
    
    def _is_protected_path(self, path: str) -> tuple[bool, str]:
        """Check if path is protected from deletion.
        
        Returns: (is_protected, reason)
        """
        import os
        
        # Normalize path
        path = os.path.normpath(os.path.abspath(path)).lower()
        
        # Check against protected paths
        for protected in self.PROTECTED_PATHS:
            protected_normalized = os.path.normpath(os.path.abspath(protected)).lower()
            # Check if path is the protected path or inside it
            if path == protected_normalized or path.startswith(protected_normalized + os.sep):
                return True, f"Cannot delete protected system path: {protected}"
        
        # Check if path is outside project root (when project is set)
        if self.project_root:
            project_root_normalized = os.path.normpath(os.path.abspath(self.project_root)).lower()
            if not path.startswith(project_root_normalized):
                return True, "Cannot delete files outside project directory"
        
        # Check for dangerous patterns
        dangerous_patterns = ['..', '~', '*', '?']
        for pattern in dangerous_patterns:
            if pattern in os.path.basename(path):
                return True, f"Path contains dangerous pattern: {pattern}"
        
        return False, ""
    
    def _delete_path(self, path: str, recursive: bool = True) -> str:
        """Delete a file or directory in project directory."""
        try:
            # Handle relative paths - use project root, NOT IDE directory
            working_dir = self.project_root or os.getcwd()
            if not os.path.isabs(path):
                path = os.path.join(working_dir, path)
            
            # Normalize path
            path = os.path.normpath(os.path.abspath(path))
            
            # SECURITY CHECK: Is this a protected path?
            is_protected, reason = self._is_protected_path(path)
            if is_protected:
                return f"❌ BLOCKED: {reason}"
            
            if not os.path.exists(path):
                return f"Path does not exist: {path}"
            
            # Additional check: Don't allow deleting entire project root
            if self.project_root:
                project_root_normalized = os.path.normpath(os.path.abspath(self.project_root)).lower()
                if os.path.normpath(path).lower() == project_root_normalized:
                    return "❌ BLOCKED: Cannot delete entire project root directory"
            
            # Check if it's a directory with many files (potential accident)
            if os.path.isdir(path):
                file_count = sum([len(files) for r, d, files in os.walk(path)])
                if file_count > 50:
                    return f"❌ BLOCKED: Directory contains {file_count} files. Too many to delete safely."
            
            import shutil
            if os.path.isdir(path):
                if recursive:
                    shutil.rmtree(path)
                    return f"✅ Directory deleted recursively: {os.path.basename(path)}"
                else:
                    os.rmdir(path)
                    return f"✅ Directory deleted: {os.path.basename(path)}"
            else:
                os.remove(path)
                return f"✅ File deleted: {os.path.basename(path)}"
        except Exception as e:
            raise Exception(f"Failed to delete path: {e}")
            
    def _list_directory(self, path: str = ".", show_hidden: bool = False) -> str:
        """List directory contents in project directory."""
        try:
            # Use project root, NOT IDE directory
            working_dir = self.project_root or os.getcwd()
            if not os.path.isabs(path):
                path = os.path.join(working_dir, path)
                
            items = []
            for item in sorted(os.listdir(path)):
                if not show_hidden and item.startswith('.'):
                    continue
                    
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    items.append(f"📁 {item}/")
                else:
                    items.append(f"📄 {item}")
                    
            return "\n".join(items) if items else "Directory is empty"
        except Exception as e:
            raise Exception(f"Failed to list directory: {e}")
            
    def _run_command(self, command: str, timeout: int = 30) -> str:
        """Run terminal command in the project directory."""
        try:
            # Determine the working directory - MUST be project root, not IDE directory
            working_dir = self.project_root or os.getcwd()
            
            # Security check: Ensure we're not running in the IDE directory
            if 'Cortex_Ai_Agent' in working_dir or 'Cortex' in working_dir.split(os.sep)[-3:]:
                log.warning(f"Terminal attempting to run in IDE directory: {working_dir}")
                log.warning("Falling back to project root or user home")
                working_dir = self.project_root or os.path.expanduser("~")
            
            log.info(f"Running command in directory: {working_dir}")
            
            if self.terminal_widget and hasattr(self.terminal_widget, 'execute_command'):
                # Ensure terminal is set to the correct directory first
                if hasattr(self.terminal_widget, 'set_cwd'):
                    self.terminal_widget.set_cwd(working_dir)
                self.terminal_widget.execute_command(command)
                return f"Command sent to terminal: {command}"
            else:
                # Fallback to subprocess with correct working directory
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=timeout, cwd=working_dir
                )
                output = result.stdout
                if result.stderr:
                    output += "\n" + result.stderr
                return output
        except subprocess.TimeoutExpired:
            raise Exception(f"Command timed out after {timeout} seconds")
        except Exception as e:
            raise Exception(f"Failed to run command: {e}")

    def _read_terminal(self, lines: int = 50) -> str:
        """Read terminal output."""
        if self.terminal_widget and hasattr(self.terminal_widget, 'get_last_output'):
            return self.terminal_widget.get_last_output(lines)
        return "Terminal output not available."
            
    def _git_status(self) -> str:
        """Get git status."""
        if not self.git_manager or not self.git_manager.is_repo():
            return "Not a git repository"
            
        try:
            files = self.git_manager.get_status()
            if not files:
                return "Working tree clean"
                
            lines = []
            for f in files:
                status_symbol = f.status.value
                staged_symbol = "✓" if f.staged else " "
                lines.append(f"{staged_symbol} {status_symbol} {f.path}")
                
            return "\n".join(lines)
        except Exception as e:
            raise Exception(f"Failed to get git status: {e}")
            
    def _git_diff(self, file_path: Optional[str] = None, staged: bool = False) -> str:
        """Get git diff."""
        if not self.git_manager or not self.git_manager.is_repo():
            return "Not a git repository"
            
        try:
            diff = self.git_manager.get_diff(file_path, staged)
            return diff if diff else "No changes to display"
        except Exception as e:
            raise Exception(f"Failed to get git diff: {e}")
            
    def _search_code(self, query: str, file_pattern: str = "*") -> str:
        """Search for text in codebase efficiently."""
        try:
            results = []
            search_path = Path(self.project_root or os.getcwd())
            
            # Exclude common large/binary directories to boost performance
            exclude_dirs = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache', 'dist', 'build'}
            
            for file_path in search_path.rglob(file_pattern):
                # Faster path filtering
                if any(ex in file_path.parts for ex in exclude_dirs):
                    continue
                
                if file_path.is_file():
                    try:
                        # Stream the file content instead of reading all at once
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                if query in line:
                                    results.append(f"{file_path.relative_to(search_path)}:{i}: {line.strip()}")
                                    if len(results) >= 20: # Hard limit for response size
                                        return "\n".join(results)
                    except:
                        continue
                        
            if not results:
                return f"No results found for '{query}'"
                
            return "\n".join(results)
            
        except Exception as e:
            raise Exception(f"Failed to search code: {e}")
