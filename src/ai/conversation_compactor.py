"""
Conversation Compactor — ported from Claude Code's microCompact.ts + autoCompact.ts

Two-tier compaction system:
1. Micro-compact: clears old tool results (cheap, no LLM call)
2. Auto-compact: LLM-based summarization when context > 80% full

Reference: claude-code-main/src/services/compact/microCompact.ts
           claude-code-main/src/services/compact/autoCompact.ts
"""

import logging
import time
from typing import List, Optional, Set, Tuple

log = logging.getLogger("cortex.conversation_compactor")

# ── Constants ────────────────────────────────────────────────────────────────

# Tools whose results can be cleared by micro-compact
# Matches Claude Code's COMPACTABLE_TOOLS set
COMPACTABLE_TOOLS: Set[str] = {
    "Read", "Bash", "Grep", "Glob",
    "Edit", "Write", "LS",
    "WebSearch", "WebFetch",
}

# Message used when tool result content is cleared
CLEARED_MESSAGE = "[Old tool result content cleared]"

# How many recent tool results to keep (rest get cleared)
DEFAULT_KEEP_RECENT = 6

# Auto-compact triggers when context usage exceeds this fraction
AUTOCOMPACT_THRESHOLD_PCT = 0.80

# Buffer tokens reserved for output during compaction
AUTOCOMPACT_BUFFER_TOKENS = 13_000

# Max consecutive auto-compact failures before circuit breaker trips
MAX_CONSECUTIVE_FAILURES = 3


# ── Micro-compact ────────────────────────────────────────────────────────────

def microcompact_messages(
    messages: list,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> Tuple[list, int]:
    """
    Clear old tool result contents, keeping the most recent N results.
    
    This is a cheap, no-LLM-call operation that replaces old tool result
    content with a short placeholder. The LLM still sees that a tool was
    called (the tool_call_id remains), but the bulky output is gone.
    
    Ported from microCompact.ts's time-based microcompact path.
    
    Args:
        messages: The conversation message list
        keep_recent: Number of most-recent compactable tool results to keep
    
    Returns:
        (modified_messages, tokens_saved_estimate)
    """
    # Step 1: Collect all compactable tool_call_ids from assistant messages
    compactable_ids = _collect_compactable_tool_ids(messages)
    
    if len(compactable_ids) <= keep_recent:
        return messages, 0  # Nothing to compact
    
    # Keep the most recent N, clear the rest
    keep_set = set(compactable_ids[-keep_recent:])
    clear_set = set(compactable_ids) - keep_set
    
    if not clear_set:
        return messages, 0
    
    # Step 2: Walk messages and clear matching tool results
    tokens_saved = 0
    modified = False
    result = []
    
    for msg in messages:
        role = getattr(msg, 'role', None)
        content = getattr(msg, 'content', None) or ''
        tcid = getattr(msg, 'tool_call_id', None)
        
        if role == 'tool' and tcid in clear_set and content != CLEARED_MESSAGE:
            # Estimate tokens saved (rough: 1 token ≈ 4 chars)
            tokens_saved += len(content) // 4
            
            # Replace content with cleared message
            try:
                new_msg = type(msg)(
                    role='tool',
                    content=CLEARED_MESSAGE,
                    tool_call_id=tcid,
                )
                result.append(new_msg)
                modified = True
            except Exception:
                # Fallback: modify in place
                msg.content = CLEARED_MESSAGE
                result.append(msg)
                modified = True
        else:
            result.append(msg)
    
    if not modified:
        return messages, 0
    
    log.info(
        f"[MICRO-COMPACT] Cleared {len(clear_set)} old tool results, "
        f"kept last {len(keep_set)}, saved ~{tokens_saved:,} tokens"
    )
    
    return result, tokens_saved


def _collect_compactable_tool_ids(messages: list) -> List[str]:
    """
    Walk messages and collect tool_call IDs for compactable tools.
    Returns IDs in encounter order (oldest first).
    
    Ported from collectCompactableToolIds() in microCompact.ts
    """
    ids = []
    for msg in messages:
        role = getattr(msg, 'role', None)
        tool_calls = getattr(msg, 'tool_calls', None)
        
        if role == 'assistant' and tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    func = tc.get('function', {})
                    name = func.get('name', '')
                    tc_id = tc.get('id', '')
                elif hasattr(tc, 'function'):
                    name = tc.function.get('name', '') if isinstance(tc.function, dict) else getattr(tc.function, 'name', '')
                    tc_id = getattr(tc, 'id', '')
                else:
                    continue
                
                if name in COMPACTABLE_TOOLS and tc_id:
                    ids.append(tc_id)
    
    return ids


# ── Auto-compact (token threshold check) ────────────────────────────────────

class AutoCompactState:
    """
    Tracks auto-compact state across turns.
    Ported from AutoCompactTrackingState in autoCompact.ts
    """
    
    def __init__(self):
        self.compacted: bool = False
        self.turn_counter: int = 0
        self.consecutive_failures: int = 0
    
    @property
    def circuit_breaker_tripped(self) -> bool:
        return self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES


def should_auto_compact(
    estimated_tokens: int,
    context_budget: int,
    state: Optional[AutoCompactState] = None,
    threshold_pct: float = AUTOCOMPACT_THRESHOLD_PCT,
) -> bool:
    """
    Check if auto-compaction should trigger.
    
    Ported from shouldAutoCompact() in autoCompact.ts
    
    Args:
        estimated_tokens: Current estimated token usage
        context_budget: Total context budget for the model
        state: Auto-compact tracking state (for circuit breaker)
        threshold_pct: Fraction of budget that triggers compaction
    
    Returns:
        True if auto-compaction should run
    """
    if state and state.circuit_breaker_tripped:
        return False
    
    if context_budget <= 0:
        return False
    
    threshold = int(context_budget * threshold_pct)
    return estimated_tokens >= threshold


def get_auto_compact_threshold(context_budget: int) -> int:
    """
    Calculate the token threshold for auto-compaction.
    Ported from getAutoCompactThreshold() in autoCompact.ts
    """
    return context_budget - AUTOCOMPACT_BUFFER_TOKENS


# ── Combined compaction pass ─────────────────────────────────────────────────

def compact_if_needed(
    messages: list,
    estimated_tokens: int,
    context_budget: int,
    compact_fn,
    PCM_class: type,
    state: Optional[AutoCompactState] = None,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> Tuple[list, bool]:
    """
    Run the two-tier compaction pipeline:
    1. Always try micro-compact first (cheap, clears old tool results)
    2. If still over threshold, run full compact (LLM summarization)
    
    Args:
        messages: Current message list
        estimated_tokens: Estimated token count
        context_budget: Total context budget
        compact_fn: Function to call for full compaction (bridge._compact_messages)
        PCM_class: The ChatMessage class for creating new messages
        state: Auto-compact tracking state
        keep_recent: How many recent tool results to keep in micro-compact
    
    Returns:
        (possibly_compacted_messages, was_compacted)
    """
    if not state:
        state = AutoCompactState()
    
    # Tier 1: Micro-compact (always try if there are enough tool results)
    compactable_ids = _collect_compactable_tool_ids(messages)
    if len(compactable_ids) > keep_recent:
        messages, tokens_saved = microcompact_messages(messages, keep_recent)
        if tokens_saved > 0:
            estimated_tokens -= tokens_saved
            log.info(
                f"[COMPACT] Micro-compact saved ~{tokens_saved:,} tokens, "
                f"estimated now: {estimated_tokens:,}/{context_budget:,}"
            )
    
    # Tier 2: Full compact if still over threshold
    if should_auto_compact(estimated_tokens, context_budget, state):
        log.info(
            f"[COMPACT] Auto-compact triggered: {estimated_tokens:,} tokens "
            f"({estimated_tokens / max(context_budget, 1):.0%} of {context_budget:,} budget)"
        )
        try:
            messages = compact_fn(messages, PCM_class)
            state.compacted = True
            state.turn_counter = 0
            state.consecutive_failures = 0
            return messages, True
        except Exception as e:
            state.consecutive_failures += 1
            log.error(
                f"[COMPACT] Auto-compact failed ({state.consecutive_failures}/"
                f"{MAX_CONSECUTIVE_FAILURES}): {e}"
            )
            if state.circuit_breaker_tripped:
                log.warning("[COMPACT] Circuit breaker tripped — no more auto-compact attempts")
    
    return messages, False
