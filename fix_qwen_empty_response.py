"""
Fix Qwen 3.5 Empty Response Issue
Test different parameters to get Qwen 3.5 working
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("=" * 70)
print("QWEN 3.5 RESPONSE FIX TEST")
print("=" * 70)

from dotenv import load_dotenv
load_dotenv(project_root / ".env")
api_key = os.getenv("TOGETHER_API_KEY", "").strip()

from together import Together
client = Together(api_key=api_key)

test_prompts = [
    ("Simple greeting", [{"role": "user", "content": "Hello!"}]),
    ("With system prompt", [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "Hi"}]),
    ("Direct question", [{"role": "user", "content": "What is 2+2?"}]),
    ("Story starter", [{"role": "user", "content": "Once upon a time"}]),
]

configs = [
    {"temp": 0.7, "max_tokens": 100},
    {"temp": 0.3, "max_tokens": 50},
    {"temp": 1.0, "max_tokens": 200},
]

for config in configs:
    print(f"\n{'='*60}")
    print(f"Config: temperature={config['temp']}, max_tokens={config['max_tokens']}")
    print('='*60)
    
    for test_name, messages in test_prompts:
        try:
            response = client.chat.completions.create(
                model="Qwen/Qwen3.5-397B-A17B",
                messages=messages,
                temperature=config['temp'],
                max_tokens=config['max_tokens']
            )
            
            content = response.choices[0].message.content
            tokens = response.usage.total_tokens
            
            if content.strip():
                print(f"✓ {test_name}: '{content[:50]}...' ({tokens} tokens)")
            else:
                print(f"✗ {test_name}: EMPTY ({tokens} tokens)")
                
        except Exception as e:
            print(f"✗ {test_name}: ERROR - {str(e)[:50]}")

print("\n" + "=" * 70)
print("\nConclusion:")
print("If ALL tests show empty responses, the model itself has an issue.")
print("If SOME tests work, we need to adjust Cortex's parameters.")
print("=" * 70)
