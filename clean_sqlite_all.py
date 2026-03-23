#!/usr/bin/env python3
"""Clean ALL chats from SQLite database."""

import sqlite3
from pathlib import Path

# Database path
db_path = Path.home() / ".cortex" / "cortex.db"

print(f"Database: {db_path}")
print(f"Exists: {db_path.exists()}")

if not db_path.exists():
    print("❌ Database doesn't exist!")
    exit(1)

# Connect and clean
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Count before
cursor.execute("SELECT COUNT(*) FROM conversations")
before_count = cursor.fetchone()[0]
print(f"\n📊 Before cleaning: {before_count:,} conversations")

# Delete all messages first (foreign key constraint)
cursor.execute("DELETE FROM chat_messages")
deleted_messages = cursor.rowcount
print(f"🗑️  Deleted {deleted_messages:,} messages")

# Delete all conversations
cursor.execute("DELETE FROM conversations")
deleted_conversations = cursor.rowcount
print(f"🗑️  Deleted {deleted_conversations:,} conversations")

# Verify
cursor.execute("SELECT COUNT(*) FROM conversations")
after_count = cursor.fetchone()[0]
print(f"\n📊 After cleaning: {after_count:,} conversations")

# Also clean project_paths table if exists
try:
    cursor.execute("SELECT COUNT(*) FROM project_paths")
    paths_count = cursor.fetchone()[0]
    print(f"\n📂 Project paths in DB: {paths_count:,}")
    
    # Optionally delete all project paths too
    # cursor.execute("DELETE FROM project_paths")
    # print(f"🗑️  Deleted {cursor.rowcount:,} project paths")
except sqlite3.OperationalError:
    pass

conn.commit()
conn.close()

print("\n✅ Database cleaned successfully!")
