# ------------------------------------------------------------
# tokenEstimation.py
# Python conversion of services/tokenEstimation.ts (lines 1-496)
#
# Token estimation and counting for multi-LLM context management.
# Supports:
# - API-based token counting (Anthropic, OpenAI, Google)
# - Haiku/Sonnet fallback token estimation via LLM calls
# - Rough byte-based estimation for offline scenarios
# - Bedrock and Vertex AI provider support
# - Thinking block handling for reasoning models
# Multi-LLM compatible: Claude, OpenAI, Gemini, Bedrock, Vertex
# ------------------------------------------------------------

import json
from typing import Any, Dict, List, Optional, Union

# ============================================================
# DEPS — defensive fallbacks for unconverted cross-modules
# ============================================================

try:
    from ..constants.betas import VERTEX_COUNT_TOKENS_ALLOWED_BETAS
except ImportError:
    VERTEX_COUNT_TOKENS_ALLOWED_BETAS = set()

try:
    from ..utils.betas import get_model_betas
except ImportError:
    def get_model_betas(model: str) -> List[str]:
        """Stub - returns model betas"""
        return []

try:
    from ..utils.env_utils import get_vertex_region_for_model, is_env_truthy
except ImportError:
    def get_vertex_region_for_model(model: str) -> str:
        return "global"
    
    def is_env_truthy(var_name: str) -> bool:
        import os
        return os.environ.get(var_name, "").lower() in ("1", "true", "yes")

try:
    from ..utils.log import log_error
except ImportError:
    def log_error(error: Exception) -> None:
        """Stub - logs error"""
        print(f"[ERROR] {error}", flush=True)

try:
    from ..utils.messages import normalize_attachment_for_api
except ImportError:
    def normalize_attachment_for_api(attachment: Any) -> List[Dict[str, Any]]:
        """Stub - normalizes attachment for API"""
        return []

try:
    from ..utils.model.model import (
        get_default_sonnet_model,
        get_main_loop_model,
        get_small_fast_model,
        normalize_model_string_for_api,
    )
except ImportError:
    def get_default_sonnet_model() -> str:
        return "claude-sonnet-4-20250514"
    
    def get_main_loop_model() -> str:
        return "claude-sonnet-4-20250514"
    
    def get_small_fast_model() -> str:
        return "claude-3-5-haiku-4-20250514"
    
    def normalize_model_string_for_api(model: str) -> str:
        return model

try:
    from ..utils.slowOperations import json_stringify
except ImportError:
    def json_stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, default=str)

try:
    from ..utils.toolSearch import is_tool_reference_block
except ImportError:
    def is_tool_reference_block(block: Any) -> bool:
        """Stub - checks if block is tool reference"""
        return False

try:
    from ..services.api.cortex import get_api_metadata, get_extra_body_params
except ImportError:
    def get_api_metadata() -> Dict[str, Any]:
        return {}
    
    def get_extra_body_params() -> Dict[str, Any]:
        return {}

try:
    from ..services.api.client import get_anthropic_client
except ImportError:
    async def get_anthropic_client(**kwargs) -> Any:
        """Stub - returns Anthropic client"""
        raise NotImplementedError("get_anthropic_client not implemented")

try:
    from ..utils.model.providers import get_api_provider
except ImportError:
    def get_api_provider() -> str:
        """Stub - returns API provider"""
        import os
        if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
            return "bedrock"
        if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
            return "vertex"
        return "anthropic"

try:
    from ..utils.model.bedrock import (
        create_bedrock_runtime_client,
        get_inference_profile_backing_model,
        is_foundation_model,
    )
except ImportError:
    async def create_bedrock_runtime_client() -> Any:
        raise NotImplementedError("Bedrock client not available")
    
    async def get_inference_profile_backing_model(model: str) -> Optional[str]:
        return None
    
    def is_foundation_model(model: str) -> bool:
        return False

try:
    from ..services.vcr import with_token_count_vcr
except ImportError:
    async def with_token_count_vcr(messages, tools, func):
        """Stub - VCR wrapper for token counting"""
        return await func()


# ============================================================
# CONSTANTS
# ============================================================

# Minimal values for token counting with thinking enabled
# API constraint: max_tokens must be greater than thinking.budget_tokens
TOKEN_COUNT_THINKING_BUDGET = 1024
TOKEN_COUNT_MAX_TOKENS = 2048


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def has_thinking_blocks(messages: List[Dict[str, Any]]) -> bool:
    """
    Check if messages contain thinking blocks.
    
    Mirrors TS hasThinkingBlocks() exactly.
    
    Args:
        messages: List of message dicts
    
    Returns:
        True if any assistant message contains thinking blocks
    """
    for message in messages:
        if message.get("role") == "assistant" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if (
                    isinstance(block, dict) and
                    block.get("type") in ("thinking", "redacted_thinking")
                ):
                    return True
    return False


def strip_tool_search_fields_from_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Strip tool search-specific fields from messages before sending for token counting.
    
    This removes 'caller' from tool_use blocks and 'tool_reference' from tool_result content.
    These fields are only valid with the tool search beta and will cause errors otherwise.
    
    Mirrors TS stripToolSearchFieldsFromMessages() exactly.
    """
    normalized_messages = []
    
    for message in messages:
        if not isinstance(message.get("content"), list):
            normalized_messages.append(message)
            continue
        
        normalized_content = []
        for block in message["content"]:
            # Strip 'caller' from tool_use blocks (assistant messages)
            if block.get("type") == "tool_use":
                normalized_content.append({
                    "type": "tool_use",
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input"),
                })
            
            # Strip tool_reference blocks from tool_result content (user messages)
            elif block.get("type") == "tool_result":
                if isinstance(block.get("content"), list):
                    filtered_content = [
                        c for c in block["content"]
                        if not is_tool_reference_block(c)
                    ]
                    
                    if len(filtered_content) == 0:
                        normalized_content.append({
                            **block,
                            "content": [{"type": "text", "text": "[tool references]"}],
                        })
                    elif len(filtered_content) != len(block["content"]):
                        normalized_content.append({
                            **block,
                            "content": filtered_content,
                        })
                    else:
                        normalized_content.append(block)
                else:
                    normalized_content.append(block)
            
            else:
                normalized_content.append(block)
        
        normalized_messages.append({
            **message,
            "content": normalized_content,
        })
    
    return normalized_messages


# ============================================================
# API-BASED TOKEN COUNTING
# ============================================================

async def count_tokens_with_api(content: str) -> Optional[int]:
    """
    Count tokens in a string using the API.
    
    Mirrors TS countTokensWithAPI() exactly.
    
    Args:
        content: Text content to count tokens for
    
    Returns:
        Token count, or None on error
    """
    # Special case for empty content - API doesn't accept empty messages
    if not content:
        return 0
    
    message = {
        "role": "user",
        "content": content,
    }
    
    return await count_messages_tokens_with_api([message], [])


async def count_messages_tokens_with_api(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Optional[int]:
    """
    Count tokens in messages using the API.
    
    Mirrors TS countMessagesTokensWithAPI() exactly.
    Multi-LLM compatible: routes to appropriate provider (Anthropic/Bedrock/Vertex).
    
    Args:
        messages: List of message dicts
        tools: List of tool definitions
    
    Returns:
        Token count, or None on error
    """
    async def _do_count():
        try:
            model = get_main_loop_model()
            betas = get_model_betas(model)
            contains_thinking = has_thinking_blocks(messages)
            
            # Route to Bedrock if configured
            if get_api_provider() == "bedrock":
                return await count_tokens_with_bedrock({
                    "model": normalize_model_string_for_api(model),
                    "messages": messages,
                    "tools": tools,
                    "betas": betas,
                    "contains_thinking": contains_thinking,
                })
            
            # For Anthropic/Vertex, use SDK countTokens
            anthropic = await get_anthropic_client({
                "maxRetries": 1,
                "model": model,
                "source": "count_tokens",
            })
            
            # Filter betas for Vertex - some betas cause 400 errors
            filtered_betas = (
                [b for b in betas if b in VERTEX_COUNT_TOKENS_ALLOWED_BETAS]
                if get_api_provider() == "vertex"
                else betas
            )
            
            # Build request payload
            request_params = {
                "model": normalize_model_string_for_api(model),
                "messages": messages if len(messages) > 0 else [{"role": "user", "content": "foo"}],
                "tools": tools,
            }
            
            if filtered_betas:
                request_params["betas"] = filtered_betas
            
            if contains_thinking:
                request_params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": TOKEN_COUNT_THINKING_BUDGET,
                }
            
            response = await anthropic.beta.messages.count_tokens(**request_params)
            
            if not isinstance(response.get("input_tokens"), (int, float)):
                # Vertex client throws, Bedrock succeeds with error response
                return None
            
            return response["input_tokens"]
            
        except Exception as error:
            log_error(error)
            return None
    
    return await with_token_count_vcr(messages, tools, _do_count)


# ============================================================
# ROUGH TOKEN ESTIMATION (Byte-Based)
# ============================================================

def rough_token_count_estimation(
    content: str,
    bytes_per_token: float = 4.0,
) -> int:
    """
    Estimate token count using byte-length heuristic.
    
    Mirrors TS roughTokenCountEstimation() exactly.
    
    Args:
        content: Text content
        bytes_per_token: Bytes per token ratio (default 4, ~2 for JSON)
    
    Returns:
        Estimated token count
    """
    return round(len(content) / bytes_per_token)


def bytes_per_token_for_file_type(file_extension: str) -> float:
    """
    Returns an estimated bytes-per-token ratio for a given file extension.
    
    Dense JSON has many single-character tokens (`{`, `}`, `:`, `,`, `"`)
    which makes the real ratio closer to 2 rather than the default 4.
    
    Mirrors TS bytesPerTokenForFileType() exactly.
    """
    if file_extension in ("json", "jsonl", "jsonc"):
        return 2.0
    return 4.0


def rough_token_count_estimation_for_file_type(
    content: str,
    file_extension: str,
) -> int:
    """
    Like rough_token_count_estimation but uses accurate bytes-per-token for file type.
    
    This matters when API-based token count is unavailable (e.g. on Bedrock)
    and we fall back to rough estimate.
    
    Mirrors TS roughTokenCountEstimationForFileType() exactly.
    """
    return rough_token_count_estimation(
        content,
        bytes_per_token_for_file_type(file_extension),
    )


# ============================================================
# HAIKU FALLBACK TOKEN COUNTING
# ============================================================

async def count_tokens_via_haiku_fallback(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Optional[int]:
    """
    Estimates token count by making an LLM call and reading usage metadata.
    
    Uses Haiku for token counting (Haiku 4.5 supports thinking blocks), except:
    - Vertex global region: uses Sonnet (Haiku not available)
    - Bedrock with thinking blocks: uses Sonnet (Haiku 3.5 doesn't support thinking)
    
    Multi-LLM compatible: respects provider configuration.
    
    Mirrors TS countTokensViaHaikuFallback() exactly.
    """
    # Check if messages contain thinking blocks
    contains_thinking = has_thinking_blocks(messages)
    
    # Determine which model to use based on provider and thinking support
    is_vertex_global_endpoint = (
        is_env_truthy("CLAUDE_CODE_USE_VERTEX") and
        get_vertex_region_for_model(get_small_fast_model()) == "global"
    )
    is_bedrock_with_thinking = (
        is_env_truthy("CLAUDE_CODE_USE_BEDROCK") and contains_thinking
    )
    is_vertex_with_thinking = (
        is_env_truthy("CLAUDE_CODE_USE_VERTEX") and contains_thinking
    )
    
    # Use Sonnet for incompatible configurations, Haiku otherwise
    model = (
        get_default_sonnet_model()
        if is_vertex_global_endpoint or is_bedrock_with_thinking or is_vertex_with_thinking
        else get_small_fast_model()
    )
    
    anthropic = await get_anthropic_client({
        "maxRetries": 1,
        "model": model,
        "source": "count_tokens",
    })
    
    # Strip tool search-specific fields before sending
    normalized_messages = strip_tool_search_fields_from_messages(messages)
    
    messages_to_send = (
        normalized_messages
        if len(normalized_messages) > 0
        else [{"role": "user", "content": "count"}]
    )
    
    betas = get_model_betas(model)
    filtered_betas = (
        [b for b in betas if b in VERTEX_COUNT_TOKENS_ALLOWED_BETAS]
        if get_api_provider() == "vertex"
        else betas
    )
    
    # Build request payload
    request_params = {
        "model": normalize_model_string_for_api(model),
        "max_tokens": TOKEN_COUNT_MAX_TOKENS if contains_thinking else 1,
        "messages": messages_to_send,
        "metadata": get_api_metadata(),
        **get_extra_body_params(),
    }
    
    if tools:
        request_params["tools"] = tools
    
    if filtered_betas:
        request_params["betas"] = filtered_betas
    
    if contains_thinking:
        request_params["thinking"] = {
            "type": "enabled",
            "budget_tokens": TOKEN_COUNT_THINKING_BUDGET,
        }
    
    response = await anthropic.beta.messages.create(**request_params)
    
    usage = response.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
    cache_read_tokens = usage.get("cache_read_input_tokens", 0)
    
    return input_tokens + cache_creation_tokens + cache_read_tokens


# ============================================================
# MESSAGE-BASED TOKEN ESTIMATION
# ============================================================

def rough_token_count_estimation_for_messages(
    messages: List[Dict[str, Any]],
) -> int:
    """
    Estimate tokens for a list of messages.
    
    Mirrors TS roughTokenCountEstimationForMessages() exactly.
    """
    total_tokens = 0
    for message in messages:
        total_tokens += rough_token_count_estimation_for_message(message)
    return total_tokens


def rough_token_count_estimation_for_message(message: Dict[str, Any]) -> int:
    """
    Estimate tokens for a single message.
    
    Mirrors TS roughTokenCountEstimationForMessage() exactly.
    """
    if message.get("type") in ("assistant", "user") and message.get("message", {}).get("content"):
        return rough_token_count_estimation_for_content(
            message["message"]["content"]
        )
    
    if message.get("type") == "attachment" and message.get("attachment"):
        user_messages = normalize_attachment_for_api(message["attachment"])
        total = 0
        for user_msg in user_messages:
            total += rough_token_count_estimation_for_content(user_msg["message"]["content"])
        return total
    
    return 0


def rough_token_count_estimation_for_content(
    content: Union[str, List[Dict[str, Any]], None],
) -> int:
    """
    Estimate tokens for message content (string or block array).
    
    Mirrors TS roughTokenCountEstimationForContent() exactly.
    """
    if not content:
        return 0
    
    if isinstance(content, str):
        return rough_token_count_estimation(content)
    
    total_tokens = 0
    for block in content:
        total_tokens += rough_token_count_estimation_for_block(block)
    return total_tokens


def rough_token_count_estimation_for_block(
    block: Union[str, Dict[str, Any]],
) -> int:
    """
    Estimate tokens for a single content block.
    
    Mirrors TS roughTokenCountEstimationForBlock() exactly.
    """
    if isinstance(block, str):
        return rough_token_count_estimation(block)
    
    block_type = block.get("type")
    
    if block_type == "text":
        return rough_token_count_estimation(block.get("text", ""))
    
    if block_type in ("image", "document"):
        # Images resized to max 2000x2000 (5333 tokens)
        # Documents (PDFs): API charges ~2000 tokens regardless of size
        return 2000
    
    if block_type == "tool_result":
        return rough_token_count_estimation_for_content(block.get("content"))
    
    if block_type == "tool_use":
        # Input is JSON — stringify once for char count
        return rough_token_count_estimation(
            block.get("name", "") + json_stringify(block.get("input") or {})
        )
    
    if block_type == "thinking":
        return rough_token_count_estimation(block.get("thinking", ""))
    
    if block_type == "redacted_thinking":
        return rough_token_count_estimation(block.get("data", ""))
    
    # server_tool_use, web_search_tool_result, mcp_tool_use, etc.
    return rough_token_count_estimation(json_stringify(block))


# ============================================================
# BEDROCK TOKEN COUNTING
# ============================================================

async def count_tokens_with_bedrock(params: Dict[str, Any]) -> Optional[int]:
    """
    Count tokens using AWS Bedrock CountTokens API.
    
    Mirrors TS countTokensWithBedrock() exactly.
    
    Args:
        params: Dict with model, messages, tools, betas, contains_thinking
    
    Returns:
        Token count, or None on error
    """
    try:
        client = await create_bedrock_runtime_client()
        
        # Bedrock CountTokens requires a model ID, not an inference profile / ARN
        model = params["model"]
        model_id = model if is_foundation_model(model) else await get_inference_profile_backing_model(model)
        
        if not model_id:
            return None
        
        # Build request body with conditional spread (mirrors TS exactly)
        request_body: Dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": params["messages"] if len(params["messages"]) > 0 else [{"role": "user", "content": "foo"}],
            "max_tokens": TOKEN_COUNT_MAX_TOKENS if params["contains_thinking"] else 1,
        }
        
        # Conditional properties (mirrors TS spread operator)
        if len(params.get("tools", [])) > 0:
            request_body["tools"] = params["tools"]
        
        if len(params.get("betas", [])) > 0:
            request_body["anthropic_beta"] = params["betas"]
        
        if params["contains_thinking"]:
            request_body["thinking"] = {
                "type": "enabled",
                "budget_tokens": TOKEN_COUNT_THINKING_BUDGET,
            }
        
        # Dynamic import for optional AWS SDK
        try:
            from aws_sdk.client_bedrock_runtime import CountTokensCommand
        except ImportError:
            log_error(Exception("aws_sdk.client_bedrock_runtime not available"))
            return None
        
        # Build CountTokensCommand input (mirrors TS exactly)
        input_data = {
            "modelId": model_id,
            "input": {
                "invokeModel": {
                    "body": json_stringify(request_body).encode("utf-8"),
                },
            },
        }
        
        response = await client.send(CountTokensCommand(input_data))
        return response.get("inputTokens")
        
    except Exception as error:
        log_error(error)
        return None


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "count_tokens_with_api",
    "count_messages_tokens_with_api",
    "count_tokens_via_haiku_fallback",
    "count_tokens_with_bedrock",
    "rough_token_count_estimation",
    "rough_token_count_estimation_for_file_type",
    "rough_token_count_estimation_for_messages",
    "rough_token_count_estimation_for_message",
    "bytes_per_token_for_file_type",
    "has_thinking_blocks",
    "strip_tool_search_fields_from_messages",
    "TOKEN_COUNT_THINKING_BUDGET",
    "TOKEN_COUNT_MAX_TOKENS",
]
