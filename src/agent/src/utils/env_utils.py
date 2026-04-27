# env_utils.py
# Python conversion of envUtils.ts
# Environment utility functions

import os
from pathlib import Path


def get_cortex_config_home_dir() -> str:
    """Get the Cortex config home directory."""
    config_dir = os.environ.get('CORTEX_CONFIG_DIR')
    if config_dir:
        return config_dir
    return str(Path.home() / '.cortex')


def get_teams_dir() -> str:
    """Get the teams directory."""
    return str(Path(get_cortex_config_home_dir()) / 'teams')


def has_node_option(flag: str) -> bool:
    """Check if NODE_OPTIONS contains a specific flag."""
    node_options = os.environ.get('NODE_OPTIONS', '')
    if not node_options:
        return False
    return flag in node_options.split()


def is_env_truthy(env_var) -> bool:
    """
    Check if an environment variable value is truthy.
    
    Args:
        env_var: Environment variable value (string, bool, or None)
    
    Returns:
        True if the value is truthy ('1', 'true', 'yes', 'on')
    """
    if not env_var:
        return False
    if isinstance(env_var, bool):
        return env_var
    normalized = str(env_var).lower().strip()
    return normalized in ['1', 'true', 'yes', 'on']


def is_env_defined_falsy(env_var) -> bool:
    """
    Check if an environment variable is defined but falsy.
    
    Args:
        env_var: Environment variable value
    
    Returns:
        True if defined and explicitly falsy ('0', 'false', 'no', 'off')
    """
    if env_var is None:
        return False
    if isinstance(env_var, bool):
        return not env_var
    if not env_var:
        return False
    normalized = str(env_var).lower().strip()
    return normalized in ['0', 'false', 'no', 'off']


__all__ = [
    'get_cortex_config_home_dir',
    'get_teams_dir',
    'has_node_option',
    'is_env_truthy',
    'is_env_defined_falsy',
]
