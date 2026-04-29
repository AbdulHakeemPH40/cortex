"""
WebFetchTool utilities.
Stub module - implement based on requirements.
"""
from typing import Optional
import re
from urllib.parse import urlparse


def validate_url(url: str) -> bool:
    """Validate URL format."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def sanitize_url(url: str) -> str:
    """Sanitize URL for fetching."""
    return url.strip()


def extract_content(html: str) -> str:
    """Extract text content from HTML."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html)
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


async def get_url_markdown_content(url: str) -> str:
    """
    Fetch a URL and return its content as plain text/markdown.

    Args:
        url: The URL to fetch.

    Returns:
        Extracted text content from the page.
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Cortex IDE AI Agent)'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode('utf-8', errors='replace')
        return extract_content(html)
    except Exception:
        return ""


__all__ = ['validate_url', 'sanitize_url', 'extract_content', 'get_url_markdown_content']
