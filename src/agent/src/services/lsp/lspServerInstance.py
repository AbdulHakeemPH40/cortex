"""
services/lsp/lspServerInstance.py
Python conversion of services/lsp/LSPServerInstance.ts (512 lines)

Single LSP server instance lifecycle management.
Manages state machine, health monitoring, request retry logic, and crash recovery.
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional


# Type aliases
LspServerState = str  # 'stopped' | 'starting' | 'running' | 'stopping' | 'error'
ScopedLspServerConfig = Dict[str, Any]


# LSP error codes
LSP_ERROR_CONTENT_MODIFIED = -32801

# Retry constants
MAX_RETRIES_FOR_TRANSIENT_ERRORS = 3
RETRY_BASE_DELAY_MS = 500


class LSPServerInstance:
    """
    Manages a single LSP server instance with lifecycle management.
    
    State machine transitions:
    - stopped → starting → running
    - running → stopping → stopped
    - any → error (on failure)
    - error → starting (on retry)
    """
    
    def __init__(self, name: str, config: ScopedLspServerConfig):
        """
        Create an LSP server instance.
        
        Args:
            name: Unique server identifier
            config: Server configuration (command, args, limits, etc.)
        """
        self.name = name
        self.config = config
        
        # Validate that unimplemented fields are not set
        if config.get('restartOnCrash') is not None:
            raise ValueError(
                f"LSP server '{name}': restartOnCrash is not yet implemented. "
                f"Remove this field from the configuration."
            )
        if config.get('shutdownTimeout') is not None:
            raise ValueError(
                f"LSP server '{name}': shutdownTimeout is not yet implemented. "
                f"Remove this field from the configuration."
            )
        
        # Private state
        self._state: LspServerState = 'stopped'
        self._start_time: Optional[datetime] = None
        self._last_error: Optional[Exception] = None
        self._restart_count = 0
        self._crash_recovery_count = 0
        
        # Lazy import LSPClient to avoid loading unless needed
        from services.lsp.lspClient import create_lsp_client
        
        # Create LSP client with crash callback
        def on_crash(error: Exception) -> None:
            self._state = 'error'
            self._last_error = error
            self._crash_recovery_count += 1
        
        self._client = create_lsp_client(name, on_crash)
    
    @property
    def state(self) -> LspServerState:
        """Current server state."""
        return self._state
    
    @property
    def start_time(self) -> Optional[datetime]:
        """When the server was last started."""
        return self._start_time
    
    @property
    def last_error(self) -> Optional[Exception]:
        """Last error encountered."""
        return self._last_error
    
    @property
    def restart_count(self) -> int:
        """Number of times restart() has been called."""
        return self._restart_count
    
    async def start(self) -> None:
        """
        Start the LSP server and initialize it with workspace info.
        
        If already running or starting, returns immediately.
        On failure, sets state to 'error' and throws.
        """
        if self._state in ('running', 'starting'):
            return
        
        # Cap crash-recovery attempts
        max_restarts = self.config.get('maxRestarts', 3)
        if self._state == 'error' and self._crash_recovery_count > max_restarts:
            error = ValueError(
                f"LSP server '{self.name}' exceeded max crash recovery attempts ({max_restarts})"
            )
            self._last_error = error
            log_error(error)
            raise error
        
        init_task: Optional[asyncio.Task] = None
        try:
            self._state = 'starting'
            from services.utils.debug import log_for_debugging
            log_for_debugging(f'Starting LSP server instance: {self.name}')
            
            # Start the client
            await self._client.start(
                self.config['command'],
                self.config.get('args', []),
                {
                    'env': self.config.get('env'),
                    'cwd': self.config.get('workspaceFolder'),
                }
            )
            
            # Build initialization parameters
            workspace_folder = self.config.get('workspaceFolder') or os.getcwd()
            workspace_uri = Path(workspace_folder).as_uri()
            
            init_params = {
                'processId': os.getpid(),
                'initializationOptions': self.config.get('initializationOptions', {}),
                'workspaceFolders': [
                    {
                        'uri': workspace_uri,
                        'name': Path(workspace_folder).name,
                    }
                ],
                # Deprecated but needed by some servers
                'rootPath': workspace_folder,
                'rootUri': workspace_uri,
                # Client capabilities
                'capabilities': {
                    'workspace': {
                        'configuration': False,
                        'workspaceFolders': False,
                    },
                    'textDocument': {
                        'synchronization': {
                            'dynamicRegistration': False,
                            'willSave': False,
                            'willSaveWaitUntil': False,
                            'didSave': True,
                        },
                        'publishDiagnostics': {
                            'relatedInformation': True,
                            'tagSupport': {
                                'valueSet': [1, 2],  # Unnecessary, Deprecated
                            },
                            'versionSupport': False,
                            'codeDescriptionSupport': True,
                            'dataSupport': False,
                        },
                        'hover': {
                            'dynamicRegistration': False,
                            'contentFormat': ['markdown', 'plaintext'],
                        },
                        'definition': {
                            'dynamicRegistration': False,
                            'linkSupport': True,
                        },
                        'references': {
                            'dynamicRegistration': False,
                        },
                        'documentSymbol': {
                            'dynamicRegistration': False,
                            'hierarchicalDocumentSymbolSupport': True,
                        },
                        'callHierarchy': {
                            'dynamicRegistration': False,
                        },
                    },
                    'general': {
                        'positionEncodings': ['utf-16'],
                    },
                },
            }
            
            # Initialize with optional timeout
            init_task = asyncio.create_task(self._client.initialize(init_params))
            
            startup_timeout = self.config.get('startupTimeout')
            if startup_timeout is not None:
                try:
                    await asyncio.wait_for(
                        init_task,
                        timeout=startup_timeout / 1000.0,  # Convert ms to seconds
                    )
                except asyncio.TimeoutError:
                    # Cancel the task on timeout to prevent background continuation
                    init_task.cancel()
                    try:
                        await init_task
                    except asyncio.CancelledError:
                        pass
                    raise TimeoutError(
                        f"LSP server '{self.name}' timed out after {startup_timeout}ms during initialization"
                    )
            else:
                await init_task
            
            # Success
            self._state = 'running'
            self._start_time = datetime.now()
            self._crash_recovery_count = 0
            log_for_debugging(f'LSP server instance started: {self.name}')
            
        except Exception as error:
            # Clean up on failure
            try:
                await self._client.stop()
            except Exception:
                pass  # Ignore cleanup errors
            
            # Cancel and await init_task to prevent unhandled errors
            if init_task and not init_task.done():
                init_task.cancel()
                try:
                    await init_task
                except asyncio.CancelledError:
                    pass
            
            self._state = 'error'
            self._last_error = error
            
            log_error(error)
            raise
    
    async def stop(self) -> None:
        """
        Stop the LSP server gracefully.
        
        If already stopped or stopping, returns immediately.
        On failure, sets state to 'error' and throws.
        """
        if self._state in ('stopped', 'stopping'):
            return
        
        try:
            self._state = 'stopping'
            await self._client.stop()
            self._state = 'stopped'
            
            from services.utils.debug import log_for_debugging
            log_for_debugging(f'LSP server instance stopped: {self.name}')
            
        except Exception as error:
            self._state = 'error'
            self._last_error = error
            
            log_error(error)
            raise
    
    async def restart(self) -> None:
        """
        Manually restart the server (stop then start).
        
        Enforces maxRestarts limit (default: 3).
        """
        try:
            await self.stop()
        except Exception as error:
            from services.utils.errors import error_message
            stop_error = ValueError(
                f"Failed to stop LSP server '{self.name}' during restart: "
                f"{error_message(error)}"
            )
            log_error(stop_error)
            raise stop_error
        
        self._restart_count += 1
        
        max_restarts = self.config.get('maxRestarts', 3)
        if self._restart_count > max_restarts:
            error = ValueError(
                f"Max restart attempts ({max_restarts}) exceeded for server '{self.name}'"
            )
            log_error(error)
            raise error
        
        try:
            await self.start()
        except Exception as error:
            from services.utils.errors import error_message
            start_error = ValueError(
                f"Failed to start LSP server '{self.name}' during restart "
                f"(attempt {self._restart_count}/{max_restarts}): "
                f"{error_message(error)}"
            )
            log_error(start_error)
            raise start_error
    
    def is_healthy(self) -> bool:
        """
        Check if server is healthy and ready for requests.
        
        Returns:
            True if state is 'running' AND client is initialized
        """
        return self._state == 'running' and self._client.is_initialized
    
    async def send_request(self, method: str, params: Any) -> Any:
        """
        Send an LSP request with retry logic for transient errors.
        
        Automatically retries on "content modified" errors (-32801) which occur
        when servers like rust-analyzer are still indexing.
        
        Args:
            method: LSP method name (e.g., 'textDocument/definition')
            params: Method parameters
            
        Returns:
            Server response
            
        Raises:
            ValueError: If server is not healthy
            Exception: If request fails after all retries
        """
        if not self.is_healthy():
            error_msg = (
                f"Cannot send request to LSP server '{self.name}': "
                f"server is {self._state}"
            )
            if self._last_error:
                error_msg += f', last error: {self._last_error}'
            
            error = ValueError(error_msg)
            log_error(error)
            raise error
        
        last_attempt_error: Optional[Exception] = None
        
        for attempt in range(MAX_RETRIES_FOR_TRANSIENT_ERRORS + 1):
            try:
                return await self._client.send_request(method, params)
                
            except Exception as error:
                last_attempt_error = error
                
                # Check if this is a transient "content modified" error
                error_code = getattr(error, 'code', None)
                is_content_modified = (
                    isinstance(error_code, (int, float)) and
                    error_code == LSP_ERROR_CONTENT_MODIFIED
                )
                
                if is_content_modified and attempt < MAX_RETRIES_FOR_TRANSIENT_ERRORS:
                    delay = RETRY_BASE_DELAY_MS * (2 ** attempt)
                    log_for_debugging(
                        f"LSP request '{method}' to '{self.name}' got ContentModified error, "
                        f"retrying in {delay}ms (attempt {attempt + 1}/{MAX_RETRIES_FOR_TRANSIENT_ERRORS})"
                    )
                    await asyncio.sleep(delay / 1000.0)
                    continue
                
                # Non-retryable error or max retries exceeded
                break
        
        # All retries failed or non-retryable error
        request_error = ValueError(
            f"LSP request '{method}' failed for server '{self.name}': "
            f"{last_attempt_error or 'unknown error'}"
        )
        log_error(request_error)
        raise request_error
    
    async def send_notification(self, method: str, params: Any) -> None:
        """
        Send an LSP notification (fire-and-forget).
        Used for file synchronization (didOpen, didChange, didClose).
        """
        if not self.is_healthy():
            error = ValueError(
                f"Cannot send notification to LSP server '{self.name}': "
                f"server is {self._state}"
            )
            log_error(error)
            raise error
        
        try:
            await self._client.send_notification(method, params)
        except Exception as error:
            from services.utils.errors import error_message
            notification_error = ValueError(
                f"LSP notification '{method}' failed for server '{self.name}': "
                f"{error_message(error)}"
            )
            log_error(notification_error)
            raise notification_error
    
    def on_notification(self, method: str, handler: Callable[[Any], None]) -> None:
        """
        Register a handler for LSP notifications from the server.
        
        Args:
            method: LSP notification method (e.g., 'window/logMessage')
            handler: Callback function
        """
        self._client.on_notification(method, handler)
    
    def on_request(
        self,
        method: str,
        handler: Callable[[Any], Any],
    ) -> None:
        """
        Register a handler for LSP requests from the server.
        
        Some LSP servers send requests TO the client (reverse direction).
        
        Args:
            method: LSP request method (e.g., 'workspace/configuration')
            handler: Callback function (can be async)
        """
        self._client.on_request(method, handler)


def create_lsp_server_instance(
    name: str,
    config: ScopedLspServerConfig,
) -> LSPServerInstance:
    """
    Factory function to create an LSP server instance.
    
    Args:
        name: Unique server identifier
        config: Server configuration
        
    Returns:
        LSPServerInstance
    """
    return LSPServerInstance(name, config)


__all__ = [
    'LSPServerInstance',
    'create_lsp_server_instance',
]
