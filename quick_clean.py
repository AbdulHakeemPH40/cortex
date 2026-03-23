"""Quick chat cleanup - run this directly."""
import sqlite3
from pathlib import Path

# Connect to database
db_path = Path.home() / ".cortex" / "cortex.db"
print(f"Database: {db_path}")
print("Connecting...")

try:
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Delete messages
    print("\nDeleting all messages...")
    cursor.execute("DELETE FROM chat_messages")
    msg_count = cursor.rowcount
    print(f"✓ Deleted {msg_count:,} messages")
    
    # Delete conversations
    print("Deleting all conversations...")
    cursor.execute("DELETE FROM conversations")
    conv_count = cursor.rowcount
    print(f"✓ Deleted {conv_count:,} conversations")
    
    # Save changes
    conn.commit()
    
    # Verify
    cursor.execute("SELECT COUNT(*) FROM conversations")
    final_conv = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM chat_messages")
    final_msg = cursor.fetchone()[0]
    
    print(f"\n=== RESULT ===")
    print(f"Conversations remaining: {final_conv:,}")
    print(f"Messages remaining: {final_msg:,}")
    
    if final_conv == 0 and final_msg == 0:
        print("\n✅ SUCCESS! All chats cleaned!")
    else:
        print("\n⚠️ Some data remains")
    
    conn.close()
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print("\nTry running Cortex IDE, then use the delete buttons in UI")
