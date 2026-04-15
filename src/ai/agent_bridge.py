"""
Cortex Agent Bridge
===================
Connects Cortex IDE UI (ai_chat.py / script.js) to the real agent core at
src/agent/src/.

Architecture:
    Cortex UI (PyQt6)
        └── ai_chat.py  ──signals──►  CortexAgentBridge (this file)
                                           │
                                    AgentWorker (QThread)
                                           │
                              _call_llm() → multi-turn agentic loop
                                           │
                              ┌────────────┴──────────────┐
                              │                           │
                    Cortex Providers              Real Agent Tools
                 (DeepSeek / Mistral)         (Read/Write/Edit/Bash/
                  src/ai/providers/            Glob/Grep/LS)
                                           │
                              bootstrap/state.py
                              (project root, session)

Tool name convention matches the real agent tool registry:
    Read, Write, Edit, Bash, Glob, Grep, LS
"""

import asyncio
import os
import sys
import json
import uuid as _uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, QThread

# ============================================================
# SETUP PATH — expose real agent core as importable package
# ============================================================
_AGENT_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'agent', 'src')
)
if _AGENT_SRC not in sys.path:
    sys.path.insert(0, _AGENT_SRC)

from src.utils.logger import get_logger
from src.ai.streaming import get_streaming_emitter
from src.ai.session_task import (
    SessionTaskRegistry,
    SessionTaskState,
    StopTaskError,
    generate_session_task_id,
    stop_session_task,
)

log = get_logger("agent_bridge")


# ============================================================
# IMPORT REAL AGENT STATE (bootstrap/state.py)
# ============================================================
try:
    from bootstrap.state import (
        set_original_cwd,
        set_project_root as _agent_set_project_root,
        get_session_id,
        get_project_root as _agent_get_project_root,
    )
    _HAS_AGENT_STATE = True
    log.info("[BRIDGE] Real agent bootstrap/state loaded")
except ImportError as _e:
    _HAS_AGENT_STATE = False
    log.warning(f"[BRIDGE] agent bootstrap/state not available: {_e}")

    def set_original_cwd(cwd: str) -> None: pass
    def _agent_set_project_root(path: str) -> None: pass
    def get_session_id() -> str: return "default"
    def _agent_get_project_root() -> str: return os.getcwd()


# ============================================================
# LOCAL DATA CLASSES
# ============================================================

@dataclass
class ChatMessage:
    """Internal chat message used by the bridge."""
    role: str                           # system / user / assistant / tool
    content: str
    images: List[str] = field(default_factory=list)
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ToolCall:
    tool_id: str
    tool_name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    tool_id: str
    result: Any
    success: bool = True
    error: Optional[str] = None


# ============================================================
# IMPORT REAL AGENT TOOLS from src/agent/src/tools/
# These are the robust, production-quality implementations.
# ============================================================

import importlib as _importlib

def _load_agent_tool(module_path: str, class_name: str) -> type | None:
    """Dynamically import a real agent tool class. Returns None on failure."""
    try:
        mod = _importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        log.info(f"[BRIDGE] Real {class_name} loaded")
        return cls
    except Exception as exc:
        log.warning(f"[BRIDGE] {class_name} not available: {exc}")
        return None

_REAL_FILE_READ_TOOL  = _load_agent_tool("tools.FileReadTool.FileReadTool",  "FileReadTool")
_REAL_FILE_EDIT_TOOL  = _load_agent_tool("tools.FileEditTool.FileEditTool",  "FileEditTool")
_REAL_FILE_WRITE_TOOL = _load_agent_tool("tools.FileWriteTool.FileWriteTool", "FileWriteTool")
_REAL_GLOB_TOOL       = _load_agent_tool("tools.GlobTool.GlobTool",          "GlobTool")
_REAL_GREP_TOOL       = _load_agent_tool("tools.GrepTool.GrepTool",          "GrepTool")


# ============================================================
# IMPORT REAL AbortController from src/agent/src/utils
# Used to signal running tools when the user presses Stop.
# ============================================================
try:
    from utils.abortController import (
        AbortController  as _AgentAbortController,
        create_abort_controller as _create_abort_controller,
    )
    _HAS_REAL_ABORT = True
    log.info("[BRIDGE] Real AbortController loaded from utils.abortController")
except ImportError as _e:
    _HAS_REAL_ABORT = False
    log.warning(f"[BRIDGE] Real AbortController not available: {_e}")

    class _AgentAbortController:  # type: ignore[no-redef]
        """Minimal fallback — no-op abort."""
        class signal:
            aborted = False
            reason  = None
            @staticmethod
            def addEventListener(*a, **kw): pass
            @staticmethod
            def removeEventListener(*a, **kw): pass
        def abort(self, reason=None): pass

    def _create_abort_controller(max_listeners: int = 50) -> "_AgentAbortController":  # type: ignore[misc]
        return _AgentAbortController()


# ============================================================
# DIFF HOOKS — useDiffData + useDiffInIDE integration
# ============================================================

def _load_diff_service():
    """Load DiffDataService singleton. Returns None if unavailable."""
    try:
        mod = _importlib.import_module("hooks.useDiffData")
        return mod.get_diff_service()
    except Exception as exc:
        log.warning(f"[BRIDGE] DiffDataService not available: {exc}")
        return None

def _load_cortex_diff_bridge():
    """Load CortexDiffBridge singleton. Returns None if unavailable."""
    try:
        mod = _importlib.import_module("hooks.useDiffInIDE")
        return mod.CortexDiffBridge.instance()
    except Exception as exc:
        log.warning(f"[BRIDGE] CortexDiffBridge not available: {exc}")
        return None

_DIFF_SERVICE      = _load_diff_service()      # DiffDataService | None
_CORTEX_DIFF_BRIDGE = _load_cortex_diff_bridge()  # _CortexDiffBridge | None


# ============================================================
# CORTEX TOOL CONTEXT — minimal adapter for real agent tools
# Real tools call context.get_app_state(), context.read_file_state,
# context.abort_controller, context.glob_limits, etc.
# ============================================================

class _PermissionContext:
    """Stub permission context — allows everything."""
    mode = "default"
    rules = []


class _AppState:
    """Minimal AppState providing tool_permission_context."""
    tool_permission_context = _PermissionContext()


class _GlobLimits:
    max_results = 1000


# _AbortController stub removed — CortexToolContext now uses the real
# AbortController imported from utils.abortController above.


class CortexToolContext:
    """
    Lightweight adapter providing the fields that real agent tools
    read from ToolUseContext.  All permission / telemetry hooks
    are stubbed to keep the bridge lean.

    Also tracks file state across tool calls so the AI avoids
    re-reading unchanged files and detects stale edits.
    """

    def __init__(self, bridge: 'CortexAgentBridge'):
        self._bridge = bridge
        self.read_file_state: Dict[str, Any] = {}
        self.file_reading_limits = {
            "maxSizeBytes": 10_000_000,
            "maxTokens": 50_000,
        }
        self.glob_limits = _GlobLimits()
        self.abort_controller = _create_abort_controller()  # real AbortController; reset per request
        self.dynamic_skill_dir_triggers: set = set()
        self.nested_memory_attachment_triggers: set = set()
        self.user_modified = False

        # ── File state tracking ────────────────────────────────
        # Tracks files the AI has read/written/edited this session
        # so the system prompt can tell the LLM what it already knows.
        self._files_read: Dict[str, float] = {}      # path → timestamp
        self._files_modified: Dict[str, float] = {}   # path → timestamp

    # Real tools call context.get_app_state()
    def get_app_state(self) -> _AppState:
        return _AppState()

    # FileEditTool / FileWriteTool check this
    def file_history_enabled(self) -> bool:
        return False

    # ── File state helpers ─────────────────────────────────

    def mark_file_read(self, path: str):
        import time
        self._files_read[os.path.normpath(path)] = time.time()

    def mark_file_modified(self, path: str):
        import time
        norm = os.path.normpath(path)
        self._files_modified[norm] = time.time()
        # Invalidate read cache — file changed, LLM should re-read
        self._files_read.pop(norm, None)

    def is_file_known(self, path: str) -> bool:
        """Return True if the AI already read this file and hasn't modified it since."""
        norm = os.path.normpath(path)
        return norm in self._files_read

    def get_known_files_summary(self) -> str:
        """Return a short summary for the system prompt."""
        lines = []
        for p in list(self._files_read)[-10:]:
            lines.append(f"  [read] {p}")
        for p in list(self._files_modified)[-10:]:
            lines.append(f"  [modified] {p}")
        return "\n".join(lines) if lines else "(none yet)"


def _always_allow_tool(*_args, **_kwargs):
    """Stub can_use_tool function — always allows."""
    return True


# Stub parent message (some tools read parent_message.uuid)
_STUB_PARENT_MESSAGE = type("_Msg", (), {"uuid": None})()


# ============================================================
# BRIDGE-NATIVE TOOLS  (no real agent equivalent exists)
# ============================================================
# Destructive-command helpers (used by BridgeBashTool)
# ============================================================

def _get_destructive_warning(command: str) -> 'Optional[str]':
    """Return a human-readable warning if the command is destructive, else None."""
    try:
        from src.agent.src.tools.BashTool.destructiveCommandWarning import get_destructive_command_warning
        return get_destructive_command_warning(command)
    except Exception:
        pass
    # Inline fallback: simple regex for the most common dangerous patterns
    import re as _re
    PATTERNS = [
        (_re.compile(r'(^|[;&|]\s*)rm\s+-[a-zA-Z]*[rR]', _re.I), 'Note: may recursively remove files'),
        (_re.compile(r'(^|[;&|]\s*)rm\s+-[a-zA-Z]*f', _re.I), 'Note: may force-remove files'),
        (_re.compile(r'(^|[;&|]\s*)rm\s+\S', _re.I), 'Note: may delete files'),
        (_re.compile(r'(^|[;&|]\s*)rmdir\b', _re.I), 'Note: may remove a directory'),
        (_re.compile(r'\bdel\b.*\b/[sS]\b', _re.I), 'Note: may delete files recursively (Windows)'),
        (_re.compile(r'(^|[;&|]\s*)del\b', _re.I), 'Note: may delete files (Windows cmd)'),
        (_re.compile(r'\bRemove-Item\b.*-Recurse', _re.I), 'Note: may recursively delete files (PowerShell)'),
        (_re.compile(r'\bRemove-Item\b', _re.I), 'Note: may delete files (PowerShell)'),
        (_re.compile(r'\bgit\s+reset\s+--hard\b'), 'Note: may discard uncommitted changes'),
        (_re.compile(r'\bgit\s+push\b.*--force\b'), 'Note: may overwrite remote history'),
        (_re.compile(r'\b(DROP|TRUNCATE)\s+(TABLE|DATABASE)\b', _re.I), 'Note: may destroy database objects'),
    ]
    for pat, msg in PATTERNS:
        if pat.search(command):
            return msg
    return None


def _extract_affected_paths(command: str) -> list:
    """Extract up to 5 path-like arguments from a shell command for display."""
    import shlex as _shlex
    import re as _re
    try:
        parts = _shlex.split(command)
    except ValueError:
        parts = command.split()
    SKIP = {
        'rm', 'rmdir', 'del', 'Remove-Item', 'git', 'kubectl', 'terraform',
        'reset', 'push', 'clean', 'hard', '--hard', '--force', '-rf', '-f',
        '-r', '-fr', '-Force', '-Recurse', '-Path', '-LiteralPath',
        'DROP', 'TRUNCATE', 'DELETE', 'FROM', 'TABLE', 'powershell.exe',
        'powershell', 'cmd', 'cmd.exe',
    }
    paths = []
    for p in parts:
        if p.startswith('-') or p in SKIP:
            continue
        # Accept if it looks like a file/path (contains / \ . or has an extension)
        if _re.search(r'[/\\.]', p) or _re.search(r'\.[a-z]{1,5}$', p, _re.I):
            paths.append(p)
        elif p not in SKIP and len(p) > 1:
            paths.append(p)
    return paths[:5]


# ============================================================

class BridgeBashTool:
    """
    Bridge-native Bash tool — real BashTool.py does not exist in
    src/agent/src/tools/BashTool/ (only helper modules).
    """
    name = "Bash"
    description = (
        "Execute a shell / PowerShell command and return its output. "
        "Commands run in the project root by default."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to run"},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 30)",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    def __init__(self, bridge: 'CortexAgentBridge'):
        self._bridge = bridge

    async def execute(self, args: Dict) -> ToolResult:
        import subprocess as _sp
        import threading as _threading
        command = args.get("command", "")
        timeout = int(args.get("timeout", 30))
        cwd = self._bridge._project_root or os.getcwd()

        # ── Dangerous-command permission gate ────────────────────────────────
        warning = _get_destructive_warning(command)
        if warning and not self._bridge._stop_requested:
            affected = _extract_affected_paths(command)
            import json as _json
            # Create a fresh event for this request
            evt = _threading.Event()
            self._bridge._permission_event  = evt
            self._bridge._permission_granted = False
            self._bridge.permission_requested.emit(
                command, warning, _json.dumps(affected)
            )
            # Wait without blocking the event loop
            granted = await asyncio.to_thread(evt.wait, 60.0)  # 60 s timeout
            self._bridge._permission_event = None
            if not granted or not self._bridge._permission_granted:
                return ToolResult(
                    tool_id="", result=None, success=False,
                    error="User rejected the command — not executed."
                )
        # ───────────────────────────────────────────────────────────────

        proc = None
        try:
            if os.name == 'nt':
                # Windows: use PowerShell so .ps1 scripts execute correctly
                # (cmd.exe triggers Windows file-association dialog for .ps1).
                # asyncio.create_subprocess_exec keeps the event loop responsive
                # so stop/cancel requests are delivered immediately.
                proc = await asyncio.create_subprocess_exec(
                    'powershell.exe',
                    '-ExecutionPolicy', 'Bypass',
                    '-NonInteractive',
                    '-Command', command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )

            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                # Kill the process; communicate() drains remaining I/O
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
                return ToolResult(tool_id="", result=None, success=False,
                                  error=f"Command timed out after {timeout}s")

            stdout = (stdout_b.decode('utf-8', errors='replace') if stdout_b else "")
            stderr = (stderr_b.decode('utf-8', errors='replace') if stderr_b else "")
            output = stdout
            if stderr:
                output += f"\n[stderr]\n{stderr}"
            return ToolResult(
                tool_id="",
                result={
                    "command": command,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": proc.returncode,
                    "output": output or "(no output)",
                },
            )

        except asyncio.CancelledError:
            # Task was cancelled — kill subprocess so it doesn't linger
            if proc is not None:
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
            raise

        except Exception as e:
            return ToolResult(tool_id="", result=None, success=False, error=str(e))


class BridgeLSTool:
    """Bridge-native LS tool — no real agent equivalent."""
    name = "LS"
    description = "List the contents of a directory. Shows files and subdirectories."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path (default: project root)",
                "default": ".",
            },
        },
    }

    def __init__(self, bridge: 'CortexAgentBridge'):
        self._bridge = bridge

    async def execute(self, args: Dict) -> ToolResult:
        dirpath = args.get("path", ".")
        if not os.path.isabs(dirpath) and self._bridge._project_root:
            dirpath = os.path.join(self._bridge._project_root, dirpath)
        try:
            entries = []
            for entry in sorted(os.scandir(dirpath), key=lambda e: (not e.is_dir(), e.name)):
                marker = "/" if entry.is_dir() else ""
                entries.append(f"{entry.name}{marker}")
            self._bridge.directory_contents.emit(dirpath, "\n".join(entries))
            return ToolResult(tool_id="", result={"path": dirpath, "entries": entries})
        except Exception as e:
            return ToolResult(tool_id="", result=None, success=False, error=str(e))


# ============================================================
# TOOL DEFINITIONS  (OpenAI-compatible function schemas)
# ============================================================

_TOOL_SCHEMAS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": (
                "Read the contents of a file. Supports text files, images, "
                "PDFs, and Jupyter notebooks. Use for exploring any file in the project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute or project-relative path"},
                    "offset":    {"type": "integer", "description": "Start line (1-indexed, optional)"},
                    "limit":     {"type": "integer", "description": "Max lines to read (optional)"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Create a new file or completely overwrite an existing file with content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file"},
                    "content":   {"type": "string", "description": "Full content to write"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": (
                "Replace a specific exact string in a file with new text. "
                "old_string must appear exactly once unless replace_all is true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path":   {"type": "string", "description": "Path to the file"},
                    "old_string":  {"type": "string", "description": "Exact text to find"},
                    "new_string":  {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": (
                "Execute a shell / PowerShell command and return its output. "
                "Commands run in the project root by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": (
                "Find files matching a glob pattern (e.g. **/*.py). "
                "Use this to discover files in the project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern"},
                    "path":    {"type": "string", "description": "Directory to search in (default: project root)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": (
                "Search for a regex or literal pattern inside files using ripgrep. "
                "Returns matching lines with file names and line numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern":          {"type": "string",  "description": "Regex/text pattern to search"},
                    "path":             {"type": "string",  "description": "Directory or file to search"},
                    "glob":             {"type": "string",  "description": "File glob filter e.g. *.py"},
                    "case_insensitive": {"type": "boolean", "description": "Case-insensitive search (default false)"},
                    "multiline":        {"type": "boolean", "description": "Enable multiline regex (default false)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "LS",
            "description": "List the contents of a directory. Shows files and subdirectories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: project root)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TodoWrite",
            "description": (
                "Update the todo list for the current session. Use proactively for complex multi-step tasks "
                "(3+ steps). Mark tasks in_progress BEFORE starting, completed IMMEDIATELY after finishing. "
                "Always provide both content (imperative) and activeForm (present continuous) for each task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "The updated list of todo items.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":         {"type": "string",  "description": "Unique identifier for the task"},
                                "content":    {"type": "string",  "description": "Task description in imperative form (e.g. 'Run tests')"},
                                "activeForm": {"type": "string",  "description": "Task in present continuous form (e.g. 'Running tests')"},
                                "status":     {"type": "string",  "enum": ["pending", "in_progress", "completed"], "description": "Current task status"},
                            },
                            "required": ["id", "content", "activeForm", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
]


def _get_tool_definitions() -> List[Dict]:
    """Return OpenAI-compatible tool definitions for all registered tools."""
    return list(_TOOL_SCHEMAS)


# ============================================================
# UI SIGNAL ROUTING
# The bridge emits tool_activity(tool_name, info, status).
# Status values expected by script.js:
#   "running"   → shows spinner card
#   "complete"  → marks card OK  (NOT "completed" — that was the old bug)
#   "error"     → marks card red
# ============================================================

_TOOL_TO_ACTIVITY_NAME: Dict[str, str] = {
    "Read":      "read_file",
    "Write":     "write_file",
    "Edit":      "edit_file",
    "Bash":      "run_command",
    "Glob":      "list_directory",
    "TodoWrite": "todo_write",
    "Grep":  "search",
    "LS":    "list_directory",
}

# Tools that trigger the "create_file" UI card (Write on a new file)
_CREATE_TOOL_NAMES = {"Write"}


# ============================================================
# AGENT WORKER THREAD
# ============================================================

class AgentWorker(QThread):
    """
    Background thread running the async agentic loop.
    Prevents UI thread from blocking during long LLM calls.
    """

    response_ready  = pyqtSignal(str)
    chunk_ready     = pyqtSignal(str)
    error_occurred  = pyqtSignal(str)
    thinking_started = pyqtSignal()
    thinking_stopped = pyqtSignal()

    def __init__(self, bridge: 'CortexAgentBridge'):
        super().__init__()
        self.bridge = bridge
        self._is_running  = False
        self._stop_req    = False
        self._queue: Optional[asyncio.Queue] = None
        self._loop:  Optional[asyncio.AbstractEventLoop] = None
        # Tracks the asyncio.Task currently running _handle_chat.
        # Assigned right after asyncio.create_task(); used by stop_generation()
        # (via stop_session_task) to cancel mid-execution.
        self._current_chat_task: Optional[asyncio.Task] = None

    # ── QThread entry ──────────────────────────────────────────

    def run(self):
        self._is_running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._process_queue())
        except Exception as exc:
            log.error(f"[WORKER] Thread error: {exc}")
            self.error_occurred.emit(str(exc))
        finally:
            self._loop.close()
            self._is_running = False

    # ── Message queue ──────────────────────────────────────────

    async def _process_queue(self):
        """
        Event loop for the agent worker thread.

        Architecture (converted from LocalMainSessionTask.ts startBackgroundSession):
          - Each chat message creates a cancellable asyncio.Task (_handle_chat).
          - While the task runs we concurrently watch the queue for a stop/new-chat
            message using asyncio.wait(FIRST_COMPLETED).  This is the Python
            equivalent of the TS AbortController.abort() / kill() pattern —
            CancelledError propagates through every await in the call chain,
            including mid-tool-execution.
          - Only _is_running=False (set by AgentWorker.stop()) exits the outer loop.
        """
        self._queue = asyncio.Queue()

        while self._is_running:
            # ── Phase 1: Wait for the next queued message ─────────────────────
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                log.error(f"[WORKER] Queue error: {exc}")
                self.error_occurred.emit(str(exc))
                continue

            if msg.get("type") == "stop":
                # stop_generation() already called task.cancel() via
                # stop_session_task(); this message is just a queue flush.
                log.info("[WORKER] Stop message received (task cancel already in flight)")
                continue

            if msg.get("type") != "chat":
                continue

            # ── Phase 2: Run the chat task (cancellable) ──────────────────────
            self._current_chat_task = asyncio.create_task(
                self._handle_chat(msg)
            )

            # Register the asyncio.Task in the session registry so that
            # stop_session_task() (called from the Qt main thread) can cancel it.
            task_id = msg.get("task_id")
            if task_id:
                ts = self.bridge._task_registry.get(task_id)
                if ts:
                    ts.asyncio_task = self._current_chat_task

            # ── Phase 3: Concurrently watch task + queue ──────────────────────
            # Mirrors the TS pattern: the running query holds an AbortSignal;
            # a stop command triggers abort() → CancelledError here.
            while self._is_running and not self._current_chat_task.done():
                get_fut: asyncio.Task = asyncio.ensure_future(self._queue.get())
                try:
                    done, _ = await asyncio.wait(
                        {get_fut, self._current_chat_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except Exception as exc:
                    get_fut.cancel()
                    log.error(f"[WORKER] asyncio.wait error: {exc}")
                    break

                # ── Task finished naturally ────────────────────────────────
                if self._current_chat_task in done:
                    get_fut.cancel()
                    break

                # ── New queue message arrived while task running ───────────
                if get_fut in done:
                    try:
                        next_msg = get_fut.result()
                    except Exception:
                        continue

                    if next_msg.get("type") == "stop":
                        log.info(
                            "[WORKER] Stop message received while running — "
                            "cancelling chat task"
                        )
                        await self._cancel_active_task()
                        break

                    elif next_msg.get("type") == "chat":
                        # New prompt arrived before the old one finished.
                        # Cancel old, then re-queue the new message so the
                        # outer loop starts it fresh.
                        log.info(
                            "[WORKER] New chat arrived while running — "
                            "cancelling old task and re-queuing new one"
                        )
                        await self._cancel_active_task()
                        await self._queue.put(next_msg)
                        break
                    # else: ignore unknown message types while running

            # ── Phase 4: Await final cleanup ──────────────────────────────────
            if (
                self._current_chat_task is not None
                and not self._current_chat_task.done()
            ):
                try:
                    await self._current_chat_task
                except (asyncio.CancelledError, Exception):
                    pass
            self._current_chat_task = None

    async def _cancel_active_task(self) -> None:
        """Cancel the current chat asyncio.Task and wait for cleanup."""
        task = self._current_chat_task
        if task is None or task.done():
            self._current_chat_task = None
            return
        log.info("[WORKER] Cancelling active chat task")
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        self._current_chat_task = None
        log.info("[WORKER] Active chat task cancelled")

    async def _handle_chat(self, msg: Dict):
        self.thinking_started.emit()
        try:
            response = await self.bridge._call_llm(
                msg.get("content", ""),
                msg.get("context", {}),
                msg.get("images", []),
            )
            # Only emit if the response wasn't cut short by a stop request
            if response and not self.bridge._stop_requested:
                self.response_ready.emit(response)
        except asyncio.CancelledError:
            # Task was cancelled via asyncio.Task.cancel() from stop_session_task().
            # This is an intentional stop — do NOT emit error_occurred.
            log.info("[WORKER] Chat task cancelled (CancelledError) — stop was requested")
            raise  # Re-raise so asyncio correctly marks the task as cancelled
        except Exception as exc:
            if not self.bridge._stop_requested:
                log.error(f"[WORKER] Chat error: {exc}")
                self.error_occurred.emit(str(exc))
            else:
                log.info(f"[WORKER] Exception during stopped chat (suppressed): {exc}")
        finally:
            self.thinking_stopped.emit()

    def queue_message(self, msg: Dict):
        if self._queue and self._loop:
            asyncio.run_coroutine_threadsafe(self._queue.put(msg), self._loop)

    def stop(self):
        self._stop_req   = True
        self._is_running = False
        self.wait()


# ============================================================
# MAIN BRIDGE CLASS
# ============================================================

class CortexAgentBridge(QObject):
    """
    Bridge between Cortex IDE UI and the agentic core.

    Signals (matching StubAIAgent interface so ai_chat.py works unchanged):
        response_chunk      — streaming text token
        response_complete   — full response text when done
        request_error       — error string
        file_generated      — (filepath, content) when Write tool runs
        file_edited_diff    — (filepath, old, new) when Edit tool runs
        tool_activity       — (tool_name, info, status) real-time card updates
        directory_contents  — (path, entries) when LS runs
        thinking_started / thinking_stopped
        todos_updated       — (todos_list, main_task)
        tool_summary_ready  — dict summary
        user_question_requested — (question, options)
    """

    # ── PyQt signals ───────────────────────────────────────────
    response_chunk          = pyqtSignal(str)
    response_complete       = pyqtSignal(str)
    request_error           = pyqtSignal(str)
    file_generated          = pyqtSignal(str, str)
    file_edited_diff        = pyqtSignal(str, str, str)
    tool_activity           = pyqtSignal(str, str, str)   # name, info, status
    directory_contents      = pyqtSignal(str, str)
    thinking_started        = pyqtSignal()
    thinking_stopped        = pyqtSignal()
    todos_updated           = pyqtSignal(list, str)
    tool_summary_ready      = pyqtSignal(dict)
    user_question_requested = pyqtSignal(str, list)
    # Permission request — emitted before a dangerous bash command runs.
    # JS shows an Accept/Reject card; Python waits via threading.Event.
    permission_requested = pyqtSignal(str, str, str)  # command, warning, files_json
    # File operation cards — show animated cards during create/edit operations
    file_creating_started = pyqtSignal(str)  # file_path
    file_editing_started = pyqtSignal(str)   # file_path
    file_operation_completed = pyqtSignal(str, str, str, str)  # card_id, file_path, content, op_type
    # Recovery signals — context compaction / turn-limit continuation
    agent_status_update = pyqtSignal(str, str)  # type ('compacting'|'retrying'), message
    turn_limit_hit      = pyqtSignal(list)       # list of still-pending todo dicts

    # ── Internal state ──────────────────────────────────────────
    def __init__(self, **kwargs):
        super().__init__()
        self._project_root: Optional[str] = None
        self._active_file:  Optional[str] = None
        self._cursor_pos:   Optional[int] = None
        self._terminal      = None
        self._ui_parent     = None
        self._always_allowed: bool = False
        self._interaction_mode: str = "default"
        self._conversation_history: List[ChatMessage] = []
        self._enhancement_data: Dict = {}
        self._streaming      = None
        self._current_todos:  List = []   # Persisted todo list for TodoWrite
        self._stop_requested: bool = False  # Set to interrupt the streaming loop
        # Persistent memory dir — computed once per project root
        self._memory_dir: Optional[str] = None
        # Permission gate — used by BridgeBashTool to pause until user accepts/rejects
        self._permission_event: 'threading.Event' = None   # lazily created
        self._permission_granted: bool = False
        # Session task registry — converted from AppStateStore.ts tasks map.
        # Tracks the active asyncio.Task for proper cancellation on stop.
        self._task_registry: SessionTaskRegistry = SessionTaskRegistry()

        log.info("[BRIDGE] Initialising Cortex Agent Bridge")

        # Initialise real agent bootstrap state
        self._init_agent_state()

        # Build tool context for real agent tools
        self._tool_ctx = CortexToolContext(self)

        # Instantiate real FileReadTool (needs instance for file-state cache)
        self._real_read_tool = None
        if _REAL_FILE_READ_TOOL is not None:
            try:
                self._real_read_tool = _REAL_FILE_READ_TOOL()
                log.info("[BRIDGE] FileReadTool instance created")
            except Exception as _e:
                log.warning(f"[BRIDGE] Could not instantiate FileReadTool: {_e}")

        # Bridge-native tools (Bash + LS — no real agent equivalents)
        self._bash_tool = BridgeBashTool(self)
        self._ls_tool   = BridgeLSTool(self)

        # Connect to Cortex streaming emitter
        self._connect_streaming()

        # Start background worker
        self._worker = AgentWorker(self)
        self._worker.response_ready.connect(self._on_response_ready)
        self._worker.chunk_ready.connect(self._on_chunk_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.thinking_started.connect(self.thinking_started.emit)
        self._worker.thinking_stopped.connect(self.thinking_stopped.emit)
        self._worker.start()

        log.info("[BRIDGE] Agent bridge ready")
        
        # Pre-warm provider registry at startup to avoid 2s delay on first message
        try:
            from src.ai.providers import get_provider_registry
            get_provider_registry()
            log.info("[BRIDGE] Provider registry pre-warmed")
        except Exception as e:
            log.warning(f"[BRIDGE] Provider pre-warm failed (will lazy-init): {e}")

    # ── Initialisation helpers ─────────────────────────────────

    def _init_agent_state(self):
        """Wire into the real agent bootstrap/state module."""
        try:
            cwd = os.getcwd()
            set_original_cwd(cwd)
            _agent_set_project_root(cwd)
            log.info(
                f"[BRIDGE] Agent state: cwd={cwd}, session={get_session_id()}"
            )
        except Exception as exc:
            log.warning(f"[BRIDGE] Could not set agent state: {exc}")

    def _connect_streaming(self):
        try:
            self._streaming = get_streaming_emitter()
            self._streaming.llm_token.connect(self.response_chunk.emit)
            self._streaming.error.connect(self.request_error.emit)
            log.info("[BRIDGE] Streaming emitter connected")
        except Exception as exc:
            log.warning(f"[BRIDGE] Streaming not available: {exc}")
            self._streaming = None

    # ── System prompt builder ──────────────────────────────────

    def _build_system_prompt(self, context: Dict) -> str:
        project_root = self._project_root or os.getcwd()
        active_file  = self._active_file or ""

        # ── Auto-discover project structure (cached) ──────────
        project_info = self._get_project_summary(project_root)

        # ── File state awareness ──────────────────────────────
        known_files = self._tool_ctx.get_known_files_summary()

        # ── Persistent memory (project-scoped, loaded once per session) ──
        memory_section = ''
        try:
            from src.config.settings import get_settings
            _mem_enabled = get_settings().get('memory', 'enabled', default=True)
        except Exception:
            _mem_enabled = True
        if _mem_enabled:
            memory_dir = self._get_memory_dir()
            self._ensure_memory_dir(memory_dir)
            memory_section = self._load_memory_section(memory_dir)

        prompt = f"""You are Cortex AI Agent, an autonomous coding assistant integrated into Cortex IDE.
You are a world-class software engineer who writes clean, efficient, well-tested code.

## Environment
Project Root: {project_root}
{f'Active File: {active_file}' if active_file else ''}
OS: Windows
Shell: PowerShell (use semicolons ; not &&)

## Project Context
{project_info}

## Files You Know About This Session
{known_files}

{memory_section}

## Tools Available
You MUST call tools to take real action. Never describe what you "would" do — actually do it.

### TodoWrite(todos)
Plan and track multi-step tasks in the UI. **CALL THIS FIRST** — before any other tool — whenever you start a task with 3+ steps. Use it to immediately show your plan in the sidebar. Mark tasks in_progress BEFORE starting them, completed IMMEDIATELY after finishing each one. Provide both content (imperative, e.g. 'Run tests') and activeForm (present continuous, e.g. 'Running tests') for every item.

**IMPORTANT**: Call TodoWrite ONCE to set up your plan, then START WORKING immediately. Do NOT call TodoWrite again until a task status actually changes (e.g. moving a task to in_progress or completed). Never call TodoWrite twice in a row with the same data.

### Read(file_path, offset?, limit?)
Read file contents. Always Read a file BEFORE editing it.
Example: Read(file_path="src/main.py")
Example: Read(file_path="src/main.py", offset=100, limit=50)  # lines 100-149

### Edit(file_path, old_string, new_string)
Surgical text replacement. old_string must match EXACTLY (including whitespace).
ALWAYS Read the file first to get the exact text.
Example: Edit(file_path="src/main.py", old_string="def old():", new_string="def new():")

### Write(file_path, content)
Create a new file or fully overwrite an existing one. Use Edit for partial changes.
Example: Write(file_path="src/new_module.py", content="# New module\n...")

### Bash(command, timeout?)
Execute a shell command. Use for: running code, installing packages, git, tests.
Example: Bash(command="python -m pytest tests/ -v")
Example: Bash(command="pip install requests")

### Glob(pattern, path?)
Find files matching a glob pattern. Great for discovering project structure.
Example: Glob(pattern="**/*.py")
Example: Glob(pattern="**/test_*.py", path="tests/")

### Grep(pattern, path?, glob?, case_insensitive?)
Search file contents with regex. Find definitions, usages, imports.
Example: Grep(pattern="def process_message", glob="*.py")
Example: Grep(pattern="import requests", path="src/")

### LS(path?)
List directory contents. Quick overview of files and folders.
Example: LS(path="src/")

## Strategy Rules
1. TODO FIRST, THEN WORK: For tasks with 3+ steps, call TodoWrite ONCE to show your plan, then immediately start the FIRST task on the next turn. Never call TodoWrite twice in a row.
2. EXPLORE FIRST: Use Glob/Grep/LS/Read to understand before making changes.
3. READ BEFORE EDIT: Always Read the file to get exact text before calling Edit.
4. VERIFY AFTER CHANGES: After editing, re-Read the file or run tests to confirm.
5. BATCH RELATED EDITS: When multiple edits go to the same file, do them sequentially.
6. USE EDIT NOT WRITE: For modifying existing files, prefer Edit over Write.
7. SKIP RE-READING: If you already read a file this session (see 'Files You Know About'),
   you don't need to read it again unless it was modified.
8. CHAIN TOOLS: You can call multiple tools in one turn for independent operations.
9. HANDLE ERRORS: If a tool fails, try an alternative approach rather than giving up.
"""
        if context.get("code_context"):
            prompt += f"\n## User's Selected Code\n```\n{context['code_context']}\n```\n"
        return prompt

    # ── Persistent Memory ───────────────────────────────────

    def _get_memory_dir(self) -> str:
        """
        Return (and cache) the memory directory for the current project.
        Stored under ~/.cortex/projects/<sanitized-project-name>/memory/
        so memories persist between IDE sessions and are scoped per project.
        """
        if self._memory_dir:
            return self._memory_dir
        import hashlib, re as _re
        project = self._project_root or os.getcwd()
        # Sanitize the project path to a safe directory name
        sanitized = _re.sub(r'[<>:"/\\|?*\0]', '_', project).strip('_ ')
        if len(sanitized) > 60:
            h = hashlib.md5(project.encode('utf-8')).hexdigest()[:8]
            sanitized = sanitized[-52:].lstrip('_') + '_' + h
        self._memory_dir = os.path.join(
            os.path.expanduser('~'), '.cortex', 'projects', sanitized, 'memory'
        )
        return self._memory_dir

    def _ensure_memory_dir(self, memory_dir: str) -> None:
        """Create memory directory if it does not exist."""
        try:
            os.makedirs(memory_dir, exist_ok=True)
        except Exception as exc:
            log.warning('[BRIDGE] Could not create memory dir: %s', exc)

    def _load_memory_section(self, memory_dir: str) -> str:
        """
        Build the complete memory prompt section to inject into the system prompt.

        Three layers:
          1. Behavioral instructions (how to save/read memories) + MEMORY.md index
             via buildMemoryPrompt() from memdir package.
          2. Content of recently-modified individual memory files (up to 10).

        Returns the combined string, or empty string if the memory system is
        not available or the directory is empty.
        """
        parts: List[str] = []

        # --- Layer 1: Instructions + MEMORY.md index ---
        try:
            from memdir.memdir import buildMemoryPrompt
            prompt = buildMemoryPrompt({
                'displayName': 'Cortex Memory',
                'memoryDir': memory_dir,
            })
            if prompt:
                parts.append(prompt)
        except Exception as exc:
            log.debug('[BRIDGE] buildMemoryPrompt failed (%s); using fallback', exc)
            # Minimal fallback: instructions + MEMORY.md content
            fallback_lines = [
                '# Cortex Memory',
                '',
                f'You have a persistent, file-based memory system at `{memory_dir}`.',
                'This directory already exists — write to it directly with the Write tool.',
                '',
                '## How to save memories',
                'Save each memory as a separate .md file with frontmatter:',
                '```markdown',
                '---',
                'name: <memory name>',
                'description: <one-line description for relevance matching>',
                'type: <user | feedback | project | reference>',
                '---',
                '',
                '<memory content>',
                '```',
                'Then update MEMORY.md index with a one-line pointer: `- [Title](file.md) — hook`.',
                '',
                '## Memory types',
                '- **user**: user role, goals, preferences, knowledge level',
                '- **feedback**: corrections and confirmed approaches (include Why + How to apply)',
                '- **project**: ongoing work, decisions, deadlines, context not in code',
                '- **reference**: pointers to external systems (dashboards, trackers)',
            ]
            memory_index_path = os.path.join(memory_dir, 'MEMORY.md')
            try:
                with open(memory_index_path, 'r', encoding='utf-8') as fh:
                    index_content = fh.read().strip()
                if index_content:
                    fallback_lines += ['', '## MEMORY.md', '', index_content]
            except FileNotFoundError:
                fallback_lines += [
                    '', '## MEMORY.md',
                    '', 'Your MEMORY.md is currently empty. When you save new memories, they will appear here.',
                ]
            except Exception:
                pass
            parts.append('\n'.join(fallback_lines))

        # --- Layer 2: Recent individual memory files ---
        try:
            from memdir.memoryAge import memoryFreshnessNote
        except Exception:
            def memoryFreshnessNote(mtime_ms):
                return ''

        try:
            mem_files = []
            for dirpath, _dirs, fnames in os.walk(memory_dir):
                for fname in fnames:
                    if fname.endswith('.md') and fname != 'MEMORY.md':
                        fp = os.path.join(dirpath, fname)
                        try:
                            mtime = os.path.getmtime(fp)
                            mem_files.append((mtime, fp))
                        except OSError:
                            pass
            # Sort newest-first; load up to 10
            mem_files.sort(key=lambda x: x[0], reverse=True)
            loaded_files: List[str] = []
            for mtime, fp in mem_files[:10]:
                try:
                    with open(fp, 'r', encoding='utf-8') as fh:
                        content = fh.read().strip()
                    rel = os.path.relpath(fp, memory_dir)
                    freshness = memoryFreshnessNote(mtime * 1000)
                    header = f'### {rel}'
                    if freshness:
                        loaded_files.append(f'{header}\n{freshness}\n{content}')
                    else:
                        loaded_files.append(f'{header}\n{content}')
                except Exception:
                    pass
            if loaded_files:
                parts.append(
                    '## Loaded Memory Files\n\n'
                    + '\n\n---\n\n'.join(loaded_files)
                )
        except Exception as exc:
            log.debug('[BRIDGE] Memory file loading skipped: %s', exc)

        return '\n\n'.join(parts)

    def _get_project_summary(self, project_root: str) -> str:
        """Auto-discover project structure for the system prompt (cached per session)."""
        if hasattr(self, '_cached_project_summary'):
            return self._cached_project_summary
        lines = []
        try:
            # Detect project type from marker files
            markers = {
                'package.json': 'Node.js/JavaScript',
                'requirements.txt': 'Python',
                'Cargo.toml': 'Rust',
                'go.mod': 'Go',
                'pom.xml': 'Java/Maven',
                'build.gradle': 'Java/Gradle',
                '.csproj': 'C#/.NET',
            }
            detected = []
            for marker, lang in markers.items():
                if os.path.exists(os.path.join(project_root, marker)):
                    detected.append(lang)
            if detected:
                lines.append(f"Tech stack: {', '.join(detected)}")

            # Show top-level directory structure
            try:
                entries = sorted(os.scandir(project_root), key=lambda e: (not e.is_dir(), e.name))
                top_level = []
                for e in entries[:20]:
                    if e.name.startswith('.') and e.name not in ('.env', '.gitignore'):
                        continue
                    marker = '/' if e.is_dir() else ''
                    top_level.append(f"  {e.name}{marker}")
                if top_level:
                    lines.append("Top-level structure:")
                    lines.extend(top_level)
            except OSError:
                pass
        except Exception:
            lines.append("(could not auto-detect project info)")
        result = "\n".join(lines) if lines else "(unknown project)"
        self._cached_project_summary = result
        return result

    # ============================================================
    # CONTEXT COMPACTION  (trim history when token limit exceeded)
    # ============================================================

    def _compact_messages(self, messages: list, PCM: type) -> list:
        """
        Trim conversation history so the next API call fits in the context window.

        Strategy
        --------
        • Always keep the system message (index 0).
        • Drop the oldest messages in the middle, keeping the last
          KEEP_TAIL messages so recent context is intact.
        • Walk the tail forward to the first safe boundary (a user or
          assistant turn) so we never orphan a tool-result block.
        • Insert a synthetic user note so the model knows history was pruned.
        """
        KEEP_TAIL = 10
        if len(messages) <= KEEP_TAIL + 2:
            return messages  # nothing meaningful to drop

        system_msg = messages[0]
        rest       = messages[1:]          # everything after the system prompt

        if len(rest) <= KEEP_TAIL:
            return messages

        tail          = rest[-KEEP_TAIL:]
        dropped_count = len(rest) - len(tail)

        # Advance `tail` to the first safe role boundary so we never start
        # mid tool-result block (tool results must follow their assistant turn).
        for i, msg in enumerate(tail):
            if getattr(msg, 'role', None) in ('user', 'assistant'):
                tail = tail[i:]
                break

        summary = PCM(
            role='user',
            content=(
                f'[System note: {dropped_count} earlier messages were removed to stay '
                'within the context window. Continue completing the current task based '
                'on the remaining context and any open todo items.]'
            )
        )
        compacted = [system_msg, summary] + tail
        log.info(
            f'[BRIDGE] Context compacted: {len(messages)} → {len(compacted)} messages '
            f'(dropped {dropped_count} middle messages)'
        )
        return compacted

    # ============================================================
    # MULTI-TURN AGENTIC LOOP  (the core of the bridge)
    # ============================================================

    async def _call_llm(
        self,
        message: str,
        context: Dict = None,
        images: List[str] = None,
    ) -> Optional[str]:
        """
        Multi-turn agentic loop:
          1. Send system prompt + conversation history + user message to LLM.
          2. LLM streams text tokens and/or tool-call deltas.
          3. Execute each tool call; emit tool_activity signals.
          4. Append tool results and loop until LLM gives a plain text answer.
        """
        context = context or {}
        images  = images  or []

        merged = {**self._enhancement_data, **context}

        try:
            from src.ai.providers import get_provider_registry, ProviderType, ChatMessage as PCM

            registry      = get_provider_registry()
            provider_name = merged.get("provider", "deepseek")
            
            # Determine provider type based on model
            model_id = merged.get("model_id", merged.get("model", "deepseek-chat"))
            model_lower = model_id.lower() if model_id else ""
            
            # Models requiring Responses API
            needs_responses = any(x in model_lower for x in ["codex", "gpt-5", "o1", "o3"])
            
            provider_type = (
                ProviderType.MISTRAL if provider_name == "mistral"
                else ProviderType.OPENAI_RESPONSES if needs_responses
                else ProviderType.OPENAI if provider_name == "openai"
                else ProviderType.DEEPSEEK
            )
            provider = registry.get_provider(provider_type)
            model    = model_id

            log.info(f"[BRIDGE] provider={provider_name} model={model}")

            # ── Build initial message list ─────────────────────
            system_prompt = merged.get("system_prompt") or self._build_system_prompt(context)

            messages: List[PCM] = [PCM(role="system", content=system_prompt)]

            # Inject conversation history (last 20 turns)
            for hist_msg in self._conversation_history[-20:]:
                if hist_msg.role in ("user", "assistant"):
                    cm = PCM(role=hist_msg.role, content=hist_msg.content or "")
                    if hist_msg.tool_calls:
                        cm.tool_calls = hist_msg.tool_calls
                    messages.append(cm)
                elif hist_msg.role == "tool":
                    messages.append(
                        PCM(role="tool", content=hist_msg.content or "",
                            tool_call_id=hist_msg.tool_call_id)
                    )

            # Current user turn
            messages.append(PCM(role="user", content=message))

            tool_defs    = _get_tool_definitions()
            full_response = ""
            MAX_TURNS     = 15

            for turn in range(MAX_TURNS):
                log.info(f"[BRIDGE] === Agentic turn {turn + 1}/{MAX_TURNS} ===")

                # ── Stream LLM response (with context-compaction retry) ────
                tool_acc:  Dict[int, Dict] = {}   # idx → {id, name, arguments}
                turn_text  = ""

                # Context-length errors are retried up to 2 times per turn by
                # compacting the message history before each retry.
                _CTX_ERR_KEYWORDS = (
                    'input is too long', 'context_length_exceeded',
                    'context length',    'prompt_too_long',
                    'too many tokens',   'maximum context',
                    'token limit',       'tokens exceed',
                    'request too large', 'content too large',
                )

                # Callback passed to the provider so we get notified before each
                # internal retry (timeout / rate-limit) and can show the user a
                # status note without waiting for the retry to succeed or fail.
                def _retry_notify(attempt_num, max_att, err_type):
                    if err_type == 'timeout':
                        msg = 'API timeout - retrying (%d/%d)...' % (attempt_num, max_att)
                    elif err_type == 'rate_limit':
                        msg = 'Rate limit hit - waiting before retry (%d/%d)...' % (attempt_num, max_att)
                    else:
                        msg = 'API error - retrying (%d/%d)...' % (attempt_num, max_att)
                    log.info('[BRIDGE] Provider retry: %s' % msg)
                    self.agent_status_update.emit('retrying', msg)

                for _compact_attempt in range(3):  # attempt 0, 1, 2
                    tool_acc  = {}
                    turn_text = ""
                    try:
                        for chunk in provider.chat_stream(
                            messages, model=model, max_tokens=8000, tools=tool_defs,
                            retry_callback=_retry_notify
                        ):
                            # Respect a stop request from the user
                            if self._stop_requested:
                                log.info("[BRIDGE] Stream interrupted by stop request")
                                break
                            # Yield to the event loop so stop/cancel signals are delivered
                            # between streaming chunks (chat_stream is a sync generator).
                            await asyncio.sleep(0)
                            if isinstance(chunk, str) and chunk.startswith("__TOOL_CALL_DELTA__:"):
                                delta_list = json.loads(chunk[20:])
                                for td in delta_list:
                                    idx = td.get("index", 0)
                                    if idx not in tool_acc:
                                        tool_acc[idx] = {"id": "", "name": "", "arguments": ""}
                                    if td.get("id"):
                                        tool_acc[idx]["id"] = td["id"]
                                    if td.get("function", {}).get("name"):
                                        tool_acc[idx]["name"] = td["function"]["name"]
                                    if td.get("function", {}).get("arguments"):
                                        tool_acc[idx]["arguments"] += td["function"]["arguments"]
                            else:
                                turn_text    += chunk
                                full_response += chunk
                                self.response_chunk.emit(chunk)
                        break  # stream completed (or stop requested) — exit retry loop

                    except Exception as _stream_exc:
                        _err_lower = str(_stream_exc).lower()
                        _is_ctx_err = any(kw in _err_lower for kw in _CTX_ERR_KEYWORDS)
                        if _is_ctx_err and _compact_attempt < 2:
                            log.warning(
                                f"[BRIDGE] Context limit on turn {turn + 1} "
                                f"(compact attempt {_compact_attempt + 1}/2): {_stream_exc}"
                            )
                            self.agent_status_update.emit(
                                'compacting',
                                'Context window exceeded - compacting history (%d/2), retrying...' % (_compact_attempt + 1)
                            )
                            messages = self._compact_messages(messages, PCM)
                            continue   # retry with compacted history
                        else:
                            raise      # non-context error or exhausted retries

                # If stop was requested, abort the entire agentic loop immediately
                if self._stop_requested:
                    log.info("[BRIDGE] Agentic loop aborted by stop request")
                    break

                # Assemble pending tool calls
                pending = []
                for idx in sorted(tool_acc):
                    tc = tool_acc[idx]
                    if tc["name"]:
                        pending.append({
                            "index": idx,
                            "id":    tc["id"] or str(_uuid.uuid4()),
                            "function": {
                                "name":      tc["name"],
                                "arguments": tc["arguments"],
                            },
                        })

                # If no tool calls → final answer
                if not pending:
                    log.info(f"[BRIDGE] No tool calls on turn {turn + 1} — done")
                    break

                log.info(
                    f"[BRIDGE] {len(pending)} tool call(s) on turn {turn + 1}: "
                    + ", ".join(p["function"]["name"] for p in pending)
                )

                # ── Append assistant turn with tool_calls ──────
                assistant_tool_calls = [
                    {
                        "id":   tc["id"],
                        "type": "function",
                        "function": {
                            "name":      tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in pending
                ]
                messages.append(
                    PCM(
                        role="assistant",
                        content=turn_text or "",
                        tool_calls=assistant_tool_calls,
                    )
                )

                # ── Execute tools, append results ──────────────
                # Separate independent and dependent tool calls for parallel execution
                parsed_calls = []
                for tc in pending:
                    tool_name = tc["function"]["name"]
                    tool_id   = tc["id"]
                    try:
                        raw_args = tc["function"]["arguments"]
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = {}
                    parsed_calls.append((tool_name, tool_id, args))

                # Classify: read-only tools can run in parallel, mutating tools run sequentially
                _READ_ONLY_TOOLS = {"Read", "Glob", "Grep", "LS"}

                # Group into batches: consecutive read-only tools form a parallel batch,
                # each mutating tool is its own sequential batch.
                batches: list = []  # Each batch is list of (tool_name, tool_id, args)
                current_parallel: list = []
                for call in parsed_calls:
                    if call[0] in _READ_ONLY_TOOLS:
                        current_parallel.append(call)
                    else:
                        # Flush any pending parallel batch
                        if current_parallel:
                            batches.append(current_parallel)
                            current_parallel = []
                        batches.append([call])  # Mutating tool alone
                if current_parallel:
                    batches.append(current_parallel)

                for batch in batches:
                    # Check stop before each tool batch — fast exit if cancelled
                    if self._stop_requested:
                        log.info("[BRIDGE] Tool batch skipped — stop requested")
                        break
                    if len(batch) == 1:
                        # Single tool — run directly
                        t_name, t_id, t_args = batch[0]
                        await self._execute_single_tool(t_name, t_id, t_args, messages, PCM)
                    else:
                        # Parallel batch — run all concurrently
                        log.info(f"[BRIDGE] Running {len(batch)} tools in parallel: "
                                 + ", ".join(b[0] for b in batch))
                        tasks = [
                            self._execute_single_tool(t_name, t_id, t_args, messages, PCM)
                            for t_name, t_id, t_args in batch
                        ]
                        await asyncio.gather(*tasks)
                    # Check stop after each tool batch too
                    if self._stop_requested:
                        log.info("[BRIDGE] Aborting remaining tool batches — stop requested")
                        break

                log.info(f"[BRIDGE] Tool results sent — continuing to turn {turn + 2}")
                # Emit a paragraph break before the next turn's text so the UI
                # doesn't run the continuation sentence directly onto the previous
                # turn's last word (e.g. "fix this.Now let me check...").
                self.response_chunk.emit("\n\n")

            # ── Pending-todo continuation check ───────────────────────
            # If the turn loop ended (naturally or at MAX_TURNS) with todos still
            # in PENDING or IN_PROGRESS state, emit a signal so the UI can offer
            # the user a "Continue" button to resume the task.
            if not self._stop_requested:
                _pending_todos = [
                    t for t in self._current_todos
                    if str(t.get('status', '')).upper() in ('PENDING', 'IN_PROGRESS')
                ]
                if _pending_todos:
                    log.info(
                        f'[BRIDGE] {len(_pending_todos)} todos still pending after '
                        f'turn loop — emitting turn_limit_hit'
                    )
                    self.turn_limit_hit.emit(_pending_todos)

            return full_response

        except Exception as exc:
            log.error(f"[BRIDGE] _call_llm failed: {exc}", exc_info=True)
            raise  # Let _handle_chat route this through error_occurred → onError in JS

    async def _execute_single_tool(
        self, tool_name: str, tool_id: str, args: Dict,
        messages: list, PCM: type,
    ):
        """Execute one tool call: emit running → dispatch → emit result → append to messages."""
        activity = _TOOL_TO_ACTIVITY_NAME.get(tool_name, tool_name.lower())

        # For Write tool, detect create vs update for proper UI card
        if tool_name == "Write":
            fpath = args.get("file_path", "")
            if not os.path.isabs(fpath) and self._project_root:
                fpath = os.path.join(self._project_root, fpath)
            activity = "create_file" if not os.path.exists(fpath) else "write_file"

        # TodoWrite is a silent background tool — no tool-activity card in UI
        _silent = (tool_name == "TodoWrite")
        if not _silent:
            self.tool_activity.emit(activity, json.dumps(args)[:500], "running")

        result = await self._dispatch_tool(tool_name, tool_id, args)

        if result.success:
            result_str = (
                json.dumps(result.result)
                if isinstance(result.result, (dict, list))
                else str(result.result)
            )
            # Bash tool: use larger truncation so output shows in UI card
            ui_limit = 2000 if tool_name == "Bash" else 500
            if not _silent:
                self.tool_activity.emit(activity, result_str[:ui_limit], "complete")
        else:
            result_str = f"Error: {result.error}"
            if not _silent:
                self.tool_activity.emit(activity, result_str[:500], "error")

        # Feed result back to LLM
        messages.append(
            PCM(role="tool", content=result_str, tool_call_id=tool_id)
        )

    # ── Tool dispatch ──────────────────────────────────────────

    async def _dispatch_tool(
        self, tool_name: str, tool_id: str, args: Dict
    ) -> ToolResult:
        """
        Dispatch a tool call to the real agent tool or bridge-native fallback.

        Real tools (from src/agent/src/tools/):
            Read  → FileReadTool.call()
            Write → FileWriteTool.call()
            Edit  → FileEditTool.call()
            Glob  → GlobTool.call()
            Grep  → GrepTool.call()

        Bridge-native (no real implementation exists):
            Bash  → BridgeBashTool.execute()
            LS    → BridgeLSTool.execute()
        """
        try:
            # ---- Real Agent Tools ----
            if tool_name == "Read":
                return await self._dispatch_read(tool_id, args)
            elif tool_name == "Write":
                return await self._dispatch_write(tool_id, args)
            elif tool_name == "Edit":
                return await self._dispatch_edit(tool_id, args)
            elif tool_name == "Glob":
                return await self._dispatch_glob(tool_id, args)
            elif tool_name == "Grep":
                return await self._dispatch_grep(tool_id, args)
            # ---- Bridge-native ----
            elif tool_name == "Bash":
                result = await self._bash_tool.execute(args)
                result.tool_id = tool_id
                return result
            elif tool_name == "LS":
                result = await self._ls_tool.execute(args)
                result.tool_id = tool_id
                return result
            elif tool_name == "TodoWrite":
                return await self._dispatch_todo_write(tool_id, args)
            else:
                return ToolResult(tool_id=tool_id, result=None, success=False,
                                  error=f"Unknown tool: {tool_name!r}")
        except Exception as exc:
            log.error(f"[BRIDGE] Tool {tool_name!r} raised: {exc}")
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(exc))

    # ---- Real tool dispatchers ----------------------------------------

    async def _dispatch_read(self, tool_id: str, args: Dict) -> ToolResult:
        """Dispatch to real FileReadTool or bridge-native fallback."""
        path = args.get("file_path", "")
        if not os.path.isabs(path) and self._project_root:
            args = {**args, "file_path": os.path.join(self._project_root, path)}

        if self._real_read_tool is not None:
            try:
                raw = await self._real_read_tool.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                data = raw.get("data")
                # Extract text content for LLM from the FileReadOutput
                if hasattr(data, "file") and hasattr(data.file, "content"):
                    content = data.file.content
                elif isinstance(data, dict) and "content" in data:
                    content = data["content"]
                else:
                    content = str(data)
                # Track file state
                self._tool_ctx.mark_file_read(args["file_path"])
                return ToolResult(tool_id=tool_id, result={"path": args["file_path"], "content": content})
            except Exception as exc:
                log.warning(f"[BRIDGE] Real FileReadTool failed, using fallback: {exc}")

        # Fallback: simple file read
        fpath = args.get("file_path", "")
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            offset = max(1, int(args.get("offset", 1))) - 1
            limit = int(args.get("limit", len(lines)))
            content = "".join(lines[offset: offset + limit])
            self._tool_ctx.mark_file_read(fpath)
            return ToolResult(tool_id=tool_id, result={"path": fpath, "content": content})
        except Exception as e:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(e))

    async def _dispatch_write(self, tool_id: str, args: Dict) -> ToolResult:
        """Dispatch to real FileWriteTool or bridge-native fallback."""
        path = args.get("file_path", "")
        content = args.get("content", "")
        if not os.path.isabs(path) and self._project_root:
            args = {**args, "file_path": os.path.join(self._project_root, path)}
        full_path = args["file_path"]
        is_new = not os.path.exists(full_path)

        # Emit signal to show "Creating file..." card with animation
        card_id = None
        try:
            import uuid
            card_id = f"file-op-{uuid.uuid4().hex[:8]}"
            self.file_creating_started.emit(full_path)
        except Exception as e:
            log.debug(f"[BRIDGE] Failed to emit file_creating_started: {e}")

        if _REAL_FILE_WRITE_TOOL is not None:
            try:
                raw = await _REAL_FILE_WRITE_TOOL.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                data = raw.get("data", {})
                op_type = data.get("type", "create" if is_new else "update")
                # Emit UI signals
                self.file_generated.emit(full_path, content)
                # Emit completion signal for card animation
                if card_id:
                    self.file_operation_completed.emit(card_id, full_path, content, "create")
                self._tool_ctx.mark_file_modified(full_path)
                return ToolResult(tool_id=tool_id, result={
                    "path": full_path, "type": op_type, "written": True,
                })
            except Exception as exc:
                log.warning(f"[BRIDGE] Real FileWriteTool failed, using fallback: {exc}")

        # Fallback: simple write
        try:
            parent = os.path.dirname(full_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.file_generated.emit(full_path, content)
            # Emit completion signal for card animation
            if card_id:
                self.file_operation_completed.emit(card_id, full_path, content, "create")
            self._tool_ctx.mark_file_modified(full_path)
            return ToolResult(tool_id=tool_id, result={
                "path": full_path, "type": "create" if is_new else "update", "written": True,
            })
        except Exception as e:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(e))

    async def _dispatch_edit(self, tool_id: str, args: Dict) -> ToolResult:
        """Dispatch to real FileEditTool or bridge-native fallback."""
        path = args.get("file_path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not os.path.isabs(path) and self._project_root:
            args = {**args, "file_path": os.path.join(self._project_root, path)}
        full_path = args["file_path"]

        # Register CortexDiffBridge open-diff callback (idempotent — safe to call each time)
        if _CORTEX_DIFF_BRIDGE is not None and not _CORTEX_DIFF_BRIDGE.is_registered:
            _CORTEX_DIFF_BRIDGE.register_open_diff(
                lambda fp, old, new: self.file_edited_diff.emit(fp, old, new)
            )
            log.info("[BRIDGE] CortexDiffBridge open_diff callback registered")

        # Emit signal to show "Editing file..." card with animation
        card_id = None
        original_content = None
        try:
            import uuid
            card_id = f"file-op-{uuid.uuid4().hex[:8]}"
            # Read original content for later comparison
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    original_content = f.read()
            except Exception:
                pass
            self.file_editing_started.emit(full_path)
        except Exception as e:
            log.debug(f"[BRIDGE] Failed to emit file_editing_started: {e}")

        if _REAL_FILE_EDIT_TOOL is not None:
            try:
                raw = await _REAL_FILE_EDIT_TOOL.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                data = raw.get("data", {})
                actual_old = data.get("oldString", old_string)
                actual_new = data.get("newString", new_string)
                # Compute full file content for diff/cache: original → new
                full_new = original_content.replace(actual_old, actual_new, 1) if original_content else actual_new
                self.file_edited_diff.emit(full_path, original_content or actual_old, full_new)
                # Emit completion signal for card animation
                if card_id:
                    self.file_operation_completed.emit(card_id, full_path, full_new, "edit")
                self._tool_ctx.mark_file_modified(full_path)
                await self._refresh_git_diff_stats(full_path)
                return ToolResult(tool_id=tool_id, result={
                    "path": full_path, "edited": True,
                })
            except Exception as exc:
                log.warning(f"[BRIDGE] Real FileEditTool failed, using fallback: {exc}")

        # Fallback: simple string replace
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                file_content = f.read()
            if old_string not in file_content:
                return ToolResult(tool_id=tool_id, result=None, success=False,
                                  error=f"old_string not found in {full_path}")
            new_content = file_content.replace(old_string, new_string, 1)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            self.file_edited_diff.emit(full_path, file_content, new_content)
            # Emit completion signal for card animation
            if card_id:
                self.file_operation_completed.emit(card_id, full_path, new_content, "edit")
            self._tool_ctx.mark_file_modified(full_path)
            await self._refresh_git_diff_stats(full_path)
            return ToolResult(tool_id=tool_id, result={"path": full_path, "edited": True})
        except Exception as e:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(e))

    async def _refresh_git_diff_stats(self, file_path: str) -> None:
        """
        After a file edit, re-fetch git diff stats via DiffDataService.
        Emits an updated file_edited_diff signal with accurate git-based
        +added/-removed counts appended to the result (used by sidebar panel).
        """
        if _DIFF_SERVICE is None:
            return
        try:
            diff_data = await _DIFF_SERVICE.fetch_diff_data()
            norm = os.path.normpath(file_path)
            # Find this file in the git diff results (match by basename or full path)
            for git_path, file_diff in vars(diff_data).get('files', []) or []:
                pass  # diff_data.files is a list of DiffFile objects
            for diff_file in (diff_data.files or []):
                git_norm = os.path.normpath(diff_file.path)
                if git_norm == norm or os.path.basename(git_norm) == os.path.basename(norm):
                    log.info(
                        f"[BRIDGE] Git diff stats for {diff_file.path}: "
                        f"+{diff_file.lines_added} -{diff_file.lines_removed}"
                        f"{' [binary]' if diff_file.is_binary else ''}"
                        f"{' [large]' if diff_file.is_large_file else ''}"
                    )
                    break
        except Exception as exc:
            log.debug(f"[BRIDGE] _refresh_git_diff_stats failed: {exc}")

    async def _dispatch_glob(self, tool_id: str, args: Dict) -> ToolResult:
        """Dispatch to real GlobTool or bridge-native fallback."""
        if _REAL_GLOB_TOOL is not None:
            try:
                raw = await _REAL_GLOB_TOOL.call(args, self._tool_ctx)
                data = raw.get("data", {})
                filenames = data.get("filenames", [])
                return ToolResult(tool_id=tool_id, result={
                    "pattern": args.get("pattern", ""),
                    "files": filenames,
                    "numFiles": data.get("numFiles", len(filenames)),
                    "truncated": data.get("truncated", False),
                })
            except Exception as exc:
                log.warning(f"[BRIDGE] Real GlobTool failed, using fallback: {exc}")

        # Fallback: simple glob
        import glob as _glob
        pattern = args.get("pattern", "")
        search_dir = args.get("path", self._project_root or os.getcwd())
        full_pattern = os.path.join(search_dir, pattern) if not os.path.isabs(pattern) else pattern
        try:
            files = sorted(_glob.glob(full_pattern, recursive=True))
            return ToolResult(tool_id=tool_id, result={"pattern": pattern, "files": files})
        except Exception as e:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(e))

    async def _dispatch_grep(self, tool_id: str, args: Dict) -> ToolResult:
        """Dispatch to real GrepTool or bridge-native fallback."""
        if _REAL_GREP_TOOL is not None:
            try:
                raw = await _REAL_GREP_TOOL.call(args, self._tool_ctx)
                data = raw.get("data", {})
                # Use map_tool_result_to_block for LLM-friendly output
                if hasattr(_REAL_GREP_TOOL, "map_tool_result_to_block"):
                    block = _REAL_GREP_TOOL.map_tool_result_to_block(data, tool_id)
                    return ToolResult(tool_id=tool_id, result={
                        "pattern": args.get("pattern", ""),
                        "matches": block.get("content", str(data)),
                    })
                return ToolResult(tool_id=tool_id, result=data)
            except Exception as exc:
                log.warning(f"[BRIDGE] Real GrepTool failed, using fallback: {exc}")

        # Fallback: simple ripgrep/grep
        import subprocess as _sp
        pattern = args.get("pattern", "")
        search_path = args.get("path", self._project_root or os.getcwd())
        include = args.get("glob", args.get("include", ""))
        try:
            cmd = ["rg", "-n", "--no-heading", pattern, search_path]
            if include:
                cmd.extend(["-g", include])
            r = _sp.run(cmd, capture_output=True, text=True)
            if r.returncode not in (0, 1):
                raise FileNotFoundError("rg not found")
            output = r.stdout
        except (FileNotFoundError, OSError):
            cmd2 = ["grep", "-rn", pattern, search_path]
            if include:
                cmd2.extend(["--include", include])
            r2 = _sp.run(cmd2, capture_output=True, text=True)
            output = r2.stdout
        return ToolResult(tool_id=tool_id, result={
            "pattern": pattern, "matches": output or "(no matches)",
        })

    async def _dispatch_todo_write(self, tool_id: str, args: Dict) -> ToolResult:
        """
        Handle the TodoWrite agent tool.

        Stores the current todo list on the bridge and emits `todos_updated`
        so the UI panel refreshes in real time.
        """
        todos = args.get("todos", [])

        # If every item is completed/cancelled, treat the list as cleared
        all_done = bool(todos) and all(
            t.get("status") in ("completed", "cancelled") for t in todos
        )

        old_todos = list(self._current_todos)
        new_todos = todos  # keep full list so UI shows completed state briefly

        self._current_todos = [] if all_done else list(new_todos)

        # Emit to update_todos() in ai_chat.py → window.updateTodos() in JS
        self.todos_updated.emit(new_todos, "")

        log.info(f"[TODO] TodoWrite dispatched: {len(new_todos)} items, all_done={all_done}")

        return ToolResult(tool_id=tool_id, result={
            "oldTodos": old_todos,
            "newTodos": new_todos,
            "allDone":  all_done,
        })

    # ── Worker signal handlers ─────────────────────────────────

    def _on_response_ready(self, response: str):
        self.response_complete.emit(response)
        if self._streaming:
            try:
                self._streaming.emit_llm_complete(response)
            except Exception:
                pass
        # Save assistant turn to history
        self._conversation_history.append(
            ChatMessage(role="assistant", content=response)
        )

    def _on_chunk_ready(self, chunk: str):
        self.response_chunk.emit(chunk)

    def _on_error(self, error: str):
        self.request_error.emit(error)

    # ============================================================
    # PUBLIC INTERFACE (matching StubAIAgent so ai_chat.py works)
    # ============================================================

    def process_message(self, message: str, images: List[str] = None):
        """Entry point: called by ai_chat.py when the user sends a message."""
        self._stop_requested = False  # Clear any previous stop before handling new request
        # Fresh AbortController so tools from the previous (aborted) request can't
        # accidentally cancel this new one.
        self._tool_ctx.abort_controller = _create_abort_controller()

        # Generate a unique task ID for this request.
        # Converted from LocalMainSessionTask.ts generateMainSessionTaskId().
        task_id = generate_session_task_id()
        log.info(f"[BRIDGE] process_message task_id={task_id}: {message[:80]}...")

        # Register the task in the registry.  The asyncio.Task is set later
        # by the worker thread (after asyncio.create_task in _process_queue).
        self._task_registry.register(
            SessionTaskState(
                task_id=task_id,
                description=message[:100],
                abort_controller=self._tool_ctx.abort_controller,
            )
        )

        # Save user turn to history
        self._conversation_history.append(
            ChatMessage(role="user", content=message, images=images or [])
        )

        self._worker.queue_message({
            "type":    "chat",
            "content": message,
            "images":  images or [],
            "context": {
                **self._enhancement_data,
                "active_file": self._active_file,
                "cursor_pos":  self._cursor_pos,
            },
            "task_id": task_id,   # Passed to worker so it can link asyncio.Task
        })

    def stop_generation(self):
        log.info("[BRIDGE] stop_generation")
        self._stop_requested = True          # Interrupt the streaming loop immediately

        # If a permission gate is open, deny it automatically on stop
        if self._permission_event is not None and not self._permission_event.is_set():
            self._permission_granted = False
            self._permission_event.set()

        # Use stop_session_task() to cancel the asyncio.Task via task.cancel().
        # Converted from stopTask.ts stopTask() → taskImpl.kill().
        # CancelledError propagates through ALL awaits in the call chain,
        # including mid-tool-execution — no polling required.
        active = self._task_registry.get_active()
        if active:
            try:
                stop_session_task(active.task_id, self._task_registry)
            except StopTaskError as exc:
                log.info(f"[BRIDGE] StopTaskError (expected if task not started): {exc}")

        # Also queue a stop message so the worker's inner asyncio.wait loop
        # (Phase 3 of _process_queue) wakes up and processes the cancellation.
        self._worker.queue_message({"type": "stop"})

    def on_permission_respond(self, decision: str):
        """Called when user clicks Accept or Reject on a permission card.
        decision: 'accept' or 'reject'
        """
        import threading as _threading
        log.info(f"[BRIDGE] Permission response: {decision}")
        self._permission_granted = (decision == 'accept')
        if self._permission_event is not None:
            # _permission_event may have been created in the async worker thread.
            # threading.Event.set() is always thread-safe.
            self._permission_event.set()

    def set_project_root(self, path: str):
        self._project_root = path
        self._memory_dir   = None  # reset so _get_memory_dir() recomputes for new project
        log.info(f"[BRIDGE] project root → {path}")
        try:
            _agent_set_project_root(path)
        except Exception:
            pass

    def set_project_context(self, context):
        if hasattr(context, "to_dict"):
            self._enhancement_data.update(context.to_dict())
        elif hasattr(context, "__dict__"):
            self._enhancement_data.update(
                {k: v for k, v in vars(context).items() if not k.startswith("_")}
            )
        elif isinstance(context, dict):
            self._enhancement_data.update(context)

    def update_settings(self, **kwargs):
        self._enhancement_data.update(kwargs)

    def set_terminal(self, terminal):
        self._terminal = terminal

    def set_active_file(self, filepath: str, cursor_pos: int = None):
        self._active_file = filepath
        self._cursor_pos  = cursor_pos

    def clear_active_file(self):
        self._active_file = None
        self._cursor_pos  = None

    def set_always_allowed(self, allowed: bool):
        self._always_allowed = allowed

    def set_interaction_mode(self, mode: str):
        self._interaction_mode = mode

    def set_ui_parent(self, parent):
        self._ui_parent = parent

    def user_responded(self, answer: str):
        log.info(f"[BRIDGE] user_responded: {answer}")

    def chat(self, message: str, context: str = ""):
        self.process_message(message)

    def chat_with_enhancement(
        self,
        message: str,
        intent: str = None,
        route: str = None,
        tools: List[str] = None,
        code_context: str = "",
    ):
        self._enhancement_data.update(
            {"intent": intent, "route": route, "tools": tools, "code_context": code_context}
        )
        self.process_message(message)

    def chat_with_testing(self, *args, **kwargs):
        self.process_message(args[0] if args else "")

    def generate_chat_title(self, message: str, conv_id: str) -> str:
        words = message.split()[:6]
        title = " ".join(words)
        if len(message.split()) > 6:
            title += "…"
        return title

    def get_last_enhancement_data(self) -> Dict:
        return self._enhancement_data.copy()

    def stop(self):
        self.stop_generation()

    def cleanup(self):
        log.info("[BRIDGE] cleanup")
        self._worker.stop()

    def clear_conversation(self):
        """Clear the in-memory conversation history."""
        self._conversation_history.clear()


# ============================================================
# FACTORY
# ============================================================

def get_agent_bridge(**kwargs) -> CortexAgentBridge:
    """Factory function — returns a ready CortexAgentBridge instance."""
    return CortexAgentBridge(**kwargs)


__all__ = [
    "CortexAgentBridge",
    "get_agent_bridge",
    "ChatMessage",
    "ToolCall",
    "ToolResult",
]
