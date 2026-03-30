"""
Permission System for Cortex AI Agent
Fine-grained access control with schema validation
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal
from src.utils.logger import get_logger

log = get_logger("permission_system")


class PermissionLevel(Enum):
    """Permission levels for operations."""
    DENY = "deny"           # Operation not allowed
    ASK = "ask"             # Ask user for confirmation
    ALLOW = "allow"         # Allow without confirmation


class ToolCategory(Enum):
    """Categories of tools."""
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_EDIT = "file_edit"
    BASH = "bash"
    WEB = "web"
    SEARCH = "search"
    SYSTEM = "system"


@dataclass
class PermissionRule:
    """A permission rule for a tool or operation."""
    tool_name: str
    level: PermissionLevel
    conditions: Dict[str, Any] = None  # e.g., {"path_prefix": "/safe/"}
    description: str = ""


@dataclass
class ToolArity:
    """Defines expected parameter count for a tool."""
    tool_name: str
    min_params: int
    max_params: int
    required_params: List[str]
    optional_params: List[str]


class PermissionSchema:
    """
    Schema-based permission validation.
    
    Defines what operations are allowed based on:
    - Tool name
    - Parameter patterns
    - Path restrictions
    """
    
    def __init__(self):
        self.rules: Dict[str, PermissionRule] = {}
        self.arity_rules: Dict[str, ToolArity] = {}
        self._init_default_rules()
        log.info("PermissionSchema initialized")
    
    def _init_default_rules(self):
        """Initialize default permission rules."""
        # File operations
        self.add_rule(PermissionRule(
            tool_name="read_file",
            level=PermissionLevel.ALLOW,
            description="Reading files is generally safe"
        ))
        
        self.add_rule(PermissionRule(
            tool_name="write_file",
            level=PermissionLevel.ASK,
            description="Writing files can be destructive"
        ))
        
        self.add_rule(PermissionRule(
            tool_name="edit_file",
            level=PermissionLevel.ASK,
            description="Editing files can be destructive"
        ))
        
        # Bash commands
        self.add_rule(PermissionRule(
            tool_name="bash",
            level=PermissionLevel.ASK,
            conditions={"dangerous_commands": ["rm", "sudo", "chmod", "chown"]},
            description="Shell commands can be dangerous"
        ))
        
        # Web operations
        self.add_rule(PermissionRule(
            tool_name="webfetch",
            level=PermissionLevel.ALLOW,
            description="Fetching web content is generally safe"
        ))
        
        # Search operations
        self.add_rule(PermissionRule(
            tool_name="grep",
            level=PermissionLevel.ALLOW,
            description="Searching code is safe"
        ))
        
        # Initialize arity rules
        self._init_arity_rules()
    
    def _init_arity_rules(self):
        """Initialize tool arity (parameter count) rules."""
        self.arity_rules["read_file"] = ToolArity(
            tool_name="read_file",
            min_params=1,
            max_params=3,
            required_params=["path"],
            optional_params=["start_line", "end_line"]
        )
        
        self.arity_rules["write_file"] = ToolArity(
            tool_name="write_file",
            min_params=2,
            max_params=2,
            required_params=["path", "content"],
            optional_params=[]
        )
        
        self.arity_rules["edit_file"] = ToolArity(
            tool_name="edit_file",
            min_params=3,
            max_params=3,
            required_params=["path", "old_string", "new_string"],
            optional_params=[]
        )
        
        self.arity_rules["bash"] = ToolArity(
            tool_name="bash",
            min_params=1,
            max_params=2,
            required_params=["command"],
            optional_params=["timeout"]
        )
        
        self.arity_rules["grep"] = ToolArity(
            tool_name="grep",
            min_params=1,
            max_params=3,
            required_params=["pattern"],
            optional_params=["include", "path"]
        )
    
    def add_rule(self, rule: PermissionRule):
        """Add a permission rule."""
        self.rules[rule.tool_name] = rule
        log.debug(f"Added permission rule for {rule.tool_name}: {rule.level.value}")
    
    def get_rule(self, tool_name: str) -> Optional[PermissionRule]:
        """Get permission rule for a tool."""
        return self.rules.get(tool_name)
    
    def check_permission(self, tool_name: str, params: Dict = None) -> PermissionLevel:
        """
        Check permission level for a tool operation.
        
        Args:
            tool_name: Name of the tool
            params: Tool parameters (for conditional checks)
            
        Returns:
            PermissionLevel
        """
        rule = self.get_rule(tool_name)
        if not rule:
            log.warning(f"No permission rule for {tool_name}, defaulting to ASK")
            return PermissionLevel.ASK
        
        # Check conditions if present
        if rule.conditions and params:
            # Check for dangerous bash commands
            if tool_name == "bash" and "command" in params:
                command = params["command"]
                dangerous = rule.conditions.get("dangerous_commands", [])
                for cmd in dangerous:
                    if cmd in command:
                        log.warning(f"Dangerous command detected: {cmd}")
                        return PermissionLevel.ASK
            
            # Check path restrictions
            if "path" in params and "path_prefix" in rule.conditions:
                if not params["path"].startswith(rule.conditions["path_prefix"]):
                    return PermissionLevel.ASK
        
        return rule.level
    
    def validate_arity(self, tool_name: str, params: Dict) -> tuple[bool, str]:
        """
        Validate parameter count (arity) for a tool.
        
        Args:
            tool_name: Name of the tool
            params: Parameters being passed
            
        Returns:
            (is_valid, error_message)
        """
        arity = self.arity_rules.get(tool_name)
        if not arity:
            # No arity rule defined, allow
            return True, ""
        
        param_count = len(params)
        
        # Check min/max
        if param_count < arity.min_params:
            return False, f"{tool_name} requires at least {arity.min_params} parameters, got {param_count}"
        
        if param_count > arity.max_params:
            return False, f"{tool_name} accepts at most {arity.max_params} parameters, got {param_count}"
        
        # Check required params
        for required in arity.required_params:
            if required not in params:
                return False, f"{tool_name} requires parameter: {required}"
        
        return True, ""


class PermissionEvaluator(QObject):
    """
    Evaluates permissions for AI agent operations.
    
    Signals:
        permission_required: Emitted when user confirmation needed
        permission_granted: Emitted when permission granted
        permission_denied: Emitted when permission denied
    """
    
    permission_required = pyqtSignal(str, str, dict)  # tool_name, description, params
    permission_granted = pyqtSignal(str)  # tool_name
    permission_denied = pyqtSignal(str, str)  # tool_name, reason
    
    def __init__(self):
        super().__init__()
        self.schema = PermissionSchema()
        self._permission_cache: Dict[str, bool] = {}  # Cache user decisions
        log.info("PermissionEvaluator initialized")
    
    def evaluate(self, tool_name: str, params: Dict = None, 
                 description: str = "") -> tuple[bool, str]:
        """
        Evaluate whether an operation should proceed.
        
        Args:
            tool_name: Name of the tool
            params: Tool parameters
            description: Description of the operation
            
        Returns:
            (should_proceed, reason)
        """
        # First check arity
        is_valid, error_msg = self.schema.validate_arity(tool_name, params or {})
        if not is_valid:
            log.warning(f"Arity validation failed: {error_msg}")
            return False, error_msg
        
        # Check permission level
        level = self.schema.check_permission(tool_name, params)
        
        if level == PermissionLevel.DENY:
            reason = f"Operation '{tool_name}' is not allowed"
            log.warning(reason)
            self.permission_denied.emit(tool_name, reason)
            return False, reason
        
        if level == PermissionLevel.ASK:
            # Check cache first
            cache_key = f"{tool_name}:{hash(str(params))}"
            if cache_key in self._permission_cache:
                if self._permission_cache[cache_key]:
                    return True, "Permission cached"
                else:
                    return False, "Permission denied (cached)"
            
            # Emit signal for UI to handle
            desc = description or self._get_default_description(tool_name)
            self.permission_required.emit(tool_name, desc, params or {})
            
            # Return False for now - actual permission handled async
            return False, "Waiting for user confirmation"
        
        # ALLOW
        self.permission_granted.emit(tool_name)
        return True, "Permission granted"
    
    def grant_permission(self, tool_name: str, params: Dict = None, 
                        remember: bool = False):
        """Grant permission for an operation."""
        if remember and params:
            cache_key = f"{tool_name}:{hash(str(params))}"
            self._permission_cache[cache_key] = True
        
        self.permission_granted.emit(tool_name)
        log.info(f"Permission granted for {tool_name}")
    
    def deny_permission(self, tool_name: str, params: Dict = None,
                       remember: bool = False):
        """Deny permission for an operation."""
        if remember and params:
            cache_key = f"{tool_name}:{hash(str(params))}"
            self._permission_cache[cache_key] = False
        
        reason = f"Permission denied by user"
        self.permission_denied.emit(tool_name, reason)
        log.info(f"Permission denied for {tool_name}")
    
    def _get_default_description(self, tool_name: str) -> str:
        """Get default description for a tool."""
        descriptions = {
            "write_file": "Create or overwrite a file",
            "edit_file": "Modify existing file content",
            "bash": "Execute shell command",
            "webfetch": "Fetch content from URL",
        }
        return descriptions.get(tool_name, f"Execute {tool_name}")
    
    def clear_cache(self):
        """Clear permission cache."""
        self._permission_cache.clear()
        log.info("Permission cache cleared")
    
    def add_custom_rule(self, tool_name: str, level: PermissionLevel, 
                       conditions: Dict = None):
        """Add a custom permission rule at runtime."""
        rule = PermissionRule(
            tool_name=tool_name,
            level=level,
            conditions=conditions
        )
        self.schema.add_rule(rule)
        log.info(f"Added custom rule for {tool_name}: {level.value}")


# Global instance
_permission_evaluator: Optional[PermissionEvaluator] = None


def get_permission_evaluator() -> PermissionEvaluator:
    """Get global PermissionEvaluator instance."""
    global _permission_evaluator
    if _permission_evaluator is None:
        _permission_evaluator = PermissionEvaluator()
    return _permission_evaluator
