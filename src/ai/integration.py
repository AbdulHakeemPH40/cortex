"""
Integration module for Phase 1, 2, 3 systems
Connects Intent Classification, Agent Routing, Tool Selection, and Permission System
to the existing AI Agent and Chat UI
"""

import asyncio
from typing import Optional, Dict, Any, List
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from src.ai.intent import classify_intent, get_intent_classifier
from src.ai.router import get_agent_router, AgentContext
from src.ai.tools.selection import get_tool_selector, ToolSelectionContext
from src.ai.permission import (
    get_permission_manager, PermissionType, PermissionScope
)
from src.ui.components.permission import get_permission_card_renderer
from src.ai.testing import (
    get_testing_decision_engine, TestExecutionPipeline,
    TestingDecision, TestType
)
from src.utils.logger import get_logger

log = get_logger("ai_integration")


class AIIntegrationLayer(QObject):
    """
    Integration layer that connects new AI systems to the existing chat flow.
    
    Flow:
    1. User sends message
    2. Classify intent
    3. Route to appropriate agent
    4. Select tools
    5. Check permissions
    6. Execute with permission cards if needed
    """
    
    # Signals for UI communication
    intent_classified = pyqtSignal(str, str, float)  # message, intent, confidence
    agent_selected = pyqtSignal(str, str, str)  # agent_type, reason, confidence
    tools_selected = pyqtSignal(list)  # list of tool names
    permission_requested = pyqtSignal(str, str)  # request_id, html_card
    permission_granted = pyqtSignal(str, str)  # request_id, scope
    permission_denied = pyqtSignal(str, str)  # request_id, reason
    
    # Testing workflow signals
    testing_decision = pyqtSignal(str, str, str)  # decision, priority, trigger
    test_tools_selected = pyqtSignal(list)  # list of test tool names
    test_execution_started = pyqtSignal(str)  # test_type
    test_execution_completed = pyqtSignal(bool, int, int)  # all_passed, passed_count, failed_count
    test_analysis_ready = pyqtSignal(dict)  # analysis results
    
    # User denied workflow signal
    user_denied_workflow = pyqtSignal(str)  # tool_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Initialize all systems
        self._intent_classifier = get_intent_classifier()
        self._agent_router = get_agent_router()
        self._tool_selector = get_tool_selector()
        self._permission_manager = get_permission_manager()
        self._card_renderer = get_permission_card_renderer()
        
        # Initialize testing workflow
        self._testing_decision_engine = get_testing_decision_engine()
        self._test_execution_pipeline = None  # Created per workspace
        
        # State
        self._session_id = "default-session"
        self._workspace_path = None
        self._pending_permission_requests = {}  # request_id -> callback
        self._testing_results = {}  # Store testing results
        
        # Track denials per tool for stopping AI on repeated denial
        self._tool_denial_counts = {}  # tool_name -> denial count
        self._max_denial_count = 2  # Stop AI after 2 denials
        
        log.info("AIIntegrationLayer initialized")
    
    def set_session(self, session_id: str, workspace_path: Optional[str] = None):
        """Set session context."""
        self._session_id = session_id
        self._workspace_path = workspace_path
        log.info(f"Session set: {session_id}, workspace: {workspace_path}")
    
    async def process_message(self, message: str, code_context: str = "") -> Dict[str, Any]:
        """
        Process a user message through all AI systems.
        
        Returns:
            Dictionary with processing results:
            {
                "intent": intent_classification,
                "route": agent_route,
                "tools": selected_tools,
                "permissions": permission_status,
                "can_proceed": bool
            }
        """
        log.info(f"Processing message: {message[:50]}...")
        
        result = {
            "intent": None,
            "route": None,
            "tools": [],
            "permissions": {},
            "can_proceed": True,
            "requires_permission_ui": False,
            "permission_html": None
        }
        
        # Step 1: Classify intent
        intent = self._intent_classifier.classify(message)
        result["intent"] = intent
        
        self.intent_classified.emit(
            message, 
            intent.primary_intent.value, 
            intent.confidence
        )
        
        log.info(f"Intent: {intent.primary_intent.value} (confidence: {intent.confidence:.2f})")
        
        # Step 2: Route to agent
        agent_context = AgentContext(
            session_id=self._session_id,
            workspace_path=self._workspace_path
        )
        
        route = await self._agent_router.route(message, agent_context)
        result["route"] = route
        
        self.agent_selected.emit(
            route.agent_type.value,
            route.routing_reason,
            route.confidence
        )
        
        log.info(f"Routed to: {route.agent_type.value} (confidence: {route.confidence:.2f})")
        
        # Step 3: Select tools
        tool_context = ToolSelectionContext(
            workspace_path=self._workspace_path,
            has_open_files=True  # TODO: Get actual state
        )
        
        selected_tools = await self._tool_selector.select_tools(
            intent, tool_context, max_tools=3
        )
        
        result["tools"] = selected_tools
        tool_names = [t.tool.name for t in selected_tools]
        self.tools_selected.emit(tool_names)
        
        log.info(f"Selected tools: {tool_names}")
        
        # Step 4: Check permissions for selected tools
        permission_checks = []
        for tool_score in selected_tools:
            tool = tool_score.tool
            
            # Determine permission type based on tool category
            if tool.category.value == "system":
                perm_type = PermissionType.TERMINAL
            elif tool.category.value == "file":
                perm_type = PermissionType.FILESYSTEM
            elif tool.category.value == "web":
                perm_type = PermissionType.NETWORK
            else:
                continue
            
            # Check permission
            check_result = self._permission_manager.check_permission(
                session_id=self._session_id,
                tool=tool.name,
                permission_type=perm_type,
                requested_access=tool.required_permissions or ["execute"]
            )
            
            permission_checks.append({
                "tool": tool.name,
                "type": perm_type.value,
                "granted": check_result.granted,
                "result": check_result
            })
            
            if not check_result.granted:
                result["can_proceed"] = False
                
                # Create permission request
                request = self._permission_manager.request_permission(
                    session_id=self._session_id,
                    tool=tool.name,
                    permission_type=perm_type,
                    requested_access=tool.required_permissions or ["execute"]
                )
                
                # Create permission card
                card_data = self._permission_manager.create_permission_card(request)
                html = self._card_renderer.render(card_data)
                
                result["requires_permission_ui"] = True
                result["permission_html"] = html
                result["permission_request_id"] = request.id
                
                # Store callback for later
                self._pending_permission_requests[request.id] = {
                    "tool": tool.name,
                    "perm_type": perm_type,
                    "callback": None
                }
                
                self.permission_requested.emit(request.id, html)
                
                log.info(f"Permission requested for {tool.name}")
        
        result["permissions"] = permission_checks
        
        return result
    
    def grant_permission(self, request_id: str, scope: str = "session", remember: bool = False):
        """Grant a pending permission request."""
        scope_enum = PermissionScope(scope)
        
        # Determine duration based on remember flag
        duration_hours = None
        if remember and scope == "global":
            duration_hours = 24 * 30  # 30 days for "Always" with remember
        
        grant = self._permission_manager.grant_permission(
            request_id=request_id,
            scope=scope_enum,
            duration_hours=duration_hours
        )
        
        if grant:
            self.permission_granted.emit(request_id, scope)
            log.info(f"Permission granted: {request_id} (scope: {scope}, remember: {remember})")
            
            # Remove from pending
            if request_id in self._pending_permission_requests:
                del self._pending_permission_requests[request_id]
            
            return True
        
        return False
    
    def deny_permission(self, request_id: str, reason: str = ""):
        """Deny a pending permission request."""
        self._permission_manager.deny_permission(request_id, reason)
        self.permission_denied.emit(request_id, reason)
        
        # Track denial count for this tool
        pending_req = self._pending_permission_requests.get(request_id, {})
        tool_name = pending_req.get("tool", "unknown")
        
        self._tool_denial_counts[tool_name] = self._tool_denial_counts.get(tool_name, 0) + 1
        denial_count = self._tool_denial_counts[tool_name]
        
        log.info(f"Permission denied: {request_id} ({reason}) - tool: {tool_name}, denial count: {denial_count}")
        
        # Remove from pending
        if request_id in self._pending_permission_requests:
            del self._pending_permission_requests[request_id]
        
        # Stop AI if user denied twice
        if denial_count >= self._max_denial_count:
            log.warning(f"User denied {tool_name} {denial_count} times - signaling AI to stop")
            self.user_denied_workflow.emit(tool_name)
    
    def analyze_command_safety(self, command: str) -> Dict[str, Any]:
        """Analyze a command for safety."""
        analysis = self._permission_manager.analyze_command(command)
        
        return {
            "command": command,
            "safety": analysis.safety.value,
            "requires_confirmation": analysis.requires_confirmation,
            "explanation": analysis.explanation,
            "patterns": analysis.patterns_detected
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get integration statistics."""
        return {
            "intent_classifier": {
                "recent_classifications": len(self._intent_classifier.get_recent_classifications())
            },
            "tool_selector": self._tool_selector.get_stats(),
            "pending_permissions": len(self._pending_permission_requests)
        }
    
    # ========== TESTING WORKFLOW METHODS ==========
    
    def analyze_testing_need(self, code_changes: List[Dict], user_message: str = "") -> TestingDecision:
        """
        Analyze if testing is needed based on code changes and user message.
        
        Args:
            code_changes: List of code changes (file path, content, type)
            user_message: User's message/query
            
        Returns:
            TestingDecision with action and metadata
        """
        decision = self._testing_decision_engine.should_write_tests(code_changes, user_message)
        
        # Emit signal for UI
        self.testing_decision.emit(
            decision.decision,
            decision.priority.value if decision.priority else "none",
            decision.trigger or decision.reason or "unknown"
        )
        
        log.info(f"Testing decision: {decision.decision} (priority: {decision.priority}, trigger: {decision.trigger})")
        
        return decision
    
    def get_test_tools_for_workspace(self) -> Dict[str, Any]:
        """
        Get testing tools for the current workspace.
        
        Returns:
            Dict with primary tool, fallback, and command
        """
        if not self._test_execution_pipeline:
            self._test_execution_pipeline = TestExecutionPipeline(self._workspace_path or ".")
        
        tools = self._test_execution_pipeline.tool_selector.select_test_tools()
        
        # Emit signal
        if tools.get('primary'):
            self.test_tools_selected.emit([tools['primary'].name])
        
        return tools
    
    def create_test_plan(self, code: str, requirements: List[str]) -> Dict[str, Any]:
        """
        Create a test plan for the given code.
        
        Args:
            code: Source code to test
            requirements: List of requirements/test scenarios
            
        Returns:
            Test plan as dictionary
        """
        if not self._test_execution_pipeline:
            self._test_execution_pipeline = TestExecutionPipeline(self._workspace_path or ".")
        
        plan = self._test_execution_pipeline.create_test_plan(code, requirements)
        
        return {
            "test_cases": [
                {
                    "name": tc.name,
                    "description": tc.description,
                    "type": tc.type.value,
                    "priority": tc.priority
                }
                for tc in plan.test_cases
            ],
            "coverage_target": plan.coverage_target,
            "estimated_time": plan.estimated_time
        }
    
    def execute_test_cycle(self, test_type: str = "unit") -> Dict[str, Any]:
        """
        Execute a test cycle.
        
        Args:
            test_type: Type of tests to run (unit, integration, e2e)
            
        Returns:
            Test execution results
        """
        self.test_execution_started.emit(test_type)
        
        if not self._test_execution_pipeline:
            self._test_execution_pipeline = TestExecutionPipeline(self._workspace_path or ".")
        
        # Get test command
        command = self._test_execution_pipeline.build_test_command(test_type)
        
        # For now, return command info (actual execution would be async)
        result = {
            "command": command,
            "test_type": test_type,
            "status": "ready",
            "message": f"Test command prepared: {command}"
        }
        
        log.info(f"Test execution prepared: {test_type} - {command}")
        
        return result
    
    def analyze_test_results(self, output: str, error: str = "") -> Dict[str, Any]:
        """
        Analyze test execution results.
        
        Args:
            output: Test output (stdout)
            error: Test error output (stderr)
            
        Returns:
            Analysis results
        """
        if not self._test_execution_pipeline:
            self._test_execution_pipeline = TestExecutionPipeline(self._workspace_path or ".")
        
        analysis = self._test_execution_pipeline.analyze_results(output, error)
        
        # Emit signals
        self.test_execution_completed.emit(
            analysis.all_passed,
            analysis.passed_count,
            analysis.failed_count
        )
        
        result = {
            "all_passed": analysis.all_passed,
            "passed_count": analysis.passed_count,
            "failed_count": analysis.failed_count,
            "failures": [
                {
                    "name": f.name,
                    "error": f.error,
                    "type": f.type
                }
                for f in analysis.failures
            ],
            "patterns": analysis.patterns,
            "suggestions": analysis.suggestions
        }
        
        self.test_analysis_ready.emit(result)
        
        return result
    
    def should_trigger_tests(self, intent_classification: Any) -> bool:
        """
        Check if tests should be triggered based on intent.
        
        Args:
            intent_classification: Intent classification result
            
        Returns:
            True if tests should be triggered
        """
        # Trigger tests for code generation and debugging intents
        test_triggering_intents = [
            "code_generation",
            "debugging",
            "refactoring",
            "file_modification"
        ]
        
        if hasattr(intent_classification, 'primary_intent'):
            return intent_classification.primary_intent.value in test_triggering_intents
        
        return False


# Singleton instance
_integration_layer = None


def get_ai_integration_layer() -> AIIntegrationLayer:
    """Get singleton instance of AIIntegrationLayer."""
    global _integration_layer
    if _integration_layer is None:
        _integration_layer = AIIntegrationLayer()
    return _integration_layer
