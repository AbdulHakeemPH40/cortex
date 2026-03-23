#!/usr/bin/env python3
"""Add performance indexes to SQLite database."""

import sqlite3
from pathlib import Path

# Database path
db_path = Path.home() / ".cortex" / "cortex.db"

print(f"Database: {db_path}")

if not db_path.exists():
    print("❌ Database doesn't exist!")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("\n📊 Adding performance indexes...")

# Index 1: conversations.created_at for fast sorting
try:
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at DESC)")
    print("✅ Index: conversations(created_at)")
except Exception as e:
    print(f"⚠️  Failed: {e}")

# Index 2: conversations.project_path for fast filtering
try:
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_path)")
    print("✅ Index: conversations(project_path)")
except Exception as e:
    print(f"⚠️  Failed: {e}")

# Index 3: chat_messages.conversation_id for fast joins
try:
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON chat_messages(conversation_id)")
    print("✅ Index: chat_messages(conversation_id)")
except Exception as e:
    print(f"⚠️  Failed: {e}")

conn.commit()
conn.close()

print("\n✅ Database optimized with indexes!")
print("🚀 Startup performance should be much better now!")
