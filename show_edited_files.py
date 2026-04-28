#!/usr/bin/env python3
"""Show only the files we manually edited for type fixing."""

print("=" * 70)
print("📝 FILES EDITED FOR TYPE FIXING (Week 1)")
print("=" * 70)

print("\n📅 DAY 1 - Type Definitions & Cleanup")
print("-" * 70)
day1_files = [
    ("src/agent/src/constants/oauth.py", "Added OauthConfig TypedDict + cleanup"),
    ("src/agent/src/constants/systemPromptSections.py", "Added ComputeFn + SystemPromptSection + cleanup"),
]

for file, desc in day1_files:
    print(f"  ✅ {file}")
    print(f"     → {desc}")

print("\n📅 DAY 2 - Undefined Variable Fixes (11 errors)")
print("-" * 70)
day2_files = [
    ("src/agent/src/coordinator/agent_context.py", "Added Optional import (3 errors)"),
    ("src/agent/src/keybindings/shortcutFormat.py", "Added KeybindingContextName enum"),
    ("src/agent/src/query/config.py", "Added QueryConfig class"),
    ("src/agent/src/query/deps.py", "Added QueryDeps dataclass"),
    ("src/agent/src/skills/bundled/remember.py", "Added registerBundledSkill import"),
    ("src/agent/src/state/AppStateStore.py", "Added AppState dataclass"),
    ("src/agent/src/tasks.py", "Added Task + TaskType (2 errors)"),
]

for file, desc in day2_files:
    print(f"  ✅ {file}")
    print(f"     → {desc}")

print("\n" + "=" * 70)
print("📊 SUMMARY")
print("=" * 70)
print(f"  Total files edited: {len(day1_files) + len(day2_files)}")
print(f"  Day 1: {len(day1_files)} files (6 errors + 15 warnings)")
print(f"  Day 2: {len(day2_files)} files (11 errors)")
print(f"  Total: 17 errors fixed ✅")
print("=" * 70)
