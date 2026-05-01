"""
model_limits.py
---------------
Multi-LLM model context-window registry for Cortex IDE.

Provides get_model_limits(model_id) which returns a ModelLimits dataclass with:
  - context_window    : total input context window (tokens)
  - max_output_tokens : safe max generation tokens for this model
  - max_tool_result_chars : per-tool-result character cap  (≈ 5 % of context)
  - max_hist_chars        : per-history-message character cap (≈ 8 % of context)
  - max_turns             : agentic loop turn limit (scales with context budget)

All downstream constants in agent_bridge.py are derived from these values so that
every supported LLM is handled gracefully without hardcoded magic numbers.

Supported families (auto-detected by model_id substring matching):
  DeepSeek · OpenAI / GPT / o-series · Claude · Mistral / Codestral
  Gemini · Qwen / SiliconFlow · Llama · Cohere · Yi
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple
import os

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ModelLimits:
    """Context-budget limits for a specific LLM model."""

    model_id:            str
    context_window:      int   # tokens
    max_output_tokens:   int   # tokens

    # Derived — computed by _derive() after construction
    max_tool_result_chars: int = field(init=False)
    max_hist_chars:        int = field(init=False)
    max_turns:             int = field(init=False)
    max_file_read_chars:   int = field(init=False)  # Single file read limit
    max_file_read_bytes:   int = field(init=False)  # Single file read limit in bytes
    context_budget:        int = field(init=False)  # Available tokens for tools/history

    def __post_init__(self) -> None:
        self._derive()

    def _derive(self) -> None:
        """
        Budget allocation (all figures in tokens, converted to chars at 4 ch/tok):

          system_prompt_reserve  =   2 000 tokens  (fixed overhead)
          output_reserve         =   max_output_tokens
          budget                 =   context_window - system_prompt_reserve - output_reserve

          tool_results_share     =  30 % of budget  (up to 8 calls / turn)
          history_share          =  40 % of budget  (up to 20 messages)
          file_read_share        =  15 % of budget  (single file max)

          per_tool_result cap    =  tool_results_share / 6        (comfortable headroom)
          per_hist_message cap   =  history_share     / 10
          per_file_read cap      =  file_read_share (single file)

        Hard floors/ceilings are applied so tiny models still work and huge
        models don't allow impractically large slices.
        """
        CHARS_PER_TOKEN = 4
        SYSTEM_RESERVE  = 2_000          # tokens

        budget_tokens = max(
            1_000,
            self.context_window - SYSTEM_RESERVE - self.max_output_tokens,
        )
        self.context_budget = budget_tokens

        # --- Tool result cap -------------------------------------------------
        tool_share_tokens = int(budget_tokens * 0.30)
        raw_tool_chars    = (tool_share_tokens // 6) * CHARS_PER_TOKEN
        self.max_tool_result_chars = max(4_000, min(raw_tool_chars, 60_000))

        # --- History message cap ---------------------------------------------
        hist_share_tokens = int(budget_tokens * 0.40)
        raw_hist_chars    = (hist_share_tokens // 10) * CHARS_PER_TOKEN
        self.max_hist_chars = max(3_000, min(raw_hist_chars, 40_000))

        # --- File read cap (CRITICAL for context overflow prevention) --------
        # Single file should never exceed 15% of budget
        # This prevents reading a 100KB file that blows up context
        file_share_tokens = int(budget_tokens * 0.15)
        raw_file_chars    = file_share_tokens * CHARS_PER_TOKEN
        # Floor: 8KB (enough for small files), Ceiling: 100KB (reasonable limit)
        self.max_file_read_chars = max(8_000, min(raw_file_chars, 100_000))
        self.max_file_read_bytes = self.max_file_read_chars * CHARS_PER_TOKEN

        # --- Agentic turn limit ----------------------------------------------
        # Larger context → agent can afford more tool-call round-trips
        # BUT we cap it to prevent analysis paralysis (especially for DeepSeek)
        if self.context_window >= 200_000:
            self.max_turns = 15  # Reduced from 40 to prevent endless loops
        elif self.context_window >= 100_000:
            self.max_turns = 30
        elif self.context_window >= 32_000:
            self.max_turns = 20
        else:
            self.max_turns = 12

    def __repr__(self) -> str:
        return (
            f"ModelLimits(model={self.model_id!r}, "
            f"ctx={self.context_window:,}, "
            f"out={self.max_output_tokens:,}, "
            f"tool_cap={self.max_tool_result_chars:,} chars, "
            f"hist_cap={self.max_hist_chars:,} chars, "
            f"file_cap={self.max_file_read_chars:,} chars, "
            f"turns={self.max_turns})"
        )


# ---------------------------------------------------------------------------
# Model registry
# Each entry: (substring_pattern, context_window_tokens, max_output_tokens)
# Patterns are tested in order; first match wins.
# ---------------------------------------------------------------------------

def _deepseek_max_output_tokens() -> int:
    """Configurable DeepSeek output cap (default: 16384, override via env)."""
    raw = os.environ.get("CORTEX_DEEPSEEK_MAX_OUTPUT_TOKENS", "16384")
    try:
        parsed = int(raw)
        if parsed > 0:
            return parsed
    except Exception:
        pass
    return 16_384


_DEEPSEEK_MAX_OUTPUT_TOKENS = _deepseek_max_output_tokens()

# fmt: off
_REGISTRY: List[Tuple[str, int, int]] = [

    # ── DeepSeek V4 / legacy aliases ─────────────────────────────────────────
    # DeepSeek V4 supports 1M context. We apply tiered caps by model power:
    # Pro/Reasoner get larger windows, Flash stays tighter for responsiveness.
    ("deepseek-v4-pro",       400_000, _DEEPSEEK_MAX_OUTPUT_TOKENS),
    ("deepseek-v4-flash",     220_000, _DEEPSEEK_MAX_OUTPUT_TOKENS),
    ("deepseek-chat",         300_000, _DEEPSEEK_MAX_OUTPUT_TOKENS),  # currently routed to V4 tier
    ("deepseek-reasoner",     420_000, _DEEPSEEK_MAX_OUTPUT_TOKENS),  # currently routed to V4 tier
    ("deepseek",              260_000, _DEEPSEEK_MAX_OUTPUT_TOKENS),  # generic DeepSeek fallback

    # ── OpenAI GPT-5.x Series (Frontier) ───────────────────────────────────
    ("gpt-5.4-nano",         400_000, 128_000),
    ("gpt-5.4-mini",         400_000, 128_000),
    ("gpt-5.4",            1_000_000, 128_000),
    ("gpt-5.1-codex-mini",  200_000,  32_000),
    ("gpt-5.1-codex",       200_000,  32_000),
    ("gpt-5",               200_000,  32_000),   # generic gpt-5 fallback

    # ── OpenAI GPT-4.1 Series ─────────────────────────────────────────
    ("gpt-4.1-nano",       1_000_000, 128_000),
    ("gpt-4.1-mini",       1_000_000, 128_000),
    ("gpt-4.1",            1_000_000, 128_000),

    # ── OpenAI GPT-4o ────────────────────────────────────────────────────────
    ("gpt-4o-mini",          128_000,  16_000),
    ("gpt-4o",               128_000,  16_000),

    # ── OpenAI GPT-4 Turbo ───────────────────────────────────────────────────
    ("gpt-4-turbo",          128_000,   4_096),
    ("gpt-4-32k",             32_000,   4_096),
    ("gpt-4",                  8_192,   4_096),

    # ── OpenAI GPT-3.5 ───────────────────────────────────────────────────────
    ("gpt-3.5-turbo-16k",     16_384,   4_096),
    ("gpt-3.5-turbo",         16_384,   4_096),
    ("gpt-3.5",               16_384,   4_096),

    # ── OpenAI o-series (reasoning models) ───────────────────────────────────
    ("o3-mini",              200_000, 100_000),
    ("o3",                   200_000, 100_000),
    ("o1-mini",              128_000,  65_536),
    ("o1-preview",           128_000,  32_768),
    ("o1",                   200_000, 100_000),

    # ── OpenAI GPT-5 (next-gen) ───────────────────────────────────────────────
    # (Specific gpt-5.x entries are in the GPT-5.x section above)

    # ── OpenAI Codex ─────────────────────────────────────────────────────────
    ("codex",                200_000,  32_000),

    # ── Anthropic Claude 3.x ─────────────────────────────────────────────────
    ("claude-3-5-haiku",     200_000,   8_192),
    ("claude-3-5-sonnet",    200_000,   8_192),
    ("claude-3-7-sonnet",    200_000,  32_000),
    ("claude-3-opus",        200_000,   4_096),
    ("claude-3-haiku",       200_000,   4_096),
    ("claude-3-sonnet",      200_000,   4_096),

    # ── Anthropic Claude 4.x ─────────────────────────────────────────────────
    ("claude-sonnet-4-6",    200_000,  32_000),
    ("claude-sonnet-4-5",    200_000,  32_000),
    ("claude-sonnet-4",      200_000,  32_000),
    ("claude-opus-4-6",      200_000,  32_000),
    ("claude-opus-4",        200_000,  32_000),
    ("claude-haiku-4",       200_000,  16_000),
    ("claude",               200_000,   8_192),   # generic claude fallback

    # ── Mistral ──────────────────────────────────────────────────────────────
    ("mistral-large",        128_000,   4_096),
    ("mistral-medium",       128_000,   4_096),
    ("mistral-small",         32_000,   4_096),
    ("mistral-7b",            32_000,   4_096),
    ("codestral",             32_000,   4_096),
    ("mixtral-8x22b",         65_536,   4_096),
    ("mixtral-8x7b",          32_768,   4_096),
    ("mistral",               128_000,   4_096),   # generic mistral fallback

    # ── Google Gemini ─────────────────────────────────────────────────────────
    ("gemini-2.5",          1_000_000,  65_536),
    ("gemini-2.0-flash",    1_000_000,   8_192),
    ("gemini-1.5-pro",      1_000_000,   8_192),
    ("gemini-1.5-flash",    1_000_000,   8_192),
    ("gemini-1.0-pro",        32_768,   2_048),
    ("gemini",                32_768,   2_048),   # generic gemini fallback

    # ── Qwen / SiliconFlow / Alibaba ─────────────────────────────────────────
    ("qwen2.5-72b",          131_072,   8_192),
    ("qwen2.5-coder",        131_072,   8_192),
    ("qwen2.5",              131_072,   8_192),
    ("qwen-max",              32_000,   8_192),
    ("qwen-plus",            131_072,   8_192),
    ("qwen-turbo",            32_000,   2_048),
    ("qwen",                  32_000,   2_048),   # generic qwen fallback

    # ── Meta Llama ───────────────────────────────────────────────────────────
    ("llama-3.3-70b",        131_072,   8_192),
    ("llama-3.2",            131_072,   4_096),
    ("llama-3.1",            131_072,   4_096),
    ("llama-3",               8_192,   2_048),
    ("llama-2",               4_096,   2_048),
    ("llama",                 8_192,   2_048),    # generic llama fallback

    # ── Cohere ───────────────────────────────────────────────────────────────
    ("command-r-plus",       128_000,   4_000),
    ("command-r",            128_000,   4_000),
    ("command",               4_096,   4_000),

    # ── Yi ────────────────────────────────────────────────────────────────────
    ("yi-large",             200_000,   4_096),
    ("yi-medium",             16_000,   4_096),
    ("yi",                   200_000,   4_096),

    # ── SiliconFlow generic ───────────────────────────────────────────────────
    ("pro/deepseek",         128_000,   8_000),
    ("free/deepseek",        128_000,   8_000),
]
# fmt: on

# ---------------------------------------------------------------------------
# Safe default for unknown models
# ---------------------------------------------------------------------------

_DEFAULT_LIMITS = ModelLimits(
    model_id="unknown",
    context_window=128_000,
    max_output_tokens=8_192,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_model_limits(model_id: str) -> ModelLimits:
    """
    Return ModelLimits for the given model_id.

    Matching is case-insensitive substring search through _REGISTRY in order.
    Falls back to a 32 K / 4 K default for unknown models.

    Usage::

        limits = get_model_limits("mistral-large-latest")
        response = provider.chat_stream(
            messages,
            model=model_id,
            max_tokens=limits.max_output_tokens,
            ...
        )
        # In _execute_single_tool:
        if len(result_str) > limits.max_tool_result_chars:
            result_str = result_str[:limits.max_tool_result_chars] + "... [truncated]"
    """
    if not model_id:
        return _DEFAULT_LIMITS

    needle = model_id.lower()
    for pattern, ctx_window, max_out in _REGISTRY:
        if pattern in needle:
            return ModelLimits(
                model_id=model_id,
                context_window=ctx_window,
                max_output_tokens=max_out,
            )

    return ModelLimits(
        model_id=model_id,
        context_window=_DEFAULT_LIMITS.context_window,
        max_output_tokens=_DEFAULT_LIMITS.max_output_tokens,
    )


# ---------------------------------------------------------------------------
# Convenience helper — useful for logging / diagnostics
# ---------------------------------------------------------------------------

def describe_model_limits(model_id: str) -> str:
    """Return a one-line human-readable summary of the model's limits."""
    lim = get_model_limits(model_id)
    return (
        f"{lim.model_id}: ctx={lim.context_window // 1_000}K tokens, "
        f"out={lim.max_output_tokens:,} tokens, "
        f"tool_cap={lim.max_tool_result_chars // 1_000}K chars, "
        f"hist_cap={lim.max_hist_chars // 1_000}K chars, "
        f"turns={lim.max_turns}"
    )
