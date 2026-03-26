"""
Together AI Provider for Cortex AI Agent IDE
Supports multiple models via unified API:
- Qwen/Qwen3.5-397B-A17B
- moonshotai/Kimi-K2.5
- MiniMaxAI/MiniMax-M2.5
"""

from typing import List, Dict, Any, Optional, Generator
import time
import json
import os
from src.utils.logger import get_logger
from src.core.key_manager import get_key_manager
from src.ai.providers import BaseProvider, ProviderType, ModelInfo, ChatMessage, ChatResponse

log = get_logger("together_provider")


class TogetherProvider(BaseProvider):
    """Together AI provider - supports multiple models via unified API."""
    
    def __init__(self):
        super().__init__(ProviderType.TOGETHER)
        self._api_key: Optional[str] = None
        self._client = None
        self._client_key = None
        self._key_manager = get_key_manager()
        
        # Load API key from key manager (which checks env vars and other sources)
        self._refresh_api_key()
    
    @property
    def available_models(self) -> list:
        """Return list of available models."""
        return [
            {"id": "moonshotai/Kimi-K2.5", "name": "Kimi K2.5", "context": 128000},
            {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3", "context": 128000},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1", "context": 128000},
        ]
    
    def _refresh_api_key(self, force: bool = False):
        """Refresh API key from key manager.
        
        Args:
            force: If True, always reload from key manager even if cache exists
        """
        new_key = self._key_manager.get_key("together", force_refresh=force)
        if new_key and new_key != self._api_key:
            log.info(f"[TOGETHER] Refreshed API key from key manager (length: {len(new_key)})")
            self._api_key = new_key
            self._client = None  # Force client recreation
        elif not new_key:
            log.error("[TOGETHER] Failed to get API key from key manager!")
    
    def set_api_key(self, api_key: str):
        """Set the API key."""
        if api_key != self._api_key:
            self._api_key = api_key
            self._client = None
            log.debug("Together AI API key updated")
    
    def _get_client(self):
        """Get or create Together client."""
        # CRITICAL: Refresh API key from key manager on every call
        # This ensures we always have the latest key
        self._refresh_api_key()
        
        log.debug(f"[TOGETHER] Current API key length: {len(self._api_key) if self._api_key else 0}")
        
        if self._client is None or self._client_key != self._api_key:
            try:
                from together import Together
                if not self._api_key:
                    log.error("[TOGETHER] ERROR: API key is empty!")
                    raise ValueError("API key not set for Together AI")
                
                log.debug(f"[TOGETHER] Creating Together client with key: {self._api_key[:10]}...")
                # Use httpx timeout for long operations (300 seconds)
                self._client = Together(
                    api_key=self._api_key,
                    timeout=300.0  # 5 minutes for complex operations
                )
                self._client_key = self._api_key
            except ImportError:
                raise ImportError("Together package not installed. Run: pip install together")
        return self._client
    
    def chat(self, messages: list, model: str = "deepseek-ai/DeepSeek-V3",
             temperature: float = 0.7, max_tokens: int = 4096,
             tools: Optional[List[Dict[str, Any]]] = None) -> dict:
        """Send chat completion request to Together AI."""
        start_time = time.time()
        
        try:
            client = self._get_client()
            
            # Format messages
            formatted_messages = []
            for msg in messages:
                m = {"role": msg.role, "content": msg.content}
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    m["tool_calls"] = msg.tool_calls
                if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
                    m["tool_call_id"] = msg.tool_call_id
                formatted_messages.append(m)
            
            # Build request
            kwargs = {
                "model": model,
                "messages": formatted_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                kwargs["tools"] = tools
            
            response = client.chat.completions.create(**kwargs)
            
            duration_ms = (time.time() - start_time) * 1000
            
            message = response.choices[0].message
            
            # Extract tool calls if present
            tool_calls = None
            if hasattr(message, 'tool_calls') and message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })
            
            return {
                "content": message.content or "",
                "model": model,
                "provider": "together",
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
                "duration_ms": duration_ms,
                "tool_calls": tool_calls
            }
            
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Together AI error: {e}")
            return {
                "content": "",
                "model": model,
                "provider": "together",
                "error": str(e),
                "duration_ms": (time.time() - start_time) * 1000
            }
    
    def _parse_kimi_tool_calls(self, content: str) -> tuple[str, list]:
        """Parse Kimi K2.5 tool calls from content with special tokens.
        
        Kimi uses format:
        Thinking...<|tool_calls_section_begin|> <|tool_call_begin|> functions.func_name:0 <|tool_call_argument_begin|> {...} <|tool_call_end|> <|tool_calls_section_end|>
        
        Returns:
            tuple of (cleaned_content, list_of_tool_calls)
        """
        import re
        
        tool_calls = []
        cleaned_content = content
        
        # Check if content contains tool call markers
        has_tool_markers = '<|tool_calls_section_begin|>' in content or '<|tool_call_begin|>' in content
        log.info(f"[TOGETHER] Parsing Kimi tool calls, has_markers={has_tool_markers}, content_len={len(content)}")
        
        if not has_tool_markers:
            # No markers found, still need to strip any leftover markers
            cleaned_content = self._strip_tool_call_markers(cleaned_content)
            return cleaned_content, tool_calls
        
        # Pattern to match tool calls section
        tool_section_pattern = r'<\|tool_calls_section_begin\|>(.*?)<\|tool_calls_section_end\|>'
        
        # Also try alternative pattern without closing tag
        alt_pattern = r'<\|tool_calls_section_begin\|>(.*?)$'
        
        def parse_tool_call_block(block: str) -> list:
            """Parse a tool calls section block."""
            calls = []
            
            # Split by tool call markers first to handle complex content
            parts = block.split('<|tool_call_begin|>')
            log.debug(f"[TOGETHER] Split into {len(parts)} parts")
            
            for i, part in enumerate(parts[1:], 1):  # Skip first part (before any tool call)
                try:
                    # Extract function name and index: "functions.write_file:8"
                    func_match = re.match(r'\s*functions\.(\w+):(\d+)', part)
                    if not func_match:
                        log.debug(f"[TOGETHER] No function match for part {i}: {part[:30]}...")
                        continue
                    
                    func_name = func_match.group(1)
                    idx = func_match.group(2)
                    
                    # Find the arguments section
                    arg_start = part.find('<|tool_call_argument_begin|>')
                    if arg_start == -1:
                        log.debug(f"[TOGETHER] No arg_start for part {i}")
                        continue
                    
                    # Find the end marker
                    arg_end = part.find('<|tool_call_end|>')
                    if arg_end == -1:
                        log.debug(f"[TOGETHER] No arg_end for part {i}")
                        continue
                    
                    # Extract arguments JSON
                    args_json = part[arg_start + len('<|tool_call_argument_begin|>'):arg_end].strip()
                    
                    log.debug(f"[TOGETHER] Part {i}: {func_name}:{idx}, args_len={len(args_json)}")
                    
                    # Generate a unique ID
                    tc_id = f"call_{int(time.time() * 1000) % 100000}_{len(calls)}"
                    calls.append({
                        'id': tc_id,
                        'index': int(idx),
                        'function': {
                            'name': func_name,
                            'arguments': args_json
                        }
                    })
                except Exception as e:
                    log.debug(f"[TOGETHER] Error parsing part {i}: {e}")
                    continue
            
            return calls
        
        # Find all tool call sections with closing tag
        section_count = 0
        for match in re.finditer(tool_section_pattern, content, re.DOTALL):  # Use original content
            section_count += 1
            section_content = match.group(1)
            parsed_calls = parse_tool_call_block(section_content)
            tool_calls.extend(parsed_calls)
            log.info(f"[TOGETHER] Section {section_count}: found {len(parsed_calls)} tool calls")
        
        if section_count == 0 and '<|tool_call_begin|>' in content:  # Use original content
            # Try without closing tag
            log.warning("[TOGETHER] Trying alternative pattern without closing tag...")
            for match in re.finditer(alt_pattern, content, re.DOTALL):  # Use original content
                section_content = match.group(1)
                parsed_calls = parse_tool_call_block(section_content)
                if parsed_calls:
                    tool_calls.extend(parsed_calls)
                    log.info(f"[TOOLGETHER] Alt pattern: found {len(parsed_calls)} tool calls")
                    break
        
        # NOW strip all markers from content AFTER extracting tool calls
        cleaned_content = self._strip_tool_call_markers(content)
        
        return cleaned_content, tool_calls
    
    def _parse_thinking_blocks(self, content: str) -> str:
        """Extract content outside thinking blocks for cleaner output."""
        import re
        # Remove thinking blocks like <|thinking|>...</|thinking|>
        cleaned = re.sub(r'<\|thinking\|>.*?</\|thinking\|>', '', content, flags=re.DOTALL)
        return cleaned
    
    def _strip_tool_call_markers(self, content: str) -> str:
        """Remove tool call markers from content for cleaner display."""
        import re
        # Remove tool_calls_section blocks
        cleaned = re.sub(r'<\|tool_calls_section_begin\|>.*?<\|tool_calls_section_end\|>', '', content, flags=re.DOTALL)
        # Also remove individual tool call markers that might be left behind
        cleaned = re.sub(r'<\|tool_call_begin\|>', '', cleaned)
        cleaned = re.sub(r'<\|tool_call_argument_begin\|>', '', cleaned)
        cleaned = re.sub(r'<\|tool_call_end\|>', '', cleaned)
        cleaned = re.sub(r'<\|tool_calls_section_end\|>', '', cleaned)
        return cleaned
    
    def chat_stream(self, messages: list, model: str = "deepseek-ai/DeepSeek-V3",
                    temperature: float = 0.7, max_tokens: int = 4096,
                    tools: Optional[List[Dict[str, Any]]] = None) -> Generator[str, None, None]:
        """Stream chat completion from Together AI.
        
        Handles special formats for:
        - Kimi K2.5: Uses <|tool_calls_section_begin|> tokens
        - DeepSeek models: Standard tool_calls in delta
        """
        # Check for Kimi compatibility mode
        use_kimi = model.startswith("moonshotai/") or model == "moonshotai/Kimi-K2.5"
        
        try:
            client = self._get_client()
            
            # Format messages
            formatted_messages = []
            for msg in messages:
                m = {"role": msg.role, "content": msg.content}
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    m["tool_calls"] = msg.tool_calls
                if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
                    m["tool_call_id"] = msg.tool_call_id
                formatted_messages.append(m)
            
            # Build request
            kwargs = {
                "model": model,
                "messages": formatted_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if tools:
                kwargs["tools"] = tools
            
            if use_kimi:
                log.info(f"[TOGETHER] Using Kimi streaming mode")
                # Kimi has issues with streaming tool calls, use non-streaming and parse
                response = client.chat.completions.create(
                    model=model,
                    messages=formatted_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False  # Non-streaming for Kimi
                )
                
                if response.choices:
                    message = response.choices[0].message
                    
                    # Debug: Check finish_reason
                    finish_reason = response.choices[0].finish_reason
                    log.info(f"[TOGETHER] Finish reason: {finish_reason}")
                    
                    # Handle truncated response (max_tokens exceeded)
                    if finish_reason == 'length':
                        log.warning(f"[TOGETHER] Response truncated due to max_tokens limit!")
                    
                    log.info(f"[TOGETHER] Checking structured tool_calls: hasattr={hasattr(message, 'tool_calls')}, type={type(message.tool_calls)}, value={repr(message.tool_calls)[:100]}")
                    
                    # First, yield structured tool calls if present
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        log.info(f"[TOGETHER] Processing {len(message.tool_calls)} structured tool_calls")
                        parsed_tool_calls = []
                        for tc in message.tool_calls:
                            # Handle both dict-like and object-like tool calls
                            if hasattr(tc, 'id'):
                                tc_id = tc.id.replace('functions.', '').replace(':', '_')
                            else:
                                tc_id = f"call_{int(time.time() * 1000) % 100000}"
                            
                            if hasattr(tc, 'function'):
                                func_name = tc.function.name if hasattr(tc.function, 'name') else str(tc.function.get('name', ''))
                                func_args = tc.function.arguments if hasattr(tc.function, 'arguments') else str(tc.function.get('arguments', '{}'))
                            else:
                                func_name = str(tc.get('function', {}).get('name', ''))
                                func_args = str(tc.get('function', {}).get('arguments', '{}'))
                            
                            parsed_tool_calls.append({
                                'id': tc_id,
                                'index': int(getattr(tc, 'index', 0) or 0),
                                'function': {
                                    'name': func_name,
                                    'arguments': func_args
                                }
                            })
                        
                        if parsed_tool_calls:
                            log.info(f"[TOGETHER] Found {len(parsed_tool_calls)} structured tool calls")
                            yield f"__TOOL_CALL_DELTA__:{json.dumps(parsed_tool_calls)}"
                    
                    # Then handle content (with possible embedded tool calls)
                    raw_content = message.content or ""
                    log.info(f"[TOOLGETHER] raw_content length: {len(raw_content)}")
                    
                    # If no content and no structured tool_calls, yield a placeholder
                    if not raw_content and not (hasattr(message, 'tool_calls') and message.tool_calls):
                        log.warning("[TOOLGETHER] Empty response with no tool calls, yielding placeholder")
                        yield "No response generated. Please try again."
                        return
                    
                    if raw_content:
                        log.info(f"[TOOLGETHER] Received content ({len(raw_content)} chars)")
                        log.info(f"[TOOLGETHER] Has markers: {'<|' in raw_content}")
                        log.info(f"[TOOLGETHER] Content preview: {raw_content[:200]}")
                        
                        # Step 1: Parse tool calls FIRST (before any cleaning)
                        # Pass ORIGINAL raw_content to preserve markers for parsing
                        embedded_tcs = []
                        parsed_content = raw_content
                        
                        # Try to parse tool calls from original content
                        parsed_result, embedded_tcs = self._parse_kimi_tool_calls(raw_content)
                        
                        # Step 2: Yield tool call deltas if found
                        if embedded_tcs:
                            log.info(f"[TOOLGETHER] Parsed {len(embedded_tcs)} embedded tool calls")
                            yield f"__TOOL_CALL_DELTA__:{json.dumps(embedded_tcs)}"
                        
                        # Step 3: Remove thinking blocks from the parsed content
                        clean_content = self._parse_thinking_blocks(parsed_result)
                        
                        # Step 4: Strip ALL remaining tool call markers from display content
                        display_content = self._strip_tool_call_markers(clean_content)
                        if display_content.strip():
                            yield display_content.strip()
                        elif not embedded_tcs:
                            # No tool calls AND no content - yield stripped content
                            log.warning(f"[TOOLGETHER] No tool calls, yielding stripped content")
                            yield self._strip_tool_call_markers(raw_content).strip()
                else:
                    log.warning("[TOGETHER] Empty response from Kimi")
                    
            else:
                # Standard streaming for DeepSeek and other models
                response = client.chat.completions.create(**kwargs)
                
                for chunk in response:
                    if not chunk.choices:
                        continue
                    
                    if chunk.choices[0].finish_reason:
                        break
                    
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        yield f"__TOOL_CALL_DELTA__:{json.dumps([{'index': tc.index, 'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}} for tc in delta.tool_calls])}"
                    
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Together AI streaming error: {e}")
            yield f"[Error: {e}]"
    
    def validate_api_key(self) -> bool:
        """Validate Together AI API key."""
        if not self._api_key:
            return False
        
        try:
            client = self._get_client()
            # Make a minimal request
            response = client.models.list()
            return True
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Together AI key validation failed: {e}")
            return False
    
    def get_last_error(self) -> Optional[str]:
        """Get last error message."""
        return self._last_error
