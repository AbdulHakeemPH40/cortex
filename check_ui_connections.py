"""
Check UI Connections for All Features
"""
import os
import re

print("=" * 70)
print("UI CONNECTION VERIFICATION REPORT")
print("=" * 70)

# Check main_window.py connections
with open('src/main_window.py', 'r', encoding='utf-8') as f:
    main_content = f.read()

# Check ai_chat.py connections  
with open('src/ui/components/ai_chat.py', 'r', encoding='utf-8') as f:
    aichat_content = f.read()

# Check script.js connections
with open('src/ui/html/ai_chat/script.js', 'r', encoding='utf-8') as f:
    js_content = f.read()

features = {
    "TODO System": {
        "main_window": ["_show_todo_manager", "_add_todo_task", "_complete_todo_task", "_todo_manager"],
        "ai_chat_py": ["todo"],
        "script_js": ["updateTodos", "currentTodoList", "todo-section"],
        "menu": True
    },
    "GitHub Agents": {
        "main_window": ["_show_github_integration", "_github_agent", "analyze_github_pr"],
        "ai_chat_py": [],
        "script_js": [],
        "menu": True
    },
    "Permission Schemas": {
        "main_window": ["_show_permission_settings", "_permission_evaluator", "check_permission"],
        "ai_chat_py": [],
        "script_js": ["permission-card", "handlePermissionAllow", "handlePermissionDeny"],
        "menu": True
    },
    "MCP Integration": {
        "main_window": ["_show_mcp_connections", "_mcp_manager", "connect_mcp_server"],
        "ai_chat_py": [],
        "script_js": [],
        "menu": True
    },
    "Prompt Templates": {
        "main_window": ["_set_agent_mode"],
        "ai_chat_py": ["mode_changed"],
        "script_js": ["on_mode_changed"],
        "menu": True
    },
    "AI Summarization": {
        "main_window": ["_message_compactor"],
        "ai_chat_py": [],
        "script_js": [],
        "menu": False
    },
    "Auto Title Generation": {
        "main_window": ["generate_chat_title", "_title_generator"],
        "ai_chat_py": [],
        "script_js": [],
        "menu": False
    },
    "Agent Control Plane": {
        "main_window": ["use_acp_for_task", "_acp"],
        "ai_chat_py": [],
        "script_js": [],
        "menu": False
    }
}

print("\n" + "=" * 70)
print("FEATURE UI CONNECTION STATUS")
print("=" * 70)

for feature, checks in features.items():
    print(f"\n📋 {feature}")
    
    # Check main_window.py
    main_found = 0
    for check in checks["main_window"]:
        if check in main_content:
            main_found += 1
    main_status = "✅" if main_found == len(checks["main_window"]) else "⚠️"
    print(f"  {main_status} main_window.py: {main_found}/{len(checks['main_window'])} connections")
    
    # Check ai_chat.py
    aichat_found = 0
    for check in checks["ai_chat_py"]:
        if check in aichat_content:
            aichat_found += 1
    aichat_status = "✅" if aichat_found == len(checks["ai_chat_py"]) else "⚠️" if checks["ai_chat_py"] else "➖"
    if checks["ai_chat_py"]:
        print(f"  {aichat_status} ai_chat.py: {aichat_found}/{len(checks['ai_chat_py'])} connections")
    
    # Check script.js
    js_found = 0
    for check in checks["script_js"]:
        if check in js_content:
            js_found += 1
    js_status = "✅" if js_found == len(checks["script_js"]) else "⚠️" if checks["script_js"] else "➖"
    if checks["script_js"]:
        print(f"  {js_status} script.js: {js_found}/{len(checks['script_js'])} connections")
    
    # Menu status
    menu_status = "✅ Menu item" if checks["menu"] else "➖ Background feature"
    print(f"  {menu_status}")

print("\n" + "=" * 70)
print("LEGEND")
print("=" * 70)
print("✅ = Properly connected")
print("⚠️  = Partially connected / Needs work")
print("➖ = Not applicable (backend only)")
print("\nNOTE: Some features work through menus/dialogs only")
print("      and don't need ai_chat.py or script.js connections")
