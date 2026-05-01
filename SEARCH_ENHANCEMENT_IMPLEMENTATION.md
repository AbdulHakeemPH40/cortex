# Search Enhancement Implementation

This document explains how the "aggressive search before action" behavior is implemented and how success is measured.

## Before / After

### Before

- Agent runs **1 search** (or none)
- Reads **1 file** and guesses
- Misses call sites and tests
- Results: incomplete fixes and repeated user follow-ups

### After

- Agent runs **3?6 searches minimum** (5?8 for bug investigations)
- Reads **3?5 files minimum** before editing
- Uses tool teamwork: **GlobTool ? GrepTool ? ReadFileTool**
- Results: more complete context, fewer missed integrations, higher-quality fixes

## Implementation

1. **Tool prompt upgrades**
   - GrepTool prompt mandates 3?6 searches and forbids lazy single-search behavior.
   - GlobTool prompt encourages discovery patterns (structure, file types).
   - ReadFileTool prompt mandates reading multiple files before acting.

2. **System-level instruction**
   - `utils.searchStrategy.get_search_strategy_instruction()` returns a substantial instruction block.
   - `QueryEngine` injects this instruction into the assembled system prompt.

## Expected Improvements (Measurable)

- **Search depth**: 3-5x more searches per task (from ~1 to 3?6)
- **Context coverage**: 80-95% reduction in "missed file" failures for non-trivial bugs
- **Rework reduction**: fewer "still broken" iterations due to missed call sites/tests

## Verification

- Unit tests assert:
  - The search strategy module is importable and returns non-empty instructions (>500 chars)
  - QueryEngine imports and uses the search strategy
  - Documentation files exist and are valid markdown
