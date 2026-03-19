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
    DEEPSEEK = "deepseek"
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
        """Get or create DeepSeek client."""
        # Recreate client if key changed or client doesn't exist
        if self._client is None or self._client_key != self._api_key:
            try:
                from openai import OpenAI
                if not self._api_key:
                    raise ValueError("API key not set for DeepSeek")

                log.debug(f"Creating DeepSeek client with key: {self._api_key[:10]}...")
                self._client = OpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url or self.DEFAULT_BASE_URL
                )
                self._client_key = self._api_key
            except ImportError:
                raise ImportError("OpenAI package not installed. Run: pip install openai")
        return self._client
    
    def chat(self, 
             messages: List[ChatMessage], 
             model: str = "deepseek-chat",
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None) -> ChatResponse:
        """Send chat completion request to DeepSeek."""
        start_time = time.time()
        
        try:
            client = self._get_client()
            formatted_messages = self._format_messages_for_provider(messages)
            
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
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        content += chunk.choices[0].delta.content
                
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
        """Stream chat completion from DeepSeek."""
        try:
            client = self._get_client()
            formatted_messages = self._format_messages_for_provider(messages)
            
            response = client.chat.completions.create(
                model=model,
                messages=formatted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                tools=tools
            )
            
            import json
            for chunk in response:
                # Check if chunk has choices
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # Process content first
                if delta.content:
                    yield delta.content
                
                # Process tool calls - IMPORTANT: process BEFORE checking finish_reason
                if delta.tool_calls:
                    # Serialize tool calls to a special string format that worker can detect
                    # Handle None arguments gracefully
                    tool_call_data = []
                    for tc in delta.tool_calls:
                        tc_info = {
                            'index': tc.index, 
                            'id': tc.id or '', 
                            'function': {
                                'name': tc.function.name if tc.function else '', 
                                'arguments': tc.function.arguments if tc.function and tc.function.arguments else ''
                            }
                        }
                        tool_call_data.append(tc_info)
                    yield f"__TOOL_CALL_DELTA__:{json.dumps(tool_call_data)}"
                
                # Check for finish reason AFTER processing - stream is done
                if chunk.choices[0].finish_reason:
                    break
                    
        except Exception as e:
            self._last_error = str(e)
            log.error(f"DeepSeek streaming error: {e}")
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
