"""
AI Provider Registry and Base Classes for Cortex AI Agent IDE
Provides unified interface for multiple LLM providers
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass
from enum import Enum
from src.utils.logger import get_logger

log = get_logger("provider_registry")


class ProviderType(Enum):
    """Supported LLM providers."""
    MISTRAL = "mistral"     # Primary provider for ALL work
    SILICONFLOW = "siliconflow"  # Vision models
    DEEPSEEK = "deepseek"   # DeepSeek V4 models (Pro & Flash)


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
        formatted: List[Dict[str, Any]] = []
        for msg in messages:
            m: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_calls:
                m["tool_calls"] = msg.tool_calls
                # When assistant has tool_calls, content can be null
                if not msg.content:
                    m["content"] = None
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            formatted.append(m)
        return formatted


class ProviderRegistry:
    """Registry for managing multiple AI providers."""
    
    def __init__(self):
        self._providers: Dict[ProviderType, BaseProvider] = {}
        self._current_provider: ProviderType = ProviderType.MISTRAL
        
        # Register Mistral provider (primary provider for ALL work)
        try:
            from src.ai.providers.mistral_provider import MistralProvider
            self._register_provider(ProviderType.MISTRAL, MistralProvider())
            log.info("MistralProvider registered")
        except (ImportError, Exception) as e:
            log.warning(f"Could not register MistralProvider: {e}")
        

        
        # Lazily register other providers if their modules are available
        try:
            from src.ai.providers.siliconflow_provider import SiliconFlowProvider
            self._register_provider(ProviderType.SILICONFLOW, SiliconFlowProvider())
            log.info("SiliconFlowProvider registered")
        except (ImportError, Exception) as e:
            log.warning(f"Could not register SiliconFlowProvider: {e}")
        
        # Register DeepSeek provider (V4 models with 1M context)
        try:
            from src.ai.providers.deepseek_provider import DeepSeekProvider
            self._register_provider(ProviderType.DEEPSEEK, DeepSeekProvider())
            log.info("DeepSeekProvider registered with V4 models")
        except (ImportError, Exception) as e:
            log.warning(f"Could not register DeepSeekProvider: {e}")
        

            
    def _register_provider(self, provider_type: ProviderType, provider: BaseProvider):
        self._providers[provider_type] = provider
    

        
    def get_provider(self, provider_type: Optional[ProviderType] = None) -> BaseProvider:
        if provider_type is None:
            provider_type = self._current_provider
        
        provider = self._providers.get(provider_type)
        if not provider:
            log.warning(f"Provider {provider_type} not found, falling back to MISTRAL")
            return self._providers[ProviderType.MISTRAL]
        return provider
        
    def set_provider(self, provider_type: ProviderType):
        if provider_type in self._providers:
            self._current_provider = provider_type
            
    def list_providers(self) -> List[ProviderType]:
        return list(self._providers.keys())
        
    def get_all_models(self) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        for provider in self._providers.values():
            models.extend(provider.available_models)
        return models
        
    def validate_all_keys(self) -> Dict[str, bool]:
        results: Dict[str, bool] = {}
        for provider_type, provider in self._providers.items():
            results[provider_type.value] = provider.validate_api_key()
        return results


_registry = None

def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
