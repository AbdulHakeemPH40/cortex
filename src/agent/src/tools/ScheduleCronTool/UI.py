# ------------------------------------------------------------
# UI.py
# Python conversion of ScheduleCronTool/UI.ts
# 
# UI rendering functions for Cron scheduling tools.
# ------------------------------------------------------------

from typing import Any, Dict


def renderCreateToolUseMessage(input_data: Dict[str, Any]) -> str:
    """Renders a tool use message for CronCreate."""
    cron = input_data.get('cron', 'unknown')
    recurring = input_data.get('recurring', True)
    durable = input_data.get('durable', False)
    
    schedule_type = 'recurring' if recurring else 'one-shot'
    persistence = 'durable' if durable else 'session-only'
    
    return f"Scheduling {schedule_type} task ({persistence}): {cron}"


def renderCreateResultMessage(output: Any) -> str:
    """Renders a tool result message for CronCreate."""
    # Handle both dict and dataclass
    if hasattr(output, 'id'):
        job_id = output.id
        human_schedule = output.humanSchedule
        recurring = output.recurring
    else:
        job_id = output.get('id', 'unknown')
        human_schedule = output.get('humanSchedule', 'unknown')
        recurring = output.get('recurring', True)
    
    schedule_type = 'recurring' if recurring else 'one-shot'
    return f"Created {schedule_type} job {job_id} ({human_schedule})"


def renderDeleteToolUseMessage(input_data: Dict[str, Any]) -> str:
    """Renders a tool use message for CronDelete."""
    job_id = input_data.get('id', 'unknown')
    return f"Canceling scheduled job: {job_id}"


def renderDeleteResultMessage(output: Any) -> str:
    """Renders a tool result message for CronDelete."""
    # Handle both dict and dataclass
    if hasattr(output, 'id'):
        job_id = output.id
    else:
        job_id = output.get('id', 'unknown')
    
    return f"Cancelled job {job_id}"


def renderListToolUseMessage(input_data: Dict[str, Any]) -> str:
    """Renders a tool use message for CronList."""
    return "Listing scheduled cron jobs"


def renderListResultMessage(output: Any) -> str:
    """Renders a tool result message for CronList."""
    # Handle both dict and dataclass
    if hasattr(output, 'jobs'):
        jobs = output.jobs
    else:
        jobs = output.get('jobs', [])
    
    count = len(jobs)
    if count == 0:
        return "No scheduled jobs"
    elif count == 1:
        return "1 scheduled job"
    else:
        return f"{count} scheduled jobs"
