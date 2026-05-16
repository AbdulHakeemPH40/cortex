# ------------------------------------------------------------
# prompt.py
# Python conversion of TaskStopTool/prompt.ts
# 
# Prompt constants for TaskStopTool - AI agent task termination system.
# ------------------------------------------------------------

TASK_STOP_TOOL_NAME = 'TaskStop'

DESCRIPTION = """
- Stops a running background task by its ID
- Takes a task_id parameter identifying the task to stop
- Returns a success or failure status
- Use this tool when you need to terminate a long-running task
"""
