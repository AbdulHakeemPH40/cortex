# Cortex AI Agent — Code Review Report

## Executive Summary
The project is functionally ambitious and feature-rich, but suffers from critical structural debt: massive god-classes, duplicate files, conflicting data models, and configuration issues that are causing the runtime bugs already encountered (DeepSeek API errors, signal issues, serialization failures).

---

## Critical Issues (Fix Immediately)

### 1. Duplicate Files — Codebase Bloat & Confusion
**Evidence**: In `src/agent/src/` alone there are 26 pairs of duplicate files with different naming conventions:
- `agent_context.py` ↔ `agentContext.py`
- `api_client.py` ↔ `apiClient.py`
- `config_manager.py` ↔ `configManager.py`
- `context_manager.py` ↔ `contextManager.py`
- ...and 22 more.

**Impact**: Python imports are case-sensitive on some filesystems. You may edit one file while the runtime imports the other.

**Fix**: Pick one convention (PEP 8 recommends `snake_case`), delete duplicates, update imports.

---

### 2. Conflicting `ChatMessage` Definitions — Root Cause of `reasoning_content` Bug
**Evidence**: Two different `ChatMessage` dataclasses exist:
- `src/ai/providers/__init__.py`: Has `reasoning_content: Optional[str] = None`
- `src/core/database.py`: Has NO `reasoning_content` field (used for chat history persistence)

**Impact**: When the bridge creates messages using the database model and passes them to providers expecting the provider model, you get:
```
ChatMessage.__init__() got unexpected keyword argument 'reasoning_content'
```

**Fix**: Create a single source of truth for `ChatMessage` in `src/core/types.py` or `src/models/chat.py`. Have both modules import from that location.

---

### 3. DeepSeek Provider Sends `reasoning_content` Back to API Incorrectly
**Evidence**: In `src/ai/providers/__init__.py`, `_format_messages_for_provider()` adds `reasoning_content` to the outgoing message dict.

**Impact**: DeepSeek's API returns `reasoning_content` in responses but rejects it in requests unless the model is in "thinking mode." This causes the 400 error:
> `reasoning_content` must be passed back in thinking mode

**Fix**: Strip `reasoning_content` from outgoing messages in `_format_messages_for_provider`. Only keep it for internal logging/display.

---

### 4. `requirements2.txt` is Corrupted
**Evidence**: The file contains shell commands and pip install lines instead of package names.

**Impact**: `pip install -r requirements2.txt` will fail.

**Fix**: Rewrite it as a proper requirements file with just package names and versions.

---

## High Severity Issues

### 5. God Classes — Files Are Far Too Large
| File | Size | Lines | Problem |
|------|------|-------|---------|
| `src/ai/agent_bridge.py` | 370 KB | ~7,500 | Does everything: agent loop, tool execution, UI updates, file watching |
| `src/main_window.py` | 301 KB | ~6,800 | Window setup, menus, panels, signals, settings |
| `src/ui/components/ai_chat.py` | 192 KB | ~4,000 | Chat UI, markdown rendering, tool call display, streaming |

**Fix**: Apply the Single Responsibility Principle. Split into focused modules.

---

### 6. `sys.path` Hacks Violate Architecture Boundaries
**Evidence**: `src/ai/agent_bridge.py` manipulates `sys.path` to reach into `src/agent/src/`.

**Fix**: Make `src/agent/src` a proper Python package with an `__init__.py`. Use absolute imports and remove all `sys.path.insert` hacks.

---

### 7. Bare `except:` Clauses Hide Bugs
**Evidence**: Found in 19 files including `agent_bridge.py`, `main_window.py`, `ai_chat.py`, `deepseek_provider.py`.

**Impact**: Catches `KeyboardInterrupt`, `SystemExit`, and `MemoryError`. Users can't quit with Ctrl+C, and real errors are hidden.

**Fix**: Replace all `except:` with `except Exception:` at minimum. Better yet, catch specific exceptions.

---

### 8. No Project Tests
**Evidence**: The `tests/` directory contains zero project-specific test files.

**Fix**: Start with smoke tests for the provider registry and database models.

---

### 9. Dependency Version Conflicts & Outdated Packages
**Evidence**: `requirements.txt` pins very old versions:
- `PyQt6==6.4.2` (from 2022)
- `urllib3==1.26.20` (old, has known vulnerabilities)
- Conflicting HTTP libraries: `httpx`, `requests`, `aiohttp`

**Fix**: Upgrade `urllib3` to `>=2.0`. Consider standardizing on `httpx`. Upgrade PyQt6 to `>=6.6`.

---

## Medium Severity Issues

### 10. PyQt6 Signal Pattern Risks
**Impact**: Previous memory notes fixed `'PyQt6.QtCore.pyqtSignal' object has no attribute 'emit'`. This happens when signals are accessed on the class instead of the instance.

**Fix**: Audit all signal definitions. Ensure `emit()` is called on the instance, not the class.

---

### 11. `agent_bridge.py` Creates `QApplication` When Imported
**Impact**: If imported in a script or test, it instantiates a Qt app, blocking CI/CD.

**Fix**: Move QApplication creation behind `if __name__ == "__main__":` or into a dedicated entry point.

---

## Recommended Priority Order

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| 1 | Delete duplicate snake_case/camelCase files | 2 hrs | High |
| 2 | Unify `ChatMessage` into one model | 1 hr | High |
| 3 | Strip `reasoning_content` from outgoing API calls | 15 min | High |
| 4 | Fix `requirements2.txt` format | 5 min | High |
| 5 | Replace bare `except:` clauses | 2 hrs | Medium |
| 6 | Remove `sys.path` hacks in `agent_bridge.py` | 2 hrs | Medium |
| 7 | Upgrade `urllib3` and audit dependencies | 1 hr | Medium |
| 8 | Write 10 smoke tests (providers + database) | 3 hrs | High |
| 9 | Split `agent_bridge.py` into smaller modules | 1 day | High |
| 10 | Split `main_window.py` and `ai_chat.py` | 2 days | High |

---

## What Works Well

- **Provider abstraction**: `BaseProvider` + `ProviderRegistry` is a solid pattern for multi-LLM support.
- **Environment-based config**: Using env vars with fallbacks is good practice.
- **Dataclass usage**: `ChatMessage`, `ModelInfo`, `ChatResponse` are well-structured.
- **Async separation**: Keeping sync providers and async UI mostly separated is architecturally sound.
- **Logging**: Consistent use of `get_logger` across modules.
