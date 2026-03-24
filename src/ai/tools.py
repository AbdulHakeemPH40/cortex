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
        if self.root:
            root_str = str(self.root)
            try:
                common = os.path.commonpath([
                    os.path.normcase(str(resolved)),
                    os.path.normcase(root_str)
                ])
            except ValueError:
                common = ""
            if common != os.path.normcase(root_str):
                # Log the attempted escape so we can diagnose wrong-directory calls
                log.warning(
                    f"PathResolver BLOCKED: '{path}' resolved to '{resolved}' "
                    f"which is outside project root '{self.root}'. "
                    f"AI should use paths relative to project root only."
                )
                raise PermissionError(
                    f"Path '{path}' escapes the project root '{self.root}'. "
                    f"Use a path relative to the project root, e.g. 'src/main.py'."
                )
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
        self._recent_tool_calls: List[Dict] = []  # Track recent calls to prevent loops
        self._max_recent_calls = 10
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
            description="Get a high-level summary of functions and classes in a file with line numbers. Use BEFORE editing files >100 lines.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True)
            ],
            function=self._get_file_outline
        )
        
        # Surgical editing tools
        self.register_tool(
            name="delete_lines",
            description="Delete lines from start_line to end_line (inclusive). Use for removing code blocks precisely. Line numbers are 1-indexed.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("start_line", "int", "First line to delete (1-indexed)", required=True),
                ToolParameter("end_line", "int", "Last line to delete (1-indexed)", required=True)
            ],
            function=self._delete_lines,
            requires_confirmation=True
        )
        
        self.register_tool(
            name="replace_lines",
            description="Replace lines from start_line to end_line with new code. Use for replacing entire functions or code blocks. Line numbers are 1-indexed.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("start_line", "int", "First line to replace (1-indexed)", required=True),
                ToolParameter("end_line", "int", "Last line to replace (1-indexed)", required=True),
                ToolParameter("new_code", "string", "New code to insert", required=True)
            ],
            function=self._replace_lines,
            requires_confirmation=True
        )
        
        self.register_tool(
            name="find_usages",
            description="Find all usages of a symbol (function, class, variable) across the codebase. Use to understand impact of changes before editing.",
            parameters=[
                ToolParameter("symbol", "string", "Symbol name to search for (e.g., function name, class name)", required=True),
                ToolParameter("file_pattern", "string", "File pattern to search (e.g., '*.py', '*.js')", required=False, default="*")
            ],
            function=self._find_usages
        )
        
        self.register_tool(
            name="analyze_file",
            description="Deep analysis of a file including dependencies, structure, and complexity. Use BEFORE making large changes to understand the file.",
            parameters=[
                ToolParameter("path", "string", "Path to the file", required=True),
                ToolParameter("analysis_type", "string", "Type of analysis: 'full', 'dependencies', 'structure', 'complexity'", required=False, default="full")
            ],
            function=self._analyze_file
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
            description="Search for text in the codebase using regex",
            parameters=[
                ToolParameter("query", "string", "Text/regex to search for", required=True),
                ToolParameter("file_pattern", "string", "File pattern to search in (e.g., *.py)", required=False, default="*")
            ],
            function=self._search_code
        )
        
        self.register_tool(
            name="search_codebase",
            description="Semantic code search - find code by meaning/intent, not just text. Use when you don't know exact function names or want to understand how something works.",
            parameters=[
                ToolParameter("query", "string", "What you're looking for (e.g., 'authentication logic', 'how payments work', 'database connection')", required=True),
                ToolParameter("target_directories", "array", "Specific directories to search (optional)", required=False, default=None)
            ],
            function=self._search_codebase
        )
        
        self.register_tool(
            name="semantic_search",
            description="Deep semantic code search using embeddings. Finds code by meaning, not keywords. Best for finding similar implementations or understanding code concepts.",
            parameters=[
                ToolParameter("query", "string", "Natural language query describing what you're looking for", required=True),
                ToolParameter("limit", "int", "Maximum number of results", required=False, default=10),
                ToolParameter("chunk_types", "array", "Filter by chunk types: 'function', 'class', 'method', 'import'", required=False, default=None)
            ],
            function=self._semantic_search
        )
        
        self.register_tool(
            name="find_function",
            description="Find function definitions by name pattern. Returns function signatures, locations, and code snippets.",
            parameters=[
                ToolParameter("name", "string", "Function name or pattern to search for", required=True),
                ToolParameter("file_pattern", "string", "File pattern to search in (e.g., '*.py')", required=False, default=None)
            ],
            function=self._find_function
        )
        
        self.register_tool(
            name="find_class",
            description="Find class definitions by name pattern. Returns class signatures, locations, and code snippets.",
            parameters=[
                ToolParameter("name", "string", "Class name or pattern to search for", required=True),
                ToolParameter("file_pattern", "string", "File pattern to search in (e.g., '*.py')", required=False, default=None)
            ],
            function=self._find_class
        )
        
        self.register_tool(
            name="find_symbol",
            description="Find any type of symbol by name pattern. Supports: function, class, method, variable, import, module. Returns symbol signatures, locations, and code snippets.",
            parameters=[
                ToolParameter("name", "string", "Symbol name or pattern to search for", required=True),
                ToolParameter("symbol_type", "string", "Optional symbol type to filter by: function, class, method, variable, import, module", required=False, default=None),
                ToolParameter("file_pattern", "string", "File pattern to search in (e.g., '*.py')", required=False, default=None)
            ],
            function=self._find_symbol
        )
        
        self.register_tool(
            name="debug_error",
            description="Analyze an error message and get fix suggestions. Works for any framework (Django, Flask, React, etc.). Extracts error context, detects framework, and provides actionable fix hints.",
            parameters=[
                ToolParameter("error_text", "string", "Full error message or traceback to analyze", required=True),
                ToolParameter("file_path", "string", "Optional file path where error occurred", required=False, default=None),
                ToolParameter("line_number", "int", "Optional line number where error occurred", required=False, default=None)
            ],
            function=self._debug_error
        )
        
        self.register_tool(
            name="check_syntax",
            description="Check syntax of a file for errors. Supports Python, JavaScript, TypeScript, Go, Rust, Java, C/C++, Ruby, PHP, and more.",
            parameters=[
                ToolParameter("file_path", "string", "Path to the file to check", required=True)
            ],
            function=self._check_syntax
        )
        
        # Code quality operations
        self.register_tool(
            name="get_problems",
            description="Check for compile errors, lint issues, and syntax problems in code files. Use after making edits to verify correctness.",
            parameters=[
                ToolParameter("file_paths", "array", "List of file paths to check (optional - checks all modified files if empty)", required=False, default=[])
            ],
            function=self._get_problems
        )
        
        # LSP/Code Intelligence operations
        self.register_tool(
            name="lsp_find_references",
            description="Find all references to a symbol (function, class, variable) across the codebase using LSP",
            parameters=[
                ToolParameter("symbol", "string", "Symbol name to find references for", required=True),
                ToolParameter("file_path", "string", "File containing the symbol definition", required=True),
                ToolParameter("line", "integer", "Line number where symbol is defined (1-based)", required=True),
                ToolParameter("character", "integer", "Character position on the line (1-based)", required=True)
            ],
            function=self._lsp_find_references
        )
        
        self.register_tool(
            name="lsp_go_to_definition",
            description="Jump to the definition of a symbol using LSP code intelligence",
            parameters=[
                ToolParameter("symbol", "string", "Symbol to find definition for", required=True),
                ToolParameter("file_path", "string", "File containing the symbol usage", required=True),
                ToolParameter("line", "integer", "Line number where symbol is used (1-based)", required=True),
                ToolParameter("character", "integer", "Character position on the line (1-based)", required=True)
            ],
            function=self._lsp_go_to_definition
        )
        
        # Verification operations
        self.register_tool(
            name="verify_fix",
            description="Verify that a fix works by running tests or checking the specific scenario. Use after applying fixes.",
            parameters=[
                ToolParameter("test_command", "string", "Command to run to verify (e.g., 'python -m pytest test_file.py')", required=False, default=None),
                ToolParameter("check_scenario", "string", "Description of what to check for", required=False, default=None),
                ToolParameter("file_paths", "array", "Files to check for errors after fix", required=False, default=None)
            ],
            function=self._verify_fix
        )
        
        # Memory operations
        self.register_tool(
            name="search_memory",
            description="Search past memories/decisions for similar problems. Use before fixing to see if we've solved this before.",
            parameters=[
                ToolParameter("query", "string", "What to remember (e.g., 'terminal blank fix', 'git loop issue')", required=True),
                ToolParameter("category", "string", "Memory category to search (e.g., 'common_pitfalls', 'task_summary')", required=False, default=""),
                ToolParameter("depth", "string", "Search depth: 'shallow' for quick, 'deep' for thorough", required=False, default="shallow")
            ],
            function=self._search_memory
        )
        
        # Git operations
        self.register_tool(
            name="git_commit",
            description="Commit changes to git repository with a message",
            parameters=[
                ToolParameter("message", "string", "Commit message describing the changes", required=True),
                ToolParameter("files", "array", "Specific files to commit (optional - commits all staged if empty)", required=False, default=None),
                ToolParameter("stage_all", "bool", "Stage all modified files before commit", required=False, default=False)
            ],
            function=self._git_commit,
            requires_confirmation=True
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

        tools_requires_project = {
            "read_file",
            "write_file",
            "edit_file",
            "inject_after",
            "add_import",
            "insert_at_line",
            "get_file_outline",
            "delete_lines",
            "replace_lines",
            "find_usages",
            "analyze_file",
            "delete_path",
            "list_directory",
            "search_code",
            "search_codebase",
            "semantic_search",
            "find_function",
            "find_class",
            "debug_error",
            "check_syntax",
            "get_problems",
            "lsp_find_references",
            "lsp_go_to_definition",
            "run_command",
        }
        if tool_name in tools_requires_project and not (self.project_root and os.path.isdir(self.project_root)):
            error_msg = (
                "Project root is not set. Open a project folder before running "
                f"'{tool_name}'."
            )
            log.warning(f"Tool {tool_name} blocked: {error_msg}")
            return ToolResult(success=False, result=None, error=error_msg, duration_ms=0)
            
        # Check for duplicate tool calls (prevent infinite loops)
        call_signature = {"tool": tool_name, "params": params}
        recent_calls = self._recent_tool_calls[-3:]  # Check last 3 calls
        duplicate_count = sum(1 for call in recent_calls if call == call_signature)
            
        if duplicate_count >= 2:
            # Same tool with same params called 2+ times recently
            log.warning(f"Preventing duplicate tool call: {tool_name} with same params (called {duplicate_count} times)")
            return ToolResult(
                success=False, 
                result=None, 
                error=f"[LOOP PREVENTION] Tool '{tool_name}' was just called with the same parameters. The AI should not repeat the same tool call. Consider the task complete or try a different approach.",
                duration_ms=0
            )
            
        # Track this call
        self._recent_tool_calls.append(call_signature)
        if len(self._recent_tool_calls) > self._max_recent_calls:
            self._recent_tool_calls.pop(0)
            
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

    def _read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None, numbered: bool = True, 
                   use_cache: bool = True, async_load: bool = False, lazy_load: bool = None, 
                   fast_fail: bool = True) -> str:
        """
        ULTRA-FAST file reading with aggressive validation and fast-fail.
        
        PERFORMANCE FEATURES:
        - Path validation BEFORE attempting read (prevents wasted time)
        - Fast-fail on missing files (no cascading delays)
        - Auto-lazy loading for large files
        - Instant cache hits (<1ms)
        
        Args:
            path: File path
            start_line: Start line (1-indexed)
            end_line: End line (optional)
            numbered: Add line numbers
            use_cache: Use cached content
            async_load: Load in background
            lazy_load: Auto-detected (None = automatic)
            fast_fail: If True, fail immediately on missing file (default: True)
        """
        try:
            resolved_path = self._resolve_path(path)
            str_path = str(resolved_path)
            
            # ⚡ PERFORMANCE: Validate path EXISTS before any processing
            if not resolved_path.exists():
                if fast_fail:
                    # Fast fail - don't waste time on non-existent files
                    log.debug(f"⚡ FAST FAIL: File not found: {path}")
                    return f"❌ File not found: `{path}`\n\nThe file does not exist. Please verify the path or create it first."
                else:
                    raise FileNotFoundError(f"File not found: {path}")
            
            # ── Hard block check for dependency/binary files ─────────────────────
            blocked, reason = is_blocked_file(str_path)
            if blocked:
                return f"🚫 BLOCKED: {reason}\n\nThis file is inside a dependency or build directory. Reading it would waste context and slow down the terminal. Focus on your source code files instead."

            # 🎯 AUTO-LAZY LOADING: Automatically detect if file needs optimization
            if lazy_load is None:  # Auto-detect mode
                try:
                    # ⚡ PERFORMANCE FIX: Use file size estimation instead of reading entire file
                    # Original: file_lines = len(Path(str_path).read_text().splitlines()) - SLOW!
                    # New: Estimate lines from file size (avg 80 chars per line)
                    file_size = resolved_path.stat().st_size
                    estimated_lines = file_size // 80  # Conservative estimate
                    
                    # Enable lazy loading for files >100 lines
                    lazy_load = estimated_lines > 100
                    
                    if lazy_load:
                        log.info(f"🎯 Auto-enabled lazy loading for {path} (~{estimated_lines} lines, {file_size:,} bytes)")
                        
                        # If no end_line specified, default to 400 line viewport
                        if end_line is None:
                            end_line = start_line + 399  # Default viewport
                except:
                    # If can't determine size, enable lazy loading by default
                    lazy_load = True
            
            # LAZY LOADING MODE - Read only requested range
            if lazy_load and hasattr(self, '_file_manager') and self._file_manager:
                # Ensure end_line is set
                if end_line is None:
                    end_line = start_line + 399  # Default 400 line viewport
                
                log.debug(f"📖 Reading range: {path}[{start_line}-{end_line}]")
                
                # Use FileManager's optimized range reading
                content = self._file_manager.read_range(str_path, start_line, end_line, use_cache)
                
                if content is None:
                    content = ""
                
                # 🔮 AUTOMATIC PREFETCH: Always prefetch next chunks (no manual trigger needed)
                try:
                    next_start = end_line + 1
                    # Prefetch next 3 viewports in background (always enabled)
                    self._file_manager.prefetch_viewport(str_path, next_start, 400, lookahead_count=3)
                except:
                    pass  # Prefetch failure is OK, won't break main read
                
                # Format output
                lines = content.splitlines(keepends=True)
                
                if numbered:
                    output = []
                    for i, line in enumerate(lines, start=start_line):
                        output.append(f"{i:4d}| {line}")
                    result = "".join(output)
                else:
                    result = "".join(lines)
                
                return result.strip()
            
            # FALLBACK: Old behavior (read full file)
            if use_cache and hasattr(self, '_file_manager') and self._file_manager:
                cached_content = self._file_manager.get_cached_content(str_path)
                if cached_content:
                    log.debug(f"✅ CACHE HIT: {path}")
                    lines = cached_content.splitlines(keepends=True)
                else:
                    # ⚡ PERFORMANCE FIX: Use FileManager's async read instead of blocking open()
                    # This prevents UI blocking for large files
                    content = self._file_manager._read_file_sync(str_path)
                    if content is None:
                        # Fallback to blocking read only if async fails
                        with open(resolved_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                    lines = content.splitlines(keepends=True) if content else []
                    self._file_manager._file_cache.put(str_path, ''.join(lines))
            else:
                # ⚡ PERFORMANCE FIX: Use optimized file reading
                # For large files, use memory-mapped reading
                file_size = resolved_path.stat().st_size
                if file_size > 1024 * 1024:  # >1MB
                    import mmap
                    with open(resolved_path, 'r+b', buffering=0) as f:
                        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                            content = mm.read().decode('utf-8', errors='replace')
                else:
                    content = resolved_path.read_text(encoding='utf-8', errors='replace')
                lines = content.splitlines(keepends=True)

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
        """Write content to file using PreciseEditor with disk sync for reliability."""
        result = self._editor.write(path, content)
        if result.success:
            # DISK SYNC: Force OS to write to physical disk before continuing
            try:
                resolved_path = Path(result.path).resolve()
                if resolved_path.exists():
                    # Force flush internal buffers
                    with open(resolved_path, 'r+', encoding='utf-8') as f:
                        f.flush()
                        os.fsync(f.fileno())  # Force OS to commit to disk
                    log.debug(f"💾 Disk sync complete for: {path}")
            except Exception as e:
                log.warning(f"Disk sync failed (non-critical): {e}")
            
            # DISK SYNC: Give OS 200ms to index the change
            # Prevents "file not found" errors when AI immediately reads after write
            time.sleep(0.2)
            
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
                f.flush()
                os.fsync(f.fileno())  # Force disk sync for reliability
            
            # DISK SYNC: Give OS 200ms to index the change
            time.sleep(0.2)
            
            _set_cached_file(str_path, new_content)
            return f"✅ Inserted {len(insert_text.splitlines())} lines at line {line} of {Path(path).name}"
        except Exception as e:
            raise Exception(f"Failed to insert: {e}")

    def _get_file_outline(self, path: str, detailed: bool = False) -> str:
        """
        Enhanced file outline extraction with deep code structure analysis.
        Extracts imports, classes, functions, and their signatures.
        
        Args:
            path: File path to analyze
            detailed: If True, include method bodies preview
        """
        try:
            resolved_path = self._resolve_path(path)
            if not resolved_path.exists():
                return f"File not found: {path}"

            ext = Path(resolved_path).suffix.lower()
            content = Path(resolved_path).read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')
            total_lines = len(lines)
            
            sections = []
            sections.append(f"📁 {Path(path).name} ({total_lines} lines)")
            sections.append("=" * 50)
            
            # 1. Extract IMPORTS
            imports = []
            import_patterns = [
                (r'^import\s+([a-zA-Z0-9_\.]+)', 'import'),
                (r'^from\s+([a-zA-Z0-9_\.]+)\s+import', 'from'),
                (r'^#include\s*[<"]([^>"]+)[>"]', 'c_include'),
                (r'^require\([\'"]([^\'"]+)[\'"]\)', 'js_require'),
                (r'^import\s+[\'"]([^\'"]+)[\'"]', 'es_import'),
            ]
            
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                for pattern, kind in import_patterns:
                    match = re.match(pattern, stripped)
                    if match:
                        module = match.group(1)
                        imports.append(f"   L{i:4d}: {kind} {module}")
                        break
            
            if imports:
                sections.append("\n📦 IMPORTS:")
                sections.extend(imports[:30])  # Limit to first 30 imports
                if len(imports) > 30:
                    sections.append(f"   ... and {len(imports) - 30} more imports")
            
            # 2. Extract CODE STRUCTURE (Language-specific)
            if ext in ('.py',):
                structure = self._extract_python_structure(lines, detailed)
            elif ext in ('.js', '.ts', '.jsx', '.tsx'):
                structure = self._extract_js_structure(lines, detailed)
            elif ext in ('.java', '.kt'):
                structure = self._extract_java_structure(lines, detailed)
            elif ext in ('.go',):
                structure = self._extract_go_structure(lines, detailed)
            elif ext in ('.rs',):
                structure = self._extract_rust_structure(lines, detailed)
            elif ext in ('.c', '.cpp', '.h', '.hpp'):
                structure = self._extract_c_structure(lines, detailed)
            else:
                structure = self._extract_generic_structure(lines)
            
            sections.extend(structure)
            
            # 3. Dependencies summary
            if imports:
                sections.append("\n📊 SUMMARY:")
                sections.append(f"   Imports: {len(imports)} modules")
                sections.append(f"   Classes: {len([s for s in structure if 'CLASS' in s])}")
                sections.append(f"   Functions: {len([s for s in structure if 'DEF' in s or 'FUNC' in s])}")
            
            return "\n".join(sections)
            
        except Exception as e:
            return f"Failed to get outline: {e}"
    
    def _extract_python_structure(self, lines: list, detailed: bool = False) -> list:
        """Extract Python classes, functions, and methods with signatures."""
        structure = []
        current_class = None
        current_class_indent = 0
        current_function = None
        current_function_indent = 0
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            
            # Skip comments and empty lines
            if stripped.startswith('#') or not stripped:
                continue
            
            # Class definition
            class_match = re.match(r'^class\s+([A-Za-z0-9_]+)(?:\s*\(([^)]*)\))?:', stripped)
            if class_match:
                class_name = class_match.group(1)
                bases = class_match.group(2) or ""
                bases_str = f"({bases})" if bases else ""
                structure.append(f"\n🏛️  CLASS: {class_name}{bases_str} (line {i})")
                current_class = class_name
                current_class_indent = indent
                continue
            
            # Function/method definition
            func_match = re.match(r'^(async\s+)?def\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', stripped)
            if func_match:
                is_async = func_match.group(1) is not None
                func_name = func_match.group(2)
                params = func_match.group(3)
                
                # Determine if method or function
                if current_class and indent > current_class_indent:
                    prefix = "   📎method" if indent <= current_class_indent + 4 else "   📎method"
                else:
                    prefix = "⚡ func"
                    current_class = None
                    current_class_indent = 0
                
                async_str = "async " if is_async else ""
                structure.append(f"{prefix}: {async_str}{func_name}({params}) → line {i}")
                current_function = func_name
                current_function_indent = indent
                continue
            
            # Detect class end (indent returns to class level or less)
            if current_class and indent <= current_class_indent and not stripped.startswith('@'):
                current_class = None
        
        return structure
    
    def _extract_js_structure(self, lines: list, detailed: bool = False) -> list:
        """Extract JS/TS classes, functions, and exports."""
        structure = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip comments
            if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
                continue
            
            # Class definition
            class_match = re.match(r'^(export\s+)?(default\s+)?class\s+([A-Za-z0-9_]+)', stripped)
            if class_match:
                is_export = class_match.group(1) is not None
                class_name = class_match.group(3)
                export_str = "export " if is_export else ""
                structure.append(f"\n🏛️  {export_str}CLASS: {class_name} (line {i})")
                continue
            
            # Function declarations
            func_match = re.match(r'^(export\s+)?(async\s+)?function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', stripped)
            if func_match:
                is_export = func_match.group(1) is not None
                is_async = func_match.group(2) is not None
                func_name = func_match.group(3)
                params = func_match.group(4)
                export_str = "export " if is_export else ""
                async_str = "async " if is_async else ""
                structure.append(f"⚡ {export_str}{async_str}func {func_name}({params}) → line {i}")
                continue
            
            # Arrow functions and const declarations
            arrow_match = re.match(r'^(export\s+)?(const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(async\s+)?\([^)]*\)\s*=>', stripped)
            if arrow_match:
                is_export = arrow_match.group(1) is not None
                kind = arrow_match.group(2)
                name = arrow_match.group(3)
                is_async = arrow_match.group(4) is not None
                export_str = "export " if is_export else ""
                async_str = "async " if is_async else ""
                structure.append(f"⚡ {export_str}{async_str}{kind} {name} = () =>  → line {i}")
                continue
            
            # Interface (TypeScript)
            interface_match = re.match(r'^(export\s+)?interface\s+([A-Za-z0-9_]+)', stripped)
            if interface_match:
                is_export = interface_match.group(1) is not None
                name = interface_match.group(2)
                export_str = "export " if is_export else ""
                structure.append(f"📋 {export_str}interface {name} → line {i}")
                continue
            
            # Type (TypeScript)
            type_match = re.match(r'^(export\s+)?type\s+([A-Za-z0-9_]+)', stripped)
            if type_match:
                is_export = type_match.group(1) is not None
                name = type_match.group(2)
                export_str = "export " if is_export else ""
                structure.append(f"📋 {export_str}type {name} → line {i}")
                continue
        
        return structure
    
    def _extract_java_structure(self, lines: list, detailed: bool = False) -> list:
        """Extract Java/Kotlin classes and methods."""
        structure = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if stripped.startswith('//') or stripped.startswith('/*'):
                continue
            
            # Class definition
            class_match = re.match(r'^(public|private|protected)?\s*(abstract|final|class|interface|enum)\s+([A-Za-z0-9_]+)', stripped)
            if class_match:
                visibility = class_match.group(1) or ""
                kind = class_match.group(2)
                name = class_match.group(3)
                structure.append(f"\n🏛️  {visibility} {kind} {name} (line {i})")
                continue
            
            # Method definition
            method_match = re.match(r'^(public|private|protected)?\s*(static\s+)?([A-Za-z0-9_<>]+)\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', stripped)
            if method_match:
                visibility = method_match.group(1) or ""
                is_static = method_match.group(2) is not None
                return_type = method_match.group(3)
                name = method_match.group(4)
                params = method_match.group(5)
                static_str = "static " if is_static else ""
                structure.append(f"   📎{visibility} {static_str}{return_type} {name}({params}) → line {i}")
        
        return structure
    
    def _extract_go_structure(self, lines: list, detailed: bool = False) -> list:
        """Extract Go structs and functions."""
        structure = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if stripped.startswith('//'):
                continue
            
            # Struct definition
            struct_match = re.match(r'^type\s+([A-Za-z0-9_]+)\s+struct', stripped)
            if struct_match:
                name = struct_match.group(1)
                structure.append(f"\n🏛️  struct {name} (line {i})")
                continue
            
            # Interface definition
            iface_match = re.match(r'^type\s+([A-Za-z0-9_]+)\s+interface', stripped)
            if iface_match:
                name = iface_match.group(1)
                structure.append(f"\n📋 interface {name} (line {i})")
                continue
            
            # Function definition
            func_match = re.match(r'^func\s+(?:\([A-Za-z0-9_]+\s+\*?[A-Za-z0-9_]+\)\s+)?([A-Za-z0-9_]+)\s*\(([^)]*)\)', stripped)
            if func_match:
                name = func_match.group(1)
                params = func_match.group(2)
                structure.append(f"⚡ func {name}({params}) → line {i}")
        
        return structure
    
    def _extract_rust_structure(self, lines: list, detailed: bool = False) -> list:
        """Extract Rust structs, enums, and functions."""
        structure = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if stripped.startswith('//'):
                continue
            
            # Struct definition
            struct_match = re.match(r'^(pub\s+)?struct\s+([A-Za-z0-9_]+)', stripped)
            if struct_match:
                is_pub = struct_match.group(1) is not None
                name = struct_match.group(2)
                pub_str = "pub " if is_pub else ""
                structure.append(f"\n🏛️  {pub_str}struct {name} (line {i})")
                continue
            
            # Enum definition
            enum_match = re.match(r'^(pub\s+)?enum\s+([A-Za-z0-9_]+)', stripped)
            if enum_match:
                is_pub = enum_match.group(1) is not None
                name = enum_match.group(2)
                pub_str = "pub " if is_pub else ""
                structure.append(f"\n📋 {pub_str}enum {name} (line {i})")
                continue
            
            # Function definition
            func_match = re.match(r'^(pub\s+)?(async\s+)?fn\s+([A-Za-z0-9_]+)\s*[<(]', stripped)
            if func_match:
                is_pub = func_match.group(1) is not None
                is_async = func_match.group(2) is not None
                name = func_match.group(3)
                pub_str = "pub " if is_pub else ""
                async_str = "async " if is_async else ""
                structure.append(f"⚡ {pub_str}{async_str}fn {name} → line {i}")
        
        return structure
    
    def _extract_c_structure(self, lines: list, detailed: bool = False) -> list:
        """Extract C/C++ classes, functions, and structs."""
        structure = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if stripped.startswith('//') or stripped.startswith('/*'):
                continue
            
            # Class definition
            class_match = re.match(r'^class\s+([A-Za-z0-9_]+)', stripped)
            if class_match:
                name = class_match.group(1)
                structure.append(f"\n🏛️  class {name} (line {i})")
                continue
            
            # Struct definition
            struct_match = re.match(r'^(typedef\s+)?struct\s+([A-Za-z0-9_]+)?\s*\{?', stripped)
            if struct_match:
                name = struct_match.group(2) or "(anonymous)"
                structure.append(f"📋 struct {name} → line {i}")
                continue
            
            # Function definition (simplified)
            func_match = re.match(r'^([A-Za-z0-9_]+)\s+([A-Za-z0-9_]+)\s*\([^)]*\)\s*\{', stripped)
            if func_match:
                return_type = func_match.group(1)
                name = func_match.group(2)
                structure.append(f"⚡ {return_type} {name}() → line {i}")
        
        return structure
    
    def _extract_generic_structure(self, lines: list) -> list:
        """Generic structure extraction for unknown file types."""
        structure = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip empty lines and comments
            if not stripped or stripped.startswith('#') or stripped.startswith('//'):
                continue
            
            # Look for function-like patterns
            func_patterns = [
                r'function\s+([A-Za-z0-9_]+)',
                r'def\s+([A-Za-z0-9_]+)',
                r'func\s+([A-Za-z0-9_]+)',
                r'fn\s+([A-Za-z0-9_]+)',
                r'class\s+([A-Za-z0-9_]+)',
            ]
            
            for pattern in func_patterns:
                match = re.search(pattern, stripped)
                if match:
                    structure.append(f"   L{i:4d}: {stripped[:60]}")
                    break
        
        return structure

    # ─── SURGICAL EDITING TOOLS ─────────────────────────────────────────────────
    
    def _delete_lines(self, path: str, start_line: int, end_line: int) -> str:
        """
        Delete lines from start_line to end_line (inclusive, 1-indexed).
        Use for removing code blocks precisely.
        """
        try:
            resolved_path = self._resolve_path(path)
            str_path = str(resolved_path)
            
            if not resolved_path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            
            with open(resolved_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            original_content = "".join(lines)
            total_lines = len(lines)
            
            # Validate line range
            if start_line < 1:
                return f"❌ Invalid start_line: {start_line}. Line numbers are 1-indexed."
            if end_line > total_lines:
                return f"❌ Invalid end_line: {end_line}. File has {total_lines} lines."
            if start_line > end_line:
                return f"❌ Invalid range: start_line ({start_line}) > end_line ({end_line})."
            
            # Record for undo
            self._editor.undo_stack.push(str_path, original_content, f"delete lines {start_line}-{end_line}")
            
            # Delete lines (convert to 0-indexed)
            deleted_lines = lines[start_line-1:end_line]
            del lines[start_line-1:end_line]
            
            new_content = "".join(lines)
            with open(resolved_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            _set_cached_file(str_path, new_content)
            
            deleted_preview = "".join(deleted_lines[:3])
            if len(deleted_lines) > 3:
                deleted_preview += f"... ({len(deleted_lines)} lines total)"
            
            return f"✅ Deleted lines {start_line}-{end_line} from {Path(path).name}\nDeleted:\n{deleted_preview}"
            
        except Exception as e:
            raise Exception(f"Failed to delete lines: {e}")
    
    def _replace_lines(self, path: str, start_line: int, end_line: int, new_code: str) -> str:
        """
        Replace lines from start_line to end_line with new_code.
        Use for replacing entire code blocks precisely.
        """
        try:
            resolved_path = self._resolve_path(path)
            str_path = str(resolved_path)
            
            if not resolved_path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            
            with open(resolved_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            original_content = "".join(lines)
            total_lines = len(lines)
            
            # Validate line range
            if start_line < 1:
                return f"❌ Invalid start_line: {start_line}. Line numbers are 1-indexed."
            if end_line > total_lines:
                return f"❌ Invalid end_line: {end_line}. File has {total_lines} lines."
            if start_line > end_line:
                return f"❌ Invalid range: start_line ({start_line}) > end_line ({end_line})."
            
            # Record for undo
            self._editor.undo_stack.push(str_path, original_content, f"replace lines {start_line}-{end_line}")
            
            # Ensure new_code ends with newline
            if not new_code.endswith('\n'):
                new_code += '\n'
            
            # Replace lines
            old_lines = lines[start_line-1:end_line]
            lines[start_line-1:end_line] = [new_code]
            
            new_content = "".join(lines)
            with open(resolved_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            _set_cached_file(str_path, new_content)
            
            return f"✅ Replaced lines {start_line}-{end_line} ({len(old_lines)} lines) with {len(new_code.splitlines())} lines in {Path(path).name}"
            
        except Exception as e:
            raise Exception(f"Failed to replace lines: {e}")
    
    def _find_usages(self, symbol: str, file_pattern: str = "*") -> str:
        """
        Find all usages of a symbol (function, class, variable) across the codebase.
        Returns file paths and line numbers where the symbol is used.
        """
        try:
            import re
            from pathlib import Path as PathLib
            
            if not self.project_root:
                return "❌ No project root set. Open a project first."
            
            root = PathLib(self.project_root)
            results = []
            files_scanned = 0
            pattern = re.compile(rf'\b{re.escape(symbol)}\b')
            
            # Walk through source files
            source_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.kt', 
                                '.go', '.rs', '.c', '.cpp', '.h', '.hpp', '.rb', '.php'}
            
            for file_path in root.rglob(file_pattern):
                # Skip excluded directories
                if any(skip in str(file_path) for skip in ['node_modules', 'venv', '__pycache__', 
                                                            '.git', 'dist', 'build', 'target']):
                    continue
                
                if file_path.suffix.lower() not in source_extensions:
                    continue
                
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    lines = content.split('\n')
                    matches_in_file = []
                    
                    for i, line in enumerate(lines, 1):
                        if pattern.search(line):
                            # Skip the definition itself (look for usage patterns)
                            stripped = line.strip()
                            if stripped.startswith('def ') or stripped.startswith('class ') or stripped.startswith('func '):
                                # Include definition
                                pass
                            matches_in_file.append((i, line.strip()[:80]))
                    
                    if matches_in_file:
                        rel_path = str(file_path.relative_to(root))
                        results.append(f"\n📄 {rel_path}")
                        for line_num, line_content in matches_in_file[:10]:  # Limit to 10 matches per file
                            results.append(f"   L{line_num}: {line_content}")
                        if len(matches_in_file) > 10:
                            results.append(f"   ... and {len(matches_in_file) - 10} more matches")
                    
                    files_scanned += 1
                    
                except Exception:
                    continue
            
            if not results:
                return f"No usages found for '{symbol}' in {files_scanned} files."
            
            return f"Found {sum(len(r.split('\\n'))-1 for r in results)} usages of '{symbol}' in {files_scanned} files:\n" + "\n".join(results)
            
        except Exception as e:
            return f"Error searching for usages: {e}"
    
    def _analyze_file(self, path: str, analysis_type: str = "full") -> str:
        """
        Deep analysis of a file for better understanding before editing.
        analysis_type: 'full' | 'dependencies' | 'structure' | 'complexity'
        """
        try:
            resolved_path = self._resolve_path(path)
            if not resolved_path.exists():
                return f"File not found: {path}"
            
            content = Path(resolved_path).read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')
            ext = Path(path).suffix.lower()
            
            results = [f"📊 Analysis of {Path(path).name} ({len(lines)} lines)"]
            results.append("=" * 50)
            
            # Import analysis
            imports = []
            import_patterns = [
                r'^import\s+([a-zA-Z0-9_\.]+)',
                r'^from\s+([a-zA-Z0-9_\.]+)\s+import',
                r'^const\s+[a-zA-Z0-9_]+\s*=\s*require\([\'"]([^\'"]+)[\'"]',
                r'^import\s+[a-zA-Z0-9_{}\s,]+\s+from\s+[\'"]([^\'"]+)[\'"]',
            ]
            
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                for pattern in import_patterns:
                    match = re.match(pattern, stripped)
                    if match:
                        imports.append((i, match.group(1)))
                        break
            
            # Extract structure using existing method
            if ext in ('.py',):
                structure = self._extract_python_structure(lines)
            elif ext in ('.js', '.ts', '.jsx', '.tsx'):
                structure = self._extract_js_structure(lines)
            else:
                structure = self._extract_generic_structure(lines)
            
            # Complexity estimate
            complexity_indicators = {
                'classes': len([s for s in structure if 'CLASS' in s]),
                'functions': len([s for s in structure if 'func' in s.lower() or 'DEF' in s]),
                'lines': len(lines),
                'imports': len(imports),
            }
            
            # Output
            results.append("\n📦 DEPENDENCIES:")
            if imports:
                for line_num, module in imports[:15]:
                    results.append(f"   L{line_num}: {module}")
                if len(imports) > 15:
                    results.append(f"   ... and {len(imports) - 15} more")
            else:
                results.append("   No imports found")
            
            results.append("\n🏗️ STRUCTURE:")
            results.extend(structure[:30])
            if len(structure) > 30:
                results.append(f"   ... and {len(structure) - 30} more items")
            
            results.append("\n📈 COMPLEXITY:")
            results.append(f"   Classes: {complexity_indicators['classes']}")
            results.append(f"   Functions/Methods: {complexity_indicators['functions']}")
            results.append(f"   Total lines: {complexity_indicators['lines']}")
            
            # Edit recommendations
            results.append("\n💡 RECOMMENDATIONS:")
            if complexity_indicators['lines'] > 500:
                results.append("   ⚠️ Large file - use get_file_outline before editing")
            if complexity_indicators['functions'] > 20:
                results.append("   ⚠️ Many functions - search for specific function before editing")
            if complexity_indicators['imports'] > 20:
                results.append("   ⚠️ Many dependencies - check import order")
            
            return "\n".join(results)
            
        except Exception as e:
            return f"Analysis failed: {e}"
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
            
    def _list_directory(self, path: str = ".", show_hidden: bool = False, depth: Optional[int] = None) -> str:
        """List directory with role annotations, skipping noise dirs and blocking dependency directories."""
        try:
            resolved_path = self._resolve_path(path)
            str_path = str(resolved_path)
            
            # Ignore depth parameter for now - always do flat listing
            
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
            
            # Add AI hints for important files
            hints = []
            all_items = items + blocked_items
            if any("README" in item for item in all_items):
                hints.append("→ Read README.md first for project overview")
            if any("package.json" in item for item in all_items):
                hints.append("→ package.json contains dependencies and scripts")
            if any("pyproject.toml" in item or "requirements.txt" in item for item in all_items):
                hints.append("→ Check pyproject.toml/requirements.txt for Python deps")
            if any("src/" in item or item.startswith("📁 src/") for item in all_items):
                hints.append("→ src/ contains the main source code")
            if any("tests/" in item or "test/" in item for item in all_items):
                hints.append("→ tests/ contains the test suite")
            
            if hints:
                items.append("")
                items.append("[AI hints:]")
                items.extend(hints)
            
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
        """Run terminal command with streaming output — never blocks UI."""
        import threading
        import queue as queue_module
        
        try:
            # Determine the working directory safely
            working_dir = None
            if self.project_root and os.path.isdir(self.project_root):
                working_dir = str(self.project_root)
            else:
                working_dir = os.getcwd()
            
            # Safety: ensure working_dir exists and is accessible
            if not os.path.isdir(working_dir):
                working_dir = os.path.expanduser("~")

            # ── HARD PATH ISOLATION: Block commands that try to leave project root ──
            command_lower = command.lower()
            project_root_lower = working_dir.lower() if working_dir else ""

            # Block any cd/change directory that goes outside project root
            if project_root_lower:
                # Check for cd commands to other locations
                if 'cd ' in command_lower:
                    # Extract the target directory from cd command
                    import re
                    cd_matches = re.findall(r'cd\s+([a-zA-Z]:[^\s;&|]+)', command, re.IGNORECASE)
                    cd_matches += re.findall(r'cd\s+"?([a-zA-Z]:[^\s;&|]+)', command, re.IGNORECASE)
                    for cd_target in cd_matches:
                        # Resolve the target path
                        try:
                            target_abs = os.path.abspath(os.path.join(working_dir, cd_target))
                            if not target_abs.lower().startswith(project_root_lower):
                                log.warning(f"BLOCKED: Command tries to cd outside project: {cd_target}")
                                return (
                                    f"❌ BLOCKED: Cannot run commands outside the project directory.\n"
                                    f"The project root is: {working_dir}\n"
                                    f"You attempted to access: {cd_target}\n"
                                    f"Stay within the project folder."
                                )
                        except Exception:
                            pass

                # Block common destructive commands targeting system areas
                dangerous_system_paths = [
                    r'c:\windows', r'c:\program files', r'c:\programdata',
                    r'/etc', r'/usr/bin', r'/usr/sbin', r'/bin', r'/sbin',
                    r'd:\windows', r'd:\program files'
                ]
                for sys_path in dangerous_system_paths:
                    if sys_path in command_lower:
                        log.warning(f"BLOCKED: Command targets system directory: {sys_path}")
                        return (
                            f"❌ BLOCKED: Cannot run commands that target system directories.\n"
                            f"This command was blocked for safety."
                        )

            # Check for virtual environment commands that might cause performance issues
            venv_indicators = ['venv', 'virtualenv', '.venv', 'env/', 'node_modules']
            dangerous_patterns = [
                'rm -rf venv', 'rm -rf node_modules', 'del venv', 'rmdir venv',
                'pip install -r', 'npm install', 'yarn install', 'pnpm install'
            ]

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
            
            log.info(f"Running command '{command}' in: {working_dir}")
            
            # ── Always use subprocess for reliable output capture ────────────────
            # Terminal widget is optional visual feedback only
            if self.terminal_widget and hasattr(self.terminal_widget, 'execute_command'):
                try:
                    # Show command in terminal for visual feedback (non-blocking)
                    if hasattr(self.terminal_widget, 'set_cwd'):
                        self.terminal_widget.set_cwd(working_dir)
                    self.terminal_widget.execute_command(command)
                except Exception as e:
                    log.debug(f"Could not show command in terminal widget: {e}")
                    # Continue anyway - subprocess will handle the actual execution

            # ── Primary: streaming subprocess ────────────────────────────────────
            output_lines = []
            output_queue = queue_module.Queue()
            process_ref = [None]  # mutable ref so thread can set it

            def _run_in_thread():
                """Run subprocess in separate thread, queue output line by line."""
                try:
                    proc = subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,    # merge stderr into stdout
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        cwd=working_dir,
                        bufsize=1                    # line-buffered
                    )
                    process_ref[0] = proc

                    for line in proc.stdout:
                        output_queue.put(('line', line))

                    proc.wait()
                    output_queue.put(('done', proc.returncode))

                except Exception as e:
                    output_queue.put(('error', str(e)))

            # Start subprocess in daemon thread (dies if app dies)
            t = threading.Thread(target=_run_in_thread, daemon=True)
            t.start()

            # ── Collect output with timeout ───────────────────────────────────────
            deadline = time.time() + timeout
            MAX_OUTPUT_LINES = 500        # hard cap — prevents memory explosion
            MAX_LINE_LEN = 500            # truncate very long lines (minified output)

            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    # Kill the process if it's still running
                    if process_ref[0]:
                        try:
                            process_ref[0].kill()
                        except Exception:
                            pass
                    output_lines.append(f"\n[TIMEOUT after {timeout}s — process killed]")
                    break

                try:
                    msg_type, value = output_queue.get(timeout=min(remaining, 0.5))
                except queue_module.Empty:
                    # Not done yet, continue waiting
                    continue

                if msg_type == 'line':
                    line = value
                    if len(line) > MAX_LINE_LEN:
                        line = line[:MAX_LINE_LEN] + ' ...[line truncated]\n'
                    output_lines.append(line)
                    if len(output_lines) >= MAX_OUTPUT_LINES:
                        output_lines.append(f"\n[Output truncated at {MAX_OUTPUT_LINES} lines]")
                        if process_ref[0]:
                            try:
                                process_ref[0].kill()
                            except Exception:
                                pass
                        break

                elif msg_type == 'done':
                    exit_code = value
                    if exit_code != 0:
                        output_lines.append(f"\n[Exit code: {exit_code}]")
                    break

                elif msg_type == 'error':
                    output_lines.append(f"\n[Error: {value}]")
                    break

            t.join(timeout=1.0)  # Brief join — thread should be done by now

            result = ''.join(output_lines) or f"[Command completed: {command}]"
            if warnings:
                result = "\n".join(warnings) + "\n\n" + result
            return result

        except Exception as e:
            raise Exception(f"Failed to run command: {e}")

    def _read_terminal(self, lines: int = 50) -> str:
        """Read terminal output."""
        if self.terminal_widget and hasattr(self.terminal_widget, 'get_last_output'):
            return self.terminal_widget.get_last_output(lines)
        return "Terminal output not available."
            
    def _git_status(self) -> str:
        """Get git status using git manager or subprocess fallback."""
        import subprocess
        import os
        
        # Determine working directory
        working_dir = self.project_root or os.getcwd()
        
        try:
            # Try using git manager first
            if self.git_manager and self.git_manager.is_repo():
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
            log.warning(f"Git manager failed, falling back to subprocess: {e}")
        
        # Fallback: use subprocess directly
        try:
            result = subprocess.run(
                ['git', 'status', '--short'],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                if "not a git repository" in result.stderr.lower():
                    return "Not a git repository"
                raise Exception(result.stderr)
            
            output = result.stdout.strip()
            if not output:
                return "Working tree clean"
            
            # Format the output
            lines = []
            for line in output.split('\n'):
                if line:
                    status = line[:2]
                    filename = line[3:]
                    staged = "✓" if status[0] != ' ' and status[0] != '?' else " "
                    lines.append(f"{staged} {status.strip()} {filename}")
            
            return "\n".join(lines)
            
        except subprocess.TimeoutExpired:
            raise Exception("Git status timed out - repository may be too large")
        except Exception as e:
            raise Exception(f"Failed to get git status: {e}")
            
    def _git_diff(self, file_path: Optional[str] = None, staged: bool = False) -> str:
        """Get git diff using git manager or subprocess fallback."""
        import subprocess
        import os
        
        working_dir = self.project_root or os.getcwd()
        
        # Try git manager first
        try:
            if self.git_manager and self.git_manager.is_repo():
                diff = self.git_manager.get_diff(file_path, staged)
                return diff if diff else "No changes to display"
        except Exception as e:
            log.warning(f"Git manager failed for diff, falling back: {e}")
        
        # Fallback: use subprocess
        try:
            cmd = ['git', 'diff']
            if staged:
                cmd.append('--staged')
            if file_path:
                cmd.append(file_path)
            
            result = subprocess.run(
                cmd,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                if "not a git repository" in result.stderr.lower():
                    return "Not a git repository"
                raise Exception(result.stderr)
            
            return result.stdout if result.stdout else "No changes to display"
            
        except subprocess.TimeoutExpired:
            raise Exception("Git diff timed out")
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

    def _search_codebase(self, query: str, target_directories: Optional[List[str]] = None) -> str:
        """Semantic code search using the search_codebase module."""
        try:
            from src.ai.codebase_search import search_codebase
            
            # Extract keywords from query
            keywords = [word for word in query.lower().split() if len(word) > 3]
            if not keywords:
                keywords = ["code", "implementation"]
            
            # Limit to 3 most important keywords
            key_words = ",".join(keywords[:3])
            
            # Build target directories
            dirs = target_directories
            if not dirs and self.project_root:
                dirs = [self.project_root]
            
            # Perform semantic search
            results = search_codebase(query, key_words, dirs)
            
            if not results:
                return f"No semantic matches found for '{query}'. Try using search_code for text-based search."
            
            # Format results
            output_lines = [f"## Semantic Search Results for: {query}\n"]
            for i, result in enumerate(results[:10], 1):
                output_lines.append(f"{i}. {result.get('file', 'Unknown')}")
                if 'snippet' in result:
                    snippet = result['snippet'][:200] + "..." if len(result['snippet']) > 200 else result['snippet']
                    output_lines.append(f"   {snippet}")
                output_lines.append("")
            
            return "\n".join(output_lines)
            
        except ImportError:
            # Fallback to simple keyword search
            return self._search_code(query, "*.py")
        except Exception as e:
            raise Exception(f"Failed to search codebase: {e}")

    def _get_problems(self, file_paths: Optional[List[str]] = None) -> str:
        """Check for compile errors, lint issues, and syntax problems.
        
        Args:
            file_paths: List of file paths to check. If None or empty, checks recent Python files.
        """
        try:
            import subprocess
            import sys
            import ast
            
            # FIX: Ensure file_paths is always a list (never null)
            if file_paths is None:
                file_paths = []
            
            problems = []
            
            # If no files specified, check recently modified Python files
            if not file_paths:
                search_path = Path(self.project_root or os.getcwd())
                file_paths = []
                for py_file in search_path.rglob("*.py"):
                    # Skip blocked directories
                    if any(blocked in str(py_file) for blocked in BLOCKED_DIRS):
                        continue
                    file_paths.append(str(py_file))
                    if len(file_paths) >= 10:  # Limit to 10 files
                        break
            
            for file_path in file_paths:
                resolved = self._resolve_path(file_path)
                if not resolved.exists():
                    continue
                
                # Check Python syntax
                try:
                    with open(resolved, 'r', encoding='utf-8', errors='ignore') as f:
                        source = f.read()
                    ast.parse(source)
                except SyntaxError as e:
                    problems.append(f"❌ {file_path}:{e.lineno}: Syntax error - {e.msg}")
                    continue
                except Exception as e:
                    problems.append(f"⚠️ {file_path}: Could not parse - {e}")
                    continue
                
                # Try importing to catch runtime errors
                try:
                    # Use py_compile for additional checks
                    import py_compile
                    py_compile.compile(str(resolved), doraise=True)
                except Exception as e:
                    problems.append(f"⚠️ {file_path}: Compile error - {e}")
            
            if not problems:
                return "✅ No problems found in checked files."
            
            return "## Code Problems Found:\n\n" + "\n".join(problems)
            
        except Exception as e:
            raise Exception(f"Failed to check for problems: {e}")

    def _lsp_find_references(self, symbol: str, file_path: str, line: int, character: int) -> str:
        """Find all references to a symbol using LSP."""
        try:
            from src.core.lsp_client import get_lsp_client
            
            resolved_path = self._resolve_path(file_path)
            
            lsp = get_lsp_client()
            if not lsp.is_running():
                return "LSP server not available. Make sure the project is indexed."
            
            references = lsp.find_references(str(resolved_path), line, character)
            
            if not references:
                return f"No references found for '{symbol}'"
            
            output_lines = [f"## References to '{symbol}':\n"]
            for ref in references[:20]:  # Limit to 20 references
                ref_path = ref.get('uri', 'Unknown').replace('file://', '')
                ref_line = ref.get('range', {}).get('start', {}).get('line', 0) + 1
                output_lines.append(f"• {ref_path}:{ref_line}")
            
            return "\n".join(output_lines)
            
        except ImportError:
            return "LSP client not available. Falling back to text search...\n\n" + self._search_code(symbol)
        except Exception as e:
            raise Exception(f"Failed to find references: {e}")

    def _lsp_go_to_definition(self, symbol: str, file_path: str, line: int, character: int) -> str:
        """Go to definition of a symbol using LSP."""
        try:
            from src.core.lsp_client import get_lsp_client
            
            resolved_path = self._resolve_path(file_path)
            
            lsp = get_lsp_client()
            if not lsp.is_running():
                return "LSP server not available."
            
            definitions = lsp.go_to_definition(str(resolved_path), line, character)
            
            if not definitions:
                return f"No definition found for '{symbol}'"
            
            output_lines = [f"## Definition of '{symbol}':\n"]
            for defn in definitions[:5]:  # Usually just 1 definition
                def_path = defn.get('uri', 'Unknown').replace('file://', '')
                def_line = defn.get('range', {}).get('start', {}).get('line', 0) + 1
                output_lines.append(f"📍 {def_path}:{def_line}")
                
                # Try to read the definition line
                try:
                    with open(def_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        if 0 <= def_line - 1 < len(lines):
                            output_lines.append(f"   {lines[def_line - 1].strip()}")
                except:
                    pass
            
            return "\n".join(output_lines)
            
        except ImportError:
            return f"LSP client not available. Try searching for 'def {symbol}' or 'class {symbol}'"
        except Exception as e:
            raise Exception(f"Failed to go to definition: {e}")

    def _verify_fix(self, test_command: Optional[str] = None, check_scenario: Optional[str] = None, 
                    file_paths: Optional[List[str]] = None) -> str:
        """Verify that a fix works by running tests or checking files."""
        results = []
        
        # 1. Check for syntax/compile errors
        if file_paths:
            results.append("### Checking for syntax errors...")
            problems_result = self._get_problems(file_paths)
            results.append(problems_result)
            
            if "❌" in problems_result or "⚠️" in problems_result:
                results.append("\n❌ Fix verification FAILED - syntax errors found")
                return "\n".join(results)
        
        # 2. Run test command if provided
        if test_command:
            results.append(f"\n### Running test command: {test_command}")
            try:
                test_result = self._run_command(test_command, timeout=60)
                results.append(test_result)
                
                # Check for test failure indicators
                if any(indicator in test_result.lower() for indicator in ['failed', 'error', 'fail', 'traceback']):
                    results.append("\n❌ Fix verification FAILED - tests did not pass")
                else:
                    results.append("\n✅ Tests passed")
            except Exception as e:
                results.append(f"\n❌ Test command failed: {e}")
        
        # 3. Check scenario description
        if check_scenario:
            results.append(f"\n### Checking scenario: {check_scenario}")
            results.append("Please verify manually that the scenario works as expected.")
        
        results.append("\n✅ Fix verification complete")
        return "\n".join(results)

    def _search_memory(self, query: str, category: str = "", depth: str = "shallow") -> str:
        """Search past memories for similar problems."""
        try:
            from src.memory.memory_manager import search_memory
            
            memories = search_memory(query, category, depth)
            
            if not memories:
                return f"No memories found for '{query}'. Proceeding with fresh analysis."
            
            output_lines = [f"## Past Memories for: {query}\n"]
            for i, mem in enumerate(memories[:5], 1):
                output_lines.append(f"{i}. {mem.get('title', 'Untitled')}")
                if 'content' in mem:
                    content = mem['content'][:300] + "..." if len(mem['content']) > 300 else mem['content']
                    output_lines.append(f"   {content}")
                output_lines.append("")
            
            output_lines.append("💡 Consider these past experiences before proceeding.")
            return "\n".join(output_lines)
            
        except ImportError:
            return "Memory system not available."
        except Exception as e:
            return f"Could not search memory: {e}"

    def _git_commit(self, message: str, files: Optional[List[str]] = None, stage_all: bool = False) -> str:
        """Commit changes to git repository."""
        import subprocess
        import os
        
        # Determine repository path
        repo_path = self.project_root or os.getcwd()
        if self.git_manager and self.git_manager.repo_path:
            repo_path = self.git_manager.repo_path
        
        # Verify it's a git repo
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return "Not a git repository"
        except Exception:
            return "Not a git repository"
        
        try:
            
            # Stage files
            if stage_all:
                result = subprocess.run(
                    ['git', 'add', '-A'],
                    cwd=repo_path,
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    raise Exception(f"Failed to stage files: {result.stderr}")
            elif files:
                for file_path in files:
                    resolved = self._resolve_path(file_path)
                    result = subprocess.run(
                        ['git', 'add', str(resolved)],
                        cwd=repo_path,
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        raise Exception(f"Failed to stage {file_path}: {result.stderr}")
            
            # Commit
            result = subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return f"✅ Committed: {message}\n{result.stdout}"
            else:
                if "nothing to commit" in result.stderr.lower():
                    return "Nothing to commit - working tree clean"
                raise Exception(f"Commit failed: {result.stderr}")
                
        except Exception as e:
            raise Exception(f"Failed to commit: {e}")

    def _semantic_search(self, query: str, limit: int = 10, chunk_types: Optional[List[str]] = None) -> str:
        """Semantic search using embeddings."""
        try:
            from src.core.semantic_search import get_semantic_searcher

            project_root = self.project_root or os.getcwd()
            searcher = get_semantic_searcher(project_root)
            stats = searcher.get_stats()
            if stats.get("files_indexed", 0) == 0:
                searcher.index_project()

            results = searcher.search(query, top_k=limit)

            if not results:
                return f"No semantic matches found for '{query}'. The project may not be indexed yet."

            output_lines = [f"## Semantic Search Results for: {query}\n"]
            output_lines.append(f"Found {len(results)} matching files:\n")
            if chunk_types:
                output_lines.append("Note: chunk_types filtering is not supported by the current semantic index.\n")

            for i, result in enumerate(results, 1):
                try:
                    rel_path = str(Path(result.file_path).relative_to(Path(project_root)))
                except Exception:
                    rel_path = result.file_path

                output_lines.append(f"### {i}. {rel_path}")
                output_lines.append(f"   Similarity: {result.similarity:.3f}")
                output_lines.append(f"   Line ~{result.line_number}")

                snippet = result.content_snippet[:300] + "..." if len(result.content_snippet) > 300 else result.content_snippet
                output_lines.append("   ```")
                output_lines.append(f"   {snippet}")
                output_lines.append("   ```\n")

            return "\n".join(output_lines)

        except ImportError:
            return (
                "Semantic search not available. The project needs to be indexed first. "
                "Use 'index_project' to enable semantic search."
            )
        except Exception as e:
            raise Exception(f"Semantic search failed: {e}")

    def _find_function(self, name: str, file_pattern: Optional[str] = None) -> str:
        """Find function definitions by name pattern."""
        try:
            from src.core.codebase_index import get_codebase_index, SymbolType
            import fnmatch

            project_root = self.project_root or os.getcwd()
            index = get_codebase_index(project_root)
            if index.get_project_stats().get("files_indexed", 0) == 0:
                index.index_project()

            name_lower = name.lower()
            symbols = []
            symbols.extend(index.find_symbols(sym_type=SymbolType.FUNCTION))
            symbols.extend(index.find_symbols(sym_type=SymbolType.METHOD))

            results = []
            for symbol in symbols:
                if name_lower not in symbol.name.lower():
                    continue
                if file_pattern and not fnmatch.fnmatch(Path(symbol.file_path).name, file_pattern):
                    continue
                results.append(symbol)

            if not results:
                return self._search_code(
                    f"def {name}|function {name}|async def {name}",
                    file_pattern or "*.py"
                )

            output_lines = [f"## Function Definitions for: {name}\n"]
            output_lines.append(f"Found {len(results)} function(s):\n")

            for i, symbol in enumerate(results, 1):
                try:
                    rel_path = str(Path(symbol.file_path).relative_to(Path(project_root)))
                except Exception:
                    rel_path = symbol.file_path
                output_lines.append(f"### {i}. {symbol.name} ({symbol.type.value})")
                output_lines.append(f"   Location: {rel_path}:{symbol.line}")
                if symbol.parent:
                    output_lines.append(f"   Parent: {symbol.parent}")
                output_lines.append("")

            return "\n".join(output_lines)

        except ImportError:
            return self._search_code(f"def {name}|function {name}", file_pattern or "*.py")
        except Exception as e:
            raise Exception(f"Failed to find function: {e}")

    def _find_class(self, name: str, file_pattern: Optional[str] = None) -> str:
        """Find class definitions by name pattern."""
        try:
            from src.core.codebase_index import get_codebase_index, SymbolType
            import fnmatch

            project_root = self.project_root or os.getcwd()
            index = get_codebase_index(project_root)
            if index.get_project_stats().get("files_indexed", 0) == 0:
                index.index_project()

            name_lower = name.lower()
            results = []
            for symbol in index.find_symbols(sym_type=SymbolType.CLASS):
                if name_lower not in symbol.name.lower():
                    continue
                if file_pattern and not fnmatch.fnmatch(Path(symbol.file_path).name, file_pattern):
                    continue
                results.append(symbol)

            if not results:
                return self._search_code(f"class {name}", file_pattern or "*.py")

            output_lines = [f"## Class Definitions for: {name}\n"]
            output_lines.append(f"Found {len(results)} class(es):\n")

            for i, symbol in enumerate(results, 1):
                try:
                    rel_path = str(Path(symbol.file_path).relative_to(Path(project_root)))
                except Exception:
                    rel_path = symbol.file_path
                output_lines.append(f"### {i}. {symbol.name}")
                output_lines.append(f"   Location: {rel_path}:{symbol.line}")
                output_lines.append("")

            return "\n".join(output_lines)

        except ImportError:
            return self._search_code(f"class {name}", file_pattern or "*.py")
        except Exception as e:
            raise Exception(f"Failed to find class: {e}")

    def _find_symbol(self, name: str, symbol_type: Optional[str] = None, file_pattern: Optional[str] = None) -> str:
        """Find any type of symbol by name pattern. Supports: function, class, method, variable, import, module."""
        try:
            from src.core.codebase_index import get_codebase_index, SymbolType
            import fnmatch

            project_root = self.project_root or os.getcwd()
            index = get_codebase_index(project_root)
            if index.get_project_stats().get("files_indexed", 0) == 0:
                index.index_project()

            # Map symbol_type string to SymbolType enum
            sym_type_map = {
                "function": SymbolType.FUNCTION,
                "class": SymbolType.CLASS,
                "method": SymbolType.METHOD,
                "variable": SymbolType.VARIABLE,
                "import": SymbolType.IMPORT,
                "module": SymbolType.MODULE,
            }
            
            sym_type = None
            if symbol_type:
                symbol_type_lower = symbol_type.lower()
                if symbol_type_lower in sym_type_map:
                    sym_type = sym_type_map[symbol_type_lower]
                else:
                    # If invalid symbol type provided, search all types
                    sym_type = None

            name_lower = name.lower()
            results = []
            for symbol in index.find_symbols(sym_type=sym_type):
                if name_lower not in symbol.name.lower():
                    continue
                if file_pattern and not fnmatch.fnmatch(Path(symbol.file_path).name, file_pattern):
                    continue
                results.append(symbol)

            if not results:
                # Fallback to text search
                search_terms = []
                if symbol_type:
                    search_terms.append(symbol_type)
                search_terms.append(name)
                return self._search_code(" ".join(search_terms), file_pattern or "*.py")

            # Group results by symbol type
            results_by_type = {}
            for symbol in results:
                symbol_type_str = symbol.type.value
                if symbol_type_str not in results_by_type:
                    results_by_type[symbol_type_str] = []
                results_by_type[symbol_type_str].append(symbol)

            output_lines = [f"## Symbol Search: {name}\n"]
            if symbol_type:
                output_lines.append(f"**Symbol Type:** {symbol_type}\n")
            output_lines.append(f"Found {len(results)} symbol(s):\n")

            for type_str, symbols in results_by_type.items():
                output_lines.append(f"### {type_str.capitalize()}s ({len(symbols)}):")
                for i, symbol in enumerate(symbols, 1):
                    try:
                        rel_path = str(Path(symbol.file_path).relative_to(Path(project_root)))
                    except Exception:
                        rel_path = symbol.file_path
                    
                    # Show parent for methods
                    location_info = f"{rel_path}:{symbol.line}"
                    if symbol.parent:
                        location_info = f"{symbol.parent}.{symbol.name} at {location_info}"
                    
                    output_lines.append(f"  {i}. {symbol.name}")
                    output_lines.append(f"     Location: {location_info}")
                    if symbol.signature:
                        output_lines.append(f"     Signature: {symbol.signature}")
                    output_lines.append("")

            return "\n".join(output_lines)

        except ImportError:
            # Fallback to text search if codebase_index not available
            search_terms = []
            if symbol_type:
                search_terms.append(symbol_type)
            search_terms.append(name)
            return self._search_code(" ".join(search_terms), file_pattern or "*.py")
        except Exception as e:
            raise Exception(f"Failed to find symbol: {e}")

    def _debug_error(self, error_text: str, file_path: Optional[str] = None, line_number: Optional[int] = None) -> str:
        """Analyze an error and provide fix suggestions."""
        try:
            from src.ai.error_analyzer import ErrorAnalyzer
            
            analyzer = ErrorAnalyzer(self.project_root)
            context = analyzer.analyze_error(error_text)
            
            # Override file/line if provided
            if file_path:
                context.file_path = file_path
            if line_number:
                context.line_number = line_number
            
            output_lines = [f"## Error Analysis\n"]
            output_lines.append(f"**Error Type:** {context.error_type}")
            output_lines.append(f"**Message:** {context.error_message}")
            
            if context.file_path and context.line_number:
                output_lines.append(f"**Location:** {context.file_path}:{context.line_number}")
            
            output_lines.append(f"**Framework Detected:** {context.framework}\n")
            
            # Get fix suggestions
            fix_suggestion = analyzer.get_fix_suggestion(context)
            output_lines.append("## Suggested Fix\n")
            output_lines.append(fix_suggestion)
            
            # Extract code snippet if file available
            if context.file_path and context.line_number:
                snippet = analyzer.extract_code_snippet(context.file_path, context.line_number, context_lines=5)
                if snippet:
                    output_lines.append("\n## Code Context\n")
                    output_lines.append("```")
                    for line_num, line_content in snippet:
                        marker = ">>>" if line_num == context.line_number else "   "
                        output_lines.append(f"{marker} {line_num:4d}| {line_content}")
                    output_lines.append("```")
            
            # Related files
            related_files = analyzer.find_related_files(context)
            if related_files:
                output_lines.append("\n## Files to Check\n")
                for f in related_files[:10]:
                    output_lines.append(f"- {f}")
            
            return "\n".join(output_lines)
            
        except ImportError:
            return f"Error analyzer not available. Error: {error_text[:200]}"
        except Exception as e:
            raise Exception(f"Failed to analyze error: {e}")

    def _check_syntax(self, file_path: str) -> str:
        """Check syntax of a file for errors."""
        try:
            from src.core.syntax_checker import get_syntax_checker
            from pathlib import Path
            
            resolved_path = self._resolve_path(file_path)
            
            if not resolved_path.exists():
                return f"File not found: {file_path}"
            
            checker = get_syntax_checker()
            content = resolved_path.read_text(encoding='utf-8', errors='ignore')
            result = checker.check_file(str(resolved_path), content)
            
            if result.success:
                return f"✅ No syntax errors in {file_path} ({result.language})"
            
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
            
            return "\n".join(output_lines)
            
        except ImportError:
            # Fallback to Python-only syntax check
            return self._get_problems([file_path])
        except Exception as e:
            raise Exception(f"Failed to check syntax: {e}")
