"""
Session Manager for AI Chat
Manages session lifecycle, persistence, and retrieval
"""

import os
import json
from typing import Optional, Dict
from pathlib import Path
from src.ai.session import Session
from src.utils.logger import get_logger

log = get_logger("session_manager")


class SessionManager:
    """Manages AI chat sessions"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._sessions: Dict[str, Session] = {}
        self._current_session: Optional[Session] = None
        self._storage_dir = Path.home() / ".cortex" / "sessions"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        
        self._initialized = True
        log.info(f"SessionManager initialized with storage at {self._storage_dir}")
    
    def create_session(self, project_root: Optional[str] = None) -> Session:
        """Create new session"""
        session = Session(project_root=project_root)
        self._sessions[session.id] = session
        self._current_session = session
        self._save_session(session)
        log.info(f"Created session {session.id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        # Check memory first
        if session_id in self._sessions:
            return self._sessions[session_id]
        
        # Try to load from disk
        session = self._load_session(session_id)
        if session:
            self._sessions[session_id] = session
        
        return session
    
    def get_current_session(self) -> Optional[Session]:
        """Get current active session"""
        return self._current_session
    
    def set_current_session(self, session_id: str) -> bool:
        """Set current session"""
        session = self.get_session(session_id)
        if session:
            self._current_session = session
            return True
        return False
    
    def save_current_session(self):
        """Save current session to disk"""
        if self._current_session:
            self._save_session(self._current_session)
    
    def _save_session(self, session: Session):
        """Save session to disk"""
        try:
            file_path = self._storage_dir / f"{session.id}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(session.to_dict(), f, indent=2)
            log.debug(f"Saved session {session.id}")
        except Exception as e:
            log.error(f"Failed to save session {session.id}: {e}")
    
    def _load_session(self, session_id: str) -> Optional[Session]:
        """Load session from disk"""
        try:
            file_path = self._storage_dir / f"{session_id}.json"
            if not file_path.exists():
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            session = Session.from_dict(data)
            log.info(f"Loaded session {session_id}")
            return session
        except Exception as e:
            log.error(f"Failed to load session {session_id}: {e}")
            return None
    
    def list_sessions(self, project_root: Optional[str] = None) -> list:
        """List all sessions, optionally filtered by project"""
        sessions = []
        
        for file_path in self._storage_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if project_root is None or data.get("project_root") == project_root:
                    sessions.append({
                        "id": data["id"],
                        "project_root": data.get("project_root"),
                        "created_at": data["created_at"],
                        "updated_at": data["updated_at"],
                        "message_count": len(data.get("messages", []))
                    })
            except Exception as e:
                log.error(f"Failed to list session {file_path}: {e}")
        
        # Sort by updated_at desc
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session"""
        try:
            # Remove from memory
            if session_id in self._sessions:
                del self._sessions[session_id]
            
            # Remove from disk
            file_path = self._storage_dir / f"{session_id}.json"
            if file_path.exists():
                file_path.unlink()
            
            # Reset current if needed
            if self._current_session and self._current_session.id == session_id:
                self._current_session = None
            
            log.info(f"Deleted session {session_id}")
            return True
        except Exception as e:
            log.error(f"Failed to delete session {session_id}: {e}")
            return False
    
    def get_or_create_session(self, project_root: Optional[str] = None) -> Session:
        """Get existing session for project or create new one"""
        # Try to find existing session for project
        if project_root:
            sessions = self.list_sessions(project_root)
            if sessions:
                session = self.get_session(sessions[0]["id"])
                if session:
                    self._current_session = session
                    return session
        
        # Create new session
        return self.create_session(project_root)


# Global instance
_session_manager = None


def get_session_manager() -> SessionManager:
    """Get global session manager instance"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
