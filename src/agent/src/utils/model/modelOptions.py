"""
Model picker options generator for Cortex AI Agent IDE.

Generates user-friendly model options for the model selector UI with:
- Human-readable labels
- Descriptions with use cases
- Pricing information
- Default recommendations
- Allowlist filtering (integrates with modelAllowlist.py)

Multi-LLM support for all Cortex IDE providers:
  - Anthropic (Claude)
  - OpenAI (GPT, o1, o3, Codex)
  - Google Gemini
  - DeepSeek
  - Mistral
  - Groq
  - Ollama
"""

from typing import List, Optional, TypedDict

try:
    from .modelAllowlist import isModelAllowed
except ImportError:
    from modelAllowlist import isModelAllowed

# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------


class ModelOption(TypedDict):
    """Model option for UI picker."""
    value: str
    label: str
    description: str
    category: str  # 'recommended', 'coding', 'budget', 'local'


# ---------------------------------------------------------------------------
# Model pricing data (per 1M tokens)
# ---------------------------------------------------------------------------

MODEL_PRICING = {
    # Anthropic
    'cortex-opus-4-6': {'input': 15.0, 'output': 75.0, 'currency': 'USD'},
    'cortex-sonnet-4-20250514': {'input': 3.15, 'output': 15.75, 'currency': 'USD'},
    'cortex-3-5-haiku-4-20250514': {'input': 0.80, 'output': 4.0, 'currency': 'USD'},
    # OpenAI
    'gpt-4o': {'input': 2.50, 'output': 10.0, 'currency': 'USD'},
    'gpt-4o-mini': {'input': 0.15, 'output': 0.60, 'currency': 'USD'},
    'o3': {'input': 10.0, 'output': 40.0, 'currency': 'USD'},
    'codex': {'input': 5.0, 'output': 15.0, 'currency': 'USD'},
    # Gemini
    'gemini-2.0-flash': {'input': 0.10, 'output': 0.40, 'currency': 'USD'},
    'gemini-2.0-flash-lite': {'input': 0.075, 'output': 0.30, 'currency': 'USD'},
    # DeepSeek V4 Models (NEW)
    'deepseek-v4-pro': {'input': 0.50, 'output': 2.00, 'cache': 0.10, 'currency': 'USD'},
    'deepseek-v4-flash': {'input': 0.10, 'output': 0.50, 'cache': 0.02, 'currency': 'USD'},
    # DeepSeek Legacy (deprecated Jul 24, 2026)
    'deepseek-chat': {'input': 0.27, 'output': 1.10, 'currency': 'USD'},
    'deepseek-coder': {'input': 0.27, 'output': 1.10, 'currency': 'USD'},
    'deepseek-reasoner': {'input': 0.55, 'output': 2.19, 'currency': 'USD'},
    # Mistral
    'mistral-large-latest': {'input': 2.0, 'output': 6.0, 'currency': 'USD'},
    'codestral-latest': {'input': 0.30, 'output': 0.90, 'currency': 'USD'},
    # Groq (free tier available)
    'llama-3.3-70b-versatile': {'input': 0.59, 'output': 0.79, 'currency': 'USD'},
    # Kimi/Moonshot AI (K2.6)
    'kimi-k2.6': {'input': 0.95, 'output': 4.00, 'cache_hit': 0.16, 'currency': 'USD'},
}


def formatPricing(modelId: str) -> str:
    """
    Format model pricing for display.

    Args:
        modelId: Full model ID

    Returns:
        Pricing string or empty string if not found

    Example:
        formatPricing('cortex-sonnet-4-20250514')
        → '$3.15/M input · $15.75/M output'
    """
    pricing = MODEL_PRICING.get(modelId)
    if not pricing:
        return ''

    currency = pricing.get('currency', 'USD')
    symbol = {'USD': '$', 'EUR': '€', 'GBP': '£'}.get(currency, currency)

    inputPrice = pricing.get('input', 0)
    outputPrice = pricing.get('output', 0)

    return f'{symbol}{inputPrice:.2f}/M input · {symbol}{outputPrice:.2f}/M output'


# ---------------------------------------------------------------------------
# Model option generators
# ---------------------------------------------------------------------------

def getDefaultOption() -> ModelOption:
    """
    Get the default recommended model option.

    Returns:
        ModelOption for the recommended default (Cortex Sonnet)

    Example:
        getDefaultOption()
        → {
            'value': 'sonnet',
            'label': 'Cortex Sonnet 4.6',
            'description': 'Best for everyday coding tasks · $3.15/M input · $15.75/M output',
            'category': 'recommended'
          }
    """
    return {
        'value': 'sonnet',
        'label': 'Cortex Sonnet 4.6',
        'description': 'Best for everyday coding tasks',
        'category': 'recommended',
    }


def getOpusOption() -> ModelOption:
    """Get Cortex Opus option for complex tasks."""
    pricing = formatPricing('cortex-opus-4-6')
    return {
        'value': 'opus',
        'label': 'Cortex Opus 4.6',
        'description': f'Most capable for complex work{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


def getHaikuOption() -> ModelOption:
    """Get Cortex Haiku option for fast, cheap responses."""
    pricing = formatPricing('cortex-3-5-haiku-4-20250514')
    return {
        'value': 'haiku',
        'label': 'Cortex Haiku 4.5',
        'description': f'Fastest for quick answers{f" · {pricing}" if pricing else ""}',
        'category': 'budget',
    }


def getGPT4oOption() -> ModelOption:
    """Get GPT-4o option."""
    pricing = formatPricing('gpt-4o')
    return {
        'value': 'gpt4o',
        'label': 'GPT-4o',
        'description': f'Great all-around model{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


def getGPT4oMiniOption() -> ModelOption:
    """Get GPT-4o Mini option for budget usage."""
    pricing = formatPricing('gpt-4o-mini')
    return {
        'value': 'gpt4o-mini',
        'label': 'GPT-4o Mini',
        'description': f'Budget-friendly{f" · {pricing}" if pricing else ""}',
        'category': 'budget',
    }


def getO3Option() -> ModelOption:
    """Get OpenAI o3 option for advanced reasoning."""
    pricing = formatPricing('o3')
    return {
        'value': 'o3',
        'label': 'OpenAI o3',
        'description': f'Advanced reasoning{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


def getCodexOption() -> ModelOption:
    """Get OpenAI Codex option for code generation."""
    pricing = formatPricing('codex')
    return {
        'value': 'codex',
        'label': 'OpenAI Codex',
        'description': f'Best for code generation{f" · {pricing}" if pricing else ""}',
        'category': 'coding',
    }


def getGemini2FlashOption() -> ModelOption:
    """Get Gemini 2.0 Flash option with 1M context."""
    pricing = formatPricing('gemini-2.0-flash')
    return {
        'value': 'gemini2flash',
        'label': 'Gemini 2.0 Flash',
        'description': f'Fast with 1M context window{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


def getDeepSeekChatOption() -> ModelOption:
    """Get DeepSeek Chat option (Legacy)."""
    pricing = formatPricing('deepseek-chat')
    return {
        'value': 'deepseekchat',
        'label': 'DeepSeek Chat V3 (Legacy)',
        'description': f'Cost-effective general model (deprecated Jul 2026){f" · {pricing}" if pricing else ""}',
        'category': 'budget',
    }


def getDeepSeekV4ProOption() -> ModelOption:
    """Get DeepSeek V4 Pro option - World-class performance."""
    pricing = formatPricing('deepseek-v4-pro')
    return {
        'value': 'deepseekv4pro',
        'label': 'DeepSeek V4 Pro',
        'description': f'1.6T params, 1M context, world-class performance{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


def getDeepSeekV4FlashOption() -> ModelOption:
    """Get DeepSeek V4 Flash option - Fast and cost-effective."""
    pricing = formatPricing('deepseek-v4-flash')
    return {
        'value': 'deepseekv4flash',
        'label': 'DeepSeek V4 Flash',
        'description': f'284B params, 1M context, fast & efficient{f" · {pricing}" if pricing else ""}',
        'category': 'budget',
    }


def getDeepSeekCoderOption() -> ModelOption:
    """Get DeepSeek Coder option."""
    pricing = formatPricing('deepseek-coder')
    return {
        'value': 'deepseekcode',
        'label': 'DeepSeek Coder',
        'description': f'Open-source coding model{f" · {pricing}" if pricing else ""}',
        'category': 'coding',
    }


def getMistralLargeOption() -> ModelOption:
    """Get Mistral Large option."""
    pricing = formatPricing('mistral-large-latest')
    return {
        'value': 'mistrallarge',
        'label': 'Mistral Large',
        'description': f'European alternative{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


def getCodestralOption() -> ModelOption:
    """Get Mistral Codestral option for coding."""
    pricing = formatPricing('codestral-latest')
    return {
        'value': 'codestral',
        'label': 'Mistral Codestral',
        'description': f'Code-specialized model{f" · {pricing}" if pricing else ""}',
        'category': 'coding',
    }


def getGroqLlamaOption() -> ModelOption:
    """Get Groq Llama 3 option for ultra-fast inference."""
    pricing = formatPricing('llama-3.3-70b-versatile')
    return {
        'value': 'llama3groq',
        'label': 'Groq Llama 3 70B',
        'description': f'Ultra-fast inference{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


def getOllamaOption() -> ModelOption:
    """Get Ollama local model option."""
    return {
        'value': 'ollama_llama3',
        'label': 'Ollama Llama 3 (Local)',
        'description': 'Run locally, no API cost, fully private',
        'category': 'local',
    }


def getKimiK26Option() -> ModelOption:
    """Get Kimi K2.6 option - Multimodal model from Moonshot AI."""
    pricing = formatPricing('kimi-k2.6')
    return {
        'value': 'kimik26',
        'label': 'Kimi K2.6 (Multimodal)',
        'description': f'Moonshot AI flagship, 256k context, code+vision{f" · {pricing}" if pricing else ""}',
        'category': 'recommended',
    }


# ---------------------------------------------------------------------------
# Main option generator
# ---------------------------------------------------------------------------

def getModelOptions(
    availableModels: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
) -> List[ModelOption]:
    """
    Generate complete model picker option list for Cortex IDE.

    Args:
        availableModels: Optional allowlist from settings (None = all models)
        categories: Optional category filter (e.g., ['recommended', 'coding'])

    Returns:
        List of ModelOption dicts for UI picker

    Example:
        getModelOptions()
        → [
            {'value': 'sonnet', 'label': 'Cortex Sonnet 4.6', ...},
            {'value': 'gpt4o', 'label': 'GPT-4o', ...},
            ...
          ]

        getModelOptions(categories=['coding'])
        → [Codex, DeepSeek Coder, Codestral options]
    """
    options: List[ModelOption] = [
        # ── Recommended defaults ──────────────────────────────────────
        getDefaultOption(),
        getOpusOption(),
        getGPT4oOption(),
        getGemini2FlashOption(),
        
        # ── DeepSeek V4 Models (NEW) ─────────────────────────────────
        getDeepSeekV4ProOption(),
        getDeepSeekV4FlashOption(),

        # ── Advanced reasoning ────────────────────────────────────────
        getO3Option(),

        # ── Coding specialized ────────────────────────────────────────
        getCodexOption(),
        getDeepSeekCoderOption(),
        getCodestralOption(),

        # ── Budget-friendly ───────────────────────────────────────────
        getHaikuOption(),
        getGPT4oMiniOption(),
        getDeepSeekChatOption(),

        # ── European/Alternative ──────────────────────────────────────
        getMistralLargeOption(),

        # ── Kimi/Moonshot AI ──────────────────────────────────────────
        getKimiK26Option(),

        # ── Ultra-fast ────────────────────────────────────────────────
        getGroqLlamaOption(),

        # ── Local/Private ─────────────────────────────────────────────
        getOllamaOption(),
    ]

    # Filter by categories if specified
    if categories:
        options = [opt for opt in options if opt.get('category') in categories]

    # Filter by allowlist if specified
    if availableModels is not None:
        options = filterModelOptionsByAllowlist(options, availableModels)

    return options


def filterModelOptionsByAllowlist(
    options: List[ModelOption],
    availableModels: List[str],
) -> List[ModelOption]:
    """
    Filter model options by the availableModels allowlist.

    Args:
        options: List of model options to filter
        availableModels: Allowlist from settings

    Returns:
        Filtered list respecting the allowlist

    Example:
        filterModelOptionsByAllowlist(options, ['sonnet', 'gpt4o'])
        → [Sonnet option, GPT-4o option only]
    """
    if not availableModels:
        return options

    return [
        opt for opt in options
        if isModelAllowed(opt['value'], availableModels)
    ]


def getModelOptionByValue(
    value: str,
    availableModels: Optional[List[str]] = None,
) -> Optional[ModelOption]:
    """
    Get a specific model option by its value.

    Args:
        value: Model value to find (e.g., 'sonnet', 'gpt4o')
        availableModels: Optional allowlist

    Returns:
        ModelOption if found, None otherwise

    Example:
        getModelOptionByValue('gpt4o')
        → {'value': 'gpt4o', 'label': 'GPT-4o', 'description': '...', 'category': 'recommended'}
    """
    allOptions = getModelOptions(availableModels)
    for opt in allOptions:
        if opt['value'] == value:
            return opt
    return None


def getCategoryOptions(
    category: str,
    availableModels: Optional[List[str]] = None,
) -> List[ModelOption]:
    """
    Get all model options in a specific category.

    Args:
        category: Category name ('recommended', 'coding', 'budget', 'local')
        availableModels: Optional allowlist

    Returns:
        List of ModelOption in the category

    Example:
        getCategoryOptions('coding')
        → [Codex, DeepSeek Coder, Codestral options]
    """
    return getModelOptions(availableModels, categories=[category])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    'ModelOption',
    'MODEL_PRICING',
    'formatPricing',
    'getDefaultOption',
    'getOpusOption',
    'getHaikuOption',
    'getGPT4oOption',
    'getGPT4oMiniOption',
    'getO3Option',
    'getCodexOption',
    'getGemini2FlashOption',
    'getKimiK26Option',
    'getDeepSeekChatOption',
    'getDeepSeekCoderOption',
    'getMistralLargeOption',
    'getCodestralOption',
    'getGroqLlamaOption',
    'getOllamaOption',
    'getModelOptions',
    'filterModelOptionsByAllowlist',
    'getModelOptionByValue',
    'getCategoryOptions',
]
