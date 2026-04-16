#!/usr/bin/env python
"""Delete all old test chats from database."""

from src.core.chat_history import get_chat_history

print("🗑️  Deleting all chats from database...")

history = get_chat_history()

# Get ALL conversations
all_conversations = history.get_conversations(None)

if not all_conversations:
    print("✅ Database already empty!")
else:
    print(f"📝 Found {len(all_conversations)} chats to delete:")
    for conv in all_conversations:
        print(f"  • {conv['title']}")
        history.delete_conversation(conv['id'])
    
    print(f"\n✅ Deleted all {len(all_conversations)} chats!")

print("-" * 80)
