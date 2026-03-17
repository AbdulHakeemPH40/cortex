"""
Context Compactor for Cortex AI Agent IDE
Intelligently reduces context size to fit within token limits
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass
from src.utils.logger import get_logger

log = get_logger("context_compactor")


@dataclass
class ContextSection:
    """Represents a section of context."""
    name: str
    content: str
    priority: int  # Higher = more important
    token_estimate: int


class ContextCompactor:
    """
    Intelligently compacts context to fit within token limits.
    Uses various strategies to reduce size while preserving important information.
    """
    
    MAX_CONTEXT_TOKENS = 8000
    CHARS_PER_TOKEN = 4  # Rough estimate: 4 characters ≈ 1 token
    
    def __init__(self, max_tokens: int = MAX_CONTEXT_TOKENS):
        self.max_tokens = max_tokens
        
    def compact_context(self, context: Dict[str, str], user_message: str = "") -> Dict[str, str]:
        """
        Compact context to fit within token limit.
        
        Args:
            context: Dictionary of context sections
            user_message: User's message (to account for its tokens)
            
        Returns:
            Compacted context dictionary
        """
        # Calculate current token usage
        user_tokens = len(user_message) // self.CHARS_PER_TOKEN if user_message else 0
        available_tokens = self.max_tokens - user_tokens
        
        # Convert to sections with priorities
        sections = self._prioritize_sections(context)
        
        # Check if already within limit
        total_tokens = sum(s.token_estimate for s in sections)
        if total_tokens <= available_tokens:
            log.info(f"Context fits within limit: {total_tokens}/{available_tokens} tokens")
            return context
            
        log.info(f"Context too large ({total_tokens} tokens), compacting...")
        
        # Apply compaction strategies
        compacted = self._apply_compaction(sections, available_tokens)
        
        return compacted
        
    def _prioritize_sections(self, context: Dict[str, str]) -> List[ContextSection]:
        """
        Convert context to prioritized sections.
        Priority order (higher number = more important):
        1. open_files (100) - Most important
        2. selected_code (90)
        3. git (70)
        4. terminal (50)
        5. project (30)
        6. conversation (20) - Least important
        """
        priority_map = {
            "open_files": 100,
            "selected_code": 90,
            "git": 70,
            "terminal": 50,
            "project": 30,
            "conversation": 20,
        }
        
        sections = []
        for name, content in context.items():
            if content:
                token_estimate = len(content) // self.CHARS_PER_TOKEN
                priority = priority_map.get(name, 50)
                sections.append(ContextSection(name, content, priority, token_estimate))
                
        # Sort by priority (highest first)
        sections.sort(key=lambda s: s.priority, reverse=True)
        
        return sections
        
    def _apply_compaction(self, sections: List[ContextSection], max_tokens: int) -> Dict[str, str]:
        """Apply compaction strategies to fit within token limit."""
        result = {}
        current_tokens = 0
        
        for section in sections:
            # Check if we can fit the whole section
            if current_tokens + section.token_estimate <= max_tokens:
                result[section.name] = section.content
                current_tokens += section.token_estimate
            else:
                # Try to truncate/summarize
                available_tokens = max_tokens - current_tokens
                if available_tokens > 100:  # Only add if we have reasonable space
                    compacted = self._compact_section(section, available_tokens)
                    if compacted:
                        result[section.name] = compacted
                        current_tokens += len(compacted) // self.CHARS_PER_TOKEN
                        
        log.info(f"Compacted context to {current_tokens}/{max_tokens} tokens")
        return result
        
    def _compact_section(self, section: ContextSection, max_tokens: int) -> str:
        """Compact a single section using appropriate strategy."""
        max_chars = max_tokens * self.CHARS_PER_TOKEN
        
        if section.name == "open_files":
            return self._compact_file_content(section.content, max_chars)
        elif section.name == "project":
            return self._compact_project_structure(section.content, max_chars)
        elif section.name == "terminal":
            return self._compact_terminal_output(section.content, max_chars)
        elif section.name == "conversation":
            return self._compact_conversation(section.content, max_chars)
        else:
            # Generic truncation
            return self._truncate(section.content, max_chars)
            
    def _compact_file_content(self, content: str, max_chars: int) -> str:
        """Compact file content by truncating intelligently."""
        if len(content) <= max_chars:
            return content
            
        # Try to keep beginning and end, truncate middle
        half_chars = max_chars // 2
        
        # Find code block boundaries
        lines = content.split('\n')
        
        if len(lines) > 50:
            # Keep first 25 and last 25 lines
            beginning = '\n'.join(lines[:25])
            ending = '\n'.join(lines[-25:])
            return beginning + "\n\n... [truncated - showing first and last 25 lines] ...\n\n" + ending
        else:
            # Simple truncation
            return self._truncate(content, max_chars)
            
    def _compact_project_structure(self, content: str, max_chars: int) -> str:
        """Compact project structure by showing only top-level items."""
        if len(content) <= max_chars:
            return content
            
        lines = content.split('\n')
        
        # Keep only top-level items (not indented)
        top_level = [line for line in lines if not line.startswith('  ')]
        
        if len('\n'.join(top_level)) <= max_chars:
            return '\n'.join(top_level) + "\n  ... [subdirectories truncated] ..."
        else:
            return self._truncate(content, max_chars)
            
    def _compact_terminal_output(self, content: str, max_chars: int) -> str:
        """Compact terminal output by keeping only last lines."""
        if len(content) <= max_chars:
            return content
            
        lines = content.split('\n')
        
        # Keep last N lines
        result_lines = []
        current_length = 0
        
        for line in reversed(lines):
            if current_length + len(line) + 1 > max_chars:
                break
            result_lines.insert(0, line)
            current_length += len(line) + 1
            
        if len(result_lines) < len(lines):
            return "... [earlier output truncated] ...\n" + '\n'.join(result_lines)
        else:
            return '\n'.join(result_lines)
            
    def _compact_conversation(self, content: str, max_chars: int) -> str:
        """Compact conversation by keeping only recent messages."""
        if len(content) <= max_chars:
            return content
            
        lines = content.split('\n')
        
        # Keep messages from the end
        result_lines = []
        current_length = 0
        
        for line in reversed(lines):
            if current_length + len(line) + 1 > max_chars:
                break
            result_lines.insert(0, line)
            current_length += len(line) + 1
            
        if len(result_lines) < len(lines):
            return "... [earlier conversation truncated] ...\n" + '\n'.join(result_lines)
        else:
            return '\n'.join(result_lines)
            
    def _truncate(self, content: str, max_chars: int) -> str:
        """Simple truncation with indicator."""
        if len(content) <= max_chars:
            return content
            
        truncated = content[:max_chars - 20]
        return truncated + "\n... [truncated] ..."
        
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        return len(text) // self.CHARS_PER_TOKEN
        
    def get_context_stats(self, context: Dict[str, str]) -> Dict[str, int]:
        """Get statistics about context size."""
        stats = {}
        total_tokens = 0
        
        for name, content in context.items():
            tokens = self.estimate_tokens(content)
            stats[name] = tokens
            total_tokens += tokens
            
        stats["total"] = total_tokens
        stats["max_allowed"] = self.max_tokens
        stats["is_within_limit"] = total_tokens <= self.max_tokens
        
        return stats
