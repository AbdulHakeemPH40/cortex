"""
Upload BriefTool attachments to private_api so web viewers can preview them.

When the repl bridge is active, attachment paths are meaningless to a web
viewer (they're on Claude's machine). We upload to /api/oauth/file_upload —
the same store MessageComposer/SpaceMessage render from — and stash the
returned file_uuid alongside the path. Web resolves file_uuid → preview;
desktop/local try path first.

Best-effort: any failure (no token, bridge off, network error, 4xx) logs
debug and returns undefined. The attachment still carries {path, size,
isImage}, so local-terminal and same-machine-desktop render unaffected.
"""

import os
import uuid
from pathlib import Path
from typing import Optional, TypedDict

# Defensive imports
try:
    from ...bridge.bridgeConfig import getBridgeAccessToken, getBridgeBaseUrlOverride
except ImportError:
    def getBridgeAccessToken():
        return None
    
    def getBridgeBaseUrlOverride():
        return None

try:
    from ...constants.oauth import getOauthConfig
except ImportError:
    def getOauthConfig():
        class MockConfig:
            BASE_API_URL = 'https://api.anthropic.com'
        return MockConfig()

try:
    from ...utils.debug import logForDebugging
except ImportError:
    def logForDebugging(msg):
        pass

try:
    from ...utils.slowOperations import jsonStringify
except ImportError:
    import json
    def jsonStringify(obj, **kwargs):
        return json.dumps(obj, **kwargs)


# Matches the private_api backend limit
MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # 30 MB

UPLOAD_TIMEOUT_MS = 30_000  # 30 seconds

# Backend dispatches on mime: image/* → upload_image_wrapped (writes
# PREVIEW/THUMBNAIL, no ORIGINAL), everything else → upload_generic_file
# (ORIGINAL only, no preview). Only whitelist raster formats the
# transcoder reliably handles — svg/bmp/ico risk a 400, and pdf routes
# to upload_pdf_file_wrapped which also skips ORIGINAL. Dispatch
# viewers use /preview for images and /contents for everything else,
# so images go image/* and the rest go octet-stream.
MIME_BY_EXT = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
}


class BriefUploadContext(TypedDict, total=False):
    """Context for brief upload operations."""
    replBridgeEnabled: bool
    signal: any  # AbortSignal equivalent


def guessMimeType(filename: str) -> str:
    """Guess MIME type from file extension."""
    ext = Path(filename).suffix.lower()
    return MIME_BY_EXT.get(ext, 'application/octet-stream')


def debug(msg: str) -> None:
    """Log debug message."""
    logForDebugging(f'[brief:upload] {msg}')


def getBridgeBaseUrl() -> str:
    """Base URL for uploads. Must match the host the token is valid for.
    
    Subprocess hosts (cowork) pass ANTHROPIC_BASE_URL alongside
    CLAUDE_CODE_OAUTH_TOKEN — prefer that since getOauthConfig() only
    returns staging when USE_STAGING_OAUTH is set, which such hosts don't
    set. Without this a staging token hits api.anthropic.com → 401 → silent
    skip → web viewer sees inert cards with no file_uuid.
    """
    return (
        getBridgeBaseUrlOverride() or
        os.environ.get('ANTHROPIC_BASE_URL') or
        getOauthConfig().BASE_API_URL
    )


async def uploadBriefAttachment(
    fullPath: str,
    size: int,
    ctx: BriefUploadContext
) -> Optional[str]:
    """Upload a single attachment. Returns file_uuid on success, undefined otherwise.
    
    Every early-return is intentional graceful degradation.
    
    Args:
        fullPath: Absolute path to file
        size: File size in bytes
        ctx: Upload context with bridge settings
    
    Returns:
        file_uuid string on success, None on failure
    """
    # Positive pattern so bun:bundle eliminates the entire body from
    # non-BRIDGE_MODE builds (negative `if (!feature(...)) return` does not).
    bridge_mode = os.environ.get('BRIDGE_MODE', '').lower() in ('true', '1', 'yes')
    
    if not bridge_mode:
        return None
    
    if not ctx.get('replBridgeEnabled'):
        return None
    
    if size > MAX_UPLOAD_BYTES:
        debug(f'skip {fullPath}: {size} bytes exceeds {MAX_UPLOAD_BYTES} limit')
        return None
    
    token = getBridgeAccessToken()
    if not token:
        debug('skip: no oauth token')
        return None
    
    # Read file content
    try:
        with open(fullPath, 'rb') as f:
            content = f.read()
    except Exception as e:
        debug(f'read failed for {fullPath}: {e}')
        return None
    
    baseUrl = getBridgeBaseUrl()
    url = f'{baseUrl}/api/oauth/file_upload'
    filename = Path(fullPath).name
    mimeType = guessMimeType(filename)
    boundary = f'----FormBoundary{uuid.uuid4()}'
    
    # Manual multipart — same pattern as filesApi.py. The oauth endpoint takes
    # a single "file" part (no "purpose" field like the public Files API).
    header = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f'Content-Type: {mimeType}\r\n\r\n'
    ).encode('utf-8')
    
    footer = f'\r\n--{boundary}--\r\n'.encode('utf-8')
    
    body = header + content + footer
    
    try:
        # Use aiohttp for async HTTP (install with: pip install aiohttp)
        try:
            import aiohttp
        except ImportError:
            debug('aiohttp not installed - cannot upload attachments')
            return None
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(len(body)),
        }
        
        timeout = aiohttp.ClientTimeout(total=UPLOAD_TIMEOUT_MS / 1000)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=body, headers=headers) as response:
                if response.status != 201:
                    response_text = await response.text()
                    debug(
                        f'upload failed for {fullPath}: status={response.status} body={jsonStringify(response_text)[:200]}'
                    )
                    return None
                
                try:
                    data = await response.json()
                    file_uuid = data.get('file_uuid')
                    
                    if not file_uuid:
                        debug(f'unexpected response shape for {fullPath}: missing file_uuid')
                        return None
                    
                    debug(f'uploaded {fullPath} → {file_uuid} ({size} bytes)')
                    return file_uuid
                    
                except Exception as e:
                    debug(f'failed to parse response for {fullPath}: {e}')
                    return None
    
    except Exception as e:
        debug(f'upload threw for {fullPath}: {e}')
        return None
