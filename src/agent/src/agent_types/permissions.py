"""
Pure permission type definitions extracted to break import cycles.

This file contains only type definitions and constants with no runtime dependencies.
Implementation files remain in src/utils/permissions/ but can now import from here
to avoid circular dependencies.
"""

from typing import Any, Dict, List, Literal, Mapping, Optional, TypedDict, Union

# ============================================================================
# Permission Modes
# ============================================================================

#: External permission modes - user-addressable
EXTERNAL_PERMISSION_MODES = [
    'acceptEdits',
    'bypassPermissions',
    'default',
    'dontAsk',
    'plan',
]

ExternalPermissionMode = Literal['acceptEdits', 'bypassPermissions', 'default', 'dontAsk', 'plan']

#: Internal permission modes - includes 'auto' and 'bubble'
InternalPermissionMode = Literal[
    'acceptEdits', 'bypassPermissions', 'default', 'dontAsk', 'plan', 'auto', 'bubble'
]

PermissionMode = InternalPermissionMode

#: Runtime validation set: modes that are user-addressable
INTERNAL_PERMISSION_MODES: List[PermissionMode] = [
    'acceptEdits',
    'bypassPermissions',
    'default',
    'dontAsk',
    'plan',
    # 'auto' is feature-flagged in TypeScript, omitting for simplicity
]

PERMISSION_MODES = INTERNAL_PERMISSION_MODES


# ============================================================================
# Permission Behaviors
# ============================================================================

PermissionBehavior = Literal['allow', 'deny', 'ask']


# ============================================================================
# Permission Rules
# ============================================================================

#: Where a permission rule originated from
PermissionRuleSource = Literal[
    'userSettings',
    'projectSettings',
    'localSettings',
    'flagSettings',
    'policySettings',
    'cliArg',
    'command',
    'session',
]


class PermissionRuleValue(TypedDict, total=False):
    """The value of a permission rule - specifies which tool and optional content."""
    toolName: str
    ruleContent: Optional[str]


class PermissionRule(TypedDict, total=False):
    """A permission rule with its source and behavior."""
    source: PermissionRuleSource
    ruleBehavior: PermissionBehavior
    ruleValue: PermissionRuleValue


# ============================================================================
# Permission Updates
# ============================================================================

#: Where a permission update should be persisted
PermissionUpdateDestination = Literal[
    'userSettings',
    'projectSettings',
    'localSettings',
    'session',
    'cliArg',
]


class PermissionUpdateAddRules(TypedDict):
    """Add rules update operation."""
    type: Literal['addRules']
    destination: PermissionUpdateDestination
    rules: List[PermissionRuleValue]
    behavior: PermissionBehavior


class PermissionUpdateReplaceRules(TypedDict):
    """Replace rules update operation."""
    type: Literal['replaceRules']
    destination: PermissionUpdateDestination
    rules: List[PermissionRuleValue]
    behavior: PermissionBehavior


class PermissionUpdateRemoveRules(TypedDict):
    """Remove rules update operation."""
    type: Literal['removeRules']
    destination: PermissionUpdateDestination
    rules: List[PermissionRuleValue]
    behavior: PermissionBehavior


class PermissionUpdateSetMode(TypedDict):
    """Set mode update operation."""
    type: Literal['setMode']
    destination: PermissionUpdateDestination
    mode: ExternalPermissionMode


class PermissionUpdateAddDirectories(TypedDict):
    """Add directories update operation."""
    type: Literal['addDirectories']
    destination: PermissionUpdateDestination
    directories: List[str]


class PermissionUpdateRemoveDirectories(TypedDict):
    """Remove directories update operation."""
    type: Literal['removeDirectories']
    destination: PermissionUpdateDestination
    directories: List[str]


PermissionUpdate = Union[
    PermissionUpdateAddRules,
    PermissionUpdateReplaceRules,
    PermissionUpdateRemoveRules,
    PermissionUpdateSetMode,
    PermissionUpdateAddDirectories,
    PermissionUpdateRemoveDirectories,
]

#: Source of an additional working directory permission
WorkingDirectorySource = PermissionRuleSource


class AdditionalWorkingDirectory(TypedDict):
    """An additional directory included in permission scope."""
    path: str
    source: WorkingDirectorySource


# ============================================================================
# Permission Decisions & Results
# ============================================================================

class PermissionCommandMetadata(TypedDict, total=False):
    """
    Minimal command shape for permission metadata.
    This is intentionally a subset of the full Command type to avoid import cycles.
    Only includes properties needed by permission-related components.
    """
    name: str
    description: Optional[str]


PermissionMetadata = Union[
    Dict[Literal['command'], PermissionCommandMetadata],
    None,
]


class PendingClassifierCheck(TypedDict):
    """
    Metadata for a pending classifier check that will run asynchronously.
    Used to enable non-blocking allow classifier evaluation.
    """
    command: str
    cwd: str
    descriptions: List[str]


class PermissionAllowDecision(TypedDict, total=False):
    """Result when permission is granted."""
    behavior: Literal['allow']
    updatedInput: Optional[Dict[str, Any]]
    userModified: Optional[bool]
    decisionReason: Optional['PermissionDecisionReason']
    toolUseID: Optional[str]
    acceptFeedback: Optional[str]
    contentBlocks: Optional[List[Dict[str, Any]]]


class PermissionAskDecision(TypedDict, total=False):
    """Result when user should be prompted."""
    behavior: Literal['ask']
    message: str
    updatedInput: Optional[Dict[str, Any]]
    decisionReason: Optional['PermissionDecisionReason']
    suggestions: Optional[List[PermissionUpdate]]
    blockedPath: Optional[str]
    metadata: Optional[PermissionMetadata]
    isBashSecurityCheckForMisparsing: Optional[bool]
    pendingClassifierCheck: Optional[PendingClassifierCheck]
    contentBlocks: Optional[List[Dict[str, Any]]]


class PermissionDenyDecision(TypedDict, total=False):
    """Result when permission is denied."""
    behavior: Literal['deny']
    message: str
    decisionReason: 'PermissionDecisionReason'
    toolUseID: Optional[str]


PermissionDecision = Union[
    PermissionAllowDecision,
    PermissionAskDecision,
    PermissionDenyDecision,
]


class PermissionPassthroughDecision(TypedDict, total=False):
    """Permission result with passthrough behavior."""
    behavior: Literal['passthrough']
    message: str
    decisionReason: Optional['PermissionDecisionReason']
    suggestions: Optional[List[PermissionUpdate]]
    blockedPath: Optional[str]
    pendingClassifierCheck: Optional[PendingClassifierCheck]


PermissionResult = Union[
    PermissionDecision,
    PermissionPassthroughDecision,
]


# ============================================================================
# Permission Decision Reasons
# ============================================================================

class PermissionDecisionReasonRule(TypedDict):
    type: Literal['rule']
    rule: PermissionRule


class PermissionDecisionReasonMode(TypedDict):
    type: Literal['mode']
    mode: PermissionMode


class PermissionDecisionReasonSubcommandResults(TypedDict):
    type: Literal['subcommandResults']
    reasons: Dict[str, PermissionResult]


class PermissionDecisionReasonPermissionPromptTool(TypedDict):
    type: Literal['permissionPromptTool']
    permissionPromptToolName: str
    toolResult: Any


class PermissionDecisionReasonHook(TypedDict):
    type: Literal['hook']
    hookName: str
    hookSource: Optional[str]
    reason: Optional[str]


class PermissionDecisionReasonAsyncAgent(TypedDict):
    type: Literal['asyncAgent']
    reason: str


class PermissionDecisionReasonSandboxOverride(TypedDict):
    type: Literal['sandboxOverride']
    reason: Literal['excludedCommand', 'dangerouslyDisableSandbox']


class PermissionDecisionReasonClassifier(TypedDict):
    type: Literal['classifier']
    classifier: str
    reason: str


class PermissionDecisionReasonWorkingDir(TypedDict):
    type: Literal['workingDir']
    reason: str


class PermissionDecisionReasonSafetyCheck(TypedDict):
    type: Literal['safetyCheck']
    reason: str
    classifierApprovable: bool


class PermissionDecisionReasonOther(TypedDict):
    type: Literal['other']
    reason: str


PermissionDecisionReason = Union[
    PermissionDecisionReasonRule,
    PermissionDecisionReasonMode,
    PermissionDecisionReasonSubcommandResults,
    PermissionDecisionReasonPermissionPromptTool,
    PermissionDecisionReasonHook,
    PermissionDecisionReasonAsyncAgent,
    PermissionDecisionReasonSandboxOverride,
    PermissionDecisionReasonClassifier,
    PermissionDecisionReasonWorkingDir,
    PermissionDecisionReasonSafetyCheck,
    PermissionDecisionReasonOther,
]


# ============================================================================
# Bash Classifier Types
# ============================================================================

ClassifierBehavior = Literal['deny', 'ask', 'allow']


class ClassifierResult(TypedDict):
    matches: bool
    matchedDescription: Optional[str]
    confidence: Literal['high', 'medium', 'low']
    reason: str


class ClassifierUsage(TypedDict):
    inputTokens: int
    outputTokens: int
    cacheReadInputTokens: int
    cacheCreationInputTokens: int


class YoloClassifierResult(TypedDict, total=False):
    thinking: Optional[str]
    shouldBlock: bool
    reason: str
    unavailable: Optional[bool]
    transcriptTooLong: Optional[bool]
    model: str
    usage: Optional[ClassifierUsage]
    durationMs: Optional[int]
    promptLengths: Optional[Dict[str, int]]
    errorDumpPath: Optional[str]
    stage: Optional[Literal['fast', 'thinking']]
    stage1Usage: Optional[ClassifierUsage]
    stage1DurationMs: Optional[int]
    stage1RequestId: Optional[str]
    stage1MsgId: Optional[str]
    stage2Usage: Optional[ClassifierUsage]
    stage2DurationMs: Optional[int]
    stage2RequestId: Optional[str]
    stage2MsgId: Optional[str]


# ============================================================================
# Permission Explainer Types
# ============================================================================

RiskLevel = Literal['LOW', 'MEDIUM', 'HIGH']


class PermissionExplanation(TypedDict):
    riskLevel: RiskLevel
    explanation: str
    reasoning: str
    risk: str


# ============================================================================
# Tool Permission Context
# ============================================================================

class ToolPermissionContext(TypedDict, total=False):
    """
    Context needed for permission checking in tools.
    Note: Uses a simplified DeepImmutable approximation for this types-only file.
    """
    mode: PermissionMode
    additionalWorkingDirectories: Mapping[str, AdditionalWorkingDirectory]
    alwaysAllowRules: Dict[str, List[str]]  # ToolPermissionRulesBySource
    alwaysDenyRules: Dict[str, List[str]]
    alwaysAskRules: Dict[str, List[str]]
    isBypassPermissionsModeAvailable: bool
    strippedDangerousRules: Optional[Dict[str, List[str]]]
    shouldAvoidPermissionPrompts: Optional[bool]
    awaitAutomatedChecksBeforeDialog: Optional[bool]
    prePlanMode: Optional[PermissionMode]


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Permission Modes
    'EXTERNAL_PERMISSION_MODES',
    'ExternalPermissionMode',
    'InternalPermissionMode',
    'PermissionMode',
    'INTERNAL_PERMISSION_MODES',
    'PERMISSION_MODES',
    # Permission Behaviors
    'PermissionBehavior',
    # Permission Rules
    'PermissionRuleSource',
    'PermissionRuleValue',
    'PermissionRule',
    # Permission Updates
    'PermissionUpdateDestination',
    'PermissionUpdateAddRules',
    'PermissionUpdateReplaceRules',
    'PermissionUpdateRemoveRules',
    'PermissionUpdateSetMode',
    'PermissionUpdateAddDirectories',
    'PermissionUpdateRemoveDirectories',
    'PermissionUpdate',
    'WorkingDirectorySource',
    'AdditionalWorkingDirectory',
    # Permission Decisions
    'PermissionCommandMetadata',
    'PermissionMetadata',
    'PendingClassifierCheck',
    'PermissionAllowDecision',
    'PermissionAskDecision',
    'PermissionDenyDecision',
    'PermissionDecision',
    'PermissionPassthroughDecision',
    'PermissionResult',
    # Permission Decision Reasons
    'PermissionDecisionReasonRule',
    'PermissionDecisionReasonMode',
    'PermissionDecisionReasonSubcommandResults',
    'PermissionDecisionReasonPermissionPromptTool',
    'PermissionDecisionReasonHook',
    'PermissionDecisionReasonAsyncAgent',
    'PermissionDecisionReasonSandboxOverride',
    'PermissionDecisionReasonClassifier',
    'PermissionDecisionReasonWorkingDir',
    'PermissionDecisionReasonSafetyCheck',
    'PermissionDecisionReasonOther',
    'PermissionDecisionReason',
    # Classifier Types
    'ClassifierBehavior',
    'ClassifierResult',
    'ClassifierUsage',
    'YoloClassifierResult',
    # Explainer Types
    'RiskLevel',
    'PermissionExplanation',
    # Tool Permission Context
    'ToolPermissionContext',
]
