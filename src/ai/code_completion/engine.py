"""
Code Completion Engine
Implements multiple completion strategies (Pattern, Template, AI-based, Context-aware)
"""
import re
import ast
from typing import List, Optional
from src.ai.code_completion.types import (
    CodeIssue, CodeHealthReport, CompletionResult, CompletionCandidate,
    CompletionContext, CompletionStrategy, IssueType, INCOMPLETE_PATTERNS,
    COMPLETION_TEMPLATES, PatternMatch
)
from src.ai.code_completion.analyzer import CodeHealthAnalyzer
from src.utils.logger import get_logger

log = get_logger("code_completion")


class PatternBasedCompleter:
    """Strategy 1: Pattern-based completion"""
    
    def complete(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Apply pattern-based completion"""
        
        if issue.type == IssueType.INCOMPLETE_STRUCTURE:
            return self._complete_structure(issue, code, context)
        
        if issue.type == IssueType.PLACEHOLDER_DETECTED:
            return self._complete_placeholder(issue, code, context)
        
        if issue.type == IssueType.SYNTAX_ERROR:
            return self._fix_syntax(issue, code, context)
        
        return code
    
    def _complete_structure(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Complete incomplete structures (functions, classes, etc.)"""
        lines = code.split('\n')
        line_num = issue.line_number - 1 if issue.line_number else 0
        
        if 0 <= line_num < len(lines):
            line = lines[line_num]
            
            # If current line is just whitespace, check previous line
            if not line.strip() and line_num > 0:
                prev_line = lines[line_num - 1]
                # Check if previous line has a function/class/if/try definition
                if re.match(r'^\s*def\s+\w+', prev_line):
                    indent = len(prev_line) - len(prev_line.lstrip())
                    # Replace the whitespace line with the completion
                    completion = ' ' * (indent + 4) + 'pass  # TODO: Implement'
                    lines[line_num] = completion
                    return '\n'.join(lines)
                elif re.match(r'^\s*class\s+\w+', prev_line):
                    indent = len(prev_line) - len(prev_line.lstrip())
                    completion = ' ' * (indent + 4) + 'pass'
                    lines[line_num] = completion
                    return '\n'.join(lines)
                elif re.match(r'^\s*if\s+.+:', prev_line):
                    indent = len(prev_line) - len(prev_line.lstrip())
                    completion = ' ' * (indent + 4) + 'pass'
                    lines[line_num] = completion
                    return '\n'.join(lines)
                elif re.match(r'^\s*try\s*:', prev_line):
                    indent = len(prev_line) - len(prev_line.lstrip())
                    lines[line_num] = ' ' * (indent + 4) + 'pass'
                    lines.insert(line_num + 1, ' ' * indent + 'except Exception as e:')
                    lines.insert(line_num + 2, ' ' * (indent + 4) + 'logger.error(f"Error: {e}")')
                    return '\n'.join(lines)
            
            # Check for specific patterns on current line
            if re.match(r'^\s*def\s+\w+', line):
                # Add pass to function
                indent = len(line) - len(line.lstrip())
                completion = ' ' * (indent + 4) + 'pass  # TODO: Implement'
                lines.insert(line_num + 1, completion)
                return '\n'.join(lines)
            
            if re.match(r'^\s*class\s+\w+', line):
                # Add pass to class
                indent = len(line) - len(line.lstrip())
                completion = ' ' * (indent + 4) + 'pass'
                lines.insert(line_num + 1, completion)
                return '\n'.join(lines)
            
            if re.match(r'^\s*if\s+.+:', line):
                # Add pass to if
                indent = len(line) - len(line.lstrip())
                completion = ' ' * (indent + 4) + 'pass'
                lines.insert(line_num + 1, completion)
                return '\n'.join(lines)
            
            if re.match(r'^\s*try\s*:', line):
                # Add except to try
                indent = len(line) - len(line.lstrip())
                except_block = [
                    ' ' * (indent + 4) + 'pass',
                    ' ' * indent + 'except Exception as e:',
                    ' ' * (indent + 4) + f'logger.error(f"Error: {{e}}")',
                ]
                for i, block_line in enumerate(except_block):
                    lines.insert(line_num + 1 + i, block_line)
                return '\n'.join(lines)
        
        return code
    
    def _complete_placeholder(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Complete TODO/FIXME placeholders"""
        lines = code.split('\n')
        
        for i, line in enumerate(lines):
            if '# TODO' in line or '# FIXME' in line:
                # Replace simple TODO with implementation hint
                indent = len(line) - len(line.lstrip())
                
                # Generate context-aware implementation
                if 'implement' in issue.context.lower() or 'create' in issue.context.lower():
                    impl = ' ' * (indent + 4) + '# Implementation needed here\n'
                    impl += ' ' * (indent + 4) + 'pass'
                    lines[i] = line.replace('# TODO:', '# TODO (Completed):')
                    lines.insert(i + 1, impl)
                    return '\n'.join(lines)
        
        return code
    
    def _fix_syntax(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Fix common syntax errors"""
        if 'parenthesis' in issue.description.lower() or 'parenthes' in issue.description.lower():
            # Count and balance parentheses
            open_count = code.count('(')
            close_count = code.count(')')
            if open_count > close_count:
                code += ')' * (open_count - close_count)
        
        if 'brace' in issue.description.lower():
            # Count and balance braces
            open_count = code.count('{')
            close_count = code.count('}')
            if open_count > close_count:
                code += '\n}' * (open_count - close_count)
        
        return code


class TemplateBasedCompleter:
    """Strategy 2: Template-based completion"""
    
    def complete(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Apply template-based completion"""
        
        templates = COMPLETION_TEMPLATES.get(context.language, {})
        
        if issue.type == IssueType.MISSING_ERROR_HANDLING:
            return self._add_error_handling(code, templates.get('error_handling', ''))
        
        if issue.type == IssueType.INCOMPLETE_FUNCTION:
            return self._add_function_template(code, templates.get('function_docstring', ''), context)
        
        return code
    
    def _add_error_handling(self, code: str, template: str) -> str:
        """Wrap code in error handling template"""
        if not template:
            return code
        
        # Simple indentation handling
        lines = code.split('\n')
        if len(lines) > 0:
            # Get base indentation
            base_indent = len(lines[0]) - len(lines[0].lstrip())
            indent = ' ' * (base_indent + 4)
            
            # Indent the code
            indented_code = '\n'.join(indent + line for line in lines)
            
            # Wrap in try-except
            completion = template.replace('{code}', indented_code)
            return completion.strip()
        
        return code
    
    def _add_function_template(self, code: str, template: str, context: CompletionContext) -> str:
        """Add docstring template to function"""
        if not template:
            return code
        
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check if function already has docstring
                    if (node.body and isinstance(node.body[0], ast.Expr) and 
                        isinstance(node.body[0].value, ast.Constant) and
                        isinstance(node.body[0].value.value, str)):
                        continue
                    
                    # Insert docstring
                    func_name = node.name
                    params = ', '.join(arg.arg for arg in node.args.args if arg.arg != 'self')
                    
                    docstring = f'\n    """\n    Function {func_name}\n    \n    Args:\n        {params}\n    \n    Returns:\n        TODO: Description\n    """\n'
                    
                    # Find insertion point
                    lines = code.split('\n')
                    insert_line = node.lineno
                    
                    # Add docstring after function definition
                    for i, line in enumerate(lines):
                        if re.match(rf'^\s*def\s+{func_name}\s*\(', line):
                            indent = '    '
                            docstring_lines = [indent + l if l.strip() else l for l in docstring.split('\n')]
                            for j, doc_line in enumerate(docstring_lines):
                                lines.insert(i + 1 + j, doc_line)
                            return '\n'.join(lines)
        except:
            pass
        
        return code


class AIBasedCompleter:
    """Strategy 3: AI-based completion"""
    
    def __init__(self, ai_agent=None):
        self.ai_agent = ai_agent
    
    def complete(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Apply AI-based completion"""
        
        # Build completion prompt
        prompt = self._build_completion_prompt(issue, code, context)
        
        # Use AI agent if available
        if self.ai_agent:
            try:
                # Request completion from AI
                response = self._request_ai_completion(prompt)
                if response:
                    return self._merge_completion(code, response, issue)
            except Exception as e:
                log.error(f"AI completion failed: {e}")
        
        # Fallback: Simple pattern-based completion
        return self._fallback_completion(issue, code, context)
    
    def _build_completion_prompt(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Build prompt for AI completion"""
        return f"""Complete the following {context.language} code. Focus on fixing: {issue.description}

Original Code:
```
{code}
```

Issue Details:
- Type: {issue.type.value}
- Severity: {issue.severity.value}
- Context: {context.hint or 'No additional context'}

Requirements:
1. Fix the {issue.type.value} issue
2. Maintain existing code structure
3. Don't change working parts
4. Add only what's necessary
5. Include appropriate error handling if relevant

Complete the code by filling in missing parts or fixing broken parts.
Output ONLY the completed code, no explanations.
"""
    
    def _request_ai_completion(self, prompt: str) -> str:
        """Request completion from AI agent"""
        # This would integrate with your existing AI agent
        # For now, return None to use fallback
        return None
    
    def _merge_completion(self, original: str, completion: str, issue: CodeIssue) -> str:
        """Smart merge of AI completion with original code"""
        # Extract code from markdown if present
        if '```' in completion:
            match = re.search(r'```(?:\w+)?\n(.*?)```', completion, re.DOTALL)
            if match:
                completion = match.group(1).strip()
        
        return completion
    
    def _fallback_completion(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Fallback completion when AI is not available"""
        # Use pattern-based completer as fallback
        pattern_completer = PatternBasedCompleter()
        return pattern_completer.complete(issue, code, context)


class ContextAwareCompleter:
    """Strategy 4: Context-aware completion"""
    
    def complete(self, issue: CodeIssue, code: str, context: CompletionContext) -> str:
        """Apply context-aware completion"""
        
        # Gather context
        full_context = self._gather_context(code, context)
        
        # Find similar patterns in project
        similar = self._find_similar_patterns(code, full_context)
        
        if similar and issue.type != IssueType.SYNTAX_ERROR:
            # Use similar pattern as template
            return self._apply_similar_pattern(code, similar[0], issue)
        
        # Otherwise, use import/context analysis
        if issue.type == IssueType.UNDEFINED_VARIABLE:
            return self._add_missing_import(code, issue, full_context)
        
        return code
    
    def _gather_context(self, code: str, context: CompletionContext) -> dict:
        """Gather full context for completion"""
        return {
            'language': context.language,
            'file_path': context.file_path,
            'surrounding_code': context.surrounding_code,
            'imports': context.imports,
            'function_scope': context.function_scope,
            'cursor_position': context.cursor_position,
        }
    
    def _find_similar_patterns(self, code: str, context: dict) -> List[PatternMatch]:
        """Find similar code patterns in project"""
        # This would search the codebase for similar patterns
        # For now, return empty list
        return []
    
    def _apply_similar_pattern(self, code: str, pattern: PatternMatch, issue: CodeIssue) -> str:
        """Apply a similar pattern to complete the code"""
        # Replace the incomplete part with the pattern
        return code.replace(pattern.match_text, pattern.completion)
    
    def _add_missing_import(self, code: str, issue: CodeIssue, context: dict) -> str:
        """Add missing import for undefined variable"""
        # Extract variable name from issue description
        match = re.search(r"'(\w+)'", issue.description)
        if match:
            var_name = match.group(1)
            
            # Common import mappings
            import_mappings = {
                'np': 'import numpy as np',
                'pd': 'import pandas as pd',
                'plt': 'import matplotlib.pyplot as plt',
                'os': 'import os',
                'sys': 'import sys',
                'json': 'import json',
                're': 'import re',
                'datetime': 'from datetime import datetime',
                'Path': 'from pathlib import Path',
            }
            
            if var_name in import_mappings:
                import_stmt = import_mappings[var_name]
                # Add import at top of file
                lines = code.split('\n')
                
                # Find insertion point (after existing imports)
                insert_idx = 0
                for i, line in enumerate(lines):
                    if line.startswith('import ') or line.startswith('from '):
                        insert_idx = i + 1
                
                lines.insert(insert_idx, import_stmt)
                return '\n'.join(lines)
        
        return code


class CodeCompletionEngine:
    """Main completion engine that orchestrates all strategies"""
    
    def __init__(self, ai_agent=None):
        self.analyzer = CodeHealthAnalyzer()
        self.pattern_completer = PatternBasedCompleter()
        self.template_completer = TemplateBasedCompleter()
        self.ai_completer = AIBasedCompleter(ai_agent)
        self.context_completer = ContextAwareCompleter()
    
    def complete_code(self, code: str, context: Optional[CompletionContext] = None) -> CompletionResult:
        """
        Complete incomplete/broken code using multiple strategies.
        
        Args:
            code: The code to complete
            context: Optional completion context
            
        Returns:
            CompletionResult with completed code and metadata
        """
        context = context or CompletionContext()
        original_code = code
        
        # Step 1: Analyze code health
        log.info("Analyzing code for completion...")
        health_report = self.analyzer.analyze(code, context.language, context)
        
        if not health_report.completion_required and not health_report.issues:
            log.info("Code is complete, no completion needed")
            return CompletionResult(
                original_code=original_code,
                completed_code=code,
                issues_fixed=0,
                confidence=1.0,
                explanations=["Code is already complete"],
                strategy_used=CompletionStrategy.PATTERN_BASED
            )
        
        log.info(f"Found {len(health_report.issues)} issues requiring completion")
        
        # Step 2: Sort issues by severity
        sorted_issues = self._sort_issues_by_severity(health_report.issues)
        
        # Step 3: Apply completion strategies
        candidates = []
        current_code = code
        
        for issue in sorted_issues:
            log.info(f"Fixing issue: {issue.description}")
            
            # Try strategies in order of priority
            strategy, completed = self._apply_strategies(issue, current_code, context)
            
            if completed != current_code:
                candidates.append(CompletionCandidate(
                    completion=completed,
                    source=strategy.value,
                    confidence=0.8,
                    reasoning=f"Fixed {issue.description} using {strategy.value}"
                ))
                current_code = completed
        
        # Step 4: Validate completion
        log.info("Validating completed code...")
        validation = self._validate_completion(current_code, original_code, health_report)
        
        # Generate explanations
        explanations = self._generate_explanations(sorted_issues)
        
        return CompletionResult(
            original_code=original_code,
            completed_code=current_code,
            issues_fixed=len(sorted_issues),
            confidence=validation['confidence'],
            explanations=explanations,
            alternatives=candidates[:3],
            strategy_used=CompletionStrategy.AI_BASED if self.ai_completer.ai_agent else CompletionStrategy.PATTERN_BASED
        )
    
    def _sort_issues_by_severity(self, issues: List[CodeIssue]) -> List[CodeIssue]:
        """Sort issues by severity"""
        severity_order = {
            'critical': 0,
            'high': 1,
            'medium': 2,
            'low': 3
        }
        return sorted(issues, key=lambda i: severity_order.get(i.severity.value, 4))
    
    def _apply_strategies(self, issue: CodeIssue, code: str, context: CompletionContext) -> tuple:
        """Apply completion strategies in order"""
        
        # Strategy 1: Pattern-based (highest priority for syntax)
        if issue.type == IssueType.SYNTAX_ERROR:
            completed = self.pattern_completer.complete(issue, code, context)
            if completed != code:
                return CompletionStrategy.PATTERN_BASED, completed
        
        # Strategy 2: Pattern-based for structure
        if issue.type in [IssueType.INCOMPLETE_STRUCTURE, IssueType.UNCLOSED_BLOCK]:
            completed = self.pattern_completer.complete(issue, code, context)
            if completed != code:
                return CompletionStrategy.PATTERN_BASED, completed
        
        # Strategy 3: Template-based
        if issue.type in [IssueType.MISSING_ERROR_HANDLING, IssueType.INCOMPLETE_FUNCTION]:
            completed = self.template_completer.complete(issue, code, context)
            if completed != code:
                return CompletionStrategy.TEMPLATE_BASED, completed
        
        # Strategy 4: Context-aware
        if issue.type in [IssueType.UNDEFINED_VARIABLE, IssueType.LOGIC_GAP]:
            completed = self.context_completer.complete(issue, code, context)
            if completed != code:
                return CompletionStrategy.CONTEXT_AWARE, completed
        
        # Strategy 5: AI-based (for complex issues)
        completed = self.ai_completer.complete(issue, code, context)
        return CompletionStrategy.AI_BASED, completed
    
    def _validate_completion(self, completed_code: str, original_code: str, original_report: CodeHealthReport) -> dict:
        """Validate the completed code"""
        # Re-analyze completed code
        new_report = self.analyzer.analyze(completed_code, original_report.language)
        
        # Calculate confidence
        if not new_report.issues:
            confidence = 1.0
        else:
            # Lower confidence if issues remain
            remaining_critical = sum(1 for i in new_report.issues if i.severity.value == 'critical')
            remaining_high = sum(1 for i in new_report.issues if i.severity.value == 'high')
            confidence = max(0.3, 1.0 - (remaining_critical * 0.3) - (remaining_high * 0.2))
        
        return {
            'confidence': confidence,
            'remaining_issues': len(new_report.issues),
            'is_valid': len(new_report.issues) < len(original_report.issues)
        }
    
    def _generate_explanations(self, issues: List[CodeIssue]) -> List[str]:
        """Generate human-readable explanations"""
        explanations = []
        
        for issue in issues:
            if issue.suggestions:
                explanations.append(f"Fixed: {issue.description}")
                explanations.append(f"  -> Applied: {issue.suggestions[0]}")
        
        return explanations


# Singleton instance
_completion_engine = None


def get_code_completion_engine(ai_agent=None) -> CodeCompletionEngine:
    """Get singleton instance of code completion engine"""
    global _completion_engine
    if _completion_engine is None:
        _completion_engine = CodeCompletionEngine(ai_agent)
    return _completion_engine
