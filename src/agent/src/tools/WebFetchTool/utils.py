import asyncio
import time
from typing import Optional, Union
from urllib.parse import urlparse

import aiohttp

# Defensive imports - stub if not available
try:
    from lru import LRU as LRUCache  # type: ignore
except ImportError:
    class LRUCache:  # type: ignore
        """Stub LRUCache for when lru package is not installed."""
        def __init__(self, *args, **kwargs):
            self._cache = {}
        def get(self, key):
            return self._cache.get(key)
        def set(self, key, value, **kwargs):
            self._cache[key] = value
        def clear(self):
            self._cache.clear()
        def has(self, key):
            return key in self._cache

try:
    from ...services.analytics import log_event
except ImportError:
    def log_event(event_name: str, metadata: dict = None):
        """Stub analytics logger."""
        pass

try:
    from ...utils.errors import AbortError
except ImportError:
    class AbortError(Exception):
        """Raised when an operation is aborted."""
        pass

try:
    from .preapproved import is_preapproved_host
except ImportError:
    def is_preapproved_host(hostname: str, pathname: str) -> bool:
        """Stub - returns False if preapproved module not available."""
        return False

try:
    from .prompt import make_secondary_model_prompt
except ImportError:
    def make_secondary_model_prompt(markdown_content: str, prompt: str, is_preapproved_domain: bool) -> str:
        """Stub prompt generator."""
        return f"{markdown_content}\n\n{prompt}"


# Custom error classes for domain blocking
class DomainBlockedError(Exception):
    def __init__(self, domain: str):
        super().__init__(f"Claude Code is unable to fetch from {domain}")
        self.name = 'DomainBlockedError'


class DomainCheckFailedError(Exception):
    def __init__(self, domain: str):
        super().__init__(
            f"Unable to verify if domain {domain} is safe to fetch. "
            f"This may be due to network restrictions or enterprise security policies blocking claude.ai."
        )
        self.name = 'DomainCheckFailedError'


class EgressBlockedError(Exception):
    def __init__(self, domain: str):
        import json
        super().__init__(json.dumps({
            'error_type': 'EGRESS_BLOCKED',
            'domain': domain,
            'message': f'Access to {domain} is blocked by the network egress proxy.',
        }))
        self.domain = domain
        self.name = 'EgressBlockedError'


# Cache for storing fetched URL content
class CacheEntry:
    def __init__(self, bytes: int, code: int, code_text: str, 
                 content: str, content_type: str, 
                 persisted_path: Optional[str] = None, 
                 persisted_size: Optional[int] = None):
        self.bytes = bytes
        self.code = code
        self.code_text = code_text
        self.content = content
        self.content_type = content_type
        self.persisted_path = persisted_path
        self.persisted_size = persisted_size


# Cache with 15-minute TTL and 50MB size limit
CACHE_TTL_MS = 15 * 60 * 1000  # 15 minutes
MAX_CACHE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

URL_CACHE = LRUCache(maxsize=MAX_CACHE_SIZE_BYTES)

# Separate cache for preflight domain checks
DOMAIN_CHECK_CACHE = LRUCache(maxsize=128)

# Track cache entry timestamps for TTL
_cache_timestamps = {}


def _is_cache_valid(key: str, ttl_ms: int) -> bool:
    """Check if a cache entry is still valid based on TTL."""
    if key not in _cache_timestamps:
        return False
    age_ms = (time.time() * 1000) - _cache_timestamps[key]
    return age_ms < ttl_ms


def clear_web_fetch_cache():
    """Clear both URL and domain check caches."""
    URL_CACHE.clear()
    DOMAIN_CHECK_CACHE.clear()
    _cache_timestamps.clear()


# PSR requested limiting the length of URLs to 250 to lower the potential
# for a data exfiltration. However, this is too restrictive for some customers'
# legitimate use cases, such as JWT-signed URLs (e.g., cloud service signed URLs)
# that can be much longer. We already require user approval for each domain,
# which provides a primary security boundary.
MAX_URL_LENGTH = 2000

# Per PSR: Implement resource consumption controls
MAX_HTTP_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB

# Timeout for the main HTTP fetch request (60 seconds)
FETCH_TIMEOUT_MS = 60_000

# Timeout for the domain blocklist preflight check (10 seconds)
DOMAIN_CHECK_TIMEOUT_MS = 10_000

# Cap same-host redirect hops
MAX_REDIRECTS = 10

# Truncate to not spend too many tokens
MAX_MARKDOWN_LENGTH = 100_000


def is_preapproved_url(url: str) -> bool:
    """Check if a URL's host is in the preapproved list."""
    try:
        parsed = urlparse(url)
        return is_preapproved_host(parsed.hostname or '', parsed.path or '')
    except Exception:
        return False


def validate_url(url: str) -> bool:
    """Validate that a URL is safe to fetch."""
    if len(url) > MAX_URL_LENGTH:
        return False
    
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    
    # Block URLs with usernames/passwords
    if parsed.username or parsed.password:
        return False
    
    # Check hostname is publicly resolvable (at least 2 parts)
    hostname = parsed.hostname
    if not hostname:
        return False
    
    parts = hostname.split('.')
    if len(parts) < 2:
        return False
    
    return True


async def check_domain_blocklist(domain: str) -> dict:
    """
    Check if a domain is allowed via Anthropic's API.
    
    Returns:
        dict with 'status' key: 'allowed', 'blocked', or 'check_failed'
    """
    if domain in DOMAIN_CHECK_CACHE and _is_cache_valid(domain, 5 * 60 * 1000):
        return {'status': 'allowed'}
    
    try:
        timeout = aiohttp.ClientTimeout(total=DOMAIN_CHECK_TIMEOUT_MS / 1000)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"https://api.anthropic.com/api/web/domain_info?domain={domain}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('can_fetch') is True:
                        DOMAIN_CHECK_CACHE[domain] = True
                        _cache_timestamps[domain] = time.time() * 1000
                        return {'status': 'allowed'}
                    return {'status': 'blocked'}
                
                return {
                    'status': 'check_failed',
                    'error': Exception(f'Domain check returned status {response.status}')
                }
    except Exception as e:
        return {'status': 'check_failed', 'error': e}


def is_permitted_redirect(original_url: str, redirect_url: str) -> bool:
    """
    Check if a redirect is safe to follow.
    
    Allows redirects that:
    - Add or remove "www." in the hostname
    - Keep the origin the same but change path/query params
    """
    try:
        parsed_original = urlparse(original_url)
        parsed_redirect = urlparse(redirect_url)
        
        # Protocol must match
        if parsed_redirect.scheme != parsed_original.scheme:
            return False
        
        # Port must match
        if parsed_redirect.port != parsed_original.port:
            return False
        
        # No username/password in redirect
        if parsed_redirect.username or parsed_redirect.password:
            return False
        
        # Strip www. and compare hostnames
        def strip_www(hostname):
            return hostname.replace('www.', '', 1) if hostname.startswith('www.') else hostname
        
        original_host = strip_www(parsed_original.hostname or '')
        redirect_host = strip_www(parsed_redirect.hostname or '')
        
        return original_host == redirect_host
    except Exception:
        return False


class RedirectInfo:
    """Information about a redirect response."""
    def __init__(self, original_url: str, redirect_url: str, status_code: int):
        self.type = 'redirect'
        self.original_url = original_url
        self.redirect_url = redirect_url
        self.status_code = status_code


class FetchedContent:
    """Content fetched from a URL."""
    def __init__(self, content: str, bytes: int, code: int, 
                 code_text: str, content_type: str,
                 persisted_path: Optional[str] = None,
                 persisted_size: Optional[int] = None):
        self.content = content
        self.bytes = bytes
        self.code = code
        self.code_text = code_text
        self.content_type = content_type
        self.persisted_path = persisted_path
        self.persisted_size = persisted_size


async def get_with_permitted_redirects(
    url: str,
    session: aiohttp.ClientSession,
    depth: int = 0
) -> Union[aiohttp.ClientResponse, RedirectInfo]:
    """
    Fetch URL with custom redirect handling.
    
    Recursively follows redirects if they pass the redirect checker.
    """
    if depth > MAX_REDIRECTS:
        raise Exception(f'Too many redirects (exceeded {MAX_REDIRECTS})')
    
    headers = {
        'Accept': 'text/markdown, text/html, */*',
        'User-Agent': 'ClaudeCode/1.0',  # TODO: Get from utils
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_MS / 1000)
        async with session.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,  # Handle redirects manually
            max_read_bytes=MAX_HTTP_CONTENT_LENGTH
        ) as response:
            # Check for redirect status codes
            if response.status in (301, 302, 307, 308):
                redirect_location = response.headers.get('Location')
                if not redirect_location:
                    raise Exception('Redirect missing Location header')
                
                # Resolve relative URLs
                from urllib.parse import urljoin
                redirect_url = urljoin(url, redirect_location)
                
                if is_permitted_redirect(url, redirect_url):
                    # Recursively follow the permitted redirect
                    return await get_with_permitted_redirects(
                        redirect_url, session, depth + 1
                    )
                else:
                    # Return redirect info to caller
                    return RedirectInfo(url, redirect_url, response.status)
            
            # Check for egress proxy blocks
            if response.status == 403:
                proxy_error = response.headers.get('X-Proxy-Error')
                if proxy_error == 'blocked-by-allowlist':
                    hostname = urlparse(url).hostname
                    raise EgressBlockedError(hostname or '')
            
            # Return the response for non-redirect cases
            # Note: Caller must read the response before session closes
            return response
            
    except EgressBlockedError:
        raise
    except Exception as e:
        raise


async def get_url_markdown_content(
    url: str,
    abort_controller: Optional[asyncio.Event] = None
) -> Union[FetchedContent, RedirectInfo]:
    """
    Fetch URL content and convert to markdown.
    
    Args:
        url: The URL to fetch
        abort_controller: Optional asyncio.Event for cancellation
    
    Returns:
        FetchedContent or RedirectInfo
    """
    if not validate_url(url):
        raise Exception('Invalid URL')
    
    # Check cache
    if url in URL_CACHE and _is_cache_valid(url, CACHE_TTL_MS):
        cached = URL_CACHE[url]
        return FetchedContent(
            content=cached['content'],
            bytes=cached['bytes'],
            code=cached['code'],
            code_text=cached['code_text'],
            content_type=cached['content_type'],
            persisted_path=cached.get('persisted_path'),
            persisted_size=cached.get('persisted_size')
        )
    
    try:
        parsed_url = urlparse(url)
        
        # Upgrade http to https
        upgraded_url = url
        if parsed_url.scheme == 'http':
            parsed_url = parsed_url._replace(scheme='https')
            upgraded_url = parsed_url.geturl()
        
        hostname = parsed_url.hostname or ''
        
        # Check domain blocklist (unless skipped)
        # TODO: Get settings - for now always check
        check_result = await check_domain_blocklist(hostname)
        
        if check_result['status'] == 'blocked':
            raise DomainBlockedError(hostname)
        elif check_result['status'] == 'check_failed':
            raise DomainCheckFailedError(hostname)
        
        # Log event for ant users
        import os
        if os.environ.get('USER_TYPE') == 'ant':
            log_event('tengu_web_fetch_host', {'hostname': hostname})
        
    except (DomainBlockedError, DomainCheckFailedError):
        raise
    except Exception as e:
        # Log other errors
        print(f"Error in domain check: {e}")
    
    # Fetch the content
    timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_MS / 1000)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        result = await get_with_permitted_redirects(upgraded_url, session)
        
        # Check if we got a redirect
        if isinstance(result, RedirectInfo):
            return result
        
        # Read response content
        response = result
        raw_bytes = await response.read()
        content_type = response.headers.get('Content-Type', '')
        status_code = response.status
        status_text = response.reason or ''
        
        # Convert to string
        html_content = raw_bytes.decode('utf-8', errors='replace')
        
        # Convert HTML to markdown if needed
        if 'text/html' in content_type:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content, 'lxml')
                # Remove non-content tags
                for tag in soup(['script', 'style', 'nav', 'footer',
                                  'header', 'aside', 'noscript', 'form']):
                    tag.decompose()
                # Preserve code blocks as plain text
                for pre in soup.find_all('pre'):
                    pre.string = '\n```\n' + pre.get_text() + '\n```\n'
                markdown_content = soup.get_text(separator='\n', strip=True)
                # Collapse 3+ blank lines into 2
                import re as _re
                markdown_content = _re.sub(r'\n{3,}', '\n\n', markdown_content)
            except ImportError:
                # bs4 not available — return raw HTML (still usable by LLM)
                markdown_content = html_content
        else:
            markdown_content = html_content
        
        content_bytes = len(raw_bytes)
        
        # Store in cache
        cache_entry = {
            'bytes': content_bytes,
            'code': status_code,
            'code_text': status_text,
            'content': markdown_content,
            'content_type': content_type,
            'persisted_path': None,
            'persisted_size': None,
        }
        URL_CACHE[url] = cache_entry
        _cache_timestamps[url] = time.time() * 1000
        
        return FetchedContent(
            content=markdown_content,
            bytes=content_bytes,
            code=status_code,
            code_text=status_text,
            content_type=content_type
        )


async def apply_prompt_to_markdown(
    prompt: str,
    markdown_content: str,
    signal: Optional[asyncio.Event] = None,
    is_non_interactive_session: bool = False,
    is_preapproved_domain: bool = False
) -> str:
    """
    Return the page content so the main LLM in the agentic loop can process it.
    The secondary `query_haiku` model is not needed — the agent's primary LLM
    receives the content directly and answers the user's question in context.
    """
    # Truncate to avoid prompt-too-long errors
    if len(markdown_content) > MAX_MARKDOWN_LENGTH:
        truncated = (
            markdown_content[:MAX_MARKDOWN_LENGTH]
            + '\n\n[Content truncated due to length. Use a more specific URL or prompt for a focused section.]'
        )
    else:
        truncated = markdown_content

    if prompt:
        return (
            f"Web page content (fetched for: \"{prompt}\"):\n"
            f"---\n{truncated}\n---\n"
            f"\nThe above content has been retrieved. Answer the user's question based on it."
        )
    return truncated
