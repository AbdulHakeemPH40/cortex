"""
Question Tool - User interaction and confirmation
Ask user questions and get responses.
Based on packages/opencode/src/tool/question.ts
"""

import time
from typing import Dict, Any

from src.ai.tools.base_tool import BaseTool, ToolResult, ToolParameter, success_result, error_result, pending_result


class QuestionTool(BaseTool):
    """
    User interaction tool.
    
    Features:
    - Ask user questions
    - Get text responses
    - Multiple choice support
    - Yes/No confirmation
    
    Use Cases:
    - Clarify requirements
    - Confirm decisions
    - Get user preferences
    """
    
    name = "question"
    description = "Ask the user a question and get their response. Use for clarification, confirmation, or gathering information."
    requires_confirmation = False  # This IS the confirmation tool
    is_safe = True
    
    parameters = [
        ToolParameter("question", "string", "Question to ask the user", required=True),
        ToolParameter("type", "string", "Question type: 'text', 'confirm', 'choice'", required=False, default="text"),
        ToolParameter("choices", "array", "List of choices (for 'choice' type)", required=False, default=None),
        ToolParameter("default", "string", "Default answer (optional)", required=False, default=None),
    ]
    
    def execute(self, params: Dict[str, Any]) -> ToolResult:
        start_time = time.time()
        
        try:
            question = params.get("question")
            if not question:
                return error_result("Missing required parameter: question")
            
            question_type = params.get("type", "text")
            choices = params.get("choices")
            default = params.get("default")
            
            # Instead of showing a dialog here (which blocks the background thread),
            # we return a 'pending' result. The AIAgent will see this and
            # trigger the UI to show a question card in the chat bubble.
            
            return pending_result(
                question=question,
                metadata={
                    'question': question,
                    'type': question_type,
                    'choices': choices,
                    'default': default,
                    'timestamp': time.time()
                }
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return error_result(f"Question failed: {str(e)}", duration_ms)
