# bootstrap/state.py
# Application state management for Cortex AI Agent IDE
# Tracks session state, working directories, cost tracking, and runtime flags.

import os
import time
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field

# ============================================================================
# GLOBAL STATE VARIABLES
# ============================================================================

# Directory state
_original_cwd: str = ""
_project_root: str = ""
_session_id: str = "default"
_session_persistence_disabled: bool = False
_original_cwd_set: bool = False

# Agent-related state
_invoked_skills: Dict[str, Set[str]] = {}  # agent_id -> set of skills
_sdk_agent_progress_summaries_enabled: bool = False
_is_remote_mode: bool = False
_is_non_interactive_session: bool = False

# Feature flags
_chrome_flag_override: Optional[bool] = None
_flag_settings_path: Optional[str] = None
_inline_plugins: List[str] = []
_main_loop_model_override: Optional[str] = None
_session_bypass_permissions_mode: bool = False
_kairos_active: bool = False

# Token budget state
_current_turn_token_budget: Optional[int] = None
_turn_output_tokens: int = 0
_budget_continuation_count: int = 0

# Claude MD state
_additional_directories_for_claude_md: List[str] = []
_cached_claude_md_content: Dict[str, str] = {}

# Classifier state
_last_classifier_requests: List[Dict[str, Any]] = []
_turn_classifier_duration: float = 0.0

# ============================================================================
# COST TRACKING STATE
# ============================================================================


@dataclass
class CostState:
    """State for tracking API costs."""

    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_input_tokens: int = 0
    total_cache_read_input_tokens: int = 0
    total_api_duration_ms: float = 0.0
    total_api_duration_without_retries_ms: float = 0.0
    total_tool_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    total_web_search_requests: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    unknown_model_cost: bool = False
    model_usage: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sdk_betas: List[str] = field(default_factory=list)


_cost_state: CostState = CostState()
_cost_counter: int = 0
_token_counter: int = 0


# ============================================================================
# DIRECTORY & SESSION FUNCTIONS
# ============================================================================


def get_original_cwd() -> str:
    """Get the original working directory at startup."""
    return _original_cwd or os.getcwd()


def set_original_cwd(cwd: str) -> None:
    """Set the original working directory."""
    global _original_cwd, _original_cwd_set
    _original_cwd = cwd
    _original_cwd_set = True


def get_project_root() -> str:
    """Get the current project root directory."""
    return _project_root or os.getcwd()


def set_project_root(root: str) -> None:
    """Set the project root directory."""
    global _project_root
    _project_root = root


def get_session_id() -> str:
    """Get the current session ID."""
    return _session_id


def is_session_persistence_disabled() -> bool:
    """Check if session persistence is disabled."""
    return _session_persistence_disabled


def set_session_persistence_disabled(disabled: bool) -> None:
    """Set whether session persistence is disabled."""
    global _session_persistence_disabled
    _session_persistence_disabled = disabled


def switch_session(session_id: str) -> None:
    """Switch to a different session."""
    global _session_id
    _session_id = session_id


# CamelCase aliases for backward compatibility
def getOriginalCwd() -> str:
    """Get the original working directory (camelCase alias)."""
    return get_original_cwd()


def getProjectRoot() -> str:
    """Get project root (camelCase alias)."""
    return get_project_root()


def getSessionId() -> str:
    """Get session ID (camelCase alias)."""
    return get_session_id()


# ============================================================================
# AGENT STATE FUNCTIONS
# ============================================================================


def clear_invoked_skills_for_agent(agent_id: str) -> None:
    """Clear skills invoked by a specific agent."""
    if agent_id in _invoked_skills:
        _invoked_skills[agent_id].clear()


def get_invoked_skills_for_agent(agent_id: str) -> Set[str]:
    """Get skills invoked by a specific agent."""
    return _invoked_skills.get(agent_id, set())


def get_sdk_agent_progress_summaries_enabled() -> bool:
    """Check if SDK agent progress summaries are enabled."""
    return _sdk_agent_progress_summaries_enabled


def get_is_non_interactive_session() -> bool:
    """Check if running in non-interactive mode."""
    return _is_non_interactive_session or os.environ.get("CI", "").lower() in (
        "1",
        "true",
        "yes",
    )


def get_is_remote_mode() -> bool:
    """Check if running in remote mode."""
    return _is_remote_mode


# CamelCase aliases
def getInvokedSkillsForAgent(agent_id: str) -> Set[str]:
    """Get skills invoked by agent (camelCase alias)."""
    return get_invoked_skills_for_agent(agent_id)


# ============================================================================
# FEATURE FLAG FUNCTIONS
# ============================================================================


def get_chrome_flag_override() -> Optional[bool]:
    """Get Chrome flag override."""
    return _chrome_flag_override


def get_flag_settings_path() -> Optional[str]:
    """Get flag settings file path."""
    return _flag_settings_path


def get_inline_plugins() -> List[str]:
    """Get list of inline plugins."""
    return _inline_plugins


def get_main_loop_model_override() -> Optional[str]:
    """Get main loop model override."""
    return _main_loop_model_override


def get_session_bypass_permissions_mode() -> bool:
    """Check if session bypasses permissions."""
    return _session_bypass_permissions_mode


def get_kairos_active() -> bool:
    """Check if Kairos is active."""
    return _kairos_active


# CamelCase aliases
def getKairosActive() -> bool:
    """Check if Kairos is active (camelCase alias)."""
    return get_kairos_active()


# ============================================================================
# SDK BETAS
# ============================================================================


def get_sdk_betas() -> List[str]:
    """Get active SDK betas."""
    return _cost_state.sdk_betas


def set_sdk_betas(betas: List[str]) -> None:
    """Set SDK betas."""
    _cost_state.sdk_betas = betas


# CamelCase alias
def getSdkBetas() -> List[str]:
    """Get SDK betas (camelCase alias)."""
    return get_sdk_betas()


# ============================================================================
# TOKEN BUDGET FUNCTIONS
# ============================================================================


def get_current_turn_token_budget() -> Optional[int]:
    """Get current turn token budget."""
    return _current_turn_token_budget


def get_turn_output_tokens() -> int:
    """Get output tokens for current turn."""
    return _turn_output_tokens


def increment_budget_continuation_count() -> int:
    """Increment and return budget continuation count."""
    global _budget_continuation_count
    _budget_continuation_count += 1
    return _budget_continuation_count


def get_cwd_state() -> Dict[str, Any]:
    """Get current working directory state."""
    return {
        "cwd": get_original_cwd(),
        "project_root": get_project_root(),
        "session_id": get_session_id(),
    }


# ============================================================================
# CLAUDE MD FUNCTIONS
# ============================================================================


def get_additional_directories_for_claude_md() -> List[str]:
    """Get additional directories for CLAUDE.md lookup."""
    return _additional_directories_for_claude_md


def set_cached_claude_md_content(path: str, content: str) -> None:
    """Cache CLAUDE.md content."""
    _cached_claude_md_content[path] = content


def get_cached_claude_md_content(path: str) -> Optional[str]:
    """Get cached CLAUDE.md content."""
    return _cached_claude_md_content.get(path)


# CamelCase alias
def getCachedClaudeMdContent(path: str) -> Optional[str]:
    """Get cached CLAUDE.md content (camelCase alias)."""
    return get_cached_claude_md_content(path)


# ============================================================================
# CLASSIFIER FUNCTIONS
# ============================================================================


def get_last_classifier_requests() -> List[Dict[str, Any]]:
    """Get last classifier requests."""
    return _last_classifier_requests


def set_last_classifier_requests(requests: List[Dict[str, Any]]) -> None:
    """Set last classifier requests."""
    global _last_classifier_requests
    _last_classifier_requests = requests


def add_to_turn_classifier_duration(duration_ms: float) -> None:
    """Add to turn classifier duration."""
    global _turn_classifier_duration
    _turn_classifier_duration += duration_ms


# CamelCase aliases
def getLastClassifierRequests() -> List[Dict[str, Any]]:
    """Get last classifier requests (camelCase alias)."""
    return get_last_classifier_requests()


def setLastClassifierRequests(requests: List[Dict[str, Any]]) -> None:
    """Set last classifier requests (camelCase alias)."""
    set_last_classifier_requests(requests)


# ============================================================================
# COST TRACKING FUNCTIONS
# ============================================================================


def get_cost_counter() -> int:
    """Get the cost counter value."""
    return _cost_counter


def get_token_counter() -> int:
    """Get the token counter value."""
    return _token_counter


def get_total_cost_usd() -> float:
    """Get total cost in USD."""
    return _cost_state.total_cost_usd


def get_total_input_tokens() -> int:
    """Get total input tokens used."""
    return _cost_state.total_input_tokens


def get_total_output_tokens() -> int:
    """Get total output tokens used."""
    return _cost_state.total_output_tokens


def get_total_cache_creation_input_tokens() -> int:
    """Get total cache creation input tokens."""
    return _cost_state.total_cache_creation_input_tokens


def get_total_cache_read_input_tokens() -> int:
    """Get total cache read input tokens."""
    return _cost_state.total_cache_read_input_tokens


def get_total_api_duration() -> float:
    """Get total API duration in milliseconds."""
    return _cost_state.total_api_duration_ms


def get_total_api_duration_without_retries() -> float:
    """Get total API duration without retries."""
    return _cost_state.total_api_duration_without_retries_ms


def get_total_tool_duration() -> float:
    """Get total tool execution duration."""
    return _cost_state.total_tool_duration_ms


def get_total_duration() -> float:
    """Get total session duration."""
    return _cost_state.total_duration_ms


def get_total_web_search_requests() -> int:
    """Get total web search requests."""
    return _cost_state.total_web_search_requests


def get_total_lines_added() -> int:
    """Get total lines added."""
    return _cost_state.total_lines_added


def get_total_lines_removed() -> int:
    """Get total lines removed."""
    return _cost_state.total_lines_removed


def get_model_usage() -> Dict[str, Dict[str, Any]]:
    """Get usage by model."""
    return _cost_state.model_usage


def get_usage_for_model(model: str) -> Optional[Dict[str, Any]]:
    """Get usage for a specific model."""
    return _cost_state.model_usage.get(model)


def has_unknown_model_cost() -> bool:
    """Check if there's an unknown model cost."""
    return _cost_state.unknown_model_cost


def add_to_total_cost_state(cost: float) -> None:
    """Add to total cost."""
    _cost_state.total_cost_usd += cost
    global _cost_counter
    _cost_counter += 1


def add_to_total_lines_changed(added: int = 0, removed: int = 0) -> None:
    """Add to total lines changed."""
    _cost_state.total_lines_added += added
    _cost_state.total_lines_removed += removed


def set_has_unknown_model_cost(value: bool) -> None:
    """Set unknown model cost flag."""
    _cost_state.unknown_model_cost = value


def reset_cost_state() -> None:
    """Reset all cost state to defaults."""
    global _cost_state, _cost_counter, _token_counter
    _cost_state = CostState()
    _cost_counter = 0
    _token_counter = 0


def reset_state_for_tests() -> None:
    """Reset all state for testing."""
    global _original_cwd, _project_root, _session_id
    global _session_persistence_disabled, _original_cwd_set
    global _is_remote_mode, _is_non_interactive_session
    global _kairos_active, _budget_continuation_count
    global _turn_output_tokens, _current_turn_token_budget

    reset_cost_state()
    _original_cwd = ""
    _project_root = ""
    _session_id = "default"
    _session_persistence_disabled = False
    _original_cwd_set = False
    _is_remote_mode = False
    _is_non_interactive_session = False
    _kairos_active = False
    _budget_continuation_count = 0
    _turn_output_tokens = 0
    _current_turn_token_budget = None


def set_cost_state_for_restore(state: Dict[str, Any]) -> None:
    """Set cost state from a dictionary (for session restore)."""
    global _cost_state
    _cost_state.total_cost_usd = state.get("total_cost_usd", 0.0)
    _cost_state.total_input_tokens = state.get("total_input_tokens", 0)
    _cost_state.total_output_tokens = state.get("total_output_tokens", 0)
    _cost_state.model_usage = state.get("model_usage", {})


# ============================================================================
# COMPACTION FUNCTIONS
# ============================================================================


def mark_post_compaction() -> None:
    """Mark that post-compaction has occurred."""
    # Stub for compaction tracking
    pass


# ============================================================================
# USER MESSAGE STATE
# ============================================================================


def get_user_msg_opt_in() -> bool:
    """Check if user message opt-in is enabled."""
    return True  # Default to enabled


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Directory & session
    "get_original_cwd",
    "set_original_cwd",
    "get_project_root",
    "set_project_root",
    "get_session_id",
    "is_session_persistence_disabled",
    "set_session_persistence_disabled",
    "switch_session",
    "getOriginalCwd",
    "getProjectRoot",
    "getSessionId",
    # Agent state
    "clear_invoked_skills_for_agent",
    "get_invoked_skills_for_agent",
    "get_sdk_agent_progress_summaries_enabled",
    "get_is_non_interactive_session",
    "get_is_remote_mode",
    "getInvokedSkillsForAgent",
    # Feature flags
    "get_chrome_flag_override",
    "get_flag_settings_path",
    "get_inline_plugins",
    "get_main_loop_model_override",
    "get_session_bypass_permissions_mode",
    "get_kairos_active",
    "getKairosActive",
    # SDK betas
    "get_sdk_betas",
    "set_sdk_betas",
    "getSdkBetas",
    # Token budget
    "get_current_turn_token_budget",
    "get_turn_output_tokens",
    "increment_budget_continuation_count",
    "get_cwd_state",
    # Claude MD
    "get_additional_directories_for_claude_md",
    "set_cached_claude_md_content",
    "get_cached_claude_md_content",
    "getCachedClaudeMdContent",
    # Classifier
    "get_last_classifier_requests",
    "set_last_classifier_requests",
    "add_to_turn_classifier_duration",
    "getLastClassifierRequests",
    "setLastClassifierRequests",
    # Cost tracking
    "get_cost_counter",
    "get_token_counter",
    "get_total_cost_usd",
    "get_total_input_tokens",
    "get_total_output_tokens",
    "get_total_cache_creation_input_tokens",
    "get_total_cache_read_input_tokens",
    "get_total_api_duration",
    "get_total_api_duration_without_retries",
    "get_total_tool_duration",
    "get_total_duration",
    "get_total_web_search_requests",
    "get_total_lines_added",
    "get_total_lines_removed",
    "get_model_usage",
    "get_usage_for_model",
    "has_unknown_model_cost",
    "add_to_total_cost_state",
    "add_to_total_lines_changed",
    "set_has_unknown_model_cost",
    "reset_cost_state",
    "reset_state_for_tests",
    "set_cost_state_for_restore",
    # Compaction
    "mark_post_compaction",
    # User message
    "get_user_msg_opt_in",
]
