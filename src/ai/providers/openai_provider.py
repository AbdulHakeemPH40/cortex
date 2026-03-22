"""
OpenAI Provider
Supports GPT-4o, GPT-4 Turbo, GPT-3.5 Turbo models with cost tracking
"""

import os
import time
import json
from typing import List, Dict, Any, Generator, Optional
from src.utils.logger import get_logger
from src.ai.providers import BaseProvider, ProviderType, ModelInfo, ChatMessage, ChatResponse

log = get_logger("openai_provider")


class OpenAIProvider(BaseProvider):
    """OpenAI API Provider"""
    
    def __init__(self):
        super().__init__(ProviderType.OPENAI)
        self._client = None
        self._client_key = None  # Track which key the client was created with
        self._token_count = {"input": 0, "output": 0}
        
        # Initialize from environment
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            self.set_api_key(api_key)
        else:
            log.warning("OPENAI_API_KEY not configured")
    
    @property
    def available_models(self) -> List[ModelInfo]:
        """Return list of available OpenAI models."""
        return [
            ModelInfo("gpt-4o", "GPT-4o", "openai", 128000, 4096, True, True, 0.005, 0.015),
            ModelInfo("gpt-4o-mini", "GPT-4o Mini", "openai", 128000, 4096, True, True, 0.00015, 0.0006),
            ModelInfo("gpt-4-turbo", "GPT-4 Turbo", "openai", 128000, 4096, True, True, 0.01, 0.03),
            ModelInfo("gpt-4", "GPT-4", "openai", 8192, 4096, True, True, 0.03, 0.06),
            ModelInfo("gpt-3.5-turbo", "GPT-3.5 Turbo", "openai", 16385, 4096, True, False, 0.0005, 0.0015),
        ]
    
    def set_api_key(self, api_key: str):
        """Set the API key and reset client if key changes."""
        if api_key != self._api_key:
            self._api_key = api_key
            self._client = None  # Reset client so it's recreated with new key
            log.debug(f"OpenAI API key updated")
    
    def _get_client(self):
        """Get or create OpenAI client."""
        # Recreate client if key changed or client doesn't exist
        if self._client is None or self._client_key != self._api_key:
            try:
                from openai import OpenAI
                if not self._api_key:
                    raise ValueError("API key not set for OpenAI")
                
                log.debug(f"Creating OpenAI client with key: {self._api_key[:10]}...")
                self._client = OpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url or "https://api.openai.com/v1"
                )
                self._client_key = self._api_key
            except ImportError:
                raise ImportError("OpenAI package not installed. Run: pip install openai")
        
        return self._client
    
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
            tools: List of tools available to the model
            tool_choice: Tool choice configuration
            
        Returns:
            ChatResponse object
        """
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
                
                # Track token usage
                if hasattr(response, 'usage') and response.usage:
                    self._token_count["input"] += response.usage.prompt_tokens
                    self._token_count["output"] += response.usage.completion_tokens
                
                return ChatResponse(
                    content=message.content or "",
                    model=model,
                    provider="openai",
                    duration_ms=duration_ms,
                    tool_calls=tool_calls,
                    finish_reason=response.choices[0].finish_reason
                )
                
        except Exception as e:
            self._last_error = str(e)
            log.error(f"OpenAI chat request failed: {e}")
            return ChatResponse(
                content="",
                model=model,
                provider="openai",
                duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )
    
    def validate_api_key(self) -> bool:
        """Validate OpenAI API key."""
        if not self._api_key:
            return False
        
        try:
            client = self._get_client()
            # Make a minimal request
            response = client.models.list()
            return True
        except Exception as e:
            self._last_error = str(e)
            log.error(f"OpenAI key validation failed: {e}")
            return False
    
    def get_token_count(self) -> Dict[str, int]:
        """Get total token usage."""
        return self._token_count.copy()
    
    def get_estimated_cost(self) -> float:
        """Calculate estimated cost based on token usage."""
        # For now, return 0 - proper cost tracking would need per-model usage
        return 0.0
    
    def reset_token_count(self):
        """Reset token counters."""
        self._token_count = {"input": 0, "output": 0}
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get provider information."""
        return {
            "name": "OpenAI",
            "type": "openai",
            "available": self._api_key is not None,
            "models": [m.id for m in self.available_models],
            "token_count": self.get_token_count(),
            "estimated_cost": self.get_estimated_cost()
        }