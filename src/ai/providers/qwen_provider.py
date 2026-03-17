"""
Alibaba Qwen (DashScope) Provider
Supports Qwen 3.5, Qwen Coder, with cost-optimized pricing tiers
"""

import os
import time
from typing import Optional, Dict, List, Any, Generator
from src.ai.providers import get_provider_registry, ProviderType, ChatMessage
from src.config.settings import get_settings
from src.utils.logger import get_logger
import requests

log = get_logger("qwen_provider")

# Model pricing per 1M tokens (USD) - Based on Alibaba Cloud pricing
MODEL_PRICING = {
    # Flagship Models (High Performance)
    "qwen-max": {"input": 2.40, "output": 9.60},  # ~$2.40/1M input tokens
    "qwen-plus": {"input": 0.80, "output": 3.20},  # Cost-optimized flagship
    
    # Qwen 3.5 Series
    "qwen-3.5-max": {"input": 2.00, "output": 8.00},
    "qwen-3.5-plus": {"input": 0.70, "output": 2.80},
    "qwen-3.5-flash": {"input": 0.10, "output": 0.40},  # Ultra cost-optimized
    
    # Qwen 3 Series
    "qwen-3-max": {"input": 1.80, "output": 7.20},
    "qwen-3-coder-plus": {"input": 0.90, "output": 3.60},
    "qwen-3-coder-flash": {"input": 0.15, "output": 0.60},
    
    # Qwen 2.5 Series (Legacy but still useful)
    "qwen-2.5-coder-32b": {"input": 0.50, "output": 2.00},
    "qwen-2.5-72b": {"input": 1.20, "output": 4.80},
}

# Performance multipliers (relative to baseline)
MODEL_PERFORMANCE = {
    "qwen-max": 1.6,      # Ultimate performance
    "qwen-plus": 1.3,     # Balanced flagship
    "qwen-3.5-max": 1.5,
    "qwen-3.5-plus": 1.3,
    "qwen-3.5-flash": 1.0,  # Baseline
    "qwen-3-max": 1.4,
    "qwen-3-coder-plus": 1.3,
    "qwen-3-coder-flash": 1.1,
    "qwen-2.5-coder-32b": 1.2,
    "qwen-2.5-72b": 1.4,
}

class QwenProvider:
    """Alibaba DashScope Qwen Provider"""
    
    def __init__(self):
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "")
        # Updated to latest DashScope endpoint (2024)
        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        # Alternative endpoints for testing:
        # - International: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
        # - China: https://dashscope.aliyuncs.com/compatible-mode/v1
        # - OpenAI-compatible: https://dashscope.aliyuncs.com/compatible-mode/v1
        self._token_count = {"input": 0, "output": 0}
        self._cost_total = 0.0
    
    def set_api_key(self, api_key: str):
        """Set API key"""
        self.api_key = api_key
        
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available Qwen models with pricing info"""
        models = []
        
        for model_id, pricing in MODEL_PRICING.items():
            perf = MODEL_PERFORMANCE.get(model_id, 1.0)
            
            # Calculate cost efficiency score (performance per dollar)
            efficiency = perf / ((pricing["input"] + pricing["output"]) / 2)
            
            models.append({
                "id": model_id,
                "name": model_id.replace("-", " ").title(),
                "pricing": pricing,
                "performance": perf,
                "efficiency": round(efficiency, 2),
                "category": self._get_model_category(model_id)
            })
        
        # Sort by efficiency (best value first)
        models.sort(key=lambda x: x["efficiency"], reverse=True)
        
        return models
    
    def _get_model_category(self, model_id: str) -> str:
        """Categorize model by use case"""
        if "coder" in model_id:
            return "Coding"
        elif "flash" in model_id:
            return "Fast & Cheap"
        elif "max" in model_id:
            return "Flagship"
        elif "plus" in model_id:
            return "Balanced"
        else:
            return "General"
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """Calculate cost for given token usage"""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["qwen-plus"])
        
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        total_cost = input_cost + output_cost
        
        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
            "currency": "USD"
        }
    
    def chat(self, messages: List[ChatMessage], model: str = "qwen-plus", 
             stream: bool = True, **kwargs) -> Generator[str, None, None]:
        """Send chat request to Qwen API"""
        import json
        
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY not configured")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Convert messages to Qwen format
        qwen_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
        
        payload = {
            "model": model,
            "messages": qwen_messages,
            "stream": stream,
            **kwargs
        }
        
        url = f"{self.base_url}/chat/completions"
        
        log.info(f"Qwen API Request: POST {url} | Model: {model} | Messages: {len(qwen_messages)}")
        
        try:
            if stream:
                response = requests.post(url, headers=headers, json=payload, stream=True)
                log.debug(f"Qwen API Response Status: {response.status_code}")
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        line_text = line.decode('utf-8')
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
                                        
                                        # Track tokens (approximate)
                                        if 'usage' in data:
                                            self._token_count["input"] = data['usage'].get('prompt_tokens', 0)
                                            self._token_count["output"] = data['usage'].get('completion_tokens', 0)
                            except json.JSONDecodeError as e:
                                log.error(f"JSON decode error: {e} | Data: {data_str[:100]}")
                                continue
            else:
                response = requests.post(url, headers=headers, json=payload)
                log.debug(f"Qwen API Response Status: {response.status_code}")
                response.raise_for_status()
                result = response.json()
                
                # Track tokens
                if 'usage' in result:
                    self._token_count["input"] = result['usage'].get('prompt_tokens', 0)
                    self._token_count["output"] = result['usage'].get('completion_tokens', 0)
                
                content = result['choices'][0]['message']['content']
                yield content
                
        except requests.exceptions.RequestException as e:
            log.error(f"Qwen API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                log.error(f"Response body: {e.response.text[:500]}")
            raise Exception(f"Qwen API request failed: {str(e)}")
    
    def chat_stream(self, messages: List[ChatMessage], model: str = "qwen-plus",
                    temperature: float = 0.7, max_tokens: int = 4096,
                    tools: Optional[List[Dict[str, Any]]] = None) -> Generator[str, None, None]:
        """Stream chat completion from Qwen API"""
        # Use the chat method with streaming
        yield from self.chat(messages, model, stream=True, temperature=temperature, max_tokens=max_tokens)
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics"""
        total_tokens = self._token_count["input"] + self._token_count["output"]
        
        # Calculate total cost across all models used
        total_cost = self._cost_total
        
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "total_tokens": total_tokens,
            "estimated_cost": total_cost,
            "currency": "USD"
        }
    
    def reset_usage(self):
        """Reset usage counters"""
        self._token_count = {"input": 0, "output": 0}
        self._cost_total = 0.0
    
    def validate_api_key(self) -> bool:
        """Validate API key"""
        return bool(self.api_key)


# Singleton instance
_qwen_provider = None

def get_qwen_provider() -> QwenProvider:
    """Get singleton Qwen provider instance"""
    global _qwen_provider
    if _qwen_provider is None:
        _qwen_provider = QwenProvider()
    return _qwen_provider
