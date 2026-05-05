"""
services/lsp/lspManager.py
Python conversion of services/lsp/manager.ts (290 lines)

LSP (Language Server Protocol) server manager singleton.
Manages initialization, lifecycle, and state of LSP servers for IDE integration.
"""

import asyncio
from typing import Dict, Optional, Set
from dataclasses import dataclass

try:
    from ...utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(msg):
        print(f"[DEBUG] {msg}")

try:
    from ...utils.envUtils import is_bare_mode
except ImportError:
    def is_bare_mode():
        return False

try:
    from ...utils.errors import error_message
except ImportError:
    def error_message(err):
        return str(err)

try:
    from ...utils.log import log_error
except ImportError:
    def log_error(err):
        print(f"[ERROR] {err}")

try:
    from .LSPServerManager import LSPServerManager, create_lsp_server_manager
except ImportError:
    LSPServerManager = None
    def create_lsp_server_manager():
        return None

try:
    from .passiveFeedback import register_lsp_notification_handlers
except ImportError:
    def register_lsp_notification_handlers(manager):
        pass


@dataclass
class InitializationStatus:
    """LSP initialization status response"""
    status: str
    error: Optional[Exception] = None


# Module-level singleton state
_lsp_manager_instance: Optional[LSPServerManager] = None
_initialization_state: str = 'not-started'  # 'not-started' | 'pending' | 'success' | 'failed'
_initialization_error: Optional[Exception] = None
_initialization_generation: int = 0
_initialization_promise: Optional[asyncio.Task] = None


def _reset_lsp_manager_for_testing() -> None:
    """Reset LSP manager state for testing (sync-only)"""
    global _initialization_state, _initialization_error, _initialization_promise
    global _initialization_generation, _lsp_manager_instance
    
    _initialization_state = 'not-started'
    _initialization_error = None
    _initialization_promise = None
    _initialization_generation += 1
    _lsp_manager_instance = None


def get_lsp_server_manager() -> Optional[LSPServerManager]:
    """
    Get the singleton LSP server manager instance.
    Returns None if not yet initialized, initialization failed, or still pending.
    """
    global _initialization_state, _lsp_manager_instance
    
    if _initialization_state == 'failed':
        return None
    
    return _lsp_manager_instance


def get_initialization_status() -> InitializationStatus:
    """
    Get the current initialization status of the LSP server manager.
    
    Returns:
        InitializationStatus with current state and error (if failed)
    """
    global _initialization_state, _initialization_error
    
    if _initialization_state == 'failed':
        return InitializationStatus(
            status='failed',
            error=_initialization_error or Exception('Initialization failed'),
        )
    elif _initialization_state == 'not-started':
        return InitializationStatus(status='not-started')
    elif _initialization_state == 'pending':
        return InitializationStatus(status='pending')
    else:
        return InitializationStatus(status='success')


def is_lsp_connected() -> bool:
    """
    Check whether at least one language server is connected and healthy.
    Backs LSPTool.isEnabled().
    """
    global _initialization_state, _lsp_manager_instance
    
    if _initialization_state == 'failed':
        return False
    
    manager = get_lsp_server_manager()
    if not manager:
        return False
    
    servers = manager.get_all_servers()
    if not servers:
        return False
    
    for server in servers.values():
        if server.get('state') != 'error':
            return True
    
    return False


async def wait_for_initialization() -> None:
    """
    Wait for LSP server manager initialization to complete.
    
    Returns immediately if initialization has already completed (success or failure).
    If initialization is pending, waits for it to complete.
    If initialization hasn't started, returns immediately.
    """
    global _initialization_state, _initialization_promise
    
    if _initialization_state in ('success', 'failed'):
        return
    
    if _initialization_state == 'pending' and _initialization_promise:
        try:
            await _initialization_promise
        except Exception:
            pass  # Already logged elsewhere


def initialize_lsp_server_manager() -> None:
    """
    Initialize the LSP server manager singleton.
    
    Called during Claude Code startup. Creates manager instance synchronously,
    then starts async initialization in background without blocking startup.
    
    Safe to call multiple times - only initializes once (idempotent).
    If initialization previously failed, calling again will retry.
    """
    global _lsp_manager_instance, _initialization_state
    global _initialization_error, _initialization_generation
    global _initialization_promise
    
    # Bare mode: no LSP needed (headless AI agent with no editor integration)
    if is_bare_mode():
        return
    
    log_for_debugging('[LSP MANAGER] initializeLspServerManager() called')
    
    # Skip if already initialized or currently initializing
    if _lsp_manager_instance is not None and _initialization_state != 'failed':
        log_for_debugging('[LSP MANAGER] Already initialized or initializing, skipping')
        return
    
    # Reset state for retry if previous initialization failed
    if _initialization_state == 'failed':
        _lsp_manager_instance = None
        _initialization_error = None
    
    # Create manager and mark as pending
    _lsp_manager_instance = create_lsp_server_manager()
    _initialization_state = 'pending'
    log_for_debugging('[LSP MANAGER] Created manager instance, state=pending')
    
    # Increment generation to invalidate any pending initializations
    _initialization_generation += 1
    current_generation = _initialization_generation
    log_for_debugging(
        f'[LSP MANAGER] Starting async initialization (generation {current_generation})'
    )
    
    # Start initialization asynchronously without blocking
    # Store promise so callers can await it
    def start_init():
        return _start_initialization_async(current_generation)
    
    # Get or create event loop (handle both sync and async contexts)
    try:
        loop = asyncio.get_running_loop()
        # We're already in an async context, use create_task
        _initialization_promise = loop.create_task(start_init())
    except RuntimeError:
        # No running loop, create one and schedule as task
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        _initialization_promise = loop.create_task(start_init())


async def _start_initialization_async(generation: int) -> None:
    """Internal async initialization handler"""
    global _lsp_manager_instance, _initialization_state
    global _initialization_error, _initialization_generation
    
    try:
        if _lsp_manager_instance is None:
            return
        
        await _lsp_manager_instance.initialize()
        
        # Only update state if this is still the current initialization
        if generation == _initialization_generation:
            _initialization_state = 'success'
            log_for_debugging('LSP server manager initialized successfully')
            
            # Register passive notification handlers
            if _lsp_manager_instance:
                register_lsp_notification_handlers(_lsp_manager_instance)
    
    except Exception as error:
        # Only update state if this is still the current initialization
        if generation == _initialization_generation:
            _initialization_state = 'failed'
            _initialization_error = error
            _lsp_manager_instance = None
            
            log_error(error)
            log_for_debugging(
                f'Failed to initialize LSP server manager: {error_message(error)}'
            )


def reinitialize_lsp_server_manager() -> None:
    """
    Force re-initialization of LSP server manager, even after prior successful init.
    
    Called from refreshActivePlugins() after plugin caches are cleared,
    so newly-loaded plugin LSP servers are picked up.
    
    Safe to call when no LSP plugins changed: initialize() is just config parsing.
    Also safe during pending init: generation counter invalidates in-flight promise.
    """
    global _initialization_state, _lsp_manager_instance
    global _initialization_error


async def _shutdown_old_manager() -> None:
    """Helper to shutdown old LSP manager instance"""
    if _lsp_manager_instance:
        try:
            await _lsp_manager_instance.shutdown()
        except Exception as err:
            log_for_debugging(
                f'[LSP MANAGER] old instance shutdown during reinit failed: {error_message(err)}'
            )
    
    if _initialization_state == 'not-started':
        # initializeLspServerManager() was never called. Don't start now.
        return
    
    log_for_debugging('[LSP MANAGER] reinitializeLspServerManager() called')
    
    # Best-effort shutdown of old instance (fire-and-forget)
    if _lsp_manager_instance:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_shutdown_old_manager())
        except RuntimeError:
            # No running loop, create one
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            loop.create_task(_shutdown_old_manager())
    
    # Reset state
    _lsp_manager_instance = None
    _initialization_state = 'not-started'
    _initialization_error = None
    
    initialize_lsp_server_manager()


async def shutdown_lsp_server_manager() -> None:
    """
    Shutdown the LSP server manager and clean up resources.
    
    Called during Claude Code shutdown. Stops all running LSP servers
    and clears internal state. Safe to call when not initialized (no-op).
    
    NOTE: Errors during shutdown are logged but NOT propagated.
    State is always cleared even if shutdown fails.
    """
    global _lsp_manager_instance, _initialization_state
    global _initialization_error, _initialization_promise
    global _initialization_generation
    
    if _lsp_manager_instance is None:
        return
    
    try:
        await _lsp_manager_instance.shutdown()
        log_for_debugging('LSP server manager shut down successfully')
    except Exception as error:
        log_error(error)
        log_for_debugging(
            f'Failed to shutdown LSP server manager: {error_message(error)}'
        )
    finally:
        # Always clear state even if shutdown failed
        _lsp_manager_instance = None
        _initialization_state = 'not-started'
        _initialization_error = None
        _initialization_promise = None
        _initialization_generation += 1


__all__ = [
    'InitializationStatus',
    'get_lsp_server_manager',
    'get_initialization_status',
    'is_lsp_connected',
    'wait_for_initialization',
    'initialize_lsp_server_manager',
    'reinitialize_lsp_server_manager',
    'shutdown_lsp_server_manager',
    '_reset_lsp_manager_for_testing',
]
