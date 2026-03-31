"""
Groq-Optimized Tool Executor
Allows Groq to work at full speed without tool execution blocking
"""

import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import threading
import queue

from src.utils.logger import get_logger
from src.ai.providers import get_provider_registry, ProviderType

log = get_logger("groq_tool_executor")


class ToolExecutionMode(Enum):
    """Execution mode for tools"""
    SYNC = "sync"           # Execute immediately and wait
    ASYNC = "async"         # Execute in background, don't block
    DEFERRED = "deferred"   # Queue for later execution


@dataclass
class GroqOptimizedConfig:
    """Configuration for Groq-optimized tool execution"""
    # When using Groq, execute tools asynchronously to not block streaming
    async_execution: bool = True
    
    # Maximum time to wait for tool results (ms)
    max_wait_ms: int = 5000
    
    # Number of worker threads for parallel execution
    max_workers: int = 10
    
    # Allow all tools when using Groq (no restrictions)
    allow_all_tools: bool = True
    
    # Execute tools while AI is still streaming
    parallel_with_streaming: bool = True
    
    # Skip slow tools and return immediately
    skip_slow_tools: bool = False
    
    # Tool timeout (seconds)
    tool_timeout: float = 10.0


class GroqToolExecutor:
    """
    Tool executor optimized for Groq's extreme speed
    
    Key features:
    - Non-blocking tool execution
    - Parallel tool execution
    - Async result collection
    - No delays between AI and tools
    """
    
    def __init__(self, config: Optional[GroqOptimizedConfig] = None):
        self.config = config or GroqOptimizedConfig()
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_workers)
        self._result_queue = queue.Queue()
        self._pending_tasks = {}
        
        # Tool registry cache
        self._tool_registry = None
        
        log.info("✅ GroqToolExecutor initialized (optimized for speed)")
    
    def _get_tool_registry(self):
        """Lazy load tool registry"""
        if self._tool_registry is None:
            from src.ai._tools_monolithic import ToolRegistry
            self._tool_registry = ToolRegistry()
        return self._tool_registry
    
    def execute_tools_async(self, tool_calls: List[Dict], 
                           callback: Optional[Callable] = None) -> List[Any]:
        """
        Execute multiple tools asynchronously without blocking
        
        Args:
            tool_calls: List of tool call dicts with 'name' and 'arguments'
            callback: Optional callback function for each result
            
        Returns:
            List of results (may be incomplete if async)
        """
        if not tool_calls:
            return []
        
        log.info(f"🚀 Executing {len(tool_calls)} tools asynchronously for Groq")
        
        futures = []
        results = []
        
        # Submit all tools to thread pool
        for tool_call in tool_calls:
            tool_name = tool_call.get('name') or tool_call.get('function', {}).get('name')
            arguments = tool_call.get('arguments') or tool_call.get('function', {}).get('arguments', '{}')
            
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except:
                    arguments = {}
            
            # Submit to thread pool
            future = self._executor.submit(self._execute_single_tool, tool_name, arguments)
            futures.append((future, tool_name))
        
        # If async mode, return immediately with placeholders
        if self.config.async_execution:
            log.info("⚡ Async mode: Returning immediately, tools executing in background")
            return [{"status": "executing_async", "tool": tc.get('name')} for tc in tool_calls]
        
        # Otherwise wait for results with timeout
        for future, tool_name in futures:
            try:
                result = future.result(timeout=self.config.tool_timeout)
                results.append({"tool": tool_name, "result": result})
                
                if callback:
                    callback(tool_name, result)
                    
            except Exception as e:
                log.error(f"Tool {tool_name} failed: {e}")
                results.append({"tool": tool_name, "error": str(e)})
        
        return results
    
    def _execute_single_tool(self, tool_name: str, arguments: Dict) -> Any:
        """Execute a single tool"""
        try:
            registry = self._get_tool_registry()
            
            if not hasattr(registry, tool_name):
                return {"error": f"Tool '{tool_name}' not found"}
            
            tool = getattr(registry, tool_name)
            
            # Execute with timing
            start = time.time()
            result = tool(**arguments)
            elapsed = time.time() - start
            
            log.info(f"✅ {tool_name} completed in {elapsed*1000:.0f}ms")
            
            return result
            
        except Exception as e:
            log.error(f"❌ {tool_name} error: {e}")
            return {"error": str(e)}
    
    def collect_results(self, timeout: float = None) -> List[Dict]:
        """
        Collect results from async tool executions
        
        Args:
            timeout: Maximum time to wait (seconds)
            
        Returns:
            List of completed results
        """
        timeout = timeout or self.config.tool_timeout
        results = []
        
        try:
            while True:
                result = self._result_queue.get(timeout=timeout)
                results.append(result)
        except queue.Empty:
            pass
        
        return results
    
    def get_allowed_tools_for_groq(self) -> List[str]:
        """
        Get list of all tools allowed when using Groq
        Groq gets ALL tools for maximum capability
        """
        if self.config.allow_all_tools:
            # Return all available tools
            registry = self._get_tool_registry()
            tools = registry.get_all_tools()
            return list(tools.keys())
        
        # Otherwise return only fast tools
        return ['read', 'grep', 'glob', 'edit', 'write', 'bash']


# Singleton instance
_groq_executor_instance: Optional[GroqToolExecutor] = None


def get_groq_tool_executor(config: Optional[GroqOptimizedConfig] = None) -> GroqToolExecutor:
    """Get singleton Groq tool executor"""
    global _groq_executor_instance
    if _groq_executor_instance is None:
        _groq_executor_instance = GroqToolExecutor(config)
    return _groq_executor_instance


def execute_tools_for_groq(tool_calls: List[Dict], 
                          async_mode: bool = True,
                          callback: Optional[Callable] = None) -> List[Any]:
    """
    Convenience function to execute tools optimized for Groq speed
    
    Args:
        tool_calls: List of tool calls
        async_mode: If True, execute asynchronously without blocking
        callback: Optional callback for results
        
    Returns:
        Tool execution results
    """
    executor = get_groq_tool_executor(
        GroqOptimizedConfig(async_execution=async_mode)
    )
    
    return executor.execute_tools_async(tool_calls, callback)
