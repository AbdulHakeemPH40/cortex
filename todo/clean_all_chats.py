"""Clean all chats from SQLite database."""
import sqlite3
from pathlib import Path

db_path = Path.home() / ".cortex" / "cortex.db"

if not db_path.exists():
    print(f"ERROR: Database not found at {db_path}")
    exit(1)

print(f"Connecting to database: {db_path}\n")

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Count before deletion
cursor.execute("SELECT COUNT(*) FROM conversations")
conv_count_before = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM chat_messages")
msg_count_before = cursor.fetchone()[0]

print(f"=== BEFORE CLEANUP ===")
print(f"Conversations: {conv_count_before:,}")
print(f"Messages: {msg_count_before:,}\n")

# Delete all chat messages
cursor.execute("DELETE FROM chat_messages")
deleted_messages = cursor.rowcount
print(f"✓ Deleted {deleted_messages:,} messages")

# Delete all conversations
cursor.execute("DELETE FROM conversations")
deleted_conversations = cursor.rowcount
print(f"✓ Deleted {deleted_conversations:,} conversations")

# Verify deletion
cursor.execute("SELECT COUNT(*) FROM conversations")
conv_count_after = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM chat_messages")
msg_count_after = cursor.fetchone()[0]

print(f"\n=== AFTER CLEANUP ===")
print(f"Conversations: {conv_count_after:,}")
print(f"Messages: {msg_count_after:,}")

# Commit changes
conn.commit()
conn.close()

print(f"\n✅ Database cleanup complete!")
print(f"   Freed {(msg_count_before - msg_count_after) * 0.5 / 1024:.2f} KB of message data")
