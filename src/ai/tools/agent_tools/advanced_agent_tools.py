"""
Advanced Agent Tools - Claude CLI Compatible

MultiAgentTool, AgentMemoryTool, AgentPlanningTool, AgentReasoningTool,
AgentLearningTool, AgentEvaluationTool, AgentOrchestrationTool

Converts TypeScript agent tools to Python for Cortex IDE.
"""

import uuid
import json
from typing import Dict, Any, Callable, Optional, List, Set
from datetime import datetime
from dataclasses import dataclass, field

from ..claude_tool import ClaudeTool, ToolUseContext, ToolCapability, AgentType
from ..constants import ASYNC_AGENT_ALLOWED_TOOLS
from ..base_tool import ToolParameter, success_result, error_result
from ..task_tools.models import get_task_manager, TaskStatus, Task


# =============================================================================
# MULTI AGENT TOOL - Multi-agent coordination
# =============================================================================

class MultiAgentTool(ClaudeTool):
    """
    Coordinate multiple agents working together on a complex task.
    
    Manages agent teams, assigns work, and aggregates results.
    """
    
    name = "multi_agent"
    description = "Coordinate multiple agents working in parallel on sub-tasks"
    capabilities = {ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="task_description",
            param_type="string",
            description="Overall task to accomplish",
            required=True
        ),
        ToolParameter(
            name="sub_tasks",
            param_type="array",
            description="List of sub-task descriptions for each agent",
            required=True
        ),
        ToolParameter(
            name="tools_per_agent",
            param_type="array",
            description="Tools each agent should have access to",
            required=False,
            default=["read_file", "grep", "glob"]
        ),
        ToolParameter(
            name="aggregation_prompt",
            param_type="string",
            description="How to combine sub-task results into final output",
            required=False,
            default="Combine all findings into a coherent summary"
        )
    ]
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ):
        try:
            task_desc = args.get("task_description", "")
            sub_tasks = args.get("sub_tasks", [])
            tools = args.get("tools_per_agent", ["read_file", "grep", "glob"])
            aggregation = args.get("aggregation_prompt", "")
            
            if not sub_tasks:
                return error_result("No sub-tasks provided")
            
            # Create parent task (BUG #6 FIX: Add null check for task_manager)
            task_manager = get_task_manager()
            if not task_manager:
                return error_result("Task manager not initialized. Cannot create parent task.")
            
            parent_task = task_manager.create_task(
                description=task_desc,
                metadata={"type": "multi_agent", "sub_task_count": len(sub_tasks)}
            )
            
            # Create sub-tasks for each agent
            child_task_ids = []
            for i, sub_task in enumerate(sub_tasks):
                child = task_manager.create_task(
                    description=sub_task,
                    parent_task_id=parent_task.id,
                    metadata={"agent_index": i, "tools": tools}
                )
                child_task_ids.append(child.id)
            
            # Spawn agents (simplified - real would integrate with agent system)
            spawned_agents = []
            for i, task_id in enumerate(child_task_ids):
                agent_id = f"agent_{uuid.uuid4().hex[:8]}"
                spawned_agents.append({
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "sub_task": sub_tasks[i]
                })
                
                # Update task to running
                task_manager.update_task(task_id, status=TaskStatus.RUNNING, agent_id=agent_id)
                
                if on_progress:
                    on_progress({
                        "type": "agent_spawned",
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "progress": f"{i+1}/{len(child_task_ids)}"
                    })
            
            return success_result(
                result={
                    "parent_task_id": parent_task.id,
                    "sub_tasks": child_task_ids,
                    "agents_spawned": len(spawned_agents),
                    "agent_details": spawned_agents,
                    "aggregation_prompt": aggregation,
                    "status": "coordinating"
                },
                metadata={"operation": "multi_agent_coordination"}
            )
            
        except Exception as e:
            return error_result(f"Multi-agent coordination failed: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        return f"Coordinating {len(args.get('sub_tasks', []))} agents"


# =============================================================================
# AGENT MEMORY TOOL - Agent memory storage/retrieval
# =============================================================================

class AgentMemoryTool(ClaudeTool):
    """
    Store and retrieve agent memories across conversations.
    
    Enables agents to remember context, learnings, and preferences.
    """
    
    name = "agent_memory"
    description = "Store or retrieve agent memory/context for continuity across sessions"
    capabilities = {ToolCapability.READ, ToolCapability.WRITE}
    
    parameters = [
        ToolParameter(
            name="operation",
            param_type="string",
            description="Operation: 'store', 'retrieve', 'list', or 'delete'",
            required=True
        ),
        ToolParameter(
            name="key",
            param_type="string",
            description="Memory key/identifier",
            required=False,
            default=None
        ),
        ToolParameter(
            name="value",
            param_type="string",
            description="Value to store (for store operation)",
            required=False,
            default=None
        ),
        ToolParameter(
            name="category",
            param_type="string",
            description="Memory category (e.g., 'learnings', 'preferences', 'context')",
            required=False,
            default="general"
        ),
        ToolParameter(
            name="scope",
            param_type="string",
            description="Memory scope: 'agent', 'conversation', or 'global'",
            required=False,
            default="agent"
        )
    ]
    
    # In-memory storage (should be database-backed in production)
    _memories: Dict[str, List[Dict]] = {}
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ):
        try:
            operation = args.get("operation", "")
            key = args.get("key")
            value = args.get("value")
            category = args.get("category", "general")
            scope = args.get("scope", "agent")
            
            # Determine memory namespace
            agent_id = context.agent_id or "main"
            namespace = f"{scope}:{agent_id}:{category}"
            
            if operation == "store":
                if not key or value is None:
                    return error_result("Store operation requires key and value")
                
                if namespace not in self._memories:
                    self._memories[namespace] = []
                
                memory = {
                    "key": key,
                    "value": value,
                    "timestamp": datetime.now().isoformat(),
                    "conversation_id": context.conversation_id
                }
                
                # Update if exists, else append
                existing = [m for m in self._memories[namespace] if m["key"] == key]
                if existing:
                    existing[0].update(memory)
                else:
                    self._memories[namespace].append(memory)
                
                return success_result(
                    result={"stored": True, "key": key, "namespace": namespace},
                    metadata={"operation": "store"}
                )
            
            elif operation == "retrieve":
                if not key:
                    return error_result("Retrieve operation requires key")
                
                memories = self._memories.get(namespace, [])
                match = next((m for m in memories if m["key"] == key), None)
                
                if match:
                    return success_result(
                        result={
                            "found": True,
                            "key": key,
                            "value": match["value"],
                            "timestamp": match["timestamp"]
                        },
                        metadata={"operation": "retrieve"}
                    )
                else:
                    return success_result(
                        result={"found": False, "key": key},
                        metadata={"operation": "retrieve"}
                    )
            
            elif operation == "list":
                memories = self._memories.get(namespace, [])
                return success_result(
                    result={
                        "count": len(memories),
                        "memories": [
                            {"key": m["key"], "timestamp": m["timestamp"]} 
                            for m in memories
                        ]
                    },
                    metadata={"operation": "list"}
                )
            
            elif operation == "delete":
                if not key:
                    return error_result("Delete operation requires key")
                
                memories = self._memories.get(namespace, [])
                self._memories[namespace] = [m for m in memories if m["key"] != key]
                
                return success_result(
                    result={"deleted": True, "key": key},
                    metadata={"operation": "delete"}
                )
            
            else:
                return error_result(f"Unknown operation: {operation}")
                
        except Exception as e:
            return error_result(f"Memory operation failed: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        return f"Agent memory {args.get('operation', 'unknown')}: {args.get('key', 'unknown')}"


# =============================================================================
# AGENT PLANNING TOOL - Task planning and decomposition
# =============================================================================

class AgentPlanningTool(ClaudeTool):
    """
    Create and manage execution plans for complex tasks.
    
    Decomposes high-level goals into actionable steps.
    """
    
    name = "agent_plan"
    description = "Create execution plans and decompose complex tasks into steps"
    capabilities = {ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="operation",
            param_type="string",
            description="Operation: 'create', 'get', 'update', 'execute_step'",
            required=True
        ),
        ToolParameter(
            name="goal",
            param_type="string",
            description="High-level goal to achieve",
            required=False,
            default=None
        ),
        ToolParameter(
            name="plan_id",
            param_type="string",
            description="Plan ID (for get/update/execute operations)",
            required=False,
            default=None
        ),
        ToolParameter(
            name="steps",
            param_type="array",
            description="List of steps to execute",
            required=False,
            default=None
        ),
        ToolParameter(
            name="constraints",
            param_type="array",
            description="Constraints and requirements",
            required=False,
            default=None
        )
    ]
    
    # Plan storage
    _plans: Dict[str, Dict] = {}
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ):
        try:
            operation = args.get("operation", "")
            
            if operation == "create":
                goal = args.get("goal", "")
                steps = args.get("steps", [])
                constraints = args.get("constraints", [])
                
                if not goal:
                    return error_result("Create operation requires goal")
                
                plan_id = f"plan_{uuid.uuid4().hex[:8]}"
                
                plan = {
                    "id": plan_id,
                    "goal": goal,
                    "steps": [{"step": i+1, "description": s, "status": "pending"} 
                             for i, s in enumerate(steps)],
                    "constraints": constraints,
                    "created_at": datetime.now().isoformat(),
                    "status": "active",
                    "current_step": 0,
                    "agent_id": context.agent_id or "main"
                }
                
                self._plans[plan_id] = plan
                
                return success_result(
                    result={
                        "plan_id": plan_id,
                        "goal": goal,
                        "total_steps": len(steps),
                        "status": "created"
                    },
                    metadata={"operation": "create"}
                )
            
            elif operation == "get":
                plan_id = args.get("plan_id")
                if not plan_id or plan_id not in self._plans:
                    return error_result(f"Plan not found: {plan_id}")
                
                return success_result(
                    result=self._plans[plan_id],
                    metadata={"operation": "get"}
                )
            
            elif operation == "update":
                plan_id = args.get("plan_id")
                if not plan_id or plan_id not in self._plans:
                    return error_result(f"Plan not found: {plan_id}")
                
                plan = self._plans[plan_id]
                
                # Update fields
                if "steps" in args:
                    plan["steps"] = args["steps"]
                if "status" in args:
                    plan["status"] = args["status"]
                
                return success_result(
                    result={"plan_id": plan_id, "updated": True},
                    metadata={"operation": "update"}
                )
            
            elif operation == "execute_step":
                plan_id = args.get("plan_id")
                if not plan_id or plan_id not in self._plans:
                    return error_result(f"Plan not found: {plan_id}")
                
                plan = self._plans[plan_id]
                current = plan.get("current_step", 0)
                
                if current < len(plan["steps"]):
                    step = plan["steps"][current]
                    step["status"] = "in_progress"
                    
                    return success_result(
                        result={
                            "plan_id": plan_id,
                            "current_step": current + 1,
                            "step_description": step["description"],
                            "status": "executing"
                        },
                        metadata={"operation": "execute_step"}
                    )
                else:
                    return success_result(
                        result={"plan_id": plan_id, "status": "completed"},
                        metadata={"operation": "execute_step"}
                    )
            
            else:
                return error_result(f"Unknown operation: {operation}")
                
        except Exception as e:
            return error_result(f"Planning failed: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        return f"Planning {args.get('operation', 'unknown')}: {args.get('goal', args.get('plan_id', 'unknown'))[:30]}"


# =============================================================================
# AGENT REASONING TOOL - Logical reasoning chains
# =============================================================================

class AgentReasoningTool(ClaudeTool):
    """
    Perform structured logical reasoning on complex problems.
    
    Breaks down problems using chain-of-thought reasoning.
    """
    
    name = "agent_reason"
    description = "Perform structured reasoning: deduce, infer, or analyze complex problems"
    capabilities = {ToolCapability.READ}
    
    parameters = [
        ToolParameter(
            name="problem",
            param_type="string",
            description="Problem or question to reason about",
            required=True
        ),
        ToolParameter(
            name="reasoning_type",
            param_type="string",
            description="Type: 'deductive', 'inductive', 'abductive', 'analogical', 'causal'",
            required=False,
            default="deductive"
        ),
        ToolParameter(
            name="context",
            param_type="string",
            description="Additional context for reasoning",
            required=False,
            default=None
        ),
        ToolParameter(
            name="steps",
            param_type="integer",
            description="Number of reasoning steps to show",
            required=False,
            default=5
        )
    ]
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ):
        try:
            problem = args.get("problem", "")
            reasoning_type = args.get("reasoning_type", "deductive")
            ctx = args.get("context", "")
            steps = args.get("steps", 5)
            
            # This tool primarily guides the AI to structure its reasoning
            # The actual reasoning happens in the AI's response
            
            reasoning_prompt = f"""Reasoning Task:
Problem: {problem}
Type: {reasoning_type}
Context: {ctx}

Please provide a {steps}-step {reasoning_type} reasoning chain:
1. Identify premises/facts
2. Analyze relationships
3. Apply {reasoning_type} logic
4. Draw conclusions
5. Verify validity"""
            
            return success_result(
                result={
                    "reasoning_prompt": reasoning_prompt,
                    "problem": problem,
                    "type": reasoning_type,
                    "requested_steps": steps,
                    "note": "Use this structured approach in your response"
                },
                metadata={"reasoning_type": reasoning_type}
            )
            
        except Exception as e:
            return error_result(f"Reasoning setup failed: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        return f"Reasoning ({args.get('reasoning_type', 'deductive')}): {args.get('problem', 'unknown')[:30]}"


# =============================================================================
# AGENT LEARNING TOOL - Learning from interactions
# =============================================================================

class AgentLearningTool(ClaudeTool):
    """
    Extract learnings from task execution and store patterns.
    
    Enables continuous improvement through experience.
    """
    
    name = "agent_learn"
    description = "Extract learnings from completed work and store patterns for future use"
    capabilities = {ToolCapability.WRITE}
    
    parameters = [
        ToolParameter(
            name="operation",
            param_type="string",
            description="Operation: 'extract', 'get_patterns', 'apply'",
            required=True
        ),
        ToolParameter(
            name="task_description",
            param_type="string",
            description="Description of completed task",
            required=False,
            default=None
        ),
        ToolParameter(
            name="approach",
            param_type="string",
            description="Approach/method that worked",
            required=False,
            default=None
        ),
        ToolParameter(
            name="outcome",
            param_type="string",
            description="Outcome and results",
            required=False,
            default=None
        ),
        ToolParameter(
            name="pattern_id",
            param_type="string",
            description="Pattern ID to retrieve or apply",
            required=False,
            default=None
        ),
        ToolParameter(
            name="tags",
            param_type="array",
            description="Tags for categorizing the learning",
            required=False,
            default=None
        )
    ]
    
    _learnings: List[Dict] = []
    _patterns: Dict[str, Dict] = {}
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ):
        try:
            operation = args.get("operation", "")
            
            if operation == "extract":
                task = args.get("task_description", "")
                approach = args.get("approach", "")
                outcome = args.get("outcome", "")
                tags = args.get("tags", [])
                
                if not all([task, approach, outcome]):
                    return error_result("Extract requires task_description, approach, and outcome")
                
                pattern_id = f"pattern_{uuid.uuid4().hex[:8]}"
                
                learning = {
                    "id": pattern_id,
                    "task_type": self._categorize_task(task),
                    "approach": approach,
                    "outcome": outcome,
                    "success": "success" in outcome.lower() or "completed" in outcome.lower(),
                    "tags": tags,
                    "timestamp": datetime.now().isoformat(),
                    "agent_id": context.agent_id or "main"
                }
                
                self._learnings.append(learning)
                self._patterns[pattern_id] = learning
                
                return success_result(
                    result={
                        "pattern_id": pattern_id,
                        "extracted": True,
                        "task_type": learning["task_type"]
                    },
                    metadata={"operation": "extract"}
                )
            
            elif operation == "get_patterns":
                task_type = args.get("task_description", "")
                tags = args.get("tags", [])
                
                # Filter patterns
                patterns = list(self._patterns.values())
                
                if task_type:
                    patterns = [p for p in patterns if task_type.lower() in p["task_type"].lower()]
                if tags:
                    patterns = [p for p in patterns if any(t in p.get("tags", []) for t in tags)]
                
                # Sort by success and recency
                patterns.sort(key=lambda x: (x["success"], x["timestamp"]), reverse=True)
                
                return success_result(
                    result={
                        "count": len(patterns),
                        "patterns": [
                            {
                                "id": p["id"],
                                "task_type": p["task_type"],
                                "approach": p["approach"][:100],
                                "success": p["success"]
                            }
                            for p in patterns[:10]
                        ]
                    },
                    metadata={"operation": "get_patterns"}
                )
            
            elif operation == "apply":
                pattern_id = args.get("pattern_id")
                
                if not pattern_id or pattern_id not in self._patterns:
                    return error_result(f"Pattern not found: {pattern_id}")
                
                pattern = self._patterns[pattern_id]
                
                return success_result(
                    result={
                        "pattern_id": pattern_id,
                        "approach": pattern["approach"],
                        "from_task": pattern["task_type"],
                        "success_rate": "high" if pattern["success"] else "unknown"
                    },
                    metadata={"operation": "apply"}
                )
            
            else:
                return error_result(f"Unknown operation: {operation}")
                
        except Exception as e:
            return error_result(f"Learning operation failed: {str(e)}")
    
    def _categorize_task(self, task: str) -> str:
        """Categorize task by type."""
        task_lower = task.lower()
        if "refactor" in task_lower:
            return "refactoring"
        elif "debug" in task_lower or "fix" in task_lower:
            return "debugging"
        elif "test" in task_lower:
            return "testing"
        elif "analyze" in task_lower:
            return "analysis"
        else:
            return "general"
    
    def get_activity_description(self, args: Dict) -> str:
        return f"Learning {args.get('operation', 'unknown')}: {args.get('task_description', 'unknown')[:30]}"


# =============================================================================
# AGENT EVALUATION TOOL - Agent performance evaluation
# =============================================================================

class AgentEvaluationTool(ClaudeTool):
    """
    Evaluate agent performance on completed tasks.
    
    Provides metrics and feedback for improvement.
    """
    
    name = "agent_evaluate"
    description = "Evaluate agent/task performance and provide quality metrics"
    capabilities = {ToolCapability.READ}
    
    parameters = [
        ToolParameter(
            name="task_id",
            param_type="string",
            description="Task ID to evaluate",
            required=True
        ),
        ToolParameter(
            name="criteria",
            param_type="array",
            description="Evaluation criteria: 'completeness', 'quality', 'efficiency', 'correctness'",
            required=False,
            default=None
        ),
        ToolParameter(
            name="expected_output",
            param_type="string",
            description="Expected result for comparison",
            required=False,
            default=None
        ),
        ToolParameter(
            name="detailed",
            param_type="boolean",
            description="Include detailed analysis",
            required=False,
            default=True
        )
    ]
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ):
        try:
            task_id = args.get("task_id")
            criteria = args.get("criteria", ["completeness", "quality"])
            expected = args.get("expected_output", "")
            detailed = args.get("detailed", True)
            
            # Get task
            task_manager = get_task_manager()
            task = task_manager.get_task(task_id)
            
            if not task:
                return error_result(f"Task not found: {task_id}")
            
            # Basic evaluation metrics
            evaluation = {
                "task_id": task_id,
                "status": task.status.value,
                "evaluated_at": datetime.now().isoformat(),
            }
            
            # Calculate duration
            if task.created_at and task.completed_at:
                duration = (task.completed_at - task.created_at).total_seconds()
                evaluation["duration_seconds"] = duration
            
            # Check if completed
            if task.status.value == "completed":
                evaluation["success"] = True
                evaluation["scores"] = {
                    "completeness": 100 if task.result else 0,
                    "quality": 80 if task.result else 0,  # Would need more analysis
                }
            elif task.status.value == "failed":
                evaluation["success"] = False
                evaluation["error"] = task.error_message
            else:
                evaluation["success"] = None
                evaluation["note"] = "Task not yet completed"
            
            if detailed:
                evaluation["details"] = {
                    "description": task.description,
                    "tool_calls_count": len(task.tool_calls),
                    "agent_id": task.agent_id,
                    "result_preview": task.result[:200] if task.result else None
                }
            
            return success_result(
                result=evaluation,
                metadata={"task_id": task_id}
            )
            
        except Exception as e:
            return error_result(f"Evaluation failed: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        return f"Evaluating task {args.get('task_id', 'unknown')[:15]}"


# =============================================================================
# AGENT ORCHESTRATION TOOL - Agent workflow orchestration
# =============================================================================

class AgentOrchestrationTool(ClaudeTool):
    """
    Orchestrate complex multi-agent workflows.
    
    Manages agent dependencies, sequencing, and data flow.
    """
    
    name = "agent_orchestrate"
    description = "Orchestrate complex multi-step workflows with agent dependencies"
    capabilities = {ToolCapability.AGENTIC}
    
    parameters = [
        ToolParameter(
            name="operation",
            param_type="string",
            description="Operation: 'create_workflow', 'execute', 'get_status', 'cancel'",
            required=True
        ),
        ToolParameter(
            name="workflow_id",
            param_type="string",
            description="Workflow ID (for execute/status/cancel)",
            required=False,
            default=None
        ),
        ToolParameter(
            name="workflow_definition",
            param_type="object",
            description="Workflow definition with steps and dependencies",
            required=False,
            default=None
        ),
        ToolParameter(
            name="input_data",
            param_type="object",
            description="Input data for workflow execution",
            required=False,
            default=None
        )
    ]
    
    _workflows: Dict[str, Dict] = {}
    _executions: Dict[str, Dict] = {}
    
    async def call(
        self,
        args: Dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Callable[[], bool] = None,
        on_progress: Optional[Callable[[Dict], None]] = None
    ):
        try:
            operation = args.get("operation", "")
            
            if operation == "create_workflow":
                definition = args.get("workflow_definition", {})
                
                if not definition or "steps" not in definition:
                    return error_result("Workflow definition must include 'steps'")
                
                workflow_id = f"workflow_{uuid.uuid4().hex[:8]}"
                
                workflow = {
                    "id": workflow_id,
                    "name": definition.get("name", "Unnamed Workflow"),
                    "steps": definition["steps"],
                    "dependencies": definition.get("dependencies", {}),
                    "created_at": datetime.now().isoformat(),
                    "created_by": context.agent_id or "main"
                }
                
                self._workflows[workflow_id] = workflow
                
                return success_result(
                    result={
                        "workflow_id": workflow_id,
                        "name": workflow["name"],
                        "step_count": len(workflow["steps"]),
                        "status": "created"
                    },
                    metadata={"operation": "create_workflow"}
                )
            
            elif operation == "execute":
                workflow_id = args.get("workflow_id")
                input_data = args.get("input_data", {})
                
                if not workflow_id or workflow_id not in self._workflows:
                    return error_result(f"Workflow not found: {workflow_id}")
                
                execution_id = f"exec_{uuid.uuid4().hex[:8]}"
                
                execution = {
                    "id": execution_id,
                    "workflow_id": workflow_id,
                    "status": "running",
                    "input": input_data,
                    "started_at": datetime.now().isoformat(),
                    "completed_steps": [],
                    "current_step": 0,
                    "results": {}
                }
                
                self._executions[execution_id] = execution
                
                # Start first step
                workflow = self._workflows[workflow_id]
                steps = workflow["steps"]
                
                if steps:
                    first_step = steps[0]
                    
                    return success_result(
                        result={
                            "execution_id": execution_id,
                            "workflow_id": workflow_id,
                            "status": "started",
                            "total_steps": len(steps),
                            "current_step": 1,
                            "step_name": first_step.get("name", "Step 1"),
                            "note": "Execute steps sequentially using task_create/agent tools"
                        },
                        metadata={"operation": "execute"}
                    )
                else:
                    return success_result(
                        result={"execution_id": execution_id, "status": "completed", "note": "No steps to execute"},
                        metadata={"operation": "execute"}
                    )
            
            elif operation == "get_status":
                execution_id = args.get("workflow_id")  # workflow_id param holds execution_id here
                
                if execution_id in self._executions:
                    exec_data = self._executions[execution_id]
                    return success_result(
                        result={
                            "execution_id": execution_id,
                            "workflow_id": exec_data["workflow_id"],
                            "status": exec_data["status"],
                            "progress": f"{len(exec_data['completed_steps'])}/{len(self._workflows[exec_data['workflow_id']]['steps'])}",
                            "current_step": exec_data["current_step"]
                        },
                        metadata={"operation": "get_status"}
                    )
                else:
                    return error_result(f"Execution not found: {execution_id}")
            
            elif operation == "cancel":
                execution_id = args.get("workflow_id")
                
                if execution_id in self._executions:
                    self._executions[execution_id]["status"] = "cancelled"
                    return success_result(
                        result={"execution_id": execution_id, "status": "cancelled"},
                        metadata={"operation": "cancel"}
                    )
                else:
                    return error_result(f"Execution not found: {execution_id}")
            
            else:
                return error_result(f"Unknown operation: {operation}")
                
        except Exception as e:
            return error_result(f"Orchestration failed: {str(e)}")
    
    def get_activity_description(self, args: Dict) -> str:
        return f"Orchestration {args.get('operation', 'unknown')}: {args.get('workflow_id', 'new')[:20]}"


# Update exports
__all__ = [
    'MultiAgentTool',
    'AgentMemoryTool',
    'AgentPlanningTool',
    'AgentReasoningTool',
    'AgentLearningTool',
    'AgentEvaluationTool',
    'AgentOrchestrationTool'
]
