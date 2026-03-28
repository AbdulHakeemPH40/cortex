"""
Cortex AI Agent IDE — Entry Point
Run with: python src/main.py
"""

import sys
import os
from pathlib import Path

# CRITICAL: Load .env FIRST before ANY other imports!
try:
    from dotenv import load_dotenv
    env_paths = [
        Path(__file__).parent.parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"[MAIN] Loaded .env from: {env_path}")
            break
except ImportError:
    pass

# HiDPI + Windows platform setup (BEFORE QApplication)
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'PassThrough'
if sys.platform == 'win32':
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    # Do NOT set QT_OPENGL=software — it disables hardware acceleration and blurs everything

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
    # HiDPI support is automatic in Qt6

    app = QApplication(sys.argv)
    app.setApplicationName("Cortex AI Agent")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Cortex")

    # Set Application Icon (Taskbar/Alt+Tab) - Using focused logo-only version
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "logo", "taskbar.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Global font - try Segoe UI first, fall back to system font
    try:
        font = QFont("Segoe UI", 10)
        app.setFont(font)
    except Exception as e:
        log.warning(f"Could not set Segoe UI font: {e}, using system default")
        font = QFont()
        font.setPointSize(10)
        app.setFont(font)

    log.info("Starting Cortex AI Agent IDE...")

    window = CortexMainWindow()
    # window.show() is now called in __init__

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
