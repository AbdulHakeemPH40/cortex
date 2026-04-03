"""
Code Completion Types and Data Structures
OpenCode-style code completion system for Cortex IDE
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum


class IssueType(Enum):
    """Types of code issues detected"""
    SYNTAX_ERROR = "syntax_error"
    INCOMPLETE_STRUCTURE = "incomplete_structure"
    LOGIC_GAP = "logic_gap"
    MISSING_IMPLEMENTATION = "missing_implementation"
    PLACEHOLDER_DETECTED = "placeholder_detected"
    UNDEFINED_VARIABLE = "undefined_variable"
    MISSING_ERROR_HANDLING = "missing_error_handling"
    INCOMPLETE_FUNCTION = "incomplete_function"
    UNCLOSED_BLOCK = "unclosed_block"
    PATTERN_MISMATCH = "pattern_mismatch"


class IssueSeverity(Enum):
    """Severity levels for code issues"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CompletionStrategy(Enum):
    """Available completion strategies"""
    PATTERN_BASED = "pattern_based"
    TEMPLATE_BASED = "template_based"
    AI_BASED = "ai_based"
    CONTEXT_AWARE = "context_aware"


@dataclass
class CodeIssue:
    """Represents a detected code issue"""
    type: IssueType
    description: str
    severity: IssueSeverity
    position: Optional[int] = None
    line_number: Optional[int] = None
    column: Optional[int] = None
    suggestions: List[str] = field(default_factory=list)
    context: str = ""
    confidence: float = 0.0
    language: str = "python"


@dataclass
class CodeHealthReport:
    """Complete health report for code"""
    code: str
    issues: List[CodeIssue]
    language: str
    severity: IssueSeverity
    completion_required: bool
    timestamp: float = field(default_factory=lambda: __import__('time').time())


@dataclass
class CompletionContext:
    """Context for code completion"""
    hint: str = ""
    language: str = "python"
    project_type: Optional[str] = None
    file_path: Optional[str] = None
    cursor_position: Optional[int] = None
    surrounding_code: str = ""
    imports: List[str] = field(default_factory=list)
    function_scope: str = ""


@dataclass
class CompletionCandidate:
    """A single completion candidate"""
    completion: str
    source: str
    confidence: float
    reasoning: str
    changes_made: List[str] = field(default_factory=list)


@dataclass
class CompletionResult:
    """Result of code completion operation"""
    original_code: str
    completed_code: str
    issues_fixed: int
    confidence: float
    explanations: List[str] = field(default_factory=list)
    alternatives: List[CompletionCandidate] = field(default_factory=list)
    strategy_used: CompletionStrategy = CompletionStrategy.AI_BASED


@dataclass
class PatternMatch:
    """Pattern match result"""
    pattern_name: str
    match_text: str
    completion: str
    confidence: float
    position: int


class CodeLanguage(Enum):
    """Supported programming languages"""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    CPP = "cpp"
    GO = "go"
    RUST = "rust"


# Common incomplete code patterns
INCOMPLETE_PATTERNS = {
    "python": [
        {
            "name": "unclosed_function",
            "pattern": r"def\s+\w+\s*\([^)]*\)\s*:\s*$",
            "completion": "\n    pass  # TODO: Implement",
            "description": "Function definition without body"
        },
        {
            "name": "unclosed_class",
            "pattern": r"class\s+\w+\s*(?:\([^)]*\))?\s*:\s*$",
            "completion": "\n    pass",
            "description": "Class definition without body"
        },
        {
            "name": "unclosed_if",
            "pattern": r"if\s+.+:\s*$",
            "completion": "\n    pass",
            "description": "If statement without body"
        },
        {
            "name": "unclosed_for",
            "pattern": r"for\s+.+:\s*$",
            "completion": "\n    pass",
            "description": "For loop without body"
        },
        {
            "name": "unclosed_try",
            "pattern": r"try:\s*$",
            "completion": "\n    pass\nexcept Exception as e:\n    pass",
            "description": "Try block without except"
        },
        {
            "name": "todo_comment",
            "pattern": r"#\s*TODO:\s*(.+)",
            "completion": None,  # AI-generated
            "description": "TODO comment needs implementation"
        },
        {
            "name": "pass_only_function",
            "pattern": r"def\s+(\w+)\s*\([^)]*\)\s*:\s*\n\s+pass\s*$",
            "completion": None,  # AI-generated
            "description": "Function with only pass statement"
        },
    ],
    "javascript": [
        {
            "name": "unclosed_function",
            "pattern": r"function\s+\w+\s*\([^)]*\)\s*\{\s*$",
            "completion": "\n    // TODO: Implement\n}",
            "description": "Function without closing brace"
        },
        {
            "name": "arrow_function_no_body",
            "pattern": r"const\s+\w+\s*=\s*\([^)]*\)\s*=>\s*$",
            "completion": " {\n    // TODO: Implement\n}",
            "description": "Arrow function without body"
        },
        {
            "name": "unclosed_if",
            "pattern": r"if\s*\([^)]*\)\s*\{\s*$",
            "completion": "\n    // TODO: Implement\n}",
            "description": "If statement without closing brace"
        },
        {
            "name": "unclosed_promise",
            "pattern": r"\.then\s*\([^)]*\)\s*$",
            "completion": "\n  .catch(error => {\n    console.error('Error:', error);\n  });",
            "description": "Promise chain without catch"
        },
    ]
}


# Template completions for common patterns
COMPLETION_TEMPLATES = {
    "python": {
        "error_handling": """
try:
    {code}
except Exception as e:
    logger.error(f"Error in {function_name}: {e}")
    raise
""",
        "function_docstring": '''
def {function_name}({params}):
    """
    {description}
    
    Args:
        {args_doc}
    
    Returns:
        {return_doc}
    """
    {code}
''',
        "class_template": '''
class {class_name}({base_classes}):
    """{description}"""
    
    def __init__(self{init_params}):
        {init_body}
    
    def __str__(self):
        return f"{class_name}({str_content})"
''',
    },
    "javascript": {
        "error_handling": """
try {
    {code}
} catch (error) {
    console.error('Error:', error);
    throw error;
}
""",
        "async_function": """
async function {function_name}({params}) {
    try {
        {code}
    } catch (error) {
        console.error('Error in {function_name}:', error);
        throw error;
    }
}
""",
        "class_template": """
class {class_name} {
    constructor({params}) {
        {init_code}
    }
    
    {methods}
}
""",
    }
}
