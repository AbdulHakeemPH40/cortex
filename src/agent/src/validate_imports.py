"""
Cortex IDE Import Validator
Scans all Python files for broken imports:
- Imported files/modules that don't exist locally
- Imported functions/classes not defined in target file
- Relative imports that can't be resolved
Skips stdlib and known third-party packages.
"""

import os
import ast
import sys
from pathlib import Path
from typing import List, Dict, Optional

SRC_DIR = Path(r"C:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\claude-code-main\claude-code-main\src")

# ---------------------------------------------------------------------------
# Stdlib + known third-party modules to skip
# ---------------------------------------------------------------------------
try:
    _STDLIB = sys.stdlib_module_names
except AttributeError:
    _STDLIB = set()

SKIP_MODULES = _STDLIB | {
    'abc','ast','asyncio','base64','builtins','collections','contextlib',
    'copy','dataclasses','datetime','decimal','enum','functools','gc',
    'glob','hashlib','heapq','hmac','html','http','importlib','inspect',
    'io','itertools','json','logging','math','mimetypes','multiprocessing',
    'operator','os','pathlib','pickle','platform','pprint','queue','random',
    're','shlex','shutil','signal','socket','sqlite3','ssl','stat','string',
    'struct','subprocess','sys','tempfile','textwrap','threading','time',
    'traceback','typing','unicodedata','unittest','urllib','uuid','warnings',
    'weakref','xml','zipfile','zlib',
    # third-party
    'typing_extensions','pydantic','aiohttp','aiofiles','anyio','attr','attrs',
    'click','cryptography','jwt','packaging','psutil','pygments','requests',
    'toml','yaml','PyQt6','PyQt5','PySide6','PySide2','setuptools','pkg_resources',
    'numpy','pandas','scipy','matplotlib','PIL','cv2','torch','tensorflow',
    'anthropic','openai','mistralai','google','azure','boto3','botocore',
    'lru_cache','functools','concurrent','contextlib',
}


def is_skip_module(module_name: str) -> bool:
    root = module_name.split('.')[0]
    return root in SKIP_MODULES


# ---------------------------------------------------------------------------
# Resolve module name -> file path
# ---------------------------------------------------------------------------

def module_to_path(module_name: str, from_file: Path) -> Optional[Path]:
    """Try to resolve an absolute import to a .py file inside SRC_DIR."""
    parts = module_name.split('.')

    # Try from SRC_DIR root
    candidate = SRC_DIR.joinpath(*parts)
    if candidate.with_suffix('.py').exists():
        return candidate.with_suffix('.py')
    if (candidate / '__init__.py').exists():
        return candidate / '__init__.py'

    # Try from the file's own directory (for bare-name imports like PermissionRule)
    base = from_file.parent
    rel = base.joinpath(*parts)
    if rel.with_suffix('.py').exists():
        return rel.with_suffix('.py')
    if (rel / '__init__.py').exists():
        return rel / '__init__.py'

    return None


def resolve_relative_import(level: int, module: str, from_file: Path) -> Optional[Path]:
    """Resolve a relative import (from . / from .. / from .x.y)."""
    base = from_file.parent
    for _ in range(level - 1):
        base = base.parent

    if module:
        parts = module.split('.')
        candidate = base.joinpath(*parts)
    else:
        candidate = base

    if candidate.with_suffix('.py').exists():
        return candidate.with_suffix('.py')
    if (candidate / '__init__.py').exists():
        return candidate / '__init__.py'

    return None


# ---------------------------------------------------------------------------
# Get all top-level defined names in a file
# ---------------------------------------------------------------------------

def get_defined_names(file_path: Path) -> List[str]:
    try:
        src = file_path.read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(src)
    except Exception:
        return []

    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.append(t.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.append(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            # Re-exported names count
            for alias in node.names:
                names.append(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.asname or alias.name.split('.')[0])
    return names


# ---------------------------------------------------------------------------
# Issue record
# ---------------------------------------------------------------------------

class Issue:
    def __init__(self, file: str, line: int, stmt: str, reason: str):
        self.file = file
        self.line = line
        self.stmt = stmt
        self.reason = reason

    def __str__(self):
        return f"  Line {self.line:4d}: {self.reason}\n           -> {self.stmt}"


# ---------------------------------------------------------------------------
# Scan a single file
# ---------------------------------------------------------------------------

def scan_file(py_file: Path) -> List[Issue]:
    issues = []
    try:
        src = py_file.read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(src, filename=str(py_file))
    except SyntaxError as e:
        return [Issue(str(py_file), 0, '', f'SyntaxError: {e}')]

    rel_path = str(py_file.relative_to(SRC_DIR))

    for node in ast.walk(tree):

        # ---- from X import Y, Z ----
        if isinstance(node, ast.ImportFrom):
            level = node.level or 0
            module = node.module or ''
            names = [alias.name for alias in node.names]
            line = node.lineno
            stmt = "from " + ('.' * level) + module + " import " + ', '.join(names)

            # Skip stdlib/third-party absolute imports
            if level == 0 and is_skip_module(module):
                continue

            # Resolve
            if level > 0:
                target = resolve_relative_import(level, module, py_file)
            else:
                target = module_to_path(module, py_file)

            if target is None:
                issues.append(Issue(rel_path, line, stmt,
                    '[MISSING MODULE] ' + ('.' * level) + module))
                continue

            # Check names exist (skip wildcard)
            if names == ['*']:
                continue

            defined = get_defined_names(target)
            for name in names:
                if name in ('__all__', '__version__', '__author__'):
                    continue
                if name not in defined:
                    try:
                        rel_target = str(target.relative_to(SRC_DIR))
                    except ValueError:
                        rel_target = str(target)
                    issues.append(Issue(rel_path, line, stmt,
                        "[MISSING NAME] '" + name + "' not found in " + rel_target))

        # ---- import X ----
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                line = node.lineno
                stmt = 'import ' + name

                if is_skip_module(name):
                    continue

                target = module_to_path(name, py_file)
                # Only report if the root name looks like a local package
                root = name.split('.')[0]
                local_roots = {p.stem for p in SRC_DIR.iterdir()}
                if root in local_roots and target is None:
                    issues.append(Issue(rel_path, line, stmt,
                        '[MISSING MODULE] ' + name))

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print('=' * 72)
    print('CORTEX IDE - IMPORT VALIDATOR')
    print('=' * 72)
    print('Scanning: ' + str(SRC_DIR))
    print()

    skip_dirs = {'__pycache__', '.qoder', 'node_modules', '.git'}
    py_files = sorted([
        f for f in SRC_DIR.rglob('*.py')
        if not any(part in skip_dirs for part in f.parts)
    ])

    print(f'Found {len(py_files)} Python files\n')

    all_issues: Dict[str, List[Issue]] = {}
    total = 0

    for py_file in py_files:
        found = scan_file(py_file)
        if found:
            key = str(py_file.relative_to(SRC_DIR))
            all_issues[key] = found
            total += len(found)

    if not all_issues:
        print('No broken imports found! All imports look valid.')
        return

    print(f'Found {total} issue(s) in {len(all_issues)} file(s):')
    print('=' * 72)

    for file_path, issues in sorted(all_issues.items()):
        print(f'\n[FILE] {file_path}')
        for issue in issues:
            print(str(issue))

    print('\n' + '=' * 72)
    print(f'TOTAL: {total} import issue(s) in {len(all_issues)} file(s)')
    print('=' * 72)

    # Write full report to file
    report_path = SRC_DIR / 'import_errors_report.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('CORTEX IDE - IMPORT VALIDATION REPORT\n')
        f.write(f'Total issues: {total} in {len(all_issues)} files\n\n')
        for file_path, issues in sorted(all_issues.items()):
            f.write(f'\n[FILE] {file_path}\n')
            for issue in issues:
                f.write(str(issue) + '\n')

    print(f'\nFull report saved to: import_errors_report.txt')


if __name__ == '__main__':
    main()
