"""
Kimi/Moonshot AI Provider - Supports Kimi K2.6 multimodal model

Kimi K2.6 is Kimi's latest and most intelligent model from Moonshot AI:
- Strong code writing with 256k context
- Native multimodal (text, image, video input)
- Thinking and non-thinking modes
- ToolCalls, JSON Mode, Partial Mode, internet search
- OpenAI-compatible API: https://api.moonshot.ai/v1

Pricing (per 1M tokens):
  - Input (Cache Hit): $0.16
  - Input (Cache Miss): $0.95
  - Output: $4.00
"""
import os
import json
import random
import time
import requests
from typing import List, Dict, Any, Optional, Generator
from src.ai.providers import BaseProvider, ProviderType, ModelInfo, ChatMessage, ChatResponse
from src.utils.logger import get_logger

log = get_logger("kimi_provider")


class KimiProvider(BaseProvider):
    """Kimi/Moonshot AI API provider with multimodal support."""

    BASE_URL = "https://api.moonshot.ai/v1"

    def __init__(self):
        super().__init__(ProviderType.KIMI)
        self._api_key = os.getenv("MOONSHOT_API_KEY", "")
        if not self._api_key:
            log.warning("MOONSHOT_API_KEY not configured for Kimi provider")
        self._session = requests.Session()
        self._max_retries = 2
        self._retry_delay = 1.0
        self._timeout = 120.0
        self._token_count = {"input": 0, "output": 0}

    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="kimi-k2.6",
                name="Kimi K2.6 (Multimodal)",
                provider="kimi",
                context_length=262144,
                max_tokens=32768,
                supports_streaming=True,
                supports_vision=True,
                cost_per_1k_input=0.00095,   # $0.95/1M (cache miss rate)
                cost_per_1k_output=0.00400,  # $4.00/1M
            ),
        ]

    def validate_api_key(self) -> bool:
        """Validate the Kimi API key by checking it's set and looks valid."""
        if not self._api_key:
            return False
        # Simple validation - Kimi keys are usually sk- prefixed
        return len(self._api_key) > 8

    def set_api_key(self, api_key: str):
        """Set the Kimi API key."""
        self._api_key = api_key
        super().set_api_key(api_key)

    def chat(self,
             messages: List[ChatMessage],
             model: str = "kimi-k2.6",
             temperature: float = 1.0,
             max_tokens: int = 4096,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None,
             **kwargs: Any) -> ChatResponse:
        """Send chat completion request to Kimi API."""
        start_time = time.time()

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        formatted_messages = self._format_messages_for_provider(messages)

        # Kimi K2.6 only accepts temperature=1.0
        kimi_temp = 1.0

        payload: Dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "temperature": kimi_temp,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        url = f"{self.BASE_URL}/chat/completions"

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                backoff = self._retry_delay * (2 ** (attempt - 1)) + random.random()
                time.sleep(backoff)

            try:
                response = self._session.post(url, headers=headers, json=payload, timeout=self._timeout)
                response.raise_for_status()
                result = response.json()

                duration_ms = (time.time() - start_time) * 1000
                message = result['choices'][0].get('message', {})
                # Kimi K2.6 thinking model: content may be empty, actual
                # response is in reasoning_content
                content = message.get('content') or message.get('reasoning_content') or ""
                tool_calls = message.get('tool_calls')

                # Track token usage
                self._token_count["input"] = result.get('usage', {}).get('prompt_tokens', 0)
                self._token_count["output"] = result.get('usage', {}).get('completion_tokens', 0)

                return ChatResponse(
                    content=content,
                    model=model,
                    provider="kimi",
                    input_tokens=self._token_count["input"],
                    output_tokens=self._token_count["output"],
                    finish_reason=result['choices'][0].get('finish_reason'),
                    duration_ms=duration_ms,
                    tool_calls=tool_calls
                )

            except requests.exceptions.Timeout:
                last_error = Exception(f"Kimi API timeout after {self._timeout}s (attempt {attempt + 1})")
                log.warning(str(last_error))
                continue
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                # Log the actual API response body for debugging
                _resp_body = ""
                if e.response is not None:
                    try:
                        _resp_body = e.response.text[:500]
                    except Exception:
                        pass
                if status in (429, 502, 503, 504) and attempt < self._max_retries:
                    log.warning(f"Kimi API transient HTTP {status} (attempt {attempt + 1})")
                    time.sleep(self._retry_delay * (2 ** attempt))
                    continue
                log.error(f"Kimi API HTTP {status}: {e} | Body: {_resp_body}")
                return ChatResponse(
                    content="", model=model, provider="kimi",
                    error=f"HTTP {status}: {_resp_body}", duration_ms=(time.time() - start_time) * 1000
                )
            except requests.exceptions.RequestException as e:
                last_error = e
                log.warning(f"Kimi API request error (attempt {attempt + 1}): {e}")
                continue

        log.error(f"Kimi API error after all retries: {last_error}")
        return ChatResponse(
            content="", model=model, provider="kimi",
            error=str(last_error), duration_ms=(time.time() - start_time) * 1000
        )

    def chat_stream(self,
                   messages: List[ChatMessage],
                   model: str = "kimi-k2.6",
                   temperature: float = 1.0,
                   max_tokens: int = 4096,
                   tools: Optional[List[Dict[str, Any]]] = None,
                   retry_callback=None,
                   **kwargs: Any) -> Generator[str, None, None]:
        """Stream chat completion from Kimi API with SSE support."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        formatted_messages = self._format_messages_for_provider(messages)

        # Kimi K2.6 only accepts temperature=1.0
        kimi_temp = 1.0

        payload: Dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "temperature": kimi_temp,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        url = f"{self.BASE_URL}/chat/completions"

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                backoff = self._retry_delay * (2 ** (attempt - 1)) + random.random()
                if retry_callback:
                    try:
                        retry_callback(attempt + 1, self._max_retries + 1, 'error')
                    except Exception:
                        pass
                time.sleep(backoff)

            try:
                response = self._session.post(url, headers=headers, json=payload, stream=True, timeout=self._timeout)
                response.raise_for_status()

                for line in response.iter_lines():
                    if line:
                        line_text = line.decode('utf-8').strip()
                        if line_text.startswith('data: '):
                            data_str = line_text[6:]
                            if data_str.strip() == '[DONE]':
                                return
                            try:
                                data = json.loads(data_str)
                                if 'choices' in data and len(data['choices']) > 0:
                                    delta = data['choices'][0].get('delta', {})
                                    # Kimi K2.6 thinking model: actual response may come
                                    # in reasoning_content, not content
                                    reasoning = delta.get('reasoning_content', '')
                                    content = delta.get('content', '')
                                    tool_calls = delta.get('tool_calls', [])

                                    if reasoning:
                                        yield "__REASONING_DELTA__:" + reasoning
                                    if content:
                                        yield content

                                    # Stream tool calls (Kimi K2.6 agentic tool use)
                                    if tool_calls:
                                        tool_call_data = []
                                        for tc in tool_calls:
                                            fn = tc.get('function', {})
                                            raw_args = fn.get('arguments', '')
                                            if isinstance(raw_args, dict):
                                                raw_args = json.dumps(raw_args)
                                            tool_call_data.append({
                                                'index': tc.get('index', 0),
                                                'id': tc.get('id', ''),
                                                'function': {
                                                    'name': fn.get('name', ''),
                                                    'arguments': raw_args if isinstance(raw_args, str) else str(raw_args)
                                                }
                                            })
                                        yield f"__TOOL_CALL_DELTA__:{json.dumps(tool_call_data)}"
                            except json.JSONDecodeError:
                                continue
                return  # Successfully streamed

            except requests.exceptions.Timeout:
                last_error = Exception(f"Kimi API timeout after {self._timeout}s (attempt {attempt + 1})")
                log.warning(str(last_error))
                continue
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                # Log the actual API response body for debugging
                _resp_body = ""
                if e.response is not None:
                    try:
                        _resp_body = e.response.text[:500]
                    except Exception:
                        pass
                if status in (429, 502, 503, 504) and attempt < self._max_retries:
                    log.warning(f"Kimi API transient HTTP {status} (attempt {attempt + 1})")
                    if retry_callback:
                        try:
                            retry_callback(attempt + 1, self._max_retries + 1, str(status))
                        except Exception:
                            pass
                    time.sleep(self._retry_delay * (2 ** attempt))
                    continue
                log.error(f"Kimi API stream HTTP {status}: {e} | Body: {_resp_body}")
                yield f"[Error: HTTP {status}]"
                return
            except requests.exceptions.RequestException as e:
                last_error = e
                log.warning(f"Kimi API stream error (attempt {attempt + 1}): {e}")
                continue

        log.error(f"Kimi API stream failed after all retries: {last_error}")
        yield f"[Error: stream failed after retries]"

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics."""
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "total_tokens": self._token_count["input"] + self._token_count["output"],
        }

    def reset_usage(self):
        """Reset usage counters."""
        self._token_count = {"input": 0, "output": 0}


# Singleton instance
_kimi_provider: Optional[KimiProvider] = None


def get_kimi_provider() -> KimiProvider:
    """Get or create Kimi provider instance."""
    global _kimi_provider
    if _kimi_provider is None:
        _kimi_provider = KimiProvider()
    return _kimi_provider
