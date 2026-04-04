#!/usr/bin/env python
"""List ALL chats in the database regardless of project path."""

from src.core.chat_history import get_chat_history

print(f"🔍 Checking ALL chats in database...")
print("-" * 80)

history = get_chat_history()

# Get ALL conversations (no project filter)
all_conversations = history.get_conversations(None)

if not all_conversations:
    print("❌ Database is completely empty!")
else:
    print(f"✅ Found {len(all_conversations)} total chat(s) in database:\n")
    
    # Group by project path
    projects = {}
    for conv in all_conversations:
        path = conv.get('project_path', 'NO PATH')
        if path not in projects:
            projects[path] = []
        projects[path].append(conv)
    
    for project_path, chats in projects.items():
        print(f"\n📁 Project: {project_path}")
        print(f"   Chats: {len(chats)}")
        for chat in chats:
            print(f"     • {chat['title']} ({chat['created_at']})")

print("-" * 80)
