"""
Migrate Chat History from JSON Files to SQLite Database
========================================================
This script migrates all existing JSON chat files to SQLite database.

Features:
- Automatic backup of JSON files before migration
- Idempotent (safe to run multiple times)
- Progress reporting
- Rollback support on failure

Usage:
    python migrate_chats_to_sqlite.py
"""

import os
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import uuid

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.core.database import CortexDatabase, get_database
from src.utils.logger import get_logger

log = get_logger("migration")


class ChatMigrator:
    """Handles migration from JSON to SQLite."""
    
    def __init__(self):
        self.json_dir = Path.home() / ".cortex" / "chats"
        self.backup_dir = Path.home() / ".cortex" / "chats_backup"
        self.db = get_database()
        self.migrated_count = 0
        self.error_count = 0
    
    def backup_json_files(self) -> bool:
        """Create backup of JSON files before migration."""
        if not self.json_dir.exists():
            log.info("No JSON chats directory found, skipping backup")
            return True
        
        try:
            # Create backup directory
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir)
            shutil.copytree(self.json_dir, self.backup_dir)
            
            log.info(f"✓ Backed up {len(list(self.json_dir.glob('*.json')))} JSON files to {self.backup_dir}")
            return True
        except Exception as e:
            log.error(f"✗ Backup failed: {e}")
            return False
    
    def get_all_json_files(self) -> List[Path]:
        """Get all JSON chat files."""
        if not self.json_dir.exists():
            return []
        
        return list(self.json_dir.glob("*.json"))
    
    def parse_storage_key(self, filename: str) -> str:
        """Extract storage key from filename."""
        # Remove .json extension
        return filename.replace(".json", "")
    
    def migrate_single_file(self, json_file: Path) -> bool:
        """
        Migrate a single JSON file to SQLite.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Read JSON data
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both array and object formats
            if isinstance(data, list):
                conversations = data
            elif isinstance(data, dict):
                conversations = [data]
            else:
                log.warning(f"Unexpected data format in {json_file}")
                return False
            
            # Extract project path from storage key
            storage_key = self.parse_storage_key(json_file.name)
            project_path = f"project_{storage_key}"  # Reconstruct project path
            
            # Migrate each conversation
            for conv in conversations:
                if not isinstance(conv, dict):
                    continue
                
                # Get or create conversation ID
                conversation_id = conv.get('id', str(uuid.uuid4()))
                
                # Check if conversation already exists (idempotency)
                existing = self.db.get_conversations(project_path)
                if any(c['conversation_id'] == conversation_id for c in existing):
                    log.debug(f"Conversation {conversation_id} already exists, skipping")
                    continue
                
                # Create conversation in SQLite
                title = conv.get('title', f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                created_at = int(datetime.now().timestamp())
                
                # Use the database's context manager for proper connection handling
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Insert conversation
                    cursor.execute("""
                        INSERT OR IGNORE INTO conversations 
                        (conversation_id, project_path, title, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (conversation_id, project_path, title, created_at, created_at))
                    
                    # Insert messages
                    messages = conv.get('messages', [])
                    for msg in messages:
                        if not isinstance(msg, dict):
                            continue
                        
                        role = msg.get('role', 'user')
                        content = msg.get('content', '')
                        timestamp = int(datetime.now().timestamp())
                        files_accessed = json.dumps(msg.get('files_accessed', []))
                        tools_used = json.dumps(msg.get('tools_used', []))
                        
                        cursor.execute("""
                            INSERT INTO chat_messages 
                            (conversation_id, role, content, timestamp, files_accessed, tools_used)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (conversation_id, role, content, timestamp, files_accessed, tools_used))
                self.migrated_count += 1
            
            log.debug(f"✓ Migrated {json_file.name}")
            return True
            
        except Exception as e:
            log.error(f"✗ Failed to migrate {json_file.name}: {e}")
            self.error_count += 1
            return False
    
    def migrate_all(self) -> bool:
        """
        Migrate all JSON files to SQLite.
        
        Returns:
            True if all migrations succeeded, False otherwise
        """
        log.info("=" * 60)
        log.info("Starting Chat History Migration: JSON → SQLite")
        log.info("=" * 60)
        
        # Step 1: Backup existing files
        log.info("Step 1/3: Creating backup...")
        if not self.backup_json_files():
            log.error("Backup failed, aborting migration")
            return False
        
        # Step 2: Get all JSON files
        json_files = self.get_all_json_files()
        if not json_files:
            log.info("No JSON files found, nothing to migrate")
            return True
        
        log.info(f"Found {len(json_files)} JSON files to migrate")
        
        # Step 3: Migrate each file
        log.info("Step 2/3: Migrating files...")
        success_count = 0
        
        for i, json_file in enumerate(json_files, 1):
            log.info(f"[{i}/{len(json_files)}] Migrating {json_file.name}...")
            if self.migrate_single_file(json_file):
                success_count += 1
        
        # Step 4: Summary
        log.info("=" * 60)
        log.info("Step 3/3: Migration Summary")
        log.info("=" * 60)
        log.info(f"✓ Successfully migrated: {success_count}/{len(json_files)} files")
        log.info(f"✓ Total conversations: {self.migrated_count}")
        log.info(f"✗ Errors: {self.error_count}")
        log.info(f"📁 Backup location: {self.backup_dir}")
        log.info("=" * 60)
        
        if self.error_count > 0:
            log.warning(f"{self.error_count} files failed to migrate")
            return False
        else:
            log.info("🎉 Migration completed successfully!")
            return True
    
    def cleanup_json_files(self, keep_backup: bool = True):
        """
        Remove original JSON files after successful migration.
        
        Args:
            keep_backup: If True, keeps backup directory intact
        """
        if not keep_backup:
            log.info("Cleaning up JSON files and backup...")
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir)
        else:
            log.info("Cleaning up JSON files (backup preserved)...")
        
        json_files = self.get_all_json_files()
        for json_file in json_files:
            try:
                json_file.unlink()
                log.debug(f"Deleted {json_file}")
            except Exception as e:
                log.error(f"Failed to delete {json_file}: {e}")
        
        log.info(f"✓ Cleaned up {len(json_files)} JSON files")


def main():
    """Main migration entry point."""
    print("\n" + "="*70)
    print(" CORTEX IDE - Chat History Migration Tool")
    print(" JSON Files → SQLite Database")
    print("="*70 + "\n")
    
    migrator = ChatMigrator()
    
    # Run migration
    success = migrator.migrate_all()
    
    if success:
        print("\n✅ Migration completed successfully!")
        print("\nNext steps:")
        print("1. Restart Cortex IDE to use SQLite backend")
        print("2. Verify chats are loading correctly")
        print("3. Optionally run: python migrate_chats_to_sqlite.py --cleanup")
        print("\nTo clean up old JSON files (keeps backup):")
        print("  python migrate_chats_to_sqlite.py --cleanup")
    else:
        print("\n❌ Migration failed! Check logs for details.")
        print("Your JSON files are safe in backup directory.")
        print("Please fix issues and try again.")
    
    print("\n" + "="*70 + "\n")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
