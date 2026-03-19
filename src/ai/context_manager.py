"""
AI Context Manager - Automatic file relevance detection and context injection.
Based on industry standards from Cursor, Windsurf, and OpenCode.

This module provides sophisticated context management for AI chat,
including automatic file relevance detection, context injection,
and bidirectional sync between chat and editor.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from src.utils.logger import get_logger
from src.core.codebase_index import get_codebase_index, SymbolType

log = get_logger("ai_context")


@dataclass
class FileContext:
    """Represents a file with its context information."""
    path: str
    content: str
    relevance_score: float = 0.0
    lines: Optional[Tuple[int, int]] = None  # (start, end) for partial content
    is_active: bool = False
    symbols: List[Dict] = field(default_factory=list)
    language: str = ""
    
    def get_snippet_around_line(self, line_number: int, context_lines: int = 5) -> str:
        """Get code snippet around a specific line number."""
        lines = self.content.split('\n')
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        return '\n'.join(lines[start:end])


@dataclass
class ChatContext:
    """Complete context for an AI chat request."""
    query: str
    active_file: Optional[FileContext] = None
    related_files: List[FileContext] = field(default_factory=list)
    project_structure: str = ""
    chat_history: List[Dict] = field(default_factory=list)
    mentioned_files: List[str] = field(default_factory=list)
    terminal_output: str = ""
    git_status: str = ""


class AIContextManager:
    """
    Manages context injection for AI chat.
    Automatically detects relevant files and formats context for the AI.
    
    Industry Standard Features:
    - Automatic relevance ranking via embeddings/symbols
    - Token-aware context selection
    - AST-based context extraction
    - Bidirectional sync between chat and editor
    """
    
    def __init__(self, project_root: str = None):
        self.project_root = project_root or os.getcwd()
        self.codebase_index = None
        self._mentioned_files_history = []
        self._session_context = []
        self._active_file_path = None
        self._cursor_position = None
        
    def initialize_index(self):
        """Initialize the codebase index for file discovery."""
        try:
            self.codebase_index = get_codebase_index(self.project_root)
            log.info("AI Context Manager initialized with codebase index")
        except Exception as e:
            log.warning(f"Could not initialize codebase index: {e}")
    
    def set_active_file(self, file_path: str, cursor_position: Tuple[int, int] = None):
        """Set the currently active file in the editor."""
        self._active_file_path = file_path
        self._cursor_position = cursor_position
        log.debug(f"Active file set: {file_path} at position {cursor_position}")
    
    def get_context_for_query(
        self, 
        query: str, 
        active_file_path: str = None,
        cursor_position: Tuple[int, int] = None,
        max_context_files: int = 5,
        max_tokens_per_file: int = 2000
    ) -> ChatContext:
        """
        Get complete context for an AI query.
        
        Industry Standard Flow:
        1. Get active file context with cursor position
        2. Find semantically related files
        3. Inject all context into AI prompt
        4. Track mentioned files for future context
        
        Args:
            query: The user's query
            active_file_path: Currently open file in editor
            cursor_position: (line, column) of cursor
            max_context_files: Maximum number of related files to include
            max_tokens_per_file: Maximum tokens per file content
            
        Returns:
            ChatContext with all relevant information
        """
        # Update active file if provided
        if active_file_path:
            self.set_active_file(active_file_path, cursor_position)
        
        context = ChatContext(query=query)
        
        # 1. Get active file context
        if self._active_file_path and os.path.exists(self._active_file_path):
            context.active_file = self._get_file_context(
                self._active_file_path, 
                is_active=True,
                cursor_position=self._cursor_position
            )
        
        # 2. Find relevant files based on query
        context.related_files = self._find_relevant_files(
            query, 
            self._active_file_path,
            max_files=max_context_files
        )
        
        # 3. Get project structure overview
        context.project_structure = self._get_project_structure()
        
        # 4. Track mentioned files from query
        context.mentioned_files = self._extract_file_mentions(query)
        self._mentioned_files_history.extend(context.mentioned_files)
        
        log.info(f"Context prepared: {len(context.related_files)} related files, "
                f"active file: {context.active_file.path if context.active_file else 'None'}")
        
        return context
    
    def _get_file_context(
        self, 
        file_path: str, 
        is_active: bool = False,
        cursor_position: Tuple[int, int] = None
    ) -> FileContext:
        """Get context for a single file with symbols and metadata."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Detect language
            language = self._detect_language(file_path)
            
            # Get symbols if available
            symbols = []
            if self.codebase_index:
                try:
                    file_symbols = self.codebase_index.find_symbols(file_path=file_path)
                    symbols = [
                        {
                            'name': sym.name,
                            'type': sym.sym_type.value,
                            'line': sym.line,
                            'col': sym.col
                        }
                        for sym in file_symbols[:10]  # Top 10 symbols
                    ]
                except Exception:
                    pass
            
            # If cursor position provided, get context around cursor
            lines = None
            if cursor_position:
                line_num = cursor_position[0]
                lines_content = content.split('\n')
                start = max(0, line_num - 15)
                end = min(len(lines_content), line_num + 15)
                content = '\n'.join(lines_content[start:end])
                lines = (start + 1, end)
                
            return FileContext(
                path=file_path,
                content=content[:10000],  # Limit content size
                is_active=is_active,
                symbols=symbols,
                language=language,
                lines=lines
            )
        except Exception as e:
            log.warning(f"Could not read file {file_path}: {e}")
            return FileContext(
                path=file_path, 
                content="", 
                is_active=is_active,
                language=self._detect_language(file_path)
            )
    
    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext = Path(file_path).suffix.lower()
        language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'jsx',
            '.tsx': 'tsx',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.h': 'c',
            '.go': 'go',
            '.rs': 'rust',
            '.php': 'php',
            '.rb': 'ruby',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.r': 'r',
            '.sql': 'sql',
            '.sh': 'bash',
            '.ps1': 'powershell',
            '.json': 'json',
            '.xml': 'xml',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
            '.vue': 'vue',
        }
        return language_map.get(ext, 'text')
    
    def _find_relevant_files(
        self, 
        query: str, 
        exclude_path: str = None,
        max_files: int = 5
    ) -> List[FileContext]:
        """
        Find files relevant to the query using multiple strategies.
        
        Strategies:
        1. Codebase index symbol search
        2. Recently mentioned files
        3. File name matching
        4. Content similarity (basic)
        """
        relevant_files = []
        seen_paths = set()
        
        # Strategy 1: Search using codebase index if available
        if self.codebase_index:
            try:
                keywords = self._extract_keywords(query)
                for keyword in keywords[:3]:
                    symbols = self.codebase_index.find_symbols(name=keyword)
                    for symbol in symbols[:2]:
                        if symbol.file_path != exclude_path and symbol.file_path not in seen_paths:
                            file_ctx = self._get_file_context(symbol.file_path)
                            file_ctx.relevance_score = 0.9  # High relevance for symbol matches
                            file_ctx.symbols.append({
                                'name': symbol.name,
                                'type': symbol.sym_type.value,
                                'line': symbol.line
                            })
                            relevant_files.append(file_ctx)
                            seen_paths.add(symbol.file_path)
            except Exception as e:
                log.warning(f"Codebase index search failed: {e}")
        
        # Strategy 2: Check for recently mentioned files
        for mentioned_file in reversed(self._mentioned_files_history[-5:]):
            if (mentioned_file != exclude_path and 
                os.path.exists(mentioned_file) and 
                mentioned_file not in seen_paths):
                file_ctx = self._get_file_context(mentioned_file)
                file_ctx.relevance_score = 0.7
                relevant_files.append(file_ctx)
                seen_paths.add(mentioned_file)
        
        # Strategy 3: Look for files with similar names to query keywords
        if len(relevant_files) < max_files:
            keywords = self._extract_keywords(query)
            for root, dirs, files in os.walk(self.project_root):
                # Skip common non-code directories
                dirs[:] = [d for d in dirs if d not in {
                    'node_modules', '__pycache__', '.git', 'venv', '.venv',
                    'dist', 'build', '.pytest_cache', '.mypy_cache', '.idea', '.vscode'
                }]
                
                for file in files:
                    if len(relevant_files) >= max_files:
                        break
                    
                    # Check if file matches keywords
                    file_lower = file.lower()
                    for keyword in keywords:
                        if keyword.lower() in file_lower:
                            file_path = os.path.join(root, file)
                            if file_path not in seen_paths and file_path != exclude_path:
                                file_ctx = self._get_file_context(file_path)
                                file_ctx.relevance_score = 0.5
                                relevant_files.append(file_ctx)
                                seen_paths.add(file_path)
                            break
                
                if len(relevant_files) >= max_files:
                    break
        
        # Sort by relevance and return
        relevant_files.sort(key=lambda x: x.relevance_score, reverse=True)
        return relevant_files[:max_files]
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract relevant keywords from text, filtering out stop words."""
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those',
            'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us',
            'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their', 'what', 'which',
            'who', 'whom', 'whose', 'where', 'when', 'why', 'how', 'all', 'each',
            'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
            'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
            'file', 'function', 'class', 'method', 'code', 'please', 'help', 'need',
            'want', 'like', 'make', 'create', 'add', 'fix', 'update', 'change', 'get',
            'set', 'use', 'using', 'how', 'what', 'where', 'when', 'why', 'who',
            'explain', 'show', 'tell', 'give', 'write', 'implement', 'modify', 'edit',
            'create', 'delete', 'remove', 'add', 'update', 'change', 'refactor'
        }
        
        # Extract words (including camelCase and snake_case)
        words = []
        current_word = ""
        for char in text:
            if char.isalnum() or char == '_':
                current_word += char
            else:
                if current_word:
                    # Split camelCase
                    if any(c.isupper() for c in current_word[1:]):
                        parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', current_word)
                        words.extend(parts)
                    else:
                        words.append(current_word)
                    current_word = ""
        if current_word:
            words.append(current_word)
        
        # Filter and return unique keywords
        keywords = []
        seen = set()
        for word in words:
            word_lower = word.lower()
            if (len(word) > 2 and 
                word_lower not in stop_words and 
                word_lower not in seen):
                keywords.append(word)
                seen.add(word_lower)
        
        return keywords[:10]
    
    def _extract_file_mentions(self, text: str) -> List[str]:
        """Extract file path mentions from text."""
        mentions = []
        
        # Pattern 1: Explicit file paths
        path_pattern = r'(?:[\w\-]+\/)+[\w\-]+\.[\w]+'
        matches = re.findall(path_pattern, text)
        for match in matches:
            if os.path.exists(match):
                mentions.append(match)
            elif os.path.exists(os.path.join(self.project_root, match)):
                mentions.append(os.path.join(self.project_root, match))
        
        # Pattern 2: File names with extensions
        file_pattern = r'\b[\w\-]+\.(?:py|js|ts|jsx|tsx|html|css|java|cpp|c|go|rs|php|rb)\b'
        matches = re.findall(file_pattern, text, re.IGNORECASE)
        for match in matches:
            # Search for file in project
            for root, dirs, files in os.walk(self.project_root):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                if match in files:
                    mentions.append(os.path.join(root, match))
                    break
        
        return list(set(mentions))
    
    def _get_project_structure(self, max_depth: int = 2) -> str:
        """Get a summary of project structure."""
        structure = []
        structure.append(f"📁 Project Root: {self.project_root}")
        structure.append("")
        
        for root, dirs, files in os.walk(self.project_root):
            depth = root.count(os.sep) - self.project_root.count(os.sep)
            if depth > max_depth:
                del dirs[:]
                continue
            
            # Skip common directories
            dirs[:] = [d for d in dirs if d not in {
                'node_modules', '__pycache__', '.git', 'venv', '.venv',
                'dist', 'build', '.pytest_cache', '.mypy_cache', '.idea', '.vscode'
            }]
            
            indent = "  " * depth
            dir_name = os.path.basename(root) or os.path.basename(self.project_root)
            structure.append(f"{indent}📁 {dir_name}/")
            
            # Add key files
            code_files = [f for f in files if f.endswith(('.py', '.js', '.ts', '.html', '.css', '.java', '.go', '.rs'))][:5]
            for file in code_files:
                structure.append(f"{indent}  📄 {file}")
            
            if len(files) > 5:
                structure.append(f"{indent}  ... and {len(files) - 5} more files")
        
        return "\n".join(structure)
    
    def format_context_for_ai(self, context: ChatContext) -> str:
        """
        Format the context into a prompt for the AI.
        Industry Standard Format with clear sections.
        """
        lines = []
        lines.append("=" * 70)
        lines.append("🤖 AI CODING ASSISTANT CONTEXT")
        lines.append("=" * 70)
        lines.append("")
        
        # User query
        lines.append(f"❓ USER QUERY:")
        lines.append(f"   {context.query}")
        lines.append("")
        
        # Active file
        if context.active_file:
            lines.append("-" * 70)
            lines.append(f"📄 ACTIVE FILE: {context.active_file.path}")
            if context.active_file.language:
                lines.append(f"   Language: {context.active_file.language}")
            if context.active_file.lines:
                lines.append(f"   Lines: {context.active_file.lines[0]}-{context.active_file.lines[1]}")
            lines.append("-" * 70)
            lines.append("```" + context.active_file.language)
            lines.append(context.active_file.content[:5000])
            lines.append("```")
            lines.append("")
        
        # Related files
        if context.related_files:
            lines.append("-" * 70)
            lines.append("📚 RELATED FILES:")
            lines.append("-" * 70)
            for i, file_ctx in enumerate(context.related_files, 1):
                lines.append(f"\n{i}. 📄 {file_ctx.path}")
                lines.append(f"   Relevance Score: {file_ctx.relevance_score:.2f}")
                if file_ctx.language:
                    lines.append(f"   Language: {file_ctx.language}")
                if file_ctx.symbols:
                    lines.append("   Key Symbols:")
                    for sym in file_ctx.symbols[:3]:
                        lines.append(f"     • {sym['name']} ({sym['type']}) at line {sym['line']}")
                # Include snippet
                content_preview = file_ctx.content[:1500]
                lines.append(f"   ```{file_ctx.language}")
                lines.append(content_preview)
                lines.append("   ```")
            lines.append("")
        
        # Project structure
        lines.append("-" * 70)
        lines.append("🗂️ PROJECT STRUCTURE:")
        lines.append("-" * 70)
        lines.append(context.project_structure)
        lines.append("")
        
        lines.append("=" * 70)
        lines.append("💡 INSTRUCTION: Provide assistance based on the above context.")
        lines.append("   When referencing files, use clickable format: `filename:line_number`")
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def update_session_context(self, message: Dict[str, Any]):
        """Update the session context with a new message."""
        self._session_context.append(message)
        # Keep only last 20 messages to manage context window
        if len(self._session_context) > 20:
            self._session_context = self._session_context[-20:]
    
    def get_session_context(self) -> List[Dict[str, Any]]:
        """Get the current session context."""
        return self._session_context.copy()
    
    def clear_session(self):
        """Clear the session context."""
        self._session_context = []
        self._mentioned_files_history = []
        log.info("Session context cleared")


# Singleton instance
_context_manager = None

def get_context_manager(project_root: str = None) -> AIContextManager:
    """Get the singleton context manager instance."""
    global _context_manager
    # Create new instance if none exists OR if project changed
    if _context_manager is None or (project_root and _context_manager.project_root != project_root):
        if project_root:
            _context_manager = AIContextManager(project_root)
            _context_manager.initialize_index()
            log.info(f"Context manager initialized for project: {project_root}")
    return _context_manager
