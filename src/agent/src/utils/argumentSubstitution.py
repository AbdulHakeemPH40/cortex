"""
Auto-converted from argumentSubstitution.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


def parseArguments(self, args: str) -> List[str]:
    """TODO: Implement parseArguments"""
    pass


def parseArgumentNames(self, argumentNames: List[Any]) -> List[str]:
    """TODO: Implement parseArgumentNames"""
    pass


def generateProgressiveArgumentHint(self, argNames: List[str], typedArgs: List[str]) -> Optional[str]:
    """TODO: Implement generateProgressiveArgumentHint"""
    pass


def substituteArguments(self, content: str, args: Optional[str], appendIfNoPlaceholder = true, argumentNames: List[List[str]]) -> str:
    """TODO: Implement substituteArguments"""
    pass



__all__ = ['parseArguments', 'parseArgumentNames', 'generateProgressiveArgumentHint', 'substituteArguments']