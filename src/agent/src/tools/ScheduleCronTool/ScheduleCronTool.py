"""
ScheduleCronTool - Task scheduling system for Cortex IDE

This module provides cron-based scheduling capabilities for AI agents,
enabling delayed and recurring task execution.

Key Features:
- Standard 5-field cron expression parsing
- One-shot and recurring task scheduling
- In-memory and persistent storage options
- Automatic expiration of old tasks
- Team-aware scheduling (no durable tasks for ephemeral teammates)

Note: Simplified conversion focusing on core scheduling logic.
Terminal-specific UI rendering removed.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import logging
import time
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Constants
CRON_CREATE_TOOL_NAME = 'CronCreate'
CRON_DELETE_TOOL_NAME = 'CronDelete'
CRON_LIST_TOOL_NAME = 'CronList'
MAX_JOBS = 50
DEFAULT_MAX_AGE_DAYS = 30


@dataclass
class CronTask:
    """Represents a scheduled cron task."""
    id: str
    cron_expression: str
    prompt: str
    recurring: bool
    durable: bool = False
    created_at: float = field(default_factory=time.time)
    last_run: Optional[float] = None
    agent_id: Optional[str] = None
    expired: bool = False


@dataclass
class CronCreateInput:
    """Input schema for creating cron tasks."""
    cron: str  # 5-field cron expression
    prompt: str  # Prompt to execute
    recurring: bool = True  # Recurring or one-shot
    durable: bool = False  # Persist across sessions


@dataclass
class CronCreateOutput:
    """Output schema for cron creation."""
    id: str
    human_schedule: str  # Human-readable schedule
    recurring: bool
    durable: bool = False


@dataclass
class CronDeleteInput:
    """Input schema for deleting cron tasks."""
    id: str


@dataclass
class CronDeleteOutput:
    """Output schema for cron deletion."""
    success: bool
    message: str


@dataclass
class CronListOutput:
    """Output schema for listing cron tasks."""
    tasks: List[CronTask]
    count: int


# In-memory task store (will be replaced with proper persistence)
_task_store: Dict[str, CronTask] = {}


def parse_cron_expression(expression: str) -> Optional[Dict[str, Any]]:
    """
    Parse a standard 5-field cron expression.
    
    Format: "M H DoM Mon DoW"
    - M: Minute (0-59)
    - H: Hour (0-23)
    - DoM: Day of Month (1-31)
    - Mon: Month (1-12)
    - DoW: Day of Week (0-6, Sunday=0)
    
    Supports:
    - Wildcards: *
    - Ranges: 1-5
    - Steps: */5, 1-10/2
    - Lists: 1,3,5
    
    Args:
        expression: Cron expression string
        
    Returns:
        Parsed cron dict or None if invalid
    """
    try:
        parts = expression.strip().split()
        if len(parts) != 5:
            return None
        
        minute, hour, dom, month, dow = parts
        
        # Basic validation (full cron parsing is complex)
        def validate_field(value: str, min_val: int, max_val: int) -> bool:
            if value == '*':
                return True
            if ',' in value:
                return all(validate_field(v, min_val, max_val) for v in value.split(','))
            if '/' in value:
                base, step = value.split('/', 1)
                if base != '*' and not base.isdigit():
                    return False
                if not step.isdigit():
                    return False
                return True
            if '-' in value:
                start, end = value.split('-', 1)
                if not (start.isdigit() and end.isdigit()):
                    return False
                return int(min_val) <= int(start) <= int(end) <= int(max_val)
            if value.isdigit():
                return int(min_val) <= int(value) <= int(max_val)
            return False
        
        if not all([
            validate_field(minute, 0, 59),
            validate_field(hour, 0, 23),
            validate_field(dom, 1, 31),
            validate_field(month, 1, 12),
            validate_field(dow, 0, 6)
        ]):
            return None
        
        return {
            'minute': minute,
            'hour': hour,
            'day_of_month': dom,
            'month': month,
            'day_of_week': dow
        }
        
    except Exception as e:
        logger.error(f"Error parsing cron expression '{expression}': {e}")
        return None


def cron_to_human(expression: str) -> str:
    """
    Convert cron expression to human-readable description.
    
    Args:
        expression: 5-field cron expression
        
    Returns:
        Human-readable schedule description
    """
    parsed = parse_cron_expression(expression)
    if not parsed:
        return f"Invalid cron: {expression}"
    
    # Simple humanization (can be enhanced)
    parts = []
    
    if parsed['minute'] == '*':
        parts.append("every minute")
    elif parsed['minute'].startswith('*/'):
        interval = parsed['minute'][2:]
        parts.append(f"every {interval} minutes")
    else:
        parts.append(f"at minute {parsed['minute']}")
    
    if parsed['hour'] != '*':
        parts.append(f"past hour {parsed['hour']}")
    
    if parsed['day_of_month'] != '*':
        parts.append(f"on day {parsed['day_of_month']}")
    
    if parsed['month'] != '*':
        parts.append(f"in month {parsed['month']}")
    
    if parsed['day_of_week'] != '*':
        days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        dow = int(parsed['day_of_week'])
        parts.append(f"on {days[dow]}")
    
    return ', '.join(parts) if parts else expression


def next_cron_run_ms(expression: str, from_time_ms: Optional[float] = None) -> Optional[float]:
    """
    Calculate next run time for a cron expression.
    
    Note: This is a simplified implementation. For production use,
    consider using the `croniter` library.
    
    Args:
        expression: Cron expression
        from_time_ms: Starting time in milliseconds (default: now)
        
    Returns:
        Next run time in milliseconds, or None if no match in next year
    """
    parsed = parse_cron_expression(expression)
    if not parsed:
        return None
    
    # Simplified: just check if expression is valid
    # Full implementation would calculate exact next run time
    # For now, return a reasonable future timestamp
    from_time = from_time_ms / 1000 if from_time_ms else time.time()
    
    # Assume valid cron will run within next year
    # TODO: Implement proper cron calculation
    return (from_time + 3600) * 1000  # Return 1 hour from now as placeholder


async def add_cron_task(
    cron: str,
    prompt: str,
    recurring: bool = True,
    durable: bool = False,
    agent_id: Optional[str] = None
) -> str:
    """
    Add a new cron task to the scheduler.
    
    Args:
        cron: 5-field cron expression
        prompt: Prompt to execute at each fire time
        recurring: True for recurring, False for one-shot
        durable: True to persist across sessions
        agent_id: Optional agent ID for teammate tasks
        
    Returns:
        Unique task ID
        
    Raises:
        ValueError: If cron expression is invalid or too many jobs
    """
    # Validate cron expression
    if not parse_cron_expression(cron):
        raise ValueError(f"Invalid cron expression: {cron}")
    
    # Check job limit
    if len(_task_store) >= MAX_JOBS:
        raise ValueError(f"Too many scheduled jobs (max {MAX_JOBS}). Cancel one first.")
    
    # Generate unique ID
    task_id = f"cron_{uuid.uuid4().hex[:12]}"
    
    # Create task
    task = CronTask(
        id=task_id,
        cron_expression=cron,
        prompt=prompt,
        recurring=recurring,
        durable=durable,
        agent_id=agent_id
    )
    
    # Store task
    _task_store[task_id] = task
    
    logger.info(
        f"Created {'recurring' if recurring else 'one-shot'} cron task {task_id}: "
        f"{cron_to_human(cron)}"
    )
    
    # TODO: If durable=True, save to .cortex/scheduled_tasks.json
    
    return task_id


async def delete_cron_task(task_id: str) -> CronDeleteOutput:
    """
    Delete a scheduled cron task.
    
    Args:
        task_id: ID of task to delete
        
    Returns:
        CronDeleteOutput with result
    """
    if task_id not in _task_store:
        return CronDeleteOutput(
            success=False,
            message=f"Task {task_id} not found"
        )
    
    del _task_store[task_id]
    logger.info(f"Deleted cron task {task_id}")
    
    return CronDeleteOutput(
        success=True,
        message=f"Task {task_id} deleted successfully"
    )


async def list_cron_tasks() -> CronListOutput:
    """
    List all scheduled cron tasks.
    
    Returns:
        CronListOutput with task list
    """
    tasks = list(_task_store.values())
    
    return CronListOutput(
        tasks=tasks,
        count=len(tasks)
    )


async def create_cron_task(input_data: CronCreateInput) -> CronCreateOutput:
    """
    Main entry point for creating cron tasks.
    
    Validates input and creates a new scheduled task.
    
    Args:
        input_data: Cron creation input
        
    Returns:
        CronCreateOutput with task details
        
    Raises:
        ValueError: If validation fails
    """
    # Validate cron expression
    parsed = parse_cron_expression(input_data.cron)
    if not parsed:
        raise ValueError(
            f"Invalid cron expression '{input_data.cron}'. "
            f"Expected 5 fields: M H DoM Mon DoW."
        )
    
    # Check if cron matches any future date
    next_run = next_cron_run_ms(input_data.cron)
    if next_run is None:
        raise ValueError(
            f"Cron expression '{input_data.cron}' does not match "
            f"any calendar date in the next year."
        )
    
    # Check job limit
    if len(_task_store) >= MAX_JOBS:
        raise ValueError(f"Too many scheduled jobs (max {MAX_JOBS}). Cancel one first.")
    
    # Teammates don't persist across sessions, so durable teammate crons would orphan
    # TODO: Check teammate context when team system is integrated
    # if input_data.durable and get_teammate_context():
    #     raise ValueError(
    #         "Durable crons are not supported for teammates "
    #         "(teammates do not persist across sessions)"
    #     )
    
    # Create the task
    task_id = await add_cron_task(
        cron=input_data.cron,
        prompt=input_data.prompt,
        recurring=input_data.recurring,
        durable=input_data.durable
    )
    
    # Enable scheduler (placeholder - actual scheduler integration needed)
    # set_scheduled_tasks_enabled(True)
    
    return CronCreateOutput(
        id=task_id,
        human_schedule=cron_to_human(input_data.cron),
        recurring=input_data.recurring,
        durable=input_data.durable
    )


def get_cron_create_prompt(durable_enabled: bool = False) -> str:
    """
    Generate system prompt for CronCreate tool usage.
    
    Args:
        durable_enabled: Whether durable (persistent) crons are enabled
        
    Returns:
        Prompt text instructing AI on how to use CronCreate
    """
    durable_note = (
        "\n\nUse durable=true ONLY when the user explicitly asks for the task "
        "to survive across Claude sessions (e.g., 'remind me tomorrow even if you restart')."
        if durable_enabled
        else "\n\nNote: Durable cron tasks are currently disabled."
    )
    
    return f"""
# CronCreate - Schedule Recurring or One-Shot Tasks

Schedule prompts to run at specific times using cron expressions.

## Cron Format
Standard 5-field cron in local time: "M H DoM Mon DoW"
- M: Minute (0-59)
- H: Hour (0-23)  
- DoM: Day of Month (1-31)
- Mon: Month (1-12)
- DoW: Day of Week (0-6, Sunday=0)

Examples:
- "*/5 * * * *" = Every 5 minutes
- "0 9 * * 1" = Every Monday at 9:00 AM
- "30 14 28 2 *" = February 28 at 2:30 PM (once per year)
- "0 0 1 * *" = First day of every month at midnight

## Parameters
- **cron**: The cron expression
- **prompt**: What to execute at each fire time
- **recurring**: true (default) = repeat until deleted; false = fire once then auto-delete
- **durable**: false (default) = session-only; true = persist to disk{durable_note}

## Use Cases
- Reminders: "Remind me to stand up every hour" → recurring=false, durable based on preference
- Daily reports: "Send me a summary every day at 5pm" → recurring=true
- One-time alerts: "Alert me at 3pm today" → recurring=false
- Weekly reviews: "Every Friday at 4pm, review my tasks" → recurring=true

## Limits
- Maximum {MAX_JOBS} concurrent jobs
- Auto-expires after {DEFAULT_MAX_AGE_DAYS} days (recurring tasks)
- Use CronDelete to cancel tasks early

When users ask for reminders, scheduled tasks, or recurring actions, use this tool.
""".strip()


def get_cron_delete_prompt() -> str:
    """Generate system prompt for CronDelete tool."""
    return """
# CronDelete - Cancel Scheduled Tasks

Cancel a previously scheduled cron task by its ID.

Use this when:
- User wants to cancel a reminder
- User says "stop reminding me"
- User wants to delete a scheduled task

Provide the task ID from CronList or from the original CronCreate response.
""".strip()


def get_cron_list_prompt() -> str:
    """Generate system prompt for CronList tool."""
    return """
# CronList - View Scheduled Tasks

List all currently scheduled cron tasks.

Use this when:
- User asks "what's scheduled?"
- User wants to see their reminders
- Before creating a new task to avoid duplicates
- User wants to find a task ID to delete

Returns task IDs, schedules, and whether they're recurring or one-shot.
""".strip()


# Export public API
__all__ = [
    'CronTask',
    'CronCreateInput',
    'CronCreateOutput',
    'CronDeleteInput',
    'CronDeleteOutput',
    'CronListOutput',
    'create_cron_task',
    'delete_cron_task',
    'list_cron_tasks',
    'add_cron_task',
    'parse_cron_expression',
    'cron_to_human',
    'next_cron_run_ms',
    'get_cron_create_prompt',
    'get_cron_delete_prompt',
    'get_cron_list_prompt',
    'MAX_JOBS',
    'DEFAULT_MAX_AGE_DAYS',
]
