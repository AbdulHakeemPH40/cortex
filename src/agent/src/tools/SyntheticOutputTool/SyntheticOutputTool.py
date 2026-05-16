"""
Python conversion of SyntheticOutputTool.ts

Structured Output Tool for returning validated JSON output.
- JSON Schema validation using jsonschema
- WeakKeyDictionary caching for performance
- Non-interactive session support
- Minimal UI for SDK/AI agent use
"""

from typing import Any, Dict, Union, Optional, Callable
from dataclasses import dataclass, field
import weakref

# ============================================================================
# Defensive Imports
# ============================================================================

try:
    from jsonschema import validate, ValidationError, Draft7Validator
    from jsonschema.exceptions import best_match
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    ValidationError = Exception
    Draft7Validator = None
    def best_match(errors): return None

try:
    from utils.errors import TelemetrySafeError
except ImportError:
    class TelemetrySafeError(Exception):
        """Telemetry-safe error with sanitized message."""
        def __init__(self, message: str, telemetry_message: str):
            super().__init__(message)
            self.telemetry_message = telemetry_message

try:
    from utils.slow_operations import json_stringify
except ImportError:
    import json
    def json_stringify(obj: Any) -> str:
        """JSON stringify with fallback."""
        try:
            return json.dumps(obj, separators=(',', ':'))
        except (TypeError, ValueError):
            return str(obj)


# ============================================================================
# Constants
# ============================================================================

SYNTHETIC_OUTPUT_TOOL_NAME = 'StructuredOutput'
MAX_RESULT_SIZE_CHARS = 100_000


# ============================================================================
# Type Definitions
# ============================================================================

@dataclass
class ToolResult:
    """Result from tool execution."""
    data: str
    structured_output: Dict[str, Any]


@dataclass
class PermissionResult:
    """Permission check result."""
    behavior: str  # 'allow' | 'deny'
    updated_input: Dict[str, Any]


@dataclass
class ToolDef:
    """Tool definition structure."""
    name: str
    description: str
    prompt: str
    search_hint: str
    max_result_size_chars: int
    is_enabled: Callable[[], bool] = field(default=lambda: True)
    is_concurrency_safe: Callable[[], bool] = field(default=lambda: True)
    is_read_only: Callable[[], bool] = field(default=lambda: True)
    is_open_world: Callable[[], bool] = field(default=lambda: False)
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    call: Optional[Callable[..., Any]] = None
    check_permissions: Optional[Callable[..., PermissionResult]] = None
    render_tool_use_message: Optional[Callable[..., Optional[str]]] = None
    render_tool_use_rejected_message: Optional[Callable[..., str]] = None
    render_tool_use_error_message: Optional[Callable[..., str]] = None
    render_tool_use_progress_message: Optional[Callable[..., Optional[str]]] = None
    render_tool_result_message: Optional[Callable[..., str]] = None
    map_tool_result_to_block_param: Optional[Callable[..., Dict[str, Any]]] = None


# ============================================================================
# Input/Output Schemas (Lazy Evaluation)
# ============================================================================

def get_input_schema() -> Dict[str, Any]:
    """
    Get input schema - allows any object since schema is provided dynamically.
    Returns a permissive JSON Schema that accepts any object.
    """
    return {
        'type': 'object',
        'additionalProperties': True,
    }


def get_output_schema() -> Dict[str, Any]:
    """Get output schema - returns string description."""
    return {
        'type': 'string',
        'description': 'Structured output tool result',
    }


# ============================================================================
# Tool Properties
# ============================================================================

def is_synthetic_output_tool_enabled(is_non_interactive_session: bool) -> bool:
    """
    Check if SyntheticOutputTool should be enabled.
    Only enabled for non-interactive sessions (SDK/AI agent workflows).
    """
    return is_non_interactive_session


# ============================================================================
# UI Rendering Functions
# ============================================================================

def render_tool_use_message(input_data: Dict[str, Any]) -> Optional[str]:
    """
    Render a compact display of the structured output input.
    Shows key fields or count for large outputs.
    """
    keys = list(input_data.keys())
    if len(keys) == 0:
        return None
    if len(keys) <= 3:
        return ', '.join(f"{k}: {json_stringify(input_data[k])}" for k in keys)
    return f"{len(keys)} fields: {', '.join(keys[:3])}\u2026"


def render_tool_use_rejected_message() -> str:
    """Render message when structured output is rejected."""
    return 'Structured output rejected'


def render_tool_use_error_message() -> str:
    """Render message when structured output has an error."""
    return 'Structured output error'


def render_tool_use_progress_message() -> Optional[str]:
    """Render progress message (none for this tool)."""
    return None


def render_tool_result_message(output: str) -> str:
    """Render the tool result message."""
    return output


def map_tool_result_to_block_param(content: str, tool_use_id: str) -> Dict[str, Any]:
    """Map tool result to block parameter format."""
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': content,
    }


# ============================================================================
# Permission Check
# ============================================================================

def check_permissions(input_data: Dict[str, Any]) -> PermissionResult:
    """
    Check permissions for the tool.
    Always allows - this tool just returns data with no side effects.
    """
    return PermissionResult(
        behavior='allow',
        updated_input=input_data,
    )


# ============================================================================
# Base Tool Call
# ============================================================================

def base_call(input_data: Dict[str, Any]) -> ToolResult:
    """
    Base tool call implementation.
    Just validates and returns the input as structured output.
    """
    return ToolResult(
        data='Structured output provided successfully',
        structured_output=input_data,
    )


# ============================================================================
# Synthetic Output Tool Definition
# ============================================================================

SyntheticOutputTool = ToolDef(
    name=SYNTHETIC_OUTPUT_TOOL_NAME,
    description='Return structured output in the requested format',
    prompt='''Use this tool to return your final response in the requested structured format. You MUST call this tool exactly once at the end of your response to provide the structured output.''',
    search_hint='return the final response as structured JSON',
    max_result_size_chars=MAX_RESULT_SIZE_CHARS,
    is_enabled=lambda: True,  # Always enabled once created
    is_concurrency_safe=lambda: True,
    is_read_only=lambda: True,
    is_open_world=lambda: False,
    input_schema=get_input_schema(),
    output_schema=get_output_schema(),
    call=base_call,
    check_permissions=check_permissions,
    render_tool_use_message=render_tool_use_message,
    render_tool_use_rejected_message=render_tool_use_rejected_message,
    render_tool_use_error_message=render_tool_use_error_message,
    render_tool_use_progress_message=render_tool_use_progress_message,
    render_tool_result_message=render_tool_result_message,
    map_tool_result_to_block_param=map_tool_result_to_block_param,
)


# ============================================================================
# Schema Validation and Tool Creation
# ============================================================================

# Workflow scripts call agent({schema: BUGS_SCHEMA}) 30-80 times per run with
# the same schema object reference. Without caching, each call does
# new Validator() + validate() (~1.4ms overhead). Identity cache brings
# 80-call workflows from ~110ms to ~4ms validation overhead.
# 
# NOTE: Python's WeakKeyDictionary cannot use plain dicts as keys.
# We use id() based caching with a regular dict and manual cleanup.
_tool_cache: Dict[int, CreateResult] = {}
_tool_cache_refs: Dict[int, Any] = {}


@dataclass
class CreateResult:
    """Result from creating a synthetic output tool."""
    tool: Optional[ToolDef] = None
    error: Optional[str] = None


def _format_validation_errors(errors: list) -> str:
    """Format validation errors into a readable string."""
    if not errors:
        return 'Unknown validation error'
    
    formatted = []
    for error in errors:
        path = error.get('path', 'root')
        message = error.get('message', 'Invalid value')
        if isinstance(path, list):
            path = '/'.join(str(p) for p in path) or 'root'
        formatted.append(f"{path}: {message}")
    
    return ', '.join(formatted)


def create_synthetic_output_tool(json_schema: Dict[str, Any]) -> CreateResult:
    """
    Create a SyntheticOutputTool configured with the given JSON schema.
    
    Returns CreateResult with tool on success or error message on invalid schema.
    Uses id() based caching for performance with repeated schema usage.
    """
    # Use object id as cache key (same object reference = same id)
    schema_id = id(json_schema)
    
    # Check if we have this schema cached
    if schema_id in _tool_cache:
        # Verify it's the same object (not just same id reused)
        if _tool_cache_refs.get(schema_id) is json_schema:
            return _tool_cache[schema_id]
    
    result = _build_synthetic_output_tool(json_schema)
    _tool_cache[schema_id] = result
    _tool_cache_refs[schema_id] = json_schema
    return result


def _build_synthetic_output_tool(json_schema: Dict[str, Any]) -> CreateResult:
    """
    Build a synthetic output tool with schema validation.
    
    Validates the JSON schema and creates a tool that validates input against it.
    """
    if not HAS_JSONSCHEMA:
        return CreateResult(
            error='jsonschema library not available. Install with: pip install jsonschema'
        )
    
    try:
        # Validate the schema itself
        try:
            Draft7Validator.check_schema(json_schema)
        except Exception as e:
            return CreateResult(error=f"Invalid JSON Schema: {str(e)}")
        
        # Compile the validator
        validator = Draft7Validator(json_schema)
        
        # Create the tool with schema validation
        def validated_call(input_data: Dict[str, Any]) -> ToolResult:
            """Call with schema validation."""
            # Validate input against schema
            errors = list(validator.iter_errors(input_data))
            
            if errors:
                error_msg = _format_validation_errors([
                    {'path': list(e.path), 'message': e.message}
                    for e in errors
                ])
                raise TelemetrySafeError(
                    f"Output does not match required schema: {error_msg}",
                    f"StructuredOutput schema mismatch: {error_msg[:150]}",
                )
            
            return ToolResult(
                data='Structured output provided successfully',
                structured_output=input_data,
            )
        
        # Create tool with validation
        tool = ToolDef(
            name=SYNTHETIC_OUTPUT_TOOL_NAME,
            description='Return structured output in the requested format',
            prompt='''Use this tool to return your final response in the requested structured format. You MUST call this tool exactly once at the end of your response to provide the structured output.''',
            search_hint='return the final response as structured JSON',
            max_result_size_chars=MAX_RESULT_SIZE_CHARS,
            is_enabled=lambda: True,
            is_concurrency_safe=lambda: True,
            is_read_only=lambda: True,
            is_open_world=lambda: False,
            input_schema=json_schema,
            output_schema=get_output_schema(),
            call=validated_call,
            check_permissions=check_permissions,
            render_tool_use_message=render_tool_use_message,
            render_tool_use_rejected_message=render_tool_use_rejected_message,
            render_tool_use_error_message=render_tool_use_error_message,
            render_tool_use_progress_message=render_tool_use_progress_message,
            render_tool_result_message=render_tool_result_message,
            map_tool_result_to_block_param=map_tool_result_to_block_param,
        )
        
        return CreateResult(tool=tool)
        
    except Exception as e:
        return CreateResult(error=str(e))


# ============================================================================
# Convenience Functions
# ============================================================================

def get_tool() -> ToolDef:
    """Get the base SyntheticOutputTool definition."""
    return SyntheticOutputTool


def is_enabled_for_session(is_non_interactive: bool) -> bool:
    """Check if tool is enabled for the given session type."""
    return is_synthetic_output_tool_enabled(is_non_interactive)
