"""
Cortex Database - SQLite + Vector Storage for Code Intelligence
Like Cursor: Semantic search, code embeddings, chat history, project memory
"""

import os
import json
import sqlite3
import hashlib
import threading
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager
from collections import deque
from PyQt6.QtCore import QTimer
from src.utils.logger import get_logger

log = get_logger("database")

# Try to import numpy for vector operations
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    log.warning("NumPy not installed. Vector search will be limited.")


@dataclass
class CodeChunk:
    """A code chunk extracted from a file."""
    id: Optional[int] = None
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    chunk_type: str = ""  # 'function', 'class', 'method', 'import', 'variable', 'comment'
    name: str = ""  # Function/class name
    code: str = ""  # Actual code content
    signature: str = ""  # Function signature
    docstring: str = ""  # Docstring/comment
    language: str = ""  # Python, JavaScript, etc.
    embedding: Optional[List[float]] = None
    dependencies: List[str] = field(default_factory=list)  # Imported modules
    hash: str = ""  # Content hash for change detection


@dataclass
class ChatMessage:
    """A chat message in history."""
    id: Optional[int] = None
    conversation_id: str = ""
    role: str = ""  # 'user' or 'assistant'
    content: str = ""
    timestamp: datetime = None
    files_accessed: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    embedding: Optional[List[float]] = None


@dataclass
class ProjectMemory:
    """Project-level memory for context."""
    key: str = ""  # e.g., 'main_entry', 'auth_system'
    value: str = ""  # JSON value
    file_path: str = ""  # Associated file
    embedding: Optional[List[float]] = None
    last_accessed: datetime = None


class CortexDatabase:
    """
    Main database for Cortex IDE.
    Combines SQLite for structured data with vector storage for semantic search.
    """
    
    # Language extensions mapping
    LANGUAGE_EXTENSIONS = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.go': 'go',
        '.rs': 'rust',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cs': 'csharp',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.m': 'objectivec',
        '.mm': 'objectivec',
        '.r': 'r',
        '.lua': 'lua',
        '.pl': 'perl',
        '.sql': 'sql',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.less': 'less',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.xml': 'xml',
        '.md': 'markdown',
        '.sh': 'bash',
        '.bash': 'bash',
        '.zsh': 'bash',
        '.ps1': 'powershell',
        '.vue': 'vue',
        '.svelte': 'svelte',
    }
    
    def __init__(self, db_path: str = None):
        """Initialize the database."""
        if db_path is None:
            # Default path in user's .cortex directory
            cortex_dir = Path.home() / ".cortex"
            cortex_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(cortex_dir / "cortex.db")
        
        self.db_path = db_path
        self.lock = threading.RLock()
        
        # Write queue for batching database operations
        self._write_queue = deque()
        self._write_timer = QTimer()
        self._write_timer.setSingleShot(True)
        self._write_timer.timeout.connect(self._flush_write_queue)
        self._write_interval = 500  # ms debounce
        
        self._init_database()
        log.info(f"Cortex database initialized at {db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Get a database connection with proper locking."""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def _init_database(self):
        """Create all tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Enable WAL mode for better performance
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=10000")
            
            # Files table - store file metadata and content
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    content TEXT,
                    language TEXT,
                    last_modified INTEGER,
                    hash TEXT,
                    indexed_at INTEGER,
                    file_size INTEGER
                )
            """)
            
            # Chunks table - code chunks for semantic search
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    chunk_type TEXT NOT NULL,
                    name TEXT,
                    code TEXT NOT NULL,
                    signature TEXT,
                    docstring TEXT,
                    language TEXT,
                    dependencies TEXT,
                    hash TEXT,
                    created_at INTEGER,
                    FOREIGN KEY (file_id) REFERENCES files(id)
                )
            """)

            # Full-text search index for chunks (FTS5)
            try:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
                    USING fts5(code, name, signature, docstring, file_path)
                """)
                cursor.execute("""
                    INSERT OR IGNORE INTO code_fts (rowid, code, name, signature, docstring, file_path)
                    SELECT id, code, name, signature, docstring, file_path FROM chunks
                """)
            except sqlite3.OperationalError as e:
                log.warning(f"FTS5 not available, code search disabled: {e}")
            
            # Embeddings table - vector embeddings for chunks
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id INTEGER UNIQUE NOT NULL,
                    embedding BLOB,
                    model_name TEXT,
                    dimensions INTEGER,
                    created_at INTEGER,
                    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
                )
            """)
            
            # Chat history table - replace JSON files
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT UNIQUE NOT NULL,
                    project_path TEXT,
                    title TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    timestamp INTEGER,
                    files_accessed TEXT,
                    tools_used TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
                )
            """)
            
            # Embeddings for chat messages
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER UNIQUE NOT NULL,
                    embedding BLOB,
                    model_name TEXT,
                    created_at INTEGER,
                    FOREIGN KEY (message_id) REFERENCES chat_messages(id)
                )
            """)
            
            # Project memory - remember project context
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS project_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_path TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    file_path TEXT,
                    last_accessed INTEGER,
                    UNIQUE(project_path, key)
                )
            """)
            
            # Search index for fast lookups
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id INTEGER NOT NULL,
                    token TEXT NOT NULL,
                    position INTEGER,
                    weight REAL DEFAULT 1.0,
                    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
                )
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(chunk_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_name ON chunks(name)")
            
            # Chat history indexes - optimized for fast loading
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at DESC)")  # Recent chats first
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON chat_messages(conversation_id)")
            
            # Project memory and search indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_project ON project_memory(project_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_token ON search_index(token)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_chunk ON search_index(chunk_id)")
            
            log.info(f"Database indexes created (optimized for {self.db_path})")
    
    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    
    def upsert_file(self, file_path: str, content: str, language: str = None) -> int:
        """
        Insert or update a file in the database.
        Returns the file ID.
        """
        file_path = str(Path(file_path).resolve())
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        file_size = len(content)
        
        if language is None:
            ext = Path(file_path).suffix.lower()
            language = self.LANGUAGE_EXTENSIONS.get(ext, 'unknown')
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if file exists
            cursor.execute("SELECT id FROM files WHERE path = ?", (file_path,))
            existing = cursor.fetchone()
            
            now = int(datetime.now().timestamp() * 1000)
            
            if existing:
                # Update existing file
                cursor.execute("""
                    UPDATE files 
                    SET content = ?, language = ?, hash = ?, file_size = ?, indexed_at = ?
                    WHERE id = ?
                """, (content, language, content_hash, file_size, now, existing['id']))
                return existing['id']
            else:
                # Insert new file
                cursor.execute("""
                    INSERT INTO files (path, content, language, hash, file_size, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (file_path, content, language, content_hash, file_size, now))
                return cursor.lastrowid
    
    def get_file(self, file_path: str) -> Optional[Dict]:
        """Get a file by path."""
        file_path = str(Path(file_path).resolve())
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE path = ?", (file_path,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_file_content(self, file_path: str) -> Optional[str]:
        """Get file content by path."""
        file_path = str(Path(file_path).resolve())
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM files WHERE path = ?", (file_path,))
            row = cursor.fetchone()
            return row['content'] if row else None
    
    def get_all_files(self, project_path: str = None) -> List[Dict]:
        """Get all files, optionally filtered by project path."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if project_path:
                cursor.execute(
                    "SELECT * FROM files WHERE path LIKE ?",
                    (f"{project_path}%",)
                )
            else:
                cursor.execute("SELECT * FROM files")
            return [dict(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # CHUNK OPERATIONS
    # =========================================================================
    
    def upsert_chunk(self, chunk: CodeChunk) -> int:
        """Insert or update a code chunk."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get file ID
            cursor.execute("SELECT id FROM files WHERE path = ?", (chunk.file_path,))
            file_row = cursor.fetchone()
            file_id = file_row['id'] if file_row else None
            
            if not file_id:
                # Need to create file entry first
                file_id = self.upsert_file(chunk.file_path, "")
            
            # Create hash for deduplication
            chunk_hash = hashlib.sha256(
                f"{chunk.file_path}:{chunk.start_line}:{chunk.code}".encode()
            ).hexdigest()
            
            now = int(datetime.now().timestamp() * 1000)
            dependencies_json = json.dumps(chunk.dependencies) if chunk.dependencies else "[]"
            
            # Check if chunk exists
            cursor.execute(
                "SELECT id FROM chunks WHERE file_id = ? AND start_line = ? AND end_line = ?",
                (file_id, chunk.start_line, chunk.end_line)
            )
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute("""
                    UPDATE chunks SET
                        chunk_type = ?, name = ?, code = ?, signature = ?,
                        docstring = ?, language = ?, dependencies = ?, hash = ?
                    WHERE id = ?
                """, (chunk.chunk_type, chunk.name, chunk.code, chunk.signature,
                      chunk.docstring, chunk.language, dependencies_json, chunk_hash, existing['id']))
                self._upsert_code_fts(cursor, existing['id'], chunk)
                return existing['id']
            else:
                cursor.execute("""
                    INSERT INTO chunks (file_id, file_path, start_line, end_line, chunk_type,
                                       name, code, signature, docstring, language, dependencies, hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (file_id, chunk.file_path, chunk.start_line, chunk.end_line, chunk.chunk_type,
                      chunk.name, chunk.code, chunk.signature, chunk.docstring, chunk.language,
                      dependencies_json, chunk_hash, now))
                chunk_id = cursor.lastrowid
                self._upsert_code_fts(cursor, chunk_id, chunk)
                return chunk_id

    def _upsert_code_fts(self, cursor, chunk_id: int, chunk: CodeChunk):
        """Keep the FTS index in sync with chunk content."""
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO code_fts (
                    rowid, code, name, signature, docstring, file_path
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                chunk_id,
                chunk.code,
                chunk.name or "",
                chunk.signature or "",
                chunk.docstring or "",
                chunk.file_path
            ))
        except sqlite3.OperationalError as e:
            log.warning(f"FTS update skipped: {e}")
    
    def get_chunks_by_file(self, file_path: str) -> List[CodeChunk]:
        """Get all chunks for a file."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM chunks WHERE file_path = ? ORDER BY start_line",
                (file_path,)
            )
            return [self._row_to_chunk(row) for row in cursor.fetchall()]
    
    def get_chunks_by_type(self, chunk_type: str, project_path: str = None) -> List[CodeChunk]:
        """Get chunks by type (function, class, etc)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if project_path:
                cursor.execute(
                    "SELECT * FROM chunks WHERE chunk_type = ? AND file_path LIKE ?",
                    (chunk_type, f"{project_path}%")
                )
            else:
                cursor.execute("SELECT * FROM chunks WHERE chunk_type = ?", (chunk_type,))
            return [self._row_to_chunk(row) for row in cursor.fetchall()]
    
    def search_chunks_text(self, query: str, limit: int = 50) -> List[CodeChunk]:
        """Full-text search on chunks."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT chunks.*
                    FROM code_fts
                    JOIN chunks ON code_fts.rowid = chunks.id
                    WHERE code_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, limit))
                return [self._row_to_chunk(row) for row in cursor.fetchall()]
            except sqlite3.OperationalError as e:
                log.warning(f"FTS search unavailable: {e}")
                return []
    
    def _row_to_chunk(self, row) -> CodeChunk:
        """Convert database row to CodeChunk object."""
        dependencies = []
        if row['dependencies']:
            try:
                dependencies = json.loads(row['dependencies'])
            except:
                pass
        
        return CodeChunk(
            id=row['id'],
            file_path=row['file_path'],
            start_line=row['start_line'],
            end_line=row['end_line'],
            chunk_type=row['chunk_type'],
            name=row['name'] or '',
            code=row['code'],
            signature=row['signature'] or '',
            docstring=row['docstring'] or '',
            language=row['language'] or '',
            dependencies=dependencies,
            hash=row['hash'] or ''
        )
    
    # =========================================================================
    # EMBEDDING OPERATIONS
    # =========================================================================
    
    def store_embedding(self, chunk_id: int, embedding: List[float], model_name: str = "all-MiniLM-L6-v2") -> int:
        """Store an embedding for a chunk."""
        if HAS_NUMPY:
            embedding_blob = np.array(embedding, dtype=np.float32).tobytes()
        else:
            import struct
            embedding_blob = struct.pack(f'{len(embedding)}f', *embedding)
        
        dimensions = len(embedding)
        now = int(datetime.now().timestamp() * 1000)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if embedding exists
            cursor.execute("SELECT id FROM embeddings WHERE chunk_id = ?", (chunk_id,))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute("""
                    UPDATE embeddings SET embedding = ?, model_name = ?, dimensions = ?, created_at = ?
                    WHERE chunk_id = ?
                """, (embedding_blob, model_name, dimensions, now, chunk_id))
                return existing['id']
            else:
                cursor.execute("""
                    INSERT INTO embeddings (chunk_id, embedding, model_name, dimensions, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (chunk_id, embedding_blob, model_name, dimensions, now))
                return cursor.lastrowid
    
    def get_embedding(self, chunk_id: int) -> Optional[List[float]]:
        """Get embedding for a chunk."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT embedding FROM embeddings WHERE chunk_id = ?", (chunk_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            blob = row['embedding']
            if HAS_NUMPY:
                return np.frombuffer(blob, dtype=np.float32).tolist()
            else:
                import struct
                dimensions = len(blob) // 4
                return list(struct.unpack(f'{dimensions}f', blob))
    
    def get_all_embeddings(self, project_path: str = None) -> List[Tuple[int, List[float], str]]:
        """Get all embeddings for a project."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if project_path:
                cursor.execute("""
                    SELECT e.chunk_id, e.embedding, c.file_path
                    FROM embeddings e
                    JOIN chunks c ON e.chunk_id = c.id
                    WHERE c.file_path LIKE ?
                """, (f"{project_path}%",))
            else:
                cursor.execute("""
                    SELECT e.chunk_id, e.embedding, c.file_path
                    FROM embeddings e
                    JOIN chunks c ON e.chunk_id = c.id
                """)
            
            results = []
            for row in cursor.fetchall():
                if HAS_NUMPY:
                    embedding = np.frombuffer(row['embedding'], dtype=np.float32).tolist()
                else:
                    import struct
                    blob = row['embedding']
                    dimensions = len(blob) // 4
                    embedding = list(struct.unpack(f'{dimensions}f', blob))
                
                results.append((row['chunk_id'], embedding, row['file_path']))
            
            return results
    
    # =========================================================================
    # CHAT HISTORY OPERATIONS
    # =========================================================================
    
    def create_conversation(self, conversation_id: str, project_path: str, title: str = None) -> str:
        """Create a new conversation."""
        now = int(datetime.now().timestamp() * 1000)
        title = title or f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO conversations (conversation_id, project_path, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (conversation_id, project_path, title, now, now))
            
        return conversation_id
    
    def add_message(self, conversation_id: str, role: str, content: str, 
                   files_accessed: List[str] = None, tools_used: List[str] = None) -> int:
        """Add a message to a conversation (batched for performance)."""
        now = int(datetime.now().timestamp() * 1000)
        files_json = json.dumps(files_accessed) if files_accessed else "[]"
        tools_json = json.dumps(tools_used) if tools_used else "[]"
        
        message_id = [None]  # Use list to capture value from closure
        
        def insert_op(cursor):
            cursor.execute("""
                INSERT INTO chat_messages (conversation_id, role, content, timestamp, files_accessed, tools_used)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (conversation_id, role, content, now, files_json, tools_json))
            
            # Update conversation updated_at
            cursor.execute("""
                UPDATE conversations SET updated_at = ? WHERE conversation_id = ?
            """, (now, conversation_id))
            
            message_id[0] = cursor.lastrowid
        
        # Queue the write operation instead of executing immediately
        self._queue_write(insert_op)
        
        # Return estimated ID (actual ID will be assigned when flushed)
        return message_id[0] or 0
    
    def get_messages(self, conversation_id: str, limit: int = 100) -> List[ChatMessage]:
        """Get messages for a conversation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM chat_messages 
                WHERE conversation_id = ? 
                ORDER BY timestamp ASC 
                LIMIT ?
            """, (conversation_id, limit))
            
            messages = []
            for row in cursor.fetchall():
                messages.append(ChatMessage(
                    id=row['id'],
                    conversation_id=row['conversation_id'],
                    role=row['role'],
                    content=row['content'],
                    timestamp=datetime.fromtimestamp(row['timestamp'] / 1000),
                    files_accessed=json.loads(row['files_accessed'] or '[]'),
                    tools_used=json.loads(row['tools_used'] or '[]')
                ))
            
            return messages
    
    def get_conversations(self, project_path: str = None) -> List[Dict]:
        """Get all conversations for a project with message counts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT c.*, COUNT(m.id) as message_count
                FROM conversations c
                JOIN chat_messages m ON m.conversation_id = c.conversation_id
            """
            
            if project_path:
                query += " WHERE c.project_path = ?"
                query += " GROUP BY c.conversation_id ORDER BY c.updated_at DESC"
                cursor.execute(query, (project_path,))
            else:
                query += " GROUP BY c.conversation_id ORDER BY c.updated_at DESC"
                cursor.execute(query)
            
            return [dict(row) for row in cursor.fetchall()]

    def get_message_count(self, conversation_id: str) -> int:
        """Get message count for a conversation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?",
                (conversation_id,)
            )
            return int(cursor.fetchone()[0] or 0)
    
    def delete_conversation(self, conversation_id: str):
        """Delete a conversation and all its messages."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
            cursor.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            
    def clear_conversation_messages(self, conversation_id: str):
        """Clear only messages for a conversation without deleting the conversation itself. 
        Crucial for preventing duplicate insertion on updates."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
    
    def _queue_write(self, operation: callable):
        """Queue a write operation and flush after debounce interval."""
        self._write_queue.append(operation)
        
        # Start/restart debounce timer
        if self._write_timer.isActive():
            self._write_timer.stop()
        self._write_timer.start(self._write_interval)
        
    def _flush_write_queue(self):
        """Flush all queued write operations in a single transaction."""
        if not self._write_queue:
            return
            
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Execute all queued operations
                while self._write_queue:
                    operation = self._write_queue.popleft()
                    operation(cursor)
                
                # Single commit for all operations
                conn.commit()
                log.debug(f"Flushed {len(self._write_queue)} database writes")
        except Exception as e:
            log.error(f"Error flushing write queue: {e}")
            # Re-queue failed operations
            conn.rollback()
    
    # =========================================================================
    # PROJECT MEMORY OPERATIONS
    # =========================================================================
    
    def set_memory(self, project_path: str, key: str, value: str, file_path: str = None):
        """Store a memory for a project."""
        now = int(datetime.now().timestamp() * 1000)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO project_memory (project_path, key, value, file_path, last_accessed)
                VALUES (?, ?, ?, ?, ?)
            """, (project_path, key, value, file_path, now))
    
    def get_memory(self, project_path: str, key: str) -> Optional[str]:
        """Get a memory from a project."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM project_memory WHERE project_path = ? AND key = ?",
                (project_path, key)
            )
            row = cursor.fetchone()
            return row['value'] if row else None
    
    def get_all_memory(self, project_path: str) -> Dict[str, str]:
        """Get all memories for a project."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT key, value FROM project_memory WHERE project_path = ?",
                (project_path,)
            )
            return {row['key']: row['value'] for row in cursor.fetchall()}
    
    def clear_memory(self, project_path: str):
        """Clear all memories for a project."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_memory WHERE project_path = ?", (project_path,))
    
    # =========================================================================
    # SEARCH OPERATIONS
    # =========================================================================
    
    def search_code(self, query: str, project_path: str = None, limit: int = 20) -> List[Dict]:
        """Search code using full-text search."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if project_path:
                    cursor.execute("""
                    SELECT
                        chunks.id AS chunk_id,
                        chunks.code,
                        chunks.name,
                        chunks.signature,
                        chunks.docstring,
                        chunks.file_path,
                        chunks.start_line,
                        chunks.end_line
                    FROM code_fts
                    JOIN chunks ON code_fts.rowid = chunks.id
                        WHERE code_fts MATCH ? AND chunks.file_path LIKE ?
                        ORDER BY rank
                        LIMIT ?
                    """, (query, f"{project_path}%", limit))
                else:
                    cursor.execute("""
                    SELECT
                        chunks.id AS chunk_id,
                        chunks.code,
                        chunks.name,
                        chunks.signature,
                        chunks.docstring,
                        chunks.file_path,
                        chunks.start_line,
                        chunks.end_line
                    FROM code_fts
                    JOIN chunks ON code_fts.rowid = chunks.id
                        WHERE code_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (query, limit))
            except sqlite3.OperationalError as e:
                log.warning(f"FTS search unavailable: {e}")
                return []
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'chunk_id': row['chunk_id'],
                    'code': row['code'],
                    'name': row['name'],
                    'signature': row['signature'],
                    'docstring': row['docstring'],
                    'file_path': row['file_path'],
                    'start_line': row['start_line'],
                    'end_line': row['end_line']
                })
            
            return results
    
    def find_functions(self, name_pattern: str = None, project_path: str = None) -> List[CodeChunk]:
        """Find function definitions by name pattern."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if project_path and name_pattern:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'function' AND name LIKE ? AND file_path LIKE ?
                    ORDER BY file_path, start_line
                """, (f"%{name_pattern}%", f"{project_path}%"))
            elif project_path:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'function' AND file_path LIKE ?
                    ORDER BY file_path, start_line
                """, (f"{project_path}%",))
            elif name_pattern:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'function' AND name LIKE ?
                    ORDER BY file_path, start_line
                """, (f"%{name_pattern}%",))
            else:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'function'
                    ORDER BY file_path, start_line
                """)
            
            return [self._row_to_chunk(row) for row in cursor.fetchall()]
    
    def find_classes(self, name_pattern: str = None, project_path: str = None) -> List[CodeChunk]:
        """Find class definitions by name pattern."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if project_path and name_pattern:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'class' AND name LIKE ? AND file_path LIKE ?
                    ORDER BY file_path, start_line
                """, (f"%{name_pattern}%", f"{project_path}%"))
            elif project_path:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'class' AND file_path LIKE ?
                    ORDER BY file_path, start_line
                """, (f"{project_path}%",))
            elif name_pattern:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'class' AND name LIKE ?
                    ORDER BY file_path, start_line
                """, (f"%{name_pattern}%",))
            else:
                cursor.execute("""
                    SELECT * FROM chunks 
                    WHERE chunk_type = 'class'
                    ORDER BY file_path, start_line
                """)
            
            return [self._row_to_chunk(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def clear_project(self, project_path: str):
        """Clear all data for a project."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Delete FTS rows first (contentless table)
            cursor.execute("DELETE FROM code_fts WHERE file_path LIKE ?", (f"{project_path}%",))

            # Delete chunks
            cursor.execute("DELETE FROM chunks WHERE file_path LIKE ?", (f"{project_path}%",))
            
            # Delete files
            cursor.execute("DELETE FROM files WHERE path LIKE ?", (f"{project_path}%",))
            
            # Delete embeddings (orphaned)
            cursor.execute("""
                DELETE FROM embeddings WHERE chunk_id NOT IN (SELECT id FROM chunks)
            """)
            
            # Clear memory
            cursor.execute("DELETE FROM project_memory WHERE project_path = ?", (project_path,))
    
    def get_stats(self) -> Dict:
        """Get database statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            cursor.execute("SELECT COUNT(*) FROM files")
            stats['files'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM chunks")
            stats['chunks'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM embeddings")
            stats['embeddings'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM chat_messages")
            stats['messages'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM conversations")
            stats['conversations'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM project_memory")
            stats['memories'] = cursor.fetchone()[0]
            
            return stats
    
    def vacuum(self):
        """Optimize database."""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
            log.info("Database vacuumed")


# Global database instance
_db_instance: Optional[CortexDatabase] = None

def get_database(db_path: str = None) -> CortexDatabase:
    """Get or create the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = CortexDatabase(db_path)
    return _db_instance
