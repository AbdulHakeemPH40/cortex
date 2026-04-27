"""
Example: Using Cortex API Client with your website (logic-practice.com)

This demonstrates the complete authentication and LLM workflow.
"""

import asyncio
import os
from dotenv import load_dotenv

from .api_client import CortexAPIClient, APIConfig
from .auth import get_auth_manager, get_api_key_manager
from .subscription import get_subscription_manager
from .usage import get_usage_tracker


async def example_workflow():
    """Complete example of authentication → subscription check → LLM request."""
    
    # Load environment variables from .env file
    load_dotenv()
    
    # 1. Initialize API client pointing to your website
    config = APIConfig(
        base_url="https://logic-practice.com/api",
        timeout=30
    )
    api_client = CortexAPIClient(config)
    
    try:
        # 2. Authenticate user
        print("Logging in...")
        user = await api_client.login("user@example.com", "password123")
        print(f"✓ Logged in as {user.username}")
        
        # 3. Check subscription status
        print("\nChecking subscription...")
        sub_manager = get_subscription_manager(api_client)
        is_active = await sub_manager.is_subscription_active()
        
        if not is_active:
            print("✗ No active subscription. Please upgrade.")
            return
        
        print("✓ Subscription active")
        
        # 4. Check if can make request
        can_request, reason = await sub_manager.can_make_request(model='gpt-4')
        if not can_request:
            print(f"✗ Cannot make request: {reason}")
            return
        
        print(f"✓ Can use GPT-4")
        
        # 5. Send LLM request through your backend
        print("\nSending LLM request...")
        messages = [
            {"role": "user", "content": "Write a Python function to calculate fibonacci"}
        ]
        
        response = await api_client.send_llm_request(
            messages=messages,
            model='gpt-4',
            temperature=0.7
        )
        
        print(f"✓ Response received ({response.tokens_used} tokens)")
        print(f"\n{response.content}")
        
        # 6. Track usage
        usage_tracker = get_usage_tracker(api_client)
        await usage_tracker.track_request(
            model=response.model,
            tokens_used=response.tokens_used,
            cost=response.cost,
            operation='code_gen'
        )
        
        print(f"\n✓ Usage tracked (${response.cost:.4f})")
        
        # 7. Show usage summary
        summary = usage_tracker.get_usage_summary(days=7)
        print(f"\n📊 This week: {summary['total_requests']} requests, ${summary['total_cost']:.2f}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        # Cleanup
        await api_client.close()


async def example_streaming():
    """Example of streaming LLM response."""
    
    config = APIConfig(base_url="https://logic-practice.com/api")
    api_client = CortexAPIClient(config)
    
    try:
        # Login first
        await api_client.login("user@example.com", "password123")
        
        # Stream response
        messages = [{"role": "user", "content": "Explain quantum computing"}]
        
        print("Streaming response...\n")
        async for chunk in api_client.stream_llm_request(messages, model='gpt-4'):
            print(chunk, end='', flush=True)
        
        print("\n\n✓ Streaming complete")
    
    finally:
        await api_client.close()


if __name__ == "__main__":
    # Run example
    asyncio.run(example_workflow())
