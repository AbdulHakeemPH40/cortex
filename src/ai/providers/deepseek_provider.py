"""
DeepSeek Provider
Supports DeepSeek Chat V3 and Reasoner R1 models with cost tracking
"""

import os
import json
from typing import List, Dict, Any, Generator, Optional
from src.utils.logger import get_logger

log = get_logger("deepseek_provider")

# DeepSeek model pricing per 1M tokens (USD)
DEEPSEEK_PRICING = {
    "deepseek-chat": {"input": 0.27, "output": 0.27},
}

# Performance multipliers
DEEPSEEK_PERFORMANCE = {
    "deepseek-chat": 1.2,
}


class DeepSeekProvider:
    """DeepSeek API Provider"""
    
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = "https://api.deepseek.com/v1"
        self._token_count = {"input": 0, "output": 0}
        
        if not self.api_key:
            log.warning("DEEPSEEK_API_KEY not configured")
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available DeepSeek models"""
        models = []
        
        for model_id, pricing in DEEPSEEK_PRICING.items():
            perf = DEEPSEEK_PERFORMANCE.get(model_id, 1.0)
            
            models.append({
                "id": model_id,
                "name": model_id.replace("-", " ").title(),
                "pricing": pricing,
                "performance": perf,
                "category": self._get_category(model_id)
            })
        
        return models
    
    def _get_category(self, model_id: str) -> str:
        """Get model category"""
        return "General"
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """Calculate cost for token usage"""
        pricing = DEEPSEEK_PRICING.get(model, DEEPSEEK_PRICING["deepseek-chat"])
        
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        total_cost = input_cost + output_cost
        
        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
            "currency": "USD"
        }
    
    def chat(self, messages: List[Dict[str, str]], model: str = "deepseek-chat",
             stream: bool = True, **kwargs) -> Generator[str, None, None]:
        """Send chat request to DeepSeek API"""
        
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not configured. Please add it to .env file.")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs
        }
        
        url = f"{self.base_url}/chat/completions"
        
        try:
            import requests
            
            if stream:
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
                                    # Handle both content and reasoning_content (for R1 model)
                                    content = delta.get('content', '')
                                    reasoning = delta.get('reasoning_content', '')
                                    
                                    # Yield content if available
                                    if content:
                                        yield content
                                    # Yield reasoning content separately (prefix with [THINK])
                                    elif reasoning:
                                        yield f"[THINK] {reasoning}"
                                    
                                    # Track tokens if available
                                    if 'usage' in data:
                                        self._token_count["input"] = data['usage'].get('prompt_tokens', 0)
                                        self._token_count["output"] = data['usage'].get('completion_tokens', 0)
                                        
                            except json.JSONDecodeError as e:
                                log.error(f"Failed to parse SSE data: {e}")
                                continue
                                
            else:
                response = requests.post(url, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                
                result = response.json()
                
                # Track tokens
                if 'usage' in result:
                    self._token_count["input"] = result['usage'].get('prompt_tokens', 0)
                    self._token_count["output"] = result['usage'].get('completion_tokens', 0)
                
                content = result['choices'][0]['message']['content']
                yield content
                
        except requests.exceptions.RequestException as e:
            log.error(f"DeepSeek API error: {e}")
            raise Exception(f"DeepSeek API request failed: {str(e)}")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            raise
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics"""
        total_tokens = self._token_count["input"] + self._token_count["output"]
        
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "total_tokens": total_tokens,
        }
    
    def reset_usage(self):
        """Reset usage counters"""
        self._token_count = {"input": 0, "output": 0}


# Singleton instance
_deepseek_provider = None


def get_deepseek_provider() -> DeepSeekProvider:
    """Get singleton DeepSeek provider instance"""
    global _deepseek_provider
    if _deepseek_provider is None:
        _deepseek_provider = DeepSeekProvider()
    return _deepseek_provider
