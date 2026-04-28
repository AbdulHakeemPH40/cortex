"""
Bundled Skills Index for Cortex IDE

Converts the TypeScript index.ts bundled skills registry to Python.
This module initializes and registers all Python-converted bundled skills
at startup.

Original: skills/bundled/index.ts (80 lines)

Note: Only registers skills that have been converted to Python.
Skipped skills (static prompts, internal-only, or deleted):
- keybindings.ts (static keyboard shortcut prompts)
- loremIpsum.ts (placeholder text generator)
- remember.ts (static memory prompts)
- verify.ts (internal-only, USER_TYPE === 'ant')
- stuck.ts (internal-only, USER_TYPE === 'ant')
- cortexInChrome.ts (MCP tool registration, deleted)
- cortexApi.ts (static documentation, deleted)
"""

import os
from typing import Any, Callable

# Import registration functions for converted Python skills
try:
    from ...skills.bundled.batch import register_batch_skill
except ImportError:
    register_batch_skill = None

try:
    from ...skills.bundled.debug import register_debug_skill
except ImportError:
    register_debug_skill = None

try:
    from ...skills.bundled.simplify import register_simplify_skill
except ImportError:
    register_simplify_skill = None

try:
    from ...skills.bundled.skillify import register_skillify_skill
except ImportError:
    register_skillify_skill = None

try:
    from ...skills.bundled.updateConfig import register_update_config_skill
except ImportError:
    register_update_config_skill = None


# =============================================================================
# FEATURE FLAG CHECKER
# =============================================================================

def feature(flag_name: str) -> bool:
    """
    Check if a feature flag is enabled.
    
    In Python, feature flags are typically controlled via environment variables.
    This function checks for FEATURE_<FLAG_NAME>=1 or <FLAG_NAME>=1.
    
    Args:
        flag_name: Name of the feature flag to check
        
    Returns:
        True if the feature flag is enabled
    """
    # Check for FEATURE_<FLAG_NAME>=1 or <FLAG_NAME>=1
    upper_flag = flag_name.upper()
    return (
        os.environ.get(f'FEATURE_{upper_flag}') == '1' or
        os.environ.get(upper_flag) == '1'
    )


# =============================================================================
# SKILL REGISTRATION
# =============================================================================

def _register_skill(
    register_fn: Callable | None,
    skill_name: str,
    register_callback: Callable[[dict[str, Any]], None]
) -> bool:
    """
    Register a single skill if the registration function exists.
    
    Args:
        register_fn: Registration function for the skill (or None if not converted)
        skill_name: Name of the skill (for logging)
        register_callback: Callback to register the skill with the system
        
    Returns:
        True if skill was registered, False otherwise
    """
    if register_fn is None:
        print(f"[Skills] Skipping {skill_name} (not converted to Python)")
        return False
    
    try:
        register_fn(register_callback)
        print(f"[Skills] Registered {skill_name}")
        return True
    except Exception as e:
        print(f"[Skills] Failed to register {skill_name}: {e}")
        return False


# =============================================================================
# MAIN INITIALIZATION FUNCTION
# =============================================================================

def init_bundled_skills(register_callback: Callable[[dict[str, Any]], None]) -> dict[str, bool]:
    """
    Initialize all bundled skills for Cortex IDE.
    
    Called at startup to register skills that ship with the IDE.
    Only registers skills that have been converted to Python.
    
    Args:
        register_callback: Function to register skills with the system.
                          Should accept a dict with skill configuration:
                          {
                              "name": str,
                              "description": str,
                              "allowed_tools": list[str],
                              "user_invocable": bool,
                              "get_prompt_for_command": async function
                          }
    
    Returns:
        Dictionary mapping skill names to registration success status
        
    Example:
        >>> def my_register(skill_config):
        ...     print(f"Registering: {skill_config['name']}")
        >>> results = init_bundled_skills(my_register)
        >>> print(results)
        {'update-config': True, 'debug': True, ...}
    """
    results = {}
    
    # =====================================================================
    # Always-Registered Skills (Core functionality)
    # =====================================================================
    
    # Update Config Skill - Settings management and hooks
    results['update-config'] = _register_skill(
        register_update_config_skill,
        "update-config",
        register_callback
    )
    
    # Debug Skill - Session debugging and log analysis
    results['debug'] = _register_skill(
        register_debug_skill,
        "debug",
        register_callback
    )
    
    # Skillify Skill - AI-powered skill creation from sessions
    results['skillify'] = _register_skill(
        register_skillify_skill,
        "skillify",
        register_callback
    )
    
    # Simplify Skill - 3 parallel review agents for code quality
    results['simplify'] = _register_skill(
        register_simplify_skill,
        "simplify",
        register_callback
    )
    
    # Batch Skill - Parallel agent orchestration (5-30 worktree agents)
    results['batch'] = _register_skill(
        register_batch_skill,
        "batch",
        register_callback
    )
    
    # =====================================================================
    # Feature-Gated Skills (Conditional registration)
    # =====================================================================
        
    # Note: schedule-remote-agents removed - cloud agent infrastructure not used
    
    # =====================================================================
    # Skipped Skills (Not converted to Python)
    # =====================================================================
    # These skills were analyzed and skipped for the following reasons:
    #
    # keybindings.ts     - Static keyboard shortcut prompts, no AI logic
    # loremIpsum.ts      - Placeholder text generator, no AI logic
    # remember.ts        - Static memory prompts, no AI logic
    # verify.ts          - Internal-only (USER_TYPE === 'ant')
    # stuck.ts           - Internal-only (USER_TYPE === 'ant')
    # cortexInChrome.ts  - MCP tool registration, deleted (no AI logic)
    # cortexApi.ts       - Static documentation bundling, deleted (no AI logic)
    #
    # Feature-gated skills (not converted):
    # dream.ts           - Feature: KAIROS/KAIROS_DREAM
    # hunter.ts          - Feature: REVIEW_ARTIFACT
    # loop.ts            - Feature: AGENT_TRIGGERS
    # runSkillGenerator.ts - Feature: RUN_SKILL_GENERATOR
    
    # Log summary
    registered = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"[Skills] Initialized {registered}/{total} bundled skills")
    
    return results


# =============================================================================
# BACKWARD COMPATIBILITY ALIAS
# =============================================================================

# Alias to match TypeScript function name
initBundledSkills = init_bundled_skills
