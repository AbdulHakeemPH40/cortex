"""
Enhanced AI Agent with Task Queue and Project Warmup
Integrates task management, project analysis, and progress tracking
"""

import os
import json
import re
from pathlib import Path
from typing import Optional, Dict, List, Any
from PyQt6.QtCore import QObject, pyqtSignal

from src.ai.agent import AIAgent, AIWorker
from src.ai.task_queue import TaskQueue, Task, TaskStatus, TaskPriority, get_task_queue, TaskStep
from src.ai.project_analyzer import ProjectAnalyzer, get_project_analyzer
from src.ai.providers import get_provider_registry, ProviderType, ChatMessage
from src.config.settings import get_settings
from src.utils.logger import get_logger

log = get_logger("enhanced_agent")


class EnhancedAIAgent(AIAgent):
    """
    Enhanced AI Agent with task queue, project warmup, and progress tracking
    
    New Features:
    - Task queuing with priorities
    - Project warmup on greeting
    - Progress visualization
    - Step-by-step execution
    - Completion tracking
    """
    
    # New signals for enhanced functionality
    task_progress = pyqtSignal(str, str, int)  # task_id, step_name, percentage
    task_step_completed = pyqtSignal(str, str, str)  # task_id, step_name, result
    task_completed = pyqtSignal(str, str)  # task_id, summary
    task_failed = pyqtSignal(str, str)  # task_id, error
    task_cancelled = pyqtSignal(str)  # task_id
    queue_status_changed = pyqtSignal(int)  # queue_length
    current_task_changed = pyqtSignal(str)  # task_id
    
    # Greeting patterns that trigger project warmup
    GREETING_PATTERNS = [
        r'^\s*(hi|hello|hey|greetings|howdy|yo)\s*$',
        r'^\s*(hi|hello|hey)\s+(there|cortex|ai)\s*$',
        r'^\s*(good\s+(morning|afternoon|evening))\s*$',
        r'^\s*(what\s+is\s+this\s+project|analyze\s+project|warmup|warm\s+up)\s*$',
        r'^\s*(start|begin|init)\s*$',
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Initialize task queue
        self._task_queue = get_task_queue(self)
        self._setup_task_queue_signals()
        
        # Project analysis cache
        self._project_analysis: Optional[ProjectAnalyzer] = None
        self._warmup_completed = False
        
        # Current task tracking
        self._current_task_id: Optional[str] = None
        self._is_processing_warmup = False
        
        log.info("Enhanced AI Agent initialized")
    
    def _setup_task_queue_signals(self):
        """Connect task queue signals to agent signals"""
        self._task_queue.task_progress.connect(
            lambda tid, step, pct: self.task_progress.emit(tid, step, pct)
        )
        self._task_queue.task_step_completed.connect(
            lambda tid, step, res: self.task_step_completed.emit(tid, step, res)
        )
        self._task_queue.task_completed.connect(
            lambda tid, summary: self._on_task_completed(tid, summary)
        )
        self._task_queue.task_failed.connect(
            lambda tid, error: self._on_task_failed(tid, error)
        )
        self._task_queue.task_cancelled.connect(
            lambda tid: self._on_task_cancelled(tid)
        )
        self._task_queue.queue_updated.connect(
            lambda length: self.queue_status_changed.emit(length)
        )
        self._task_queue.current_task_changed.connect(
            lambda tid: self._on_current_task_changed(tid)
        )
    
    def chat(self, user_message: Optional[str], code_context: str = ""):
        """
        Enhanced chat with task queuing and project warmup
        
        Args:
            user_message: User's message (None to continue without new message)
            code_context: Current code context from editor
        """
        if user_message is None:
            # Continue existing task
            super().chat(None, code_context)
            return
        
        # Check if it's a greeting that should trigger warmup
        if self._is_greeting(user_message) and not self._warmup_completed:
            self._handle_project_warmup()
            return
        
        # Check if it's a stop request during task execution
        if self._is_stop_request(user_message):
            self.stop_current_task()
            return
        
        # Add task to queue
        context = {
            "code_context": code_context,
            "project_root": self._project_root,
            "mode": self._mode
        }
        
        task_id = self._task_queue.enqueue(
            prompt=user_message,
            priority=TaskPriority.NORMAL,
            context=context
        )
        
        log.info(f"Task {task_id} added to queue: {user_message[:50]}...")
        
        # Start processing if not already running
        if not self._task_queue.is_busy():
            self._task_queue.start_processing()
        else:
            # Emit message that task is queued
            self.response_chunk.emit(f"📋 Task queued (position: {self._task_queue.get_queue_position(task_id)})")
    
    def _is_greeting(self, message: str) -> bool:
        """Check if message is a greeting"""
        message_lower = message.lower().strip()
        for pattern in self.GREETING_PATTERNS:
            if re.match(pattern, message_lower):
                return True
        return False
    
    def _is_stop_request(self, message: str) -> bool:
        """Check if message is a stop/cancel request"""
        stop_patterns = [
            r'^\s*(stop|cancel|abort|halt|quit)\s*$',
            r'^\s*(stop|cancel)\s+(current|this|now)\s*$',
        ]
        message_lower = message.lower().strip()
        for pattern in stop_patterns:
            if re.match(pattern, message_lower):
                return True
        return False
    
    def _handle_project_warmup(self):
        """Perform project warmup and analysis"""
        if not self._project_root:
            self.response_chunk.emit("⚠️ No project is currently open. Please open a project first.")
            self.response_complete.emit("No project open")
            return
        
        if self._is_processing_warmup:
            return
        
        self._is_processing_warmup = True
        
        # Create a special warmup task
        task_id = self._task_queue.enqueue(
            prompt="__WARMUP__",
            priority=TaskPriority.HIGH,
            context={"project_root": self._project_root, "is_warmup": True}
        )
        
        log.info(f"Warmup task {task_id} created")
        self._task_queue.start_processing()
    
    def _on_current_task_changed(self, task_id: str):
        """Handle task switching"""
        self._current_task_id = task_id if task_id else None
        
        if task_id:
            task = self._task_queue.get_task(task_id)
            if task:
                if task.user_prompt == "__WARMUP__":
                    self._execute_warmup_task(task)
                else:
                    self._execute_regular_task(task)
    
    def _execute_warmup_task(self, task: Task):
        """Execute project warmup task"""
        log.info("Executing warmup task")
        
        # Add steps for warmup
        task.steps = [
            TaskStep(
                id=f"{task.id}_analyze",
                name="Analyzing Project",
                description="Scanning project structure and files"
            ),
            TaskStep(
                id=f"{task.id}_detect",
                name="Detecting Stack",
                description="Identifying technologies and frameworks"
            ),
            TaskStep(
                id=f"{task.id}_generate",
                name="Generating Report",
                description="Creating comprehensive project summary"
            ),
            TaskStep(
                id=f"{task.id}_present",
                name="Presenting Overview",
                description="Displaying project information"
            )
        ]
        
        # Start analysis
        self._task_queue.complete_current_step(result="Starting analysis")
        
        try:
            # Step 1: Analyze project
            analyzer = get_project_analyzer(self._project_root)
            self._project_analysis = analyzer
            
            # Mark step complete
            self._task_queue.complete_current_step(result="Project structure analyzed")
            
            # Step 2: Detect stack
            # (already done during analysis)
            self._task_queue.complete_current_step(result=f"Stack detected: {analyzer.analysis.project_type}")
            
            # Step 3: Generate report
            report = analyzer.generate_warmup_report()
            self._task_queue.complete_current_step(result="Report generated")
            
            # Step 4: Present
            self.response_chunk.emit(report)
            self.response_complete.emit("Warmup complete")
            
            self._task_queue.complete_current_step(result="Displayed to user")
            
            self._warmup_completed = True
            self._is_processing_warmup = False
            
        except Exception as e:
            log.error(f"Warmup failed: {e}")
            self._task_queue.complete_current_step(error=str(e))
            self._is_processing_warmup = False
    
    def _execute_regular_task(self, task: Task):
        """Execute regular user task"""
        log.info(f"Executing task: {task.user_prompt[:50]}...")
        
        # Analyze task and create steps
        self._analyze_and_create_steps(task)
        
        # Execute first step
        self._execute_task_step(task)
    
    def _analyze_and_create_steps(self, task: Task):
        """Analyze user prompt and create execution steps"""
        prompt = task.user_prompt.lower()
        
        # Determine intent and create appropriate steps
        if any(word in prompt for word in ['enhance', 'improve', 'refactor', 'optimize', 'better']):
            task.steps = self._create_enhancement_steps(task)
        elif any(word in prompt for word in ['implement', 'add', 'create', 'build', 'make']):
            task.steps = self._create_implementation_steps(task)
        elif any(word in prompt for word in ['fix', 'debug', 'error', 'bug', 'issue']):
            task.steps = self._create_debug_steps(task)
        elif any(word in prompt for word in ['test', 'testing', 'coverage']):
            task.steps = self._create_test_steps(task)
        elif any(word in prompt for word in ['explain', 'understand', 'what', 'how']):
            task.steps = self._create_explanation_steps(task)
        else:
            # Default single-step execution
            task.steps = [
                TaskStep(
                    id=f"{task.id}_execute",
                    name="Processing Request",
                    description=f"Executing: {task.user_prompt[:50]}..."
                )
            ]
    
    def _create_enhancement_steps(self, task: Task) -> List[TaskStep]:
        """Create steps for enhancement task"""
        return [
            TaskStep(
                id=f"{task.id}_analyze",
                name="Analyzing Current Code",
                description="Understanding existing implementation"
            ),
            TaskStep(
                id=f"{task.id}_identify",
                name="Identifying Improvements",
                description="Finding enhancement opportunities"
            ),
            TaskStep(
                id=f"{task.id}_plan",
                name="Creating Enhancement Plan",
                description="Designing improvements"
            ),
            TaskStep(
                id=f"{task.id}_implement",
                name="Implementing Changes",
                description="Applying enhancements",
                requires_confirmation=True
            ),
            TaskStep(
                id=f"{task.id}_verify",
                name="Verifying Changes",
                description="Checking implementation"
            )
        ]
    
    def _create_implementation_steps(self, task: Task) -> List[TaskStep]:
        """Create steps for implementation task"""
        return [
            TaskStep(
                id=f"{task.id}_clarify",
                name="Clarifying Requirements",
                description="Understanding what needs to be built"
            ),
            TaskStep(
                id=f"{task.id}_research",
                name="Researching Patterns",
                description="Finding similar implementations in codebase"
            ),
            TaskStep(
                id=f"{task.id}_design",
                name="Designing Solution",
                description="Planning implementation approach"
            ),
            TaskStep(
                id=f"{task.id}_implement",
                name="Implementing Feature",
                description="Writing code",
                requires_confirmation=True
            ),
            TaskStep(
                id=f"{task.id}_test",
                name="Adding Tests",
                description="Creating test coverage"
            ),
            TaskStep(
                id=f"{task.id}_document",
                name="Documenting",
                description="Adding documentation"
            )
        ]
    
    def _create_debug_steps(self, task: Task) -> List[TaskStep]:
        """Create steps for debugging task"""
        return [
            TaskStep(
                id=f"{task.id}_diagnose",
                name="Diagnosing Issue",
                description="Analyzing error and context"
            ),
            TaskStep(
                id=f"{task.id}_locate",
                name="Locating Root Cause",
                description="Finding source of problem"
            ),
            TaskStep(
                id=f"{task.id}_solution",
                name="Designing Fix",
                description="Planning solution"
            ),
            TaskStep(
                id=f"{task.id}_fix",
                name="Implementing Fix",
                description="Applying solution",
                requires_confirmation=True
            ),
            TaskStep(
                id=f"{task.id}_verify",
                name="Verifying Fix",
                description="Testing the solution"
            )
        ]
    
    def _create_test_steps(self, task: Task) -> List[TaskStep]:
        """Create steps for testing task"""
        return [
            TaskStep(
                id=f"{task.id}_analyze",
                name="Analyzing Code",
                description="Understanding what to test"
            ),
            TaskStep(
                id=f"{task.id}_identify",
                name="Identifying Test Cases",
                description="Determining test coverage"
            ),
            TaskStep(
                id=f"{task.id}_write",
                name="Writing Tests",
                description="Creating test code",
                requires_confirmation=True
            ),
            TaskStep(
                id=f"{task.id}_run",
                name="Running Tests",
                description="Executing test suite"
            )
        ]
    
    def _create_explanation_steps(self, task: Task) -> List[TaskStep]:
        """Create steps for explanation task"""
        return [
            TaskStep(
                id=f"{task.id}_read",
                name="Reading Code",
                description="Analyzing relevant files"
            ),
            TaskStep(
                id=f"{task.id}_understand",
                name="Understanding Logic",
                description="Comprehending implementation"
            ),
            TaskStep(
                id=f"{task.id}_explain",
                name="Generating Explanation",
                description="Creating clear explanation"
            )
        ]
    
    def _execute_task_step(self, task: Task):
        """Execute current step of task"""
        if task.current_step_index >= len(task.steps):
            # All steps complete
            return
        
        step = task.steps[task.current_step_index]
        
        # Check if step requires confirmation
        if step.requires_confirmation and not step.confirmed:
            self._request_step_confirmation(task, step)
            return
        
        # Execute step
        log.info(f"Task {task.id}: Executing step '{step.name}'")
        
        # Build context for AI
        context = self._build_step_context(task, step)
        
        # Call parent AI chat for this step
        super().chat(context, task.context.get("code_context", ""))
    
    def _build_step_context(self, task: Task, step: TaskStep) -> str:
        """Build context for the current step"""
        parts = [
            f"## Task: {task.user_prompt}",
            f"## Current Step: {step.name}",
            f"## Description: {step.description}",
            "",
            "### Progress:",
        ]
        
        # Add progress of previous steps
        for i, s in enumerate(task.steps[:task.current_step_index]):
            status = "✅" if s.status == TaskStatus.COMPLETED else "❌"
            parts.append(f"{status} {i+1}. {s.name}")
        
        parts.append(f"🔄 {task.current_step_index+1}. {step.name} (Current)")
        
        for i in range(task.current_step_index+1, len(task.steps)):
            parts.append(f"⏳ {i+1}. {task.steps[i].name}")
        
        parts.append("")
        parts.append(f"### Instructions:")
        parts.append(f"Execute this step: {step.description}")
        parts.append(f"When complete, indicate completion clearly.")
        
        return "\n".join(parts)
    
    def _request_step_confirmation(self, task: Task, step: TaskStep):
        """Request user confirmation before executing step"""
        confirmation_msg = f"""
<permission>
[{{
    "name": "{step.name}",
    "info": "{step.description}"
}}]
</permission>
"""
        self.response_chunk.emit(confirmation_msg)
        self.response_complete.emit(f"Waiting for confirmation to: {step.name}")
    
    def _on_task_completed(self, task_id: str, summary: str):
        """Handle task completion"""
        log.info(f"Task {task_id} completed")
        self.task_completed.emit(task_id, summary)
        
        # Emit completion message
        completion_msg = f"""

---
✅ **Task Completed Successfully!**

{summary}

*Ready for your next request...*
"""
        self.response_chunk.emit(completion_msg)
        self.response_complete.emit("Task completed")
    
    def _on_task_failed(self, task_id: str, error: str):
        """Handle task failure"""
        log.error(f"Task {task_id} failed: {error}")
        self.task_failed.emit(task_id, error)
        self.request_error.emit(f"Task failed: {error}")
    
    def _on_task_cancelled(self, task_id: str):
        """Handle task cancellation"""
        log.info(f"Task {task_id} cancelled")
        self.task_cancelled.emit(task_id)
        self.response_chunk.emit("❌ Task cancelled by user")
        self.response_complete.emit("Task cancelled")
    
    def stop_current_task(self, graceful: bool = True):
        """Stop the current task"""
        log.info(f"Stopping current task (graceful={graceful})")
        
        if self._task_queue.stop_current(graceful):
            if graceful:
                self.response_chunk.emit("⏹️ Stopping after current step...")
            else:
                self.response_chunk.emit("⏹️ Stopping immediately...")
        else:
            log.warning("No task to stop")
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status for display"""
        return self._task_queue.get_queue_status()
    
    def get_project_summary(self) -> Optional[str]:
        """Get project summary if warmup is complete"""
        if self._project_analysis and self._warmup_completed:
            return self._project_analysis.generate_warmup_report()
        return None
    
    def is_busy(self) -> bool:
        """Check if agent is currently processing"""
        return self._task_queue.is_busy() or super().is_busy()


# Singleton instance
_enhanced_agent = None


def get_enhanced_ai_agent(parent=None) -> EnhancedAIAgent:
    """Get singleton enhanced AI agent"""
    global _enhanced_agent
    if _enhanced_agent is None:
        _enhanced_agent = EnhancedAIAgent(parent)
    return _enhanced_agent
