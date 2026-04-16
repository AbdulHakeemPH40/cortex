"""Code formatter for multiple languages.

Supports formatting for:
- Python (using black or autopep8)
- JavaScript/TypeScript (using jsbeautifier)
- JSON (using json module)
- HTML (using jsbeautifier)
- CSS (using jsbeautifier)
"""

import json
import subprocess
import sys
from typing import Optional, Dict, Callable
from dataclasses import dataclass


@dataclass
class FormatResult:
    """Result of formatting operation."""
    success: bool
    formatted_code: str
    error_message: str = ""


class CodeFormatter:
    """Multi-language code formatter."""
    
    def __init__(self):
        self.formatters: Dict[str, Callable[[str], FormatResult]] = {
            "python": self._format_python,
            "javascript": self._format_javascript,
            "typescript": self._format_typescript,
            "json": self._format_json,
            "html": self._format_html,
            "css": self._format_css,
            "scss": self._format_css,
            "less": self._format_css,
        }
    
    def format_code(self, code: str, language: str) -> FormatResult:
        """Format code for the given language."""
        formatter = self.formatters.get(language.lower())
        if not formatter:
            return FormatResult(
                success=False,
                formatted_code=code,
                error_message=f"No formatter available for {language}"
            )
        
        try:
            return formatter(code)
        except Exception as e:
            return FormatResult(
                success=False,
                formatted_code=code,
                error_message=str(e)
            )
    
    def _format_python(self, code: str) -> FormatResult:
        """Format Python code using black or autopep8."""
        # Try black first
        try:
            result = subprocess.run(
                [sys.executable, "-m", "black", "-", "--quiet"],
                input=code,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=10
            )
            if result.returncode == 0:
                return FormatResult(success=True, formatted_code=result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Fallback to autopep8
        try:
            result = subprocess.run(
                [sys.executable, "-m", "autopep8", "-", "--max-line-length", "100"],
                input=code,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=10
            )
            if result.returncode == 0:
                return FormatResult(success=True, formatted_code=result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Final fallback: return unchanged
        return FormatResult(success=True, formatted_code=code)
    
    def _format_javascript(self, code: str) -> FormatResult:
        """Format JavaScript using jsbeautifier (Python-based)."""
        try:
            import jsbeautifier
            opts = jsbeautifier.default_options()
            opts.indent_size = 2
            opts.indent_char = ' '
            opts.preserve_newlines = True
            opts.max_preserve_newlines = 2
            formatted = jsbeautifier.beautify(code, opts)
            return FormatResult(success=True, formatted_code=formatted)
        except ImportError:
            return FormatResult(success=True, formatted_code=code, error_message="jsbeautifier not installed")
        except Exception as e:
            return FormatResult(success=False, formatted_code=code, error_message=str(e))
    
    def _format_typescript(self, code: str) -> FormatResult:
        """Format TypeScript using jsbeautifier (Python-based)."""
        # jsbeautifier works well with TypeScript too
        return self._format_javascript(code)
    
    def _format_css(self, code: str) -> FormatResult:
        """Format CSS using basic indentation."""
        # CSS formatting - just fix basic indentation
        try:
            lines = code.split('\n')
            result = []
            indent = 0
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    result.append('')
                    continue
                # Decrease indent for closing brace
                if stripped.startswith('}'):
                    indent = max(0, indent - 1)
                result.append('  ' * indent + stripped)
                # Increase indent after opening brace
                if stripped.endswith('{'):
                    indent += 1
            return FormatResult(success=True, formatted_code='\n'.join(result))
        except Exception as e:
            return FormatResult(success=False, formatted_code=code, error_message=str(e))
    
    def _format_json(self, code: str) -> FormatResult:
        """Format JSON using Python's json module."""
        try:
            parsed = json.loads(code)
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=False)
            return FormatResult(success=True, formatted_code=formatted)
        except json.JSONDecodeError as e:
            return FormatResult(
                success=False,
                formatted_code=code,
                error_message=f"Invalid JSON: {e}"
            )
    
    def _format_html(self, code: str) -> FormatResult:
        """Format HTML using BeautifulSoup's prettify."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(code, 'html.parser')
            formatted = soup.prettify()
            return FormatResult(success=True, formatted_code=formatted)
        except ImportError:
            return FormatResult(success=True, formatted_code=code, error_message="beautifulsoup4 not installed")
        except Exception as e:
            return FormatResult(success=False, formatted_code=code, error_message=str(e))


# Singleton instance
_formatter: Optional[CodeFormatter] = None


def get_code_formatter() -> CodeFormatter:
    """Get the singleton code formatter."""
    global _formatter
    if _formatter is None:
        _formatter = CodeFormatter()
    return _formatter


def format_code(code: str, language: str) -> FormatResult:
    """Convenience function to format code."""
    return get_code_formatter().format_code(code, language)
