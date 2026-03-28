"""
AutoGen Wrapper for Cortex IDE
Enables multi-agent collaboration using DeepSeek provider
Compatible with AutoGen 0.7+
"""

from typing import List, Dict, Any, Optional
import os
import asyncio
from src.utils.logger import get_logger

log = get_logger("autogen_wrapper")

try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
    from autogen_core import CancellationToken
    from autogen_ext.models.openai import OpenAIChatCompletionClient
    AUTOGEN_AVAILABLE = True
    log.info("✅ AutoGen 0.7+ loaded successfully")
except ImportError as e:
    log.debug(f"AutoGen 0.7+ not available, checking legacy... ({e})")
    # Try old import for compatibility
    try:
        from autogen import AssistantAgent, UserProxyAgent, ConversableAgent, GroupChat, GroupChatManager
        AUTOGEN_AVAILABLE = True
        log.info("✅ AutoGen (legacy) loaded successfully")
    except ImportError as e2:
        AUTOGEN_AVAILABLE = False
        log.debug(f"Legacy AutoGen also not available ({e2})")
        log.warning("⚠️ AutoGen not installed. Multi-agent features disabled.")


class CortexAgent:
    """Represents a specialized AI agent in the multi-agent system."""
    
    def __init__(self, name: str, role: str, api_key: str, 
                 system_message: Optional[str] = None,
                 human_input_mode: str = "NEVER"):
        self.name = name
        self.role = role
        self.api_key = api_key
        
        # Default system messages based on role - Enhanced with specialized agents
        default_messages = {
            "product_manager": """You are a Senior Product Manager. Your responsibilities:
- Extract and analyze requirements from design documents
- Create detailed product specifications
- Define user stories with acceptance criteria (Given/When/Then format)
- Prioritize features using MoSCoW method (Must have, Should have, Could have, Won't have)
- Identify dependencies and risks
- Ensure product-market fit
- Create roadmaps and milestones""",
            
            "architect": """You are a Principal Solutions Architect. Your expertise:
- Design scalable, maintainable system architectures (MVC, Microservices, Event-Driven, Serverless)
- Select appropriate technology stacks with justification
- Create architectural decision records (ADRs)
- Design API contracts (REST, GraphQL, gRPC)
- Plan data models and database schemas
- Define integration patterns and messaging strategies
- Ensure separation of concerns and SOLID principles
- Create component diagrams and data flow documentation""",
            
            "security_agent": """You are a Security Engineering Specialist. Your focus areas:
- OWASP Top 10 vulnerability prevention
- Authentication & authorization implementation (OAuth2, JWT, RBAC)
- Input validation and sanitization
- SQL injection, XSS, CSRF protection
- Secrets management and encryption
- Security headers and CORS policies
- Rate limiting and DDoS protection
- Compliance requirements (GDPR, HIPAA, SOC2)
- Threat modeling and risk assessment
- Security testing and penetration testing strategies""",
            
            "performance_agent": """You are a Performance Optimization Expert. Your specialties:
- Response time optimization (< 200ms target)
- Caching strategies (Redis, Memcached, CDN)
- Database query optimization and indexing
- Load balancing and horizontal scaling
- Performance profiling and bottleneck identification
- Resource utilization optimization
- Concurrency and parallelization
- Memory management and garbage collection
- Network optimization and compression
- Performance monitoring and alerting setup""",
            
            "devops_agent": """You are a DevOps Automation Engineer. Your domain:
- CI/CD pipeline design (GitHub Actions, GitLab CI, Jenkins)
- Infrastructure as Code (Terraform, CloudFormation, Pulumi)
- Container orchestration (Docker, Kubernetes, ECS)
- Monitoring and logging (Prometheus, Grafana, ELK Stack)
- Cloud deployment (AWS, Azure, GCP)
- Environment management (dev, staging, production)
- Blue-green and canary deployments
- Disaster recovery and backup strategies
- Configuration management
- Git workflows and branching strategies""",
            
            "testing_strategy_agent": """You are a Test Automation Architect. Your expertise:
- Test pyramid implementation (70% unit, 20% integration, 10% E2E)
- Unit test generation for all functions/methods
- Integration testing for APIs and services
- E2E testing for critical user flows
- Property-based and fuzz testing
- Test coverage analysis (target: 80%+)
- Mocking and stubbing strategies
- Performance and load testing
- Accessibility testing (WCAG 2.1)
- Test data management and fixtures""",
            
            "documentation_agent": """You are a Technical Documentation Specialist. Your outputs:
- README.md with quickstart guides
- API documentation (OpenAPI/Swagger)
- Architecture documentation (ARCHITECTURE.md)
- Deployment guides (DEPLOYMENT.md)
- Contributing guidelines (CONTRIBUTING.md)
- Troubleshooting guides
- Code comments and inline documentation
- Changelog and release notes
- User manuals and tutorials
- Knowledge base articles""",
            
            "coder": """You are a Senior Software Engineer. Your standards:
- Write clean, readable, maintainable code following Clean Code principles
- Apply SOLID principles consistently
- Use design patterns appropriately (Factory, Singleton, Strategy, Observer, etc.)
- Implement comprehensive error handling and logging
- Add type hints and docstrings to all code
- Follow naming conventions (camelCase, PascalCase, snake_case)
- Write self-documenting code with meaningful variable names
- Optimize for readability first, performance second
- Refactor ruthlessly to eliminate duplication
- Use version control best practices (atomic commits, descriptive messages)""",
            
            "tester": """You are a Senior QA Automation Engineer. Your approach:
- Create comprehensive test plans covering all requirements
- Write automated tests at all levels (unit, integration, E2E)
- Perform exploratory testing to find edge cases
- Conduct regression testing for bug fixes
- Validate functional and non-functional requirements
- Create test data and fixtures
- Document bugs with clear reproduction steps
- Verify fixes and close the loop
- Track quality metrics (defect density, escape rate)
- Advocate for quality throughout development""",
            
            "reviewer": """You are a Principal Code Reviewer. Your review checklist:
- Code correctness and logic errors
- adherence to project coding standards
- SOLID principles and design pattern usage
- Error handling completeness
- Security vulnerabilities (OWASP Top 10)
- Performance issues and optimization opportunities
- Test coverage adequacy
- Code duplication and DRY violations
- Readability and maintainability
- Documentation completeness (docstrings, comments)
- Proper logging and debugging capabilities
- Edge case handling""",
            
            "general": "You are a helpful AI assistant specialized in software development."
        }
        
        self.system_message = system_message or default_messages.get(
            role.lower(), 
            default_messages["general"]
        )
        
        self.agent = None
        self._initialize_agent()
    
    def _initialize_agent(self):
        """Initialize the AutoGen agent with DeepSeek configuration."""
        if not AUTOGEN_AVAILABLE:
            log.error("AutoGen not available")
            return
        
        try:
            # Create DeepSeek client for AutoGen 0.7+
            model_client = OpenAIChatCompletionClient(
                model="deepseek-chat",
                api_key=self.api_key,
                base_url="https://api.deepseek.com/v1",
                model_info={
                    "vision": False,
                    "function_calling": True,
                    "json_output": False,
                    "family": "unknown"
                }
            )
            
            self.agent = AssistantAgent(
                name=self.name,
                model_client=model_client,
                system_message=self.system_message
            )
            
            log.info(f"✅ Agent '{self.name}' ({self.role}) initialized with DeepSeek (AutoGen 0.7+)")
            
        except Exception as e:
            log.error(f"Failed to initialize agent: {e}")
            self.agent = None
    
    async def chat_async(self, message: str) -> str:
        """Async chat method for AutoGen 0.7+"""
        if not self.agent:
            return "Error: Agent not initialized"
        
        try:
            # Run the task
            result = await self.agent.run(message)
            return result.messages[-1].content if hasattr(result, 'messages') else str(result)
        except Exception as e:
            log.error(f"Agent chat error: {e}")
            return f"Error during conversation: {str(e)}"
    
    def chat(self, message: str, other_agent: 'CortexAgent' = None) -> str:
        """Synchronous wrapper for chat."""
        try:
            return asyncio.run(self.chat_async(message))
        except Exception as e:
            log.error(f"Sync chat error: {e}")
            return f"Error: {str(e)}"


class CortexMultiAgentSystem:
    """Manages multiple agents working together."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.agents: Dict[str, CortexAgent] = {}
        self.team = None
        
        log.info("🤖 Initializing Multi-Agent System with DeepSeek (AutoGen 0.7+)")
    
    def add_agent(self, name: str, role: str, 
                  system_message: Optional[str] = None) -> CortexAgent:
        """Add a new agent to the system."""
        agent = CortexAgent(
            name=name,
            role=role,
            api_key=self.api_key,
            system_message=system_message
        )
        self.agents[name] = agent
        log.info(f"➕ Added agent: {name} ({role})")
        return agent
    
    def remove_agent(self, name: str):
        """Remove an agent from the system."""
        if name in self.agents:
            del self.agents[name]
            log.info(f"➖ Removed agent: {name}")
    
    def get_agent(self, name: str) -> Optional[CortexAgent]:
        """Get an agent by name."""
        return self.agents.get(name)
    
    async def run_task_async(self, task: str) -> str:
        """Run a task with all agents collaborating (async)."""
        if not self.agents:
            return "Error: No agents available"
        
        try:
            # Simple round-robin collaboration
            result = task
            for agent_name, agent in self.agents.items():
                if agent.agent:
                    log.info(f"➡️ Agent {agent_name} processing...")
                    instruction = f"Previous result:\n{result}\n\nYour contribution:"
                    response = await agent.chat_async(instruction)
                    result = f"{result}\n\n{agent_name}: {response}"
            
            return result
            
        except Exception as e:
            log.error(f"Team task error: {e}")
            return f"Error during collaboration: {str(e)}"
    
    def run_collaborative_task(self, task: str, initiator_name: str = None) -> str:
        """Synchronous wrapper for collaborative task."""
        try:
            return asyncio.run(self.run_task_async(task))
        except Exception as e:
            log.error(f"Collaborative task error: {e}")
            return f"Error: {str(e)}"
    
    def run_sequential_workflow(self, task: str, workflow: List[str]) -> str:
        """Run a sequential workflow where agents pass work down the chain."""
        if len(workflow) < 2:
            return "Error: Need at least 2 agents for sequential workflow"
        
        current_result = task
        
        for i, agent_name in enumerate(workflow):
            if agent_name not in self.agents:
                log.error(f"Agent '{agent_name}' not found in workflow")
                continue
            
            agent = self.agents[agent_name]
            log.info(f"➡️ Agent {agent_name} processing step {i+1}/{len(workflow)}")
            
            # Pass task to next agent
            instruction = f"""
Previous step result:
{current_result}

Your task: Continue working on this. Add your expertise and pass to next agent.
"""
            current_result = agent.chat(instruction)
        
        log.info(f"✅ Sequential workflow completed")
        return current_result
    
    def list_agents(self) -> List[Dict[str, str]]:
        """List all active agents."""
        return [
            {"name": agent.name, "role": agent.role}
            for agent in self.agents.values()
        ]
    
    def shutdown(self):
        """Clean up resources."""
        self.agents.clear()
        self.team = None
        log.info("🛑 Multi-Agent System shut down")


# Convenience functions for quick setup - Enhanced with specialized agents
def create_standard_team(api_key: str, include_specialists: bool = True) -> CortexMultiAgentSystem:
    """
    Create a comprehensive multi-agent team with specialized domain experts.
    
    Args:
        api_key: DeepSeek API key
        include_specialists: If True, include Security, DevOps, Performance, Testing, and Documentation agents
    """
    system = CortexMultiAgentSystem(api_key)
    
    # Core development team (always included)
    system.add_agent("PM", "product_manager", 
                    "You are a Product Manager. Define clear requirements and user stories.")
    system.add_agent("Architect", "architect",
                    "You are a Solutions Architect. Design scalable, maintainable systems.")
    system.add_agent("Developer", "coder",
                    "You are a Senior Developer. Write clean, tested, production-ready code.")
    system.add_agent("QA", "tester",
                    "You are a QA Engineer. Find edge cases and ensure quality.")
    system.add_agent("Reviewer", "reviewer",
                    "You are a Code Reviewer. Ensure best practices and security.")
    
    # Specialized domain experts (optional for complex projects)
    if include_specialists:
        system.add_agent("SecurityAgent", "security_agent",
                        "You are a Security Specialist. Focus on OWASP Top 10, auth, encryption.")
        system.add_agent("PerformanceAgent", "performance_agent",
                        "You are a Performance Expert. Optimize for speed and scalability.")
        system.add_agent("DevOpsAgent", "devops_agent",
                        "You are a DevOps Engineer. Automate deployment and infrastructure.")
        system.add_agent("TestingStrategyAgent", "testing_strategy_agent",
                        "You are a Test Architect. Design comprehensive test strategies.")
        system.add_agent("DocumentationAgent", "documentation_agent",
                        "You are a Technical Writer. Create clear documentation.")
        
        log.info("🤖 Complete multi-agent team initialized:")
        log.info("   Core: PM + Architect + Developer + QA + Reviewer")
        log.info("   Specialists: Security + Performance + DevOps + Testing + Documentation")
    else:
        log.info("🤖 Core development team initialized: PM + Architect + Developer + QA + Reviewer")
    
    return system


def create_coding_duo(api_key: str) -> CortexMultiAgentSystem:
    """Create a simple coder-reviewer pair."""
    system = CortexMultiAgentSystem(api_key)
    
    system.add_agent("Coder", "coder",
                    "You write code. Focus on functionality and clarity.")
    system.add_agent("Reviewer", "reviewer",
                    "You review code. Look for bugs, improvements, and best practices.")
    
    log.info("✅ Coder-Reviewer duo created")
    return system


# Global instance for singleton pattern
_autogen_system_instance: Optional[CortexMultiAgentSystem] = None


def init_autogen_system(api_key: str) -> CortexMultiAgentSystem:
    """Initialize and return the global AutoGen system instance."""
    global _autogen_system_instance
    
    if _autogen_system_instance is None:
        _autogen_system_instance = create_standard_team(api_key)
        log.info("✅ Global AutoGen system initialized")
    
    return _autogen_system_instance


def get_autogen_system() -> Optional[CortexMultiAgentSystem]:
    """Get the global AutoGen system instance."""
    return _autogen_system_instance
