"""
remote/RemoteSessionManager.py
Python conversion of remote/RemoteSessionManager.ts (344 lines)

Remote session manager for Cortex IDE with multi-LLM support.
Manages WebSocket connections to remote AI sessions (CCR/cloud agents).

Adapted for Cortex IDE:
- PyQt6 signal-based callbacks instead of TypeScript callbacks
- Multi-LLM provider support (Anthropic, OpenAI, Gemini, etc.)
- Async/await for WebSocket operations
- Thread-safe for GUI event loop integration
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


@dataclass
class RemotePermissionResponse:
    """Permission response for remote sessions."""
    behavior: str  # 'allow' or 'deny'
    updated_input: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


@dataclass
class RemoteSessionConfig:
    """Configuration for a remote session."""
    session_id: str
    get_access_token: Callable[[], str]
    org_uuid: str
    has_initial_prompt: bool = False
    viewer_only: bool = False  # True if pure viewer (no interrupt capability)
    provider: str = ""  # LLM provider for multi-LLM routing (e.g., "anthropic", "openai", "gemini")


class RemoteSessionSignals(QObject):
    """
    PyQt6 signals for remote session events.
    Replaces TypeScript callback functions with Qt signals.
    """
    # Message received from remote session
    message_received = pyqtSignal(dict)  # SDKMessage dict
    
    # Permission request from remote agent
    permission_requested = pyqtSignal(dict, str)  # request_dict, request_id
    
    # Permission request cancelled by server
    permission_cancelled = pyqtSignal(str, str)  # request_id, tool_use_id
    
    # Connection state changes
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    reconnecting = pyqtSignal()
    
    # Error handling
    error_occurred = pyqtSignal(str)  # error_message


class RemoteSessionManager:
    """
    Manages a remote CCR (Claude Code Runtime) session for Cortex IDE.
    
    Coordinates:
    - WebSocket connection for receiving messages from remote session
    - HTTP POST for sending user messages to remote session
    - Permission request/response flow for tool approval
    - Multi-LLM provider support via session metadata
    
    Usage:
        config = RemoteSessionConfig(
            session_id="session_abc123",
            get_access_token=lambda: "token_here",
            org_uuid="org_xyz"
        )
        manager = RemoteSessionManager(config)
        manager.signals.message_received.connect(on_message)
        manager.connect()
    """
    
    def __init__(self, config: RemoteSessionConfig):
        self.config = config
        self.signals = RemoteSessionSignals()
        self._websocket: Optional[Any] = None  # WebSocket client (lazy import)
        self._pending_permission_requests: Dict[str, Dict[str, Any]] = {}
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def connect(self) -> None:
        """
        Connect to the remote session via WebSocket.
        Must be called from an async context.
        """
        logger.info(f"[RemoteSessionManager] Connecting to session {self.config.session_id}")
        
        try:
            # Import here to avoid circular dependency
            from .SessionsWebSocket import SessionsWebSocket, SessionsWebSocketCallbacks
            
            callbacks = SessionsWebSocketCallbacks(
                on_message=self._handle_message,
                on_connected=self._on_connected,
                on_closed=self._on_disconnected,
                on_reconnecting=self._on_reconnecting,
                on_error=self._on_error,
            )
            
            self._websocket = SessionsWebSocket(
                session_id=self.config.session_id,
                org_uuid=self.config.org_uuid,
                get_access_token=self.config.get_access_token,
                callbacks=callbacks,
            )
            
            await self._websocket.connect()
            
        except Exception as e:
            logger.error(f"[RemoteSessionManager] Connection failed: {e}")
            self.signals.error_occurred.emit(str(e))
    
    def _handle_message(self, message: Dict[str, Any]) -> None:
        """
        Handle messages from WebSocket.
        Routes control requests vs SDK messages.
        """
        msg_type = message.get("type")
        
        # Handle control requests (permission prompts from remote)
        if msg_type == "control_request":
            self._handle_control_request(message)
            return
        
        # Handle control cancel requests (server cancelling permission prompt)
        if msg_type == "control_cancel_request":
            request_id = message.get("request_id", "")
            pending_request = self._pending_permission_requests.pop(request_id, None)
            logger.info(f"[RemoteSessionManager] Permission request cancelled: {request_id}")
            
            tool_use_id = pending_request.get("tool_use_id") if pending_request else None
            self.signals.permission_cancelled.emit(request_id, tool_use_id or "")
            return
        
        # Handle control responses (acknowledgments)
        if msg_type == "control_response":
            logger.debug("[RemoteSessionManager] Received control response")
            return
        
        # Forward SDK messages to callback
        self.signals.message_received.emit(message)
    
    def _handle_control_request(self, request: Dict[str, Any]) -> None:
        """Handle control requests from remote (e.g., permission requests)."""
        request_id = request.get("request_id", "")
        inner_request = request.get("request", {})
        subtype = inner_request.get("subtype")
        
        if subtype == "can_use_tool":
            tool_name = inner_request.get("tool_name", "unknown")
            logger.info(f"[RemoteSessionManager] Permission request for tool: {tool_name}")
            
            self._pending_permission_requests[request_id] = inner_request
            self.signals.permission_requested.emit(inner_request, request_id)
        else:
            # Send error response for unrecognized subtypes
            logger.warning(f"[RemoteSessionManager] Unsupported control request subtype: {subtype}")
            
            response = {
                "type": "control_response",
                "response": {
                    "subtype": "error",
                    "request_id": request_id,
                    "error": f"Unsupported control request subtype: {subtype}",
                },
            }
            
            if self._websocket:
                self._websocket.send_control_response(response)
    
    async def send_message(self, content: Dict[str, Any], opts: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send a user message to the remote session via HTTP POST.
        
        Args:
            content: Message content (text, images, etc.)
            opts: Optional parameters (uuid, etc.)
            
        Returns:
            True if message sent successfully
        """
        logger.info(f"[RemoteSessionManager] Sending message to session {self.config.session_id}")
        
        try:
            from ..utils.teleport.api import send_event_to_remote_session
            
            success = await send_event_to_remote_session(
                self.config.session_id,
                content,
                opts or {},
            )
            
            if not success:
                logger.error(f"[RemoteSessionManager] Failed to send message to session {self.config.session_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"[RemoteSessionManager] Error sending message: {e}")
            return False
    
    def respond_to_permission_request(self, request_id: str, result: RemotePermissionResponse) -> None:
        """
        Respond to a permission request from remote session.
        
        Args:
            request_id: ID of the permission request
            result: Permission response (allow/deny)
        """
        pending_request = self._pending_permission_requests.pop(request_id, None)
        
        if not pending_request:
            logger.error(f"[RemoteSessionManager] No pending permission request with ID: {request_id}")
            return
        
        response = {
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": request_id,
                "response": {
                    "behavior": result.behavior,
                    **({"updatedInput": result.updated_input} if result.behavior == "allow" and result.updated_input else {}),
                    **({"message": result.message} if result.behavior == "deny" and result.message else {}),
                },
            },
        }
        
        logger.info(f"[RemoteSessionManager] Sending permission response: {result.behavior}")
        
        if self._websocket:
            self._websocket.send_control_response(response)
    
    def is_connected(self) -> bool:
        """Check if connected to the remote session."""
        if self._websocket is not None and hasattr(self._websocket, 'is_connected'):
            return self._websocket.is_connected()
        return self._connected
    
    def cancel_session(self) -> None:
        """
        Send an interrupt signal to cancel the current request on the remote session.
        No-op if this is a viewer-only session.
        """
        if self.config.viewer_only:
            logger.debug("[RemoteSessionManager] Ignoring cancel - viewer_only mode")
            return
        
        logger.info("[RemoteSessionManager] Sending interrupt signal")
        
        if self._websocket:
            self._websocket.send_control_request({"subtype": "interrupt"})
    
    def get_session_id(self) -> str:
        """Get the session ID."""
        return self.config.session_id
    
    def disconnect(self) -> None:
        """Disconnect from the remote session."""
        logger.info("[RemoteSessionManager] Disconnecting")
        
        if self._websocket:
            self._websocket.close()
            self._websocket = None
        
        self._pending_permission_requests.clear()
        self._connected = False
    
    def reconnect(self) -> None:
        """Force reconnect the WebSocket."""
        logger.info("[RemoteSessionManager] Reconnecting WebSocket")
        
        if self._websocket:
            self._websocket.reconnect()
    
    # ---- Signal handlers ----
    
    def _on_connected(self) -> None:
        """Called when connection is established."""
        logger.info("[RemoteSessionManager] Connected")
        self._connected = True
        self.signals.connected.emit()
    
    def _on_disconnected(self) -> None:
        """Called when connection is lost and cannot be restored."""
        logger.info("[RemoteSessionManager] Disconnected")
        self._connected = False
        self.signals.disconnected.emit()
    
    def _on_reconnecting(self) -> None:
        """Called on transient WS drop while reconnect backoff is in progress."""
        logger.info("[RemoteSessionManager] Reconnecting")
        self.signals.reconnecting.emit()
    
    def _on_error(self, error: Exception) -> None:
        """Called on error."""
        logger.error(f"[RemoteSessionManager] Error: {error}")
        self.signals.error_occurred.emit(str(error))


def create_remote_session_config(
    session_id: str,
    get_access_token: Callable[[], str],
    org_uuid: str,
    has_initial_prompt: bool = False,
    viewer_only: bool = False,
    provider: str = "",
) -> RemoteSessionConfig:
    """
    Create a remote session config from OAuth tokens.
    
    Args:
        session_id: Remote session identifier
        get_access_token: Callable to retrieve current access token
        org_uuid: Organization UUID
        has_initial_prompt: True if session has initial prompt being processed
        viewer_only: True if pure viewer (no interrupt capability)
        provider: LLM provider name for multi-LLM routing
        
    Returns:
        RemoteSessionConfig instance
    """
    return RemoteSessionConfig(
        session_id=session_id,
        get_access_token=get_access_token,
        org_uuid=org_uuid,
        has_initial_prompt=has_initial_prompt,
        viewer_only=viewer_only,
        provider=provider,
    )


__all__: List[str] = [
    "RemotePermissionResponse",
    "RemoteSessionConfig",
    "RemoteSessionSignals",
    "RemoteSessionManager",
    "create_remote_session_config",
]
