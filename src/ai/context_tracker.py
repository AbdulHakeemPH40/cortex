"""
Cross-File Context Awareness System
Tracks dependencies, imports, and relationships across entire codebase.
Enables AI to understand project structure and make informed changes.
"""

from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field
import ast
import os
import re
import logging
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class FileNode:
    """Represents a file in the codebase."""
    path: str
    language: str
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    symbols: Dict[str, str] = field(default_factory=dict)  # name -> type
    last_modified: float = 0.0
    size_bytes: int = 0


@dataclass
class DependencyGraph:
    """Complete dependency graph for the project."""
    files: Dict[str, FileNode] = field(default_factory=dict)
    import_map: Dict[str, Set[str]] = field(default_factory=dict)  # module -> importers
    circular_deps: List[List[str]] = field(default_factory=list)


class CrossFileContextTracker:
    """
    Maintains awareness of cross-file relationships and dependencies.
    
    Capabilities:
    - Track imports/exports across files
    - Build dependency graphs
    - Detect circular dependencies
    - Find all usages of a symbol
    - Suggest refactoring impacts
    """
    
    def __init__(self, root_path: str):
        self.root_path = root_path
        self.graph = DependencyGraph()
        self.supported_extensions = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript"
        }
    
    def index_project(self) -> DependencyGraph:
        """Index entire project and build dependency graph."""
        log.info(f"🔍 Indexing project at: {self.root_path}")
        
        self.graph = DependencyGraph()
        files_indexed = 0
        
        # Walk through project directory
        for root, dirs, files in os.walk(self.root_path):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in 
                      ['node_modules', '__pycache__', '.git', 'venv', 'env', 'dist', 'build']]
            
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext in self.supported_extensions:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.root_path)
                    
                    self._index_file(rel_path, self.supported_extensions[ext])
                    files_indexed += 1
        
        # Build dependency relationships
        self._build_dependency_relationships()
        
        # Detect circular dependencies
        self._detect_circular_dependencies()
        
        log.info(f"   ✅ Indexed {files_indexed} files, found {len(self.graph.files)} modules")
        
        return self.graph
    
    def _index_file(self, file_path: str, language: str) -> None:
        """Parse and index a single file."""
        try:
            full_path = os.path.join(self.root_path, file_path)
            
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Create file node
            node = FileNode(
                path=file_path,
                language=language,
                size_bytes=len(content),
                last_modified=os.path.getmtime(full_path)
            )
            
            # Extract imports and symbols based on language
            if language == "python":
                self._extract_python_info(node, content)
            elif language in ["javascript", "typescript"]:
                self._extract_js_ts_info(node, content)
            
            self.graph.files[file_path] = node
            
        except Exception as e:
            log.error(f"Failed to index {file_path}: {e}")
    
    def _extract_python_info(self, node: FileNode, content: str) -> None:
        """Extract Python imports and definitions."""
        try:
            tree = ast.parse(content)
            
            for stmt in ast.walk(tree):
                # Import statements
                if isinstance(stmt, ast.Import):
                    for alias in stmt.names:
                        node.imports.append(alias.name)
                
                elif isinstance(stmt, ast.ImportFrom):
                    if stmt.module:
                        node.imports.append(stmt.module)
                        for alias in stmt.names:
                            node.exports.append(alias.name)
                
                # Class definitions
                elif isinstance(stmt, ast.ClassDef):
                    node.symbols[stmt.name] = "class"
                    node.exports.append(stmt.name)
                    
                    # Extract methods
                    for item in stmt.body:
                        if isinstance(item, ast.FunctionDef):
                            node.symbols[f"{stmt.name}.{item.name}"] = "method"
                
                # Function definitions
                elif isinstance(stmt, ast.FunctionDef):
                    node.symbols[stmt.name] = "function"
                    node.exports.append(stmt.name)
                
                # Variable assignments (module level)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            node.symbols[target.id] = "variable"
        
        except SyntaxError as e:
            log.warning(f"Python syntax error in {node.path}: {e}")
    
    def _extract_js_ts_info(self, node: FileNode, content: str) -> None:
        """Extract JavaScript/TypeScript imports and exports."""
        # Import patterns
        import_patterns = [
            r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]',  # import X from 'module'
            r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',     # require('module')
            r'import\s+[\'"]([^\'"]+)[\'"]'                 # import 'module'
        ]
        
        for pattern in import_patterns:
            matches = re.findall(pattern, content)
            node.imports.extend(matches)
        
        # Export patterns
        export_patterns = [
            r'export\s+(?:default\s+)?(?:class|function|const|let|var)\s+(\w+)',
            r'export\s+\{([^}]+)\}'
        ]
        
        for pattern in export_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if ',' in match:
                    # Multiple exports
                    exports = [x.strip() for x in match.split(',')]
                    node.exports.extend(exports)
                else:
                    node.exports.append(match.strip())
        
        # Extract classes and functions
        class_matches = re.finditer(r'class\s+(\w+)', content)
        for match in class_matches:
            node.symbols[match.group(1)] = "class"
        
        func_matches = re.finditer(r'(?:async\s+)?function\s+(\w+)', content)
        for match in func_matches:
            node.symbols[match.group(1)] = "function"
    
    def _build_dependency_relationships(self) -> None:
        """Build import/export relationships between files."""
        # Create reverse index: module -> files that import it
        import_index: Dict[str, Set[str]] = {}
        
        for file_path, node in self.graph.files.items():
            for imp in node.imports:
                # Normalize import path
                normalized = self._normalize_import_path(imp)
                
                if normalized not in import_index:
                    import_index[normalized] = set()
                import_index[normalized].add(file_path)
                
                # Add as dependency if we have that file
                if normalized in self.graph.files:
                    node.dependencies.append(normalized)
                    self.graph.files[normalized].dependents.append(file_path)
        
        self.graph.import_map = import_index
    
    def _normalize_import_path(self, import_path: str) -> str:
        """Normalize import path to match file paths."""
        # Convert module notation to path
        path = import_path.replace('.', os.sep)
        
        # Try different extensions
        possible_paths = [
            path + ".py",
            path + ".js",
            path + ".ts",
            os.path.join(path, "__init__.py"),
            os.path.join(path, "index.js"),
            os.path.join(path, "index.ts")
        ]
        
        # Check which one exists
        for candidate in possible_paths:
            if candidate in self.graph.files:
                return candidate
        
        # Return original if no match
        return import_path
    
    def _detect_circular_dependencies(self) -> None:
        """Detect circular dependencies using DFS."""
        visited = set()
        rec_stack = set()
        cycles = []
        
        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            
            file_node = self.graph.files.get(node)
            if file_node:
                for dep in file_node.dependencies:
                    if dep not in visited:
                        dfs(dep, path + [dep])
                    elif dep in rec_stack:
                        # Found cycle
                        cycle_start = path.index(dep) if dep in path else 0
                        cycle = path[cycle_start:] + [dep]
                        cycles.append(cycle)
            
            rec_stack.remove(node)
        
        for file_path in self.graph.files.keys():
            if file_path not in visited:
                dfs(file_path, [file_path])
        
        self.graph.circular_deps = cycles
        
        if cycles:
            log.warning(f"   ⚠️ Detected {len(cycles)} circular dependencies")
    
    def find_symbol_usages(self, symbol_name: str, file_path: Optional[str] = None) -> List[str]:
        """
        Find all files that use a specific symbol.
        
        Args:
            symbol_name: Name of symbol to search for
            file_path: Optional - limit search to this file's dependents
        
        Returns:
            List of file paths that reference the symbol
        """
        usages = []
        
        # If file_path provided, check its dependents
        if file_path and file_path in self.graph.files:
            candidates = self.graph.files[file_path].dependents
        else:
            candidates = list(self.graph.files.keys())
        
        for candidate in candidates:
            node = self.graph.files[candidate]
            if symbol_name in node.imports or symbol_name in node.symbols:
                usages.append(candidate)
        
        log.info(f"   🔍 Found {len(usages)} usages of '{symbol_name}'")
        
        return usages
    
    def get_impact_analysis(self, changed_files: List[str]) -> Dict[str, Any]:
        """
        Analyze impact of file changes.
        
        Args:
            changed_files: List of modified file paths
        
        Returns:
            Impact analysis report
        """
        impacted_files = set()
        
        # Find all files that depend on changed files
        for file_path in changed_files:
            if file_path in self.graph.files:
                node = self.graph.files[file_path]
                impacted_files.update(node.dependents)
        
        # Remove changed files themselves
        impacted_files -= set(changed_files)
        
        report = {
            "changed_files": changed_files,
            "impacted_files": list(impacted_files),
            "impact_count": len(impacted_files),
            "risk_level": self._calculate_risk_level(changed_files, impacted_files),
            "requires_testing": list(impacted_files)
        }
        
        log.info(f"   📊 Impact analysis: {len(changed_files)} changes → {len(impacted_files)} impacted")
        
        return report
    
    def _calculate_risk_level(self, changed: List[str], impacted: Set[str]) -> str:
        """Calculate risk level based on impact."""
        if len(impacted) > 20:
            return "HIGH"
        elif len(impacted) > 5:
            return "MEDIUM"
        else:
            return "LOW"
    
    def suggest_refactoring(self, file_path: str) -> List[str]:
        """
        Suggest refactoring opportunities for a file.
        
        Args:
            file_path: File to analyze
        
        Returns:
            List of refactoring suggestions
        """
        suggestions = []
        
        if file_path not in self.graph.files:
            return suggestions
        
        node = self.graph.files[file_path]
        
        # Check for too many dependencies
        if len(node.dependencies) > 10:
            suggestions.append(
                f"⚠️ High coupling: {len(node.dependencies)} dependencies. Consider reducing."
            )
        
        # Check for too many dependents (god class/file)
        if len(node.dependents) > 15:
            suggestions.append(
                f"⚠️ Central dependency: {len(node.dependents)} files depend on this. Consider splitting."
            )
        
        # Check file size
        if node.size_bytes > 10000:  # > 10KB
            suggestions.append(
                f"⚠️ Large file ({node.size_bytes} bytes). Consider breaking into smaller modules."
            )
        
        # Check for circular dependencies
        for cycle in self.graph.circular_deps:
            if file_path in cycle:
                suggestions.append(
                    f"🔴 Circular dependency detected: {' → '.join(cycle)}"
                )
        
        return suggestions
    
    def get_context_for_file(self, file_path: str) -> Dict[str, Any]:
        """
        Get complete context for editing a file.
        
        Returns:
            Dictionary with all relevant context:
            - imports needed
            - dependent files
            - related symbols
            - recent changes
        """
        if file_path not in self.graph.files:
            return {"error": "File not indexed"}
        
        node = self.graph.files[file_path]
        
        return {
            "path": file_path,
            "language": node.language,
            "imports": node.imports,
            "exports": node.exports,
            "dependencies": node.dependencies,
            "dependents": node.dependents,
            "symbols": node.symbols,
            "size": node.size_bytes,
            "last_modified": node.last_modified
        }


def create_context_tracker(project_root: str) -> CrossFileContextTracker:
    """Create and initialize a context tracker for a project."""
    tracker = CrossFileContextTracker(project_root)
    tracker.index_project()
    return tracker
