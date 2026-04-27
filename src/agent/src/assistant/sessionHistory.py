"""Session history fetching with pagination."""
from typing import Any, Dict, List, Optional

# Defensive imports
try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from ..constants.oauth import get_oauth_config
except ImportError:
    def get_oauth_config():
        """Stub OAuth config."""
        class Config:
            BASE_API_URL = 'https://api.anthropic.com'
        return Config()

try:
    from ..utils.teleport.api import get_oauth_headers, prepare_api_request
except ImportError:
    async def prepare_api_request():
        """Stub API request preparation."""
        return {'accessToken': None, 'orgUUID': None}
    
    def get_oauth_headers(token):
        """Stub OAuth headers."""
        return {}

try:
    from ..utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(msg):
        """Stub debug logger."""
        print(f"[DEBUG] {msg}")


HISTORY_PAGE_SIZE = 100


class HistoryPage:
    """Represents a page of session history events."""
    def __init__(
        self,
        events: List[Dict[str, Any]],
        first_id: Optional[str],
        has_more: bool
    ):
        # Chronological order within the page
        self.events = events
        # Oldest event ID in this page → before_id cursor for next-older page
        self.first_id = first_id
        # True = older events exist
        self.has_more = has_more


class HistoryAuthCtx:
    """Authentication context reused across pagination requests."""
    def __init__(self, base_url: str, headers: Dict[str, str]):
        self.base_url = base_url
        self.headers = headers


async def create_history_auth_ctx(session_id: str) -> HistoryAuthCtx:
    """
    Prepare auth + headers + base URL once, reuse across pages.
    
    Args:
        session_id: The session ID to fetch history for
    
    Returns:
        HistoryAuthCtx with base URL and authentication headers
    """
    api_info = await prepare_api_request()
    access_token = api_info.get('accessToken')
    org_uuid = api_info.get('orgUUID')
    
    oauth_config = get_oauth_config()
    base_url = f"{oauth_config.BASE_API_URL}/v1/sessions/{session_id}/events"
    
    headers = {
        **get_oauth_headers(access_token),
        'anthropic-beta': 'ccr-byoc-2025-07-29',
        'x-organization-uuid': org_uuid or '',
    }
    
    return HistoryAuthCtx(base_url=base_url, headers=headers)


async def fetch_page(
    ctx: HistoryAuthCtx,
    params: Dict[str, Any],
    label: str
) -> Optional[HistoryPage]:
    """
    Fetch a single page of session events.
    
    Args:
        ctx: Authentication context
        params: Query parameters for the request
        label: Debug label for logging
    
    Returns:
        HistoryPage if successful, None on error
    """
    if not aiohttp:
        log_for_debugging(f"[{label}] aiohttp not available")
        return None
    
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                ctx.base_url,
                headers=ctx.headers,
                params=params,
                timeout=timeout
            ) as resp:
                if resp.status != 200:
                    log_for_debugging(f"[{label}] HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                
                events = data.get('data', [])
                if not isinstance(events, list):
                    events = []
                
                return HistoryPage(
                    events=events,
                    first_id=data.get('first_id'),
                    has_more=data.get('has_more', False)
                )
    
    except Exception as e:
        log_for_debugging(f"[{label}] Error: {str(e)}")
        return None


async def fetch_latest_events(
    ctx: HistoryAuthCtx,
    limit: int = HISTORY_PAGE_SIZE
) -> Optional[HistoryPage]:
    """
    Fetch newest page: last `limit` events, chronological, via anchor_to_latest.
    has_more=true means older events exist.
    
    Args:
        ctx: Authentication context
        limit: Number of events to fetch (default: 100)
    
    Returns:
        HistoryPage with latest events, or None on error
    """
    return await fetch_page(
        ctx,
        {'limit': limit, 'anchor_to_latest': True},
        'fetchLatestEvents'
    )


async def fetch_older_events(
    ctx: HistoryAuthCtx,
    before_id: str,
    limit: int = HISTORY_PAGE_SIZE
) -> Optional[HistoryPage]:
    """
    Fetch older page: events immediately before `before_id` cursor.
    
    Args:
        ctx: Authentication context
        before_id: Cursor ID to fetch events before
        limit: Number of events to fetch (default: 100)
    
    Returns:
        HistoryPage with older events, or None on error
    """
    return await fetch_page(
        ctx,
        {'limit': limit, 'before_id': before_id},
        'fetchOlderEvents'
    )
