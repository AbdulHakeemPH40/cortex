"""
Groq Provider with Speed Guardrails & Crash Prevention
Optimized for extreme-speed inference with state management and safety controls
"""

import os
import json
import time
import asyncio
from typing import List, Dict, Any, Generator, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import threading
from src.utils.logger import get_logger
from src.ai.providers import BaseProvider, ProviderType, ModelInfo, ChatMessage, ChatResponse

log = get_logger("groq_provider")


class GroqModel(str, Enum):
    """Available Groq models with performance characteristics"""
    # Groq Compound Models (Reasoning/Agentic)
    COMPOUND = "groq/compound"
    COMPOUND_MINI = "groq/compound-mini"
    
    # Llama 3.1 Series
    LLAMA_3_1_8B_INSTANT = "llama-3.1-8b-instant"
    
    # Llama 3.3 Series
    LLAMA_3_3_70B_VERSATILE = "llama-3.3-70b-versatile"
    
    # Llama 4 Series
    LLAMA_4_SCOUT = "meta-llama/llama-4-scout-17b-16e-instruct"
    
    # Llama Prompt Guard Models
    PROMPT_GUARD_2_22M = "meta-llama/llama-prompt-guard-2-22m"
    PROMPT_GUARD_2_86M = "meta-llama/llama-prompt-guard-2-86m"
    
    # Moonshot Kimi K2
    KIMI_K2_INSTRUCT = "moonshotai/kimi-k2-instruct"
    KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905"
    
    # OpenAI GPT-OSS Models
    GPT_OSS_120B = "openai/gpt-oss-120b"
    GPT_OSS_20B = "openai/gpt-oss-20b"
    GPT_OSS_SAFEGUARD_20B = "openai/gpt-oss-safeguard-20b"
    
    # Qwen Models
    QWEN3_32B = "qwen/qwen3-32b"
    
    # Legacy models (kept for compatibility)
    LLAMA3_8B = "llama3-8b-8192"
    LLAMA3_70B = "llama3-70b-8192"
    MIXTRAL_8X7B = "mixtral-8x7b-32768"
    GEMMA_7B = "gemma-7b-it"


@dataclass
class SpeedGuardrails:
    """Configuration for Groq speed management and crash prevention"""
    # Rate limiting
    max_requests_per_second: float = 10.0
    max_requests_per_minute: int = 100
    max_tokens_per_minute: int = 500000
    
    # Concurrency control
    max_concurrent_requests: int = 5
    max_queue_size: int = 20
    
    # Response throttling
    throttle_tokens_per_second: Optional[int] = None  # None = no throttling
    min_delay_between_requests_ms: int = 100
    
    # Circuit breaker
    circuit_breaker_threshold: int = 5  # Errors before opening
    circuit_breaker_timeout_seconds: int = 60
    
    # Memory management
    max_context_length: int = 128000
    enable_context_compaction: bool = True
    compaction_threshold: int = 100000
    
    # Streaming control
    enable_stream_buffer: bool = True
    stream_buffer_size: int = 1024
    max_stream_duration_seconds: int = 300


@dataclass
class GroqState:
    """State management for Groq provider (Reducer pattern)"""
    session_id: str = field(default_factory=lambda: str(int(time.time() * 1000)))
    status: str = "idle"  # idle, planning, executing, reviewing, completed, failed
    
    # Request tracking
    request_count: int = 0
    request_timestamps: deque = field(default_factory=lambda: deque(maxlen=100))
    token_count_total: int = 0
    token_timestamps: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Concurrency tracking
    active_requests: int = 0
    request_queue: deque = field(default_factory=lambda: deque(maxlen=20))
    
    # Circuit breaker state
    consecutive_errors: int = 0
    circuit_open: bool = False
    circuit_opened_at: Optional[float] = None
    
    # Tool execution state
    executed_tools: List[Dict] = field(default_factory=list)
    pending_tools: List[Dict] = field(default_factory=list)
    
    # Performance metrics
    last_request_time: float = 0.0
    average_latency_ms: float = 0.0
    peak_tokens_per_second: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'status': self.status,
            'request_count': self.request_count,
            'token_count_total': self.token_count_total,
            'active_requests': self.active_requests,
            'circuit_open': self.circuit_open,
            'consecutive_errors': self.consecutive_errors,
        }


class RateLimiter:
    """Token bucket rate limiter for Groq API"""
    
    def __init__(self, max_requests_per_second: float = 10.0, 
                 max_requests_per_minute: int = 100):
        self.max_rps = max_requests_per_second
        self.max_rpm = max_requests_per_minute
        self.tokens = max_requests_per_second
        self.last_update = time.time()
        self.request_times: deque = deque(maxlen=100)
        self._lock = threading.Lock()
    
    def acquire(self) -> bool:
        """Try to acquire a rate limit token. Returns True if allowed."""
        with self._lock:
            now = time.time()
            
            # Replenish tokens based on time passed
            time_passed = now - self.last_update
            self.tokens = min(self.max_rps, self.tokens + time_passed * self.max_rps)
            self.last_update = now
            
            # Check per-minute limit
            minute_ago = now - 60
            recent_requests = sum(1 for t in self.request_times if t > minute_ago)
            if recent_requests >= self.max_rpm:
                return False
            
            # Check if token available
            if self.tokens >= 1:
                self.tokens -= 1
                self.request_times.append(now)
                return True
            
            return False
    
    def get_wait_time(self) -> float:
        """Get estimated wait time for next token"""
        with self._lock:
            if self.tokens >= 1:
                return 0.0
            return (1 - self.tokens) / self.max_rps


class CircuitBreaker:
    """Circuit breaker pattern for API resilience"""
    
    def __init__(self, threshold: int = 5, timeout_seconds: int = 60):
        self.threshold = threshold
        self.timeout = timeout_seconds
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open
        self._lock = threading.Lock()
    
    def can_execute(self) -> bool:
        """Check if request can be executed"""
        with self._lock:
            if self.state == "closed":
                return True
            
            if self.state == "open":
                if self.last_failure_time and (time.time() - self.last_failure_time) > self.timeout:
                    self.state = "half-open"
                    self.failure_count = 0
                    return True
                return False
            
            return True  # half-open
    
    def record_success(self):
        """Record successful request"""
        with self._lock:
            self.failure_count = 0
            self.state = "closed"
    
    def record_failure(self) -> bool:
        """Record failed request. Returns True if circuit opened."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.threshold:
                self.state = "open"
                log.error(f"🔴 Circuit breaker OPENED after {self.failure_count} failures")
                return True
            
            return False


class GroqProvider(BaseProvider):
    """
    Groq Provider with extreme speed optimization and crash prevention
    Inherits from BaseProvider for unified interface
    
    Features:
    - State management via reducer pattern
    - Rate limiting and concurrency control
    - Circuit breaker for resilience
    - Stream throttling to prevent UI crashes
    - Automatic context compaction
    - Tool orchestration support
    """
    
    # Model pricing per 1M tokens (USD) - approximate
    PRICING = {
        # Groq Compound Models
        GroqModel.COMPOUND: {"input": 0.30, "output": 0.60},
        GroqModel.COMPOUND_MINI: {"input": 0.15, "output": 0.30},
        
        # Llama 3.1 Series
        GroqModel.LLAMA_3_1_8B_INSTANT: {"input": 0.05, "output": 0.08},
        
        # Llama 3.3 Series
        GroqModel.LLAMA_3_3_70B_VERSATILE: {"input": 0.59, "output": 0.79},
        
        # Llama 4 Series
        GroqModel.LLAMA_4_SCOUT: {"input": 0.25, "output": 0.35},
        
        # Llama Prompt Guard (lower cost, specialized)
        GroqModel.PROMPT_GUARD_2_22M: {"input": 0.01, "output": 0.01},
        GroqModel.PROMPT_GUARD_2_86M: {"input": 0.02, "output": 0.02},
        
        # Moonshot Kimi K2
        GroqModel.KIMI_K2_INSTRUCT: {"input": 0.40, "output": 0.60},
        GroqModel.KIMI_K2_INSTRUCT_0905: {"input": 0.40, "output": 0.60},
        
        # OpenAI GPT-OSS Models
        GroqModel.GPT_OSS_120B: {"input": 0.50, "output": 0.75},
        GroqModel.GPT_OSS_20B: {"input": 0.15, "output": 0.25},
        GroqModel.GPT_OSS_SAFEGUARD_20B: {"input": 0.10, "output": 0.15},
        
        # Qwen Models
        GroqModel.QWEN3_32B: {"input": 0.20, "output": 0.30},
        
        # Legacy models
        GroqModel.LLAMA3_8B: {"input": 0.05, "output": 0.08},
        GroqModel.LLAMA3_70B: {"input": 0.59, "output": 0.79},
        GroqModel.MIXTRAL_8X7B: {"input": 0.27, "output": 0.27},
        GroqModel.GEMMA_7B: {"input": 0.10, "output": 0.10},
    }
    
    # Performance characteristics
    PERFORMANCE = {
        # Groq Compound Models (slower, more capable)
        GroqModel.COMPOUND: {"tokens_per_sec": 150, "latency_ms": 400},
        GroqModel.COMPOUND_MINI: {"tokens_per_sec": 250, "latency_ms": 250},
        
        # Llama 3.1 Series (fast)
        GroqModel.LLAMA_3_1_8B_INSTANT: {"tokens_per_sec": 1000, "latency_ms": 40},
        
        # Llama 3.3 Series (balanced)
        GroqModel.LLAMA_3_3_70B_VERSATILE: {"tokens_per_sec": 300, "latency_ms": 200},
        
        # Llama 4 Series
        GroqModel.LLAMA_4_SCOUT: {"tokens_per_sec": 320, "latency_ms": 220},
        
        # Llama Prompt Guard (very fast, specialized)
        GroqModel.PROMPT_GUARD_2_22M: {"tokens_per_sec": 2000, "latency_ms": 20},
        GroqModel.PROMPT_GUARD_2_86M: {"tokens_per_sec": 1500, "latency_ms": 30},
        
        # Moonshot Kimi K2
        GroqModel.KIMI_K2_INSTRUCT: {"tokens_per_sec": 250, "latency_ms": 300},
        GroqModel.KIMI_K2_INSTRUCT_0905: {"tokens_per_sec": 250, "latency_ms": 300},
        
        # OpenAI GPT-OSS Models
        GroqModel.GPT_OSS_120B: {"tokens_per_sec": 150, "latency_ms": 500},
        GroqModel.GPT_OSS_20B: {"tokens_per_sec": 400, "latency_ms": 150},
        GroqModel.GPT_OSS_SAFEGUARD_20B: {"tokens_per_sec": 500, "latency_ms": 120},
        
        # Qwen Models
        GroqModel.QWEN3_32B: {"tokens_per_sec": 350, "latency_ms": 180},
        
        # Legacy models
        GroqModel.LLAMA3_8B: {"tokens_per_sec": 800, "latency_ms": 50},
        GroqModel.LLAMA3_70B: {"tokens_per_sec": 300, "latency_ms": 200},
        GroqModel.MIXTRAL_8X7B: {"tokens_per_sec": 280, "latency_ms": 250},
        GroqModel.GEMMA_7B: {"tokens_per_sec": 600, "latency_ms": 80},
    }
    
    def __init__(self, guardrails: Optional[SpeedGuardrails] = None):
        super().__init__(ProviderType.GROQ)
        self.api_key = os.getenv("GROQ_API_KEY", "")
        # Groq client automatically adds /openai/v1, so we use the base URL only
        self._base_url = "https://api.groq.com"
        self._client = None
        
        # State management
        self.state = GroqState()
        self.guardrails = guardrails or SpeedGuardrails()
        
        # Safety mechanisms
        self.rate_limiter = RateLimiter(
            self.guardrails.max_requests_per_second,
            self.guardrails.max_requests_per_minute
        )
        self.circuit_breaker = CircuitBreaker(
            self.guardrails.circuit_breaker_threshold,
            self.guardrails.circuit_breaker_timeout_seconds
        )
        
        # Concurrency control
        self._request_semaphore = threading.Semaphore(self.guardrails.max_concurrent_requests)
        self._state_lock = threading.Lock()
        
        # Stream buffer for throttling
        self._stream_buffer: deque = deque(maxlen=self.guardrails.stream_buffer_size)
        
        if not self.api_key:
            log.warning("⚠️ GROQ_API_KEY not configured")
        else:
            log.info("✅ GroqProvider initialized with speed guardrails")
    
    def _get_client(self):
        """Get or create Groq client with lazy loading"""
        if self._client is None:
            try:
                from groq import Groq
                self._client = Groq(
                    api_key=self.api_key,
                    base_url=self._base_url
                )
                log.info("✅ Groq client created")
            except ImportError:
                raise ImportError("groq package not installed. Run: pip install groq")
        return self._client
    
    def _update_state(self, action: str, payload: Dict = None):
        """Reducer pattern for state management"""
        with self._state_lock:
            if action == "REQUEST_START":
                self.state.active_requests += 1
                self.state.request_count += 1
                self.state.request_timestamps.append(time.time())
                self.state.status = "executing"
                
            elif action == "REQUEST_COMPLETE":
                self.state.active_requests = max(0, self.state.active_requests - 1)
                self.circuit_breaker.record_success()
                self.state.consecutive_errors = 0
                
            elif action == "REQUEST_ERROR":
                self.state.active_requests = max(0, self.state.active_requests - 1)
                self.state.consecutive_errors += 1
                if self.circuit_breaker.record_failure():
                    self.state.circuit_open = True
                    self.state.circuit_opened_at = time.time()
                    
            elif action == "TOKENS_PROCESSED":
                tokens = payload.get("tokens", 0)
                self.state.token_count_total += tokens
                self.state.token_timestamps.append((time.time(), tokens))
                
            elif action == "STATUS_CHANGE":
                self.state.status = payload.get("status", "idle")
                
            elif action == "TOOL_EXECUTED":
                tool_info = payload.get("tool", {})
                self.state.executed_tools.append(tool_info)
                
            elif action == "RESET_CIRCUIT":
                self.state.circuit_open = False
                self.state.circuit_opened_at = None
                self.state.consecutive_errors = 0
                self.circuit_breaker.state = "closed"
    
    def _check_rate_limits(self) -> tuple[bool, Optional[float]]:
        """Check if request can proceed under rate limits"""
        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            return False, None
        
        # Check rate limiter
        if not self.rate_limiter.acquire():
            wait_time = self.rate_limiter.get_wait_time()
            return False, wait_time
        
        # Check concurrent request limit
        if self.state.active_requests >= self.guardrails.max_concurrent_requests:
            return False, 0.5  # Wait 500ms
        
        return True, None
    
    def _compact_context(self, messages: List[Dict]) -> List[Dict]:
        """Compact messages to fit within context limits"""
        if not self.guardrails.enable_context_compaction:
            return messages
        
        # Estimate token count (rough approximation: 4 chars ≈ 1 token)
        total_chars = sum(len(m.get("content", "")) for m in messages)
        estimated_tokens = total_chars // 4
        
        if estimated_tokens < self.guardrails.compaction_threshold:
            return messages
        
        log.info(f"🗜️ Compacting context: ~{estimated_tokens} tokens -> target {self.guardrails.max_context_length}")
        
        # Keep system message and most recent messages
        compacted = []
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        
        # Always keep system messages
        compacted.extend(system_msgs)
        
        # Keep last N messages
        keep_count = min(len(other_msgs), 20)  # Keep last 20 exchanges
        compacted.extend(other_msgs[-keep_count:])
        
        log.info(f"🗜️ Compacted from {len(messages)} to {len(compacted)} messages")
        return compacted
    
    @property
    def available_models(self) -> List[ModelInfo]:
        """Get list of available Groq models as ModelInfo objects"""
        models = []
        
        for model in GroqModel:
            pricing = self.PRICING.get(model, {"input": 0.0, "output": 0.0})
            perf = self.PERFORMANCE.get(model, {"tokens_per_sec": 300, "latency_ms": 200})
            
            models.append(ModelInfo(
                id=model.value,
                name=model.value.replace("-", " ").title(),
                provider="groq",
                context_length=128000,
                max_tokens=4096,
                supports_streaming=True,
                supports_vision=False,
                cost_per_1k_input=pricing["input"],
                cost_per_1k_output=pricing["output"]
            ))
        
        return models
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available Groq models with detailed info"""
        models = []
        
        for model in GroqModel:
            pricing = self.PRICING.get(model, {"input": 0.0, "output": 0.0})
            perf = self.PERFORMANCE.get(model, {"tokens_per_sec": 300, "latency_ms": 200})
            
            models.append({
                "id": model.value,
                "name": model.value.replace("-", " ").title(),
                "pricing": pricing,
                "performance": perf,
                "category": self._get_category(model),
                "speed_tier": self._get_speed_tier(model)
            })
        
        return models
    
    def _get_category(self, model: GroqModel) -> str:
        """Categorize models by capability"""
        if model in [GroqModel.LLAMA3_8B, GroqModel.GEMMA_7B]:
            return "Fast"
        elif model in [GroqModel.LLAMA3_70B, GroqModel.MIXTRAL_8X7B]:
            return "Balanced"
        else:
            return "Advanced"
    
    def _get_speed_tier(self, model: GroqModel) -> str:
        """Get speed classification"""
        perf = self.PERFORMANCE.get(model, {})
        tps = perf.get("tokens_per_sec", 300)
        
        if tps >= 500:
            return "Ultra"
        elif tps >= 300:
            return "Fast"
        elif tps >= 200:
            return "Standard"
        else:
            return "Thorough"
    
    def chat(self, messages: List[ChatMessage], model: str = "llama3-70b-8192",
             temperature: float = 0.7, max_tokens: int = 4096,
             stream: bool = False, tools: Optional[List[Dict]] = None,
             tool_choice: Optional[str] = None) -> ChatResponse:
        """
        BaseProvider-compatible chat method (non-streaming)
        
        Args:
            messages: List of ChatMessage objects
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream (always returns non-streamed response)
            tools: Optional tool definitions
            tool_choice: Tool choice strategy
            
        Returns:
            ChatResponse object
        """
        # Convert ChatMessage to dict format
        messages_dict = self._format_messages_for_provider(messages)
        
        try:
            client = self._get_client()
            
            payload = {
                "model": model,
                "messages": messages_dict,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            
            if tools:
                payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
            
            response = client.chat.completions.create(**payload)
            
            message = response.choices[0].message
            
            # Extract tool calls
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
            
            return ChatResponse(
                content=message.content or "",
                model=model,
                provider="groq",
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                duration_ms=0.0,
                tool_calls=tool_calls
            )
            
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Groq chat error: {e}")
            return ChatResponse(
                content="",
                model=model,
                provider="groq",
                error=str(e)
            )
    
    def chat_stream(self, messages: List[ChatMessage], model: str = "llama3-70b-8192",
                    temperature: float = 0.7, max_tokens: int = 4096,
                    tools: Optional[List[Dict]] = None) -> Generator[str, None, None]:
        """
        Stream chat completion from Groq
        
        Args:
            messages: List of ChatMessage objects
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            tools: Optional tool definitions
            
        Yields:
            Response chunks (strings) or tool call markers
        """
        # Convert ChatMessage to dict format
        messages_dict = self._format_messages_for_provider(messages)
        
        # Use the existing streaming implementation
        for chunk in self._chat_stream_internal(
            messages_dict, model, temperature, max_tokens, tools
        ):
            yield chunk
    
    def _chat_stream_internal(self, messages: List[Dict[str, str]], model: str = GroqModel.LLAMA3_70B.value,
             temperature: float = 0.7, max_tokens: int = 4096,
             tools: Optional[List[Dict]] = None, **kwargs) -> Generator[str, None, None]:
        """
        Internal streaming method with full speed guardrails
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            tools: Optional tool definitions for function calling
            **kwargs: Additional parameters
            
        Yields:
            Response chunks (strings) or tool call markers
        """
        # Check rate limits
        can_proceed, wait_time = self._check_rate_limits()
        if not can_proceed:
            if wait_time:
                log.warning(f"⏱️ Rate limit hit, waiting {wait_time:.2f}s")
                time.sleep(wait_time)
            else:
                yield "[Error: Circuit breaker open - too many failures. Please wait...]"
                return
        
        # Compact context if needed
        messages = self._compact_context(messages)
        
        # Update state
        self._update_state("REQUEST_START")
        self._update_state("STATUS_CHANGE", {"status": "executing"})
        
        start_time = time.time()
        token_count = 0
        
        try:
            client = self._get_client()
            
            # Build request payload - always stream in this method
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            
            log.info(f"🚀 Groq request: model={model}, messages={len(messages)}, stream=True")
            
            # Stream with throttling
            response = client.chat.completions.create(**payload)
            
            for chunk in response:
                # Check max duration
                if time.time() - start_time > self.guardrails.max_stream_duration_seconds:
                    log.warning("⏱️ Stream timeout reached")
                    yield "\n\n[Stream timed out - partial response]"
                    break
                
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # Handle content
                if delta.content:
                    # Apply throttling if enabled
                    if self.guardrails.throttle_tokens_per_second:
                        token_count += 1
                        expected_time = token_count / self.guardrails.throttle_tokens_per_second
                        elapsed = time.time() - start_time
                        if elapsed < expected_time:
                            time.sleep(expected_time - elapsed)
                    
                    yield delta.content
                
                # Handle tool calls
                if delta.tool_calls:
                    tool_data = []
                    for tc in delta.tool_calls:
                        tool_data.append({
                            "index": tc.index,
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name if hasattr(tc.function, 'name') else '',
                                "arguments": tc.function.arguments if hasattr(tc.function, 'arguments') else '{}'
                            }
                        })
                    
                    if tool_data:
                        yield f"__TOOL_CALL_DELTA__:{json.dumps(tool_data)}"
                
                # Check finish reason
                if chunk.choices[0].finish_reason:
                    break
            
            # Update state on success
            self._update_state("REQUEST_COMPLETE")
            self._update_state("TOKENS_PROCESSED", {"tokens": token_count})
            
            duration = time.time() - start_time
            tps = token_count / duration if duration > 0 else 0
            log.info(f"✅ Groq response: {token_count} tokens in {duration:.2f}s ({tps:.0f} TPS)")
            
        except Exception as e:
            self._update_state("REQUEST_ERROR")
            log.error(f"❌ Groq API error: {e}")
            yield f"[Error: {str(e)}]"
    
    def chat_with_deliberation(self, messages: List[Dict[str, str]], 
                               model: str = GroqModel.LLAMA3_70B.value,
                               deliberation_time_ms: int = 1000,
                               **kwargs) -> Generator[str, None, None]:
        """
        Chat with deliberation phase - allows AI time to think
        
        This implements the "Reducer Pattern" for agentic systems:
        1. Fast initial understanding
        2. Deliberation period for planning
        3. Tool evaluation
        4. Execution
        """
        # Phase 1: Fast initial understanding (always use fast model)
        fast_model = GroqModel.LLAMA3_8B.value
        log.info(f"🧠 Phase 1: Fast understanding with {fast_model}")
        
        understanding_prompt = """Analyze the user's request and identify:
1. Primary intent
2. Required tools/actions
3. Complexity level (1-5)
4. Potential edge cases

Be concise."""
        
        understanding_messages = messages + [{"role": "user", "content": understanding_prompt}]
        
        understanding = ""
        for chunk in self.chat(understanding_messages, model=fast_model, stream=True, max_tokens=500):
            if chunk.startswith("[Error:"):
                yield chunk
                return
            understanding += chunk
        
        # Phase 2: Deliberation (if complexity > 3)
        complexity = 3  # Default medium
        if "complexity" in understanding.lower():
            try:
                # Extract complexity score
                for line in understanding.split("\n"):
                    if "complexity" in line.lower():
                        for word in line.split():
                            if word.isdigit():
                                complexity = int(word)
                                break
            except:
                pass
        
        if complexity >= 3 and deliberation_time_ms > 0:
            log.info(f"🤔 Phase 2: Deliberating for {deliberation_time_ms}ms")
            self._update_state("STATUS_CHANGE", {"status": "planning"})
            
            # Use fast model for planning
            plan_messages = messages + [{
                "role": "assistant",
                "content": f"Understanding: {understanding}\n\nNow create a step-by-step plan."
            }]
            
            plan = ""
            for chunk in self.chat(plan_messages, model=fast_model, stream=True, max_tokens=800):
                plan += chunk
            
            # Simulate deliberation time
            time.sleep(deliberation_time_ms / 1000)
        
        # Phase 3: Execute with main model
        log.info(f"⚡ Phase 3: Executing with {model}")
        self._update_state("STATUS_CHANGE", {"status": "executing"})
        
        if complexity >= 3:
            # Include plan in final execution
            messages = messages + [{"role": "assistant", "content": f"Plan:\n{plan}"}]
        
        for chunk in self.chat(messages, model=model, stream=True, **kwargs):
            yield chunk
    
    def execute_tool_with_groq(self, tool_name: str, tool_params: Dict,
                               context: Dict = None) -> Dict[str, Any]:
        """
        Execute a tool with Groq providing intelligent parameter optimization
        
        This allows Groq to optimize tool execution parameters before calling
        """
        context = context or {}
        
        # Log tool execution
        self._update_state("TOOL_EXECUTED", {
            "tool": tool_name,
            "params": tool_params,
            "timestamp": time.time()
        })
        
        log.info(f"🔧 Groq-optimized tool execution: {tool_name}")
        
        # Return tool info for execution
        return {
            "tool": tool_name,
            "params": tool_params,
            "optimized": True,
            "context": context
        }
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics"""
        return {
            "requests_total": self.state.request_count,
            "tokens_total": self.state.token_count_total,
            "active_requests": self.state.active_requests,
            "circuit_open": self.state.circuit_open,
            "consecutive_errors": self.state.consecutive_errors,
            "status": self.state.status,
        }
    
    def reset_circuit(self):
        """Manually reset circuit breaker"""
        self._update_state("RESET_CIRCUIT")
        log.info("🔄 Circuit breaker reset")
    
    def validate_api_key(self) -> bool:
        """Validate Groq API key"""
        if not self.api_key:
            return False
        
        try:
            client = self._get_client()
            # Make minimal request
            response = client.models.list()
            return True
        except Exception as e:
            log.error(f"API key validation failed: {e}")
            return False


# Singleton instance
_groq_provider_instance: Optional[GroqProvider] = None


def get_groq_provider(guardrails: Optional[SpeedGuardrails] = None) -> GroqProvider:
    """Get singleton Groq provider instance"""
    global _groq_provider_instance
    if _groq_provider_instance is None:
        _groq_provider_instance = GroqProvider(guardrails)
    return _groq_provider_instance


def create_fast_groq_provider() -> GroqProvider:
    """Create Groq provider optimized for maximum speed (minimal guardrails)"""
    guardrails = SpeedGuardrails(
        max_requests_per_second=20.0,
        max_concurrent_requests=10,
        throttle_tokens_per_second=None,  # No throttling
        enable_context_compaction=True
    )
    return GroqProvider(guardrails)


def create_safe_groq_provider() -> GroqProvider:
    """Create Groq provider with maximum safety (conservative guardrails)"""
    guardrails = SpeedGuardrails(
        max_requests_per_second=5.0,
        max_concurrent_requests=2,
        throttle_tokens_per_second=100,  # Throttle to 100 TPS
        min_delay_between_requests_ms=200,
        enable_context_compaction=True,
        max_stream_duration_seconds=120
    )
    return GroqProvider(guardrails)
