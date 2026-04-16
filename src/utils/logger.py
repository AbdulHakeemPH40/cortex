"""
Logger utility for Cortex AI Agent IDE
"""
import logging
import sys
from pathlib import Path


def get_logger(name: str = "cortex") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # Prevent duplicate logs from root logger
        
        # Always log to user home directory to avoid file locks during project operations
        # Location: C:\Users\Hakeem1\.cortex\logs\cortex.log
        log_dir = Path.home() / ".cortex" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "cortex.log"
        
        # File handler - Windows-safe: use TimedRotatingFileHandler with delay
        # Override rotator to handle Windows file locks gracefully
        from logging.handlers import TimedRotatingFileHandler
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
