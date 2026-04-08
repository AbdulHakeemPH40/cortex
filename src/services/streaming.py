"""
Streaming Event Loop for Cortex IDE
Extracted from claude-code-main/src/services/api/claude.ts

Provides the async generator loop that:
  1. Feeds messages to an LLMClient provider
  2. Emits PyQt6 signals for real-time UI updates (tokens, tool calls, errors)
  3. Handles abort (cancel button) via asyncio.Event

Mirrors: queryModelWithStreaming, executeNonStreamingRequest, cleanupStream
"""

from __future__ import annotations

import asyncio
import threading
from typing import Callable, Generator, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.services.llm_client import (
    LLMClient, LLMOptions, LLMResponse, Message, Provider,
    StreamEvent, FinishReason, get_llm_client,
)
from src.services.usage_tracker import UsageTracker, get_usage_tracker
from src.utils.logger import get_logger

log = get_logger("streaming")


# ═════════════════════════════════════════════════════════════════════════════
# PyQt6 worker — runs streaming in a QThread so the UI stays responsive
# ═════════════════════════════════════════════════════════════════════════════

class StreamWorker(QObject):
    """
    Runs LLMClient.stream() in a background QThread.
    Emits signals for every event type so any GUI widget can connect.

    Signal contract mirrors StreamingEventEmitter in src/ai/streaming.py but
    adds tool_call and thinking events from claude.ts streaming.
    """

    # Signals
    token_received   = pyqtSignal(str)               # text delta
    thinking_received = pyqtSignal(str)              # extended thinking delta
    tool_call_ready  = pyqtSignal(str, str, dict)    # tool_id, tool_name, args
    stream_done      = pyqtSignal(str)               # finish_reason value
    stream_error     = pyqtSignal(str)               # error message
    usage_updated    = pyqtSignal(int, int)          # input_tokens, output_tokens

    def __init__(
        self,
        messages:      List[Message],
        options:       LLMOptions,
        client:        Optional[LLMClient] = None,
        tracker:       Optional[UsageTracker] = None,
    ):
        super().__init__()
        self._messages   = messages
        self._options    = options
        self._client     = client or get_llm_client()
        self._tracker    = tracker or get_usage_tracker()
        self._abort      = asyncio.Event()
        self._cancelled  = False

    def cancel(self):
        """Call from the UI thread to abort the in-progress stream."""
        self._cancelled = True
        self._abort.set()
        log.info("Stream cancelled by user")

    def run(self):
        """Entry point called by QThread.started signal."""
        try:
            self._run_stream()
        except Exception as exc:
            log.error("StreamWorker.run unhandled: %s", exc)
            self.stream_error.emit(str(exc))

    def _run_stream(self):
        log.info("Starting stream → provider=%s model=%s",
                 self._options.provider.value, self._options.model)
        input_tok = 0
        output_tok = 0

        for event in self._client.stream(self._messages, self._options, self._abort):
            if self._cancelled:
                break

            if event.type == "text_delta":
                self.token_received.emit(event.content)
                output_tok += _estimate_tokens(event.content)

            elif event.type == "thinking_delta":
                self.thinking_received.emit(event.content)

            elif event.type == "tool_use":
                self.tool_call_ready.emit(
                    event.tool_id, event.tool_name, event.tool_input
                )

            elif event.type == "done":
                reason = event.finish_reason.value if event.finish_reason else "stop"
                self.stream_done.emit(reason)
                break

            elif event.type == "error":
                log.error("Stream error event: %s", event.error)
                self.stream_error.emit(event.error or "Unknown stream error")
                break

        # Update usage tracker
        if input_tok or output_tok:
            self._tracker.record(
                provider   = self._options.provider.value,
                model      = self._options.model,
                input_tok  = input_tok,
                output_tok = output_tok,
            )
            self.usage_updated.emit(input_tok, output_tok)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token. Used for streaming output counting."""
    return max(1, len(text) // 4)


# ═════════════════════════════════════════════════════════════════════════════
# QThread launcher
# ═════════════════════════════════════════════════════════════════════════════

class StreamSession(QObject):
    """
    Manages the lifecycle of a single streaming session.
    Creates a QThread + StreamWorker pair and exposes their signals.

    Usage:
        session = StreamSession(messages, options)
        session.token_received.connect(my_widget.append_token)
        session.stream_done.connect(my_widget.on_done)
        session.start()
        # ...
        session.cancel()   # stop early
    """

    token_received   = pyqtSignal(str)
    thinking_received = pyqtSignal(str)
    tool_call_ready  = pyqtSignal(str, str, dict)
    stream_done      = pyqtSignal(str)
    stream_error     = pyqtSignal(str)
    usage_updated    = pyqtSignal(int, int)

    def __init__(
        self,
        messages: List[Message],
        options:  LLMOptions,
        client:   Optional[LLMClient] = None,
    ):
        super().__init__()
        self._thread = QThread()
        self._worker = StreamWorker(messages, options, client)
        self._worker.moveToThread(self._thread)

        # Wire worker signals → session signals (pass-through)
        self._worker.token_received.connect(self.token_received)
        self._worker.thinking_received.connect(self.thinking_received)
        self._worker.tool_call_ready.connect(self.tool_call_ready)
        self._worker.stream_done.connect(self.stream_done)
        self._worker.stream_error.connect(self.stream_error)
        self._worker.usage_updated.connect(self.usage_updated)

        # Lifecycle
        self._thread.started.connect(self._worker.run)
        self._worker.stream_done.connect(self._thread.quit)
        self._worker.stream_error.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)

    def start(self):
        """Start the background thread."""
        self._thread.start()

    def cancel(self):
        """Abort the stream and stop the thread."""
        self._worker.cancel()


# ═════════════════════════════════════════════════════════════════════════════
# Synchronous (non-streaming) completion
# ═════════════════════════════════════════════════════════════════════════════

def complete_sync(
    messages: List[Message],
    options:  LLMOptions,
    client:   Optional[LLMClient] = None,
    tracker:  Optional[UsageTracker] = None,
) -> LLMResponse:
    """
    Non-streaming completion helper.
    Mirrors queryModelWithoutStreaming in claude.ts:709.
    Blocks the calling thread — use StreamSession for UI contexts.
    """
    c = client or get_llm_client()
    t = tracker or get_usage_tracker()
    resp = c.complete(messages, options)
    if resp.input_tokens or resp.output_tokens:
        t.record(
            provider   = options.provider.value,
            model      = options.model,
            input_tok  = resp.input_tokens,
            output_tok = resp.output_tokens,
            cost_usd   = _calc_cost(options.model, resp.input_tokens, resp.output_tokens),
        )
    return resp


def _calc_cost(model: str, input_tok: int, output_tok: int) -> float:
    """
    Rough cost estimate in USD.
    Mirrors calculateUSDCost from utils/modelCost.ts.
    Rates are approximate — update as pricing changes.
    """
    RATES: dict = {
        # model_prefix: (input_per_1k, output_per_1k)
        "claude-opus":    (0.015, 0.075),
        "claude-sonnet":  (0.003, 0.015),
        "claude-haiku":   (0.00025, 0.00125),
        "gpt-4o":         (0.005, 0.015),
        "gpt-4o-mini":    (0.00015, 0.0006),
        "deepseek-reasoner": (0.00055, 0.00219),
        "deepseek-chat":  (0.00027, 0.0011),
        "gemini-1.5-pro": (0.00125, 0.005),
        "gemini-2.0":     (0.000035, 0.000105),
        "mistral-large":  (0.004, 0.012),
    }
    for prefix, (inp, out) in RATES.items():
        if model.lower().startswith(prefix):
            return (input_tok / 1000) * inp + (output_tok / 1000) * out
    return 0.0
