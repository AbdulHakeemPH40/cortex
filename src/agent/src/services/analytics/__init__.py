"""
Auto-converted from index.ts
TODO: Review and refine type annotations
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


def attachAnalyticsSink(self, newSink: AnalyticsSink) -> None:
    """TODO: Implement attachAnalyticsSink"""
    pass


def logEvent(self, eventName: str, // intentionally no strings unless AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS, // to avoid accidentally logging code/filepaths
  metadata: LogEventMetadata) -> None:
    """TODO: Implement logEvent"""
    pass


def logEventAsync(self, eventName: str, // intentionally no strings, to avoid accidentally logging code/filepaths
  metadata: LogEventMetadata) -> None:
    """TODO: Implement logEventAsync"""
    pass


def _resetForTesting(self) -> None:
    """TODO: Implement _resetForTesting"""
    pass



__all__ = ['attachAnalyticsSink', 'logEvent', 'logEventAsync', '_resetForTesting']