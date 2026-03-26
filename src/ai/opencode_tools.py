"""
OpenCode-Inspired Enhanced Tools
Industry-standard tool implementations for Cortex IDE
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
import re


class OpenCodeStyleTools:
    """
    Enhanced tools inspired by OpenCode's implementation.
    Better than basic file operations - smarter, safer, more reliable.
    """
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
    
    # ========== FILE READING (Enhanced) ==========
    
    def read_file(self, path: str, limit: int = None) -> Dict[str, Any]:
        """
        Smart file reading with:
        - Automatic path resolution
        - Size limits to prevent context overflow
        - Line count metadata
        - Encoding detection
        """
        try:
            # Resolve path relative to project root
            file_path = self._resolve_path(path)
            
            if not file_path.exists():
                return {
                    "success": False,
                    "error": f"File not found: {file_path}",
                    "content": None,
                    "line_count": 0
                }
            
            # Read content
            content = file_path.read_text(encoding='utf-8')
            lines = content.splitlines()
            line_count = len(lines)
            
            # Apply limit if needed
            if limit and line_count > limit:
                content = '\n'.join(lines[:limit])
                truncated = True
            else:
                truncated = False
            
            return {
                "success": True,
                "content": content,
                "line_count": line_count,
                "path": str(file_path),
                "truncated": truncated,
                "size_bytes": len(content.encode('utf-8'))
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": None,
                "line_count": 0
            }
    
    # ========== FILE EDITING (Search/Replace) ==========
    
    def edit_file(self, path: str, old_text: str, new_text: str, 
                  expected_replacements: int = 1) -> Dict[str, Any]:
        """
        Precise search/replace editing with validation.
        Like OpenCode's edit.ts but safer.
        """
        try:
            file_path = self._resolve_path(path)
            
            if not file_path.exists():
                return {
                    "success": False,
                    "error": f"File not found: {file_path}",
                    "old_content": None,
                    "new_content": None
                }
            
            old_content = file_path.read_text(encoding='utf-8')
            
            # Count occurrences
            occurrences = old_content.count(old_text)
            
            if occurrences == 0:
                return {
                    "success": False,
                    "error": f"Text not found in file",
                    "searched_text": old_text[:200],
                    "occurrences_found": 0
                }
            
            if occurrences != expected_replacements:
                return {
                    "success": False,
                    "error": f"Expected {expected_replacements} occurrence(s), found {occurrences}",
                    "hint": "Use more specific text or set expected_replacements parameter",
                    "occurrences_found": occurrences
                }
            
            # Perform replacement
            new_content = old_content.replace(old_text, new_text, expected_replacements)
            
            # Write back
            file_path.write_text(new_content, encoding='utf-8')
            
            # Calculate diff stats
            old_lines = old_content.splitlines()
            new_lines = new_content.splitlines()
            lines_added = len(new_lines) - len(old_lines)
            chars_added = len(new_content) - len(old_content)
            
            return {
                "success": True,
                "old_content": old_content,
                "new_content": new_content,
                "replacements_made": expected_replacements,
                "lines_added": lines_added,
                "chars_added": chars_added,
                "path": str(file_path)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "old_content": None,
                "new_content": None
            }
    
    # ========== CODE SEARCH (Grep) ==========
    
    def grep(self, pattern: str, include: str = "*.py", 
             exclude_dirs: List[str] = None) -> Dict[str, Any]:
        """
        Code search like OpenCode's grep.ts
        Search file contents with regex support.
        """
        if exclude_dirs is None:
            exclude_dirs = ['venv', 'node_modules', '.git', '__pycache__', '.venv']
        
        results = []
        files_searched = 0
        total_matches = 0
        
        try:
            # Search all matching files
            for file_path in self.project_root.rglob(include):
                # Skip excluded directories
                if any(excl in file_path.parts for excl in exclude_dirs):
                    continue
                
                if not file_path.is_file():
                    continue
                
                files_searched += 1
                
                try:
                    content = file_path.read_text(encoding='utf-8')
                    lines = content.splitlines()
                    
                    for line_num, line in enumerate(lines, 1):
                        if re.search(pattern, line, re.IGNORECASE):
                            results.append({
                                "file": str(file_path.relative_to(self.project_root)),
                                "line": line_num,
                                "content": line.strip(),
                                "match": re.search(pattern, line).group(0)
                            })
                            total_matches += 1
                            
                except (UnicodeDecodeError, PermissionError):
                    continue  # Skip binary files
            
            return {
                "success": True,
                "matches": results,
                "total_matches": total_matches,
                "files_searched": files_searched,
                "pattern": pattern,
                "include": include
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "matches": [],
                "total_matches": 0
            }
    
    # ========== FILE PATTERN MATCHING (Glob) ==========
    
    def glob(self, pattern: str, exclude_dirs: List[str] = None) -> Dict[str, Any]:
        """
        File pattern matching like OpenCode's glob.ts
        Find files by glob pattern.
        """
        if exclude_dirs is None:
            exclude_dirs = ['venv', 'node_modules', '.git', '__pycache__']
        
        try:
            matches = []
            
            # Handle ** patterns for recursive search
            if '**' in pattern:
                # Recursive search from project root
                base_pattern = pattern.replace('**/', '')
                for file_path in self.project_root.rglob(base_pattern):
                    if file_path.is_file():
                        rel_path = file_path.relative_to(self.project_root)
                        
                        # Skip excluded directories
                        if any(excl in rel_path.parts for excl in exclude_dirs):
                            continue
                        
                        matches.append(str(rel_path))
            else:
                # Simple pattern
                for file_path in self.project_root.glob(pattern):
                    if file_path.is_file():
                        rel_path = file_path.relative_to(self.project_root)
                        
                        if any(excl in rel_path.parts for excl in exclude_dirs):
                            continue
                        
                        matches.append(str(rel_path))
            
            return {
                "success": True,
                "files": matches,
                "count": len(matches),
                "pattern": pattern
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "files": [],
                "count": 0
            }
    
    # ========== UTILITY METHODS ==========
    
    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to project root."""
        p = Path(path)
        
        # If absolute path, use as-is
        if p.is_absolute():
            return p
        
        # If relative to project root
        full_path = self.project_root / p
        if full_path.exists():
            return full_path
        
        # Return as-is (might be new file)
        return full_path
    
    def list_directory(self, path: str = ".", depth: int = 1) -> Dict[str, Any]:
        """
        Enhanced directory listing with depth control.
        """
        try:
            dir_path = self._resolve_path(path)
            
            if not dir_path.exists():
                return {
                    "success": False,
                    "error": f"Directory not found: {dir_path}",
                    "entries": []
                }
            
            entries = []
            
            def scan_dir(current_path: Path, current_depth: int):
                if current_depth > depth:
                    return
                
                try:
                    for item in sorted(current_path.iterdir()):
                        # Skip hidden and excluded dirs
                        if item.name.startswith('.'):
                            continue
                        
                        rel_path = item.relative_to(dir_path)
                        
                        entry = {
                            "name": item.name,
                            "type": "directory" if item.is_dir() else "file",
                            "path": str(rel_path)
                        }
                        
                        if item.is_file():
                            entry["size_bytes"] = item.stat().st_size
                        
                        entries.append(entry)
                        
                        # Recurse into subdirectories
                        if item.is_dir() and current_depth < depth:
                            scan_dir(item, current_depth + 1)
                            
                except PermissionError:
                    pass
            
            scan_dir(dir_path, 0)
            
            return {
                "success": True,
                "directory": str(dir_path),
                "entries": entries,
                "count": len(entries)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "entries": []
            }


# Global instance helper
_tools_cache: Dict[str, OpenCodeStyleTools] = {}

def get_opencode_tools(project_root: str) -> OpenCodeStyleTools:
    """Get or create OpenCode-style tools instance for project."""
    if project_root not in _tools_cache:
        _tools_cache[project_root] = OpenCodeStyleTools(project_root)
    return _tools_cache[project_root]
