"""
Decision Framework for Cortex IDE AI Agent
Analysis-first approach matching human developer workflow
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from src.utils.logger import get_logger

log = get_logger("decision_framework")


class IssuePriority(Enum):
    CRITICAL = "critical"      # Crashes, infinite loops, data loss
    PERFORMANCE = "performance"  # Slow, memory leaks, UI lag
    FEATURE = "feature"        # New capabilities
    REFACTOR = "refactor"      # Code cleanup


class ActionType(Enum):
    ANALYZE = "analyze"        # Gather evidence
    VERIFY = "verify"          # Check if fix worked
    FIX = "fix"                # Apply fix
    TEST = "test"              # Run tests
    PLAN = "plan"              # Create action plan


@dataclass
class AnalysisResult:
    """Result of problem analysis phase"""
    issue_type: str = "unknown"
    root_cause: str = ""
    affected_files: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 to 1.0
    
    def to_prompt(self) -> str:
        """Convert to system prompt format"""
        lines = [
            "## ANALYSIS RESULT",
            f"Issue Type: {self.issue_type}",
            f"Root Cause: {self.root_cause}",
            f"Confidence: {self.confidence:.0%}",
            "",
            "### Affected Files",
        ]
        for f in self.affected_files:
            lines.append(f"- {f}")
        lines.extend(["", "### Evidence"])
        for e in self.evidence:
            lines.append(f"- {e}")
        return "\n".join(lines)


@dataclass
class ActionStep:
    """Single step in action plan"""
    step_number: int
    action_type: ActionType
    description: str
    target_file: Optional[str] = None
    verification_method: str = ""
    completed: bool = False
    result: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "step": self.step_number,
            "type": self.action_type.value,
            "description": self.description,
            "target": self.target_file,
            "verify": self.verification_method,
            "completed": self.completed,
            "result": self.result
        }


@dataclass
class DecisionLog:
    """Log of why decisions were made"""
    timestamp: str
    context: str
    decision: str
    reasoning: str
    alternatives_considered: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "context": self.context,
            "decision": self.decision,
            "reasoning": self.reasoning,
            "alternatives": self.alternatives_considered
        }


class DecisionFramework:
    """
    Analysis-first decision framework for AI agent.
    
    Workflow:
    1. GATHER - Collect evidence (logs, error traces, code)
    2. ANALYZE - Determine root cause and priority
    3. PLAN - Create step-by-step action plan
    4. EXECUTE - Perform actions with verification
    5. VERIFY - Confirm fix worked
    """
    
    def __init__(self, project_root: str = ""):
        self.project_root = project_root
        self.current_analysis: Optional[AnalysisResult] = None
        self.action_plan: List[ActionStep] = []
        self.decision_logs: List[DecisionLog] = []
        self.current_step: int = 0
        
    def gather_evidence(self, error_message: str = "", context: str = "") -> Dict[str, Any]:
        """
        Phase 1: Gather all relevant evidence
        """
        evidence = {
            "error_message": error_message,
            "context": context,
            "logs": [],
            "recent_files": [],
            "suggested_files": []
        }
        
        # Auto-read error logs if they exist
        log_files = [
            "error.log",
            "app.log",
            "debug.log",
            os.path.join(self.project_root, "error.log") if self.project_root else ""
        ]
        
        for log_file in log_files:
            if log_file and os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        # Get last 50 lines
                        evidence["logs"].extend(lines[-50:])
                        log.info(f"Auto-read log file: {log_file}")
                except Exception as e:
                    log.warning(f"Could not read log {log_file}: {e}")
        
        # Extract file paths from error message
        if error_message:
            import re
            # Match common file path patterns
            file_patterns = [
                r'File "([^"]+)"',  # Python traceback
                r'at ([^\s:]+\.\w+):(\d+)',  # Generic stack trace
                r'([\w/\\]+\.py)[\s:]*line',  # Alternative format
            ]
            for pattern in file_patterns:
                matches = re.findall(pattern, error_message)
                for match in matches:
                    if isinstance(match, tuple):
                        filepath = match[0]
                    else:
                        filepath = match
                    if filepath not in evidence["suggested_files"]:
                        evidence["suggested_files"].append(filepath)
        
        return evidence
    
    def analyze_problem(self, evidence: Dict[str, Any]) -> AnalysisResult:
        """
        Phase 2: Analyze evidence to determine root cause
        """
        analysis = AnalysisResult()
        
        # Determine issue type from evidence
        error_msg = evidence.get("error_message", "").lower()
        
        if any(x in error_msg for x in ["crash", "exception", "error", "traceback", "nameerror", "importerror"]):
            analysis.issue_type = "runtime_error"
            analysis.priority = IssuePriority.CRITICAL
        elif any(x in error_msg for x in ["infinite", "loop", "hang", "stuck", "timeout"]):
            analysis.issue_type = "infinite_loop"
            analysis.priority = IssuePriority.CRITICAL
        elif any(x in error_msg for x in ["slow", "lag", "memory", "performance"]):
            analysis.issue_type = "performance"
            analysis.priority = IssuePriority.PERFORMANCE
        elif any(x in error_msg for x in ["blank", "not showing", "not working", "empty"]):
            analysis.issue_type = "ui_issue"
            analysis.priority = IssuePriority.CRITICAL
        else:
            analysis.issue_type = "unknown"
            analysis.priority = IssuePriority.FEATURE
        
        # Collect affected files
        analysis.affected_files = evidence.get("suggested_files", [])
        
        # Build evidence list
        analysis.evidence = [
            f"Error: {evidence.get('error_message', 'N/A')[:200]}",
            f"Context: {evidence.get('context', 'N/A')[:200]}",
            f"Log entries: {len(evidence.get('logs', []))}",
        ]
        
        # Confidence based on evidence quality
        if analysis.affected_files and evidence.get("logs"):
            analysis.confidence = 0.9
        elif analysis.affected_files:
            analysis.confidence = 0.7
        else:
            analysis.confidence = 0.5
        
        self.current_analysis = analysis
        
        # Log the decision
        self._log_decision(
            context=f"Analyzing: {error_msg[:100]}",
            decision=f"Classified as {analysis.issue_type} with {analysis.priority.value} priority",
            reasoning=f"Based on error message patterns and {len(analysis.affected_files)} affected files"
        )
        
        return analysis
    
    def create_action_plan(self, analysis: AnalysisResult) -> List[ActionStep]:
        """
        Phase 3: Create step-by-step action plan
        """
        plan = []
        step_num = 1
        
        # Step 1: Always read affected files first
        for filepath in analysis.affected_files[:3]:  # Limit to top 3
            plan.append(ActionStep(
                step_number=step_num,
                action_type=ActionType.ANALYZE,
                description=f"Read and analyze {filepath}",
                target_file=filepath,
                verification_method=f"Confirm file exists and contains relevant code"
            ))
            step_num += 1
        
        # Step 2: Based on issue type, add specific fix steps
        if analysis.issue_type == "runtime_error":
            plan.append(ActionStep(
                step_number=step_num,
                action_type=ActionType.FIX,
                description=f"Fix the root cause: {analysis.root_cause}",
                verification_method="Verify no syntax errors and imports work"
            ))
            step_num += 1
            
        elif analysis.issue_type == "infinite_loop":
            plan.append(ActionStep(
                step_number=step_num,
                action_type=ActionType.FIX,
                description="Add iteration limits and proper exit conditions",
                verification_method="Test that loop exits after max iterations"
            ))
            step_num += 1
            
        elif analysis.issue_type == "ui_issue":
            plan.append(ActionStep(
                step_number=step_num,
                action_type=ActionType.FIX,
                description="Fix UI rendering or initialization",
                verification_method="Verify UI displays correctly in both dev and bundled mode"
            ))
            step_num += 1
        
        # Step 3: Always verify the fix
        plan.append(ActionStep(
            step_number=step_num,
            action_type=ActionType.VERIFY,
            description="Verify the fix resolves the issue",
            verification_method="Test the exact scenario that was failing"
        ))
        
        self.action_plan = plan
        self.current_step = 0
        
        # Log the plan creation
        self._log_decision(
            context=f"Creating plan for {analysis.issue_type}",
            decision=f"Created {len(plan)} step plan",
            reasoning=f"Based on priority {analysis.priority.value} and {len(analysis.affected_files)} files"
        )
        
        return plan
    
    def get_next_action(self) -> Optional[ActionStep]:
        """
        Get the next action to execute
        """
        if self.current_step < len(self.action_plan):
            action = self.action_plan[self.current_step]
            self.current_step += 1
            return action
        return None
    
    def mark_step_completed(self, step_number: int, result: str):
        """
        Mark a step as completed with result
        """
        for step in self.action_plan:
            if step.step_number == step_number:
                step.completed = True
                step.result = result
                log.info(f"Step {step_number} completed: {result[:100]}")
                break
    
    def should_continue(self) -> bool:
        """
        Determine if we should continue with next action
        """
        return self.current_step < len(self.action_plan)
    
    def get_plan_summary(self) -> str:
        """
        Get human-readable plan summary
        """
        lines = ["## ACTION PLAN", ""]
        for step in self.action_plan:
            status = "✓" if step.completed else "○"
            lines.append(f"{status} Step {step.step_number}: [{step.action_type.value.upper()}] {step.description}")
            if step.target_file:
                lines.append(f"   Target: {step.target_file}")
            if step.completed and step.result:
                lines.append(f"   Result: {step.result[:100]}")
        return "\n".join(lines)
    
    def _log_decision(self, context: str, decision: str, reasoning: str):
        """
        Log why a decision was made
        """
        from datetime import datetime
        log_entry = DecisionLog(
            timestamp=datetime.now().isoformat(),
            context=context,
            decision=decision,
            reasoning=reasoning
        )
        self.decision_logs.append(log_entry)
        log.info(f"[DECISION] {decision} | Reason: {reasoning}")
    
    def to_system_prompt(self) -> str:
        """
        Convert current state to system prompt addition
        """
        parts = []
        
        if self.current_analysis:
            parts.append(self.current_analysis.to_prompt())
        
        if self.action_plan:
            parts.append(self.get_plan_summary())
        
        return "\n\n".join(parts)


# Singleton instance for the agent
_framework_instance: Optional[DecisionFramework] = None


def get_decision_framework(project_root: str = "") -> DecisionFramework:
    """Get or create decision framework instance"""
    global _framework_instance
    if _framework_instance is None:
        _framework_instance = DecisionFramework(project_root)
    return _framework_instance


def reset_decision_framework():
    """Reset the framework (call when starting new task)"""
    global _framework_instance
    _framework_instance = None
