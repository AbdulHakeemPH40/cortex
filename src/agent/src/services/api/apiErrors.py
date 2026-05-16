"""
services/api/apiErrors.py
Python conversion of services/api/errors.ts (1208 lines, core logic)

AI error types, constants, and user-friendly error messages for:
- Prompt too long errors
- Media size errors (images, PDFs)
- Authentication errors
- Rate limit errors
- Credit balance errors
"""

from typing import Any, Dict, Optional, Tuple


# Error message constants
API_ERROR_MESSAGE_PREFIX = 'API Error'
PROMPT_TOO_LONG_ERROR_MESSAGE = 'Prompt is too long'
CREDIT_BALANCE_TOO_LOW_ERROR_MESSAGE = 'Credit balance is too low'
INVALID_API_KEY_ERROR_MESSAGE = 'Not logged in · Please run /login'
INVALID_API_KEY_ERROR_MESSAGE_EXTERNAL = 'Invalid API key · Fix external API key'
ORG_DISABLED_ERROR_MESSAGE_ENV_KEY_WITH_OAUTH = (
    'Your ANTHROPIC_API_KEY belongs to a disabled organization · '
    'Unset the environment variable to use your subscription instead'
)
ORG_DISABLED_ERROR_MESSAGE_ENV_KEY = (
    'Your ANTHROPIC_API_KEY belongs to a disabled organization · '
    'Update or unset the environment variable'
)
TOKEN_REVOKED_ERROR_MESSAGE = 'OAuth token revoked · Please run /login'
CCR_AUTH_ERROR_MESSAGE = (
    'Authentication error · This may be a temporary network issue, please try again'
)
REPEATED_529_ERROR_MESSAGE = 'Repeated 529 Overloaded errors'
CUSTOM_OFF_SWITCH_MESSAGE = 'Opus is experiencing high load, please use /model to switch to Sonnet'
API_TIMEOUT_ERROR_MESSAGE = 'Request timed out'
OAUTH_ORG_NOT_ALLOWED_ERROR_MESSAGE = (
    'Your account does not have access to Claude Code. Please run /login.'
)

# API limits
API_PDF_MAX_PAGES = 500
PDF_TARGET_RAW_SIZE = 30 * 1024 * 1024  # 30 MB


def starts_with_api_error_prefix(text: str) -> bool:
    """Check if error message starts with API error prefix"""
    return text.startswith(API_ERROR_MESSAGE_PREFIX) or \
           text.startswith(f'Please run /login · {API_ERROR_MESSAGE_PREFIX}')


def parse_prompt_too_long_token_counts(raw_message: str) -> Dict[str, Optional[int]]:
    """
    Parse actual/limit token counts from prompt-too-long API error.
    
    Example: "prompt is too long: 137500 tokens > 135000 maximum"
    
    Returns:
        Dict with 'actual_tokens' and 'limit_tokens'
    """
    import re
    
    match = re.search(
        r'prompt is too long[^0-9]*(\d+)\s*tokens?\s*>\s*(\d+)',
        raw_message,
        re.IGNORECASE
    )
    
    if not match:
        return {'actual_tokens': None, 'limit_tokens': None}
    
    return {
        'actual_tokens': int(match.group(1)),
        'limit_tokens': int(match.group(2)),
    }


def get_prompt_too_long_token_gap(error_details: str) -> Optional[int]:
    """
    Calculate how many tokens over the limit.
    
    Used by reactive compact to jump past multiple groups in one retry.
    
    Returns:
        Token gap (positive number) or None if not parseable
    """
    counts = parse_prompt_too_long_token_counts(error_details)
    actual = counts.get('actual_tokens')
    limit = counts.get('limit_tokens')
    
    if actual is None or limit is None:
        return None
    
    gap = actual - limit
    return gap if gap > 0 else None


def is_media_size_error(raw: str) -> bool:
    """
    Check if error is a media-size rejection (image or PDF too large).
    
    Patterns synced with API error response formats.
    """
    return (
        ('image exceeds' in raw and 'maximum' in raw) or
        ('image dimensions exceed' in raw and 'many-image' in raw) or
        _matches_pdf_page_limit(raw)
    )


def _matches_pdf_page_limit(raw: str) -> bool:
    """Check if error mentions PDF page limit"""
    import re
    return bool(re.search(r'maximum of \d+ PDF pages', raw))


def is_prompt_too_long_error(error_details: str) -> bool:
    """Check if error details indicate prompt too long"""
    return PROMPT_TOO_LONG_ERROR_MESSAGE in error_details


def get_pdf_too_large_error_message(is_non_interactive: bool = False) -> str:
    """Get user-friendly PDF too large error message"""
    limits = f'max {API_PDF_MAX_PAGES} pages, {PDF_TARGET_RAW_SIZE / (1024*1024):.0f} MB'
    
    if is_non_interactive:
        return f'PDF too large ({limits}). Try reading the file a different way (e.g., extract text with pdftotext).'
    else:
        return f'PDF too large ({limits}). Go back and try again, or use pdftotext to convert to text first.'


def get_pdf_password_protected_error_message(is_non_interactive: bool = False) -> str:
    """Get PDF password protected error message"""
    if is_non_interactive:
        return 'PDF is password protected. Try using an AI agent tool to extract or convert the PDF.'
    else:
        return 'PDF is password protected. Go back and try again.'


def get_pdf_invalid_error_message(is_non_interactive: bool = False) -> str:
    """Get PDF invalid error message"""
    if is_non_interactive:
        return 'The PDF file was not valid. Try converting it to text first (e.g., pdftotext).'
    else:
        return 'The PDF file was not valid. Go back and try again with a different file.'


def get_image_too_large_error_message(is_non_interactive: bool = False) -> str:
    """Get image too large error message"""
    if is_non_interactive:
        return 'Image was too large. Try resizing the image or using a different approach.'
    else:
        return 'Image was too large. Go back and try again with a smaller image.'


def get_request_too_large_error_message(is_non_interactive: bool = False) -> str:
    """Get request too large error message"""
    limits = f'max {PDF_TARGET_RAW_SIZE / (1024*1024):.0f} MB'
    
    if is_non_interactive:
        return f'Request too large ({limits}). Try with a smaller file.'
    else:
        return f'Request too large ({limits}). Go back and try with a smaller file.'


def get_token_revoked_error_message(is_non_interactive: bool = False) -> str:
    """Get OAuth token revoked error message"""
    if is_non_interactive:
        return 'Your account does not have access to Claude. Please login again or contact your administrator.'
    else:
        return TOKEN_REVOKED_ERROR_MESSAGE


def get_oauth_org_not_allowed_error_message(is_non_interactive: bool = False) -> str:
    """Get organization not allowed error message"""
    if is_non_interactive:
        return 'Your organization does not have access to Claude. Please login again or contact your administrator.'
    else:
        return OAUTH_ORG_NOT_ALLOWED_ERROR_MESSAGE


def classify_api_error(
    error_message: str,
    status_code: Optional[int] = None,
    is_non_interactive: bool = False,
) -> Dict[str, Any]:
    """
    Classify API error and return user-friendly message.
    
    Args:
        error_message: Raw error message from API
        status_code: HTTP status code (if available)
        is_non_interactive: Whether running in non-interactive mode
        
    Returns:
        Dict with 'type', 'message', 'retryable'
    """
    # Prompt too long
    if is_prompt_too_long_error(error_message):
        token_gap = get_prompt_too_long_token_gap(error_message)
        return {
            'type': 'prompt_too_long',
            'message': PROMPT_TOO_LONG_ERROR_MESSAGE,
            'retryable': True,
            'token_gap': token_gap,
        }
    
    # Media size errors
    if is_media_size_error(error_message):
        if 'PDF' in error_message or 'pdf' in error_message:
            return {
                'type': 'pdf_too_large',
                'message': get_pdf_too_large_error_message(is_non_interactive),
                'retryable': False,
            }
        else:
            return {
                'type': 'image_too_large',
                'message': get_image_too_large_error_message(is_non_interactive),
                'retryable': False,
            }
    
    # Authentication errors
    if '401' in error_message or 'unauthorized' in error_message.lower():
        return {
            'type': 'auth_error',
            'message': INVALID_API_KEY_ERROR_MESSAGE,
            'retryable': False,
        }
    
    # Rate limit errors (429)
    if status_code == 429 or '429' in error_message or 'rate limit' in error_message.lower():
        return {
            'type': 'rate_limit',
            'message': 'Rate limit exceeded · Please wait and try again',
            'retryable': True,
        }
    
    # Server overload (529)
    if '529' in error_message:
        return {
            'type': 'server_overload',
            'message': 'Server overloaded · Please try again in a moment',
            'retryable': True,
        }
    
    # Timeout errors
    if 'timeout' in error_message.lower() or 'timed out' in error_message.lower():
        return {
            'type': 'timeout',
            'message': API_TIMEOUT_ERROR_MESSAGE,
            'retryable': True,
        }
    
    # Credit balance too low
    if CREDIT_BALANCE_TOO_LOW_ERROR_MESSAGE in error_message:
        return {
            'type': 'credit_balance_too_low',
            'message': CREDIT_BALANCE_TOO_LOW_ERROR_MESSAGE,
            'retryable': False,
        }
    
    # Organization disabled
    if 'disabled organization' in error_message.lower():
        return {
            'type': 'org_disabled',
            'message': ORG_DISABLED_ERROR_MESSAGE_ENV_KEY,
            'retryable': False,
        }
    
    # Default: generic API error
    return {
        'type': 'unknown',
        'message': f'{API_ERROR_MESSAGE_PREFIX}: {error_message}',
        'retryable': False,
    }


def is_retryable_api_error(error_info: Dict[str, Any]) -> bool:
    """Check if classified error is retryable"""
    return error_info.get('retryable', False)


def get_error_severity(error_type: str) -> str:
    """Get error severity level"""
    severity_map = {
        'prompt_too_long': 'warning',
        'pdf_too_large': 'error',
        'image_too_large': 'error',
        'auth_error': 'critical',
        'rate_limit': 'warning',
        'server_overload': 'warning',
        'timeout': 'warning',
        'credit_balance_too_low': 'error',
        'org_disabled': 'critical',
        'unknown': 'error',
    }
    
    return severity_map.get(error_type, 'error')


__all__ = [
    # Constants
    'API_ERROR_MESSAGE_PREFIX',
    'PROMPT_TOO_LONG_ERROR_MESSAGE',
    'CREDIT_BALANCE_TOO_LOW_ERROR_MESSAGE',
    'INVALID_API_KEY_ERROR_MESSAGE',
    'TOKEN_REVOKED_ERROR_MESSAGE',
    'API_TIMEOUT_ERROR_MESSAGE',
    'OAUTH_ORG_NOT_ALLOWED_ERROR_MESSAGE',
    'API_PDF_MAX_PAGES',
    'PDF_TARGET_RAW_SIZE',
    
    # Classification functions
    'starts_with_api_error_prefix',
    'parse_prompt_too_long_token_counts',
    'get_prompt_too_long_token_gap',
    'is_media_size_error',
    'is_prompt_too_long_error',
    'classify_api_error',
    'is_retryable_api_error',
    'get_error_severity',
    
    # Error message generators
    'get_pdf_too_large_error_message',
    'get_pdf_password_protected_error_message',
    'get_pdf_invalid_error_message',
    'get_image_too_large_error_message',
    'get_request_too_large_error_message',
    'get_token_revoked_error_message',
    'get_oauth_org_not_allowed_error_message',
]
