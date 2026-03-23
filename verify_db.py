import sqlite3
from pathlib import Path

db_path = Path.home() / ".cortex" / "cortex.db"

if not db_path.exists():
    print(f"ERROR: Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("=== Tables in Database ===")
for table in tables:
    print(f"  ✓ {table[0]}")

# Check conversations structure
print("\n=== Conversations Table ===")
cursor.execute("PRAGMA table_info(conversations)")
columns = cursor.fetchall()
for col in columns:
    print(f"  {col[1]} ({col[2]})")

# Count records
cursor.execute("SELECT COUNT(*) FROM conversations")
count = cursor.fetchone()[0]
print(f"\nTotal conversations: {count}")

# Show sample
print("\n=== Sample Conversations (First 5) ===")
cursor.execute("SELECT conversation_id, title, created_at FROM conversations LIMIT 5")
for row in cursor.fetchall():
    print(f"  - {row[1]}")
    print(f"    ID: {row[0]}")
    print(f"    Created: {row[2]}\n")

conn.close()

print("\n✅ Database check complete!")
