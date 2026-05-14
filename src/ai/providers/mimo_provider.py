"""
Xiaomi MiMo Provider - Supports MiMo-V2.5 model family

MiMo-V2.5 is Xiaomi's latest model family from platform.xiaomimimo.com:
- MiMo-V2.5-Pro: 1.02T-param MoE (42B active), 1M context, 128K output
  — Long-horizon agentic coding, autonomous agent loops
- MiMo-V2.5: Full-modal (text/image/video/audio), 1M context, 128K output
  — Multimodal agentic perception & workflows
- MiMo-V2.5-Flash: Lightweight text model, 256K context, 64K output
  — High-throughput coding, simple tasks

API: OpenAI-compatible chat completions
  https://api.xiaomimimo.com/v1/chat/completions
(Anthropic-compatible endpoint also available at /anthropic — not used by this provider)

Pricing (per 1M tokens, overseas, cache-miss / cached / output):
  mimo-v2.5-pro:   $1.00 / $0.20 / $3.00
  mimo-v2.5:       $0.40 / $0.08 / $2.00
  mimo-v2.5-flash: $0.10 / $0.01 / $0.30
  (Long-context >256K surcharge applies to pro and v2.5)
  Cache write is currently free.

Env vars:
  MIMO_API_KEY                     — API key from platform.xiaomimimo.com
  CORTEX_MIMO_MAX_RETRIES          — int, default 4
  CORTEX_MIMO_CONNECT_TIMEOUT_SEC  — float, default 20.0
  CORTEX_MIMO_READ_TIMEOUT_SEC     — float, default 40.0
  CORTEX_MIMO_TOOL_READ_TIMEOUT_SEC — float, default 50.0
"""
import os
import json
import random
import time
import requests
from typing import List, Dict, Any, Optional, Generator
from src.ai.providers import BaseProvider, ProviderType, ModelInfo, ChatMessage, ChatResponse
from src.utils.logger import get_logger

log = get_logger("mimo_provider")


class MimoProvider(BaseProvider):
    """Xiaomi MiMo API provider (OpenAI-compatible) with full agentic support."""

    BASE_URL = "https://api.xiaomimimo.com/v1"

    def __init__(self):
        super().__init__(ProviderType.MIMO)
        self._api_key = os.getenv("MIMO_API_KEY", "")
        if not self._api_key:
            log.warning("MIMO_API_KEY not configured for Mimo provider")
        self._session = requests.Session()
        self._max_retries = self._get_int_env("CORTEX_MIMO_MAX_RETRIES", 4, minimum=1, maximum=5)
        self._retry_delay = 1.0
        self._connect_timeout = self._get_float_env("CORTEX_MIMO_CONNECT_TIMEOUT_SEC", 20.0, minimum=1.0, maximum=120.0)
        self._read_timeout = self._get_float_env("CORTEX_MIMO_READ_TIMEOUT_SEC", 40.0, minimum=3.0, maximum=300.0)
        self._tool_read_timeout = self._get_float_env("CORTEX_MIMO_TOOL_READ_TIMEOUT_SEC", 50.0, minimum=5.0, maximum=300.0)
        self._token_count = {"input": 0, "output": 0}

    # ─── env helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _get_int_env(name: str, default: int, minimum: int = 1, maximum: int = 10) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return max(minimum, min(maximum, int(raw)))
        except Exception:
            return default

    @staticmethod
    def _get_float_env(name: str, default: float, minimum: float = 1.0, maximum: float = 300.0) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return max(minimum, min(maximum, float(raw)))
        except Exception:
            return default

    def _resolve_read_timeout(self, stream: bool, tools: Optional[List[Dict[str, Any]]]) -> float:
        """Use a higher read-timeout for tool-heavy streaming first-token latency."""
        if stream and tools:
            return max(self._read_timeout, self._tool_read_timeout)
        return self._read_timeout

    # ─── model registry ───────────────────────────────────────────────────────

    @property
    def available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="mimo-v2.5-pro",
                name="MiMo V2.5 Pro (Agentic, 1.05M ctx)",
                provider="mimo",
                context_length=1_048_576,
                max_tokens=131_072,
                supports_streaming=True,
                supports_vision=False,          # text-only
                cost_per_1k_input=0.00100,      # $1.00 / 1M (cache-miss)
                cost_per_1k_output=0.00300,     # $3.00 / 1M
            ),
            ModelInfo(
                id="mimo-v2.5",
                name="MiMo V2.5 (Full-Modal, 1.05M ctx)",
                provider="mimo",
                context_length=1_048_576,
                max_tokens=131_072,
                supports_streaming=True,
                supports_vision=True,           # text + image + video + audio
                cost_per_1k_input=0.00040,      # $0.40 / 1M (cache-miss)
                cost_per_1k_output=0.00200,     # $2.00 / 1M
            ),
            ModelInfo(
                id="mimo-v2.5-flash",
                name="MiMo V2.5 Flash (256K ctx)",
                provider="mimo",
                context_length=262_144,
                max_tokens=65_536,
                supports_streaming=True,
                supports_vision=False,
                cost_per_1k_input=0.00010,      # $0.10 / 1M (cache-miss)
                cost_per_1k_output=0.00030,     # $0.30 / 1M
            ),
        ]

    # ─── auth ─────────────────────────────────────────────────────────────────

    def validate_api_key(self) -> bool:
        """Validate that a Mimo API key is present and plausible."""
        if not self._api_key:
            return False
        return len(self._api_key) > 8

    def set_api_key(self, api_key: str):
        """Set the Mimo API key at runtime."""
        self._api_key = api_key
        super().set_api_key(api_key)

    # ─── chat (non-streaming) ─────────────────────────────────────────────────

    def chat(self,
             messages: List[ChatMessage],
             model: str = "mimo-v2.5-pro",
             temperature: float = 0.6,
             max_tokens: int = 32_768,
             stream: bool = False,
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: Optional[str] = None,
             **kwargs: Any) -> ChatResponse:
        """Send a chat completion request to the Mimo API (OpenAI-compatible)."""
        start_time = time.time()

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        formatted_messages = self._format_messages_for_provider(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "temperature": temperature,
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
                response = self._session.post(
                    url, headers=headers, json=payload,
                    timeout=(self._connect_timeout, self._read_timeout),
                )
                response.raise_for_status()
                result = response.json()

                duration_ms = (time.time() - start_time) * 1000
                message = result["choices"][0].get("message", {})

                # MiMo reasoning models may surface chain-of-thought in
                # reasoning_content (same pattern as Kimi K2.6 / DeepSeek).
                content = (
                    message.get("content")
                    or message.get("reasoning_content")
                    or ""
                )
                tool_calls = message.get("tool_calls")

                usage = result.get("usage", {})
                self._token_count["input"] = usage.get("prompt_tokens", 0)
                self._token_count["output"] = usage.get("completion_tokens", 0)

                return ChatResponse(
                    content=content,
                    model=model,
                    provider="mimo",
                    input_tokens=self._token_count["input"],
                    output_tokens=self._token_count["output"],
                    finish_reason=result["choices"][0].get("finish_reason"),
                    duration_ms=duration_ms,
                    tool_calls=tool_calls,
                )

            except requests.exceptions.Timeout:
                last_error = Exception(
                    f"Mimo API timeout after connect={self._connect_timeout}s / "
                    f"read={self._read_timeout}s (attempt {attempt + 1})"
                )
                log.warning(str(last_error))
                continue

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                _resp_body = ""
                if e.response is not None:
                    try:
                        _resp_body = e.response.text[:500]
                    except Exception:
                        pass

                # Detect daily quota exhaustion — non-retryable
                _is_quota = (
                    "quota" in _resp_body.lower()
                    or "rate limit" in _resp_body.lower()
                    or "tokens per day" in _resp_body.lower()
                )
                if _is_quota and status == 429:
                    log.error(f"Mimo API daily quota exhausted: {_resp_body}")
                    return ChatResponse(
                        content="", model=model, provider="mimo",
                        error=f"QUOTA_EXHAUSTED: {_resp_body}",
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                if status in (429, 502, 503, 504) and attempt < self._max_retries:
                    log.warning(f"Mimo API transient HTTP {status} (attempt {attempt + 1})")
                    continue

                log.error(f"Mimo API HTTP {status}: {e} | Body: {_resp_body}")
                return ChatResponse(
                    content="", model=model, provider="mimo",
                    error=f"HTTP {status}: {_resp_body}",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            except requests.exceptions.RequestException as e:
                last_error = e
                log.warning(f"Mimo API request error (attempt {attempt + 1}): {e}")
                continue

        log.error(f"Mimo API error after all retries: {last_error}")
        return ChatResponse(
            content="", model=model, provider="mimo",
            error=str(last_error),
            duration_ms=(time.time() - start_time) * 1000,
        )

    # ─── chat_stream (SSE) ────────────────────────────────────────────────────

    def chat_stream(self,
                    messages: List[ChatMessage],
                    model: str = "mimo-v2.5-pro",
                    temperature: float = 0.6,
                    max_tokens: int = 32_768,
                    tools: Optional[List[Dict[str, Any]]] = None,
                    retry_callback=None,
                    **kwargs: Any) -> Generator[str, None, None]:
        """Stream chat completion from Mimo API using SSE."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        formatted_messages = self._format_messages_for_provider(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "temperature": temperature,
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
                        retry_callback(attempt + 1, self._max_retries + 1, "error")
                    except Exception:
                        pass
                time.sleep(backoff)

            try:
                _read_to = self._resolve_read_timeout(True, tools)
                response = self._session.post(
                    url, headers=headers, json=payload, stream=True,
                    timeout=(self._connect_timeout, _read_to),
                )
                response.raise_for_status()

                for line in response.iter_lines():
                    if not line:
                        continue
                    line_text = line.decode("utf-8").strip()
                    if not line_text.startswith("data: "):
                        continue
                    data_str = line_text[6:]
                    if data_str.strip() == "[DONE]":
                        return

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = data.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    # Chain-of-thought / reasoning tokens (MoE reasoning models)
                    reasoning = delta.get("reasoning_content", "")
                    content = delta.get("content", "")
                    tool_calls = delta.get("tool_calls", [])

                    if reasoning:
                        yield "__REASONING_DELTA__:" + reasoning
                    if content:
                        yield content

                    # Agentic tool calls (function calling)
                    if tool_calls:
                        tool_call_data = []
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            raw_args = fn.get("arguments", "")
                            if isinstance(raw_args, dict):
                                raw_args = json.dumps(raw_args)
                            tool_call_data.append({
                                "index": tc.get("index", 0),
                                "id": tc.get("id", ""),
                                "function": {
                                    "name": fn.get("name", ""),
                                    "arguments": raw_args if isinstance(raw_args, str) else str(raw_args),
                                },
                            })
                        yield f"__TOOL_CALL_DELTA__:{json.dumps(tool_call_data)}"

                return  # clean exit after full stream

            except requests.exceptions.Timeout:
                last_error = Exception(
                    f"Mimo API stream timeout after connect={self._connect_timeout}s / "
                    f"read={self._read_timeout}s (attempt {attempt + 1})"
                )
                log.warning(str(last_error))
                continue

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                _resp_body = ""
                if e.response is not None:
                    try:
                        _resp_body = e.response.text[:500]
                    except Exception:
                        pass

                _is_quota = (
                    "quota" in _resp_body.lower()
                    or "rate limit" in _resp_body.lower()
                    or "tokens per day" in _resp_body.lower()
                )
                if _is_quota and status == 429:
                    log.error(f"Mimo API stream daily quota exhausted: {_resp_body}")
                    raise RuntimeError(
                        f"QUOTA_EXHAUSTED: Mimo daily token quota reached — {_resp_body}"
                    )

                if status in (429, 502, 503, 504) and attempt < self._max_retries:
                    log.warning(f"Mimo API stream transient HTTP {status} (attempt {attempt + 1})")
                    if retry_callback:
                        try:
                            retry_callback(attempt + 1, self._max_retries + 1, str(status))
                        except Exception:
                            pass
                    continue

                log.error(f"Mimo API stream HTTP {status}: {e} | Body: {_resp_body}")
                yield f"[Error: HTTP {status}]"
                return

            except requests.exceptions.RequestException as e:
                last_error = e
                log.warning(f"Mimo API stream error (attempt {attempt + 1}): {e}")
                continue

        log.error(f"Mimo API stream failed after all retries: {last_error}")
        yield "[Error: stream failed after retries]"

    # ─── web search (MiMo native built-in tool) ───────────────────────────────

    def web_search(self,
                   query: str,
                   model: str = "mimo-v2.5-pro",
                   max_keyword: int = 3,
                   force_search: bool = True,
                   limit: int = 1,
                   user_location: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Search the web using MiMo's native web_search built-in tool.

        Returns a list of dicts with keys:
          title, url, snippet, site_name, publish_time, logo_url

        Returns empty list on failure (caller should fall back to other search providers).
        """
        if not self._api_key:
            log.debug("MimoProvider.web_search: no API key configured")
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        messages = [
            {"role": "system", "content": "You are a web search assistant. Search the web and return the results."},
            {"role": "user", "content": query},
        ]

        web_search_tool = {
            "type": "web_search",
            "max_keyword": min(max_keyword, 3),
            "force_search": force_search,
            "limit": min(limit, 5),
        }
        if user_location:
            web_search_tool["user_location"] = user_location

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.3,
            "stream": False,
            "tools": [web_search_tool],
            "tool_choice": "auto",
        }

        url = f"{self.BASE_URL}/chat/completions"

        for attempt in range(min(self._max_retries + 1, 2)):
            if attempt > 0:
                time.sleep(self._retry_delay * (2 ** (attempt - 1)) + random.random())
            try:
                response = self._session.post(
                    url, headers=headers, json=payload,
                    timeout=(self._connect_timeout, self._read_timeout),
                )
                response.raise_for_status()
                result = response.json()

                message = result.get("choices", [{}])[0].get("message", {})
                annotations = message.get("annotations", [])

                results: List[Dict[str, Any]] = []
                for ann in annotations:
                    if ann.get("type") == "url_citation":
                        results.append({
                            "title": ann.get("title", ""),
                            "url": ann.get("url", ""),
                            "snippet": (ann.get("summary", "") or "")[:300],
                            "site_name": ann.get("site_name", ""),
                            "publish_time": ann.get("publish_time", ""),
                            "logo_url": ann.get("logo_url", ""),
                        })

                log.info(f"[MiMo WebSearch] {len(results)} results for '{query[:80]}'")
                return results

            except requests.exceptions.Timeout:
                log.warning(f"[MiMo WebSearch] timeout (attempt {attempt + 1})")
                continue
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status in (429, 502, 503, 504) and attempt < min(self._max_retries + 1, 2) - 1:
                    log.warning(f"[MiMo WebSearch] transient HTTP {status} (attempt {attempt + 1})")
                    continue
                log.warning(f"[MiMo WebSearch] HTTP {status}: {e}")
                break
            except requests.exceptions.RequestException as e:
                log.warning(f"[MiMo WebSearch] request error (attempt {attempt + 1}): {e}")
                continue

        return []

    # ─── usage ────────────────────────────────────────────────────────────────

    def get_usage_stats(self) -> Dict[str, Any]:
        """Return current session token usage."""
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "total_tokens": self._token_count["input"] + self._token_count["output"],
        }

    def reset_usage(self):
        """Reset token usage counters."""
        self._token_count = {"input": 0, "output": 0}


# ─── singleton ────────────────────────────────────────────────────────────────

_mimo_provider: Optional[MimoProvider] = None


def get_mimo_provider() -> MimoProvider:
    """Get or create the global MimoProvider singleton."""
    global _mimo_provider
    if _mimo_provider is None:
        _mimo_provider = MimoProvider()
    return _mimo_provider
