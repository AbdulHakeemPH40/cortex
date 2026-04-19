"""
SiliconFlow Provider - Supports vision models like Qwen-VL
"""
import os
import json
import time
import requests
from typing import List, Dict, Any, Optional, Generator
from src.ai.providers import BaseProvider, ProviderType, ModelInfo, ChatMessage, ChatResponse
from src.utils.logger import get_logger
from src.config.settings import get_settings

log = get_logger("siliconflow_provider")


class SiliconFlowProvider(BaseProvider):
    """SiliconFlow API provider with vision support."""
    
    BASE_URL = "https://api.siliconflow.com/v1"
    
    def __init__(self):
        super().__init__(ProviderType.SILICONFLOW)  # SiliconFlow provider
        self._api_key = os.getenv("SILICONFLOW_API_KEY", "")
        if not self._api_key:
            log.warning("SiliconFlow API key not configured")
    
    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="Qwen/Qwen3-VL-32B-Instruct",
                name="Qwen3-VL-32B (Vision)",
                provider="siliconflow",
                context_length=32000,
                max_tokens=4000,
                supports_streaming=True,
                supports_vision=True,
                cost_per_1k_input=0.001,
                cost_per_1k_output=0.002
            ),
            ModelInfo(
                id="Qwen/Qwen3-VL-8B-Instruct",
                name="Qwen3-VL-8B (Vision, Fast)",
                provider="siliconflow",
                context_length=32000,
                max_tokens=4000,
                supports_streaming=True,
                supports_vision=True,
                cost_per_1k_input=0.0005,
                cost_per_1k_output=0.001
            ),
            ModelInfo(
                id="Qwen/Qwen2.5-VL-72B-Instruct",
                name="Qwen2.5-VL-72B (Vision)",
                provider="siliconflow",
                context_length=32000,
                max_tokens=4000,
                supports_streaming=True,
                supports_vision=True,
                cost_per_1k_input=0.002,
                cost_per_1k_output=0.004
            ),
            ModelInfo(
                id="Qwen/QwQ-32B",
                name="QwQ-32B (Reasoning)",
                provider="siliconflow",
                context_length=32000,
                max_tokens=4000,
                supports_streaming=True,
                supports_vision=False,
                cost_per_1k_input=0.001,
                cost_per_1k_output=0.002
            ),
        ]
    
    def chat(self,
             messages: List[ChatMessage],
             model: str = "Qwen/Qwen2-VL-72B-Instruct",
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             images: Optional[List[Dict[str, Any]]] = None) -> ChatResponse:
        """Send chat completion request."""
        start_time = time.time()
        
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            }
            
            formatted_messages = self._format_messages_for_api(messages, images)
            
            payload = {
                "model": model,
                "messages": formatted_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream,
            }
            
            if tools:
                payload["tools"] = tools
            
            url = f"{self.BASE_URL}/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            
            duration_ms = (time.time() - start_time) * 1000
            
            content = result['choices'][0]['message']['content'] or ""
            
            return ChatResponse(
                content=content,
                model=model,
                provider="siliconflow",
                input_tokens=result.get('usage', {}).get('prompt_tokens', 0),
                output_tokens=result.get('usage', {}).get('completion_tokens', 0),
                finish_reason=result['choices'][0].get('finish_reason'),
                duration_ms=duration_ms
            )
            
        except Exception as e:
            log.error(f"SiliconFlow API error: {e}")
            return ChatResponse(
                content="",
                model=model,
                provider="siliconflow",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )
    
    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str = "Qwen/Qwen2-VL-72B-Instruct",
                   temperature: float = 0.7,
                   max_tokens: int = 2000,
                   tools: Optional[List[Dict[str, Any]]] = None,
                   images: Optional[List[Dict[str, Any]]] = None,
                   retry_callback=None) -> Generator[str, None, None]:
        """Stream chat completion."""
        # retry_callback is for API compatibility with agent_bridge
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            }
            
            formatted_messages = self._format_messages_for_api(messages, images)
            
            payload = {
                "model": model,
                "messages": formatted_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            
            if tools:
                payload["tools"] = tools
            
            url = f"{self.BASE_URL}/chat/completions"
            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8').strip()
                    if line_text.startswith('data: '):
                        data_str = line_text[6:]
                        if data_str.strip() == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            if 'choices' in data and len(data['choices']) > 0:
                                delta = data['choices'][0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            log.error(f"SiliconFlow stream error: {e}")
            yield f"[Error: {str(e)}]"
    
    def validate_api_key(self) -> bool:
        """Validate the SiliconFlow API key."""
        if not self._api_key:
            return False
        try:
            import requests
            headers = {"Authorization": f"Bearer {self._api_key}"}
            response = requests.get(
                "https://api.siliconflow.com/v1/models",
                headers=headers,
                timeout=10
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def _format_messages_for_api(self, messages: List[ChatMessage], images: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Format messages for SiliconFlow API with vision support."""
        formatted = []
        
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get('content', '')
                role = msg.get('role', 'user')
            else:
                content = msg.content
                role = msg.role
            
            # Handle vision images for user messages
            if role == 'user' and images:
                if isinstance(content, str):
                    content = [{"type": "text", "text": content}]
                elif isinstance(content, list):
                    pass  # Already formatted
                
                # Add images to content
                for img in images:
                    img_obj = {
                        "type": "image_url",
                        "image_url": {
                            "url": img.get('url', img.get('data', ''))
                        }
                    }
                    if isinstance(content, list):
                        content.append(img_obj)
                    else:
                        content = [{"type": "text", "text": content}, img_obj]
            
            formatted.append({
                "role": role,
                "content": content
            })
        
        return formatted


# Singleton instance
_siliconflow_provider: Optional[SiliconFlowProvider] = None

def get_siliconflow_provider() -> SiliconFlowProvider:
    """Get or create SiliconFlow provider instance."""
    global _siliconflow_provider
    if _siliconflow_provider is None:
        _siliconflow_provider = SiliconFlowProvider()
    return _siliconflow_provider
