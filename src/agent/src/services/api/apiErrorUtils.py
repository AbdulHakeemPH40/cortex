"""
services/api/apiErrorUtils.py
Python conversion of services/api/errorUtils.ts (261 lines)

API error utilities for connection error detection, SSL/TLS error handling,
and user-friendly error formatting.
"""

from typing import Any, Dict, Optional, Tuple


# SSL/TLS error codes (from OpenSSL)
SSL_ERROR_CODES = frozenset([
    # Certificate verification errors
    'UNABLE_TO_VERIFY_LEAF_SIGNATURE',
    'UNABLE_TO_GET_ISSUER_CERT',
    'UNABLE_TO_GET_ISSUER_CERT_LOCALLY',
    'CERT_SIGNATURE_FAILURE',
    'CERT_NOT_YET_VALID',
    'CERT_HAS_EXPIRED',
    'CERT_REVOKED',
    'CERT_REJECTED',
    'CERT_UNTRUSTED',
    # Self-signed certificate errors
    'DEPTH_ZERO_SELF_SIGNED_CERT',
    'SELF_SIGNED_CERT_IN_CHAIN',
    # Chain errors
    'CERT_CHAIN_TOO_LONG',
    'PATH_LENGTH_EXCEEDED',
    # Hostname/altname errors
    'ERR_TLS_CERT_ALTNAME_INVALID',
    'HOSTNAME_MISMATCH',
    # TLS handshake errors
    'ERR_TLS_HANDSHAKE_TIMEOUT',
    'ERR_SSL_WRONG_VERSION_NUMBER',
    'ERR_SSL_DECRYPTION_FAILED_OR_BAD_RECORD_MAC',
])


def extract_connection_error_details(error: Exception) -> Optional[Dict[str, Any]]:
    """
    Extract connection error details from error cause chain.
    
    Python errors use __cause__ and __context__ for exception chaining.
    This walks the chain to find root error code/message.
    
    Returns:
        Dict with 'code', 'message', 'isSSLError' or None
    """
    if not error:
        return None
    
    # Walk the exception chain
    current = error
    max_depth = 5
    depth = 0
    
    while current and depth < max_depth:
        # Check if this exception has a code attribute
        error_code = getattr(current, 'code', None) or getattr(current, 'errno', None)
        
        if error_code and isinstance(error_code, str):
            is_ssl_error = error_code in SSL_ERROR_CODES
            return {
                'code': error_code,
                'message': str(current),
                'isSSLError': is_ssl_error,
            }
        
        # Move to the next cause in the chain
        cause = getattr(current, '__cause__', None) or getattr(current, '__context__', None)
        if cause and cause is not current:
            current = cause
            depth += 1
        else:
            break
    
    return None


def get_ssl_error_hint(error: Exception) -> Optional[str]:
    """
    Returns actionable hint for SSL/TLS errors.
    
    For enterprise users behind TLS-intercepting proxies (Zscaler, etc.),
    this provides the likely fix for certificate errors.
    
    Returns:
        User-friendly hint string or None if not SSL error
    """
    details = extract_connection_error_details(error)
    if not details or not details.get('isSSLError'):
        return None
    
    return (
        f"SSL certificate error ({details['code']}). "
        f"If you are behind a corporate proxy or TLS-intercepting firewall, "
        f"set REQUESTS_CA_BUNDLE to your CA bundle path, or ask IT to allowlist *.anthropic.com."
    )


def format_api_error(error: Exception, include_hints: bool = True) -> str:
    """
    Format API error into user-friendly message.
    
    Handles:
    - Connection errors (with SSL hints)
    - Timeout errors
    - HTTP status errors
    - Generic errors
    
    Args:
        error: The exception to format
        include_hints: Whether to include actionable hints
        
    Returns:
        User-friendly error message
    """
    # Check for SSL/TLS errors first
    if include_hints:
        ssl_hint = get_ssl_error_hint(error)
        if ssl_hint:
            return ssl_hint
    
    # Extract error details
    error_code = getattr(error, 'code', None) or getattr(error, 'errno', None)
    status_code = getattr(error, 'status_code', None)
    
    # Build message
    if status_code:
        message = f"API Error (HTTP {status_code}): {error}"
    elif error_code:
        message = f"Connection Error ({error_code}): {error}"
    else:
        message = f"API Error: {error}"
    
    return message


def is_connection_error(error: Exception) -> bool:
    """Check if error is a connection/network error"""
    details = extract_connection_error_details(error)
    if details:
        return True
    
    # Check common connection error types
    error_type = type(error).__name__
    connection_errors = [
        'ConnectionError',
        'ConnectionRefusedError',
        'ConnectionResetError',
        'TimeoutError',
        'Timeout',
        'SSLError',
        'CertificateError',
    ]
    
    return error_type in connection_errors


def is_timeout_error(error: Exception) -> bool:
    """Check if error is a timeout error"""
    error_type = type(error).__name__
    timeout_errors = ['TimeoutError', 'Timeout', 'ReadTimeout', 'ConnectTimeout']
    
    if error_type in timeout_errors:
        return True
    
    # Check error message for timeout indicators
    error_msg = str(error).lower()
    return 'timeout' in error_msg or 'timed out' in error_msg


def is_ssl_error(error: Exception) -> bool:
    """Check if error is an SSL/TLS error"""
    details = extract_connection_error_details(error)
    if details and details.get('isSSLError'):
        return True
    
    error_type = type(error).__name__
    return error_type in ('SSLError', 'CertificateError')


def get_retryable_error_delay(error: Exception, attempt: int) -> Optional[float]:
    """
    Calculate retry delay for retryable errors.
    
    Uses exponential backoff with jitter.
    
    Args:
        error: The error that occurred
        attempt: Current attempt number (0-based)
        
    Returns:
        Delay in seconds, or None if not retryable
    """
    if not is_connection_error(error) and not is_timeout_error(error):
        return None
    
    # Exponential backoff: 1s, 2s, 4s, 8s, ...
    import random
    base_delay = 1.0
    max_delay = 30.0
    
    delay = min(base_delay * (2 ** attempt), max_delay)
    
    # Add jitter (±25%)
    jitter = delay * 0.25 * (random.random() * 2 - 1)
    delay += jitter
    
    return max(0.1, delay)


__all__ = [
    'SSL_ERROR_CODES',
    'extract_connection_error_details',
    'get_ssl_error_hint',
    'format_api_error',
    'is_connection_error',
    'is_timeout_error',
    'is_ssl_error',
    'get_retryable_error_delay',
]
