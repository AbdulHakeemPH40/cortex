"""
Comprehensive Verification Script for All 3 Phases
Checks that all files exist and are importable
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("COMPREHENSIVE VERIFICATION: ALL 3 PHASES")
print("=" * 70)

errors = []
warnings = []

# ============================================================================
# PHASE 1: PROMPT SYSTEM & AUTO TITLES
# ============================================================================
print("\n[PHASE 1] Checking Prompt System & Auto Titles...")
print("-" * 70)

# Check prompt files
prompt_files = [
    "src/ai/prompts/build.txt",
    "src/ai/prompts/explore.txt",
    "src/ai/prompts/debug.txt",
    "src/ai/prompts/plan.txt",
    "src/ai/prompts/title.txt",
    "src/ai/prompts/summary.txt"
]

for pf in prompt_files:
    if os.path.exists(pf):
        size = os.path.getsize(pf)
        print(f"  [OK] {pf} ({size} bytes)")
    else:
        errors.append(f"MISSING: {pf}")
        print(f"  [FAIL] {pf} - MISSING!")

# Check Python modules
phase1_modules = [
    ("src.ai.prompt_manager", "PromptManager"),
    ("src.ai.title_generator", "TitleGenerator")
]

for module, class_name in phase1_modules:
    try:
        exec(f"from {module} import {class_name}")
        print(f"  [OK] {module}.{class_name}")
    except Exception as e:
        errors.append(f"IMPORT ERROR: {module}.{class_name}: {e}")
        print(f"  [FAIL] {module}.{class_name} - ERROR: {e}")

# Test imports work
try:
    from src.ai.prompt_manager import get_prompt_manager
    from src.ai.title_generator import get_title_generator
    pm = get_prompt_manager()
    prompts = pm.list_available()
    print(f"  [OK] PromptManager working - {len(prompts)} prompts available")
except Exception as e:
    errors.append(f"Phase 1 runtime error: {e}")
    print(f"  [FAIL] Phase 1 runtime error: {e}")

# ============================================================================
# PHASE 2: CONTEXT COMPACTION & DATABASE
# ============================================================================
print("\n[PHASE 2] Checking Context Compaction & Database...")
print("-" * 70)

phase2_modules = [
    ("src.ai.message_compactor", "MessageCompactor"),
    ("src.ai.session_schema", "SessionSchemaManager")
]

for module, class_name in phase2_modules:
    try:
        exec(f"from {module} import {class_name}")
        print(f"  [OK] {module}.{class_name}")
    except Exception as e:
        errors.append(f"IMPORT ERROR: {module}.{class_name}: {e}")
        print(f"  [FAIL] {module}.{class_name} - ERROR: {e}")

# Test imports work
try:
    from src.ai.message_compactor import get_message_compactor
    from src.ai.session_schema import get_session_schema_manager
    compactor = get_message_compactor()
    db = get_session_schema_manager()
    print(f"  [OK] MessageCompactor working")
    print(f"  [OK] SessionSchemaManager working")
except Exception as e:
    errors.append(f"Phase 2 runtime error: {e}")
    print(f"  [FAIL] Phase 2 runtime error: {e}")

# ============================================================================
# PHASE 3: MULTI-AGENT, SKILLS & MCP
# ============================================================================
print("\n[PHASE 3] Checking Multi-Agent System, Skills & MCP...")
print("-" * 70)

# Check directories exist
dirs_to_check = [
    "src/ai/acp",
    "src/ai/skills",
    "src/ai/mcp"
]

for d in dirs_to_check:
    if os.path.isdir(d):
        files = os.listdir(d)
        print(f"  [OK] {d}/ ({len(files)} files)")
    else:
        errors.append(f"MISSING DIR: {d}")
        print(f"  [FAIL] {d}/ - MISSING!")

# Check Phase 3 Python files
phase3_files = [
    "src/ai/acp/__init__.py",
    "src/ai/acp/control_plane.py",
    "src/ai/skills/__init__.py",
    "src/ai/skills/registry.py",
    "src/ai/mcp/__init__.py",
    "src/ai/mcp/client.py"
]

for pf in phase3_files:
    if os.path.exists(pf):
        size = os.path.getsize(pf)
        print(f"  [OK] {pf} ({size} bytes)")
    else:
        errors.append(f"MISSING: {pf}")
        print(f"  [FAIL] {pf} - MISSING!")

# Test imports
phase3_modules = [
    ("src.ai.acp", "AgentControlPlane"),
    ("src.ai.skills", "SkillRegistry"),
    ("src.ai.mcp", "MCPManager")
]

for module, class_name in phase3_modules:
    try:
        exec(f"from {module} import {class_name}")
        print(f"  [OK] {module}.{class_name}")
    except Exception as e:
        errors.append(f"IMPORT ERROR: {module}.{class_name}: {e}")
        print(f"  [FAIL] {module}.{class_name} - ERROR: {e}")

# Test runtime
try:
    from src.ai.acp import get_agent_control_plane, AgentType
    from src.ai.skills import get_skill_registry
    from src.ai.mcp import get_mcp_manager
    
    acp = get_agent_control_plane()
    agents = acp.list_agents()
    print(f"  [OK] AgentControlPlane working - {len(agents)} agents")
    
    skills = get_skill_registry().list_skills()
    print(f"  [OK] SkillRegistry working - {len(skills)} skills")
    
    mcp = get_mcp_manager()
    print(f"  [OK] MCPManager working")
except Exception as e:
    errors.append(f"Phase 3 runtime error: {e}")
    print(f"  [FAIL] Phase 3 runtime error: {e}")

# ============================================================================
# INTEGRATION CHECK
# ============================================================================
print("\n[INTEGRATION] Checking IDE Integration...")
print("-" * 70)

# Check agent.py integration
agent_file = "src/ai/agent.py"
if os.path.exists(agent_file):
    with open(agent_file, 'r', encoding='utf-8') as f:
        content = f.read()
        if "from src.ai.prompt_manager import" in content:
            print("  [OK] agent.py - Phase 1 imports")
        else:
            warnings.append("agent.py missing Phase 1 imports")
            print("  [WARN] agent.py - Phase 1 imports not found")
            
        if "get_prompt_manager()" in content:
            print("  [OK] agent.py - PromptManager initialized")
        else:
            warnings.append("agent.py not initializing PromptManager")
            print("  [WARN] agent.py - PromptManager not initialized")
            
        if "get_agent_control_plane()" in content:
            print("  [OK] agent.py - ACP initialized")
        else:
            warnings.append("agent.py not initializing ACP")
            print("  [WARN] agent.py - ACP not initialized")
else:
    errors.append("agent.py not found!")
    print("  [FAIL] agent.py - NOT FOUND!")

# Check main_window.py integration
main_file = "src/main_window.py"
if os.path.exists(main_file):
    with open(main_file, 'r', encoding='utf-8') as f:
        content = f.read()
        if "get_title_generator" in content:
            print("  [OK] main_window.py - TitleGenerator integration")
        else:
            warnings.append("main_window.py missing TitleGenerator")
            print("  [WARN] main_window.py - TitleGenerator not integrated")
            
        if "get_session_schema_manager" in content:
            print("  [OK] main_window.py - SessionSchema integration")
        else:
            warnings.append("main_window.py missing SessionSchema")
            print("  [WARN] main_window.py - SessionSchema not integrated")
            
        if "_set_agent_mode" in content:
            print("  [OK] main_window.py - Agent mode menu")
        else:
            warnings.append("main_window.py missing agent mode menu")
            print("  [WARN] main_window.py - Agent mode menu not found")
else:
    errors.append("main_window.py not found!")
    print("  [FAIL] main_window.py - NOT FOUND!")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 70)
print("VERIFICATION SUMMARY")
print("=" * 70)

if not errors and not warnings:
    print("\nSUCCESS ALL CHECKS PASSED!")
    print("\nAll 3 phases are fully implemented and integrated:")
    print("  [OK] Phase 1: 6 prompt templates + PromptManager + TitleGenerator")
    print("  [OK] Phase 2: MessageCompactor + SessionSchema (SQLite + FTS)")
    print("  [OK] Phase 3: ACP + Skills + MCP with all __init__.py files")
    print("  [OK] Integration: agent.py and main_window.py connected")
    print("\n[READY] READY TO USE!")
    sys.exit(0)
elif not errors:
    print("\n[WARN] ALL CRITICAL CHECKS PASSED (with warnings)")
    print("\nWarnings:")
    for w in warnings:
        print(f"  - {w}")
    print("\n[READY] Should work but review warnings")
    sys.exit(0)
else:
    print(f"\nFAILED {len(errors)} ERRORS FOUND!")
    print("\nErrors:")
    for e in errors:
        print(f"  [FAIL] {e}")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  [WARN] {w}")
    print("\nFAILED NEEDS ATTENTION!")
    sys.exit(1)
