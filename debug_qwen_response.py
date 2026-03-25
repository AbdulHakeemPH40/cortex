"""
Debug Qwen 3.5 Response Issue
This shows the raw response from Qwen 3.5 to understand the 400 error
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("=" * 70)
print("DEBUG: QWEN 3.5 RESPONSE ANALYSIS")
print("=" * 70)

from dotenv import load_dotenv
load_dotenv(project_root / ".env")
api_key = os.getenv("TOGETHER_API_KEY", "").strip()

from together import Together
client = Together(api_key=api_key)

# Test 1: Non-streaming request with full debug info
print("\n[Test 1] Non-streaming request...")
try:
    response = client.chat.completions.create(
        model="Qwen/Qwen3.5-397B-A17B",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say hello in 3 words"}
        ],
        max_tokens=50,
        temperature=0.7
    )
    
    print(f"✓ Response received")
    print(f"  Finish reason: {response.choices[0].finish_reason}")
    print(f"  Content: '{response.choices[0].message.content}'")
    print(f"  Tokens: {response.usage.total_tokens}")
except Exception as e:
    print(f"✗ Error: {type(e).__name__}: {e}")

# Test 2: Streaming request (like Cortex uses)
print("\n[Test 2] Streaming request...")
try:
    response = client.chat.completions.create(
        model="Qwen/Qwen3.5-397B-A17B",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say hello in 3 words"}
        ],
        max_tokens=50,
        temperature=0.7,
        stream=True
    )
    
    chunks = []
    for chunk in response:
        if hasattr(chunk, 'choices') and chunk.choices:
            finish = chunk.choices[0].finish_reason
            delta = chunk.choices[0].delta
            content = delta.content if hasattr(delta, 'content') else None
            
            chunks.append({
                'finish': finish,
                'content': content
            })
            
            if content:
                print(f"  Chunk: '{content}'")
            if finish:
                print(f"  Finish: {finish}")
                break
    
    print(f"\n✓ Total chunks: {len(chunks)}")
    print(f"  Combined: '{''.join([c['content'] or '' for c in chunks])}'")
    
except Exception as e:
    print(f"✗ Error: {type(e).__name__}: {e}")

# Test 3: Try WITHOUT system message
print("\n[Test 3] Without system message...")
try:
    response = client.chat.completions.create(
        model="Qwen/Qwen3.5-397B-A17B",
        messages=[
            {"role": "user", "content": "Say hello in 3 words"}
        ],
        max_tokens=50,
        temperature=0.7
    )
    
    print(f"✓ Response: '{response.choices[0].message.content}'")
except Exception as e:
    print(f"✗ Error: {type(e).__name__}: {e}")

print("\n" + "=" * 70)
