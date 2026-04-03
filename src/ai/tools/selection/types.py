"""
Tool Selection Types for Cortex AI Agent
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


class ToolCategory(Enum):
    """Categories of tools available."""
    FILE = "file"
    SEARCH = "search"
    SYSTEM = "system"
    WEB = "web"
    INTERACTION = "interaction"


@dataclass
class ToolDefinition:
    """Definition of a tool."""
    name: str
    description: str
    category: ToolCategory
    keywords: List[str] = field(default_factory=list)
    required_permissions: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    estimated_time_ms: int = 1000
    complexity: str = "simple"  # simple, medium, complex


@dataclass
class ToolScore:
    """Score for a tool selection."""
    tool: ToolDefinition
    score: float
    reasoning: str
    estimated_complexity: str
    confidence: float


@dataclass
class ToolSelection:
    """Selected tool with execution context."""
    tool: ToolDefinition
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1
    dependencies: List[str] = field(default_factory=list)


@dataclass
class ExecutionHistory:
    """History of tool execution for learning."""
    tool_name: str
    intent: str
    success: bool
    execution_time_ms: int
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSelectionContext:
    """Context for tool selection."""
    workspace_path: Optional[str] = None
    active_file: Optional[str] = None
    open_files: List[str] = field(default_factory=list)
    has_open_files: bool = False
    search_patterns: List[str] = field(default_factory=list)
    workspace_type: str = "general"  # python, nodejs, rust, etc.
    available_tools: List[str] = field(default_factory=list)
    previous_commands: List[str] = field(default_factory=list)
    os_type: str = "windows"  # windows, linux, macos
