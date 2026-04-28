"""
Auto-converted from oauth.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict


class OauthConfig(TypedDict):
    """OAuth configuration."""
    client_id: str
    client_secret: str
    redirect_uri: Optional[str]
    scopes: List[str]


def fileSuffixForOauthConfig(self) -> str:
    """TODO: Implement fileSuffixForOauthConfig"""
    pass


def getOauthConfig(self) -> OauthConfig:
    """TODO: Implement getOauthConfig"""
    pass



__all__ = ['fileSuffixForOauthConfig', 'getOauthConfig']