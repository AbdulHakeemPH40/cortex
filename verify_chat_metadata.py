"""Verify chat metadata includes message_count."""
import sqlite3
from pathlib import Path

db_path = Path.home() / ".cortex" / "cortex.db"

print(f"🔍 Checking Chat Metadata")
print("=" * 60)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Get most recent conversation with message count
cursor.execute("""
    SELECT c.id, c.conversation_id, c.title, 
           COUNT(m.id) as message_count,
           c.created_at
    FROM conversations c
    LEFT JOIN chat_messages m ON c.conversation_id = m.conversation_id
    GROUP BY c.id, c.conversation_id, c.title, c.created_at
    ORDER BY c.created_at DESC
    LIMIT 5
""")

convs = cursor.fetchall()

print("\n📋 Recent Conversations with Message Counts:\n")
for i, conv in enumerate(convs, 1):
    print(f"{i}. Title: {conv[2]}")
    print(f"   Conversation ID: {conv[1]}")
    print(f"   📊 Message Count: {conv[3]} messages")
    
    # Verify by counting directly
    cursor.execute("""
        SELECT COUNT(*) FROM chat_messages 
        WHERE conversation_id = ?
    """, (conv[1],))
    
    actual_count = cursor.fetchone()[0]
    print(f"   ✅ Verified Count: {actual_count} messages")
    
    if conv[3] > 0:
        print(f"   📝 Last message preview:")
        cursor.execute("""
            SELECT role, content, timestamp 
            FROM chat_messages 
            WHERE conversation_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
        """, (conv[1],))
        
        last_msg = cursor.fetchone()
        from datetime import datetime
        msg_time = datetime.fromtimestamp(last_msg[2] / 1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"      [{last_msg[0]}] {last_msg[1][:80]}... at {msg_time}")
    
    print()

conn.close()
