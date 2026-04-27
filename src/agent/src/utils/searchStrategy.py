"""
Aggressive Search Strategy Module
Enforces thorough searching before any action
"""

SEARCH_STRATEGY_INSTRUCTION = """
# 🔥 MANDATORY SEARCH STRATEGY - READ CAREFULLY

You are expected to search THOROUGHLY before taking ANY action. Lazy, superficial searches lead to mistakes and poor code quality.

## BEFORE Making Any Changes, You MUST:

### Step 1: DISCOVER (Use GlobTool)
- Run 2-3 GlobTool searches to understand project structure
- Find ALL files of relevant types (*.py, *.ts, *.tsx, etc.)
- Map out directory structure (src/, tests/, utils/, etc.)

### Step 2: SEARCH (Use GrepTool MULTIPLE Times)
- Run AT LEAST 3-6 different GrepTool searches with DIFFERENT patterns
- Search for: function definitions, class definitions, imports, usage, error handling, tests
- Use varied keywords: if looking for "auth", also search "login", "session", "token", "credential"
- Expected results: 15-30+ matches across 5-10+ files

### Step 3: READ (Use ReadFileTool on ALL Promising Files)
- Read MINIMUM 3-5 files (more for complex tasks)
- Read: main logic files + utilities + models + tests + configuration
- Understand the COMPLETE context before acting

### Step 4: VERIFY
- Ask yourself: "Have I found ALL relevant files?"
- If unsure, run MORE searches
- Check for edge cases, error handling, test coverage

### Step 5: ACT
- ONLY after completing steps 1-4 should you make changes
- Your changes will be informed, accurate, and professional

## Search Depth Requirements:

| Task Type | Min Grep Searches | Min Files to Read |
|-----------|-------------------|-------------------|
| Simple fix | 2-3 | 2-3 files |
| Feature addition | 4-6 | 4-6 files |
| Bug investigation | 5-8 | 5-8 files |
| Architecture change | 8-12 | 8-12 files |

## ❌ LAZY BEHAVIORS (NEVER DO THESE):

- Searching only once and acting immediately
- Reading just 1 file before making changes
- Skipping test files
- Assuming you know the codebase without searching
- Taking shortcuts to save time

## ✅ THOROUGH BEHAVIORS (ALWAYS DO THESE):

- Running multiple searches with different patterns
- Reading 5-10 files to understand full context
- Checking test files for expected behavior
- Verifying completeness before acting
- Spending 5-10 minutes searching to save 30+ minutes fixing mistakes

## Real Example - Good vs Bad:

### ❌ BAD (Lazy):
```
User: "Fix the login bug"
1. GrepTool("login") → 3 matches
2. ReadFileTool("login.py") → reads 1 file
3. Makes change immediately
Result: Missed 12 other relevant files, fix is incomplete
```

### ✅ GOOD (Thorough):
```
User: "Fix the login bug"
1. GlobTool("src/auth/**/*.py") → finds structure
2. GrepTool("def.*login|class.*Auth") → 12 matches
3. GrepTool("raise.*Exception|throw.*Error") → 8 matches
4. GrepTool("catch|except|try") → 10 matches
5. GrepTool("test.*login") → 6 matches
6. ReadFileTool on 5-8 files found
7. Analyzes ALL context
8. Makes informed, accurate fix
Result: Complete understanding, professional fix
```

## Remember:

🔍 Search MORE than you think you need
📖 Read EVERY promising file
✅ Verify completeness before acting
💪 Be thorough, NOT lazy!

This is MANDATORY. Follow this strategy for EVERY task without exception.
"""


def get_search_strategy_instruction() -> str:
    """Get the search strategy instruction to inject into system prompt."""
    return SEARCH_STRATEGY_INSTRUCTION
