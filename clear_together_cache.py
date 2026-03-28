"""
Clear Together AI API key cache and reload from .env
Run this after updating your API key in .env file
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("=" * 60)
print("Together AI API Key Cache Clearer")
print("=" * 60)

# Load .env first
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"\n✓ Loaded .env from: {env_path}")
else:
    print(f"\n✗ .env not found at: {env_path}")
    sys.exit(1)

# Check new API key
new_key = os.getenv("TOGETHER_API_KEY", "")
if new_key:
    print(f"✓ Found new TOGETHER_API_KEY in .env: {new_key[:15]}...{new_key[-5:]}")
    print(f"  Length: {len(new_key)} characters")
else:
    print("✗ TOGETHER_API_KEY not found in .env!")
    sys.exit(1)

# Clear key manager cache
from src.core.key_manager import get_key_manager
key_manager = get_key_manager()

print("\nClearing Together AI cache...")
key_manager.clear_cache("together")
print("✓ Cache cleared for 'together' provider")

# Force reload the key
print("\nReloading API key from key manager...")
refreshed_key = key_manager.get_key("together", force_refresh=True)

if refreshed_key:
    print(f"✓ Successfully loaded new API key: {refreshed_key[:15]}...{refreshed_key[-5:]}")
    
    if refreshed_key == new_key:
        print("\n✅ SUCCESS! API key matches .env file")
        print("\nThe new API key is now active. Restart Cortex IDE to use it.")
    else:
        print("\n⚠️ WARNING: Loaded key doesn't match .env!")
        print(f"   .env has: {new_key[:20]}...")
        print(f"   Loaded:   {refreshed_key[:20]}...")
        print("\nTry removing the old key from Windows Credential Manager:")
        print("   1. Open 'Credential Manager' in Windows Control Panel")
        print("   2. Look for 'Cortex/together' or similar entry")
        print("   3. Delete it")
        print("   4. Run this script again")
else:
    print("✗ Failed to load API key from key manager!")
    print("\nCheck that:")
    print("   1. .env file contains TOGETHER_API_KEY=tgp_...")
    print("   2. The key is valid (starts with 'tgp_v1_')")

print("\n" + "=" * 60)
