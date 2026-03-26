"""
Bash Tool - OpenCode-style shell command execution
Run shell commands with timeout, output streaming, and safety.
Based on packages/opencode/src/tool/bash.ts
"""

import subprocess
import time
import os
import platform
from pathlib import Path
from typing import Dict, Any, Optional

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result


class BashTool(BaseTool):
    """
    Shell command execution tool.
    
    Features:
    - Run shell commands safely
    - Timeout protection
    - Working directory control
    - Output capture
    
    Safety:
    - Requires user confirmation (potentially destructive)
    - Timeout prevents hanging
    - Project-scoped working directory
    """
    
    name = "bash"
    requires_confirmation = True
    is_safe = False
    
    parameters = [
        ToolParameter("command", "string", "Shell command to execute", required=True),
        ToolParameter("cwd", "string", "Working directory (default: project root)", required=False, default=None),
        ToolParameter("timeout", "integer", "Timeout in seconds (default: 60)", required=False, default=60),
    ]

    @property
    def description(self) -> str:
        """Dynamic description based on current OS."""
        os_info = platform.system()
        shell_info = "PowerShell/CMD" if os_info == "Windows" else "Bash/Zsh"
        return f"Execute a shell command on {os_info} ({shell_info}). Use for running scripts, installing packages, git operations, etc. IMPORTANT: You are on {os_info}, use appropriate syntax."

    @description.setter
    def description(self, value):
        # Allow manual override if needed
        pass

    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            command = params.get("command")
            if not command:
                return error_result("Missing required parameter: command")
            
            cwd = params.get("cwd") or self.project_root or str(Path.cwd())
            timeout = params.get("timeout", 60)
            
            # Windows Shims for Linux-isms
            if platform.system() == "Windows":
                # Handle 'mkdir -p' (common AI mistake on Windows)
                if command.strip().startswith("mkdir -p "):
                    path = command.strip()[len("mkdir -p "):].strip().strip('"').strip("'")
                    win_path = path.replace('/', '\\')
                    # In PowerShell, New-Item -ItemType Directory -Force creates parents
                    command = f'New-Item -ItemType Directory -Force -Path "{win_path}"'
                    log.info(f"BashTool: Shimmed 'mkdir -p' to PowerShell: {command}")
                
                # Handle 'wc -l' (common for counting lines)
                elif "wc -l" in command:
                    # Replace wc -l "file" with (Get-Content "file" | Measure-Object -Line).Lines
                    import re
                    command = re.sub(r'wc -l\s+["\']?([^"\'\s;&|]+)["\']?', r'(Get-Content "\1" | Measure-Object -Line).Lines', command)
                    log.info(f"BashTool: Shimmed 'wc -l' to PowerShell: {command}")

            # Security check: prevent dangerous commands
            dangerous_commands = ['rm -rf /', 'format c:', 'del /f /q *', 'sudo rm']
            if any(dc in command.lower() for dc in dangerous_commands):
                return error_result(f"Command blocked for safety: {command}")
            
            # Run command
            try:
                # 🗲 PERFORMANCE: On Windows, use PowerShell for better compatibility with Linux-style commands
                # This allows ls, cat, rm, cp, mv, etc. to work via PowerShell aliases
                shell_exec = None
                if platform.system() == "Windows":
                    shell_exec = "powershell.exe"
                
                result = subprocess.run(
                    command,
                    shell=True,
                    executable=shell_exec,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                duration_ms = (time.time() - start_time) * 1000
                
                # Check for errors
                if result.returncode != 0:
                    return error_result(
                        f"Command failed with exit code {result.returncode}\n\n"
                        f"STDOUT:\n{result.stdout}\n\n"
                        f"STDERR:\n{result.stderr}"
                    )
                
                # Success
                output = result.stdout
                if result.stderr:
                    output += f"\n\nSTDERR:\n{result.stderr}"
                
                # 🔄 SYNC CACHE: Shell commands may create/modify files.
                # Clear entire cache to ensure next tool sees changes.
                if self.file_manager:
                    log.info(f"BashTool: Clearing file manager cache after command execution: {command[:30]}...")
                    self.file_manager.clear_cache()
                
                return success_result(
                    result=output,
                    duration_ms=duration_ms,
                    metadata={
                        'command': command,
                        'cwd': cwd,
                        'exit_code': result.returncode,
                        'has_stderr': bool(result.stderr)
                    }
                )
                
            except subprocess.TimeoutExpired:
                return error_result(
                    f"Command timed out after {timeout} seconds. "
                    f"Consider increasing timeout or optimizing the command."
                )
            except FileNotFoundError:
                return error_result(f"Command not found: {command.split()[0] if command else 'unknown'}")
            except Exception as e:
                return error_result(f"Command execution failed: {str(e)}")
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Bash tool error: {str(e)}", duration_ms)
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """Enhanced validation for shell commands."""
        is_valid, message = super().validate_params(params)
        
        if not is_valid:
            return False, message
        
        command = params.get("command", "")
        if not command:
            return False, "Command cannot be empty"
        
        # Block dangerous patterns
        dangerous_patterns = [
            'rm -rf /', 'rm -rf *', 'format ', 'del /', 
            'sudo rm -rf', ':(){ :|:& };:'
        ]
        
        for pattern in dangerous_patterns:
            if pattern in command.lower():
                return False, f"Dangerous command blocked: {pattern}"
        
        return True, "OK"
