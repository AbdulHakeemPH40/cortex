# ------------------------------------------------------------
# tokenBudget.py (query)
# Python conversion of query/tokenBudget.ts (lines 1-94)
#
# Token budget enforcement for task budgets:
# - BudgetTracker state machine
# - checkTokenBudget() decision logic
# - Diminishing returns detection
# - Continuation vs stop decisions
# ------------------------------------------------------------

import time
from dataclasses import dataclass
from typing import Literal, Optional, Union

try:
    from ...utils.tokenBudget import get_budget_continuation_message
except ImportError:
    def get_budget_continuation_message(pct: int, turn_tokens: float, budget: float) -> str:
        return f"Stopped at {pct}% of token target ({turn_tokens} / {budget}). Keep working."


COMPLETION_THRESHOLD = 0.9
DIMINISHING_THRESHOLD = 500


@dataclass
class BudgetTracker:
    """
    Tracks token usage across conversation turns to enforce task budgets.

    Attributes:
        continuationCount: Number of times we continued despite being under budget.
        lastDeltaTokens: Tokens added since the last budget check.
        lastGlobalTurnTokens: Token count at the last check.
        startedAt: Timestamp when tracking began (ms since epoch).
    """
    continuation_count: int = 0
    last_delta_tokens: int = 0
    last_global_turn_tokens: int = 0
    started_at: float = 0.0

    def __post_init__(self):
        if self.started_at == 0.0:
            object.__setattr__(self, "started_at", time.time() * 1000)


def create_budget_tracker() -> BudgetTracker:
    """Factory: create a fresh BudgetTracker with default values."""
    return BudgetTracker(
        continuation_count=0,
        last_delta_tokens=0,
        last_global_turn_tokens=0,
        started_at=time.time() * 1000,
    )


# ---- Decision result types ----

@dataclass
class ContinueDecision:
    """Budget not exhausted — continue the task."""
    action: Literal["continue"]
    nudge_message: str
    continuation_count: int
    pct: int
    turn_tokens: int
    budget: float


@dataclass
class StopDecision:
    """Budget exhausted or budget not set — stop the task."""
    action: Literal["stop"]
    completion_event: Optional[dict] = None


# completion_event shape (when not None):
# {
#   continuationCount: int
#   pct: int
#   turnTokens: int
#   budget: float
#   diminishingReturns: bool
#   durationMs: number
# }


TokenBudgetDecision = Union[ContinueDecision, StopDecision]


def check_token_budget(
    tracker: BudgetTracker,
    agent_id: Optional[str],
    budget: Optional[float],
    global_turn_tokens: int,
) -> TokenBudgetDecision:
    """
    Check whether to continue or stop based on token budget.

    Decision logic:
    1. If agent task (agentId set) or no budget → stop
    2. If under 90% of budget and not diminishing → continue
    3. If diminishing returns (slow progress) OR had continuations → stop
    4. Otherwise → stop (no completion event)

    Args:
        tracker: BudgetTracker state from previous checks
        agent_id: Set if this is a sub-agent task (skip budget)
        budget: Task budget in tokens (None = no budget)
        global_turn_tokens: Current turn's token count

    Returns:
        ContinueDecision with nudge message, or StopDecision
    """
    # Agents have their own budget enforcement; skip here
    if agent_id or budget is None or budget <= 0:
        return StopDecision(action="stop", completion_event=None)

    turn_tokens = global_turn_tokens
    pct = int(round((turn_tokens / budget) * 100))
    delta_since_last_check = global_turn_tokens - tracker.last_global_turn_tokens

    # Diminishing returns: slow progress over multiple turns
    is_diminishing = (
        tracker.continuation_count >= 3 and
        delta_since_last_check < DIMINISHING_THRESHOLD and
        tracker.last_delta_tokens < DIMINISHING_THRESHOLD
    )

    if not is_diminishing and turn_tokens < budget * COMPLETION_THRESHOLD:
        tracker.continuation_count += 1
        tracker.last_delta_tokens = delta_since_last_check
        tracker.last_global_turn_tokens = global_turn_tokens
        return ContinueDecision(
            action="continue",
            nudge_message=get_budget_continuation_message(pct, turn_tokens, budget),
            continuation_count=tracker.continuation_count,
            pct=pct,
            turn_tokens=turn_tokens,
            budget=budget,
        )

    if is_diminishing or tracker.continuation_count > 0:
        return StopDecision(
            action="stop",
            completion_event={
                "continuationCount": tracker.continuation_count,
                "pct": pct,
                "turnTokens": turn_tokens,
                "budget": budget,
                "diminishingReturns": is_diminishing,
                "durationMs": int(time.time() * 1000 - tracker.started_at),
            },
        )

    return StopDecision(action="stop", completion_event=None)


__all__ = [
    "BudgetTracker",
    "create_budget_tracker",
    "check_token_budget",
    "ContinueDecision",
    "StopDecision",
    "TokenBudgetDecision",
    "COMPLETION_THRESHOLD",
    "DIMINISHING_THRESHOLD",
]
