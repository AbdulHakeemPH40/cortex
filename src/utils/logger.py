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
        
        # Always log to user home directory to avoid file locks during project operations
        # Location: C:\Users\Hakeem1\.cortex\logs\cortex.log
        log_dir = Path.home() / ".cortex" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "cortex.log"
        
        # File handler - Windows-safe: use TimedRotatingFileHandler with delay
        # RotatingFileHandler causes WinError 32 (file locked) on Windows rollover
        from logging.handlers import TimedRotatingFileHandler
        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',   # rotate at midnight instead of by size
            backupCount=3,
            encoding='utf-8',
            delay=True         # don't open file until first log write
        )
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
