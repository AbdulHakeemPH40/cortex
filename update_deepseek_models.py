#!/usr/bin/env python3
"""Update aichat.html with DeepSeek models"""

import re

file_path = r"c:\Users\Hakeem1\OneDrive\Desktop\Cortex_Ai_Agent\Cortex\src\ui\html\ai_chat\aichat.html"

# Read file
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Old section to replace
old_section = """<!-- DeepSeek - Direct Access -->
                                    <div class="dropdown-header">DeepSeek Models</div>
                                    <div class="dropdown-item" data-value="deepseek-chat" data-provider="deepseek">
                                        <div class="item-icon deepseek-icon">
                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                                        </div>
                                        <div class="item-text">
                                            <span>DeepSeek V3</span>
                                        </div>
                                    </div>
                                    
                                    <div class="dropdown-divider"></div>
                                    <div class="dropdown-header">⚡ Select Code Writing Model</div>
                                    
                                    <div class="dropdown-divider"></div>
                                    <div class="dropdown-header">Together AI Models</div>
                                    
                                    <!-- Kimi K2.5 with streaming compatibility layer -->
                                    <div class="dropdown-item" data-value="moonshotai/Kimi-K2.5" data-provider="together" data-perf="9.0">"""

# New section with all DeepSeek models
new_section = """<!-- DeepSeek - Direct API Access -->
                                    <div class="dropdown-header">DeepSeek Models (Direct API)</div>
                                    
                                    <div class="dropdown-item" data-value="deepseek-chat" data-provider="deepseek" data-perf="9.5">
                                        <div class="item-icon deepseek-icon">
                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                                        </div>
                                        <div class="item-text">
                                            <span>DeepSeek Chat</span>
                                            <span class="tag recommended">Fast</span>
                                        </div>
                                    </div>
                                    
                                    <div class="dropdown-item" data-value="deepseek-coder" data-provider="deepseek" data-perf="9.3">
                                        <div class="item-icon deepseek-icon">
                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                                        </div>
                                        <div class="item-text">
                                            <span>DeepSeek Coder</span>
                                            <span class="tag">Code</span>
                                        </div>
                                    </div>
                                    
                                    <div class="dropdown-item" data-value="deepseek-reasoner" data-provider="deepseek" data-perf="9.7">
                                        <div class="item-icon deepseek-icon">
                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                                        </div>
                                        <div class="item-text">
                                            <span>DeepSeek R1 (Reasoner)</span>
                                            <span class="tag">Reasoning</span>
                                        </div>
                                    </div>
                                    
                                    <div class="dropdown-divider"></div>
                                    <div class="dropdown-header">Together AI (Hosted DeepSeek)</div>
                                    
                                    <!-- Kimi K2.5 with streaming compatibility layer -->
                                    <div class="dropdown-item" data-value="moonshotai/Kimi-K2.5" data-provider="together" data-perf="9.0">"""

# Replace
if old_section in content:
    content = content.replace(old_section, new_section)
    
    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ Successfully updated aichat.html with DeepSeek models!")
    print("   Added: DeepSeek Chat, DeepSeek Coder, DeepSeek R1 (Reasoner)")
else:
    print("❌ Could not find the target section in aichat.html")
    print("   The file may have already been modified or has different formatting")
