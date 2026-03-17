"""
Multi-Agent System for Cortex AI Agent IDE
Different AI personalities/agents for different tasks
"""

from enum import Enum, auto
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


class AgentType(Enum):
    """Different types of AI agents for different tasks."""
    BUILD = "build"      # Full access - can edit files, run commands
    PLAN = "plan"        # Read-only - analysis and suggestions only
    DEBUG = "debug"      # Debug specialist
    REVIEW = "review"    # Code review specialist
    GENERAL = "general"  # General questions and help


@dataclass
class AgentCapabilities:
    """Defines what an agent can do."""
    can_edit_files: bool = True
    can_run_commands: bool = True
    can_access_terminal: bool = True
    can_access_git: bool = True
    read_only: bool = False
    max_context_tokens: int = 8000
    allowed_tools: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.allowed_tools is None:
            self.allowed_tools = []


class BaseAgent:
    """Base class for all agents."""
    
    def __init__(self, agent_type: AgentType, capabilities: AgentCapabilities):
        self.agent_type = agent_type
        self.capabilities = capabilities
        self.system_prompt = self._get_system_prompt()
        
    def _get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        return "You are a helpful AI assistant."
        
    def get_full_prompt(self, user_message: str, context: Dict[str, str]) -> str:
        """Build the complete prompt with system message and context."""
        sections = [self.system_prompt]
        
        # Add capability restrictions
        if self.capabilities.read_only:
            sections.append("\n⚠️ READ-ONLY MODE: You can analyze and suggest but cannot make direct changes.")
        
        # Add context sections
        for section_name, section_content in context.items():
            if section_content:
                sections.append(f"\n## {section_name.upper().replace('_', ' ')}\n{section_content}")
        
        # Add user message
        sections.append(f"\n## User Request\n{user_message}")
        
        return "\n".join(sections)


class BuildAgent(BaseAgent):
    """Full-access development agent - can do everything."""
    
    def __init__(self):
        capabilities = AgentCapabilities(
            can_edit_files=True,
            can_run_commands=True,
            can_access_terminal=True,
            can_access_git=True,
            read_only=False,
            max_context_tokens=8000,
            allowed_tools=["read_file", "write_file", "edit_file", "run_command", "git_status", "search_code", "apply_patch"]
        )
        super().__init__(AgentType.BUILD, capabilities)
        
    def _get_system_prompt(self) -> str:
        return """You are the CORTEX BUILD AGENT - a full-access development specialist.
You operate with the authority to modify the codebase and execute commands to achieve project goals.

CORE DIRECTIVES:
1. [AUTONOMY]: Take initiative in refactoring and project scaffolding.
2. [SAFETY]: Adhere strictly to CORTEX safety protocols; no malicious/illegal code generation.
3. [QUALITY]: Write production-ready, testable, and well-documented code.
4. [TRANSPARENCY]: Explain architectural decisions and show clear diffs for changes.

Focus on: Multi-file refactoring, project generation, and tool-use chaining."""


class PlanAgent(BaseAgent):
    """Read-only analysis agent - for planning and analysis."""
    
    def __init__(self):
        capabilities = AgentCapabilities(
            can_edit_files=False,
            can_run_commands=False,
            can_access_terminal=False,
            can_access_git=True,
            read_only=True,
            max_context_tokens=8000,
            allowed_tools=["read_file", "git_status", "search_code"]
        )
        super().__init__(AgentType.PLAN, capabilities)
        
    def _get_system_prompt(self) -> str:
        return """You are the CORTEX PLANNER AGENT - a high-level architecture and analysis specialist.
You operate in READ-ONLY mode to design systems and project roadmaps without direct state mutation.

CORE DIRECTIVES:
1. [PLANNING]: Design folder structures, API contracts, and tech stacks first.
2. [SCAFFOLDING]: Generate comprehensive project specifications and implementation plans.
3. [ANALYSIS]: identify technical debt, security bottlenecks, and architectural flaws.
4. [SAFETY REVIEW]: Proactively flag ethical or security risks in user requests.

Focus on: Architecture design, dependency planning, and sequential implementation workflows."""


class DebugAgent(BaseAgent):
    """Debug specialist - focused on fixing bugs and issues."""
    
    def __init__(self):
        capabilities = AgentCapabilities(
            can_edit_files=True,
            can_run_commands=True,
            can_access_terminal=True,
            can_access_git=False,
            read_only=False,
            max_context_tokens=8000,
            allowed_tools=["read_file", "write_file", "run_command", "search_code"]
        )
        super().__init__(AgentType.DEBUG, capabilities)
        
    def _get_system_prompt(self) -> str:
        return """You are the CORTEX DEBUG SPECIALIST - an expert in error recovery and self-correction.
You focus on stabilizing the environment and fixing regressions.

CORE DIRECTIVES:
1. [ROOT CAUSE]: Use stack traces and terminal output to identify the exact point of failure.
2. [INCREMENTAL FIXING]: Apply small, testable changes to isolate bugs.
3. [RECOVERY]: Suggest rollback plans if a fix causes side effects.
4. [VALIDATION]: Always propose a verification command or test case to confirm the fix.

Focus on: Stack trace analysis, troubleshooting async/race conditions, and automated bug fixing."""


class ReviewAgent(BaseAgent):
    """Code review specialist - reviews code for quality."""
    
    def __init__(self):
        capabilities = AgentCapabilities(
            can_edit_files=False,
            can_run_commands=False,
            can_access_terminal=False,
            can_access_git=True,
            read_only=True,
            max_context_tokens=8000,
            allowed_tools=["read_file", "git_status", "search_code"]
        )
        super().__init__(AgentType.REVIEW, capabilities)
        
    def _get_system_prompt(self) -> str:
        return """You are the CORTEX REVIEW SPECIALIST - a guardian of code quality and security.
You perform rigorous code audits to ensure compliance with industry standards.

CORE DIRECTIVES:
1. [VULNERABILITY SCAN]: Identify potential security leaks, hardcoded secrets, and injection points.
2. [OPTIMIZATION]: Suggest performance improvements and resource usage reductions.
3. [MAINTAINABILITY]: enforce clean code principles, DRY, and SOLID patterns.
4. [ETHICS AUDIT]: Evaluate if the code aligns with CORTEX safety and ethical guidelines.

Focus on: Security auditing, performance benchmarking, and architectural review."""


class GeneralAgent(BaseAgent):
    """General purpose agent for questions and help."""
    
    def __init__(self):
        capabilities = AgentCapabilities(
            can_edit_files=False,
            can_run_commands=False,
            can_access_terminal=False,
            can_access_git=False,
            read_only=True,
            max_context_tokens=4000,
            allowed_tools=["search_code"]
        )
        super().__init__(AgentType.GENERAL, capabilities)
        
    def _get_system_prompt(self) -> str:
        return """You are the CORTEX KNOWLEDGE ASSISTANT - an educational guide for programming and IDE mastery.
You provide high-level conceptual help without direct environment mutation.

CORE DIRECTIVES:
1. [EDUCATION]: Focus on explaining concepts, design patterns, and "how things work".
2. [GUIDANCE]: Suggest best practices and provide alternative implementation strategies.
3. [IDE HELP]: Assist with Cortex IDE features, keyboard shortcuts, and configurations.
4. [SAFETY ADVISORY]: Educate users on the safety implications of their requests.

Focus on: Programming fundamentals, architectural theory, and IDE documentation."""


class AgentOrchestrator:
    """Manages agents and routes messages to appropriate agent."""
    
    def __init__(self):
        self.agents: Dict[AgentType, BaseAgent] = {
            AgentType.BUILD: BuildAgent(),
            AgentType.PLAN: PlanAgent(),
            AgentType.DEBUG: DebugAgent(),
            AgentType.REVIEW: ReviewAgent(),
            AgentType.GENERAL: GeneralAgent(),
        }
        self.current_agent = AgentType.BUILD
        
    def get_agent(self, agent_type: Optional[AgentType] = None) -> BaseAgent:
        """Get an agent by type."""
        if agent_type is None:
            agent_type = self.current_agent
        return self.agents.get(agent_type, self.agents[AgentType.BUILD])
        
    def set_agent(self, agent_type: AgentType):
        """Set the current agent."""
        self.current_agent = agent_type
        
    def detect_intent(self, message: str) -> AgentType:
        """Detect which agent should handle this message."""
        message_lower = message.lower()
        
        # Debug-related keywords
        debug_keywords = ["debug", "fix", "error", "bug", "exception", "crash", "traceback", 
                         "not working", "broken", "fails", "failure"]
        if any(keyword in message_lower for keyword in debug_keywords):
            return AgentType.DEBUG
            
        # Review-related keywords
        review_keywords = ["review", "check", "analyze code", "code review", "look at", 
                          "improve", "optimize", "refactor"]
        if any(keyword in message_lower for keyword in review_keywords):
            return AgentType.REVIEW
            
        # Plan-related keywords
        plan_keywords = ["plan", "architecture", "design", "how should i", "approach", 
                        "strategy", "structure", "organize"]
        if any(keyword in message_lower for keyword in plan_keywords):
            return AgentType.PLAN
            
        # General question keywords
        question_keywords = ["what is", "how to", "explain", "what are", "difference between",
                            "why", "when to", "best practice"]
        if any(keyword in message_lower for keyword in question_keywords):
            return AgentType.GENERAL
            
        # Default to BUILD agent
        return AgentType.BUILD
        
    def get_agent_descriptions(self) -> Dict[str, str]:
        """Get descriptions of all agents for UI."""
        return {
            "build": "🏗️ Build - Full development access",
            "plan": "📋 Plan - Read-only analysis",
            "debug": "🐛 Debug - Fix bugs and issues", 
            "review": "👀 Review - Code quality review",
            "general": "❓ General - Questions and help"
        }
