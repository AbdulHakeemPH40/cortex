"""
memoryAge - Memory staleness detection and age formatting.

Calculates memory age in days and provides human-readable staleness warnings
to prevent the AI from treating old memories as current facts.
"""

import time


def memoryAgeDays(mtime_ms: float) -> int:
    """
    Days elapsed since mtime. Floor-rounded — 0 for today, 1 for
    yesterday, 2+ for older. Negative inputs (future mtime, clock skew)
    clamp to 0.
    """
    return max(0, int((time.time() * 1000 - mtime_ms) / 86_400_000))


def memoryAge(mtime_ms: float) -> str:
    """
    Human-readable age string. Models are poor at date arithmetic —
    a raw ISO timestamp doesn't trigger staleness reasoning the way
    "47 days ago" does.
    """
    d = memoryAgeDays(mtime_ms)
    if d == 0:
        return 'today'
    if d == 1:
        return 'yesterday'
    return f'{d} days ago'


def memoryFreshnessText(mtime_ms: float) -> str:
    """
    Plain-text staleness caveat for memories >1 day old. Returns ''
    for fresh (today/yesterday) memories — warning there is noise.
    
    Use this when the consumer already provides its own wrapping
    (e.g. messages.py relevant_memories → wrapMessagesInSystemReminder).
    
    Motivated by user reports of stale code-state memories (file:line
    citations to code that has since changed) being asserted as fact —
    the citation makes the stale claim sound more authoritative, not less.
    """
    d = memoryAgeDays(mtime_ms)
    if d <= 1:
        return ''
    
    return (
        f'This memory is {d} days old. '
        'Memories are point-in-time observations, not live state — '
        'claims about code behavior or file:line citations may be outdated. '
        'Verify against current code before asserting as fact.'
    )


def memoryFreshnessNote(mtime_ms: float) -> str:
    """
    Per-memory staleness note wrapped in <system-reminder> tags.
    Returns '' for memories ≤ 1 day old. Use this for callers that
    don't add their own system-reminder wrapper (e.g. FileReadTool output).
    """
    text = memoryFreshnessText(mtime_ms)
    if not text:
        return ''
    return f'<system-reminder>{text}</system-reminder>\n'
