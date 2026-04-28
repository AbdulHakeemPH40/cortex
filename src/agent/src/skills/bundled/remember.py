"""
remember - Memory review skill for organizing and promoting auto-memory entries.

Analyzes auto-memory entries and proposes promotions to CORTEX.md, CORTEX.local.md,
or shared team memory. Detects outdated, conflicting, and duplicate entries across
memory layers.

Skills/Usage:
  - /remember - Review and organize memory entries
  - Multi-layer memory comparison and cleanup
  - Conflict detection and resolution proposals

Converted from TypeScript: skills/bundled/remember.ts
"""

import os
from typing import Any, Optional

# Import registerBundledSkill
from src.agent.src.skills.bundledSkills import registerBundledSkill


# Defensive import for isAutoMemoryEnabled
try:
    from ..memdir.paths import isAutoMemoryEnabled
except ImportError:
    def isAutoMemoryEnabled() -> bool:
        """Fallback: auto-memory disabled"""
        return False


# ============================================================================
# SKILL PROMPT - Memory Review Instructions
# ============================================================================

SKILL_PROMPT = """# Memory Review

## Goal
Review the user's memory landscape and produce a clear report of proposed changes, grouped by action type. Do NOT apply changes — present proposals for user approval.

## Steps

### 1. Gather all memory layers
Read CORTEX.md and CORTEX.local.md from the project root (if they exist). Your auto-memory content is already in your system prompt — review it there. Note which team memory sections exist, if any.

**Success criteria**: You have the contents of all memory layers and can compare them.

### 2. Classify each auto-memory entry
For each substantive entry in auto-memory, determine the best destination:

| Destination | What belongs there | Examples |
|---|---|---|
| **CORTEX.md** | Project conventions and instructions for Cortex that all contributors should follow | "use bun not npm", "API routes use kebab-case", "test command is bun test", "prefer functional style" |
| **CORTEX.local.md** | Personal instructions for Cortex specific to this user, not applicable to other contributors | "I prefer concise responses", "always explain trade-offs", "don't auto-commit", "run tests before committing" |
| **Team memory** | Org-wide knowledge that applies across repositories (only if team memory is configured) | "deploy PRs go through #deploy-queue", "staging is at staging.internal", "platform team owns infra" |
| **Stay in auto-memory** | Working notes, temporary context, or entries that don't clearly fit elsewhere | Session-specific observations, uncertain patterns |

**Important distinctions:**
- CORTEX.md and CORTEX.local.md contain instructions for Cortex, not user preferences for external tools (editor theme, IDE keybindings, etc. don't belong in either)
- Workflow practices (PR conventions, merge strategies, branch naming) are ambiguous — ask the user whether they're personal or team-wide
- When unsure, ask rather than guess

**Success criteria**: Each entry has a proposed destination or is flagged as ambiguous.

### 3. Identify cleanup opportunities
Scan across all layers for:
- **Duplicates**: Auto-memory entries already captured in CORTEX.md or CORTEX.local.md → propose removing from auto-memory
- **Outdated**: CORTEX.md or CORTEX.local.md entries contradicted by newer auto-memory entries → propose updating the older layer
- **Conflicts**: Contradictions between any two layers → propose resolution, noting which is more recent

**Success criteria**: All cross-layer issues identified.

### 4. Present the report
Output a structured report grouped by action type:
1. **Promotions** — entries to move, with destination and rationale
2. **Cleanup** — duplicates, outdated entries, conflicts to resolve
3. **Ambiguous** — entries where you need the user's input on destination
4. **No action needed** — brief note on entries that should stay put

If auto-memory is empty, say so and offer to review CORTEX.md for cleanup.

**Success criteria**: User can review and approve/reject each proposal individually.

## Rules
- Present ALL proposals before making any changes
- Do NOT modify files without explicit user approval
- Do NOT create new files unless the target doesn't exist yet
- Ask about ambiguous entries — don't guess
"""


# ============================================================================
# Skill Registration
# ============================================================================

def register_remember_skill() -> None:
    """
    Register the /remember skill for memory review and organization.
    
    This skill is only available when:
    1. Auto-memory is enabled (isAutoMemoryEnabled)
    2. USER_TYPE === 'ant' (internal testing)
    """
    # Check if user is internal tester
    if os.environ.get('USER_TYPE') != 'ant':
        return
    
    # Check if auto-memory is enabled
    if not isAutoMemoryEnabled():
        return
    
    registerBundledSkill({
        'name': 'remember',
        'description': (
            'Review auto-memory entries and propose promotions to CORTEX.md, '
            'CORTEX.local.md, or shared memory. Also detects outdated, conflicting, '
            'and duplicate entries across memory layers.'
        ),
        'whenToUse': (
            'Use when the user wants to review, organize, or promote their auto-memory entries. '
            'Also useful for cleaning up outdated or conflicting entries across CORTEX.md, '
            'CORTEX.local.md, and auto-memory.'
        ),
        'userInvocable': True,
        'isEnabled': lambda: isAutoMemoryEnabled(),
        'getPromptForCommand': get_prompt_for_command,
    })


async def get_prompt_for_command(args: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Generate the memory review prompt with optional additional context.
    
    Args:
        args: Optional additional context from user
        
    Returns:
        List of content blocks with memory review instructions
    """
    prompt = SKILL_PROMPT
    
    if args:
        prompt += f'\n## Additional context from user\n\n{args}'
    
    return [{'type': 'text', 'text': prompt}]
