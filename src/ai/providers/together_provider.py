"""
Together AI Provider for Cortex AI Agent IDE
Supports multiple models via unified API:
- Qwen/Qwen3.5-397B-A17B
- moonshotai/Kimi-K2.5
- MiniMaxAI/MiniMax-M2.5
"""

from typing import List, Dict, Any, Optional, Generator
import time
import json
from src.utils.logger import get_logger

log = get_logger("together_provider")


class TogetherProvider:
    """Together AI provider - supports multiple models via unified API."""
    
    def __init__(self):
        self._api_key: Optional[str] = None
        self._client = None
        self._client_key = None
        self._last_error: Optional[str] = None
    
    @property
    def available_models(self) -> list:
        """Return list of available models."""
        return [
            {"id": "Qwen/Qwen3.5-397B-A17B", "name": "Qwen 3.5 397B", "context": 128000},
            {"id": "moonshotai/Kimi-K2.5", "name": "Kimi K2.5", "context": 128000},
            {"id": "MiniMaxAI/MiniMax-M2.5", "name": "MiniMax M2.5", "context": 128000},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1", "context": 128000},
            {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3", "context": 128000},
        ]
    
    def set_api_key(self, api_key: str):
        """Set the API key."""
        if api_key != self._api_key:
            self._api_key = api_key
            self._client = None
            log.debug("Together AI API key updated")
    
    def _get_client(self):
        """Get or create Together client."""
        if self._client is None or self._client_key != self._api_key:
            try:
                from together import Together
                if not self._api_key:
                    raise ValueError("API key not set for Together AI")
                
                log.debug(f"Creating Together client with key: {self._api_key[:10]}...")
                self._client = Together(api_key=self._api_key)
                self._client_key = self._api_key
            except ImportError:
                raise ImportError("Together package not installed. Run: pip install together")
        return self._client
    
    def chat(self, messages: list, model: str = "Qwen/Qwen3.5-397B-A17B",
             temperature: float = 0.7, max_tokens: int = 4096,
             tools: Optional[List[Dict[str, Any]]] = None) -> dict:
        """Send chat completion request to Together AI."""
        start_time = time.time()
        
        try:
            client = self._get_client()
            
            # Format messages
            formatted_messages = []
            for msg in messages:
                m = {"role": msg.role, "content": msg.content}
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    m["tool_calls"] = msg.tool_calls
                if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
                    m["tool_call_id"] = msg.tool_call_id
                formatted_messages.append(m)
            
            # Build request
            kwargs = {
                "model": model,
                "messages": formatted_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                kwargs["tools"] = tools
            
            response = client.chat.completions.create(**kwargs)
            
            duration_ms = (time.time() - start_time) * 1000
            
            message = response.choices[0].message
            
            # Extract tool calls if present
            tool_calls = None
            if hasattr(message, 'tool_calls') and message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })
            
            return {
                "content": message.content or "",
                "model": model,
                "provider": "together",
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
                "duration_ms": duration_ms,
                "tool_calls": tool_calls
            }
            
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Together AI error: {e}")
            return {
                "content": "",
                "model": model,
                "provider": "together",
                "error": str(e),
                "duration_ms": (time.time() - start_time) * 1000
            }
    
    def chat_stream(self, messages: list, model: str = "Qwen/Qwen3.5-397B-A17B",
                    temperature: float = 0.7, max_tokens: int = 4096,
                    tools: Optional[List[Dict[str, Any]]] = None) -> Generator[str, None, None]:
        """Stream chat completion from Together AI."""
        try:
            client = self._get_client()
            
            # Format messages
            formatted_messages = []
            for msg in messages:
                m = {"role": msg.role, "content": msg.content}
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    m["tool_calls"] = msg.tool_calls
                if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
                    m["tool_call_id"] = msg.tool_call_id
                formatted_messages.append(m)
            
            # Build request
            kwargs = {
                "model": model,
                "messages": formatted_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if tools:
                kwargs["tools"] = tools
            
            response = client.chat.completions.create(**kwargs)
            
            for chunk in response:
                if not chunk.choices:
                    continue
                
                if chunk.choices[0].finish_reason:
                    break
                
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    yield f"__TOOL_CALL_DELTA__:{json.dumps([{'index': tc.index, 'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}} for tc in delta.tool_calls])}"
                    
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Together AI streaming error: {e}")
            yield f"[Error: {e}]"
    
    def validate_api_key(self) -> bool:
        """Validate Together AI API key."""
        if not self._api_key:
            return False
        
        try:
            client = self._get_client()
            # Make a minimal request
            response = client.models.list()
            return True
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Together AI key validation failed: {e}")
            return False
    
    def get_last_error(self) -> Optional[str]:
        """Get last error message."""
        return self._last_error
