"""
Groq-Specific Configuration and Optimizations
Ensures Groq works at maximum speed with proper tool support
"""

# Groq API Configuration
GROQ_BASE_URL = "https://api.groq.com"  # Without /openai/v1 path

# Tool calling configuration for Groq
# Groq supports OpenAI-compatible tool calling but with some limitations
GROQ_TOOL_CONFIG = {
    # Models that support tool calling well
    "supported_models": [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "llama3-8b-8192",
        "llama3-70b-8192",
        "llama-3.1-70b-versatile",
        "mixtral-8x7b-32768",
        "gemma-7b-it",
        "groq/compound",
        "groq/compound-mini",
    ],
    
    # Models that don't support tool calling well
    "no_tool_support": [
        "meta-llama/llama-prompt-guard-2-22m",
        "meta-llama/llama-prompt-guard-2-86m",
    ],
    
    # Best models for different tasks
    "best_for_tools": "llama-3.3-70b-versatile",  # Most reliable tool calling
    "best_for_speed": "llama-3.1-8b-instant",     # Fastest
    "best_for_reasoning": "groq/compound",        # Best reasoning
}

# Speed optimization settings
GROQ_SPEED_CONFIG = {
    # Disable tool throttling for Groq - let it run at full speed
    "throttle_tokens_per_second": None,
    
    # Higher concurrent requests for Groq's LPU
    "max_concurrent_requests": 10,
    
    # No artificial delays
    "min_delay_between_requests_ms": 0,
    
    # Allow longer streams for complex tasks
    "max_stream_duration_seconds": 600,  # 10 minutes
    
    # Don't compact context aggressively
    "compaction_threshold": 200000,  # 200k tokens
}

# Tool execution settings for Groq
GROQ_TOOL_EXECUTION = {
    # Execute tools asynchronously to not block Groq's streaming
    "async_execution": True,
    
    # Don't wait for tool results - continue streaming
    "non_blocking": True,
    
    # Maximum time to wait for tools (milliseconds)
    "max_wait_ms": 100,
    
    # If tool takes too long, skip it and continue
    "skip_slow_tools": True,
    
    # Tool timeout (seconds)
    "tool_timeout": 5.0,
}


def should_use_tools_with_groq(model: str) -> bool:
    """Check if a Groq model supports tool calling"""
    if model in GROQ_TOOL_CONFIG["no_tool_support"]:
        return False
    if model in GROQ_TOOL_CONFIG["supported_models"]:
        return True
    # Default to True for unknown models (they likely support it)
    return True


def get_optimal_groq_model(task: str = "general") -> str:
    """Get the best Groq model for a specific task"""
    if task == "tools" or task == "agent":
        return GROQ_TOOL_CONFIG["best_for_tools"]
    elif task == "speed":
        return GROQ_TOOL_CONFIG["best_for_speed"]
    elif task == "reasoning":
        return GROQ_TOOL_CONFIG["best_for_reasoning"]
    else:
        return GROQ_TOOL_CONFIG["best_for_tools"]  # Default to reliable model
