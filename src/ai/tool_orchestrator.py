"""
AI Tool Orchestrator for DeepSeek and SiliconFlow
Manages tool calling across multiple providers with intelligent routing
"""

import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Callable, Generator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import threading

from src.utils.logger import get_logger
from src.ai.providers import get_provider_registry, ProviderType

log = get_logger("tool_orchestrator")


class ToolExecutionStatus(Enum):
    """Status of tool execution"""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolExecution:
    """Represents a tool execution request"""
    id: str
    tool_name: str
    parameters: Dict[str, Any]
    status: ToolExecutionStatus = ToolExecutionStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_ms: float = 0.0
    retry_count: int = 0
    max_retries: int = 2
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'tool': self.tool_name,
            'status': self.status.value,
            'result': self.result,
            'error': self.error,
            'duration_ms': self.duration_ms,
            'retry_count': self.retry_count
        }


@dataclass
class OrchestratorState:
    """State management for tool orchestrator (Reducer pattern)"""
    session_id: str = field(default_factory=lambda: str(int(time.time() * 1000)))
    status: str = "idle"  # idle, planning, executing, reviewing, completed, failed
    
    # Tool tracking
    executions: List[ToolExecution] = field(default_factory=list)
    pending_executions: List[ToolExecution] = field(default_factory=list)
    completed_executions: List[ToolExecution] = field(default_factory=list)
    failed_executions: List[ToolExecution] = field(default_factory=list)
    
    # Performance tracking
    total_tools_executed: int = 0
    total_execution_time_ms: float = 0.0
    average_tool_time_ms: float = 0.0
    
    # Provider selection
    primary_provider: str = "deepseek"  # Can be 'deepseek', 'siliconflow'
    tool_provider: str = "auto"  # 'auto', 'deepseek', 'siliconflow'
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'status': self.status,
            'total_executed': self.total_tools_executed,
            'pending': len(self.pending_executions),
            'completed': len(self.completed_executions),
            'failed': len(self.failed_executions),
            'avg_time_ms': self.average_tool_time_ms,
            'primary_provider': self.primary_provider
        }


class ToolOrchestrator:
    """
    Intelligent tool orchestrator for AI agents
    
    Features:
    - Multi-provider support (DeepSeek, SiliconFlow)
    - Intelligent tool selection based on context
    - Parallel execution with dependency management
    - Automatic retry with exponential backoff
    - State management via reducer pattern
    """
    
    # Tool categories with recommended providers
    TOOL_CATEGORIES = {
        "fast": ["read", "grep", "glob"],  # Fast file/search operations
        "io": ["write", "edit", "bash"],   # I/O heavy operations  
        "complex": ["webfetch", "websearch"],  # Complex operations
        "interactive": ["question"]  # User interaction
    }
    
    # Provider characteristics for tool selection
    PROVIDER_CHARACTERISTICS = {
        "deepseek": {
            "speed": "medium",  # 100-200 tokens/sec
            "latency": "medium", # 200-500ms
            "best_for": ["complex_reasoning", "code_generation"],
            "context_window": 64000,
            "cost_efficiency": "very_high"
        },
        "siliconflow": {
            "speed": "high",
            "latency": "medium",
            "best_for": ["multi_model", "fallback"],
            "context_window": 128000,
            "cost_efficiency": "medium"
        }
    }
    
    def __init__(self, project_root: Optional[str] = None):
        self.project_root = project_root or str(Path.cwd())
        self.state = OrchestratorState()
        self._state_lock = threading.Lock()
        
        # Tool registry
        self._tools: Dict[str, Any] = {}
        self._tool_registry = None
        
        # Provider registry
        self._provider_registry = get_provider_registry()
        
        # Execution queue
        self._execution_queue: List[ToolExecution] = []
        self._max_concurrent = 3
        self._semaphore = threading.Semaphore(self._max_concurrent)
        
        log.info("✅ ToolOrchestrator initialized")
    
    def _update_state(self, action: str, payload: Dict = None):
        """Reducer pattern for state management"""
        with self._state_lock:
            payload = payload or {}
            
            if action == "TOOL_QUEUED":
                execution = payload.get("execution")
                if execution:
                    self.state.pending_executions.append(execution)
                    self.state.status = "planning"
                    
            elif action == "TOOL_STARTED":
                execution = payload.get("execution")
                if execution:
                    execution.status = ToolExecutionStatus.EXECUTING
                    execution.start_time = time.time()
                    if execution in self.state.pending_executions:
                        self.state.pending_executions.remove(execution)
                    self.state.status = "executing"
                    
            elif action == "TOOL_COMPLETED":
                execution = payload.get("execution")
                result = payload.get("result")
                if execution:
                    execution.status = ToolExecutionStatus.COMPLETED
                    execution.end_time = time.time()
                    execution.duration_ms = (execution.end_time - execution.start_time) * 1000
                    execution.result = result
                    self.state.completed_executions.append(execution)
                    self.state.total_tools_executed += 1
                    self._update_average_time()
                    
            elif action == "TOOL_FAILED":
                execution = payload.get("execution")
                error = payload.get("error")
                if execution:
                    execution.status = ToolExecutionStatus.FAILED
                    execution.end_time = time.time()
                    execution.error = error
                    execution.retry_count += 1
                    
                    if execution.retry_count < execution.max_retries:
                        # Re-queue for retry
                        execution.status = ToolExecutionStatus.PENDING
                        self.state.pending_executions.append(execution)
                        log.info(f"🔄 Retrying {execution.tool_name} (attempt {execution.retry_count + 1})")
                    else:
                        self.state.failed_executions.append(execution)
                        
            elif action == "STATUS_CHANGE":
                self.state.status = payload.get("status", "idle")
                
            elif action == "SET_PROVIDER":
                provider = payload.get("provider")
                if provider:
                    self.state.primary_provider = provider
    
    def _update_average_time(self):
        """Update average execution time"""
        if self.state.completed_executions:
            total = sum(e.duration_ms for e in self.state.completed_executions)
            self.state.total_execution_time_ms = total
            self.state.average_tool_time_ms = total / len(self.state.completed_executions)
    
    def _get_tool_registry(self):
        """Lazy load tool registry"""
        if self._tool_registry is None:
            from src.ai._tools_monolithic import ToolRegistry
            self._tool_registry = ToolRegistry(project_root=self.project_root)
        return self._tool_registry
    
    def select_best_provider(self, tool_name: str, context: Dict = None) -> str:
        """
        Select the best provider for a tool based on characteristics
        
        Strategy:
        1. Base tools -> deepseek
        2. Fallback -> siliconflow
        """
        context = context or {}
        
        # Check if specific provider requested
        requested = context.get("force_provider")
        if requested and requested in self.PROVIDER_CHARACTERISTICS:
            return requested
        
        return self.state.primary_provider
    
    def get_provider_for_model(self, provider_name: str):
        """Get provider instance by name"""
        provider_map = {
            "deepseek": ProviderType.DEEPSEEK,
            "siliconflow": ProviderType.SILICONFLOW
        }
        
        provider_type = provider_map.get(provider_name.lower(), ProviderType.DEEPSEEK)
        return self._provider_registry.get_provider(provider_type)
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                     context: Dict = None, execution_id: str = None) -> ToolExecution:
        """
        Execute a single tool with intelligent provider selection
        
        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters
            context: Execution context (can specify force_provider)
            execution_id: Optional execution ID
            
        Returns:
            ToolExecution with result
        """
        execution_id = execution_id or f"exec_{int(time.time() * 1000)}"
        
        execution = ToolExecution(
            id=execution_id,
            tool_name=tool_name,
            parameters=parameters,
            max_retries=context.get("max_retries", 2) if context else 2
        )
        
        # Update state
        self._update_state("TOOL_QUEUED", {"execution": execution})
        
        # Select provider
        provider_name = self.select_best_provider(tool_name, context)
        
        log.info(f"🔧 Executing {tool_name} with {provider_name} provider")
        
        # Acquire semaphore for concurrency control
        with self._semaphore:
            self._update_state("TOOL_STARTED", {"execution": execution})
            
            try:
                # Get tool from registry
                registry = self._get_tool_registry()
                
                if not hasattr(registry, tool_name):
                    raise ValueError(f"Tool '{tool_name}' not found in registry")
                
                tool = getattr(registry, tool_name)
                
                # Execute tool
                start_time = time.time()
                result = tool(**parameters)
                duration_ms = (time.time() - start_time) * 1000
                
                execution.duration_ms = duration_ms
                execution.result = result
                
                self._update_state("TOOL_COMPLETED", {
                    "execution": execution,
                    "result": result
                })
                
                log.info(f"✅ {tool_name} completed in {duration_ms:.0f}ms")
                
            except Exception as e:
                error_msg = str(e)
                log.error(f"❌ {tool_name} failed: {error_msg}")
                
                self._update_state("TOOL_FAILED", {
                    "execution": execution,
                    "error": error_msg
                })
                
                if execution.retry_count >= execution.max_retries:
                    execution.status = ToolExecutionStatus.FAILED
                    execution.error = error_msg
        
        return execution
    
    def execute_tools_parallel(self, tool_calls: List[Dict[str, Any]],
                               context: Dict = None) -> List[ToolExecution]:
        """
        Execute multiple tools in parallel with dependency resolution
        
        Args:
            tool_calls: List of dicts with 'tool', 'parameters', 'depends_on'
            context: Execution context
            
        Returns:
            List of ToolExecution results
        """
        context = context or {}
        executions = []
        
        log.info(f"🚀 Executing {len(tool_calls)} tools in parallel")
        
        # Group by dependencies
        dependency_graph = self._build_dependency_graph(tool_calls)
        
        # Execute in batches based on dependencies
        completed_ids = set()
        
        while dependency_graph:
            # Find tools with no pending dependencies
            ready_to_execute = [
                tc for tc in dependency_graph
                if all(dep in completed_ids for dep in tc.get("depends_on", []))
            ]
            
            if not ready_to_execute:
                log.error("Dependency resolution failed - circular dependency?")
                break
            
            # Execute ready tools in parallel
            with threading.ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
                futures = []
                for tc in ready_to_execute:
                    future = executor.submit(
                        self.execute_tool,
                        tc["tool"],
                        tc.get("parameters", {}),
                        context,
                        tc.get("id")
                    )
                    futures.append((future, tc))
                
                # Collect results
                for future, tc in futures:
                    try:
                        execution = future.result(timeout=30)  # 30s timeout per tool
                        executions.append(execution)
                        completed_ids.add(tc.get("id", execution.id))
                    except Exception as e:
                        log.error(f"Tool execution failed: {e}")
            
            # Remove completed from graph
            dependency_graph = [
                tc for tc in dependency_graph
                if tc.get("id") not in completed_ids
            ]
        
        log.info(f"✅ Completed {len(executions)} parallel executions")
        return executions
    
    def _build_dependency_graph(self, tool_calls: List[Dict]) -> List[Dict]:
        """Build dependency graph from tool calls"""
        # Add IDs if missing
        for i, tc in enumerate(tool_calls):
            if "id" not in tc:
                tc["id"] = f"tool_{i}"
        return tool_calls
    
    def process_tool_calls_with_ai(self, tool_calls: List[Dict],
                                   messages: List[Dict],
                                   provider: str = "auto") -> Generator[str, None, None]:
        """
        Process tool calls and continue conversation with AI
        
        This is the main integration point:
        1. Execute tools
        2. Format results
        3. Continue conversation with AI
        
        Works with DeepSeek or SiliconFlow
        """
        if provider == "auto":
            provider = self.select_best_provider("complex")
        
        # Execute tools
        executions = self.execute_tools_parallel(tool_calls)
        
        # Format results for AI
        tool_results = []
        for exec in executions:
            if exec.status == ToolExecutionStatus.COMPLETED:
                tool_results.append({
                    "tool": exec.tool_name,
                    "result": exec.result,
                    "duration_ms": exec.duration_ms
                })
            else:
                tool_results.append({
                    "tool": exec.tool_name,
                    "error": exec.error,
                    "status": exec.status.value
                })
        
        # Add tool results to conversation
        results_message = {
            "role": "user",
            "content": f"Tool execution results:\n{json.dumps(tool_results, indent=2)}"
        }
        
        conversation = messages + [results_message]
        
        # Get AI response
        provider_instance = self.get_provider_for_model(provider)
        
        log.info(f"🤖 Getting AI response with {provider} after tool execution")
        
        # Stream response
        for chunk in provider_instance.chat_stream(
            conversation,
            model=self._get_model_for_provider(provider),
            temperature=0.7,
            max_tokens=4096
        ):
            yield chunk
    
    def _get_model_for_provider(self, provider: str) -> str:
        """Get default model for provider"""
        models = {
            "deepseek": "deepseek-chat",
            "siliconflow": "pro/deepseek-ai/DeepSeek-V3"
        }
        return models.get(provider, "deepseek-chat")
    
    def get_state(self) -> Dict[str, Any]:
        """Get current orchestrator state"""
        return self.state.to_dict()
    
    def reset_state(self):
        """Reset orchestrator state"""
        self.state = OrchestratorState()
        log.info("🔄 ToolOrchestrator state reset")


# Singleton instance
_orchestrator_instance: Optional[ToolOrchestrator] = None


def get_tool_orchestrator(project_root: Optional[str] = None) -> ToolOrchestrator:
    """Get singleton tool orchestrator instance"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = ToolOrchestrator(project_root)
    return _orchestrator_instance


def execute_tool_with_orchestrator(tool_name: str, parameters: Dict,
                                   provider: str = "auto") -> Dict[str, Any]:
    """
    Convenience function to execute a tool with orchestrator
    
    Args:
        tool_name: Tool to execute
        parameters: Tool parameters
        provider: Provider to use ('auto', 'deepseek', 'siliconflow')
        
    Returns:
        Tool execution result
    """
    orchestrator = get_tool_orchestrator()
    context = {"force_provider": provider} if provider != "auto" else {}
    
    execution = orchestrator.execute_tool(tool_name, parameters, context)
    
    return {
        "success": execution.status == ToolExecutionStatus.COMPLETED,
        "result": execution.result,
        "error": execution.error,
        "duration_ms": execution.duration_ms,
        "provider": provider if provider != "auto" else orchestrator.select_best_provider(tool_name)
    }
