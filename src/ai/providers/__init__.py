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
    SILICONFLOW = "siliconflow" # Vision models
    OPENAI = "openai"       # For OpenAI or SiliconFlow if used as OpenAI


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

    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("deepseek-chat", "DeepSeek Chat", "deepseek", 64000, 4096, True, False, 0.0005, 0.0015),
            ModelInfo("deepseek-coder", "DeepSeek Coder", "deepseek", 64000, 4096, True, False, 0.0005, 0.0015),
        ]

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
            
            if not self._api_key:
                log.error("DeepSeek API key not set!")
                yield "[Error: API key not configured]"
                return
            
            url = f"{self._base_url or self.DEFAULT_BASE_URL}/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
            formatted_messages = self._format_messages_for_provider(messages)
            payload = {
                "model": model,
                "messages": formatted_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }
            if tools:
                payload["tools"] = tools
            
            log.info(f"POST {url} (streaming mode)")
            
            response = req.post(url, headers=headers, json=payload, stream=True, timeout=120)
            
            # Check for HTTP errors
            if response.status_code == 402:
                yield "[Error: Insufficient DeepSeek Balance. Please top up at https://platform.deepseek.com/]"
                return
            elif response.status_code != 200:
                error_text = response.text
                log.error(f"DeepSeek API error: {response.status_code} - {error_text[:500]}")
                yield f"[Error: HTTP {response.status_code}]"
                return
            
            log.info(f"Stream established, receiving chunks...")
            
            chunk_count = 0
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith(':'):
                        continue
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str.strip() == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data_str)
                            if 'error' in chunk:
                                yield f"[Error: {chunk['error'].get('message', 'Unknown error')}]"
                                return
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                if 'content' in delta and delta['content']:
                                    chunk_count += 1
                                    yield delta['content']
                                tool_calls = delta.get('tool_calls', [])
                                if tool_calls:
                                    tool_call_data = []
                                    for tc in tool_calls:
                                        tc_info = {
                                            'index': tc.get('index', 0),
                                            'id': tc.get('id', ''),
                                            'function': {
                                                'name': tc.get('function', {}).get('name', ''),
                                                'arguments': tc.get('function', {}).get('arguments', '')
                                            }
                                        }
                                        tool_call_data.append(tc_info)
                                    yield f"__TOOL_CALL_DELTA__:{json.dumps(tool_call_data)}"
                        except json.JSONDecodeError:
                            pass
                            
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Streaming error: {e}")
            yield f"[Error: {e}]"
    
    def chat(self, messages, model, temperature=0.7, max_tokens=2000, stream=False, tools=None, tool_choice=None):
        # Support for non-streaming case if needed, but registry uses chat_stream for agent
        return ChatResponse(content="Full chat not implemented in this minimal view", model=model, provider="deepseek")

    def validate_api_key(self) -> bool:
        return bool(self._api_key)


class ProviderRegistry:
    """Registry for managing multiple AI providers."""
    
    def __init__(self):
        self._providers: Dict[ProviderType, BaseProvider] = {}
        self._current_provider: ProviderType = ProviderType.DEEPSEEK
        
        # Register core provider
        self._register_provider(ProviderType.DEEPSEEK, DeepSeekProvider())
        
        # Lazily register other providers if their modules are available
        try:
            from src.ai.providers.together_provider import TogetherProvider
            self._register_provider(ProviderType.TOGETHER, TogetherProvider())
            log.info("TogetherProvider registered")
        except (ImportError, Exception) as e:
            log.warning(f"Could not register TogetherProvider: {e}")
            
        try:
            from src.ai.providers.siliconflow_provider import SiliconFlowProvider
            self._register_provider(ProviderType.SILICONFLOW, SiliconFlowProvider())
            # Maintain backward compatibility if it used OPENAI type
            self._register_provider(ProviderType.OPENAI, self._providers[ProviderType.SILICONFLOW])
            log.info("SiliconFlowProvider registered")
        except (ImportError, Exception) as e:
            log.warning(f"Could not register SiliconFlowProvider: {e}")
            
    def _register_provider(self, provider_type: ProviderType, provider: BaseProvider):
        self._providers[provider_type] = provider
        
    def get_provider(self, provider_type: Optional[ProviderType] = None) -> BaseProvider:
        if provider_type is None:
            provider_type = self._current_provider
        
        provider = self._providers.get(provider_type)
        if not provider:
            log.warning(f"Provider {provider_type} not found, falling back to DEEPSEEK")
            return self._providers[ProviderType.DEEPSEEK]
        return provider
        
    def set_provider(self, provider_type: ProviderType):
        if provider_type in self._providers:
            self._current_provider = provider_type
            
    def list_providers(self) -> List[ProviderType]:
        return list(self._providers.keys())
        
    def get_all_models(self) -> List[ModelInfo]:
        models = []
        for provider in self._providers.values():
            models.extend(provider.available_models)
        return models
        
    def validate_all_keys(self) -> Dict[str, bool]:
        results = {}
        for provider_type, provider in self._providers.items():
            results[provider_type.value] = provider.validate_api_key()
        return results


_registry = None

def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
