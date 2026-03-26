"""
Base Tool Interface for Cortex IDE
Industry-standard abstract base class for all tools.
Inspired by OpenCode's tool.ts architecture.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class ToolResult:
    """
    Standardized result from tool execution.
    
    Attributes:
        success: Whether the tool executed successfully
        result: The actual result data (content, output, etc.)
        error: Error message if success is False
        duration_ms: Execution time in milliseconds
        metadata: Additional context (file paths, line counts, etc.)
    """
    success: bool
    result: Any
    status: str = "completed"  # completed, pending, error
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'success': self.success,
            'result': self.result,
            'error': self.error,
            'duration_ms': self.duration_ms,
            'metadata': self.metadata or {}
        }


@dataclass
class ToolParameter:
    """
    Tool parameter definition.
    
    Attributes:
        name: Parameter name
        param_type: Type (string, integer, boolean, array, object)
        description: What the parameter does
        required: Whether it's mandatory
        default: Default value if not provided
    """
    name: str
    param_type: str
    description: str
    required: bool = True
    default: Any = None


class BaseTool(ABC):
    """
    Abstract base class for all tools.
    
    Every tool must implement:
    - name: Unique identifier
    - description: What it does
    - parameters: Parameter definitions
    - execute: Main logic
    
    Inspired by OpenCode's tool.ts pattern.
    """
    
    # Class attributes (override in subclasses)
    name: str = "base_tool"
    description: str = "Base tool class"
    parameters: List[ToolParameter] = []
    requires_confirmation: bool = False
    is_safe: bool = False  # Auto-approve if True
    
    # Instance attributes (set by registry)
    project_root: Optional[str] = None
    file_manager: Optional[Any] = None
    precise_editor: Optional[Any] = None
    terminal_widget: Optional[Any] = None
    
    @abstractmethod
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Execute the tool with given parameters.
        
        Args:
            params: Dictionary of parameter values
            
        Returns:
            ToolResult with success status and data
        """
        pass
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """
        Validate parameters before execution.
        
        Override this for custom validation logic.
        
        Args:
            params: Parameter values to validate
            
        Returns:
            (is_valid, error_message)
        """
        # Check required parameters
        for param in self.parameters:
            if param.required and param.name not in params:
                return False, f"Missing required parameter: {param.name}"
            
            # Type checking (basic)
            if param.name in params:
                value = params[param.name]
                expected_type = param.param_type
                
                if expected_type == "string" and not isinstance(value, str):
                    return False, f"Parameter '{param.name}' must be a string"
                elif expected_type == "integer" and not isinstance(value, int):
                    return False, f"Parameter '{param.name}' must be an integer"
                elif expected_type == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter '{param.name}' must be a boolean"
                elif expected_type == "array" and not isinstance(value, list):
                    return False, f"Parameter '{param.name}' must be an array"
        
        return True, "OK"
    
    def _resolve_path(self, path: str) -> Path:
        """
        Resolve path relative to project root.
        
        Utility method for file-based tools.
        
        Args:
            path: File path (relative or absolute)
            
        Returns:
            Absolute Path object
        """
        p = Path(path)
        
        # If absolute, use as-is
        if p.is_absolute():
            return p
        
        # If project root set, resolve relative to it
        if self.project_root:
            return Path(self.project_root) / p
        
        # Fallback to current directory
        return Path.cwd() / path

    def _sync_file_cache(self, path: str, content: Optional[str] = None):
        """
        Update the global file manager cache with new content.
        If content is None, reads from disk.
        """
        if not self.file_manager:
            return
            
        try:
            resolved_path = self._resolve_path(path)
            if not resolved_path.exists():
                return
                
            abs_path = str(resolved_path.resolve())
            
            # Read from disk if not provided
            if content is None:
                content = resolved_path.read_text(encoding='utf-8', errors='replace')
            
            # Update cache if methods exist
            if hasattr(self.file_manager, '_file_cache'):
                self.file_manager._file_cache.put(abs_path, content)
                
                # Clear any range-specific caches for this file
                # Use list() to avoid dictionary changed size during iteration error
                keys_to_del = [k for k in list(self.file_manager._file_cache.cache.keys()) 
                              if k.startswith(abs_path + ":")]
                for k in keys_to_del:
                    del self.file_manager._file_cache.cache[k]
            
            if hasattr(self.file_manager, '_hash_cache'):
                self.file_manager._hash_cache[abs_path] = self.file_manager._compute_hash(content)
            
            if hasattr(self.file_manager, '_open_files'):
                self.file_manager._open_files[abs_path] = content
                
        except Exception as e:
            # Non-critical
            import logging
            logging.getLogger("BaseTool").debug(f"Cache sync failed for {path}: {e}")
    
    def get_description_for_ai(self) -> str:
        """
        Generate AI-readable tool description.
        
        Used in system prompts to tell AI what tools are available.
        
        Returns:
            Formatted description string
        """
        param_descriptions = []
        
        for param in self.parameters:
            req = "required" if param.required else "optional"
            default = f" (default: {param.default})" if param.default is not None else ""
            param_descriptions.append(
                f"  - {param.name} ({param.param_type}, {req}): {param.description}{default}"
            )
        
        return f"""
Tool: {self.name}
Description: {self.description}
Parameters:
{chr(10).join(param_descriptions)}
"""


# Convenience function for creating tool results
def success_result(result: Any, duration_ms: float = 0.0, metadata: Dict = None, status: str = "completed") -> ToolResult:
    """Create a successful tool result."""
    return ToolResult(
        success=True,
        result=result,
        status=status,
        duration_ms=duration_ms,
        metadata=metadata
    )


def error_result(error: str, duration_ms: float = 0.0) -> ToolResult:
    """Create an error tool result."""
    return ToolResult(
        success=False,
        result=None,
        status="error",
        error=error,
        duration_ms=duration_ms
    )


def pending_result(question: str, metadata: Dict = None) -> ToolResult:
    """Create a pending tool result (waiting for user input)."""
    return ToolResult(
        success=True,
        result=question,
        status="pending",
        metadata=metadata
    )
