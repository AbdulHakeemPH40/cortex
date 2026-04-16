"""
services/oauth/oauthClient.py
Python conversion of services/oauth/client.ts (567 lines)

OAuth client for handling authentication flows with Claude services.
Manages token exchange, refresh, profile fetching, and account storage.
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    requests = None

try:
    from ...constants.oauth import (
        ALL_OAUTH_SCOPES,
        CLAUDE_AI_INFERENCE_SCOPE,
        CLAUDE_AI_OAUTH_SCOPES,
        get_oauth_config,
    )
except ImportError:
    # Fallback constants for standalone testing
    CLAUDE_AI_INFERENCE_SCOPE = 'claude:inference'
    ALL_OAUTH_SCOPES = ['claude:inference', 'user:profile', 'org:read']
    CLAUDE_AI_OAUTH_SCOPES = ['claude:inference', 'user:profile']
    def get_oauth_config():
        return {}

try:
    from ...utils.auth import (
        check_and_refresh_oauth_token_if_needed,
        get_cloud_ai_oauth_tokens,
        has_profile_scope,
        is_cloud_ai_subscriber,
        save_api_key,
    )
except ImportError:
    def check_and_refresh_oauth_token_if_needed():
        pass
    def get_cloud_ai_oauth_tokens():
        return None
    def has_profile_scope():
        return False
    def is_cloud_ai_subscriber():
        return False
    def save_api_key(key):
        pass

try:
    from ...utils.config import (
        get_global_config,
        save_global_config,
    )
except ImportError:
    def get_global_config():
        return {}
    def save_global_config(fn):
        pass

try:
    from ...utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(msg):
        print(f"[DEBUG] {msg}")

try:
    from ...services.analytics.index import log_event
except ImportError:
    def log_event(event_name: str, metadata: Optional[Dict[str, Any]] = None):
        pass

try:
    from .getOauthProfile import get_oauth_profile_from_oauth_token
except ImportError:
    async def get_oauth_profile_from_oauth_token(access_token: str):
        return None


# Type definitions
class OAuthTokens:
    """OAuth token response"""
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: int,
        scopes: list,
        subscription_type: Optional[str] = None,
        rate_limit_tier: Optional[str] = None,
        profile: Optional[Dict] = None,
        token_account: Optional[Dict] = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.scopes = scopes
        self.subscription_type = subscription_type
        self.rate_limit_tier = rate_limit_tier
        self.profile = profile
        self.token_account = token_account


def should_use_cloud_ai_auth(scopes: Optional[list]) -> bool:
    """Check if the user has Claude.ai authentication scope"""
    return bool(scopes and CLAUDE_AI_INFERENCE_SCOPE in scopes)


def parse_scopes(scope_string: Optional[str]) -> list:
    """Parse OAuth scope string into list"""
    if not scope_string:
        return []
    return [s for s in scope_string.split(' ') if s]


def build_auth_url(
    code_challenge: str,
    state: str,
    port: int,
    is_manual: bool,
    login_with_claude_ai: bool = False,
    inference_only: bool = False,
    org_uuid: Optional[str] = None,
    login_hint: Optional[str] = None,
    login_method: Optional[str] = None,
) -> str:
    """Build OAuth authorization URL"""
    config = get_oauth_config()
    
    auth_url_base = (
        config.get('CLAUDE_AI_AUTHORIZE_URL')
        if login_with_claude_ai
        else config.get('CONSOLE_AUTHORIZE_URL')
    )
    
    params = {
        'code': 'true',  # Show Claude Max upsell
        'client_id': config.get('CLIENT_ID', ''),
        'response_type': 'code',
        'redirect_uri': (
            config.get('MANUAL_REDIRECT_URL')
            if is_manual
            else f'http://localhost:{port}/callback'
        ),
        'scope': ' '.join(
            [CLAUDE_AI_INFERENCE_SCOPE]
            if inference_only
            else ALL_OAUTH_SCOPES
        ),
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'state': state,
    }
    
    if org_uuid:
        params['orgUUID'] = org_uuid
    if login_hint:
        params['login_hint'] = login_hint
    if login_method:
        params['login_method'] = login_method
    
    # Build URL with proper parameter encoding
    query_string = urlencode(params)
    separator = '&' if '?' in auth_url_base else '?'
    return f'{auth_url_base}{separator}{query_string}'


async def exchange_code_for_tokens(
    authorization_code: str,
    state: str,
    code_verifier: str,
    port: int,
    use_manual_redirect: bool = False,
    expires_in: Optional[int] = None,
) -> Dict[str, Any]:
    """Exchange authorization code for OAuth tokens"""
    if not requests:
        raise ImportError('requests library required for OAuth')
    
    config = get_oauth_config()
    
    request_body = {
        'grant_type': 'authorization_code',
        'code': authorization_code,
        'redirect_uri': (
            config.get('MANUAL_REDIRECT_URL')
            if use_manual_redirect
            else f'http://localhost:{port}/callback'
        ),
        'client_id': config.get('CLIENT_ID', ''),
        'code_verifier': code_verifier,
        'state': state,
    }
    
    if expires_in is not None:
        request_body['expires_in'] = expires_in
    
    try:
        response = requests.post(
            config.get('TOKEN_URL', ''),
            json=request_body,
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )
        
        if response.status_code != 200:
            error_msg = (
                'Authentication failed: Invalid authorization code'
                if response.status_code == 401
                else f'Token exchange failed ({response.status_code}): {response.reason}'
            )
            raise Exception(error_msg)
        
        log_event('tengu_oauth_token_exchange_success', {})
        return response.json()
    except Exception as e:
        log_event('tengu_oauth_token_exchange_failure', {
            'error': str(e),
        })
        raise


async def refresh_oauth_token(
    refresh_token: str,
    scopes: Optional[list] = None,
) -> OAuthTokens:
    """Refresh OAuth token"""
    if not requests:
        raise ImportError('requests library required for OAuth')
    
    config = get_oauth_config()
    
    request_body = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': config.get('CLIENT_ID', ''),
        'scope': ' '.join(
            scopes if scopes else CLAUDE_AI_OAUTH_SCOPES
        ),
    }
    
    try:
        response = requests.post(
            config.get('TOKEN_URL', ''),
            json=request_body,
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )
        
        if response.status_code != 200:
            raise Exception(f'Token refresh failed: {response.reason}')
        
        data = response.json()
        access_token = data.get('access_token')
        new_refresh_token = data.get('refresh_token', refresh_token)
        expires_in = data.get('expires_in', 0)
        expires_at = int(datetime.now().timestamp() * 1000) + (expires_in * 1000)
        scopes_list = parse_scopes(data.get('scope'))
        
        log_event('tengu_oauth_token_refresh_success', {})
        
        # Check if profile info already cached
        global_config = get_global_config()
        existing_tokens = get_cloud_ai_oauth_tokens()
        have_profile_already = (
            global_config.get('oauthAccount', {}).get('billingType') is not None
            and global_config.get('oauthAccount', {}).get('accountCreatedAt') is not None
            and global_config.get('oauthAccount', {}).get('subscriptionCreatedAt') is not None
            and (existing_tokens and existing_tokens.get('subscriptionType'))
            and (existing_tokens and existing_tokens.get('rateLimitTier'))
        )
        
        profile_info = None
        if not have_profile_already:
            profile_info = await fetch_profile_info(access_token)
        
        # Update config if profile changed
        if profile_info and global_config.get('oauthAccount'):
            updates = {}
            if profile_info.get('displayName'):
                updates['displayName'] = profile_info['displayName']
            if profile_info.get('hasExtraUsageEnabled') is not None:
                updates['hasExtraUsageEnabled'] = profile_info['hasExtraUsageEnabled']
            if profile_info.get('billingType'):
                updates['billingType'] = profile_info['billingType']
            if profile_info.get('accountCreatedAt'):
                updates['accountCreatedAt'] = profile_info['accountCreatedAt']
            if profile_info.get('subscriptionCreatedAt'):
                updates['subscriptionCreatedAt'] = profile_info['subscriptionCreatedAt']
            
            if updates:
                def update_config(current):
                    return {
                        **current,
                        'oauthAccount': {
                            **current.get('oauthAccount', {}),
                            **updates,
                        }
                    }
                save_global_config(update_config)
        
        return OAuthTokens(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_at=expires_at,
            scopes=scopes_list,
            subscription_type=profile_info.get('subscriptionType') if profile_info else existing_tokens.get('subscriptionType') if existing_tokens else None,
            rate_limit_tier=profile_info.get('rateLimitTier') if profile_info else existing_tokens.get('rateLimitTier') if existing_tokens else None,
            profile=profile_info.get('rawProfile') if profile_info else None,
            token_account=data.get('account'),
        )
    except Exception as e:
        log_event('tengu_oauth_token_refresh_failure', {
            'error': str(e),
        })
        raise


async def fetch_and_store_user_roles(access_token: str) -> None:
    """Fetch and store user roles"""
    if not requests:
        raise ImportError('requests library required for OAuth')
    
    config = get_oauth_config()
    
    try:
        response = requests.get(
            config.get('ROLES_URL', ''),
            headers={'Authorization': f'Bearer {access_token}'},
        )
        
        if response.status_code != 200:
            raise Exception(f'Failed to fetch user roles: {response.reason}')
        
        data = response.json()
        global_config = get_global_config()
        
        if not global_config.get('oauthAccount'):
            raise Exception('OAuth account information not found in config')
        
        def update_config(current):
            return {
                **current,
                'oauthAccount': {
                    **current.get('oauthAccount', {}),
                    'organizationRole': data.get('organization_role'),
                    'workspaceRole': data.get('workspace_role'),
                    'organizationName': data.get('organization_name'),
                }
            }
        
        save_global_config(update_config)
        
        log_event('tengu_oauth_roles_stored', {
            'org_role': data.get('organization_role'),
        })
    except Exception as e:
        log_event('tengu_oauth_roles_fetch_failed', {
            'error': str(e),
        })
        raise


async def create_and_store_api_key(access_token: str) -> Optional[str]:
    """Create and store API key"""
    if not requests:
        raise ImportError('requests library required for OAuth')
    
    config = get_oauth_config()
    
    try:
        response = requests.post(
            config.get('API_KEY_URL', ''),
            headers={'Authorization': f'Bearer {access_token}'},
        )
        
        api_key = response.json().get('raw_key') if response.status_code == 200 else None
        
        if api_key:
            # save_api_key might be async or sync, try to handle both
            result = save_api_key(api_key)
            if hasattr(result, '__await__'):  # Check if it's an awaitable
                await result
            
            log_event('tengu_oauth_api_key', {
                'status': 'success',
                'statusCode': response.status_code,
            })
            return api_key
        
        return None
    except Exception as e:
        log_event('tengu_oauth_api_key', {
            'status': 'failure',
            'error': str(e),
        })
        raise


def is_oauth_token_expired(expires_at: Optional[int]) -> bool:
    """Check if OAuth token is expired"""
    if expires_at is None:
        return False
    
    buffer_time_ms = 5 * 60 * 1000  # 5 minutes
    now_ms = int(datetime.now().timestamp() * 1000)
    expires_with_buffer = now_ms + buffer_time_ms
    
    return expires_with_buffer >= expires_at


async def fetch_profile_info(access_token: str) -> Optional[Dict[str, Any]]:
    """Fetch profile info from OAuth token"""
    try:
        profile = await get_oauth_profile_from_oauth_token(access_token)
        if not profile:
            return None
        
        org_type = profile.get('organization', {}).get('organization_type')
        
        # Map organization type to subscription type
        subscription_type_map = {
            'claude_max': 'max',
            'claude_pro': 'pro',
            'claude_enterprise': 'enterprise',
            'claude_team': 'team',
        }
        subscription_type = subscription_type_map.get(org_type)
        
        result = {
            'subscriptionType': subscription_type,
            'displayName': profile.get('account', {}).get('display_name'),
            'rateLimitTier': profile.get('organization', {}).get('rate_limit_tier'),
            'hasExtraUsageEnabled': profile.get('organization', {}).get('has_extra_usage_enabled'),
            'billingType': profile.get('organization', {}).get('billing_type'),
            'accountCreatedAt': profile.get('account', {}).get('created_at'),
            'subscriptionCreatedAt': profile.get('organization', {}).get('subscription_created_at'),
            'rawProfile': profile,
        }
        
        log_event('tengu_oauth_profile_fetch_success', {})
        return result
    except Exception as e:
        log_event('tengu_oauth_profile_fetch_failed', {
            'error': str(e),
        })
        return None


async def get_organization_uuid() -> Optional[str]:
    """Get organization UUID from OAuth token"""
    # Check global config first
    global_config = get_global_config()
    org_uuid = global_config.get('oauthAccount', {}).get('organizationUuid')
    if org_uuid:
        return org_uuid
    
    # Fall back to fetching from profile
    tokens = get_cloud_ai_oauth_tokens()
    if not tokens or not has_profile_scope():
        return None
    
    profile = await get_oauth_profile_from_oauth_token(tokens.get('accessToken'))
    if not profile:
        return None
    
    return profile.get('organization', {}).get('uuid')


async def populate_oauth_account_info_if_needed() -> bool:
    """Populate OAuth account info if not already cached"""
    import os
    
    # Check env vars first
    env_account_uuid = os.getenv('CLAUDE_CODE_ACCOUNT_UUID')
    env_user_email = os.getenv('CLAUDE_CODE_USER_EMAIL')
    env_organization_uuid = os.getenv('CLAUDE_CODE_ORGANIZATION_UUID')
    
    has_env_vars = bool(env_account_uuid and env_user_email and env_organization_uuid)
    
    if has_env_vars:
        global_config = get_global_config()
        if not global_config.get('oauthAccount'):
            store_oauth_account_info(
                account_uuid=env_account_uuid,
                email_address=env_user_email,
                organization_uuid=env_organization_uuid,
            )
    
    # Wait for any in-flight token refresh
    await check_and_refresh_oauth_token_if_needed()
    
    global_config = get_global_config()
    oauth_account = global_config.get('oauthAccount', {})
    
    if (
        oauth_account.get('billingType') is not None
        and oauth_account.get('accountCreatedAt') is not None
        and oauth_account.get('subscriptionCreatedAt') is not None
    ) or not is_cloud_ai_subscriber() or not has_profile_scope():
        return False
    
    tokens = get_cloud_ai_oauth_tokens()
    if tokens and tokens.get('accessToken'):
        profile = await get_oauth_profile_from_oauth_token(tokens.get('accessToken'))
        if profile:
            if has_env_vars:
                log_for_debugging('OAuth profile fetch succeeded, overriding env var account info')
            
            store_oauth_account_info(
                account_uuid=profile.get('account', {}).get('uuid'),
                email_address=profile.get('account', {}).get('email'),
                organization_uuid=profile.get('organization', {}).get('uuid'),
                display_name=profile.get('account', {}).get('display_name'),
                has_extra_usage_enabled=profile.get('organization', {}).get('has_extra_usage_enabled', False),
                billing_type=profile.get('organization', {}).get('billing_type'),
                account_created_at=profile.get('account', {}).get('created_at'),
                subscription_created_at=profile.get('organization', {}).get('subscription_created_at'),
            )
            return True
    
    return False


def store_oauth_account_info(
    account_uuid: str,
    email_address: str,
    organization_uuid: Optional[str] = None,
    display_name: Optional[str] = None,
    has_extra_usage_enabled: Optional[bool] = None,
    billing_type: Optional[str] = None,
    account_created_at: Optional[str] = None,
    subscription_created_at: Optional[str] = None,
) -> None:
    """Store OAuth account info in config"""
    account_info = {
        'accountUuid': account_uuid,
        'emailAddress': email_address,
        'organizationUuid': organization_uuid,
        'hasExtraUsageEnabled': has_extra_usage_enabled,
        'billingType': billing_type,
        'accountCreatedAt': account_created_at,
        'subscriptionCreatedAt': subscription_created_at,
    }
    
    if display_name:
        account_info['displayName'] = display_name
    
    def update_config(current):
        current_account = current.get('oauthAccount', {})
        # Check if unchanged before updating
        if current_account == account_info:
            return current
        
        return {
            **current,
            'oauthAccount': account_info,
        }
    
    save_global_config(update_config)


__all__ = [
    'OAuthTokens',
    'should_use_cloud_ai_auth',
    'parse_scopes',
    'build_auth_url',
    'exchange_code_for_tokens',
    'refresh_oauth_token',
    'fetch_and_store_user_roles',
    'create_and_store_api_key',
    'is_oauth_token_expired',
    'fetch_profile_info',
    'get_organization_uuid',
    'populate_oauth_account_info_if_needed',
    'store_oauth_account_info',
]
