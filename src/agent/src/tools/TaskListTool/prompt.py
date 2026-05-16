# ------------------------------------------------------------
# prompt.py
# Python conversion of TaskListTool/prompt.ts
# 
# Dynamic prompt generation for TaskListTool - AI agent task listing system.
# Includes conditional teammate workflow guidance based on feature flags.
# ------------------------------------------------------------

import os

try:
    from ...utils.agentSwarmsEnabled import isAgentSwarmsEnabled
except ImportError:
    # Fallback when agentSwarmsEnabled module doesn't exist yet
    def isAgentSwarmsEnabled() -> bool:
        """Check if agent swarms feature is enabled via environment variable."""
        return os.environ.get('CORTEX_ENABLE_AGENT_SWARMS', '').lower() in ('1', 'true', 'yes')


DESCRIPTION = 'List all tasks in the task list'


def getPrompt() -> str:
    """
    Generate dynamic prompt for TaskListTool.
    
    Includes conditional sections based on feature flags:
    - Teammate use case mention
    - Task ID description
    - Teammate workflow guidance
    
    Returns prompt string for AI agent instructions.
    """
    teammate_use_case = (
        '- Before assigning tasks to teammates, to see what\'s available\n'
        if isAgentSwarmsEnabled()
        else ''
    )
    
    # Same description regardless of feature flag
    id_description = '- **id**: Task identifier (use with TaskGet, TaskUpdate)'
    
    teammate_workflow = (
        """
## Teammate Workflow

When working as a teammate:
1. After completing your current task, call TaskList to find available work
2. Look for tasks with status 'pending', no owner, and empty blockedBy
3. **Prefer tasks in ID order** (lowest ID first) when multiple tasks are available, as earlier tasks often set up context for later ones
4. Claim an available task using TaskUpdate (set `owner` to your name), or wait for leader assignment
5. If blocked, focus on unblocking tasks or notify the team lead
"""
        if isAgentSwarmsEnabled()
        else ''
    )
    
    return f"""Use this tool to list all tasks in the task list.

## When to Use This Tool

- To see what tasks are available to work on (status: 'pending', no owner, not blocked)
- To check overall progress on the project
- To find tasks that are blocked and need dependencies resolved
{teammate_use_case}- After completing a task, to check for newly unblocked work or claim the next available task
- **Prefer working on tasks in ID order** (lowest ID first) when multiple tasks are available, as earlier tasks often set up context for later ones

## Output

Returns a summary of each task:
{id_description}
- **subject**: Brief description of the task
- **status**: 'pending', 'in_progress', or 'completed'
- **owner**: Agent ID if assigned, empty if available
- **blockedBy**: List of open task IDs that must be resolved first (tasks with blockedBy cannot be claimed until dependencies resolve)

Use TaskGet with a specific task ID to view full details including description and comments.
{teammate_workflow}"""
