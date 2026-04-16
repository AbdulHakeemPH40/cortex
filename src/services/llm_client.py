"""
Unified LLM Client for Cortex IDE
Extracted from claude-code-main/src/services/api/claude.ts

Provides a single interface over Claude (Anthropic), OpenAI, Gemini, DeepSeek,
Mistral and any other OpenAI-compatible provider — replacing the Claude-only
SDK wiring in the original TypeScript source.

Key patterns ported from claude.ts:
  - queryModelWithStreaming / queryModelWithoutStreaming  →  LLMClient.stream / .complete
  - updateUsage / accumulateUsage                        →  usage_tracker.py
  - verifyApiKey                                         →  LLMClient.verify_api_key
  - stripExcessMediaItems                                →  LLMClient._strip_excess_media
  - max_tokens / thinking budget adjustment              →  LLMClient._cap_tokens
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any, AsyncGenerator, Dict, Generator, List, Optional, Tuple, Union
)

from src.utils.logger import get_logger

log = get_logger("llm_client")

# ─── Maximum tokens for non-streaming fallback (mirrors claude.ts:3354) ──────
MAX_NON_STREAMING_TOKENS: int = 64_000

# ─── Max media items per request (mirrors constants/apiLimits.ts) ─────────────
API_MAX_MEDIA_PER_REQUEST: int = 20


# ═════════════════════════════════════════════════════════════════════════════
# Enumerations
# ═════════════════════════════════════════════════════════════════════════════

class Provider(str, Enum):
    """Supported LLM providers."""
    ANTHROPIC   = "anthropic"
    OPENAI      = "openai"
    GEMINI      = "gemini"
    DEEPSEEK    = "deepseek"
    MISTRAL     = "mistral"
    GROQ        = "groq"
    OLLAMA      = "ollama"
    CUSTOM      = "custom"   # any OpenAI-compatible endpoint


class FinishReason(str, Enum):
    STOP          = "stop"
    MAX_TOKENS    = "max_tokens"
    TOOL_USE      = "tool_use"
    ERROR         = "error"
    ABORTED       = "aborted"
    CONTENT_FILTER = "content_filter"


class ThinkingMode(str, Enum):
    DISABLED = "disabled"
    ENABLED  = "enabled"
    AUTO     = "auto"


# ═════════════════════════════════════════════════════════════════════════════
# Data classes
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Message:
    """Single chat message (user / assistant / system / tool)."""
    role:        str
    content:     Union[str, List[Dict[str, Any]]]
    name:        Optional[str]                    = None
    tool_calls:  Optional[List[Dict[str, Any]]]   = None
    tool_call_id: Optional[str]                   = None


@dataclass
class ToolDefinition:
    """Schema for a callable tool (function-calling spec)."""
    name:        str
    description: str
    parameters:  Dict[str, Any]   # JSON-Schema object


@dataclass
class ThinkingConfig:
    """Extended-thinking configuration (Claude 3.7+ / o-series)."""
    mode:          ThinkingMode = ThinkingMode.DISABLED
    budget_tokens: int          = 10_000


@dataclass
class LLMOptions:
    """
    Options forwarded to the underlying provider API.
    Mirrors the Options type in claude.ts:676.
    """
    model:               str
    provider:            Provider              = Provider.ANTHROPIC
    max_tokens:          int                   = 4096
    temperature:         float                 = 1.0
    thinking:            ThinkingConfig        = field(default_factory=ThinkingConfig)
    tools:               List[ToolDefinition]  = field(default_factory=list)
    system_prompt:       Optional[str]         = None
    stream:              bool                  = True
    timeout:             float                 = 300.0
    max_retries:         int                   = 3
    # Provider-specific extras passed through as-is
    extra_params:        Dict[str, Any]        = field(default_factory=dict)


@dataclass
class StreamEvent:
    """Typed event emitted by the streaming generator."""
    type:      str          # "text_delta" | "thinking_delta" | "tool_use" | "done" | "error"
    content:   str          = ""
    tool_name: str          = ""
    tool_id:   str          = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[FinishReason] = None
    error:     Optional[str]              = None


@dataclass
class LLMResponse:
    """Final (non-streaming) response from an LLM provider."""
    content:      str
    model:        str
    provider:     Provider
    input_tokens: int                    = 0
    output_tokens: int                   = 0
    thinking:     Optional[str]          = None
    tool_calls:   List[Dict[str, Any]]   = field(default_factory=list)
    finish_reason: FinishReason          = FinishReason.STOP
    duration_ms:  float                  = 0.0
    error:        Optional[str]          = None


# ═════════════════════════════════════════════════════════════════════════════
# Abstract base
# ═════════════════════════════════════════════════════════════════════════════

class BaseProviderClient(ABC):
    """
    Abstract provider client.  Concrete implementations live in
    src/ai/providers/ (DeepSeek, Mistral, SiliconFlow …) and can be wrapped
    by this client layer without modification.
    """

    def __init__(self, provider: Provider, api_key: str = "", base_url: str = ""):
        self.provider   = provider
        self._api_key   = api_key or os.getenv(self._default_env_key(), "")
        self._base_url  = base_url
        self._last_error: Optional[str] = None

    def _default_env_key(self) -> str:
        return f"{self.provider.value.upper()}_API_KEY"

    @abstractmethod
    def verify_api_key(self) -> bool:
        """Return True when the API key appears valid (cheap request)."""

    @abstractmethod
    def complete(self, messages: List[Message], options: LLMOptions) -> LLMResponse:
        """Non-streaming completion. Mirrors queryModelWithoutStreaming."""

    @abstractmethod
    def stream(
        self,
        messages: List[Message],
        options: LLMOptions,
        abort_signal: Optional[asyncio.Event] = None,
    ) -> Generator[StreamEvent, None, None]:
        """
        Streaming completion as a synchronous generator of StreamEvent.
        Mirrors queryModelWithStreaming (the async generator in claude.ts).
        """

    # ── Shared helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _cap_tokens(max_tokens: int, thinking_budget: int, cap: int) -> Tuple[int, int]:
        """
        Adjust token budget so API constraint max_tokens > thinking_budget holds.
        Mirrors adjustParamsForNonStreaming in claude.ts:3364.
        """
        capped = min(max_tokens, cap)
        if thinking_budget and thinking_budget >= capped:
            thinking_budget = max(0, capped - 1)
        return capped, thinking_budget

    @staticmethod
    def _strip_excess_media(
        messages: List[Message],
        max_media: int = API_MAX_MEDIA_PER_REQUEST,
    ) -> List[Message]:
        """
        Remove image/document blocks beyond max_media per request.
        Mirrors stripExcessMediaItems in claude.ts:956.
        """
        media_count = 0
        result: List[Message] = []
        for msg in reversed(messages):
            if not isinstance(msg.content, list):
                result.append(msg)
                continue
            filtered_blocks = []
            for block in msg.content:
                btype = block.get("type", "")
                if btype in ("image", "document"):
                    media_count += 1
                    if media_count > max_media:
                        log.warning(
                            "Dropping media block %d (limit=%d)", media_count, max_media
                        )
                        continue
                filtered_blocks.append(block)
            result.append(Message(role=msg.role, content=filtered_blocks,
                                  name=msg.name, tool_calls=msg.tool_calls,
                                  tool_call_id=msg.tool_call_id))
        result.reverse()
        return result

    def _format_tools(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Convert ToolDefinition list to OpenAI-style function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]


# ═════════════════════════════════════════════════════════════════════════════
# OpenAI-compatible client (Claude / DeepSeek / Groq / Ollama / custom)
# ═════════════════════════════════════════════════════════════════════════════

class OpenAICompatibleClient(BaseProviderClient):
    """
    Generic client for any OpenAI-API-compatible provider.
    Used directly for: OpenAI, DeepSeek, Groq, Ollama, custom endpoints.
    For Anthropic the AnthropicClient subclass below adds extra headers.
    """

    DEFAULT_BASE_URLS: Dict[Provider, str] = {
        Provider.OPENAI:   "https://api.openai.com/v1",
        Provider.DEEPSEEK: "https://api.deepseek.com/v1",
        Provider.GROQ:     "https://api.groq.com/openai/v1",
        Provider.OLLAMA:   "http://localhost:11434/v1",
    }

    def __init__(self, provider: Provider, api_key: str = "", base_url: str = ""):
        super().__init__(provider, api_key, base_url)
        self._base_url = base_url or self.DEFAULT_BASE_URLS.get(provider, "")

    # ── Internal HTTP ─────────────────────────────────────────────────────────

    def _post(self, payload: Dict[str, Any], stream: bool = False, timeout: float = 300.0):
        """Raw HTTP POST to /chat/completions."""
        import requests
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        return requests.post(url, headers=headers, json=payload,
                             stream=stream, timeout=timeout)

    def _messages_to_api(self, messages: List[Message]) -> List[Dict[str, Any]]:
        out = []
        for m in messages:
            entry: Dict[str, Any] = {"role": m.role, "content": m.content}
            if m.name:
                entry["name"] = m.name
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            out.append(entry)
        return out

    def _build_payload(
        self, messages: List[Message], options: LLMOptions, stream: bool
    ) -> Dict[str, Any]:
        api_messages = self._messages_to_api(messages)
        if options.system_prompt:
            api_messages.insert(0, {"role": "system", "content": options.system_prompt})

        payload: Dict[str, Any] = {
            "model":       options.model,
            "messages":    api_messages,
            "temperature": options.temperature,
            "max_tokens":  options.max_tokens,
            "stream":      stream,
        }
        if options.tools:
            payload["tools"] = self._format_tools(options.tools)
        payload.update(options.extra_params)
        return payload

    # ── Public API ────────────────────────────────────────────────────────────

    def verify_api_key(self) -> bool:
        if not self._api_key:
            return False
        try:
            payload = {
                "model":      self._smallest_model(),
                "messages":   [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "stream":     False,
            }
            resp = self._post(payload, timeout=10.0)
            return resp.status_code in (200, 400)   # 400 = model issue, key valid
        except Exception as exc:
            log.error("verify_api_key failed: %s", exc)
            return False

    def _smallest_model(self) -> str:
        """Return a cheap/fast model for key-verification pings."""
        defaults = {
            Provider.OPENAI:   "gpt-4o-mini",
            Provider.DEEPSEEK: "deepseek-chat",
            Provider.GROQ:     "llama-3.1-8b-instant",
            Provider.OLLAMA:   "llama3",
        }
        return defaults.get(self.provider, "gpt-4o-mini")

    def complete(self, messages: List[Message], options: LLMOptions) -> LLMResponse:
        """Non-streaming completion (mirrors queryModelWithoutStreaming)."""
        import time, requests
        stripped = self._strip_excess_media(messages)
        max_tok, _ = self._cap_tokens(options.max_tokens, 0, MAX_NON_STREAMING_TOKENS)
        payload = self._build_payload(stripped, options, stream=False)
        payload["max_tokens"] = max_tok

        start = time.monotonic()
        try:
            resp = self._post(payload, timeout=options.timeout)
            duration_ms = (time.monotonic() - start) * 1000

            if resp.status_code != 200:
                err = self._extract_error(resp)
                return LLMResponse(content="", model=options.model,
                                   provider=self.provider, error=err,
                                   finish_reason=FinishReason.ERROR,
                                   duration_ms=duration_ms)

            data = resp.json()
            choice   = data["choices"][0]
            msg      = choice.get("message", {})
            content  = msg.get("content") or ""
            usage    = data.get("usage", {})
            tc       = msg.get("tool_calls") or []
            finish   = FinishReason(choice.get("finish_reason", "stop"))

            return LLMResponse(
                content       = content,
                model         = data.get("model", options.model),
                provider      = self.provider,
                input_tokens  = usage.get("prompt_tokens", 0),
                output_tokens = usage.get("completion_tokens", 0),
                tool_calls    = tc,
                finish_reason = finish,
                duration_ms   = duration_ms,
            )
        except Exception as exc:
            self._last_error = str(exc)
            log.error("complete() error: %s", exc)
            return LLMResponse(content="", model=options.model,
                               provider=self.provider, error=str(exc),
                               finish_reason=FinishReason.ERROR)

    def stream(
        self,
        messages: List[Message],
        options: LLMOptions,
        abort_signal: Optional[asyncio.Event] = None,
    ) -> Generator[StreamEvent, None, None]:
        """
        SSE streaming generator — mirrors queryModelWithStreaming pattern.
        Yields StreamEvent objects that the GUI can consume directly.
        """
        import requests as req

        stripped = self._strip_excess_media(messages)
        payload  = self._build_payload(stripped, options, stream=True)

        try:
            response = self._post(payload, stream=True, timeout=options.timeout)

            if response.status_code != 200:
                err = self._extract_error(response)
                yield StreamEvent(type="error", error=err,
                                  finish_reason=FinishReason.ERROR)
                return

            # Accumulate tool-call deltas by index
            tool_call_accum: Dict[int, Dict[str, Any]] = {}

            for raw_line in response.iter_lines():
                # Honour abort signal (GUI cancel button)
                if abort_signal and abort_signal.is_set():
                    yield StreamEvent(type="done", finish_reason=FinishReason.ABORTED)
                    response.close()
                    return

                if not raw_line:
                    continue

                line: str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if line.startswith(":"):       # SSE comment / keepalive
                    continue
                if not line.startswith("data: "):
                    continue

                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if "error" in chunk:
                    yield StreamEvent(type="error",
                                      error=chunk["error"].get("message", "unknown"),
                                      finish_reason=FinishReason.ERROR)
                    return

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta  = choice.get("delta", {})
                reason = choice.get("finish_reason")

                # Text delta
                text = delta.get("content") or ""
                if text:
                    yield StreamEvent(type="text_delta", content=text)

                # Tool-call deltas (accumulate fragments across chunks)
                for tc_delta in delta.get("tool_calls", []):
                    idx  = tc_delta.get("index", 0)
                    if idx not in tool_call_accum:
                        tool_call_accum[idx] = {
                            "id":       tc_delta.get("id", ""),
                            "name":     tc_delta.get("function", {}).get("name", ""),
                            "args_raw": "",
                        }
                    fn = tc_delta.get("function", {})
                    tool_call_accum[idx]["args_raw"] += fn.get("arguments", "")
                    if tc_delta.get("id"):
                        tool_call_accum[idx]["id"] = tc_delta["id"]
                    if fn.get("name"):
                        tool_call_accum[idx]["name"] = fn["name"]

                if reason:
                    # Flush accumulated tool calls
                    for tc in tool_call_accum.values():
                        try:
                            args = json.loads(tc["args_raw"]) if tc["args_raw"] else {}
                        except json.JSONDecodeError:
                            args = {"_raw": tc["args_raw"]}
                        yield StreamEvent(
                            type       = "tool_use",
                            tool_id    = tc["id"],
                            tool_name  = tc["name"],
                            tool_input = args,
                        )
                    tool_call_accum.clear()

                    finish = FinishReason(reason) if reason in FinishReason._value2member_map_ else FinishReason.STOP
                    yield StreamEvent(type="done", finish_reason=finish)
                    return

            yield StreamEvent(type="done", finish_reason=FinishReason.STOP)

        except Exception as exc:
            self._last_error = str(exc)
            log.error("stream() error: %s", exc)
            yield StreamEvent(type="error", error=str(exc),
                              finish_reason=FinishReason.ERROR)

    @staticmethod
    def _extract_error(resp) -> str:
        try:
            body = resp.json()
            return body.get("error", {}).get("message") or resp.text
        except Exception:
            return resp.text or f"HTTP {resp.status_code}"


# ═════════════════════════════════════════════════════════════════════════════
# Anthropic-specific client
# ═════════════════════════════════════════════════════════════════════════════

class AnthropicClient(BaseProviderClient):
    """
    Anthropic (Claude) provider client.
    Uses the anthropic Python SDK when available, falls back to raw HTTP.
    Ports the core logic from claude.ts: prompt caching, thinking, betas.
    """

    BASE_URL = "https://api.anthropic.com"
    API_VERSION = "2023-06-01"
    # Beta features sent via anthropic-beta header
    DEFAULT_BETAS = ["max-tokens-3-5-sonnet-2024-07-15"]

    def __init__(self, api_key: str = ""):
        super().__init__(Provider.ANTHROPIC, api_key)

    def _headers(self, extra_betas: Optional[List[str]] = None) -> Dict[str, str]:
        betas = list(self.DEFAULT_BETAS)
        if extra_betas:
            betas.extend(b for b in extra_betas if b not in betas)
        return {
            "x-api-key":        self._api_key,
            "anthropic-version": self.API_VERSION,
            "content-type":     "application/json",
            **({"anthropic-beta": ",".join(betas)} if betas else {}),
        }

    def _messages_to_api(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert to Anthropic messages format (role / content)."""
        out = []
        for m in messages:
            if m.role == "system":
                continue  # system handled separately
            entry: Dict[str, Any] = {"role": m.role}
            if isinstance(m.content, str):
                entry["content"] = m.content
            elif isinstance(m.content, list):
                entry["content"] = m.content
            else:
                entry["content"] = str(m.content)
            if m.tool_calls:
                # Convert OpenAI-style tool_calls to Anthropic tool_use blocks
                blocks = []
                for tc in m.tool_calls:
                    fn = tc.get("function", {})
                    blocks.append({
                        "type":  "tool_use",
                        "id":    tc.get("id", str(uuid.uuid4())),
                        "name":  fn.get("name", ""),
                        "input": json.loads(fn.get("arguments", "{}")) if isinstance(fn.get("arguments"), str) else fn.get("arguments", {}),
                    })
                entry["content"] = blocks
            if m.tool_call_id:
                # Tool result message
                entry["role"] = "user"
                entry["content"] = [{
                    "type":        "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content":     m.content if isinstance(m.content, str) else json.dumps(m.content),
                }]
            out.append(entry)
        return out

    def _build_payload(
        self, messages: List[Message], options: LLMOptions, stream: bool
    ) -> Dict[str, Any]:
        api_messages = self._messages_to_api(messages)
        system_parts = [m for m in messages if m.role == "system"]
        system_text  = (options.system_prompt or "") + " ".join(
            m.content if isinstance(m.content, str) else "" for m in system_parts
        )

        payload: Dict[str, Any] = {
            "model":      options.model,
            "messages":   api_messages,
            "max_tokens": options.max_tokens,
            "stream":     stream,
        }
        if system_text.strip():
            payload["system"] = system_text.strip()
        if options.temperature != 1.0:
            payload["temperature"] = options.temperature

        # Thinking (Extended Thinking for Claude 3.7+ / 4)
        if options.thinking.mode == ThinkingMode.ENABLED:
            payload["thinking"] = {
                "type":         "enabled",
                "budget_tokens": options.thinking.budget_tokens,
            }
            # When thinking is enabled temperature must be 1
            payload["temperature"] = 1.0

        # Tools → Anthropic format
        if options.tools:
            payload["tools"] = [
                {
                    "name":         t.name,
                    "description":  t.description,
                    "input_schema": t.parameters,
                }
                for t in options.tools
            ]

        payload.update(options.extra_params)
        return payload

    def _post(self, payload: Dict[str, Any], stream: bool = False,
              timeout: float = 300.0, extra_betas: Optional[List[str]] = None):
        import requests
        url = f"{self.BASE_URL}/v1/messages"
        return requests.post(url, headers=self._headers(extra_betas),
                             json=payload, stream=stream, timeout=timeout)

    def verify_api_key(self) -> bool:
        if not self._api_key:
            return False
        try:
            payload = {
                "model":      "claude-haiku-4-5",
                "messages":   [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "stream":     False,
            }
            resp = self._post(payload, timeout=10.0)
            return resp.status_code in (200, 400, 529)
        except Exception as exc:
            log.error("AnthropicClient.verify_api_key: %s", exc)
            return False

    def complete(self, messages: List[Message], options: LLMOptions) -> LLMResponse:
        import time
        stripped = self._strip_excess_media(messages)
        max_tok, think_budget = self._cap_tokens(
            options.max_tokens,
            options.thinking.budget_tokens if options.thinking.mode == ThinkingMode.ENABLED else 0,
            MAX_NON_STREAMING_TOKENS,
        )
        opts = LLMOptions(**{**options.__dict__,
                             "max_tokens": max_tok,
                             "thinking": ThinkingConfig(options.thinking.mode, think_budget)})
        payload = self._build_payload(stripped, opts, stream=False)

        start = time.monotonic()
        try:
            resp = self._post(payload, timeout=options.timeout)
            duration_ms = (time.monotonic() - start) * 1000

            if resp.status_code != 200:
                err = resp.text
                return LLMResponse(content="", model=options.model,
                                   provider=Provider.ANTHROPIC, error=err,
                                   finish_reason=FinishReason.ERROR,
                                   duration_ms=duration_ms)

            data   = resp.json()
            blocks = data.get("content", [])
            text   = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            think  = " ".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
            tc     = [
                {"id": b.get("id"), "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input", {}))}}
                for b in blocks if b.get("type") == "tool_use"
            ]
            usage  = data.get("usage", {})
            reason_str = data.get("stop_reason", "end_turn")
            reason_map = {
                "end_turn":    FinishReason.STOP,
                "max_tokens":  FinishReason.MAX_TOKENS,
                "tool_use":    FinishReason.TOOL_USE,
            }
            finish = reason_map.get(reason_str, FinishReason.STOP)

            return LLMResponse(
                content       = text,
                model         = data.get("model", options.model),
                provider      = Provider.ANTHROPIC,
                input_tokens  = usage.get("input_tokens", 0),
                output_tokens = usage.get("output_tokens", 0),
                thinking      = think or None,
                tool_calls    = tc,
                finish_reason = finish,
                duration_ms   = duration_ms,
            )
        except Exception as exc:
            self._last_error = str(exc)
            log.error("AnthropicClient.complete: %s", exc)
            return LLMResponse(content="", model=options.model,
                               provider=Provider.ANTHROPIC, error=str(exc),
                               finish_reason=FinishReason.ERROR)

    def stream(
        self,
        messages: List[Message],
        options: LLMOptions,
        abort_signal: Optional[asyncio.Event] = None,
    ) -> Generator[StreamEvent, None, None]:
        """
        Anthropic SSE streaming.
        Mirrors the event loop in queryModel / executeNonStreamingRequest (claude.ts).
        Event types: message_start, content_block_start, content_block_delta,
                     content_block_stop, message_delta, message_stop.
        """
        stripped = self._strip_excess_media(messages)
        payload  = self._build_payload(stripped, options, stream=True)

        try:
            resp = self._post(payload, stream=True, timeout=options.timeout)

            if resp.status_code != 200:
                yield StreamEvent(type="error", error=resp.text,
                                  finish_reason=FinishReason.ERROR)
                return

            # Track open content blocks
            current_block_type = ""
            current_tool: Dict[str, Any] = {}

            for raw_line in resp.iter_lines():
                if abort_signal and abort_signal.is_set():
                    yield StreamEvent(type="done", finish_reason=FinishReason.ABORTED)
                    resp.close()
                    return

                if not raw_line:
                    continue

                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if line.startswith("event:"):
                    continue
                if not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                try:
                    ev = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                etype = ev.get("type", "")

                if etype == "content_block_start":
                    block = ev.get("content_block", {})
                    current_block_type = block.get("type", "")
                    if current_block_type == "tool_use":
                        current_tool = {
                            "id":       block.get("id", ""),
                            "name":     block.get("name", ""),
                            "args_raw": "",
                        }

                elif etype == "content_block_delta":
                    delta = ev.get("delta", {})
                    dtype = delta.get("type", "")
                    if dtype == "text_delta":
                        yield StreamEvent(type="text_delta",
                                          content=delta.get("text", ""))
                    elif dtype == "thinking_delta":
                        yield StreamEvent(type="thinking_delta",
                                          content=delta.get("thinking", ""))
                    elif dtype == "input_json_delta" and current_block_type == "tool_use":
                        current_tool["args_raw"] += delta.get("partial_json", "")

                elif etype == "content_block_stop":
                    if current_block_type == "tool_use" and current_tool:
                        try:
                            args = json.loads(current_tool["args_raw"]) if current_tool["args_raw"] else {}
                        except json.JSONDecodeError:
                            args = {"_raw": current_tool["args_raw"]}
                        yield StreamEvent(
                            type       = "tool_use",
                            tool_id    = current_tool["id"],
                            tool_name  = current_tool["name"],
                            tool_input = args,
                        )
                        current_tool = {}
                    current_block_type = ""

                elif etype == "message_delta":
                    reason_str = ev.get("delta", {}).get("stop_reason", "")
                    reason_map = {
                        "end_turn":   FinishReason.STOP,
                        "max_tokens": FinishReason.MAX_TOKENS,
                        "tool_use":   FinishReason.TOOL_USE,
                    }
                    finish = reason_map.get(reason_str, FinishReason.STOP)
                    yield StreamEvent(type="done", finish_reason=finish)
                    return

                elif etype == "error":
                    err = ev.get("error", {}).get("message", "Unknown API error")
                    yield StreamEvent(type="error", error=err,
                                      finish_reason=FinishReason.ERROR)
                    return

            yield StreamEvent(type="done", finish_reason=FinishReason.STOP)

        except Exception as exc:
            self._last_error = str(exc)
            log.error("AnthropicClient.stream: %s", exc)
            yield StreamEvent(type="error", error=str(exc),
                              finish_reason=FinishReason.ERROR)


# ═════════════════════════════════════════════════════════════════════════════
# Gemini client (Google Generative AI)
# ═════════════════════════════════════════════════════════════════════════════

class GeminiClient(BaseProviderClient):
    """
    Google Gemini provider client.
    Uses the Gemini REST API (v1beta generateContent / streamGenerateContent).
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str = ""):
        super().__init__(Provider.GEMINI, api_key)

    def _default_env_key(self) -> str:
        return "GEMINI_API_KEY"

    def verify_api_key(self) -> bool:
        if not self._api_key:
            return False
        try:
            import requests
            url = f"{self.BASE_URL}/models?key={self._api_key}"
            resp = requests.get(url, timeout=10)
            return resp.status_code == 200
        except Exception as exc:
            log.error("GeminiClient.verify_api_key: %s", exc)
            return False

    def _convert_messages(
        self, messages: List[Message], options: LLMOptions
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Convert to Gemini contents format. Returns (system_instruction, contents)."""
        system = options.system_prompt or ""
        sys_msgs = [m for m in messages if m.role == "system"]
        if sys_msgs:
            system += "\n".join(m.content if isinstance(m.content, str) else "" for m in sys_msgs)

        contents = []
        for m in messages:
            if m.role == "system":
                continue
            role = "user" if m.role in ("user", "tool") else "model"
            if isinstance(m.content, str):
                parts = [{"text": m.content}]
            else:
                parts = [{"text": json.dumps(m.content)}]
            contents.append({"role": role, "parts": parts})

        return system.strip() or None, contents

    def _build_payload(self, messages: List[Message], options: LLMOptions) -> Dict[str, Any]:
        system_text, contents = self._convert_messages(messages, options)
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": options.max_tokens,
                "temperature":     options.temperature,
            },
        }
        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}
        return payload

    def complete(self, messages: List[Message], options: LLMOptions) -> LLMResponse:
        import time, requests
        stripped = self._strip_excess_media(messages)
        payload  = self._build_payload(stripped, options)
        url = f"{self.BASE_URL}/models/{options.model}:generateContent?key={self._api_key}"

        start = time.monotonic()
        try:
            resp = requests.post(url, json=payload, timeout=options.timeout)
            duration_ms = (time.monotonic() - start) * 1000
            if resp.status_code != 200:
                return LLMResponse(content="", model=options.model,
                                   provider=Provider.GEMINI,
                                   error=resp.text, finish_reason=FinishReason.ERROR,
                                   duration_ms=duration_ms)
            data = resp.json()
            candidate = data.get("candidates", [{}])[0]
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            meta = data.get("usageMetadata", {})
            return LLMResponse(
                content       = text,
                model         = options.model,
                provider      = Provider.GEMINI,
                input_tokens  = meta.get("promptTokenCount", 0),
                output_tokens = meta.get("candidatesTokenCount", 0),
                finish_reason = FinishReason.STOP,
                duration_ms   = duration_ms,
            )
        except Exception as exc:
            self._last_error = str(exc)
            return LLMResponse(content="", model=options.model, provider=Provider.GEMINI,
                               error=str(exc), finish_reason=FinishReason.ERROR)

    def stream(
        self,
        messages: List[Message],
        options: LLMOptions,
        abort_signal: Optional[asyncio.Event] = None,
    ) -> Generator[StreamEvent, None, None]:
        import requests
        stripped = self._strip_excess_media(messages)
        payload  = self._build_payload(stripped, options)
        url = f"{self.BASE_URL}/models/{options.model}:streamGenerateContent?key={self._api_key}&alt=sse"

        try:
            resp = requests.post(url, json=payload, stream=True, timeout=options.timeout)
            if resp.status_code != 200:
                yield StreamEvent(type="error", error=resp.text,
                                  finish_reason=FinishReason.ERROR)
                return

            for raw_line in resp.iter_lines():
                if abort_signal and abort_signal.is_set():
                    yield StreamEvent(type="done", finish_reason=FinishReason.ABORTED)
                    return
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data:"):
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                    parts = chunk.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    for p in parts:
                        if "text" in p:
                            yield StreamEvent(type="text_delta", content=p["text"])
                except json.JSONDecodeError:
                    continue

            yield StreamEvent(type="done", finish_reason=FinishReason.STOP)
        except Exception as exc:
            self._last_error = str(exc)
            yield StreamEvent(type="error", error=str(exc), finish_reason=FinishReason.ERROR)


# ═════════════════════════════════════════════════════════════════════════════
# Unified LLMClient facade
# ═════════════════════════════════════════════════════════════════════════════

class LLMClient:
    """
    Top-level facade used by Cortex IDE components.
    Selects the appropriate provider client based on LLMOptions.provider.

    Usage:
        client = LLMClient()
        for event in client.stream(messages, options):
            if event.type == "text_delta":
                print(event.content, end="", flush=True)
    """

    def __init__(self):
        self._clients: Dict[Provider, BaseProviderClient] = {
            Provider.ANTHROPIC: AnthropicClient(),
            Provider.OPENAI:    OpenAICompatibleClient(Provider.OPENAI),
            Provider.DEEPSEEK:  OpenAICompatibleClient(Provider.DEEPSEEK),
            Provider.GEMINI:    GeminiClient(),
            Provider.GROQ:      OpenAICompatibleClient(Provider.GROQ),
            Provider.MISTRAL:   OpenAICompatibleClient(
                Provider.MISTRAL, base_url="https://api.mistral.ai/v1"
            ),
            Provider.OLLAMA:    OpenAICompatibleClient(Provider.OLLAMA),
        }

    def get_client(self, provider: Provider) -> BaseProviderClient:
        client = self._clients.get(provider)
        if not client:
            raise ValueError(f"Unsupported provider: {provider}")
        return client

    def register_custom(self, api_key: str, base_url: str) -> BaseProviderClient:
        """Register a custom OpenAI-compatible endpoint (e.g. LMStudio, vLLM)."""
        c = OpenAICompatibleClient(Provider.CUSTOM, api_key=api_key, base_url=base_url)
        self._clients[Provider.CUSTOM] = c
        return c

    def stream(
        self,
        messages: List[Message],
        options: LLMOptions,
        abort_signal: Optional[asyncio.Event] = None,
    ) -> Generator[StreamEvent, None, None]:
        """Route streaming request to the correct provider."""
        client = self.get_client(options.provider)
        yield from client.stream(messages, options, abort_signal)

    def complete(self, messages: List[Message], options: LLMOptions) -> LLMResponse:
        """Route non-streaming request to the correct provider."""
        client = self.get_client(options.provider)
        return client.complete(messages, options)

    def verify_api_key(self, provider: Provider) -> bool:
        """Verify API key for a given provider."""
        try:
            return self.get_client(provider).verify_api_key()
        except Exception as exc:
            log.error("verify_api_key(%s): %s", provider, exc)
            return False


# ─── Module-level singleton ───────────────────────────────────────────────────
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Return the shared LLMClient singleton."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
