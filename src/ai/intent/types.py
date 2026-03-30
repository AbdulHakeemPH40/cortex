"""
Intent Classification Types and Enums for Cortex AI Agent
Based on OpenCode's intent classification system
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


class IntentType(Enum):
    """Primary intent types for user messages."""
    # Terminal/Command operations
    TERMINAL_COMMAND = "terminal_command"
    SYSTEM_MONITORING = "system_monitoring"
    FILE_OPERATION = "file_operation"
    
    # Code operations
    CODE_GENERATION = "code_generation"
    CODE_ANALYSIS = "code_analysis"
    CODE_REVIEW = "code_review"
    REFACTORING = "refactoring"
    
    # Debug operations
    DEBUGGING = "debugging"
    ERROR_ANALYSIS = "error_analysis"
    
    # Research operations
    RESEARCH = "research"
    DOCUMENTATION = "documentation"
    LEARNING = "learning"
    
    # Build/Deploy operations
    BUILD_PROCESS = "build_process"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    
    # General
    GENERAL_CONVERSATION = "general_conversation"
    QUESTION_ANSWERING = "question_answering"


class SubIntent(Enum):
    """Sub-intents for more granular classification."""
    # Complexity levels
    SIMPLE = "simple"
    COMPLEX = "complex"
    MULTI_STEP = "multi_step"
    
    # Terminal sub-intents
    SIMPLE_COMMAND = "simple_command"
    FILE_LISTING = "file_listing"
    SEARCH_FILES = "search_files"
    PACKAGE_INSTALL = "package_install"
    GIT_OPERATION = "git_operation"
    
    # Code sub-intents
    WRITE_FUNCTION = "write_function"
    WRITE_CLASS = "write_class"
    FIX_BUG = "fix_bug"
    OPTIMIZE = "optimize"
    
    # Debug sub-intents
    TRACE_ERROR = "trace_error"
    INSPECT_VARIABLE = "inspect_variable"
    
    # Research sub-intents
    WEB_SEARCH = "web_search"
    CODE_EXPLORATION = "code_exploration"


class AgentType(Enum):
    """Types of agents available in the system."""
    GENERAL = "general"           # General conversation & simple tasks
    BUILD = "build"              # Code compilation & building
    PLAN = "plan"                # Complex multi-step planning
    DEBUG = "debug"              # Debugging assistance
    RESEARCH = "research"        # Research & analysis
    CODE = "code"                # Code-specific operations
    TERMINAL = "terminal"        # Terminal-focused operations


@dataclass
class IntentClassification:
    """Result of intent classification."""
    primary_intent: IntentType
    sub_intents: List[SubIntent] = field(default_factory=list)
    confidence: float = 0.0
    requires_terminal: bool = False
    requires_code_tools: bool = False
    requires_web_search: bool = False
    complexity: str = "simple"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "primary_intent": self.primary_intent.value,
            "sub_intents": [s.value for s in self.sub_intents],
            "confidence": self.confidence,
            "requires_terminal": self.requires_terminal,
            "requires_code_tools": self.requires_code_tools,
            "requires_web_search": self.requires_web_search,
            "complexity": self.complexity,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AgentRoute:
    """Routing decision for an agent."""
    agent_type: AgentType
    confidence: float = 0.0
    supporting_agents: List[AgentType] = field(default_factory=list)
    routing_reason: str = ""
    estimated_steps: int = 1
    requires_planning: bool = False


@dataclass
class PatternMatch:
    """A pattern match result."""
    pattern: str
    intent: IntentType
    confidence: float
    matched_text: str


# Intent detection patterns
INTENT_PATTERNS = {
    IntentType.TERMINAL_COMMAND: [
        # Command execution patterns
        r'\brun\b.*\b(command|script|bash|shell|terminal)\b',
        r'\bexecute\b.*\bcommand\b',
        r'\bshow\b.*\b(files|directory|process|system)\b',
        r'\bcheck\b.*\b(status|version|installed)\b',
        r'\blist\b.*\b(files|directories|processes)\b',
        r'\bfind\b.*\b(file|pattern|text)\b',
        r'\bgrep\b.*\b(pattern|text)\b',
        r'\bcat\b|\bhead\b|\btail\b|\bless\b',
        r'\bcd\b.*\b(to|directory)\b',
        r'\bmkdir\b|\brmdir\b|\btouch\b',
        r'\bcopy\b|\bmove\b|\brename\b',
        r'\binstall\b.*\b(package|dependency)\b',
        r'\bupdate\b.*\b(package|system)\b',
        r'\bstart\b|\bstop\b|\brestart\b.*\b(service|server)\b',
        r'\bkill\b.*\b(process)\b',
        r'\bgit\b.*\b(push|pull|commit|clone|branch|status)\b',
        r'\bdocker\b.*\b(run|build|stop|start)\b',
        r'\bnpm\b|\byarn\b|\bpip\b.*\b(install|run)\b',
    ],
    
    IntentType.CODE_GENERATION: [
        r'\b(code|program|function|class)\b.*\b(write|create|generate)\b',
        r'\bwrite\b.*\b(code|function|class|method)\b',
        r'\bcreate\b.*\b(code|script|program)\b',
        r'\bgenerate\b.*\b(code|implementation)\b',
        r'\bimplement\b.*\b(function|class|feature)\b',
        r'\badd\b.*\b(feature|function|method)\b',
    ],
    
    IntentType.CODE_ANALYSIS: [
        r'\banalyze\b.*\b(code|function|class)\b',
        r'\bexplain\b.*\b(code|function|algorithm)\b',
        r'\bwhat\s+does\b.*\b(code|function|class)\b',
        r'\bhow\s+does\b.*\b(work|function)\b',
        r'\breview\b.*\b(code|implementation)\b',
        r'\bcheck\b.*\b(code|quality|style)\b',
    ],
    
    IntentType.DEBUGGING: [
        r'\bdebug\b.*\b(code|error|issue)\b',
        r'\bfix\b.*\b(code|bug|error)\b',
        r'\bsolve\b.*\b(error|issue|problem)\b',
        r'\berror\b.*\b(in|with)\b',
        r'\bexception\b|\btraceback\b|\bstack\s+trace\b',
        r'\bnot\s+working\b|\bfailing\b|\bbroken\b',
        r'\bwhy\s+is\b.*\b(error|failing|not)\b',
    ],
    
    IntentType.REFACTORING: [
        r'\brefactor\b.*\b(code|function|class)\b',
        r'\boptimize\b.*\b(code|performance)\b',
        r'\bimprove\b.*\b(code|quality|performance)\b',
        r'\bclean\s+up\b.*\b(code)\b',
        r'\bmake\b.*\b(better|faster|cleaner)\b',
    ],
    
    IntentType.BUILD_PROCESS: [
        r'\bcompile\b|\bbuild\b|\bmake\b',
        r'\brun\b.*\b(tests?|build)\b',
        r'\btest\b.*\b(code|project)\b',
        r'\bdeploy\b.*\b(code|project)\b',
        r'\bpackage\b.*\b(project|code)\b',
    ],
    
    IntentType.RESEARCH: [
        r'\bresearch\b|\bsearch\b|\bfind\b.*\bonline',
        r'\blook\s+up\b|\bgoogle\b|\bsearch\s+for\b',
        r'\bwhat\s+is\b|\bhow\s+to\b|\bdocumentation\s+for\b',
        r'\bdocumentation\b|\bdocs\b|\breference\b',
        r'\btutorial\b|\bguide\b|\bexample\b',
    ],
    
    IntentType.SYSTEM_MONITORING: [
        r'\bcheck\b.*\b(disk|memory|cpu|usage)\b',
        r'\bmonitor\b.*\b(system|resources)\b',
        r'\bnetwork\b.*\b(connection|status|ping)\b',
        r'\bshow\b.*\b(processes|resources|usage)\b',
    ],
}


# Complexity indicators
COMPLEXITY_INDICATORS = {
    "complex": [
        r'\band\b.*\band\b.*\band\b',  # Multiple "and" operations
        r'\bstep\s+\d+\b',  # Explicit steps mentioned
        r'\bfirst\b.*\bthen\b.*\bfinally\b',
        r'\bmultiple\b|\bseveral\b|\bmany\b',
        r'\bimplement\b.*\b(system|feature|module)\b',
        r'\bcreate\b.*\b(project|application|system)\b',
        r'\bsetup\b.*\b(project|environment)\b',
    ],
    "multi_step": [
        r'\bplan\b|\broadmap\b|\bstrategy\b',
        r'\bdesign\b.*\b(architecture|system)\b',
        r'\bbreak\s+down\b|\bdecompose\b',
    ],
}


# Terminal command patterns for sub-intent detection
TERMINAL_SUB_PATTERNS = {
    SubIntent.FILE_LISTING: [
        r'\blist\b.*\bfiles?\b',
        r'\bshow\b.*\b(files?|directory|folders?)\b',
        r'\bls\b|\bdir\b',
    ],
    SubIntent.SEARCH_FILES: [
        r'\bsearch\b.*\b(in|within)\b.*\bfiles?\b',
        r'\bfind\b.*\b(text|pattern|string)\b',
        r'\bgrep\b.*\b(for|pattern)\b',
    ],
    SubIntent.PACKAGE_INSTALL: [
        r'\binstall\b.*\b(package|dependency|module|library)\b',
        r'\bnpm\s+install\b|\byarn\s+add\b|\bpip\s+install\b',
    ],
    SubIntent.GIT_OPERATION: [
        r'\bgit\s+(status|log|commit|push|pull|clone|branch)\b',
        r'\bcommit\b.*\b(changes|code)\b',
    ],
}


# Code sub-patterns
CODE_SUB_PATTERNS = {
    SubIntent.WRITE_FUNCTION: [
        r'\bwrite\b.*\bfunction\b',
        r'\bcreate\b.*\bfunction\b',
        r'\bimplement\b.*\bfunction\b',
    ],
    SubIntent.WRITE_CLASS: [
        r'\bwrite\b.*\bclass\b',
        r'\bcreate\b.*\bclass\b',
        r'\bdefine\b.*\bclass\b',
    ],
    SubIntent.FIX_BUG: [
        r'\bfix\b.*\bbug\b',
        r'\bsolve\b.*\b(error|issue)\b',
        r'\bdebug\b.*\b(code|error)\b',
    ],
    SubIntent.OPTIMIZE: [
        r'\boptimize\b.*\b(code|performance)\b',
        r'\bmake\b.*\b(faster|efficient|better)\b',
    ],
}
