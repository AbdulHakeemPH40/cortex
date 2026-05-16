"""
Shared attachment validation + resolution for SendUserMessage and SendUserFile.

Lives in BriefTool/ so the dynamic `./upload.py` import inside the
feature('BRIDGE_MODE') guard stays relative and upload.py (axios, crypto,
auth utils) remains tree-shakeable from non-bridge builds.
"""

import os
from pathlib import Path
from typing import List, Optional, TypedDict

# Defensive imports
try:
    from ...Tool import ValidationResult
except ImportError:
    class ValidationResult(TypedDict, total=False):
        result: bool
        message: str
        errorCode: int

try:
    from ...utils.cwd import getCwd
except ImportError:
    def getCwd():
        return os.getcwd()

try:
    from ...utils.envUtils import isEnvTruthy
except ImportError:
    def isEnvTruthy(value):
        if value is None:
            return False
        return str(value).lower() in ('true', '1', 'yes')

try:
    from ...utils.errors import getErrnoCode
except ImportError:
    def getErrnoCode(error):
        """Extract errno code from exception."""
        return getattr(error, 'errno', None) or str(error)

try:
    from ...utils.imagePaste import IMAGE_EXTENSION_REGEX
except ImportError:
    import re
    IMAGE_EXTENSION_REGEX = re.compile(r'\.(png|jpe?g|gif|webp|bmp|svg)$', re.IGNORECASE)

try:
    from ...utils.path import expandPath
except ImportError:
    def expandPath(path):
        """Expand path with tilde and environment variables."""
        return os.path.expanduser(os.path.expandvars(path))


class ResolvedAttachment(TypedDict, total=False):
    """Resolved attachment metadata."""
    path: str
    size: int
    isImage: bool
    file_uuid: Optional[str]


async def validateAttachmentPaths(rawPaths: List[str]) -> ValidationResult:
    """Validate that all attachment paths exist and are regular files.
    
    Args:
        rawPaths: List of file paths to validate (absolute or relative to cwd)
    
    Returns:
        ValidationResult with success/failure and error message
    """
    cwd = getCwd()
    
    for rawPath in rawPaths:
        fullPath = expandPath(rawPath)
        
        try:
            path_obj = Path(fullPath)
            
            # Check if path exists
            if not path_obj.exists():
                return {
                    'result': False,
                    'message': f'Attachment "{rawPath}" does not exist. Current working directory: {cwd}.',
                    'errorCode': 1,
                }
            
            # Check if it's a regular file (not directory, symlink to dir, etc.)
            if not path_obj.is_file():
                return {
                    'result': False,
                    'message': f'Attachment "{rawPath}" is not a regular file.',
                    'errorCode': 1,
                }
            
        except PermissionError:
            return {
                'result': False,
                'message': f'Attachment "{rawPath}" is not accessible (permission denied).',
                'errorCode': 1,
            }
        except OSError as e:
            code = getErrnoCode(e)
            if code == 'ENOENT' or code == 2:  # errno.ENOENT
                return {
                    'result': False,
                    'message': f'Attachment "{rawPath}" does not exist. Current working directory: {cwd}.',
                    'errorCode': 1,
                }
            elif code in ('EACCES', 'EPERM', 13, 1):  # errno.EACCES, errno.EPERM
                return {
                    'result': False,
                    'message': f'Attachment "{rawPath}" is not accessible (permission denied).',
                    'errorCode': 1,
                }
            raise
    
    return {'result': True}


async def resolveAttachments(
    rawPaths: List[str],
    uploadCtx: Dict[str, any]
) -> List[ResolvedAttachment]:
    """Resolve attachment paths and optionally upload to bridge.
    
    Stat serially (local, fast) to keep ordering deterministic, then upload
    in parallel (network, slow). Upload failures resolve undefined — the
    attachment still carries {path, size, isImage} for local renderers.
    
    Args:
        rawPaths: List of file paths to resolve
        uploadCtx: Context with replBridgeEnabled flag and optional abort signal
    
    Returns:
        List of resolved attachment metadata
    """
    # Stat serially to maintain ordering
    stated: List[ResolvedAttachment] = []
    
    for rawPath in rawPaths:
        fullPath = expandPath(rawPath)
        
        # Single stat — we need size, so this is the operation, not a guard.
        # validateInput ran before us, but the file could have moved since
        # (TOCTOU); if it did, let the error propagate so the model sees it.
        try:
            stats = os.stat(fullPath)
            stated.append({
                'path': fullPath,
                'size': stats.st_size,
                'isImage': bool(IMAGE_EXTENSION_REGEX.search(fullPath)),
            })
        except Exception:
            # If file disappeared between validation and here, let error propagate
            raise
    
    # Dynamic import inside the feature() guard so upload.py (axios, crypto,
    # zod, auth utils, MIME map) is fully eliminated from non-BRIDGE_MODE
    # builds. A static import would force module-scope evaluation regardless
    # of the guard inside uploadBriefAttachment — CORTEX.md: "helpers defined
    # outside remain in the build even if never called".
    bridge_mode = isEnvTruthy(os.environ.get('BRIDGE_MODE'))
    
    if bridge_mode:
        # Headless/SDK callers never set appState.replBridgeEnabled (only the TTY
        # REPL does, at main.tsx init). CORTEX_CODE_BRIEF_UPLOAD lets a host that
        # runs the AI agent as a subprocess opt in — e.g. the cowork desktop bridge,
        # which already passes CORTEX_CODE_OAUTH_TOKEN for auth.
        shouldUpload = (
            uploadCtx.get('replBridgeEnabled', False) or
            isEnvTruthy(os.environ.get('CORTEX_CODE_BRIEF_UPLOAD'))
        )
        
        try:
            from .upload import uploadBriefAttachment
            
            # Upload in parallel
            import asyncio
            uuids = await asyncio.gather(*[
                uploadBriefAttachment(
                    attachment['path'],
                    attachment['size'],
                    {
                        'replBridgeEnabled': shouldUpload,
                        'signal': uploadCtx.get('signal'),
                    }
                )
                for attachment in stated
            ])
            
            # Merge UUIDs back into attachments
            return [
                {**attachment, 'file_uuid': uuid} if uuid else attachment
                for attachment, uuid in zip(stated, uuids)
            ]
        except ImportError:
            # upload.py not available, return stated attachments without UUIDs
            pass
    
    return stated
