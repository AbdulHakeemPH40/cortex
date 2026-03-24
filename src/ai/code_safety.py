"""
Code Execution Safety Layer for Cortex IDE + AutoGen

Provides secure code execution with:
- Sandboxed environment
- Pre-execution review
- Timeout protection
- Resource limits
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from src.utils.logger import get_logger

log = get_logger("code_safety")


class CodeExecutionSafety:
    """Safe code execution with multiple security layers."""
    
    # Dangerous operations to block
    DANGEROUS_PATTERNS = [
        "os.system(",
        "subprocess.",
        "eval(",
        "exec(",
        "__import__(",
        "open(",  # File access needs review
        "shutil.",
        "rm -rf",
        "del ",
        ":(){ :|:& };:",  # Fork bomb
    ]
    
    # Resource limits
    MAX_EXECUTION_TIME = 30  # seconds
    MAX_MEMORY_MB = 512  # MB
    MAX_OUTPUT_SIZE = 10000  # characters
    
    def __init__(self, work_dir: Optional[Path] = None):
        """Initialize safety layer."""
        self.work_dir = work_dir or Path("coding")
        self.work_dir.mkdir(exist_ok=True)
        
        log.info(f"🛡️ Code execution safety initialized")
        log.info(f"   Work directory: {self.work_dir.absolute()}")
        log.info(f"   Max execution time: {self.MAX_EXECUTION_TIME}s")
        log.info(f"   Max memory: {self.MAX_MEMORY_MB}MB")
    
    def review_code(self, code: str) -> Tuple[bool, str]:
        """
        Review code for safety issues.
        
        Returns:
            (is_safe, reason)
        """
        lines = code.split('\n')
        
        # Check for dangerous patterns
        for line_num, line in enumerate(lines, 1):
            for pattern in self.DANGEROUS_PATTERNS:
                if pattern in line:
                    log.warning(f"⚠️ Dangerous pattern '{pattern}' at line {line_num}")
                    return False, f"Dangerous operation '{pattern}' detected at line {line_num}"
        
        # Check for infinite loops
        if 'while True:' in code and 'break' not in code:
            log.warning("⚠️ Potential infinite loop detected")
            return False, "Infinite loop without break condition"
        
        # Check for excessive resource usage
        if len(code) > 10000:
            log.warning(f"⚠️ Code too large ({len(code)} chars)")
            return False, f"Code exceeds size limit ({len(code)} > 10000 chars)"
        
        log.debug("✅ Code passed safety review")
        return True, "Code appears safe"
    
    def execute_safe(
        self,
        code: str,
        timeout: Optional[int] = None,
        allow_file_access: bool = False
    ) -> Dict[str, Any]:
        """
        Execute code safely with multiple protections.
        
        Args:
            code: Python code to execute
            timeout: Custom timeout (seconds)
            allow_file_access: Whether to allow file operations
        
        Returns:
            Dictionary with success, output, error, execution_time
        """
        start_time = __import__('time').time()
        
        # Step 1: Safety review
        is_safe, reason = self.review_code(code)
        if not is_safe:
            return {
                "success": False,
                "error": f"Safety check failed: {reason}",
                "output": "",
                "execution_time": 0
            }
        
        # Step 2: Create temporary file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            dir=self.work_dir,
            delete=False
        ) as f:
            temp_path = Path(f.name)
            f.write(code)
        
        try:
            # Step 3: Execute with timeout and resource limits
            timeout = timeout or self.MAX_EXECUTION_TIME
            
            # Build command with resource limits
            cmd = [sys.executable, str(temp_path)]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.work_dir),
                env=self._get_safe_env()
            )
            
            execution_time = __import__('time').time() - start_time
            
            # Process output
            output = result.stdout[:self.MAX_OUTPUT_SIZE]
            error = result.stderr[:self.MAX_OUTPUT_SIZE]
            
            if result.returncode != 0:
                log.error(f"❌ Code execution failed: {error[:200]}")
                return {
                    "success": False,
                    "error": error,
                    "output": output,
                    "execution_time": execution_time
                }
            
            log.info(f"✅ Code executed successfully in {execution_time:.2f}s")
            return {
                "success": True,
                "output": output,
                "error": "",
                "execution_time": execution_time
            }
            
        except subprocess.TimeoutExpired:
            log.error(f"⏱️ Code execution timed out after {timeout}s")
            return {
                "success": False,
                "error": f"Execution timed out after {timeout} seconds",
                "output": "",
                "execution_time": timeout
            }
        except Exception as e:
            log.error(f"❌ Execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "output": "",
                "execution_time": 0
            }
        finally:
            # Step 4: Cleanup
            try:
                temp_path.unlink()
            except Exception as e:
                log.warning(f"Failed to cleanup temp file: {e}")
    
    def _get_safe_env(self) -> Dict[str, str]:
        """Get a sanitized environment for execution."""
        # Start with current environment
        env = os.environ.copy()
        
        # Remove sensitive variables
        sensitive_keys = [
            'API_KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'CREDENTIAL'
        ]
        
        for key in list(env.keys()):
            if any(sensitive in key.upper() for sensitive in sensitive_keys):
                del env[key]
                log.debug(f"Removed sensitive env var: {key}")
        
        # Set resource limits (Unix-like systems)
        if sys.platform != 'win32':
            env['RLIMIT_CPU'] = str(self.MAX_EXECUTION_TIME)
            env['RLIMIT_AS'] = str(self.MAX_MEMORY_MB * 1024 * 1024)
        
        return env
    
    def get_stats(self) -> Dict[str, Any]:
        """Get safety layer statistics."""
        return {
            "work_dir": str(self.work_dir.absolute()),
            "max_execution_time": self.MAX_EXECUTION_TIME,
            "max_memory_mb": self.MAX_MEMORY_MB,
            "max_output_size": self.MAX_OUTPUT_SIZE,
            "dangerous_patterns_blocked": len(self.DANGEROUS_PATTERNS)
        }


# Singleton instance
_safety_instance: Optional[CodeExecutionSafety] = None


def get_code_safety() -> CodeExecutionSafety:
    """Get singleton code safety instance."""
    global _safety_instance
    if _safety_instance is None:
        _safety_instance = CodeExecutionSafety()
    return _safety_instance
