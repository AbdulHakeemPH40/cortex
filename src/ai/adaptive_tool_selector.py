"""
adaptive_tool_selector.py - Dynamic Tool Selection Based on Conversation Context

Solves API timeout issues by:
1. Analyzing conversation history to determine current task phase
2. Dynamically filtering tools based on what's actually needed
3. Reducing payload size from 39 tools → 5-10 tools max
4. Learning from previous tool usage in the conversation
"""

import re
from typing import Set, List, Dict, Optional, Tuple
from enum import Enum

class ConversationPhase(Enum):
    """Conversation phases for adaptive tool selection."""
    EXPLORATION = "exploration"           # Reading, understanding project
    PLANNING = "planning"                 # Creating plans, task lists
    CREATION = "creation"                 # Writing new files
    MODIFICATION = "modification"         # Editing existing files
    EXECUTION = "execution"               # Running commands
    DEBUGGING = "debugging"              # Fixing errors
    VERIFICATION = "verification"        # Testing, checking results
    COMPLETION = "completion"            # Wrapping up, summarizing


# DYNAMIC TOOL RESTRICTIONS BY PHASE
PHASE_TOOL_RULES = {
    ConversationPhase.EXPLORATION: {
        "essential": {"read_file", "list_directory", "search_codebase", "grep", "semantic_search"},
        "optional": {"get_file_outline", "find_symbol", "analyze_file"},
        "forbidden": {"write_file", "edit_file", "run_command", "bash"}
    },
    ConversationPhase.PLANNING: {
        "essential": {"read_file", "list_directory", "task"},
        "optional": {"search_codebase", "get_file_outline"},
        "forbidden": {"write_file", "edit_file", "run_command", "bash"}
    },
    ConversationPhase.CREATION: {
        "essential": {"write_file", "read_file"},
        "optional": {"inject_after", "add_import", "get_file_outline"},
        "forbidden": {"list_directory", "check_syntax", "search_codebase"}
    },
    ConversationPhase.MODIFICATION: {
        "essential": {"read_file", "edit_file", "smart_edit"},
        "optional": {"get_file_outline", "find_usages", "inject_after", "analyze_file"},
        "forbidden": {"list_directory", "check_syntax", "run_command", "bash", "debug_error"}
    },
    ConversationPhase.EXECUTION: {
        "essential": {"run_command", "bash"},
        "optional": {"read_terminal"},
        "forbidden": {"check_syntax", "list_directory", "read_file"}
    },
    ConversationPhase.DEBUGGING: {
        "essential": {"read_file", "grep", "find_usages"},
        "optional": {"run_command", "debug_error", "get_problems"},
        "forbidden": {"check_syntax", "list_directory"}
    },
    ConversationPhase.VERIFICATION: {
        "essential": {"read_file", "get_problems"},
        "optional": {"run_command", "check_syntax"},
        "forbidden": {"write_file", "edit_file"}
    },
    ConversationPhase.COMPLETION: {
        "essential": {"read_file"},
        "optional": {"task", "question"},
        "forbidden": {"write_file", "edit_file", "run_command"}
    }
}


class AdaptiveToolSelector:
    """Dynamically select tools based on conversation context."""
    
    def __init__(self):
        self.phase_history: List[ConversationPhase] = []
        self.tool_usage_history: Dict[str, int] = {}  # Track tool usage frequency
        
    def analyze_conversation_phase(self, messages: List[Dict[str, any]], 
                                   user_message: str) -> ConversationPhase:
        """
        Analyze conversation history to determine current phase.
        
        Args:
            messages: Full conversation history
            user_message: Current user message
            
        Returns:
            ConversationPhase enum value
        """
        # Check last assistant message for context
        last_assistant_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "") or ""
                tool_calls = msg.get("tool_calls", [])
                
                # If last message had tool calls, check what tools were used
                if tool_calls:
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("function", {}).get("name", "")
                        if tool_name:
                            self.tool_usage_history[tool_name] = \
                                self.tool_usage_history.get(tool_name, 0) + 1
                
                if content:
                    last_assistant_msg = content.lower()
                    break
        
        # Analyze based on patterns
        msg_lower = user_message.lower()
        
        # DETECT PHASE FROM USER MESSAGE (priority order matters!)
        
        # Completion indicators
        if any(kw in msg_lower for kw in ["done", "complete", "finish", "that's all", "thank", "perfect"]):
            return ConversationPhase.COMPLETION
        
        # Modification indicators MUST be checked EARLY (before debugging)
        # "Refactor" and "docstring" are modification, NOT debugging
        if any(kw in msg_lower for kw in ["refactor", "improve", "optimize", "clean up", "restructure", "docstring", "add documentation"]):
            return ConversationPhase.MODIFICATION
        
        # Debugging indicators (only if no modification keywords found)
        if any(kw in msg_lower for kw in ["error", "bug", "crash", "fail", "wrong", "not working", "fix"]):
            return ConversationPhase.DEBUGGING
        
        # Creation indicators MUST be checked BEFORE execution
        # (e.g., "Create a python file" should be CREATION, not EXECUTION)
        if any(kw in msg_lower for kw in ["create", "make", "new file", "write file", "generate", "add file", "touch"]):
            if not any(kw in msg_lower for kw in ["modify", "change", "edit", "update"]):
                return ConversationPhase.CREATION
        
        # Execution indicators (check AFTER creation to avoid false positives)
        # Be more specific: look for command execution patterns
        if any(kw in msg_lower for kw in ["run ", "run the", "execute ", "start ", "build ", "test ", "deploy"]):
            return ConversationPhase.EXECUTION
        # Check for specific command patterns (but NOT in "create a python file" context)
        if any(kw in msg_lower for kw in ["python ", "npm ", "pip "]):
            # Only if it's about running, not creating
            if any(kw in msg_lower for kw in ["run", "execute", "test", "start"]):
                return ConversationPhase.EXECUTION
        
        # Planning indicators
        if any(kw in msg_lower for kw in ["plan", "strategy", "approach", "steps", "task list", "todo"]):
            return ConversationPhase.PLANNING
        
        # Additional modification indicators
        if any(kw in msg_lower for kw in ["edit", "change", "modify", "update", "replace", "remove"]):
            return ConversationPhase.MODIFICATION
        
        # Verification indicators
        if any(kw in msg_lower for kw in ["verify", "check", "test", "validate", "confirm", "looks right"]):
            return ConversationPhase.VERIFICATION
        
        # Exploration indicators
        if any(kw in msg_lower for kw in ["explore", "understand", "analyze", "show me", "what is", "where", "find", "list"]):
            return ConversationPhase.EXPLORATION
        
        # FALLBACK: Use last assistant message context
        if last_assistant_msg:
            if "created" in last_assistant_msg or "written" in last_assistant_msg:
                return ConversationPhase.CREATION
            if "running" in last_assistant_msg or "executing" in last_assistant_msg:
                return ConversationPhase.EXECUTION
            if "error" in last_assistant_msg or "failed" in last_assistant_msg:
                return ConversationPhase.DEBUGGING
        
        # Default to exploration if unclear
        return ConversationPhase.EXPLORATION
    
    def get_tools_for_phase(self, phase: ConversationPhase, 
                           all_tools: List[Dict[str, any]],
                           max_tools: int = 10) -> List[Dict[str, any]]:
        """
        Get filtered tools for a specific phase.
        
        Args:
            phase: Current conversation phase
            all_tools: All available tools (full schema)
            max_tools: Maximum number of tools to return
            
        Returns:
            Filtered list of tool schemas
        """
        rules = PHASE_TOOL_RULES.get(phase, {})
        essential = rules.get("essential", set())
        optional = rules.get("optional", set())
        forbidden = rules.get("forbidden", set())
        
        # Extract tool names from full schema
        tool_names = {t["function"]["name"] for t in all_tools}
        
        # Phase 1: Add all essential tools first
        selected_tools = []
        for tool in all_tools:
            name = tool["function"]["name"]
            if name in essential and name in tool_names:
                selected_tools.append(tool)
        
        # Phase 2: Add optional tools if under limit
        if len(selected_tools) < max_tools:
            for tool in all_tools:
                name = tool["function"]["name"]
                if name in optional and name in tool_names and len(selected_tools) < max_tools:
                    selected_tools.append(tool)
        
        # Phase 3: If still under limit, add frequently used tools from history
        if len(selected_tools) < max_tools and self.tool_usage_history:
            # Sort by usage frequency
            sorted_tools = sorted(
                self.tool_usage_history.items(),
                key=lambda x: x[1],
                reverse=True
            )
            for tool_name, _ in sorted_tools:
                if len(selected_tools) >= max_tools:
                    break
                # Find and add this tool if not already selected
                for tool in all_tools:
                    if tool["function"]["name"] == tool_name and tool not in selected_tools:
                        if tool_name not in forbidden:
                            selected_tools.append(tool)
                            break
        
        return selected_tools[:max_tools]
    
    def select_tools(self, messages: List[Dict[str, any]], 
                    user_message: str,
                    all_tools: List[Dict[str, any]],
                    max_tools: int = 10,
                    creation_mode: bool = False) -> List[Dict[str, any]]:
        """
        Main entry point: Select tools based on conversation context.
        
        Args:
            messages: Full conversation history
            user_message: Current user message
            all_tools: All available tools
            max_tools: Maximum tools to send to API
            creation_mode: If True, use stricter filtering
            
        Returns:
            Filtered list of tool schemas
        """
        # Step 1: Analyze conversation phase
        phase = self.analyze_conversation_phase(messages, user_message)
        
        # Store phase in history
        self.phase_history.append(phase)
        if len(self.phase_history) > 10:
            self.phase_history.pop(0)
        
        # Step 2: Get tools for this phase
        selected_tools = self.get_tools_for_phase(phase, all_tools, max_tools)
        
        # Step 3: Apply creation mode restrictions if enabled
        if creation_mode:
            creation_blocklist = {
                "list_directory", "check_syntax", "git_status", "git_diff",
                "find_function", "find_class", "lsp_find_references", 
                "lsp_go_to_definition", "verify_fix"
            }
            selected_tools = [
                t for t in selected_tools 
                if t["function"]["name"] not in creation_blocklist
            ]
        
        # Step 4: Log selection info
        tool_names = [t["function"]["name"] for t in selected_tools]
        
        return selected_tools
    
    def reset(self):
        """Reset selector state for new conversation."""
        self.phase_history = []
        self.tool_usage_history = {}


# Singleton instance
_selector_instance: Optional[AdaptiveToolSelector] = None

def get_adaptive_tool_selector() -> AdaptiveToolSelector:
    """Get singleton instance."""
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = AdaptiveToolSelector()
    return _selector_instance


def select_tools_adaptively(messages: List[Dict[str, any]], 
                           user_message: str,
                           all_tools: List[Dict[str, any]],
                           max_tools: int = 10,
                           creation_mode: bool = False) -> List[Dict[str, any]]:
    """Convenience function for adaptive tool selection."""
    selector = get_adaptive_tool_selector()
    return selector.select_tools(messages, user_message, all_tools, max_tools, creation_mode)
