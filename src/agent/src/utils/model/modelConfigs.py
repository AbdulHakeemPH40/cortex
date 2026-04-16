"""
Model configuration mappings for Cortex AI Agent IDE.

Maps each model to its correct ID across multiple providers.
Supports all 9+ LLM providers in Cortex IDE:
  - Anthropic (Claude)
  - OpenAI (GPT-4o, o1, o3, Codex)
  - Google Gemini
  - DeepSeek
  - Mistral
  - Groq / Meta
  - Ollama (local)
  - Together AI
  - SiliconFlow

Also provides canonical model lists and reverse lookups for settings
validation and persistence.
"""

from typing import Dict, List, Literal, Optional, Tuple

# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

# All supported providers in Cortex IDE
APIProvider = Literal[
    'anthropic',    # Direct Anthropic API
    'bedrock',      # AWS Bedrock
    'vertex',       # Google Vertex AI
    'foundry',      # IBM/Microsoft Foundry
    'openai',       # OpenAI API
    'google',       # Google AI Studio
    'deepseek',     # DeepSeek API
    'mistral',      # Mistral API
    'groq',         # Groq API
    'ollama',       # Local Ollama
    'together',     # Together AI
    'siliconflow',  # SiliconFlow
]

ModelKey = Literal[
    # Anthropic
    'haiku35', 'haiku45',
    'sonnet35', 'sonnet37', 'sonnet40', 'sonnet45', 'sonnet46',
    'opus40', 'opus41', 'opus45', 'opus46',
    # OpenAI
    'gpt4o', 'gpt4omini', 'o1', 'o1mini', 'o3', 'o3mini', 'codex', 'codexmini',
    # Google Gemini
    'gemini2flash', 'gemini2flashlite', 'gemini15pro', 'gemini15flash',
    # DeepSeek
    'deepseekchat', 'deepseekcode', 'deepseekr1',
    # Mistral
    'mistrallarge', 'mistralsmall', 'codestral', 'ministral', 'pixtral',
    # Groq
    'llama370b', 'llama38b',
    # Ollama
    'ollama_llama3', 'ollama_phi3', 'ollama_qwen',
    # SiliconFlow
    'siliconflow_qwen3vl32b', 'siliconflow_qwen3vl8b', 'siliconflow_qwen25vl72b', 'siliconflow_qwenq32b',
]

ModelConfig = Dict[str, str]  # provider → model ID

# ---------------------------------------------------------------------------
# Per-model provider configurations
# ---------------------------------------------------------------------------

CLAUDE_3_7_SONNET_CONFIG: ModelConfig = {
    'anthropic': 'claude-3-7-sonnet-20250219',
    'bedrock':   'us.anthropic.claude-3-7-sonnet-20250219-v1:0',
    'vertex':    'claude-3-7-sonnet@20250219',
    'foundry':   'claude-3-7-sonnet',
}

CLAUDE_3_5_V2_SONNET_CONFIG: ModelConfig = {
    'anthropic': 'claude-3-5-sonnet-20241022',
    'bedrock':   'anthropic.claude-3-5-sonnet-20241022-v2:0',
    'vertex':    'claude-3-5-sonnet-v2@20241022',
    'foundry':   'claude-3-5-sonnet',
}

CLAUDE_3_5_HAIKU_CONFIG: ModelConfig = {
    'anthropic': 'claude-3-5-haiku-20241022',
    'bedrock':   'us.anthropic.claude-3-5-haiku-20241022-v1:0',
    'vertex':    'claude-3-5-haiku@20241022',
    'foundry':   'claude-3-5-haiku',
}

CLAUDE_HAIKU_4_5_CONFIG: ModelConfig = {
    'anthropic': 'claude-haiku-4-5-20251001',
    'bedrock':   'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    'vertex':    'claude-haiku-4-5@20251001',
    'foundry':   'claude-haiku-4-5',
}

CLAUDE_SONNET_4_CONFIG: ModelConfig = {
    'anthropic': 'claude-sonnet-4-20250514',
    'bedrock':   'us.anthropic.claude-sonnet-4-20250514-v1:0',
    'vertex':    'claude-sonnet-4@20250514',
    'foundry':   'claude-sonnet-4',
}

CLAUDE_SONNET_4_5_CONFIG: ModelConfig = {
    'anthropic': 'claude-sonnet-4-5-20250929',
    'bedrock':   'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
    'vertex':    'claude-sonnet-4-5@20250929',
    'foundry':   'claude-sonnet-4-5',
}

CLAUDE_OPUS_4_CONFIG: ModelConfig = {
    'anthropic': 'claude-opus-4-20250514',
    'bedrock':   'us.anthropic.claude-opus-4-20250514-v1:0',
    'vertex':    'claude-opus-4@20250514',
    'foundry':   'claude-opus-4',
}

CLAUDE_OPUS_4_1_CONFIG: ModelConfig = {
    'anthropic': 'claude-opus-4-1-20250805',
    'bedrock':   'us.anthropic.claude-opus-4-1-20250805-v1:0',
    'vertex':    'claude-opus-4-1@20250805',
    'foundry':   'claude-opus-4-1',
}

CLAUDE_OPUS_4_5_CONFIG: ModelConfig = {
    'anthropic': 'claude-opus-4-5-20251101',
    'bedrock':   'us.anthropic.claude-opus-4-5-20251101-v1:0',
    'vertex':    'claude-opus-4-5@20251101',
    'foundry':   'claude-opus-4-5',
}

CLAUDE_OPUS_4_6_CONFIG: ModelConfig = {
    'anthropic': 'claude-opus-4-6',
    'bedrock':   'us.anthropic.claude-opus-4-6-v1',
    'vertex':    'claude-opus-4-6',
    'foundry':   'claude-opus-4-6',
}

CLAUDE_SONNET_4_6_CONFIG: ModelConfig = {
    'anthropic': 'claude-sonnet-4-6',
    'bedrock':   'us.anthropic.claude-sonnet-4-6',
    'vertex':    'claude-sonnet-4-6',
    'foundry':   'claude-sonnet-4-6',
}

# ---------------------------------------------------------------------------
# OpenAI configurations
# ---------------------------------------------------------------------------

GPT_4O_CONFIG: ModelConfig = {
    'openai': 'gpt-4o',
    'azure':  'gpt-4o',
}

GPT_4O_MINI_CONFIG: ModelConfig = {
    'openai': 'gpt-4o-mini',
    'azure':  'gpt-4o-mini',
}

O1_CONFIG: ModelConfig = {
    'openai': 'o1',
    'azure':  'o1',
}

O1_MINI_CONFIG: ModelConfig = {
    'openai': 'o1-mini',
    'azure':  'o1-mini',
}

O3_CONFIG: ModelConfig = {
    'openai': 'o3',
    'azure':  'o3',
}

O3_MINI_CONFIG: ModelConfig = {
    'openai': 'o3-mini',
    'azure':  'o3-mini',
}

CODEX_CONFIG: ModelConfig = {
    'openai': 'codex',
}

CODEX_MINI_CONFIG: ModelConfig = {
    'openai': 'codex-mini-latest',
}

# ---------------------------------------------------------------------------
# Google Gemini configurations
# ---------------------------------------------------------------------------

GEMINI_2_FLASH_CONFIG: ModelConfig = {
    'google': 'gemini-2.0-flash',
    'vertex': 'gemini-2.0-flash@latest',
}

GEMINI_2_FLASH_LITE_CONFIG: ModelConfig = {
    'google': 'gemini-2.0-flash-lite',
    'vertex': 'gemini-2.0-flash-lite@latest',
}

GEMINI_1_5_PRO_CONFIG: ModelConfig = {
    'google': 'gemini-1.5-pro',
    'vertex': 'gemini-1.5-pro@latest',
}

GEMINI_1_5_FLASH_CONFIG: ModelConfig = {
    'google': 'gemini-1.5-flash',
    'vertex': 'gemini-1.5-flash@latest',
}

# ---------------------------------------------------------------------------
# DeepSeek configurations
# ---------------------------------------------------------------------------

DEEPSEEK_CHAT_CONFIG: ModelConfig = {
    'deepseek': 'deepseek-chat',
}

DEEPSEEK_CODE_CONFIG: ModelConfig = {
    'deepseek': 'deepseek-coder',
}

DEEPSEEK_R1_CONFIG: ModelConfig = {
    'deepseek': 'deepseek-reasoner',
}

# ---------------------------------------------------------------------------
# Mistral configurations
# ---------------------------------------------------------------------------

MISTRAL_LARGE_CONFIG: ModelConfig = {
    'mistral': 'mistral-large-latest',
}

MISTRAL_SMALL_CONFIG: ModelConfig = {
    'mistral': 'mistral-small-latest',
}

CODESTRAL_CONFIG: ModelConfig = {
    'mistral': 'codestral-latest',
}

MINISTRAL_8B_CONFIG: ModelConfig = {
    'mistral': 'ministral-8b-latest',
}

PIXTRAL_12B_CONFIG: ModelConfig = {
    'mistral': 'pixtral-12b-latest',
}

# ---------------------------------------------------------------------------
# Groq / Meta configurations
# ---------------------------------------------------------------------------

LLAMA_3_70B_CONFIG: ModelConfig = {
    'groq': 'llama-3.3-70b-versatile',
}

LLAMA_3_8B_CONFIG: ModelConfig = {
    'groq': 'llama-3.1-8b-instant',
}

# ---------------------------------------------------------------------------
# Ollama (local) configurations
# ---------------------------------------------------------------------------

OLLAMA_LLAMA3_CONFIG: ModelConfig = {
    'ollama': 'llama3',
}

OLLAMA_PHI3_CONFIG: ModelConfig = {
    'ollama': 'phi3',
}

OLLAMA_QWEN_CONFIG: ModelConfig = {
    'ollama': 'qwen2.5-coder',
}

# ---------------------------------------------------------------------------
# SiliconFlow configurations
# ---------------------------------------------------------------------------

SILICONFLOW_QWEN3_VL_32B_CONFIG: ModelConfig = {
    'siliconflow': 'Qwen/Qwen3-VL-32B-Instruct',
}

SILICONFLOW_QWEN3_VL_8B_CONFIG: ModelConfig = {
    'siliconflow': 'Qwen/Qwen3-VL-8B-Instruct',
}

SILICONFLOW_QWEN25_VL_72B_CONFIG: ModelConfig = {
    'siliconflow': 'Qwen/Qwen2.5-VL-72B-Instruct',
}

SILICONFLOW_QWQ_32B_CONFIG: ModelConfig = {
    'siliconflow': 'Qwen/QwQ-32B',
}

# ---------------------------------------------------------------------------
# Master registry — all model configurations
# ---------------------------------------------------------------------------

ALL_MODEL_CONFIGS: Dict[ModelKey, ModelConfig] = {
    # ── Anthropic ──────────────────────────────────────────────────────────
    'haiku35':  CLAUDE_3_5_HAIKU_CONFIG,
    'haiku45':  CLAUDE_HAIKU_4_5_CONFIG,
    'sonnet35': CLAUDE_3_5_V2_SONNET_CONFIG,
    'sonnet37': CLAUDE_3_7_SONNET_CONFIG,
    'sonnet40': CLAUDE_SONNET_4_CONFIG,
    'sonnet45': CLAUDE_SONNET_4_5_CONFIG,
    'sonnet46': CLAUDE_SONNET_4_6_CONFIG,
    'opus40':   CLAUDE_OPUS_4_CONFIG,
    'opus41':   CLAUDE_OPUS_4_1_CONFIG,
    'opus45':   CLAUDE_OPUS_4_5_CONFIG,
    'opus46':   CLAUDE_OPUS_4_6_CONFIG,
    # ── OpenAI ────────────────────────────────────────────────────────────
    'gpt4o':      GPT_4O_CONFIG,
    'gpt4omini':  GPT_4O_MINI_CONFIG,
    'o1':         O1_CONFIG,
    'o1mini':     O1_MINI_CONFIG,
    'o3':         O3_CONFIG,
    'o3mini':     O3_MINI_CONFIG,
    'codex':      CODEX_CONFIG,
    'codexmini':  CODEX_MINI_CONFIG,
    # ── Google Gemini ─────────────────────────────────────────────────────
    'gemini2flash':     GEMINI_2_FLASH_CONFIG,
    'gemini2flashlite': GEMINI_2_FLASH_LITE_CONFIG,
    'gemini15pro':      GEMINI_1_5_PRO_CONFIG,
    'gemini15flash':    GEMINI_1_5_FLASH_CONFIG,
    # ── DeepSeek ──────────────────────────────────────────────────────────
    'deepseekchat': DEEPSEEK_CHAT_CONFIG,
    'deepseekcode': DEEPSEEK_CODE_CONFIG,
    'deepseekr1':   DEEPSEEK_R1_CONFIG,
    # ── Mistral ───────────────────────────────────────────────────────────
    'mistrallarge':  MISTRAL_LARGE_CONFIG,
    'mistralsmall':  MISTRAL_SMALL_CONFIG,
    'codestral':     CODESTRAL_CONFIG,
    'ministral':     MINISTRAL_8B_CONFIG,
    'pixtral':       PIXTRAL_12B_CONFIG,
    # ── Groq ─────────────────────────────────────────────────────────────
    'llama370b': LLAMA_3_70B_CONFIG,
    'llama38b':  LLAMA_3_8B_CONFIG,
    # ── Ollama (local) ───────────────────────────────────────────────────
    'ollama_llama3': OLLAMA_LLAMA3_CONFIG,
    'ollama_phi3':   OLLAMA_PHI3_CONFIG,
    'ollama_qwen':   OLLAMA_QWEN_CONFIG,
    # ── SiliconFlow ──────────────────────────────────────────────────────
    'siliconflow_qwen3vl32b':   SILICONFLOW_QWEN3_VL_32B_CONFIG,
    'siliconflow_qwen3vl8b':    SILICONFLOW_QWEN3_VL_8B_CONFIG,
    'siliconflow_qwen25vl72b':  SILICONFLOW_QWEN25_VL_72B_CONFIG,
    'siliconflow_qwenq32b':     SILICONFLOW_QWQ_32B_CONFIG,
}

# ---------------------------------------------------------------------------
# Canonical model utilities
# ---------------------------------------------------------------------------

# Tuple of all canonical model IDs (primary provider format)
# Claude → Anthropic, OpenAI → openai, Gemini → google, etc.
CANONICAL_MODEL_IDS: Tuple[str, ...] = tuple(
    list(cfg.values())[0] for cfg in ALL_MODEL_CONFIGS.values()
)

# Reverse lookup: model ID → short key
# e.g. 'claude-opus-4-6' → 'opus46', 'gpt-4o' → 'gpt4o'
CANONICAL_ID_TO_KEY: Dict[str, ModelKey] = {}
for key, cfg in ALL_MODEL_CONFIGS.items():
    for model_id in cfg.values():
        CANONICAL_ID_TO_KEY[model_id] = key

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def getModelConfig(modelKey: ModelKey) -> ModelConfig:
    """
    Get the full provider configuration for a model.

    Args:
        modelKey: Short model identifier (e.g. 'opus46', 'sonnet45')

    Returns:
        Dict mapping provider → model ID

    Example:
        getModelConfig('opus46')['anthropic']  → 'claude-opus-4-6'
        getModelConfig('sonnet40')['bedrock']  → 'us.anthropic.claude-sonnet-4-20250514-v1:0'
    """
    return ALL_MODEL_CONFIGS[modelKey]


def getModelIdForProvider(modelKey: ModelKey, provider: str) -> Optional[str]:
    """
    Get the model ID for a specific provider.

    Args:
        modelKey: Short model identifier (e.g. 'opus46', 'gpt4o', 'gemini2flash')
        provider: Provider name ('anthropic', 'openai', 'google', 'bedrock', etc.)

    Returns:
        Provider-specific model ID string, or None if provider not supported for this model

    Example:
        getModelIdForProvider('opus46', 'anthropic') → 'claude-opus-4-6'
        getModelIdForProvider('opus46', 'bedrock')   → 'us.anthropic.claude-opus-4-6-v1'
        getModelIdForProvider('gpt4o', 'openai')     → 'gpt-4o'
        getModelIdForProvider('gemini2flash', 'google') → 'gemini-2.0-flash'
    """
    return ALL_MODEL_CONFIGS[modelKey].get(provider)


def resolveModelKey(modelId: str) -> Optional[ModelKey]:
    """
    Resolve a model ID to its short key.

    Args:
        modelId: Model ID from any provider (e.g. 'claude-opus-4-6', 'gpt-4o', 'gemini-2.0-flash')

    Returns:
        Short model key, or None if not recognised

    Example:
        resolveModelKey('claude-opus-4-6')      → 'opus46'
        resolveModelKey('claude-sonnet-4-5-20250929') → 'sonnet45'
        resolveModelKey('gpt-4o')               → 'gpt4o'
        resolveModelKey('gemini-2.0-flash')     → 'gemini2flash'
        resolveModelKey('unknown-model')        → None
    """
    return CANONICAL_ID_TO_KEY.get(modelId)


def isCanonicalModelId(modelId: str) -> bool:
    """
    Check if a model ID is a canonical model ID (any provider).

    Args:
        modelId: Model ID string to validate

    Returns:
        True if modelId is in CANONICAL_MODEL_IDS

    Example:
        isCanonicalModelId('claude-opus-4-6') → True
        isCanonicalModelId('gpt-4o') → True
        isCanonicalModelId('gemini-2.0-flash') → True
        isCanonicalModelId('custom-model') → False
    """
    return modelId in CANONICAL_MODEL_IDS


def getProvidersForModel(modelKey: ModelKey) -> List[str]:
    """
    Get list of providers that support a model.

    Args:
        modelKey: Short model identifier

    Returns:
        List of provider names (e.g. ['anthropic', 'bedrock', 'vertex', 'foundry'])

    Example:
        getProvidersForModel('opus46') → ['anthropic', 'bedrock', 'vertex', 'foundry']
        getProvidersForModel('gpt4o') → ['openai', 'azure']
        getProvidersForModel('deepseekchat') → ['deepseek']
    """
    return list(ALL_MODEL_CONFIGS[modelKey].keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    'APIProvider',
    'ModelKey',
    'ModelConfig',
    # Claude configs
    'CLAUDE_3_7_SONNET_CONFIG',
    'CLAUDE_3_5_V2_SONNET_CONFIG',
    'CLAUDE_3_5_HAIKU_CONFIG',
    'CLAUDE_HAIKU_4_5_CONFIG',
    'CLAUDE_SONNET_4_CONFIG',
    'CLAUDE_SONNET_4_5_CONFIG',
    'CLAUDE_OPUS_4_CONFIG',
    'CLAUDE_OPUS_4_1_CONFIG',
    'CLAUDE_OPUS_4_5_CONFIG',
    'CLAUDE_OPUS_4_6_CONFIG',
    'CLAUDE_SONNET_4_6_CONFIG',
    # OpenAI configs
    'GPT_4O_CONFIG',
    'GPT_4O_MINI_CONFIG',
    'O1_CONFIG',
    'O1_MINI_CONFIG',
    'O3_CONFIG',
    'O3_MINI_CONFIG',
    'CODEX_CONFIG',
    'CODEX_MINI_CONFIG',
    # Gemini configs
    'GEMINI_2_FLASH_CONFIG',
    'GEMINI_2_FLASH_LITE_CONFIG',
    'GEMINI_1_5_PRO_CONFIG',
    'GEMINI_1_5_FLASH_CONFIG',
    # DeepSeek configs
    'DEEPSEEK_CHAT_CONFIG',
    'DEEPSEEK_CODE_CONFIG',
    'DEEPSEEK_R1_CONFIG',
    # Mistral configs
    'MISTRAL_LARGE_CONFIG',
    'MISTRAL_SMALL_CONFIG',
    'CODESTRAL_CONFIG',
    'MINISTRAL_8B_CONFIG',
    'PIXTRAL_12B_CONFIG',
    # Groq configs
    'LLAMA_3_70B_CONFIG',
    'LLAMA_3_8B_CONFIG',
    # Ollama configs
    'OLLAMA_LLAMA3_CONFIG',
    'OLLAMA_PHI3_CONFIG',
    'OLLAMA_QWEN_CONFIG',
    # Master registry
    'ALL_MODEL_CONFIGS',
    'CANONICAL_MODEL_IDS',
    'CANONICAL_ID_TO_KEY',
    # Helper functions
    'getModelConfig',
    'getModelIdForProvider',
    'resolveModelKey',
    'isCanonicalModelId',
    'getProvidersForModel',
]
