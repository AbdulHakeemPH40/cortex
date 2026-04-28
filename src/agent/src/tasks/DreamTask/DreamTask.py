"""
Auto-converted from DreamTask.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


def isDreamTask(self, task: Any) -> task is DreamTaskState:
    """TODO: Implement isDreamTask"""
    pass


def registerDreamTask(self, setAppState: SetAppState, opts: {) -> str:
    """TODO: Implement registerDreamTask"""
    pass


def addDreamTurn(self, taskId: str, turn: DreamTurn, touchedPaths: List[str], setAppState: SetAppState) -> None:
    """TODO: Implement addDreamTurn"""
    pass


def completeDreamTask(self, taskId: str, setAppState: SetAppState) -> None:
    """TODO: Implement completeDreamTask"""
    pass


def failDreamTask(self, taskId: str, setAppState: SetAppState) -> None:
    """TODO: Implement failDreamTask"""
    pass



__all__ = ['isDreamTask', 'registerDreamTask', 'addDreamTurn', 'completeDreamTask', 'failDreamTask']