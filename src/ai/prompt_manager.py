"""
Prompt Template System for Cortex AI Agent
Manages externalized, customizable prompt templates
Based on OpenCode's prompt system (packages/opencode/src/agent/prompt/)
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional, Any
from src.utils.logger import get_logger

log = get_logger("prompt_manager")


class PromptManager:
    """
    Manages prompt templates for different agent modes and tasks.
    
    Features:
    - Load prompt templates from external files
    - Variable substitution ({{variable_name}})
    - Multiple agent modes (build, explore, debug, etc.)
    - Custom user prompts support
    """
    
    def __init__(self, prompts_dir: Optional[str] = None):
        """
        Initialize prompt manager.
        
        Args:
            prompts_dir: Directory containing prompt templates. 
                        Defaults to src/ai/prompts/
        """
        if prompts_dir is None:
            # Default location: src/ai/prompts/
            self.prompts_dir = Path(__file__).parent / "prompts"
        else:
            self.prompts_dir = Path(prompts_dir)
        
        # Cache for loaded prompts
        self._prompt_cache: Dict[str, str] = {}
        
        # Available prompt types
        self.available_prompts = self._discover_prompts()
        
        log.info(f"PromptManager initialized with {len(self.available_prompts)} prompts")
    
    def _discover_prompts(self) -> Dict[str, Path]:
        """Discover all available prompt files."""
        prompts = {}
        
        if not self.prompts_dir.exists():
            log.warning(f"Prompts directory not found: {self.prompts_dir}")
            return prompts
        
        for prompt_file in self.prompts_dir.glob("*.txt"):
            prompt_name = prompt_file.stem  # filename without extension
            prompts[prompt_name] = prompt_file
            log.debug(f"Discovered prompt: {prompt_name}")
        
        return prompts
    
    def get_prompt(self, prompt_name: str, variables: Optional[Dict[str, Any]] = None) -> str:
        """
        Get a prompt template with variable substitution.
        
        Args:
            prompt_name: Name of the prompt (e.g., 'build', 'explore', 'title')
            variables: Dictionary of variables to substitute (e.g., {'project_root': '/path'})
            
        Returns:
            The prompt text with variables substituted
            
        Example:
            prompt = manager.get_prompt('build', {
                'project_root': '/home/user/project',
                'current_file': 'main.py'
            })
        """
        # Load prompt from cache or file
        if prompt_name not in self._prompt_cache:
            if prompt_name not in self.available_prompts:
                log.error(f"Prompt not found: {prompt_name}")
                return self._get_default_prompt(prompt_name)
            
            prompt_path = self.available_prompts[prompt_name]
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    self._prompt_cache[prompt_name] = f.read()
                log.debug(f"Loaded prompt: {prompt_name}")
            except Exception as e:
                log.error(f"Failed to load prompt {prompt_name}: {e}")
                return self._get_default_prompt(prompt_name)
        
        prompt_text = self._prompt_cache[prompt_name]
        
        # Substitute variables
        if variables:
            prompt_text = self._substitute_variables(prompt_text, variables)
        
        return prompt_text
    
    def _substitute_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """
        Substitute {{variable_name}} with actual values.
        
        Args:
            text: Template text with {{variables}}
            variables: Dictionary of variable names and values
            
        Returns:
            Text with variables substituted
        """
        result = text
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value) if value is not None else "")
        
        # Log any remaining unreplaced variables
        remaining = re.findall(r'\{\{(\w+)\}\}', result)
        if remaining:
            log.debug(f"Unsubstituted variables in prompt: {remaining}")
        
        return result
    
    def _get_default_prompt(self, prompt_name: str) -> str:
        """Get a default prompt if the requested one is not found."""
        defaults = {
            'build': "You are a helpful AI coding assistant. Help the user build and edit code.",
            'explore': "You are a helpful AI assistant. Help the user understand and explore code.",
            'debug': "You are a helpful AI assistant. Help the user debug and fix issues.",
            'title': "Generate a short title (3-6 words) for this conversation:\n\n{{user_message}}\n\nTitle:",
            'summary': "Summarize the key points from this conversation:\n\n{{conversation_history}}\n\nSummary:"
        }
        
        return defaults.get(prompt_name, "You are a helpful AI assistant.")
    
    def reload_prompt(self, prompt_name: str) -> bool:
        """
        Reload a prompt from disk (useful for hot-reloading during development).
        
        Args:
            prompt_name: Name of the prompt to reload
            
        Returns:
            True if successful, False otherwise
        """
        if prompt_name in self._prompt_cache:
            del self._prompt_cache[prompt_name]
        
        # Rediscover in case new files were added
        self.available_prompts = self._discover_prompts()
        
        try:
            self.get_prompt(prompt_name)
            return True
        except Exception as e:
            log.error(f"Failed to reload prompt {prompt_name}: {e}")
            return False
    
    def reload_all(self) -> None:
        """Clear cache and rediscover all prompts."""
        self._prompt_cache.clear()
        self.available_prompts = self._discover_prompts()
        log.info(f"Reloaded {len(self.available_prompts)} prompts")
    
    def list_available(self) -> list:
        """Return list of available prompt names."""
        return list(self.available_prompts.keys())
    
    def get_agent_mode_prompt(self, mode: str, context: Dict[str, Any]) -> str:
        """
        Get the appropriate prompt for an agent mode.
        
        Args:
            mode: Agent mode ('build', 'explore', 'debug')
            context: Context variables (project_root, current_file, selected_code, etc.)
            
        Returns:
            The formatted system prompt
        """
        mode_map = {
            'build': 'build',
            'explore': 'explore',
            'debug': 'debug',
            'plan': 'explore',  # Plan mode uses explore prompt
            'chat': 'build'     # Default to build mode
        }
        
        prompt_name = mode_map.get(mode, 'build')
        return self.get_prompt(prompt_name, context)


# Singleton instance for global access
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(prompts_dir: Optional[str] = None) -> PromptManager:
    """
    Get the global PromptManager instance.
    
    Args:
        prompts_dir: Optional directory for prompts (only used on first call)
        
    Returns:
        PromptManager instance
    """
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager(prompts_dir)
    return _prompt_manager
