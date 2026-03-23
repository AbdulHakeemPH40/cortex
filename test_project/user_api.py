#!/usr/bin/env python3
"""Real-world test: API endpoint with multiple bugs."""

from typing import List, Dict
import json

class UserAPI:
    """Simulated user API endpoint."""
    
    def __init__(self):
        self.users = [
            {"id": 1, "name": "Alice", "email": "alice@example.com", "active": True},
            {"id": 2, "name": "Bob", "email": "bob@example.com", "active": False},
            {"id": 3, "name": "Charlie", "email": "charlie@example.com", "active": True}
        ]
    
    def get_users(self, active_only: bool = False) -> List[Dict]:
        """Get all users or only active users."""
        # BUG: Filter logic is inverted
        # FIX: Return active users when active_only=True
        if active_only:
            return [u for u in self.users if u['active']]
        return self.users
    
    def get_user_by_id(self, user_id: int) -> Dict:
        """Get single user by ID."""
        # BUG: Returns wrong user (off-by-one index)
        # FIX: Search for user by ID instead of using ID as index
        for user in self.users:
            if user["id"] == user_id:
                return user
        raise ValueError(f"User with ID {user_id} not found")
    
    def create_user(self, name: str, email: str) -> Dict:
        """Create new user."""
        # BUG: Doesn't validate email format
        # BUG: ID generation is wrong
        # FIX: Validate email format
        if not self._is_valid_email(email):
            raise ValueError(f"Invalid email format: {email}")
        
        # FIX: Validate name
        if not name or not name.strip():
            raise ValueError("Name cannot be empty")
        
        # FIX: Check for duplicate email
        if any(user["email"].lower() == email.lower() for user in self.users):
            raise ValueError(f"Email already exists: {email}")
        
        # FIX: Generate correct ID (max existing ID + 1)
        max_id = max([user["id"] for user in self.users]) if self.users else 0
        new_id = max_id + 1
        
        new_user = {
            "id": new_id,
            "name": name.strip(),
            "email": email.lower(),  # Store email in lowercase
            "active": True
        }
        self.users.append(new_user)
        return new_user
    
    def _is_valid_email(self, email: str) -> bool:
        """Validate email format."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def delete_user(self, user_id: int) -> bool:
        """Delete user by ID."""
        # BUG: Doesn't actually remove, just marks inactive
        # FIX: Actually remove user from list
        for i, user in enumerate(self.users):
            if user["id"] == user_id:
                del self.users[i]
                return True
        return False
    
    def search_users(self, query: str) -> List[Dict]:
        """Search users by name."""
        # BUG: Case-sensitive search (should be case-insensitive)
        # FIX: Make search case-insensitive
        query_lower = query.lower()
        return [u for u in self.users if query_lower in u['name'].lower()]
    
    def to_json(self, users: List[Dict]) -> str:
        """Convert users list to JSON string."""
        # BUG: Missing ensure_ascii=False for international names
        # FIX: Add ensure_ascii=False and proper formatting
        return json.dumps(users, ensure_ascii=False, indent=2)
    
    def update_user(self, user_id: int, name: str = None, email: str = None, active: bool = None) -> Dict:
        """Update user information."""
        for user in self.users:
            if user["id"] == user_id:
                if name is not None:
                    if not name or not name.strip():
                        raise ValueError("Name cannot be empty")
                    user["name"] = name.strip()
                
                if email is not None:
                    if not self._is_valid_email(email):
                        raise ValueError(f"Invalid email format: {email}")
                    # Check for duplicate email (excluding current user)
                    if any(u["email"].lower() == email.lower() and u["id"] != user_id for u in self.users):
                        raise ValueError(f"Email already exists: {email}")
                    user["email"] = email.lower()
                
                if active is not None:
                    user["active"] = active
                
                return user
        raise ValueError(f"User with ID {user_id} not found")
    
    def get_active_user_count(self) -> int:
        """Get count of active users."""
        return len([u for u in self.users if u['active']])


def main():
    """Test the API."""
    api = UserAPI()
    
    print("All users:")
    print(api.get_users())
    
    print("\nActive users only:")
    print(api.get_users(active_only=True))
    
    print("\nGet user by ID 2:")
    print(api.get_user_by_id(2))
    
    print("\nCreate new user:")
    new_user = api.create_user("David", "david@example.com")
    print(new_user)
    
    print("\nSearch for 'ali':")
    print(api.search_users("ali"))  # Should find Alice but won't (case-sensitive)
    
    print("\nActive user count:")
    print(api.get_active_user_count())
    
    print("\nUpdate user ID 1:")
    updated = api.update_user(1, name="Alice Updated", email="alice.updated@example.com")
    print(updated)
    
    print("\nAll users after update:")
    print(api.get_users())


if __name__ == "__main__":
    main()
