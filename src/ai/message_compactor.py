"""
Message Compactor for Cortex AI Agent
Intelligently compacts conversation history to fit within token limits
Based on OpenCode's compaction system
"""

import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from src.ai.prompt_manager import get_prompt_manager
from src.utils.logger import get_logger

log = get_logger("message_compactor")


class CompactionStrategy(Enum):
    """Strategies for message compaction."""
    NONE = "none"              # No compaction
    SUMMARIZE = "summarize"    # AI-powered summarization
    TRUNCATE = "truncate"      # Simple truncation
    SELECTIVE = "selective"    # Keep important, remove noise


@dataclass
class CompactionMessage:
    """Represents a message in the conversation."""
    role: str  # user, assistant, system
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {}
        }


@dataclass
class CompactionResult:
    """Result of message compaction."""
    messages: List[CompactionMessage]
    summary: Optional[str]
    tokens_saved: int
    strategy_used: CompactionStrategy


class MessageCompactor:
    """
    Manages conversation messages to stay within token limits.
    
    Features:
    - AI-powered summarization of old messages
    - Smart selection of important messages
    - Token counting and budget management
    - Multiple compaction strategies
    """
    
    # Token limits (approximate)
    DEFAULT_TOKEN_BUDGET = 4000  # Leave room for response
    SUMMARIZATION_THRESHOLD = 6000  # When to start summarizing
    MAX_MESSAGES_BEFORE_COMPACTION = 20
    
    def __init__(self, token_budget: int = None):
        """
        Initialize message compactor.
        
        Args:
            token_budget: Maximum tokens to allow in context
        """
        self.token_budget = token_budget or self.DEFAULT_TOKEN_BUDGET
        self.prompt_manager = get_prompt_manager()
        
        # Statistics
        self._compaction_count = 0
        self._total_tokens_saved = 0
        
        log.info(f"MessageCompactor initialized with budget: {self.token_budget} tokens")
    
    def compact(self, messages: List[CompactionMessage], 
                force_strategy: CompactionStrategy = None) -> CompactionResult:
        """
        Compact messages to fit within token budget.
        
        Args:
            messages: List of conversation messages
            force_strategy: Force specific strategy (optional)
            
        Returns:
            CompactionResult with compacted messages and summary
        """
        if not messages:
            return CompactionResult(messages, None, 0, CompactionStrategy.NONE)
        
        # Count current tokens
        total_tokens = self._count_tokens(messages)
        
        # Check if compaction needed
        if total_tokens <= self.token_budget and len(messages) <= self.MAX_MESSAGES_BEFORE_COMPACTION:
            log.debug(f"No compaction needed: {total_tokens} tokens, {len(messages)} messages")
            return CompactionResult(messages, None, 0, CompactionStrategy.NONE)
        
        log.info(f"Compacting messages: {total_tokens} tokens, {len(messages)} messages")
        
        # Choose strategy
        strategy = force_strategy or self._choose_strategy(messages, total_tokens)
        
        # Apply compaction
        if strategy == CompactionStrategy.SUMMARIZE:
            result = self._summarize_messages(messages)
        elif strategy == CompactionStrategy.TRUNCATE:
            result = self._truncate_messages(messages)
        elif strategy == CompactionStrategy.SELECTIVE:
            result = self._selective_compaction(messages)
        else:
            result = CompactionResult(messages, None, 0, CompactionStrategy.NONE)
        
        # Update stats
        self._compaction_count += 1
        self._total_tokens_saved += result.tokens_saved
        
        log.info(f"Compaction complete: saved {result.tokens_saved} tokens using {strategy.value}")
        
        return result
    
    def _count_tokens(self, messages: List[CompactionMessage]) -> int:
        """
        Estimate token count for messages.
        
        Rough approximation: 1 token ≈ 4 characters for English text
        """
        total_chars = sum(len(msg.content) for msg in messages)
        # Add overhead for message structure (role, metadata)
        overhead = len(messages) * 20
        return (total_chars + overhead) // 4
    
    def _choose_strategy(self, messages: List[CompactionMessage], total_tokens: int) -> CompactionStrategy:
        """Choose appropriate compaction strategy."""
        msg_count = len(messages)
        
        # If very long, use summarization
        if total_tokens > self.SUMMARIZATION_THRESHOLD or msg_count > 50:
            return CompactionStrategy.SUMMARIZE
        
        # If moderately long, use selective compaction
        if msg_count > self.MAX_MESSAGES_BEFORE_COMPACTION:
            return CompactionStrategy.SELECTIVE
        
        # Otherwise truncate
        return CompactionStrategy.TRUNCATE
    
    def _summarize_messages(self, messages: List[CompactionMessage]) -> CompactionResult:
        """
        Use AI to summarize old messages.
        
        Strategy:
        - Keep system prompt and recent messages (last 6)
        - Summarize middle section
        """
        if len(messages) <= 10:
            return self._truncate_messages(messages)
        
        # Split messages
        system_msgs = [m for m in messages if m.role == "system"]
        recent_msgs = messages[-6:]  # Keep last 6
        old_msgs = messages[len(system_msgs):-6]  # Middle section to summarize
        
        if not old_msgs:
            return self._truncate_messages(messages)
        
        # Create summary
        summary = self._generate_summary(old_msgs)
        
        # Build compacted message list
        compacted = system_msgs.copy()
        
        if summary:
            # Add summary as system message
            summary_msg = CompactionMessage(
                role="system",
                content=f"[Previous conversation summary]: {summary}",
                timestamp=datetime.now(),
                metadata={"is_summary": True}
            )
            compacted.append(summary_msg)
        
        # Add recent messages
        compacted.extend(recent_msgs)
        
        # Calculate tokens saved
        old_tokens = self._count_tokens(messages)
        new_tokens = self._count_tokens(compacted)
        tokens_saved = old_tokens - new_tokens
        
        return CompactionResult(
            messages=compacted,
            summary=summary,
            tokens_saved=tokens_saved,
            strategy_used=CompactionStrategy.SUMMARIZE
        )
    
    def _generate_summary(self, messages: List[CompactionMessage]) -> str:
        """
        Generate AI summary of messages.
        
        For now, uses a simple heuristic. In production, this would call the AI.
        """
        try:
            # Extract key information
            user_msgs = [m for m in messages if m.role == "user"]
            assistant_msgs = [m for m in messages if m.role == "assistant"]
            
            key_points = []
            
            # Extract user goals from first user message
            if user_msgs:
                first_user = user_msgs[0].content[:100]
                key_points.append(f"Goal: {first_user}...")
            
            # Count interactions
            key_points.append(f"{len(user_msgs)} user messages, {len(assistant_msgs)} assistant responses")
            
            # Note any errors
            errors = [m for m in messages if "error" in m.content.lower()]
            if errors:
                key_points.append(f"{len(errors)} errors encountered")
            
            # Note files mentioned
            import re
            files_mentioned = set()
            for msg in messages:
                matches = re.findall(r'[\w/\\-]+\.(py|js|ts|java|cpp|c|h|md|txt)', msg.content)
                files_mentioned.update(matches)
            
            if files_mentioned:
                files_str = ", ".join(list(files_mentioned)[:5])
                key_points.append(f"Files: {files_str}")
            
            return " | ".join(key_points)
            
        except Exception as e:
            log.error(f"Failed to generate summary: {e}")
            return f"Conversation with {len(messages)} messages"
    
    def _truncate_messages(self, messages: List[CompactionMessage]) -> CompactionResult:
        """
        Simple truncation strategy.
        
        Keep:
        - System messages
        - Most recent messages until budget reached
        """
        if not messages:
            return CompactionResult(messages, None, 0, CompactionStrategy.TRUNCATE)
        
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        
        # Start with system messages
        compacted = system_msgs.copy()
        current_tokens = self._count_tokens(compacted)
        
        # Add recent messages until budget reached
        for msg in reversed(non_system):
            msg_tokens = len(msg.content) // 4
            if current_tokens + msg_tokens > self.token_budget:
                break
            compacted.insert(len(system_msgs), msg)
            current_tokens += msg_tokens
        
        # Sort by timestamp
        compacted.sort(key=lambda m: m.timestamp)
        
        old_tokens = self._count_tokens(messages)
        new_tokens = self._count_tokens(compacted)
        tokens_saved = old_tokens - new_tokens
        
        return CompactionResult(
            messages=compacted,
            summary=None,
            tokens_saved=tokens_saved,
            strategy_used=CompactionStrategy.TRUNCATE
        )
    
    def _selective_compaction(self, messages: List[CompactionMessage]) -> CompactionResult:
        """
        Selective compaction - keep important messages, remove noise.
        
        Keep:
        - System messages
        - User messages with questions/requests
        - Assistant messages with code/tool results
        - Error messages
        
        Remove:
        - Simple acknowledgments
        - Tool execution confirmations without errors
        - Repetitive content
        """
        system_msgs = [m for m in messages if m.role == "system"]
        compacted = system_msgs.copy()
        
        for msg in messages:
            if msg.role == "system":
                continue
            
            # Always keep if contains error
            if "error" in msg.content.lower():
                compacted.append(msg)
                continue
            
            # Always keep user questions
            if msg.role == "user" and "?" in msg.content:
                compacted.append(msg)
                continue
            
            # Keep if contains code
            if "```" in msg.content or "def " in msg.content or "class " in msg.content:
                compacted.append(msg)
                continue
            
            # Keep if contains file operations
            if any(word in msg.content.lower() for word in ["created", "modified", "deleted", "file"]):
                compacted.append(msg)
                continue
            
            # Skip simple confirmations
            if msg.content.strip().lower() in ["ok", "done", "sure", "yes"]:
                continue
            
            # Keep everything else
            compacted.append(msg)
        
        # Sort by timestamp
        compacted.sort(key=lambda m: m.timestamp)
        
        old_tokens = self._count_tokens(messages)
        new_tokens = self._count_tokens(compacted)
        tokens_saved = old_tokens - new_tokens
        
        return CompactionResult(
            messages=compacted,
            summary=None,
            tokens_saved=tokens_saved,
            strategy_used=CompactionStrategy.SELECTIVE
        )
    
    def should_compact(self, messages: List[CompactionMessage]) -> bool:
        """Check if compaction is needed."""
        if not messages:
            return False
        
        token_count = self._count_tokens(messages)
        return token_count > self.token_budget or len(messages) > self.MAX_MESSAGES_BEFORE_COMPACTION
    
    def get_stats(self) -> Dict[str, Any]:
        """Get compaction statistics."""
        return {
            "compaction_count": self._compaction_count,
            "total_tokens_saved": self._total_tokens_saved,
            "token_budget": self.token_budget
        }


# Global instance
_compactor: Optional[MessageCompactor] = None


def get_message_compactor(token_budget: int = None) -> MessageCompactor:
    """Get global MessageCompactor instance."""
    global _compactor
    if _compactor is None:
        _compactor = MessageCompactor(token_budget)
    return _compactor
