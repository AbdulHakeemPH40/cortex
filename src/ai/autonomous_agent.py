"""
Unified Autonomous AI Agent for Cortex IDE
Orchestrates all autonomous capabilities to build production-ready applications from .md specifications.

Capabilities:
1. Requirements Analysis - Parse .md design documents
2. Multi-Agent Collaboration - AutoGen team of specialists
3. Self-Healing Code Generation - Auto-detect & fix bugs
4. Automated Testing - Generate comprehensive test suites
5. Production Readiness - Quality checks & deployment automation
6. Cross-File Context - Track dependencies across codebase
"""

from typing import Dict, List, Optional, Any
import logging
import asyncio
from pathlib import Path

from src.ai.requirements_analyzer import RequirementsAnalyzer, RequirementsDocument
from src.ai.autogen_wrapper import init_autogen_system, get_autogen_system
from src.ai.self_healing_generator import SelfHealingCodeGenerator, generate_self_healing_code
from src.ai.test_generator import TestGenerator, generate_tests
from src.ai.production_readiness import ProductionReadinessChecker, assess_production_readiness
from src.ai.context_tracker import CrossFileContextTracker, create_context_tracker
from src.core.key_manager import get_key_manager
from src.utils.logger import get_logger

log = get_logger("autonomous_agent")


class AutonomousAIAgent:
    """
    Fully autonomous AI software development agent.
    
    Reads .md design document → Builds production-ready application
    
    Workflow:
    1. Analyze requirements from .md file
    2. Clarify gaps with user (if needed)
    3. Design architecture with multi-agent team
    4. Generate code with self-healing
    5. Create comprehensive tests
    6. Verify production readiness
    7. Deploy with IaC artifacts
    """
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.api_key = None
        self.agents = None
        self.context_tracker = None
        self.requirements = None
        self.generated_files = []
        
        log.info("🤖 Initializing Autonomous AI Agent...")
    
    def initialize(self, api_key: Optional[str] = None) -> bool:
        """Initialize all subsystems."""
        try:
            # Get API key
            if not api_key:
                key_manager = get_key_manager()
                self.api_key = key_manager.get_key("deepseek")
            else:
                self.api_key = api_key
            
            if not self.api_key:
                log.error("❌ DeepSeek API key required")
                return False
            
            # Initialize AutoGen multi-agent system
            self.agents = init_autogen_system(self.api_key)
            
            # Initialize context tracker
            self.context_tracker = create_context_tracker(self.project_root)
            
            log.info("✅ Autonomous AI Agent initialized successfully")
            log.info(f"   🧠 Multi-Agent System: {len(self.agents.list_agents())} agents ready")
            log.info(f"   📊 Context Tracker: {len(self.context_tracker.graph.files)} files indexed")
            
            return True
            
        except Exception as e:
            log.error(f"Failed to initialize: {e}")
            return False
    
    async def build_from_spec(self, spec_file: str) -> Dict[str, Any]:
        """
        Build complete application from .md specification file.
        
        Args:
            spec_file: Path to .md design document
        
        Returns:
            Build result with generated files, tests, and deployment artifacts
        """
        log.info("🚀 Starting autonomous build from specification...")
        log.info(f"   📄 Specification: {spec_file}")
        
        result = {
            "success": False,
            "phase": "initialization",
            "generated_files": [],
            "tests": [],
            "deployment_artifacts": [],
            "issues": [],
            "recommendations": []
        }
        
        try:
            # Phase 1: Requirements Analysis
            result["phase"] = "requirements_analysis"
            log.info("=" * 60)
            log.info("PHASE 1: Requirements Analysis")
            log.info("=" * 60)
            
            self.requirements = self._analyze_requirements(spec_file)
            
            if not self.requirements:
                result["issues"].append("Failed to parse requirements")
                return result
            
            log.info(f"   ✅ Extracted {len(self.requirements.features)} features")
            log.info(f"   ✅ Identified {len(self.requirements.user_stories)} user stories")
            log.info(f"   ✅ Found {len(self.requirements.api_endpoints)} API endpoints")
            
            if self.requirements.missing_requirements:
                log.warning(f"   ⚠️ {len(self.requirements.missing_requirements)} gaps detected")
                result["recommendations"].extend(self.requirements.clarifying_questions)
            
            # Phase 2: Architecture Design (Multi-Agent)
            result["phase"] = "architecture_design"
            log.info("=" * 60)
            log.info("PHASE 2: Architecture Design")
            log.info("=" * 60)
            
            architecture = await self._design_architecture()
            result["generated_files"].extend(architecture["files"])
            
            # Phase 3: Code Generation (Self-Healing)
            result["phase"] = "code_generation"
            log.info("=" * 60)
            log.info("PHASE 3: Code Generation")
            log.info("=" * 60)
            
            code_result = await self._generate_code()
            result["generated_files"].extend(code_result["files"])
            result["issues"].extend(code_result.get("fixed_issues", []))
            
            # Phase 4: Test Generation
            result["phase"] = "test_generation"
            log.info("=" * 60)
            log.info("PHASE 4: Test Generation")
            log.info("=" * 60)
            
            test_result = self._generate_tests()
            result["tests"].extend(test_result["files"])
            
            # Phase 5: Production Readiness Check
            result["phase"] = "production_readiness"
            log.info("=" * 60)
            log.info("PHASE 5: Production Readiness Assessment")
            log.info("=" * 60)
            
            readiness_report = self._assess_production_readiness()
            result["deployment_artifacts"].extend(readiness_report.deployment_artifacts)
            result["recommendations"].extend(readiness_report.recommendations)
            
            # Final Summary
            result["success"] = True
            result["phase"] = "completed"
            
            log.info("=" * 60)
            log.info("✅ AUTONOMOUS BUILD COMPLETED SUCCESSFULLY")
            log.info("=" * 60)
            log.info(f"   📁 Generated Files: {len(result['generated_files'])}")
            log.info(f"   🧪 Test Files: {len(result['tests'])}")
            log.info(f"   🏗️ Deployment Artifacts: {len(result['deployment_artifacts'])}")
            
            if result["recommendations"]:
                log.info(f"   💡 Recommendations: {len(result['recommendations'])}")
            
            return result
            
        except Exception as e:
            log.error(f"Build failed in phase {result.get('phase', 'unknown')}: {e}")
            result["issues"].append(str(e))
            return result
    
    def _analyze_requirements(self, spec_file: str) -> Optional[RequirementsDocument]:
        """Phase 1: Parse and analyze requirements."""
        try:
            analyzer = RequirementsAnalyzer()
            requirements = analyzer.parse_file(spec_file)
            
            log.info(f"   📋 Title: {requirements.title}")
            log.info(f"   📋 Version: {requirements.version}")
            
            if requirements.tech_stack:
                ts = requirements.tech_stack
                if ts.languages:
                    log.info(f"   💻 Languages: {', '.join(ts.languages)}")
                if ts.frameworks:
                    log.info(f"   🚀 Frameworks: {', '.join(ts.frameworks)}")
            
            return requirements
            
        except Exception as e:
            log.error(f"Requirements analysis failed: {e}")
            return None
    
    async def _design_architecture(self) -> Dict[str, Any]:
        """Phase 2: Design architecture using multi-agent team."""
        log.info("   🏗️ Designing architecture with multi-agent team...")
        
        # Use Architect agent
        architect_task = f"""
Based on these requirements, design a complete system architecture:

Project: {self.requirements.title}
Features: {len(self.requirements.features)}
Tech Stack: {self.requirements.tech_stack.frameworks if self.requirements.tech_stack else 'To be determined'}

Please provide:
1. Architecture pattern (MVC, Microservices, etc.)
2. Component diagram
3. Technology choices with justification
4. Data model design
5. API structure
6. Deployment strategy
"""
        
        # Run through AutoGen
        if self.agents:
            try:
                architecture_response = await self.agents.run_task_async(architect_task)
                
                # Save architecture document
                arch_file = "ARCHITECTURE.md"
                arch_path = Path(self.project_root) / arch_file
                arch_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(arch_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Architecture Document\n\n{architecture_response}")
                
                log.info(f"   ✅ Architecture saved to: {arch_file}")
                
                return {
                    "files": [arch_file],
                    "response": architecture_response
                }
                
            except Exception as e:
                log.error(f"Architecture design failed: {e}")
                return {"files": [], "response": ""}
        
        return {"files": [], "response": ""}
    
    async def _generate_code(self) -> Dict[str, Any]:
        """Phase 3: Generate code with self-healing."""
        log.info("   💻 Generating code with self-healing...")
        
        generated_files = []
        fixed_issues = []
        
        # Generate code for each feature
        for i, feature in enumerate(self.requirements.features, 1):
            log.info(f"   Implementing feature {i}/{len(self.requirements.features)}: {feature.name}")
            
            # Generate initial code
            code_task = f"""
Implement this feature:

Feature: {feature.name}
Description: {feature.description}
Priority: {feature.priority}
User Stories: {chr(10).join(feature.user_stories[:3]) if feature.user_stories else 'None'}

Generate production-ready code following:
- Clean Code principles
- SOLID design
- Comprehensive error handling
- Type hints and documentation
- Logging and monitoring
"""
            
            try:
                # Generate code using Developer agent
                if self.agents:
                    initial_code = await self.agents.run_task_async(code_task)
                    
                    # Apply self-healing
                    healing_result = generate_self_healing_code(
                        initial_code,
                        language="python",  # Could infer from tech stack
                        context={
                            "feature": feature.name,
                            "requirements": feature.description
                        }
                    )
                    
                    if healing_result.success:
                        log.info(f"      ✅ Code generated (healed in {healing_result.iterations} iterations)")
                        
                        # Save file
                        filename = f"feature_{feature.name.lower().replace(' ', '_')}.py"
                        file_path = Path(self.project_root) / "src" / filename
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(healing_result.code)
                        
                        generated_files.append(str(file_path.relative_to(self.project_root)))
                        
                        if healing_result.errors_fixed:
                            fixed_issues.extend(healing_result.errors_fixed)
                            log.info(f"      🔧 Fixed: {', '.join(healing_result.errors_fixed[:3])}")
                    
            except Exception as e:
                log.error(f"      ❌ Feature implementation failed: {e}")
        
        return {
            "files": generated_files,
            "fixed_issues": fixed_issues
        }
    
    def _generate_tests(self) -> Dict[str, Any]:
        """Phase 4: Generate comprehensive test suite."""
        log.info("   🧪 Generating automated tests...")
        
        # Collect all generated code
        code_files = []
        for file_path in Path(self.project_root).glob("src/**/*.py"):
            if not file_path.name.startswith("test_"):
                code_files.append(str(file_path))
        
        if not code_files:
            log.warning("   ⚠️ No code files found for testing")
            return {"files": []}
        
        # Generate tests
        test_generator = TestGenerator(language="python")
        test_files = []
        
        for code_file in code_files[:5]:  # Limit to first 5 files
            try:
                with open(code_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                
                # Generate unit tests
                unit_tests = test_generator.generate_unit_tests(code)
                
                if unit_tests:
                    test_file = f"test_{Path(code_file).name}"
                    test_path = Path(self.project_root) / "tests" / test_file
                    test_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(test_path, 'w', encoding='utf-8') as f:
                        f.write(unit_tests)
                    
                    test_files.append(str(test_path.relative_to(self.project_root)))
                    log.info(f"      ✅ Tests: {test_file}")
                    
            except Exception as e:
                log.error(f"      Test generation failed for {code_file}: {e}")
        
        return {"files": test_files}
    
    def _assess_production_readiness(self) -> Any:
        """Phase 5: Production readiness assessment."""
        log.info("   🔍 Assessing production readiness...")
        
        # Build project context
        context = {
            "language": "python",
            "has_readme": (Path(self.project_root) / "README.md").exists(),
            "has_dockerfile": (Path(self.project_root) / "Dockerfile").exists(),
            "has_tests": len(list(Path(self.project_root).glob("tests/**/*.py"))) > 0,
            "has_linting": (Path(self.project_root) / ".pylintrc").exists(),
        }
        
        # Run assessment
        checker = ProductionReadinessChecker()
        report = checker.assess_readiness(context)
        
        log.info(f"   📊 Overall Status: {report.overall_status.value}")
        log.info(f"   ✅ Passed: {report.passed}/{report.total_checks}")
        
        if report.failed > 0:
            log.warning(f"   ❌ Failed: {report.failed}")
        
        # Generate deployment artifacts
        artifacts = checker.generate_deployment_artifacts(context)
        
        for artifact in artifacts:
            log.info(f"      🏗️ Generated: {artifact}")
        
        return report
    
    def shutdown(self):
        """Clean shutdown of all subsystems."""
        log.info("🛑 Shutting down Autonomous AI Agent...")
        
        if self.agents:
            self.agents.shutdown()
        
        log.info("   ✅ Shutdown complete")


# Convenience function
async def build_project(spec_file: str, project_root: str = None) -> Dict[str, Any]:
    """
    Build complete project from .md specification.
    
    Usage:
        result = await build_project("requirements.md")
        print(f"Generated {len(result['generated_files'])} files")
    """
    if not project_root:
        project_root = str(Path.cwd())
    
    agent = AutonomousAIAgent(project_root)
    
    if not agent.initialize():
        return {
            "success": False,
            "phase": "initialization",
            "issues": ["Failed to initialize agent"]
        }
    
    try:
        return await agent.build_from_spec(spec_file)
    finally:
        agent.shutdown()
