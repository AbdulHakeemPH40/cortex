"""
UUID generation and validation utilities for Cortex IDE.

Provides functions to:
- Generate unique agent IDs with optional labels
- Validate UUID format
"""

import os
import re
from typing import Optional

# Standard UUID format: 8-4-4-4-12 hex digits
UUID_REGEX = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)

# Agent ID pattern: a + optional <label>- + 16 hex chars
AGENT_ID_PATTERN = re.compile(r'^a(?:.+-)?[0-9a-f]{16}$')


def validate_uuid(maybe_uuid: any) -> Optional[str]:
    """
    Validate uuid.
    
    Args:
        maybe_uuid: The value to be checked if it is a uuid
        
    Returns:
        string as UUID or None if it is not valid
        
    Format: 8-4-4-4-12 hex digits
    """
    # UUID format: 8-4-4-4-12 hex digits
    if not isinstance(maybe_uuid, str):
        return None

    return maybe_uuid if UUID_REGEX.match(maybe_uuid) else None


def create_agent_id(label: Optional[str] = None) -> str:
    """
    Generate a new agent ID with prefix for consistency with task IDs.
    
    Args:
        label: Optional label to include in the agent ID
        
    Returns:
        Generated agent ID in format: a{label-}{16 hex chars}
        
    Examples:
        create_agent_id() -> "aa3f2c1b4d5e6f7a"
        create_agent_id('skill') -> "askill-a3f2c1b4d5e6f7a"
    """
    suffix = os.urandom(8).hex()
    return f"a{label}-{suffix}" if label else f"a{suffix}"


def validate_agent_id(maybe_agent_id: str) -> Optional[str]:
    """
    Validate and return agent ID if it matches the expected format.
    
    Args:
        maybe_agent_id: The value to validate as an agent ID
        
    Returns:
        The agent ID string if valid, None otherwise
        
    Format: a + optional <label>- + 16 hex chars
    """
    if not isinstance(maybe_agent_id, str):
        return None

    return maybe_agent_id if AGENT_ID_PATTERN.match(maybe_agent_id) else None
