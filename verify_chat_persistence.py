import sqlite3
import os

db_path = os.path.expanduser('~/.cortex/cortex.db')

print("=" * 60)
print("VERIFYING CHAT PERSISTENCE")
print("=" * 60)

print(f"\nDatabase path: {db_path}")
print(f"Database exists: {os.path.exists(db_path)}")
print(f"Database size: {os.path.getsize(db_path) / 1024:.2f} KB")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
print(f"\nTables in database: {tables}")

# Check conversations
if 'conversations' in tables:
    cursor.execute("SELECT COUNT(*) FROM conversations")
    conv_count = cursor.fetchone()[0]
    print(f"\nTotal conversations: {conv_count}")
    
    if conv_count > 0:
        cursor.execute("SELECT conversation_id, project_path, title, created_at FROM conversations LIMIT 5")
        print("\nRecent conversations:")
        for row in cursor.fetchall():
            print(f"  - {row[2]} ({row[1]})")
            print(f"    ID: {row[0]}")
            print(f"    Created: {row[3]}")
            print()
        
        # Check messages
        cursor.execute("SELECT COUNT(*) FROM chat_messages")
        msg_count = cursor.fetchone()[0]
        print(f"Total messages: {msg_count}")
    else:
        print("\n⚠️  No conversations found in database")
        print("This means either:")
        print("  1. You haven't chatted yet, OR")
        print("  2. Chat saving is not working")
else:
    print("\n❌ conversations table not found!")

conn.close()

print("\n" + "=" * 60)
print("MEMORY FILES CHECK")
print("=" * 60)

import glob
memory_files = glob.glob(os.path.expanduser('~/.cortex/projects/*/memory/*.md'))
print(f"\nMemory files found: {len(memory_files)}")

if memory_files:
    for f in memory_files[:5]:
        print(f"  - {os.path.basename(f)}")
else:
    print("⚠️  No memory files found")
    print("This is normal if you haven't had long conversations yet")

print("\n" + "=" * 60)
print("CONCLUSION")
print("=" * 60)

if 'conversations' in tables and conv_count > 0:
    print("✅ Chat persistence IS working!")
    print("✅ Your conversations are saved to SQLite database")
    print("✅ They will be available when you reopen the IDE")
elif 'conversations' in tables:
    print("⚠️  Database structure exists but no conversations yet")
    print("✅ System is ready to save conversations")
    print("📝 Start chatting and they will be saved automatically")
else:
    print("❌ Database structure not found")
    print("❌ Chat persistence may not be working")
