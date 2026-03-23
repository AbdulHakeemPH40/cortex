"""
Error Pattern Recognition and Debugging System
Works for ANY framework - Django, Flask, FastAPI, React, Vue, Express, etc.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from src.utils.logger import get_logger

log = get_logger("error_analyzer")


@dataclass
class ErrorContext:
    """Extracted context from an error."""
    error_type: str
    error_message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    code_snippet: List[str] = field(default_factory=list)
    traceback_lines: List[str] = field(default_factory=list)
    framework: str = "unknown"
    suggested_files: List[str] = field(default_factory=list)
    fix_suggestion: str = ""


class ErrorAnalyzer:
    """
    Generic error analyzer that works for any framework.
    Extracts error context, detects framework, suggests fixes.
    """
    
    # Framework detection patterns
    FRAMEWORK_FILES = {
        'django': ['manage.py', 'settings.py', 'asgi.py', 'wsgi.py'],
        'flask': ['app.py', 'wsgi.py'],
        'fastapi': ['main.py', 'app.py'],
        'react': ['package.json'],
        'vue': ['vue.config.js', 'vite.config.js'],
        'express': ['app.js', 'server.js', 'index.js'],
        'spring': ['pom.xml', 'build.gradle'],
        'dotnet': ['*.csproj', '*.sln'],
        'rails': ['Gemfile', 'config/routes.rb'],
        'laravel': ['artisan', 'composer.json'],
    }
    
    # Generic error patterns (framework-agnostic)
    ERROR_PATTERNS = {
        # Import/Module errors
        'ImportError': {
            'cause': 'Module or package not found',
            'check_files': ['requirements.txt', 'package.json', 'imports'],
            'fix_hint': 'Install missing package or fix import path',
        },
        'ModuleNotFoundError': {
            'cause': 'Python module not installed',
            'check_files': ['requirements.txt', 'pyproject.toml'],
            'fix_hint': 'pip install <module> or add to requirements.txt',
        },
        
        # Path/URL errors
        'NoReverseMatch': {
            'cause': 'URL/route name not found',
            'check_files': ['urls.py', 'urls/', 'routes/', 'routes.py'],
            'fix_hint': 'Add URL/route definition or fix template reference',
        },
        'Http404': {
            'cause': 'Page/resource not found',
            'check_files': ['urls.py', 'views.py', 'routes/'],
            'fix_hint': 'Check URL pattern or add missing route',
        },
        
        # Template/view errors
        'TemplateDoesNotExist': {
            'cause': 'Template file missing',
            'check_files': ['templates/', 'settings.py', 'views.py'],
            'fix_hint': 'Create template or fix template path',
        },
        'TemplateSyntaxError': {
            'cause': 'Syntax error in template',
            'check_files': ['templates/'],
            'fix_hint': 'Fix template syntax (check braces, tags, filters)',
        },
        
        # Type/Attribute errors
        'TypeError': {
            'cause': 'Wrong type or arguments',
            'check_files': ['function definition'],
            'fix_hint': 'Check function signature and arguments passed',
        },
        'AttributeError': {
            'cause': 'Object missing attribute/method',
            'check_files': ['class definition'],
            'fix_hint': 'Check if object has the attribute, or if object is None',
        },
        'KeyError': {
            'cause': 'Dictionary key not found',
            'check_files': ['data access code'],
            'fix_hint': 'Check if key exists, use .get() for safe access',
        },
        'IndexError': {
            'cause': 'List/array index out of range',
            'check_files': ['list access code'],
            'fix_hint': 'Check list length before accessing index',
        },
        
        # Database errors
        'OperationalError': {
            'cause': 'Database connection/query error',
            'check_files': ['settings.py', 'models.py', 'migrations/'],
            'fix_hint': 'Check database connection, run migrations',
        },
        'IntegrityError': {
            'cause': 'Database constraint violation',
            'check_files': ['models.py', 'database schema'],
            'fix_hint': 'Check unique constraints, foreign keys',
        },
        
        # Permission/Config errors
        'PermissionError': {
            'cause': 'File/folder permission denied',
            'check_files': ['file permissions'],
            'fix_hint': 'Check file permissions, run with correct privileges',
        },
        'FileNotFoundError': {
            'cause': 'File does not exist',
            'check_files': ['file path'],
            'fix_hint': 'Create file or fix path',
        },
        
        # Syntax errors
        'SyntaxError': {
            'cause': 'Invalid syntax',
            'check_files': ['file at line number'],
            'fix_hint': 'Fix syntax error (missing colon, bracket, etc.)',
        },
        'IndentationError': {
            'cause': 'Wrong indentation',
            'check_files': ['file at line number'],
            'fix_hint': 'Fix indentation (use consistent spaces/tabs)',
        },
        
        # Connection/Network errors
        'ConnectionError': {
            'cause': 'Network connection failed',
            'check_files': ['API endpoints', 'settings.py'],
            'fix_hint': 'Check URL, port, network connectivity',
        },
        'TimeoutError': {
            'cause': 'Request timed out',
            'check_files': ['API calls', 'timeout settings'],
            'fix_hint': 'Increase timeout or check slow service',
        },
    }
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root) if project_root else None
        self._framework_cache: Optional[str] = None
    
    def detect_framework(self) -> str:
        """Detect the project framework."""
        if self._framework_cache:
            return self._framework_cache
        
        if not self.project_root or not self.project_root.exists():
            return "unknown"
        
        try:
            root_files = list(self.project_root.glob('*'))
            root_names = [f.name for f in root_files if f.is_file()]
            root_dirs = [f.name for f in root_files if f.is_dir()]
            
            # Check package.json for JS frameworks
            package_json = self.project_root / 'package.json'
            if package_json.exists():
                try:
                    import json
                    with open(package_json) as f:
                        pkg = json.load(f)
                    deps = list(pkg.get('dependencies', {}).keys())
                    dev_deps = list(pkg.get('devDependencies', {}).keys())
                    all_deps = deps + dev_deps
                    
                    if 'next' in all_deps:
                        self._framework_cache = 'nextjs'
                    elif 'react' in all_deps:
                        self._framework_cache = 'react'
                    elif 'vue' in all_deps:
                        self._framework_cache = 'vue'
                    elif 'express' in all_deps:
                        self._framework_cache = 'express'
                    elif 'svelte' in all_deps:
                        self._framework_cache = 'svelte'
                    elif 'angular' in all_deps or '@angular/core' in all_deps:
                        self._framework_cache = 'angular'
                    else:
                        self._framework_cache = 'nodejs'
                    return self._framework_cache
                except Exception:
                    pass
            
            # Check Python frameworks
            if 'manage.py' in root_names:
                self._framework_cache = 'django'
            elif 'asgi.py' in root_names or 'wsgi.py' in root_names:
                self._framework_cache = 'django'
            elif any('settings' in str(f) for f in root_files):
                # Check for Django settings
                for f in root_files:
                    if 'settings' in str(f):
                        self._framework_cache = 'django'
                        break
            elif 'app.py' in root_names:
                # Could be Flask or FastAPI
                app_file = self.project_root / 'app.py'
                try:
                    content = app_file.read_text(encoding='utf-8', errors='ignore')
                    if 'FastAPI' in content or 'fastapi' in content:
                        self._framework_cache = 'fastapi'
                    elif 'Flask' in content or 'flask' in content:
                        self._framework_cache = 'flask'
                    else:
                        self._framework_cache = 'flask'
                except:
                    self._framework_cache = 'flask'
            elif 'main.py' in root_names:
                main_file = self.project_root / 'main.py'
                try:
                    content = main_file.read_text(encoding='utf-8', errors='ignore')
                    if 'FastAPI' in content or 'fastapi' in content:
                        self._framework_cache = 'fastapi'
                    elif 'Flask' in content:
                        self._framework_cache = 'flask'
                    else:
                        self._framework_cache = 'python'
                except:
                    self._framework_cache = 'python'
            elif 'requirements.txt' in root_names:
                self._framework_cache = 'python'
            
            # Java frameworks
            elif 'pom.xml' in root_names:
                self._framework_cache = 'spring'
            elif 'build.gradle' in root_names:
                self._framework_cache = 'spring'
            
            # Go
            elif 'go.mod' in root_names:
                self._framework_cache = 'go'
            
            # Rust
            elif 'Cargo.toml' in root_names:
                self._framework_cache = 'rust'
            
            # Ruby
            elif 'Gemfile' in root_names:
                self._framework_cache = 'ruby'
            
            # PHP
            elif 'composer.json' in root_names:
                self._framework_cache = 'php'
            
            else:
                self._framework_cache = 'unknown'
            
            return self._framework_cache
            
        except Exception as e:
            log.warning(f"Framework detection failed: {e}")
            return "unknown"
    
    def analyze_error(self, error_text: str) -> ErrorContext:
        """
        Analyze an error and extract context.
        Works with any error format (Python traceback, JS error, etc.)
        """
        context = ErrorContext(
            error_type="Unknown",
            error_message=error_text.split('\n')[0][:200] if error_text else "",
            traceback_lines=error_text.split('\n') if error_text else [],
        )
        
        if not error_text:
            return context
        
        # Extract error type (usually last non-empty line or first line)
        lines = [l for l in error_text.split('\n') if l.strip()]
        if lines:
            # For Python tracebacks, error is usually last line
            last_line = lines[-1].strip()
            # Check for "ErrorType: message" pattern
            if ':' in last_line:
                parts = last_line.split(':', 1)
                context.error_type = parts[0].strip()
                context.error_message = parts[1].strip() if len(parts) > 1 else last_line
            else:
                context.error_type = last_line[:50]
        
        # Extract file path and line number
        # Python: File "path/to/file.py", line 42
        # JS: at file.js:42:10
        # Java: at com.example.Class.method(File.java:42)
        
        patterns = [
            r'File "([^"]+)", line (\d+)',  # Python
            r'at (.+?\.(py|js|ts|java|go|rs)):(\d+)',  # JS/Go
            r'at (.+?):(\d+)',  # Generic
            r'in (.+?\.(py|js|ts|java|go|rs)):(\d+)',  # Alternative
            r'File "([^"]+)", line (\d+)',  # Python alternative
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_text)
            if match:
                if len(match.groups()) >= 2:
                    context.file_path = match.group(1)
                    context.line_number = int(match.group(2)) if match.group(2).isdigit() else None
                    break
        
        # Get framework
        context.framework = self.detect_framework()
        
        # Get pattern hint
        if context.error_type in self.ERROR_PATTERNS:
            pattern = self.ERROR_PATTERNS[context.error_type]
            context.fix_suggestion = pattern.get('fix_hint', '')
            context.suggested_files = pattern.get('check_files', [])
        
        return context
    
    def extract_code_snippet(
        self, 
        file_path: str, 
        line_number: int, 
        context_lines: int = 10
    ) -> List[Tuple[int, str]]:
        """
        Extract code snippet around a line number.
        Returns list of (line_num, line_content) tuples.
        """
        try:
            if self.project_root:
                full_path = self.project_root / file_path
            else:
                full_path = Path(file_path)
            
            if not full_path.exists():
                return []
            
            lines = full_path.read_text(encoding='utf-8', errors='ignore').split('\n')
            
            start = max(0, line_number - context_lines - 1)
            end = min(len(lines), line_number + context_lines)
            
            result = []
            for i in range(start, end):
                result.append((i + 1, lines[i]))
            
            return result
            
        except Exception as e:
            log.warning(f"Failed to extract code snippet: {e}")
            return []
    
    def get_fix_suggestion(self, error_context: ErrorContext) -> str:
        """Generate a fix suggestion based on error type and framework."""
        suggestions = []
        
        # Framework-specific suggestions
        framework = error_context.framework
        
        if framework == 'django':
            suggestions.extend(self._django_fix_suggestions(error_context))
        elif framework == 'flask':
            suggestions.extend(self._flask_fix_suggestions(error_context))
        elif framework == 'fastapi':
            suggestions.extend(self._fastapi_fix_suggestions(error_context))
        elif framework in ('react', 'vue', 'express', 'nextjs', 'angular'):
            suggestions.extend(self._javascript_fix_suggestions(error_context))
        
        # Generic suggestions based on error type
        error_type = error_context.error_type
        if error_type in self.ERROR_PATTERNS:
            pattern = self.ERROR_PATTERNS[error_type]
            suggestions.append(f"💡 {pattern['fix_hint']}")
            if pattern['check_files']:
                suggestions.append(f"📁 Check these files: {', '.join(pattern['check_files'])}")
        
        # File-specific suggestion
        if error_context.file_path:
            suggestions.append(f"📍 Error location: {error_context.file_path}:{error_context.line_number}")
        
        return '\n'.join(suggestions) if suggestions else "No specific suggestion available."
    
    def _django_fix_suggestions(self, ctx: ErrorContext) -> List[str]:
        """Django-specific fix suggestions."""
        suggestions = []
        error_type = ctx.error_type
        
        if error_type == 'NoReverseMatch':
            suggestions.append("🔧 Django NoReverseMatch: URL name not found")
            suggestions.append("   1. Check urls.py for available URL names")
            suggestions.append("   2. Verify template {% url 'name' %} matches")
            suggestions.append("   3. Make sure app is in INSTALLED_APPS")
        
        elif error_type == 'TemplateDoesNotExist':
            suggestions.append("🔧 Django TemplateDoesNotExist")
            suggestions.append("   1. Check template exists in templates/ dir")
            suggestions.append("   2. Check DIRS in TEMPLATES setting")
            suggestions.append("   3. Verify app is in INSTALLED_APPS")
        
        elif error_type == 'ImportError':
            suggestions.append("🔧 Django ImportError")
            suggestions.append("   1. Check requirements.txt")
            suggestions.append("   2. Run: pip install -r requirements.txt")
            suggestions.append("   3. Check INSTALLED_APPS in settings.py")
        
        return suggestions
    
    def _flask_fix_suggestions(self, ctx: ErrorContext) -> List[str]:
        """Flask-specific fix suggestions."""
        suggestions = []
        error_type = ctx.error_type
        
        if 'BuildError' in error_type or 'url' in ctx.error_message.lower():
            suggestions.append("🔧 Flask URL Build Error")
            suggestions.append("   1. Check route decorators @app.route()")
            suggestions.append("   2. Verify url_for('route_name') matches")
        
        elif error_type == 'TemplateNotFound':
            suggestions.append("🔧 Flask Template Not Found")
            suggestions.append("   1. Check template file in templates/ folder")
            suggestions.append("   2. Verify render_template('file.html')")
        
        return suggestions
    
    def _fastapi_fix_suggestions(self, ctx: ErrorContext) -> List[str]:
        """FastAPI-specific fix suggestions."""
        suggestions = []
        error_type = ctx.error_type
        
        if 'validation' in ctx.error_message.lower() or 'pydantic' in ctx.error_message.lower():
            suggestions.append("🔧 FastAPI Validation Error")
            suggestions.append("   1. Check request body schema")
            suggestions.append("   2. Verify Pydantic model fields")
            suggestions.append("   3. Check required vs optional fields")
        
        return suggestions
    
    def _javascript_fix_suggestions(self, ctx: ErrorContext) -> List[str]:
        """JavaScript framework fix suggestions."""
        suggestions = []
        error_type = ctx.error_type
        error_msg = ctx.error_message.lower()
        
        if 'undefined' in error_msg or 'not defined' in error_msg:
            suggestions.append("🔧 JavaScript Undefined Error")
            suggestions.append("   1. Check variable/function declaration")
            suggestions.append("   2. Verify import statement")
            suggestions.append("   3. Check if module is installed (npm install)")
        
        elif 'cannot read' in error_msg and 'property' in error_msg:
            suggestions.append("🔧 JavaScript Property Access Error")
            suggestions.append("   1. Check if object is null/undefined")
            suggestions.append("   2. Add optional chaining (?.)")
            suggestions.append("   3. Add null check before access")
        
        elif 'module' in error_msg or 'import' in error_msg:
            suggestions.append("🔧 JavaScript Module Error")
            suggestions.append("   1. Run: npm install")
            suggestions.append("   2. Check import path")
            suggestions.append("   3. Verify package.json dependencies")
        
        return suggestions
    
    def find_related_files(self, error_context: ErrorContext) -> List[str]:
        """
        Find files potentially related to the error.
        Returns list of file paths to check.
        """
        related = []
        
        if not self.project_root:
            return related
        
        error_type = error_context.error_type
        framework = error_context.framework
        
        # Framework-specific files
        if framework == 'django':
            patterns = ['**/urls.py', '**/views.py', '**/models.py', '**/settings.py', '**/templates/**/*.html']
        elif framework == 'flask':
            patterns = ['**/app.py', '**/views.py', '**/routes.py', '**/templates/**/*.html']
        elif framework == 'fastapi':
            patterns = ['**/main.py', '**/routers/*.py', '**/models.py', '**/schemas.py']
        elif framework in ('react', 'vue', 'nextjs'):
            patterns = ['**/*.jsx', '**/*.tsx', '**/*.vue', '**/routes/**', '**/pages/**']
        else:
            patterns = ['**/*.py', '**/*.js', '**/*.ts']
        
        for pattern in patterns:
            try:
                for f in self.project_root.glob(pattern):
                    if 'node_modules' not in str(f) and 'venv' not in str(f):
                        related.append(str(f.relative_to(self.project_root)))
            except Exception:
                pass
        
        # Prioritize the error file
        if error_context.file_path:
            if error_context.file_path in related:
                related.remove(error_context.file_path)
            related.insert(0, error_context.file_path)
        
        return related[:20]  # Limit to 20 files