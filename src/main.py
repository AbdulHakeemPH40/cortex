"""
Cortex AI Agent IDE — Entry Point
Run with: python src/main.py
"""

import sys
import os

# Force Windows platform
if sys.platform == 'win32':
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    os.environ['QT_OPENGL'] = 'software'

# Add project root to path so 'src' imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from src.main_window import CortexMainWindow
from src.utils.logger import get_logger

log = get_logger("main")


def main():
    # HiDPI support is automatic in Qt6

    app = QApplication(sys.argv)
    app.setApplicationName("Cortex AI Agent")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Cortex")

    # Global font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    log.info("Starting Cortex AI Agent IDE...")

    window = CortexMainWindow()
    # window.show() is now called in __init__

    log.info("Application ready. Entering event loop...")
    print(">>> Main: Entering app.exec()")
    
    # Simple timer to prove the loop is at least starting
    QTimer.singleShot(1000, lambda: print(">>> Main: Loop is ALIVE! (1s check)"))
    
    try:
        res = app.exec()
        log.info(f"Application exited with code {res}")
        sys.exit(res)
    except Exception as e:
        log.critical(f"FATAL EXCEPTION in main loop: {e}", exc_info=True)
        print(f"FATAL EXCEPTION: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
