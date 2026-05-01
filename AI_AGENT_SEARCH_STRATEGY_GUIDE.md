# AI Agent Search Strategy Guide

This guide defines the **industry-standard** way the Cortex agent should search a codebase before making changes.
The goal is to prevent "read 1 file ? guess ? write" behavior and instead enforce a repeatable, high-signal workflow.

## Core Rule

Before implementing anything, run **multiple searches**. One search is almost never enough.

- Minimum: **3?6 searches** for most tasks
- Bugs/unknowns: **5?8 searches**
- Refactors/architecture: **8?12 searches**

If you don?t search deeply, you will miss the real root cause.

## File-Finding Workflow (Tool Teamwork)

Use tools as a team:

1. **GlobTool** ? quickly enumerate candidate files (by extension, folder, naming patterns)
2. **GrepTool** ? search across the codebase for definitions/usage/errors
3. **ReadFileTool** ? read the most relevant files (minimum **3?5**) before acting

## Search Depth Table

| Scenario | Searches | Files to read | Notes |
|---|---:|---:|---|
| Simple fix | 2?3 | 2?3 | Only if you already know the module |
| Feature addition | 4?6 | 4?6 | Trace call sites + tests |
| Bug investigation | 5?8 | 5?8 | Search logs + error messages + boundary code |
| Architecture change | 8?12 | 8?12 | Include config, docs, and cross-module integrations |

## What to Search For

Always include at least these categories:

- **Definition**: class/function definitions
- **Usage**: call sites, event wiring, signal/slot, CLI entrypoints
- **Imports**: where the symbol is pulled from (and whether a stub fallback exists)
- **Error handling**: try/except blocks, fallbacks, circuit breakers
- **Tests**: the tests that cover the behavior

## Language Pattern Examples

### Python

Common globs:
- `*.py`

Common search patterns:
- `def <name>`
- `class <Name>`
- `ImportError` (to detect silent stub fallbacks)

### TypeScript / JavaScript

Common globs:
- `*.ts`, `*.tsx`, `*.js`, `*.jsx`

Common search patterns:
- `export function` / `export const`
- `class <Name>`
- `import .* from` usage chains

## GOOD vs BAD

? **GOOD**
- Search ? find 15?30+ matches ? read 5?10 files ? understand ? implement ? verify

? **BAD (LAZY)**
- Search once ? read 1 file ? implement ? claim done

The BAD pattern is explicitly forbidden because it produces brittle fixes and wastes user time.

## Example

**User:** "The app says code search is disabled. Fix it."

**Scenario:** SQLite FTS index fails due to schema drift.

Suggested search plan:
1. Grep: `FTS5 not available`
2. Grep: `code_fts`
3. Grep: `CREATE VIRTUAL TABLE`
4. Grep: `INSERT OR IGNORE INTO code_fts`
5. Read the database init + migration code
6. Add a schema repair path (drop/recreate) and verify with tests
