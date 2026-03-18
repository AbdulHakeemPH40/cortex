"""
Session Management for AI Chat
Manages conversation state, tool execution, and context
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json
import uuid
from src.utils.logger import get_logger

log = get_logger("ai_session")


@dataclass
class ToolCall:
    """Represents a tool call from the AI"""
    id: str
    name: str
    arguments: Dict[str, Any]
    status: str = "pending"  # pending, executing, completed, error
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class Message:
    """Chat message"""
    id: str
    role: str  # user, assistant, tool
    content: str
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "status": tc.status,
                    "result": tc.result,
                    "error": tc.error
                } for tc in self.tool_calls
            ] if self.tool_calls else None,
            "tool_call_id": self.tool_call_id,
            "timestamp": self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Message":
        tool_calls = None
        if data.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=tc["arguments"],
                    status=tc.get("status", "completed"),
                    result=tc.get("result"),
                    error=tc.get("error")
                ) for tc in data["tool_calls"]
            ]
        
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            role=data["role"],
            content=data["content"],
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now()
        )


class Session:
    """Manages AI chat session state"""
    
    def __init__(self, session_id: Optional[str] = None, project_root: Optional[str] = None):
        self.id = session_id or str(uuid.uuid4())
        self.project_root = project_root
        self.messages: List[Message] = []
        self.active_tool_calls: Dict[str, ToolCall] = {}
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.metadata: Dict[str, Any] = {}
        
        log.info(f"Session {self.id} created")
    
    def add_user_message(self, content: str) -> Message:
        """Add user message to session"""
        msg = Message(
            id=str(uuid.uuid4()),
            role="user",
            content=content
        )
        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg
    
    def add_assistant_message(self, content: str, tool_calls: Optional[List[ToolCall]] = None) -> Message:
        """Add assistant message to session"""
        msg = Message(
            id=str(uuid.uuid4()),
            role="assistant",
            content=content,
            tool_calls=tool_calls
        )
        self.messages.append(msg)
        
        # Track active tool calls
        if tool_calls:
            for tc in tool_calls:
                self.active_tool_calls[tc.id] = tc
        
        self.updated_at = datetime.now()
        return msg
    
    def add_tool_result(self, tool_call_id: str, result: Any, error: Optional[str] = None) -> Message:
        """Add tool result to session"""
        # Update the tool call
        if tool_call_id in self.active_tool_calls:
            tc = self.active_tool_calls[tool_call_id]
            tc.status = "error" if error else "completed"
            tc.result = result
            tc.error = error
            tc.completed_at = datetime.now()
        
        # Add tool message
        content = str(result) if result else (error or "")
        msg = Message(
            id=str(uuid.uuid4()),
            role="tool",
            content=content,
            tool_call_id=tool_call_id
        )
        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg
    
    def get_recent_messages(self, limit: int = 20) -> List[Message]:
        """Get recent messages for context"""
        return self.messages[-limit:]
    
    def to_dict(self) -> Dict:
        """Serialize session to dict"""
        return {
            "id": self.id,
            "project_root": self.project_root,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Session":
        """Deserialize session from dict"""
        session = cls(
            session_id=data["id"],
            project_root=data.get("project_root")
        )
        session.messages = [Message.from_dict(m) for m in data.get("messages", [])]
        session.created_at = datetime.fromisoformat(data["created_at"])
        session.updated_at = datetime.fromisoformat(data["updated_at"])
        session.metadata = data.get("metadata", {})
        return session
    
    def get_messages_for_llm(self) -> List[Dict[str, Any]]:
        """Convert messages to LLM format"""
        llm_messages = []
        
        for msg in self.messages:
            if msg.role == "tool":
                llm_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content
                })
            elif msg.role == "assistant" and msg.tool_calls:
                llm_messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments)
                            }
                        } for tc in msg.tool_calls
                    ]
                })
            else:
                llm_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        return llm_messages
