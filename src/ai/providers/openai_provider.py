"""
OpenAI Provider for Cortex AI Agent IDE
Supports comprehensive programming/coding models including Codex, GPT-4o, o1, o3 series
with full agentic capabilities including tool calling, structured output, and retry mechanisms
"""

import os
import json
import time
import re
from typing import List, Dict, Any, Generator, Optional, Callable, Tuple
from dataclasses import dataclass
from requests.utils import parse_header_links
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


@dataclass
class OpenAIRateLimitState:
    """Observed rate-limit state returned by OpenAI response headers."""
    requests_limit: Optional[int] = None
    requests_remaining: Optional[int] = None
    requests_reset: Optional[str] = None
    tokens_limit: Optional[int] = None
    tokens_remaining: Optional[int] = None
    tokens_reset: Optional[str] = None
    retry_after_seconds: Optional[float] = None


# System prompt for OpenAI agentic capabilities
OPENAI_AGENT_SYSTEM_PROMPT = """You are an AI coding assistant with agentic capabilities. Follow these rules:

1. Use the available tools when needed to gather information or perform actions.
2. When using tools, follow the exact format specified.
3. For structured responses, use valid JSON format.
4. Be deterministic when possible - same input should produce same output.
5. When writing code, ensure it's complete and runnable.
6. Always consider the current project context and files when making decisions.

For tool calls, use the format:
__TOOL_CALL_DELTA__: with JSON containing tool call information.

For reasoning, use [THINK] prefix before your thought process."""

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
    OpenAI API Provider with comprehensive model support and full agentic capabilities
    
    Supports all OpenAI models including GPT-4o, o1, o3, and GPT-5 series with:
    - Advanced tool calling with validation and formatting
    - Structured JSON output enforcement
    - Automatic retry mechanism with exponential backoff
    - System prompt enforcement for agentic behavior
    - Dynamic tool name validation to prevent hallucinations
    - Cost tracking and usage statistics
    - Project context awareness for coding tasks
    
    Designed to work seamlessly with the Cortex AI Agent IDE for:
    - File operations (read/write/edit/delete)
    - Project navigation and analysis
    - Code generation and refactoring
    - Tool-based workflows
    - Multi-step reasoning and planning
    """
    
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = "https://api.openai.com/v1"
        self._token_count = {"input": 0, "output": 0, "cached": 0}
        self._cost_tracking = {"input_cost": 0.0, "output_cost": 0.0, "total": 0.0}
        self._max_retries = 5
        self._retry_delay = 1.0
        self._request_timeout = 300
        self._rate_limit_state = OpenAIRateLimitState()
        # Default tool names for validation
        self._allowed_tool_names = {
            "read_file", "write_file", "edit_file", "delete_file",
            "list_directory", "search_files", "execute_command",
            "run_python", "web_search", "web_fetch", "ask_user",
            "semantic_search", "git_status", "git_diff", "git_commit"
        }
        
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

    def get_model_info(self, model: str) -> OpenAIModel:
        """Return configured model metadata, defaulting to gpt-4o-mini."""
        return OPENAI_MODELS.get(model, OPENAI_MODELS["gpt-4o-mini"])

    def get_max_output_tokens(self, model: str, requested_max_tokens: Optional[int] = None) -> int:
        """Clamp requested output tokens to the configured model capability."""
        model_info = self.get_model_info(model)
        if requested_max_tokens is None or requested_max_tokens <= 0:
            return model_info.max_output
        return min(requested_max_tokens, model_info.max_output)

    def get_effective_context_window(self, model: str) -> int:
        """Return known effective context window for the selected model."""
        return self.get_model_info(model).context_window

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Expose the last observed OpenAI rate-limit header state."""
        return {
            "requests_limit": self._rate_limit_state.requests_limit,
            "requests_remaining": self._rate_limit_state.requests_remaining,
            "requests_reset": self._rate_limit_state.requests_reset,
            "tokens_limit": self._rate_limit_state.tokens_limit,
            "tokens_remaining": self._rate_limit_state.tokens_remaining,
            "tokens_reset": self._rate_limit_state.tokens_reset,
            "retry_after_seconds": self._rate_limit_state.retry_after_seconds,
        }

    def _normalize_max_tokens_kwargs(self, model: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize max token fields and cap them to the model's supported output."""
        normalized_kwargs = dict(kwargs)
        requested_max = normalized_kwargs.pop("max_completion_tokens", None)
        if requested_max is None:
            requested_max = normalized_kwargs.pop("max_output_tokens", None)
        if requested_max is None:
            requested_max = normalized_kwargs.get("max_tokens")

        effective_max = self.get_max_output_tokens(model, requested_max)
        normalized_kwargs["max_tokens"] = effective_max

        if requested_max and requested_max > effective_max:
            log.info(
                f"[OpenAI] Clamped requested max tokens from {requested_max} to {effective_max} for model {model}"
            )

        return normalized_kwargs

    def _safe_int(self, value: Optional[str]) -> Optional[int]:
        """Best-effort integer conversion for rate-limit headers."""
        if value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _safe_float(self, value: Optional[str]) -> Optional[float]:
        """Best-effort float conversion for Retry-After headers."""
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _update_rate_limit_state(self, headers: Dict[str, Any]):
        """Capture OpenAI rate-limit information from response headers."""
        if not headers:
            return

        self._rate_limit_state = OpenAIRateLimitState(
            requests_limit=self._safe_int(headers.get("x-ratelimit-limit-requests")),
            requests_remaining=self._safe_int(headers.get("x-ratelimit-remaining-requests")),
            requests_reset=headers.get("x-ratelimit-reset-requests"),
            tokens_limit=self._safe_int(headers.get("x-ratelimit-limit-tokens")),
            tokens_remaining=self._safe_int(headers.get("x-ratelimit-remaining-tokens")),
            tokens_reset=headers.get("x-ratelimit-reset-tokens"),
            retry_after_seconds=self._safe_float(headers.get("retry-after")),
        )

    def _get_retry_delay(self, attempt: int, error_type: str, error: Optional[Exception] = None) -> float:
        """Calculate retry delay using rate-limit headers when available."""
        if error_type == 'rate_limit':
            if self._rate_limit_state.retry_after_seconds:
                return max(self._rate_limit_state.retry_after_seconds, self._retry_delay)
            if error is not None:
                response = getattr(error, 'response', None)
                if response is not None:
                    retry_after = self._safe_float(response.headers.get("retry-after"))
                    if retry_after:
                        return max(retry_after, self._retry_delay)
            return min(2 ** (attempt + 2), 60)

        return self._retry_delay * (attempt + 1)
    
    def chat(self, messages: List[Dict[str, str]], model: str = "gpt-4o-mini",
             stream: bool = True, retry_callback=None, **kwargs) -> Generator[str, None, None]:
        """Send chat request to OpenAI API with retry support"""
        
        log.info(f"[OpenAI] Using model: {model}")
        
        # Only enforce system prompt when NO tools are provided
        # When tools are present, let OpenAI use tool_calls format
        if 'tools' not in kwargs or not kwargs['tools']:
            messages = self._enforce_system_prompt(messages)
        
        kwargs = self._normalize_max_tokens_kwargs(model, kwargs)

        # Set temperature: higher for tool calling, lower for text-only
        if "temperature" not in kwargs:
            kwargs["temperature"] = 0.7 if ('tools' in kwargs and kwargs['tools']) else 0.2
            
        # Use chat_with_retry for automatic retry support
        yield from self.chat_with_retry(
            messages, 
            model=model, 
            stream=stream,
            retry_callback=retry_callback,
            **kwargs
        )
    
    def chat_with_retry(self, messages: List[Dict[str, str]], model: str = "gpt-4o-mini",
                       stream: bool = True, max_retries: int = 3, 
                       validate_json: bool = False, retry_callback=None, **kwargs) -> Generator[str, None, None]:
        """Chat with retry logic and optional JSON validation.
        
        retry_callback(attempt, max_retries, error_type) is called just before
        each retry so the caller can show UI feedback.
        error_type is 'timeout', 'rate_limit', or 'error'.
        """
        # Only enforce system prompt when NO tools are provided
        # When tools are present, let OpenAI use tool_calls format
        if 'tools' not in kwargs or not kwargs['tools']:
            messages = self._enforce_system_prompt(messages)
        
        kwargs = self._normalize_max_tokens_kwargs(model, kwargs)

        # Set temperature: higher for tool calling, lower for text-only
        if "temperature" not in kwargs:
            kwargs["temperature"] = 0.7 if ('tools' in kwargs and kwargs['tools']) else 0.2

        last_error = None
        for attempt in range(max_retries):
            try:
                log.info(f"[OpenAI] Attempt {attempt + 1}/{max_retries} with model: {model}")
                
                result_chunks = []
                for chunk in self._chat_internal(messages, model, stream, **kwargs):
                    result_chunks.append(chunk)
                    yield chunk
                
                # Validate JSON if requested
                if validate_json and result_chunks:
                    full_response = "".join(result_chunks)
                    is_valid, parsed = self._validate_json_output(full_response)
                    if not is_valid:
                        log.warning(f"[OpenAI] Invalid JSON output, retrying...")
                        if attempt < max_retries - 1:
                            time.sleep(self._retry_delay * (attempt + 1))
                            continue
                
                return
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # Classify the error type for callback + logging
                if "timed out" in error_str or "timeout" in error_str or "read timed" in error_str:
                    error_type = 'timeout'
                elif "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                    error_type = 'rate_limit'
                else:
                    error_type = 'error'
                
                # SPECIAL HANDLING FOR 429 RATE LIMIT ERRORS
                if error_type == 'rate_limit':
                    log.warning(f"[OpenAI] Rate limited (attempt {attempt + 1}/{max_retries})")
                    backoff_seconds = self._get_retry_delay(attempt, error_type, e)
                    log.info(f"[OpenAI] Waiting {backoff_seconds}s before retry due to rate limit...")
                    
                    if attempt < max_retries - 1:
                        if retry_callback:
                            try:
                                retry_callback(attempt + 2, max_retries, 'rate_limit')
                            except Exception:
                                pass
                        time.sleep(backoff_seconds)
                        continue
                    else:
                        raise Exception(
                            f"OpenAI API rate limit exceeded. Please wait {backoff_seconds} seconds before trying again. "
                            f"Observed limits: {self.get_rate_limit_status()}"
                        )
                
                # Standard error handling (timeouts, network errors, etc.)
                log.error(f"[OpenAI] Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    if retry_callback:
                        try:
                            retry_callback(attempt + 2, max_retries, error_type)
                        except Exception:
                            pass
                    time.sleep(self._get_retry_delay(attempt, error_type, e))
                else:
                    raise last_error
    
    def _chat_internal(self, messages: List[Dict[str, str]], model: str = "gpt-4o-mini",
                      stream: bool = True, **kwargs) -> Generator[str, None, None]:
        """Internal chat method (actual API call)"""
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not configured. Please add it to .env file.")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        kwargs = self._normalize_max_tokens_kwargs(model, kwargs)
        
        # Format tools for OpenAI API
        formatted_tools = None
        if 'tools' in kwargs and kwargs['tools']:
            formatted_tools = self._format_tools_for_openai(kwargs['tools'])
            kwargs['tools'] = formatted_tools
        
        # Ensure messages are plain dicts (ChatMessage dataclass objects are not
        # JSON-serializable by requests.post(json=...)).  The wrapper in
        # providers/__init__.py already does this conversion, but we guard here
        # as a safety net for any direct callers.
        serializable_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                serializable_messages.append(msg)
            else:
                m = {
                    "role": getattr(msg, 'role', 'user'),
                    "content": getattr(msg, 'content', '') or ''
                }
                if getattr(msg, 'name', None):
                    m["name"] = msg.name
                if getattr(msg, 'tool_calls', None):
                    m["tool_calls"] = msg.tool_calls
                    if not msg.content:
                        m["content"] = None
                if getattr(msg, 'tool_call_id', None):
                    m["tool_call_id"] = msg.tool_call_id
                serializable_messages.append(m)
        messages = serializable_messages
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs
        }
        
        # Validate tools if present
        if 'tools' in kwargs and kwargs['tools']:
            log.info(f"[OpenAI] Sending {len(kwargs['tools'])} tools to API")
            
            # DYNAMICALLY POPULATE allowed tool names from registered tools
            self._allowed_tool_names = set()
            tool_names = []
            for tool in kwargs['tools']:
                tool_name = tool.get('function', {}).get('name', '')
                if tool_name:
                    self._allowed_tool_names.add(tool_name)
                    tool_names.append(tool_name)
                    if not self._validate_tool_name(tool_name):
                        log.warning(f"[OpenAI] Unusual tool name: {tool_name}")
            
            # Log all tool names in a single line
            log.debug(f"[OpenAI] Tools: {', '.join(tool_names)}")
        
        url = f"{self.base_url}/chat/completions"
        
        try:
            import requests
            
            if stream:
                response = requests.post(url, headers=headers, json=payload, 
                                        stream=True, timeout=self._request_timeout)
                self._update_rate_limit_state(response.headers)
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
                                    
                                    # Handle tool calls with validation
                                    if tool_calls:
                                        validated_tool_calls = []
                                        for tc in tool_calls:
                                            tool_name = tc.get('function', {}).get('name', '')
                                            
                                            # Validate tool name - WARN but don't reject
                                            if tool_name and not self._validate_tool_name(tool_name):
                                                log.warning(f"[OpenAI] Tool not in allowed list (may be valid): {tool_name}")
                                            
                                            tc_info = {
                                                'index': tc.get('index', 0),
                                                'id': tc.get('id', ''),
                                                'function': {
                                                    'name': tool_name,
                                                    'arguments': tc.get('function', {}).get('arguments', '')
                                                }
                                            }
                                            validated_tool_calls.append(tc_info)
                                        
                                        if validated_tool_calls:
                                            yield f"__TOOL_CALL_DELTA__:{json.dumps(validated_tool_calls)}"
                                    
                                    # Track tokens
                                    if 'usage' in data:
                                        self._token_count["input"] = data['usage'].get('prompt_tokens', 0)
                                        self._token_count["output"] = data['usage'].get('completion_tokens', 0)
                                        
                                        # Update cost tracking
                                        cost = self.calculate_cost(model, self._token_count["input"], self._token_count["output"])
                                        self._cost_tracking["input_cost"] = cost["input_cost"]
                                        self._cost_tracking["output_cost"] = cost["output_cost"]
                                        self._cost_tracking["total"] = cost["total_cost"]
                            
                            except json.JSONDecodeError as e:
                                log.error(f"Failed to parse SSE data: {e}")
                                continue
            else:
                response = requests.post(url, headers=headers, json=payload, timeout=self._request_timeout)
                self._update_rate_limit_state(response.headers)
                response.raise_for_status()
                
                result = response.json()
                
                # Track tokens
                if 'usage' in result:
                    self._token_count["input"] = result['usage'].get('prompt_tokens', 0)
                    self._token_count["output"] = result['usage'].get('completion_tokens', 0)
                    
                    # Update cost tracking
                    cost = self.calculate_cost(model, self._token_count["input"], self._token_count["output"])
                    self._cost_tracking["input_cost"] = cost["input_cost"]
                    self._cost_tracking["output_cost"] = cost["output_cost"]
                    self._cost_tracking["total"] = cost["total_cost"]
                
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
        effective_max_tokens = self.get_max_output_tokens(model, max_tokens)
        yield from self.chat_with_retry(
            messages, 
            model=model, 
            stream=True,
            max_retries=self._max_retries,
            retry_callback=retry_callback,
            tools=tools,
            max_tokens=effective_max_tokens,
            **kwargs
        )
    
    def chat_structured(self, messages: List[Dict[str, str]], model: str = "gpt-4o-mini",
                       output_schema: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Chat with guaranteed structured JSON output (for tool calls/planning)"""
        
        # Enforce JSON mode
        if output_schema:
            # Add schema to system prompt
            schema_prompt = f"\n\nYou MUST return ONLY valid JSON matching this schema:\n{json.dumps(output_schema, indent=2)}"
            messages = self._enforce_system_prompt(messages)
            messages[0]["content"] += schema_prompt
        
        kwargs = self._normalize_max_tokens_kwargs(model, kwargs)
        kwargs["temperature"] = 0.2  # Force deterministic
        
        for attempt in range(self._max_retries):
            try:
                result_chunks = []
                for chunk in self._chat_internal(messages, model, stream=False, **kwargs):
                    result_chunks.append(chunk)
                
                full_response = "".join(result_chunks)
                is_valid, parsed = self._validate_json_output(full_response)
                
                if is_valid:
                    return {"success": True, "data": parsed, "raw": full_response}
                else:
                    log.warning(f"[OpenAI] Invalid JSON on attempt {attempt + 1}")
                    if attempt < self._max_retries - 1:
                        time.sleep(self._retry_delay * (attempt + 1))
                        continue
                    else:
                        return {"success": False, "error": "Failed to get valid JSON", "raw": full_response}
                
            except Exception as e:
                log.error(f"[OpenAI] Structured chat error: {e}")
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                else:
                    return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Max retries exceeded"}
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics with cost breakdown"""
        total_tokens = self._token_count["input"] + self._token_count["output"]
        
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "cached_tokens": self._token_count.get("cached", 0),
            "total_tokens": total_tokens,
            "cost_breakdown": {
                "input_cost": self._cost_tracking["input_cost"],
                "output_cost": self._cost_tracking["output_cost"],
                "total_cost": self._cost_tracking["total"]
            },
            "estimated_cost": self._cost_tracking["total"],
            "model_limits": {
                "last_observed_rate_limits": self.get_rate_limit_status()
            }
        }
    
    def reset_usage(self):
        """Reset usage and cost counters"""
        self._token_count = {"input": 0, "output": 0, "cached": 0}
        self._cost_tracking = {"input_cost": 0.0, "output_cost": 0.0, "total": 0.0}
        # Reset allowed tool names to default
        self._allowed_tool_names = {
            "read_file", "write_file", "edit_file", "delete_file",
            "list_directory", "search_files", "execute_command",
            "run_python", "web_search", "web_fetch", "ask_user",
            "semantic_search", "git_status", "git_diff", "git_commit"
        }
        
    def update_allowed_tools(self, tool_names: List[str]):
        """Update the list of allowed tool names for validation"""
        self._allowed_tool_names.update(tool_names)
        log.info(f"[OpenAI] Updated allowed tools. Total: {len(self._allowed_tool_names)}")
    
    def _validate_tool_name(self, tool_name: str) -> bool:
        """Validate tool name to prevent hallucinations.
        
        Uses dynamically populated allowed_tool_names which is refreshed
        for each request based on the tools actually sent to the API.
        """
        if not tool_name or not isinstance(tool_name, str):
            return False
        # Check against dynamic set that's refreshed per request
        return tool_name in self._allowed_tool_names

    def _format_tools_for_openai(self, tools: List[Any]) -> List[Dict]:
        """Convert tool objects to OpenAI API format.
        
        OpenAI expects tools in format:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "what it does",
                "parameters": {...}
            }
        }
        """
        formatted = []
        
        for tool in tools:
            # Check if already formatted (has 'type' key)
            if isinstance(tool, dict) and 'type' in tool:
                formatted.append(tool)
                continue
            
            # Format objects with name and input_schema attributes
            if hasattr(tool, 'name') and hasattr(tool, 'input_schema'):
                try:
                    formatted_tool = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": getattr(tool, 'description', f"Tool: {tool.name}"),
                            "parameters": tool.input_schema() if callable(tool.input_schema) else tool.input_schema
                        }
                    }
                    formatted.append(formatted_tool)
                except Exception as e:
                    log.warning(f"Failed to format tool {getattr(tool, 'name', 'unknown')}: {e}")
                    continue
            elif isinstance(tool, dict):
                # Already a dictionary, ensure proper format
                if 'function' in tool:
                    formatted.append({
                        "type": tool.get("type", "function"),
                        "function": tool["function"]
                    })
        
        log.info(f"[OpenAI] Formatted {len(formatted)} tools for API (from {len(tools)} input tools)")
        return formatted

    def _enforce_system_prompt(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Insert Cortex agent system prompt only when no system message exists.
        
        NOTE: We never *replace* an existing system message because the bridge
        always injects its own comprehensive prompt (which includes tool usage
        rules, project context, memory etc.).  Overwriting it with the generic
        OPENAI_AGENT_SYSTEM_PROMPT would strip out all that context.
        """
        if not messages:
            return messages
        
        # Preserve any existing system message (bridge provides its own)
        if messages[0].get("role") == "system":
            return messages
        
        # No system message present — insert the default agent prompt
        return [{"role": "system", "content": OPENAI_AGENT_SYSTEM_PROMPT}] + list(messages)

    def _validate_json_output(self, content: str) -> Tuple[bool, Any]:
        """Validate JSON output format"""
        try:
            # Try to parse as JSON
            parsed = json.loads(content)
            return True, parsed
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if "```json" in content:
                try:
                    json_str = content.split("```json")[1].split("```")[0].strip()
                    parsed = json.loads(json_str)
                    return True, parsed
                except (IndexError, json.JSONDecodeError):
                    pass
            
            # Try to find JSON between curly braces
            try:
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1 and end > start:
                    json_str = content[start:end+1]
                    parsed = json.loads(json_str)
                    return True, parsed
            except json.JSONDecodeError:
                pass
            
            return False, None

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
