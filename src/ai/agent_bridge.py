import asyncio
import os
import sys
import json
import re
import time
import uuid as _uuid
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Callable, Tuple, Type, Set, Protocol, cast
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal, QThread

# ============================================================
# SETUP PATH — expose real agent core as importable package
# ============================================================
_AGENT_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'agent', 'src')
)
_PROJECT_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_SRC not in sys.path:
    sys.path.insert(0, _PROJECT_SRC)
# Keep agent internals importable, but do not prepend to avoid shadowing stdlib
# modules (e.g. src/agent/src/types.py vs Python's built-in types module).
if _AGENT_SRC not in sys.path:
    sys.path.append(_AGENT_SRC)

from src.utils.logger import get_logger  
from src.ai.streaming import get_streaming_emitter  
from src.ai.session_task import (  
    SessionTaskRegistry,
    SessionTaskState,
    StopTaskError,
    generate_session_task_id,
    stop_session_task,
)
from src.ai.model_limits import ModelLimits
import urllib.error
import urllib.request

log = get_logger("agent_bridge")

DEFAULT_READ_CHUNK_LINES_ENV = "CORTEX_READ_DEFAULT_CHUNK_LINES"
DEFAULT_READ_CHUNK_LINES_FALLBACK = 200


def _get_default_read_chunk_lines() -> int:
    """Return safe default chunk size for unbounded Read calls."""
    raw = os.environ.get(DEFAULT_READ_CHUNK_LINES_ENV)
    if raw:
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            pass
    return DEFAULT_READ_CHUNK_LINES_FALLBACK


# ============================================================
# IMPORT REAL AGENT STATE (bootstrap/state.py)
# ============================================================
_has_agent_state = False  # Internal flag (lowercase to avoid constant redefinition warning)
try:
    from agent.src.bootstrap.state import ( 
        set_original_cwd,  
        set_project_root as _agent_set_project_root,  
        getSessionId as _get_session_id,
        get_project_root as _agent_get_project_root,
    )
    _has_agent_state = True
    log.info("[BRIDGE] Real agent bootstrap/state loaded")
except ImportError as _e:
    log.warning(f"[BRIDGE] agent bootstrap/state not available: {_e}")

    def set_original_cwd(cwd: str) -> None: pass
    def _agent_set_project_root(path: str) -> None: pass
    def _get_session_id() -> str: return "default"
    def _agent_get_project_root() -> str: return os.getcwd()

# Public wrapper functions
def get_session_id() -> str:
    """Get current session ID."""
    return _get_session_id()

def get_project_root() -> str:
    """Get project root directory."""
    return _agent_get_project_root()

# Backwards compatibility alias
_HAS_AGENT_STATE = _has_agent_state


# ============================================================
# LOCAL DATA CLASSES
# ============================================================

@dataclass
class ChatMessage:
    """Internal chat message used by the bridge."""
    role: str                           # system / user / assistant / tool
    content: str
    images: Optional[List[str]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    reasoning_content: Optional[str] = None
    
    def __post_init__(self):
        if self.images is None:
            self.images = []


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


WorkerMessage = Dict[str, Any]
ParsedToolCall = Tuple[str, str, Any]


class _ToolLimitsLike(Protocol):
    max_tool_result_chars: int


# ============================================================
# EXTRACTED UTILITIES (Phase B refactor)
# ============================================================
from src.ai.circuit_breaker import ToolCircuitBreaker
from src.ai.tool_executor import ToolExecutionEngine
from src.core.task_graph import TaskGraph, TaskNode, TaskStatus


# ============================================================
# IMPORT REAL AGENT TOOLS from src/agent/src/tools/
# These are the robust, production-quality implementations.
# ============================================================

import importlib as _importlib
import importlib.util as _importlib_util

def _load_agent_tool(module_path: str, class_name: str) -> Optional[type]:
    """Dynamically import a real agent tool class. Returns None on failure."""
    try:
        mod = _importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        log.info(f"[BRIDGE] Real {class_name} loaded")
        return cls
    except Exception as exc:
        log.warning(f"[BRIDGE] {class_name} not available: {exc}")
        return None

_REAL_FILE_READ_TOOL  = _load_agent_tool("agent.src.tools.FileReadTool.FileReadTool",  "FileReadTool")
_REAL_FILE_EDIT_TOOL  = _load_agent_tool("agent.src.tools.FileEditTool.FileEditTool",  "FileEditTool")
_REAL_FILE_WRITE_TOOL = _load_agent_tool("agent.src.tools.FileWriteTool.FileWriteTool", "FileWriteTool")
_REAL_GLOB_TOOL       = _load_agent_tool("agent.src.tools.GlobTool.GlobTool",          "GlobTool")
_REAL_GREP_TOOL       = _load_agent_tool("agent.src.tools.GrepTool.GrepTool",          "GrepTool")


# ============================================================
# IMPORT REAL AbortController from src/agent/src/utils
# Used to signal running tools when the user presses Stop.
# ============================================================
_has_real_abort = False  # Internal flag (lowercase to avoid constant redefinition warning)

# Define fallback implementation first
class _FallbackAbortController:
    """Fallback stub AbortController."""
    def __init__(self) -> None:
        class _Signal:
            aborted: bool = False
            reason: Optional[str] = None
        self.signal: _Signal = _Signal()
    
    def abort(self, reason: str = "AbortError") -> None:
        self.signal.aborted = True
        self.signal.reason = reason


def _fallback_create_abort_controller(max_listeners: int = 50) -> _FallbackAbortController:
    """Fallback stub create_abort_controller."""
    return _FallbackAbortController()


try:
    from agent.src.utils.abortController import ( 
        AbortController as _RealAbortController, 
        create_abort_controller as _real_create_abort_controller,
    )
    _has_real_abort = True
    log.info("[BRIDGE] Real AbortController loaded from utils.abortController")
    
    # Use real implementations
    AbortController = _RealAbortController
    create_abort_controller = _real_create_abort_controller
except ImportError as _e:
    log.warning(f"[BRIDGE] utils.abortController not available: {_e}")
    
    # Use fallback implementations
    AbortController = _FallbackAbortController
    create_abort_controller = _fallback_create_abort_controller


# ============================================================
# DIFF HOOKS — useDiffData + useDiffInIDE integration
# ============================================================

def _load_diff_service():
    """Load DiffDataService singleton. Returns None if unavailable."""
    try:
        mod = _importlib.import_module("agent.src.hooks.useDiffData")
        return mod.get_diff_service()
    except Exception as exc:
        log.warning(f"[BRIDGE] DiffDataService not available: {exc}")
        return None

def _load_cortex_diff_bridge():
    """Load CortexDiffBridge singleton. Returns None if unavailable."""
    try:
        mod = _importlib.import_module("agent.src.hooks.useDiffInIDE")
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
    """AppState providing tool_permission_context and session state."""
    tool_permission_context = _PermissionContext()
    
    def __init__(self):
        self._state: Dict[str, Any] = {}
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        self._state[key] = value
    
    def update(self, data: Dict[str, Any]) -> None:
        self._state.update(data)


class _GlobLimits:
    max_results = 1000


class _WaitResumeController:
    """
    Controller for wait/resume mechanism.
    Allows tools to pause execution and wait for external events.
    """
    def __init__(self):
        self._waiting = False
        self._event = None
        self._result = None
    
    def is_waiting(self) -> bool:
        return self._waiting
    
    def wait(self, timeout: float = 30.0) -> Any:
        """Block until resumed or timeout."""
        import threading
        self._waiting = True
        self._event = threading.Event()
        self._event.wait(timeout)
        self._waiting = False
        return self._result
    
    def resume(self, result: Any = None) -> None:
        """Resume execution with a result."""
        self._result = result
        self._waiting = False
        if self._event:
            self._event.set()


class _MCPHookManager:
    """
    Manager for MCP (Model Context Protocol) hooks.
    Allows registration and execution of MCP server hooks.
    """
    def __init__(self) -> None:
        self._hooks: Dict[str, List[Callable[..., Any]]] = {}
    
    def register(self, event: str, callback: Callable[..., Any]) -> None:
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)
    
    def unregister(self, event: str, callback: Callable[..., Any]) -> None:
        if event in self._hooks and callback in self._hooks[event]:
            self._hooks[event].remove(callback)
    
    async def trigger(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        results: List[Any] = []
        for callback in self._hooks.get(event, []):
            try:
                result = callback(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                results.append(result)
            except Exception as e:
                log.warning(f"[MCP Hook] {event} callback failed: {e}")
        return results


class _AuthHookManager:
    """
    Manager for authentication hooks.
    Allows tools to request authentication from the UI.
    """
    def __init__(self, bridge: 'CortexAgentBridge'):
        self._bridge = bridge
        self._pending_auth: Dict[str, Any] = {}
    
    def request_auth(self, service: str, scopes: Optional[List[str]] = None) -> str:
        """Request authentication for a service. Returns auth request ID."""
        import uuid
        request_id = f"auth-{uuid.uuid4().hex[:8]}"
        self._pending_auth[request_id] = {
            "service": service,
            "scopes": scopes or [],
            "status": "pending",
            "result": None,
        }
        log.info(f"[AUTH] Auth request {request_id} for {service}")
        return request_id
    
    def complete_auth(self, request_id: str, result: Any) -> None:
        """Complete an auth request with a result."""
        if request_id in self._pending_auth:
            self._pending_auth[request_id]["status"] = "completed"
            self._pending_auth[request_id]["result"] = result
    
    def get_auth_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        return self._pending_auth.get(request_id)


class _SessionStateManager:
    """
    Manager for session-level state that tools can read/write.
    Provides a key-value store for tool communication.
    """
    def __init__(self) -> None:
        self._state: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Callable[[str, Any, Any], None]]] = {}
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        old_value = self._state.get(key)
        self._state[key] = value
        # Notify listeners
        for callback in self._listeners.get(key, []):
            try:
                callback(key, old_value, value)
            except Exception as e:
                log.warning(f"[State] Listener for {key} failed: {e}")
    
    def subscribe(self, key: str, callback: Callable[[str, Any, Any], None]) -> None:
        if key not in self._listeners:
            self._listeners[key] = []
        self._listeners[key].append(callback)
    
    def unsubscribe(self, key: str, callback: Callable[[str, Any, Any], None]) -> None:
        if key in self._listeners and callback in self._listeners[key]:
            self._listeners[key].remove(callback)


class _ContextBudgetTracker:
    """
    Tracks context budget usage across tool calls.
    Prevents context overflow by monitoring cumulative token usage.
    """
    def __init__(self, model_limits: Optional[ModelLimits] = None):
        self._model_limits = model_limits
        self._hard_context_cap_tokens = self._get_hard_context_cap_tokens()
        self._files_in_context: Dict[str, int] = {}  # path -> estimated tokens
        self._total_estimated_tokens = 0
        self._warnings: List[str] = []

    @staticmethod
    def _get_hard_context_cap_tokens() -> int:
        # Global safety ceiling for per-turn context usage.
        # Default raised to 1M so high-context models (e.g., DeepSeek V4) are
        # not artificially constrained unless user overrides via env.
        raw = os.environ.get("CORTEX_MAX_CONTEXT_TOKENS_PER_TURN", "1000000")
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except Exception:
            pass
        return 1_000_000

    def _effective_budget_tokens(self) -> int:
        if self._model_limits:
            return min(self._model_limits.context_budget, self._hard_context_cap_tokens)
        return self._hard_context_cap_tokens
    
    def set_model_limits(self, limits: ModelLimits) -> None:
        self._model_limits = limits
    
    def add_file(self, path: str, char_count: int) -> int:
        estimated_tokens = char_count // 4
        self._files_in_context[path] = estimated_tokens
        self._total_estimated_tokens += estimated_tokens
        return self._check_budget()
    
    def remove_file(self, path: str) -> None:
        if path in self._files_in_context:
            self._total_estimated_tokens -= self._files_in_context[path]
            del self._files_in_context[path]
    
    def _check_budget(self) -> int:
        budget = self._effective_budget_tokens()
        used = self._total_estimated_tokens
        remaining = budget - used
        if remaining < budget * 0.2:
            self._warnings.append(f"Context budget low: {remaining:,} tokens remaining")
        safe_remaining = int(remaining * 0.8)
        return max(4_000, safe_remaining * 4)
    
    def get_remaining_budget_chars(self) -> int:
        budget = self._effective_budget_tokens()
        safe_remaining = int((budget - self._total_estimated_tokens) * 0.8)
        return max(4_000, safe_remaining * 4)
    
    def get_warnings(self) -> List[str]:
        warnings = self._warnings.copy()
        self._warnings.clear()
        return warnings
    
    def is_over_budget(self) -> bool:
        budget = self._effective_budget_tokens()
        return self._total_estimated_tokens > budget * 0.9


class CortexToolContext:
    """
    Expanded context with MODEL-AWARE FILE READ LIMITS.
    
    CRITICAL: Prevents context overflow by capping file reads based on
    model context window. Large files MUST be read in chunks.
    
    Includes:
    - Model-aware file reading limits (prevents context overflow)
    - Context budget tracking (monitors cumulative token usage)
    - File state tracking (read/modified files)
    - LRU file read dedup cache (ported from Claude Code's fileStateCache.ts)
    - App state management, Wait/resume, MCP/Auth hooks
    """

    # ── LRU File Read Cache constants ────────────────────────────────────
    # Ported from Claude Code: fileStateCache.ts (100 entries, 25MB max)
    _FILE_CACHE_MAX_ENTRIES = 100
    _FILE_CACHE_MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25MB
    _FILE_UNCHANGED_STUB = (
        "[File content unchanged since last read — using cached version. "
        "No need to re-read. Proceed with the content you already have.]"
    )

    def __init__(self, bridge: 'CortexAgentBridge', model_id: str = "gpt-4o"):
        self._bridge = bridge
        self._model_id = model_id
        
        # Model-aware limits
        self._model_limits: Optional[Any] = None
        self._budget_tracker = _ContextBudgetTracker()
        
        # File reading limits - updated when model is set
        self.read_file_state: Dict[str, Any] = {}
        self.file_reading_limits = {
            "maxSizeBytes": 40_000,
            "maxTokens": 10_000,
        }
        
        # ── LRU File Read Dedup Cache ────────────────────────────────────
        # Tracks file content by normalized path. On re-read, if mtime + 
        # offset/limit match, returns FILE_UNCHANGED_STUB instead of full
        # content, saving massive context. Uses OrderedDict for LRU eviction.
        # Ported from Claude Code's FileStateCache (fileStateCache.ts)
        from collections import OrderedDict
        self._file_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()  # norm_path → {content, timestamp, offset, limit, size}
        self._file_cache_total_size: int = 0
        
        self.glob_limits = _GlobLimits()
        self.abort_controller = create_abort_controller()
        self.dynamic_skill_dir_triggers: set = set()
        self.nested_memory_attachment_triggers: set = set()
        self.user_modified = False
        
        # Content replacement state for per-message budget enforcement
        # (ported from Claude Code's ContentReplacementState)
        self._content_replacement_state = None  # lazy init

        # File state tracking
        self._files_read: Dict[str, float] = {}
        self._files_modified: Dict[str, float] = {}
        
        # Expanded state management
        self._app_state = _AppState()
        self._wait_resume = _WaitResumeController()
        self._mcp_hooks = _MCPHookManager()
        self._auth_hooks = _AuthHookManager(bridge)
        self._session_state = _SessionStateManager()
        
        # Permission context
        self._permission_context = _PermissionContext()
        
        # Initialize limits for default model
        self._init_model_limits(model_id)
    
    def _init_model_limits(self, model_id: str) -> None:
        """Initialize model-aware file reading limits."""
        try:
            from src.ai.model_limits import get_model_limits  
            self._model_limits = get_model_limits(model_id)
            self._budget_tracker.set_model_limits(self._model_limits)
            # _model_limits is guaranteed to be set here by get_model_limits()
            assert self._model_limits is not None  # Ensure type checker knows it's not None
            self.file_reading_limits = {
                "maxSizeBytes": self._model_limits.max_file_read_bytes,
                "maxTokens": self._model_limits.max_file_read_chars // 4,
            }
            log.info(f"[CTX] Model limits: {model_id} -> file_cap={self._model_limits.max_file_read_chars:,} chars")
        except Exception as e:
            log.warning(f"[CTX] Failed to get model limits: {e}")
            self.file_reading_limits = {"maxSizeBytes": 40_000, "maxTokens": 10_000}
    
    def set_model(self, model_id: str) -> None:
        if model_id != self._model_id:
            self._model_id = model_id
            self._init_model_limits(model_id)
    
    def get_max_file_read_chars(self) -> int:
        if self._model_limits:
            return self._model_limits.max_file_read_chars
        return 10_000
    def get_remaining_budget_chars(self) -> int:
        return self._budget_tracker.get_remaining_budget_chars()
    def track_file_read(self, path: str, char_count: int) -> None:
        self._budget_tracker.add_file(path, char_count)
    def is_context_over_budget(self) -> bool:
        return self._budget_tracker.is_over_budget()
    def get_budget_warnings(self) -> List[str]:
        return self._budget_tracker.get_warnings()

    # ── LRU File Read Dedup Cache methods ─────────────────────────────────
    # Ported from Claude Code's FileStateCache (fileStateCache.ts)

    def file_cache_get(self, norm_path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> Optional[str]:
        """
        Check if a file read can be served from cache.
        Returns FILE_UNCHANGED_STUB if cached content matches current disk mtime
        and same offset/limit. Returns None if cache miss.
        """
        entry: Optional[Dict[str, Any]] = self._file_cache.get(norm_path)
        if entry is None:
            return None
        
        # Check mtime
        try:
            current_mtime = os.path.getmtime(norm_path)
        except OSError:
            return None
        
        if entry['timestamp'] != current_mtime:
            # File changed — invalidate cache entry
            self._file_cache_evict(norm_path)
            return None
        
        # Check offset/limit match
        if entry['offset'] != offset or entry['limit'] != limit:
            return None
        
        # Cache HIT — move to end (most recently used)
        self._file_cache.move_to_end(norm_path)
        log.info(f"[CTX] File cache HIT: {os.path.basename(norm_path)} (saved {entry['size']:,} chars)")
        return self._FILE_UNCHANGED_STUB

    def file_cache_put(self, norm_path: str, content: str, mtime: float, offset: Optional[int] = None, limit: Optional[int] = None) -> None:
        """Store a file read result in the LRU cache."""
        content_size = len(content.encode('utf-8', errors='replace'))
        
        # Evict if already present (to update size tracking)
        if norm_path in self._file_cache:
            self._file_cache_evict(norm_path)
        
        # Evict LRU entries until under size limit
        while (self._file_cache_total_size + content_size > self._FILE_CACHE_MAX_SIZE_BYTES
               and self._file_cache):
            oldest_key: str = next(iter(self._file_cache))
            self._file_cache_evict(oldest_key)
        
        # Evict if too many entries
        while len(self._file_cache) >= self._FILE_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(self._file_cache))
            self._file_cache_evict(oldest_key)
        
        self._file_cache[norm_path] = {
            'content': content,
            'timestamp': mtime,
            'offset': offset,
            'limit': limit,
            'size': content_size,
        }
        self._file_cache_total_size += content_size

    def _file_cache_evict(self, norm_path: str) -> None:
        """Remove an entry from the file cache."""
        entry = self._file_cache.pop(norm_path, None)
        if entry:
            self._file_cache_total_size -= entry['size']

    def file_cache_invalidate(self, norm_path: str):
        """Invalidate cache for a file (e.g. after edit/write)."""
        self._file_cache_evict(os.path.normpath(os.path.abspath(norm_path)))

    def get_content_replacement_state(self):
        """Get or create the per-conversation content replacement state."""
        if self._content_replacement_state is None:
            from src.ai.tool_result_storage import ContentReplacementState 
            self._content_replacement_state = ContentReplacementState()
        return self._content_replacement_state

    # Real tools call context.get_app_state()
    def get_app_state(self) -> _AppState:
        return self._app_state
    
    # App state setters
    def set_app_state(self, key: str, value: Any) -> None:
        self._app_state.set(key, value)
    
    def update_app_state(self, data: Dict[str, Any]) -> None:
        self._app_state.update(data)

    # FileEditTool / FileWriteTool check this
    def file_history_enabled(self) -> bool:
        return False

    # Wait/resume mechanism
    def wait_for_event(self, timeout: float = 30.0) -> Any:
        """Wait for an external event. Tools can use this for async operations."""
        return self._wait_resume.wait(timeout)
    
    def resume_execution(self, result: Any = None) -> None:
        """Resume execution after waiting."""
        self._wait_resume.resume(result)
    
    def is_waiting(self) -> bool:
        return self._wait_resume.is_waiting()

    # MCP hooks
    def register_mcp_hook(self, event: str, callback: Callable[..., Any]) -> None:
        self._mcp_hooks.register(event, callback)
    
    def unregister_mcp_hook(self, event: str, callback: Callable[..., Any]) -> None:
        self._mcp_hooks.unregister(event, callback)
    
    async def trigger_mcp_hook(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        return await self._mcp_hooks.trigger(event, *args, **kwargs)

    # Auth hooks
    def request_auth(self, service: str, scopes: Optional[List[str]] = None) -> str:
        return self._auth_hooks.request_auth(service, scopes)
    
    def complete_auth(self, request_id: str, result: Any) -> None:
        self._auth_hooks.complete_auth(request_id, result)
    
    def get_auth_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        return self._auth_hooks.get_auth_status(request_id)

    # Session state
    def get_session_state(self, key: str, default: Any = None) -> Any:
        return self._session_state.get(key, default)
    
    def set_session_state(self, key: str, value: Any) -> None:
        self._session_state.set(key, value)
      
    def subscribe_session_state(self, key: str, callback: Callable[[str, Any, Any], None]) -> None:
        self._session_state.subscribe(key, callback)
    
    def unsubscribe_session_state(self, key: str, callback: Callable[[str, Any, Any], None]) -> None:
        self._session_state.unsubscribe(key, callback)

    # Permission context
    def get_permission_context(self) -> _PermissionContext:
        return self._permission_context

    # File state helpers
    def mark_file_read(self, path: str):
        import time
        self._files_read[os.path.normpath(path)] = time.time()

    def mark_file_modified(self, path: str):
        import time
        norm = os.path.normpath(path)
        self._files_modified[norm] = time.time()
        self._files_read.pop(norm, None)

    def is_file_known(self, path: str) -> bool:
        norm = os.path.normpath(path)
        return norm in self._files_read

    def get_known_files_summary(self) -> str:
        lines: List[str] = []
        for p in list(self._files_read)[-10:]:
            lines.append(f"  [read] {p}")
        for p in list(self._files_modified)[-10:]:
            lines.append(f"  [modified] {p}")
        return "\n".join(lines) if lines else "(none yet)"

    def get_recent_read_files(self, limit: int = 10) -> List[str]:
        return list(self._files_read.keys())[-limit:]

    def get_recent_modified_files(self, limit: int = 10) -> List[str]:
        return list(self._files_modified.keys())[-limit:]


def _always_allow_tool(*_args: Any, **_kwargs: Any) -> bool:
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


def _extract_affected_paths(command: str) -> List[str]:
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
    paths: List[str] = []
    for p in parts:
        if p.startswith('-') or p in SKIP:
            continue
        # Accept if it looks like a file/path (contains / \ . or has an extension)
        if _re.search(r'[/\\.]', p) or _re.search(r'\.[a-z]{1,5}$', p, _re.I):
            paths.append(p)
        elif p not in SKIP and len(p) > 1:
            paths.append(p)
    return paths[:5]


def _get_current_timestamp() -> str:
    """Get current timestamp in ISO format."""
    from datetime import datetime
    return datetime.now().isoformat()


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
    parameters: Dict[str, Any] = {
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

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        import threading as _threading
        command: str = args.get("command", "")
        timeout: int = int(args.get("timeout", 30))
        cwd = self._bridge.project_root or os.getcwd()

        # ── Dangerous-command permission gate ────────────────────────────────
        warning = _get_destructive_warning(command)
        if warning and self._bridge.always_allowed:
            log.info(
                "[BRIDGE] Permission gate bypassed (always_allow=True): %s",
                command[:180].replace("\n", " "),
            )
        if warning and not self._bridge.stop_requested and not self._bridge.always_allowed:
            affected = _extract_affected_paths(command)
            import json as _json
            # Create a fresh event for this request
            evt = _threading.Event()
            self._bridge.permission_event = evt
            self._bridge.permission_granted = False
            self._bridge.permission_requested.emit(
                command, warning, _json.dumps(affected)
            )
            # Wait without blocking the event loop
            granted = await asyncio.to_thread(evt.wait, 60.0)  # 60 s timeout
            self._bridge.permission_event = None
            if not granted or not self._bridge.permission_granted:
                return ToolResult(
                    tool_id="", result=None, success=False,
                    error="User rejected the command — not executed."
                )
        # ───────────────────────────────────────────────────────────────

        proc = None
        try:
            # Windows: use PowerShell so .ps1 scripts execute correctly
            # (cmd.exe triggers Windows file-association dialog for .ps1).
            # asyncio.create_subprocess_exec keeps the event loop responsive
            # so stop/cancel requests are delivered immediately.
            import subprocess as _sp
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
    parameters: Dict[str, Any] = {
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

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        dirpath: str = args.get("path", ".")
        if not os.path.isabs(dirpath) and self._bridge.project_root:
            dirpath = os.path.join(self._bridge.project_root, dirpath)
        try:
            entries: List[str] = []
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

_TOOL_SCHEMAS: List[Dict[str, Any]] = [
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
    {
        "type": "function",
        "function": {
            "name": "AskUserQuestion",
            "description": (
                "Ask the user a multiple-choice question to gather preferences, clarify requirements, "
                "or make decisions during execution. Use when you need user input to proceed. "
                "The user will see the question in the chat UI and can select one or more options."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "List of questions to ask (1-4 questions).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question":    {"type": "string", "description": "The complete question to ask"},
                                "header":      {"type": "string", "description": "Short label for chip/tag (max 12 chars)"},
                                "multiSelect": {"type": "boolean", "description": "Allow multiple selections (default false)"},
                                "options": {
                                    "type": "array",
                                    "description": "2-4 options for the user to choose from",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label":       {"type": "string", "description": "Display text (1-5 words)"},
                                            "description": {"type": "string", "description": "Explanation of what this option means"},
                                        },
                                        "required": ["label", "description"],
                                    },
                                },
                            },
                            "required": ["question", "header", "options"],
                        },
                    },
                },
                "required": ["questions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "LSP",
            "description": (
                "Language Server Protocol tool for code intelligence. Provides go-to-definition, "
                "find references, hover info, document symbols, and call hierarchy navigation. "
                "Use to understand code structure and navigate relationships between symbols."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["goToDefinition", "findReferences", "hover", "documentSymbol", 
                                 "workspaceSymbol", "goToImplementation", "prepareCallHierarchy", 
                                 "incomingCalls", "outgoingCalls"],
                        "description": "The LSP operation to perform"
                    },
                    "filePath": {
                        "type": "string",
                        "description": "Absolute path to the file"
                    },
                    "line": {
                        "type": "integer",
                        "description": "1-based line number"
                    },
                    "character": {
                        "type": "integer",
                        "description": "1-based character/column position"
                    },
                },
                "required": ["operation", "filePath", "line", "character"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "WebFetch",
            "description": (
                "Fetch and extract content from a URL. Returns the main content as markdown. "
                "Use to retrieve documentation, API references, or other web content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch content from"
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional search query to find specific content on the page"
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "WebSearch",
            "description": (
                "Search the web for current information. Returns a list of relevant results "
                "with titles, URLs, and snippets. Use for finding up-to-date information, "
                "documentation, or solutions to problems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "allowed_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of domains to restrict search to"
                    },
                    "blocked_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of domains to exclude from search"
                    },
                },
                "required": ["query"],
            },
        },
    },
    # ============================================================
    # TASK V2 TOOLS - Structured task management
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "TaskCreate",
            "description": (
                "Create a new task in the task list. Use for complex multi-step tasks "
                "to track progress and demonstrate thoroughness. Creates structured tasks "
                "with subject, description, and optional metadata."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Brief, actionable title in imperative form (e.g., 'Fix authentication bug')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of what needs to be done"
                    },
                    "activeForm": {
                        "type": "string",
                        "description": "Present continuous form shown when task is in_progress (e.g., 'Fixing authentication bug')"
                    },
                    "parentId": {
                        "type": "string",
                        "description": "Optional ID of the parent task if this is a subtask"
                    },
                    "dependsOn": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of task IDs that must be completed before this task can start"
                    },
                    "estimatedEffort": {
                        "type": "string",
                        "description": "Optional estimated effort (e.g., '30min', '2h', '3d')"
                    },
                },
                "required": ["subject", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TaskUpdate",
            "description": (
                "Update an existing task's status, owner, or dependencies. "
                "Use to mark tasks as in_progress/completed, assign to teammates, or set dependencies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {
                        "type": "string",
                        "description": "ID of the task to update"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled", "blocked"],
                        "description": "New status for the task"
                    },
                    "owner": {
                        "type": "string",
                        "description": "Agent ID to assign as owner"
                    },
                    "blocks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Task IDs that this task blocks"
                    },
                    "blockedBy": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Task IDs that block this task"
                    },
                    "parentId": {
                        "type": "string",
                        "description": "Update the parent task ID (or empty string to remove parent)"
                    },
                    "dependsOn": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Replace the list of dependency task IDs"
                    },
                    "estimatedEffort": {
                        "type": "string",
                        "description": "Update estimated effort (e.g., '30min', '2h', '3d')"
                    },
                },
                "required": ["taskId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TaskList",
            "description": (
                "List all tasks in the current session. Shows task status, owners, "
                "and dependencies. Use to understand current work state before creating new tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled", "all"],
                        "description": "Filter tasks by status (default: all)"
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TaskGet",
            "description": (
                "Get details of a specific task by ID. Returns full task information "
                "including description, status, owner, and dependencies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {
                        "type": "string",
                        "description": "ID of the task to retrieve"
                    },
                },
                "required": ["taskId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TaskStop",
            "description": (
                "Stop a running task. Marks the task as cancelled and cleans up any "
                "running processes associated with it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {
                        "type": "string",
                        "description": "ID of the task to stop"
                    },
                },
                "required": ["taskId"],
            },
        },
    },
    # ============================================================
    # MCP TOOL - Model Context Protocol
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "MCP",
            "description": (
                "Execute a tool from an MCP (Model Context Protocol) server. "
                "MCP servers provide external tools for databases, APIs, and custom integrations. "
                "Use to interact with external systems beyond the built-in tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "serverName": {
                        "type": "string",
                        "description": "Name of the MCP server to use"
                    },
                    "toolName": {
                        "type": "string",
                        "description": "Name of the tool on the MCP server"
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments to pass to the MCP tool"
                    },
                },
                "required": ["serverName", "toolName"],
            },
        },
    },
    # ============================================================
    # TEAM/SWARM TOOLS - Multi-agent orchestration
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "TeamCreate",
            "description": (
                "Create a new team of AI agents for parallel task execution. "
                "Teams can work on different parts of a project simultaneously, "
                "with a team lead coordinating work distribution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the team"
                    },
                    "description": {
                        "type": "string",
                        "description": "Purpose/goal of the team"
                    },
                    "teammates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Name for this teammate"},
                                "role": {"type": "string", "description": "Role/specialization (e.g., 'frontend', 'backend', 'testing')"},
                            },
                        },
                        "description": "List of teammates to create"
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "TeamDelete",
            "description": (
                "Delete a team and stop all its agents. "
                "Cleans up team resources and terminates running processes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "teamName": {
                        "type": "string",
                        "description": "Name of the team to delete"
                    },
                },
                "required": ["teamName"],
            },
        },
    },
]


def _get_tool_definitions() -> List[Dict[str, Any]]:
    """
    Return OpenAI-compatible tool definitions.

    Returns built-in schemas directly.  The tool_registry.py stub does not
    provide a functional get_all_base_tools, so registry-based loading is
    skipped to avoid false warnings.
    """
    return list(_TOOL_SCHEMAS)


def _tool_name_from_schema(tool_def: Dict[str, Any]) -> str:
    """Extract tool function name from OpenAI-compatible schema entry."""
    fn_any = tool_def.get("function")
    fn = cast(Dict[str, Any], fn_any) if isinstance(fn_any, dict) else None
    if isinstance(fn, dict):
        name = fn.get("name")
        if isinstance(name, str):
            return name
    return ""


def _filter_tool_definitions(
    tool_defs: List[Dict[str, Any]],
    allowed_names: Set[str],
) -> List[Dict[str, Any]]:
    """Return only tool schemas whose function name is in allowed_names."""
    if not allowed_names:
        return []
    out: List[Dict[str, Any]] = []
    for td in tool_defs:
        if _tool_name_from_schema(td) in allowed_names:
            out.append(td)
    return out


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
    "TeamCreate": "team_create",
    "TeamDelete": "team_delete",
    "TaskCreate": "task_create",
    "TaskUpdate": "task_update",
    "TaskList":   "task_list",
    "TaskGet":    "task_get",
    "TaskStop":   "task_stop",
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
        self._queue: Optional[asyncio.Queue[WorkerMessage]] = None
        self._loop:  Optional[asyncio.AbstractEventLoop] = None
        # Tracks the asyncio.Task currently running _handle_chat.
        # Assigned right after asyncio.create_task(); used by stop_generation()
        # (via stop_session_task) to cancel mid-execution.
        self._current_chat_task: Optional[asyncio.Task[Any]] = None

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
        self._queue = asyncio.Queue[WorkerMessage]()

        while self._is_running:
            # ── Phase 1: Wait for the next queued message ─────────────────────
            try:
                msg: WorkerMessage = await asyncio.wait_for(self._queue.get(), timeout=0.1)
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
            task_id_raw = msg.get("task_id")
            task_id = task_id_raw if isinstance(task_id_raw, str) and task_id_raw else None
            if task_id and self._current_chat_task is not None:
                self.bridge.link_worker_task(task_id, self._current_chat_task)

            # ── Phase 3: Concurrently watch task + queue ──────────────────────
            # Mirrors the TS pattern: the running query holds an AbortSignal;
            # a stop command triggers abort() → CancelledError here.
            while self._is_running and not self._current_chat_task.done():
                get_fut: asyncio.Task[WorkerMessage] = asyncio.ensure_future(self._queue.get())
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
                        next_msg: WorkerMessage = get_fut.result()
                    except Exception:
                        continue

                    if next_msg.get("type") == "stop":
                        log.info(
                            "[WORKER] Stop message received while running — cancelling chat task"
                        )
                        await self._cancel_active_task()
                        break

                    elif next_msg.get("type") == "chat":
                        # New prompt arrived before the old one finished.
                        # Cancel old, then re-queue the new message so the
                        # outer loop starts it fresh.
                        log.info(
                            "[WORKER] New chat arrived while running — cancelling old task and re-queuing new one"
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

    async def _handle_chat(self, msg: WorkerMessage):
        self.thinking_started.emit()
        try:
            response = await self.bridge.call_llm(
                msg.get("content", ""),
                msg.get("context", {}),
                msg.get("images", []),
            )
            # ── INDUSTRY-STANDARD: Task Completion Validation ───────────
            # Before emitting response_ready (which triggers Windows notification),
            # verify that ALL todos are actually completed with mutations.
            # This prevents premature notifications when AI tries to skip work.
            
            _should_notify = True
            _pending_count = 0
            # Use PERSISTENT session counter, not per-turn counter
            _mutation_count = self.bridge._session_mutation_count
            
            # ── CRITICAL: Check if todos were auto-cancelled (incomplete) ──
            if getattr(self.bridge, '_todos_auto_cancelled', False):
                _should_notify = False
                msg_text = (
                    "[WORKER] Notification BLOCKED: Todos were auto-cancelled (not completed). "
                    f"AI made {_mutation_count} mutation(s) but tasks were NOT finished."
                )
                log.warning(msg_text)
                self.bridge.allow_notification = False
                self.bridge._todos_auto_cancelled = False  # Reset for next time
            
            # Check if there are pending todos
            elif hasattr(self.bridge, '_current_todos') and self.bridge._current_todos:
                _pending_todos = [
                    t for t in self.bridge._current_todos
                    if t.get("status") not in ("COMPLETE", "CANCELLED")
                ]
                _pending_count = len(_pending_todos)
                
                # If there are pending todos, DO NOT show notification
                if _pending_count > 0:
                    _should_notify = False
                    log.warning(
                        "[WORKER] Suppressing notification: " +
                        f"{_pending_count} todo(s) still pending. " +
                        f"AI made {_mutation_count} mutation(s) but tasks incomplete."
                    )
                
                # Even if todos marked complete, check if mutations match
                elif _pending_count == 0 and _mutation_count == 0:
                    # All marked complete but zero mutations = AI skipped work
                    _should_notify = False
                    log.warning(
                        "[WORKER] Suppressing notification: Todos marked complete but NO mutations made. " +
                        "AI tried to skip work!"
                    )
            
            # Always emit response_ready (even if response is empty text) so
            # on_complete → onComplete() → _onGenerationComplete() always fires
            # in JS, which drains the message queue and un-sticks any 'Continue'
            # message that was enqueued while _isGenerating was still True.
            if not self.bridge.stop_requested:
                # Attach task completion metadata to response for notification control
                self.response_ready.emit(response or "")
                
                if _should_notify:
                    log.info(
                        f"[WORKER] Notification allowed: {_mutation_count} mutation(s), " +
                        f"{_pending_count} pending todo(s) — task genuinely complete."
                    )
                    # Set flag for main_window to check before showing notification
                    self.bridge.allow_notification = True
                else:
                    # Block notification - tasks incomplete
                    self.bridge.allow_notification = False
                    log.info(
                        f"[WORKER] Notification BLOCKED: {_pending_count} pending todo(s), " +
                        f"{_mutation_count} mutation(s) — AI must complete remaining tasks."
                    )
        except asyncio.CancelledError:
            # Task was cancelled via asyncio.Task.cancel() from stop_session_task().
            # This is an intentional stop — do NOT emit error_occurred.
            log.info("[WORKER] Chat task cancelled (CancelledError) — stop was requested")
            raise  # Re-raise so asyncio correctly marks the task as cancelled
        except Exception as exc:
            if not self.bridge.stop_requested:
                log.error(f"[WORKER] Chat error: {exc}")
                self.error_occurred.emit(str(exc))
            else:
                log.info(f"[WORKER] Exception during stopped chat (suppressed): {exc}")
        finally:
            self.thinking_stopped.emit()

    def queue_message(self, msg: WorkerMessage):
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
    user_question_requested = pyqtSignal(dict)  # Full payload: {"tool_call_id": str, "question": str, "type": str, "choices": list, "default": str, "details": str, "scope": str, "tool_name": str}
    # Permission request — emitted before a dangerous bash command runs.
    # JS shows an Accept/Reject card; Python waits via threading.Event.
    permission_requested = pyqtSignal(str, str, str)  # command, warning, files_json
    # File operation cards — show animated cards during create/edit operations
    file_creating_started = pyqtSignal(str)  # file_path
    file_editing_started = pyqtSignal(str)   # file_path
    file_operation_completed = pyqtSignal(str, str, str, str)  # card_id, file_path, content, op_type
    # Recovery signals — context compaction / turn-limit continuation
    agent_status_update = pyqtSignal(str, str)  # type ('compacting'|'retrying'|'failover'), message
    turn_limit_hit      = pyqtSignal(list)       # list of still-pending todo dicts
    # Token budget signal — (used_tokens, budget_tokens, provider_name)
    context_budget_update = pyqtSignal(int, int, str)
    # ── INDUSTRY-STANDARD: Progress tracking signal ───────────
    # Emits (completed, total, percentage, status_message)
    # Allows UI to show progress bar: "3/5 tasks complete (60%)"
    task_progress_update = pyqtSignal(int, int, int, str)

    # ── Internal state ──────────────────────────────────────────
    def __init__(self, **kwargs: Any):
        super().__init__()
        self._project_root: Optional[str] = None
        self._active_file:  Optional[str] = None
        self._cursor_pos:   Optional[int] = None
        self._terminal      = None
        self._ui_parent     = None
        self._lsp_manager   = None
        self._always_allowed: bool = False
        self._interaction_mode: str = "default"
        self._conversation_history: List[ChatMessage] = []
        self._enhancement_data: Dict[str, Any] = {}
        self._streaming      = None
        self._current_todos: List[Dict[str, Any]] = []   # Persisted todo list for TodoWrite
        self._pending_questions: Dict[str, Any] = {}  # Pending AskUserQuestion items
        # ── Stale-continue detection ──────────────────────────────────
        # Track how many times the same set of todos survived a Continue cycle
        # without any progress.  After _MAX_STALE_CYCLES, auto-cancel them.
        self._continue_cycle_count: int = 0
        self._last_pending_ids: set[str] = set()
        self._MAX_STALE_CYCLES: int = 3  # Increased from 1 to allow more working turns
        # Guard against "plan-only" loops where TodoWrite repeats without real action.
        self._todo_write_streak: int = 0
        self._last_todo_signature: str = ""
        self._mutation_success_count: int = 0
        self._last_todo_mutation_count: int = -1
        # ── Persistent session mutation counter ─────────────────────
        # This survives across call_llm calls to track TOTAL mutations
        # made by the AI throughout the entire session (not just one message)
        self._session_mutation_count: int = 0
        self._stop_requested: bool = False  # Set to interrupt the streaming loop
        # ── Notification control flag ────────────────────────────────
        # Set by worker thread to control whether Windows notification should show.
        # Only True when ALL todos are genuinely completed with mutations.
        self._allow_notification: bool = True  # Default: allow (for simple Q&A with no todos)
        # ── Auto-cancel tracking ─────────────────────────────────────
        # Tracks if todos were auto-cancelled (incomplete) vs genuinely completed
        self._todos_auto_cancelled: bool = False
        # Persistent memory dir — computed once per project root
        self._memory_dir: Optional[str] = None
        # Permission gate — used by BridgeBashTool to pause until user accepts/rejects
        self._permission_event: Optional[threading.Event] = None   # lazily created
        self._permission_granted: bool = False
        # Session task registry — converted from AppStateStore.ts tasks map.
        # Tracks the active asyncio.Task for proper cancellation on stop.
        self._task_registry: SessionTaskRegistry = SessionTaskRegistry()

        # ── Circuit breaker & Tool Execution Engine (Phase B) ───────────
        self._tool_circuit_breaker: ToolCircuitBreaker = ToolCircuitBreaker(
            threshold=5,
            repetitive_limit=50,  # Allow 50 calls per tool before repetitive-limit kicks in (was 4, which killed Write after 4 edits)
        )
        self._tool_executor: ToolExecutionEngine = ToolExecutionEngine(self._tool_circuit_breaker)
        # Legacy aliases for backward compatibility
        self._tool_fail_counts: Dict[str, int] = self._tool_circuit_breaker._fail_counts
        self._disabled_tools: set = self._tool_circuit_breaker._disabled_tools
        self._tool_total_calls: Dict[str, int] = self._tool_circuit_breaker._total_calls
        self._session_tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> task payload
        self._teams: Dict[str, Dict[str, Any]] = {}  # team_id -> team payload

        # ── Test verification state ────────────────────────────────────────
        # Stores recent tool results for verification enforcement.
        # Each entry: (tool_name: str, success: bool, content_preview: str, exit_code: Optional[int])
        self._recent_tool_results: List[Tuple[str, bool, str, Optional[int]]] = []
        self._max_recent_results: int = 20  # Keep last 20 tool results
        # Detected test framework (populated lazily on first check)
        self._test_framework: Optional[str] = None
        self._test_framework_checked: bool = False

        # ── Self-healing debug loop state ─────────────────────────────────
        from src.core.debug_loop import DebugLoop
        self._debug_loop: DebugLoop = DebugLoop()

        # ── Sandbox execution manager (Phase 7) ────────────────────────────
        # Lazy-initialized on first call via property
        self._sandbox_manager: Optional[Any] = None

        # ── Hierarchical task graph ───────────────────────────────────────
        self._task_graph: TaskGraph = TaskGraph()

        log.info("[BRIDGE] Initialising Cortex Agent Bridge")

        # Initialise real agent bootstrap state
        self._init_agent_state()

        # Build tool context for real agent tools (use model from settings if available)
        _initial_model: str = 'mistral-large-latest'
        try:
            from src.config.settings import get_settings
            _raw_settings: Any = get_settings()
            _raw_ai: Any = _raw_settings.get('ai')
            _raw_model: Optional[str] = None
            if isinstance(_raw_ai, dict):
                _ai_map = cast(Dict[str, Any], _raw_ai)
                _candidate = _ai_map.get('model')
                if isinstance(_candidate, str) and _candidate:
                    _raw_model = _candidate
            if _raw_model:
                _initial_model = _raw_model
        except Exception:
            pass
        self._tool_ctx = CortexToolContext(self, _initial_model)
        self._current_model_id: str = _initial_model

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
        self._connect_qt_signal(self._worker.response_ready, self._on_response_ready)
        self._connect_qt_signal(self._worker.chunk_ready, self._on_chunk_ready)
        self._connect_qt_signal(self._worker.error_occurred, self._on_error)
        self._connect_qt_signal(self._worker.thinking_started, self.thinking_started.emit)
        self._connect_qt_signal(self._worker.thinking_stopped, self.thinking_stopped.emit)
        self._worker.start()

        # ── Phase 4: Auto-resume from previous interrupted session ────────
        _resume_requested = "--resume" in sys.argv
        _no_resume_requested = "--no-resume" in sys.argv
        if not _no_resume_requested and (_resume_requested or (Path.home() / ".cortex" / "agent_state.json").exists()):
            try:
                from src.core.agent_session_manager import load_snapshot
                snapshot = load_snapshot()
                if snapshot:
                    self._hydrate_from_snapshot(snapshot)
                    log.info("[SESSION] Session restored from snapshot")
            except Exception as _ses_exc:
                log.warning(f"[SESSION] Auto-resume failed: {_ses_exc}")

        log.info("[BRIDGE] Agent bridge ready")
        
        # Pre-warm provider registry at startup to avoid 2s delay on first message
        try:
            from src.ai.providers import get_provider_registry
            get_provider_registry()
            log.info("[BRIDGE] Provider registry pre-warmed")
        except Exception as e:
            log.warning(f"[BRIDGE] Provider pre-warm failed (will lazy-init): {e}")

        # Initialize file_edit_notification signal for WebChannel
        self.file_edit_notification = pyqtSignal(str, str, str)  # filePath, editType, status
        log.info("[BRIDGE] file_edit_notification signal initialized")

    @property
    def allow_notification(self) -> bool:
        """Whether Windows notification should show after task completion."""
        return self._allow_notification

    @allow_notification.setter
    def allow_notification(self, value: bool) -> None:
        self._allow_notification = value

    @staticmethod
    def _connect_qt_signal(signal: Any, slot: Callable[..., Any]) -> None:
        """Typed wrapper for Qt signal connections (PyQt stubs expose partial Unknown here)."""
        signal.connect(slot)

    def link_worker_task(self, task_id: str, task: asyncio.Task[Any]) -> None:
        """Link worker-created asyncio task to the registered session task state."""
        ts = self._task_registry.get(task_id)
        if ts is not None:
            ts.asyncio_task = task

    # ── Public property accessors for protected attributes ─────────────────
    # These provide controlled access to internal state from tool classes
    
    @property
    def project_root(self) -> Optional[str]:
        """Get the project root path."""
        return self._project_root
    
    @property
    def always_allowed(self) -> bool:
        """Check if tools are always allowed without permission."""
        return self._always_allowed
    
    @property
    def stop_requested(self) -> bool:
        """Check if stop has been requested."""
        return self._stop_requested
    
    @property
    def permission_event(self) -> Optional[threading.Event]:
        """Get the current permission event."""
        return self._permission_event
    
    @permission_event.setter
    def permission_event(self, value: Optional[threading.Event]) -> None:
        """Set the permission event."""
        self._permission_event = value
    
    @property
    def permission_granted(self) -> bool:
        """Check if permission was granted."""
        return self._permission_granted
    
    @permission_granted.setter
    def permission_granted(self, value: bool) -> None:
        """Set permission granted status."""
        self._permission_granted = value

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
            self._connect_qt_signal(self._streaming.llm_token, self.response_chunk.emit)
            self._connect_qt_signal(self._streaming.error, self.request_error.emit)
            log.info("[BRIDGE] Streaming emitter connected")
        except Exception as exc:
            log.warning(f"[BRIDGE] Streaming not available: {exc}")
            self._streaming = None

    # ── System prompt builder ──────────────────────────────────

    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        project_root = self._project_root or os.getcwd()
        active_file  = self._active_file or ""

        # ── Auto-discover project structure (cached) ──────────
        project_info = self._get_project_summary(project_root)

        # ── File state awareness ──────────────────────────────
        known_files = self._tool_ctx.get_known_files_summary()

        # ── Persistent memory (project-scoped, loaded once per session) ──
        memory_section = ''
        _mem_enabled: bool = True
        try:
            from src.config.settings import get_settings
            _raw_settings: Any = get_settings()
            _raw_memory: Any = _raw_settings.get('memory')
            if isinstance(_raw_memory, dict):
                _memory_map = cast(Dict[str, Any], _raw_memory)
                _candidate = _memory_map.get('enabled')
                if isinstance(_candidate, bool):
                    _mem_enabled = _candidate
        except Exception:
            pass
        if _mem_enabled:
            memory_dir = self._get_memory_dir()
            self._ensure_memory_dir(memory_dir)
            memory_section = self._load_memory_section(memory_dir)

        prompt = f"""You are Cortex AI Agent, an autonomous coding assistant integrated into Cortex AI Agent.
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

## Task Graph
{self._task_graph.build_prompt_section() if self._task_graph and self._task_graph.get_task_count() > 0 else "No tasks created yet. Use TaskCreate to create structured tasks with optional parent/child relationships and dependencies."}

## Tools Available
You MUST call tools to take real action. Never describe what you "would" do — actually do it.

## Performance Rules
- Minimize tool calls. Prefer 1–2 high-signal reads over repeated directory listings.
- Batch independent tool calls in the SAME turn when possible (e.g., multiple Reads), instead of a back-and-forth loop.
- Avoid repeating the same tool call (especially `LS`) unless the filesystem likely changed.

### TodoWrite(todos)
Plan and track multi-step tasks in the UI. **CALL THIS FIRST** — before any other tool — whenever you start a task with 3+ steps. Use it to immediately show your plan in the sidebar. Mark tasks in_progress BEFORE starting them, completed IMMEDIATELY after finishing each one. Provide both content (imperative, e.g. 'Run tests') and activeForm (present continuous, e.g. 'Running tests') for every item.

**IMPORTANT**: Call TodoWrite ONCE to set up your plan, then START WORKING immediately. Do NOT call TodoWrite again until a task status actually changes (e.g. moving a task to in_progress or completed). Never call TodoWrite twice in a row with the same data.

### Read(file_path, offset?, limit?)
Read file contents. Always Read a file BEFORE editing it.
**SMART READING**: Files >250 lines automatically return a SKELETON (structure + line numbers)
instead of full content. Use line numbers from the skeleton for targeted reads.
**WORKFLOW for any file**:
  1. Read(file_path="file.py") → if small: full content; if large: skeleton with line numbers
  2. Find the section you need from the skeleton
  3. Read(file_path="file.py", offset=LINE, limit=80) → get just that section
  4. OR use Grep(pattern="keyword") first to find exact line numbers
NEVER try to read an entire large file at once — it wastes your context budget.
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
BEST PRACTICE: Use Grep BEFORE Read to find exact line numbers, then Read with offset/limit.
This avoids wasting context on irrelevant code. Do NOT call Grep more than 2-3 times in a row.
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
10. LARGE FILES — SMART CHUNK-BASED READING:
    Your IDE uses the SAME strategy as Cursor, VS Code Copilot, and Claude Code:
    Files >250 lines automatically return a SKELETON (not full content).
    The skeleton shows class/function signatures with LINE NUMBERS.
    
    CRITICAL: Your model has a FIXED context window. Reading entire large files
    wastes 90%+ of your token budget on irrelevant code.
    
    Smart workflow:
      a) Read(file_path="file.py") → skeleton with line numbers (auto for >250 lines)
      b) Identify the function/class you need from the skeleton
      c) Read(file_path="file.py", offset=LINE, limit=80) → just that section
      d) OR: Grep(pattern="keyword") first, THEN targeted Read with offset/limit
    
    NEVER attempt to read the entire content of a file >250 lines at once.
    Use Grep → Read(offset, limit) pattern for maximum efficiency.

## Content Formatting & Visualization
When explaining concepts, architectures, or workflows, use visual formats to enhance clarity:

### Mermaid Diagrams
Use Mermaid syntax for flowcharts, sequence diagrams, state diagrams, and architecture visualizations.
Wrap Mermaid code in triple backticks with `mermaid` language identifier:
```mermaid
graph TD
    A[Start] --> B[Process]
    B --> C[End]
```

Common Mermaid diagram types:
- **Flowcharts**: `graph TD` (top-down) or `graph LR` (left-right)
- **Sequence diagrams**: `sequenceDiagram` for interactions between components
- **State diagrams**: `stateDiagram-v2` for state machines
- **Class diagrams**: `classDiagram` for software architecture
- **ER diagrams**: `erDiagram` for database schemas
- **Gantt charts**: `gantt` for project timelines

Use diagrams when:
- Explaining system architecture
- Showing data flow between components
- Visualizing algorithms or processes
- Documenting API interactions
- Planning project structure

### Math & Equations
Use LaTeX syntax for mathematical expressions:
- Inline math: `$E = mc^2$`
- Display math example: integral from 0 to infinity of e^(-x^2) dx = sqrt(pi)/2

### Tables
Use Markdown tables for structured data comparison:
| Feature | Option A | Option B |
|---------|----------|----------|
| Speed   | Fast     | Slow     |
| Cost    | High     | Low      |
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
        if _importlib_util.find_spec("agent.src.memdir.memdir"):
            try:
                from agent.src.memdir.memdir import buildMemoryPrompt
                prompt = buildMemoryPrompt({
                    'displayName': 'Cortex Memory',
                    'memoryDir': memory_dir,
                })
                if prompt:
                    parts.append(prompt)
            except Exception as exc:
                log.debug('[BRIDGE] buildMemoryPrompt failed (%s); using fallback', exc)
        else:
            log.debug('[BRIDGE] memdir.memdir not available; using fallback')
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
        memoryFreshnessNote: Callable[[float], str] = lambda mtime_ms: ""

        if _importlib_util.find_spec("agent.src.memdir.memoryAge"):
            try:
                from agent.src.memdir.memoryAge import memoryFreshnessNote as _mf
                memoryFreshnessNote = cast(Callable[[float], str], _mf)
            except Exception:
                pass

        try:
            mem_files: List[Tuple[float, str]] = []
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

        # --- Layer 3: Cross-session semantic memory ---
        try:
            from src.core.semantic_memory import get_semantic_memory_index
            _sem_idx = get_semantic_memory_index()
            if _sem_idx is not None and _sem_idx.count() > 0:
                # Use a generic query so we get broad-relevance results
                semantic_section = _sem_idx.build_prompt_section(
                    "coding project context decisions architecture",
                    max_entries=3,
                )
                if semantic_section:
                    # Keep memory section lean by tail-inserting
                    parts.append(semantic_section)
        except ImportError:
            pass
        except Exception as exc:
            log.debug('[BRIDGE] Semantic memory search skipped: %s', exc)

        return '\n\n'.join(parts)

    def _get_project_summary(self, project_root: str) -> Optional[str]:
        """Auto-discover project structure for the system prompt (cached per session)."""
        if hasattr(self, '_cached_project_summary'):
            return self._cached_project_summary
        lines: List[str] = []
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
            detected: List[str] = []
            for marker, lang in markers.items():
                if os.path.exists(os.path.join(project_root, marker)):
                    detected.append(lang)
            if detected:
                lines.append(f"Tech stack: {', '.join(detected)}")

            # Show top-level directory structure
            try:
                entries = sorted(os.scandir(project_root), key=lambda e: (not e.is_dir(), e.name))
                top_level: List[str] = []
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
    # CONTEXT CHECKPOINT & COMPACTION
    # ============================================================

    def _create_context_checkpoint(self, messages: List[Any], user_message: str = "") -> str:
        """
        Create a structured checkpoint of the current conversation state
        and persist it to MEMORY.md for cross-session recovery.

        Captures:
        - Current task / user request
        - Todo items with statuses
        - Files read and modified this session
        - Key assistant decisions
        - Conversation summary digest

        The checkpoint is saved to:
          1. A timestamped .md file in the memory dir
          2. MEMORY.md index (so it's loaded automatically on next session)

        Returns the checkpoint text (also used inline by _compact_messages).
        """
        import time as _time
        from datetime import datetime as _dt

        parts: List[str] = []

        # 1. Current user request (first user message or most recent)
        _user_msg = user_message
        if not _user_msg:
            for msg in reversed(messages):
                if getattr(msg, 'role', None) == 'user':
                    _content = getattr(msg, 'content', '') or ''
                    if not _content.startswith('[System note') and not _content.startswith('[Context Recovery'):
                        _user_msg = _content[:500]
                        break
        if _user_msg:
            parts.append(f"**Current Task:** {_user_msg[:500]}")

        # 2. Todo items
        if self._current_todos:
            todo_lines: List[str] = []
            for t in self._current_todos:
                status = str(t.get('status', 'pending')).upper()
                content = t.get('content', t.get('activeForm', ''))
                icon = {'COMPLETED': '[x]', 'IN_PROGRESS': '[~]', 'CANCELLED': '[-]'}.get(status, '[ ]')
                todo_lines.append(f"  {icon} {content}")
            parts.append("**Todo Progress:**\n" + "\n".join(todo_lines))

        # 3. Files read / modified
        _read_files = self._tool_ctx.get_recent_read_files(10)
        _mod_files = self._tool_ctx.get_recent_modified_files(10)
        if _read_files:
            parts.append("**Files Read:** " + ", ".join(os.path.basename(f) for f in _read_files))
        if _mod_files:
            parts.append("**Files Modified:** " + ", ".join(os.path.basename(f) for f in _mod_files))

        # 4. Key assistant decisions (last 3 assistant messages, truncated)
        _decisions: List[str] = []
        for msg in reversed(messages):
            if getattr(msg, 'role', None) == 'assistant':
                _content = getattr(msg, 'content', '') or ''
                if _content and not getattr(msg, 'tool_calls', None):
                    _decisions.append(_content[:200])
                    if len(_decisions) >= 3:
                        break
        if _decisions:
            parts.append("**Key Decisions:**\n" + "\n".join(f"- {d}" for d in reversed(_decisions)))

        # 5. Conversation summary digest (collect all user+assistant exchanges)
        _summary_lines: List[str] = []
        _msg_count = 0
        for msg in messages:
            _role = getattr(msg, 'role', None)
            _content = getattr(msg, 'content', '') or ''
            if _role == 'user' and _content and not _content.startswith('['):
                _summary_lines.append(f"User: {_content[:150]}")
                _msg_count += 1
            elif _role == 'assistant' and _content and not getattr(msg, 'tool_calls', None):
                _summary_lines.append(f"Assistant: {_content[:150]}")
                _msg_count += 1
            if _msg_count >= 10:  # Keep last 10 exchanges max
                break
        if _summary_lines:
            parts.append("**Conversation Digest:**\n" + "\n".join(_summary_lines))

        checkpoint_text = "\n\n".join(parts)

        # Save to persistent memory dir
        try:
            memory_dir = self._get_memory_dir()
            self._ensure_memory_dir(memory_dir)
            ts = int(_time.time())
            now_str = _dt.now().strftime('%Y-%m-%d %H:%M')
            filename = f"checkpoint_{ts}.md"
            filepath = os.path.join(memory_dir, filename)
            frontmatter = (
                "---\n"
                f"name: Context Checkpoint {now_str}\n"
                "description: Auto-saved conversation state before context compaction\n"
                "type: project\n"
                "---\n\n"
            )
            with open(filepath, 'w', encoding='utf-8') as fh:
                fh.write(frontmatter + checkpoint_text)
            log.info(f"[BRIDGE] Context checkpoint saved: {filename}")

            # ── UPDATE MEMORY.md with conversation summary ────────────────
            # This is the KEY feature: MEMORY.md acts as the persistent
            # conversation summary that survives across sessions.
            # On next session start, _load_memory_section() reads it
            # and injects it into the system prompt automatically.
            self._update_memory_md(memory_dir, checkpoint_text, now_str, filename)

            # Clean up old checkpoints (keep only last 3)
            self._cleanup_old_checkpoints(memory_dir, keep=3)

            # ── Update cross-session semantic memory index ─────────────────
            try:
                from src.core.semantic_memory import get_semantic_memory_index
                _sem_idx = get_semantic_memory_index()
                if _sem_idx is not None:
                    # Derive a compact summary from the checkpoint text
                    _sem_summary = self._extract_semantic_summary(checkpoint_text)
                    _project_dir = os.path.basename(self._project_root) if self._project_root else 'unknown'
                    _sem_idx.store_session(
                        session_id=f"chk_{ts}",
                        summary=_sem_summary,
                        metadata={
                            "project": _project_dir,
                            "checkpoint_file": filename,
                            "source": "context_compaction",
                        },
                    )
            except ImportError:
                pass
            except Exception as exc:
                log.debug(f"[BRIDGE] Semantic memory update skipped: {exc}")

        except Exception as exc:
            log.warning(f"[BRIDGE] Failed to save context checkpoint: {exc}")

        return checkpoint_text

    def _update_memory_md(self, memory_dir: str, checkpoint_text: str, timestamp: str, checkpoint_file: str):
        """
        Update MEMORY.md with the latest compaction summary.
        
        MEMORY.md serves as the persistent conversation summary that:
        - Survives across IDE sessions
        - Gets auto-loaded into system prompt via _load_memory_section()
        - Lets the LLM continue work seamlessly after context compaction
        
        Like Qoder/VS Code Copilot: "Compacting conversation" -> save summary -> continue.
        """
        memory_md_path = os.path.join(memory_dir, 'MEMORY.md')
        
        # Build the new MEMORY.md content
        # Keep existing non-checkpoint entries, replace/append the latest summary
        existing_entries: List[str] = []
        try:
            with open(memory_md_path, 'r', encoding='utf-8') as fh:
                content = fh.read()
            # Parse existing entries (lines starting with "- [")
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('- [') and 'checkpoint_' not in line.lower():
                    existing_entries.append(line)
        except FileNotFoundError:
            pass
        except Exception:
            pass

        # Build updated MEMORY.md
        lines: List[str] = [
            '# Cortex Memory Index',
            '',
            '## Conversation Summary (auto-updated on compaction)',
            '',
            f'Last compacted: {timestamp}',
            '',
        ]
        
        # Add the summary section directly in MEMORY.md
        # This is what gets loaded into the system prompt on next session
        _summary_lines: List[str] = checkpoint_text.split('\n')
        # Truncate to ~2000 chars to keep MEMORY.md lean
        _truncated: List[str] = []
        _total = 0
        for sl in _summary_lines:
            if _total + len(sl) > 2000:
                _truncated.append('...(truncated)')
                break
            _truncated.append(sl)
            _total += len(sl)
        lines.extend(_truncated)
        lines.append('')
        
        # Add pointer to full checkpoint file
        lines.append(f'- [Full checkpoint]({checkpoint_file}) — {timestamp}')
        lines.append('')

        # Preserve existing non-checkpoint memory entries
        if existing_entries:
            lines.append('## Other Memories')
            lines.append('')
            lines.extend(existing_entries)
            lines.append('')

        try:
            with open(memory_md_path, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(lines))
            log.info(f"[BRIDGE] MEMORY.md updated with compaction summary ({len(checkpoint_text)} chars)")
        except Exception as exc:
            log.warning(f"[BRIDGE] Failed to update MEMORY.md: {exc}")

    def _cleanup_old_checkpoints(self, memory_dir: str, keep: int = 3):
        """Remove old checkpoint files, keeping only the most recent N."""
        try:
            checkpoints: List[Tuple[float, str]] = []
            for fname in os.listdir(memory_dir):
                if fname.startswith('checkpoint_') and fname.endswith('.md'):
                    fpath = os.path.join(memory_dir, fname)
                    checkpoints.append((os.path.getmtime(fpath), fpath))
            checkpoints.sort(reverse=True)  # newest first
            for _, fpath in checkpoints[keep:]:
                try:
                    os.remove(fpath)
                    log.debug(f"[BRIDGE] Removed old checkpoint: {os.path.basename(fpath)}")
                except OSError:
                    pass
        except Exception:
            pass

    def _estimate_message_tokens(self, messages: List[Any]) -> int:
        """
        Estimate total token count of message list.
        Uses ~4 chars per token approximation.
        """
        total_chars = 0
        for msg in messages:
            content_raw = getattr(msg, 'content', '')
            content = content_raw if isinstance(content_raw, str) else ''
            total_chars += len(content)
            # Tool calls add ~100 tokens each for metadata
            tool_calls = getattr(msg, 'tool_calls', None)
            if isinstance(tool_calls, list) and tool_calls:
                total_chars += len(cast(List[Any], tool_calls)) * 400
        return total_chars // 4

    def _compact_messages(self, messages: List[Any], PCM: Type[Any]) -> List[Any]:
        """
        Trim conversation history so the next API call fits in the context window.
        Saves the conversation summary to MEMORY.md for cross-session recovery.

        Strategy
        --------
        • Always keep the system message (index 0).
        • Create a context checkpoint capturing task state, todos, files.
        • Persist the checkpoint to MEMORY.md (like Qoder/VS Code “Compacting conversation”).
        • Drop the oldest messages in the middle, keeping the last
          KEEP_TAIL messages so recent context is intact.
        • Walk the tail forward to the first safe boundary (a user or
          assistant turn) so we never orphan a tool-result block.
        • Inject the checkpoint as a rich summary so the LLM continues seamlessly.
        """
        # ── Emit UI status: "Compacting conversation..." ────────────────
        try:
            self._safe_emit(
                self.agent_status_update,
                'compacting',
                'Compacting conversation — saving summary to memory...'
            )
        except Exception:
            pass

        KEEP_TAIL = 10
        if len(messages) <= KEEP_TAIL + 2:
            return messages  # nothing meaningful to drop

        system_msg: Any = messages[0]
        rest: List[Any] = messages[1:]          # everything after the system prompt

        if len(rest) <= KEEP_TAIL:
            return messages

        tail: List[Any] = rest[-KEEP_TAIL:]
        dropped_count = len(rest) - len(tail)

        # Advance `tail` to the first safe role boundary so we never start
        # mid tool-result block (tool results must follow their assistant turn).
        for i, msg in enumerate(tail):
            if getattr(msg, 'role', None) in ('user', 'assistant'):
                tail = tail[i:]
                break

        # Create checkpoint with rich context + persist to MEMORY.md
        checkpoint_text = self._create_context_checkpoint(messages)

        summary: Any = PCM(
            role='user',
            content=(
                f'[Context Recovery: {dropped_count} earlier messages were compacted. '
                f'Conversation summary has been saved to MEMORY.md for persistence. '
                f'Here is the saved state of your work so far:]\n\n'
                f'{checkpoint_text}\n\n'
                f'[Continue completing the task based on this checkpoint and the '
                f'remaining messages below. Do NOT re-read files you already read.]'
            )
        )
        compacted: List[Any] = [system_msg, summary] + tail
        log.info(
            f'[BRIDGE] Context compacted: {len(messages)} \u2192 {len(compacted)} messages (dropped {dropped_count} middle messages, summary saved to MEMORY.md)'
        )

        # ── Emit completion status ───────────────────────────────────────
        try:
            self._safe_emit(
                self.agent_status_update,
                'ready',
                f'Conversation compacted — {dropped_count} messages summarized to MEMORY.md'
            )
        except Exception:
            pass

        return compacted

    # ============================================================
    # PROVIDER FAILOVER HELPERS
    # ============================================================

    # Failover priority chain: Mistral only
    _failover_chain = None  # lazily built

    def _get_failover_provider(self, current_type: Any, registry: Any) -> Optional[Any]:
        """
        Return the next provider in the failover chain, or None if exhausted.
        Skips providers that don't have a valid API key.
        Max 2 failover hops to avoid infinite cycling.
        """
        from src.ai.providers import ProviderType, ProviderRegistry  
        current_provider = cast(ProviderType, current_type)
        provider_registry = cast(ProviderRegistry, registry)
        if self._failover_chain is None:
            self._failover_chain = [
                ProviderType.MISTRAL,
                ProviderType.SILICONFLOW,
                ProviderType.DEEPSEEK,
            ]

        _attempted_raw = getattr(self, '_failover_attempted', None)
        _attempted: Set[Any] = cast(Set[Any], _attempted_raw) if isinstance(_attempted_raw, set) else set()
        _attempted.add(current_provider)
        self._failover_attempted = _attempted

        if len(_attempted) >= 3:  # max 2 hops
            return None

        for pt in self._failover_chain:
            if pt in _attempted:
                continue
            # Check if provider is registered and has a key
            if pt not in provider_registry.list_providers():
                continue
            _prov = provider_registry.get_provider(pt)
            try:
                if _prov.validate_api_key():
                    return pt
            except Exception:
                continue
        return None

    def _get_default_model_for_provider(self, provider_type: Any, original_model: str) -> str:
        """
        Map a provider type to a sensible default model when failing over.
        Tries to keep the same "tier" (e.g. small -> small).
        """
        from src.ai.providers import ProviderType
        provider_enum = cast(ProviderType, provider_type)
        _model_lower = original_model.lower() if original_model else ""
        _is_small = any(x in _model_lower for x in ['mini', 'nano', 'small', 'lite'])

        _defaults = {
            ProviderType.MISTRAL: 'mistral-small-latest' if _is_small else 'mistral-medium-latest',
        }
        return _defaults.get(provider_enum, original_model)

    # ============================================================
    # MULTI-TURN AGENTIC LOOP  (the core of the bridge)
    # ============================================================

    async def _call_llm(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        images: Optional[List[str]] = None,
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

        # Reset failover state for this call
        self._failover_attempted: Set[Any] = set()
        self._failover_exhausted = False
        # Per-request mutation progress counters.
        self._mutation_success_count = 0
        self._last_todo_mutation_count = -1
        # Reset auto-cancel tracking
        self._todos_auto_cancelled = False

        merged = {**self._enhancement_data, **context}

        try:
            from src.ai.providers import get_provider_registry, ProviderType, ChatMessage as PCM

            registry      = get_provider_registry()
            
            # Determine provider type based on model
            model_id = merged.get("model_id", merged.get("model", "mistral-large-latest"))
            model_lower = model_id.lower() if model_id else ""
            
            # Update tool context with current model (for model-aware file limits)
            if model_id != getattr(self, '_current_model_id', None):
                self._current_model_id = model_id
                self._tool_ctx.set_model(model_id)
                log.info(f"[BRIDGE] Updated tool context for model: {model_id}")

            # ── Model-aware context limits ─────────────────────────────────────
            # Derive all budget constants from the model's actual context window so
            # every supported LLM is handled correctly without hardcoded magic numbers.
            try:
                from src.ai.model_limits import get_model_limits, describe_model_limits
                _limits = get_model_limits(model_id)
                log.info(f"[BRIDGE] {describe_model_limits(model_id)}")
            except Exception as _lim_err:
                log.warning(f"[BRIDGE] model_limits import failed, using defaults: {_lim_err}")
                class _FallbackLimits:
                    max_output_tokens      = 32_000
                    max_tool_result_chars  = 15_000
                    max_hist_chars         = 20_000
                    max_turns              = 25
                _limits = _FallbackLimits()
            
            # Models requiring Responses API (removed - no longer supported)
            # needs_responses = any(x in model_lower for x in ["codex", "gpt-5", "o1", "o3"])
            
            # Determine provider type based on model ID
            provider_type = ProviderType.MISTRAL  # Default
            
            if model_lower.startswith("deepseek"):
                # DeepSeek models (V4-Pro, V4-Flash, etc.)
                provider_type = ProviderType.DEEPSEEK
            elif model_lower.startswith("mistral") or model_lower.startswith("codestral"):
                # Mistral models
                provider_type = ProviderType.MISTRAL
            elif model_lower.startswith("qwen") or "siliconflow" in model_lower:
                # SiliconFlow/Qwen vision models
                provider_type = ProviderType.SILICONFLOW
            
            provider = registry.get_provider(provider_type)
            model    = model_id

            log.info(f"[BRIDGE] provider={provider_type.value} model={model}")

            # ── Build initial message list ─────────────────────
            # Fast-path: for very simple messages (e.g. greetings), skip the heavy
            # IDE system prompt + history + tool schema. This reduces payload size
            # and improves time-to-first-token on slow/latent providers.
            _simple_query = False
            try:
                _simple_query = self._is_simple_query(message)
            except Exception:
                _simple_query = False

            messages: List[Any]
            if _simple_query:
                system_prompt = (
                    "You are Cortex AI Chat inside a coding IDE. "
                    "Answer the user directly and concisely. "
                    "Do not mention internal tools or system details."
                )
                messages = [
                    PCM(role="system", content=system_prompt),
                    PCM(role="user", content=message),
                ]
                tool_defs = []
                log.info("[BRIDGE] Simple-query fast path: skipping tools + history + project prompt")
                max_turns = 1
            else:
                system_prompt = merged.get("system_prompt") or self._build_system_prompt(context)
                messages = [PCM(role="system", content=system_prompt)]

                # Inject conversation history (last 20 turns).
                # Truncate very large messages (e.g. pasted file contents) so the
                # Continue run does not re-pay the full context cost of the first request.
                _MAX_HIST_CONTENT = _limits.max_hist_chars  # scaled to model context window
                for hist_msg in self._conversation_history[-20:]:
                    if hist_msg.role in ("user", "assistant"):
                        hist_content = hist_msg.content or ""
                        has_tool_calls = bool(hist_msg.tool_calls)
                        # Skip empty assistant messages (no content + no tool_calls)
                        # — these cause Mistral API errors
                        if hist_msg.role == 'assistant' and not hist_content and not has_tool_calls:
                            continue
                        if len(hist_content) > _MAX_HIST_CONTENT:
                            hist_content = (
                                hist_content[:_MAX_HIST_CONTENT]
                                + f"\n... [context trimmed: {len(hist_msg.content) - _MAX_HIST_CONTENT} chars omitted]"
                            )
                        cm = PCM(role=hist_msg.role, content=hist_content)
                        if getattr(hist_msg, "reasoning_content", None):
                            cm.reasoning_content = hist_msg.reasoning_content
                        if has_tool_calls:
                            cm.tool_calls = hist_msg.tool_calls
                        messages.append(cm)
                    elif hist_msg.role == "tool":
                        hist_content = hist_msg.content or ""
                        if len(hist_content) > _MAX_HIST_CONTENT:
                            hist_content = hist_content[:_MAX_HIST_CONTENT] + "\n... [context trimmed]"
                        messages.append(
                            PCM(role="tool", content=hist_content,
                                tool_call_id=hist_msg.tool_call_id)
                        )

                # Current user turn
                messages.append(PCM(role="user", content=message))

                tool_defs = _get_tool_definitions()
                log.info(f"[BRIDGE] Total tools after merge: {len(tool_defs)}")
                max_turns = _limits.max_turns
                # Keep agent loops bounded for responsiveness. Can be overridden.
                try:
                    # Lower default improves first-action latency for typical IDE tasks.
                    _max_turns_env = int(os.environ.get("CORTEX_MAX_AGENT_TURNS", "25"))
                    if _max_turns_env > 0:
                        max_turns = min(max_turns, _max_turns_env)
                except Exception:
                    pass

            full_response = ""

            # ── Circuit breaker & Tool execution engine (Phase B) ──
            # Both are persistent instances owned by the bridge.
            _cb: ToolCircuitBreaker = self._tool_circuit_breaker
            _executor: ToolExecutionEngine = self._tool_executor
            _REPETITIVE_CALL_LIMIT = 4  # Prevent wasteful loops (Grep/Read/Todo cycles)
            _CONSECUTIVE_READONLY_LIMIT = 3  # Max same read-only tool in a row
            
            # ── Mutation progress detector ─────────────────────────────────────
            # Track if agent has performed ANY write/edit operation
            # If no mutation after N turns, force aggressive action mode
            _mutation_turns = 0  # Turns with write/edit/bash operations
            _READONLY_FORCE_ACTION_TURN = 8  # Increased from 4 — give agent more reading/planning turns before nagging
            _AGGRESSIVE_NUDGE_TURN = 12  # Increased from 6
            _has_mutated = False  # Track if ANY mutation has occurred this session
            _POST_MUTATION_READ_LIMIT = 5  # Increased from 2 — let agent read more files post-mutation before forcing verify

            _compacted_once = False  # Track if we already compacted
            _mistral_downgraded_once = False  # Per-request, timeout-triggered model fallback within Mistral

            # ── Auto-compact state (ported from Claude Code's autoCompact.ts) ───
            _auto_compact_state = None
            try:
                from src.ai.conversation_compactor import AutoCompactState
                _auto_compact_state = AutoCompactState()
            except ImportError:
                pass

            for turn in range(max_turns):
                log.info(f"[BRIDGE] === Agentic turn {turn + 1}/{max_turns} ===")
                # Track per-turn tool success so we only count successful mutations
                self._tool_call_success = {}

                
                # ── INDUSTRY-STANDARD: Agent Phase Tracking ─────────────────
                # Track which phase the agent is in to enforce proper workflow
                # Phases: READING → PLANNING → IMPLEMENTING → VERIFYING → DONE
                if turn == 0:
                    _agent_phase = "READING"
                elif _has_mutated and len(self._current_todos) == 0:
                    _agent_phase = "VERIFYING"
                elif _has_mutated:
                    _agent_phase = "IMPLEMENTING"
                elif self._current_todos:
                    _agent_phase = "PLANNING"
                else:
                    _agent_phase = "READING"
                
                # Log phase transitions
                if turn == 0 or _agent_phase != getattr(self, '_last_agent_phase', ''):
                    log.info(f"[BRIDGE] Agent phase: {_agent_phase}")
                    self._last_agent_phase = _agent_phase

                # ── Micro-compact: clear old tool results (cheap, no LLM) ────
                # Ported from Claude Code's microCompact.ts. Runs every turn
                # to keep context lean by clearing stale tool result content.
                if turn > 0:
                    try:
                        from src.ai.conversation_compactor import microcompact_messages
                        messages, _mc_saved = microcompact_messages(messages, keep_recent=6)
                        if _mc_saved > 0:
                            log.info(f"[BRIDGE] Micro-compact saved ~{_mc_saved:,} tokens on turn {turn + 1}")
                    except Exception as _mc_err:
                        log.debug(f"[BRIDGE] Micro-compact skipped: {_mc_err}")

                # ── Emit token budget update to UI ─────────────────────────
                _est_tokens = self._estimate_message_tokens(messages)
                _budget = getattr(_limits, 'context_budget', 100_000)
                _prov_label = provider_type.value if hasattr(provider_type, 'value') else str(provider_type)
                try:
                    self._safe_emit(self.context_budget_update, int(_est_tokens), int(_budget), _prov_label)
                except Exception:
                    pass  # UI signal failures must never break the loop

                # ── Pre-overflow detection ──────────────────────────────────
                # Estimate current context usage before sending to LLM.
                # If approaching the limit, proactively compact instead of
                # waiting for the API to reject with a context_length error.
                if turn > 0:  # Skip first turn (messages are fresh)
                    _usage_pct = _est_tokens / max(_budget, 1)
                    if _usage_pct > 0.75:
                        if not _compacted_once:
                            log.warning(
                                f"[BRIDGE] Pre-overflow: {_est_tokens:,} tokens estimated ({_usage_pct:.0%} of {_budget:,} budget) — compacting proactively"
                            )
                            self._safe_emit(
                                self.agent_status_update,
                                'compacting',
                                f'Context {_usage_pct:.0%} full — checkpointing and compacting...'
                            )
                            messages = self._compact_messages(messages, PCM)
                            _compacted_once = True
                        elif _usage_pct > 0.85:
                            # Already compacted once and STILL over 85% — aggressive trim
                            log.warning(
                                f"[BRIDGE] Post-compact overflow: {_est_tokens:,} tokens ({_usage_pct:.0%}) — aggressive trim"
                            )
                            messages = self._compact_messages(messages, PCM)

                # ── Stream LLM response (with context-compaction retry) ────
                tool_acc: Dict[int, Dict[str, Any]] = {}   # idx -> {id, name, arguments}
                turn_text  = ""
                turn_reasoning = ""
                # ── INDUSTRY-STANDARD: Start with minimal toolset ────
                # Only load 9 core tools initially to:
                # 1. Save tokens (~10,000 tokens per turn)
                # 2. Reduce AI confusion
                # 3. Speed up responses (3-5s vs 10-15s)
                # Expand to full set only after mutations occur
                core_names = {
                    "Read", "Write", "Edit", "Glob", "Grep", "LS", "Bash",
                    "TodoWrite", "AskUserQuestion",
                }
                active_tool_defs = _filter_tool_definitions(list(tool_defs), core_names)
                
                # After AI has made mutations, expand toolset slightly
                # but DON'T dump all 19 tools — only add WebSearch + LSP
                # for research/navigation, keep task/MCP/team tools excluded
                # to save ~500+ lines of JSON per turn.
                if self._session_mutation_count > 5:
                    expanded_names = core_names | {"WebSearch", "LSP"}
                    active_tool_defs = _filter_tool_definitions(list(tool_defs), expanded_names)
                    log.info(
                        f"[TOOLS] Expanded to {len(active_tool_defs)} tools "
                        f"after {self._session_mutation_count} mutations"
                    )

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
                def _retry_notify(attempt_num: int, max_att: int, err_type: str) -> None:
                    if err_type == 'timeout':
                        msg = 'API timeout - retrying (%d/%d)...' % (attempt_num, max_att)
                    elif err_type == 'rate_limit':
                        msg = 'Rate limit hit - waiting before retry (%d/%d)...' % (attempt_num, max_att)
                    else:
                        msg = 'API error - retrying (%d/%d)...' % (attempt_num, max_att)
                    log.info('[BRIDGE] Provider retry: %s' % msg)
                    self._safe_emit(self.agent_status_update, 'retrying', msg)

                for _compact_attempt in range(3):  # attempt 0, 1, 2
                    tool_acc  = {}
                    turn_text = ""
                    turn_reasoning = ""
                    try:
                        # Get max_tokens from model_limits
                        max_tokens = _limits.max_output_tokens
                        
                        # Apply performance mode token multiplier if set
                        try:
                            from src.config.settings import get_settings
                            settings_any: Any = get_settings()
                            _raw_mult: Any = 1.0
                            _raw_ai = settings_any.get("ai")
                            if isinstance(_raw_ai, dict):
                                _ai_map = cast(Dict[str, Any], _raw_ai)
                                _raw_mult = _ai_map.get("token_multiplier", 1.0)
                            token_multiplier = float(_raw_mult) if isinstance(_raw_mult, (int, float, str)) else 1.0
                            if token_multiplier != 1.0:
                                # Calculate with multiplier
                                calculated_tokens = int(max_tokens * token_multiplier)
                                
                                # CRITICAL: Cap at model's hard limit to avoid API errors
                                # APIs enforce strict max_output_tokens limits
                                if calculated_tokens > max_tokens:
                                    log.warning(
                                        f"[BRIDGE] Token multiplier {token_multiplier}x would exceed model limit ({calculated_tokens} > {max_tokens}). Capping at {max_tokens}"
                                    )
                                    calculated_tokens = max_tokens
                                
                                max_tokens = calculated_tokens
                                log.info(f"[BRIDGE] Applied performance token_multiplier: {token_multiplier}x, max_tokens: {_limits.max_output_tokens} -> {max_tokens}")
                        except Exception as _mult_err:
                            pass  # Use base max_tokens if multiplier not available
                        
                        _chat_kwargs: Dict[str, Any] = {
                            "retry_callback": _retry_notify
                        }
                        if provider_type == ProviderType.MISTRAL and active_tool_defs:
                            _chat_kwargs["max_retries"] = 3

                        # Adaptive output budget:
                        # - keep tool turns intentionally lean for fast iteration
                        # - allow larger answers when no tools are needed
                        # Always respect model cap (max_tokens) and remaining context budget.
                        if active_tool_defs:
                            prompt_chars = len(message)
                            tool_count = len(active_tool_defs)
                            remaining_ctx = max(0, int(_budget - _est_tokens))
                            budget_cap = min(max_tokens, max(800, remaining_ctx // 4))

                            # Complexity hint grows with prompt size, number of tools, and later turns.
                            complexity_hint = prompt_chars + (tool_count * 120) + (turn * 300)
                            # Keep tool turns lean for lower latency.
                            tool_turn_upper_cap = min(max_tokens, 1_600)
                            tool_turn_mid_cap = min(max_tokens, 900)
                            if complexity_hint < 900:
                                stream_max_tokens = min(max_tokens, 500)
                            elif complexity_hint < 2400:
                                stream_max_tokens = min(budget_cap, max(700, tool_turn_mid_cap))
                            else:
                                stream_max_tokens = min(budget_cap, max(1_000, tool_turn_upper_cap))
                        else:
                            # Final answer / no-tool turns can be larger, but keep bounded.
                            stream_max_tokens = min(max_tokens, 8_192)

                        log.debug(f"[BRIDGE] Adaptive stream cap: {stream_max_tokens} (tool_turn={bool(active_tool_defs)}, est={_est_tokens}, budget={_budget}, base_max={max_tokens})")

                        for chunk in provider.chat_stream(
                            messages, model=model, max_tokens=stream_max_tokens, tools=active_tool_defs, **_chat_kwargs
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
                            elif isinstance(chunk, str) and chunk.startswith("__REASONING_DELTA__:"):
                                _reason_chunk = chunk[len("__REASONING_DELTA__:"):]
                                turn_reasoning += _reason_chunk
                                # Stream reasoning/thought updates to UI activity pane in real time.
                                try:
                                    self._safe_emit(
                                        self.tool_activity,
                                        "thinking",
                                        json.dumps({"text": _reason_chunk}),
                                        "running",
                                    )
                                except Exception:
                                    pass
                            else:
                                turn_text    += chunk
                                full_response += chunk
                                self._safe_emit(self.response_chunk, chunk)
                        break  # stream completed (or stop requested) — exit retry loop

                    except Exception as _stream_exc:
                        _err_lower = str(_stream_exc).lower()
                        _is_ctx_err = any(kw in _err_lower for kw in _CTX_ERR_KEYWORDS)
                        _RATE_LIMIT_KEYWORDS = (
                            'rate limit', 'rate_limit', '429', 'too many requests',
                            'quota exceeded', 'insufficient_quota', 'billing',
                            'no credits', 'exceeded your current quota',
                        )
                        _TIMEOUT_KEYWORDS = (
                            'timed out', 'timeout', 'read timed out',
                            'connect timeout', 'connection timed out',
                        )
                        _is_rate_err = any(kw in _err_lower for kw in _RATE_LIMIT_KEYWORDS)
                        _is_timeout_err = any(kw in _err_lower for kw in _TIMEOUT_KEYWORDS)
                        if _is_ctx_err and _compact_attempt < 2:
                            log.warning(
                                f"[BRIDGE] Context limit on turn {turn + 1} (compact attempt {_compact_attempt + 1}/2): {_stream_exc}"
                            )
                            self._safe_emit(
                                self.agent_status_update,
                                'compacting',
                                'Context window exceeded - compacting history (%d/2), retrying...' % (_compact_attempt + 1)
                            )
                            messages = self._compact_messages(messages, PCM)
                            continue   # retry with compacted history
                        elif (_is_rate_err or _is_timeout_err) and not getattr(self, '_failover_exhausted', False):
                            # Mistral-only recovery: on timeout with large model, downgrade model tier once.
                            if (
                                _is_timeout_err
                                and provider_type == ProviderType.MISTRAL
                                and isinstance(model, str)
                                and "large" in model.lower()
                                and not _mistral_downgraded_once
                            ):
                                _mistral_downgraded_once = True
                                old_model = model
                                model = "mistral-medium-latest"
                                log.warning(
                                    f"[BRIDGE] Timeout on {old_model} — retrying with {model} (Mistral-only fallback)"
                                )
                                self._safe_emit(
                                    self.agent_status_update,
                                    'retrying',
                                    f'Timeout on {old_model} — retrying with {model}...'
                                )
                                continue

                            # ── Provider auto-failover on rate-limit/timeout ───
                            _next = self._get_failover_provider(provider_type, registry)
                            if _next is not None:
                                _old_name = provider_type.value
                                provider_type = _next
                                provider = registry.get_provider(provider_type)
                                # Re-derive model for new provider
                                model = self._get_default_model_for_provider(provider_type, model_id)
                                reason = "rate limited" if _is_rate_err else "timed out"
                                log.warning(
                                    f"[BRIDGE] Provider {_old_name} {reason} — failing over to {provider_type.value} (model={model})"
                                )
                                self._safe_emit(
                                    self.agent_status_update,
                                    'failover',
                                    f'Provider {_old_name} {reason} — switching to {provider_type.value}...'
                                )
                                continue  # retry with new provider
                            else:
                                self._failover_exhausted = True
                                raise
                        else:
                            raise      # non-context error or exhausted retries

                # If stop was requested, abort the entire agentic loop immediately
                if self._stop_requested:
                    log.info("[BRIDGE] Agentic loop aborted by stop request")
                    break

                # Assemble pending tool calls
                pending: List[Dict[str, Any]] = []
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

                # If no tool calls → check if we should force action or exit
                if not pending:
                    # ── INDUSTRY-STANDARD: Task Completion Verification ──────
                    # AI cannot exit unless:
                    # 1. It has made mutations (wrote/edited files)
                    # 2. All todos are marked complete
                    # 3. OR it's a legitimate informational response
                    
                    _has_pending_todos = len(self._current_todos) > 0
                    _todos_all_done = all(
                        t.get("status") in ("completed", "cancelled") 
                        for t in self._current_todos
                    ) if self._current_todos else True
                    
                    # Case 1: No mutations yet and early turns - FORCE ACTION
                    if _mutation_turns == 0 and (turn + 1) <= 5:
                        log.warning(
                            f"[BRIDGE] AI attempted to exit on turn {turn + 1} without making any changes. " +
                            "Forcing action mode - injecting strong directive."
                        )
                        _force_action_msg = (
                            f"STOP. You are trying to end the conversation on turn {turn + 1} without making ANY file changes. "
                            f"The user's task is NOT complete. You MUST:\n"
                            f"1. Use Write or Edit tool to modify files NOW\n"
                            f"2. Do NOT respond with just text - you MUST call a tool\n"
                            f"3. Start implementing the solution immediately\n\n"
                            f"User request: {message[:100]}..."
                        )
                        messages.append(PCM(role="user", content=_force_action_msg))
                        continue
                    
                    # Case 2: Has mutations but todos still pending - VERIFY COMPLETION
                    if _has_mutated and _has_pending_todos and not _todos_all_done:
                        _pending_count = sum(
                            1 for t in self._current_todos 
                            if t.get("status") not in ("completed", "cancelled")
                        )
                        log.warning(
                            f"[BRIDGE] AI tried to exit with {_pending_count} pending todos. " +
                            "Requiring verification before allowing exit."
                        )
                        _verify_msg = (
                            f"You have {_pending_count} incomplete task(s). Before ending:\n" +
                            "1. Verify ALL your changes actually work\n" +
                            "2. Complete remaining todos or mark them cancelled with explanation\n" +
                            "3. Test the result (use Bash to run/test if needed)\n" +
                            "4. Only then can you end the conversation\n\n" +
                            "Pending tasks:\n" +
                            "\n".join(f"  - {t['content']} [{t.get('status', 'pending')}]" for t in self._current_todos if t.get("status") not in ("completed", "cancelled"))
                        )
                        messages.append(PCM(role="user", content=_verify_msg))
                        continue
                    
                    # Case 3: Legitimate exit - all done or informational
                    log.info(f"[BRIDGE] No tool calls on turn {turn + 1} — done")
                    break

                log.info(
                    f"[BRIDGE] {len(pending)} tool call(s) on turn {turn + 1}: "
                    + ", ".join(p["function"]["name"] for p in pending)
                )

                # ── Append assistant turn with tool_calls ──────
                assistant_tool_calls: List[Dict[str, Any]] = [
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
                        reasoning_content=turn_reasoning or None,
                    )
                )

                # ── Execute tools via ToolExecutionEngine (Phase B) ─
                parsed_calls: List[Tuple[str, str, Any]] = []
                for tc in pending:
                    tool_name: str = str(tc["function"]["name"])
                    tool_id: str = str(tc["id"])
                    try:
                        raw_args = tc["function"]["arguments"]
                        args: Any = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = cast(Dict[str, Any], {})
                    parsed_calls.append((tool_name, tool_id, args))

                _nudges = await _executor.execute_turn(
                    parsed_calls,
                    self._execute_single_tool,
                    messages,
                    PCM,
                    _limits,
                )
                for _n in _nudges:
                    messages.append(PCM(role="user", content=_n))

                # Check stop after tool execution
                if self._stop_requested:
                    log.info("[BRIDGE] Aborting remaining — stop requested")
                    break

                log.info(f"[BRIDGE] Tool results sent — continuing to turn {turn + 2}")

                # ── Phase 4: Auto-save session snapshot ──────────────────────
                # Save every 3 turns so we can resume if the app crashes/restarts.
                if turn > 0 and (turn + 1) % 3 == 0:
                    try:
                        from src.core.agent_session_manager import save_snapshot
                        save_snapshot(self)
                    except Exception as _ses_exc:
                        log.warning(f"[SESSION] Auto-save failed on turn {turn + 1}: {_ses_exc}")

                # ── Self-healing debug loop ──────────────────────────────────
                # Phase 2: If a command failed, enter structured debug cycle
                if self._debug_loop.should_enter(self._recent_tool_results):
                    self._debug_loop.enter_debug_cycle()
                    debug_nudge = self._debug_loop.build_nudge_message()
                    if debug_nudge:
                        log.info(
                            f"[DEBUG LOOP] Injecting debug nudge (cycle "
                            f"{self._debug_loop.cycle_count})"
                        )
                        messages.append(PCM(role="user", content=debug_nudge))
                        # Reset the stop flag so debug can proceed
                        self._stop_requested = False
                        # Continue the turn loop for debugging
                        continue

                # ── Track mutation progress ───────────────────────────────────
                # Check if any tool in this turn was a write/edit/bash operation
                _mutation_tools = {"Write", "Edit", "Bash", "NotebookEdit"}
                _turn_had_mutation = any(
                    (t_name in _mutation_tools) and self._tool_call_success.get(t_id, False)
                    for t_name, t_id, _ in parsed_calls
                )
                if _turn_had_mutation:
                    _mutation_turns += 1
                    _has_mutated = True  # Mark that mutation has occurred
                    _post_mutation_read_count = 0  # Reset read counter after mutation
                    
                    # Track which todo this mutation corresponds to
                    if self._current_todos:
                        # Find first IN_PROGRESS todo and verify it gets real work
                        for _todo in self._current_todos:
                            if _todo.get("status") == "IN_PROGRESS":
                                _todo["_mutation_count"] = _todo.get("_mutation_count", 0) + 1
                                log.info(
                                    f"[TODO] Mutation #{_todo['_mutation_count']} for todo: "
                                    + f"{_todo.get('content', 'unknown')[:50]}"
                                )
                                break
                
                # ── Post-mutation enforcement ─────────────────────────────────
                # After mutation, limit how many turns can be pure reading
                # This prevents AI from going backwards after making changes
                if _has_mutated:
                    _read_only_tools = {"Read", "Grep", "Glob", "LS"}
                    _turn_is_read_only = all(t_name in _read_only_tools for t_name, _, _ in parsed_calls)
                    if _turn_is_read_only:
                        _post_mutation_read_count = getattr(self, '_post_mutation_read_count', 0) + 1
                        self._post_mutation_read_count = _post_mutation_read_count
                        
                        if _post_mutation_read_count >= _POST_MUTATION_READ_LIMIT:
                            _verify_nudge = (
                                f"STOP READING. You already made file changes. Now you MUST:\n"
                                f"1. VERIFY your changes work (test in browser, run commands, etc.)\n"
                                f"2. COMPLETE remaining tasks\n"
                                f"3. Do NOT read more files unless absolutely necessary for debugging\n"
                                f"4. Use Bash to test, or Write/Edit to fix issues"
                            )
                            log.warning(
                                f"[BRIDGE] Post-mutation read limit reached ({_post_mutation_read_count} turns). "
                                + f"Injecting verification directive."
                            )
                            messages.append(PCM(role="user", content=_verify_nudge))
                    else:
                        # Reset counter if turn had non-read tools
                        self._post_mutation_read_count = 0
                
                # ── Aggressive action enforcement ─────────────────────────────
                # If agent hasn't mutated anything after N turns, inject strong nudge
                if turn + 1 >= _READONLY_FORCE_ACTION_TURN and _mutation_turns == 0:
                    _severity = "AGGRESSIVE" if (turn + 1 >= _AGGRESSIVE_NUDGE_TURN) else "STRONG"
                    if _severity == "AGGRESSIVE":
                        _action_nudge = (
                            f"CRITICAL: You have spent {turn + 1} turns ONLY reading files without making ANY changes. "
                            f"This is unacceptable. You MUST take action NOW:\n"
                            f"1. Summarize what you've learned in 2-3 sentences MAX\n"
                            f"2. IMMEDIATELY use Write or Edit to modify files\n"
                            f"3. Do NOT read any more files\n"
                            f"4. Start coding RIGHT NOW"
                        )
                    else:
                        _action_nudge = (
                            f"IMPORTANT: You've read multiple files across {turn + 1} turns but haven't written any code yet. "
                            f"Stop analyzing and START IMPLEMENTING. Use Write/Edit tools to make changes now. "
                            f"Reading more files won't complete the task - action will."
                        )
                    log.warning(f"[BRIDGE] {_severity} action nudge at turn {turn + 1} (no mutation yet)")
                    messages.append(PCM(role="user", content=_action_nudge))

                # ── Per-message budget enforcement ─────────────────────────────
                # Ported from Claude Code's enforceToolResultBudget().
                # Caps total tool results per turn to prevent N parallel tools
                # from collectively blowing up context.
                try:
                    from src.ai.tool_result_storage import enforce_tool_result_budget as _enforce_tool_result_budget
                    enforce_budget = cast(Callable[[List[Any], Any], List[Any]], _enforce_tool_result_budget)
                    _rep_state = self._tool_ctx.get_content_replacement_state()
                    messages = enforce_budget(messages, _rep_state)
                except Exception as _budget_err:
                    log.debug(f"[BRIDGE] Budget enforcement skipped: {_budget_err}")

                # Emit a paragraph break before the next turn's text so the UI
                # doesn't run the continuation sentence directly onto the previous
                # turn's last word (e.g. "fix this.Now let me check...").
                self.response_chunk.emit("\n\n")

            # ── Pending-todo continuation check with stale detection ──
            # If the turn loop ended with todos still PENDING/IN_PROGRESS,
            # check whether we're stuck in a loop (same todos, no progress).
            # After _MAX_STALE_CYCLES consecutive stale cycles, auto-cancel
            # the stuck todos instead of showing "Continue" again.
            #
            # IMPORTANT: Compare by CONTENT (not IDs) because the model
            # often creates fresh todos with new IDs each cycle even when
            # the actual tasks are identical.  Also track the count of
            # pending items — if the count stays the same or increases
            # across cycles, that's a strong stale signal.
            if not self._stop_requested:
                _pending_todos: List[Dict[str, Any]] = [
                    t for t in self._current_todos
                    if str(t.get('status', '')).upper() in ('PENDING', 'IN_PROGRESS')
                ]
                if _pending_todos:
                    # Use content-based fingerprint instead of IDs
                    _cur_fingerprint = set(
                        str(t.get('content', t.get('description', ''))).strip().lower()[:80]
                        for t in _pending_todos
                    )
                    _cur_count = len(_pending_todos)

                    # Stale if: same content OR same/higher count of pending items
                    _content_same = (_cur_fingerprint == self._last_pending_ids)
                    _count_same = (_cur_count >= getattr(self, '_last_pending_count', 0))
                    # Both checks together = high confidence of no progress
                    if _content_same or (_count_same and self._continue_cycle_count > 0):
                        self._continue_cycle_count += 1
                    else:
                        self._continue_cycle_count = 1
                    self._last_pending_ids = _cur_fingerprint
                    self._last_pending_count = _cur_count

                    if self._continue_cycle_count >= self._MAX_STALE_CYCLES:
                        log.warning(
                            f'[BRIDGE] Stale continue detected: same {len(_pending_todos)} todo(s) pending for {self._continue_cycle_count} cycles — auto-cancelling to prevent infinite loop'
                        )
                        # Auto-cancel the stuck todos
                        for t in self._current_todos:
                            if str(t.get('status', '')).upper() in ('PENDING', 'IN_PROGRESS'):
                                t['status'] = 'CANCELLED'
                        
                        # CRITICAL: Mark that todos were auto-cancelled (not completed)
                        # This prevents false "task complete" notifications
                        self._todos_auto_cancelled = True
                        # Ensure the UI and system notifications do not claim completion
                        self._allow_notification = False
                        try:
                            self.todos_updated.emit(list(self._current_todos), "")
                        except Exception:
                            pass
                        try:
                            _total = len(self._current_todos)
                            _completed = sum(
                                1 for t in self._current_todos
                                if t.get("status") in ("COMPLETE", "CANCELLED")
                            )
                            _pct = int((_completed / _total) * 100) if _total > 0 else 0
                            self.task_progress_update.emit(
                                _completed, _total, _pct, f"{_completed}/{_total} tasks complete ({_pct}%)"
                            )
                        except Exception:
                            pass
                        
                        self._continue_cycle_count = 0
                        self._last_pending_ids = set()
                        # Emit a final note to the user
                        self._safe_emit(
                            self.response_chunk,
                            f'\n\n---\n*Remaining tasks were auto-cancelled after repeated attempts without progress. You can start a new request if needed.*\n'
                        )
                    else:
                        log.info(
                            f'[BRIDGE] {len(_pending_todos)} todos still pending after turn loop (cycle {self._continue_cycle_count}/{self._MAX_STALE_CYCLES}) — emitting turn_limit_hit'
                        )
                        self._safe_emit(self.turn_limit_hit, _pending_todos)
                else:
                    # All done — reset stale tracking
                    self._continue_cycle_count = 0
                    self._last_pending_ids = set()

            # ── Phase 4: Save/clear snapshot on session exit ────────────
            try:
                from src.core.agent_session_manager import save_snapshot, clear_snapshot
                _pending = [t for t in self._current_todos
                            if t.get("status") in ("PENDING", "IN_PROGRESS")]
                if _pending:
                    # Still has pending work — save snapshot for resume later
                    save_snapshot(self)
                else:
                    # All done — clean up snapshot
                    clear_snapshot()
            except Exception as _ses_exc:
                log.warning(f"[SESSION] Exit save failed: {_ses_exc}")

            return full_response

        except Exception as exc:
            log.error(f"[BRIDGE] _call_llm failed: {exc}", exc_info=True)
            raise  # Let _handle_chat route this through error_occurred → onError in JS

    async def call_llm(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        images: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Public wrapper for _call_llm.
        Provides controlled access for inner classes (AgentWorker).
        """
        return await self._call_llm(message, context, images)

    def _safe_emit(self, signal: Any, *args: Any) -> None:
        """Emit a PyQt signal only if the C++ object is still alive."""
        try:
            from PyQt6.sip import isdeleted
            if isdeleted(self):
                return
        except ImportError:
            pass  # sip not available, assume object is alive
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # C++ object deleted during emit

    def _build_activity_info(
        self, activity: str, tool_name: str, args: Dict[str, Any],
        result_str: Optional[str], status: str,
    ) -> str:
        """Build structured JSON info for tool_activity signal.

        Returns a JSON string with rich details for the UI to render
        Cursor-style activity cards (file paths, line ranges, match results).
        """
        info: Dict[str, Any] = {}
        try:
            fp_raw = args.get("file_path")
            if not isinstance(fp_raw, str) or not fp_raw:
                fp_raw = args.get("path")
            fp = fp_raw if isinstance(fp_raw, str) else ""
            # Make paths relative to project root for compact display
            if fp and self._project_root:
                try:
                    rel = os.path.relpath(fp, self._project_root)
                    if not rel.startswith('..'):
                        fp = rel.replace('\\', '/')
                except ValueError:
                    pass

            if activity == "read_file":
                info["file_path"] = fp
                requested_offset_raw = args.get("offset", 1)
                requested_limit_raw = args.get("limit")
                requested_offset = (
                    requested_offset_raw
                    if isinstance(requested_offset_raw, int) and requested_offset_raw >= 1
                    else 1
                )
                requested_limit = (
                    requested_limit_raw
                    if isinstance(requested_limit_raw, int) and requested_limit_raw > 0
                    else _get_default_read_chunk_lines()
                )
                info["offset"] = requested_offset
                info["limit"] = requested_limit
                info["requested_offset"] = requested_offset
                info["requested_limit"] = requested_limit
                if status == "complete" and result_str:
                    try:
                        parsed = json.loads(result_str)
                    except Exception:
                        parsed = None

                    if isinstance(parsed, dict):
                        parsed_map = cast(Dict[str, Any], parsed)
                        start_line = parsed_map.get("start_line")
                        num_lines = parsed_map.get("num_lines")
                        total_lines = parsed_map.get("total_lines")

                        if isinstance(start_line, int) and start_line >= 1:
                            info["offset"] = start_line
                            info["actual_start_line"] = start_line
                        if isinstance(num_lines, int) and num_lines > 0:
                            info["limit"] = num_lines
                            info["lines_read"] = num_lines
                            if isinstance(start_line, int) and start_line >= 1:
                                info["actual_end_line"] = start_line + num_lines - 1
                        if isinstance(total_lines, int) and total_lines >= 0:
                            info["total_lines"] = total_lines
                            if isinstance(start_line, int) and isinstance(num_lines, int):
                                end_line = start_line + num_lines - 1
                                if end_line < total_lines:
                                    info["remaining_lines"] = total_lines - end_line
                                    info["remaining_range"] = str(end_line + 1) + "-" + str(total_lines)

                        _parsed_content = parsed_map.get("content")
                        if "lines_read" not in info and isinstance(_parsed_content, str):
                            _content: str = _parsed_content
                            info["lines_read"] = _content.count('\n') + (1 if _content else 0)
                    else:
                        info["lines_read"] = result_str.count('\n') + (1 if result_str else 0)
                if status == "error" and result_str:
                    info["error"] = result_str[:400]

            elif activity == "edit_file":
                info["file_path"] = fp
                old_s = args.get("old_string", "")
                new_s = args.get("new_string", "")
                if old_s and new_s:
                    info["description"] = "Editing"
                elif new_s:
                    info["description"] = "Editing"
                else:
                    info["description"] = "Deleting lines"

            elif activity in ("write_file", "create_file"):
                info["file_path"] = fp
                content = args.get("content", "")
                info["lines"] = content.count('\n') + 1 if content else 0
                info["description"] = "Creating" if activity == "create_file" else "Writing"

            elif activity == "search":
                # Grep tool
                info["search_type"] = (tool_name or "Grep").lower()
                info["pattern"] = args.get("pattern", "")
                info["path"] = fp or "."
                info["glob"] = args.get("glob", "")
                info["include"] = args.get("glob", args.get("include", ""))
                if status == "complete" and result_str:
                    matches: List[Dict[str, Any]] = self._parse_grep_matches(result_str)
                    info["match_count"] = len(matches)
                    info["matches"] = matches[:15]  # limit for UI

            elif activity == "list_directory":
                info["search_type"] = (tool_name or "LS").lower()
                info["path"] = fp or args.get("path", ".")
                info["pattern"] = args.get("pattern", "")
                if status == "complete" and result_str:
                    # Count files from result
                    lines = [l for l in result_str.split('\n') if l.strip()]
                    info["count"] = len(lines)

            elif activity == "run_command":
                cmd = args.get("command", "")
                info["command"] = cmd[:200] if cmd else ""
                info["timeout"] = args.get("timeout", "")
                # Include sandbox/container state so UI can show whether this
                # command is running in sandboxed container or local shell.
                try:
                    from src.agent.src.utils.sandbox.sandbox_adapter import SandboxManager
                    sandbox_enabled = bool(SandboxManager.is_sandbox_enabled_in_settings())
                    sandbox_runtime_enabled = bool(SandboxManager.is_sandboxing_enabled())
                    unavailable_reason = str(SandboxManager.get_sandbox_unavailable_reason() or "")
                except Exception:
                    sandbox_enabled = False
                    sandbox_runtime_enabled = False
                    unavailable_reason = ""
                info["sandbox_enabled"] = sandbox_enabled
                info["sandbox_runtime_enabled"] = sandbox_runtime_enabled
                info["sandbox_active"] = bool(sandbox_enabled and sandbox_runtime_enabled)
                if unavailable_reason:
                    info["sandbox_unavailable_reason"] = unavailable_reason
                if status in ("complete", "error") and result_str:
                    info["output"] = result_str[:2000]

            elif activity in ("team_create", "team_delete"):
                info["team_name"] = args.get("name", "")
                if status == "complete" and result_str:
                    try:
                        parsed = json.loads(result_str)
                        if isinstance(parsed, dict):
                            parsed_map = cast(Dict[str, Any], parsed)
                            info["team_id"] = parsed_map.get("teamId", "")
                            info["message"] = parsed_map.get("message", "")
                    except Exception:
                        pass

            elif activity in ("task_create", "task_update", "task_list", "task_get", "task_stop"):
                info["task_id"] = args.get("taskId", "")
                info["subject"] = args.get("subject", "")
                if status == "complete" and result_str:
                    try:
                        parsed = json.loads(result_str)
                        if isinstance(parsed, dict):
                            parsed_map = cast(Dict[str, Any], parsed)
                            info["message"] = parsed_map.get("message", "")
                            info["task_id"] = parsed_map.get("taskId", info["task_id"])
                    except Exception:
                        pass

            else:
                # Fallback: pass raw args
                info = {"raw": json.dumps(args)[:400]}

        except Exception as e:
            log.debug(f"[BRIDGE] _build_activity_info error: {e}")
            info = {"raw": json.dumps(args)[:400]}

        if status == "error" and result_str and "error" not in info:
            info["error"] = result_str[:400]

        return json.dumps(info)

    def _parse_grep_matches(self, result_str: str) -> List[Dict[str, Any]]:
        """Parse grep/search result into structured match list for UI."""
        matches: List[Dict[str, Any]] = []
        try:
            # Try JSON parse first (real Grep tool returns structured results)
            data = json.loads(result_str)
            if isinstance(data, str):
                # Plain text result — parse line-by-line
                for line in data.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    # Format: "path/to/file.py:123: matched text"
                    parts = line.split(':', 2)
                    if len(parts) >= 2:
                        fpath = parts[0].strip()
                        try:
                            lineno = int(parts[1].strip())
                        except ValueError:
                            lineno = 0
                        fname = fpath.split('/')[-1].split('\\')[-1]
                        matches.append({"file": fname, "line": lineno, "path": fpath})
            elif isinstance(data, list):
                data_list: List[Any] = cast(List[Any], data)
                for item in data_list[:15]:
                    if isinstance(item, str):
                        fname = item.split('/')[-1].split('\\')[-1]
                        matches.append({"file": fname, "line": 0, "path": item})
            elif isinstance(data, dict):
                # Possible {files: [...]} or {matches: [...]}
                data_map = cast(Dict[str, Any], data)
                items_any = data_map.get('files')
                if not isinstance(items_any, list):
                    items_any = data_map.get('matches')
                if not isinstance(items_any, list):
                    items_any = data_map.get('results')
                items: List[Any] = cast(List[Any], items_any) if isinstance(items_any, list) else []
                if items:
                    for item in items[:15]:
                        if isinstance(item, str):
                            fname = item.split('/')[-1].split('\\')[-1]
                            matches.append({"file": fname, "line": 0, "path": item})
        except (json.JSONDecodeError, TypeError):
            # Plain text — parse lines
            for line in result_str.split('\n')[:15]:
                line = line.strip()
                if not line or line.startswith('---') or line.startswith('==='):
                    continue
                parts = line.split(':', 2)
                if len(parts) >= 2:
                    fpath = parts[0].strip()
                    try:
                        lineno = int(parts[1].strip())
                    except ValueError:
                        lineno = 0
                    fname = fpath.split('/')[-1].split('\\')[-1]
                    matches.append({"file": fname, "line": lineno, "path": fpath})
                else:
                    matches.append({"file": line[:60], "line": 0, "path": line})
        return matches

    async def _execute_single_tool(
        self,
        tool_name: str,
        tool_id: str,
        args: Dict[str, Any],
        messages: List[Any],
        PCM: Type[Any],
        _limits: Optional[_ToolLimitsLike] = None,
    ) -> None:
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
            running_info = self._build_activity_info(activity, tool_name, args, None, "running")
            self._safe_emit(self.tool_activity, activity, running_info, "running")

        result: ToolResult = cast(ToolResult, await self._dispatch_tool(tool_name, tool_id, args))

        try:
            self._tool_call_success[tool_id] = bool(result.success)
        except Exception:
            pass

        # ── Record in circuit breaker ────────────────────────────────
        _error_text = str(result.error) if not result.success and result.error else ""
        self._tool_circuit_breaker.record_call(tool_name, result.success, _error_text)

        if result.success:
            if tool_name in ("Write", "Edit", "Bash"):
                self._mutation_success_count += 1
                self._session_mutation_count += 1  # Persistent session counter
                log.debug(
                    f"[MUTATION] Turn mutation: {self._mutation_success_count}, "
                    f"Session mutation: {self._session_mutation_count}"
                )
            result_payload: Any = result.result
            if isinstance(result_payload, dict):
                result_str = json.dumps(cast(Dict[str, Any], result_payload))
            elif isinstance(result_payload, list):
                result_str = json.dumps(cast(List[Any], result_payload))
            else:
                result_str = str(result_payload)
            if not _silent:
                complete_info = self._build_activity_info(activity, tool_name, args, result_str, "complete")
                self._safe_emit(self.tool_activity, activity, complete_info, "complete")
        else:
            result_str = f"Error: {result.error}"
            if not _silent:
                error_info = self._build_activity_info(activity, tool_name, args, result_str, "error")
                self._safe_emit(self.tool_activity, activity, error_info, "error")

        # ── Track tool results for verification enforcement ────────────────
        _exit_code: Optional[int] = None
        if tool_name in ("Bash", "PowerShell", "LS"):
            try:
                _raw = result.result if hasattr(result, 'result') else None
                if isinstance(_raw, dict):
                    _exit_code = _raw.get("exit_code") or _raw.get("exitCode")
            except Exception:
                pass
        self._recent_tool_results.append((tool_name, bool(result.success), result_str[:200], _exit_code))
        if len(self._recent_tool_results) > self._max_recent_results:
            self._recent_tool_results = self._recent_tool_results[-self._max_recent_results:]

        # Feed result back to LLM — persist large results to disk instead of truncating.
        # Ported from Claude Code's toolResultStorage.ts: results exceeding
        # the threshold are saved to disk; LLM gets a 2KB preview + file path.
        # Falls back to truncation if persistence fails.
        _MAX_TOOL_RESULT = (_limits.max_tool_result_chars if _limits is not None else 15_000)
        try:
            from src.ai.tool_result_storage import maybe_persist_large_result
            result_str_for_history = maybe_persist_large_result(
                result_str, tool_name, tool_id, threshold=_MAX_TOOL_RESULT
            )
        except Exception as _persist_err:
            log.debug(f"[BRIDGE] Persistence fallback: {_persist_err}")
            # Fallback: simple truncation
            if len(result_str) > _MAX_TOOL_RESULT:
                result_str_for_history = (
                    result_str[:_MAX_TOOL_RESULT]
                    + f"\n... [truncated: {len(result_str) - _MAX_TOOL_RESULT} chars omitted]"
                )
            else:
                result_str_for_history = result_str
        messages.append(
            PCM(role="tool", content=result_str_for_history, tool_call_id=tool_id)
        )

        # Invalidate file read cache for write/edit tools so next Read sees fresh content
        if tool_name in ("Write", "Edit"):
            _wp = args.get("file_path", "")
            if _wp:
                if not os.path.isabs(_wp) and self._project_root:
                    _wp = os.path.join(self._project_root, _wp)
                self._tool_ctx.file_cache_invalidate(_wp)

    # ── Test framework detection and verification ─────────────────
    # Phase 1: Replace keyword-nudge verification with actual test
    # execution analysis.  See plan: frolicking-singing-garden.md

    _TEST_CONFIG_FILES: Dict[str, Tuple[str, ...]] = {
        "pytest":       ("pytest.ini", "setup.cfg", "pyproject.toml", "tox.ini"),
        "unittest":     ("",),  # built-in; always available
        "node":         ("package.json",),
        "jest":         ("jest.config.js", "jest.config.ts", "jest.config.mjs"),
        "go test":      ("go.mod",),
        "cargo test":   ("Cargo.toml",),
    }

    _TEST_COMMAND_PATTERNS: Dict[str, str] = {
        "pytest":       r"\bpytest\b",
        "unittest":     r"python\s+-m\s+unittest\b",
        "node":         r"(?:npm|yarn|pnpm)\s+(?:test|run\s+test)",
        "jest":         r"\bnpx\s+jest\b|node_modules/\.bin/jest",
        "go test":      r"\bgo\s+test\b",
        "cargo test":   r"\bcargo\s+test\b",
    }

    def _detect_test_framework(self) -> Optional[str]:
        """Detect which test framework the project uses by scanning for config files.

        Scans from project root, lazily caching result. Returns None if no
        recognised framework is detected.
        """
        if self._test_framework_checked:
            return self._test_framework
        self._test_framework_checked = True

        root = self._project_root or os.getcwd()
        try:
            for framework, config_files in self._TEST_CONFIG_FILES.items():
                for cfg in config_files:
                    if not cfg:
                        continue
                    candidate = os.path.join(root, cfg)
                    if os.path.isfile(candidate):
                        self._test_framework = framework
                        log.info(f"[VERIFY] Detected test framework: {framework} (via {cfg})")
                        return framework
                    # Also check pyproject.toml content for [tool.pytest]
                    if cfg == "pyproject.toml":
                        try:
                            with open(candidate, "r", encoding="utf-8") as fh:
                                content = fh.read()
                            if "[tool.pytest" in content:
                                self._test_framework = "pytest"
                                log.info(f"[VERIFY] Detected test framework: pytest (via pyproject.toml)")
                                return "pytest"
                            if "[tool.jest" in content:
                                self._test_framework = "jest"
                                return "jest"
                        except Exception:
                            pass
        except Exception as exc:
            log.warning(f"[VERIFY] Error detecting test framework: {exc}")

        self._test_framework = "unknown"
        return None

    def _check_recent_tool_results_for_tests(self) -> Tuple[bool, str]:
        """Scan recent tool results for test/verification commands and their outcomes.

        Returns:
            (was_tested: bool, message: str)
            - was_tested=True + message="": Tests passed
            - was_tested=True + message!="": Tests ran but failed
            - was_tested=False + message: No tests found (explanation)
        """
        # Count how many of the last N results are test runs
        test_tool_names = {"Bash", "PowerShell", "LS"}
        recent = self._recent_tool_results[-15:]  # Look at last 15 tools

        test_runs: List[Tuple[str, bool, str, Optional[int]]] = []
        for entry in reversed(recent):
            t_name, success, preview, exit_code = entry
            if t_name not in test_tool_names:
                continue
            # Detect test commands in the preview
            preview_lower = preview.lower()
            is_test = any(
                re.search(pat, preview_lower)
                for pat in [r"\bpytest\b", r"python\s+-m\s+pytest", r"python\s+-m\s+unittest",
                            r"\bnpm\s+test", r"\byarn\s+test", r"go\s+test", r"cargo\s+test",
                            r"\bnpx\s+jest", r"\brun\s+test", r"verify"]
            )
            if is_test:
                test_runs.append((t_name, success, preview[:150], exit_code))

        if not test_runs:
            return False, "No test or verification commands found in recent tool results."

        # Check if any test run failed
        failed_runs = [(n, p, ec) for n, s, p, ec in test_runs if not s]
        if failed_runs:
            t_name, preview, exit_code = failed_runs[0]
            details = preview.strip()
            return True, (
                f"Test/verification command FAILED ({t_name}):\n"
                f"  {details}\n"
                f"  Exit code: {exit_code}\n\n"
                "Fix the issue before marking tasks complete."
            )

        # All test runs succeeded
        return True, ""

    def _build_verification_message(self) -> Optional[str]:
        """Build a verification-required error message if tests haven't passed.

        Returns None if verification is satisfied, or an error string to block completion.
        """
        # Quick pass: if no mutations were made, verification is not needed
        if self._mutation_success_count == 0 and self._session_mutation_count == 0:
            return None

        # Check if tests were run and passed
        was_tested, test_msg = self._check_recent_tool_results_for_tests()

        # Detect framework for the suggestion
        framework = self._detect_test_framework()
        framework_suggestion = ""
        if framework and framework != "unknown":
            if framework == "pytest":
                framework_suggestion = "python -m pytest"
            elif framework == "unittest":
                framework_suggestion = "python -m unittest discover"
            elif framework == "node":
                framework_suggestion = "npm test"
            elif framework == "jest":
                framework_suggestion = "npx jest"
            elif framework == "go test":
                framework_suggestion = "go test ./..."
            elif framework == "cargo test":
                framework_suggestion = "cargo test"
            else:
                framework_suggestion = "python -m pytest"
        else:
            framework_suggestion = "python -m pytest"

        if was_tested and not test_msg:
            return None  # Tests ran and passed — verification satisfied

        if was_tested and test_msg:
            # Tests ran but failed
            return (
                f"VERIFICATION FAILED: Your changes produced test/verification failures.\n\n"
                f"Details: {test_msg}\n\n"
                f"Fix the failing tests before marking tasks complete."
            )

        # No tests found — require them
        return (
            f"VERIFICATION REQUIRED: You've made changes, but no tests or verification "
            f"commands were detected.\n\n"
            f"Before marking tasks complete, you MUST:\n"
            f"1. Run tests to verify your changes work\n"
            f"2. Run your app to verify it still functions\n"
            f"3. Fix any issues found\n\n"
            f"Suggested command: {framework_suggestion}"
        )

    # ── Task Graph Sync ───────────────────────────────────────────────

    def _sync_tasks_to_graph(self) -> None:
        """Bulk-sync all existing _session_tasks into the task graph.

        Called after session restore to populate the graph from flat task dicts.
        """
        if not self._session_tasks:
            return
        from src.core.task_graph import TaskNode, TaskStatus
        for task_id, task in self._session_tasks.items():
            if self._task_graph.has_node(task_id):
                continue
            status_kind = TaskStatus.from_str(task.get("status", "pending"))
            node = TaskNode(
                id=task_id,
                subject=task.get("subject", ""),
                description=task.get("description", ""),
                status=status_kind,
                active_form=task.get("activeForm"),
                owner=task.get("owner"),
                parent_id=task.get("parentId"),
                depends_on=list(task.get("dependsOn", []) or task.get("blockedBy", [])),
                estimated_effort=task.get("estimatedEffort"),
            )
            self._task_graph.add_node(node)

    # ── Phase 4: Session restore ──────────────────────────────────

    def _hydrate_from_snapshot(self, snapshot: dict) -> None:
        """Restore session state from a previously saved snapshot.

        Called during __init__ when a snapshot file is found on disk.
        Restores the task graph, mutation counters, debug loop, and tool
        circuit breaker state. Does NOT restore full conversation history.
        """
        # Tasks
        saved_tasks: dict = snapshot.get("session_tasks", {})
        if saved_tasks:
            self._session_tasks.update(saved_tasks)
            log.info(f"[SESSION] Restored {len(saved_tasks)} session tasks")

        # Task graph
        saved_graph: dict = snapshot.get("task_graph", {})
        if saved_graph and saved_graph.get("nodes"):
            try:
                from src.core.task_graph import TaskGraph
                self._task_graph = TaskGraph.from_dict(saved_graph)
                log.info(f"[SESSION] Restored task graph: {self._task_graph.get_task_count()} nodes")
            except Exception as e:
                log.warning(f"[SESSION] Failed to restore task graph: {e}")

        # Todos
        saved_todos: list = snapshot.get("current_todos", [])
        if saved_todos:
            self._current_todos.clear()
            self._current_todos.extend(saved_todos)
            log.info(f"[SESSION] Restored {len(saved_todos)} todos")

        # Mutation counters
        self._session_mutation_count = snapshot.get("session_mutation_count", 0)
        self._mutation_success_count = snapshot.get("mutation_success_count", 0)

        # Tool circuit breaker
        disabled = snapshot.get("disabled_tools", [])
        if disabled:
            self._disabled_tools = set(disabled)
            log.info(f"[SESSION] Restored {len(disabled)} disabled tools: {disabled}")

        tool_fails: dict = snapshot.get("tool_fail_counts", {})
        if tool_fails:
            self._tool_fail_counts.update(tool_fails)

        # Recent tool results (last 10 for context continuity)
        recent: list = snapshot.get("recent_tool_results", [])
        if recent:
            self._recent_tool_results = list(recent)[-10:]

        # Debug loop
        dl_data: dict = snapshot.get("debug_loop", {})
        if dl_data and dl_data.get("state", "idle") != "idle":
            try:
                from src.core.debug_loop import DebugLoopState
                dl_state = DebugLoopState(dl_data.get("state", "idle"))
                self._debug_loop.cycle_count = dl_data.get("cycle_count", 0)
                self._debug_loop.state = dl_state
                self._debug_loop.failed_tool_name = dl_data.get("failed_tool_name", "")
                self._debug_loop.failed_exit_code = dl_data.get("failed_exit_code")
                self._debug_loop.failed_preview = dl_data.get("failed_preview", "")
                self._debug_loop.failed_command = dl_data.get("failed_command", "")
                self._debug_loop.last_fix_summary = dl_data.get("last_fix_summary", "")
                log.info(f"[SESSION] Restored debug loop: state={dl_state}, cycles={self._debug_loop.cycle_count}")
            except Exception as e:
                log.warning(f"[SESSION] Failed to restore debug loop: {e}")

        # Inject resume marker into conversation history
        saved_at = snapshot.get("saved_at", 0)
        task_count = len(saved_tasks)
        mutation_count = snapshot.get("session_mutation_count", 0)
        resume_msg = (
            f"[System: Session resumed from {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(saved_at))}. "
            f"{mutation_count} mutations had been made, {task_count} tasks were in progress. "
            f"Continuing from previous state.]"
        )
        self._conversation_history.append(
            ChatMessage(role="system", content=resume_msg)
        )
        log.info(f"[SESSION] Injected resume marker: {resume_msg[:80]}...")

    def _rollback_last_change(self) -> Optional[str]:
        """Roll back the last change group via the change orchestrator.

        Used by the debug loop to revert failed changes. Returns a summary
        string if a rollback occurred, or None if there was nothing to roll back.
        """
        try:
            from src.core.change_orchestrator import get_change_orchestrator
            orch = get_change_orchestrator()
            if orch.can_undo():
                group = orch.undo()
                if group:
                    summary = group.description or f"{len(group)} file(s)"
                    log.info(f"[DEBUG LOOP] Rolled back: {summary}")
                    return summary
        except Exception as exc:
            log.warning(f"[DEBUG LOOP] Rollback failed: {exc}")
        return None

    # ── Tool dispatch ──────────────────────────────────────────

    async def _dispatch_tool(
        self, tool_name: str, tool_id: str, args: Dict[str, Any]
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
            # ── Autonomy gate (Phase 8) ────────────────────────────────────
            try:
                from src.core.autonomy_manager import get_autonomy_manager
                _auto_mgr = get_autonomy_manager()
                if _auto_mgr.get_level().value != "ask":
                    decision = _auto_mgr.check_action(tool_name, args)
                    if decision.requires_permission:
                        log.info(f"[AUTONOMY] Blocked {tool_name} (mode={decision.autonomy_level.value}): {decision.reason}")
                        return ToolResult(
                            tool_id=tool_id,
                            result=None,
                            success=False,
                            error=(
                                f"[Autonomy] Action requires permission: {decision.reason}. "
                                f"Current mode: {decision.autonomy_level.value.upper()}. "
                                f"Switch to ASK mode or adjust autonomy level."
                            ),
                        )
            except ImportError:
                pass
            except Exception as exc:
                log.debug(f"[AUTONOMY] Gate check skipped: {exc}")

            # Track TodoWrite streaks so we can short-circuit planning loops.
            if tool_name == "TodoWrite":
                self._todo_write_streak += 1
            else:
                self._todo_write_streak = 0

            # ---- Dispatch via registry map (Phase B) ----
            _TOOL_DISPATCH_MAP = {
                "Read":            self._dispatch_read,
                "Write":           self._dispatch_write,
                "Edit":            self._dispatch_edit,
                "Glob":            self._dispatch_glob,
                "Grep":            self._dispatch_grep,
                "TodoWrite":       self._dispatch_todo_write,
                "AskUserQuestion": self._dispatch_ask_user_question,
                "LSP":             self._dispatch_lsp,
                "WebFetch":        self._dispatch_web_fetch,
                "WebSearch":       self._dispatch_web_search,
                "TaskCreate":      self._dispatch_task_create,
                "TaskUpdate":      self._dispatch_task_update,
                "TaskList":        self._dispatch_task_list,
                "TaskGet":         self._dispatch_task_get,
                "TaskStop":        self._dispatch_task_stop,
                "MCP":             self._dispatch_mcp,
                "TeamCreate":      self._dispatch_team_create,
                "TeamDelete":      self._dispatch_team_delete,
            }

            handler = _TOOL_DISPATCH_MAP.get(tool_name)
            if handler is not None:
                return await handler(tool_id, args)

            # ---- Bridge-native tools with special pre-processing ----
            if tool_name == "Bash":
                command = args.get("command", "")
                # Check sandbox policy if enabled (lazy init)
                if self._sandbox_manager is None:
                    try:
                        from src.core.sandbox_manager import get_sandbox_manager
                        self._sandbox_manager = get_sandbox_manager()
                    except Exception:
                        pass
                if self._sandbox_manager and self._sandbox_manager.is_enabled():
                    allowed, reason = self._sandbox_manager.is_command_allowed(command)
                    if not allowed:
                        result = ToolResult(
                            tool_id=tool_id,
                            result=None,
                            success=False,
                            error=f"[Sandbox] Command blocked: {reason}",
                        )
                        return result
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

    async def _dispatch_read(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """Dispatch to real FileReadTool or bridge-native fallback."""
        path = args.get("file_path", "")
        if not os.path.isabs(path) and self._project_root:
            args = {**args, "file_path": os.path.join(self._project_root, path)}
        if args.get("limit") in (None, "", 0):
            args = {**args, "limit": _get_default_read_chunk_lines()}
        if self._tool_ctx.is_context_over_budget():
            _basename = os.path.basename(args.get("file_path", path))
            _remaining = self._tool_ctx.get_remaining_budget_chars()
            return ToolResult(
                tool_id=tool_id, result=None, success=False,
                error=(
                    f"Context budget nearly exhausted. Remaining: ~{_remaining:,} chars. "
                    f"Do NOT read full files. Use small chunks only, e.g. "
                    f"Read(file_path='{_basename}', offset=1, limit=50)."
                )
            )

        # ── FILE READ DEDUP (ported from Claude Code's fileStateCache.ts) ───
        # If we already read this file with same offset/limit and it hasn't
        # changed on disk, return a stub instead of the full content.
        _fpath_resolved = args.get("file_path", "")
        _norm = os.path.normpath(os.path.abspath(_fpath_resolved)) if _fpath_resolved else ""
        _req_offset = args.get("offset")
        _req_limit = args.get("limit")
        if _norm and os.path.isfile(_norm):
            _cached = self._tool_ctx.file_cache_get(_norm, _req_offset, _req_limit)
            if _cached is not None:
                return ToolResult(tool_id=tool_id, result={
                    "path": _fpath_resolved,
                    "content": _cached,
                    "cached": True,
                })

        if self._real_read_tool is not None:
            try:
                raw = await self._real_read_tool.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                data = raw.get("data")
                start_line: Optional[int] = None
                num_lines: Optional[int] = None
                total_lines: Optional[int] = None
                content: str = ""

                # Extract text content for LLM from the FileReadOutput
                if hasattr(data, "file") and hasattr(data.file, "content"):
                    content_raw = getattr(data.file, "content", "")
                    content = content_raw if isinstance(content_raw, str) else str(content_raw)
                    start_raw = getattr(data.file, "start_line", None)
                    num_raw = getattr(data.file, "num_lines", None)
                    total_raw = getattr(data.file, "total_lines", None)
                    start_line = start_raw if isinstance(start_raw, int) else None
                    num_lines = num_raw if isinstance(num_raw, int) else None
                    total_lines = total_raw if isinstance(total_raw, int) else None
                elif isinstance(data, dict):
                    data_map = cast(Dict[str, Any], data)
                    if "content" in data_map:
                        content_raw = data_map.get("content", "")
                        content = content_raw if isinstance(content_raw, str) else str(content_raw)
                        start_raw = data_map.get("start_line")
                        num_raw = data_map.get("num_lines")
                        total_raw = data_map.get("total_lines")
                        start_line = start_raw if isinstance(start_raw, int) else None
                        num_lines = num_raw if isinstance(num_raw, int) else None
                        total_lines = total_raw if isinstance(total_raw, int) else None
                    else:
                        file_any = data_map.get("file")
                        if isinstance(file_any, dict):
                            file_obj = cast(Dict[str, Any], file_any)
                            content_raw = file_obj.get("content", "")
                            content = content_raw if isinstance(content_raw, str) else str(content_raw)
                            start_raw = file_obj.get("start_line")
                            num_raw = file_obj.get("num_lines")
                            total_raw = file_obj.get("total_lines")
                            start_line = start_raw if isinstance(start_raw, int) else None
                            num_lines = num_raw if isinstance(num_raw, int) else None
                            total_lines = total_raw if isinstance(total_raw, int) else None
                        else:
                            content = str(data_map)
                else:
                    content = str(data)
                if start_line is None:
                    start_line = args.get("offset", 1)
                effective_limit = args.get("limit")
                if effective_limit is None and isinstance(num_lines, int) and num_lines >= 0:
                    effective_limit = num_lines
                _remaining_chars = self._tool_ctx.get_remaining_budget_chars()
                if len(content) > _remaining_chars:
                    _basename = os.path.basename(args.get("file_path", "file"))
                    return ToolResult(
                        tool_id=tool_id, result=None, success=False,
                        error=(
                            f"Read output too large for current context budget "
                            f"({len(content):,} chars > ~{_remaining_chars:,} remaining). "
                            f"Read a smaller chunk: Read(file_path='{_basename}', offset={start_line}, limit=80)."
                        )
                    )
                # Track file state
                self._tool_ctx.mark_file_read(args["file_path"])
                self._tool_ctx.track_file_read(args["file_path"], len(content))
                warnings = self._tool_ctx.get_budget_warnings()
                if warnings:
                    log.warning(f"[CTX] Budget warnings: {warnings}")
                # Sync into context.read_file_state so FileEditTool's staleness check passes
                try:
                    _norm = os.path.abspath(args["file_path"])
                    self._tool_ctx.read_file_state[_norm] = {
                        "content": content,
                        "timestamp": os.path.getmtime(args["file_path"]),
                        "offset": start_line,
                        "limit": effective_limit,
                    }
                    # Populate LRU dedup cache
                    self._tool_ctx.file_cache_put(
                        _norm, content, os.path.getmtime(args["file_path"]),
                        start_line, effective_limit
                    )
                except Exception:
                    pass
                result_payload: Dict[str, Any] = {
                    "path": args["file_path"],
                    "content": content,
                    "start_line": start_line,
                    "num_lines": num_lines if isinstance(num_lines, int) else (content.count('\n') + (1 if content else 0)),
                    "total_lines": total_lines,
                }
                return ToolResult(tool_id=tool_id, result=result_payload)
            except Exception as exc:
                _err_str = str(exc)
                _err_lower = _err_str.lower()
                _SIZE_KEYWORDS = (
                    'exceeds maximum allowed tokens', 'maximum allowed tokens',
                    'token limit', 'file too large', 'too large to read',
                )
                if any(kw in _err_lower for kw in _SIZE_KEYWORDS):
                    # ── SKELETON-FIRST READING for real tool size errors ──────
                    # Instead of passing the error to the LLM, try to generate
                    # a skeleton so it can still get useful structure info.
                    _fpath = args.get("file_path", "")
                    _basename = os.path.basename(_fpath)
                    try:
                        from src.ai.file_skeleton import generate_skeleton
                        skeleton = generate_skeleton(_fpath)
                        if skeleton:
                            log.warning(f"[BRIDGE] FileReadTool size error → returning skeleton: {_err_str}")
                            self._tool_ctx.mark_file_read(_fpath)
                            return ToolResult(tool_id=tool_id, result={
                                "path": _fpath,
                                "content": skeleton,
                                "skeleton": True,
                                "hint": (
                                    f"This is a SKELETON view of {_basename}. "
                                    f"Use line numbers to read specific sections: "
                                    f"Read(file_path='{_basename}', offset=LINE_NUMBER, limit=80)"
                                )
                            })
                    except Exception as skel_err:
                        log.warning(f"[BRIDGE] Skeleton generation failed for size error: {skel_err}")
                    # Fallback: return the original error
                    log.warning(f"[BRIDGE] FileReadTool size error → returning to LLM: {_err_str}")
                    return ToolResult(tool_id=tool_id, result=None, success=False, error=_err_str)
                log.warning(f"[BRIDGE] Real FileReadTool failed, using fallback: {exc}")

        # Fallback: simple file read
        # Use the already-resolved (possibly absolute) path from args
        fpath = args.get("file_path", "")
        if not os.path.isabs(fpath) and self._project_root:
            fpath = os.path.join(self._project_root, fpath)

        # ── MODEL-AWARE SIZE GUARD (CRITICAL for context overflow prevention) ──────
        # Get model-specific limit from context
        _max_bytes = self._tool_ctx.file_reading_limits.get("maxSizeBytes", 40_000)
        _max_chars = self._tool_ctx.get_max_file_read_chars()
        
        # Check if context budget is running low
        if self._tool_ctx.is_context_over_budget():
            _basename = os.path.basename(fpath)
            _remaining = self._tool_ctx.get_remaining_budget_chars()
            return ToolResult(
                tool_id=tool_id, result=None, success=False,
                error=(
                    f"Context budget nearly exhausted. "
                    f"Remaining: ~{_remaining:,} chars. "
                    f"Use Grep to find specific sections, or read with small limit: "
                    f"Read(file_path='{_basename}', offset=1, limit=50)."
                )
            )
        
        try:
            _fsize = os.path.getsize(fpath)
            _has_pagination = args.get("offset") or args.get("limit")
            if _fsize > _max_bytes and not _has_pagination:
                # ── SKELETON-FIRST READING ─────────────────────────────
                # Instead of rejecting large files outright, return a
                # structural skeleton showing class/function definitions
                # with line numbers so the LLM can do targeted reads.
                _basename = os.path.basename(fpath)
                try:
                    from src.ai.file_skeleton import generate_skeleton
                    skeleton = generate_skeleton(fpath)
                    if skeleton:
                        log.info(f"[BRIDGE] Skeleton-first read for large file: {_basename} ({_fsize:,} bytes)")
                        self._tool_ctx.mark_file_read(fpath)
                        return ToolResult(tool_id=tool_id, result={
                            "path": fpath,
                            "content": skeleton,
                            "skeleton": True,
                            "hint": (
                                f"This is a SKELETON view of {_basename} ({_fsize:,} bytes). "
                                f"Use the line numbers above to read specific sections: "
                                f"Read(file_path='{_basename}', offset=LINE_NUMBER, limit=80)"
                            )
                        })
                except Exception as skel_err:
                    log.warning(f"[BRIDGE] Skeleton generation failed: {skel_err}")

                # Fallback if skeleton fails: return the old error message
                _model_id = getattr(self._tool_ctx, '_model_id', 'unknown')
                return ToolResult(
                    tool_id=tool_id, result=None, success=False,
                    error=(
                        f"File '{_basename}' ({_fsize:,} bytes / ~{_fsize // 4:,} tokens) "
                        f"exceeds model limit ({_max_bytes:,} bytes) for {_model_id}. "
                        f"CRITICAL: Use Grep to locate code, then read with pagination: "
                        f"Read(file_path='{_basename}', offset=1, limit=100). "
                        f"NEVER read large files without offset and limit. "
                        f"Model context window is limited - respect it."
                    )
                )
        except OSError:
            pass
        # ────────────────────────────────────────────────────────────────────────

        # ── SMART CHUNK-BASED READING (like Cursor/Copilot/Claude Code) ─────
        # Instead of dumping an entire file into context, check line count first.
        # If the file is large and no pagination was requested, return a skeleton
        # so the LLM can do targeted reads with offset/limit.
        _SKELETON_LINE_THRESHOLD = 250  # Files with more lines → skeleton-first
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            _has_pagination = args.get("offset") or args.get("limit")
            _total_lines = len(lines)

            # ── Skeleton-first for medium/large files without pagination ────
            if _total_lines > _SKELETON_LINE_THRESHOLD and not _has_pagination:
                _basename = os.path.basename(fpath)
                try:
                    from src.ai.file_skeleton import generate_skeleton
                    skeleton = generate_skeleton(fpath)
                    if skeleton:
                        log.info(f"[BRIDGE] Smart read: {_basename} has {_total_lines} lines → returning skeleton (threshold={_SKELETON_LINE_THRESHOLD})")
                        self._tool_ctx.mark_file_read(fpath)
                        # Track skeleton size (much smaller) instead of full file
                        self._tool_ctx.track_file_read(fpath, len(skeleton))
                        return ToolResult(tool_id=tool_id, result={
                            "path": fpath,
                            "content": skeleton,
                            "skeleton": True,
                            "total_lines": _total_lines,
                            "hint": (
                                f"This file has {_total_lines:,} lines — too large to read at once. "
                                f"Above is a SKELETON showing structure with line numbers. "
                                f"To read a specific section: Read(file_path='{_basename}', offset=LINE_NUMBER, limit=80). "
                                f"Or use Grep(pattern='keyword', path='{_basename}') to find exact locations first."
                            )
                        })
                except Exception as skel_err:
                    log.warning(f"[BRIDGE] Skeleton gen failed for smart read, falling back to full read: {skel_err}")

            offset = max(1, int(args.get("offset", 1))) - 1
            limit = int(args.get("limit", len(lines)))
            content = "".join(lines[offset: offset + limit])
            read_lines = len(lines[offset: offset + limit])
            _remaining_chars = self._tool_ctx.get_remaining_budget_chars()
            if len(content) > _remaining_chars:
                _basename = os.path.basename(fpath)
                return ToolResult(
                    tool_id=tool_id, result=None, success=False,
                    error=(
                        f"Read output too large for current context budget "
                        f"({len(content):,} chars > ~{_remaining_chars:,} remaining). "
                        f"Read a smaller chunk: Read(file_path='{_basename}', offset={offset + 1}, limit=80)."
                    )
                )
            
            # Track this read for budget purposes
            self._tool_ctx.mark_file_read(fpath)
            self._tool_ctx.track_file_read(fpath, len(content))
            
            # Check for budget warnings
            warnings = self._tool_ctx.get_budget_warnings()
            if warnings:
                log.warning(f"[CTX] Budget warnings: {warnings}")
            
            # Populate context.read_file_state so FileEditTool staleness check passes
            try:
                _norm = os.path.abspath(fpath)
                _off_raw = args.get("offset")
                _lim_raw = args.get("limit")
                _mtime = os.path.getmtime(fpath)
                self._tool_ctx.read_file_state[_norm] = {
                    "content": content,
                    "timestamp": _mtime,
                    "offset": int(_off_raw) if _off_raw is not None else None,
                    "limit": int(_lim_raw) if _lim_raw is not None else None,
                }
                # Populate LRU dedup cache
                self._tool_ctx.file_cache_put(
                    _norm, content, _mtime,
                    int(_off_raw) if _off_raw is not None else None,
                    int(_lim_raw) if _lim_raw is not None else None,
                )
            except Exception:
                pass
            return ToolResult(tool_id=tool_id, result={
                "path": fpath,
                "content": content,
                "start_line": offset + 1,
                "num_lines": read_lines,
                "total_lines": _total_lines,
            })
        except Exception as e:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(e))

    def _resolve_directory_target_path(self, requested_path: str) -> Optional[str]:
        """
        Resolve a directory target to a concrete file path when possible.
        Returns None when no sensible file target can be inferred.
        """
        if not os.path.isdir(requested_path):
            return requested_path

        # Prefer active file if it is inside the requested directory.
        if self._active_file and os.path.isfile(self._active_file):
            try:
                active_abs = os.path.abspath(self._active_file)
                req_abs = os.path.abspath(requested_path)
                if active_abs.startswith(req_abs + os.sep):
                    return active_abs
            except Exception:
                pass

        preferred_names = [
            "index.html",
            "main.py",
            "app.py",
            "script.js",
            "style.css",
            "README.md",
        ]
        for name in preferred_names:
            candidate = os.path.join(requested_path, name)
            if os.path.isfile(candidate):
                return candidate
        return None

    async def _dispatch_write(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """Dispatch to real FileWriteTool or bridge-native fallback."""
        path = args.get("file_path", "")
        content = args.get("content", "")
        
        # INDUSTRY-STANDARD: Strict path validation
        # Reject directory paths IMMEDIATELY with clear error message
        if path.endswith((os.sep, '/')) or os.path.isdir(path):
            log.warning(f"[WRITE] Rejected directory path: {path}")
            return ToolResult(
                tool_id=tool_id,
                result=None,
                success=False,
                error=(
                    f"ERROR: You provided a directory path '{path}' instead of a file path.\n\n"
                    f"You MUST provide a complete file path with filename and extension.\n"
                    f"Examples:\n"
                    f"  CORRECT: 'index.html', 'src/questions.js', 'main.py'\n"
                    f"  WRONG: 'C:\\Game\\', 'src/', './'\n\n"
                    f"Please call Write again with the FULL file path."
                ),
            )
        
        if not os.path.isabs(path) and self._project_root:
            args = {**args, "file_path": os.path.join(self._project_root, path)}
        full_path = str(args["file_path"])
        if os.path.isdir(full_path):
            resolved = self._resolve_directory_target_path(full_path)
            if resolved is None:
                return ToolResult(
                    tool_id=tool_id,
                    result=None,
                    success=False,
                    error=(
                        f"Write expected a file path, but received directory: {full_path}. "
                        "Provide a concrete file path (for example, index.html or main.py)."
                    ),
                )
            args = {**args, "file_path": resolved}
            full_path = resolved
            log.warning(f"[BRIDGE] Write received directory path; auto-resolved to file: {full_path}")
        is_new = not os.path.exists(full_path)
        original_content: Optional[str] = None
        if not is_new:
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    original_content = f.read()
            except Exception:
                original_content = None

        # ── SAFETY: Prevent catastrophic overwrite of large files ──
        # If the existing file is significantly larger than the new content,
        # the LLM likely truncated its output. Refuse the write and tell
        # the LLM to use Edit instead.
        if not is_new:
            try:
                existing_size = os.path.getsize(full_path)
                new_size = len(content.encode('utf-8'))
                # If existing file is >500 bytes and new content is <30% of it,
                # this is almost certainly a truncated overwrite.
                if existing_size > 500 and new_size < existing_size * 0.30:
                    return ToolResult(
                        tool_id=tool_id, result=None, success=False,
                        error=(
                            f"SAFETY: Refusing to overwrite {os.path.basename(full_path)} "
                            f"({existing_size} bytes) with much smaller content "
                            f"({new_size} bytes, {new_size*100//existing_size}% of original). "
                            f"This would destroy existing code. "
                            f"Use the Edit tool to make targeted changes instead of "
                            f"rewriting the entire file."
                        ),
                    )
            except OSError:
                pass  # File stat failed — proceed with write

        # Emit signal to show file operation card with animation
        card_id = None
        ui_op_type = "create" if is_new else "edit"
        try:
            import uuid
            card_id = f"file-op-{uuid.uuid4().hex[:8]}"
            if is_new:
                self.file_creating_started.emit(full_path)
            else:
                self.file_editing_started.emit(full_path)
        except Exception as e:
            log.debug(f"[BRIDGE] Failed to emit file operation started: {e}")

        if _REAL_FILE_WRITE_TOOL is not None:
            try:
                real_write_tool = cast(Any, _REAL_FILE_WRITE_TOOL)
                raw_any: Any = await real_write_tool.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                raw_map = cast(Dict[str, Any], raw_any) if isinstance(raw_any, dict) else {}
                data_any = raw_map.get("data", {})
                data_map = cast(Dict[str, Any], data_any) if isinstance(data_any, dict) else {}
                op_raw = data_map.get("type", "create" if is_new else "update")
                op_type: str = op_raw if isinstance(op_raw, str) else ("create" if is_new else "update")
                # Emit UI signals
                self.file_generated.emit(full_path, content)
                if (not is_new) and (original_content is not None) and (original_content != content):
                    self.file_edited_diff.emit(full_path, original_content, content)
                # Emit completion signal for card animation
                if card_id:
                    self.file_operation_completed.emit(card_id, full_path, content, ui_op_type)
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
            if (not is_new) and (original_content is not None) and (original_content != content):
                self.file_edited_diff.emit(full_path, original_content, content)
            # Emit completion signal for card animation
            if card_id:
                self.file_operation_completed.emit(card_id, full_path, content, ui_op_type)
            self._tool_ctx.mark_file_modified(full_path)
            return ToolResult(tool_id=tool_id, result={
                "path": full_path, "type": "create" if is_new else "update", "written": True,
            })
        except Exception as e:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(e))

    async def _dispatch_edit(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """Dispatch to real FileEditTool or bridge-native fallback."""
        path = args.get("file_path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not os.path.isabs(path) and self._project_root:
            args = {**args, "file_path": os.path.join(self._project_root, path)}
        full_path = str(args["file_path"])
        if os.path.isdir(full_path):
            resolved = self._resolve_directory_target_path(full_path)
            if resolved is None:
                return ToolResult(
                    tool_id=tool_id,
                    result=None,
                    success=False,
                    error=(
                        f"Edit expected a file path, but received directory: {full_path}. "
                        "Use a concrete file path to edit (for example, index.html or main.py)."
                    ),
                )
            args = {**args, "file_path": resolved}
            full_path = resolved
            log.warning(f"[BRIDGE] Edit received directory path; auto-resolved to file: {full_path}")

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
                real_edit_tool = cast(Any, _REAL_FILE_EDIT_TOOL)
                raw_any: Any = await real_edit_tool.call(
                    args, self._tool_ctx, _always_allow_tool, _STUB_PARENT_MESSAGE
                )
                raw_map = cast(Dict[str, Any], raw_any) if isinstance(raw_any, dict) else {}
                data_any = raw_map.get("data", {})
                data_map = cast(Dict[str, Any], data_any) if isinstance(data_any, dict) else {}
                old_raw = data_map.get("oldString", old_string)
                new_raw = data_map.get("newString", new_string)
                actual_old = old_raw if isinstance(old_raw, str) else old_string
                actual_new = new_raw if isinstance(new_raw, str) else new_string
                # Compute full file content for diff/cache: original → new
                # If we have original content, apply the replacement;
                # otherwise re-read the file from disk (the real tool already wrote it)
                if original_content:
                    full_new = original_content.replace(actual_old, actual_new, 1)
                else:
                    try:
                        with open(full_path, "r", encoding="utf-8") as _f:
                            full_new = _f.read()
                    except Exception:
                        full_new = actual_new
                    original_content = actual_old  # best-effort for diff display
                self.file_edited_diff.emit(full_path, original_content, full_new)
                # Emit completion signal for card animation
                if card_id:
                    self.file_operation_completed.emit(card_id, full_path, full_new, "edit")
                self._tool_ctx.mark_file_modified(full_path)
                
                # Emit file edit notification for WebChannel
                self._safe_emit(self.file_edit_notification, full_path, "edit", "complete")
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
            # Update read_file_state so the next Edit turn's staleness check passes
            try:
                _norm = os.path.abspath(full_path)
                self._tool_ctx.read_file_state[_norm] = {
                    "content": new_content,
                    "timestamp": os.path.getmtime(full_path),
                    "offset": None,
                    "limit": None,
                }
                # Emit file edit notification for WebChannel
                self._safe_emit(self.file_edit_notification, full_path, "edit", "complete")
            except Exception:
                pass
            self.file_edited_diff.emit(full_path, file_content, new_content)
            # Emit completion signal for card animation
            if card_id:
                self.file_operation_completed.emit(card_id, full_path, new_content, "edit")
            self._tool_ctx.mark_file_modified(full_path)
            
            # Emit file edit notification for WebChannel
            self._safe_emit(self.file_edit_notification, full_path, "edit", "complete")
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
            diff_files_any = getattr(diff_data, "files", None)
            diff_files: List[Any] = cast(List[Any], diff_files_any) if isinstance(diff_files_any, list) else []
            for diff_file in diff_files:
                diff_path = getattr(diff_file, "path", "")
                if not isinstance(diff_path, str) or not diff_path:
                    continue
                git_norm = os.path.normpath(diff_path)
                if git_norm == norm or os.path.basename(git_norm) == os.path.basename(norm):
                    _added   = getattr(diff_file, 'lines_added', 0) or 0
                    _removed = getattr(diff_file, 'lines_removed', 0) or 0
                    _binary  = getattr(diff_file, 'is_binary', False) or False
                    _large   = getattr(diff_file, 'is_large_file', False) or False
                    _flags = (" [binary]" if _binary else "") + (" [large]" if _large else "")
                    log.info(
                        f"[BRIDGE] Git diff stats for {diff_path}: +{_added} -{_removed}{_flags}"
                    )
                    break
        except Exception as exc:
            log.debug(f"[BRIDGE] _refresh_git_diff_stats failed: {exc}")

    async def _dispatch_glob(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """Dispatch to real GlobTool or bridge-native fallback."""
        if _REAL_GLOB_TOOL is not None:
            try:
                real_glob_tool = cast(Any, _REAL_GLOB_TOOL)
                raw_any: Any = await real_glob_tool.call(args, self._tool_ctx)
                raw_map = cast(Dict[str, Any], raw_any) if isinstance(raw_any, dict) else {}
                data_any = raw_map.get("data", {})
                data_map = cast(Dict[str, Any], data_any) if isinstance(data_any, dict) else {}
                filenames_raw = data_map.get("filenames", [])
                filenames: List[str] = [
                    f for f in cast(List[Any], filenames_raw) if isinstance(f, str)
                ] if isinstance(filenames_raw, list) else []
                return ToolResult(tool_id=tool_id, result={
                    "pattern": args.get("pattern", ""),
                    "files": filenames,
                    "numFiles": data_map.get("numFiles", len(filenames)),
                    "truncated": data_map.get("truncated", False),
                })
            except Exception as exc:
                log.warning(f"[BRIDGE] Real GlobTool failed, using fallback: {exc}")

        # Fallback: simple glob
        import glob as _glob
        pattern = args.get("pattern", "")
        search_dir = args.get("path", self._project_root or os.getcwd())
        # Make relative search_dir absolute against project root
        if search_dir and not os.path.isabs(search_dir) and self._project_root:
            search_dir = os.path.join(self._project_root, search_dir)
        full_pattern = os.path.join(search_dir, pattern) if not os.path.isabs(pattern) else pattern
        try:
            files = sorted(_glob.glob(full_pattern, recursive=True))
            return ToolResult(tool_id=tool_id, result={"pattern": pattern, "files": files})
        except Exception as e:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(e))

    async def _dispatch_grep(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """Dispatch to real GrepTool or bridge-native fallback."""
        if _REAL_GREP_TOOL is not None:
            try:
                real_grep_tool = cast(Any, _REAL_GREP_TOOL)
                raw_any: Any = await real_grep_tool.call(args, self._tool_ctx)
                raw_map = cast(Dict[str, Any], raw_any) if isinstance(raw_any, dict) else {}
                data_any = raw_map.get("data", {})
                data = cast(Dict[str, Any], data_any) if isinstance(data_any, dict) else {}
                # Use map_tool_result_to_block for LLM-friendly output
                map_to_block = getattr(real_grep_tool, "map_tool_result_to_block", None)
                if callable(map_to_block):
                    map_to_block_fn = cast(Callable[[Dict[str, Any], str], Dict[str, Any]], map_to_block)
                    block = map_to_block_fn(data, tool_id)
                    return ToolResult(tool_id=tool_id, result={
                        "pattern": args.get("pattern", ""),
                        "matches": block.get("content", str(data)),
                    })
                return ToolResult(tool_id=tool_id, result=data)
            except Exception as exc:
                log.warning(f"[BRIDGE] Real GrepTool failed, using fallback: {exc}")

        # Fallback: pure-Python grep — no rg/grep binary required
        import re as _re
        import fnmatch as _fnmatch
        _FALLBACK_MATCH_LIMIT = 80  # Consistent with GrepTool.DEFAULT_HEAD_LIMIT
        pattern  = args.get("pattern", "")
        search_path = args.get("path", self._project_root or os.getcwd())
        if not os.path.isabs(search_path) and self._project_root:
            search_path = os.path.join(self._project_root, search_path)
        include_glob = args.get("glob", args.get("include", ""))
        case_insensitive = args.get("case_insensitive", False)
        _SKIP_DIRS = {'.git', '.svn', '.hg', 'node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build'}
        try:
            flags = _re.IGNORECASE if case_insensitive else 0
            compiled = _re.compile(pattern, flags)
            results: List[str] = []
            walk_target = search_path if os.path.isdir(search_path) else os.path.dirname(search_path)
            if os.path.isfile(search_path):
                # Single-file search
                files_to_scan: List[str] = [search_path]
            else:
                files_to_scan = []
                for root, dirs, files in os.walk(walk_target):
                    dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                    for fname in files:
                        if include_glob and not _fnmatch.fnmatch(fname, include_glob):
                            continue
                        files_to_scan.append(os.path.join(root, fname))
            for fpath in files_to_scan:
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                        for lineno, line in enumerate(fh, 1):
                            if compiled.search(line):
                                results.append(f"{fpath}:{lineno}:{line.rstrip()}")
                                if len(results) >= _FALLBACK_MATCH_LIMIT:
                                    break
                except (OSError, PermissionError):
                    pass
                if len(results) >= _FALLBACK_MATCH_LIMIT:
                    break
            if len(results) >= _FALLBACK_MATCH_LIMIT:
                output = "\n".join(results) + f"\n... (truncated at {_FALLBACK_MATCH_LIMIT} matches, refine your search pattern)"
            else:
                output = "\n".join(results)
            return ToolResult(tool_id=tool_id, result={
                "pattern": pattern, "matches": output or "(no matches)",
            })
        except _re.error as exc:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error=f"Invalid regex pattern: {exc}")
        except Exception as exc:
            return ToolResult(tool_id=tool_id, result=None, success=False, error=str(exc))

    async def _dispatch_todo_write(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle the TodoWrite agent tool.

        Stores the current todo list on the bridge and emits `todos_updated`
        so the UI panel refreshes in real time.
        """
        todos = args.get("todos", [])

        def _normalize_status(raw: Any) -> str:
            s = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
            if s in ("complete", "completed", "done"):
                return "COMPLETE"
            if s in ("in_progress", "inprogress", "running", "active"):
                return "IN_PROGRESS"
            if s in ("cancelled", "canceled"):
                return "CANCELLED"
            return "PENDING"

        normalized_todos: List[Dict[str, Any]] = []
        todo_items: List[Any] = cast(List[Any], todos) if isinstance(todos, list) else []
        for t in todo_items:
            if not isinstance(t, dict):
                continue
            t_map = cast(Dict[str, Any], t)
            td: Dict[str, Any] = dict(t_map)
            td["status"] = _normalize_status(td.get("status"))
            
            # ── Validate todo completion ───────────────────────────────
            # If marking as COMPLETE, check if it has mutations
            if td["status"] == "COMPLETE":
                _mutation_count = td.get("_mutation_count", 0)
                _content = td.get("content", "").lower()
                
                # Skip validation for non-implementation tasks
                _is_implementation = not any(
                    _content.startswith(x) for x in 
                    ("test", "verify", "analyze", "read", "review", "check")
                )
                
                if _is_implementation and _mutation_count == 0:
                    log.warning(
                        f"[TODO] Todo marked COMPLETE without mutations: {td.get('content', '')[:60]}"
                    )
                    # Don't block, but log warning for monitoring
            
            normalized_todos.append(td)

        if self._todo_write_streak >= 2 and self._mutation_success_count == self._last_todo_mutation_count:
            return ToolResult(
                tool_id=tool_id,
                result=None,
                success=False,
                error=(
                    "TodoWrite loop detected: no successful Write/Edit since the previous TodoWrite. "
                    "Perform real implementation actions first, then update todos."
                ),
            )

        if self._todo_write_streak >= 3:
            return ToolResult(
                tool_id=tool_id,
                result=None,
                success=False,
                error=(
                    "TodoWrite loop detected (3+ consecutive TodoWrite calls). "
                    "Do not call TodoWrite again right now; run real tools "
                    "(Read/Edit/Write/Bash) and update todos only after progress."
                ),
            )

        # If every item is completed/cancelled, treat the list as cleared
        all_done = bool(normalized_todos) and all(
            t.get("status") in ("COMPLETE", "CANCELLED") for t in normalized_todos
        )
        
        # ── INDUSTRY-STANDARD: Todo Completion Validation ─────────────────
        # CRITICAL: AI cannot mark todos as complete without actual mutations!
        # Validate that mutations match the number of implementation tasks
        if all_done:
            _implementation_tasks = [
                t for t in normalized_todos 
                if t.get("status") == "COMPLETE"
                and not t.get("content", "").lower().startswith(("test", "verify", "analyze", "read"))
            ]
            _required_mutations = len(_implementation_tasks)
            
            # ── MANDATORY VERIFICATION STEP ─────────────────────
            # Industry-standard: block completion unless tests/verification
            # commands were run and passed successfully.
            _verification_msg = self._build_verification_message()

            if _verification_msg is not None:
                log.warning("[TODO] AI trying to complete without passing verification.")
                return ToolResult(
                    tool_id=tool_id,
                    result=None,
                    success=False,
                    error=_verification_msg,
                )
            
            # If AI claims tasks are done but hasn't made enough mutations, BLOCK IT
            if _required_mutations > 0 and self._session_mutation_count < _required_mutations:
                log.warning(
                    f"[TODO] TodoWrite blocked: AI claims {_required_mutations} tasks complete "
                    + f"but only made {self._session_mutation_count} mutation(s). "
                    + f"Forcing actual implementation!"
                )
                return ToolResult(
                    tool_id=tool_id,
                    result=None,
                    success=False,
                    error=(
                        f"INVALID: You marked {_required_mutations} task(s) as complete, "
                        f"but you've only made {self._session_mutation_count} file change(s). "
                        f"You cannot mark tasks complete without actually doing the work!\n\n"
                        f"Required: At least {_required_mutations} Write/Edit operations\n"
                        f"Your mutations so far: {self._session_mutation_count}\n\n"
                        f"COMPLETE THE ACTUAL WORK FIRST, then update todos."
                    ),
                )
        
        old_todos = list(self._current_todos)
        new_todos = normalized_todos  # keep full list so UI shows completed state briefly

        # Block no-op TodoWrite calls (same ids/status/content repeatedly).
        try:
            _todo_sig = json.dumps(
                [
                    {
                        "id": str(t.get("id", "")),
                        "status": str(t.get("status", "")),
                        "content": str(t.get("content", "")),
                        "activeForm": str(t.get("activeForm", "")),
                    }
                    for t in new_todos
                ],
                sort_keys=True,
            )
        except Exception:
            _todo_sig = ""

        if _todo_sig and _todo_sig == self._last_todo_signature:
            return ToolResult(
                tool_id=tool_id,
                result=None,
                success=False,
                error=(
                    "TodoWrite made no changes compared to previous call. "
                    "Skip TodoWrite and continue with actual implementation actions."
                ),
            )
        self._last_todo_signature = _todo_sig
        self._last_todo_mutation_count = self._mutation_success_count

        # ── CRITICAL FIX: Never clear todos without verification ─────────
        # Even if AI marks all as "complete", we keep them in _current_todos
        # so the exit verification can check them
        # Only clear if:
        # 1. All are complete AND
        # 2. AI has made sufficient mutations AND  
        # 3. At least one verification/test action occurred after last mutation
        
        _should_clear_todos = False
        if all_done:
            _has_verification = getattr(self, '_post_mutation_read_count', 0) == 0
            # Only clear if mutations happened AND some verification occurred
            _should_clear_todos = (self._mutation_success_count > 0 and _has_verification)
            
            if not _should_clear_todos and self._mutation_success_count == 0:
                log.warning(
                    "[TODO] Todos marked complete but NO mutations made. "
                    + "Keeping todos visible - AI is trying to skip work!"
                )
        
        self._current_todos = [] if _should_clear_todos else list(new_todos)

        # Emit to update_todos() in ai_chat.py → window.updateTodos() in JS
        self.todos_updated.emit(new_todos, "")
        
        # ── INDUSTRY-STANDARD: Emit progress update ───────────
        if new_todos:
            _total = len(new_todos)
            _completed = sum(1 for t in new_todos if t.get("status") in ("COMPLETE", "CANCELLED"))
            _pct = int((_completed / _total) * 100) if _total > 0 else 0
            _msg = f"{_completed}/{_total} tasks complete ({_pct}%)" if _total > 0 else "No tasks"
            
            self.task_progress_update.emit(_completed, _total, _pct, _msg)
            log.info(f"[PROGRESS] {_msg}")

        log.info(f"[TODO] TodoWrite dispatched: {len(new_todos)} items, all_done={all_done}")

        return ToolResult(tool_id=tool_id, result={
            "oldTodos": old_todos,
            "newTodos": new_todos,
            "allDone":  all_done,
        })

    def toggle_todo_status(self, task_id: str, completed: bool) -> None:
        """
        Apply a UI todo toggle to bridge state so backend and UI stay in sync.
        """
        if not self._current_todos:
            return

        target_id = str(task_id or "")
        new_status = "COMPLETE" if completed else "PENDING"
        updated = False
        for todo in self._current_todos:
            todo_id = str(todo.get("id", ""))
            if todo_id == target_id:
                todo["status"] = new_status
                updated = True
                break

        if not updated:
            return

        # Keep main prompt state aligned with what the UI currently shows.
        self.todos_updated.emit(list(self._current_todos), "")
        log.info(f"[TODO] Backend sync from UI toggle: {target_id} -> {new_status}")

    def on_answer_question(self, question_id: str, answer: str) -> None:
        """
        Handle the user's answer to a pending question.
        Resolves the asyncio.Future so _dispatch_ask_user_question can resume.
        Called from the Qt main thread via the answer_question_requested signal.
        """
        pending = self._pending_questions.get(question_id)
        if pending:
            future_obj = pending.get("future")
            future: Optional[asyncio.Future[str]] = (
                cast(Optional[asyncio.Future[str]], future_obj)
                if isinstance(future_obj, asyncio.Future)
                else None
            )
            if future is not None and not future.done():
                # Resolve the future from the Qt main thread using
                # call_soon_threadsafe so the worker's asyncio loop picks it up
                # safely without any thread-safety violations.
                worker_loop = getattr(self._worker, "_loop", None)
                if worker_loop and worker_loop.is_running():
                    worker_loop.call_soon_threadsafe(future.set_result, answer)
                    log.info(f"[ASK] Answer routed to agent for question: {question_id}")
                else:
                    log.warning("[ASK] Worker loop not running — cannot resume agent")
            else:
                log.warning(f"[ASK] Future already resolved for question {question_id}")
        else:
            log.warning(f"[ASK] Received answer for unknown question ID: {question_id}")

    def _resume_agent_with_answer(self, _pending_question: Dict[str, Any]) -> None:
        """
        Legacy stub — superseded by the asyncio.Future approach in
        _dispatch_ask_user_question / on_answer_question.
        Kept here only to avoid AttributeError if referenced elsewhere.
        """
        question_id = _pending_question.get("id")
        log.warning(
            f"[ASK] _resume_agent_with_answer called for question_id={question_id!r} — this is a no-op; use on_answer_question instead."
        )

    async def _dispatch_ask_user_question(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle the AskUserQuestion agent tool.

        Emits the question to the UI via `user_question_requested` signal, then
        suspends the agent turn loop by awaiting an asyncio.Future.  The future
        is resolved (from the Qt main thread) when the user submits an answer.
        """
        questions = args.get("questions", [])

        if not questions:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="AskUserQuestion requires at least one question")

        # Validate questions structure
        for i, q in enumerate(questions):
            if not q.get("question"):
                return ToolResult(tool_id=tool_id, result=None, success=False,
                                  error=f"Question {i+1} missing 'question' field")
            if not q.get("header"):
                return ToolResult(tool_id=tool_id, result=None, success=False,
                                  error=f"Question {i+1} missing 'header' field")
            if not q.get("options"):
                return ToolResult(tool_id=tool_id, result=None, success=False,
                                  error=f"Question {i+1} missing 'options' field")

        # Use first question for the UI card
        first_q = questions[0]
        question_text = first_q.get("question", "")
        options = first_q.get("options", [])
        question_id = first_q.get("id", str(_uuid.uuid4()))

        # Create a Future on the current event loop that will be resolved
        # by on_answer_question() when the user submits their answer.
        loop = asyncio.get_running_loop()
        answer_future: asyncio.Future[str] = loop.create_future()

        # Store pending question state including the future
        self._pending_questions[question_id] = {
            "id": question_id,
            "questions": questions,
            "current_question": first_q,
            "tool_id": tool_id,
            "status": "pending",
            "future": answer_future,
        }

        # Emit to UI via signal — Qt main thread will render the question card
        self.user_question_requested.emit({
            "id": question_id,
            "text": question_text,
            "type": first_q.get("type", "text"),
            "choices": options if options else [],
            "default": first_q.get("default", ""),
            "details": first_q.get("details", ""),
            "scope": first_q.get("scope", "user"),
            "tool_name": "AskUserQuestion"
        })

        log.info(f"[ASK] Agent suspended — waiting for user answer (id={question_id})")

        # Await the future — this suspends the agent turn loop until the user
        # answers (or the task is cancelled / times out after 5 minutes).
        try:
            answer: str = await asyncio.wait_for(answer_future, timeout=300.0)
        except asyncio.TimeoutError:
            self._pending_questions.pop(question_id, None)
            log.warning(f"[ASK] Question {question_id} timed out after 5 min")
            return ToolResult(
                tool_id=tool_id, result=None, success=False,
                error="User did not answer within 5 minutes. Proceeding without answer."
            )
        except asyncio.CancelledError:
            # Task was cancelled (e.g. user sent a new message or stopped generation).
            # Clean up and re-raise so the task cancellation propagates correctly.
            self._pending_questions.pop(question_id, None)
            raise

        # Clean up and return the actual answer as the tool result
        self._pending_questions.pop(question_id, None)
        log.info(f"[ASK] User answered question {question_id!r}: {answer!r}")

        return ToolResult(
            tool_id=tool_id,
            result={
                "answers": {question_text: answer},
                "question_id": question_id,
                "status": "answered",
            },
            success=True
        )

    async def _dispatch_lsp(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle the LSP tool.

        Dispatches LSP operations to the LSP manager if available.
        Operations: goToDefinition, findReferences, hover, documentSymbol,
        workspaceSymbol, goToImplementation, call hierarchy.
        """
        operation = args.get("operation", "")
        file_path = args.get("filePath", "")
        line = args.get("line", 1)
        character = args.get("character", 1)

        if not operation:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="LSP requires 'operation' parameter")
        if not file_path:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="LSP requires 'filePath' parameter")

        # Resolve relative paths
        if not os.path.isabs(file_path) and self._project_root:
            file_path = os.path.join(self._project_root, file_path)

        # Try to use the LSP manager if available
        lsp_result = None
        if hasattr(self, '_lsp_manager') and self._lsp_manager:
            try:
                # LSP operations are synchronous in the manager
                if operation == "goToDefinition":
                    lsp_result = self._lsp_manager.go_to_definition(file_path, line, character)
                elif operation == "findReferences":
                    lsp_result = self._lsp_manager.find_references(file_path, line, character)
                elif operation == "hover":
                    lsp_result = self._lsp_manager.get_hover(file_path, line, character)
                elif operation == "documentSymbol":
                    lsp_result = self._lsp_manager.get_document_symbols(file_path)
                elif operation == "workspaceSymbol":
                    lsp_result = self._lsp_manager.get_workspace_symbols(args.get("query", ""))
                elif operation == "goToImplementation":
                    lsp_result = self._lsp_manager.go_to_implementation(file_path, line, character)
            except Exception as exc:
                log.warning(f"[LSP] LSP operation failed: {exc}")
                lsp_result = None

        if lsp_result:
            return ToolResult(tool_id=tool_id, result={
                "operation": operation,
                "file": file_path,
                "position": {"line": line, "character": character},
                "result": lsp_result,
            })

        # Fallback: return guidance for manual navigation
        return ToolResult(tool_id=tool_id, result={
            "operation": operation,
            "file": file_path,
            "position": {"line": line, "character": character},
            "result": None,
            "message": (
                f"LSP operation '{operation}' at {file_path}:{line}:{character}. "
                f"LSP server may not be running for this file type. "
                f"Use Grep or Read tools to search for definitions/references manually."
            ),
        })

    async def _dispatch_web_fetch(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle the WebFetch tool.

        Fetches content from a URL and extracts the main content.
        """
        url = args.get("url", "")
        query = args.get("query", "")

        if not url:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="WebFetch requires 'url' parameter")

        # Try to import and use the real WebFetchTool
        if _importlib_util.find_spec("agent.src.tools.WebFetchTool.utils"):
            try:
                from agent.src.tools.WebFetchTool.utils import get_url_markdown_content
                content = await get_url_markdown_content(url)
                return ToolResult(tool_id=tool_id, result={
                    "url": url,
                    "content": content[:50000] if content else "",
                    "query": query,
                })
            except Exception as exc:
                log.warning(f"[WebFetch] Failed to fetch {url}: {exc}")

        # Fallback: use stdlib urllib (always available)
        import re
        text = ""
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; Cortex IDE AI Agent)'
            })
            with urllib.request.urlopen(req, timeout=30) as response:
                html = response.read().decode('utf-8', errors='replace')

            # Simple text extraction (remove HTML tags)
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            return ToolResult(tool_id=tool_id, result={
                "url": url,
                "content": text[:50000],
                "query": query,
            })
        except urllib.error.URLError as exc:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error=f"Failed to fetch URL: {exc}")
        except Exception as exc:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error=f"WebFetch error: {exc}")

    async def _dispatch_web_search(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle the WebSearch tool.

        Searches the web for information.
        """
        query = args.get("query", "")

        if not query:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="WebSearch requires 'query' parameter")

        # WebSearch is not fully configured — return guidance so the LLM
        # does NOT retry this tool and instead proceeds with available info.
        return ToolResult(tool_id=tool_id, result={
            "query": query,
            "results": [],
            "message": (
                f"Web search for '{query}' is not available in this environment. "
                f"Do NOT call WebSearch again. "
                f"Proceed with the information you already have, "
                f"or ask the user to provide the information you need."
            ),
        })

    # ============================================================
    # TASK V2 DISPATCHERS
    # ============================================================

    async def _dispatch_task_create(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle TaskCreate tool - create a new structured task.
        Supports hierarchical fields: parentId, dependsOn, estimatedEffort.
        """
        subject = args.get("subject", "")
        description = args.get("description", "")
        active_form = args.get("activeForm", "")

        if not subject:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="TaskCreate requires 'subject' parameter")
        if not description:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="TaskCreate requires 'description' parameter")

        # Generate task ID
        import uuid
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        # Hierarchical fields
        parent_id = args.get("parentId")
        depends_on = args.get("dependsOn", [])
        estimated_effort = args.get("estimatedEffort")

        # Prevent circular dependencies before creating
        if depends_on and task_id in depends_on:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="Task cannot depend on itself")

        # Store task in session
        task: Dict[str, Any] = {
            "id": task_id,
            "subject": subject,
            "description": description,
            "activeForm": active_form or f"Working on: {subject}",
            "status": "pending",
            "owner": None,
            "blocks": [],
            "blockedBy": list(depends_on),
            "parentId": parent_id,
            "dependsOn": list(depends_on),
            "estimatedEffort": estimated_effort,
            "tags": [],
            "createdAt": _get_current_timestamp(),
        }

        # Add to session task list
        self._session_tasks[task_id] = task

        # Sync with hierarchical task graph
        node = TaskNode(
            id=task_id,
            subject=subject,
            description=description,
            status=TaskStatus.PENDING,
            active_form=active_form or f"Working on: {subject}",
            parent_id=parent_id,
            depends_on=list(depends_on),
            estimated_effort=estimated_effort,
        )
        self._task_graph.add_node(node)

        # Emit event
        try:
            from src.core.event_bus import get_event_bus, EventType, EventData
            bus = get_event_bus()
            bus.publish(EventType.TASK_GRAPH_UPDATED, EventData(source_component="agent_bridge"))
        except Exception:
            pass

        log.info(f"[TASK] Created task {task_id}: {subject}"
                 f"{' parent=' + parent_id if parent_id else ''}"
                 f"{' deps=' + str(depends_on) if depends_on else ''}")

        return ToolResult(tool_id=tool_id, result={
            "taskId": task_id,
            "task": task,
            "message": f"Task '{subject}' created with ID {task_id}"
        })

    async def _dispatch_task_update(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle TaskUpdate tool - update task status, owner, or dependencies.
        Also syncs with hierarchical task graph.
        """
        task_id = args.get("taskId", "")
        status = args.get("status")
        owner = args.get("owner")
        blocks = args.get("blocks")
        blocked_by = args.get("blockedBy")
        parent_id = args.get("parentId")  # "" means clear parent
        depends_on = args.get("dependsOn")
        estimated_effort = args.get("estimatedEffort")

        if not task_id:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="TaskUpdate requires 'taskId' parameter")

        # Get task from session
        if task_id not in self._session_tasks:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error=f"Task {task_id} not found")

        task = self._session_tasks[task_id]

        # Update flat task dict
        if status:
            task["status"] = status
        if owner is not None:
            task["owner"] = owner
        if blocks is not None:
            task["blocks"] = blocks
        if blocked_by is not None:
            task["blockedBy"] = blocked_by
        if parent_id is not None:
            task["parentId"] = parent_id if parent_id else None
        if depends_on is not None:
            task["dependsOn"] = list(depends_on)
        if estimated_effort is not None:
            task["estimatedEffort"] = estimated_effort
        task["updatedAt"] = _get_current_timestamp()

        # Sync with hierarchical task graph
        if self._task_graph.has_node(task_id):
            updates: Dict[str, Any] = {}
            if status:
                updates["status"] = TaskStatus.from_str(status)
            if owner is not None:
                updates["owner"] = owner
            if parent_id is not None:
                updates["parent_id"] = parent_id if parent_id else None
            if depends_on is not None:
                updates["depends_on"] = list(depends_on)
            if estimated_effort is not None:
                updates["estimated_effort"] = estimated_effort
            if updates:
                self._task_graph.update_node(task_id, **updates)

        # Emit event
        try:
            from src.core.event_bus import get_event_bus, EventType, EventData
            bus = get_event_bus()
            bus.publish(EventType.TASK_GRAPH_UPDATED, EventData(source_component="agent_bridge"))
        except Exception:
            pass

        log.info(f"[TASK] Updated task {task_id}: status={status or 'unchanged'}")

        return ToolResult(tool_id=tool_id, result={
            "taskId": task_id,
            "task": task,
            "message": f"Task {task_id} updated"
        })

    async def _dispatch_task_list(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle TaskList tool - list all tasks in session.
        """
        status_filter = args.get("status", "all")

        tasks = list(self._session_tasks.values())

        if status_filter != "all":
            tasks = [t for t in tasks if t.get("status") == status_filter]

        log.info(f"[TASK] Listed {len(tasks)} tasks (filter={status_filter})")

        # Include task graph summary
        graph_section = self._task_graph.build_prompt_section() if self._task_graph else ""

        return ToolResult(tool_id=tool_id, result={
            "tasks": tasks,
            "count": len(tasks),
            "filter": status_filter,
            "graph": graph_section,
        })

    async def _dispatch_task_get(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle TaskGet tool - get details of a specific task.
        """
        task_id = args.get("taskId", "")

        if not task_id:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="TaskGet requires 'taskId' parameter")

        if task_id not in self._session_tasks:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error=f"Task {task_id} not found")

        task = self._session_tasks[task_id]

        # Include hierarchical context
        children = []
        rollup = {}
        if self._task_graph and self._task_graph.has_node(task_id):
            child_nodes = self._task_graph.get_direct_children(task_id)
            children = [{"id": c.id, "subject": c.subject, "status": c.status.value}
                        for c in child_nodes]
            rollup = self._task_graph.get_rollup_status(task_id)

        return ToolResult(tool_id=tool_id, result={
            "task": task,
            "children": children,
            "rollup": rollup,
        })

    async def _dispatch_task_stop(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle TaskStop tool - stop a running task.
        """
        task_id = args.get("taskId", "")

        if not task_id:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="TaskStop requires 'taskId' parameter")

        if task_id not in self._session_tasks:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error=f"Task {task_id} not found")

        task = self._session_tasks[task_id]
        task["status"] = "cancelled"
        task["stoppedAt"] = _get_current_timestamp()

        log.info(f"[TASK] Stopped task {task_id}")

        return ToolResult(tool_id=tool_id, result={
            "taskId": task_id,
            "status": "cancelled",
            "message": f"Task {task_id} stopped"
        })

    # ============================================================
    # MCP DISPATCHER
    # ============================================================

    async def _dispatch_mcp(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle MCP tool - execute a tool from an MCP server.
        """
        server_name = args.get("serverName", "")
        tool_name = args.get("toolName", "")
        arguments = args.get("arguments", {})

        if not server_name:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="MCP requires 'serverName' parameter")
        if not tool_name:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="MCP requires 'toolName' parameter")

        log.info(f"[MCP] Tool call: {server_name}.{tool_name}")

        return ToolResult(tool_id=tool_id, result={
            "serverName": server_name,
            "toolName": tool_name,
            "arguments": arguments,
            "result": None,
            "message": (
                f"MCP tool '{tool_name}' on server '{server_name}'. "
                f"MCP servers need to be configured in settings. "
                f"Use the built-in tools (Read, Write, Bash, etc.) for file and command operations."
            )
        })

    # ============================================================
    # TEAM/SWARM DISPATCHERS
    # ============================================================

    async def _dispatch_team_create(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle TeamCreate tool - create a multi-agent team.
        """
        name = args.get("name", "")
        description = args.get("description", "")
        teammates = args.get("teammates", [])

        if not name:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="TeamCreate requires 'name' parameter")

        # Generate team ID
        import uuid
        team_id = f"team-{uuid.uuid4().hex[:8]}"

        # Create team structure
        team: Dict[str, Any] = {
            "id": team_id,
            "name": name,
            "description": description,
            "teammates": [],
            "status": "active",
            "createdAt": _get_current_timestamp(),
        }

        # Add teammates
        for i, tm in enumerate(teammates):
            teammate_id = f"agent-{uuid.uuid4().hex[:6]}"
            team["teammates"].append({
                "id": teammate_id,
                "name": tm.get("name", f"agent-{i+1}"),
                "role": tm.get("role", "general"),
                "status": "idle",
            })

        # Store team
        self._teams[team_id] = team

        log.info(f"[TEAM] Created team {team_id}: {name} with {len(teammates)} teammates")

        return ToolResult(tool_id=tool_id, result={
            "teamId": team_id,
            "team": team,
            "message": f"Team '{name}' created with {len(teammates)} agents"
        })

    async def _dispatch_team_delete(self, tool_id: str, args: Dict[str, Any]) -> ToolResult:
        """
        Handle TeamDelete tool - delete a team.
        """
        team_name = args.get("teamName", "")

        if not team_name:
            return ToolResult(tool_id=tool_id, result=None, success=False,
                              error="TeamDelete requires 'teamName' parameter")

        # Find team by name
        for tid, team in list(self._teams.items()):
            if team.get("name") == team_name:
                del self._teams[tid]
                log.info(f"[TEAM] Deleted team {tid}: {team_name}")
                return ToolResult(tool_id=tool_id, result={
                    "teamId": tid,
                    "message": f"Team '{team_name}' deleted"
                })

        return ToolResult(tool_id=tool_id, result=None, success=False,
                          error=f"Team '{team_name}' not found")

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

    def inject_vision_history(self, user_text: str, assistant_response: str):
        """Inject a vision exchange into conversation history.
        
        Called when vision processing completes outside the normal agent flow.
        This ensures follow-up text messages have context about what was in images.
        
        IMPORTANT: Truncate the vision response to avoid eating the entire hist_cap.
        The full response is already displayed in the UI; we only need a summary
        in history so the model knows what was discussed.
        """
        _MAX_VISION_HIST = 3000  # Max chars for vision response in history
        
        if len(assistant_response) > _MAX_VISION_HIST:
            truncated = assistant_response[:_MAX_VISION_HIST]
            assistant_response = (
                truncated + 
                f"\n\n[... vision analysis truncated from {len(assistant_response)} to {_MAX_VISION_HIST} chars for history context]"
            )
        
        log.info(f"[BRIDGE] Injecting vision exchange into history: user={len(user_text)} chars, assistant={len(assistant_response)} chars")
        self._conversation_history.append(
            ChatMessage(role="user", content=user_text)
        )
        self._conversation_history.append(
            ChatMessage(role="assistant", content=assistant_response)
        )

    def _on_chunk_ready(self, chunk: str):
        self.response_chunk.emit(chunk)

    def _on_error(self, error: str):
        self.request_error.emit(error)
    
    def _is_simple_query(self, text: str) -> bool:
        """Check if query is a pure greeting/ack that needs no tools.
        
        CONSERVATIVE: Only skip tools for pure social messages (hi, thanks, bye).
        Any message that MIGHT involve coding, files, or project work MUST get
        the full agentic loop with tools enabled.
        
        Returns:
            True if pure greeting/ack (skip tools), False otherwise (load tools)
        """
        import re
        text_lower = text.strip().lower()
        
        # Only exact greetings and social messages skip tools
        greeting_patterns = [
            r'^(hi|hello|hey|yo|sup|greetings)[!.\s]*$',
            r'^(thanks?|thank you|thx)[!.\s]*$',
            r'^(ok|okay|got it|sure|alright)[!.\s]*$',
            r'^(bye|goodbye|see you|good night)[!.\s]*$',
            r'^(good (morning|afternoon|evening))[!.\s]*$',
            r'^how are you[?!.\s]*$',
            r'^what\'?s up[?!.\s]*$',
        ]
        
        for pattern in greeting_patterns:
            if re.match(pattern, text_lower):
                return True
        
        # Everything else gets full agentic capabilities
        return False

    def _is_greeting(self, text: str) -> bool:
        """Return True for pure greeting/ack messages.

        Used to bypass the LLM entirely for instant UX on trivial inputs.
        """
        t = (text or "").strip().lower()
        if not t:
            return False
        # Normalize common punctuation
        t = t.replace("!", "").replace(".", "").replace(",", "").strip()

        greetings = {
            "hi", "hello", "hey", "hiya", "yo",
            "hi there", "hello there", "hey there",
            "good morning", "good afternoon", "good evening",
        }
        acks = {"thanks", "thank you", "thx", "ty"}
        byes = {"bye", "goodbye", "see you", "cya"}
        return t in greetings or t in acks or t in byes

    # ============================================================
    # PUBLIC INTERFACE (matching StubAIAgent so ai_chat.py works)
    # ============================================================

    def process_message(self, message: str, images: Optional[List[str]] = None):
        """Entry point: called by ai_chat.py when the user sends a message."""
        self._stop_requested = False  # Clear any previous stop before handling new request
        # Fresh AbortController so tools from the previous (aborted) request can't
        # accidentally cancel this new one.
        self._tool_ctx.abort_controller = create_abort_controller()

        # Reset tool safety counters for genuinely new requests (not Continue).
        _is_continue = message.strip().startswith('Continue the task.')
        if not _is_continue:
            self._continue_cycle_count = 0
            self._last_pending_ids = set()
        # Always reset tool counters — even on Continue — so tools
        # aren't still disabled from the previous cycle's limits.
        self._tool_fail_counts.clear()
        self._disabled_tools.clear()
        self._tool_total_calls.clear()

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
        log.info(f"[BRIDGE] Permission response: {decision}")
        self._permission_granted = (decision == 'accept')
        if self._permission_event is not None:
            # _permission_event may have been created in the async worker thread.
            # threading.Event.set() is always thread-safe.
            self._permission_event.set()

    def set_project_root(self, path: str):
        self._project_root = path
        self._memory_dir   = None  # reset so _get_memory_dir() recomputes for new project
        self._cached_project_summary = None  # reset so _get_project_summary() rebuilds for new project
        log.info(f"[BRIDGE] project root → {path}")
        try:
            _agent_set_project_root(path)
        except Exception:
            pass

    def set_project_context(self, context: Any) -> None:
        if isinstance(context, dict):
            self._enhancement_data.update(cast(Dict[str, Any], context))
        elif hasattr(context, "to_dict"):
            to_dict_fn = getattr(context, "to_dict", None)
            if callable(to_dict_fn):
                mapped = to_dict_fn()
                if isinstance(mapped, dict):
                    self._enhancement_data.update(cast(Dict[str, Any], mapped))
        elif hasattr(context, "__dict__"):
            raw_vars_any: Any = vars(context)  # pyright: ignore[reportUnknownVariableType]
            raw_vars = cast(Dict[str, Any], raw_vars_any) if isinstance(raw_vars_any, dict) else {}
            filtered: Dict[str, Any] = {
                str(k): v for k, v in raw_vars.items() if isinstance(k, str) and not k.startswith("_")
            }
            self._enhancement_data.update(filtered)

    def update_settings(self, **kwargs: Any) -> None:
        self._enhancement_data.update(kwargs)

    def set_terminal(self, terminal: Any) -> None:
        self._terminal = terminal

    def set_active_file(self, filepath: str, cursor_pos: Optional[int] = None):
        self._active_file = filepath
        self._cursor_pos  = cursor_pos

    def clear_active_file(self):
        self._active_file = None
        self._cursor_pos  = None

    def set_always_allowed(self, allowed: bool):
        self._always_allowed = allowed

    def set_interaction_mode(self, mode: str):
        self._interaction_mode = mode

    def set_ui_parent(self, parent: Any) -> None:
        self._ui_parent = parent

    def user_responded(self, question_id: str, answer: str):
        """Forward answer from UI signal (answer_question_requested) to on_answer_question."""
        log.info(f"[BRIDGE] user_responded: question_id={question_id!r}")
        self.on_answer_question(question_id, answer)

    def chat(self, message: str, context: str = ""):
        self.process_message(message)

    def chat_with_enhancement(
        self,
        message: str,
        intent: Optional[str] = None,
        route: Optional[str] = None,
        tools: Optional[List[str]] = None,
        code_context: str = "",
    ):
        self._enhancement_data.update(
            {"intent": intent, "route": route, "tools": tools, "code_context": code_context}
        )
        self.process_message(message)

    def chat_with_testing(self, message: str = "", **kwargs: Any):
        self.process_message(message)

    def generate_chat_title(self, message: str, conv_id: str) -> str:
        words = message.split()[:6]
        title = " ".join(words)
        if len(message.split()) > 6:
            title += "…"
        return title

    def get_last_enhancement_data(self) -> Dict[str, Any]:
        return self._enhancement_data.copy()

    def stop(self):
        self.stop_generation()

    def cleanup(self):
        log.info("[BRIDGE] cleanup")
        self._worker.stop()

    def clear_conversation(self):
        """Clear the in-memory conversation history."""
        self._conversation_history.clear()

    @staticmethod
    def _extract_semantic_summary(checkpoint_text: str, max_chars: int = 500) -> str:
        """
        Extract a concise summary from a context checkpoint for semantic storage.

        Pulls the Conversation Digest section (most recent exchanges) which
        gives the best snapshot of what happened in the session.
        """
        # Try to find the Conversation Digest section
        digest_marker = "**Conversation Digest:**"
        digest_idx = checkpoint_text.find(digest_marker)
        if digest_idx >= 0:
            return checkpoint_text[digest_idx + len(digest_marker):].strip()[:max_chars]

        # Fallback: first non-empty lines up to max_chars
        lines = [l.strip() for l in checkpoint_text.split("\n") if l.strip()]
        return " | ".join(lines[:10])[:max_chars]


# ============================================================
# FACTORY
# ============================================================

def get_agent_bridge(**kwargs: Any) -> CortexAgentBridge:
    """Factory function — returns a ready CortexAgentBridge instance."""
    return CortexAgentBridge(**kwargs)


__all__ = [
    "CortexAgentBridge",
    "get_agent_bridge",
    "ChatMessage",
    "ToolCall",
    "ToolResult",
]
