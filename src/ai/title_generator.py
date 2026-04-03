"""
Auto Title Generator for Cortex AI Agent
Generates concise, descriptive chat titles using AI
Based on OpenCode's title generation (packages/opencode/src/agent/prompt/title.txt)
"""

from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from src.ai.prompt_manager import get_prompt_manager
from src.utils.logger import get_logger

log = get_logger("title_generator")


class TitleGenerator(QObject):
    """
    Generates AI-powered chat titles based on user messages.
    
    Features:
    - Async title generation (non-blocking)
    - Configurable title length
    - Caching to avoid regenerating titles
    """
    
    title_generated = pyqtSignal(str, str)  # conversation_id, title
    
    def __init__(self, ai_agent=None):
        """
        Initialize title generator.
        
        Args:
            ai_agent: AIAgent instance for making title generation requests
        """
        super().__init__()
        self.ai_agent = ai_agent
        self.prompt_manager = get_prompt_manager()
        
        # Cache for generated titles
        self._title_cache: dict = {}
        
        log.info("TitleGenerator initialized")
    
    def generate_title(self, user_message: str, conversation_id: str) -> Optional[str]:
        """
        Generate a title for a conversation based on the first user message.
        
        Args:
            user_message: The first message from the user
            conversation_id: Unique conversation identifier
            
        Returns:
            Generated title string, or None if generation fails
            
        Example:
            title = generator.generate_title(
                "Create a login system with JWT authentication",
                "conv-123"
            )
            # Returns: "JWT Authentication Implementation"
        """
        # Check cache
        if conversation_id in self._title_cache:
            log.debug(f"Using cached title for {conversation_id}")
            return self._title_cache[conversation_id]
        
        # Generate title prompt
        title_prompt = self.prompt_manager.get_prompt('title', {
            'user_message': user_message
        })
        
        try:
            # Use AI to generate title
            if self.ai_agent and hasattr(self.ai_agent, 'generate_completion'):
                # Async generation through AI agent
                title = self._generate_with_ai(title_prompt)
            else:
                # Fallback: simple heuristic
                title = self._generate_heuristic(user_message)
            
            # Clean and validate
            title = self._clean_title(title)
            
            # Cache and emit
            self._title_cache[conversation_id] = title
            self.title_generated.emit(conversation_id, title)
            
            log.info(f"Generated title for {conversation_id}: {title}")
            return title
            
        except Exception as e:
            log.error(f"Failed to generate title: {e}")
            return None
    
    def generate_title_async(self, user_message: str, conversation_id: str):
        """
        Generate title asynchronously (non-blocking).
        
        Args:
            user_message: The first message from the user
            conversation_id: Unique conversation identifier
        """
        if conversation_id in self._title_cache:
            self.title_generated.emit(conversation_id, self._title_cache[conversation_id])
            return
        
        # Create worker thread
        worker = TitleGenerationWorker(
            user_message=user_message,
            conversation_id=conversation_id,
            prompt_manager=self.prompt_manager,
            ai_agent=self.ai_agent
        )
        worker.title_ready.connect(self._on_title_ready)
        worker.start()
    
    def _on_title_ready(self, conversation_id: str, title: str):
        """Handle async title generation completion."""
        self._title_cache[conversation_id] = title
        self.title_generated.emit(conversation_id, title)
    
    def _generate_with_ai(self, prompt: str) -> str:
        """Generate title using AI agent."""
        # This would integrate with the AI provider
        # For now, return a heuristic title
        return self._generate_heuristic(prompt)
    
    def _generate_heuristic(self, user_message: str) -> str:
        """
        Generate a title using simple heuristics (fallback).
        
        Args:
            user_message: User's first message
            
        Returns:
            Generated title
        """
        import re
        
        # Clean the message
        message = user_message.strip()
        
        # Remove code blocks
        message = re.sub(r'```[\s\S]*?```', '', message)
        message = re.sub(r'`[^`]*`', '', message)
        
        # Remove URLs
        message = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', message)
        
        # Get first sentence or first 80 chars
        first_sentence = re.split(r'[.!?\n]', message)[0].strip()
        if len(first_sentence) > 80:
            first_sentence = first_sentence[:77] + "..."
        
        # Extract keywords
        words = first_sentence.split()
        
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their', 'this', 'that', 'these', 'those'}
        
        keywords = [w for w in words if w.lower() not in stop_words and len(w) > 2]
        
        # Build title from keywords (max 6 words)
        if len(keywords) >= 3:
            title_words = keywords[:6]
        else:
            title_words = words[:6] if len(words) <= 6 else words[:6]
        
        title = ' '.join(title_words)
        
        # Capitalize
        title = title.title()
        
        # If still empty, use generic title
        if not title:
            title = "New Chat"
        
        return title
    
    def _clean_title(self, title: str) -> str:
        """Clean and format the generated title."""
        # Remove quotes if present
        title = title.strip().strip('"\'')
        
        # Limit length
        words = title.split()
        if len(words) > 6:
            title = ' '.join(words[:6])
        
        # Ensure title case
        title = title.title()
        
        return title
    
    def get_cached_title(self, conversation_id: str) -> Optional[str]:
        """Get a cached title if available."""
        return self._title_cache.get(conversation_id)
    
    def clear_cache(self, conversation_id: Optional[str] = None):
        """
        Clear title cache.
        
        Args:
            conversation_id: Specific conversation to clear, or None for all
        """
        if conversation_id:
            self._title_cache.pop(conversation_id, None)
        else:
            self._title_cache.clear()


class TitleGenerationWorker(QThread):
    """Background worker for async title generation."""
    
    title_ready = pyqtSignal(str, str)  # conversation_id, title
    
    def __init__(self, user_message: str, conversation_id: str, 
                 prompt_manager, ai_agent=None, parent=None):
        super().__init__(parent)
        self.user_message = user_message
        self.conversation_id = conversation_id
        self.prompt_manager = prompt_manager
        self.ai_agent = ai_agent
    
    def run(self):
        """Generate title in background thread."""
        try:
            # Get title prompt
            title_prompt = self.prompt_manager.get_prompt('title', {
                'user_message': self.user_message
            })
            
            # Generate title
            if self.ai_agent and hasattr(self.ai_agent, 'generate_completion'):
                # Use AI for generation
                title = self._generate_with_ai(title_prompt)
            else:
                # Fallback to heuristic
                title = self._generate_heuristic(self.user_message)
            
            # Clean title
            title = self._clean_title(title)
            
            self.title_ready.emit(self.conversation_id, title)
            
        except Exception as e:
            log.error(f"Title generation failed: {e}")
            # Emit fallback title
            self.title_ready.emit(self.conversation_id, "New Chat")
    
    def _generate_with_ai(self, prompt: str) -> str:
        """Generate using AI agent."""
        # Placeholder - integrate with actual AI provider
        return self._generate_heuristic(prompt)
    
    def _generate_heuristic(self, user_message: str) -> str:
        """Simple heuristic title generation."""
        import re
        
        message = user_message.strip()
        message = re.sub(r'```[\s\S]*?```', '', message)
        message = re.sub(r'`[^`]*`', '', message)
        
        first_sentence = re.split(r'[.!?\n]', message)[0].strip()
        if len(first_sentence) > 80:
            first_sentence = first_sentence[:77] + "..."
        
        words = first_sentence.split()
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        keywords = [w for w in words if w.lower() not in stop_words and len(w) > 2]
        
        title_words = keywords[:6] if len(keywords) >= 3 else words[:6]
        title = ' '.join(title_words).title()
        
        return title if title else "New Chat"
    
    def _clean_title(self, title: str) -> str:
        """Clean the generated title."""
        title = title.strip().strip('"\'')
        words = title.split()
        if len(words) > 6:
            title = ' '.join(words[:6])
        return title.title()


# Global instance
_title_generator: Optional[TitleGenerator] = None


def get_title_generator(ai_agent=None) -> TitleGenerator:
    """Get global TitleGenerator instance."""
    global _title_generator
    if _title_generator is None:
        _title_generator = TitleGenerator(ai_agent)
    elif ai_agent is not None:
        _title_generator.ai_agent = ai_agent
    return _title_generator
