"""
Code Completion Module
OpenCode-style intelligent code completion for Cortex IDE
"""
from src.ai.code_completion.types import (
    CodeIssue,
    CodeHealthReport,
    CompletionResult,
    CompletionCandidate,
    CompletionContext,
    IssueType,
    IssueSeverity,
    CompletionStrategy,
    PatternMatch
)
from src.ai.code_completion.analyzer import CodeHealthAnalyzer
from src.ai.code_completion.engine import (
    CodeCompletionEngine,
    get_code_completion_engine
)

__all__ = [
    'CodeIssue',
    'CodeHealthReport',
    'CompletionResult',
    'CompletionCandidate',
    'CompletionContext',
    'IssueType',
    'IssueSeverity',
    'CompletionStrategy',
    'PatternMatch',
    'CodeHealthAnalyzer',
    'CodeCompletionEngine',
    'get_code_completion_engine',
]
