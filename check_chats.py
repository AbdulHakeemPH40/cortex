#!/usr/bin/env python
"""Check if chats exist in database for the sales dashbord project."""

from src.core.chat_history import get_chat_history

project_path = r"C:\Users\Hakeem1\sales dashbord"

print(f"🔍 Checking chats for project: {project_path}")
print("-" * 80)

history = get_chat_history()
conversations = history.get_conversations(project_path)

if not conversations:
    print("❌ NO CHATS FOUND in database for this project!")
    print("\nThis means:")
    print("1. You haven't created any chats yet, OR")
    print("2. The project path doesn't match exactly")
else:
    print(f"✅ Found {len(conversations)} chat(s):")
    for conv in conversations:
        print(f"\n  📝 ID: {conv['id']}")
        print(f"     Title: {conv['title']}")
        print(f"     Created: {conv['created_at']}")
        print(f"     Messages: {conv.get('message_count', 'unknown')}")

print("-" * 80)
print(f"\nDatabase location: C:\\Users\\Hakeem1\\.cortex\\cortex.db")
