"""
services/mcp/elicitationHandler.py
Python conversion of services/mcp/elicitationHandler.ts (314 lines)

MCP elicitation handler for user confirmation/interaction flows.
Handles form and URL-based elicitation requests from MCP servers.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ElicitationWaitingState:
    """Configuration for the waiting state shown after the user opens a URL."""
    # Button label, e.g. "Retry now" or "Skip confirmation"
    action_label: str
    # Whether to show a visible Cancel button (e.g. for error-based retry flow)
    show_cancel: bool = False


@dataclass
class ElicitationRequestEvent:
    """Represents a queued elicitation request event."""
    server_name: str
    # The JSON-RPC request ID, unique per server connection
    request_id: Any  # string | number
    params: Dict[str, Any]
    signal: Optional[Any] = None  # Cancellation signal (optional)
    # Resolves the elicitation
    respond: Optional[Callable[[Dict[str, Any]], None]] = None
    # For URL elicitations: shown after user opens the browser
    waiting_state: Optional[ElicitationWaitingState] = None
    # Called when phase 2 (waiting) is dismissed by user action or completion
    on_waiting_dismiss: Optional[Callable[[str], None]] = None
    # Set to true by the completion notification handler when server confirms
    completed: bool = False


def get_elicitation_mode(params: Dict[str, Any]) -> str:
    """
    Determine the elicitation mode from request params.
    
    Args:
        params: Elicitation request params dict
        
    Returns:
        'url' or 'form'
    """
    return 'url' if params.get('mode') == 'url' else 'form'


def find_elicitation_in_queue(
    queue: List[ElicitationRequestEvent],
    server_name: str,
    elicitation_id: str,
) -> int:
    """
    Find a queued elicitation event by server name and elicitationId.
    
    Args:
        queue: Queue of elicitation events
        server_name: Server name to match
        elicitation_id: Elicitation ID to match
        
    Returns:
        Index in queue or -1 if not found
    """
    for i, event in enumerate(queue):
        if (
            event.server_name == server_name
            and event.params.get('mode') == 'url'
            and 'elicitationId' in event.params
            and event.params.get('elicitationId') == elicitation_id
        ):
            return i
    return -1


class ElicitationManager:
    """
    Manages MCP elicitation requests and responses.
    
    This class replaces the React hook pattern with a Python class that
    manages elicitation state and handles request/response cycles.
    """
    
    def __init__(
        self,
        state_update_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        run_hooks_callback: Optional[Callable] = None,
        run_result_hooks_callback: Optional[Callable] = None,
        log_debug: Optional[Callable[[str, str], None]] = None,
        log_error: Optional[Callable[[str, str], None]] = None,
        log_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        """
        Initialize the elicitation manager.
        
        Args:
            state_update_callback: Function to update application state
            run_hooks_callback: Function to run elicitation hooks
            run_result_hooks_callback: Function to run elicitation result hooks
            log_debug: Debug logging function
            log_error: Error logging function
            log_event: Analytics logging function
        """
        self._queue: List[ElicitationRequestEvent] = []
        self._state_update_callback = state_update_callback
        self._run_hooks_callback = run_hooks_callback
        self._run_result_hooks_callback = run_result_hooks_callback
        self._log_debug = log_debug or (lambda n, m: logger.debug(f"[{n}] {m}"))
        self._log_error = log_error or (lambda n, m: logger.error(f"[{n}] {m}"))
        self._log_event = log_event or (lambda e, d: None)
    
    def register_elicitation_handler(
        self,
        client: Any,
        server_name: str,
    ) -> None:
        """
        Register the elicitation request handler on an MCP client.
        
        Args:
            client: MCP client instance
            server_name: Name of the MCP server
            
        Note:
            Wrapped in try/catch because setRequestHandler throws if the client
            wasn't created with elicitation capability declared.
        """
        try:
            # Register the elicitation request handler
            client.setRequestHandler(
                'elicitation/request',
                self._create_request_handler(server_name),
            )
            
            # Register handler for elicitation completion notifications (URL mode)
            client.setNotificationHandler(
                'notifications/elicitation/complete',
                lambda notification: self._handle_completion_notification(
                    server_name,
                    notification,
                ),
            )
            
        except Exception:
            # Client wasn't created with elicitation capability - nothing to register
            logger.debug(
                f"Client for {server_name} doesn't support elicitation capability"
            )
    
    def _create_request_handler(self, server_name: str) -> Callable:
        """
        Create an elicitation request handler for a specific server.
        
        Args:
            server_name: Name of the MCP server
            
        Returns:
            Async request handler function
        """
        async def handler(request: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
            self._log_debug(
                server_name,
                f"Received elicitation request: {request}",
            )
            
            mode = get_elicitation_mode(request.get('params', {}))
            
            self._log_event('tengu_mcp_elicitation_shown', {
                'mode': mode,
            })
            
            try:
                # Run elicitation hooks first - they can provide a response programmatically
                hook_response = await self.run_elicitation_hooks(
                    server_name,
                    request.get('params', {}),
                    extra.get('signal'),
                )
                
                if hook_response:
                    self._log_debug(
                        server_name,
                        f"Elicitation resolved by hook: {hook_response}",
                    )
                    self._log_event('tengu_mcp_elicitation_response', {
                        'mode': mode,
                        'action': hook_response.get('action'),
                    })
                    return hook_response
                
                # Extract elicitation ID for URL mode
                elicitation_id = None
                if mode == 'url' and 'elicitationId' in request.get('params', {}):
                    elicitation_id = request['params'].get('elicitationId')
                
                # Create response promise
                response = asyncio.get_event_loop().create_future()
                
                def on_abort():
                    if not response.done():
                        response.set_result({'action': 'cancel'})
                
                # Check if already aborted
                signal = extra.get('signal')
                if signal and getattr(signal, 'is_set', lambda: False)():
                    on_abort()
                    return await response
                
                # Create waiting state for URL mode
                waiting_state = None
                if elicitation_id:
                    waiting_state = ElicitationWaitingState(
                        action_label='Skip confirmation',
                    )
                
                # Create respond callback
                def respond(result: Dict[str, Any]):
                    self._log_event('tengu_mcp_elicitation_response', {
                        'mode': mode,
                        'action': result.get('action'),
                    })
                    if not response.done():
                        response.set_result(result)
                
                # Add to queue
                event = ElicitationRequestEvent(
                    server_name=server_name,
                    request_id=extra.get('requestId'),
                    params=request.get('params', {}),
                    signal=signal,
                    waiting_state=waiting_state,
                    respond=respond,
                )
                
                # Update state
                self._add_to_queue(event)
                
                # Wait for response
                raw_result = await response
                
                self._log_debug(
                    server_name,
                    f"Elicitation response: {raw_result}",
                )
                
                # Run result hooks
                result = await self.run_elicitation_result_hooks(
                    server_name,
                    raw_result,
                    signal,
                    mode,
                    elicitation_id,
                )
                
                return result
                
            except Exception as error:
                self._log_error(server_name, f"Elicitation error: {error}")
                return {'action': 'cancel'}
        
        return handler
    
    def _add_to_queue(self, event: ElicitationRequestEvent) -> None:
        """
        Add an elicitation event to the queue and update state.
        
        Args:
            event: Elicitation request event to add
        """
        self._queue.append(event)
        
        # Update application state
        if self._state_update_callback:
            self._state_update_callback({
                'elicitation': {
                    'queue': self._queue.copy(),
                },
            })
    
    def _handle_completion_notification(
        self,
        server_name: str,
        notification: Dict[str, Any],
    ) -> None:
        """
        Handle elicitation completion notification (URL mode).
        
        Sets `completed: true` on the matching queue event; the dialog reacts to this flag.
        
        Args:
            server_name: Name of the MCP server
            notification: Completion notification dict
        """
        elicitation_id = notification.get('params', {}).get('elicitationId', '')
        
        self._log_debug(
            server_name,
            f"Received elicitation completion notification: {elicitation_id}",
        )
        
        # Execute notification hooks
        try:
            self._execute_notification_hooks({
                'message': f'MCP server "{server_name}" confirmed elicitation {elicitation_id} complete',
                'notificationType': 'elicitation_complete',
            })
        except Exception:
            pass
        
        # Find and mark the elicitation as completed
        found = False
        idx = find_elicitation_in_queue(
            self._queue,
            server_name,
            elicitation_id,
        )
        
        if idx != -1:
            self._queue[idx].completed = True
            found = True
            
            # Update state
            if self._state_update_callback:
                self._state_update_callback({
                    'elicitation': {
                        'queue': self._queue.copy(),
                    },
                })
        
        if not found:
            self._log_debug(
                server_name,
                f"Ignoring completion notification for unknown elicitation: {elicitation_id}",
            )
    
    async def run_elicitation_hooks(
        self,
        server_name: str,
        params: Dict[str, Any],
        signal: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run elicitation hooks - they can provide a response programmatically.
        
        Args:
            server_name: Name of the MCP server
            params: Elicitation request params
            signal: Cancellation signal
            
        Returns:
            Elicitation result dict from hooks, or None if no hook responded
        """
        try:
            mode = 'url' if params.get('mode') == 'url' else 'form'
            url = params.get('url')
            elicitation_id = params.get('elicitationId')
            
            if not self._run_hooks_callback:
                return None
            
            result = await self._run_hooks_callback(
                server_name=server_name,
                message=params.get('message'),
                requested_schema=params.get('requestedSchema'),
                signal=signal,
                mode=mode,
                url=url,
                elicitation_id=elicitation_id,
            )
            
            if result and result.get('blockingError'):
                return {'action': 'decline'}
            
            if result and result.get('elicitationResponse'):
                hook_response = result['elicitationResponse']
                return {
                    'action': hook_response.get('action'),
                    'content': hook_response.get('content'),
                }
            
            return None
            
        except Exception as error:
            self._log_error(server_name, f"Elicitation hook error: {error}")
            return None
    
    async def run_elicitation_result_hooks(
        self,
        server_name: str,
        result: Dict[str, Any],
        signal: Optional[Any] = None,
        mode: Optional[str] = None,
        elicitation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run ElicitationResult hooks after the user has responded.
        
        Returns a (potentially modified) ElicitResult — hooks may override
        the action/content or block the response.
        
        Args:
            server_name: Name of the MCP server
            result: Original elicitation result
            signal: Cancellation signal
            mode: Elicitation mode ('form' or 'url')
            elicitation_id: Elicitation ID for URL mode
            
        Returns:
            Final (possibly modified) elicitation result
        """
        try:
            if not self._run_result_hooks_callback:
                return result
            
            hook_result = await self._run_result_hooks_callback(
                server_name=server_name,
                action=result.get('action'),
                content=result.get('content'),
                signal=signal,
                mode=mode,
                elicitation_id=elicitation_id,
            )
            
            if hook_result and hook_result.get('blockingError'):
                self._execute_notification_hooks({
                    'message': f'Elicitation response for server "{server_name}": decline',
                    'notificationType': 'elicitation_response',
                })
                return {'action': 'decline'}
            
            final_result = result
            if hook_result and hook_result.get('elicitationResultResponse'):
                hook_response = hook_result['elicitationResultResponse']
                final_result = {
                    'action': hook_response.get('action', result.get('action')),
                    'content': hook_response.get('content', result.get('content')),
                }
            
            # Fire a notification for observability
            self._execute_notification_hooks({
                'message': f'Elicitation response for server "{server_name}": {final_result.get("action")}',
                'notificationType': 'elicitation_response',
            })
            
            return final_result
            
        except Exception as error:
            self._log_error(server_name, f"ElicitationResult hook error: {error}")
            # Fire notification even on error
            self._execute_notification_hooks({
                'message': f'Elicitation response for server "{server_name}": {result.get("action")}',
                'notificationType': 'elicitation_response',
            })
            return result
    
    def _execute_notification_hooks(self, hook_data: Dict[str, Any]) -> None:
        """
        Execute notification hooks.
        
        Args:
            hook_data: Hook payload dict
        """
        # This would call executeNotificationHooks from utils/hooks.js
        # For now, just log the notification
        logger.debug(f"Notification hook: {hook_data}")
    
    def get_queue(self) -> List[ElicitationRequestEvent]:
        """Get the current elicitation queue."""
        return self._queue.copy()
    
    def clear_queue(self) -> None:
        """Clear the elicitation queue."""
        self._queue.clear()
        if self._state_update_callback:
            self._state_update_callback({
                'elicitation': {
                    'queue': [],
                },
            })


def register_elicitation_handler(
    client: Any,
    server_name: str,
    state_update_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> ElicitationManager:
    """
    Convenience function to create and register an elicitation handler.
    
    Args:
        client: MCP client instance
        server_name: Name of the MCP server
        state_update_callback: Function to update application state
        
    Returns:
        ElicitationManager instance
    """
    manager = ElicitationManager(
        state_update_callback=state_update_callback,
    )
    manager.register_elicitation_handler(client, server_name)
    return manager


__all__ = [
    'ElicitationWaitingState',
    'ElicitationRequestEvent',
    'ElicitationManager',
    'get_elicitation_mode',
    'find_elicitation_in_queue',
    'register_elicitation_handler',
]
