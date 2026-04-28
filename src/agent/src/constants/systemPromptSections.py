"""
Auto-converted from systemPromptSections.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


# Type definitions
ComputeFn = Callable[[], str]


@dataclass
class SystemPromptSection:
    """Represents a section in the system prompt."""
    name: str
    compute: ComputeFn
    cached: bool = True


def systemPromptSection(self, name: str, compute: ComputeFn) -> SystemPromptSection:
    """TODO: Implement systemPromptSection"""
    pass


def DANGEROUS_uncachedSystemPromptSection(self, name: str, compute: ComputeFn, _reason: str) -> SystemPromptSection:
    """TODO: Implement DANGEROUS_uncachedSystemPromptSection"""
    pass


def resolveSystemPromptSections(self, sections: List[SystemPromptSection]) -> List[Any]:
    """TODO: Implement resolveSystemPromptSections"""
    pass


def clearSystemPromptSections(self) -> None:
    """TODO: Implement clearSystemPromptSections"""
    pass



__all__ = ['systemPromptSection', 'DANGEROUS_uncachedSystemPromptSection', 'resolveSystemPromptSections', 'clearSystemPromptSections']