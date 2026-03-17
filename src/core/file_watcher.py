"""
File Watcher for Cortex AI Agent IDE
Monitors file system changes and emits signals
"""

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from pathlib import Path
from typing import Set, Dict, Optional
import os
from src.utils.logger import get_logger

log = get_logger("file_watcher")

# Try to import watchdog for better file watching
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    log.warning("watchdog not available, using polling fallback")


class FileChangeEvent:
    """Represents a file change event."""
    def __init__(self, path: str, event_type: str, is_directory: bool = False):
        self.path = path
        self.type = event_type  # 'modified', 'created', 'deleted', 'moved'
        self.is_directory = is_directory


class FileWatcher(QObject):
    """Watches files and directories for changes."""
    
    file_modified = pyqtSignal(str)  # path
    file_created = pyqtSignal(str)  # path
    file_deleted = pyqtSignal(str)  # path
    file_moved = pyqtSignal(str, str)  # old_path, new_path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._watched_paths: Set[str] = set()
        self._file_hashes: Dict[str, str] = {}  # For polling-based detection
        self._observer = None
        self._handler = None
        self._timer = None
        self._poll_interval = 1000  # ms
        
        if WATCHDOG_AVAILABLE:
            self._setup_watchdog()
        else:
            self._setup_polling()
            
    def _setup_watchdog(self):
        """Setup watchdog observer."""
        self._handler = WatchdogHandler(self)
        self._observer = Observer()
        
    def _setup_polling(self):
        """Setup polling-based watching."""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_files)
        self._timer.start(self._poll_interval)
        
    def add_path(self, path: str, recursive: bool = True) -> bool:
        """Add a path to watch."""
        if not Path(path).exists():
            return False
            
        self._watched_paths.add(path)
        
        if WATCHDOG_AVAILABLE and self._observer:
            try:
                self._observer.schedule(
                    self._handler,
                    path,
                    recursive=recursive
                )
                if not self._observer.is_alive():
                    self._observer.start()
                return True
            except Exception as e:
                log.error(f"Failed to watch path {path}: {e}")
                return False
        else:
            # Store initial hash for polling
            self._update_file_hash(path)
            return True
            
    def remove_path(self, path: str):
        """Remove a path from watching."""
        self._watched_paths.discard(path)
        if path in self._file_hashes:
            del self._file_hashes[path]
            
    def clear(self):
        """Clear all watched paths."""
        self._watched_paths.clear()
        self._file_hashes.clear()
        
    def _update_file_hash(self, path: str):
        """Calculate and store file hash."""
        try:
            if Path(path).is_file():
                import hashlib
                with open(path, 'rb') as f:
                    content = f.read(8192)  # First 8KB
                    file_hash = hashlib.md5(content).hexdigest()
                    self._file_hashes[path] = file_hash
        except:
            pass
            
    def _poll_files(self):
        """Poll files for changes (fallback method)."""
        for path in list(self._watched_paths):
            if not Path(path).exists():
                # File was deleted
                self.file_deleted.emit(path)
                self.remove_path(path)
                continue
                
            if Path(path).is_file():
                import hashlib
                try:
                    with open(path, 'rb') as f:
                        content = f.read(8192)
                        file_hash = hashlib.md5(content).hexdigest()
                        
                    old_hash = self._file_hashes.get(path)
                    if old_hash and old_hash != file_hash:
                        self.file_modified.emit(path)
                        
                    self._file_hashes[path] = file_hash
                except:
                    pass
            elif Path(path).is_dir():
                # For directories, scan for new/deleted files
                self._scan_directory(path)
                
    def _scan_directory(self, dir_path: str):
        """Scan directory for changes."""
        try:
            current_files = set()
            for root, dirs, files in os.walk(dir_path):
                # Skip hidden and common ignore directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and 
                          d not in ['__pycache__', 'node_modules', 'venv', '.git']]
                
                for file in files:
                    file_path = os.path.join(root, file)
                    current_files.add(file_path)
                    
                    # Check if file is new or modified
                    import hashlib
                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read(8192)
                            file_hash = hashlib.md5(content).hexdigest()
                            
                        old_hash = self._file_hashes.get(file_path)
                        if old_hash is None:
                            # New file
                            self.file_created.emit(file_path)
                        elif old_hash != file_hash:
                            # Modified file
                            self.file_modified.emit(file_path)
                            
                        self._file_hashes[file_path] = file_hash
                    except:
                        pass
                        
            # Check for deleted files
            watched_files = {p for p in self._file_hashes if p.startswith(dir_path)}
            for file_path in watched_files - current_files:
                self.file_deleted.emit(file_path)
                if file_path in self._file_hashes:
                    del self._file_hashes[file_path]
                    
        except Exception as e:
            log.error(f"Error scanning directory {dir_path}: {e}")
            
    def stop(self):
        """Stop the file watcher."""
        if WATCHDOG_AVAILABLE and self._observer:
            self._observer.stop()
            self._observer.join()
        elif self._timer:
            self._timer.stop()


if WATCHDOG_AVAILABLE:
    class WatchdogHandler(FileSystemEventHandler):
        """Handler for watchdog events."""
        
        def __init__(self, watcher: FileWatcher):
            self.watcher = watcher
            
        def on_modified(self, event):
            if not event.is_directory:
                self.watcher.file_modified.emit(event.src_path)
                
        def on_created(self, event):
            if not event.is_directory:
                self.watcher.file_created.emit(event.src_path)
                
        def on_deleted(self, event):
            if not event.is_directory:
                self.watcher.file_deleted.emit(event.src_path)
                
        def on_moved(self, event):
            if not event.is_directory:
                self.watcher.file_moved.emit(event.src_path, event.dest_path)
