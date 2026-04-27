# ------------------------------------------------------------
# prompt.py
# Python conversion of ScheduleCronTool/prompt.ts
# 
# Cron scheduling system prompts and feature flags for AI Agent IDE.
# Enables AI to schedule recurring and one-shot tasks.
# ------------------------------------------------------------

import os
from typing import Optional

# Import dependencies
try:
    from ...services.analytics.growthbook import getFeatureValue_CACHED_WITH_REFRESH
except ImportError:
    def getFeatureValue_CACHED_WITH_REFRESH(key, default, refresh_ms):
        return default

try:
    from ...utils.envUtils import isEnvTruthy
except ImportError:
    def isEnvTruthy(value):
        if value is None:
            return False
        return value.strip().lower() in ('1', 'true', 'yes', 'on')

try:
    from ...utils.cronTasks import DEFAULT_CRON_JITTER_CONFIG
    DEFAULT_MAX_AGE_DAYS = DEFAULT_CRON_JITTER_CONFIG['recurringMaxAgeMs'] / (24 * 60 * 60 * 1000)
except ImportError:
    DEFAULT_MAX_AGE_DAYS = 30  # Default fallback

KAIROS_CRON_REFRESH_MS = 5 * 60 * 1000  # 5 minutes

# Tool names
CRON_CREATE_TOOL_NAME = 'CronCreate'
CRON_DELETE_TOOL_NAME = 'CronDelete'
CRON_LIST_TOOL_NAME = 'CronList'


def isKairosCronEnabled() -> bool:
    """
    Unified gate for the cron scheduling system.
    
    Combines the build-time feature flag with the runtime GrowthBook gate
    on a 5-minute refresh window.
    
    AGENT_TRIGGERS is independently shippable from KAIROS.
    The default is `true` — /loop is GA.
    
    `CLAUDE_CODE_DISABLE_CRON` is a local override that wins over GB.
    
    Returns:
        True if cron scheduling is enabled
    """
    # Check build-time feature flag (simulate with env var)
    agent_triggers = os.environ.get('FEATURE_AGENT_TRIGGERS', '1') == '1'
    
    if not agent_triggers:
        return False
    
    # Check local override
    if isEnvTruthy(os.environ.get('CLAUDE_CODE_DISABLE_CRON')):
        return False
    
    # Check GrowthBook feature flag
    return getFeatureValue_CACHED_WITH_REFRESH(
        'tengu_kairos_cron',
        True,
        KAIROS_CRON_REFRESH_MS,
    )


def isDurableCronEnabled() -> bool:
    """
    Kill switch for disk-persistent (durable) cron tasks.
    
    Narrower than isKairosCronEnabled — flipping this off forces 
    `durable: false` at the call() site, leaving session-only cron 
    (in-memory, GA) untouched.
    
    Defaults to `true` so Bedrock/Vertex/Foundry and DISABLE_TELEMETRY 
    users get durable cron.
    
    Returns:
        True if durable cron persistence is enabled
    """
    return getFeatureValue_CACHED_WITH_REFRESH(
        'tengu_kairos_cron_durable',
        True,
        KAIROS_CRON_REFRESH_MS,
    )


def buildCronCreateDescription(durable_enabled: bool) -> str:
    """Build the description for CronCreate tool."""
    if durable_enabled:
        return (
            'Schedule a prompt to run at a future time — either recurring on a '
            'cron schedule, or once at a specific time. Pass durable: true to '
            'persist to .cortex/scheduled_tasks.json; otherwise session-only.'
        )
    else:
        return (
            'Schedule a prompt to run at a future time within this Claude session '
            '— either recurring on a cron schedule, or once at a specific time.'
        )


def buildCronCreatePrompt(durable_enabled: bool) -> str:
    """Build the prompt for CronCreate tool."""
    if durable_enabled:
        durability_section = """## Durability

By default (durable: false) the job lives only in this Claude session — nothing is written to disk, and the job is gone when Claude exits. Pass durable: true to write to .cortex/scheduled_tasks.json so the job survives restarts. Only use durable: true when the user explicitly asks for the task to persist ("keep doing this every day", "set this up permanently"). Most "remind me in 5 minutes" / "check back in an hour" requests should stay session-only."""
        durable_runtime_note = (
            'Durable jobs persist to .cortex/scheduled_tasks.json and survive session '
            'restarts — on next launch they resume automatically. One-shot durable tasks '
            'that were missed while the REPL was closed are surfaced for catch-up. '
            'Session-only jobs die with the process. '
        )
    else:
        durability_section = """## Session-only

Jobs live only in this Claude session — nothing is written to disk, and the job is gone when Claude exits."""
        durable_runtime_note = ''

    return f"""Schedule a prompt to be enqueued at a future time. Use for both recurring schedules and one-shot reminders.

Uses standard 5-field cron in the user's local timezone: minute hour day-of-month month day-of-week. "0 9 * * *" means 9am local — no timezone conversion needed.

## One-shot tasks (recurring: false)

For "remind me at X" or "at <time>, do Y" requests — fire once then auto-delete.
Pin minute/hour/day-of-month/month to specific values:
  "remind me at 2:30pm today to check the deploy" → cron: "30 14 <today_dom> <today_month> *", recurring: false
  "tomorrow morning, run the smoke test" → cron: "57 8 <tomorrow_dom> <tomorrow_month> *", recurring: false

## Recurring jobs (recurring: true, the default)

For "every N minutes" / "every hour" / "weekdays at 9am" requests:
  "*/5 * * * *" (every 5 min), "0 * * * *" (hourly), "0 9 * * 1-5" (weekdays at 9am local)

## Avoid the :00 and :30 minute marks when the task allows it

Every user who asks for "9am" gets `0 9`, and every user who asks for "hourly" gets `0 *` — which means requests from across the planet land on the API at the same instant. When the user's request is approximate, pick a minute that is NOT 0 or 30:
  "every morning around 9" → "57 8 * * *" or "3 9 * * *" (not "0 9 * * *")
  "hourly" → "7 * * * *" (not "0 * * * *")
  "in an hour or so, remind me to..." → pick whatever minute you land on, don't round

Only use minute 0 or 30 when the user names that exact time and clearly means it ("at 9:00 sharp", "at half past", coordinating with a meeting). When in doubt, nudge a few minutes early or late — the user will not notice, and the fleet will.

{durability_section}

## Runtime behavior

Jobs only fire while the REPL is idle (not mid-query). {durable_runtime_note}The scheduler adds a small deterministic jitter on top of whatever you pick: recurring tasks fire up to 10% of their period late (max 15 min); one-shot tasks landing on :00 or :30 fire up to 90 s early. Picking an off-minute is still the bigger lever.

Recurring tasks auto-expire after {DEFAULT_MAX_AGE_DAYS} days — they fire one final time, then are deleted. This bounds session lifetime. Tell the user about the {DEFAULT_MAX_AGE_DAYS}-day limit when scheduling recurring jobs.

Returns a job ID you can pass to {CRON_DELETE_TOOL_NAME}."""


# CronDelete descriptions
CRON_DELETE_DESCRIPTION = 'Cancel a scheduled cron job by ID'


def buildCronDeletePrompt(durable_enabled: bool) -> str:
    """Build the prompt for CronDelete tool."""
    if durable_enabled:
        return (
            f'Cancel a cron job previously scheduled with {CRON_CREATE_TOOL_NAME}. '
            'Removes it from .cortex/scheduled_tasks.json (durable jobs) or the '
            'in-memory session store (session-only jobs).'
        )
    else:
        return (
            f'Cancel a cron job previously scheduled with {CRON_CREATE_TOOL_NAME}. '
            'Removes it from the in-memory session store.'
        )


# CronList descriptions
CRON_LIST_DESCRIPTION = 'List scheduled cron jobs'


def buildCronListPrompt(durable_enabled: bool) -> str:
    """Build the prompt for CronList tool."""
    if durable_enabled:
        return (
            f'List all cron jobs scheduled via {CRON_CREATE_TOOL_NAME}, both durable '
            '(.cortex/scheduled_tasks.json) and session-only.'
        )
    else:
        return (
            f'List all cron jobs scheduled via {CRON_CREATE_TOOL_NAME} in this session.'
        )
