"""Check SQLite database for chats."""
from src.core.chat_history import get_chat_history

# Get chat history manager
history = get_chat_history()

# Try different project path formats
project_paths = [
    'project_cortex_chats_40582b0a',
    'project_C:\\Users\\Hakeem1\\OneDrive\\Desktop\\Cortex_Ai_Agent\\Cortex',
    'project_cortex'
]

for project_path in project_paths:
    print(f"\n=== Checking: {project_path} ===")
    conversations = history.get_conversations(project_path)
    
    if conversations:
        print(f"✓ Found {len(conversations)} conversations")
        for i, conv in enumerate(conversations[:10]):  # Show first 10
            msg_count = len(history.get_messages(conv['conversation_id']))
            print(f"  {i+1}. {conv['title']} ({msg_count} messages)")
            print(f"     Created: {conv.get('created_at', 'N/A')}")
        
        if len(conversations) > 10:
            print(f"  ... and {len(conversations) - 10} more")
    else:
        print("✗ No chats found")

# Also check total database stats
print("\n=== Database Stats ===")
import sqlite3
from pathlib import Path

db_path = Path.home() / ".cortex" / "cortex.db"
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Count conversations
    cursor.execute("SELECT COUNT(*) FROM conversations")
    conv_count = cursor.fetchone()[0]
    print(f"Total conversations in DB: {conv_count}")
    
    # Count messages
    cursor.execute("SELECT COUNT(*) FROM messages")
    msg_count = cursor.fetchone()[0]
    print(f"Total messages in DB: {msg_count}")
    
    # Show recent conversations
    cursor.execute("""
        SELECT conversation_id, title, created_at 
        FROM conversations 
        ORDER BY created_at DESC 
        LIMIT 5
    """)
    print("\n=== 5 Most Recent Chats ===")
    for row in cursor.fetchall():
        print(f"- {row[1]} (Created: {row[2]})")
    
    conn.close()
else:
    print(f"✗ Database not found at {db_path}")
