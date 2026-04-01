"""
AI Agent V2 - Session-based Architecture
Inspired by OpenCode's architecture
"""

import json
import time
from typing import Optional, List, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal, QThread

from src.ai.session import Session, ToolCall
from src.ai.session_manager import get_session_manager
from src.ai.streaming import get_streaming_emitter
from src.ai.providers import get_provider_registry, ProviderType, ChatMessage
from src.ai._tools_monolithic import ToolRegistry
from src.utils.logger import get_logger

log = get_logger("agent_v2")


class AIWorkerV2(QThread):
    """Worker thread for AI processing"""
    
    def __init__(self, session: Session, model: str, provider: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.model = model
        self.provider = provider
        self.emitter = get_streaming_emitter()
        self._tool_registry = ToolRegistry()  # Use monolithic registry
        self._full_response = ""
        self._tool_calls_buffer: Dict[int, Dict] = {}
    
    MAX_AGENT_ITERATIONS = 15  # Hard cap on agentic loop depth
    
    def run(self):
        """Process the session iteratively (not recursively)."""
        try:
            log.info(f"AIWorkerV2 started for session {self.session.id}")
            
            for iteration in range(self.MAX_AGENT_ITERATIONS):
                log.info(f"Agent iteration {iteration + 1}/{self.MAX_AGENT_ITERATIONS}")
                
                done = self._process_one_turn()
                
                if done:
                    log.info(f"Agent completed after {iteration + 1} iterations")
                    break
            else:
                # Hit max iterations
                log.warning(f"Agent hit max iterations ({self.MAX_AGENT_ITERATIONS})")
                self.emitter.emit_llm_token(
                    f"\n\n⚠️ *Reached maximum of {self.MAX_AGENT_ITERATIONS} steps. "
                    f"Stopping to prevent infinite loop. Please review the progress above.*"
                )
                self._finalize_response()
            
            log.info("AIWorkerV2 completed successfully")
        except Exception as e:
            log.error(f"AIWorkerV2 error: {e}")
            self.emitter.emit_error(str(e))
    
    def _process_one_turn(self) -> bool:
        """
        Execute one LLM call + tool execution round.
        Returns True if done (no more tool calls), False if should continue.
        """
        # Reset response for this turn
        self._full_response = ""
        self._tool_calls_buffer = {}
        
        # Get messages for LLM
        messages = self.session.get_messages_for_llm()
        
        # Get provider
        registry = get_provider_registry()
        provider_map = {
            "deepseek": ProviderType.DEEPSEEK,
            "together": ProviderType.TOGETHER,
        }
        provider_type = provider_map.get(self.provider, ProviderType.DEEPSEEK)
        provider = registry.get_provider(provider_type)
        
        # Convert to ChatMessage objects
        chat_messages = []
        for msg in messages:
            chat_messages.append(ChatMessage(
                role=msg["role"],
                content=msg.get("content", ""),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id")
            ))
        
        # Stream response
        log.info("Starting LLM stream...")
        chunk_count = 0
        
        for chunk in provider.chat_stream(
            messages=chat_messages,
            model=self.model,
            temperature=0.7,
            max_tokens=4000,
            tools=self._get_tools_schema()
        ):
            if not chunk:
                continue
            
            chunk_count += 1
            
            # Handle tool call deltas
            if chunk.startswith("__TOOL_CALL_DELTA__:"):
                self._handle_tool_call_delta(chunk)
            else:
                # Regular content
                self._full_response += chunk
                self.emitter.emit_llm_token(chunk)
        
        log.info(f"Stream completed, {chunk_count} chunks")
        
        # Process any tool calls
        if self._tool_calls_buffer:
            self._execute_tools()
            return False  # Continue loop
        else:
            # No tools, just complete
            self._finalize_response()
            return True   # Done
    
    def _handle_tool_call_delta(self, chunk: str):
        """Handle tool call delta from stream"""
        try:
            deltas = json.loads(chunk[len("__TOOL_CALL_DELTA__:"):])
            for delta in deltas:
                index = delta.get("index", 0)
                if index not in self._tool_calls_buffer:
                    self._tool_calls_buffer[index] = {"id": "", "name": "", "arguments": ""}
                
                if delta.get("id"):
                    self._tool_calls_buffer[index]["id"] += delta["id"]
                if delta.get("function", {}).get("name"):
                    self._tool_calls_buffer[index]["name"] += delta["function"]["name"]
                if delta.get("function", {}).get("arguments"):
                    self._tool_calls_buffer[index]["arguments"] += delta["function"]["arguments"]
        except Exception as e:
            log.error(f"Error parsing tool call delta: {e}")
    
    def _execute_tools(self):
        """Execute collected tool calls"""
        # Convert buffer to ToolCall objects
        tool_calls = []
        for idx in sorted(self._tool_calls_buffer.keys()):
            tc_data = self._tool_calls_buffer[idx]
            if tc_data["id"] and tc_data["name"]:
                try:
                    args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                except:
                    args = {}
                
                tool_call = ToolCall(
                    id=tc_data["id"],
                    name=tc_data["name"],
                    arguments=args
                )
                tool_calls.append(tool_call)
        
        if not tool_calls:
            self._finalize_response()
            return
        
        # Add assistant message with tool calls to session
        self.session.add_assistant_message(self._full_response, tool_calls)
        
        # Execute each tool
        log.info(f"Executing {len(tool_calls)} tools")
        for tc in tool_calls:
            self._execute_single_tool(tc)
        
        # Continue with updated context
        self._continue_after_tools()
    
    def _execute_single_tool(self, tool_call: ToolCall):
        """Execute a single tool"""
        tool_call.status = "executing"
        tool_call.started_at = time.time()
        
        # Emit tool start event
        self.emitter.emit_tool_call_start(
            tool_call.id,
            tool_call.name,
            tool_call.arguments
        )
        
        # Execute
        result = self._tool_registry.execute_tool(
            tool_call.name,
            tool_call.arguments
        )
        
        # Update tool call
        tool_call.status = "completed" if result.success else "error"
        tool_call.result = result.result if result.success else None
        tool_call.error = result.error if not result.success else None
        tool_call.completed_at = time.time()
        
        # Add to session
        self.session.add_tool_result(
            tool_call.id,
            tool_call.result,
            tool_call.error
        )
        
        # Emit result event
        self.emitter.emit_tool_result(
            tool_call.id,
            tool_call.result or tool_call.error,
            result.success
        )
    
    def _finalize_response(self):
        """Finalize the response"""
        if self._full_response:
            self.session.add_assistant_message(self._full_response)
        
        self.emitter.emit_llm_complete(self._full_response)
        get_session_manager().save_current_session()
    
    def _get_tools_schema(self) -> List[Dict]:
        """Get tools schema for LLM"""
        tools = []
        for name, tool in self._tool_registry._tools.items():
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            })
        return tools


class AIAgentV2(QObject):
    """Simplified AI Agent using session-based architecture"""
    
    response_chunk = pyqtSignal(str)
    response_complete = pyqtSignal(str)
    request_error = pyqtSignal(str)
    file_edited_diff = pyqtSignal(str, str, str)  # path, old, new
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[AIWorkerV2] = None
        self._model = "deepseek-reasoner"
        self._provider = "deepseek"
        self._session_manager = get_session_manager()
        self._streaming_emitter = get_streaming_emitter()
        
        # Connect streaming events
        self._setup_streaming_connections()
        
        log.info("AIAgentV2 initialized")
    
    def _setup_streaming_connections(self):
        """Connect streaming events to signals"""
        self._streaming_emitter.llm_token.connect(self.response_chunk.emit)
        self._streaming_emitter.llm_complete.connect(self.response_complete.emit)
        self._streaming_emitter.error.connect(self.request_error.emit)
    
    def chat(self, user_message: str):
        """Send user message and get response"""
        if self._worker and self._worker.isRunning():
            log.warning("Worker already running, skipping")
            return
        
        # Get or create session
        session = self._session_manager.get_current_session()
        if not session:
            session = self._session_manager.create_session()
        
        # Add user message
        session.add_user_message(user_message)
        
        # Start worker
        self._start_worker(session)
    
    def _start_worker(self, session: Session):
        """Start AI worker"""
        self._worker = AIWorkerV2(
            session=session,
            model=self._model,
            provider=self._provider,
            parent=self
        )
        self._worker.start()
    
    def set_project_root(self, path: str):
        """Set project root for new sessions"""
        session = self._session_manager.get_or_create_session(path)
        log.info(f"Project root set: {path}")
    
    def clear_history(self):
        """Clear current session history"""
        session = self._session_manager.get_current_session()
        if session:
            session.messages.clear()
            self._session_manager.save_current_session()
            log.info("History cleared")


# Global instance
_agent_v2 = None


def get_agent_v2() -> AIAgentV2:
    """Get global AIAgentV2 instance"""
    global _agent_v2
    if _agent_v2 is None:
        _agent_v2 = AIAgentV2()
    return _agent_v2
