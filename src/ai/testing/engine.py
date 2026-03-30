"""
AI-Driven Testing System for Cortex AI Agent
Based on OpenCode's testing workflow architecture
"""

import os
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from src.utils.logger import get_logger

log = get_logger("ai_testing")


class TestType(Enum):
    """Types of tests available."""
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    SNAPSHOT = "snapshot"
    PERFORMANCE = "performance"


class TestPriority(Enum):
    """Priority levels for testing."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class TestingDecision:
    """Result of testing decision."""
    decision: str  # 'write_tests', 'skip_tests', 'run_existing'
    priority: Optional[TestPriority] = None
    trigger: Optional[str] = None
    scope: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class TestTool:
    """Definition of a testing tool."""
    name: str
    command: str
    config_files: List[str]
    languages: List[str]
    capabilities: List[str]
    priority: int = 1


@dataclass
class TestCase:
    """A single test case."""
    name: str
    description: str
    type: TestType
    priority: str


@dataclass
class TestPlan:
    """Plan for testing."""
    test_cases: List[TestCase]
    coverage_target: int = 80
    estimated_time: int = 30


@dataclass
class TestResult:
    """Result of a test execution."""
    name: str
    passed: bool
    error: Optional[str] = None
    duration: float = 0.0
    type: str = "unit"


@dataclass
class TestAnalysis:
    """Analysis of test results."""
    all_passed: bool
    passed_count: int
    failed_count: int
    failures: List[TestResult]
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class TestingDecisionEngine:
    """
    Decides when and how to test based on code changes and context.
    """
    
    def __init__(self):
        self.test_keywords = [
            'test', 'tests', 'testing', 'test suite', 'unit test',
            'integration test', 'e2e test', 'tdd', 'bdd',
            'test coverage', 'test case', 'spec', 'should',
            'assert', 'expect', 'verify', 'validate',
            'debug', 'bug', 'fix', 'error', 'exception'
        ]
        self.auto_test_threshold = 0.7
        log.info("TestingDecisionEngine initialized")
    
    def should_write_tests(self, code_changes: List[Dict], user_message: str = "") -> TestingDecision:
        """
        Determine if tests should be written based on context.
        
        Returns:
            TestingDecision with action and metadata
        """
        # Priority 1: Explicit user request
        if self._has_explicit_test_request(user_message):
            return TestingDecision(
                decision='write_tests',
                priority=TestPriority.HIGH,
                trigger='user_request',
                scope=self._determine_test_scope(code_changes)
            )
        
        # Implicit triggers
        implicit_score = self._calculate_implicit_test_score(code_changes, user_message)
        
        if implicit_score > self.auto_test_threshold:
            return TestingDecision(
                decision='write_tests',
                priority=TestPriority.MEDIUM,
                trigger='complexity_detected',
                scope=self._limit_scope_by_complexity(implicit_score)
            )
        
        # Check for quality issues
        if self._detects_quality_issues(code_changes):
            return TestingDecision(
                decision='write_tests',
                priority=TestPriority.LOW,
                trigger='quality_assurance',
                scope='critical_paths_only'
            )
        
        return TestingDecision(
            decision='skip_tests',
            reason='no_triggers_detected'
        )
    
    def _has_explicit_test_request(self, message: str) -> bool:
        """Check if user explicitly requested testing."""
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in self.test_keywords)
    
    def _calculate_implicit_test_score(self, code_changes: List[Dict], message: str) -> float:
        """Calculate implicit testing need score (0.0-1.0)."""
        score = 0.0
        
        # New components need tests
        new_files = [c for c in code_changes if c.get('type') == 'new']
        score += len(new_files) * 0.2
        
        # Complex files (heuristic based on size)
        for change in code_changes:
            content = change.get('content', '')
            if len(content) > 500:  # Larger files likely more complex
                score += 0.1
            if 'def ' in content or 'function' in content:  # Has functions
                score += 0.1
        
        # Keywords in message
        if self._has_explicit_test_request(message):
            score += 0.3
        
        return min(score, 1.0)
    
    def _determine_test_scope(self, code_changes: List[Dict]) -> str:
        """Determine appropriate test scope."""
        if len(code_changes) == 1:
            return 'single_component'
        elif len(code_changes) <= 3:
            return 'related_components'
        else:
            return 'full_module'
    
    def _limit_scope_by_complexity(self, score: float) -> str:
        """Limit test scope based on complexity score."""
        if score > 0.9:
            return 'full_coverage'
        elif score > 0.8:
            return 'critical_paths'
        else:
            return 'basic_coverage'
    
    def _detects_quality_issues(self, code_changes: List[Dict]) -> bool:
        """Detect if code changes have quality issues requiring tests."""
        for change in code_changes:
            content = change.get('content', '')
            # TODO: Add more sophisticated quality checks
            if 'TODO' in content or 'FIXME' in content:
                return True
        return False


class TestToolSelector:
    """
    Selects appropriate testing tools based on project context.
    """
    
    def __init__(self, workspace_path: str = "."):
        self.workspace_path = workspace_path
        self.tool_registry = self._initialize_tools()
        log.info("TestToolSelector initialized for %s", workspace_path)
    
    def _initialize_tools(self) -> Dict[str, TestTool]:
        """Initialize registry of available testing tools."""
        tools = {}
        
        # JavaScript/TypeScript tools
        tools['jest'] = TestTool(
            name='jest',
            command='npm test -- --coverage',
            config_files=['jest.config.js', 'jest.config.ts', 'package.json'],
            languages=['javascript', 'typescript'],
            capabilities=['unit', 'integration', 'snapshot'],
            priority=1
        )
        
        tools['vitest'] = TestTool(
            name='vitest',
            command='npm run test -- --coverage',
            config_files=['vitest.config.js', 'vitest.config.ts'],
            languages=['javascript', 'typescript'],
            capabilities=['unit', 'integration', 'coverage'],
            priority=2
        )
        
        tools['mocha'] = TestTool(
            name='mocha',
            command='npx mocha',
            config_files=['.mocharc.js', '.mocharc.json'],
            languages=['javascript', 'typescript'],
            capabilities=['unit', 'integration'],
            priority=3
        )
        
        # Python tools
        tools['pytest'] = TestTool(
            name='pytest',
            command='pytest -v --cov',
            config_files=['pytest.ini', 'setup.cfg', 'pyproject.toml'],
            languages=['python'],
            capabilities=['unit', 'integration', 'e2e'],
            priority=1
        )
        
        tools['unittest'] = TestTool(
            name='unittest',
            command='python -m unittest discover -v',
            config_files=[],
            languages=['python'],
            capabilities=['unit'],
            priority=2
        )
        
        # Java tools
        tools['junit'] = TestTool(
            name='junit',
            command='mvn test',
            config_files=['pom.xml'],
            languages=['java'],
            capabilities=['unit', 'integration'],
            priority=1
        )
        
        return tools
    
    def select_test_tools(self) -> Dict[str, Any]:
        """
        Select best testing tools for current project.
        
        Returns:
            Dict with primary tool, fallback, and command
        """
        # Check for existing test config
        existing_config = self._find_existing_test_config()
        if existing_config:
            return self._select_by_existing_config(existing_config)
        
        # Detect project type
        project_type = self._detect_project_type()
        return self._select_by_project_type(project_type)
    
    def _find_existing_test_config(self) -> Optional[str]:
        """Find existing test configuration files."""
        config_files = [
            'jest.config.js', 'jest.config.ts', 'vitest.config.js',
            'vitest.config.ts', '.mocharc.js', '.mocharc.json',
            'pytest.ini', 'setup.cfg', 'pyproject.toml', 'pom.xml'
        ]
        
        for config in config_files:
            if os.path.exists(os.path.join(self.workspace_path, config)):
                return config
        
        # Check package.json for test scripts
        package_json = os.path.join(self.workspace_path, 'package.json')
        if os.path.exists(package_json):
            try:
                with open(package_json, 'r') as f:
                    data = json.load(f)
                    if data.get('scripts', {}).get('test'):
                        return 'package.json'
            except:
                pass
        
        return None
    
    def _detect_project_type(self) -> str:
        """Detect project type based on files."""
        files = os.listdir(self.workspace_path)
        
        if 'package.json' in files:
            # Check for React
            try:
                with open(os.path.join(self.workspace_path, 'package.json'), 'r') as f:
                    data = json.load(f)
                    deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
                    if 'react' in deps:
                        return 'react'
            except:
                pass
            return 'nodejs'
        
        if any(f in files for f in ['requirements.txt', 'pyproject.toml', 'setup.py']):
            return 'python'
        
        if any(f in files for f in ['pom.xml', 'build.gradle']):
            return 'java'
        
        return 'unknown'
    
    def _select_by_existing_config(self, config_file: str) -> Dict[str, Any]:
        """Select tools based on existing configuration."""
        tool_map = {
            'jest.config.js': 'jest',
            'jest.config.ts': 'jest',
            'vitest.config.js': 'vitest',
            'vitest.config.ts': 'vitest',
            'pytest.ini': 'pytest',
            'setup.cfg': 'pytest',
            'pom.xml': 'junit'
        }
        
        tool_name = tool_map.get(config_file, 'jest')
        primary = self.tool_registry.get(tool_name)
        
        # Find fallback
        fallback = None
        for name, tool in self.tool_registry.items():
            if name != tool_name and tool.languages == primary.languages:
                fallback = tool
                break
        
        return {
            'primary': primary,
            'fallback': fallback,
            'command': primary.command if primary else 'npm test'
        }
    
    def _select_by_project_type(self, project_type: str) -> Dict[str, Any]:
        """Select tools based on project type."""
        if project_type in ['nodejs', 'react']:
            return {
                'primary': self.tool_registry['jest'],
                'fallback': self.tool_registry['vitest'],
                'command': 'npm test -- --coverage'
            }
        elif project_type == 'python':
            return {
                'primary': self.tool_registry['pytest'],
                'fallback': self.tool_registry['unittest'],
                'command': 'pytest -v --cov'
            }
        elif project_type == 'java':
            return {
                'primary': self.tool_registry['junit'],
                'fallback': None,
                'command': 'mvn test'
            }
        else:
            return {
                'primary': self.tool_registry['jest'],
                'fallback': None,
                'command': 'npm test'
            }


class TestExecutionPipeline:
    """
    Pipeline for executing tests and analyzing results.
    """
    
    def __init__(self, workspace_path: str = "."):
        self.workspace_path = workspace_path
        self.tool_selector = TestToolSelector(workspace_path)
        log.info("TestExecutionPipeline initialized")
    
    def create_test_plan(self, code: str, requirements: List[str]) -> TestPlan:
        """
        Create a test plan based on code and requirements.
        
        This is a simplified version. In production, this would use LLM.
        """
        test_cases = []
        
        # Basic heuristic: create test cases based on functions
        import re
        functions = re.findall(r'def\s+(\w+)|function\s+(\w+)', code)
        
        for func_match in functions[:5]:  # Limit to 5 functions
            func_name = func_match[0] or func_match[1]
            test_cases.append(TestCase(
                name=f'{func_name} works correctly',
                description=f'Test that {func_name} returns expected results',
                type=TestType.UNIT,
                priority='high'
            ))
        
        # Add edge case tests
        test_cases.append(TestCase(
            name='Edge cases handled',
            description='Test edge cases and error conditions',
            type=TestType.UNIT,
            priority='medium'
        ))
        
        return TestPlan(
            test_cases=test_cases,
            coverage_target=80,
            estimated_time=len(test_cases) * 5
        )
    
    def build_test_command(self, test_type: str = 'unit') -> str:
        """Build command to execute tests."""
        tools = self.tool_selector.select_test_tools()
        base_command = tools['command']
        
        if test_type == 'unit':
            return base_command
        elif test_type == 'integration':
            return f"{base_command} --testNamePattern='integration'"
        elif test_type == 'e2e':
            return f"{base_command} --testNamePattern='e2e'"
        
        return base_command
    
    def analyze_results(self, output: str, error: str = "") -> TestAnalysis:
        """
        Analyze test execution output.
        
        This is a simplified parser. Production would use more sophisticated parsing.
        """
        # Simple heuristic parsing
        passed = output.count('PASS') + output.count('passed')
        failed = output.count('FAIL') + output.count('failed')
        
        all_passed = failed == 0 and 'FAIL' not in output
        
        failures = []
        if error:
            failures.append(TestResult(
                name='Execution Error',
                passed=False,
                error=error,
                type='execution'
            ))
        
        return TestAnalysis(
            all_passed=all_passed,
            passed_count=passed,
            failed_count=failed,
            failures=failures
        )


# Convenience functions
def get_testing_decision_engine() -> TestingDecisionEngine:
    """Get singleton instance of TestingDecisionEngine."""
    return TestingDecisionEngine()


def should_test(code_changes: List[Dict], user_message: str = "") -> TestingDecision:
    """Quick function to check if testing is needed."""
    engine = get_testing_decision_engine()
    return engine.should_write_tests(code_changes, user_message)


def get_test_tools(workspace_path: str = ".") -> Dict[str, Any]:
    """Quick function to get test tools for workspace."""
    selector = TestToolSelector(workspace_path)
    return selector.select_test_tools()
