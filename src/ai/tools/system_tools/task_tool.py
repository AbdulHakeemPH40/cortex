"""
Task Tool - Background task management
Run long-running tasks in background with monitoring.
Based on packages/opencode/src/tool/task.ts
"""

import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional
import threading

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class TaskTool(BaseTool):
    """
    Background task management tool.
    
    Features:
    - Run tasks in background
    - Monitor task status
    - Kill running tasks
    - Capture output
    
    Use Cases:
    - Long-running test suites
    - Build processes
    - Development servers
    """
    
    name = "task"
    description = "Run a long-running task in background. Use for tests, builds, dev servers that run continuously."
    requires_confirmation = True
    is_safe = False
    
    # Track running tasks
    _running_tasks: Dict[str, subprocess.Popen] = {}
    
    parameters = [
        ToolParameter("operation", "string", "Operation: 'start', 'stop', 'status'", required=True),
        ToolParameter("command", "string", "Command to run (for 'start' operation)", required=False, default=None),
        ToolParameter("task_id", "string", "Task ID (for 'stop' operation)", required=False, default=None),
        ToolParameter("cwd", "string", "Working directory", required=False, default=None),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            operation = params.get("operation")
            if not operation:
                return error_result("Missing required parameter: operation")
            
            if operation == "start":
                return self._start_task(params, start_time)
            elif operation == "stop":
                return self._stop_task(params, start_time)
            elif operation == "status":
                return self._get_status(params, start_time)
            else:
                return error_result(f"Unknown task operation: {operation}")
                
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Task operation failed: {str(e)}", duration_ms)
    
    def _start_task(self, params: Dict, start_time: float) -> ToolResult:
        """Start a background task."""
        try:
            command = params.get("command")
            if not command:
                return error_result("Missing required parameter: command for 'start' operation")
            
            cwd = params.get("cwd") or self.project_root or str(Path.cwd())
            
            # Generate task ID
            import uuid
            task_id = str(uuid.uuid4())[:8]
            
            # Start process
            try:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # Store running process
                self._running_tasks[task_id] = process
                
                duration_ms = (time.time() - start_time) * 1000
                
                return success_result(
                    result=f"Task started with ID: {task_id}",
                    duration_ms=duration_ms,
                    metadata={
                        'task_id': task_id,
                        'command': command,
                        'cwd': cwd,
                        'pid': process.pid,
                        'status': 'running'
                    }
                )
                
            except Exception as e:
                return error_result(f"Failed to start task: {str(e)}")
            
        except Exception as e:
            return error_result(f"Start task failed: {str(e)}")
    
    def _stop_task(self, params: Dict, start_time: float) -> ToolResult:
        """Stop a running task."""
        try:
            task_id = params.get("task_id")
            if not task_id:
                return error_result("Missing required parameter: task_id for 'stop' operation")
            
            if task_id not in self._running_tasks:
                return error_result(f"Task not found: {task_id}")
            
            process = self._running_tasks[task_id]
            
            # Kill process
            try:
                process.kill()
                process.wait(timeout=5)
                
                # Remove from tracking
                del self._running_tasks[task_id]
                
                duration_ms = (time.time() - start_time) * 1000
                
                return success_result(
                    result=f"Task {task_id} stopped",
                    duration_ms=duration_ms,
                    metadata={
                        'task_id': task_id,
                        'status': 'stopped',
                        'exit_code': process.returncode
                    }
                )
                
            except subprocess.TimeoutExpired:
                process.terminate()
                return error_result(f"Task {task_id} terminated (force kill)")
            except Exception as e:
                return error_result(f"Failed to stop task: {str(e)}")
            
        except Exception as e:
            return error_result(f"Stop task failed: {str(e)}")
    
    def _get_status(self, params: Dict, start_time: float) -> ToolResult:
        """Get status of running tasks."""
        try:
            task_id = params.get("task_id")
            
            if task_id:
                # Status of specific task
                if task_id not in self._running_tasks:
                    return error_result(f"Task not found: {task_id}")
                
                process = self._running_tasks[task_id]
                is_running = process.poll() is None
                
                duration_ms = (time.time() - start_time) * 1000
                
                return success_result(
                    result={
                        'task_id': task_id,
                        'status': 'running' if is_running else 'finished',
                        'pid': process.pid,
                        'return_code': process.returncode
                    },
                    duration_ms=duration_ms,
                    metadata={'operation': 'status'}
                )
            else:
                # Status of all tasks
                running_tasks = []
                for tid, proc in self._running_tasks.items():
                    is_running = proc.poll() is None
                    running_tasks.append({
                        'task_id': tid,
                        'pid': proc.pid,
                        'status': 'running' if is_running else 'finished',
                        'return_code': proc.returncode
                    })
                
                duration_ms = (time.time() - start_time) * 1000
                
                return success_result(
                    result=running_tasks,
                    duration_ms=duration_ms,
                    metadata={
                        'total_running': len(running_tasks),
                        'operation': 'status_all'
                    }
                )
            
        except Exception as e:
            return error_result(f"Get status failed: {str(e)}")
