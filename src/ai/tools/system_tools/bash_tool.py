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
from src.utils.logger import get_logger

log = get_logger("bash_tool")


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
            log.info(f"BashTool.execute() called with command: {command}")
            if not command:
                return error_result("Missing required parameter: command")
            
            cwd = params.get("cwd") or self.project_root or str(Path.cwd())
            timeout = params.get("timeout", 60)
            
            # Windows Shims for Linux-isms
            if platform.system() == "Windows":
                cmd_lower = command.strip().lower()
                
                # Handle 'mkdir -p' (common AI mistake on Windows)
                if cmd_lower.startswith("mkdir -p "):
                    path = command.strip()[len("mkdir -p "):].strip().strip('"').strip("'")
                    win_path = path.replace('/', '\\')
                    command = f'New-Item -ItemType Directory -Force -Path "{win_path}"'
                    log.info(f"BashTool: Shimmed 'mkdir -p' to PowerShell: {command}")
                
                # Handle 'wc -l' (common for counting lines)
                elif "wc -l" in command:
                    import re
                    command = re.sub(r'wc -l\s+["\']?([^"\'\s;&|]+)["\']?', r'(Get-Content "\1" | Measure-Object -Line).Lines', command)
                    log.info(f"BashTool: Shimmed 'wc -l' to PowerShell: {command}")
                
                # Handle 'which' -> 'where'
                elif cmd_lower.startswith("which "):
                    import re
                    match = re.match(r'which\s+["\']?(\S+)["\']?', command)
                    if match:
                        target = match.group(1)
                        command = f'where {target}'
                        log.info(f"BashTool: Shimmed 'which' to 'where': {command}")
                
                # Handle 'pwd' -> 'cd' (pwd output)
                elif cmd_lower.strip() == "pwd":
                    command = "(Get-Location).Path"
                    log.info(f"BashTool: Shimmed 'pwd' to PowerShell: {command}")
                
                # Handle 'rm -rf' -> 'Remove-Item -Recurse -Force'
                elif "rm -rf " in cmd_lower or "rm -r " in cmd_lower:
                    import re
                    match = re.search(r'rm\s+-rf?\s+["\']?([^"\'\s]+)["\']?', command)
                    if match:
                        target = match.group(1).replace('/', '\\')
                        command = f'Remove-Item -Recurse -Force -Path "{target}"'
                        log.info(f"BashTool: Shimmed 'rm' to PowerShell: {command}")
                
                # Handle 'ls' -> 'Get-ChildItem'
                elif cmd_lower.strip() == "ls" or cmd_lower.startswith("ls "):
                    import re
                    # Check for flags like -la, -l, -a, -al
                    flags_match = re.search(r'ls\s+(-[a-zA-Z]+)', cmd_lower)
                    flags = flags_match.group(1) if flags_match else ""
                    # Get the path (anything after flags or the ls command itself)
                    path_match = re.search(r'ls\s+[^\s-]+\s+(.+)|ls\s+(.+?)\s*$', command)
                    
                    if "-a" in flags or "-all" in flags:
                        # Include hidden files
                        target = (path_match.group(1) or path_match.group(2) or ".") if path_match else "."
                        command = f'Get-ChildItem -Path "{target}" -Force'
                    else:
                        target = (path_match.group(1) or path_match.group(2) or ".") if path_match else "."
                        command = f'Get-ChildItem -Path "{target}"'
                    
                    if flags:
                        command += f"  # Flags: {flags}"
                    log.info(f"BashTool: Shimmed 'ls' to PowerShell: {command}")
                
                # Handle 'cat' -> 'Get-Content'
                elif cmd_lower.startswith("cat "):
                    import re
                    match = re.match(r'cat\s+["\']?([^"\'\s]+)["\']?', command)
                    if match:
                        target = match.group(1)
                        command = f'Get-Content -Path "{target}"'
                    log.info(f"BashTool: Shimmed 'cat' to PowerShell: {command}")
                
                # Handle 'touch' -> 'New-Item'
                elif cmd_lower.startswith("touch "):
                    import re
                    match = re.match(r'touch\s+["\']?([^"\'\s]+)["\']?', command)
                    if match:
                        target = match.group(1)
                        command = f'if (!(Test-Path "{target}")) {{ New-Item -ItemType File -Path "{target}" }}'
                    log.info(f"BashTool: Shimmed 'touch' to PowerShell: {command}")

            # Security check: prevent dangerous commands
            dangerous_commands = ['rm -rf /', 'format c:', 'del /f /q *', 'sudo rm']
            if any(dc in command.lower() for dc in dangerous_commands):
                return error_result(f"Command blocked for safety: {command}")
            
            # Run command
            try:
                # 🗲 PERFORMANCE: On Windows, use PowerShell for better compatibility with Linux-style commands
                # This allows ls, cat, rm, cp, mv, etc. to work via PowerShell aliases
                
                log.info(f"Executing command: {command}")
                log.info(f"Working directory: {cwd}")
                
                # Detect interactive commands that might hang - log warning but always use DEVNULL
                is_interactive = False
                cmd_for_check = command.lower()
                
                # Python scripts with input() are interactive
                if 'python' in cmd_for_check or 'py ' in cmd_for_check:
                    # Check if it's running a Python script file
                    import re
                    py_match = re.search(r'python\s+(\S+\.py)', command, re.IGNORECASE)
                    if py_match:
                        script_path = os.path.join(cwd, py_match.group(1)) if not os.path.isabs(py_match.group(1)) else py_match.group(1)
                        if os.path.exists(script_path):
                            try:
                                with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                    if 'input(' in content or 'sys.stdin' in content:
                                        is_interactive = True
                                        log.warning(f"BashTool: Detected interactive Python script with input() - will use DEVNULL stdin: {script_path}")
                            except Exception:
                                pass
                
                # Always use DEVNULL to prevent hanging on interactive commands
                # Interactive scripts (with input()) will get empty string from stdin
                stdin_source = subprocess.DEVNULL
                
                # Try PowerShell first on Windows, then fallback to CMD
                result = None
                last_error = None
                
                if platform.system() == "Windows":
                    # On Windows, use full system paths for shells (they may not be in venv PATH)
                    windows_dir = os.environ.get('WINDIR', 'C:\\Windows')
                    system32 = os.path.join(windows_dir, 'System32')
                    powershell_path = os.path.join(system32, 'WindowsPowerShell', 'v1.0', 'powershell.exe')
                    cmd_path = os.path.join(system32, 'cmd.exe')
                    
                    shells_to_try = [
                        (powershell_path, ["-NoProfile", "-Command", command]),
                        (cmd_path, ["/c", command]),
                    ]
                    
                    for shell_name, cmd_args in shells_to_try:
                        try:
                            log.info(f"Trying shell: {shell_name} with args: {cmd_args[:2]}...")
                            result = subprocess.run(
                                cmd_args,
                                shell=False,  # Don't use shell=True with cmd array
                                executable=shell_name,
                                cwd=cwd,
                                capture_output=True,
                                text=True,
                                timeout=timeout,
                                stdin=stdin_source  # DEVNULL for non-interactive, None for interactive
                            )
                            log.info(f"Command executed successfully with shell: {shell_name}, exit code: {result.returncode}")
                            break  # Success
                        except FileNotFoundError as e:
                            log.warning(f"{shell_name} not found: {e}")
                            last_error = e
                            continue  # Try next shell
                        except Exception as e:
                            log.warning(f"{shell_name} failed: {e}")
                            last_error = e
                            continue
                else:
                    # On Unix, just run the command directly
                    try:
                        result = subprocess.run(
                            command,
                            shell=True,
                            cwd=cwd,
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                            stdin=stdin_source
                        )
                        log.info(f"Command executed successfully with exit code: {result.returncode}")
                    except Exception as e:
                        return error_result(f"Command execution failed: {str(e)}")
                
                if result is None:
                    cmd_name = command.split()[0] if command else 'unknown'
                    return error_result(
                        f"Command not found: {cmd_name}\n\n"
                        f"Failed to execute with PowerShell and CMD. "
                        f"Ensure the command exists and is in your PATH."
                    )
                
                log.info(f"Command completed with exit code: {result.returncode}")
                log.debug(f"STDOUT: {result.stdout[:500] if result.stdout else 'empty'}")
                log.debug(f"STDERR: {result.stderr[:500] if result.stderr else 'empty'}")
                
                duration_ms = (time.time() - start_time) * 1000
                
                # Check for errors
                if result.returncode != 0:
                    log.warning(f"Command failed with exit code {result.returncode}")
                    return error_result(
                        f"Command failed with exit code {result.returncode}\n\n"
                        f"STDOUT:\n{result.stdout}\n\n"
                        f"STDERR:\n{result.stderr}"
                    )
                
                # Success
                output = result.stdout
                if result.stderr:
                    output += f"\n\nSTDERR:\n{result.stderr}"
                
                log.info(f"Command succeeded with output length: {len(output)}")
                
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
                log.warning(f"Command timed out: {command}")
                return error_result(
                    f"Command timed out after {timeout} seconds. "
                    f"Consider increasing timeout or optimizing the command."
                )
            except FileNotFoundError as e:
                cmd_name = command.split()[0] if command else 'unknown'
                log.error(f"Command not found: {cmd_name} - {e}")
                
                # Provide helpful error message for Windows users
                if platform.system() == "Windows":
                    return error_result(
                        f"Command not found: {cmd_name}\n\n"
                        f"On Windows, some commands may need different syntax:\n"
                        f"- 'echo' works in CMD but may need 'Write-Output' in PowerShell\n"
                        f"- 'where.exe' is 'where' in PowerShell\n"
                        f"- Use full paths if the command is not in PATH\n"
                        f"- Try using 'cmd /c {command}' to force CMD execution"
                    )
                return error_result(f"Command not found: {cmd_name}")
            except Exception as e:
                log.error(f"Command execution failed: {command} - {e}")
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
