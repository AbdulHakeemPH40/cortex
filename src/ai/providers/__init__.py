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
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    MOCK = "mock"


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


class OpenAIProvider(BaseProvider):
    """OpenAI API provider implementation."""
    
    def __init__(self):
        super().__init__(ProviderType.OPENAI)
        self._client = None
        
    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("gpt-4-turbo-preview", "GPT-4 Turbo", "openai", 128000, 4096, True, False, 0.01, 0.03),
            ModelInfo("gpt-4", "GPT-4", "openai", 8192, 4096, True, False, 0.03, 0.06),
            ModelInfo("gpt-3.5-turbo", "GPT-3.5 Turbo", "openai", 16385, 4096, True, False, 0.0005, 0.0015),
        ]
    
    def _get_client(self):
        """Get or create OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self._api_key)
            except ImportError:
                raise ImportError("OpenAI package not installed. Run: pip install openai")
        return self._client
    
    def chat(self, 
             messages: List[ChatMessage], 
             model: str = "gpt-3.5-turbo",
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None) -> ChatResponse:
        """Send chat completion request to OpenAI."""
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
                    provider="openai",
                    duration_ms=duration_ms
                )
            else:
                # Handle regular response
                return ChatResponse(
                    content=response.choices[0].message.content,
                    model=model,
                    provider="openai",
                    input_tokens=response.usage.prompt_tokens if response.usage else 0,
                    output_tokens=response.usage.completion_tokens if response.usage else 0,
                    finish_reason=response.choices[0].finish_reason,
                    duration_ms=duration_ms
                )
                
        except Exception as e:
            self._last_error = str(e)
            log.error(f"OpenAI API error: {e}")
            return ChatResponse(
                content="",
                model=model,
                provider="openai",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )
    
    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str = "gpt-3.5-turbo",
                   temperature: float = 0.7,
                   max_tokens: int = 2000,
                   tools: Optional[List[Dict[str, Any]]] = None) -> Generator[str, None, None]:
        """Stream chat completion from OpenAI."""
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
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
                if delta.tool_calls:
                    # Serialize tool calls to a special string format that worker can detect
                    yield f"__TOOL_CALL_DELTA__:{json.dumps([{'index': tc.index, 'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}} for tc in delta.tool_calls])}"
                    
        except Exception as e:
            self._last_error = str(e)
            log.error(f"OpenAI streaming error: {e}")
            yield f"[Error: {e}]"
    
    def validate_api_key(self) -> bool:
        """Validate OpenAI API key by making a test request."""
        if not self._api_key:
            return False
        
        try:
            client = self._get_client()
            # Make a minimal request to validate
            response = client.models.list()
            return True
        except Exception as e:
            self._last_error = str(e)
            log.error(f"OpenAI key validation failed: {e}")
            return False


class AnthropicProvider(BaseProvider):
    """Anthropic Claude API provider implementation."""
    
    def __init__(self):
        super().__init__(ProviderType.ANTHROPIC)
        self._client = None
        
    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("claude-3-opus-20240229", "Claude 3 Opus", "anthropic", 200000, 4096, True, True, 0.015, 0.075),
            ModelInfo("claude-3-sonnet-20240229", "Claude 3 Sonnet", "anthropic", 200000, 4096, True, True, 0.003, 0.015),
            ModelInfo("claude-3-haiku-20240307", "Claude 3 Haiku", "anthropic", 200000, 4096, True, True, 0.00025, 0.00125),
        ]
    
    def _get_client(self):
        """Get or create Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError("Anthropic package not installed. Run: pip install anthropic")
        return self._client
    
    def _format_messages_for_provider(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Format messages for Anthropic API (system prompt separate)."""
        system_message = ""
        chat_messages = []
        
        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                chat_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        return system_message, chat_messages
    
    def chat(self, 
             messages: List[ChatMessage], 
             model: str = "claude-3-sonnet-20240229",
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None) -> ChatResponse:
        """Send chat completion request to Anthropic."""
        start_time = time.time()
        
        try:
            client = self._get_client()
            system, chat_messages = self._format_messages_for_provider(messages)
            
            # Anthropic's tool_choice is more complex, for now, we'll only pass tools if tool_choice is not specified
            # or if it's "auto" (which is default behavior if tools are present)
            anthropic_tools = tools if tools and (tool_choice is None or tool_choice == "auto") else None

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system if system else None,
                messages=chat_messages,
                tools=anthropic_tools
            )
            
            duration_ms = (time.time() - start_time) * 1000
            
            return ChatResponse(
                content=response.content[0].text,
                model=model,
                provider="anthropic",
                input_tokens=response.usage.input_tokens if response.usage else 0,
                output_tokens=response.usage.output_tokens if response.usage else 0,
                finish_reason=response.stop_reason,
                duration_ms=duration_ms
            )
                
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Anthropic API error: {e}")
            return ChatResponse(
                content="",
                model=model,
                provider="anthropic",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )
    
    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str = "claude-3-sonnet-20240229",
                   temperature: float = 0.7,
                   max_tokens: int = 2000,
                   tools: Optional[List[Dict[str, Any]]] = None) -> Generator[str, None, None]:
        """Stream chat completion from Anthropic."""
        try:
            client = self._get_client()
            system, chat_messages = self._format_messages_for_provider(messages)
            
            # Anthropic's tool_choice is more complex, for now, we'll only pass tools if tool_choice is not specified
            # or if it's "auto" (which is default behavior if tools are present)
            anthropic_tools = tools if tools else None

            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system if system else None,
                messages=chat_messages,
                tools=anthropic_tools
            ) as stream:
                for text in stream.text_stream:
                    yield text
                    
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Anthropic streaming error: {e}")
            yield f"[Error: {e}]"
    
    def validate_api_key(self) -> bool:
        """Validate Anthropic API key."""
        if not self._api_key:
            return False
        
        try:
            client = self._get_client()
            # Make a minimal request
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return True
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Anthropic key validation failed: {e}")
            return False


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
                
                # Check for finish reason - stream is done
                if chunk.choices[0].finish_reason:
                    break
                
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
                if delta.tool_calls:
                    # Serialize tool calls to a special string format that worker can detect
                    yield f"__TOOL_CALL_DELTA__:{json.dumps([{'index': tc.index, 'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}} for tc in delta.tool_calls])}"
                    
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


class MockProvider(BaseProvider):
    """Mock provider for testing without API keys."""
    
    def __init__(self):
        super().__init__(ProviderType.MOCK)
        self._responses = [
            "I'm a mock AI assistant. This is a test response.",
            "Mock mode activated! No API key required.",
            "This is a simulated response for testing purposes.",
            "Mock provider is working correctly.",
        ]
        self._response_index = 0
        
    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("mock-model", "Mock Model", "mock", 4096, 2000, True, False, 0.0, 0.0),
        ]
    
    def chat(self, 
             messages: List[ChatMessage], 
             model: str = "mock-model",
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False) -> ChatResponse:
        """Return mock response."""
        import time
        start_time = time.time()
        
        # Get next response
        response_text = self._responses[self._response_index]
        self._response_index = (self._response_index + 1) % len(self._responses)
        
        # Simulate delay
        time.sleep(0.5)
        
        return ChatResponse(
            content=response_text,
            model=model,
            provider="mock",
            input_tokens=len(str(messages)),
            output_tokens=len(response_text),
            duration_ms=(time.time() - start_time) * 1000
        )
    
    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str = "mock-model",
                   temperature: float = 0.7,
                   max_tokens: int = 2000) -> Generator[str, None, None]:
        """Stream mock response."""
        import time
        
        response_text = self._responses[self._response_index]
        self._response_index = (self._response_index + 1) % len(self._responses)
        
        # Stream word by word
        words = response_text.split()
        for word in words:
            yield word + " "
            time.sleep(0.1)
    
    def validate_api_key(self) -> bool:
        """Mock always validates."""
        return True


class ProviderRegistry:
    """Registry for managing multiple AI providers."""
    
    def __init__(self):
        self._providers: Dict[ProviderType, BaseProvider] = {}
        self._current_provider: ProviderType = ProviderType.MOCK
        
        # Register providers
        self._register_provider(ProviderType.OPENAI, OpenAIProvider())
        self._register_provider(ProviderType.ANTHROPIC, AnthropicProvider())
        self._register_provider(ProviderType.DEEPSEEK, DeepSeekProvider())
        self._register_provider(ProviderType.MOCK, MockProvider())
        
    def _register_provider(self, provider_type: ProviderType, provider: BaseProvider):
        """Register a provider."""
        self._providers[provider_type] = provider
        
    def get_provider(self, provider_type: Optional[ProviderType] = None) -> BaseProvider:
        """Get a provider by type."""
        if provider_type is None:
            provider_type = self._current_provider
        return self._providers.get(provider_type, self._providers[ProviderType.MOCK])
        
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
            if provider_type != ProviderType.MOCK:
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
