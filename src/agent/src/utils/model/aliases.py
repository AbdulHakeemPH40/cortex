"""
Model alias definitions for Cortex AI Agent IDE.

Provides friendly shorthand names across ALL supported LLM providers so
users can type 'sonnet' or 'gpt4o' instead of full model IDs in settings.

Supported providers (mirrors Cortex llm_client.py Provider enum):
  - Anthropic  (Claude sonnet / opus / haiku)
  - OpenAI     (GPT-4o, o1, o3)
  - Google     (Gemini)
  - DeepSeek
  - Mistral
  - Groq
  - Ollama     (local)
  - Together AI
  - SiliconFlow

Family aliases act as wildcards in the availableModels allowlist:
  'opus'  → any opus version is allowed (4.5, 4.6, etc.)
  'gpt4'  → any GPT-4 variant is allowed
  A full model ID → only that exact version is allowed.
"""

from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Short aliases → canonical model IDs
# Each entry: alias_string → full_model_id
# ---------------------------------------------------------------------------

ALIAS_MAP: Dict[str, str] = {
    # ── Anthropic ──────────────────────────────────────────────────────────
    'sonnet':       'claude-sonnet-4-20250514',
    'sonnet4':      'claude-sonnet-4-20250514',
    'sonnet35':     'claude-3-5-sonnet-3-20250514',
    'opus':         'claude-opus-4-20250514',
    'opus4':        'claude-opus-4-20250514',
    'haiku':        'claude-3-5-haiku-4-20250514',
    'haiku35':      'claude-3-5-haiku-4-20250514',
    'sonnet[1m]':   'claude-sonnet-4-20250514',   # 1M context variant
    'opus[1m]':     'claude-opus-4-20250514',
    'opusplan':     'claude-opus-4-20250514',      # opus in plan mode

    # ── OpenAI ────────────────────────────────────────────────────────────
    'gpt4o':        'gpt-4o',
    'gpt4omini':    'gpt-4o-mini',
    'gpt4':         'gpt-4',
    'gpt4turbo':    'gpt-4-turbo',
    'gpt35':        'gpt-3.5-turbo',
    'o1':           'o1',
    'o1mini':       'o1-mini',
    'o3':           'o3',
    'o3mini':       'o3-mini',

    # ── OpenAI Codex (code-specialised) ───────────────────────────────────
    'codex':        'codex',
    'codexmini':    'codex-mini-latest',

    # ── Google Gemini ──────────────────────────────────────────────────────
    'gemini':       'gemini-2.0-flash',
    'gemini2':      'gemini-2.0-flash',
    'gemini2lite':  'gemini-2.0-flash-lite',
    'gemini15pro':  'gemini-1.5-pro',
    'gemini15':     'gemini-1.5-flash',

    # ── DeepSeek ──────────────────────────────────────────────────────────
    'deepseek':     'deepseek-chat',
    'deepseekcode': 'deepseek-coder',
    'deepseekr1':   'deepseek-reasoner',

    # ── Mistral (user's preferred alternative to Minimax) ─────────────────
    'mistral':      'mistral-large-latest',
    'mistrallarge': 'mistral-large-latest',
    'mistralsmall': 'mistral-small-latest',
    'codestral':    'codestral-latest',
    'ministral':    'ministral-8b-latest',
    'pixtral':      'pixtral-12b-latest',

    # ── Groq / Meta ───────────────────────────────────────────────────────
    'groq':         'llama-3.3-70b-versatile',
    'llama3':       'llama-3.3-70b-versatile',
    'llama38b':     'llama-3.1-8b-instant',

    # ── Ollama (local) ────────────────────────────────────────────────────
    'ollama':       'llama3',
    'phi3':         'phi3',
    'qwen':         'qwen2.5-coder',

    # ── Together AI ───────────────────────────────────────────────────────
    'together':     'meta-llama/Llama-3-70b-chat-hf',

    # ── SiliconFlow ───────────────────────────────────────────────────────
    'siliconflow':  'Qwen/Qwen2.5-72B-Instruct',
    'qwen72b':      'Qwen/Qwen2.5-72B-Instruct',

    # ── Kimi/Moonshot AI ──────────────────────────────────────────────────
    'kimi':         'kimi-k2.6',
    'kimik26':      'kimi-k2.6',
    'moonshot':     'kimi-k2.6',

    # ── Smart aliases (provider-agnostic) ─────────────────────────────────
    'best':         'claude-opus-4-20250514',     # best available model
    'fast':         'claude-3-5-haiku-4-20250514', # fastest/cheapest
    'code':         'deepseek-coder',              # best for coding tasks
    'local':        'llama3',                      # local model via Ollama
}

# Flat tuple of all recognised alias strings (for validation)
MODEL_ALIASES: Tuple[str, ...] = tuple(ALIAS_MAP.keys())

# Type alias
ModelAlias = str


# ---------------------------------------------------------------------------
# Family aliases — bare wildcards for allowlists
# ---------------------------------------------------------------------------
# When a family alias is in the allowlist, ANY model from that family is
# permitted regardless of version. A full model ID restricts to exact version.

MODEL_FAMILY_ALIASES: Tuple[str, ...] = (
    # Anthropic families
    'sonnet', 'opus', 'haiku',
    # OpenAI families
    'gpt4o', 'gpt4', 'o1', 'o3',
    # Google families
    'gemini',
    # DeepSeek families
    'deepseek',
    # Mistral families
    'mistral', 'codestral',
    # Groq / Meta families
    'llama3', 'groq',
    # Local
    'ollama',
    # Kimi/Moonshot AI families
    'kimi',
)


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def isModelAlias(modelInput: str) -> bool:
    """
    Check if a string is a recognised model alias.

    Args:
        modelInput: User-supplied string (e.g. 'sonnet', 'gpt4o', 'deepseek')

    Returns:
        True if modelInput matches any entry in ALIAS_MAP
    """
    return modelInput in ALIAS_MAP


def isModelFamilyAlias(model: str) -> bool:
    """
    Check if a string is a bare model-family wildcard alias.

    Args:
        model: String to check (e.g. 'opus', 'gpt4', 'gemini')

    Returns:
        True if model is a family-level wildcard
    """
    return model in MODEL_FAMILY_ALIASES


def resolveAlias(alias: str) -> Optional[str]:
    """
    Resolve a short alias to its canonical model ID.

    Args:
        alias: Short alias string (e.g. 'sonnet', 'gpt4o', 'deepseek')

    Returns:
        Full model ID string, or None if alias is not recognised

    Example:
        resolveAlias('sonnet')  → 'claude-sonnet-4-20250514'
        resolveAlias('gpt4o')   → 'gpt-4o'
        resolveAlias('unknown') → None
    """
    return ALIAS_MAP.get(alias)


def resolveOrPassthrough(modelInput: str) -> str:
    """
    Resolve alias to full model ID, or return the input unchanged if it is
    already a full model ID (not an alias).

    Args:
        modelInput: Alias or full model ID

    Returns:
        Canonical model ID

    Example:
        resolveOrPassthrough('sonnet')                 → 'claude-sonnet-4-20250514'
        resolveOrPassthrough('claude-opus-4-20250514') → 'claude-opus-4-20250514'
    """
    return ALIAS_MAP.get(modelInput, modelInput)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    'ALIAS_MAP',
    'MODEL_ALIASES',
    'ModelAlias',
    'MODEL_FAMILY_ALIASES',
    'isModelAlias',
    'isModelFamilyAlias',
    'resolveAlias',
    'resolveOrPassthrough',
]
