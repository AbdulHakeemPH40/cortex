"""Check Cortex IDE database for chat history."""
import sqlite3
from pathlib import Path

# Database location
db_path = Path.home() / ".cortex" / "cortex.db"

print(f"📊 Checking Cortex IDE Database")
print(f"Location: {db_path}")
print("=" * 60)

try:
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print(f"\n📁 Tables found: {len(tables)}")
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"   - {table_name}: {count} records")
    
    # Check for conversations table (might be named differently)
    conversation_tables = [t[0] for t in tables if 'conversation' in t[0].lower() or 'chat' in t[0].lower()]
    
    if conversation_tables:
        print(f"\n💬 Conversation/Chat tables: {conversation_tables}")
        
        for table_name in conversation_tables:
            print(f"\n📋 Recent entries from {table_name}:")
            try:
                cursor.execute(f"SELECT * FROM {table_name} ORDER BY rowid DESC LIMIT 5")
                rows = cursor.fetchall()
                
                if rows:
                    # Get column names
                    columns = [desc[0] for desc in cursor.description]
                    print(f"   Columns: {columns}")
                    
                    for i, row in enumerate(rows, 1):
                        print(f"\n   Entry {i}:")
                        for col, val in zip(columns, row):
                            if isinstance(val, str) and len(val) > 100:
                                val = val[:100] + "..."
                            print(f"      {col}: {val}")
                else:
                    print("   No entries found")
            except Exception as e:
                print(f"   Error reading {table_name}: {e}")
    else:
        print("\n⚠️ No conversation/chat tables found")
        print("   The database might use a different schema or store chats elsewhere")
    
    conn.close()
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
