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


class _AbortController:
    signal = None


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
        self.abort_controller = _AbortController()
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
        command = args.get("command", "")
        timeout = int(args.get("timeout", 30))
        cwd = self._bridge._project_root or os.getcwd()
        try:
            proc = _sp.run(
                command, shell=True,
                capture_output=True, text=True,
                cwd=cwd, timeout=timeout,
            )
            output = proc.stdout
            if proc.stderr:
                output += f"\n[stderr]\n{proc.stderr}"
            return ToolResult(
                tool_id="",
                result={
                    "command": command,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "returncode": proc.returncode,
                    "output": output or "(no output)",
                },
            )
        except _sp.TimeoutExpired:
            return ToolResult(tool_id="", result=None, success=False,
                              error=f"Command timed out after {timeout}s")
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
    "Read":  "read_file",
    "Write": "write_file",
    "Edit":  "edit_file",
    "Bash":  "run_command",
    "Glob":  "list_directory",
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
        self._queue = asyncio.Queue()
        while self._is_running and not self._stop_req:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                await self._dispatch(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                log.error(f"[WORKER] Queue error: {exc}")
                self.error_occurred.emit(str(exc))

    async def _dispatch(self, msg: Dict):
        if msg.get("type") == "chat":
            await self._handle_chat(msg)
        elif msg.get("type") == "stop":
            self._stop_req = True

    async def _handle_chat(self, msg: Dict):
        self.thinking_started.emit()
        try:
            response = await self.bridge._call_llm(
                msg.get("content", ""),
                msg.get("context", {}),
                msg.get("images", []),
            )
            if response:
                self.response_ready.emit(response)
        except Exception as exc:
            log.error(f"[WORKER] Chat error: {exc}")
            self.error_occurred.emit(str(exc))
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
        self._streaming     = None

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

## Tools Available
You MUST call tools to take real action. Never describe what you "would" do — actually do it.

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
1. EXPLORE FIRST: Use Glob/Grep/LS/Read to understand before making changes.
2. READ BEFORE EDIT: Always Read the file to get exact text before calling Edit.
3. VERIFY AFTER CHANGES: After editing, re-Read the file or run tests to confirm.
4. BATCH RELATED EDITS: When multiple edits go to the same file, do them sequentially.
5. USE EDIT NOT WRITE: For modifying existing files, prefer Edit over Write.
6. SKIP RE-READING: If you already read a file this session (see 'Files You Know About'),
   you don't need to read it again unless it was modified.
7. CHAIN TOOLS: You can call multiple tools in one turn for independent operations.
8. HANDLE ERRORS: If a tool fails, try an alternative approach rather than giving up.
"""
        if context.get("code_context"):
            prompt += f"\n## User's Selected Code\n```\n{context['code_context']}\n```\n"
        return prompt

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
            provider_type = (
                ProviderType.MISTRAL if provider_name == "mistral"
                else ProviderType.DEEPSEEK
            )
            provider = registry.get_provider(provider_type)
            model    = merged.get("model_id", merged.get("model", "deepseek-chat"))

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

                # ── Stream LLM response ────────────────────────
                tool_acc: Dict[int, Dict] = {}   # idx → {id, name, arguments}
                turn_text = ""

                for chunk in provider.chat_stream(
                    messages, model=model, max_tokens=8000, tools=tool_defs
                ):
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

                log.info(f"[BRIDGE] Tool results sent — continuing to turn {turn + 2}")

            return full_response

        except Exception as exc:
            log.error(f"[BRIDGE] _call_llm failed: {exc}", exc_info=True)
            return f"Error: {exc}"

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
            self.tool_activity.emit(activity, result_str[:ui_limit], "complete")
        else:
            result_str = f"Error: {result.error}"
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

        if _REAL_FILE_WRITE_TOOL is not None:
            try:
                raw = await _REAL_FILE_WRITE_TOOL.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                data = raw.get("data", {})
                op_type = data.get("type", "create" if is_new else "update")
                # Emit UI signals
                self.file_generated.emit(full_path, content)
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

        if _REAL_FILE_EDIT_TOOL is not None:
            try:
                raw = await _REAL_FILE_EDIT_TOOL.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                data = raw.get("data", {})
                actual_old = data.get("oldString", old_string)
                actual_new = data.get("newString", new_string)
                self.file_edited_diff.emit(full_path, actual_old, actual_new)
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
            self.file_edited_diff.emit(full_path, old_string, new_string)
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
        log.info(f"[BRIDGE] process_message: {message[:80]}...")

        # Save user turn to history
        self._conversation_history.append(
            ChatMessage(role="user", content=message, images=images or [])
        )

        self._worker.queue_message({
            "type":    "chat",
            "content": message,
            "images":  images or [],
            "context": {
                "active_file": self._active_file,
                "cursor_pos":  self._cursor_pos,
            },
        })

    def stop_generation(self):
        log.info("[BRIDGE] stop_generation")
        self._worker.queue_message({"type": "stop"})

    def set_project_root(self, path: str):
        self._project_root = path
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
