"""
Model validation for Cortex AI Agent IDE.

Validates models by checking allowlists, aliases, and making actual API calls.
Provides fallback suggestions when models are unavailable.

Supports all Cortex providers:
  - Anthropic, OpenAI, Google, DeepSeek, Mistral, Groq, Ollama, SiliconFlow

Simplified from original:
  - Removed Anthropic-specific sideQuery()
  - Removed firstParty vs 3P logic
  - Uses provider SDK calls instead
  - Generic error handling (not Anthropic-specific)
"""

import time
from typing import Any, Dict, Optional

try:
    from .modelAllowlist import isModelAllowed
    from .aliases import MODEL_ALIASES
    from .modelStrings import getModelStrings
except ImportError:
    from modelAllowlist import isModelAllowed
    from aliases import MODEL_ALIASES
    from modelStrings import getModelStrings


# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------

# Cache: model_name → (is_valid, timestamp)
_valid_model_cache: Dict[str, tuple[bool, float]] = {}
CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Core validation function
# ---------------------------------------------------------------------------

async def validate_model(
    model: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate a model name by checking allowlists and making API call.

    Validation steps:
    1. Check if model name is empty
    2. Check against allowlist (modelAllowlist.py)
    3. Check if it's a known alias (aliases.py)
    4. Check cache (avoid repeated API calls)
    5. Make actual API call to verify model exists

    Args:
        model: Model name to validate
        provider: Provider name (e.g., 'anthropic', 'openai', 'deepseek')
        api_key: API key for the provider (optional, uses env var if not provided)

    Returns:
        Dict with 'valid' key and optional 'error' message
        - {'valid': True} if model is valid
        - {'valid': False, 'error': 'message'} if invalid

    Example:
        await validate_model('claude-sonnet-4-20250514', 'anthropic')
        → {'valid': True}

        await validate_model('nonexistent-model', 'openai')
        → {'valid': False, 'error': "Model 'nonexistent-model' not found. Try 'gpt-4o' instead"}
    """
    normalized_model = model.strip()

    # Step 1: Check if empty
    if not normalized_model:
        return {'valid': False, 'error': 'Model name cannot be empty'}

    # Step 2: Check against allowlist
    if not isModelAllowed(normalized_model):
        return {
            'valid': False,
            'error': f"Model '{normalized_model}' is not in the list of available models",
        }

    # Step 3: Check if it's a known alias
    lower_model = normalized_model.lower()
    if lower_model in MODEL_ALIASES:
        return {'valid': True}

    # Step 4: Check cache
    if _is_cache_valid(normalized_model):
        return {'valid': True}

    # Step 5: Try actual API call
    try:
        await _test_model_with_api(normalized_model, provider, api_key)

        # If we got here, the model is valid - cache it
        _cache_model(normalized_model, True)
        return {'valid': True}

    except Exception as error:
        return _handle_validation_error(error, normalized_model, provider)


# ---------------------------------------------------------------------------
# API testing
# ---------------------------------------------------------------------------

async def _test_model_with_api(
    model: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> None:
    """
    Test model with a minimal API call.

    Uses your existing Cortex providers to make a test request.

    Args:
        model: Model name to test
        provider: Provider name
        api_key: API key (optional)

    Raises:
        Exception: If API call fails
    """
    if provider is None:
        provider = 'anthropic'

    # Import providers dynamically to avoid circular dependencies
    try:
        if provider == 'anthropic':
            await _test_anthropic_model(model, api_key)
        elif provider == 'openai':
            await _test_openai_model(model, api_key)
        elif provider == 'google':
            await _test_google_model(model, api_key)
        elif provider == 'deepseek':
            await _test_deepseek_model(model, api_key)
        elif provider == 'mistral':
            await _test_mistral_model(model, api_key)
        elif provider == 'siliconflow':
            await _test_siliconflow_model(model, api_key)
        elif provider == 'groq':
            await _test_groq_model(model, api_key)
        elif provider == 'ollama':
            await _test_ollama_model(model)
        else:
            # Unknown provider - skip API test, assume valid if passed allowlist
            pass

    except ImportError:
        # Provider not installed - skip API test
        pass


async def _test_anthropic_model(model: str, api_key: Optional[str] = None) -> None:
    """Test Anthropic model with minimal API call"""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)
    await client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{'role': 'user', 'content': 'Hi'}],
    )


async def _test_openai_model(model: str, api_key: Optional[str] = None) -> None:
    """Test OpenAI model with minimal API call"""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    await client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{'role': 'user', 'content': 'Hi'}],
    )


async def _test_google_model(model: str, api_key: Optional[str] = None) -> None:
    """Test Google Gemini model with minimal API call"""
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    gen_model = genai.GenerativeModel(model)
    await gen_model.generate_content_async('Hi')


async def _test_deepseek_model(model: str, api_key: Optional[str] = None) -> None:
    """Test DeepSeek model with minimal API call"""
    from openai import AsyncOpenAI

    # DeepSeek uses OpenAI-compatible API
    client = AsyncOpenAI(
        api_key=api_key,
        base_url='https://api.deepseek.com/v1',
    )
    await client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{'role': 'user', 'content': 'Hi'}],
    )


async def _test_mistral_model(model: str, api_key: Optional[str] = None) -> None:
    """Test Mistral model with minimal API call"""
    from mistralai import Mistral

    client = Mistral(api_key=api_key)
    await client.chat.complete_async(
        model=model,
        max_tokens=1,
        messages=[{'role': 'user', 'content': 'Hi'}],
    )


async def _test_siliconflow_model(model: str, api_key: Optional[str] = None) -> None:
    """Test SiliconFlow model with minimal API call"""
    from openai import AsyncOpenAI

    # SiliconFlow uses OpenAI-compatible API
    client = AsyncOpenAI(
        api_key=api_key,
        base_url='https://api.siliconflow.com/v1',
    )
    await client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{'role': 'user', 'content': 'Hi'}],
    )


async def _test_groq_model(model: str, api_key: Optional[str] = None) -> None:
    """Test Groq model with minimal API call"""
    from groq import AsyncGroq

    client = AsyncGroq(api_key=api_key)
    await client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{'role': 'user', 'content': 'Hi'}],
    )


async def _test_ollama_model(model: str) -> None:
    """Test Ollama model with minimal API call"""
    import aiohttp

    url = 'http://localhost:11434/api/chat'
    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': 'Hi'}],
        'stream': False,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=10) as response:
            if response.status != 200:
                raise Exception(f'Ollama API error: {response.status}')


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def _handle_validation_error(
    error: Exception,
    model_name: str,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse validation errors and return user-friendly messages.

    Args:
        error: Exception from API call
        model_name: Model that failed validation
        provider: Provider name for fallback suggestion

    Returns:
        Dict with 'valid': False and 'error' message
    """
    error_str = str(error).lower()

    # Authentication errors
    if 'auth' in error_str or 'api key' in error_str or 'unauthorized' in error_str:
        return {
            'valid': False,
            'error': 'Authentication failed. Please check your API credentials.',
        }

    # Network errors
    if 'network' in error_str or 'connection' in error_str or 'timeout' in error_str:
        return {
            'valid': False,
            'error': 'Network error. Please check your internet connection.',
        }

    # Model not found errors
    if 'not found' in error_str or 'does not exist' in error_str or 'invalid model' in error_str:
        fallback = _get_fallback_suggestion(model_name, provider)
        suggestion = f". Try '{fallback}' instead" if fallback else ''
        return {
            'valid': False,
            'error': f"Model '{model_name}' not found{suggestion}",
        }

    # Rate limit errors
    if 'rate limit' in error_str or 'too many requests' in error_str or '429' in error_str:
        return {
            'valid': False,
            'error': f"Rate limit exceeded for model '{model_name}'. Please try again later.",
        }

    # Generic error
    return {
        'valid': False,
        'error': f"Unable to validate model '{model_name}': {str(error)}",
    }


# ---------------------------------------------------------------------------
# Fallback suggestions
# ---------------------------------------------------------------------------

def _get_fallback_suggestion(model: str, provider: Optional[str] = None) -> Optional[str]:
    """
    Suggest a fallback model when the selected model is unavailable.

    Maps newer models to their previous versions as fallbacks.

    Args:
        model: Model name that failed
        provider: Provider name

    Returns:
        Fallback model name or None

    Example:
        _get_fallback_suggestion('claude-opus-4-6') → 'claude-opus-4-1'
        _get_fallback_suggestion('gpt-4o') → 'gpt-4o-mini'
    """
    lower_model = model.lower()

    # Anthropic fallbacks
    if 'opus-4-6' in lower_model or 'opus_4_6' in lower_model:
        return getModelStrings(provider).get('opus41')
    if 'sonnet-4-6' in lower_model or 'sonnet_4_6' in lower_model:
        return getModelStrings(provider).get('sonnet45')
    if 'sonnet-4-5' in lower_model or 'sonnet_4_5' in lower_model:
        return getModelStrings(provider).get('sonnet40')

    # OpenAI fallbacks
    if 'gpt-4o' in lower_model and 'mini' not in lower_model:
        return 'gpt-4o-mini'
    if 'o3' in lower_model:
        return 'o1'

    # DeepSeek fallbacks
    if 'deepseek-chat' in lower_model:
        return 'deepseek-coder'

    # Mistral fallbacks
    if 'mistral-large' in lower_model:
        return 'mistral-medium-latest'
    if 'codestral' in lower_model:
        return 'mistral-small-latest'

    # Google fallbacks
    if 'gemini-2.0' in lower_model:
        return 'gemini-1.5-pro'
    if 'gemini-1.5-pro' in lower_model:
        return 'gemini-1.5-flash'

    return None


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def _is_cache_valid(model: str) -> bool:
    """
    Check if model validation is still in cache and not expired.

    Args:
        model: Model name to check

    Returns:
        True if cached and not expired
    """
    if model not in _valid_model_cache:
        return False

    is_valid, timestamp = _valid_model_cache[model]
    if time.time() - timestamp > CACHE_TTL:
        # Cache expired
        del _valid_model_cache[model]
        return False

    return is_valid


def _cache_model(model: str, is_valid: bool) -> None:
    """
    Cache model validation result.

    Args:
        model: Model name
        is_valid: Validation result
    """
    _valid_model_cache[model] = (is_valid, time.time())


def clear_model_cache() -> None:
    """Clear all cached model validations"""
    _valid_model_cache.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    'validate_model',
    'clear_model_cache',
]
