"""
Session Database Schema Management
Structured storage for chat sessions using SQLite
Based on OpenCode's session.sql.ts approach
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from src.utils.logger import get_logger

log = get_logger("session_schema")


@dataclass
class SessionMetadata:
    """Session metadata structure."""
    id: str
    title: str
    created_at: str
    updated_at: str
    project_path: str
    model: str
    message_count: int = 0
    total_tokens: int = 0
    tags: List[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_path": self.project_path,
            "model": self.model,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "tags": self.tags or []
        }


@dataclass
class MessageRecord:
    """Message record structure."""
    id: str
    session_id: str
    role: str
    content: str
    timestamp: str
    token_count: int
    tool_calls: Optional[str]  # JSON string
    tool_call_id: Optional[str]
    metadata: Optional[str]  # JSON string


class SessionSchemaManager:
    """
    Manages SQLite schema for chat sessions.
    
    Features:
    - Structured session storage
    - Message history with metadata
    - Full-text search
    - Migration support
    - Statistics tracking
    """
    
    SCHEMA_VERSION = 1
    
    def __init__(self, db_path: str = None):
        """
        Initialize schema manager.
        
        Args:
            db_path: Path to SQLite database. Defaults to .cortex/sessions.db
        """
        if db_path is None:
            # Default: ~/.cortex/sessions.db
            home = Path.home()
            cortex_dir = home / ".cortex"
            cortex_dir.mkdir(exist_ok=True)
            db_path = cortex_dir / "sessions.db"
        
        self.db_path = Path(db_path)
        self._ensure_schema()
        
        log.info(f"SessionSchemaManager initialized: {self.db_path}")
    
    def _ensure_schema(self):
        """Ensure database schema exists and is up to date."""
        with sqlite3.connect(self.db_path) as conn:
            # Schema version table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Sessions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    project_path TEXT,
                    model TEXT,
                    message_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    tags TEXT,  -- JSON array
                    metadata TEXT  -- JSON object
                )
            """)
            
            # Messages table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,  -- user, assistant, system, tool
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    token_count INTEGER DEFAULT 0,
                    tool_calls TEXT,  -- JSON array of tool calls
                    tool_call_id TEXT,
                    metadata TEXT,  -- JSON object
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session 
                ON messages(session_id, timestamp)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_project 
                ON sessions(project_path, updated_at DESC)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_updated 
                ON sessions(updated_at DESC)
            """)
            
            # Full-text search for messages
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    session_id UNINDEXED,
                    tokenize='porter'
                )
            """)
            
            # Triggers to keep FTS index in sync
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages
                BEGIN
                    INSERT INTO messages_fts(rowid, content, session_id)
                    VALUES (new.rowid, new.content, new.session_id);
                END
            """)
            
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages
                BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.rowid;
                END
            """)
            
            # Update schema version
            conn.execute("""
                INSERT OR REPLACE INTO schema_version (version) VALUES (?)
            """, (self.SCHEMA_VERSION,))
            
            conn.commit()
            log.debug(f"Schema v{self.SCHEMA_VERSION} ensured")
    
    def create_session(self, session_id: str, title: str, project_path: str, 
                      model: str = "unknown", tags: List[str] = None) -> bool:
        """
        Create a new session.
        
        Args:
            session_id: Unique session ID
            title: Session title
            project_path: Project root path
            model: AI model used
            tags: List of tags
            
        Returns:
            True if successful
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now().isoformat()
                conn.execute("""
                    INSERT INTO sessions 
                    (id, title, created_at, updated_at, project_path, model, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, title, now, now, project_path, model,
                    json.dumps(tags or [])
                ))
                conn.commit()
                log.info(f"Created session: {session_id}")
                return True
        except sqlite3.IntegrityError:
            log.warning(f"Session already exists: {session_id}")
            return False
        except Exception as e:
            log.error(f"Failed to create session: {e}")
            return False
    
    def add_message(self, session_id: str, message_id: str, role: str,
                   content: str, token_count: int = 0,
                   tool_calls: List[Dict] = None, tool_call_id: str = None,
                   metadata: Dict = None) -> bool:
        """
        Add a message to a session.
        
        Args:
            session_id: Session ID
            message_id: Unique message ID
            role: Message role (user, assistant, system, tool)
            content: Message content
            token_count: Estimated token count
            tool_calls: Tool calls (for assistant messages)
            tool_call_id: Tool call ID (for tool messages)
            metadata: Additional metadata
            
        Returns:
            True if successful
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now().isoformat()
                
                conn.execute("""
                    INSERT INTO messages 
                    (id, session_id, role, content, timestamp, token_count, 
                     tool_calls, tool_call_id, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    message_id, session_id, role, content, now, token_count,
                    json.dumps(tool_calls) if tool_calls else None,
                    tool_call_id,
                    json.dumps(metadata) if metadata else None
                ))
                
                # Update session stats
                conn.execute("""
                    UPDATE sessions 
                    SET message_count = message_count + 1,
                        total_tokens = total_tokens + ?,
                        updated_at = ?
                    WHERE id = ?
                """, (token_count, now, session_id))
                
                conn.commit()
                return True
        except Exception as e:
            log.error(f"Failed to add message: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[SessionMetadata]:
        """Get session metadata."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    return SessionMetadata(
                        id=row['id'],
                        title=row['title'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at'],
                        project_path=row['project_path'],
                        model=row['model'],
                        message_count=row['message_count'],
                        total_tokens=row['total_tokens'],
                        tags=json.loads(row['tags']) if row['tags'] else []
                    )
                return None
        except Exception as e:
            log.error(f"Failed to get session: {e}")
            return None
    
    def get_session_messages(self, session_id: str, 
                            limit: int = None,
                            offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get messages for a session.
        
        Args:
            session_id: Session ID
            limit: Maximum number of messages
            offset: Number of messages to skip
            
        Returns:
            List of message dictionaries
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                query = "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp"
                params = [session_id]
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                    if offset:
                        query += " OFFSET ?"
                        params.append(offset)
                
                cursor = conn.execute(query, params)
                
                messages = []
                for row in cursor.fetchall():
                    messages.append({
                        'id': row['id'],
                        'role': row['role'],
                        'content': row['content'],
                        'timestamp': row['timestamp'],
                        'token_count': row['token_count'],
                        'tool_calls': json.loads(row['tool_calls']) if row['tool_calls'] else None,
                        'tool_call_id': row['tool_call_id'],
                        'metadata': json.loads(row['metadata']) if row['metadata'] else None
                    })
                
                return messages
        except Exception as e:
            log.error(f"Failed to get messages: {e}")
            return []
    
    def list_sessions(self, project_path: str = None, 
                     limit: int = 50,
                     offset: int = 0) -> List[SessionMetadata]:
        """
        List sessions.
        
        Args:
            project_path: Filter by project path (optional)
            limit: Maximum sessions to return
            offset: Sessions to skip
            
        Returns:
            List of SessionMetadata
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if project_path:
                    query = """
                        SELECT * FROM sessions 
                        WHERE project_path = ?
                        ORDER BY updated_at DESC 
                        LIMIT ? OFFSET ?
                    """
                    params = (project_path, limit, offset)
                else:
                    query = """
                        SELECT * FROM sessions 
                        ORDER BY updated_at DESC 
                        LIMIT ? OFFSET ?
                    """
                    params = (limit, offset)
                
                cursor = conn.execute(query, params)
                
                sessions = []
                for row in cursor.fetchall():
                    sessions.append(SessionMetadata(
                        id=row['id'],
                        title=row['title'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at'],
                        project_path=row['project_path'],
                        model=row['model'],
                        message_count=row['message_count'],
                        total_tokens=row['total_tokens'],
                        tags=json.loads(row['tags']) if row['tags'] else []
                    ))
                
                return sessions
        except Exception as e:
            log.error(f"Failed to list sessions: {e}")
            return []
    
    def search_messages(self, query: str, session_id: str = None) -> List[Dict[str, Any]]:
        """
        Search messages using full-text search.
        
        Args:
            query: Search query
            session_id: Limit to specific session (optional)
            
        Returns:
            List of matching messages
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if session_id:
                    cursor = conn.execute("""
                        SELECT m.* FROM messages m
                        JOIN messages_fts fts ON m.rowid = fts.rowid
                        WHERE messages_fts MATCH ? AND m.session_id = ?
                        ORDER BY rank
                    """, (query, session_id))
                else:
                    cursor = conn.execute("""
                        SELECT m.* FROM messages m
                        JOIN messages_fts fts ON m.rowid = fts.rowid
                        WHERE messages_fts MATCH ?
                        ORDER BY rank
                    """, (query,))
                
                messages = []
                for row in cursor.fetchall():
                    messages.append({
                        'id': row['id'],
                        'session_id': row['session_id'],
                        'role': row['role'],
                        'content': row['content'],
                        'timestamp': row['timestamp']
                    })
                
                return messages
        except Exception as e:
            log.error(f"Failed to search messages: {e}")
            return []
    
    def update_session_title(self, session_id: str, new_title: str) -> bool:
        """Update session title."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now().isoformat()
                cursor = conn.execute(
                    "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (new_title, now, session_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            log.error(f"Failed to update title: {e}")
            return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                conn.commit()
                log.info(f"Deleted session: {session_id}")
                return True
        except Exception as e:
            log.error(f"Failed to delete session: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM sessions")
                session_count = cursor.fetchone()[0]
                
                cursor = conn.execute("SELECT COUNT(*) FROM messages")
                message_count = cursor.fetchone()[0]
                
                cursor = conn.execute(
                    "SELECT SUM(total_tokens) FROM sessions"
                )
                total_tokens = cursor.fetchone()[0] or 0
                
                return {
                    "sessions": session_count,
                    "messages": message_count,
                    "total_tokens": total_tokens,
                    "db_path": str(self.db_path),
                    "schema_version": self.SCHEMA_VERSION
                }
        except Exception as e:
            log.error(f"Failed to get stats: {e}")
            return {}


# Global instance
_schema_manager: Optional[SessionSchemaManager] = None


def get_session_schema_manager(db_path: str = None) -> SessionSchemaManager:
    """Get global SessionSchemaManager instance."""
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = SessionSchemaManager(db_path)
    return _schema_manager
