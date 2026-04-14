# ------------------------------------------------------------
# tokenBudget.py (utils)
# Python conversion of utils/tokenBudget.ts (lines 1-74)
#
# Token budget string parsing utilities:
# - Parses shorthand notation (+500k, +2.5m, +1b)
# - Parses verbose notation (use 2M tokens, spend 500k tokens)
# - Finds positions of budget mentions in text
# - Generates budget continuation nudge messages
# ------------------------------------------------------------

import re
from typing import List, Optional


# Shorthand (+500k) anchored to start/end to avoid false positives in natural language.
# Verbose (use/spend 2M tokens) matches anywhere.
# Capture leading whitespace instead of lookbehind — avoids regex engine issues.
SHORTHAND_START_RE = re.compile(r"^\s*\+(\d+(?:\.\d+)?)\s*([kmb])\b", re.IGNORECASE)
SHORTHAND_END_RE = re.compile(r"\s\+(\d+(?:\.\d+)?)\s*([kmb])\s*[.!?]?\s*$", re.IGNORECASE)
VERBOSE_RE = re.compile(r"\b(?:use|spend)\s+(\d+(?:\.\d+)?)\s*([kmb])\s*tokens?\b", re.IGNORECASE)
VERBOSE_RE_G = re.compile(VERBOSE_RE.pattern, re.IGNORECASE)

MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
}


def parse_budget_match(value: str, suffix: str) -> float:
    """Parse a numeric value and multiplier suffix into a total number."""
    return float(value) * MULTIPLIERS[suffix.lower()]


def parse_token_budget(text: str) -> Optional[float]:
    """
    Extract a token budget number from text.

    Supports:
    - Start shorthand: "+500k", "+2.5m", "+1b"
    - End shorthand: "... +500k." (with punctuation)
    - Verbose: "use 2M tokens", "spend 500k tokens"

    Returns the budget in tokens, or None if not found.
    """
    # Start shorthand: +500k at beginning
    start_match = SHORTHAND_START_RE.match(text)
    if start_match:
        return parse_budget_match(start_match.group(1), start_match.group(2))

    # End shorthand: +500k at end
    end_match = SHORTHAND_END_RE.search(text)
    if end_match:
        return parse_budget_match(end_match.group(1), end_match.group(2))

    # Verbose: use/spend X tokens
    verbose_match = VERBOSE_RE.search(text)
    if verbose_match:
        return parse_budget_match(verbose_match.group(1), verbose_match.group(2))

    return None


def find_token_budget_positions(
    text: str,
) -> List[dict]:
    """
    Find character positions of all budget mentions in text.

    Returns a list of {start, end} position dicts for each match.
    Handles deduplication when shorthand start/end overlap.
    """
    positions: List[dict] = []

    # Start shorthand
    start_match = SHORTHAND_START_RE.match(text)
    if start_match:
        # Offset to skip leading whitespace in the match
        offset = (
            start_match.start() +
            len(start_match.group(0)) -
            len(start_match.group(0).lstrip())
        )
        positions.append({
            "start": offset,
            "end": start_match.start() + len(start_match.group(0)),
        })

    # End shorthand
    end_match = SHORTHAND_END_RE.search(text)
    if end_match:
        # +1: regex includes leading whitespace, skip it
        end_start = end_match.start() + 1
        # Avoid double-counting when input is just "+500k"
        already_covered = any(
            p["start"] <= end_start < p["end"]
            for p in positions
        )
        if not already_covered:
            positions.append({
                "start": end_start,
                "end": end_match.start() + len(end_match.group(0)),
            })

    # Verbose matches (global)
    for match in VERBOSE_RE_G.finditer(text):
        positions.append({
            "start": match.start(),
            "end": match.start() + len(match.group(0)),
        })

    return positions


def get_budget_continuation_message(
    pct: int,
    turn_tokens: float,
    budget: float,
) -> str:
    """
    Generate a nudge message when approaching token budget limit.

    Tells the model to continue working rather than summarizing.
    """
    def fmt(n: float) -> str:
        return f"{n:,.0f}"

    return (
        f"Stopped at ${pct}% of token target "
        f"({fmt(turn_tokens)} / ${fmt(budget)}). "
        "Keep working \u2014 do not summarize."
    )


__all__ = [
    "parse_token_budget",
    "find_token_budget_positions",
    "get_budget_continuation_message",
]
