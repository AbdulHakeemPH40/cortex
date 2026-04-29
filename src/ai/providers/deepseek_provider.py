"""
DeepSeek Provider
Supports DeepSeek V4 models (V4-Pro, V4-Flash) with cost tracking and 1M context length

Models:
- deepseek-v4-pro: 1.6T total / 49B active params, world-class performance
- deepseek-v4-flash: 284B total / 13B active params, fast and cost-effective

Note: deepseek-chat and deepseek-reasoner will be retired after Jul 24th, 2026
"""

import os
import json
import re
from typing import List, Dict, Any, Generator, Optional
import requests
from src.utils.logger import get_logger
from src.ai.providers import BaseProvider, ProviderType, ChatMessage, ChatResponse, ModelInfo

log = get_logger("deepseek_provider")

# DeepSeek V4 model pricing per 1M tokens (USD)
# Updated: April 2026 - V4 models now available
DEEPSEEK_PRICING = {
    "deepseek-v4-pro": {"input": 0.50, "output": 2.00, "cache": 0.10},
    "deepseek-v4-flash": {"input": 0.10, "output": 0.50, "cache": 0.02},
    # Legacy models (will be retired Jul 24, 2026)
    "deepseek-chat": {"input": 0.27, "output": 0.27},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
}

# Performance multipliers (relative score)
DEEPSEEK_PERFORMANCE = {
    "deepseek-v4-pro": 1.5,
    "deepseek-v4-flash": 1.2,
    "deepseek-chat": 1.0,
    "deepseek-reasoner": 1.3,
}


class DeepSeekProvider(BaseProvider):
    """DeepSeek API Provider - Supports V4 models with 1M context length"""
    
    def __init__(self):
        # Initialize base class with DEEPSEEK provider type
        super().__init__(ProviderType.DEEPSEEK)
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self._base_url = "https://api.deepseek.com/v1"
        self._token_count = {"input": 0, "output": 0}
        
        if not self.api_key:
            log.warning("DEEPSEEK_API_KEY not configured")
    
    @property
    def available_models(self) -> List[ModelInfo]:
        """Return list of available DeepSeek models as ModelInfo objects."""
        models: List[ModelInfo] = []
        
        for model_id, pricing in DEEPSEEK_PRICING.items():
            # Calculate cost per 1k tokens (API expects per 1k, we store per 1M)
            input_cost_per_1k = pricing["input"] / 1000.0
            output_cost_per_1k = pricing["output"] / 1000.0
            
            models.append(ModelInfo(
                id=model_id,
                name=self._get_display_name(model_id),
                provider="deepseek",
                context_length=1_000_000,
                max_tokens=1_000_000,
                supports_streaming=True,
                supports_vision=False,
                cost_per_1k_input=input_cost_per_1k,
                cost_per_1k_output=output_cost_per_1k
            ))
        
        return models
    
    def validate_api_key(self) -> bool:
        """Validate the current DeepSeek API key."""
        if not self.api_key:
            return False
        
        # Simple validation - check if key looks valid
        return len(self.api_key) > 10
    
    def set_api_key(self, api_key: str):
        """Set the DeepSeek API key."""
        self.api_key = api_key
        super().set_api_key(api_key)
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available DeepSeek models"""
        models: List[Dict[str, Any]] = []
        
        for model_id, pricing in DEEPSEEK_PRICING.items():
            perf = DEEPSEEK_PERFORMANCE.get(model_id, 1.0)
            
            models.append({
                "id": model_id,
                "name": self._get_display_name(model_id),
                "pricing": pricing,
                "performance": perf,
                "category": self._get_category(model_id),
                "context_length": 1_000_000,  # All V4 models support 1M context
                "deprecated": model_id in ["deepseek-chat", "deepseek-reasoner"]
            })
        
        return models
    
    def _get_display_name(self, model_id: str) -> str:
        """Get user-friendly display name for model"""
        display_names = {
            "deepseek-v4-pro": "DeepSeek V4 Pro",
            "deepseek-v4-flash": "DeepSeek V4 Flash",
            "deepseek-chat": "DeepSeek Chat V3 (Legacy)",
            "deepseek-reasoner": "DeepSeek Reasoner R1 (Legacy)"
        }
        return display_names.get(model_id, model_id.replace("-", " ").title())
    
    def _get_category(self, model_id: str) -> str:
        """Get model category"""
        if "pro" in model_id:
            return "High Performance"
        elif "flash" in model_id:
            return "Fast & Efficient"
        elif "reasoner" in model_id:
            return "Reasoning"
        else:
            return "General (Legacy)"
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int, 
                       cache_tokens: int = 0) -> Dict[str, Any]:
        """Calculate cost for token usage"""
        pricing = DEEPSEEK_PRICING.get(model, DEEPSEEK_PRICING["deepseek-v4-flash"])
        
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        cache_cost = (cache_tokens / 1_000_000) * pricing.get("cache", 0.0)
        total_cost = input_cost + output_cost + cache_cost
        
        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "cache_cost": cache_cost,
            "total_cost": total_cost,
            "currency": "USD"
        }

    def _sanitize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize messages for strict OpenAI-compatible DeepSeek payload parsing."""
        normalized: List[Dict[str, Any]] = []
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue

            role = str(msg.get("role", "")).strip()
            if not role:
                continue

            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")
            tool_call_id = msg.get("tool_call_id")
            reasoning_content = msg.get("reasoning_content")
            name = msg.get("name")

            if isinstance(content, list):
                parts: List[str] = []
                for block in content:
                    if isinstance(block, dict):
                        text_val = block.get("text", "")
                        parts.append(text_val if isinstance(text_val, str) else str(text_val))
                    else:
                        parts.append(str(block))
                content = "".join(parts)
            elif content is None:
                # For compatibility, avoid null content in strict parsers.
                content = ""
            elif not isinstance(content, str):
                content = str(content)

            out: Dict[str, Any] = {"role": role, "content": content}
            if name:
                out["name"] = name
            if tool_calls:
                out["tool_calls"] = tool_calls
            if tool_call_id:
                out["tool_call_id"] = tool_call_id
            if isinstance(reasoning_content, str) and reasoning_content:
                out["reasoning_content"] = reasoning_content
            normalized.append(out)

        return normalized

    def _sanitize_tools(self, tools: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
        """Convert tool schema into strict OpenAI tool shape and drop invalid entries."""
        if not tools:
            return None

        sanitized: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue

            fn = tool.get("function", {})
            if not isinstance(fn, dict):
                continue

            name = fn.get("name")
            if not name:
                continue

            params = fn.get("parameters")
            if not isinstance(params, dict):
                params = {}
            if params.get("type") != "object":
                params["type"] = "object"
            if "properties" not in params or not isinstance(params["properties"], dict):
                params["properties"] = {}

            sanitized.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(name),
                        "description": str(fn.get("description", "")),
                        "parameters": params,
                    },
                }
            )

        return sanitized or None
    
    def _chat_raw(self, messages: List[Dict[str, str]], model: str = "deepseek-v4-flash",
                  stream: bool = True, **kwargs: Any) -> Generator[str, None, None]:
        """Low-level chat request to DeepSeek API (internal use).
        
        Args:
            messages: List of message dicts
            model: Model ID (deepseek-v4-pro, deepseek-v4-flash)
            stream: Enable streaming
            **kwargs: Additional params (tools, temperature, etc.)
        """
        
        # Warn if using deprecated model
        if model in ["deepseek-chat", "deepseek-reasoner"]:
            warning_msg = (
                f"[DeepSeek] Model '{model}' is deprecated and will be retired on Jul 24, 2026. "
                f"Please migrate to deepseek-v4-pro or deepseek-v4-flash."
            )
            log.warning(warning_msg)
        
        # Log which model is being used
        log.info(f"[DeepSeek] Using model: {model}")
        
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not configured. Please add it to .env file.")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Filter out non-API and empty optional parameters before payload build.
        api_params = {
            k: v for k, v in kwargs.items()
            if k not in ("retry_callback", "max_retries", "retry_notify")
        }
        sanitized_messages = self._sanitize_messages(messages)
        sanitized_tools = self._sanitize_tools(api_params.get("tools"))
        tool_choice = api_params.get("tool_choice")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": sanitized_messages,
            "stream": stream,
        }

        for k, v in api_params.items():
            if k in ("tools", "tool_choice"):
                continue
            if v is None:
                continue
            payload[k] = v

        if sanitized_tools:
            payload["tools"] = sanitized_tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        
        # DEBUG: Log if tools are present
        if 'tools' in kwargs and kwargs['tools']:
            log.info(f"[DEEPSEEK DEBUG] Sending {len(kwargs['tools'])} tools to API")
            tool_names = [t.get('function', {}).get('name', '?') for t in kwargs['tools']]  
            log.debug(f"[DEEPSEEK DEBUG] Tools: {', '.join(tool_names)}")
        else:
            log.debug("[DEEPSEEK DEBUG] No tools in request")
        
        url = f"{self._base_url}/chat/completions"
        
        try:
            if stream:
                response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
                if not response.ok:
                    try:
                        log.error("[DeepSeek] API error response: %s", json.dumps(response.json(), indent=2))
                    except Exception:
                        log.error("[DeepSeek] API error response (text): %s", response.text[:1000])
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        try:
                            line_text = line.decode('utf-8', errors='replace').strip()
                        except UnicodeDecodeError as e:
                            log.warning(f"[DeepSeek] Unicode decode error: {e}")
                            line_text = line.decode('utf-8', errors='replace').strip()
                        
                        if line_text.startswith('data: '):
                            data_str = line_text[6:]
                            
                            if data_str.strip() == '[DONE]':
                                break
                            
                            try:
                                data = json.loads(data_str)
                                if 'choices' in data and len(data['choices']) > 0:
                                    delta = data['choices'][0].get('delta', {})
                                    # Handle content, reasoning_content (V4 models), and tool_calls
                                    content = delta.get('content', '')
                                    reasoning = delta.get('reasoning_content', '')
                                    tool_calls = delta.get('tool_calls', [])
                                    
                                    # Yield content if available
                                    if content:
                                        # Filter out corrupted/non-printable characters
                                        # Remove replacement chars and control chars, BUT preserve \n (0x0a) and \t (0x09)
                                        content = re.sub(r'[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]', '', content)
                                        # Preserve whitespace-only chunks to avoid breaking token spacing.
                                        if content:
                                            yield content
                                    # Consume reasoning chunks internally so they are not rendered as
                                    # visible "[THINK]" text in the main assistant output stream.
                                    elif reasoning:
                                        # Also sanitize reasoning content for safety/debug visibility.
                                        reasoning = re.sub(r'[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]', '', reasoning)
                                        if reasoning:
                                            log.debug("[DeepSeek] Received reasoning_content chunk (%d chars)", len(reasoning))
                                            yield f"__REASONING_DELTA__:{reasoning}"
                                    
                                    # Handle tool calls
                                    if tool_calls:
                                        tool_call_data: List[Dict[str, Any]] = []
                                        for tc in tool_calls:
                                            tc_info: Dict[str, Any] = {
                                                'index': tc.get('index', 0),
                                                'id': tc.get('id', ''),
                                                'function': {
                                                    'name': tc.get('function', {}).get('name', ''),
                                                    'arguments': tc.get('function', {}).get('arguments', '')
                                               }
                                            }
                                            tool_call_data.append(tc_info)
                                        yield f"__TOOL_CALL_DELTA__:{json.dumps(tool_call_data)}"
                                    
                                    # Track tokens if available
                                    if 'usage' in data:
                                        self._token_count["input"] = data['usage'].get('prompt_tokens', 0)
                                        self._token_count["output"] = data['usage'].get('completion_tokens', 0)
                                        
                            except json.JSONDecodeError as e:
                                log.error(f"Failed to parse SSE data: {e}")
                                continue
                                
            else:
                response = requests.post(url, headers=headers, json=payload, timeout=120)
                if not response.ok:
                    try:
                        log.error("[DeepSeek] API error response: %s", json.dumps(response.json(), indent=2))
                    except Exception:
                        log.error("[DeepSeek] API error response (text): %s", response.text[:1000])
                response.raise_for_status()
                
                result = response.json()
                
                # Track tokens
                if 'usage' in result:
                    self._token_count["input"] = result['usage'].get('prompt_tokens', 0)
                    self._token_count["output"] = result['usage'].get('completion_tokens', 0)
                
                content = result['choices'][0]['message']['content']
                yield content
                
        except requests.exceptions.RequestException as e:
            detail = ""
            try:
                if e.response is not None:
                    detail = (e.response.text or "")[:1000]
            except Exception:
                detail = ""
            log.error(f"DeepSeek API error: {e}")
            if detail:
                raise Exception(f"DeepSeek API request failed: {str(e)} | response: {detail}")
            raise Exception(f"DeepSeek API request failed: {str(e)}")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            raise
    
    def chat(self, 
             messages: List[ChatMessage], 
             model: str = "deepseek-v4-flash",
             temperature: float = 0.7,
             max_tokens: int = 2000,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None,
             **kwargs: Any) -> ChatResponse:
        """Send chat request to DeepSeek API and return ChatResponse.
        
        This implements the BaseProvider abstract method.
        """
        import time
        start_time = time.time()
        
        # Convert ChatMessage objects to dict format
        message_dicts = self._format_messages_for_provider(messages)
        
        # Build kwargs for tools
        chat_kwargs: Dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if tools:
            chat_kwargs["tools"] = tools
        if tool_choice:
            chat_kwargs["tool_choice"] = tool_choice
        chat_kwargs.update(kwargs)
        
        try:
            # Use the streaming chat internally and collect results
            content_parts: List[str] = []
            tool_calls: Optional[List[Dict[str, Any]]] = None
            
            for chunk in self._chat_raw(
                message_dicts,  
                model=model,
                stream=True,
                **chat_kwargs
            ):
                if chunk.startswith("__TOOL_CALL_DELTA__:"):
                    # Parse tool call data
                    tool_calls = json.loads(chunk.replace("__TOOL_CALL_DELTA__:", ""))
                elif chunk.startswith("__REASONING_DELTA__:"):
                    # Internal metadata for follow-up turns; don't mix into visible answer text.
                    continue
                else:
                    content_parts.append(chunk)
            
            duration_ms = (time.time() - start_time) * 1000
            
            return ChatResponse(
                content="".join(content_parts),
                model=model,
                provider="deepseek",
                input_tokens=self._token_count["input"],
                output_tokens=self._token_count["output"],
                finish_reason="stop",
                duration_ms=duration_ms,
                tool_calls=tool_calls
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self._last_error = str(e)
            return ChatResponse(
                content="",
                model=model,
                provider="deepseek",
                input_tokens=0,
                output_tokens=0,
                finish_reason="error",
                duration_ms=duration_ms,
                error=str(e)
            )
    
    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str = "deepseek-v4-flash",
                   temperature: float = 0.7,
                   max_tokens: int = 2000,
                   tools: Optional[List[Dict[str, Any]]] = None,
                   **kwargs: Any) -> Generator[str, None, None]:
        """Stream chat completion response.
        
        This overrides BaseProvider.chat_stream for DeepSeek-specific streaming.
        """
        # Convert ChatMessage objects to dict format
        message_dicts = self._format_messages_for_provider(messages)
        
        # Call the raw chat method with streaming
        yield from self._chat_raw(
            message_dicts,
            model=model,
            stream=True,
            temperature=temperature,
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
