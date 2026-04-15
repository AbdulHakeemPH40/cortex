"""
Enhanced logging system for Cortex IDE (Multi-LLM Support).

Combines Python standard logging with TypeScript log.ts features:
- Multi-destination error logging (memory, file, console)
- MCP error and debug logging
- Startup error queue (no errors lost during initialization)
- In-memory error buffer (last 100 errors)
- Session display title generation
- Privacy controls for error reporting
- Log rotation and persistence

Supports: OpenAI, Anthropic, Google Gemini, xAI Grok, DeepSeek, Qwen, and more.

Usage:
    from ..utils.log import log_error, get_in_memory_errors, get_log_display_title
    
    # Log errors
    log_error(Exception("Something went wrong"))
    
    # Log MCP server errors
    log_mcp_error("my-server", Exception("Connection failed"))
    
    # Get recent errors for UI
    recent_errors = get_in_memory_errors()
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, Dict, List
from dataclasses import dataclass, field
from logging.handlers import TimedRotatingFileHandler


# ============================================================================
# Constants
# ============================================================================

MAX_IN_MEMORY_ERRORS = 100
TICK_TAG = "tick"  # Autonomous mode tick tag


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ErrorLogEntry:
    """Represents an error log entry."""
    error: str
    timestamp: str


@dataclass
class LogOption:
    """Represents a log/session entry for display."""
    date: str
    full_path: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    value: int = 0
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    first_prompt: str = "No prompt"
    message_count: int = 0
    is_sidechain: bool = False
    agent_name: Optional[str] = None
    custom_title: Optional[str] = None
    summary: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class QueuedErrorEvent:
    """Represents a queued error event before sink is attached."""
    event_type: str  # 'error', 'mcp_error', 'mcp_debug'
    error: Optional[Exception] = None
    server_name: Optional[str] = None
    message: Optional[str] = None


# ============================================================================
# Global State
# ============================================================================

# In-memory error log for recent errors
_in_memory_error_log: List[ErrorLogEntry] = []

# Queued events for events logged before sink is attached
_error_queue: List[QueuedErrorEvent] = []

# Sink - initialized during app startup
_error_log_sink: Optional[Any] = None

# Privacy flag - can be set via environment variables
_error_reporting_disabled = False


# ============================================================================
# Standard Logger Setup (from existing logger.py)
# ============================================================================

def _create_standard_logger(name: str = "cortex") -> logging.Logger:
    """Create a standard Python logger with file and console handlers."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        
        # Always log to user home directory to avoid file locks during project operations
        # Location: C:\Users\Hakeem1\.cortex\logs\cortex.log
        log_dir = Path.home() / ".cortex" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "cortex.log"
        
        # File handler - Windows-safe: use TimedRotatingFileHandler with delay
        # Override rotator to handle Windows file locks gracefully
        import os

        def _windows_safe_rotator(source, dest):
            """Rotate log file, handling Windows file lock errors gracefully."""
            try:
                if os.path.exists(dest):
                    os.remove(dest)
                os.rename(source, dest)
            except (PermissionError, OSError):
                # File is locked by another process/handler - skip rotation
                pass

        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            backupCount=3,
            encoding='utf-8',
            delay=True
        )
        file_handler.rotator = _windows_safe_rotator
        file_handler.setLevel(logging.INFO)  # INFO not DEBUG - prevents heartbeat/debug spam
        file_handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(file_handler)
        
        # Console handler - show INFO and above (includes model usage logs)
        # Use simple StreamHandler (PyInstaller compatible)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)  # Show INFO for model/provider logs
        console_handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                datefmt="%H:%M:%S"
            )
        )
        logger.addHandler(console_handler)
        
    return logger


# Create the standard logger instance
_standard_logger = _create_standard_logger("cortex")


# ============================================================================
# Helper Functions
# ============================================================================

def _add_to_in_memory_error_log(error_info: ErrorLogEntry) -> None:
    """Add error to in-memory log, removing oldest if at capacity."""
    if len(_in_memory_error_log) >= MAX_IN_MEMORY_ERRORS:
        _in_memory_error_log.pop(0)  # Remove oldest error
    _in_memory_error_log.append(error_info)


def _is_error_reporting_disabled() -> bool:
    """Check if error reporting should be disabled based on environment."""
    # Check environment variables that disable error reporting
    # Supports all major LLM providers
    disabled_vars = [
        # Claude/Anthropic
        'CORTEX_USE_BEDROCK',
        'CORTEX_USE_VERTEX',
        'CORTEX_USE_FOUNDRY',
        # OpenAI
        'CORTEX_USE_OPENAI',
        # Google
        'CORTEX_USE_GEMINI',
        # xAI
        'CORTEX_USE_GROK',
        # DeepSeek
        'CORTEX_USE_DEEPSEEK',
        # Alibaba
        'CORTEX_USE_QWEN',
        # Generic
        'DISABLE_ERROR_REPORTING',
    ]
    
    for var in disabled_vars:
        if os.environ.get(var, '').lower() in ('true', '1', 'yes'):
            return True
    
    return _error_reporting_disabled


def date_to_filename(date: Optional[datetime] = None) -> str:
    """Convert date to filename-safe format."""
    if date is None:
        date = datetime.now()
    return date.isoformat().replace(':', '-').replace('.', '-')


def parse_iso_string(s: str) -> Optional[datetime]:
    """Parse ISO date string to datetime."""
    try:
        # Handle various ISO formats
        s = s.replace('Z', '+00:00')
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        # Fallback: parse manually
        try:
            parts = re.split(r'\D+', s)
            if len(parts) >= 6:
                return datetime(
                    int(parts[0]),
                    int(parts[1]),
                    int(parts[2]),
                    int(parts[3]),
                    int(parts[4]),
                    int(parts[5])
                )
        except (ValueError, IndexError):
            pass
    return None


def strip_display_tags(text: str) -> str:
    """Strip display-unfriendly XML tags from text."""
    # Remove tags like <ide_opened_file>, <command-name>, etc.
    return re.sub(r'<[^>]+>', '', text).strip()


def strip_display_tags_allow_empty(text: str) -> str:
    """Strip display tags and return the stripped result (can be empty)."""
    # Remove tags like <ide_opened_file>, <command-name>, etc.
    result = re.sub(r'<[^>]+>', '', text).strip()
    return result


# ============================================================================
# Error Log Sink Interface
# ============================================================================

class ErrorLogSink:
    """Interface for the error logging backend."""
    
    def log_error(self, error: Exception) -> None:
        """Log a general error."""
        raise NotImplementedError
    
    def log_mcp_error(self, server_name: str, error: Any) -> None:
        """Log an MCP server error."""
        raise NotImplementedError
    
    def log_mcp_debug(self, server_name: str, message: str) -> None:
        """Log MCP server debug message."""
        raise NotImplementedError
    
    def get_errors_path(self) -> str:
        """Get path to errors directory."""
        raise NotImplementedError
    
    def get_mcp_logs_path(self, server_name: str) -> str:
        """Get path to MCP logs for a specific server."""
        raise NotImplementedError


# ============================================================================
# Core Functions (from TypeScript log.ts)
# ============================================================================

def attach_error_log_sink(new_sink: ErrorLogSink) -> None:
    """
    Attach the error log sink that will receive all error events.
    Queued events are drained immediately to ensure no errors are lost.
    
    Idempotent: if a sink is already attached, this is a no-op. This allows
    calling from both the preAction hook (for subcommands) and setup() (for
    the default command) without coordination.
    """
    global _error_log_sink
    
    if _error_log_sink is not None:
        return  # Already attached
    
    _error_log_sink = new_sink
    
    # Drain the queue immediately - errors should not be delayed
    if len(_error_queue) > 0:
        queued_events = list(_error_queue)
        _error_queue.clear()
        
        for event in queued_events:
            if event.event_type == 'error' and event.error:
                _error_log_sink.log_error(event.error)
            elif event.event_type == 'mcp_error' and event.server_name:
                _error_log_sink.log_mcp_error(event.server_name, event.error)
            elif event.event_type == 'mcp_debug' and event.server_name and event.message:
                _error_log_sink.log_mcp_debug(event.server_name, event.message)


def log_error(error: Any) -> None:
    """
    Logs an error to multiple destinations for debugging and monitoring.
    
    This function logs errors to:
    - Standard logger (visible in cortex.log and console)
    - In-memory error log (accessible via get_in_memory_errors(), useful for
      including in bug reports or displaying recent errors to users)
    - Persistent error log file (if sink is attached)
    
    Usage:
        log_error(Exception("Failed to connect"))
        log_error("String error message")
        log_error(SomeExceptionInstance)
    
    To view errors:
    - File: Check ~/.cortex/logs/cortex.log
    - Console: Run with verbose mode
    - In-memory: Call get_in_memory_errors() to get recent errors
    """
    global _error_queue
    
    try:
        # Check if error reporting should be disabled
        if _is_error_reporting_disabled():
            return
        
        # Convert to exception if it's not already
        if isinstance(error, Exception):
            err = error
        else:
            err = Exception(str(error))
        
        error_str = str(err)
        if hasattr(err, '__traceback__') and err.__traceback__:
            import traceback
            error_str = ''.join(traceback.format_exception(type(err), err, err.__traceback__))
        
        error_info = ErrorLogEntry(
            error=error_str,
            timestamp=datetime.now().isoformat()
        )
        
        # Always add to in-memory log (no dependencies needed)
        _add_to_in_memory_error_log(error_info)
        
        # Log to standard logger
        _standard_logger.error(f"Error: {error_str}")
        
        # If sink not attached, queue the event
        if _error_log_sink is None:
            _error_queue.append(QueuedErrorEvent(
                event_type='error',
                error=err
            ))
            return
        
        # Otherwise, send to sink
        _error_log_sink.log_error(err)
        
    except Exception:
        # Silently fail - don't let error logging crash the app
        pass


def get_in_memory_errors() -> List[Dict[str, str]]:
    """Get recent errors from in-memory buffer."""
    return [
        {"error": entry.error, "timestamp": entry.timestamp}
        for entry in _in_memory_error_log
    ]


def log_mcp_error(server_name: str, error: Any) -> None:
    """
    Log an MCP (Model Context Protocol) server error.
    
    Args:
        server_name: Name of the MCP server
        error: The error that occurred
    """
    global _error_queue
    
    try:
        # If sink not attached, queue the event
        if _error_log_sink is None:
            _error_queue.append(QueuedErrorEvent(
                event_type='mcp_error',
                server_name=server_name,
                error=error if isinstance(error, Exception) else Exception(str(error))
            ))
            return
        
        _error_log_sink.log_mcp_error(server_name, error)
        
    except Exception:
        # Silently fail
        pass


def log_mcp_debug(server_name: str, message: str) -> None:
    """
    Log MCP server debug message.
    
    Args:
        server_name: Name of the MCP server
        message: Debug message
    """
    global _error_queue
    
    try:
        # If sink not attached, queue the event
        if _error_log_sink is None:
            _error_queue.append(QueuedErrorEvent(
                event_type='mcp_debug',
                server_name=server_name,
                message=message
            ))
            return
        
        _error_log_sink.log_mcp_debug(server_name, message)
        
    except Exception:
        # Silently fail
        pass


# ============================================================================
# Log Display Title (from TypeScript getLogDisplayTitle)
# ============================================================================

def get_log_display_title(log: LogOption, default_title: Optional[str] = None) -> str:
    """
    Gets the display title for a log/session with fallback logic.
    Skips firstPrompt if it starts with a tick/goal tag (autonomous mode auto-prompt).
    Strips display-unfriendly tags (like <ide_opened_file>) from the result.
    Falls back to a truncated session ID when no other title is available.
    
    Args:
        log: LogOption object containing session metadata
        default_title: Fallback title if no other title is available
    
    Returns:
        Display-safe title string
    """
    # Skip firstPrompt if it's a tick/goal message (autonomous mode auto-prompt)
    is_autonomous_prompt = (
        log.first_prompt and 
        log.first_prompt.startswith(f"<{TICK_TAG}>")
    )
    
    # Strip display-unfriendly tags (command-name, ide_opened_file, etc.) early
    # so that command-only prompts (e.g. /clear) become empty and fall through
    # to the next fallback instead of showing raw XML tags.
    stripped_first_prompt = (
        strip_display_tags_allow_empty(log.first_prompt)
        if log.first_prompt
        else ''
    )
    
    use_first_prompt = stripped_first_prompt and not is_autonomous_prompt
    
    # Build title with fallback chain
    title = (
        log.agent_name or
        log.custom_title or
        log.summary or
        (stripped_first_prompt if use_first_prompt else None) or
        default_title or
        # For autonomous sessions without other context, show a meaningful label
        ('Autonomous session' if is_autonomous_prompt else None) or
        # Fall back to truncated session ID for lite logs with no metadata
        (log.session_id[:8] if log.session_id else '') or
        ''
    )
    
    # Strip display-unfriendly tags (like <ide_opened_file>) for cleaner titles
    return strip_display_tags(title).strip()


# ============================================================================
# Log Loading Functions
# ============================================================================

async def load_error_logs() -> List[LogOption]:
    """
    Loads the list of error logs from disk.
    
    Returns:
        List of error logs sorted by date
    """
    errors_path = Path.home() / ".cortex" / "errors"
    if not errors_path.exists():
        return []
    
    return await _load_log_list(str(errors_path))


async def get_error_log_by_index(index: int) -> Optional[LogOption]:
    """
    Gets an error log by its index.
    
    Args:
        index: Index in the sorted list of logs (0-based)
    
    Returns:
        Log data or None if not found
    """
    logs = await load_error_logs()
    return logs[index] if index < len(logs) else None


async def _load_log_list(path: str) -> List[LogOption]:
    """
    Internal function to load and process logs from a specified path.
    
    Args:
        path: Directory containing logs
    
    Returns:
        Array of logs sorted by date
    """
    try:
        log_dir = Path(path)
        if not log_dir.exists():
            log_error(Exception(f"No logs found at {path}"))
            return []
        
        files = list(log_dir.iterdir())
        log_data = []
        
        for i, file_path in enumerate(files):
            if not file_path.is_file():
                continue
            
            try:
                content = file_path.read_text(encoding='utf-8')
                messages = json.loads(content)
                
                if not isinstance(messages, list):
                    continue
                
                first_message = messages[0] if messages else None
                last_message = messages[-1] if messages else None
                
                # Extract first prompt
                first_prompt = 'No prompt'
                if (
                    first_message and
                    isinstance(first_message, dict) and
                    first_message.get('type') == 'user' and
                    isinstance(first_message.get('message', {}).get('content'), str)
                ):
                    first_prompt = first_message['message']['content']
                
                # Get file stats
                file_stats = file_path.stat()
                date = date_to_filename(datetime.fromtimestamp(file_stats.st_mtime))
                
                # Check if it's a sidechain by looking at filename
                is_sidechain = 'sidechain' in str(file_path)
                
                # Parse timestamps
                created = parse_iso_string(first_message.get('timestamp', date) if first_message else date)
                modified = (
                    parse_iso_string(last_message.get('timestamp', date))
                    if last_message and last_message.get('timestamp')
                    else parse_iso_string(date)
                )
                
                # Truncate first prompt
                first_line = first_prompt.split('\n')[0][:50]
                if len(first_prompt) > 50:
                    first_line += '…'
                
                log_entry = LogOption(
                    date=date,
                    full_path=str(file_path),
                    messages=messages,
                    value=i,
                    created=created,
                    modified=modified,
                    first_prompt=first_line or 'No prompt',
                    message_count=len(messages),
                    is_sidechain=is_sidechain
                )
                
                log_data.append(log_entry)
                
            except Exception as e:
                log_error(Exception(f"Failed to load log file {file_path}: {e}"))
                continue
        
        # Sort logs by date (newest first)
        log_data.sort(key=lambda x: x.modified or x.created or datetime.min, reverse=True)
        
        # Update value indices
        for i, log_entry in enumerate(log_data):
            log_entry.value = i
        
        return log_data
        
    except Exception as e:
        log_error(Exception(f"Failed to load logs from {path}: {e}"))
        return []


# ============================================================================
# API Request Capture (from TypeScript captureAPIRequest)
# ============================================================================

# Simple in-memory storage for last API request
_last_api_request: Optional[Dict[str, Any]] = None
_last_api_request_messages: Optional[Any] = None


def capture_api_request(params: Dict[str, Any], query_source: Optional[str] = None) -> None:
    """
    Captures the last API request for inclusion in bug reports.
    
    Args:
        params: API request parameters
        query_source: Source of the query (e.g., 'repl_main_thread:outputStyle:Explanatory')
    """
    global _last_api_request, _last_api_request_messages
    
    # Only capture main REPL thread requests
    if not query_source or not query_source.startswith('repl_main_thread'):
        return
    
    # Store params WITHOUT messages to avoid retaining the entire conversation
    params_without_messages = {k: v for k, v in params.items() if k != 'messages'}
    _last_api_request = params_without_messages
    
    # For internal testing: also keep reference to messages
    user_type = os.environ.get('USER_TYPE', '')
    if user_type == 'ant':
        _last_api_request_messages = params.get('messages')


def get_last_api_request() -> Optional[Dict[str, Any]]:
    """Get the last captured API request (without messages)."""
    return _last_api_request


def get_last_api_request_messages() -> Optional[Any]:
    """Get the last captured API request messages (if enabled)."""
    return _last_api_request_messages


# ============================================================================
# Testing Utilities
# ============================================================================

def _reset_error_log_for_testing() -> None:
    """
    Reset error log state for testing purposes only.
    @internal
    """
    global _error_log_sink, _error_queue, _in_memory_error_log, _last_api_request, _last_api_request_messages
    _error_log_sink = None
    _error_queue.clear()
    _in_memory_error_log.clear()
    _last_api_request = None
    _last_api_request_messages = None


# ============================================================================
# Convenience Re-exports
# ============================================================================

# Re-export standard logger for backward compatibility
def get_logger(name: str = "cortex") -> logging.Logger:
    """Get a standard Python logger (backward compatibility)."""
    return _create_standard_logger(name)


# ============================================================================
# CamelCase Aliases (for backward compatibility with TypeScript imports)
# ============================================================================

def clear_error_queue() -> None:
    """Clear the error queue (for testing/cleanup)."""
    global _error_queue
    _error_queue.clear()


def log_for_debugging(message: str, level: str = 'debug') -> None:
    """Log a debug message (stub for compatibility)."""
    _standard_logger.debug(message)


logError = log_error
logMCPError = log_mcp_error
logMCPDebug = log_mcp_debug
getLogDisplayTitle = get_log_display_title
getInMemoryErrors = get_in_memory_errors
clearErrorQueue = clear_error_queue
logForDebugging = log_for_debugging
attachErrorLogSink = attach_error_log_sink
getInMemoryErrorLog = lambda: _in_memory_error_log


# ============================================================================
# PUBLIC API EXPORTS
# ============================================================================

__all__ = [
    # Core functions (snake_case)
    "log_error",
    "log_mcp_error",
    "log_mcp_debug",
    "get_in_memory_errors",
    "get_log_display_title",
    "attach_error_log_sink",
    "clear_error_queue",
    "log_for_debugging",
    "capture_api_request",
    "get_last_api_request",
    "get_last_api_request_messages",
    # CamelCase aliases
    "logError",
    "logMCPError",
    "logMCPDebug",
    "getInMemoryErrors",
    "getLogDisplayTitle",
    "clearErrorQueue",
    "logForDebugging",
    "attachErrorLogSink",
    # Classes and types
    "ErrorLogEntry",
    "LogOption",
    "QueuedErrorEvent",
    "ErrorLogSink",
    # Utilities
    "get_logger",
    "date_to_filename",
    "parse_iso_string",
    "strip_display_tags",
    "strip_display_tags_allow_empty",
]
