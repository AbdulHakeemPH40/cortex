import sys
import os
import json
import subprocess
import threading
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from enum import Enum

from PyQt6.QtCore import QObject, pyqtSignal
from src.utils.logger import get_logger

log = get_logger("lsp_manager")


class LSPConnectionState(Enum):
    """LSP server connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    READY = "ready"
    ERROR = "error"
    RECONNECTING = "reconnecting"

class LSPServerInstance(QObject):
    """Represents a running Language Server process with enhanced state management."""
    
    # Signals for reactive UI updates
    state_changed = pyqtSignal(str, str)  # server_name, new_state
    progress_started = pyqtSignal(str, dict)  # token, value
    progress_updated = pyqtSignal(str, int, str)  # token, percentage, message
    progress_ended = pyqtSignal(str)  # token
    message_received = pyqtSignal(dict)  # message
    
    def __init__(self, name: str, cmd: List[str], root_uri: str):
        super().__init__()
        self.name = name
        self.cmd = cmd
        self.root_uri = root_uri
        self.process: Optional[subprocess.Popen] = None
        self.id_counter = 0
        self.callbacks: Dict[int, Callable] = {}
        self.diagnostics_callback: Optional[Callable] = None
        self._is_running = False
        self._read_thread: Optional[threading.Thread] = None
        self.capabilities = {}
        
        # Enhanced state management
        self.state = LSPConnectionState.DISCONNECTED
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._reconnect_delay = 1.0  # seconds
        self._pending_messages: List[Dict] = []  # Queue for messages during reconnection
        
        # Request tracking with timeouts
        self._active_requests: Dict[int, Dict] = {}  # Track pending requests
        self._request_timeouts: Dict[int, threading.Timer] = {}
        self._default_timeout = 5.0  # 5 second default timeout
        
        # Message buffering
        self._buffer = b""
        
    def _set_state(self, new_state: LSPConnectionState):
        """Update state and emit signal."""
        old_state = self.state
        self.state = new_state
        log.info(f"LSP server {self.name}: {old_state.value} -> {new_state.value}")
        self.state_changed.emit(self.name, new_state.value)

    def start(self):
        """Start the LSP server process and reader thread."""
        try:
            self._set_state(LSPConnectionState.CONNECTING)
            log.info(f"Starting LSP server '{self.name}': {' '.join(self.cmd)}")
            self.process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=True if os.name == 'nt' else False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            self._is_running = True
            self._reconnect_attempts = 0  # Reset on successful start
            
            # Start error logger thread
            threading.Thread(target=self._stderr_loop, daemon=True).start()
            
            # Start primary reader thread
            self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()
            
            self._set_state(LSPConnectionState.INITIALIZING)
            
            # Handshake with standard capabilities
            self.send_request("initialize", {
                "processId": os.getpid(),
                "rootUri": self.root_uri,
                "capabilities": {
                    "textDocument": {
                        "publishDiagnostics": {"relatedInformation": True},
                        "completion": {"completionItem": {"snippetSupport": True}},
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "definition": {"dynamicRegistration": True},
                        "rename": {"dynamicRegistration": True},
                        "codeAction": {"dynamicRegistration": True}
                    },
                    "workspace": {
                        "symbol": {"dynamicRegistration": True},
                        "executeCommand": {"dynamicRegistration": True}
                    }
                }
            }, self._on_initialized)
            
            return True
        except Exception as e:
            log.error(f"Failed to start LSP server {self.name}: {e}")
            self._set_state(LSPConnectionState.ERROR)
            self._handle_connection_error(e)
            return False

    def stop(self):
        """Stop the LSP server."""
        self._is_running = False
        self._set_state(LSPConnectionState.DISCONNECTED)
        
        # Cancel all pending requests
        for timer in self._request_timeouts.values():
            timer.cancel()
        self._request_timeouts.clear()
        self._active_requests.clear()
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=0.2)
            except Exception as e:
                log.debug(f"Error terminating LSP process {self.name}: {e}")
            self.process = None
        
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=0.5)
            if self._read_thread.is_alive():
                log.warning(f"LSP server {self.name} read thread did not terminate gracefully.")

    def _handle_connection_error(self, error: Exception):
        """Graceful error handling with automatic reconnection."""
        log.error(f"LSP connection error in {self.name}: {error}")
        self._set_state(LSPConnectionState.ERROR)
        
        if self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            delay = self._reconnect_delay * self._reconnect_attempts
            log.info(f"Attempting reconnection {self._reconnect_attempts}/{self._max_reconnect_attempts} in {delay}s")
            self._set_state(LSPConnectionState.RECONNECTING)
            threading.Timer(delay, self._attempt_reconnect).start()
        else:
            log.error(f"Max reconnection attempts reached for {self.name}")

    def _attempt_reconnect(self):
        """Attempt to restart the server and restore state."""
        try:
            log.info(f"Attempting to reconnect {self.name}...")
            self.stop()
            if self.start():
                log.info(f"Successfully reconnected {self.name}")
                self._replay_pending_messages()
        except Exception as e:
            log.error(f"Reconnection failed: {e}")
            self._handle_connection_error(e)

    def _replay_pending_messages(self):
        """Replay messages that were queued during disconnection."""
        if self._pending_messages:
            log.info(f"Replaying {len(self._pending_messages)} pending messages")
            for msg in self._pending_messages:
                self._send(msg)
            self._pending_messages.clear()


    def send_request(self, method: str, params: Any, 
                     callback: Optional[Callable] = None,
                     timeout: Optional[float] = None) -> int:
        """Send a JSON-RPC request with optional timeout.
        
        Args:
            method: LSP method name
            params: Request parameters
            callback: Callback function for response
            timeout: Request timeout in seconds (default: 5.0)
            
        Returns:
            Message ID for tracking/cancellation
        """
        self.id_counter += 1
        msg_id = self.id_counter
        
        if callback:
            self.callbacks[msg_id] = callback
            self._active_requests[msg_id] = {
                "method": method,
                "params": params,
                "timestamp": time.time()
            }
            
            # Set up timeout
            timeout_duration = timeout or self._default_timeout
            timer = threading.Timer(timeout_duration, 
                                   lambda: self._handle_timeout(msg_id))
            timer.daemon = True
            timer.start()
            self._request_timeouts[msg_id] = timer
        
        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params
        }
        self._send(payload)
        return msg_id
    
    def _handle_timeout(self, msg_id: int):
        """Handle request timeout."""
        if msg_id in self._active_requests:
            request_info = self._active_requests.pop(msg_id)
            if msg_id in self.callbacks:
                callback = self.callbacks.pop(msg_id)
                error = {"code": -32603, "message": "Request timeout"}
                callback(None, error)
            log.warning(f"Request {msg_id} ({request_info['method']}) timed out")
    
    def cancel_request(self, msg_id: int):
        """Cancel a pending request."""
        if msg_id in self._active_requests:
            del self._active_requests[msg_id]
            if msg_id in self._request_timeouts:
                self._request_timeouts[msg_id].cancel()
                del self._request_timeouts[msg_id]
            
            # Send cancellation notification to server
            self.send_notification("$/cancelRequest", {"id": msg_id})
            log.debug(f"Cancelled request {msg_id}")

    def send_notification(self, method: str, params: Any):
        """Send a JSON-RPC notification."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        self._send(payload)

    def _send(self, payload: Dict):
        """Low-level transport: send bytes with Content-Length header."""
        if not self.process or not self.process.stdin:
            # Queue message for when connection is restored
            self._pending_messages.append(payload)
            return
            
        body = json.dumps(payload).encode('utf-8')
        header = f"Content-Length: {len(body)}\r\n\r\n".encode('ascii')
        
        try:
            self.process.stdin.write(header)
            self.process.stdin.write(body)
            self.process.stdin.flush()
        except Exception as e:
            log.error(f"LSP Transport Write Error in {self.name}: {e}")
            self._handle_connection_error(e)

    def _stderr_loop(self):
        """Log LSP server errors."""
        if not self.process or not self.process.stderr: return
        while self._is_running and self.process:
            line = self.process.stderr.readline()
            if not line: break
            log.debug(f"[{self.name} STDERR] {line.decode('utf-8', errors='ignore').strip()}")

    def _read_loop(self):
        """Low-level reader loop handling LSP headers and JSON bodies."""
        if not self.process or not self.process.stdout: return
        stdout = self.process.stdout
        while self._is_running and self.process:
            try:
                line = stdout.readline()
                if not line: break
                
                line_str = line.decode('ascii', errors='ignore').strip()
                if line_str.startswith("Content-Length:"):
                    length = int(line_str.split(":")[1].strip())
                    
                    # Consume lines until we find the start of the body
                    while True:
                        l = stdout.readline().decode('ascii', errors='ignore').strip()
                        if not l: break
                    
                    body = stdout.read(length).decode('utf-8', errors='ignore')
                    msg = json.loads(body)
                    self._handle_message(msg)
            except Exception as e:
                log.error(f"LSP Read Loop error in {self.name}: {e}")
                break

    def _handle_message(self, msg: Dict):
        """Route messages with enhanced handler support."""
        # Clear timeout timer if this is a response to a request
        if "id" in msg:
            msg_id = msg["id"]
            if msg_id in self._request_timeouts:
                self._request_timeouts[msg_id].cancel()
                del self._request_timeouts[msg_id]
            if msg_id in self._active_requests:
                del self._active_requests[msg_id]
            
            if msg_id in self.callbacks:
                callback = self.callbacks.pop(msg_id)
                callback(msg.get("result"), msg.get("error"))
        
        # Handle server-initiated notifications
        elif "method" in msg:
            method = msg["method"]
            params = msg.get("params", {})
            
            # Route to appropriate handler
            handlers = {
                "textDocument/publishDiagnostics": self._on_diagnostics,
                "$/progress": self._on_progress,
                "window/showMessage": self._on_show_message,
                "window/logMessage": self._on_log_message,
            }
            
            handler = handlers.get(method)
            if handler:
                handler(params)
            
            # Emit generic message signal for extensibility
            self.message_received.emit(msg)
    
    def _on_diagnostics(self, params: Dict):
        """Handle diagnostic notifications."""
        if self.diagnostics_callback:
            self.diagnostics_callback(params)
    
    def _on_progress(self, params: Dict):
        """Handle progress notifications for long operations."""
        token = params.get("token")
        value = params.get("value", {})
        
        if value.get("kind") == "begin":
            log.info(f"LSP operation started: {value.get('title', 'Unknown')}")
            self.progress_started.emit(token, value)
        elif value.get("kind") == "report":
            percentage = value.get("percentage", 0)
            message = value.get("message", "")
            self.progress_updated.emit(token, percentage, message)
        elif value.get("kind") == "end":
            self.progress_ended.emit(token)
    
    def _on_show_message(self, params: Dict):
        """Handle window/showMessage notifications."""
        msg_type = params.get("type", 1)  # 1=Error, 2=Warning, 3=Info, 4=Log
        message = params.get("message", "")
        log.info(f"LSP Message ({msg_type}): {message}")
    
    def _on_log_message(self, params: Dict):
        """Handle window/logMessage notifications."""
        msg_type = params.get("type", 4)
        message = params.get("message", "")
        log.debug(f"LSP Log ({msg_type}): {message}")

    def _on_initialized(self, result, error):
        if error:
            log.error(f"LSP {self.name} init error: {error}")
            self._set_state(LSPConnectionState.ERROR)
        else:
            self.capabilities = result.get("capabilities", {})
            self.send_notification("initialized", {})
            self._set_state(LSPConnectionState.READY)
            log.info(f"LSP server {self.name} is ready.")

class LSPManager(QObject):
    """Manages language server instances with IntelliSense support."""
    diagnostics_updated = pyqtSignal(str, list)  # file_path, diagnostics
    
    _instance = None
    
    def __init__(self):
        super().__init__()
        if hasattr(self, '_initialized'): return
        self.servers: Dict[str, LSPServerInstance] = {}
        self.diagnostics_cache: Dict[str, List[Dict]] = {}
        self.doc_versions: Dict[str, int] = {}
        
        # Smart root detection
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            self.project_root = sys._MEIPASS
            self._is_bundled = True
        else:
            self.project_root = os.getcwd()
            self._is_bundled = False
            
        self._initialized = True

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LSPManager()
        return cls._instance

    def notify_changed(self, file_path: str, content: str, language: str):
        """Notify document changes with versioning."""
        server = self.get_server(language)
        if not server: return
        
        abs_path = os.path.abspath(file_path)
        uri = Path(abs_path).as_uri()
        v = self.doc_versions.get(abs_path, 0) + 1
        self.doc_versions[abs_path] = v
        
        if v == 1:
            server.send_notification("textDocument/didOpen", {
                "textDocument": {"uri": uri, "languageId": language, "version": v, "text": content}
            })
        else:
            server.send_notification("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": v},
                "contentChanges": [{"text": content}]
            })

    def _on_initialized(self, result: Dict, error: Optional[Dict]):
        if error:
            log.error(f"LSP server {self.name} initialization failed: {error}")

    def get_completions(self, file_path: str, line: int, col: int, language: str, callback: Callable):
        server = self.get_server(language)
        if not server: return
        uri = Path(os.path.abspath(file_path)).as_uri()
        params = {
            "textDocument": {"uri": uri}, 
            "position": {"line": line - 1, "character": col - 1},
            "context": {"triggerKind": 1} # Invoked
        }
        server.send_request("textDocument/completion", params, callback)

    def get_hover(self, file_path: str, line: int, col: int, language: str, callback: Callable):
        server = self.get_server(language)
        if not server: return
        uri = Path(os.path.abspath(file_path)).as_uri()
        params = {"textDocument": {"uri": uri}, "position": {"line": line - 1, "character": col - 1}}
        server.send_request("textDocument/hover", params, callback)

    def get_definition(self, file_path: str, line: int, col: int, 
                       language: str, callback: Callable):
        """Request definition location for symbol at position."""
        server = self.get_server(language)
        if not server: return
        
        uri = Path(os.path.abspath(file_path)).as_uri()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": col - 1}
        }
        
        def on_result(result, error):
            if error:
                log.error(f"Definition request failed: {error}")
                callback(None)
                return
            
            # Parse result - can be Location | Location[] | LocationLink[] | null
            if not result:
                callback(None)
                return
            
            # Normalize to list of locations
            locations = result if isinstance(result, list) else [result]
            
            parsed_locations = []
            for loc in locations:
                if isinstance(loc, dict):
                    # Handle LocationLink (newer format)
                    if "targetUri" in loc:
                        parsed_locations.append({
                            "uri": loc["targetUri"],
                            "range": loc.get("targetRange", loc.get("targetSelectionRange", {}))
                        })
                    # Handle Location (standard format)
                    elif "uri" in loc:
                        parsed_locations.append({
                            "uri": loc["uri"],
                            "range": loc.get("range", {})
                        })
            
            callback(parsed_locations)
        
        server.send_request("textDocument/definition", params, on_result)

    def prepare_rename(self, file_path: str, line: int, col: int,
                       language: str, callback: Callable):
        """Check if position can be renamed and get range."""
        server = self.get_server(language)
        if not server: return
        
        uri = Path(os.path.abspath(file_path)).as_uri()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": col - 1}
        }
        server.send_request("textDocument/prepareRename", params, callback)

    def rename_symbol(self, file_path: str, line: int, col: int,
                      new_name: str, language: str, callback: Callable):
        """Rename symbol across workspace."""
        server = self.get_server(language)
        if not server: return
        
        uri = Path(os.path.abspath(file_path)).as_uri()
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": col - 1},
            "newName": new_name
        }
        
        def on_result(result, error):
            if error:
                callback(None, error)
                return
            
            # Parse WorkspaceEdit
            if not result:
                callback(None, None)
                return
            
            # Result contains documentChanges or changes
            changes = result.get("documentChanges", result.get("changes", {}))
            callback(changes, None)
        
        server.send_request("textDocument/rename", params, on_result)

    def search_workspace_symbols(self, query: str, language: str, 
                                 callback: Callable):
        """Search for symbols across entire workspace."""
        server = self.get_server(language)
        if not server: return
        
        params = {
            "query": query,
            "limit": 50  # Limit results for performance
        }
        
        def on_result(result, error):
            if error or not result:
                callback([])
                return
            
            symbols = []
            for item in result:
                symbols.append({
                    "name": item.get("name"),
                    "kind": item.get("kind"),  # SymbolKind enum
                    "location": item.get("location"),
                    "containerName": item.get("containerName", "")
                })
            
            callback(symbols)
        
        server.send_request("workspace/symbol", params, on_result)

    def get_code_actions(self, file_path: str, line: int, col: int,
                         language: str, callback: Callable):
        """Get available code actions at position."""
        server = self.get_server(language)
        if not server: return
        
        uri = Path(os.path.abspath(file_path)).as_uri()
        params = {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": line - 1, "character": col - 1},
                "end": {"line": line - 1, "character": col - 1}
            },
            "context": {
                "diagnostics": [],  # Could include current diagnostics
                "only": ["quickfix", "refactor", "source"]  # Filter by kind
            }
        }
        server.send_request("textDocument/codeAction", params, callback)

    def execute_code_action(self, action: Dict, language: str, callback: Callable):
        """Execute a code action (apply quick fix)."""
        server = self.get_server(language)
        if not server: return
        
        # If action has edit, apply directly
        if "edit" in action:
            callback(action["edit"])
            return
        
        # Otherwise, execute command
        if "command" in action:
            command = action["command"]
            if isinstance(command, dict):
                server.send_request("workspace/executeCommand", {
                    "command": command.get("command"),
                    "arguments": command.get("arguments", [])
                }, callback)

    def _on_diagnostics(self, params: Dict):
        uri = params.get("uri", "")
        if not uri: return
        try:
            parsed = urlparse(uri)
            path = url2pathname(parsed.path)
            if os.name == 'nt' and path.startswith('\\') and len(path) > 2 and path[2] == ':':
                path = path[1:]
            
            normalized_path = os.path.normcase(os.path.normpath(path))
            
            # Store in cache
            diagnostics = params.get("diagnostics", [])
            self.diagnostics_cache[normalized_path] = diagnostics
            
            # BROADCAST: Emit signal for reactive UI updates
            try:
                self.diagnostics_updated.emit(normalized_path, diagnostics)
            except RuntimeError:
                # Occurs during shutdown if the QObject is already deleted
                pass
            
        except Exception as e:
            log.error(f"LSP Diagnostics Conversion Error: {e}")

    def get_diagnostics(self, file_path: str) -> List[Dict]:
        """Fetch cached diagnostics for the given file."""
        return self.diagnostics_cache.get(os.path.normcase(os.path.normpath(file_path)), [])

    def get_server(self, language: str) -> Optional[LSPServerInstance]:
        """Get or start the appropriate LSP server for the language."""
        lang = language.lower()
        if lang in ["js", "ts", "javascript", "typescript"]: lang = "typescript"
        elif lang in ["c", "cpp", "c++", "objc", "objcpp"]: lang = "clangd"
        elif lang in ["java"]: lang = "java"
        elif lang in ["bash", "sh"]: lang = "bash"
        elif lang in ["json"]: lang = "json"
        
        if lang in self.servers: return self.servers[lang]
        
        cmd = self._find_server_command(lang)
        if not cmd: return None
        
        root_uri = Path(self.project_root).as_uri()
        server = LSPServerInstance(lang, cmd, root_uri)
        server.diagnostics_callback = self._on_diagnostics
        
        if server.start():
            self.servers[lang] = server
            return server
        return None

    def _get_node_path(self) -> str:
        if self._is_bundled:
            p = os.path.join(self.project_root, "bin", "node", "node.exe")
            if os.path.exists(p): return p
        return "node"

    def _get_server_bin_path(self, server_bin: str) -> str:
        exts = ["", ".cmd", ".ps1"] if os.name == 'nt' else [""]
        for ext in exts:
            p = os.path.join(self.project_root, "node_modules", ".bin", f"{server_bin}{ext}")
            if os.path.exists(p): return p
        return server_bin

    def _find_server_command(self, lang: str) -> Optional[List[str]]:
        """Map language to professional LSP server command (Bundled or System)."""
        node = self._get_node_path()
        
        # 1. Node-based servers
        if lang == "python":
            bin_p = self._get_server_bin_path("pyright-langserver")
            return [node, bin_p, "--stdio"] if node != "node" else [bin_p, "--stdio"]
            
        elif lang == "typescript":
            bin_p = self._get_server_bin_path("typescript-language-server")
            return [node, bin_p, "--stdio"] if node != "node" else [bin_p, "--stdio"]
            
        elif lang == "html":
            bin_p = self._get_server_bin_path("vscode-html-language-server")
            return [node, bin_p, "--stdio"] if node != "node" else [bin_p, "--stdio"]
            
        elif lang == "css":
            bin_p = self._get_server_bin_path("vscode-css-language-server")
            return [node, bin_p, "--stdio"] if node != "node" else [bin_p, "--stdio"]
            
        elif lang == "json":
            bin_p = self._get_server_bin_path("vscode-json-language-server")
            return [node, bin_p, "--stdio"] if node != "node" else [bin_p, "--stdio"]
            
        # 2. Native binary servers (must be in system PATH)
        elif lang == "clangd":
            # standard LLVM LSP for C/C++/ObjC
            return ["clangd", "--background-index"]
            
        elif lang == "java":
            # standard Eclipse JDT.LS
            return ["jdtls"]
            
        elif lang == "bash":
            bin_p = self._get_server_bin_path("bash-language-server")
            return [node, bin_p, "start"]
            
        return None

    def shutdown_all(self):
        for s in list(self.servers.values()): s.stop()
        self.servers.clear()

def get_lsp_manager():
    return LSPManager.get_instance()
