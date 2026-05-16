"""
Auto-converted from mcpOutputStorage.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


def getFormatDescription(self, type: MCPResultType, schema: Any = None) -> str:
    """TODO: Implement getFormatDescription"""
    pass


def getLargeOutputInstructions(self, rawOutputPath: str, contentLength: int, formatDescription: str, maxReadLength: int = None) -> str:
    """TODO: Implement getLargeOutputInstructions"""
    pass


def extensionForMimeType(self, mimeType: Optional[str]) -> str:
    """TODO: Implement extensionForMimeType"""
    pass


def isBinaryContentType(self, contentType: str) -> bool:
    """TODO: Implement isBinaryContentType"""
    pass


def persistBinaryContent(self, bytes: Buffer, mimeType: Optional[str], persistId: str) -> PersistBinaryResult:
    """TODO: Implement persistBinaryContent"""
    pass


def getBinaryBlobSavedMessage(self, filepath: str, mimeType: Optional[str], size: int, sourceDescription: str) -> str:
    """TODO: Implement getBinaryBlobSavedMessage"""
    pass



__all__ = ['getFormatDescription', 'getLargeOutputInstructions', 'extensionForMimeType', 'isBinaryContentType', 'persistBinaryContent', 'getBinaryBlobSavedMessage']