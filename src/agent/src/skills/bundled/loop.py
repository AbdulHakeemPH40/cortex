"""
Loop Skill for Cortex IDE

Converts the TypeScript loop.ts bundled skill to Python.
This skill enables scheduling recurring prompts on intervals
with AI-powered natural language parsing and cron expression generation.

Original: skills/bundled/loop.ts (93 lines)
"""

import os
import re
import math
from typing import Optional, TypedDict

# Defensive imports with fallbacks
try:
    from ...utils.errors import to_error as to_error_fn
except ImportError:
    def to_error_fn(e: Exception) -> Exception:
        return e

try:
    from ...tools.ScheduleCronTool.prompt import (
        CRON_CREATE_TOOL_NAME,
        CRON_DELETE_TOOL_NAME,
        DEFAULT_MAX_AGE_DAYS,
        is_kairos_cron_enabled,
    )
except ImportError:
    # Fallback constants if ScheduleCronTool not available
    CRON_CREATE_TOOL_NAME = 'CronCreate'
    CRON_DELETE_TOOL_NAME = 'CronDelete'
    DEFAULT_MAX_AGE_DAYS = 30
    
    def is_kairos_cron_enabled() -> bool:
        """Fallback: check environment variable for cron feature."""
        return (
            os.environ.get('KAIROS_CRON_ENABLED') == '1' or
            os.environ.get('FEATURE_AGENT_TRIGGERS') == '1'
        )


class ContentBlock(TypedDict):
    """Type definition for content block returned by skill."""
    type: str
    text: str


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_INTERVAL = '10m'

USAGE_MESSAGE = f"""Usage: /loop [interval] <prompt>

Run a prompt or slash command on a recurring interval.

Intervals: Ns, Nm, Nh, Nd (e.g. 5m, 30m, 2h, 1d). Minimum granularity is 1 minute.
If no interval is specified, defaults to {DEFAULT_INTERVAL}.

Examples:
  /loop 5m /babysit-prs
  /loop 30m check the deploy
  /loop 1h /standup 1
  /loop check the deploy          (defaults to {DEFAULT_INTERVAL})
  /loop check the deploy every 20m"""


# =============================================================================
# INTERVAL PARSING AND CRON GENERATION
# =============================================================================

def parse_interval(text: str) -> tuple[str, str]:
    """
    Parse the input text into interval and prompt.
    
    Uses 3-rule priority parsing:
    1. Leading token: if first token matches ^\\d+[smhd]$, that's the interval
    2. Trailing "every" clause: if ends with "every <N><unit>", extract interval
    3. Default: interval is DEFAULT_INTERVAL, entire input is prompt
    
    Args:
        text: User input string
        
    Returns:
        Tuple of (interval, prompt)
        
    Examples:
        >>> parse_interval("5m /babysit-prs")
        ('5m', '/babysit-prs')
        >>> parse_interval("check the deploy every 20m")
        ('20m', 'check the deploy')
        >>> parse_interval("check the deploy")
        ('10m', 'check the deploy')
        >>> parse_interval("check every PR")
        ('10m', 'check every PR')  # "every" not followed by time
    """
    # Rule 1: Leading token interval
    leading_match = re.match(r'^(\d+[smhd])\s+(.+)$', text, re.DOTALL)
    if leading_match:
        return leading_match.group(1), leading_match.group(2).strip()
    
    # Rule 2: Trailing "every" clause
    # Match "every <N><unit>" or "every <N> <unit-word>"
    every_match = re.search(
        r'\s+every\s+(\d+)\s*(s(?:econds?)?|m(?:inutes?)?|h(?:ours?)?|d(?:ays?)?)\s*$',
        text,
        re.IGNORECASE
    )
    if every_match:
        number = every_match.group(1)
        unit_word = every_match.group(2).lower()
        
        # Convert unit word to abbreviation
        unit_map = {
            's': 's', 'sec': 's', 'second': 's', 'seconds': 's',
            'm': 'm', 'min': 'm', 'minute': 'm', 'minutes': 'm',
            'h': 'h', 'hr': 'h', 'hour': 'h', 'hours': 'h',
            'd': 'd', 'day': 'd', 'days': 'd',
        }
        
        # Find the unit abbreviation
        unit = unit_map.get(unit_word[0], unit_word[0])
        
        interval = f"{number}{unit}"
        prompt = text[:every_match.start()].strip()
        return interval, prompt
    
    # Rule 3: Default interval
    return DEFAULT_INTERVAL, text


def interval_to_cron(interval: str) -> tuple[str, str]:
    """
    Convert an interval string to a cron expression.
    
    Supported suffixes:
    - s (seconds, rounded up to nearest minute, min 1)
    - m (minutes)
    - h (hours)
    - d (days)
    
    Args:
        interval: Interval string (e.g., "5m", "2h", "1d")
        
    Returns:
        Tuple of (cron_expression, human_readable_description)
        
    Raises:
        ValueError: If interval format is invalid
    """
    match = re.match(r'^(\d+)([smhd])$', interval)
    if not match:
        raise ValueError(f"Invalid interval format: {interval}. Expected format: Ns, Nm, Nh, or Nd")
    
    value = int(match.group(1))
    unit = match.group(2)
    
    if unit == 's':
        # Seconds: round up to nearest minute, min 1
        minutes = max(1, math.ceil(value / 60))
        if minutes >= 60:
            # If >= 60 minutes, treat as hours
            hours = minutes // 60
            if 24 % hours == 0:
                return f"0 */{hours} * * *", f"every {hours} hours"
            else:
                # Pick nearest clean interval
                rounded = 24 if hours > 12 else 12
                return f"0 */{rounded} * * *", f"every {rounded} hours (rounded from {value}s)"
        return f"*/{minutes} * * * *", f"every {minutes} minutes (rounded from {value}s)"
    
    elif unit == 'm':
        if value <= 59:
            # Check if it divides evenly into 60
            if 60 % value == 0:
                return f"*/{value} * * * *", f"every {value} minutes"
            else:
                # Pick nearest clean interval
                if value <= 10:
                    rounded = 10
                elif value <= 15:
                    rounded = 15
                elif value <= 20:
                    rounded = 20
                elif value <= 30:
                    rounded = 30
                else:
                    rounded = 60
                return f"*/{rounded} * * * *", f"every {rounded} minutes (rounded from {value}m)"
        else:
            # >= 60 minutes, convert to hours
            hours = value // 60
            if 24 % hours == 0:
                return f"0 */{hours} * * *", f"every {hours} hours"
            else:
                # Pick nearest clean interval
                if hours <= 4:
                    rounded = 4
                elif hours <= 6:
                    rounded = 6
                elif hours <= 8:
                    rounded = 8
                else:
                    rounded = 12
                return f"0 */{rounded} * * *", f"every {rounded} hours (rounded from {value}m)"
    
    elif unit == 'h':
        if value <= 23:
            if 24 % value == 0:
                return f"0 */{value} * * *", f"every {value} hours"
            else:
                # Pick nearest clean interval
                if value <= 4:
                    rounded = 4
                elif value <= 6:
                    rounded = 6
                elif value <= 8:
                    rounded = 8
                else:
                    rounded = 12
                return f"0 */{rounded} * * *", f"every {rounded} hours (rounded from {value}h)"
        else:
            # >= 24 hours, convert to days
            days = value // 24
            return f"0 0 */{days} * *", f"every {days} days at midnight"
    
    elif unit == 'd':
        return f"0 0 */{value} * *", f"every {value} days at midnight"
    
    else:
        raise ValueError(f"Invalid interval unit: {unit}")


# =============================================================================
# PROMPT GENERATION
# =============================================================================

def build_prompt(args: str) -> str:
    """
    Build the skill prompt with parsing instructions.
    
    Args:
        args: User input string (interval + prompt)
        
    Returns:
        Complete prompt string for the AI agent
    """
    return f"""# /loop — schedule a recurring prompt

Parse the input below into `[interval] <prompt…>` and schedule it with {CRON_CREATE_TOOL_NAME}.

## Parsing (in priority order)

1. **Leading token**: if the first whitespace-delimited token matches `^\\d+[smhd]$` (e.g. `5m`, `2h`), that's the interval; the rest is the prompt.
2. **Trailing "every" clause**: otherwise, if the input ends with `every <N><unit>` or `every <N> <unit-word>` (e.g. `every 20m`, `every 5 minutes`, `every 2 hours`), extract that as the interval and strip it from the prompt. Only match when what follows "every" is a time expression — `check every PR` has no interval.
3. **Default**: otherwise, interval is `{DEFAULT_INTERVAL}` and the entire input is the prompt.

If the resulting prompt is empty, show usage `/loop [interval] <prompt>` and stop — do not call {CRON_CREATE_TOOL_NAME}.

Examples:
- `5m /babysit-prs` → interval `5m`, prompt `/babysit-prs` (rule 1)
- `check the deploy every 20m` → interval `20m`, prompt `check the deploy` (rule 2)
- `run tests every 5 minutes` → interval `5m`, prompt `run tests` (rule 2)
- `check the deploy` → interval `{DEFAULT_INTERVAL}`, prompt `check the deploy` (rule 3)
- `check every PR` → interval `{DEFAULT_INTERVAL}`, prompt `check every PR` (rule 3 — "every" not followed by time)
- `5m` → empty prompt → show usage

## Interval → cron

Supported suffixes: `s` (seconds, rounded up to nearest minute, min 1), `m` (minutes), `h` (hours), `d` (days). Convert:

| Interval pattern      | Cron expression     | Notes                                    |
|-----------------------|---------------------|------------------------------------------|
| `Nm` where N ≤ 59   | `*/N * * * *`     | every N minutes                          |
| `Nm` where N ≥ 60   | `0 */H * * *`     | round to hours (H = N/60, must divide 24)|
| `Nh` where N ≤ 23   | `0 */N * * *`     | every N hours                            |
| `Nd`                | `0 0 */N * *`     | every N days at midnight local           |
| `Ns`                | treat as `ceil(N/60)m` | cron minimum granularity is 1 minute  |

**If the interval doesn't cleanly divide its unit** (e.g. `7m` → `*/7 * * * *` gives uneven gaps at :56→:00; `90m` → 1.5h which cron can't express), pick the nearest clean interval and tell the user what you rounded to before scheduling.

## Action

1. Call {CRON_CREATE_TOOL_NAME} with:
   - `cron`: the expression from the table above
   - `prompt`: the parsed prompt from above, verbatim (slash commands are passed through unchanged)
   - `recurring`: `true`
2. Briefly confirm: what's scheduled, the cron expression, the human-readable cadence, that recurring tasks auto-expire after {DEFAULT_MAX_AGE_DAYS} days, and that they can cancel sooner with {CRON_DELETE_TOOL_NAME} (include the job ID).
3. **Then immediately execute the parsed prompt now** — don't wait for the first cron fire. If it's a slash command, invoke it via the Skill tool; otherwise act on it directly.

## Input

{args}"""


# =============================================================================
# MAIN SKILL FUNCTION
# =============================================================================

async def get_prompt_for_command(args: Optional[str] = None) -> list[ContentBlock]:
    """
    Generate the prompt for the loop skill.
    
    If args is empty, returns usage message.
    Otherwise, returns the full parsing and scheduling prompt.
    
    Args:
        args: Optional user input (interval + prompt)
        
    Returns:
        List of content blocks with the generated prompt
    """
    try:
        if args is None:
            args = ''
        
        trimmed = args.strip()
        if not trimmed:
            return [{"type": "text", "text": USAGE_MESSAGE}]
        
        return [{"type": "text", "text": build_prompt(trimmed)}]
    
    except Exception as error:
        # Return minimal fallback prompt
        normalized_error = to_error_fn(error)
        return [{
            "type": "text",
            "text": f"# Loop Skill\n\nAn error occurred while generating the prompt: {str(normalized_error)}"
        }]


# =============================================================================
# REGISTRATION FUNCTION
# =============================================================================

LOOP_SKILL_DESCRIPTION = (
    "Run a prompt or slash command on a recurring interval "
    f"(e.g. /loop 5m /foo, defaults to {DEFAULT_INTERVAL})"
)

LOOP_SKILL_WHEN_TO_USE = (
    "When the user wants to set up a recurring task, poll for status, "
    "or run something repeatedly on an interval (e.g. \"check the deploy every 5 minutes\", "
    "\"keep running /babysit-prs\"). Do NOT invoke for one-off tasks."
)


def register_loop_skill(register_callback):
    """
    Register the loop bundled skill with Cortex IDE.
    
    Args:
        register_callback: Function to register the skill with the system
                          (maps to registerBundledSkill from TypeScript)
    """
    register_callback({
        "name": "loop",
        "description": LOOP_SKILL_DESCRIPTION,
        "when_to_use": LOOP_SKILL_WHEN_TO_USE,
        "argument_hint": "[interval] <prompt>",
        "user_invocable": True,
        "is_enabled": is_kairos_cron_enabled,
        "get_prompt_for_command": get_prompt_for_command,
    })
