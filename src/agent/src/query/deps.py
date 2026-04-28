"""
Auto-converted from deps.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class QueryDeps:
    """Query dependencies."""
    tools: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


def productionDeps() -> QueryDeps:
    """Get production dependencies."""
    return QueryDeps()



__all__ = ['productionDeps']