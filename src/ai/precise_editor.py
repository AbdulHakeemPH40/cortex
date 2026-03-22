"""
precise_editor.py
─────────────────
Surgical file editing for Cortex IDE AI Agent.
Implements: search-replace, line-range, AST edit, diff apply, verification.
Based on PRECISE_FILE_EDITING_SYSTEM.md specification.
"""

import ast
import re
import json
import time
import shutil
import difflib
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass, field
from src.utils.logger import get_logger

log = get_logger("precise_editor")


# ─── DATA STRUCTURES ─────────────────────────────────────────────────────────

@dataclass
class EditResult:
    success: bool
    path: str = ""
    lines_before: int = 0
    lines_after: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    delta: int = 0
    diff_preview: str = ""
    error: str = ""
    action: str = ""    # recovery hint for the agent
    undo_available: bool = False


@dataclass
class UndoRecord:
    path: str
    original_content: str
    timestamp: float = field(default_factory=time.time)
    description: str = ""


# ─── UNDO STACK ──────────────────────────────────────────────────────────────

class UndoStack:
    def __init__(self, max_depth: int = 50):
        self._stack: List[UndoRecord] = []
        self._max = max_depth
    
    def push(self, path: str, original: str, description: str = ""):
        self._stack.append(UndoRecord(path, original, description=description))
        if len(self._stack) > self._max:
            self._stack.pop(0)
    
    def undo(self) -> Optional[str]:
        if not self._stack:
            return None
        record = self._stack.pop()
        Path(record.path).write_text(record.original_content, encoding="utf-8")
        log.info(f"Undid edit to {record.path}")
        return str(record.path)
    
    def undo_all(self) -> List[str]:
        restored = []
        while self._stack:
            path = self.undo()
            if path:
                restored.append(path)
        return restored
    
    def peek(self) -> Optional[UndoRecord]:
        return self._stack[-1] if self._stack else None
    
    @property
    def depth(self) -> int:
        return len(self._stack)


# ─── SYNTAX CHECKER ──────────────────────────────────────────────────────────

class SyntaxChecker:
    
    @staticmethod
    def check(file_path: str, content: str) -> Tuple[bool, str]:
        """Returns (is_valid, error_message)"""
        ext = Path(file_path).suffix.lower()
        
        if ext == ".py":
            return SyntaxChecker._check_python(content)
        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            return SyntaxChecker._check_js(content, file_path)
        else:
            return True, ""  # Unknown type — assume valid
    
    @staticmethod
    def _check_python(content: str) -> Tuple[bool, str]:
        try:
            ast.parse(content)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"
    
    @staticmethod
    def _check_js(content: str, file_path: str) -> Tuple[bool, str]:
        try:
            # Use node to check syntax if available
            result = subprocess.run(
                ["node", "--check"],
                input=content, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True, ""
            return False, str(result.stderr)[:200]
        except Exception:
            # node not available — skip check
            return True, ""


# ─── INDENTATION HANDLER ─────────────────────────────────────────────────────

class IndentationHandler:
    
    @staticmethod
    def detect(content: str) -> Tuple[str, int]:
        """Returns (char, size): ("\t", 1) or (" ", 4)"""
        for line in content.splitlines():
            stripped = line.lstrip()
            if stripped and len(line) > len(stripped):
                leading = line[:len(line) - len(stripped)]
                if "\t" in leading:
                    return "\t", 1
                spaces = len(leading)
                if spaces in (2, 4, 8):
                    return " ", spaces
        return " ", 4
    
    @staticmethod
    def get_line_indent(line: str) -> str:
        """Return the leading whitespace of a line"""
        return line[:len(line) - len(line.lstrip())]
    
    @staticmethod
    def normalize_block(code: str, target_indent: str) -> str:
        """
        Remove all leading indentation from a code block,
        then re-apply target_indent to each line.
        """
        lines = code.splitlines()
        if not lines:
            return code
        
        # Filter out empty lines for min_ws calculation
        non_empty_lines = [l for l in lines if l.strip()]
        if not non_empty_lines:
            return code
            
        min_ws = min(len(l) - len(l.lstrip()) for l in non_empty_lines)
        
        result = []
        for line in lines:
            if line.strip():
                result.append(target_indent + line[min_ws:].lstrip())
            else:
                result.append("")
        
        return "\n".join(result)


# ─── PRECISE EDITOR ──────────────────────────────────────────────────────────

class PreciseEditor:
    """
    The core editing engine for Cortex IDE.
    All AI-driven file edits go through this class.
    """
    
    def __init__(self, project_root: str):
        self.root = Path(project_root)
        self.undo_stack = UndoStack()
        self._syntax = SyntaxChecker()
        self._indent = IndentationHandler()
    
    def _calculate_counts(self, old_text: str, new_text: str) -> Tuple[int, int]:
        """Calculate lines added and removed using ndiff logic."""
        added = 0
        removed = 0
        
        # Split into lines for diffing
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        
        diff = list(difflib.ndiff(old_lines, new_lines))
        for line in diff:
            if line.startswith('+ '):
                added += 1
            elif line.startswith('- '):
                removed += 1
        
        return added, removed
    
    # ── PRIMARY EDIT METHOD ──────────────────────────────────────────────────
    
    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_count: int = 1
    ) -> EditResult:
        """
        The main edit method. Surgical search-and-replace.
        
        path:           file to edit
        old_string:     exact content to replace (must be unique)
        new_string:     replacement content
        expected_count: how many occurrences to expect (default: 1)
        """
        full_path = self._resolve(path)
        
        # Read current content
        try:
            content = full_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Try to find similar files to suggest
            suggestions = self._find_similar_files(path)
            error_msg = f"File not found: {path}"
            error_msg += f"\n\nProject root: {self.root}"
            error_msg += f"\nResolved path: {full_path}"
            if suggestions:
                error_msg += f"\n\nSimilar files in project:"
                for s in suggestions[:5]:
                    error_msg += f"\n  • {s}"
            else:
                error_msg += f"\n\nNo similar files found."
            error_msg += f"\n\nIMPORTANT: Use list_directory('.') to see project structure first."
            action = "Use list_directory('.') to explore the project structure, then use the correct relative path."
            return EditResult(False, path=path, error=error_msg, action=action)
        except Exception as e:
            return EditResult(False, path=path, error=str(e))
        
        lines_before = content.count("\n") + 1
        
        # Validate old_string
        count = content.count(old_string)
        
        if count == 0:
            return EditResult(
                False, path=path,
                error="old_string not found in file",
                action="Re-read the file with read_file() and copy old_string exactly from the output"
            )
        
        if count != expected_count:
            msg = f"old_string found {count} times, expected {expected_count} in '{path}'"
            if count > 1:
                # Find line numbers for matches
                matches = list(re.finditer(re.escape(old_string), content))
                line_numbers = [content.count("\n", 0, m.start()) + 1 for m in matches]
                msg += f". Matches found at lines: {', '.join(map(str, line_numbers))}."
                action = f"The string appears multiple times. Add more surrounding lines of code to 'old_string' to make it unique. Occurrences are at lines {', '.join(map(str, line_numbers))}."
            else:
                action = "The 'old_string' doesn't exist. Check for typos or indentation mismatches."
            
            return EditResult(
                False, path=path,
                error=msg,
                action=action
            )
        
        # Apply replacement
        new_content = content.replace(old_string, new_string, expected_count)
        
        # Sanity: not empty
        if content.strip() and not new_content.strip():
            return EditResult(
                False, path=path,
                error="Replacement produced empty file — likely wrong replacement"
            )
        
        # Syntax check
        ok, err = self._syntax.check(path, new_content)
        if not ok:
            return EditResult(
                False, path=path,
                error=f"new_string introduces syntax error: {err}",
                action="Fix the syntax error in new_string. Check indentation and brackets."
            )
        
        # Commit
        self.undo_stack.push(str(full_path), content, f"edit {path}")
        full_path.write_text(new_content, encoding="utf-8")
        
        lines_after = new_content.count("\n") + 1
        diff = self._generate_diff(old_string, new_string, path)
        added, removed = self._calculate_counts(old_string, new_string)
        
        log.info(f"Edit applied to {path}: {lines_before}→{lines_after} lines (+{added}, -{removed})")
        
        return EditResult(
            success=True,
            path=path,
            lines_before=lines_before,
            lines_after=lines_after,
            lines_added=added,
            lines_removed=removed,
            delta=lines_after - lines_before,
            diff_preview=diff,
            undo_available=True
        )
    
    # ── LINE-RANGE REPLACEMENT ───────────────────────────────────────────────
    
    def replace_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str
    ) -> EditResult:
        """Replace a range of lines (1-based, inclusive)."""
        full_path = self._resolve(path)
        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        
        if not (1 <= start_line <= end_line <= len(lines)):
            return EditResult(
                False, path=path,
                error=f"Line range {start_line}-{end_line} invalid for {len(lines)}-line file"
            )
        
        new_lines = new_content.splitlines(keepends=True)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        
        result_lines = lines[:start_line-1] + new_lines + lines[end_line:]
        result = "".join(result_lines)
        
        old_range_lines = lines[start_line-1:end_line]
        old_range_content = "".join(old_range_lines)
        added, removed = self._calculate_counts(old_range_content, new_content)
        
        self.undo_stack.push(str(full_path), content)
        full_path.write_text(result, encoding="utf-8")
        
        lines_before = len(lines)
        lines_after = len(result_lines)
        
        return EditResult(
            success=True, 
            path=path, 
            lines_before=lines_before,
            lines_after=lines_after,
            lines_added=added,
            lines_removed=removed,
            delta=lines_after - lines_before,
            undo_available=True
        )
    
    # ── INJECT AFTER ANCHOR ──────────────────────────────────────────────────
    
    def inject_after(
        self,
        path: str,
        anchor: str,
        new_code: str,
        preserve_indent: bool = True
    ) -> EditResult:
        """Insert new_code immediately after the line containing anchor."""
        full_path = self._resolve(path)
        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        
        # Find anchor (unique)
        matches = [i for i, line in enumerate(lines) if anchor in line]
        if len(matches) == 0:
            return EditResult(False, path=path, error="anchor not found",
                             action="Use a more specific anchor string")
        if len(matches) > 1:
            return EditResult(False, path=path, error=f"anchor found {len(matches)} times",
                             action="Use a more specific anchor string")
        
        anchor_idx = matches[0]
        
        # Determine indent
        if preserve_indent:
            base_indent = self._indent.get_line_indent(lines[anchor_idx])
        else:
            base_indent = ""
        
        new_lines = []
        for code_line in new_code.splitlines():
            if code_line.strip():
                new_lines.append(base_indent + code_line.lstrip() + "\n")
            else:
                new_lines.append("\n")
        
        result_lines = lines[:anchor_idx+1] + new_lines + lines[anchor_idx+1:]
        result = "".join(result_lines)
        
        ok, err = self._syntax.check(path, result)
        if not ok:
            return EditResult(False, path=path, error=f"Syntax error: {err}")
        
        self.undo_stack.push(str(full_path), content)
        full_path.write_text(result, encoding="utf-8")
        
        lines_before = len(lines)
        lines_after = result.count("\n") + 1
        added, removed = self._calculate_counts("", "".join(new_lines))
        
        return EditResult(
            success=True,
            path=path,
            lines_before=lines_before,
            lines_after=lines_after,
            lines_added=added,
            lines_removed=removed,
            delta=lines_after - lines_before,
            undo_available=True
        )
    
    # ── ADD IMPORT ───────────────────────────────────────────────────────────
    
    def add_import(self, path: str, import_statement: str) -> EditResult:
        """Add import to file if not already present."""
        full_path = self._resolve(path)
        content = full_path.read_text(encoding="utf-8")
        
        if import_statement in content:
            return EditResult(success=True, path=path, error="",
                             diff_preview="Import already present — no change made")
        
        lines = content.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_at = i + 1
        
        lines.insert(insert_at, import_statement + "\n")
        new_content = "".join(lines)
        
        ok, err = self._syntax.check(path, new_content)
        if not ok:
            return EditResult(False, path=path, error=str(err))
        
        self.undo_stack.push(str(full_path), content)
        full_path.write_text(new_content, encoding="utf-8")
        
        added, removed = self._calculate_counts("", import_statement + "\n")
        
        return EditResult(
            success=True, 
            path=path,
            lines_before=len(lines) - 1,
            lines_after=len(lines),
            lines_added=added,
            lines_removed=removed,
            delta=1,
            undo_available=True
        )
    
    # ── WRITE NEW FILE ───────────────────────────────────────────────────────
    
    def write(self, path: str, content: str) -> EditResult:
        """Create or overwrite a file with full content."""
        full_path = self._resolve(path)
        
        # Overwrite safety
        if full_path.exists():
            original = full_path.read_text(encoding="utf-8")
            if len(content) < len(original) * 0.4 and len(original) > 300:
                return EditResult(
                    False, path=path,
                    error=f"New content is only {len(content)} chars vs original {len(original)} chars. Looks like truncation.",
                    action="Use edit_file for partial changes. Only use write_file for complete rewrites."
                )
            self.undo_stack.push(str(full_path), original)
        
        ok, err = self._syntax.check(path, content)
        if not ok:
            return EditResult(False, path=path, error=f"Content has syntax error: {err}")
        
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        
        lines_after = content.count("\n") + 1
        
        return EditResult(
            success=True, 
            path=path, 
            lines_before=0, # Assume 0 if new/overwrite
            lines_after=lines_after,
            lines_added=lines_after,
            lines_removed=0,
            delta=lines_after
        )
    
    # ── UNDO ─────────────────────────────────────────────────────────────────
    
    def undo(self) -> Optional[str]:
        path = self.undo_stack.undo()
        return path
    
    def undo_all_session(self) -> List[str]:
        return self.undo_stack.undo_all()
    
    # ── VERIFY ───────────────────────────────────────────────────────────────
    
    def verify_edit(self, path: str, must_contain: str = None, 
                    must_not_contain: str = None) -> dict:
        """Post-edit verification. Call after edit() to confirm correctness."""
        content = self._resolve(path).read_text(encoding="utf-8")
        
        if must_contain and must_contain not in content:
            self.undo()
            return {
                "verified": False,
                "error": f"Expected content not found after edit. Edit rolled back.",
                "must_contain": must_contain
            }
        
        if must_not_contain and must_not_contain in content:
            self.undo()
            return {
                "verified": False,
                "error": f"Unexpected content still present after edit. Edit rolled back.",
                "must_not_contain": must_not_contain
            }
        
        ok, err = self._syntax.check(path, content)
        if not ok:
            self.undo()
            return {"verified": False, "error": f"Syntax error after edit: {err}. Rolled back."}
        
        return {"verified": True, "lines": content.count("\n") + 1}
    
    # ── HELPERS ──────────────────────────────────────────────────────────────
    
    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        return p
    
    def _find_similar_files(self, path: str) -> list:
        """Find files with similar names in the project to suggest correct paths."""
        try:
            if not self.root or not self.root.exists():
                return []
            
            filename = Path(path).name.lower()
            basename = Path(path).stem.lower()  # filename without extension
            
            # Extensions to search (source code files)
            search_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', 
                                '.json', '.md', '.txt', '.vue', '.svelte', '.go', '.rs',
                                '.java', '.kt', '.swift', '.c', '.cpp', '.h', '.hpp'}
            
            similar = []
            seen = set()
            
            for file_path in self.root.rglob('*'):
                # Skip directories
                if file_path.is_dir():
                    continue
                
                # Only search source code files
                if file_path.suffix.lower() not in search_extensions:
                    continue
                
                rel_path = str(file_path.relative_to(self.root))
                file_name = file_path.name.lower()
                file_stem = file_path.stem.lower()
                
                # Exact filename match
                if file_name == filename and rel_path not in seen:
                    similar.append(rel_path)
                    seen.add(rel_path)
                # Similar name (basename match)
                elif basename and file_stem and basename in file_stem and rel_path not in seen:
                    similar.append(rel_path)
                    seen.add(rel_path)
                # Partial match on filename
                elif filename and file_name and (filename in file_name or file_name in filename) and rel_path not in seen:
                    similar.append(rel_path)
                    seen.add(rel_path)
                
                if len(similar) >= 10:
                    break
            
            return similar
        except Exception as e:
            log.warning(f"Error finding similar files: {e}")
            return []
    
    def _generate_diff(self, old: str, new: str, path: str) -> str:
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm=""
        )
        result = "".join(diff)
        return result[:2000]  # Cap for LLM context


# ─── TOOL REGISTRY INTEGRATION ───────────────────────────────────────────────
# Wire these as tools that the AI agent can call.

_editor: Optional[PreciseEditor] = None

def get_editor(project_root: str = None) -> PreciseEditor:
    global _editor
    if _editor is None or (project_root and str(_editor.root) != project_root):
        _editor = PreciseEditor(project_root or ".")
    return _editor


# These are the functions you register as agent tools:

def tool_edit_file(path: str, old_string: str, new_string: str) -> str:
    result = get_editor().edit(path, old_string, new_string)
    return json.dumps({
        "success": result.success,
        "error": result.error or None,
        "action": result.action or None,
        "delta_lines": result.delta,
        "added_lines": result.lines_added,
        "removed_lines": result.lines_removed,
        "diff": result.diff_preview[:500] if result.diff_preview else None
    })

def tool_write_file(path: str, content: str) -> str:
    result = get_editor().write(path, content)
    return json.dumps({
        "success": result.success,
        "error": result.error or None,
        "lines": result.lines_after
    })

def tool_inject_after(path: str, anchor: str, new_code: str) -> str:
    result = get_editor().inject_after(path, anchor, new_code)
    return json.dumps({
        "success": result.success, 
        "error": result.error or None,
        "added_lines": result.lines_added,
        "removed_lines": result.lines_removed
    })

def tool_add_import(path: str, import_statement: str) -> str:
    result = get_editor().add_import(path, import_statement)
    return json.dumps({
        "success": result.success, 
        "note": result.diff_preview or None,
        "added_lines": result.lines_added,
        "removed_lines": result.lines_removed
    })

def tool_undo_last_edit() -> str:
    path = get_editor().undo()
    return json.dumps({"restored": path})
