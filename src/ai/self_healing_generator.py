"""
Self-Healing Code Generation System
Autonomously detects and fixes bugs before presenting code to user.
Implements iterative refinement loop similar to Qodo and Cursor.
"""

from typing import Dict, List, Optional, Tuple
import re
import logging
import subprocess
import tempfile
import os
import json
from src.ai.precise_editor import PreciseEditor, SyntaxChecker
from src.ai.enhanced_agent_with_diff import EnhancedAIAgentWithDiff
from src.core.key_manager import get_key_manager

log = logging.getLogger(__name__)


class SelfHealingResult:
    """Result of self-healing process."""
    
    def __init__(self, success: bool, code: str, iterations: int = 0,
                 errors_fixed: List[str] = None, warnings: List[str] = None):
        self.success = success
        self.code = code
        self.iterations = iterations
        self.errors_fixed = errors_fixed or []
        self.warnings = warnings or []
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "code": self.code,
            "iterations": self.iterations,
            "errors_fixed": self.errors_fixed,
            "warnings": self.warnings
        }


class SelfHealingCodeGenerator:
    """
    Generates code with built-in self-healing capabilities.
    
    Workflow:
    1. Generate initial code
    2. Run syntax check
    3. Run linter (if available)
    4. Execute tests (if available)
    5. If errors found → analyze → fix → repeat
    6. Return only when code is clean or max iterations reached
    """
    
    MAX_ITERATIONS = 5  # Prevent infinite loops
    
    def __init__(self, language: str = "python", project_root: str = None):
        self.language = language
        self.project_root = project_root or "."
        self.syntax_checker = SyntaxChecker()
        self.precise_editor = PreciseEditor(self.project_root)
        
        # Language-specific configurations
        self.configs = {
            "python": {
                "file_extension": ".py",
                "lint_command": "pylint",
                "test_command": "pytest",
                "syntax_check": True
            },
            "javascript": {
                "file_extension": ".js",
                "lint_command": "eslint",
                "test_command": "jest",
                "syntax_check": True
            },
            "typescript": {
                "file_extension": ".ts",
                "lint_command": "eslint",
                "test_command": "jest",
                "syntax_check": True
            },
            "java": {
                "file_extension": ".java",
                "lint_command": "checkstyle",
                "test_command": "junit",
                "syntax_check": True
            },
            "rust": {
                "file_extension": ".rs",
                "lint_command": "clippy",
                "test_command": "cargo test",
                "syntax_check": True
            }
        }
    
    def generate_with_self_healing(self, initial_code: str, 
                                   context: Optional[Dict] = None,
                                   file_path: Optional[str] = None) -> SelfHealingResult:
        """
        Generate code and automatically fix any issues found.
        
        Args:
            initial_code: Initial generated code
            context: Additional context (requirements, constraints, etc.)
            file_path: Target file path for testing
        
        Returns:
            SelfHealingResult with cleaned, working code
        """
        log.info("🔧 Starting self-healing code generation...")
        
        current_code = initial_code
        iteration = 0
        errors_fixed = []
        warnings = []
        
        while iteration < self.MAX_ITERATIONS:
            iteration += 1
            log.info(f"   Iteration {iteration}/{self.MAX_ITERATIONS}")
            
            # Step 1: Syntax Check
            syntax_errors = self._check_syntax(current_code, file_path)
            
            if syntax_errors:
                log.warning(f"   ❌ Found {len(syntax_errors)} syntax error(s)")
                errors_fixed.extend(syntax_errors)
                
                # Attempt to fix syntax errors
                current_code = self._fix_syntax_errors(current_code, syntax_errors)
                
                # Continue to next iteration to verify fix
                continue
            
            # Step 2: Lint Check (optional - only if linter available)
            lint_warnings = self._check_linting(current_code, file_path)
            
            if lint_warnings:
                log.info(f"   ⚠️ Found {len(lint_warnings)} linting issue(s)")
                warnings.extend(lint_warnings)
                
                # Fix critical linting issues
                current_code = self._fix_linting_issues(current_code, lint_warnings)
                
                # Continue if we made changes
                if current_code != initial_code:
                    continue
            
            # Step 3: Test Execution (if tests provided)
            if context and context.get("tests"):
                test_results = self._run_tests(current_code, context["tests"], file_path)
                
                if not test_results["passed"]:
                    log.warning(f"   ❌ Tests failed: {test_results['failures']}")
                    
                    # Attempt to fix failing tests
                    current_code = self._fix_test_failures(
                        current_code, 
                        test_results["failures"],
                        context["tests"]
                    )
                    errors_fixed.append("Test failures fixed")
                    continue
            
            # If we reach here, code passed all checks
            log.info(f"   ✅ Self-healing complete! Fixed {len(errors_fixed)} issues")
            
            return SelfHealingResult(
                success=True,
                code=current_code,
                iterations=iteration,
                errors_fixed=errors_fixed,
                warnings=warnings
            )
        
        # Max iterations reached
        log.error(f"   ⚠️ Max iterations ({self.MAX_ITERATIONS}) reached. Returning best effort.")
        
        return SelfHealingResult(
            success=False,
            code=current_code,
            iterations=iteration,
            errors_fixed=errors_fixed,
            warnings=warnings
        )
    
    def _check_syntax(self, code: str, file_path: Optional[str] = None) -> List[str]:
        """Check code for syntax errors."""
        if not self.configs[self.language]["syntax_check"]:
            return []
        
        try:
            # Use existing SyntaxChecker
            result = self.syntax_checker.check_syntax(code, file_path or f"temp{self.configs[self.language]['file_extension']}")
            
            if result.get("valid", True):
                return []
            
            # Extract error messages
            errors = []
            if "errors" in result:
                for error in result["errors"]:
                    errors.append(str(error))
            
            return errors
            
        except Exception as e:
            log.error(f"Syntax check failed: {e}")
            return [f"Syntax check error: {e}"]
    
    def _fix_syntax_errors(self, code: str, errors: List[str]) -> str:
        """Attempt to fix syntax errors using AI-powered correction."""
        log.info(f"   🔧 Fixing {len(errors)} syntax error(s)...")
        
        # Create a fix prompt
        error_context = "\n".join([f"- {err}" for err in errors])
        
        fix_prompt = f"""
The following code has syntax errors that need to be fixed:

ERRORS:
{error_context}

CODE:
```{self.language}
{code}
```

Please fix ALL syntax errors while preserving the original functionality.
Return ONLY the corrected code without explanations.

Common fixes needed:
- Missing colons, parentheses, or brackets
- Indentation errors
- Invalid syntax
- Missing imports
- Type errors
"""
        
        # Use EnhancedAIAgentWithDiff to apply fixes
        try:
            key_manager = get_key_manager()
            api_key = key_manager.get_key("deepseek")
            
            if api_key:
                agent = EnhancedAIAgentWithDiff(api_key=api_key, project_root=self.project_root)
                fixed_code = agent.generate_code(fix_prompt)
                
                # Extract code from markdown blocks if present
                code_match = re.search(r'```(?:\w+)?\n([\s\S]*?)```', fixed_code)
                if code_match:
                    return code_match.group(1).strip()
                return fixed_code.strip()
        except Exception as e:
            log.error(f"Failed to auto-fix syntax errors: {e}")
        
        # Fallback: return original code
        return code
    
    def _run_real_linter(self, code: str, file_path: str) -> List[str]:
        """Run actual linter (Pylint/ESLint) and return warnings."""
        try:
            if self.language == "python":
                # Check if pylint is installed
                try:
                    subprocess.run(['pylint', '--version'], 
                                 capture_output=True, timeout=5)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    log.warning("Pylint not installed. Install with: pip install pylint")
                    return []
                
                # Run pylint on temp file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(code)
                    temp_pylint_file = f.name
                
                try:
                    result = subprocess.run(
                        ['pylint', temp_pylint_file, '--output-format=json', '--reports=n'],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    try:
                        lint_output = json.loads(result.stdout)
                        warnings = []
                        
                        for issue in lint_output:
                            severity = issue.get('type', 'convention')
                            message = f"Line {issue['line']}: {issue['message']} ({severity})"
                            warnings.append(message)
                        
                        return warnings
                        
                    except json.JSONDecodeError:
                        log.error(f"Failed to parse pylint output: {result.stdout}")
                        return []
                finally:
                    try:
                        os.unlink(temp_pylint_file)
                    except:
                        pass
            
            elif self.language == "javascript":
                # Check if eslint is installed
                try:
                    subprocess.run(['eslint', '--version'], 
                                 capture_output=True, timeout=5)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    log.warning("ESLint not installed. Install with: npm install -g eslint")
                    return []
                
                # Run eslint on temp file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
                    f.write(code)
                    temp_eslint_file = f.name
                
                try:
                    result = subprocess.run(
                        ['eslint', temp_eslint_file, '-f', 'json'],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    try:
                        lint_output = json.loads(result.stdout)
                        warnings = []
                        
                        if lint_output and len(lint_output) > 0:
                            for message in lint_output[0].get('messages', []):
                                severity = 'error' if message['severity'] == 2 else 'warning'
                                warning = f"Line {message['line']}: {message['message']} ({severity})"
                                warnings.append(warning)
                        
                        return warnings
                        
                    except (json.JSONDecodeError, IndexError):
                        log.error(f"Failed to parse eslint output: {result.stdout}")
                        return []
                finally:
                    try:
                        os.unlink(temp_eslint_file)
                    except:
                        pass
        
        except subprocess.TimeoutExpired:
            log.error("Linter execution timed out")
            return []
        except Exception as e:
            log.error(f"Linter execution failed: {e}")
            return []
        
        return []
    
    def _check_linting(self, code: str, file_path: Optional[str] = None) -> List[str]:
        """Enhanced linting with real tool integration."""
        # First try real linter if file path provided
        if file_path:
            real_warnings = self._run_real_linter(code, file_path)
            if real_warnings:
                return real_warnings
        
        # Fallback to pattern matching
        warnings = []
        
        if self.language == "python":
            # Basic Python linting patterns
            if re.search(r'\s+$', code, re.MULTILINE):
                warnings.append("Trailing whitespace detected")
            
            if 'import *' in code:
                warnings.append("Wildcard import found (not recommended)")
            
            if len(code.split('\n')) > 500:
                warnings.append("File too long (>500 lines)")
        
        elif self.language == "javascript":
            # Basic JS linting patterns
            if 'var ' in code:
                warnings.append("Use 'let' or 'const' instead of 'var'")
            
            if re.search(r'==[^=]', code):
                warnings.append("Use === instead of ==")
        
        return warnings
    
    def _apply_refactoring(self, code: str, suggestion: str) -> str:
        """Actually apply refactoring suggestion using AI."""
        log.info(f"   🔄 Applying refactoring: {suggestion}")
        
        try:
            key_manager = get_key_manager()
            api_key = key_manager.get_key("deepseek")
            
            if not api_key:
                log.warning("No API key available for refactoring")
                return code
            
            agent = EnhancedAIAgentWithDiff(api_key=api_key, project_root=self.project_root)
            
            prompt = f"""
Refactor this code based on the suggestion below:

SUGGESTION: {suggestion}

CODE:
```{self.language}
{code}
```

Return ONLY the refactored code without explanations.
Apply the refactoring while preserving all functionality.
"""
            
            refactored_code = agent.generate_code(prompt)
            
            # Extract code from markdown blocks if present
            code_match = re.search(r'```(?:\w+)?\n([\s\S]*?)```', refactored_code)
            if code_match:
                return code_match.group(1).strip()
            return refactored_code.strip()
            
        except Exception as e:
            log.error(f"Failed to apply refactoring: {e}")
            return code
    
    def _fix_linting_issues(self, code: str, warnings: List[str]) -> str:
        """Fix linting issues."""
        if not warnings:
            return code
        
        log.info(f"   🔧 Fixing {len(warnings)} linting issue(s)...")
        
        # Check if we should apply AI refactoring
        ai_refactor_keywords = [
            "complexity", "too many", "large", "long", 
            "refactor", "extract", "split", "break down"
        ]
        
        needs_ai_refactor = any(
            any(keyword in warning.lower() for keyword in ai_refactor_keywords)
            for warning in warnings
        )
        
        if needs_ai_refactor:
            # Use AI-powered refactoring
            suggestion = f"Fix these issues: {'; '.join(warnings[:3])}"
            return self._apply_refactoring(code, suggestion)
        
        # Simple automated fixes
        fixed_code = code
        
        if self.language == "python":
            # Remove trailing whitespace
            fixed_code = '\n'.join(line.rstrip() for line in fixed_code.split('\n'))
        
        elif self.language == "javascript":
            # Replace var with let (simple replacement)
            fixed_code = re.sub(r'\bvar\b', 'let', fixed_code)
        
        return fixed_code
    
    def _run_tests(self, code: str, tests: str, file_path: Optional[str] = None) -> Dict:
        """Run actual tests using pytest and return results."""
        log.info("   🧪 Running tests with pytest...")
        
        import subprocess
        import tempfile
        import os
        
        try:
            # Create temporary test file
            with tempfile.NamedTemporaryFile(
                mode='w', 
                suffix='_test.py', 
                delete=False,
                encoding='utf-8'
            ) as f:
                f.write(f"{code}\n\n{tests}")
                test_file = f.name
            
            log.info(f"   Created temp test file: {test_file}")
            
            # Run pytest with verbose output
            result = subprocess.run(
                [
                    'pytest', 
                    test_file,
                    '-v',           # Verbose output
                    '--tb=short',   # Short traceback format
                    '--timeout=30'  # 30 second timeout per test
                ],
                capture_output=True,
                text=True,
                timeout=120  # Total timeout 2 minutes
            )
            
            # Clean up temp file
            try:
                os.unlink(test_file)
            except:
                pass
            
            # Parse results
            if result.returncode == 0:
                log.info("   ✅ All tests passed!")
                return {"passed": True, "failures": []}
            else:
                log.warning(f"   ❌ Tests failed:")
                log.warning(result.stdout[-1000:])  # Last 1000 chars
                
                return {
                    "passed": False,
                    "failures": [result.stdout],
                    "stderr": result.stderr
                }
        
        except subprocess.TimeoutExpired:
            log.error("   ⏰ Test execution timed out")
            return {
                "passed": False,
                "failures": ["Test execution timed out after 120 seconds"]
            }
        except FileNotFoundError:
            log.error("   ❌ pytest not found. Install with: pip install pytest")
            return {
                "passed": False,
                "failures": ["pytest not installed. Install with: pip install pytest"]
            }
        except Exception as e:
            log.error(f"   ❌ Test execution failed: {e}")
            return {
                "passed": False,
                "failures": [str(e)]
            }
    
    def _fix_test_failures(self, code: str, failures: List[str], tests: str) -> str:
        """Fix code based on test failures."""
        log.info(f"   🔧 Fixing {len(failures)} test failure(s)...")
        
        failure_context = "\n".join([f"- {fail}" for fail in failures])
        
        fix_prompt = f"""
The code failed tests. Please fix the issues:

TEST FAILURES:
{failure_context}

TESTS:
```
{tests}
```

CURRENT CODE:
```{self.language}
{code}
```

Modify the code to pass all tests while maintaining correct behavior.
Return ONLY the fixed code.
"""
        
        try:
            from src.ai.enhanced_agent import EnhancedAgent
            from src.core.key_manager import get_key_manager
            
            key_manager = get_key_manager()
            api_key = key_manager.get_key("deepseek")
            
            if api_key:
                agent = EnhancedAgent(api_key=api_key)
                fixed_code = agent.generate_code(fix_prompt)
                
                code_match = re.search(r'```(?:\w+)?\n([\s\S]*?)```', fixed_code)
                if code_match:
                    return code_match.group(1).strip()
                return fixed_code.strip()
        except Exception as e:
            log.error(f"Failed to fix test failures: {e}")
        
        return code


def generate_self_healing_code(code: str, language: str = "python", 
                               context: Optional[Dict] = None,
                               project_root: str = None) -> SelfHealingResult:
    """
    Convenience function for self-healing code generation.
    
    Usage:
        result = generate_self_healing_code(initial_code, language="python")
        if result.success:
            print(f"✅ Clean code after {result.iterations} iterations")
            print(result.code)
    """
    generator = SelfHealingCodeGenerator(language, project_root)
    return generator.generate_with_self_healing(code, context)
