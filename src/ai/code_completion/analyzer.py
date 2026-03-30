"""
Code Analysis Engine
Multi-layered code analysis system (Syntax, Structure, Intent, Pattern, Context)
"""
import re
import ast
from typing import List, Optional, Tuple
from src.ai.code_completion.types import (
    CodeIssue, CodeHealthReport, IssueType, IssueSeverity,
    INCOMPLETE_PATTERNS, CompletionContext
)


class SyntaxAnalyzer:
    """Layer 1: Syntax Error Detection"""
    
    def analyze(self, code: str, language: str = "python") -> List[CodeIssue]:
        """Analyze code for syntax errors"""
        issues = []
        
        if language == "python":
            issues.extend(self._analyze_python_syntax(code))
        elif language in ["javascript", "typescript"]:
            issues.extend(self._analyze_js_syntax(code))
        
        return issues
    
    def _analyze_python_syntax(self, code: str) -> List[CodeIssue]:
        """Analyze Python code for syntax errors"""
        issues = []
        
        try:
            ast.parse(code)
        except SyntaxError as e:
            # Check if this is actually an incomplete structure issue
            error_msg = e.msg.lower()
            
            if 'expected an indented block' in error_msg:
                # This is an incomplete structure, not a syntax error
                if 'function definition' in error_msg or 'def ' in code.split('\n')[e.lineno-1] if e.lineno <= len(code.split('\n')) else False:
                    issue_type = IssueType.INCOMPLETE_STRUCTURE
                    description = "Function definition missing body"
                    severity = IssueSeverity.HIGH
                    suggestions = ["Add function body with pass or implementation"]
                elif 'class definition' in error_msg:
                    issue_type = IssueType.INCOMPLETE_STRUCTURE
                    description = "Class definition missing body"
                    severity = IssueSeverity.HIGH
                    suggestions = ["Add class body"]
                elif 'if' in error_msg:
                    issue_type = IssueType.INCOMPLETE_STRUCTURE
                    description = "If statement missing body"
                    severity = IssueSeverity.HIGH
                    suggestions = ["Add if statement body"]
                elif 'for' in error_msg:
                    issue_type = IssueType.INCOMPLETE_STRUCTURE
                    description = "For loop missing body"
                    severity = IssueSeverity.HIGH
                    suggestions = ["Add for loop body"]
                elif 'while' in error_msg:
                    issue_type = IssueType.INCOMPLETE_STRUCTURE
                    description = "While loop missing body"
                    severity = IssueSeverity.HIGH
                    suggestions = ["Add while loop body"]
                else:
                    issue_type = IssueType.INCOMPLETE_STRUCTURE
                    description = f"Incomplete code block: {e.msg}"
                    severity = IssueSeverity.HIGH
                    suggestions = ["Add missing code block body"]
            else:
                issue_type = IssueType.SYNTAX_ERROR
                description = f"Syntax error: {e.msg}"
                severity = IssueSeverity.CRITICAL
                suggestions = ["Check for missing parentheses, colons, or incorrect indentation"]
            
            issues.append(CodeIssue(
                type=issue_type,
                description=description,
                severity=severity,
                position=e.offset,
                line_number=e.lineno,
                column=e.offset,
                suggestions=suggestions,
                language="python"
            ))
        except Exception as e:
            issues.append(CodeIssue(
                type=IssueType.SYNTAX_ERROR,
                description=f"Parse error: {str(e)}",
                severity=IssueSeverity.HIGH,
                suggestions=["Check for invalid Python syntax"],
                language="python"
            ))
        
        return issues
    
    def _analyze_js_syntax(self, code: str) -> List[CodeIssue]:
        """Basic JavaScript syntax checks"""
        issues = []
        
        # Check for unbalanced braces
        open_braces = code.count('{') - code.count('}')
        if open_braces > 0:
            issues.append(CodeIssue(
                type=IssueType.SYNTAX_ERROR,
                description=f"Missing {open_braces} closing brace(s)",
                severity=IssueSeverity.HIGH,
                suggestions=["Add missing '}' to close blocks"],
                language="javascript"
            ))
        elif open_braces < 0:
            issues.append(CodeIssue(
                type=IssueType.SYNTAX_ERROR,
                description=f"Extra {-open_braces} closing brace(s)",
                severity=IssueSeverity.HIGH,
                suggestions=["Remove extra '}'"],
                language="javascript"
            ))
        
        # Check for unbalanced parentheses
        open_parens = code.count('(') - code.count(')')
        if open_parens > 0:
            issues.append(CodeIssue(
                type=IssueType.SYNTAX_ERROR,
                description=f"Missing {open_parens} closing parenthesis(es)",
                severity=IssueSeverity.CRITICAL,
                suggestions=["Add missing ')'"],
                language="javascript"
            ))
        
        return issues


class StructuralAnalyzer:
    """Layer 2: Structural Completeness Analysis"""
    
    def analyze(self, code: str, language: str = "python") -> List[CodeIssue]:
        """Analyze code structure for completeness"""
        issues = []
        
        # Check for incomplete constructs (only if code can be partially parsed)
        try:
            ast.parse(code)
            issues.extend(self._check_incomplete_patterns(code, language))
        except SyntaxError:
            # If there's a syntax error, the incomplete patterns are likely
            # already detected by the syntax analyzer
            pass
        
        # Check for missing returns in functions
        if language == "python":
            issues.extend(self._check_function_returns(code))
        
        # Check for placeholder comments
        issues.extend(self._check_placeholders(code))
        
        return issues
    
    def _check_incomplete_patterns(self, code: str, language: str) -> List[CodeIssue]:
        """Check for incomplete code patterns"""
        issues = []
        
        patterns = INCOMPLETE_PATTERNS.get(language, [])
        lines = code.split('\n')
        
        for i, line in enumerate(lines, 1):
            for pattern_def in patterns:
                if re.search(pattern_def["pattern"], line.strip()):
                    # Check if next line is empty or missing
                    if i < len(lines):
                        next_line = lines[i].strip() if i < len(lines) else ""
                        if not next_line or next_line.startswith('#'):
                            issues.append(CodeIssue(
                                type=IssueType.INCOMPLETE_STRUCTURE,
                                description=pattern_def["description"],
                                severity=IssueSeverity.HIGH,
                                line_number=i,
                                suggestions=[pattern_def.get("completion", "Add implementation")],
                                language=language
                            ))
        
        return issues
    
    def _check_function_returns(self, code: str) -> List[CodeIssue]:
        """Check for functions that might need return statements"""
        issues = []
        
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check if function has return statement
                    has_return = any(
                        isinstance(n, ast.Return) 
                        for n in ast.walk(node)
                        if n is not node
                    )
                    
                    # Check function name patterns that suggest it should return something
                    return_indicators = ['get_', 'find_', 'calculate_', 'compute_', 'parse_', 'convert_']
                    if any(node.name.startswith(ind) for ind in return_indicators) and not has_return:
                        issues.append(CodeIssue(
                            type=IssueType.INCOMPLETE_FUNCTION,
                            description=f"Function '{node.name}' may be missing a return statement",
                            severity=IssueSeverity.MEDIUM,
                            line_number=node.lineno,
                            suggestions=[f"Add 'return' statement to function '{node.name}'"],
                            language="python"
                        ))
        except:
            pass
        
        return issues
    
    def _check_placeholders(self, code: str) -> List[CodeIssue]:
        """Check for placeholder comments and TODOs"""
        issues = []
        
        placeholder_patterns = [
            (r'#\s*TODO[:\s]*(.+)', IssueType.PLACEHOLDER_DETECTED, "TODO comment needs implementation"),
            (r'#\s*FIXME[:\s]*(.+)', IssueType.PLACEHOLDER_DETECTED, "FIXME comment needs attention"),
            (r'#\s*IMPLEMENT[:\s]*(.+)', IssueType.PLACEHOLDER_DETECTED, "Implementation needed"),
            (r'pass\s*$', IssueType.PLACEHOLDER_DETECTED, "Placeholder 'pass' statement"),
            (r'\.\.\.', IssueType.PLACEHOLDER_DETECTED, "Ellipsis placeholder"),
        ]
        
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            for pattern, issue_type, description in placeholder_patterns:
                match = re.search(pattern, line.strip(), re.IGNORECASE)
                if match:
                    context = match.group(1) if match.groups() else line.strip()
                    issues.append(CodeIssue(
                        type=issue_type,
                        description=f"{description}: {context}",
                        severity=IssueSeverity.MEDIUM,
                        line_number=i,
                        context=context,
                        language="python"
                    ))
        
        return issues


class IntentAnalyzer:
    """Layer 3: Intent & Logic Gap Detection"""
    
    def analyze(self, code: str, language: str = "python") -> List[CodeIssue]:
        """Analyze code for logical gaps"""
        issues = []
        
        # Check for undefined variables
        issues.extend(self._check_undefined_variables(code, language))
        
        # Check for missing error handling
        issues.extend(self._check_error_handling(code, language))
        
        # Check for incomplete logic flows
        issues.extend(self._check_logic_completeness(code, language))
        
        return issues
    
    def _check_undefined_variables(self, code: str, language: str) -> List[CodeIssue]:
        """Check for variables used before definition"""
        issues = []
        
        if language == "python":
            try:
                tree = ast.parse(code)
                defined = set()
                used = set()
                
                # Collect function arguments first
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # Add function parameters to defined set
                        for arg in node.args.args:
                            defined.add(arg.arg)
                        for arg in node.args.posonlyargs:
                            defined.add(arg.arg)
                        for arg in node.args.kwonlyargs:
                            defined.add(arg.arg)
                        if node.args.vararg:
                            defined.add(node.args.vararg.arg)
                        if node.args.kwarg:
                            defined.add(node.args.kwarg.arg)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        if isinstance(node.ctx, ast.Store):
                            defined.add(node.id)
                        elif isinstance(node.ctx, ast.Load):
                            used.add(node.id)
                
                # Built-ins and common imports
                built_ins = {'True', 'False', 'None', 'print', 'len', 'range', 'enumerate', 
                           'zip', 'map', 'filter', 'sum', 'min', 'max', 'int', 'str', 'float',
                           'list', 'dict', 'tuple', 'set', 'open', 'isinstance', 'hasattr',
                           'getattr', 'setattr', 'super', 'self', 'cls'}
                
                undefined = used - defined - built_ins
                
                for var in undefined:
                    issues.append(CodeIssue(
                        type=IssueType.UNDEFINED_VARIABLE,
                        description=f"Variable '{var}' may be undefined",
                        severity=IssueSeverity.HIGH,
                        suggestions=[f"Define variable '{var}' before use or import it"],
                        language=language
                    ))
            except:
                pass
        
        return issues
    
    def _check_error_handling(self, code: str, language: str) -> List[CodeIssue]:
        """Check for missing error handling"""
        issues = []
        
        if language == "python":
            try:
                tree = ast.parse(code)
                
                # Check for risky operations without try-except
                risky_operations = [
                    (ast.Call, ['open', 'read', 'write', 'load', 'parse'], 'File/IO operation without error handling'),
                    (ast.Call, ['requests', 'get', 'post', 'put', 'delete'], 'Network call without error handling'),
                    (ast.Call, ['json.loads', 'json.load'], 'JSON parsing without error handling'),
                ]
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        # Check if inside try block
                        in_try = False
                        for parent in ast.walk(tree):
                            if isinstance(parent, ast.Try):
                                if node in ast.walk(parent):
                                    in_try = True
                                    break
                        
                        if not in_try:
                            func_name = ""
                            if isinstance(node.func, ast.Name):
                                func_name = node.func.id
                            elif isinstance(node.func, ast.Attribute):
                                func_name = node.func.attr
                            
                            for _, funcs, msg in risky_operations:
                                if func_name in funcs:
                                    issues.append(CodeIssue(
                                        type=IssueType.MISSING_ERROR_HANDLING,
                                        description=msg,
                                        severity=IssueSeverity.MEDIUM,
                                        line_number=getattr(node, 'lineno', 0),
                                        suggestions=["Wrap in try-except block"],
                                        language=language
                                    ))
            except:
                pass
        
        return issues
    
    def _check_logic_completeness(self, code: str, language: str) -> List[CodeIssue]:
        """Check for incomplete logic flows"""
        issues = []
        
        if language == "python":
            # Check for if statements without else
            if_pattern = r'if\s+.+:\s*\n.+\n(?!\s*else:)'
            if re.search(if_pattern, code):
                # This is a simplified check
                pass
            
            # Check for try without except/finally
            try_pattern = r'try:\s*\n.+(?!\s*except|\s*finally)'
            matches = re.finditer(try_pattern, code, re.MULTILINE | re.DOTALL)
            for match in matches:
                # Check if it's really missing except
                block_end = match.end()
                remaining = code[block_end:block_end+100]
                if 'except' not in remaining and 'finally' not in remaining:
                    issues.append(CodeIssue(
                        type=IssueType.INCOMPLETE_STRUCTURE,
                        description="Try block missing except/finally",
                        severity=IssueSeverity.HIGH,
                        suggestions=["Add 'except' or 'finally' block"],
                        language=language
                    ))
        
        return issues


class PatternAnalyzer:
    """Layer 4: Pattern Recognition"""
    
    def analyze(self, code: str, language: str = "python") -> List[CodeIssue]:
        """Analyze code for pattern-based issues"""
        issues = []
        
        # Check for common anti-patterns
        issues.extend(self._check_antipatterns(code, language))
        
        # Check for code smells
        issues.extend(self._check_code_smells(code, language))
        
        return issues
    
    def _check_antipatterns(self, code: str, language: str) -> List[CodeIssue]:
        """Check for code anti-patterns"""
        issues = []
        
        if language == "python":
            # Check for bare except
            if re.search(r'except\s*:', code):
                issues.append(CodeIssue(
                    type=IssueType.PATTERN_MISMATCH,
                    description="Bare 'except:' clause catches all exceptions including KeyboardInterrupt",
                    severity=IssueSeverity.MEDIUM,
                    suggestions=["Use 'except Exception:' or specific exception types"],
                    language=language
                ))
            
            # Check for mutable default arguments
            if re.search(r'def\s+\w+\s*\([^)]*=\s*(\[|\{)', code):
                issues.append(CodeIssue(
                    type=IssueType.PATTERN_MISMATCH,
                    description="Mutable default argument detected",
                    severity=IssueSeverity.MEDIUM,
                    suggestions=["Use None as default and initialize mutable object inside function"],
                    language=language
                ))
        
        return issues
    
    def _check_code_smells(self, code: str, language: str) -> List[CodeIssue]:
        """Check for code smells"""
        issues = []
        
        if language == "python":
            # Check for very long functions
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        func_length = node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0
                        if func_length > 50:
                            issues.append(CodeIssue(
                                type=IssueType.LOGIC_GAP,
                                description=f"Function '{node.name}' is very long ({func_length} lines)",
                                severity=IssueSeverity.LOW,
                                line_number=node.lineno,
                                suggestions=["Consider breaking into smaller functions"],
                                language=language
                            ))
            except:
                pass
        
        return issues


class CodeHealthAnalyzer:
    """Main analyzer that coordinates all analysis layers"""
    
    def __init__(self):
        self.syntax_analyzer = SyntaxAnalyzer()
        self.structural_analyzer = StructuralAnalyzer()
        self.intent_analyzer = IntentAnalyzer()
        self.pattern_analyzer = PatternAnalyzer()
    
    def analyze(self, code: str, language: str = "python", context: Optional[CompletionContext] = None) -> CodeHealthReport:
        """Perform complete code health analysis"""
        issues = []
        
        # Layer 1: Syntax Analysis
        issues.extend(self.syntax_analyzer.analyze(code, language))
        
        # Only continue if no critical syntax errors
        has_critical = any(i.severity == IssueSeverity.CRITICAL for i in issues)
        
        if not has_critical:
            # Layer 2: Structural Analysis
            issues.extend(self.structural_analyzer.analyze(code, language))
            
            # Layer 3: Intent Analysis
            issues.extend(self.intent_analyzer.analyze(code, language))
            
            # Layer 4: Pattern Analysis
            issues.extend(self.pattern_analyzer.analyze(code, language))
        
        # Calculate overall severity
        severity = self._calculate_severity(issues)
        
        # Determine if completion is required
        completion_required = any(
            i.type in [IssueType.INCOMPLETE_STRUCTURE, IssueType.INCOMPLETE_FUNCTION, 
                      IssueType.PLACEHOLDER_DETECTED, IssueType.MISSING_IMPLEMENTATION]
            for i in issues
        )
        
        return CodeHealthReport(
            code=code,
            issues=issues,
            language=language,
            severity=severity,
            completion_required=completion_required
        )
    
    def _calculate_severity(self, issues: List[CodeIssue]) -> IssueSeverity:
        """Calculate overall severity from issues"""
        if not issues:
            return IssueSeverity.LOW
        
        severities = [i.severity for i in issues]
        
        if IssueSeverity.CRITICAL in severities:
            return IssueSeverity.CRITICAL
        elif IssueSeverity.HIGH in severities:
            return IssueSeverity.HIGH
        elif IssueSeverity.MEDIUM in severities:
            return IssueSeverity.MEDIUM
        else:
            return IssueSeverity.LOW
