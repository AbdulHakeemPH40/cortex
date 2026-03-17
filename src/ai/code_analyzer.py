"""
Code Analyzer — static helpers for code-related AI actions.
"""

import re
from pathlib import Path


class CodeAnalyzer:
    @staticmethod
    def extract_functions(code: str, language: str = "python") -> list[str]:
        """Extract function/method names from code."""
        patterns = {
            "python": r"^\s*def\s+(\w+)\s*\(",
            "javascript": r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\()",
            "typescript": r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\()",
        }
        pat = patterns.get(language, patterns["python"])
        matches = []
        for m in re.finditer(pat, code, re.MULTILINE):
            name = next((g for g in m.groups() if g), None)
            if name:
                matches.append(name)
        return matches

    @staticmethod
    def extract_classes(code: str) -> list[str]:
        return re.findall(r"^\s*class\s+(\w+)", code, re.MULTILINE)

    @staticmethod
    def count_lines(code: str) -> dict:
        lines = code.splitlines()
        blank = sum(1 for l in lines if not l.strip())
        comment = sum(1 for l in lines if l.strip().startswith(("#", "//", "/*", "*")))
        return {
            "total": len(lines),
            "code": len(lines) - blank - comment,
            "blank": blank,
            "comment": comment,
        }

    @staticmethod
    def get_selected_context(code: str, start_line: int, end_line: int) -> str:
        lines = code.splitlines()
        return "\n".join(lines[start_line:end_line])

    @staticmethod
    def build_explain_prompt(code: str, language: str) -> str:
        return (
            f"Please explain the following {language} code clearly and concisely. "
            f"Describe what it does, how it works, and note any important details:\n\n"
            f"```{language}\n{code}\n```"
        )

    @staticmethod
    def build_refactor_prompt(code: str, language: str) -> str:
        return (
            f"Refactor the following {language} code to improve readability, "
            f"performance, and best practices. Show the refactored version with a brief explanation:\n\n"
            f"```{language}\n{code}\n```"
        )

    @staticmethod
    def build_test_prompt(code: str, language: str) -> str:
        return (
            f"Write comprehensive unit tests for the following {language} code. "
            f"Use the standard testing framework for {language}:\n\n"
            f"```{language}\n{code}\n```"
        )

    @staticmethod
    def build_debug_prompt(code: str, error: str, language: str) -> str:
        return (
            f"Debug the following {language} code. The error is:\n`{error}`\n\n"
            f"```{language}\n{code}\n```\n\n"
            f"Identify the bug and provide a corrected version."
        )
