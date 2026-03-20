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
        
        # File handler - writes to rotating log file
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5*1024*1024,  # 5MB max
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(file_handler)
        
        # Console handler - only WARNING and above (no INFO/DEBUG in terminal)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.WARNING)  # Only show warnings/errors in terminal
        console_handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                datefmt="%H:%M:%S"
            )
        )
        logger.addHandler(console_handler)
        
    return logger
