"""
Agent Router for Cortex AI Agent
Routes user messages to appropriate specialized agents based on intent
"""

from typing import Dict, List, Optional, Any, Type
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from datetime import datetime

from src.ai.intent.types import (
    IntentType, SubIntent, AgentType, IntentClassification, AgentRoute
)
from src.ai.intent.classifier import get_intent_classifier
from src.utils.logger import get_logger

log = get_logger("agent_router")


@dataclass
class AgentContext:
    """Context for agent execution."""
    session_id: str
    workspace_path: Optional[str] = None
    active_file: Optional[str] = None
    open_files: List[str] = field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class for all agents."""
    
    def __init__(self, agent_type: AgentType, name: str, description: str):
        self.agent_type = agent_type
        self.name = name
        self.description = description
        self.capabilities: List[str] = []
        self.tools: List[str] = []
        
    @abstractmethod
    async def can_handle(self, intent: IntentClassification, context: AgentContext) -> float:
        """
        Check if this agent can handle the given intent.
        Returns confidence score (0.0 to 1.0).
        """
        pass
    
    @abstractmethod
    async def execute(
        self, 
        message: str, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[str, Any]:
        """
        Execute the agent's task.
        Returns execution result.
        """
        pass
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        return f"You are the {self.name} agent. {self.description}"


class GeneralAgent(BaseAgent):
    """General purpose agent for simple tasks and conversation."""
    
    def __init__(self):
        super().__init__(
            AgentType.GENERAL,
            "General",
            "Handles general conversation, questions, and simple tasks"
        )
        self.capabilities = [
            "conversation",
            "question_answering",
            "simple_explanations",
            "general_assistance"
        ]
        self.tools = ["read", "grep", "webfetch"]
    
    async def can_handle(self, intent: IntentClassification, context: AgentContext) -> float:
        if intent.primary_intent == IntentType.GENERAL_CONVERSATION:
            return 0.95
        elif intent.primary_intent == IntentType.QUESTION_ANSWERING:
            return 0.90
        elif intent.complexity == "simple":
            return 0.70
        return 0.30
    
    async def execute(
        self, 
        message: str, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[str, Any]:
        return {
            "agent": self.name,
            "type": "direct_response",
            "message": message,
            "suggested_tools": self.tools[:2]
        }


class BuildAgent(BaseAgent):
    """Agent for build, compilation, and package management tasks."""
    
    def __init__(self):
        super().__init__(
            AgentType.BUILD,
            "Build",
            "Handles compilation, building, testing, and package installation"
        )
        self.capabilities = [
            "compilation",
            "building",
            "testing",
            "package_installation",
            "dependency_management"
        ]
        self.tools = ["bash", "read", "write", "edit"]
    
    async def can_handle(self, intent: IntentClassification, context: AgentContext) -> float:
        if intent.primary_intent == IntentType.BUILD_PROCESS:
            return 0.95
        elif intent.primary_intent == IntentType.TERMINAL_COMMAND:
            if SubIntent.PACKAGE_INSTALL in intent.sub_intents:
                return 0.90
            return 0.75
        elif SubIntent.SIMPLE_COMMAND in intent.sub_intents:
            return 0.60
        return 0.20
    
    async def execute(
        self, 
        message: str, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[str, Any]:
        # Detect project type and build system
        project_type = self._detect_project_type(context.workspace_path)
        build_system = self._detect_build_system(project_type, context.workspace_path)
        
        return {
            "agent": self.name,
            "type": "build_task",
            "project_type": project_type,
            "build_system": build_system,
            "commands": self._generate_build_commands(build_system, message),
            "tools": self.tools
        }
    
    def _detect_project_type(self, workspace_path: Optional[str]) -> str:
        """Detect the project type based on files."""
        if not workspace_path:
            return "unknown"
        
        import os
        
        # Check for common project files
        indicators = {
            "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
            "nodejs": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
            "rust": ["Cargo.toml", "Cargo.lock"],
            "java": ["pom.xml", "build.gradle", "gradlew"],
            "go": ["go.mod", "go.sum"],
        }
        
        for project_type, files in indicators.items():
            for file in files:
                if os.path.exists(os.path.join(workspace_path, file)):
                    return project_type
        
        return "unknown"
    
    def _detect_build_system(self, project_type: str, workspace_path: Optional[str]) -> str:
        """Detect build system based on project type."""
        build_systems = {
            "python": "pip",
            "nodejs": "npm",
            "rust": "cargo",
            "java": "maven",
            "go": "go",
        }
        return build_systems.get(project_type, "make")
    
    def _generate_build_commands(self, build_system: str, request: str) -> List[str]:
        """Generate appropriate build commands."""
        commands = []
        
        # Base commands by build system
        base_commands = {
            "npm": ["npm install", "npm run build"],
            "yarn": ["yarn install", "yarn build"],
            "pip": ["pip install -r requirements.txt"],
            "cargo": ["cargo build"],
            "maven": ["mvn clean install"],
            "go": ["go build", "go test"],
            "make": ["make"],
        }
        
        base = base_commands.get(build_system, ["make"])
        
        # Adjust based on request
        if "clean" in request.lower():
            if build_system in ["npm", "yarn"]:
                commands.append(f"{build_system} run clean")
            elif build_system == "cargo":
                commands.append("cargo clean")
            elif build_system == "maven":
                commands.append("mvn clean")
        
        if "test" in request.lower():
            if build_system in ["npm", "yarn"]:
                commands.append(f"{build_system} test")
            elif build_system == "cargo":
                commands.append("cargo test")
            elif build_system == "go":
                commands.append("go test ./...")
        
        commands.extend(base)
        return commands


class PlanAgent(BaseAgent):
    """Agent for complex multi-step planning and task decomposition."""
    
    def __init__(self):
        super().__init__(
            AgentType.PLAN,
            "Plan",
            "Breaks down complex tasks into executable steps and creates execution plans"
        )
        self.capabilities = [
            "task_decomposition",
            "planning",
            "project_setup",
            "architecture_design",
            "multi_step_coordination"
        ]
        self.tools = ["read", "write", "edit", "bash", "grep"]
    
    async def can_handle(self, intent: IntentClassification, context: AgentContext) -> float:
        if intent.complexity == "multi_step":
            return 0.95
        elif SubIntent.MULTI_STEP in intent.sub_intents:
            return 0.90
        elif intent.complexity == "complex":
            return 0.85
        elif "plan" in intent.metadata.get("matched_patterns", []):
            return 0.80
        return 0.25
    
    async def execute(
        self, 
        message: str, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[str, Any]:
        # Estimate number of steps
        estimated_steps = self._estimate_steps(message, intent)
        
        return {
            "agent": self.name,
            "type": "planning",
            "estimated_steps": estimated_steps,
            "requires_decomposition": intent.complexity in ["complex", "multi_step"],
            "plan": {
                "goal": message,
                "estimated_steps": estimated_steps,
                "approach": self._determine_approach(intent)
            },
            "supporting_agents": [AgentType.CODE, AgentType.BUILD],
            "tools": self.tools
        }
    
    def _estimate_steps(self, message: str, intent: IntentClassification) -> int:
        """Estimate number of steps required."""
        # Simple heuristic based on complexity
        if intent.complexity == "multi_step":
            return 5
        elif intent.complexity == "complex":
            return 3
        
        # Count action words
        action_words = ["create", "write", "add", "implement", "setup", "configure", "build"]
        count = sum(1 for word in action_words if word in message.lower())
        return max(2, count)
    
    def _determine_approach(self, intent: IntentClassification) -> str:
        """Determine the planning approach."""
        if IntentType.CODE_GENERATION in [intent.primary_intent]:
            return "incremental_implementation"
        elif IntentType.RESEARCH in [intent.primary_intent]:
            return "research_then_implement"
        else:
            return "sequential_execution"


class DebugAgent(BaseAgent):
    """Agent for debugging and error analysis."""
    
    def __init__(self):
        super().__init__(
            AgentType.DEBUG,
            "Debug",
            "Analyzes errors, traces bugs, and suggests fixes"
        )
        self.capabilities = [
            "error_analysis",
            "bug_tracing",
            "stack_trace_analysis",
            "breakpoint_management",
            "variable_inspection"
        ]
        self.tools = ["read", "grep", "edit", "bash"]
    
    async def can_handle(self, intent: IntentClassification, context: AgentContext) -> float:
        if intent.primary_intent == IntentType.DEBUGGING:
            return 0.95
        elif intent.primary_intent == IntentType.ERROR_ANALYSIS:
            return 0.95
        elif SubIntent.FIX_BUG in intent.sub_intents:
            return 0.90
        elif "error" in str(intent.metadata.get("matched_patterns", [])).lower():
            return 0.75
        return 0.20
    
    async def execute(
        self, 
        message: str, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[str, Any]:
        # Check if we have error context
        has_error_context = "error" in message.lower() or "traceback" in message.lower()
        
        return {
            "agent": self.name,
            "type": "debugging",
            "has_error_context": has_error_context,
            "suggested_approach": self._suggest_approach(message),
            "tools": self.tools,
            "focus_areas": ["error_location", "root_cause", "solution"]
        }
    
    def _suggest_approach(self, message: str) -> str:
        """Suggest debugging approach based on message."""
        if "traceback" in message.lower():
            return "analyze_stack_trace"
        elif "error" in message.lower():
            return "locate_and_fix"
        else:
            return "inspect_and_debug"


class ResearchAgent(BaseAgent):
    """Agent for research, documentation, and learning tasks."""
    
    def __init__(self):
        super().__init__(
            AgentType.RESEARCH,
            "Research",
            "Researches topics, finds documentation, and explores codebases"
        )
        self.capabilities = [
            "web_search",
            "documentation_lookup",
            "code_exploration",
            "api_research",
            "learning_assistance"
        ]
        self.tools = ["webfetch", "read", "grep", "bash"]
    
    async def can_handle(self, intent: IntentClassification, context: AgentContext) -> float:
        if intent.primary_intent == IntentType.RESEARCH:
            return 0.95
        elif intent.primary_intent == IntentType.DOCUMENTATION:
            return 0.95
        elif intent.primary_intent == IntentType.LEARNING:
            return 0.90
        elif intent.requires_web_search:
            return 0.85
        elif SubIntent.WEB_SEARCH in intent.sub_intents:
            return 0.80
        return 0.25
    
    async def execute(
        self, 
        message: str, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[str, Any]:
        return {
            "agent": self.name,
            "type": "research",
            "requires_web": intent.requires_web_search,
            "research_areas": self._identify_research_areas(message),
            "tools": self.tools
        }
    
    def _identify_research_areas(self, message: str) -> List[str]:
        """Identify what needs to be researched."""
        areas = []
        
        if "documentation" in message.lower():
            areas.append("documentation")
        if "api" in message.lower():
            areas.append("api_reference")
        if "example" in message.lower():
            areas.append("code_examples")
        if "how to" in message.lower():
            areas.append("tutorial")
        
        return areas if areas else ["general_research"]


class CodeAgent(BaseAgent):
    """Agent for code-specific operations."""
    
    def __init__(self):
        super().__init__(
            AgentType.CODE,
            "Code",
            "Handles code writing, editing, and refactoring"
        )
        self.capabilities = [
            "code_writing",
            "code_editing",
            "refactoring",
            "code_review",
            "implementation"
        ]
        self.tools = ["read", "write", "edit", "grep", "bash"]
    
    async def can_handle(self, intent: IntentClassification, context: AgentContext) -> float:
        if intent.primary_intent == IntentType.CODE_GENERATION:
            return 0.95
        elif intent.primary_intent == IntentType.CODE_ANALYSIS:
            return 0.90
        elif intent.primary_intent == IntentType.REFACTORING:
            return 0.95
        elif intent.requires_code_tools:
            return 0.80
        elif SubIntent.WRITE_FUNCTION in intent.sub_intents:
            return 0.85
        return 0.40
    
    async def execute(
        self, 
        message: str, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[str, Any]:
        return {
            "agent": self.name,
            "type": "code_operation",
            "operation_type": self._determine_operation(intent),
            "target_files": context.open_files or [],
            "tools": self.tools
        }
    
    def _determine_operation(self, intent: IntentClassification) -> str:
        """Determine the type of code operation."""
        if intent.primary_intent == IntentType.CODE_GENERATION:
            return "generate"
        elif intent.primary_intent == IntentType.REFACTORING:
            return "refactor"
        elif SubIntent.FIX_BUG in intent.sub_intents:
            return "fix"
        else:
            return "edit"


class AgentRouter:
    """
    Routes user messages to the most appropriate agent based on intent classification.
    """
    
    def __init__(self):
        self.agents: Dict[AgentType, BaseAgent] = {}
        self._initialize_agents()
        log.info("AgentRouter initialized with %d agents", len(self.agents))
    
    def _initialize_agents(self):
        """Initialize all available agents."""
        self.agents[AgentType.GENERAL] = GeneralAgent()
        self.agents[AgentType.BUILD] = BuildAgent()
        self.agents[AgentType.PLAN] = PlanAgent()
        self.agents[AgentType.DEBUG] = DebugAgent()
        self.agents[AgentType.RESEARCH] = ResearchAgent()
        self.agents[AgentType.CODE] = CodeAgent()
    
    async def route(
        self, 
        message: str, 
        context: AgentContext
    ) -> AgentRoute:
        """
        Route a message to the most appropriate agent.
        
        Args:
            message: The user's input message
            context: Context for the agent
            
        Returns:
            AgentRoute with the selected agent and metadata
        """
        # Classify intent
        intent = get_intent_classifier().classify(message)
        
        # Get capability scores from all agents
        agent_scores = await self._score_agents(intent, context)
        
        # Select primary agent
        primary_agent_type = self._select_primary_agent(agent_scores, intent)
        
        # Select supporting agents
        supporting_agents = self._select_supporting_agents(
            agent_scores, 
            primary_agent_type,
            intent
        )
        
        # Generate routing reason
        routing_reason = self._generate_routing_reason(
            primary_agent_type, 
            intent, 
            agent_scores[primary_agent_type]
        )
        
        route = AgentRoute(
            agent_type=primary_agent_type,
            confidence=agent_scores[primary_agent_type],
            supporting_agents=supporting_agents,
            routing_reason=routing_reason,
            estimated_steps=self._estimate_steps(intent),
            requires_planning=intent.complexity in ["complex", "multi_step"]
        )
        
        log.info(
            f"Routed to {primary_agent_type.value} "
            f"(confidence: {route.confidence:.2f}, "
            f"supporting: {[a.value for a in supporting_agents]})"
        )
        
        return route
    
    async def _score_agents(
        self, 
        intent: IntentClassification, 
        context: AgentContext
    ) -> Dict[AgentType, float]:
        """Score each agent's ability to handle the intent."""
        scores = {}
        
        for agent_type, agent in self.agents.items():
            try:
                score = await agent.can_handle(intent, context)
                scores[agent_type] = score
            except Exception as e:
                log.error(f"Error scoring agent {agent_type.value}: {e}")
                scores[agent_type] = 0.0
        
        return scores
    
    def _select_primary_agent(
        self, 
        scores: Dict[AgentType, float], 
        intent: IntentClassification
    ) -> AgentType:
        """Select the primary agent based on scores."""
        # Sort by score
        sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        # Check if top agent meets threshold
        if sorted_agents[0][1] >= 0.5:
            return sorted_agents[0][0]
        
        # Default to general agent for low confidence
        return AgentType.GENERAL
    
    def _select_supporting_agents(
        self, 
        scores: Dict[AgentType, float],
        primary_agent: AgentType,
        intent: IntentClassification
    ) -> List[AgentType]:
        """Select supporting agents that can assist."""
        supporting = []
        
        # Get agents with decent scores (above 0.4) that aren't the primary
        for agent_type, score in scores.items():
            if agent_type != primary_agent and score >= 0.4:
                supporting.append(agent_type)
        
        # Limit to top 2 supporting agents
        supporting.sort(key=lambda x: scores[x], reverse=True)
        return supporting[:2]
    
    def _generate_routing_reason(
        self, 
        agent_type: AgentType, 
        intent: IntentClassification,
        confidence: float
    ) -> str:
        """Generate human-readable routing reason."""
        agent = self.agents[agent_type]
        
        reasons = {
            AgentType.GENERAL: "Simple conversation or general assistance",
            AgentType.BUILD: "Build, compilation, or package management task",
            AgentType.PLAN: "Complex multi-step task requiring planning",
            AgentType.DEBUG: "Debugging or error analysis needed",
            AgentType.RESEARCH: "Research, documentation, or exploration",
            AgentType.CODE: "Code writing, editing, or refactoring",
        }
        
        base_reason = reasons.get(agent_type, "General task")
        
        return f"{base_reason} (intent: {intent.primary_intent.value}, confidence: {confidence:.0%})"
    
    def _estimate_steps(self, intent: IntentClassification) -> int:
        """Estimate number of steps required."""
        if intent.complexity == "multi_step":
            return 5
        elif intent.complexity == "complex":
            return 3
        return 1
    
    def get_agent(self, agent_type: AgentType) -> Optional[BaseAgent]:
        """Get an agent by type."""
        return self.agents.get(agent_type)
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """List all available agents with their info."""
        return [
            {
                "type": agent.agent_type.value,
                "name": agent.name,
                "description": agent.description,
                "capabilities": agent.capabilities,
                "tools": agent.tools
            }
            for agent in self.agents.values()
        ]


# Singleton instance
_agent_router = None


def get_agent_router() -> AgentRouter:
    """Get singleton instance of AgentRouter."""
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter()
    return _agent_router


# Convenience function
async def route_message(
    message: str, 
    session_id: str,
    workspace_path: Optional[str] = None
) -> AgentRoute:
    """Route a message using the singleton router."""
    context = AgentContext(
        session_id=session_id,
        workspace_path=workspace_path
    )
    return await get_agent_router().route(message, context)
