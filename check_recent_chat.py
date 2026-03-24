"""Check most recent chat timestamp in Cortex database."""
import sqlite3
from pathlib import Path
from datetime import datetime

# Database location
db_path = Path.home() / ".cortex" / "cortex.db"

print(f"📊 Most Recent Chat Activity")
print(f"Database: {db_path}")
print("=" * 60)

try:
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Get most recent conversation
    cursor.execute("""
        SELECT id, conversation_id, project_path, title, created_at, updated_at 
        FROM conversations 
        ORDER BY created_at DESC 
        LIMIT 1
    """)
    
    latest_conv = cursor.fetchone()
    
    if latest_conv:
        print("\n💬 MOST RECENT CONVERSATION:")
        print(f"   ID: {latest_conv[0]}")
        print(f"   Conversation ID: {latest_conv[1]}")
        print(f"   Project: {latest_conv[2]}")
        print(f"   Title: {latest_conv[3]}")
        
        # Convert timestamps
        created_ms = latest_conv[4]
        updated_ms = latest_conv[5]
        
        created_dt = datetime.fromtimestamp(created_ms / 1000)
        updated_dt = datetime.fromtimestamp(updated_ms / 1000)
        
        print(f"\n   📅 Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"      (Unix ms: {created_ms})")
        print(f"   🕐 Updated: {updated_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"      (Unix ms: {updated_ms})")
        
        # Get messages for this conversation
        cursor.execute("""
            SELECT role, content, timestamp 
            FROM chat_messages 
            WHERE conversation_id = ? 
            ORDER BY timestamp DESC
        """, (latest_conv[1],))
        
        messages = cursor.fetchall()
        
        print(f"\n💬 Messages in this conversation: {len(messages)}")
        
        if messages:
            latest_msg = messages[0]
            msg_time_ms = latest_msg[2]
            msg_time_dt = datetime.fromtimestamp(msg_time_ms / 1000)
            
            print(f"\n📝 LATEST MESSAGE:")
            print(f"   Role: {latest_msg[0]}")
            print(f"   Content preview: {latest_msg[1][:100]}...")
            print(f"   ⏰ Timestamp: {msg_time_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"      (Unix ms: {msg_time_ms})")
            
            # Calculate time differences
            now = datetime.now()
            time_diff = now - msg_time_dt
            
            print(f"\n⏱️  Time elapsed since last message:")
            print(f"   {time_diff.seconds} seconds ago")
            print(f"   {time_diff.seconds // 60} minutes ago")
        
        # Overall statistics
        cursor.execute("SELECT COUNT(*) FROM conversations")
        total_conv = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM chat_messages")
        total_msgs = cursor.fetchone()[0]
        
        print(f"\n📊 OVERALL STATISTICS:")
        print(f"   Total conversations: {total_conv}")
        print(f"   Total messages: {total_msgs}")
        print(f"   Average messages per conversation: {total_msgs / total_conv:.1f}")
        
    else:
        print("No conversations found!")
    
    conn.close()
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
