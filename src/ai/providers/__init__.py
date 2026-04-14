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
    DEEPSEEK = "deepseek"   # Primary provider for agentic work
    SILICONFLOW = "siliconflow"  # Vision models
    MISTRAL = "mistral"     # Mistral AI models
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
                # When assistant has tool_calls, content can be null
                if not msg.content:
                    m["content"] = None
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            formatted.append(m)
        return formatted


class DeepSeekProvider(BaseProvider):
    """DeepSeek API provider implementation (OpenAI-compatible)."""

    DEFAULT_BASE_URL = "https://api.deepseek.com"

    def __init__(self):
        super().__init__(ProviderType.DEEPSEEK)
        # Load API key from environment
        import os
        self._api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not self._api_key:
            log.warning("DEEPSEEK_API_KEY not configured")

    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("deepseek-chat", "DeepSeek Chat (V3)", "deepseek", 64000, 4096, True, False, 0.0005, 0.0015),
            ModelInfo("deepseek-coder", "DeepSeek Coder", "deepseek", 64000, 4096, True, False, 0.0005, 0.0015),
            ModelInfo("deepseek-reasoner", "DeepSeek Reasoner (R1)", "deepseek", 64000, 8192, True, False, 0.002, 0.008),
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
            if response.status_code == 400:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('error', {}).get('message', '')
                if "Model Not Exist" in error_msg:
                    log.error(f"DeepSeek Model Not Exist: {model}. Fallback recommended.")
                    yield f"[Error: Model '{model}' not available on your DeepSeek account. Please check your API tier or use 'deepseek-reasoner'.]"
                else:
                    log.error(f"DeepSeek Bad Request: {response.text}")
                    yield f"[Error: HTTP 400 - {error_msg}]"
                return
            elif response.status_code == 402:
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
        """Non-streaming chat completion for DeepSeek"""
        try:
            import requests as req
            import json
            
            if not self._api_key:
                log.error("DeepSeek API key not set!")
                return ChatResponse(content="[Error: API key not configured]", model=model, provider="deepseek")
            
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
                "stream": False
            }
            if tools:
                payload["tools"] = tools
            
            log.info(f"POST {url} (non-streaming)")
            
            response = req.post(url, headers=headers, json=payload, timeout=120)
            
            # Check for errors
            if response.status_code == 402:
                return ChatResponse(content="[Error: Insufficient DeepSeek Balance]", model=model, provider="deepseek")
            elif response.status_code != 200:
                error_text = response.text
                log.error(f"DeepSeek API error: {response.status_code} - {error_text[:500]}")
                return ChatResponse(content=f"[Error: HTTP {response.status_code}]", model=model, provider="deepseek")
            
            result = response.json()
            
            # Extract content
            if 'choices' in result and len(result['choices']) > 0:
                message = result['choices'][0].get('message', {})
                content = message.get('content', '')
                
                # Get usage stats
                usage = result.get('usage', {})
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)
                
                return ChatResponse(
                    content=content,
                    model=model,
                    provider="deepseek",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens
                )
            else:
                return ChatResponse(content="[Error: No response content]", model=model, provider="deepseek")
                
        except Exception as e:
            log.error(f"Chat error: {e}")
            return ChatResponse(content=f"[Error: {str(e)}]", model=model, provider="deepseek")

    def validate_api_key(self) -> bool:
        return bool(self._api_key)


class ProviderRegistry:
    """Registry for managing multiple AI providers."""
    
    def __init__(self):
        self._providers: Dict[ProviderType, BaseProvider] = {}
        self._current_provider: ProviderType = ProviderType.DEEPSEEK
        
        # Register core provider
        self._register_provider(ProviderType.DEEPSEEK, DeepSeekProvider())
        
        # Register Mistral provider
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
