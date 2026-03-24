"""
AI Provider Registry and Base Classes for Cortex AI Agent IDE
Provides unified interface for multiple LLM providers
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Generator, Callable
from dataclasses import dataclass
from enum import Enum
import time
import json
from src.utils.logger import get_logger

log = get_logger("provider_registry")


class ProviderType(Enum):
    """Supported LLM providers."""
    DEEPSEEK = "deepseek"  # Primary provider for agentic work
    TOGETHER = "together"  # Qwen, Kimi, MiniMax, DeepSeek-R1


@dataclass
class ModelInfo:
    """Information about an LLM model."""
    id: str
    name: str
    provider: str
    context_length: int
    max_tokens: int
    supports_streaming: bool = True
    supports_vision: bool = False
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


@dataclass
class ChatMessage:
    """Represents a chat message."""
    role: str  # 'system', 'user', 'assistant', 'tool'
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ChatResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: Optional[str] = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class BaseProvider(ABC):
    """Abstract base class for all LLM providers."""
    
    def __init__(self, provider_type: ProviderType):
        self.provider_type = provider_type
        self._api_key: Optional[str] = None
        self._base_url: Optional[str] = None
        self._last_error: Optional[str] = None
        
    @property
    @abstractmethod
    def available_models(self) -> List[ModelInfo]:
        """Return list of available models for this provider."""
        pass
    
    @abstractmethod
    def chat(self, 
             messages: List[ChatMessage], 
             model: str,
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None) -> ChatResponse:
        """
        Send a chat completion request.
        
        Args:
            messages: List of chat messages
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            
        Returns:
            ChatResponse object
        """
        pass
    
    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str,
                   temperature: float = 0.7,
                   max_tokens: int = 2000,
                   tools: Optional[List[Dict[str, Any]]] = None) -> Generator[str, None, None]:
        """
        Stream chat completion response.
        
        Args:
            messages: List of chat messages
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Yields:
            String chunks of the response
        """
        response = self.chat(messages, model, temperature, max_tokens, stream=True, tools=tools)
        yield response.content
    
    @abstractmethod
    def validate_api_key(self) -> bool:
        """Validate the current API key."""
        pass
    
    def set_api_key(self, api_key: str):
        """Set the API key for this provider."""
        self._api_key = api_key
        
    def get_last_error(self) -> Optional[str]:
        """Get the last error message."""
        return self._last_error
    
    def _format_messages_for_provider(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Convert internal messages to provider-specific format."""
        formatted = []
        for msg in messages:
            m = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_calls:
                m["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            formatted.append(m)
        return formatted


class DeepSeekProvider(BaseProvider):
    """DeepSeek API provider implementation (OpenAI-compatible)."""

    DEFAULT_BASE_URL = "https://api.deepseek.com"

    def __init__(self):
        super().__init__(ProviderType.DEEPSEEK)
        self._client = None
        self._client_key = None  # Track which key the client was created with

    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("deepseek-chat", "DeepSeek Chat", "deepseek", 64000, 4096, True, False, 0.0005, 0.0015),
            ModelInfo("deepseek-coder", "DeepSeek Coder", "deepseek", 64000, 4096, True, False, 0.0005, 0.0015),
        ]

    def set_api_key(self, api_key: str):
        """Set the API key and reset client if key changes."""
        if api_key != self._api_key:
            self._api_key = api_key
            self._client = None  # Reset client so it's recreated with new key
            log.debug(f"DeepSeek API key updated")

    def _get_client(self):
        """Get or create DeepSeek client - NOT USING OPENAI SDK (it hangs)."""
        # We don't use OpenAI SDK - it hangs when connecting to DeepSeek
        # Direct HTTP requests work reliably
        return None
    
    def chat(self, 
             messages: List[ChatMessage], 
             model: str = "deepseek-chat",
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None) -> ChatResponse:
        """Send chat completion request to DeepSeek using OpenAI SDK."""
        start_time = time.time()
        
        try:
            client = self._get_client()
            formatted_messages = self._format_messages_for_provider(messages)
            
            log.info(f"Calling DeepSeek API via OpenAI SDK (stream={stream})...")
            
            response = client.chat.completions.create(
                model=model,
                messages=formatted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice
            )
            
            duration_ms = (time.time() - start_time) * 1000
            
            if stream:
                # Handle streaming response
                content = ""
                chunk_count = 0
                for chunk in response:
                    chunk_count += 1
                    if chunk.choices and chunk.choices[0].delta.content:
                        content += chunk.choices[0].delta.content
                
                log.info(f"Stream completed: {chunk_count} chunks, {len(content)} chars")
                
                return ChatResponse(
                    content=content,
                    model=model,
                    provider="deepseek",
                    duration_ms=duration_ms
                )
            else:
                # Handle regular response
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
                
                return ChatResponse(
                    content=message.content or "",
                    model=model,
                    provider="deepseek",
                    input_tokens=response.usage.prompt_tokens if response.usage else 0,
                    output_tokens=response.usage.completion_tokens if response.usage else 0,
                    finish_reason=response.choices[0].finish_reason,
                    duration_ms=duration_ms,
                    tool_calls=tool_calls
                )
                
        except Exception as e:
            self._last_error = str(e)
            log.error(f"DeepSeek API error: {e}")
            return ChatResponse(
                content="",
                model=model,
                provider="deepseek",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )
    
    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str = "deepseek-chat",
                   temperature: float = 0.7,
                   max_tokens: int = 2000,
                   tools: Optional[List[Dict[str, Any]]] = None) -> Generator[str, None, None]:
        """Stream chat completion from DeepSeek using direct HTTP requests."""
        try:
            import requests as req
            import json
            
            url = f"{self._base_url or self.DEFAULT_BASE_URL}/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
            payload = {
                "model": model,
                "messages": self._format_messages_for_provider(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True  # Enable streaming
            }
            if tools:
                payload["tools"] = tools
            
            log.info(f"POST {url} (streaming mode)")
            
            # Use requests with stream=True for real-time chunks
            response = req.post(url, headers=headers, json=payload, stream=True, timeout=30)
            response.raise_for_status()
            
            log.info(f"Stream established, receiving chunks...")
            
            chunk_count = 0
            
            # Parse SSE stream line by line
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    
                    # Skip comments
                    if line_str.startswith(':'):
                        continue
                    
                    # Parse data lines
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        
                        # Check for end of stream
                        if data_str.strip() == '[DONE]':
                            log.info(f"Stream finished after {chunk_count} chunks")
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            
                            # Extract content from chunk
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                
                                # Yield content
                                if 'content' in delta and delta['content']:
                                    chunk_count += 1
                                    yield delta['content']
                                    
                        except json.JSONDecodeError as e:
                            log.debug(f"Failed to parse chunk: {e}")
            
            if chunk_count == 0:
                log.warning("No chunks received")
            else:
                log.info(f"Streaming complete: {chunk_count} chunks")
                    
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Streaming error: {e}")
            import traceback
            log.error(traceback.format_exc())
            yield f"[Error: {e}]"
    
    def validate_api_key(self) -> bool:
        """Validate DeepSeek API key by making a test request."""
        if not self._api_key:
            return False
        
        try:
            client = self._get_client()
            # Make a minimal request to validate
            response = client.models.list()
            return True
        except Exception as e:
            self._last_error = str(e)
            log.error(f"DeepSeek key validation failed: {e}")
            return False


class ProviderRegistry:
    """Registry for managing multiple AI providers."""
    
    def __init__(self):
        self._providers: Dict[ProviderType, BaseProvider] = {}
        self._current_provider: ProviderType = ProviderType.DEEPSEEK
        
        # Register providers
        self._register_provider(ProviderType.DEEPSEEK, DeepSeekProvider())
        
        # Register Together AI provider
        try:
            from src.ai.providers.together_provider import TogetherProvider
            self._providers[ProviderType.TOGETHER] = TogetherProvider()
        except ImportError:
            log.warning("Together provider not available")
        
        # DeepSeek provider already registered above (only provider needed)
        
    def _register_provider(self, provider_type: ProviderType, provider: BaseProvider):
        """Register a provider."""
        self._providers[provider_type] = provider
        
    def get_provider(self, provider_type: Optional[ProviderType] = None) -> BaseProvider:
        """Get a provider by type."""
        if provider_type is None:
            provider_type = self._current_provider
        return self._providers.get(provider_type, self._providers[ProviderType.DEEPSEEK])
        
    def set_provider(self, provider_type: ProviderType):
        """Set the current provider."""
        if provider_type in self._providers:
            self._current_provider = provider_type
        else:
            log.warning(f"Unknown provider: {provider_type}")
            
    def list_providers(self) -> List[ProviderType]:
        """List all available provider types."""
        return list(self._providers.keys())
        
    def get_all_models(self) -> List[ModelInfo]:
        """Get all models from all providers."""
        models = []
        for provider in self._providers.values():
            models.extend(provider.available_models)
        return models
        
    def validate_all_keys(self) -> Dict[str, bool]:
        """Validate API keys for all providers."""
        results = {}
        for provider_type, provider in self._providers.items():
            results[provider_type.value] = provider.validate_api_key()
        return results


# Global registry instance
_registry = None

def get_provider_registry() -> ProviderRegistry:
    """Get singleton provider registry."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
