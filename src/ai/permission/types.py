"""
Permission System Types for Cortex AI Agent
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


class PermissionType(Enum):
    """Types of permissions that can be requested."""
    TERMINAL = "terminal"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    ENV = "env"
    PLUGINS = "plugins"


class PermissionScope(Enum):
    """Scope of permission grant."""
    SESSION = "session"      # Valid for current session only
    WORKSPACE = "workspace"  # Valid for current project/workspace
    GLOBAL = "global"        # Valid permanently


class PermissionStatus(Enum):
    """Status of a permission request."""
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    EXPIRED = "expired"


class CommandSafety(Enum):
    """Safety level of a command."""
    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"


@dataclass
class PermissionRequest:
    """A request for permission."""
    id: str
    tool: str
    permission_type: PermissionType
    requested_access: List[str]
    session_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    status: PermissionStatus = PermissionStatus.PENDING
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionGrant:
    """A granted permission."""
    tool: str
    permission_type: PermissionType
    access: List[str]
    scope: PermissionScope
    session_id: str
    granted_at: datetime = field(default_factory=datetime.now)
    expires: Optional[datetime] = None
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_valid(self) -> bool:
        """Check if permission is still valid."""
        if self.expires is None:
            return True
        return datetime.now() < self.expires
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tool": self.tool,
            "permission_type": self.permission_type.value,
            "access": self.access,
            "scope": self.scope.value,
            "session_id": self.session_id,
            "granted_at": self.granted_at.isoformat(),
            "expires": self.expires.isoformat() if self.expires else None,
        }


@dataclass
class PermissionCardData:
    """Data for rendering a permission card in UI."""
    request_id: str
    tool: str
    permission_type: PermissionType
    requested_access: List[str]
    title: str
    description: str
    risks: List[str]
    safeguards: List[str]
    default_scope: PermissionScope = PermissionScope.SESSION
    auto_expire: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for UI."""
        return {
            "request_id": self.request_id,
            "tool": self.tool,
            "permission_type": self.permission_type.value,
            "requested_access": self.requested_access,
            "title": self.title,
            "description": self.description,
            "risks": self.risks,
            "safeguards": self.safeguards,
            "default_scope": self.default_scope.value,
            "auto_expire": self.auto_expire,
        }


@dataclass
class PermissionCheckResult:
    """Result of a permission check."""
    granted: bool
    permission: Optional[PermissionGrant] = None
    reason: Optional[str] = None
    required_access: Optional[List[str]] = None
    existing_access: Optional[List[str]] = None
    request_id: Optional[str] = None


@dataclass
class CommandAnalysis:
    """Analysis of a command for safety."""
    command: str
    safety: CommandSafety
    patterns_detected: List[str] = field(default_factory=list)
    requires_confirmation: bool = False
    explanation: str = ""


# Permission type configurations for UI cards
PERMISSION_CARD_CONFIGS = {
    PermissionType.TERMINAL: {
        "title": "Terminal Access Requested",
        "description": "This tool wants to run commands in your terminal",
        "risks": [
            "Can execute arbitrary commands",
            "Can modify files and directories",
            "Can access environment variables",
            "Can install packages",
        ],
        "safeguards": [
            "Commands run in sandboxed environment",
            "Limited to workspace directory by default",
            "Command preview before execution",
            "Session-scoped permissions",
        ],
    },
    PermissionType.FILESYSTEM: {
        "title": "File System Access",
        "description": "This tool wants to read/write files",
        "risks": [
            "Can read sensitive files",
            "Can overwrite existing files",
            "Can delete files",
        ],
        "safeguards": [
            "Restricted to workspace",
            "Read-only by default",
            "Backup before destructive operations",
        ],
    },
    PermissionType.NETWORK: {
        "title": "Network Access",
        "description": "This tool wants to access the internet",
        "risks": [
            "Can download content from web",
            "Can send data to external services",
        ],
        "safeguards": [
            "HTTPS only",
            "Timeout protection",
            "Domain whitelist available",
        ],
    },
    PermissionType.ENV: {
        "title": "Environment Variable Access",
        "description": "This tool wants to access environment variables",
        "risks": [
            "Can read sensitive credentials",
            "Can modify environment",
        ],
        "safeguards": [
            "Only safe variables exposed by default",
            "Explicit permission for sensitive vars",
        ],
    },
    PermissionType.PLUGINS: {
        "title": "Plugin Access",
        "description": "This tool wants to use plugins",
        "risks": [
            "Can execute third-party code",
        ],
        "safeguards": [
            "Plugin sandboxing",
            "Code review recommended",
        ],
    },
}


# Dangerous command patterns
DANGEROUS_PATTERNS = [
    (r'rm\s+-rf', 'Recursive force delete'),
    (r'rm\s+.*-f', 'Force delete'),
    (r'rm\s+.*\*', 'Wildcard delete'),
    (r'rm\s+.*\.', 'Delete current directory'),
    (r':\{\s*:\|:&\s*\};:', 'Fork bomb'),
    (r'mv\s+.*\/dev\/null', 'Move to null device'),
    (r'dd\s+.*if=.*of=', 'Direct disk write'),
    (r'chmod\s+.*\/.+', 'Change permissions recursively'),
    (r'chown\s+.*root.*\/.+', 'Change ownership to root'),
    (r'wget\s+.*\|\s*sh', 'Download and execute script'),
    (r'curl\s+.*\|\s*sh', 'Download and execute script'),
    (r'sudo\s+.*(rm|mv|chmod|chown|dd)', 'Destructive sudo command'),
]


# Warning command patterns
WARNING_PATTERNS = [
    (r'rm\s+.*[^\s]', 'File deletion'),
    (r'mv\s+.*[^\s]', 'File move'),
    (r'cp\s+.*[^\s]', 'File copy'),
    (r'find\s+.*-delete', 'Find and delete'),
    (r'find\s+.*-exec\s+.*rm', 'Find and remove'),
    (r'git\s+.*--hard', 'Git hard reset'),
    (r'git\s+.*-f', 'Git force operation'),
]


# Safe command whitelist
SAFE_COMMANDS = [
    'ls', 'cat', 'head', 'tail', 'grep', 'find', 'wc', 'stat',
    'pwd', 'cd', 'mkdir', 'rmdir',
    'git', 'npm', 'yarn', 'pnpm', 'bun',
    'make', 'cmake', 'gcc', 'g++', 'rustc', 'cargo',
    'ps', 'kill', 'echo', 'printf',
    'python', 'python3', 'pip', 'node',
]
