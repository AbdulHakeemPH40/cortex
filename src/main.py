"""
Cortex AI Agent IDE — Entry Point
Run with: python src/main.py
"""

import sys
import os
import signal
import logging
from pathlib import Path
import datetime as _datetime

# Align the embedded agent's memdir base with Cortex's config home.
# agent/src/memdir/paths.py uses CLAUDE_CODE_REMOTE_MEMORY_DIR as the memory base.
if not os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR"):
    os.environ["CLAUDE_CODE_REMOTE_MEMORY_DIR"] = str(Path.home() / ".cortex")

# Ensure global rules directory exists early so users can drop rules without manual setup.
try:
    (Path.home() / ".cortex" / "rules").mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# CRITICAL: Load .env FIRST before ANY other imports!
try:
    from dotenv import load_dotenv
    
    # Resolve correct root path for PyInstaller
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller bundled app - .env is in _MEIPASS temp folder
            app_root = Path(sys._MEIPASS)
        else:
            # Nuitka or other compiler - next to executable
            app_root = Path(sys.executable).parent
    else:
        # Development mode
        app_root = Path(__file__).parent.parent
        
    env_paths = [
        app_root / ".env",
        Path.cwd() / ".env",
        # Fallback: user's home directory
        Path.home() / ".cortex" / ".env",
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"[MAIN] Loaded .env from: {env_path}")
            break
    else:
        print("[MAIN] WARNING: No .env file found!")
except ImportError:
    print("[MAIN] WARNING: python-dotenv not installed")

# CRITICAL: Monkey-patch subprocess to default close_fds=True on Windows.
# Qt WebEngine (Chromium) opens numerous file descriptors for GPU surfaces,
# shared memory, and IPC channels. If ANY subprocess inherits these FDs via
# Popen or run without close_fds=True, the IDE silently crashes.
# This patch ensures ALL subprocess calls throughout the application
# (including third-party libraries) are protected.
import subprocess as _subprocess_module

# Patch subprocess.run (a function — safe to replace)
_original_run = _subprocess_module.run

def _patched_run(*args, **kwargs):
    """Wrapped subprocess.run that defaults close_fds=True on all platforms."""
    kwargs.setdefault('close_fds', True)
    return _original_run(*args, **kwargs)

_subprocess_module.run = _patched_run

# Patch subprocess.Popen.__init__ (must preserve class structure for asyncio etc.)
_original_popen_init = _subprocess_module.Popen.__init__

def _patched_popen_init(self, *args, **kwargs):
    """Patched Popen.__init__ that defaults close_fds=True."""
    kwargs.setdefault('close_fds', True)
    _original_popen_init(self, *args, **kwargs)

_subprocess_module.Popen.__init__ = _patched_popen_init

# CRITICAL FIX: Hide console window on Windows (prevents subprocess popups)
# This MUST come before QApplication initialization
if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    try:
        import ctypes
        # SW_HIDE = 0
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass  # Ignore if fails

# HiDPI + Windows platform setup (BEFORE QApplication)
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'PassThrough'
if sys.platform == 'win32':
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    
# GPU flags are deliberately NOT set — Qt6's Chromium handles GPU gracefully
# and explicit --disable-gpu or --use-gl can cause slow startup or conflicts.
# Crash prevention is handled by:
#   1. Reduced Monaco rendering features (no bracket colorization, smooth scroll, etc.)
#   2. LSP marker line-number validation (prevents out-of-bounds decoration crash)
#   3. QWebChannel call throttling and null-safety guards
#   4. renderProcessTerminated signal handler in webview_panel.py

# Add project root to path so 'src' imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set AppUserModelID for Windows Taskbar Taskbar icon fix
if sys.platform == 'win32':
    import ctypes
    try:
        myappid = 'cortex.ai.agent.ide.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon

from src.main_window import CortexMainWindow
from src.utils.logger import get_logger

log = get_logger("main")


def main():
    # Capture fatal crashes (e.g., native/Qt segfault) to a persistent log.
    # This helps diagnose "sudden close" cases that don't raise Python exceptions.
    try:
        import faulthandler as _faulthandler

        crash_dir = Path.home() / ".cortex"
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_path = crash_dir / "crash.log"
        _crash_fp = open(crash_path, "a", encoding="utf-8", buffering=1)
        _crash_fp.write(f"\n===== Cortex crash session { _datetime.datetime.now().isoformat(timespec='seconds') } =====\n")
        _faulthandler.enable(file=_crash_fp, all_threads=True)
        # Dump tracebacks if the process appears to hang
        _faulthandler.dump_traceback_later(120, repeat=True, file=_crash_fp)
        log.info(f"[CRASH] faulthandler enabled -> {crash_path}")
    except Exception as e:
        log.debug(f"[CRASH] faulthandler not enabled: {e}")

    # HiDPI support is automatic in Qt6
    
    app = QApplication(sys.argv)
    app.setApplicationName("Cortex AI Agent")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Cortex")

    # Set Application Icon (Taskbar/Alt+Tab)
    # Uses pre-generated taskbar_rounded.png (run generate_icons.py once to create it)
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    logo_dir = os.path.join(base, "src", "assets", "logo")
    if not os.path.isdir(logo_dir):
        # Fallback: try exe directory
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        logo_dir = os.path.join(exe_dir, "src", "assets", "logo")
    if not os.path.isdir(logo_dir):
        # Fallback: try _internal directory (PyInstaller onedir)
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        logo_dir = os.path.join(exe_dir, "_internal", "src", "assets", "logo")
    if not os.path.isdir(logo_dir):
        logo_dir = os.path.join(os.getcwd(), "src", "assets", "logo")

    # Prefer pre-generated rounded PNG (crisp, no runtime PIL needed)
    icon_candidates = [
        os.path.join(logo_dir, "taskbar_rounded.png"),
        os.path.join(logo_dir, "taskbar.png"),
        os.path.join(logo_dir, "taskbar.ico"),
    ]

    icon = QIcon()
    for candidate in icon_candidates:
        if os.path.exists(candidate):
            from PyQt6.QtGui import QPixmap
            from PyQt6.QtCore import Qt as QtConst
            pm = QPixmap(candidate)
            if not pm.isNull():
                # Add at multiple sizes for crisp rendering at all DPIs
                for sz in [16, 32, 48, 64, 128, 256]:
                    icon.addPixmap(pm.scaled(sz, sz, QtConst.AspectRatioMode.KeepAspectRatio, QtConst.TransformationMode.SmoothTransformation))
                break

    if not icon.isNull():
        app.setWindowIcon(icon)

    # Global font - try Segoe UI first, fall back to system font
    try:
        font = QFont("Segoe UI", 10)
        app.setFont(font)
    except Exception as e:
        log.warning(f"Could not set Segoe UI font: {e}, using system default")
        font = QFont()
        font.setPointSize(10)
        app.setFont(font)

    # CRITICAL: Install global exception handler to prevent crashes
    def handle_exception(exc_type, exc_value, exc_traceback):
        """Global exception handler to keep IDE running."""
        import traceback
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        error_msg = f"Uncaught exception: {str(exc_value)}\n{''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))}"
        log.critical(error_msg)
        print(f"\n❌ {error_msg}\n", file=sys.stderr)
        # Don't exit - just log and continue running
    
    sys.excepthook = handle_exception

    log.info("Starting Cortex AI Agent IDE...")

    window = CortexMainWindow()
    # window.show() is now called in __init__

    # ═══════════════════════════════════════════════════════════════
    # SHUTDOWN HARDENING — Emergency save on force-kill / crash
    # ═══════════════════════════════════════════════════════════════
    
    _shutdown_saved = False  # Prevent double-save
    _auto_save_seq = [0]     # Mutable counter for debounce (skip if unchanged)
    _last_turn_count = [-1]  # Track turn count to skip redundant saves

    def _emergency_save(reason: str = "unknown") -> None:
        """Save agent state + settings immediately. Idempotent — skips if already saved."""
        nonlocal _shutdown_saved
        if _shutdown_saved:
            return
        _shutdown_saved = True
        try:
            from src.core.agent_session_manager import save_snapshot
            from src.ai.agent_bridge import get_agent_bridge
            bridge = get_agent_bridge()
            if bridge is not None:
                save_snapshot(bridge)
                log.info(f"[SHUTDOWN] Agent state saved (reason: {reason})")
        except Exception as e:
            log.warning(f"[SHUTDOWN] Failed to save agent state: {e}")
        try:
            # Force settings flush
            from src.config.settings import get_settings
            settings = get_settings()
            if hasattr(settings, 'sync'):
                settings.sync()
            elif hasattr(settings, 'save'):
                settings.save()
            log.info(f"[SHUTDOWN] Settings flushed (reason: {reason})")
        except Exception as e:
            log.warning(f"[SHUTDOWN] Failed to flush settings: {e}")
        # Persist chat history to SQLite (fire-and-forget via window reference)
        try:
            if window and hasattr(window, '_ai_chat') and window._ai_chat:
                window._ai_chat.run_javascript(
                    "if(window.saveProjectChats) saveProjectChats(window.chats);"
                )
                log.info(f"[SHUTDOWN] Chat persistence triggered (reason: {reason})")
        except Exception as e:
            log.warning(f"[SHUTDOWN] Failed to trigger chat persistence: {e}")

    def _auto_save_tick() -> None:
        """Periodic background save — fires every 30s when IDE is idle."""
        try:
            from src.ai.agent_bridge import get_agent_bridge
            bridge = get_agent_bridge()
            if bridge is None:
                return
            # Skip if an LLM call is in progress (avoid race conditions)
            if getattr(bridge, '_streaming', None) and getattr(bridge._streaming, '_active', False):
                return
            # Skip if no new turns since last save
            current_turn = getattr(bridge, '_tool_turn_count', 0)
            if current_turn == _last_turn_count[0]:
                return
            _last_turn_count[0] = current_turn
            _auto_save_seq[0] += 1
            from src.core.agent_session_manager import save_snapshot
            save_snapshot(bridge)
            log.debug(f"[AUTO-SAVE #{_auto_save_seq[0]}] Agent state snapshot saved (turn {current_turn})")
        except Exception as e:
            log.debug(f"[AUTO-SAVE] Skipped: {e}")

    # ── Qt aboutToQuit — fires when event loop is ending (catches more scenarios) ──
    app.aboutToQuit.connect(lambda: _emergency_save("aboutToQuit"))

    # ── Periodic auto-save timer — every 30 seconds ──
    _auto_save_timer = QTimer()
    _auto_save_timer.timeout.connect(_auto_save_tick)
    _auto_save_timer.start(30_000)  # 30 seconds
    log.info("[AUTO-SAVE] Periodic snapshot timer started (every 30s)")

    # ── OS signal handlers (SIGTERM, SIGINT) for terminal-based kills ──
    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        log.warning(f"[SHUTDOWN] Received {sig_name} — performing emergency save...")
        _emergency_save(sig_name)
        # Stop the timer to prevent re-entry
        try:
            _auto_save_timer.stop()
        except Exception:
            pass
        # Give the save a moment to flush, then exit
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
        log.info("[SHUTDOWN] SIGTERM/SIGINT handlers installed")
    except Exception as e:
        log.warning(f"[SHUTDOWN] Could not install signal handlers: {e}")

    # Handle path argument (from right-click "Open with Cortex IDE" or drag-drop launch)
    if len(sys.argv) > 1:
        launch_path = sys.argv[1]
        if os.path.isdir(launch_path):
            QTimer.singleShot(200, lambda p=launch_path: window._open_folder_programmatic(p))
        elif os.path.isfile(launch_path):
            QTimer.singleShot(200, lambda p=launch_path: window._open_file(p))

    log.info("Application ready. Entering event loop...")
    
    # Simple timer to prove the loop is at least starting (debug only)
    QTimer.singleShot(1000, lambda: log.debug("Main: Loop is ALIVE! (1s check)"))
    QTimer.singleShot(2000, lambda: log.debug("Main: Loop is ALIVE! (2s check)"))
    QTimer.singleShot(3000, lambda: log.debug("Main: Loop is ALIVE! (3s check)"))
    
    try:
        log.info("Calling app.exec()...")
        # Debug: check if window is visible
        log.info(f"Window is visible: {window.isVisible()}")
        log.info(f"Window is active: {window.isActiveWindow()}")
        log.info(f"Window geometry: {window.geometry()}")
        
        res = app.exec()
        log.info(f"Application exited with code {res}")
        sys.exit(res)
    except Exception as e:
        log.critical(f"FATAL EXCEPTION in main loop: {e}", exc_info=True)
        print(f"FATAL EXCEPTION: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
