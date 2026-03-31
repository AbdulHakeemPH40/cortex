"""
INTELLIGENT TOOL SELECTOR - Industry Standard Agentic Filtering

Solves:
1. Tool bloat (38 tools → 8-12 relevant tools)
2. Unnecessary tool calls
3. Task paralysis from too many options
4. Infinite loops from wrong tool selection
"""

import re
from typing import Set, List, Dict, Optional
from enum import Enum

class TaskType(Enum):
    """Task classification for intelligent tool filtering."""
    CREATE_FILE = "create_file"           # write_file only
    EDIT_CODE = "edit_code"               # edit_file, read_file, get_file_outline
    RUN_COMMAND = "run_command"           # run_command, bash only (NO verification)
    READ_ANALYZE = "read_analyze"         # read_file, search_code, grep
    DEBUG_ERROR = "debug_error"           # read_file, find_by_error, grep, run_command
    NAVIGATE = "navigate"                 # list_directory, find_by_symbol
    REFACTOR = "refactor"                 # read_file, edit_file, find_usages, get_file_outline

# TOOL RESTRICTION RULES - PREVENTS UNNECESSARY TOOL CALLS
TOOL_RESTRICTIONS = {
    TaskType.CREATE_FILE: {
        "allowed": {"write_file", "inject_after"},
        "forbidden": {"list_directory", "check_syntax", "read_file", "run_command"}
    },
    TaskType.EDIT_CODE: {
        "allowed": {"read_file", "edit_file", "smart_edit", "get_file_outline", "find_usages"},
        "forbidden": {"list_directory", "check_syntax"}  # Read first, then decide
    },
    TaskType.RUN_COMMAND: {
        "allowed": {"run_command", "bash"},
        "forbidden": {"check_syntax", "list_directory", "read_file"}  # NO verification!
    },
    TaskType.READ_ANALYZE: {
        "allowed": {"read_file", "search_code", "grep", "find_symbol", "get_file_outline"},
        "forbidden": {"write_file", "edit_file", "run_command"}
    },
    TaskType.DEBUG_ERROR: {
        "allowed": {"read_file", "grep", "run_command", "find_usages"},
        "forbidden": {"check_syntax"}  # Check AFTER reading
    },
    TaskType.NAVIGATE: {
        "allowed": {"list_directory", "find_function", "find_class", "find_symbol"},
        "forbidden": {"write_file", "edit_file", "run_command"}
    },
    TaskType.REFACTOR: {
        "allowed": {"read_file", "edit_file", "find_usages", "get_file_outline", "search_code"},
        "forbidden": {"list_directory", "check_syntax"}
    }
}

class ToolSelector:
    """Select relevant tools based on task classification."""
    
    @staticmethod
    def classify_task(user_message: str) -> TaskType:
        """
        Classify user message to determine which tools are needed.
        This prevents exposing all 38 tools at once.
        """
        msg_lower = user_message.lower()
        
        # CREATE_FILE: "create", "make", "new file", "write", "generate"
        if any(kw in msg_lower for kw in ["create", "make", "new file", "write file", "generate", "add file", "touch"]):
            # But NOT if they're also asking to read/modify existing
            if not any(kw in msg_lower for kw in ["modify", "change", "edit", "update", "fix"]):
                return TaskType.CREATE_FILE
        
        # EDIT_CODE: "edit", "change", "fix", "modify", "refactor", "replace"
        if any(kw in msg_lower for kw in ["edit", "change", "fix", "modify", "replace", "remove", "delete line", "swap"]):
            if "error" in msg_lower or "bug" in msg_lower:
                return TaskType.DEBUG_ERROR
            return TaskType.EDIT_CODE
        
        # RUN_COMMAND: "run", "execute", "test", "start", "build", "deploy"
        if any(kw in msg_lower for kw in ["run", "execute", "test", "start", "build", "deploy", "python", "npm", "pip"]):
            return TaskType.RUN_COMMAND
        
        # DEBUG_ERROR: "error", "crash", "bug", "fail", "exception"
        if any(kw in msg_lower for kw in ["error", "crash", "bug", "fail", "exception", "debug", "wrong", "not working"]):
            return TaskType.DEBUG_ERROR
        
        # NAVIGATE: "find", "where", "show me", "what files", "list"
        if any(kw in msg_lower for kw in ["find", "where", "show me", "what files", "list", "structure", "navigate"]):
            return TaskType.NAVIGATE
        
        # REFACTOR: "refactor", "improve", "clean up", "optimize"
        if any(kw in msg_lower for kw in ["refactor", "improve", "clean", "optimize", "structure", "organize"]):
            return TaskType.REFACTOR
        
        # READ_ANALYZE: Default - "analyze", "read", "understand", "what is", "how does"
        return TaskType.READ_ANALYZE
    
    @staticmethod
    def get_allowed_tools(task_type: TaskType) -> Set[str]:
        """
        Get set of allowed tools for a specific task type.
        This is the CORE filtering mechanism that prevents AI paralysis.
        
        Returns: Set of allowed tool names (e.g., {"write_file", "edit_file"})
        """
        restrictions = TOOL_RESTRICTIONS.get(task_type, {})
        return restrictions.get("allowed", set())
    
    @staticmethod
    def is_tool_allowed(tool_name: str, task_type: TaskType) -> bool:
        """Check if a specific tool is allowed for a task type."""
        allowed = ToolSelector.get_allowed_tools(task_type)
        forbidden = TOOL_RESTRICTIONS.get(task_type, {}).get("forbidden", set())
        
        if tool_name in forbidden:
            return False
        if allowed and tool_name not in allowed:
            return False
        return True
    
    @staticmethod
    def filter_tools(all_tools: List[str], task_type: TaskType) -> List[str]:
        """
        Filter all available tools to only the relevant ones for this task.
        
        Args:
            all_tools: List of ALL available tool names
            task_type: Task classification
            
        Returns:
            Filtered list of tools (8-12 max) relevant to the task
        """
        allowed = ToolSelector.get_allowed_tools(task_type)
        
        if allowed:
            return [t for t in all_tools if t in allowed]
        else:
            # Fallback: return minimal tool set (reading only)
            return [t for t in all_tools if t in {"read_file", "list_directory", "search_code"}]
    
    @staticmethod
    def get_system_prompt_for_task(task_type: TaskType) -> str:
        """
        Get task-specific system prompt that ENCOURAGES the right tools.
        This replaces the contradictory 6,500-char prompt.
        
        Industry Standard: Be prescriptive about which tools to use
        """
        reminders = {
            TaskType.CREATE_FILE: (
                "## TASK: CREATE FUNCTION\n"
                "✅ USE: write_file\n"
                "❌ DON'T USE: list_directory, check_syntax, read_file\n"
                "RULE: Write the file. Success = task complete."
            ),
            TaskType.EDIT_CODE: (
                "## TASK: MODIFY EXISTING CODE\n"
                "✅ STEPS: 1) read_file → 2) understand → 3) edit_file\n"
                "❌ DON'T: Use check_syntax or verify (trust edit success)\n"
                "RULE: Edit once, correctly. No verification needed."
            ),
            TaskType.RUN_COMMAND: (
                "## TASK: EXECUTE CODE\n"
                "✅ USE: run_command (PowerShell on Windows)\n"
                "❌ DON'T: Use check_syntax, list_directory, or verify after\n"
                "RULE: Run it. Capture output. Done."
            ),
            TaskType.DEBUG_ERROR: (
                "## TASK: FIX ERROR\n"
                "✅ STEPS: 1) read_file with error context → 2) grep for pattern → 3) edit_file\n"
                "❌ DON'T: Re-verify or re-run unless new error\n"
                "RULE: Change something. Test once. Move on."
            ),
            TaskType.NAVIGATE: (
                "## TASK: EXPLORE PROJECT\n"
                "✅ USE: list_directory, find_symbol, find_function\n"
                "❌ DON'T: Modify files (read-only task)\n"
                "RULE: Report what you found. Ask user next step."
            ),
            TaskType.REFACTOR: (
                "## TASK: IMPROVE CODE\n"
                "✅ STEPS: 1) read_file → 2) find_usages → 3) edit_file with improvements\n"
                "❌ DON'T: Check syntax or re-read after editing\n"
                "RULE: Single comprehensive edit. Done."
            ),
            TaskType.READ_ANALYZE: (
                "## TASK: UNDERSTAND CODE\n"
                "✅ USE: read_file, search_code, grep\n"
                "❌ DON'T: Modify or execute\n"
                "RULE: Read. Analyze. Explain findings."
            )
        }
        
        return reminders.get(task_type, "")

def get_task_type(user_message: str) -> TaskType:
    """Convenience function."""
    return ToolSelector.classify_task(user_message)
