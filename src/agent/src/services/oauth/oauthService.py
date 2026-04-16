"""
services/oauth/oauthService.py
Python conversion of services/oauth/index.ts (199 lines)

OAuth service that handles the OAuth 2.0 authorization code flow with PKCE.

Supports two ways to get authorization codes:
1. Automatic: Opens browser, redirects to localhost where we capture the code
2. Manual: User manually copies and pastes the code (used in non-browser environments)
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

try:
    from ...services.analytics.index import log_event
except ImportError:
    def log_event(event_name: str, metadata: dict = None):
        pass

try:
    from ...utils.browser import open_browser
except ImportError:
    async def open_browser(url: str):
        import webbrowser
        webbrowser.open(url)

try:
    from .crypto import generate_code_verifier, generate_code_challenge, generate_state
except ImportError:
    import crypto
    generate_code_verifier = crypto.generate_code_verifier
    generate_code_challenge = crypto.generate_code_challenge
    generate_state = crypto.generate_state

try:
    from .authCodeListener import AuthCodeListener
except ImportError:
    import authCodeListener
    AuthCodeListener = authCodeListener.AuthCodeListener

try:
    from .oauthClient import (
        build_auth_url,
        exchange_code_for_tokens,
        fetch_profile_info,
        parse_scopes,
    )
except ImportError:
    import oauthClient
    build_auth_url = oauthClient.build_auth_url
    exchange_code_for_tokens = oauthClient.exchange_code_for_tokens
    fetch_profile_info = oauthClient.fetch_profile_info
    parse_scopes = oauthClient.parse_scopes

logger = logging.getLogger(__name__)


class OAuthService:
    """
    OAuth service that handles the OAuth 2.0 authorization code flow with PKCE.
    
    Supports two ways to get authorization codes:
    1. Automatic: Opens browser, redirects to localhost where we capture the code
    2. Manual: User manually copies and pastes the code (used in non-browser environments)
    """
    
    def __init__(self):
        """Initialize OAuth service with PKCE code verifier"""
        self.code_verifier = generate_code_verifier()
        self.auth_code_listener: Optional[AuthCodeListener] = None
        self.port: Optional[int] = None
        self.manual_auth_code_resolver: Optional[Callable[[str], None]] = None
    
    async def start_oauth_flow(
        self,
        auth_url_handler: Callable[[str, Optional[str]], Any],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Start the OAuth authentication flow.
        
        Args:
            auth_url_handler: Callback to handle auth URL (for manual flow)
            options: Optional configuration
                - login_with_claude_ai: Use Claude.ai auth
                - inference_only: Request only inference scope
                - expires_in: Token expiration time
                - org_uuid: Organization UUID
                - login_hint: Pre-populate email
                - login_method: Request specific login method (sso, magic_link, google)
                - skip_browser_open: Don't call open_browser(), caller handles URLs
                
        Returns:
            OAuth tokens dict with access_token, refresh_token, etc.
        """
        if options is None:
            options = {}
        
        # Create OAuth callback listener and start it
        self.auth_code_listener = AuthCodeListener()
        self.port = await self.auth_code_listener.start()
        
        # Generate PKCE values and state
        code_challenge = generate_code_challenge(self.code_verifier)
        state = generate_state()
        
        # Build auth URLs for both automatic and manual flows
        auth_url_opts = {
            'code_challenge': code_challenge,
            'state': state,
            'port': self.port,
            'login_with_claude_ai': options.get('login_with_claude_ai'),
            'inference_only': options.get('inference_only'),
            'org_uuid': options.get('org_uuid'),
            'login_hint': options.get('login_hint'),
            'login_method': options.get('login_method'),
        }
        
        manual_flow_url = build_auth_url(is_manual=True, **auth_url_opts)
        automatic_flow_url = build_auth_url(is_manual=False, **auth_url_opts)
        
        # Wait for either automatic or manual auth code
        authorization_code = await self.wait_for_authorization_code(
            state,
            lambda: self._handle_auth_urls(
                auth_url_handler,
                manual_flow_url,
                automatic_flow_url,
                options.get('skip_browser_open', False),
            ),
        )
        
        # Check if the automatic flow is still active (has a pending response)
        is_automatic_flow = (
            self.auth_code_listener.has_pending_response()
            if self.auth_code_listener
            else False
        )
        
        log_event('tengu_oauth_auth_code_received', {'automatic': is_automatic_flow})
        
        try:
            # Exchange authorization code for tokens
            token_response = await exchange_code_for_tokens(
                authorization_code,
                state,
                self.code_verifier,
                self.port,
                not is_automatic_flow,  # Pass is_manual=True if it's NOT automatic flow
                options.get('expires_in'),
            )
            
            # Fetch profile info (subscription type and rate limit tier)
            profile_info = await fetch_profile_info(token_response.get('access_token'))
            
            # Handle success redirect for automatic flow
            if is_automatic_flow and self.auth_code_listener:
                scopes = parse_scopes(token_response.get('scope'))
                self.auth_code_listener.handle_success_redirect(scopes)
            
            return self.format_tokens(
                token_response,
                profile_info.get('subscriptionType') if profile_info else None,
                profile_info.get('rateLimitTier') if profile_info else None,
                profile_info.get('rawProfile') if profile_info else None,
            )
        except Exception as error:
            # If we have a pending response, send an error redirect before closing
            if is_automatic_flow and self.auth_code_listener:
                self.auth_code_listener.handle_error_redirect()
            raise
        finally:
            # Always cleanup
            if self.auth_code_listener:
                self.auth_code_listener.close()
    
    async def _handle_auth_urls(
        self,
        auth_url_handler,
        manual_url: str,
        automatic_url: str,
        skip_browser: bool,
    ):
        """Handle opening auth URLs based on configuration"""
        if skip_browser:
            # Hand both URLs to the caller. The automatic one still works
            # if the caller opens it on the same host (localhost listener
            # is running); the manual one works from anywhere.
            result = auth_url_handler(manual_url, automatic_url)
            if asyncio.iscoroutine(result):
                await result
        else:
            # Show manual option to user
            result = auth_url_handler(manual_url)
            if asyncio.iscoroutine(result):
                await result
            
            # Try automatic flow
            await open_browser(automatic_url)
    
    async def wait_for_authorization_code(
        self,
        state: str,
        on_ready: Callable[[], Any],
    ) -> str:
        """
        Wait for authorization code from either automatic or manual flow.
        
        Args:
            state: Expected state parameter for CSRF protection
            on_ready: Callback to call when server is ready
            
        Returns:
            Authorization code
        """
        # Create event for signaling
        code_event = asyncio.Event()
        code_result = {'code': None, 'error': None}
        
        # Set up manual auth code resolver
        def resolve_manual(code: str):
            code_result['code'] = code
            code_event.set()
        
        self.manual_auth_code_resolver = resolve_manual
        
        # Start automatic flow
        async def wait_for_auto():
            try:
                if self.auth_code_listener:
                    code = await self.auth_code_listener.wait_for_authorization(
                        state,
                        on_ready,
                    )
                    code_result['code'] = code
                    code_event.set()
            except Exception as e:
                code_result['error'] = e
                code_event.set()
        
        auto_task = asyncio.create_task(wait_for_auto())
        
        # Wait for either flow to complete
        await code_event.wait()
        
        # Cancel the other task
        if not auto_task.done():
            auto_task.cancel()
            try:
                await auto_task
            except asyncio.CancelledError:
                pass
        
        self.manual_auth_code_resolver = None
        
        if code_result['error']:
            raise code_result['error']
        
        return code_result['code']
    
    def handle_manual_auth_code_input(self, params: Dict[str, str]):
        """
        Handle manual flow callback when user pastes the auth code.
        
        Args:
            params: Dict with 'authorizationCode' and 'state' keys
        """
        if self.manual_auth_code_resolver:
            self.manual_auth_code_resolver(params['authorizationCode'])
            self.manual_auth_code_resolver = None
            # Close the auth code listener since manual input was used
            if self.auth_code_listener:
                self.auth_code_listener.close()
    
    def format_tokens(
        self,
        response: Dict[str, Any],
        subscription_type: Optional[str],
        rate_limit_tier: Optional[str],
        profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Format OAuth token response.
        
        Args:
            response: Token exchange response
            subscription_type: User's subscription type
            rate_limit_tier: User's rate limit tier
            profile: Raw profile data
            
        Returns:
            Formatted tokens dict
        """
        import time
        
        result = {
            'accessToken': response.get('access_token'),
            'refreshToken': response.get('refresh_token'),
            'expiresAt': int(time.time() * 1000) + (response.get('expires_in', 0) * 1000),
            'scopes': parse_scopes(response.get('scope')),
            'subscriptionType': subscription_type,
            'rateLimitTier': rate_limit_tier,
            'profile': profile,
        }
        
        # Add token account if present
        if response.get('account'):
            result['tokenAccount'] = {
                'uuid': response['account'].get('uuid'),
                'emailAddress': response['account'].get('email_address'),
                'organizationUuid': response.get('organization', {}).get('uuid'),
            }
        
        return result
    
    def cleanup(self):
        """Clean up any resources (like the local server)"""
        if self.auth_code_listener:
            self.auth_code_listener.close()
        self.manual_auth_code_resolver = None


__all__ = [
    'OAuthService',
]
