"""
Auto-converted from fsOperations.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


def safeResolvePath(self, fs: FsOperations, filePath: str) -> :
    """TODO: Implement safeResolvePath"""
    pass


def isDuplicatePath(self, fs: FsOperations, filePath: str, loadedPaths: Set<string>) -> bool:
    """TODO: Implement isDuplicatePath"""
    pass


def resolveDeepestExistingAncestorSync(self, fs: FsOperations, absolutePath: str) -> Optional[str]:
    """TODO: Implement resolveDeepestExistingAncestorSync"""
    pass


def getPathsForPermissionCheck(self, inputPath: str) -> List[str]:
    """TODO: Implement getPathsForPermissionCheck"""
    pass


def setFsImplementation(self, implementation: FsOperations) -> None:
    """TODO: Implement setFsImplementation"""
    pass


def getFsImplementation(self) -> FsOperations:
    """TODO: Implement getFsImplementation"""
    pass


def setOriginalFsImplementation(self) -> None:
    """TODO: Implement setOriginalFsImplementation"""
    pass


def readFileRange(self, path: str, offset: int, maxBytes: int) -> Any:
    """TODO: Implement readFileRange"""
    pass


def tailFile(self, path: str, maxBytes: int) -> ReadFileRangeResult:
    """TODO: Implement tailFile"""
    pass



__all__ = ['safeResolvePath', 'isDuplicatePath', 'resolveDeepestExistingAncestorSync', 'getPathsForPermissionCheck', 'setFsImplementation', 'getFsImplementation', 'setOriginalFsImplementation', 'readFileRange', 'tailFile']