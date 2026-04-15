"""
OpenAI Provider for Cortex AI Agent IDE
Supports comprehensive programming/coding models including Codex, GPT-4o, o1, o3 series
"""

import os
import json
from typing import List, Dict, Any, Generator, Optional
from dataclasses import dataclass
from src.utils.logger import get_logger

log = get_logger("openai_provider")


@dataclass
class OpenAIModel:
    """OpenAI model configuration"""
    id: str
    name: str
    category: str  # 'coding', 'reasoning', 'general', 'economy'
    input_price: float  # per 1M tokens
    output_price: float  # per 1M tokens
    cached_input_price: float  # per 1M tokens
    context_window: int
    max_output: int
    supports_tools: bool
    supports_vision: bool
    supports_streaming: bool
    description: str


# Comprehensive OpenAI Model Pricing (per 1M tokens in USD)
# Updated: 2025
OPENAI_MODELS = {
    # ========== CODING SPECIALIZED MODELS ==========
    
    # ========== FRONTIER MODELS (GPT-5.4 Series) ==========
    "gpt-5.4": OpenAIModel(
        id="gpt-5.4",
        name="GPT-5.4",
        category="general",
        input_price=2.50,
        output_price=15.00,
        cached_input_price=0.25,
        context_window=1000000,
        max_output=128000,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Most capable model for complex reasoning and coding"
    ),
    "gpt-5.4-mini": OpenAIModel(
        id="gpt-5.4-mini",
        name="GPT-5.4 Mini",
        category="general",
        input_price=0.75,
        output_price=4.50,
        cached_input_price=0.075,
        context_window=400000,
        max_output=128000,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Strong mini model for coding, computer use, and subagents"
    ),
    "gpt-5.4-nano": OpenAIModel(
        id="gpt-5.4-nano",
        name="GPT-5.4 Nano",
        category="economy",
        input_price=0.20,
        output_price=1.25,
        cached_input_price=0.025,
        context_window=400000,
        max_output=128000,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Cheapest GPT-5.4-class model for simple high-volume tasks"
    ),
    
    # ========== GPT-4.1 SERIES ==========
    "gpt-4.1": OpenAIModel(
        id="gpt-4.1",
        name="GPT-4.1",
        category="general",
        input_price=2.00,
        output_price=8.00,
        cached_input_price=0.50,
        context_window=1000000,
        max_output=128000,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Balanced performance for coding and general tasks"
    ),
    "gpt-4.1-mini": OpenAIModel(
        id="gpt-4.1-mini",
        name="GPT-4.1 Mini",
        category="coding",
        input_price=0.40,
        output_price=1.60,
        cached_input_price=0.10,
        context_window=1000000,
        max_output=128000,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Efficient coding model with excellent performance"
    ),
    "gpt-4.1-nano": OpenAIModel(
        id="gpt-4.1-nano",
        name="GPT-4.1 Nano",
        category="economy",
        input_price=0.10,
        output_price=0.40,
        cached_input_price=0.025,
        context_window=1000000,
        max_output=128000,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Ultra-low cost for simple coding tasks"
    ),
    
    # ========== GPT-4o SERIES ==========
    "gpt-4o": OpenAIModel(
        id="gpt-4o",
        name="GPT-4o",
        category="general",
        input_price=2.50,
        output_price=10.00,
        cached_input_price=1.25,
        context_window=128000,
        max_output=16384,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Multimodal model for text, vision, and audio"
    ),
    "gpt-4o-mini": OpenAIModel(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        category="economy",
        input_price=0.15,
        output_price=0.60,
        cached_input_price=0.075,
        context_window=128000,
        max_output=16384,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Affordable and fast for everyday coding tasks"
    ),
    
    # ========== REASONING MODELS (o-series) ==========
    "o3": OpenAIModel(
        id="o3",
        name="o3",
        category="reasoning",
        input_price=2.00,
        output_price=8.00,
        cached_input_price=0.50,
        context_window=200000,
        max_output=100000,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Advanced reasoning for complex problem-solving"
    ),
    "o1": OpenAIModel(
        id="o1",
        name="o1",
        category="reasoning",
        input_price=15.00,
        output_price=60.00,
        cached_input_price=7.50,
        context_window=200000,
        max_output=100000,
        supports_tools=True,
        supports_vision=False,
        supports_streaming=True,
        description="High-performance reasoning for complex tasks"
    ),
    "o1-mini": OpenAIModel(
        id="o1-mini",
        name="o1 Mini",
        category="reasoning",
        input_price=1.10,
        output_price=4.40,
        cached_input_price=0.55,
        context_window=128000,
        max_output=65536,
        supports_tools=True,
        supports_vision=False,
        supports_streaming=True,
        description="Efficient reasoning for coding and STEM"
    ),
    
    # ========== GPT-5 SERIES ==========
    "gpt-5": OpenAIModel(
        id="gpt-5",
        name="GPT-5",
        category="general",
        input_price=1.25,
        output_price=10.00,
        cached_input_price=0.125,
        context_window=128000,
        max_output=16384,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Next-generation general purpose model"
    ),
    "gpt-5-mini": OpenAIModel(
        id="gpt-5-mini",
        name="GPT-5 Mini",
        category="economy",
        input_price=0.25,
        output_price=2.00,
        cached_input_price=0.025,
        context_window=128000,
        max_output=16384,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Compact GPT-5 for fast responses"
    ),
    "gpt-5-nano": OpenAIModel(
        id="gpt-5-nano",
        name="GPT-5 Nano",
        category="economy",
        input_price=0.05,
        output_price=0.40,
        cached_input_price=0.005,
        context_window=128000,
        max_output=16384,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        description="Ultra-compact for simple tasks"
    ),
}


class OpenAIProvider:
    """
    OpenAI API Provider with comprehensive model support
    Includes Codex, GPT-4o, o1, o3, GPT-5 series for coding tasks
    """
    
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = "https://api.openai.com/v1"
        self._token_count = {"input": 0, "output": 0, "cached": 0}
        self._cost_tracking = {"input_cost": 0.0, "output_cost": 0.0, "total": 0.0}
        
        if not self.api_key:
            log.warning("OPENAI_API_KEY not configured")
    
    def get_available_models(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of available OpenAI models, optionally filtered by category"""
        models = []
        
        for model_id, model in OPENAI_MODELS.items():
            if category and model.category != category:
                continue
                
            models.append({
                "id": model_id,
                "name": model.name,
                "category": model.category,
                "pricing": {
                    "input": model.input_price,
                    "output": model.output_price,
                    "cached_input": model.cached_input_price
                },
                "context_window": model.context_window,
                "max_output": model.max_output,
                "supports_tools": model.supports_tools,
                "supports_vision": model.supports_vision,
                "supports_streaming": model.supports_streaming,
                "description": model.description
            })
        
        # Sort by category then by price
        category_order = {"coding": 0, "reasoning": 1, "general": 2, "economy": 3}
        models.sort(key=lambda x: (category_order.get(x["category"], 99), x["pricing"]["input"]))
        
        return models
    
    def get_coding_models(self) -> List[Dict[str, Any]]:
        """Get models optimized for coding tasks"""
        return self.get_available_models(category="coding")
    
    def get_economy_models(self) -> List[Dict[str, Any]]:
        """Get most cost-effective models"""
        return self.get_available_models(category="economy")
    
    def get_reasoning_models(self) -> List[Dict[str, Any]]:
        """Get reasoning-optimized models (o-series)"""
        return self.get_available_models(category="reasoning")
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int, 
                       cached_tokens: int = 0) -> Dict[str, float]:
        """Calculate cost for token usage"""
        model_info = OPENAI_MODELS.get(model, OPENAI_MODELS["gpt-4o-mini"])
        
        # Calculate costs (prices are per 1M tokens)
        input_cost = (input_tokens / 1_000_000) * model_info.input_price
        output_cost = (output_tokens / 1_000_000) * model_info.output_price
        cached_cost = (cached_tokens / 1_000_000) * model_info.cached_input_price
        
        # Input cost is reduced by cached tokens
        effective_input_cost = max(0, input_cost - cached_cost)
        total_cost = effective_input_cost + output_cost
        
        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "cached_cost": cached_cost,
            "effective_input_cost": effective_input_cost,
            "total_cost": total_cost,
            "currency": "USD"
        }
    
    def get_model_recommendation(self, task_type: str = "coding", 
                                  budget: str = "medium") -> str:
        """Get recommended model based on task and budget"""
        recommendations = {
            "coding": {
                "low": "gpt-4.1-nano",      # $0.10/$0.40 per 1M
                "medium": "gpt-4.1-mini",   # $0.40/$1.60 per 1M
                "high": "gpt-4.1",          # $2.00/$8.00 per 1M
                "premium": "gpt-5.4"        # $2.50/$15.00 per 1M
            },
            "reasoning": {
                "low": "o3",               # $2.00/$8.00 per 1M
                "medium": "o3",             # $2.00/$8.00 per 1M
                "high": "o3",               # $2.00/$8.00 per 1M
                "premium": "o1"             # $15.00/$60.00 per 1M
            },
            "general": {
                "low": "gpt-5-nano",        # $0.05/$0.40 per 1M
                "medium": "gpt-4o-mini",    # $0.15/$0.60 per 1M
                "high": "gpt-4.1",          # $2.00/$8.00 per 1M
                "premium": "gpt-5.4"        # $2.50/$15.00 per 1M
            }
        }
        
        return recommendations.get(task_type, {}).get(budget, "gpt-4o-mini")
    
    def chat(self, messages: List[Dict[str, str]], model: str = "gpt-4o-mini",
             stream: bool = True, **kwargs) -> Generator[str, None, None]:
        """Send chat request to OpenAI API"""
        
        log.info(f"[OpenAI] Using model: {model}")
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not configured. Please add it to .env file.")
        
        # Validate model
        if model not in OPENAI_MODELS:
            log.warning(f"Model {model} not in known models, using anyway")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Serialize messages: convert ChatMessage objects or dataclasses to plain dicts
        serialized_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                serialized_messages.append(msg)
            elif hasattr(msg, '__dict__'):
                # dataclass or object — build role/content dict
                d = {"role": msg.role, "content": msg.content or ""}
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    d["tool_calls"] = msg.tool_calls
                if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
                    d["tool_call_id"] = msg.tool_call_id
                if hasattr(msg, 'name') and msg.name:
                    d["name"] = msg.name
                serialized_messages.append(d)
            else:
                serialized_messages.append(str(msg))

        payload = {
            "model": model,
            "messages": serialized_messages,
            "stream": stream,
            **kwargs
        }
        
        # Log tools if present
        if 'tools' in kwargs and kwargs['tools']:
            log.info(f"[OpenAI] Sending {len(kwargs['tools'])} tools to API")
        
        url = f"{self.base_url}/chat/completions"
        
        try:
            import requests
            
            if stream:
                response = requests.post(url, headers=headers, json=payload, 
                                        stream=True, timeout=120)
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        try:
                            line_text = line.decode('utf-8', errors='replace').strip()
                        except UnicodeDecodeError as e:
                            log.warning(f"[OpenAI] Unicode decode error: {e}")
                            line_text = line.decode('utf-8', errors='replace').strip()
                        
                        if line_text.startswith('data: '):
                            data_str = line_text[6:]
                            
                            if data_str.strip() == '[DONE]':
                                break
                            
                            try:
                                data = json.loads(data_str)
                                if 'choices' in data and len(data['choices']) > 0:
                                    delta = data['choices'][0].get('delta', {})
                                    content = delta.get('content', '')
                                    reasoning = delta.get('reasoning_content', '')
                                    tool_calls = delta.get('tool_calls', [])
                                    
                                    # Yield content if available
                                    if content:
                                        import re
                                        content = re.sub(r'[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]', '', content)
                                        if content:  # yield even whitespace/newlines for proper markdown
                                            yield content
                                    
                                    # Yield reasoning content
                                    elif reasoning:
                                        reasoning = re.sub(r'[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]', '', reasoning)
                                        if reasoning.strip():
                                            yield f"[THINK] {reasoning}"
                                    
                                    # Handle tool calls
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
                                    
                                    # Track tokens
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
            log.error(f"OpenAI API error: {e}")
            raise Exception(f"OpenAI API request failed: {str(e)}")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            raise
    
    def chat_stream(self, messages: List[Dict[str, str]], model: str = "gpt-4o-mini",
                    max_tokens: int = 2000, tools: List = None, 
                    retry_callback=None, **kwargs) -> Generator[str, None, None]:
        """Stream chat response with retry support"""
        yield from self.chat(
            messages, 
            model=model, 
            stream=True,
            max_tokens=max_tokens,
            tools=tools,
            **kwargs
        )
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics"""
        total_tokens = self._token_count["input"] + self._token_count["output"]
        
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "total_tokens": total_tokens,
            "estimated_cost": self._cost_tracking["total"]
        }
    
    def reset_usage(self):
        """Reset usage counters"""
        self._token_count = {"input": 0, "output": 0, "cached": 0}
        self._cost_tracking = {"input_cost": 0.0, "output_cost": 0.0, "total": 0.0}
    
    def validate_api_key(self) -> bool:
        """Validate the API key by making a simple request"""
        if not self.api_key:
            return False
        
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = requests.get(f"{self.base_url}/models", headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            log.error(f"API key validation failed: {e}")
            return False


# Singleton instance
_openai_provider = None


def get_openai_provider() -> OpenAIProvider:
    """Get singleton OpenAI provider instance"""
    global _openai_provider
    if _openai_provider is None:
        _openai_provider = OpenAIProvider()
    return _openai_provider
