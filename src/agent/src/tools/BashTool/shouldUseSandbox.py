# ------------------------------------------------------------
# shouldUseSandbox.py
# Python conversion of shouldUseSandbox.ts (lines 1-154)
# 
# Determines whether a bash command should run in the sandbox.
# ------------------------------------------------------------

from typing import Any, Dict, List, Optional, Set

try:
    from ...services.analytics.growthbook import get_feature_value_cached_may_be_stale
except ImportError:
    def get_feature_value_cached_may_be_stale(key: str, default: Any = None) -> Any:
        return default

try:
    from ...utils.bash.commands import split_command_deprecated
except ImportError:
    def split_command_deprecated(command: str) -> List[str]:
        """Stub: Split compound commands into subcommands."""
        # Simple split on && and || for stub
        import re
        return re.split(r'\s*(&&|\|\|)\s*', command)

try:
    from ...utils.sandbox.sandbox_adapter import SandboxManager
except ImportError:
    class SandboxManager:
        """Stub: Sandbox manager for command isolation."""
        
        @staticmethod
        def is_sandboxing_enabled() -> bool:
            return True
        
        @staticmethod
        def are_unsandboxed_commands_allowed() -> bool:
            return False

try:
    from ...utils.settings.settings import get_settings_deprecated
except ImportError:
    def get_settings_deprecated() -> Dict[str, Any]:
        return {"sandbox": {"excludedCommands": []}}

try:
    from .bashPermissions import (
        BINARY_HIJACK_VARS,
        bash_permission_rule,
        match_wildcard_pattern,
        strip_all_leading_env_vars,
        strip_safe_wrappers,
    )
except ImportError:
    # Stubs for bashPermissions dependencies
    BINARY_HIJACK_VARS: List[str] = []
    
    def bash_permission_rule(pattern: str):
        return {"type": "wildcard", "pattern": pattern}
    
    def match_wildcard_pattern(pattern: str, text: str) -> bool:
        import fnmatch
        return fnmatch.fnmatch(text, pattern)
    
    def strip_all_leading_env_vars(cmd: str, vars_list: List[str]) -> str:
        return cmd
    
    def strip_safe_wrappers(cmd: str) -> str:
        return cmd


# ============================================================
# TYPE DEFINITIONS
# ============================================================

class SandboxInput:
    """Input parameters for sandbox decision."""
    
    def __init__(
        self,
        command: Optional[str] = None,
        dangerously_disable_sandbox: bool = False,
    ):
        self.command = command
        self.dangerously_disable_sandbox = dangerously_disable_sandbox


# ============================================================
# SANDBOX EXCLUSION LOGIC
# ============================================================

def contains_excluded_command(command: str) -> bool:
    """
    Check if command contains any excluded commands or substrings.
    
    NOTE: excludedCommands is a user-facing convenience feature, not a security boundary.
    It is not a security bug to be able to bypass excludedCommands — the sandbox permission
    system (which prompts users) is the actual security control.
    
    Args:
        command: Full bash command string to check
        
    Returns:
        True if command contains excluded patterns
    """
    import os
    
    # Check dynamic config for disabled commands and substrings (only for ants)
    if os.environ.get("USER_TYPE") == "ant":
        disabled_config = get_feature_value_cached_may_be_stale(
            'tengu_sandbox_disabled_commands',
            {"commands": [], "substrings": []}
        )
        
        disabled_commands = disabled_config.get("commands", [])
        disabled_substrings = disabled_config.get("substrings", [])
        
        # Check if command contains any disabled substrings
        for substring in disabled_substrings:
            if substring in command:
                return True
        
        # Check if command starts with any disabled commands
        try:
            command_parts = split_command_deprecated(command)
            for part in command_parts:
                base_command = part.strip().split(' ')[0]
                if base_command and base_command in disabled_commands:
                    return True
        except Exception:
            # If we can't parse the command (e.g., malformed bash syntax),
            # treat it as not excluded to allow other validation checks to handle it
            # This prevents crashes when rendering tool use messages
            pass
    
    # Check user-configured excluded commands from settings
    settings = get_settings_deprecated()
    sandbox_config = settings.get("sandbox", {})
    user_excluded_commands = sandbox_config.get("excludedCommands", [])
    
    if not user_excluded_commands:
        return False
    
    # Split compound commands (e.g. "docker ps && curl evil.com") into individual
    # subcommands and check each one against excluded patterns. This prevents a
    # compound command from escaping the sandbox just because its first subcommand
    # matches an excluded pattern.
    try:
        subcommands = split_command_deprecated(command)
    except Exception:
        subcommands = [command]
    
    for subcommand in subcommands:
        trimmed = subcommand.strip()
        
        # Also try matching with env var prefixes and wrapper commands stripped, so
        # that `FOO=bar bazel ...` and `timeout 30 bazel ...` match `bazel:*`. Not a
        # security boundary (see NOTE at top); the &&-split above already lets
        # `export FOO=bar && bazel ...` match. BINARY_HIJACK_VARS kept as a heuristic.
        #
        # We iteratively apply both stripping operations until no new candidates are
        # produced (fixed-point), matching the approach in filterRulesByContentsMatchingInput.
        # This handles interleaved patterns like `timeout 300 FOO=bar bazel run`
        # where single-pass composition would fail.
        candidates = [trimmed]
        seen: Set[str] = set(candidates)
        start_idx = 0
        
        while start_idx < len(candidates):
            end_idx = len(candidates)
            for i in range(start_idx, end_idx):
                cmd = candidates[i]
                env_stripped = strip_all_leading_env_vars(cmd, BINARY_HIJACK_VARS)
                if env_stripped not in seen:
                    candidates.append(env_stripped)
                    seen.add(env_stripped)
                
                wrapper_stripped = strip_safe_wrappers(cmd)
                if wrapper_stripped not in seen:
                    candidates.append(wrapper_stripped)
                    seen.add(wrapper_stripped)
            
            start_idx = end_idx
        
        # Check each candidate against exclusion patterns
        for pattern in user_excluded_commands:
            rule = bash_permission_rule(pattern)
            rule_type = rule.get("type", "wildcard")
            
            for cand in candidates:
                if rule_type == "prefix":
                    prefix = rule.get("prefix", "")
                    if cand == prefix or cand.startswith(prefix + " "):
                        return True
                
                elif rule_type == "exact":
                    exact_cmd = rule.get("command", "")
                    if cand == exact_cmd:
                        return True
                
                elif rule_type == "wildcard":
                    wildcard_pattern = rule.get("pattern", "")
                    if match_wildcard_pattern(wildcard_pattern, cand):
                        return True
    
    return False


# ============================================================
# MAIN SANDBOX DECISION FUNCTION
# ============================================================

def should_use_sandbox(
    command: Optional[str] = None,
    dangerously_disable_sandbox: bool = False,
) -> bool:
    """
    Determine whether a bash command should run in the sandbox.
    
    Args:
        command: The bash command to evaluate
        dangerously_disable_sandbox: If True and policy allows, skip sandbox
        
    Returns:
        True if command should run in sandbox, False otherwise
    """
    if not SandboxManager.is_sandboxing_enabled():
        return False
    
    # Don't sandbox if explicitly overridden AND unsandboxed commands are allowed by policy
    if (
        dangerously_disable_sandbox and
        SandboxManager.are_unsandboxed_commands_allowed()
    ):
        return False
    
    if not command:
        return False
    
    # Don't sandbox if the command contains user-configured excluded commands
    if contains_excluded_command(command):
        return False
    
    return True


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "SandboxInput",
    "contains_excluded_command",
    "should_use_sandbox",
]
