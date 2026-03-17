"""
Context Manager for Cortex AI Agent IDE
Injects project context into AI prompts for better responses
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from src.utils.logger import get_logger

log = get_logger("context_manager")


class ContextInjector:
    """Injects relevant project context into AI prompts."""
    
    def __init__(self, project_manager=None, editor_widget=None, 
                 terminal_widget=None, git_manager=None):
        self.project_manager = project_manager
        self.editor_widget = editor_widget
        self.terminal_widget = terminal_widget
        self.git_manager = git_manager
        
    def gather_context(self, selected_context_types: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Gather all available context based on selected types.
        
        Args:
            selected_context_types: List of context types to include
                                   Options: "files", "project", "git", "terminal", "history"
        """
        if selected_context_types is None:
            selected_context_types = ["files", "project", "git"]
            
        context = {}
        
        try:
            # 1. Open files context
            if "files" in selected_context_types:
                files_context = self._get_open_files_context()
                if files_context:
                    context["open_files"] = files_context
                    
            # 2. Project structure context
            if "project" in selected_context_types:
                project_context = self._get_project_structure()
                if project_context:
                    context["project"] = project_context
                    
            # 3. Git context
            if "git" in selected_context_types and self.git_manager:
                git_context = self._get_git_context()
                if git_context:
                    context["git"] = git_context
                    
            # 4. Terminal context
            if "terminal" in selected_context_types and self.terminal_widget:
                terminal_context = self._get_terminal_context()
                if terminal_context:
                    context["terminal"] = terminal_context
                    
        except Exception as e:
            log.error(f"Error gathering context: {e}")
            
        return context
        
    def _get_open_files_context(self, max_chars: int = 3000) -> str:
        """Get content of currently open/selected files."""
        files_info = []
        
        try:
            # Get current file from editor widget
            if self.editor_widget:
                # Try to get current file path
                current_file = getattr(self.editor_widget, '_filepath', None) or \
                              getattr(self.editor_widget, 'current_file', None)
                
                if current_file and os.path.exists(current_file):
                    # Get content
                    content = self._read_file_content(current_file, max_chars)
                    if content:
                        files_info.append(f"Current File: {current_file}\n```\n{content}\n```")
                        
                # Also get selected text if any
                selected_text = getattr(self.editor_widget, 'get_selected_text', lambda: None)()
                if selected_text:
                    files_info.append(f"Selected Code:\n```\n{selected_text[:500]}\n```")
                    
        except Exception as e:
            log.error(f"Error getting open files context: {e}")
            
        return "\n\n".join(files_info) if files_info else ""
        
    def _read_file_content(self, file_path: str, max_chars: int) -> str:
        """Safely read file content."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(max_chars)
                if len(content) == max_chars:
                    content += "\n... [truncated]"
                return content
        except Exception as e:
            log.error(f"Error reading file {file_path}: {e}")
            return ""
            
    def _get_project_structure(self, max_items: int = 30) -> str:
        """Get project file structure."""
        try:
            root = self._get_project_root()
            if not root:
                return ""
                
            structure = []
            root_path = Path(root)
            
            # Add root
            structure.append(f"📁 {root_path.name}/")
            
            # Get top-level items
            count = 0
            for item in sorted(root_path.iterdir()):
                if count >= max_items:
                    structure.append("  ...")
                    break
                    
                # Skip hidden and common ignore directories
                if item.name.startswith('.') or item.name in ['__pycache__', 'node_modules', 'venv', '.venv']:
                    continue
                    
                if item.is_dir():
                    # Count files in directory
                    try:
                        file_count = len(list(item.iterdir()))
                        structure.append(f"  📁 {item.name}/ ({file_count} items)")
                    except:
                        structure.append(f"  📁 {item.name}/")
                else:
                    structure.append(f"  📄 {item.name}")
                    
                count += 1
                
            return "Project Structure:\n" + "\n".join(structure)
            
        except Exception as e:
            log.error(f"Error getting project structure: {e}")
            return ""
            
    def _get_git_context(self) -> str:
        """Get git status and information."""
        try:
            if not self.git_manager or not self.git_manager.is_repo():
                return ""
                
            context_parts = []
            
            # Get current branch
            branch = self.git_manager.get_branch()
            if branch:
                context_parts.append(f"Branch: {branch}")
                
            # Get status
            files = self.git_manager.get_status()
            if files:
                modified = [f.path for f in files if f.status.value == 'M' and not f.staged]
                staged = [f.path for f in files if f.staged]
                untracked = [f.path for f in files if f.status.value == '?']
                
                if modified:
                    context_parts.append(f"Modified files ({len(modified)}): {', '.join(modified[:5])}")
                if staged:
                    context_parts.append(f"Staged files ({len(staged)}): {', '.join(staged[:5])}")
                if untracked:
                    context_parts.append(f"Untracked files ({len(untracked)}): {', '.join(untracked[:5])}")
                    
            return "Git Status:\n" + "\n".join(context_parts) if context_parts else ""
            
        except Exception as e:
            log.error(f"Error getting git context: {e}")
            return ""
            
    def _get_terminal_context(self, max_lines: int = 10) -> str:
        """Get recent terminal output."""
        try:
            if not self.terminal_widget:
                return ""
                
            # Try to get last output
            output_widget = getattr(self.terminal_widget, '_output', None) or \
                           getattr(self.terminal_widget, 'output', None)
                           
            if output_widget:
                text = output_widget.toPlainText()
                lines = text.split('\n')
                recent_lines = lines[-max_lines:] if len(lines) > max_lines else lines
                
                # Filter out empty lines and prompts
                filtered = [line for line in recent_lines if line.strip() and not line.strip().endswith('>')]
                
                if filtered:
                    return "Recent Terminal Output:\n```\n" + "\n".join(filtered) + "\n```"
                    
        except Exception as e:
            log.error(f"Error getting terminal context: {e}")
            
        return ""
        
    def _get_project_root(self) -> Optional[str]:
        """Get the project root directory."""
        if self.project_manager:
            root = getattr(self.project_manager, 'root', None)
            if root:
                return str(root)
                
        # Fallback to current working directory
        return os.getcwd()
        
    def build_prompt_with_context(self, user_message: str, context: Dict[str, str]) -> str:
        """
        Build the final prompt with all context.
        
        Args:
            user_message: The user's message
            context: Dictionary of context sections
            
        Returns:
            Complete prompt string
        """
        sections = [
            "You are an AI coding assistant. Use the following context to help answer the user's question.",
            "",
        ]
        
        # Priority order for context sections
        priority_order = ["open_files", "selected_code", "project", "git", "terminal", "conversation"]
        
        # Add each context section in priority order
        for section_name in priority_order:
            if section_name in context and context[section_name]:
                sections.append(context[section_name])
                sections.append("")
                
        # Add user message
        sections.append("## User Question")
        sections.append(user_message)
        sections.append("")
        sections.append("Please provide a helpful response based on the context above.")
        
        return "\n".join(sections)
        
    def get_context_preview(self, context: Dict[str, str], max_length: int = 500) -> str:
        """Get a preview of the context for display."""
        preview_parts = []
        
        for section_name, section_content in context.items():
            if section_content:
                # Truncate each section
                content = section_content[:200] + "..." if len(section_content) > 200 else section_content
                preview_parts.append(f"{section_name}: {len(section_content)} chars")
                
        return "\n".join(preview_parts) if preview_parts else "No context gathered"
