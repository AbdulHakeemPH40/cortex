"""
services/lsp/lspServerManager.py
Python conversion of services/lsp/LSPServerManager.ts (421 lines)

LSP Server Manager - Manages multiple LSP server instances and routes requests
based on file extensions.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from services.lsp.config import get_all_lsp_servers
from services.lsp.lspServerInstance import LSPServerInstance, create_lsp_server_instance


class LSPServerManager:
    """
    LSP Server Manager - manages multiple LSP server instances and routes
    requests based on file extensions.
    
    Public interface returned by create_lsp_server_manager().
    """
    
    def __init__(self):
        """Initialize the manager with empty state."""
        # Private state
        self._servers: Dict[str, LSPServerInstance] = {}
        self._extension_map: Dict[str, list] = {}  # extension -> [server names]
        self._opened_files: Dict[str, str] = {}  # file URI -> server name
    
    async def initialize(self) -> None:
        """
        Initialize the manager by loading all configured LSP servers.
        
        Raises:
            Error: If configuration loading fails
        """
        try:
            result = await get_all_lsp_servers()
            server_configs = result.get('servers', {})
            log_for_debugging(
                f'[LSP SERVER MANAGER] getAllLspServers returned '
                f'{len(server_configs)} server(s)'
            )
        except Exception as error:
            log_error(
                Exception(f'Failed to load LSP server configuration: {error}')
            )
            raise
        
        # Build extension → server mapping
        for server_name, config in server_configs.items():
            try:
                # Validate config before using it
                if not config.get('command'):
                    raise ValueError(
                        f"Server {server_name} missing required 'command' field"
                    )
                
                ext_to_lang = config.get('extensionToLanguage', {})
                if not ext_to_lang or len(ext_to_lang) == 0:
                    raise ValueError(
                        f"Server {server_name} missing required "
                        f"'extensionToLanguage' field"
                    )
                
                # Map file extensions to this server (derive from extensionToLanguage)
                file_extensions = list(ext_to_lang.keys())
                for ext in file_extensions:
                    normalized = ext.lower()
                    if normalized not in self._extension_map:
                        self._extension_map[normalized] = []
                    self._extension_map[normalized].append(server_name)
                
                # Create server instance
                instance = create_lsp_server_instance(server_name, config)
                self._servers[server_name] = instance
                
                # Register handler for workspace/configuration requests from the server
                # Some servers (like TypeScript) send these even when we say we don't support them
                def handle_workspace_config(
                    params: Dict[str, Any],
                    s_name: str = server_name  # Capture server name
                ) -> list:
                    log_for_debugging(
                        f'LSP: Received workspace/configuration request '
                        f'from {s_name}'
                    )
                    # Return empty/null config for each requested item
                    # This satisfies the protocol without providing actual configuration
                    items = params.get('items', [])
                    return [None for _ in items]
                
                instance.on_request(
                    'workspace/configuration',
                    handle_workspace_config,
                )
                
            except Exception as error:
                log_error(
                    Exception(
                        f'Failed to initialize LSP server {server_name}: '
                        f'{error}'
                    )
                )
                # Continue with other servers - don't fail entire initialization
        
        log_for_debugging(
            f'LSP manager initialized with {len(self._servers)} servers'
        )
    
    async def shutdown(self) -> None:
        """
        Shutdown all running servers and clear state.
        
        Only servers in 'running' or 'error' state are explicitly stopped;
        servers in other states are cleared without shutdown.
        
        Raises:
            Error: If one or more servers fail to stop
        """
        to_stop = [
            (name, server)
            for name, server in self._servers.items()
            if server.state in ('running', 'error')
        ]
        
        # Stop all servers in parallel
        stop_tasks = [
            asyncio.create_task(server.stop())
            for _, server in to_stop
        ]
        results = await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        # Clear state
        self._servers.clear()
        self._extension_map.clear()
        self._opened_files.clear()
        
        # Collect errors
        errors = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                server_name = to_stop[i][0]
                errors.append(f'{server_name}: {error_message(result)}')
        
        if len(errors) > 0:
            error = Exception(
                f'Failed to stop {len(errors)} LSP server(s): '
                f'{"; ".join(errors)}'
            )
            log_error(error)
            raise error
    
    def get_server_for_file(self, file_path: str) -> Optional[LSPServerInstance]:
        """
        Get the LSP server instance for a given file path.
        
        If multiple servers handle the same extension, returns the first
        registered server.
        
        Returns:
            LSPServerInstance or None if no server handles this file type
        """
        ext = Path(file_path).suffix.lower()
        server_names = self._extension_map.get(ext)
        
        if not server_names or len(server_names) == 0:
            return None
        
        # Use first server (can add priority later)
        server_name = server_names[0]
        return self._servers.get(server_name)
    
    async def ensure_server_started(
        self,
        file_path: str,
    ) -> Optional[LSPServerInstance]:
        """
        Ensure the appropriate LSP server is started for the given file.
        
        Returns:
            LSPServerInstance or None if no server handles this file type
            
        Raises:
            Error: If server fails to start
        """
        server = self.get_server_for_file(file_path)
        if server is None:
            return None
        
        if server.state in ('stopped', 'error'):
            try:
                await server.start()
            except Exception as error:
                log_error(
                    Exception(
                        f'Failed to start LSP server for file {file_path}: '
                        f'{error}'
                    )
                )
                raise
        
        return server
    
    async def send_request(
        self,
        file_path: str,
        method: str,
        params: Any,
    ) -> Any:
        """
        Send a request to the appropriate LSP server for the given file.
        
        Returns:
            Server response or None if no server handles this file type
            
        Raises:
            Error: If server fails to start or request fails
        """
        server = await self.ensure_server_started(file_path)
        if server is None:
            return None
        
        try:
            return await server.send_request(method, params)
        except Exception as error:
            log_error(
                Exception(
                    f"LSP request failed for file {file_path}, "
                    f"method '{method}': {error}"
                )
            )
            raise
    
    def get_all_servers(self) -> Dict[str, LSPServerInstance]:
        """Get all running server instances."""
        return self._servers
    
    async def open_file(self, file_path: str, content: str) -> None:
        """
        Synchronize file open to LSP server (sends didOpen notification).
        
        Raises:
            Error: If notification fails
        """
        server = await self.ensure_server_started(file_path)
        if server is None:
            return
        
        file_uri = Path(file_path).resolve().as_uri()
        
        # Skip if already opened on this server
        if self._opened_files.get(file_uri) == server.name:
            log_for_debugging(
                f'LSP: File already open, skipping didOpen for {file_path}'
            )
            return
        
        # Get language ID from server's extensionToLanguage mapping
        ext = Path(file_path).suffix.lower()
        ext_to_lang = server.config.get('extensionToLanguage', {})
        language_id = ext_to_lang.get(ext, 'plaintext')
        
        try:
            await server.send_notification('textDocument/didOpen', {
                'textDocument': {
                    'uri': file_uri,
                    'languageId': language_id,
                    'version': 1,
                    'text': content,
                }
            })
            # Track that this file is now open on this server
            self._opened_files[file_uri] = server.name
            log_for_debugging(
                f'LSP: Sent didOpen for {file_path} '
                f'(languageId: {language_id})'
            )
        except Exception as error:
            err = Exception(
                f'Failed to sync file open {file_path}: {error_message(error)}'
            )
            log_error(err)
            # Re-throw to propagate error to caller
            raise err
    
    async def change_file(self, file_path: str, content: str) -> None:
        """
        Synchronize file change to LSP server (sends didChange notification).
        
        If file hasn't been opened yet, opens it first.
        
        Raises:
            Error: If notification fails
        """
        server = self.get_server_for_file(file_path)
        if server is None or server.state != 'running':
            return await self.open_file(file_path, content)
        
        file_uri = Path(file_path).resolve().as_uri()
        
        # If file hasn't been opened on this server yet, open it first
        # LSP servers require didOpen before didChange
        if self._opened_files.get(file_uri) != server.name:
            return await self.open_file(file_path, content)
        
        try:
            await server.send_notification('textDocument/didChange', {
                'textDocument': {
                    'uri': file_uri,
                    'version': 1,
                },
                'contentChanges': [{'text': content}],
            })
            log_for_debugging(f'LSP: Sent didChange for {file_path}')
        except Exception as error:
            err = Exception(
                f'Failed to sync file change {file_path}: '
                f'{error_message(error)}'
            )
            log_error(err)
            # Re-throw to propagate error to caller
            raise err
    
    async def save_file(self, file_path: str) -> None:
        """
        Save a file in LSP servers (sends didSave notification).
        
        Called after file is written to disk to trigger diagnostics.
        
        Raises:
            Error: If notification fails
        """
        server = self.get_server_for_file(file_path)
        if server is None or server.state != 'running':
            return
        
        try:
            file_uri = Path(file_path).resolve().as_uri()
            await server.send_notification('textDocument/didSave', {
                'textDocument': {
                    'uri': file_uri,
                }
            })
            log_for_debugging(f'LSP: Sent didSave for {file_path}')
        except Exception as error:
            err = Exception(
                f'Failed to sync file save {file_path}: '
                f'{error_message(error)}'
            )
            log_error(err)
            # Re-throw to propagate error to caller
            raise err
    
    async def close_file(self, file_path: str) -> None:
        """
        Close a file in LSP servers (sends didClose notification).
        
        NOTE: Currently available but not yet integrated with compact flow.
        TODO: Integrate with compact - call close_file() when compact removes
              files from context. This will notify LSP servers that files are
              no longer in active use.
        
        Raises:
            Error: If notification fails
        """
        server = self.get_server_for_file(file_path)
        if server is None or server.state != 'running':
            return
        
        file_uri = Path(file_path).resolve().as_uri()
        
        try:
            await server.send_notification('textDocument/didClose', {
                'textDocument': {
                    'uri': file_uri,
                }
            })
            # Remove from tracking so file can be reopened later
            if file_uri in self._opened_files:
                del self._opened_files[file_uri]
            log_for_debugging(f'LSP: Sent didClose for {file_path}')
        except Exception as error:
            err = Exception(
                f'Failed to sync file close {file_path}: '
                f'{error_message(error)}'
            )
            log_error(err)
            # Re-throw to propagate error to caller
            raise err
    
    def is_file_open(self, file_path: str) -> bool:
        """Check if a file is already open on a compatible LSP server."""
        file_uri = Path(file_path).resolve().as_uri()
        return file_uri in self._opened_files


def create_lsp_server_manager() -> LSPServerManager:
    """
    Factory function to create an LSP server manager instance.
    
    Manages multiple LSP server instances and routes requests based on
    file extensions.
    
    Returns:
        LSPServerManager instance
    
    Example:
        manager = create_lsp_server_manager()
        await manager.initialize()
        result = await manager.send_request(
            '/path/to/file.ts',
            'textDocument/definition',
            params
        )
        await manager.shutdown()
    """
    return LSPServerManager()


__all__ = [
    'LSPServerManager',
    'create_lsp_server_manager',
]
