"""
Chat History Manager - SQLite-based chat history storage
Migrates from JSON files to persistent SQLite database
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import dataclass
from src.utils.logger import get_logger
from src.core.database import CortexDatabase, get_database

log = get_logger("chat_history")


@dataclass
class Conversation:
    """A chat conversation."""
    id: str
    title: str
    project_path: str
    created_at: datetime
    updated_at: datetime
    messages: List[Dict]


class ChatHistoryManager:
    """
    Manages chat history using SQLite database.
    Provides migration from JSON files to database.
    """
    
    def __init__(self, db: CortexDatabase = None):
        """Initialize chat history manager."""
        self.db = db or get_database()
        self._json_dir = Path.home() / ".cortex" / "chats"
    
    def create_conversation(self, project_path: str, title: str = None, conversation_id: str = None) -> str:
        """Create a new conversation and return its ID."""
        import uuid
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        
        self.db.create_conversation(
            conversation_id=conversation_id,
            project_path=project_path,
            title=title or f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        log.debug(f"Created conversation {conversation_id}")
        return conversation_id
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        files_accessed: List[str] = None,
        tools_used: List[str] = None
    ) -> int:
        """Add a message to a conversation."""
        return self.db.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            files_accessed=files_accessed or [],
            tools_used=tools_used or []
        )
    
    def get_messages(
        self,
        conversation_id: str,
        limit: int = 5000
    ) -> List[Dict]:
        """Get messages for a conversation."""
        messages = self.db.get_messages(conversation_id, limit)
        return [
            {
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'timestamp': m.timestamp.isoformat() if m.timestamp else None,
                'files_accessed': m.files_accessed,
                'tools_used': m.tools_used
            }
            for m in messages
        ]
    
    def get_conversations(self, project_path: str = None) -> List[Dict]:
        """Get all conversations for a project."""
        return self.db.get_conversations(project_path)
    
    def delete_conversation(self, conversation_id: str):
        """Delete a conversation and all its messages."""
        self.db.delete_conversation(conversation_id)
        log.debug(f"Deleted conversation {conversation_id}")
        
    def clear_conversation_messages(self, conversation_id: str):
        """Clear all messages from a conversation without deleting it."""
        self.db.clear_conversation_messages(conversation_id)
    
    def search_messages(self, query: str, project_path: str = None) -> List[Dict]:
        """Search through message content."""
        # This would use FTS on the messages table
        # For now, return empty list - can be implemented with FTS5
        return []
    
    def get_or_create_conversation(
        self,
        project_path: str,
        conversation_id: str = None
    ) -> str:
        """Get existing conversation or create new one."""
        if conversation_id:
            conversations = self.db.get_conversations(project_path)
            for conv in conversations:
                if conv['conversation_id'] == conversation_id:
                    return conversation_id
        
        # Create new conversation
        return self.create_conversation(project_path)
    
    def migrate_from_json(self, project_path: str, storage_key: str) -> int:
        """
        Migrate chat history from JSON file to database.
        Returns number of conversations migrated.
        """
        json_file = self._json_dir / f"{storage_key}.json"
        
        if not json_file.exists():
            return 0
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            migrated = 0
            for chat_data in data if isinstance(data, list) else [data]:
                # Create conversation
                conv_id = self.create_conversation(
                    project_path=project_path,
                    title=chat_data.get('title', 'Imported Chat'),
                    conversation_id=chat_data.get('id')
                )
                
                # Add messages
                for msg in chat_data.get('messages', []):
                    # Handle both 'content' (new) and 'text' (legacy) keys
                    msg_content = msg.get('content') or msg.get('text', '')
                    self.add_message(
                        conversation_id=conv_id,
                        role=msg.get('role', 'user'),
                        content=msg_content,
                        files_accessed=msg.get('files_accessed', []),
                        tools_used=msg.get('tools_used', [])
                    )
                
                migrated += 1
            
            # Backup the old JSON file
            backup_file = json_file.with_suffix('.json.bak')
            json_file.rename(backup_file)
            log.info(f"Migrated {migrated} conversations from {json_file}")
            
            return migrated
            
        except Exception as e:
            log.error(f"Failed to migrate from {json_file}: {e}")
            return 0
    
    def export_to_json(self, project_path: str) -> Dict:
        """Export chat history to JSON format."""
        conversations = self.get_conversations(project_path)
        
        result = []
        for conv in conversations:
            messages = self.get_messages(conv['conversation_id'])
            result.append({
                'id': conv['conversation_id'],
                'title': conv.get('title', ''),
                'created_at': conv.get('created_at'),
                'updated_at': conv.get('updated_at'),
                'messages': messages
            })
        
        return result
    
    def get_recent_context(
        self,
        conversation_id: str,
        max_messages: int = 10
    ) -> str:
        """
        Get recent context as a formatted string.
        Used for AI context building.
        """
        messages = self.get_messages(conversation_id, max_messages)
        
        context_parts = []
        for msg in messages[-max_messages:]:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            if role == 'user':
                context_parts.append(f"User: {content}")
            elif role == 'assistant':
                context_parts.append(f"Assistant: {content}")
        
        return '\n\n'.join(context_parts)
    
    def clear_project_history(self, project_path: str):
        """Clear all chat history for a project."""
        conversations = self.get_conversations(project_path)
        for conv in conversations:
            self.delete_conversation(conv['conversation_id'])
        log.info(f"Cleared {len(conversations)} conversations for {project_path}")


# Global instance
_chat_history: Optional[ChatHistoryManager] = None


def get_chat_history(db: CortexDatabase = None) -> ChatHistoryManager:
    """Get or create the global chat history manager."""
    global _chat_history
    if _chat_history is None:
        _chat_history = ChatHistoryManager(db)
    return _chat_history