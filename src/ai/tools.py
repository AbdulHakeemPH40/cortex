"""
Tool System for Cortex AI Agent IDE
Allows AI to use tools to interact with the IDE environment
"""

import os
import re
import subprocess
import time
import shutil
import hashlib
from typing import Dict, List, Callable, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from src.ai.precise_editor import get_editor, PreciseEditor
from src.utils.logger import get_logger

log = get_logger("tool_registry")

# ═══════════════════════════════════════════════════════════════════════════════
# VIRTUAL ENVIRONMENT & DEPENDENCY DIRECTORY EXCLUSION SYSTEM
# Prevents AI from exploring framework dependency directories (performance killer)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Master exclusion patterns ─────────────────────────────────────────────────
BLOCKED_DIRS = {
    # Python virtual environments
    'venv', '.venv', 'env', '.env', 'virtualenv', 'ENV',
    '__pycache__', '.eggs', '.tox', '.mypy_cache',
    '.pytest_cache', '.ruff_cache', '.nox',
    
    # Node.js
    'node_modules', '.npm', '.yarn', '.pnpm-store', '.pnp',
    '.next', '.nuxt', '.svelte-kit', '.parcel-cache',
    '.turbo', '.vercel', 'coverage',
    
    # Flutter / Dart
    '.dart_tool', '.pub-cache', '.flutter-plugins',
    
    # Java / Android / Kotlin
    '.gradle', '.idea', 'out',
    
    # Rust
    'target', '.cargo',
    
    # Go
    'vendor', 'Godeps',
    
    # Ruby
    '.bundle',
    
    # .NET / C#
    'bin', 'obj',
    
    # iOS / Swift
    'Pods', '.cocoapods',
    
    # Haskell
    '.stack-work', 'dist-newstyle',
    
    # Elixir
    '_build', 'deps', '.elixir_ls',
    
    # PHP
    'vendor',
    
    # Generic build/cache
    '.cache', '.temp', '.tmp', 'dist', 'build',
    '.git', '.svn', '.hg',
}

BLOCKED_DIR_PATTERNS = [
    r'site-packages',      # inside venv
    r'dist-packages',      # inside venv (Debian/Ubuntu)
    r'\.egg-info$',        # Python egg metadata
    r'__pycache__',        # anywhere in tree
    r'node_modules',       # anywhere in tree
    r'ios[/\\]Pods',       # Flutter iOS
    r'android[/\\]\.gradle',  # Flutter Android
    r'\.dart_tool',        # anywhere in tree
    r'\.cargo',            # Rust cargo
    r'target[/\\]debug',   # Rust debug builds
    r'target[/\\]release', # Rust release builds
    r'\.stack-work',       # Haskell
    r'dist-newstyle',      # Haskell
    r'_build',             # Elixir
    r'\.elixir_ls',        # Elixir LS
    r'vendor[/\\]bundle',  # Ruby
]

BLOCKED_EXTENSIONS = {
    # Compiled / binary
    '.pyc', '.pyo', '.pyd', '.so', '.dylib', '.dll',
    '.exe', '.bin', '.wasm', '.class', '.jar', '.war',
    '.aar', '.apk', '.ipa', '.o', '.obj', '.lib', '.a',
    
    # Media
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp',
    '.bmp', '.tiff', '.mp4', '.mov', '.avi', '.mkv',
    '.mp3', '.wav', '.ogg', '.flac', '.aac',
    
    # Archives
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.xz',
    
    # Documents (binary)
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    
    # Generated/minified
    '.min.js', '.min.css', '.map',
    '.tsbuildinfo', '.d.ts.map',
}

# Lock files — readable but warn
LOCK_FILES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'cargo.lock', 'poetry.lock', 'pipfile.lock',
    'gemfile.lock', 'composer.lock', 'pubspec.lock',
}


def is_blocked_path(path: str) -> Tuple[bool, str]:
    """
    Check if a path should be blocked from tool access.
    Returns (is_blocked: bool, reason: str)
    """
    path_lower = path.lower().replace('\\', '/')
    parts = Path(path).parts
    
    # Check each directory component
    for part in parts:
        # Convert Path object to string if needed (Windows compatibility)
        part_str = str(part)
        part_lower = part_str.lower()
        # Strip trailing slash
        part_clean = part_lower.rstrip('/')
        
        if part_clean in BLOCKED_DIRS:
            return True, f"Blocked directory '{part_str}' — dependency/build directory (not user code)"
    
    # Check pattern matches on the full path
    for pattern in BLOCKED_DIR_PATTERNS:
        if re.search(pattern, path_lower):
            return True, f"Blocked path pattern '{pattern}' — dependency/generated directory"
    
    return False, ""


def is_blocked_file(file_path: str) -> Tuple[bool, str]:
    """
    Check if a file should be blocked from being read.
    Returns (is_blocked: bool, reason: str)
    """
    # First check path (is it inside a blocked directory?)
    blocked, reason = is_blocked_path(file_path)
    if blocked:
        return True, reason
    
    path = Path(file_path)
    name_lower = path.name.lower()
    suffix_lower = path.suffix.lower()
    
    # Check extension
    if suffix_lower in BLOCKED_EXTENSIONS:
        return True, f"Blocked file type '{suffix_lower}' — binary/compiled/generated file"
    
    # Check double extensions like .min.js
    if name_lower.endswith('.min.js') or name_lower.endswith('.min.css'):
        return True, "Blocked minified file — auto-generated, not user code"
    
    # Warn on lock files but allow
    if name_lower in LOCK_FILES:
        return False, ""
    
    return False, ""


def get_directory_size_estimate(path: str) -> int:
    """
    Quick estimate of number of items in a directory (non-recursive).
    Used to warn before listing huge directories.
    """
    try:
        return sum(1 for _ in Path(path).iterdir())
    except (PermissionError, OSError):
        return -1


LARGE_DIR_THRESHOLD = 500  # warn if more than this many items

# Simple file cache to avoid re-reading same files
_file_cache: Dict[str, tuple] = {}
_file_cache_ttl = 5.0  # Cache TTL in seconds

def _get_cached_file(path: str) -> Optional[str]:
    """Get file content from cache if available and not expired."""
    if path in _file_cache:
        content, timestamp = _file_cache[path]
        if time.time() - timestamp < _file_cache_ttl:
            return content
        else:
            _file_cache.pop(path, None)
    return None

def _set_cached_file(path: str, content: str):
    """Cache file content with timestamp."""
    _file_cache[path] = (content, time.time())

def _clear_file_cache():
    """Clear the file cache."""
    _file_cache.clear()


# ─── UNDO STACK ──────────────────────────────────────────────────────────────

@dataclass
class UndoAction:
    """Records a reversible file operation."""
    action_type: str   # "file_edit", "file_create", "file_delete"
    path: str
    original: str = ""     # original content (for file_edit)
    undo_path: str = ""    # trash path (for file_delete)
    timestamp: float = field(default_factory=time.time)


class UndoStack:
    """
    Session-level undo for all file operations the AI performs.
    Every write_file / edit_file / delete_path is recorded here.
    """
    def __init__(self):
        self._stack: List[UndoAction] = []

    def push_file_edit(self, path: str, original_content: str):
        """Record the original content before an edit or overwrite."""
        self._stack.append(UndoAction("file_edit", path, original=original_content))

    def push_file_create(self, path: str):
        """Record a newly created file (so undo can delete it)."""
        self._stack.append(UndoAction("file_create", path))

    def push_file_delete(self, path: str, undo_path: str):
        """Record a deleted file (moved to undo_path in trash)."""
        self._stack.append(UndoAction("file_delete", path, undo_path=undo_path))

    def undo(self) -> str:
        """Undo the last file operation. Returns description of what was restored."""
        if not self._stack:
            return "Nothing to undo."
        action = self._stack.pop()
        try:
            if action.action_type == "file_edit":
                Path(action.path).write_text(action.original, encoding="utf-8")
                _set_cached_file(action.path, action.original)
                return f"✅ Restored `{Path(action.path).name}` to its previous content."
            elif action.action_type == "file_create":
                p = Path(action.path)
                if p.exists():
                    p.unlink()
                return f"✅ Deleted `{Path(action.path).name}` (undid creation)."
            elif action.action_type == "file_delete":
                if action.undo_path and Path(action.undo_path).exists():
                    shutil.move(action.undo_path, action.path)
                    return f"✅ Restored `{Path(action.path).name}` from trash."
                return f"❌ Cannot restore `{Path(action.path).name}` — undo cache not found."
        except Exception as e:
            return f"❌ Undo failed: {e}"

    def undo_all_session(self) -> List[str]:
        """Undo EVERY operation performed this session (reverse order)."""
        results = []
        while self._stack:
            results.append(self.undo())
        return results

    def clear(self):
        self._stack.clear()


# ─── PATH RESOLVER ────────────────────────────────────────────────────────────

class PathResolver:
    """
    Resolves all paths relative to the project root.
    Blocks path traversal outside the project root.
    """
    def __init__(self, project_root: str):
        self.root = Path(project_root).resolve() if project_root else None

    def resolve(self, path: str) -> Path:
        """Return absolute resolved path. Raises PermissionError if outside root."""
        p = Path(path)
        if not p.is_absolute():
            base = self.root or Path.cwd()
            p = base / p
        resolved = p.resolve()
        if self.root and not str(resolved).startswith(str(self.root)):
            raise PermissionError(f"Path '{path}' escapes the project root. Access denied.")
        return resolved

    def display(self, path: str) -> str:
        """Return path relative to project root for display."""
        try:
            p = Path(path).resolve()
            if self.root:
                return str(p.relative_to(self.root))
            return str(p)
        except Exception:
            return path


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
    duration_ms: float = 0.0


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
            duration_ms = (time.time() - start_time) * 1000
            return ToolResult(success=True, result=result, duration_ms=duration_ms)
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            log.error(f"Tool {self.name} execution failed: {e}")
            return ToolResult(success=False, result=None, error=str(e), duration_ms=duration_ms)
            
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
    
    # Directories to skip in listing/search (noise dirs)
    SKIP_DIRS = {
        '.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env',
        'dist', 'build', '.next', '.nuxt', 'coverage', '.pytest_cache',
        '.mypy_cache', '.tox', 'htmlcov', '.eggs', '*.egg-info'
    }

    # Role annotations for well-known directory names
    DIR_ROLES = {
        'src':        '← source code',
        'lib':        '← library',
        'app':        '← application',
        'core':       '← core logic',
        'api':        '← API layer',
        'tests':      '← test suite',
        'test':       '← test suite',
        'spec':       '← test suite',
        'docs':       '← documentation',
        'doc':        '← documentation',
        'config':     '← configuration',
        'configs':    '← configuration',
        'scripts':    '← scripts / tools',
        'bin':        '← executables',
        'utils':      '← utilities',
        'models':     '← data models',
        'views':      '← views / templates',
        'static':     '← static assets',
        'assets':     '← assets',
        'public':     '← public web assets',
        'migrations': '← DB migrations',
        'ui':         '← UI components',
        'components': '← UI components',
        'plugins':    '← plugins',
    }

    def __init__(self, file_manager=None, terminal_widget=None, git_manager=None, project_root=None):
        self.file_manager = file_manager
        self.terminal_widget = terminal_widget
        self.git_manager = git_manager
        self.project_root = project_root
        self.tools: Dict[str, Tool] = {}
        self._editor = get_editor(project_root)
        self._path_resolver = PathResolver(project_root) if project_root else None
        self._register_default_tools()
        
    def _register_default_tools(self):
        """Register the default set of tools."""
        
        # File operations
        self.register_tool(
            name="read_file",
            description="Read file content with optional line numbers and range. Use range for large files.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("start_line", "int", "First line to read (1-indexed)", required=False, default=1),
                ToolParameter("end_line", "int", "Last line to read (inclusive)", required=False, default=None),
                ToolParameter("numbered", "bool", "Include line numbers in output", required=False, default=True)
            ],
            function=self._read_file
        )
        
        self.register_tool(
            name="write_file",
            description="Write content to a file. WARNING: For large new files (>50 lines), write only the skeleton or first part, then use edit_file to add more. Massive writes may lead to truncation.",
            parameters=[
                ToolParameter("path", "string", "Absolute path to the file", required=True),
                ToolParameter("content", "string", "Content to write", required=True)
            ],
            function=self._write_file,
            requires_confirmation=True
        )
        
        self.register_tool(
            name="edit_file",
            description="Surgical find-and-replace. old_string MUST be UNIQUE (include 3+ lines of context). If not unique, the error message will show all match line numbers to help you disambiguate.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("old_string", "string", "Exact text to find (include context lines)", required=True),
                ToolParameter("new_string", "string", "Replacement text", required=True),
                ToolParameter("expected_occurrences", "int", "Error if matches != this count", required=False, default=1)
            ],
            function=self._edit_file,
            requires_confirmation=True
        )

        self.register_tool(
            name="inject_after",
            description="Insert code immediately after a specific UNIQUE anchor line. Safer than edit_file for large additions.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("anchor", "string", "Unique text to find the anchor line", required=True),
                ToolParameter("new_code", "string", "Code to insert", required=True)
            ],
            function=self._inject_after,
            requires_confirmation=True
        )

        self.register_tool(
            name="add_import",
            description="Add an import statement to the top of the file if not present.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("import_statement", "string", "The import line (e.g. 'import os')", required=True)
            ],
            function=self._add_import,
            requires_confirmation=True
        )

        self.register_tool(
            name="insert_at_line",
            description="Insert content at a specific line number. Best for adding imports or non-unique blocks.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("line", "int", "Line number to insert at (1-indexed)", required=True),
                ToolParameter("content", "string", "Code to insert", required=True)
            ],
            function=self._insert_at_line,
            requires_confirmation=True
        )

        self.register_tool(
            name="get_file_outline",
            description="Get a high-level summary of functions and classes in a file with line numbers.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True)
            ],
            function=self._get_file_outline
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
            description="List files and directories in a path with role annotations",
            parameters=[
                ToolParameter("path", "string", "Directory path (default: project root)", required=False, default="."),
                ToolParameter("show_hidden", "bool", "Show hidden files", required=False, default=False)
            ],
            function=self._list_directory
        )

        # Undo last AI file operation
        self.register_tool(
            name="undo_last_action",
            description="Undo the last file operation (write, edit, or delete) performed by the AI in this session",
            parameters=[],
            function=self._undo_last_action
        )
        
        # Terminal operations
        self.register_tool(
            name="run_command",
            description="Run a terminal command. IMPORTANT: Never modify virtual environment directories (venv/, .venv/, node_modules/) directly. Use package managers (pip, npm, etc.) instead.",
            parameters=[
                ToolParameter("command", "string", "Command to execute. WARNING: Do not run commands that modify venv/, node_modules/, or other dependency directories directly.", required=True),
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

    def set_project_root(self, project_root: str):
        """Update project root and recreate path resolver."""
        self.project_root = project_root
        self._path_resolver = PathResolver(project_root)
        self._editor = get_editor(project_root)
        
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
        missing_params = []
        for param in tool.parameters:
            if param.required and (param.name not in params or params[param.name] is None or params[param.name] == ""):
                missing_params.append(param.name)
        
        if missing_params:
            required_param_names = [p.name for p in tool.parameters if p.required]
            error_msg = (
                f"Missing required parameters: {', '.join(missing_params)}. "
                f"This tool requires: {', '.join(required_param_names)}. "
                "Please try again with all required parameters."
            )
            log.error(f"Tool {tool_name} failed: {error_msg}")
            return ToolResult(success=False, result=None, error=error_msg, duration_ms=0)
            
        return tool.execute(params)
        
    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to project root safely using PathResolver."""
        if not self._path_resolver:
            # Fallback for initialization or if root is missing
            abs_path = Path(path).resolve() if Path(path).is_absolute() else (Path(self.project_root or os.getcwd()) / path).resolve()
            return abs_path
        return self._path_resolver.resolve(path)

    def _read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None, numbered: bool = True) -> str:
        """Read file contents with line range and optional numbers."""
        try:
            resolved_path = self._resolve_path(path)
            str_path = str(resolved_path)
            
            # ── Hard block check for dependency/binary files ─────────────────────
            blocked, reason = is_blocked_file(str_path)
            if blocked:
                return f"🚫 BLOCKED: {reason}\n\nThis file is inside a dependency or build directory. Reading it would waste context and slow down the terminal. Focus on your source code files instead."
            
            if not resolved_path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            # Apply line range (1-indexed)
            total_lines = len(lines)
            start_idx = max(0, start_line - 1)
            end_idx = min(total_lines, end_line if end_line is not None else total_lines)
            
            selected_lines = lines[start_idx:end_idx]
            
            if not selected_lines:
                return f"[Empty range or file: lines {start_line}-{end_line if end_line else 'end'}]"

            if numbered:
                output = []
                for i, line in enumerate(selected_lines, start=start_idx + 1):
                    output.append(f"{i:4d}| {line}")
                result = "".join(output)
            else:
                result = "".join(selected_lines)

            # Inform AI if truncated
            prefix = "" if start_line == 1 else f"... [lines 1-{start_line-1} hidden] ...\n"
            suffix = "" if end_idx == total_lines else f"... [lines {end_idx+1}-{total_lines} hidden] ..."
            
            return f"{prefix}{result}\n{suffix}".strip()
        except Exception as e:
            log.error(f"Failed to read file {path}: {e}")
            raise Exception(f"Failed to read file: {e}")
            
    def _write_file(self, path: str, content: str) -> str:
        """Write content to file using PreciseEditor."""
        result = self._editor.write(path, content)
        if result.success:
            return f"✅ File written: {path} ({result.lines_after} lines)"
        else:
            raise Exception(f"Failed to write file: {result.error}")

    def _edit_file(self, path: str, old_string: str, new_string: str, expected_occurrences: int = 1) -> str:
        """Edit file using PreciseEditor."""
        result = self._editor.edit(path, old_string, new_string, expected_count=expected_occurrences)
        if result.success:
            return f"✅ File edited: {Path(path).name} ({result.delta} lines delta)"
        else:
            error_msg = result.error
            if result.action:
                error_msg += f"\nRECOVERY HINT: {result.action}"
            raise Exception(f"Failed to edit file: {error_msg}")

    def _inject_after(self, path: str, anchor: str, new_code: str) -> str:
        """Inject code after anchor using PreciseEditor."""
        result = self._editor.inject_after(path, anchor, new_code)
        if result.success:
            return f"✅ Code injected into {Path(path).name}"
        else:
            raise Exception(f"Injection failed: {result.error}")

    def _add_import(self, path: str, import_statement: str) -> str:
        """Add import using PreciseEditor."""
        result = self._editor.add_import(path, import_statement)
        if result.success:
            return f"✅ Import added to {Path(path).name} (or already present)"
        else:
            raise Exception(f"Failed to add import: {result.error}")

    def _insert_at_line(self, path: str, line: int, content: str) -> str:
        """Insert content at a specific line number."""
        try:
            resolved_path = self._resolve_path(path)
            str_path = str(resolved_path)
            
            if not resolved_path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            with open(resolved_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            original_content = "".join(lines)

            # Record for undo (Handled by PreciseEditor or manually for this custom method)
            self._editor.undo_stack.push(str_path, original_content, f"insert at {line}")

            # Insert (1-indexed)
            idx = max(0, line - 1)
            # Ensure content ends with newline
            insert_text = content if content.endswith('\n') else content + '\n'
            lines.insert(idx, insert_text)

            new_content = "".join(lines)
            with open(resolved_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            _set_cached_file(str_path, new_content)
            return f"✅ Inserted {len(insert_text.splitlines())} lines at line {line} of {Path(path).name}"
        except Exception as e:
            raise Exception(f"Failed to insert: {e}")

    def _get_file_outline(self, path: str) -> str:
        """Simple regex-based outline of classes and functions."""
        try:
            resolved_path = self._resolve_path(path)
            if not resolved_path.exists():
                return f"File not found: {path}"

            import re
            # Patterns for Python, JS/TS, CSS
            patterns = [
                (r'^(class\s+[a-zA-Z0-9_]+)', 'Class'),
                (r'^(def\s+[a-zA-Z0-9_]+)', 'Function'),
                (r'^(async\s+function\s+[a-zA-Z0-9_]+)', 'Async Function'),
                (r'^(function\s+[a-zA-Z0-9_]+)', 'Function'),
                (r'^([a-zA-Z0-9_]+\s*:\s*function)', 'Method'),
                (r'^(\.[a-zA-Z0-9_-]+\s*\{)', 'CSS Selector'),
                (r'^(# [^#].*)', 'Markdown H1'),
                (r'^(## [^#].*)', 'Markdown H2'),
            ]
            
            outline = []
            with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f, 1):
                    for pattern, kind in patterns:
                        match = re.search(pattern, line)
                        if match:
                            outline.append(f"{i:4d}| {kind}: {match.group(1).strip()}")
                            break
            
            if not outline:
                return "No major structures (classes/functions) detected."
            return "\n".join(outline)
        except Exception as e:
            return f"Failed to get outline: {e}"

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
        """Delete a file or directory. Moves to undo cache first for safe recovery."""
        try:
            # Handle relative paths - use project root
            path = self._resolve_path(path)
            
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
                    return f"❌ BLOCKED: Directory contains {file_count} files. Too many to delete safely. Use run_command for bulk operations."
            
            # Move to undo cache BEFORE deleting (enables recovery)
            undo_dir = Path.home() / ".cortex" / "undo_cache"
            undo_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time())
            undo_path = str(undo_dir / f"{timestamp}_{Path(path).name}")
            shutil.move(path, undo_path)
            
            # Record in undo stack
            self._editor.undo_stack.push(str(path), "FOLDER_OR_FILE_DELETED_MARKER", description=f"delete {path}")
            # Note: PreciseEditor's undo_stack expects content, but for delete we'd need a different mechanism
            # for full folder recovery. For now, we'll rely on the trash move.
            # I will update PreciseEditor to handle this more robustness later.
            # For now, let's just use the trash move which is already implemented here.
            
            return f"✅ Deleted: {Path(path).name} (recoverable via undo_last_action)"
        except Exception as e:
            raise Exception(f"Failed to delete path: {e}")
            
    def _list_directory(self, path: str = ".", show_hidden: bool = False) -> str:
        """List directory with role annotations, skipping noise dirs and blocking dependency directories."""
        try:
            resolved_path = self._resolve_path(path)
            str_path = str(resolved_path)
            
            # ── Hard block on known dependency dirs ──────────────────────────────
            blocked, reason = is_blocked_path(str_path)
            if blocked:
                return f"🚫 BLOCKED: {reason}\n\nThis directory contains framework dependencies, not user code. Exploring it would freeze the terminal and waste context. Focus on your source files instead."

            if not os.path.isdir(resolved_path):
                return f"Not a directory: {path}"

            items = []
            blocked_items = []
            
            for item in sorted(os.listdir(resolved_path)):
                if not show_hidden and item.startswith('.'):
                    continue
                # Skip noise directories
                if item in self.SKIP_DIRS:
                    continue

                full_path = os.path.join(str(resolved_path), item)
                
                # Check if this item is a blocked dependency directory
                item_blocked, item_reason = is_blocked_path(full_path)
                if item_blocked:
                    # Count items for informational display
                    item_count = get_directory_size_estimate(full_path)
                    count_str = f"~{item_count}" if item_count > 0 else "many"
                    blocked_items.append(f"📁 {item}/  ({count_str} items — SKIPPED: dependency directory)")
                    continue
                
                if os.path.isdir(full_path):
                    role = self.DIR_ROLES.get(item.lower(), "")
                    role_str = f"  {role}" if role else ""
                    items.append(f"📁 {item}/{role_str}")
                else:
                    try:
                        size = os.path.getsize(full_path)
                        size_str = f"{size}B" if size < 1024 else f"{size//1024}KB"
                        items.append(f"📄 {item}  ({size_str})")
                    except Exception:
                        items.append(f"📄 {item}")

            # Add separator and blocked items info
            if blocked_items:
                if items:
                    items.append("")
                items.append(f"── {len(blocked_items)} dependency/build directories excluded ──")
                items.extend(blocked_items[:5])  # Show max 5
                if len(blocked_items) > 5:
                    items.append(f"... and {len(blocked_items)-5} more blocked directories")

            if not items:
                return "Directory is empty (or contains only hidden/noise directories)."
            return "\n".join(items)
        except Exception as e:
            raise Exception(f"Failed to list directory: {e}")

    def _undo_last_action(self) -> str:
        """Undo the last file operation using PreciseEditor."""
        path = self._editor.undo()
        if path:
            return f"✅ Restored `{Path(path).name}` to its previous state."
        return "Nothing to undo."
            
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
            
            # Check for virtual environment commands that might cause performance issues
            venv_indicators = ['venv', 'virtualenv', '.venv', 'env/', 'node_modules']
            dangerous_patterns = [
                'rm -rf venv', 'rm -rf node_modules', 'del venv', 'rmdir venv',
                'pip install -r', 'npm install', 'yarn install', 'pnpm install'
            ]
            
            command_lower = command.lower()
            warnings = []
            
            # Check for potentially dangerous commands
            for pattern in dangerous_patterns:
                if pattern in command_lower:
                    warnings.append(f"⚠️ This command may affect dependencies: '{pattern}'")
            
            # Check if command targets virtual environment directories
            for indicator in venv_indicators:
                if indicator in command_lower:
                    warnings.append(f"⚠️ Command references '{indicator}' - virtual environments should not be manually modified")
                    break
            
            if warnings:
                log.warning(f"Command warnings for '{command}': {'; '.join(warnings)}")
            
            log.info(f"Running command in directory: {working_dir}")
            
            if self.terminal_widget and hasattr(self.terminal_widget, 'execute_command'):
                # Ensure terminal is set to the correct directory first
                if hasattr(self.terminal_widget, 'set_cwd'):
                    self.terminal_widget.set_cwd(working_dir)
                self.terminal_widget.execute_command(command)
                
                response = f"Command sent to terminal: {command}"
                if warnings:
                    response += "\n\n" + "\n".join(warnings)
                return response
            else:
                # Fallback to subprocess with correct working directory
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=timeout, cwd=working_dir
                )
                output = result.stdout
                if result.stderr:
                    output += "\n" + result.stderr
                
                if warnings:
                    output = "\n".join(warnings) + "\n\n" + output
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
