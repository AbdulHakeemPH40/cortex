"""
Task Planner - Breaks down prompts into actionable steps
Helps AI agents plan and execute tasks systematically
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from src.utils.logger import get_logger

log = get_logger("task_planner")


class TaskPriority(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskType(Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_EDIT = "file_edit"
    FILE_DELETE = "file_delete"
    COMMAND_RUN = "command_run"
    SEARCH = "search"
    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    DEBUG = "debug"
    DOCUMENTATION = "documentation"
    REFACTOR = "refactor"
    OTHER = "other"


@dataclass
class TaskStep:
    """A single step in a task plan."""
    id: int
    description: str
    task_type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    dependencies: List[int] = field(default_factory=list)
    estimated_complexity: str = "simple"  # simple, moderate, complex
    files_involved: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, completed, failed
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class TaskPlan:
    """A complete plan for executing a task."""
    id: str
    title: str
    description: str
    steps: List[TaskStep]
    context: str = ""
    estimated_steps: int = 0
    created_at: str = ""
    
    def get_pending_steps(self) -> List[TaskStep]:
        """Get all pending steps."""
        return [s for s in self.steps if s.status == "pending"]
    
    def get_next_step(self) -> Optional[TaskStep]:
        """Get the next step that can be executed."""
        for step in self.steps:
            if step.status == "pending":
                # Check if all dependencies are completed
                deps_completed = all(
                    self.get_step_by_id(dep).status == "completed"
                    for dep in step.dependencies
                    if self.get_step_by_id(dep)
                )
                if deps_completed:
                    return step
        return None
    
    def get_step_by_id(self, step_id: int) -> Optional[TaskStep]:
        """Get a step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
    
    def mark_step_completed(self, step_id: int, result: str = None):
        """Mark a step as completed."""
        step = self.get_step_by_id(step_id)
        if step:
            step.status = "completed"
            step.result = result
    
    def mark_step_failed(self, step_id: int, error: str):
        """Mark a step as failed."""
        step = self.get_step_by_id(step_id)
        if step:
            step.status = "failed"
            step.error = error


class TaskPlanner:
    """
    Plans and breaks down tasks into actionable steps.
    Analyzes user prompts and creates structured execution plans.
    """
    
    # Patterns for detecting task types
    TASK_PATTERNS = {
        TaskType.FILE_READ: [
            r'(?:read|show|display|view|open|check|see|inspect|examine|look at)\s+(?:the\s+)?(?:file|code|content)',
            r'what(?:\'s| is)\s+(?:in|inside|the content of)\s+(?:the\s+)?file',
            r'(?:file|code)\s+(?:content|read|show)',
        ],
        TaskType.FILE_WRITE: [
            r'(?:create|write|generate|make|add)\s+(?:a\s+)?(?:new\s+)?(?:file|script|module|class)',
            r'(?:save|store)\s+(?:to|as)\s+(?:a\s+)?(?:new\s+)?file',
        ],
        TaskType.FILE_EDIT: [
            r'(?:edit|modify|change|update|fix|update|refactor|rename)\s+(?:the\s+)?(?:file|code|function|class|method)',
            r'(?:add|insert|append)\s+(?:to|into)\s+(?:the\s+)?(?:file|code)',
            r'(?:delete|remove)\s+(?:from|in)\s+(?:the\s+)?(?:file|code)',
        ],
        TaskType.COMMAND_RUN: [
            r'(?:run|execute|invoke|call)\s+(?:the\s+)?(?:command|script|test|build|server)',
            r'(?:start|launch|boot)\s+(?:the\s+)?(?:server|app|application)',
            r'(?:npm|pip|cargo|go|python|node|npm|yarn|pnpm)\s+',
        ],
        TaskType.SEARCH: [
            r'(?:find|search|locate|look for|where)\s+(?:the\s+)?(?:file|function|class|method|variable|definition)',
            r'(?:search|grep|find)\s+(?:for|in)',
        ],
        TaskType.ANALYSIS: [
            r'(?:analyze|analyse|review|check|examine|understand)\s+(?:the\s+)?(?:code|project|structure|architecture)',
            r'(?:explain|describe|summarize)\s+(?:how|what|why)',
            r'(?:what does|how does|why does)',
        ],
        TaskType.IMPLEMENTATION: [
            r'(?:implement|create|build|develop|write)\s+(?:a\s+)?(?:new\s+)?(?:feature|function|method|class|module|component)',
            r'(?:add|integrate)\s+(?:a\s+)?(?:feature|function|method)',
        ],
        TaskType.TESTING: [
            r'(?:test|testing|write tests?|add tests?|create tests?)',
            r'(?:unit\s+test|integration\s+test|e2e\s+test)',
        ],
        TaskType.DEBUG: [
            r'(?:debug|fix|solve|resolve|troubleshoot|investigate)\s+(?:the\s+)?(?:error|bug|issue|problem|exception)',
            r'(?:why is|why does)\s+.*(?:not working|failing|error|wrong)',
        ],
        TaskType.DOCUMENTATION: [
            r'(?:document|docs|documentation|comment|comments|add comments?)',
            r'(?:write|create|add)\s+(?:documentation|docs|readme)',
        ],
        TaskType.REFACTOR: [
            r'(?:refactor|restructure|reorganize|clean up|improve)\s+(?:the\s+)?(?:code|structure|architecture)',
            r'(?:remove|extract|move|split)\s+(?:duplicate|redundant)',
        ],
    }
    
    # Key phrases indicating priority
    HIGH_PRIORITY_PHRASES = [
        'critical', 'urgent', 'important', 'essential', 'vital', 'immediately', 'asap',
        'crash', 'broken', 'not working', 'failing', 'error', 'bug', 'issue'
    ]
    
    LOW_PRIORITY_PHRASES = [
        'optional', 'nice to have', 'later', 'whenever', 'not urgent', 'low priority',
        'minor', 'small', 'tweak', 'adjust'
    ]
    
    # Complexity indicators
    COMPLEXITY_INDICATORS = {
        'simple': [
            'single', 'simple', 'basic', 'just', 'only', 'quick', 'small'
        ],
        'complex': [
            'multiple', 'complex', 'comprehensive', 'complete', 'full', 'entire',
            'all', 'system', 'architecture', 'refactor', 'restructure'
        ]
    }
    
    def __init__(self):
        self._plan_counter = 0
    
    def create_plan(self, prompt: str, context: str = "") -> TaskPlan:
        """
        Create a structured plan from a user prompt.
        
        Args:
            prompt: The user's request/prompt
            context: Additional context (files, project info, etc.)
        
        Returns:
            A TaskPlan with actionable steps
        """
        self._plan_counter += 1
        plan_id = f"plan_{self._plan_counter}"
        
        import datetime
        created_at = datetime.datetime.now().isoformat()
        
        # Analyze the prompt
        steps = self._generate_steps(prompt, context)
        
        # Calculate estimated steps
        estimated = len(steps)
        
        # Determine title
        title = self._extract_title(prompt)
        
        return TaskPlan(
            id=plan_id,
            title=title,
            description=prompt,
            steps=steps,
            context=context,
            estimated_steps=estimated,
            created_at=created_at
        )
    
    def _extract_title(self, prompt: str) -> str:
        """Extract a concise title from the prompt."""
        # Get first sentence or up to 50 chars
        prompt = prompt.strip()
        
        # Try to get the first sentence
        match = re.match(r'^([^.!?\n]+[.!?]?)', prompt)
        if match:
            title = match.group(1).strip()
        else:
            # Fall back to first line
            title = prompt.split('\n')[0].strip()
        
        # Truncate if too long
        if len(title) > 60:
            title = title[:57] + "..."
        
        return title
    
    def _generate_steps(self, prompt: str, context: str) -> List[TaskStep]:
        """Generate steps from prompt and context."""
        prompt_lower = prompt.lower()
        steps = []
        step_id = 0
        
        # Detect task types
        detected_types = []
        for task_type, patterns in self.TASK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, prompt_lower):
                    detected_types.append(task_type)
                    break
        
        # Determine priority
        priority = TaskPriority.MEDIUM
        for phrase in self.HIGH_PRIORITY_PHRASES:
            if phrase in prompt_lower:
                priority = TaskPriority.HIGH
                break
        else:
            for phrase in self.LOW_PRIORITY_PHRASES:
                if phrase in prompt_lower:
                    priority = TaskPriority.LOW
                    break
        
        # Determine complexity
        complexity = "moderate"
        for word in self.COMPLEXITY_INDICATORS['simple']:
            if word in prompt_lower:
                complexity = "simple"
                break
        else:
            for word in self.COMPLEXITY_INDICATORS['complex']:
                if word in prompt_lower:
                    complexity = "complex"
                    break
        
        # Extract files mentioned
        files_mentioned = self._extract_files(prompt, context)
        
        # Generate steps based on detected task types
        if TaskType.FILE_READ in detected_types:
            for file_path in files_mentioned[:1]:  # Limit to first file
                step_id += 1
                steps.append(TaskStep(
                    id=step_id,
                    description=f"Read and understand {file_path}",
                    task_type=TaskType.FILE_READ,
                    priority=priority,
                    estimated_complexity="simple",
                    files_involved=[file_path]
                ))
        
        if TaskType.SEARCH in detected_types:
            query = self._extract_search_query(prompt)
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description=f"Search for: {query}",
                task_type=TaskType.SEARCH,
                priority=priority,
                estimated_complexity=complexity
            ))
        
        if TaskType.DEBUG in detected_types:
            # Debug tasks typically need analysis first
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Analyze error and identify root cause",
                task_type=TaskType.ANALYSIS,
                priority=TaskPriority.HIGH,
                estimated_complexity=complexity,
                dependencies=[] if not steps else [steps[-1].id]
            ))
            
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Implement fix for the error",
                task_type=TaskType.FILE_EDIT,
                priority=TaskPriority.HIGH,
                estimated_complexity=complexity,
                dependencies=[step_id - 1]
            ))
            
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Verify the fix resolves the issue",
                task_type=TaskType.TESTING,
                priority=TaskPriority.HIGH,
                estimated_complexity="simple",
                dependencies=[step_id - 1]
            ))
        
        if TaskType.IMPLEMENTATION in detected_types:
            # Implementation tasks need planning and execution
            if TaskType.FILE_READ not in detected_types and files_mentioned:
                step_id += 1
                steps.append(TaskStep(
                    id=step_id,
                    description="Understand existing code structure",
                    task_type=TaskType.FILE_READ,
                    priority=TaskPriority.MEDIUM,
                    estimated_complexity="simple",
                    files_involved=files_mentioned[:2]
                ))
            
            step_id += 1
            deps = [steps[-1].id] if steps else []
            steps.append(TaskStep(
                id=step_id,
                description="Plan the implementation approach",
                task_type=TaskType.ANALYSIS,
                priority=priority,
                estimated_complexity="moderate",
                dependencies=deps
            ))
            
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Implement the new feature/functionality",
                task_type=TaskType.FILE_WRITE,
                priority=TaskPriority.HIGH,
                estimated_complexity=complexity,
                dependencies=[step_id - 1]
            ))
            
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Test the implementation",
                task_type=TaskType.TESTING,
                priority=TaskPriority.MEDIUM,
                estimated_complexity="moderate",
                dependencies=[step_id - 1]
            ))
        
        if TaskType.FILE_EDIT in detected_types and TaskType.DEBUG not in detected_types and TaskType.IMPLEMENTATION not in detected_types:
            for file_path in files_mentioned[:1]:
                step_id += 1
                steps.append(TaskStep(
                    id=step_id,
                    description=f"Edit {file_path}",
                    task_type=TaskType.FILE_EDIT,
                    priority=priority,
                    estimated_complexity=complexity,
                    files_involved=[file_path]
                ))
        
        if TaskType.COMMAND_RUN in detected_types:
            commands = self._extract_commands(prompt)
            for cmd in commands:
                step_id += 1
                steps.append(TaskStep(
                    id=step_id,
                    description=f"Run: {cmd}",
                    task_type=TaskType.COMMAND_RUN,
                    priority=priority,
                    estimated_complexity="simple",
                    commands=[cmd]
                ))
        
        if TaskType.TESTING in detected_types and TaskType.DEBUG not in detected_types:
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Write tests for the functionality",
                task_type=TaskType.TESTING,
                priority=TaskPriority.MEDIUM,
                estimated_complexity="moderate"
            ))
        
        if TaskType.DOCUMENTATION in detected_types:
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Add documentation and comments",
                task_type=TaskType.DOCUMENTATION,
                priority=TaskPriority.LOW,
                estimated_complexity="simple"
            ))
        
        if TaskType.REFACTOR in detected_types:
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Analyze current code structure",
                task_type=TaskType.ANALYSIS,
                priority=TaskPriority.MEDIUM,
                estimated_complexity="moderate"
            ))
            
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Refactor and reorganize code",
                task_type=TaskType.FILE_EDIT,
                priority=TaskPriority.MEDIUM,
                estimated_complexity=complexity,
                dependencies=[step_id - 1]
            ))
        
        # If no specific task types detected, create a general plan
        if not steps:
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Understand the request",
                task_type=TaskType.ANALYSIS,
                priority=priority,
                estimated_complexity="simple"
            ))
            
            step_id += 1
            steps.append(TaskStep(
                id=step_id,
                description="Execute the requested task",
                task_type=TaskType.OTHER,
                priority=priority,
                estimated_complexity=complexity,
                dependencies=[step_id - 1]
            ))
        
        return steps
    
    def _extract_files(self, prompt: str, context: str) -> List[str]:
        """Extract file paths mentioned in prompt and context."""
        files = []
        
        # Pattern for file paths
        file_patterns = [
            r'[\w/\-\\]+\.(?:py|js|ts|jsx|tsx|java|go|rs|c|cpp|h|hpp|cs|rb|php|swift|kt|scala|vue|svelte|html|css|scss|json|yaml|yml|xml|md|sql|sh|bash)',
            r'[\w/\-\\]+\.[a-zA-Z]{1,4}(?=\s|$|,|\.|:|;)',
        ]
        
        combined = prompt + " " + context
        
        for pattern in file_patterns:
            matches = re.findall(pattern, combined)
            for match in matches:
                # Clean up the match
                match = match.strip('.,;:')
                if match and len(match) < 200:  # Sanity check
                    files.append(match)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_files = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)
        
        return unique_files[:10]  # Limit to 10 files
    
    def _extract_search_query(self, prompt: str) -> str:
        """Extract search query from prompt."""
        # Remove common filler words
        filler_words = ['find', 'search', 'for', 'the', 'a', 'an', 'where', 'is', 'are', 'what']
        words = prompt.lower().split()
        
        query_words = []
        for word in words:
            word = word.strip('.,;:')
            if word and word not in filler_words:
                query_words.append(word)
        
        return ' '.join(query_words[:5])  # Limit to 5 words
    
    def _extract_commands(self, prompt: str) -> List[str]:
        """Extract commands to run from prompt."""
        commands = []
        
        # Common command patterns
        cmd_patterns = [
            r'(?:npm|yarn|pnpm|pip|cargo|go|python|node|pytest|jest|mocha|make|gradle|mvn)\s+[\w\-]+',
            r'run\s+([\w\-]+)',
            r'execute\s+([\w\-]+)',
            r'(?:start|launch|stop|restart)\s+(?:the\s+)?(?:server|app|application|service)',
        ]
        
        for pattern in cmd_patterns:
            matches = re.findall(pattern, prompt, re.IGNORECASE)
            commands.extend(matches)
        
        return commands[:3]  # Limit to 3 commands
    
    def refine_plan(self, plan: TaskPlan, new_context: str) -> TaskPlan:
        """
        Refine a plan based on new information or context.
        
        Args:
            plan: Existing plan
            new_context: New context information
        
        Returns:
            Refined plan with updated steps
        """
        # Re-generate steps with combined context
        combined_context = plan.context + "\n" + new_context
        new_steps = self._generate_steps(plan.description, combined_context)
        
        # Preserve completed step statuses
        for new_step in new_steps:
            for old_step in plan.steps:
                if new_step.description == old_step.description:
                    new_step.status = old_step.status
                    new_step.result = old_step.result
                    new_step.error = old_step.error
        
        plan.steps = new_steps
        plan.context = combined_context
        return plan
    
    def get_execution_order(self, plan: TaskPlan) -> List[List[int]]:
        """
        Get the order of step execution based on dependencies.
        Returns a list of steps that can be executed in parallel.
        
        Args:
            plan: Task plan
        
        Returns:
            List of step ID lists (each inner list can be executed in parallel)
        """
        if not plan.steps:
            return []
        
        # Build dependency graph
        completed = set()
        order = []
        
        while len(completed) < len(plan.steps):
            # Find steps whose dependencies are all completed
            ready = []
            for step in plan.steps:
                if step.id in completed:
                    continue
                if all(dep in completed for dep in step.dependencies):
                    ready.append(step.id)
            
            if not ready:
                # Circular dependency or missing dependency
                # Add remaining steps anyway
                remaining = [s.id for s in plan.steps if s.id not in completed]
                order.append(remaining)
                break
            
            order.append(ready)
            completed.update(ready)
        
        return order


# Global instance
_task_planner: Optional[TaskPlanner] = None


def get_task_planner() -> TaskPlanner:
    """Get or create the global task planner."""
    global _task_planner
    if _task_planner is None:
        _task_planner = TaskPlanner()
    return _task_planner