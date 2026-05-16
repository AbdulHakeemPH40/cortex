"""
services/oauth/getOauthProfile.py
Python conversion of services/oauth/getOauthProfile.ts (54 lines)

Fetch OAuth profile information from API using either API key or OAuth token.
"""

import logging
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    requests = None

try:
    from ...constants.oauth import get_oauth_config, OAUTH_BETA_HEADER
except ImportError:
    def get_oauth_config():
        return {}
    OAUTH_BETA_HEADER = 'oauth-enabled=true'

try:
    from ...utils.auth import get_anthropic_api_key
except ImportError:
    def get_anthropic_api_key():
        return None

try:
    from ...utils.config import get_global_config
except ImportError:
    def get_global_config():
        return {}

try:
    from ...utils.log import log_error
except ImportError:
    def log_error(error: Exception):
        print(f"[ERROR] {error}")

logger = logging.getLogger(__name__)


async def get_oauth_profile_from_api_key() -> Optional[Dict[str, Any]]:
    """
    Fetch OAuth profile using API key authentication.
    Assumes interactive session.
    
    Returns:
        OAuth profile response or None if failed
    """
    # Need both account UUID and API key to check
    config = get_global_config()
    account_uuid = config.get('oauthAccount', {}).get('accountUuid')
    api_key = get_anthropic_api_key()
    
    if not account_uuid or not api_key:
        return None
    
    oauth_config = get_oauth_config()
    endpoint = f"{oauth_config.get('BASE_API_URL', '')}/api/claude_cli_profile"
    
    try:
        response = requests.get(
            endpoint,
            headers={
                'x-api-key': api_key,
                'anthropic-beta': OAUTH_BETA_HEADER,
            },
            params={
                'account_uuid': account_uuid,
            },
            timeout=10,
        )
        
        if response.status_code == 200:
            return response.json()
        
        return None
    except Exception as error:
        log_error(error)
        return None


async def get_oauth_profile_from_oauth_token(
    access_token: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch OAuth profile using OAuth token authentication.
    
    Args:
        access_token: OAuth access token
        
    Returns:
        OAuth profile response or None if failed
    """
    oauth_config = get_oauth_config()
    endpoint = f"{oauth_config.get('BASE_API_URL', '')}/api/oauth/profile"
    
    try:
        response = requests.get(
            endpoint,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            timeout=10,
        )
        
        if response.status_code == 200:
            return response.json()
        
        return None
    except Exception as error:
        log_error(error)
        return None


__all__ = [
    'get_oauth_profile_from_api_key',
    'get_oauth_profile_from_oauth_token',
]
