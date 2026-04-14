# ------------------------------------------------------------
# withRetry.py
# Python conversion of withRetry.ts (lines 1-823)
#
# Retry engine for multi-LLM API calls supporting:
# - Exponential backoff with jitter
# - Fallback model on repeated 529s (Opus → Sonnet)
# - Fast mode cooldown on 429/529
# - Persistent retry mode for unattended sessions
# - OAuth/Bedrock/Vertex auth refresh on 401/403
# - Max-tokens context overflow adjustment
# - Per query-source 529 retry policy
# ------------------------------------------------------------

import asyncio
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, Optional, Set


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from bun.bundle import feature
except ImportError:
    def feature(feature_name: str) -> bool:
        return False

try:
    from anthropic import (
        APIConnectionError,
        APIError,
        APIUserAbortError,
    )
except ImportError:
    class APIError(Exception):
        status: Optional[int] = None
        message: str = ""
        headers: Any = None

    class APIConnectionError(APIError):
        pass

    class APIUserAbortError(APIError):
        pass

try:
    from .errors import REPEATED_529_ERROR_MESSAGE
except ImportError:
    REPEATED_529_ERROR_MESSAGE = "The API is currently overloaded. Please try again later."

try:
    from .errorUtils import extract_connection_error_details
except ImportError:
    def extract_connection_error_details(error: Any) -> Optional[Dict[str, str]]:
        return None

try:
    from ...utils.auth import (
        clear_api_key_helper_cache,
        clear_aws_credentials_cache,
        clear_gcp_credentials_cache,
        get_cloud_ai_oauth_tokens,
        handle_oauth_401_error,
        is_cloud_ai_subscriber,
        is_enterprise_subscriber,
    )
except ImportError:
    def clear_api_key_helper_cache() -> None: pass
    def clear_aws_credentials_cache() -> None: pass
    def clear_gcp_credentials_cache() -> None: pass
    def get_cloud_ai_oauth_tokens() -> Optional[Dict]: return None
    async def handle_oauth_401_error(token: str) -> None: pass
    def is_cloud_ai_subscriber() -> bool: return False
    def is_enterprise_subscriber() -> bool: return False

try:
    from ...utils.env_utils import is_env_truthy
except ImportError:
    def is_env_truthy(value: Optional[str]) -> bool:
        return str(value).lower() in ("true", "1", "yes") if value else False

try:
    from ...utils.errors import error_message
except ImportError:
    def error_message(error: Any) -> str:
        return str(error)

try:
    from ...utils.fast_mode import (
        handle_fast_mode_overage_rejection,
        handle_fast_mode_rejected_by_api,
        is_fast_mode_cooldown,
        is_fast_mode_enabled,
        trigger_fast_mode_cooldown,
    )
    CooldownReason = str
except ImportError:
    def handle_fast_mode_overage_rejection(reason: str) -> None: pass
    def handle_fast_mode_rejected_by_api() -> None: pass
    def is_fast_mode_cooldown() -> bool: return False
    def is_fast_mode_enabled() -> bool: return False
    def trigger_fast_mode_cooldown(until: int, reason: str) -> None: pass
    CooldownReason = str

try:
    from ...utils.model.model import is_non_custom_opus_model
except ImportError:
    def is_non_custom_opus_model(model: str) -> bool:
        return "opus" in model.lower()

try:
    from ...utils.proxy import disable_keep_alive
except ImportError:
    def disable_keep_alive() -> None: pass

try:
    from ...utils.sleep import sleep
except ImportError:
    async def sleep(ms: float, signal: Any = None, options: Any = None) -> None:
        """Async sleep with abort-signal support and abortError callback."""
        remaining = ms
        while remaining > 0:
            if signal and getattr(signal, "aborted", False):
                if options and options.get("abortError"):
                    raise options["abortError"]()
                return
            chunk = min(remaining, 1000)
            await asyncio.sleep(chunk / 1000)
            remaining -= chunk

try:
    from ...utils.aws import is_aws_credentials_provider_error
except ImportError:
    def is_aws_credentials_provider_error(error: Any) -> bool:
        return False

try:
    from ...utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(msg: str, options: Any = None) -> None:
        pass

try:
    from ...utils.log import log_error
except ImportError:
    def log_error(error: Exception) -> None:
        print(f"ERROR: {error}")

try:
    from ..analytics.growthbook import get_feature_value_cached_may_be_stale
except ImportError:
    def get_feature_value_cached_may_be_stale(key: str, default: Any) -> Any:
        return default

try:
    from ..analytics.index import log_event
except ImportError:
    def log_event(event: str, data: Dict) -> None:
        pass

try:
    from ..rate_limit_mocking import check_mock_rate_limit_error, is_mock_rate_limit_error
except ImportError:
    def check_mock_rate_limit_error(model: str, fast_mode: bool) -> Optional[Exception]:
        return None
    def is_mock_rate_limit_error(error: Any) -> bool:
        return False

try:
    from ...utils.messages import create_system_api_error_message
except ImportError:
    def create_system_api_error_message(error: Any, delay_ms: int, attempt: int, max_retries: int) -> Dict:
        return {
            "type": "system",
            "subtype": "api_error",
            "error": error,
            "retryInMs": delay_ms,
            "retryAttempt": attempt,
            "maxRetries": max_retries,
        }

try:
    from ..analytics.index import get_api_provider_for_statsig
except ImportError:
    def get_api_provider_for_statsig() -> str:
        return "anthropic"


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_MAX_RETRIES = 10
FLOOR_OUTPUT_TOKENS = 3000
MAX_529_RETRIES = 3
BASE_DELAY_MS = 500

DEFAULT_FAST_MODE_FALLBACK_HOLD_MS = 30 * 60 * 1000   # 30 minutes
SHORT_RETRY_THRESHOLD_MS = 20 * 1000                   # 20 seconds
MIN_COOLDOWN_MS = 10 * 60 * 1000                       # 10 minutes

PERSISTENT_MAX_BACKOFF_MS = 5 * 60 * 1000             # 5 minutes
PERSISTENT_RESET_CAP_MS = 6 * 60 * 60 * 1000          # 6 hours
HEARTBEAT_INTERVAL_MS = 30_000                          # 30 seconds

# Query sources where users block on the result — retry 529 for these.
FOREGROUND_529_RETRY_SOURCES: Set[str] = {
    "repl_main_thread",
    "repl_main_thread:outputStyle:custom",
    "repl_main_thread:outputStyle:Explanatory",
    "repl_main_thread:outputStyle:Learning",
    "sdk",
    "agent:custom",
    "agent:default",
    "agent:builtin",
    "compact",
    "hook_agent",
    "hook_prompt",
    "verification_agent",
    "side_question",
    "auto_mode",
    *( ["bash_classifier"] if feature("BASH_CLASSIFIER") else [] ),
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class RetryContext:
    model: str
    thinking_config: Dict[str, Any]
    max_tokens_override: Optional[int] = None
    fast_mode: Optional[bool] = None


@dataclass
class RetryOptions:
    model: str
    thinking_config: Dict[str, Any]
    max_retries: Optional[int] = None
    fallback_model: Optional[str] = None
    fast_mode: Optional[bool] = None
    signal: Optional[Any] = None
    query_source: Optional[str] = None
    initial_consecutive_529_errors: int = 0


# ============================================================
# CUSTOM EXCEPTIONS
# ============================================================

class CannotRetryError(Exception):
    """Raised when all retry attempts have been exhausted."""
    def __init__(self, original_error: Any, retry_context: RetryContext):
        msg = error_message(original_error)
        super().__init__(msg)
        self.name = "RetryError"
        self.original_error = original_error
        self.retry_context = retry_context
        if isinstance(original_error, Exception) and hasattr(original_error, "__traceback__"):
            self.__traceback__ = original_error.__traceback__


class FallbackTriggeredError(Exception):
    """Raised when model fallback is triggered (e.g., Opus → Sonnet)."""
    def __init__(self, original_model: str, fallback_model: str):
        super().__init__(f"Model fallback triggered: {original_model} -> {fallback_model}")
        self.name = "FallbackTriggeredError"
        self.original_model = original_model
        self.fallback_model = fallback_model


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def should_retry_529(query_source: Optional[str]) -> bool:
    """Undefined source → retry (conservative for untagged call paths)."""
    return query_source is None or query_source in FOREGROUND_529_RETRY_SOURCES


def is_persistent_retry_enabled() -> bool:
    return (
        feature("UNATTENDED_RETRY") and
        is_env_truthy(os.environ.get("CLAUDE_CODE_UNATTENDED_RETRY"))
    )


def is_transient_capacity_error(error: Any) -> bool:
    return is_529_error(error) or (isinstance(error, APIError) and error.status == 429)


def is_stale_connection_error(error: Any) -> bool:
    if not isinstance(error, APIConnectionError):
        return False
    details = extract_connection_error_details(error)
    return details is not None and details.get("code") in ("ECONNRESET", "EPIPE")


def is_529_error(error: Any) -> bool:
    if not isinstance(error, APIError):
        return False
    return (
        error.status == 529 or
        (error.message and '"type":"overloaded_error"' in error.message)
    )


def is_oauth_token_revoked_error(error: Any) -> bool:
    return (
        isinstance(error, APIError) and
        error.status == 403 and
        bool(error.message and "OAuth token has been revoked" in error.message)
    )


def is_bedrock_auth_error(error: Any) -> bool:
    if is_env_truthy(os.environ.get("CLAUDE_CODE_USE_BEDROCK")):
        if is_aws_credentials_provider_error(error):
            return True
        if isinstance(error, APIError) and error.status == 403:
            return True
    return False


def handle_aws_credential_error(error: Any) -> bool:
    """Clear AWS auth caches if applicable. Returns True if action was taken."""
    if is_bedrock_auth_error(error):
        clear_aws_credentials_cache()
        return True
    return False


def is_google_auth_library_credential_error(error: Any) -> bool:
    if not isinstance(error, Exception):
        return False
    msg = str(error)
    return any(phrase in msg for phrase in [
        "Could not load the default credentials",
        "Could not refresh access token",
        "invalid_grant",
    ])


def is_vertex_auth_error(error: Any) -> bool:
    if is_env_truthy(os.environ.get("CLAUDE_CODE_USE_VERTEX")):
        if is_google_auth_library_credential_error(error):
            return True
        if isinstance(error, APIError) and error.status == 401:
            return True
    return False


def handle_gcp_credential_error(error: Any) -> bool:
    """Clear GCP auth caches if applicable. Returns True if action was taken."""
    if is_vertex_auth_error(error):
        clear_gcp_credentials_cache()
        return True
    return False


def is_fast_mode_not_enabled_error(error: Any) -> bool:
    return (
        isinstance(error, APIError) and
        error.status == 400 and
        bool(error.message and "Fast mode is not enabled" in error.message)
    )


def get_retry_after(error: Any) -> Optional[str]:
    """Extract Retry-After header value from error."""
    try:
        headers = getattr(error, "headers", None)
        if headers is None:
            return None
        if isinstance(headers, dict):
            return headers.get("retry-after")
        if hasattr(headers, "get"):
            return headers.get("retry-after")
    except Exception:
        pass
    return None


def get_retry_after_ms(error: Any) -> Optional[int]:
    retry_after = get_retry_after(error)
    if retry_after:
        try:
            seconds = int(retry_after)
            return seconds * 1000
        except (ValueError, TypeError):
            pass
    return None


def get_rate_limit_reset_delay_ms(error: Any) -> Optional[int]:
    try:
        headers = getattr(error, "headers", None)
        if headers is None:
            return None
        reset_header = headers.get("anthropic-ratelimit-unified-reset") if hasattr(headers, "get") else None
        if not reset_header:
            return None
        reset_unix_sec = float(reset_header)
        if not math.isfinite(reset_unix_sec):
            return None
        delay_ms = int(reset_unix_sec * 1000 - time.time() * 1000)
        if delay_ms <= 0:
            return None
        return min(delay_ms, PERSISTENT_RESET_CAP_MS)
    except Exception:
        return None


def get_retry_delay(
    attempt: int,
    retry_after_header: Optional[str] = None,
    max_delay_ms: int = 32000,
) -> float:
    """Exponential backoff with jitter. Respects Retry-After header."""
    if retry_after_header:
        try:
            seconds = int(retry_after_header)
            return seconds * 1000
        except (ValueError, TypeError):
            pass

    base_delay = min(BASE_DELAY_MS * (2 ** (attempt - 1)), max_delay_ms)
    jitter = random.random() * 0.25 * base_delay
    return base_delay + jitter


def get_default_max_retries() -> int:
    env_val = os.environ.get("CLAUDE_CODE_MAX_RETRIES")
    if env_val:
        try:
            return int(env_val)
        except (ValueError, TypeError):
            pass
    return DEFAULT_MAX_RETRIES


def get_max_retries(options: RetryOptions) -> int:
    return options.max_retries if options.max_retries is not None else get_default_max_retries()


def parse_max_tokens_context_overflow_error(error: Any) -> Optional[Dict[str, int]]:
    """
    Parse context overflow errors and return token counts.
    Example message: "input length and `max_tokens` exceed context limit: 188059 + 20000 > 200000"
    """
    if not isinstance(error, APIError):
        return None
    if error.status != 400 or not error.message:
        return None
    if "input length and `max_tokens` exceed context limit" not in error.message:
        return None

    pattern = r"input length and `max_tokens` exceed context limit: (\d+) \+ (\d+) > (\d+)"
    match = re.search(pattern, error.message)
    if not match or len(match.groups()) != 3:
        return None

    try:
        input_tokens = int(match.group(1))
        max_tokens = int(match.group(2))
        context_limit = int(match.group(3))
        return {"inputTokens": input_tokens, "maxTokens": max_tokens, "contextLimit": context_limit}
    except (ValueError, TypeError):
        return None


def should_retry(error: Any) -> bool:
    """Determine if an APIError warrants a retry."""
    if not isinstance(error, APIError):
        return False

    if is_mock_rate_limit_error(error):
        return False

    if is_persistent_retry_enabled() and is_transient_capacity_error(error):
        return True

    # CCR: auth errors are transient blips
    if (
        is_env_truthy(os.environ.get("CLAUDE_CODE_REMOTE")) and
        error.status in (401, 403)
    ):
        return True

    if error.message and '"type":"overloaded_error"' in error.message:
        return True

    if parse_max_tokens_context_overflow_error(error):
        return True

    headers = getattr(error, "headers", None)
    should_retry_header = headers.get("x-should-retry") if headers and hasattr(headers, "get") else None

    if should_retry_header == "true" and (not is_cloud_ai_subscriber() or is_enterprise_subscriber()):
        return True

    if should_retry_header == "false":
        is_5xx = error.status is not None and error.status >= 500
        if not (os.environ.get("USER_TYPE") == "ant" and is_5xx):
            return False

    if isinstance(error, APIConnectionError):
        return True

    if not error.status:
        return False

    if error.status == 408:  # Request timeout
        return True

    if error.status == 409:  # Lock timeout
        return True

    if error.status == 429:
        return not is_cloud_ai_subscriber() or is_enterprise_subscriber()

    if error.status == 401:
        clear_api_key_helper_cache()
        return True

    if is_oauth_token_revoked_error(error):
        return True

    if error.status >= 500:
        return True

    return False


# ============================================================
# MAIN RETRY GENERATOR
# ============================================================

async def with_retry(
    get_client: Callable,
    operation: Callable,
    options: RetryOptions,
) -> AsyncGenerator[Dict, Any]:
    """
    Async generator that retries an API operation with exponential backoff.

    Yields SystemAPIErrorMessage dicts on retryable errors.
    Returns the final result on success.
    Raises CannotRetryError or FallbackTriggeredError when exhausted.

    Args:
        get_client:  Async callable returning an Anthropic client.
        operation:   Async callable (client, attempt, context) -> result.
        options:     RetryOptions controlling retry behaviour.
    """
    max_retries = get_max_retries(options)
    retry_context = RetryContext(
        model=options.model,
        thinking_config=options.thinking_config,
        fast_mode=options.fast_mode if is_fast_mode_enabled() else None,
    )

    client = None
    consecutive_529_errors = options.initial_consecutive_529_errors
    last_error: Any = None
    persistent_attempt = 0
    attempt = 1

    while attempt <= max_retries + 1:
        # Respect abort signal
        signal = options.signal
        if signal and getattr(signal, "aborted", False):
            raise APIUserAbortError()

        was_fast_mode_active = (
            is_fast_mode_enabled() and
            bool(retry_context.fast_mode) and
            not is_fast_mode_cooldown()
        )

        try:
            # Mock rate-limit injection (ant employees only)
            if os.environ.get("USER_TYPE") == "ant":
                mock_error = check_mock_rate_limit_error(retry_context.model, was_fast_mode_active)
                if mock_error:
                    raise mock_error

            # Refresh client on first attempt or after auth/stale-connection errors
            is_stale = is_stale_connection_error(last_error)
            if is_stale and get_feature_value_cached_may_be_stale(
                "tengu_disable_keepalive_on_econnreset", False
            ):
                log_for_debugging("Stale connection (ECONNRESET/EPIPE) — disabling keep-alive for retry")
                disable_keep_alive()

            need_fresh_client = (
                client is None or
                (isinstance(last_error, APIError) and last_error.status == 401) or
                is_oauth_token_revoked_error(last_error) or
                is_bedrock_auth_error(last_error) or
                is_vertex_auth_error(last_error) or
                is_stale
            )
            if need_fresh_client:
                # Force token refresh on 401 / token-revoked
                if isinstance(last_error, APIError) and last_error.status == 401 or is_oauth_token_revoked_error(last_error):
                    tokens = get_cloud_ai_oauth_tokens()
                    if tokens and tokens.get("accessToken"):
                        await handle_oauth_401_error(tokens["accessToken"])
                client = await get_client()

            result = await operation(client, attempt, retry_context)
            raise StopAsyncIteration(result)  # Success — exit generator

        except Exception as error:
            last_error = error
            status = getattr(error, "status", None)
            log_for_debugging(
                f"API error (attempt {attempt}/{max_retries + 1}): "
                f"{status} {error_message(error)}" if isinstance(error, APIError) else error_message(error),
                {"level": "error"},
            )

            # ---- Fast mode: short-retry or cooldown on 429/529 ----
            if (
                was_fast_mode_active and
                not is_persistent_retry_enabled() and
                isinstance(error, APIError) and
                (error.status == 429 or is_529_error(error))
            ):
                headers = getattr(error, "headers", None)
                overage_reason = headers.get(
                    "anthropic-ratelimit-unified-overage-disabled-reason"
                ) if headers and hasattr(headers, "get") else None

                if overage_reason is not None:
                    handle_fast_mode_overage_rejection(overage_reason)
                    retry_context.fast_mode = False
                    attempt += 1
                    continue

                retry_after_ms = get_retry_after_ms(error)
                if retry_after_ms is not None and retry_after_ms < SHORT_RETRY_THRESHOLD_MS:
                    await sleep(retry_after_ms, signal, {"abortError": lambda: APIUserAbortError()})
                    attempt += 1
                    continue

                cooldown_ms = max(
                    retry_after_ms if retry_after_ms is not None else DEFAULT_FAST_MODE_FALLBACK_HOLD_MS,
                    MIN_COOLDOWN_MS,
                )
                cooldown_reason: CooldownReason = "overloaded" if is_529_error(error) else "rate_limit"
                trigger_fast_mode_cooldown(int(time.time() * 1000) + cooldown_ms, cooldown_reason)
                if is_fast_mode_enabled():
                    retry_context.fast_mode = False
                attempt += 1
                continue

            # ---- Fast mode: API rejected fast mode parameter ----
            if was_fast_mode_active and is_fast_mode_not_enabled_error(error):
                handle_fast_mode_rejected_by_api()
                retry_context.fast_mode = False
                attempt += 1
                continue

            # ---- Background 529: drop immediately, no retry amplification ----
            if is_529_error(error) and not should_retry_529(options.query_source):
                log_event("tengu_api_529_background_dropped", {"query_source": options.query_source or ""})
                raise CannotRetryError(error, retry_context)

            # ---- Consecutive 529 tracking → model fallback ----
            if is_529_error(error) and (
                os.environ.get("FALLBACK_FOR_ALL_PRIMARY_MODELS") or
                (not is_cloud_ai_subscriber() and is_non_custom_opus_model(options.model))
            ):
                consecutive_529_errors += 1
                if consecutive_529_errors >= MAX_529_RETRIES:
                    if options.fallback_model:
                        log_event("tengu_api_opus_fallback_triggered", {
                            "original_model": options.model,
                            "fallback_model": options.fallback_model,
                            "provider": get_api_provider_for_statsig(),
                        })
                        raise FallbackTriggeredError(options.model, options.fallback_model)

                    if (
                        os.environ.get("USER_TYPE") == "external" and
                        not os.environ.get("IS_SANDBOX") and
                        not is_persistent_retry_enabled()
                    ):
                        log_event("tengu_api_custom_529_overloaded_error", {})
                        raise CannotRetryError(
                            Exception(REPEATED_529_ERROR_MESSAGE),
                            retry_context,
                        )

            # ---- Exhausted retries ----
            persistent = is_persistent_retry_enabled() and is_transient_capacity_error(error)
            if attempt > max_retries and not persistent:
                raise CannotRetryError(error, retry_context)

            # ---- Cloud auth refresh ----
            handled_cloud_auth = handle_aws_credential_error(error) or handle_gcp_credential_error(error)
            if not handled_cloud_auth and (
                not isinstance(error, APIError) or not should_retry(error)
            ):
                raise CannotRetryError(error, retry_context)

            # ---- Context overflow: adjust max_tokens ----
            if isinstance(error, APIError):
                overflow = parse_max_tokens_context_overflow_error(error)
                if overflow:
                    input_tokens = overflow["inputTokens"]
                    context_limit = overflow["contextLimit"]
                    safety_buffer = 1000
                    available = max(0, context_limit - input_tokens - safety_buffer)
                    if available < FLOOR_OUTPUT_TOKENS:
                        log_error(Exception(
                            f"availableContext {available} is less than FLOOR_OUTPUT_TOKENS {FLOOR_OUTPUT_TOKENS}"
                        ))
                        raise error

                    thinking = retry_context.thinking_config or {}
                    min_required = (
                        thinking.get("budgetTokens", 0)
                        if thinking.get("type") == "enabled"
                        else 0
                    ) + 1
                    adjusted = max(FLOOR_OUTPUT_TOKENS, available, min_required)
                    retry_context.max_tokens_override = adjusted
                    log_event("tengu_max_tokens_context_overflow_adjustment", {
                        "inputTokens": input_tokens,
                        "contextLimit": context_limit,
                        "adjustedMaxTokens": adjusted,
                        "attempt": attempt,
                    })
                    attempt += 1
                    continue

            # ---- Compute backoff delay ----
            retry_after = get_retry_after(error)
            if persistent and isinstance(error, APIError) and error.status == 429:
                persistent_attempt += 1
                reset_delay = get_rate_limit_reset_delay_ms(error)
                delay_ms = (
                    reset_delay if reset_delay is not None
                    else min(
                        get_retry_delay(persistent_attempt, retry_after, PERSISTENT_MAX_BACKOFF_MS),
                        PERSISTENT_RESET_CAP_MS,
                    )
                )
            elif persistent:
                persistent_attempt += 1
                delay_ms = min(
                    get_retry_delay(persistent_attempt, retry_after, PERSISTENT_MAX_BACKOFF_MS),
                    PERSISTENT_RESET_CAP_MS,
                )
            else:
                delay_ms = get_retry_delay(attempt, retry_after)

            reported_attempt = persistent_attempt if persistent else attempt
            log_event("tengu_api_retry", {
                "attempt": reported_attempt,
                "delayMs": delay_ms,
                "error": error_message(error),
                "status": getattr(error, "status", None),
                "provider": get_api_provider_for_statsig(),
            })

            # ---- Sleep (chunked in persistent mode for keep-alive) ----
            if persistent:
                if delay_ms > 60_000:
                    log_event("tengu_api_persistent_retry_wait", {
                        "status": getattr(error, "status", None),
                        "delayMs": delay_ms,
                        "attempt": reported_attempt,
                        "provider": get_api_provider_for_statsig(),
                    })

                remaining = delay_ms
                while remaining > 0:
                    if signal and getattr(signal, "aborted", False):
                        raise APIUserAbortError()
                    if isinstance(error, APIError):
                        yield create_system_api_error_message(error, int(remaining), reported_attempt, max_retries)
                    chunk = min(remaining, HEARTBEAT_INTERVAL_MS)
                    await sleep(chunk, signal, {"abortError": lambda: APIUserAbortError()})
                    remaining -= chunk

                # Clamp so the while loop never terminates; backoff uses persistentAttempt
                if attempt >= max_retries:
                    attempt = max_retries
            else:
                if isinstance(error, APIError):
                    yield create_system_api_error_message(error, int(delay_ms), attempt, max_retries)
                await sleep(delay_ms, signal, {"abortError": lambda: APIUserAbortError()})

        attempt += 1

    raise CannotRetryError(last_error, retry_context)


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    # Data classes
    "RetryContext",
    "RetryOptions",
    # Exceptions
    "CannotRetryError",
    "FallbackTriggeredError",
    # Main function
    "with_retry",
    # Utilities
    "get_retry_delay",
    "get_default_max_retries",
    "parse_max_tokens_context_overflow_error",
    "is_529_error",
    "should_retry_529",
    # Constants
    "BASE_DELAY_MS",
]
