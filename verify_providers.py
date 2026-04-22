"""
Cortex AI Agent - Provider Configuration Verification
Run this script to verify all providers are properly configured.

Usage: python verify_providers.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✓ Loaded .env from: {env_path}\n")
else:
    print(f"⚠ .env file not found at: {env_path}")
    print("  Create from .env.example first!\n")

# Provider configuration check
providers = {
    "Mistral AI": {
        "vars": ["MISTRAL_API_KEY"],
        "required": True,
        "url": "https://console.mistral.ai/api-keys"
    },
    "OpenAI": {
        "vars": ["OPENAI_API_KEY"],
        "required": False,
        "url": "https://platform.openai.com/api-keys"
    },
    "Anthropic (Claude)": {
        "vars": ["ANTHROPIC_API_KEY"],
        "required": False,
        "url": "https://console.anthropic.com/settings/keys"
    },
    "SiliconFlow (Vision)": {
        "vars": ["SILICONFLOW_API_KEY"],
        "required": False,
        "url": "https://cloud.siliconflow.cn/"
    },
    "Google Gemini": {
        "vars": ["GOOGLE_API_KEY"],
        "required": False,
        "url": "https://aistudio.google.com/apikey"
    },
    "AWS Bedrock": {
        "vars": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"],
        "required": False,
        "url": "https://aws.amazon.com/bedrock/"
    },
    "Google Vertex AI": {
        "vars": ["GOOGLE_APPLICATION_CREDENTIALS", "CLOUD_ML_REGION"],
        "required": False,
        "url": "https://cloud.google.com/vertex-ai"
    },
    "Azure Foundry": {
        "vars": ["ANTHROPIC_FOUNDRY_API_KEY"],
        "required": False,
        "url": "https://azure.microsoft.com/"
    },
    "Groq": {
        "vars": ["GROQ_API_KEY"],
        "required": False,
        "url": "https://console.groq.com/"
    },
    "Together AI": {
        "vars": ["TOGETHER_API_KEY"],
        "required": False,
        "url": "https://api.together.ai/"
    },
    "Qwen/Alibaba": {
        "vars": ["QWEN_API_KEY"],
        "required": False,
        "url": "https://dashscope.console.aliyun.com/"
    },
    "XAI (Grok)": {
        "vars": ["XAI_API_KEY"],
        "required": False,
        "url": "https://console.x.ai/"
    }
}

print("=" * 60)
print("  Cortex AI Agent - Provider Configuration Report")
print("=" * 60)
print()

configured_count = 0
total_count = len(providers)

for provider_name, config in providers.items():
    env_vars = config["vars"]
    required = config["required"]
    url = config["url"]
    
    # Check if all required env vars are set
    is_configured = all(os.getenv(var) for var in env_vars)
    
    if is_configured:
        configured_count += 1
        status = "✓"
        color = "Green"
    else:
        status = "✗"
        color = "Red"
    
    # Print provider status
    print(f"{status} {provider_name}")
    
    if required:
        print(f"    Status: {'CONFIGURED' if is_configured else 'REQUIRED ⚠'}")
    else:
        print(f"    Status: {'CONFIGURED' if is_configured else 'Optional'}")
    
    # Show which variables are set/missing
    for var in env_vars:
        value = os.getenv(var)
        if value:
            # Show first 10 chars for security
            masked = value[:10] + "..." if len(value) > 10 else "***"
            print(f"    • {var}: {masked}")
        else:
            print(f"    • {var}: <not set>")
    
    print(f"    Get key: {url}")
    print()

print("=" * 60)
print(f"  Summary: {configured_count}/{total_count} providers configured")
print("=" * 60)
print()

if configured_count == 0:
    print("⚠ WARNING: No providers configured!")
    print("  The app will run in Mock mode (no real AI responses)")
    print()
    print("  To enable AI features:")
    print("  1. Copy .env.example to .env")
    print("  2. Add at least one API key to .env")
    print("  3. Restart Cortex")
    print()
elif configured_count == 1:
    print("✓ One provider configured - ready for basic AI features")
else:
    print(f"✓ {configured_count} providers configured - excellent!")

print()
print("For detailed setup instructions, see:")
print("  • .env.example - Template with all provider keys")
print("  • BUILD_CHECKLIST.md - Complete build & release guide")
print()

# Test import of provider modules
print("Testing provider module imports...")
try:
    from src.ai.providers.mistral_provider import MistralProvider
    print("  ✓ MistralProvider imported successfully")
except ImportError as e:
    print(f"  ✗ MistralProvider import failed: {e}")

try:
    from src.ai.providers.siliconflow_provider import SiliconFlowProvider
    print("  ✓ SiliconFlowProvider imported successfully")
except ImportError as e:
    print(f"  ✗ SiliconFlowProvider import failed: {e}")

try:
    from src.agent.src.utils.auth import get_configured_providers
    providers_list = get_configured_providers()
    print(f"  ✓ Auth system loaded: {len(providers_list)} providers detected")
except ImportError as e:
    print(f"  ✗ Auth system import failed: {e}")

print()
print("Verification complete!")
