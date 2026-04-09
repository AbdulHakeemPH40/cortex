"""
Syntax Checker - Multi-language syntax error detection
Like VS Code's syntax checking for all programming languages
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from src.utils.logger import get_logger
from src.core.lsp_manager import get_lsp_manager

log = get_logger("syntax_checker")


@dataclass
class DiagnosticError:
    """A diagnostic problem found in source code with precise range support."""
    file_path: str
    line: int
    column: int
    message: str
    end_line: int = 0
    end_column: int = 0
    severity: str = "error"  # error, warning, info
    code: str = ""  # Error code if available
    source: str = ""  # Source tool name


@dataclass
class SyntaxResult:
    """Result of syntax checking."""
    file_path: str
    language: str
    errors: List[DiagnosticError]
    success: bool
    check_time_ms: float = 0


class SyntaxChecker:
    """
    Multi-language syntax checker.
    Detects syntax errors for Python, JavaScript, TypeScript, Go, Rust, etc.
    """
    
    # Language detection by extension
    LANGUAGE_EXTENSIONS = {
        '.py': 'python',
        '.pyw': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.mjs': 'javascript',
        '.cjs': 'javascript',
        '.java': 'java',
        '.kt': 'kotlin',
        '.kts': 'kotlin',
        '.go': 'go',
        '.rs': 'rust',
        '.c': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cs': 'csharp',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.m': 'objectivec',
        '.mm': 'objectivec',
        '.r': 'r',
        '.lua': 'lua',
        '.pl': 'perl',
        '.pm': 'perl',
        '.sql': 'sql',
        '.html': 'html',
        '.htm': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.sass': 'sass',
        '.less': 'less',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.xml': 'xml',
        '.sh': 'bash',
        '.bash': 'bash',
        '.zsh': 'bash',
        '.ps1': 'powershell',
        '.vue': 'vue',
        '.svelte': 'svelte',
    }
    
    def __init__(self):
        self._lsp_manager = get_lsp_manager()
        self._opened_files = set()
        self._checkers = {
            'python': self._check_python,
            'javascript': self._check_javascript,
            'typescript': self._check_typescript,
            'java': self._check_java,
            'go': self._check_go,
            'rust': self._check_rust,
            'c': self._check_c,
            'cpp': self._check_cpp,
            'csharp': self._check_csharp,
            'ruby': self._check_ruby,
            'php': self._check_php,
            'json': self._check_json,
            'yaml': self._check_yaml,
            'html': self._check_html,
            'css': self._check_css,
            'sql': self._check_sql,
        }
    
    def detect_language(self, file_path: str) -> str:
        """Detect language from file extension."""
        ext = Path(file_path).suffix.lower()
        return self.LANGUAGE_EXTENSIONS.get(ext, 'unknown')
    
    def check_file(self, file_path: str, content: str = None) -> SyntaxResult:
        """Check a file for syntax errors using LSP + Local fallback."""
        import time
        start_t = time.time()
        
        language = self.detect_language(file_path)
        
        if content is None:
            try:
                content = Path(file_path).read_text(encoding='utf-8', errors='ignore')
            except Exception as e:
                return SyntaxResult(file_path, language, [DiagnosticError(file_path, 0, 0, f"Read error: {e}")], False)

        # 1. 🚀 Industry Standard: LSP Analysis
        errors = self._get_lsp_diagnostics(file_path, content, language)
        
        # 2. Local Fallback (Fast Highlighting / AST)
        checker = self._checkers.get(language, self._check_generic)
        try:
            local_errors = checker(file_path, content)
            # Avoid duplicate warnings for the same line if LSP already caught it
            lsp_lines = {e.line for e in errors}
            for e in local_errors:
                if e.line not in lsp_lines:
                    errors.append(e)
        except Exception as e:
            log.warning(f"Local scanner for {language} failed: {e}")
            
        print(f"[SyntaxChecker] Checked {file_path} ({language}): Found {len(errors)} errors.")
        check_time_ms = (time.time() - start_t) * 1000
        
        return SyntaxResult(
            file_path=file_path,
            language=language,
            errors=errors,
            success=len(errors) == 0,
            check_time_ms=check_time_ms
        )

    def _get_lsp_diagnostics(self, file_path: str, content: str, language: str) -> List[DiagnosticError]:
        """Talk to LSP server and convert standard diagnostics with precise ranges."""
        self._lsp_manager.notify_changed(file_path, content, language)
        
        abs_path = os.path.abspath(file_path)
        raw_diagnostics = self._lsp_manager.get_diagnostics(abs_path)
        standard_errors = []
        
        severity_map = {1: "error", 2: "warning", 3: "info", 4: "info"}
        for d in raw_diagnostics:
            rng_start = d.get("range", {}).get("start", {})
            rng_end = d.get("range", {}).get("end", {})
            
            standard_errors.append(DiagnosticError(
                file_path=abs_path,
                line=rng_start.get("line", 0) + 1,
                column=rng_start.get("character", 0) + 1,
                end_line=rng_end.get("line", 0) + 1,
                end_column=rng_end.get("character", 0) + 1,
                message=d.get("message", "Unknown problem"),
                severity=severity_map.get(d.get("severity", 1), "error"),
                source=f"LSP ({language})", # Source is usually the server's lang
                code=str(d.get("code", ""))
            ))
            
        return standard_errors
    
    def _check_python(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check Python syntax using ast module."""
        errors = []
        
        try:
            import ast
            ast.parse(content)
        except Exception as e:
            # Check specifically for SyntaxError without shadowing it
            if e.__class__.__name__ == 'SyntaxError':
                errors.append(DiagnosticError(
                    file_path=file_path,
                    line=getattr(e, 'lineno', 1) or 1,
                    column=getattr(e, 'offset', 0) or 0,
                    message=getattr(e, 'msg', str(e)) or str(e),
                    code="syntax-error",
                    source="python-ast"
                ))
        
        # Try py_compile for additional checks
        try:
            import py_compile
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', delete=False, encoding='utf-8'
            ) as f:
                f.write(content)
                temp_path = f.name
            
            try:
                py_compile.compile(temp_path, doraise=True)
            except py_compile.PyCompileError as e:
                # Parse line number from error message
                match = re.search(r'line (\d+)', str(e))
                line = int(match.group(1)) if match else 1
                errors.append(DiagnosticError(
                    file_path=file_path,
                    line=line,
                    column=0,
                    message=str(e).split('\n')[0],
                    code="compile-error",
                    source="py-compile"
                ))
            finally:
                os.unlink(temp_path)
        except Exception:
            pass
        
        return errors
    
    def _check_javascript(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check JavaScript syntax using Node.js."""
        return self._check_with_node(file_path, content)
    
    def _check_typescript(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check TypeScript syntax using tsc or Node.js."""
        # Try tsc if available
        errors = self._check_with_tsc(file_path, content)
        if not errors:
            # Fall back to JS checking
            errors = self._check_with_node(file_path, content)
        return errors
    
    def _check_with_node(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check JS syntax using Node.js --check or -e."""
        errors = []
        
        try:
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
                f.write(content)
                temp_path = f.name
                
            result = subprocess.run(
                ['node', '--check', temp_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=5
            )
            with open('tmp/node_test_input.js', 'w', encoding='utf-8') as dbg:
                dbg.write(content)
            
            if result.returncode != 0:
                errors.extend(self._parse_node_error(result.stderr, file_path))
                
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        except FileNotFoundError:
            # Node not installed - try basic regex checks
            errors = self._check_js_regex(file_path, content)
        except subprocess.TimeoutExpired:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="Syntax check timed out"
            ))
        except Exception as e:
            log.debug(f"Node syntax check failed: {e}")
            errors = self._check_js_regex(file_path, content)
        
        return errors
    
    def _check_with_tsc(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check TypeScript syntax using tsc."""
        errors = []
        
        try:
            result = subprocess.run(
                ['tsc', '--noEmit', '--skipLibCheck', file_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                errors.extend(self._parse_tsc_error(result.stdout, file_path))
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            log.debug(f"TSC check failed: {e}")
        
        return errors
    
    def _parse_node_error(self, stderr: str, file_path: str) -> List[DiagnosticError]:
        """Parse Node.js error output."""
        errors = []
        
        lines = stderr.strip().split('\n')
        line_num = 1
        col_num = 0
        
        # In node errors, the first line is usually "filename:line" or similar
        if lines:
            first_line_match = re.search(r':(\d+)(?::(\d+))?', lines[0])
            if first_line_match:
                line_num = int(first_line_match.group(1))
                if len(first_line_match.groups()) > 1 and first_line_match.group(2):
                    col_num = int(first_line_match.group(2))

        for line in lines:
            if 'SyntaxError' in line or 'Error' in line:
                # Get error message
                msg_match = re.search(r'(?:SyntaxError|Error):\s*(.+)', line)
                msg = msg_match.group(1) if msg_match else line
                
                errors.append(DiagnosticError(
                    file_path=file_path,
                    line=line_num,
                    column=col_num,
                    message=msg.strip(),
                    source="node"
                ))
                break
        
        return errors
    
    def _parse_tsc_error(self, stdout: str, file_path: str) -> List[DiagnosticError]:
        """Parse TypeScript compiler error output."""
        errors = []
        
        # Example: file.ts(5,10): error TS1005: ';' expected.
        pattern = r'(.+?)\((\d+),(\d+)\): error (TS\d+): (.+)'
        
        for line in stdout.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                errors.append(DiagnosticError(
                    file_path=match.group(1),
                    line=int(match.group(2)),
                    column=int(match.group(3)),
                    message=match.group(5),
                    code=match.group(4),
                    source="tsc"
                ))
        
        return errors
    
    def _check_js_regex(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Basic JavaScript syntax check using regex patterns."""
        errors = []
        lines = content.split('\n')
        
        # Check for common JS errors
        open_braces = 0
        open_brackets = 0
        open_parens = 0
        
        for line_num, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith('//'):
                continue
            
            # Count brackets
            open_braces += line.count('{') - line.count('}')
            open_brackets += line.count('[') - line.count(']')
            open_parens += line.count('(') - line.count(')')
            
            # Check for missing semicolon (basic)
            stripped = line.strip()
            if stripped and not stripped.endswith(('{', '}', ',', ';', ':', '\\')):
                if not any(kw in stripped for kw in ['if', 'else', 'for', 'while', 'function', 'class']):
                    # Likely issue but not definitive
                    pass
            
            # Check for unmatched quotes
            single_quotes = line.count("'") - line.count("\\'")
            double_quotes = line.count('"') - line.count('\\"')
            backticks = line.count('`')
            
            # Odd quote counts might indicate issues
            # (simplified - doesn't handle multi-line strings well)
        
        # Check for unbalanced brackets
        if open_braces != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced braces: {abs(open_braces)} {'missing' if open_braces > 0 else 'extra'}",
                severity="warning",
                source="regex"
            ))
        
        if open_brackets != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced brackets: {abs(open_brackets)} {'missing' if open_brackets > 0 else 'extra'} ]",
                severity="warning",
                source="regex"
            ))
        
        if open_parens != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced parentheses: {abs(open_parens)} {'missing' if open_parens > 0 else 'extra'} )",
                severity="warning",
                source="regex"
            ))
        
        return errors
    
    def _check_java(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check Java syntax using javac."""
        errors = []
        
        try:
            result = subprocess.run(
                ['javac', '-Xlint:none', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                errors.extend(self._parse_java_error(result.stderr, file_path))
        except FileNotFoundError:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="javac not installed - cannot check Java syntax",
                severity="warning"
            ))
        except subprocess.TimeoutExpired:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="Java syntax check timed out"
            ))
        except Exception as e:
            log.debug(f"Java check failed: {e}")
        
        return errors
    
    def _parse_java_error(self, stderr: str, file_path: str) -> List[DiagnosticError]:
        """Parse Java compiler error output."""
        errors = []
        
        # Example: File.java:5: error: ';' expected
        pattern = r'(.+\.java):(\d+): error: (.+)'
        
        for line in stderr.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                errors.append(DiagnosticError(
                    file_path=match.group(1),
                    line=int(match.group(2)),
                    column=0,
                    message=match.group(3),
                    source="javac"
                ))
        
        return errors
    
    def _check_go(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check Go syntax using go vet/parser."""
        errors = []
        
        try:
            result = subprocess.run(
                ['go', 'vet', file_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                errors.extend(self._parse_go_error(result.stderr, file_path))
        except FileNotFoundError:
            # Try basic Go regex check
            errors = self._check_go_regex(file_path, content)
        except subprocess.TimeoutExpired:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="Go syntax check timed out"
            ))
        except Exception as e:
            log.debug(f"Go check failed: {e}")
        
        return errors
    
    def _check_go_regex(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Basic Go syntax check using regex."""
        errors = []
        
        # Check for common Go issues
        lines = content.split('\n')
        open_braces = 0
        
        for line_num, line in enumerate(lines, 1):
            open_braces += line.count('{') - line.count('}')
        
        if open_braces != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced braces in Go file",
                severity="warning"
            ))
        
        return errors
    
    def _parse_go_error(self, stderr: str, file_path: str) -> List[DiagnosticError]:
        """Parse Go vet output."""
        errors = []
        
        # Example: file.go:5: syntax error
        pattern = r'(.+\.go):(\d+)(?::(\d+))?: (.+)'
        
        for line in stderr.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                errors.append(DiagnosticError(
                    file_path=match.group(1),
                    line=int(match.group(2)),
                    column=int(match.group(3)) if match.group(3) else 0,
                    message=match.group(4),
                    source="go-vet"
                ))
        
        return errors
    
    def _check_rust(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check Rust syntax using rustc --check."""
        errors = []
        
        try:
            result = subprocess.run(
                ['rustc', '--error-format=short', '-Z', 'parse-only', file_path],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                errors.extend(self._parse_rust_error(result.stderr, file_path))
        except FileNotFoundError:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="rustc not installed - cannot check Rust syntax",
                severity="warning"
            ))
        except subprocess.TimeoutExpired:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="Rust syntax check timed out"
            ))
        except Exception as e:
            log.debug(f"Rust check failed: {e}")
        
        return errors
    
    def _parse_rust_error(self, stderr: str, file_path: str) -> List[DiagnosticError]:
        """Parse Rust compiler output."""
        errors = []
        
        # Example: file.rs:5:10: error: expected `;`
        pattern = r'(.+\.rs):(\d+):(\d+): error: (.+)'
        
        for line in stderr.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                errors.append(DiagnosticError(
                    file_path=match.group(1),
                    line=int(match.group(2)),
                    column=int(match.group(3)),
                    message=match.group(4),
                    source="rustc"
                ))
        
        return errors
    
    def _check_c(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check C syntax using gcc/clang."""
        return self._check_c_cpp(file_path, content, is_cpp=False)
    
    def _check_cpp(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check C++ syntax using g++/clang++."""
        return self._check_c_cpp(file_path, content, is_cpp=True)
    
    def _check_c_cpp(self, file_path: str, content: str, is_cpp: bool) -> List[DiagnosticError]:
        """Check C/C++ syntax."""
        errors = []
        compiler = 'g++' if is_cpp else 'gcc'
        ext = '.cpp' if is_cpp else '.c'
        
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix=ext, delete=False, encoding='utf-8'
            ) as f:
                f.write(content)
                temp_path = f.name
            
            result = subprocess.run(
                [compiler, '-fsyntax-only', '-w', temp_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                errors.extend(self._parse_c_error(result.stderr, file_path))
            
            os.unlink(temp_path)
        except FileNotFoundError:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message=f"{compiler} not installed - cannot check {'C++' if is_cpp else 'C'} syntax",
                severity="warning"
            ))
        except Exception as e:
            log.debug(f"C/C++ check failed: {e}")
        
        return errors
    
    def _parse_c_error(self, stderr: str, file_path: str) -> List[DiagnosticError]:
        """Parse GCC/Clang error output."""
        errors = []
        
        # Example: file.c:5:10: error: expected ';' before '}'
        pattern = r'(.+):(\d+):(\d+): error: (.+)'
        
        for line in stderr.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                errors.append(DiagnosticError(
                    file_path=match.group(1),
                    line=int(match.group(2)),
                    column=int(match.group(3)),
                    message=match.group(4),
                    source="gcc"
                ))
        
        return errors
    
    def _check_csharp(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check C# syntax using dotnet build."""
        errors = []
        
        try:
            # dotnet build requires a project file, so we'll use csc if available
            result = subprocess.run(
                ['csc', '-target:library', file_path],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                errors.extend(self._parse_csharp_error(result.stderr, file_path))
        except FileNotFoundError:
            # Try basic syntax check
            errors = self._check_csharp_regex(file_path, content)
        except subprocess.TimeoutExpired:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="C# syntax check timed out"
            ))
        except Exception as e:
            log.debug(f"C# check failed: {e}")
        
        return errors
    
    def _check_csharp_regex(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Basic C# syntax check."""
        errors = []
        
        # Check for common issues
        lines = content.split('\n')
        open_braces = 0
        
        for line in lines:
            open_braces += line.count('{') - line.count('}')
        
        if open_braces != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced braces",
                severity="warning"
            ))
        
        return errors
    
    def _parse_csharp_error(self, stderr: str, file_path: str) -> List[DiagnosticError]:
        """Parse C# compiler error output."""
        errors = []
        
        # Example: file.cs(5,10): error CS1002: ; expected
        pattern = r'(.+\.cs)\((\d+),(\d+)\): error (CS\d+): (.+)'
        
        for line in stderr.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                errors.append(DiagnosticError(
                    file_path=match.group(1),
                    line=int(match.group(2)),
                    column=int(match.group(3)),
                    message=match.group(5),
                    code=match.group(4),
                    source="csc"
                ))
        
        return errors
    
    def _check_ruby(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check Ruby syntax using ruby -c."""
        errors = []
        
        try:
            result = subprocess.run(
                ['ruby', '-c', file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                errors.extend(self._parse_ruby_error(result.stderr, file_path))
        except FileNotFoundError:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="ruby not installed - cannot check Ruby syntax",
                severity="warning"
            ))
        except subprocess.TimeoutExpired:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="Ruby syntax check timed out"
            ))
        except Exception as e:
            log.debug(f"Ruby check failed: {e}")
        
        return errors
    
    def _parse_ruby_error(self, stderr: str, file_path: str) -> List[DiagnosticError]:
        """Parse Ruby syntax error."""
        errors = []
        
        # Example: file.rb:5: syntax error, unexpected '}'
        pattern = r'(.+):(\d+): (.+)'
        
        for line in stderr.strip().split('\n'):
            match = re.match(pattern, line)
            if match and 'syntax' in line.lower():
                errors.append(DiagnosticError(
                    file_path=match.group(1),
                    line=int(match.group(2)),
                    column=0,
                    message=match.group(3),
                    source="ruby"
                ))
        
        return errors
    
    def _check_php(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check PHP syntax using php -l."""
        errors = []
        
        try:
            result = subprocess.run(
                ['php', '-l', file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0 or 'Parse error' in result.stdout:
                errors.extend(self._parse_php_error(
                    result.stderr or result.stdout, file_path
                ))
        except FileNotFoundError:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="php not installed - cannot check PHP syntax",
                severity="warning"
            ))
        except subprocess.TimeoutExpired:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=0,
                column=0,
                message="PHP syntax check timed out"
            ))
        except Exception as e:
            log.debug(f"PHP check failed: {e}")
        
        return errors
    
    def _parse_php_error(self, output: str, file_path: str) -> List[DiagnosticError]:
        """Parse PHP linter output."""
        errors = []
        
        # Example: Parse error: syntax error in file.php on line 5
        pattern = r'Parse error: (.+?) in (.+?) on line (\d+)'
        
        match = re.search(pattern, output)
        if match:
            errors.append(DiagnosticError(
                file_path=match.group(2),
                line=int(match.group(3)),
                column=0,
                message=match.group(1),
                source="php-lint"
            ))
        
        return errors
    
    def _check_json(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check JSON syntax."""
        errors = []
        
        try:
            import json
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=e.lineno or 1,
                column=e.colno or 0,
                message=e.msg,
                code="json-parse",
                source="json"
            ))
        
        return errors
    
    def _check_yaml(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check YAML syntax."""
        errors = []
        
        try:
            import yaml
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            # Try to extract line number
            line = 1
            if hasattr(e, 'problem_mark') and e.problem_mark:
                line = e.problem_mark.line + 1
            
            errors.append(DiagnosticError(
                file_path=file_path,
                line=line,
                column=0,
                message=str(e).split('\n')[0],
                code="yaml-parse",
                source="yaml"
            ))
        except ImportError:
            # fallback to basic check
            pass
        
        return errors
    
    def _check_html(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check HTML for basic issues and embedded languages (JS/CSS)."""
        errors = []
        
        # 1. Basic HTML Tag Check
        # IMPORTANT: Strip <script> and <style> block CONTENT first to prevent
        # JS template strings like innerHTML='<span>' from being treated as HTML tags.
        # Also strip HTML comments to avoid false positives.
        
        # These tags are self-closing / void and never need a closing tag
        VOID_TAGS = {
            'br', 'hr', 'img', 'input', 'meta', 'link', 'area', 'base', 'col',
            'embed', 'param', 'source', 'track', 'wbr', 'command', 'keygen', 'menuitem'
        }
        # These tags have OPTIONAL closing in HTML5 — their absence is valid,
        # and browsers auto-close them. We handle them leniently but still
        # report genuine mismatches if a wrong tag closes them.
        # NOTE: html/body/head are NOT here — they ARE real structural tags
        # and extra/mismatched ones should be caught.
        OPTIONAL_CLOSE_TAGS = {
            'p', 'li', 'dt', 'dd', 'td', 'th', 'tr', 'option', 'optgroup',
            'colgroup', 'caption', 'thead', 'tbody', 'tfoot'
        }
        
        # Strip <script>...</script> and <style>...</style> content (keep tags, blank inner)
        # This prevents JS template strings like `'<span class="x">'` from polluting the stack
        stripped = re.sub(
            r'(<script[^>]*>)(.*?)(</script>)',
            lambda m: m.group(1) + ' ' + m.group(3),
            content, flags=re.DOTALL | re.IGNORECASE
        )
        stripped = re.sub(
            r'(<style[^>]*>)(.*?)(</style>)',
            lambda m: m.group(1) + ' ' + m.group(3),
            stripped, flags=re.DOTALL | re.IGNORECASE
        )
        # Strip HTML comments (e.g. <!-- comment --> containing tags)
        stripped = re.sub(r'<!--.*?-->', '', stripped, flags=re.DOTALL)
        
        tag_stack = []  # list of (tag_name, line_num)
        pattern = r'<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*?/?>'
        
        for match in re.finditer(pattern, stripped):
            is_closing = match.group(1) == '/'
            tag_name = match.group(2).lower()
            line_num = content[:match.start()].count('\n') + 1
            
            # Skip self-closing tags — they never need a closing counterpart
            if tag_name in VOID_TAGS:
                continue
            # Skip self-closing syntax: <br/>, <img/>
            if match.group(0).rstrip().endswith('/>'):
                continue
            
            if is_closing:
                if tag_stack and tag_stack[-1][0] == tag_name:
                    # Perfect match at top of stack
                    tag_stack.pop()
                elif tag_name in OPTIONAL_CLOSE_TAGS:
                    # Optional tag: pop up to it (browser-style auto-close intervening optionals)
                    while tag_stack and tag_stack[-1][0] != tag_name:
                        if tag_stack[-1][0] in OPTIONAL_CLOSE_TAGS:
                            tag_stack.pop()
                        else:
                            break
                    if tag_stack and tag_stack[-1][0] == tag_name:
                        tag_stack.pop()
                    # If not found, silently ignore (HTML5 optional close)
                elif tag_name in [t[0] for t in tag_stack]:
                    # Tag is deeper in the stack — try to get to it
                    while tag_stack and tag_stack[-1][0] != tag_name:
                        blocked = tag_stack[-1]
                        if blocked[0] in OPTIONAL_CLOSE_TAGS:
                            tag_stack.pop()  # auto-close optional
                        else:
                            # Real unclosed tag blocking — report mismatch
                            errors.append(DiagnosticError(
                                file_path, line_num, 0,
                                f"Mismatched closing tag </{tag_name}> — expected </{blocked[0]}>",
                                "warning", source="html-tag"
                            ))
                            break
                    if tag_stack and tag_stack[-1][0] == tag_name:
                        tag_stack.pop()
                else:
                    # Tag not in stack at all — extra/unexpected closing tag (real error)
                    errors.append(DiagnosticError(
                        file_path, line_num, 0,
                        f"Unexpected closing tag </{tag_name}> with no matching opening tag",
                        "warning", source="html-tag"
                    ))
            else:
                tag_stack.append((tag_name, line_num))
        
        # Report genuinely unclosed tags (exclude optional-close ones)
        unclosed = [(t, ln) for t, ln in tag_stack if t not in OPTIONAL_CLOSE_TAGS]
        for tag, ln in unclosed:
            errors.append(DiagnosticError(
                file_path, ln, 0,
                f"Unclosed tag <{tag}>",
                "warning", source="html-tag"
            ))

        # 2. Check Embedded JavaScript (<script> blocks)
        script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
        for match in script_pattern.finditer(content):
            inner_js = match.group(1)
            line_offset = content[:match.start()].count('\n')
            if inner_js.strip():
                js_errors = self._check_javascript(file_path, inner_js.lstrip())
                for e in js_errors:
                    e.line += line_offset
                    e.source = f"html-js ({e.source})"
                    errors.append(e)

        # 3. Check Embedded CSS (<style> blocks)
        style_pattern = re.compile(r'<style[^>]*>(.*?)</style>', re.DOTALL | re.IGNORECASE)
        for match in style_pattern.finditer(content):
            inner_css = match.group(1)
            line_offset = content[:match.start()].count('\n')
            if inner_css.strip():
                css_errors = self._check_css(file_path, inner_css)
                for e in css_errors:
                    e.line += line_offset
                    errors.append(e)
        
        return errors
    
    def _check_css(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check CSS for basic issues."""
        errors = []
        
        # Check for unmatched braces
        open_braces = content.count('{') - content.count('}')
        if open_braces != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced braces: {abs(open_braces)} {'missing' if open_braces > 0 else 'extra'}",
                severity="warning",
                source="css-check"
            ))
        
        return errors
    
    def _check_sql(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Check SQL for basic issues."""
        errors = []
        
        # Basic SQL checks
        content_upper = content.upper()
        
        # Check for common keywords
        if 'SELECT' in content_upper and 'FROM' not in content_upper:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message="SELECT without FROM clause",
                severity="info",
                source="sql-check"
            ))
        
        return errors
    
    def _check_generic(self, file_path: str, content: str) -> List[DiagnosticError]:
        """Generic syntax check for unknown languages."""
        errors = []
        
        # Check for common issues
        open_parens = content.count('(') - content.count(')')
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        if open_parens != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced parentheses",
                severity="warning",
                source="generic"
            ))
        
        if open_braces != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced braces",
                severity="warning",
                source="generic"
            ))
        
        if open_brackets != 0:
            errors.append(DiagnosticError(
                file_path=file_path,
                line=1,
                column=0,
                message=f"Unbalanced brackets",
                severity="warning",
                source="generic"
            ))
        
        return errors


# Global instance
_syntax_checker: Optional[SyntaxChecker] = None


def get_syntax_checker() -> SyntaxChecker:
    """Get or create the global syntax checker."""
    global _syntax_checker
    if _syntax_checker is None:
        _syntax_checker = SyntaxChecker()
    return _syntax_checker
