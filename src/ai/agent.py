"""
agent.py - AI Agent
AI Agent — Gateway to OpenAI / Anthropic / Mock responses.
Runs in a QThread to keep the UI responsive.
Uses Provider Registry and Key Manager for secure API key handling.
"""

import os
import json
import time
from pathlib import Path
import hashlib
from typing import Optional, List, Dict, Any
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer

# Load .env FIRST - before any other imports that might use API keys
try:
    from dotenv import load_dotenv
    import sys
    
    # Resolve correct root path for PyInstaller
    if getattr(sys, 'frozen', False):
        app_root = Path(sys.executable).parent
    else:
        app_root = Path(__file__).parent.parent.parent
        
    env_paths = [
        app_root / ".env",
        Path.cwd() / ".env",
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass

# NOW import other modules (after .env is loaded)
from src.utils.logger import get_logger
log = get_logger("ai_agent")

from src.core.key_manager import get_key_manager
from src.ai.providers import get_provider_registry, ProviderType, ChatMessage
from src.ai.decision_framework import get_decision_framework, reset_decision_framework, ActionType
from src.ai.autogen_wrapper import get_autogen_system, init_autogen_system

# Phase 1, 2, 3 Integration Imports
from src.ai.prompt_manager import get_prompt_manager
from src.ai.title_generator import get_title_generator
from src.ai.message_compactor import get_message_compactor, CompactionMessage
from src.ai.session_schema import get_session_schema_manager
from src.ai.acp import get_agent_control_plane, AgentType
from src.ai.skills import get_skill_registry
from src.ai.mcp import get_mcp_manager

# Phase 4 Integration Imports
from src.ai.todo import get_todo_manager
from src.ai.permission import get_permission_evaluator
from src.ai.github import get_github_agent

# NEW: OpenCode Enhancement Integration
from src.ai.intent import IntentClassification, AgentRoute
from src.ai.tools.selection import ToolScore

# PERFORMANCE OPTIMIZATION: Industry Standard Modules
from src.ai.tool_selector import TaskType
from src.ai.terminal_optimizer import TerminalOutputBatcher
from src.ai.context_optimizer import MessageDeduplicator, ContextOptimizer
from src.ai.adaptive_tool_selector import select_tools_adaptively, get_adaptive_tool_selector


def _categorize_error_message(error_msg: str) -> str:
    msg = (error_msg or "").lower()
    if "api key" in msg or "authentication" in msg or "unauthorized" in msg:
        return "auth"
    if "rate limit" in msg:
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "connection" in msg or "network" in msg or "dns" in msg:
        return "network"
    if "tool" in msg and "timeout" in msg:
        return "tool_timeout"


def _try_repair_json(json_str: str) -> Optional[dict]:
    """Attempt to repair incomplete/malformed JSON strings from AI.
    
    Handles common issues:
    - Unterminated strings (missing closing quotes)
    - Missing closing braces/brackets
    - Truncated content in multi-line strings
    """
    if not json_str or not isinstance(json_str, str):
        return None
    
    original = json_str.strip()
    if not original:
        return None
    
    try:
        return json.loads(original)
    except json.JSONDecodeError as e:
        pass
    
    repair_attempted = False
    
    # Strategy 1: Fix unterminated strings (common with large file content)
    if 'e' in locals() and e.msg == "Unterminated string starting at":
        repair_attempted = True
        test_str = original
        # Find the last quote and properly close the string
        if test_str.endswith('"') or '" ' in test_str:
            last_quote = test_str.rfind('"')
            if last_quote > 0:
                test_str = test_str[:last_quote] + '"'
                # Balance quotes
                while test_str.count('"') % 2 != 0:
                    test_str += '"'
                try:
                    return json.loads(test_str)
                except:
                    pass
    
    # Strategy 2: Add missing closing braces
    open_braces = original.count('{') - original.count('}')
    if open_braces > 0:
        repair_attempted = True
        test_str = original + '}' * open_braces
        try:
            return json.loads(test_str)
        except:
            pass
    
    # Strategy 3: Add missing closing brackets
    open_brackets = original.count('[') - original.count(']')
    if open_brackets > 0:
        repair_attempted = True
        test_str = original + ']' * open_brackets
        try:
            return json.loads(test_str)
        except:
            pass
    
    # Strategy 4: Handle truncated content fields (especially for write_file)
    # Look for patterns like: {"path": "file.html", "content": "<html>...
    if '{' in original and '"content"' in original:
        # Try to find and close the content string
        content_start = original.find('"content"')
        if content_start > 0:
            # Find where content value starts
            colon_pos = original.find(':', content_start)
            if colon_pos > 0:
                # Look for opening quote of content
                quote_start = original.find('"', colon_pos)
                if quote_start > 0:
                    # Count quotes after this point
                    remaining = original[quote_start+1:]
                    quote_count = remaining.count('"')
                    # If odd number of quotes, we need to close the string
                    if quote_count % 2 != 0:
                        # Find last quote and add closing
                        last_quote_pos = original.rfind('"')
                        if last_quote_pos > quote_start:
                            # Check if there's unclosed content before end
                            test_str = original.rstrip()
                            if not test_str.endswith('",') and not test_str.endswith('"}'):
                                test_str += '"'
                            # Now balance braces
                            open_b = test_str.count('{') - test_str.count('}')
                            if open_b > 0:
                                test_str += '}' * open_b
                            try:
                                return json.loads(test_str)
                            except:
                                pass
                    # CRITICAL FIX: Even if quote count is even, content might be truncated
                    # Just close and balance everything aggressively
                    else:
                        test_str = original.rstrip()
                        # Ensure content string is closed
                        if not test_str.endswith('",') and not test_str.endswith('"}'):
                            test_str += '"'
                        # Balance braces
                        open_b = test_str.count('{') - test_str.count('}')
                        if open_b > 0:
                            test_str += '}' * open_b
                        try:
                            return json.loads(test_str)
                        except:
                            pass
    
    # Strategy 5: ULTRA AGGRESSIVE - For write_file specifically
    # If we see "path" with .html/.css/.js but broken JSON, force-close it
    if '"path"' in original and ('.html' in original or '.css' in original or '.js' in original):
        # This is likely a file creation that got truncated
        test_str = original
        # Add closing quote if missing
        if test_str.count('"') % 2 != 0:
            test_str += '"'
        # Close all braces
        while test_str.count('{') > test_str.count('}'):
            test_str += '}'
        while test_str.count('[') > test_str.count(']'):
            test_str += ']'
        try:
            return json.loads(test_str)
        except:
            pass
    
    # Strategy 6: Nuclear option - just keep adding closing braces until it parses
    if '{' in original:
        test_str = original
        for i in range(20):  # Try up to 20 closing braces
            try:
                return json.loads(test_str)
            except:
                test_str += '}'
        # Also try with quotes + braces
        test_str = original + '"'
        for i in range(20):
            try:
                return json.loads(test_str)
            except:
                test_str += '}'
    if repair_attempted:
        log.debug(f"[JSON REPAIR] Repair attempted but failed: {original[:100]}...")
    
    return None

# PERFORMANCE: API response cache to avoid repeating identical requests
_api_response_cache: Dict[str, Any] = {}
_api_cache_max_size = 100  # LRU cache size
_api_cache_ttl = 3600  # Cache TTL: 1 hour

def _get_api_cache_key(messages: List[Dict], model: str, provider: str) -> str:
    """Generate cache key for API request."""
    # Create hash of messages + model + provider
    hasher = hashlib.sha256()
    for msg in messages:
        hasher.update(json.dumps(msg, sort_keys=True).encode())
    hasher.update(model.encode())
    hasher.update(provider.encode())
    return hasher.hexdigest()

def _cache_api_response(key: str, response: Any):
    """Cache API response with LRU eviction."""
    global _api_response_cache
    if len(_api_response_cache) >= _api_cache_max_size:
        # Remove oldest entry (LRU)
        oldest_key = next(iter(_api_response_cache))
        del _api_response_cache[oldest_key]
    _api_response_cache[key] = {
        'response': response,
        'timestamp': time.time()
    }

def _get_cached_api_response(key: str) -> Optional[Any]:
    """Get cached API response if not expired."""
    global _api_response_cache
    if key in _api_response_cache:
        entry = _api_response_cache[key]
        if time.time() - entry['timestamp'] < _api_cache_ttl:
            return entry['response']
        else:
            # Expired - remove
            del _api_response_cache[key]
    return None


class ToolWorker(QThread):
    """Runs tools in a background thread to keep UI responsive."""
    tool_started = pyqtSignal(str, dict)  # name, args
    tool_completed = pyqtSignal(str, dict, object)  # name, args, result
    all_tools_completed = pyqtSignal(list)  # all tool results
    error_occurred = pyqtSignal(str)
    tool_timeout = pyqtSignal(str, str)  # tool_name, recovery_hint

    TOOL_TIMEOUT_SECONDS = 30  # Hard limit per tool call

    def __init__(self, tool_registry, tool_calls: list, parent=None):
        super().__init__(parent)
        self.tool_registry = tool_registry
        self.tool_calls = tool_calls
        self._results = []
        
    def _repair_json(self, json_str: str) -> str:
        """Robustly repair truncated JSON by closing strings and brackets."""
        json_str = json_str.strip()
        if not json_str: return "{}"
        
        # 1. Handle unclosed quotes
        quote_count: int = 0
        escaped: bool = False
        for char in json_str:
            if char == '\\':
                escaped = not escaped
            elif char == '"' and not escaped:
                quote_count += 1
                escaped = False
            else:
                escaped = False
        
        if quote_count % 2 != 0:
            json_str += '"'
            
        # 2. Balance braces and brackets
        braces: list[int] = []
        brackets: list[int] = []
        in_string: bool = False
        escaped = False
        
        for i, char in enumerate(json_str):
            if char == '\\':
                escaped = not escaped
                continue
            if char == '"' and not escaped:
                in_string = not in_string
            escaped = False
            
            if not in_string:
                if char == '{': braces.append(i)
                elif char == '}': 
                    if braces: braces.pop()
                elif char == '[': brackets.append(i)
                elif char == ']':
                    if brackets: brackets.pop()
        
        # Close in reverse order
        while braces or brackets:
            last_brace: int = braces[-1] if braces else -1
            last_bracket: int = brackets[-1] if brackets else -1
            
            if last_brace > last_bracket:
                json_str += '}'
                braces.pop()
            else:
                json_str += ']'
                brackets.pop()
                
        return json_str

    def run(self):
        """Execute all tools sequentially in background thread with per-tool timeout."""
        import threading
        import time as _time

        try:
            completed_tools = []  # track for recovery hint

            for tool_call in self.tool_calls:
                name = tool_call["function"]["name"]
                try:
                    raw_args: str = tool_call["function"]["arguments"]
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        log.warning(f"Malformed JSON in tool call {name}, attempting repair...")
                        repaired: str = self._repair_json(raw_args)
                        try:
                            args = json.loads(repaired)
                            log.info(f"Successfully repaired JSON for {name}")
                        except Exception as e:
                            log.error(f"Failed to repair JSON for {name}: {e}. Repaired: {repaired[:100]}...")
                            args = {}
                except Exception as e:
                    log.error(f"Error preparing tool arguments: {e}")
                    args = {}

                # Emit started signal
                self.tool_started.emit(name, args)

                # ── Run tool in a sub-thread so we can apply a hard timeout ────────
                result_holder = [None]
                exc_holder = [None]

                def _run_tool():
                    try:
                        result_holder[0] = self.tool_registry.execute_tool(name, args)
                    except Exception as exc:
                        exc_holder[0] = exc

                t = threading.Thread(target=_run_tool, daemon=True)
                t.start()
                t.join(timeout=self.TOOL_TIMEOUT_SECONDS)

                if t.is_alive():
                    # Tool timed out — build a recovery hint and fail gracefully
                    completed_str = ", ".join(completed_tools) if completed_tools else "none"
                    recovery_hint = (
                        f"⚠️ Tool `{name}` exceeded {self.TOOL_TIMEOUT_SECONDS}s and was aborted.\n"
                        f"Completed tools so far: [{completed_str}].\n"
                        f"RECOVERY: resume the task from the next pending step."
                    )
                    log.warning(f"Tool timeout: {name} after {self.TOOL_TIMEOUT_SECONDS}s")
                    self.tool_timeout.emit(name, recovery_hint)

                    # Inject a timeout result so the AI knows what happened
                    timeout_result_content = (
                        f"TOOL_TIMEOUT: `{name}` did not respond within "
                        f"{self.TOOL_TIMEOUT_SECONDS} seconds. "
                        f"This usually means a subprocess or network call hung. "
                        f"Skip this step and continue with the remaining tasks."
                    )
                    from src.ai.tools import ToolResult
                    result = ToolResult(
                        success=False,
                        result=None,
                        error=timeout_result_content,
                        duration_ms=self.TOOL_TIMEOUT_SECONDS * 1000
                    )
                elif exc_holder[0] is not None:
                    from src.ai.tools import ToolResult
                    result = ToolResult(
                        success=False,
                        result=None,
                        error=str(exc_holder[0]),
                        duration_ms=0
                    )
                else:
                    result = result_holder[0]
                    completed_tools.append(name)

                # Store result with truncation to prevent context window overflow
                MAX_TOOL_CONTENT = 4000  # ~1000 tokens — enough for AI to understand result

                content = str(result.result) if result.success else f"Error: {result.error}"

                # Truncate long outputs — keep first + last portion (most informative)
                if len(content) > MAX_TOOL_CONTENT:
                    half = MAX_TOOL_CONTENT // 2
                    content = (
                        content[:half]
                        + f"\n\n... [output truncated: {len(content)} chars total, showing first and last {half}] ...\n\n"
                        + content[-half:]
                    )

                tool_result_metadata = getattr(result, 'metadata', {}) or {}
                self._results.append({
                    "tool_call_id": tool_call["id"],
                    "name": name,
                    "content": content,
                    "success": result.success,
                    "duration_ms": result.duration_ms,
                    "status": getattr(result, 'status', 'completed'),
                    "metadata": tool_result_metadata
                })

                # Emit completed signal
                self.tool_completed.emit(name, args, result)

                # Stop batch if tool is pending (Interactive stop-and-wait)
                if getattr(result, 'status', 'completed') == 'pending':
                    log.info(f"Stopping batch execution: {name} is PENDING")
                    break

            # Emit all completed
            self.all_tools_completed.emit(self._results)

        except Exception as e:
            log.error(f"ToolWorker error: {e}")
            self.error_occurred.emit(str(e))


class AIWorker(QThread):
    """Runs the AI API call in a background thread using Provider Registry."""
    chunk_received = pyqtSignal(str)
    finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, messages: list[dict], model: str, temperature: float,
                 max_tokens: int, provider: str, tools: list[dict] = None, parent=None):
        super().__init__(parent)
        self.messages = messages
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider = provider
        self.tools = tools
        self._full_response = ""
        self._tool_calls = {}  # index -> {"id": id, "name": name, "arguments": args}
        self.tool_calls = None  # Final parsed tool calls (list format)

    def run(self):
        """Run the AI API call in background thread with comprehensive error handling."""
        log.info("AIWorker.run() started")
        import time
        import traceback
        start_time = time.time()
        try:
            self._call_provider()
            elapsed = time.time() - start_time
            log.info(f"AIWorker.run() completed successfully in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - start_time
            error_details = traceback.format_exc()
            log.error(f"AI Worker error after {elapsed:.1f}s: {e}")
            log.error(f"AI Worker full traceback:\n{error_details}")
            
            # Emit detailed error message
            error_message = f"{str(e)}\n\nTime: {elapsed:.1f}s\nModel: {self.model}\nProvider: {self.provider}"
            self.error_occurred.emit(error_message)

    def _call_provider(self):
        """Call AI provider using the provider registry."""
        # Map provider string to ProviderType
        provider_map = {
            "deepseek": ProviderType.DEEPSEEK,
            "mistral": ProviderType.MISTRAL,
            "siliconflow": ProviderType.SILICONFLOW,
        }
        
        # Use selected provider directly (no auto-switching)
        provider_type = provider_map.get(self.provider, ProviderType.DEEPSEEK)
        
        # Get provider instance from registry
        registry = get_provider_registry()
        provider = registry.get_provider(provider_type)
        
        # Get API key - Prioritize environment variable (.env) over storage
        api_key = os.getenv(f"{self.provider.upper()}_API_KEY", "")
        
        if not api_key:
            key_manager = get_key_manager()
            api_key = key_manager.get_key(self.provider)
        
        if not api_key:
            raise ValueError(
                    f"No API key found for {self.provider}.\n\n"
                    f"Please add your key via AI → API Key Settings or set "
                    f"{self.provider.upper()}_API_KEY environment variable."
                )
        
        # Set the API key on the provider
        provider.set_api_key(api_key)
        
        log.info(f"   Using {self.provider} provider")
        
        # Convert messages to ChatMessage objects
        chat_messages = []
        for msg in self.messages:
            chat_messages.append(ChatMessage(
                role=msg["role"],
                content=msg.get("content", ""),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
                name=msg.get("name")
            ))
        
        # PERFORMANCE: Check cache first (before making API call)
        cache_key = _get_api_cache_key(self.messages, self.model, self.provider)
        cached_response = _get_cached_api_response(cache_key)
        if cached_response:
            log.info(f"[CACHE] HIT: Reusing cached API response")
            self._full_response = cached_response
            self.finished.emit(self._full_response)
            return
        
        log.info(f"[CACHE] MISS: Making fresh API call")
        
        # Stream the response for live UI updates
        log.info(f"Starting streaming request to {self.provider}...")
        
        try:
            chunk_count = 0
            tool_call_buffer = {}
            estimated_tokens = 0
            
            # DYNAMIC TOKEN BUDGETING (Claude Desktop Hybrid Strategy)
            # Adjust based on model capabilities and task complexity
            model_token_limits = {
                'deepseek': 4096,      # DeepSeek typical limit
                'groq': 8192,          # Groq Llama models
                'kimi': 8192,          # Kimi K2.5
                'together': 4096,      # Together AI varies
                'default': 4096
            }
            
            # Get base limit for current model/provider
            base_limit = model_token_limits.get(self.provider.lower(), model_token_limits['default'])
            
            # Check if model name suggests higher capacity (e.g., "8k", "32k", "128k")
            import re
            capacity_match = re.search(r'(\d+)(k|kb)?', self.model.lower())
            if capacity_match:
                capacity_value = int(capacity_match.group(1))
                if 'k' in capacity_match.group(0):
                    # Model explicitly states capacity (e.g., "32k")
                    base_limit = min(capacity_value * 1000, 128000)  # Cap at 128K
            
            # Set safe threshold (leave room for JSON structure and tool call overhead)
            MAX_SAFE_TOKENS = int(base_limit * 0.85)  # Use 85% of limit as buffer
            MIN_SAFE_TOKENS = 3500  # Absolute minimum for safety
            MAX_SAFE_TOKENS = max(MAX_SAFE_TOKENS, MIN_SAFE_TOKENS)  # Ensure reasonable minimum
            
            log.info(f"[TOKEN BUDGET] Model: {self.model}, Provider: {self.provider}")
            log.info(f"[TOKEN BUDGET] Base limit: {base_limit}, Safe threshold: {MAX_SAFE_TOKENS}")
            
            log.info(f"Starting streaming with OpenAI SDK (SSL disabled)...")
            
            # For Kimi, don't emit "Thinking..." since it has its own thinking blocks
            if "kimi" not in self.model.lower():
                self.chunk_received.emit("Thinking...\n")
            
            # Simple streaming via OpenAI SDK with error handling
            log.info(f"[DEBUG] Calling provider.chat_stream with tools={len(self.tools) if self.tools else 0}")
            if self.tools:
                log.info(f"[DEBUG] First 3 tools: {[t.get('function', {}).get('name', 'unknown') for t in self.tools[:3]]}")
            
            try:
                stream = provider.chat_stream(
                    messages=chat_messages,
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    tools=self.tools
                )
                log.info(f"[DEBUG] Stream established, type={type(stream)}")
            except Exception as stream_error:
                log.error(f"Failed to establish stream: {stream_error}")
                import traceback
                log.error(f"Stream error traceback: {traceback.format_exc()}")
                raise RuntimeError(f"API stream failed: {str(stream_error)}") from stream_error
            
            # Process chunks
            last_stream_error = None
            try:
                # STATEFUL STREAM CLEANING (Fixes stagnation and junk output)
                state = {
                    "in_thinking": False,
                    "in_tool_section": False,
                    "in_tool_call": False,
                    "buffer": ""
                }
                
                for chunk in stream:
                    if not chunk:
                        continue
                    
                    chunk_count += 1
                    
                    # Detect special markers (handle cross-chunk markers with a small buffer if needed)
                    # For now, we handle full markers within a chunk or simple prefix
                    # 1. Handle Thinking Blocks (Stateful)
                    if "<|thinking|>" in chunk or chunk.startswith("[THINK]"):
                        state["in_thinking"] = True
                        # Clean prefix if it's the start
                        display_chunk = chunk.replace("<|thinking|>", "").replace("[THINK]", "Thinking... ")
                        if display_chunk.strip():
                            self.chunk_received.emit(display_chunk)
                        continue
                    
                    if "</|thinking|>" in chunk:
                        state["in_thinking"] = False
                        parts = chunk.split("</|thinking|>")
                        if len(parts) > 1 and parts[1]:
                            self._full_response += parts[1]
                            self.chunk_received.emit(parts[1])
                        continue
                        
                    if state["in_thinking"]:
                        # For DeepSeek R1/Reasoner, reasoning is often valuable to show
                        # If the chunk is just reasoning, emit as hint but don't add to full_response (metadata)
                        self.chunk_received.emit(chunk)
                        continue

                    # 2. Handle Tool Call Metadata (Internal protocol)
                    # Handle tool call deltas directly - NO MORE swallowed chunks!
                    if chunk.startswith("__TOOL_CALL_DELTA__:"):
                        state["in_tool_call"] = True
                        try:
                            deltas = json.loads(chunk[len("__TOOL_CALL_DELTA__:"):])
                            log.debug(f"[AIWorker] Received {len(deltas)} tool call deltas")
                            for delta in deltas:
                                index = delta.get("index", 0)
                                if index not in tool_call_buffer:
                                    tool_call_buffer[index] = {"id": "", "name": "", "arguments": ""}
                                
                                if delta.get("id"):
                                    tool_call_buffer[index]["id"] += delta["id"]
                                if delta.get("function", {}).get("name"):
                                    tool_call_buffer[index]["name"] += delta["function"]["name"]
                                if delta.get("function", {}).get("arguments"):
                                    tool_call_buffer[index]["arguments"] += delta["function"]["arguments"]
                        except json.JSONDecodeError as e:
                            log.error(f"Error parsing tool delta JSON: {e}")
                            log.debug(f"Raw delta: {chunk[:200]}")
                        
                        # Reset tool call state for next chunk logic
                        state["in_tool_call"] = False
                        continue

                    # PROACTIVE TOKEN MONITORING (Claude-style strategy)
                    estimated_tokens += len(chunk) // 4
                    if estimated_tokens > MAX_SAFE_TOKENS:
                        log.warning(f"[HYBRID STRATEGY] Approaching token limit ({estimated_tokens}/{MAX_SAFE_TOKENS})")
                    
                    # Regular content
                    cleaned_chunk = chunk
                    for tag in ["<|tool_call_begin|>", "<|tool_call_end|>", 
                               "<|tool_calls_section_begin|>", "<|tool_calls_section_end|>",
                               "<|tool_call_argument_begin|>"]:
                        cleaned_chunk = cleaned_chunk.replace(tag, "")
                        
                    if cleaned_chunk:
                        self._full_response += cleaned_chunk
                        self.chunk_received.emit(cleaned_chunk)
            except Exception as e:
                log.error(f"Stream processing error: {e}")
                last_stream_error = e
                # Continue to process what we have
            
            log.info(f"Stream completed: {chunk_count} chunks, full_response={len(self._full_response)} chars, tool_calls={len(tool_call_buffer)}")
            
            # HEURISTIC PARSING FOR DEEPSEEK (doesn't support native tool calling)
            # If no tool calls were extracted but response mentions file creation, try to parse from text
            if len(tool_call_buffer) == 0 and self._full_response:
                log.info(f"[HEURISTIC] No native tool calls found, attempting robust sequence parsing...")
                import re
                
                # HEURISTIC 1: Look for JSON blocks in markdown (common for DeepSeek V3)
                # ```json { "name": "...", "arguments": {...} } ```
                markdown_json_pattern = r'```(?:json)?\s*(\{\s*"name"\s*:\s*"(?:write_file|edit_file|read_file|run_command|list_directory)"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\})\s*```'
                md_matches = re.findall(markdown_json_pattern, self._full_response, re.DOTALL)
                
                if md_matches:
                    log.info(f"[HEURISTIC] Found {len(md_matches)} JSON blocks in markdown")
                    for idx, json_str in enumerate(md_matches):
                        try:
                            tool_data = json.loads(json_str)
                            tool_call_buffer[idx] = {
                                'id': f'heuristic_md_{idx}',
                                'name': tool_data.get('name'),
                                'arguments': json.dumps(tool_data.get('arguments', {}))
                            }
                        except Exception as e:
                            log.warning(f"[HEURISTIC] Failed to parse MD JSON: {e}")

                # HEURISTIC 2: Look for raw JSON patterns (existing logic)
                if not tool_call_buffer:
                    raw_json_pattern = r'(\{\s*"name"\s*:\s*"(?:write_file|edit_file|read_file|run_command|list_directory)"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\})'
                    raw_matches = re.findall(raw_json_pattern, self._full_response, re.DOTALL)
                    for idx, json_str in enumerate(raw_matches):
                        if idx in tool_call_buffer: continue # Skip if already found in MD
                        try:
                            tool_data = json.loads(json_str)
                            tool_call_buffer[idx] = {
                                'id': f'heuristic_raw_{idx}',
                                'name': tool_data.get('name'),
                                'arguments': json.dumps(tool_data.get('arguments', {}))
                            }
                        except: continue

                # HEURISTIC 3: DeepSeek-specific <|tool_call_begin|> style parsing if we have raw text
                if not tool_call_buffer:
                    tag_pattern = r'<\|tool_call_begin\|>(.*?)(?:<\|tool_call_end\|>|$)'
                    tag_matches = re.findall(tag_pattern, self._full_response, re.DOTALL)
                    for idx, content in enumerate(tag_matches):
                        try:
                            # Content inside tags might be partial or raw JSON
                            tool_data = _try_repair_json(content)
                            if tool_data and tool_data.get('name'):
                                tool_call_buffer[idx] = {
                                    'id': f'heuristic_tag_{idx}',
                                    'name': tool_data.get('name'),
                                    'arguments': json.dumps(tool_data.get('arguments', {}))
                                }
                        except: continue

                if tool_call_buffer:
                    log.info(f"[HEURISTIC] SUCCESS: Extracted {len(tool_call_buffer)} tool calls from text response!")
                else:
                    log.warning(f"[HEURISTIC] FAILED to extract any tool calls from response.")
            
            # CLAUDE-STYLE HYBRID STRATEGY: Detect large file creation attempts
            if tool_call_buffer:
                for idx, tc in tool_call_buffer.items():
                    if tc["name"] == "write_file":
                        args_str = tc["arguments"]
                        try:
                            args = json.loads(args_str) if args_str else {}
                            # Check if content is very large (>250 lines or >15KB)
                            content = args.get("content", "")
                            path = args.get("path", "")
                            if content:
                                lines = content.count('\n') + 1
                                size_kb = len(content) / 1024
                                
                                # INTELLIGENT THRESHOLD: Adjust based on model capacity
                                LINE_THRESHOLD = int((MAX_SAFE_TOKENS / 4) * 0.7)  # ~70% of token budget
                                SIZE_THRESHOLD_KB = 20  # Conservative file size limit
                                
                                if lines > LINE_THRESHOLD or size_kb > SIZE_THRESHOLD_KB:
                                    log.warning(f"[HYBRID STRATEGY] Large file detected: {path} ({lines} lines, {size_kb:.1f}KB)")
                                    log.warning(f"[HYBRID STRATEGY] Token budget: {MAX_SAFE_TOKENS}, Estimated need: ~{lines//4} tokens")
                                    log.warning(f"[HYBRID STRATEGY] Consider: skeleton-first + edit_file OR split into multiple files")
                                    # Don't block - our JSON repair will handle truncation if it occurs
                                    # But log for user awareness and AI learning
                        except:
                            pass  # Ignore parsing errors here
            
            # Process tool calls
            if tool_call_buffer:
                final_tool_calls = []
                for idx in sorted(tool_call_buffer.keys()):
                    tc = tool_call_buffer[idx]
                    # Robustness: Allow tool calls that have at least a name
                    if tc["name"]:
                        # Generate ID if missing
                        if not tc["id"]:
                            tc["id"] = f"call_{int(time.time())}_{idx}"
                            
                        args = tc["arguments"].strip() if tc["arguments"] else "{}"
                        
                        # AGENTIC FIX: Attempt to repair truncated JSON arguments
                        # This handles cases where streaming cuts off mid-JSON
                        if args and args != "{}":
                            try:
                                json.loads(args)  # Validate first
                            except json.JSONDecodeError:
                                log.warning(f"Tool {tc['name']} has malformed arguments, attempting repair...")
                                repaired_args = _try_repair_json(args)
                                if repaired_args:
                                    log.info(f"✅ Repaired tool {tc['name']} arguments")
                                    args = json.dumps(repaired_args)
                                else:
                                    log.error(f"❌ Failed to repair tool {tc['name']} arguments: {args[:100]}...")
                        
                        final_tool_calls.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": args}
                        })
                if final_tool_calls:
                    self.tool_calls = final_tool_calls
                    log.info(f"✅ Processed {len(final_tool_calls)} tool calls from stream")
            
            # Cache and finish - succeed if we have EITHER content OR tool calls
            if self._full_response:
                cache_key = _get_api_cache_key(self.messages, self.model, self.provider)
                _cache_api_response(cache_key, self._full_response)
                self.finished.emit(self._full_response)
                return
            
            # If no content but we have tool calls, that's a valid response!
            if self.tool_calls:
                self.finished.emit("")  # Empty content, but tool calls exist
                return
            
            # Handle truncated response (max_tokens exceeded)
            if chunk_count > 0:
                # We received chunks but no content/tool calls - likely truncated
                log.warning(f"[AIWorker] Response truncated (received {chunk_count} chunks but no content/tool_calls)")
                truncated_msg = "[Truncated] Response was cut off. Please try again or the task may be incomplete."
                self.finished.emit(truncated_msg)
                return
            
            # No content AND no tool calls - that's an error
            # BUT first check if we got any chunks at all
            if chunk_count == 0:
                # Check if this might be a rate limit or API issue
                log.error(f"[AIWorker] Stream returned empty (0 chunks received)")
                if last_stream_error is not None:
                    msg = str(last_stream_error)
                    if 'rate limit' in msg.lower() or '429' in msg:
                        raise Exception("Rate limit from provider. Please wait and retry. Details: " + msg)
                    raise Exception(msg)
                raise Exception("No response from stream - API returned empty")
            else:
                # We received some chunks but parsing failed - try to salvage
                log.warning(f"[AIWorker] Received {chunk_count} chunks but parsing failed")
                if self._full_response and self._full_response.strip():
                    log.info(f"[AIWorker] Salvaging partial response: {len(self._full_response)} chars")
                    self.finished.emit(self._full_response)
                    return
            
            raise Exception("No response from stream")
            
        except Exception as e:
            log.error(f"API call failed: {e}")
            raise


class AIAgent(QObject):
    """
    High-level AI agent with MAXIMUM performance optimizations.
    Features: Async file loading, predictive prefetching, LRU caching.
    """
    response_chunk = pyqtSignal(str)
    response_complete = pyqtSignal(str)
    request_error = pyqtSignal(str)
    file_generated = pyqtSignal(str)
    file_edited_diff = pyqtSignal(str, str, str)  # file_path, original_content, new_content
    tool_activity = pyqtSignal(str, str, str)  # tool_type, info, status
    directory_contents = pyqtSignal(str, str)  # path, contents
    thinking_started = pyqtSignal()
    thinking_stopped = pyqtSignal()
    todos_updated = pyqtSignal(list, str)  # todos_list, main_task
    tool_summary_ready = pyqtSignal(dict)  # structured tool summary data
    
    # Performance: File prefetch signal
    files_prefetch = pyqtSignal(list)  # list of file paths to prefetch

    def _normalize_path(self, path: str) -> str:
        """Helper to create a canonical, absolute, and case-normalized path for tracking."""
        if not path:
            return ""
        try:
            import os
            # 1. Expand user and normalize slashes
            p = os.path.expanduser(path)
            # 2. If relative, resolve against project root or CWD
            if not os.path.isabs(p):
                if hasattr(self, '_project_root') and self._project_root:
                    p = os.path.join(str(self._project_root), p)
                else:
                    p = os.path.abspath(p)
            # 3. Final canonicalization (absolute, normalized, and lowered case for Windows)
            return os.path.normcase(os.path.normpath(os.path.abspath(p)))
        except Exception as e:
            log.warning(f"Path normalization failed for {path}: {e}")
            return os.path.normcase(os.path.normpath(path))

    SYSTEM_PROMPT = """🚨 ATTENTION: CRITICAL EFFICIENCY RULES 🚨
YOU MUST FOLLOW THESE RULES OR YOU WILL FAIL:
1. NEVER call list_directory, dir, ls - just CREATE files
2. NEVER read_file before creating - files don't exist yet
3. NEVER check_syntax - write_file success is enough
4. NEVER run dir to verify - trust the success message
5. NEVER separate script runs - batch in ONE command

❌ FORBIDDEN THOUGHTS:
- "Let me check if files exist" → JUST CREATE THEM
- "Let me verify with dir" → DON'T - trust success
- "I need to read the file first" → WRONG - create it

✅ CORRECT PATH:
write_file → write_file → write_file → run_command(all scripts)
THAT'S IT. NO VERIFICATION NEEDED.

---

# CORTEX AI — AGENTIC BUILD AGENT

You are an AI AGENT with tool-calling capabilities. Your job is to BUILD by using tools effectively.

## 💻 WINDOWS ENVIRONMENT DETECTION

**CRITICAL: You are running on a WINDOWS system.**

### Shell Syntax Requirements:
- **Shell**: PowerShell (NOT bash, NOT Unix shell)
- **Path separator**: Backslash `\\` (e.g., `C:\\Users\\Hakeem1\\file.txt`)
- **Command chaining**: Use semicolons `;` or commas `,` (NOT `&&`)
- **Virtual env activation**: `.\\venv\\Scripts\\activate` (NOT `./venv/bin/activate`)

### PowerShell Commands (ALL Unix aliases work):
- ✅ `ls` - List directory
- ✅ `cat filename` - Read file
- ✅ `rm path` - Delete file  
- ✅ `cp source dest` - Copy file
- ✅ `mv source dest` - Move/rename file
- ✅ `cd path` - Change directory
- ✅ `mkdir folder` - Create directory

### Command Chaining Examples:
```powershell
# CORRECT (Windows PowerShell):
python script1.py; python script2.py; python script3.py
cd C:\\Project; .\\venv\\Scripts\\activate; python manage.py runserver

# WRONG (Unix bash - will fail):
cd C:/Project && ./venv/bin/activate && python manage.py runserver
```

### File Path Handling:
- Always use **forward slashes** `/` or **escaped backslashes** `\\\\` in Python strings
- Example: `"C:\\\\Users\\\\Hakeem1\\\\file.txt"` or `"C:/Users/Hakeem1/file.txt"`
- In commands: `cd C:\\Project` or `cd C:/Project`

## ⚡ EFFICIENCY RULES (ABSOLUTE - NO EXCEPTIONS)

### 🚫 STRICTLY PROHIBITED:
1. **NO `list_directory` or `dir` commands** - Never check if files exist, just CREATE them
2. **NO `check_syntax` calls** - Write success means the file is valid
3. **NO reading files after creation** - write_file success is enough
4. **NO running `dir` to verify** - Files are created, trust the tool result
5. **NO separate commands for each script** - Use ONE command for all scripts

### ❌ WRONG BEHAVIOR (will fail review):
```
Thought: Let me check if files exist first
Action: list_directory  ← FORBIDDEN
Action: dir  ← FORBIDDEN  
Action: read_file(newfile.py)  ← FORBIDDEN
```

### ✅ CORRECT BEHAVIOR:
```
Thought: Create the files
Action: write_file(helloworld.py)
Action: write_file(for_loop.py)  
Action: write_file(while_loop.py)
Action: run_command(python helloworld.py; python for_loop.py; python while_loop.py)
```

### Running Scripts (Windows PowerShell):
- CORRECT: `python file1.py; python file2.py; python file3.py`
- CORRECT: `python file1.py`, then `python file2.py`, then `python file3.py` - ALL IN ONE run_command call
- WRONG: Three separate run_command calls

### Target: 4 tool calls MAX for creating and testing 3 files

## ⏸️  PERMISSION & TOOL STATE HANDLING (CRITICAL)

### When tool returns status="pending":
- WAIT indefinitely for user permission via permission card
- Do NOT attempt alternative tools
- Do NOT continue execution
- Always check tool response status BEFORE proceeding

### Tool Execution Sequence:
1. Call tool (e.g., edit_file)
2. Check response status:
   - If status="pending": WAIT (permission card shown to user)
   - If status="completed": Proceed with next tool
   - If status="error": Debug and retry

### WRONG: Treating PENDING as failure
❌ Tool returns status="pending"
❌ You interpret as "edit_file failed, try smart_edit instead"
❌ Result: Permission loop (trying multiple tools while waiting)

### RIGHT: Respecting PENDING state
✅ Tool returns status="pending"
✅ You WAIT for user permission response
✅ Tool re-executes after permission granted
✅ Task completes

    ## 🎨 UI & LAYOUT DEBUGGING PROTOCOL
    If a user reports a UI element is "missing", "cut off", or "not displaying", and there are no syntax errors:
    1. **DO NOT assume the code was deleted.**
    2. **Check for `overflow: hidden`** on the `body` or parent containers which might chop off the element on shorter screens.
    3. **Check for fixed `height` or `max-height`** constraints clipping children.
    4. **Check `z-index`** layering issues.
    5. **USE THE `check_layout` TOOL** (if available) to quickly dump the parent CSS hierarchy!
    6. **🚫 CRITICAL RULE:** DO NOT write Python scripts to test HTML/CSS! Just fix the CSS directly using `edit_file`! Do not waste credits building diagnostic scripts for frontend bugs!

    ## CRITICAL: TOOL USAGE POLICY (MOST IMPORTANT)

**FOR ANY CREATE/BUILD/MAKE/WRITE/ADD/MODIFY TASK:**
- **FIRST 50 TOKENS MUST BE A TOOL CALL** - No explanations, no thinking out loud
- **ZERO DISCUSSION BEFORE FIRST TOOL** - Don't say "I'll help you create...", just DO IT
- **DIRECT TOOL SYNTAX IN THOUGHTS** - Think: `write_file(path="file.html", content="...")` NOT "Maybe I should create..."

**EXAMPLES:**
✅ USER: "Create button" → YOU: [Immediately calls write_file()]
❌ USER: "Create button" → YOU: "I'd be happy to help! Let me think..." [NO TOOL]

**YOU MUST USE TOOLS FOR:**
- Creating files → write_file()
- Modifying files → edit_file()
- Reading files → read_file()
- Running commands → run_in_terminal()

**NEVER:**
- ❌ Talk about creating without actually calling write_file()
- ❌ Explain your plan before taking action
- ❌ Say "I'll create" without the actual tool call

**ALWAYS:**
- ✅ ACT FIRST, explain later (if needed)
- ✅ Tool calls within first 2 sentences MAXIMUM


"""
    # Internal signal to bridge background tool processing back to main thread safely
    _tool_batch_finished = pyqtSignal(list, list, str) # results, tool_calls, assistant_content
    
    # Signal for interactive user questions (Pending status)
    # user_question_requested.emit(tool_call_id, question_text, metadata)
    user_question_requested = pyqtSignal(str, str, dict)
    
    def __init__(self, file_manager: Optional[Any] = None, terminal_widget=None, parent=None):
        super().__init__(parent)
        from src.config.settings import get_settings
        # Import ToolRegistry from _tools_monolithic.py (to avoid tools/ package conflict)
        from src.ai._tools_monolithic import ToolRegistry
        from src.ai.context_manager import get_context_manager
        from src.core.change_orchestrator import get_change_orchestrator
        self._settings = get_settings()
        self._project_root: Optional[str] = None
        self._tool_registry = ToolRegistry(
            file_manager=file_manager,
            terminal_widget=terminal_widget,
            project_root=self._project_root,
            parent_agent=self  # Pass agent reference for creation mode tracking
        )
        self._history: list[dict] = []
        self._history_summary: str = ""
        self._worker: AIWorker | None = None
        self._pending_tool_calls: list[dict] = []
        self._always_allowed: bool = False
        self._continue_after_tools_flag: bool = False  # Reset on error
        self._waiting_for_user_response = False
        self._pending_tool_call_id = None
        self._check_configuration()
        self._mode = "Agent"  # Default mode
        self._always_allowed = True  # Agent mode has full autonomy by default
        self._warmup_shown = False  # Track if warmup has been shown
        self._context_manager = None  # Will be initialized when project is set
        self._project_context = None  # ProjectContext when ready
        self._cached_project_context = None  # Cached project context string for performance
        self._active_file_path = None
        self._cursor_position = None
        self._change_orchestrator = get_change_orchestrator()
        self._pre_edit_snapshots: dict = {}  # Capture file content before edits for diff
        self._decision_framework = None  # Initialized when project is set
        self._request_started_at: float | None = None
        self._request_in_flight = False
        self._auto_verify_enabled = bool(self._settings.get("ai", "auto_verify", default=True))
        
        # Creation Mode: Blocks unnecessary verification tools when AI is creating files
        self._creation_mode = False
        self._creation_mode_tool_blocklist = {"list_directory", "check_syntax"}
        
        # AutoGen Multi-Agent System
        self._autogen_system = None
        self._autogen_enabled = bool(self._settings.get("ai", "autogen_enabled", default=False))
        self._auto_verify_command = (self._settings.get("ai", "test_command", default="") or "").strip()
        if not self._auto_verify_command:
            env_test_command = os.getenv("CORTEX_TEST_COMMAND", "").strip()
            if env_test_command:
                self._auto_verify_command = env_test_command
        self._auto_verify_max_retries = int(self._settings.get("ai", "max_verify_retries", default=2) or 2)
        self._auto_verify_attempts = 0
        self._auto_verify_in_progress = False
        self._pending_verify_files: set[str] = set()
        # AutoGen multi-agent system configuration
        self._use_autogen = False  # Disabled by default, enable via UI toggle
        self._autogen_system: Optional[CortexMultiAgentSystem] = None
        # Human-in-the-loop configuration
        self._require_human_approval = False  # Enabled via enable_human_in_loop()
        
        self._metrics = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_error": 0,
            "request_ms_total": 0,
            "last_request_ms": 0,
            "tool_calls_total": 0,
            "tool_calls_success": 0,
            "tool_calls_error": 0,
            "tool_timeouts": 0,
            "edit_calls": 0,
            "edit_success": 0,
            "lint_checks": 0,
            "lint_clean": 0,
            "retries_total": 0
        }
        
        # Phase 1, 2, 3 Integration: Initialize new components
        self._prompt_manager = get_prompt_manager()
        self._title_generator = get_title_generator(self)
        self._message_compactor = get_message_compactor()
        self._acp = get_agent_control_plane()
        self._skill_registry = get_skill_registry()
        self._mcp_manager = get_mcp_manager()
        
        # PERFORMANCE OPTIMIZATION: Initialize optimization components
        self._terminal_batcher = TerminalOutputBatcher(
            flush_callback=self._flush_terminal_output,
            batch_size=50,
            flush_interval_ms=100
        )
        self._message_deduplicator = MessageDeduplicator()
        self._context_optimizer = ContextOptimizer()
        self._current_mode = "build"  # build, explore, debug, plan
        
        # Phase 4 Integration: Initialize new components
        self._todo_manager = get_todo_manager()
        self._permission_evaluator = get_permission_evaluator()
        self._github_agent = get_github_agent()
        log.info("AIAgent initialized with Phase 1, 2, 3, 4 components")
        
        # Connect internal signal for thread-safe cross-turn handover
        self._tool_batch_finished.connect(self._on_all_tools_completed)
        
        # Event bus integration for proactive AI suggestions (NEW)
        self._setup_event_bus()
        
        log.info(
            "Metrics enabled: edit success rate, lint clean rate, time-to-answer, tool timeout rate"
        )

    def _setup_event_bus(self):
        """Setup event bus integration for proactive AI suggestions."""
        try:
            from src.core.event_bus import get_event_bus, EventType
            self._event_bus = get_event_bus()
            
            # Subscribe to critical events
            self._event_bus.subscribe(EventType.CRITICAL_ERRORS_FOUND, self._on_critical_errors)
            self._event_bus.subscribe(EventType.PROBLEMS_DETECTED, self._on_problems_detected)
            
            log.info("Event bus integration enabled for proactive suggestions")
        except Exception as e:
            log.warning(f"Could not setup event bus: {e}")
            self._event_bus = None
    
    def _on_critical_errors(self, event_type, data):
        """Handle critical errors detected - offer immediate help."""
        if hasattr(data, 'error_count') and data.error_count > 0:
            # Only auto-offer if there are multiple critical errors
            if data.error_count >= 3:
                self.response_chunk.emit(
                    f"\n\n🔴 **I noticed {data.error_count} critical errors** in your code. "
                    f"Would you like me to analyze and fix them?"
                )
    
    def _on_problems_detected(self, event_type, data):
        """Handle problems detected - track for pattern recognition."""
        # Track error patterns for proactive suggestions
        if not hasattr(self, '_recent_problems'):
            self._recent_problems = []
        
        self._recent_problems.append({
            'severity': getattr(data, 'severity', 'info'),
            'message': getattr(data, 'message', ''),
            'file_path': getattr(data, 'file_path', ''),
            'timestamp': getattr(data, 'timestamp', 0)
        })
        
        # Keep only recent problems (last 20)
        if len(self._recent_problems) > 20:
            self._recent_problems = self._recent_problems[-20:]
        
        # Detect error spikes (5+ errors in short time)
        recent_errors = [p for p in self._recent_problems if p['severity'] == 'error']
        if len(recent_errors) >= 5:
            # Check if we haven't already offered help recently
            if not getattr(self, '_offered_help_recently', False):
                self.response_chunk.emit(
                    f"\n\n⚠️ **I'm seeing multiple errors** ({len(recent_errors)} recent). "
                    f"Shall I investigate what's going wrong?"
                )
                self._offered_help_recently = True
                
                # Reset flag after 30 seconds
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(30000, self._reset_help_flag)
    
    def _reset_help_flag(self):
        """Reset the help offered flag to allow future suggestions."""
        self._offered_help_recently = False

    # Phase 1, 2, 3 Integration Methods
    def set_mode(self, mode: str):
        """
        Set agent mode (build, explore, debug, plan).
        
        Args:
            mode: One of 'build', 'explore', 'debug', 'plan'
        """
        valid_modes = ['build', 'explore', 'debug', 'plan']
        if mode in valid_modes:
            self._current_mode = mode
            log.info(f"Agent mode set to: {mode}")
        else:
            log.warning(f"Invalid mode: {mode}. Valid modes: {valid_modes}")
    
    def get_mode(self) -> str:
        """Get current agent mode."""
        return self._current_mode
    
    def _get_system_prompt_for_mode(self) -> str:
        """
        Get system prompt based on current mode using Prompt Manager.
        
        Returns:
            System prompt string
        """
        context = {
            'project_root': self._project_root or '',
            'current_file': self._active_file_path or '',
            'selected_code': ''
        }
        return self._prompt_manager.get_agent_mode_prompt(self._current_mode, context)
    
    def generate_chat_title(self, user_message: str, conversation_id: str) -> str:
        """
        Generate AI title for chat (Phase 1).
        
        Args:
            user_message: First user message
            conversation_id: Conversation ID
            
        Returns:
            Generated title
        """
        return self._title_generator.generate_title(user_message, conversation_id)
    
    def use_acp_for_task(self, task_description: str, agent_type: AgentType = None) -> str:
        """
        Route task through Agent Control Plane (Phase 3).
        
        Args:
            task_description: Task description
            agent_type: Type of agent to use
            
        Returns:
            Task ID
        """
        task_id = self._acp.create_task(task_description, agent_type)
        log.info(f"Task routed via ACP: {task_id}")
        return task_id
    
    def execute_skill(self, skill_id: str, capability: str, params: dict) -> any:
        """
        Execute a skill capability (Phase 3).
        
        Args:
            skill_id: Skill ID (e.g., 'builtin.code_analysis')
            capability: Capability name
            params: Parameters for capability
            
        Returns:
            Skill execution result
        """
        try:
            result = self._skill_registry.execute_capability(skill_id, capability, params)
            log.info(f"Skill executed: {skill_id}.{capability}")
            return result
        except Exception as e:
            log.error(f"Skill execution failed: {e}")
            return None
    
    def connect_mcp_server(self, name: str, server_url: str) -> bool:
        """
        Connect to MCP server (Phase 3).
        
        Args:
            name: Server name
            server_url: Server URL
            
        Returns:
            True if connected
        """
        success = self._mcp_manager.connect_server(name, server_url)
        if success:
            log.info(f"Connected to MCP server: {name}")
        return success
    
    def get_available_skills(self) -> list:
        """Get list of available skills."""
        return self._skill_registry.list_skills()
    
    def get_acp_agents(self) -> list:
        """Get list of ACP agents."""
        return self._acp.list_agents()
    
    # Phase 4 Methods
    def add_todo_task(self, session_id: str, description: str, 
                     priority: int = 2) -> str:
        """
        Add a todo task (Phase 4).
        
        Args:
            session_id: Session ID
            description: Task description
            priority: 1=high, 2=medium, 3=low
            
        Returns:
            Task ID
        """
        return self._todo_manager.add_task(session_id, description, priority)
    
    def get_session_todos(self, session_id: str) -> list:
        """Get all todo tasks for a session."""
        tasks = self._todo_manager.get_session_tasks(session_id)
        return [task.to_dict() for task in tasks]
    
    def complete_todo_task(self, task_id: str) -> bool:
        """Mark a todo task as completed."""
        return self._todo_manager.complete_task(task_id)
    
    def check_permission(self, tool_name: str, params: dict = None) -> tuple:
        """
        Check permission for a tool operation (Phase 4).
        
        Args:
            tool_name: Name of the tool
            params: Tool parameters
            
        Returns:
            (should_proceed, reason)
        """
        return self._permission_evaluator.evaluate(tool_name, params)
    
    def set_github_repository(self, owner: str, repo: str):
        """Set GitHub repository for automation (Phase 4)."""
        self._github_agent.set_repository(owner, repo)
    
    def analyze_github_pr(self, pr_number: int) -> dict:
        """
        Analyze a GitHub PR (Phase 4).
        
        Args:
            pr_number: PR number
            
        Returns:
            Analysis results
        """
        return self._github_agent.analyze_pr(pr_number)
    
    def get_github_metrics(self) -> dict:
        """Get Phase 4 component metrics."""
        return {
            "pending_todos": len(self._todo_manager.get_pending_tasks()),
            "permission_cache_size": len(self._permission_evaluator._permission_cache),
        }
    
    def get_metrics(self) -> dict:
        """Return a copy of current metrics."""
        return dict(self._metrics)

    def _record_request_start(self):
        self._metrics["requests_total"] += 1
        self._request_started_at = time.time()
        self._request_in_flight = True

    def _record_request_end(self, success: bool, error_category: str | None = None):
        if not self._request_in_flight:
            return
        elapsed_ms = 0
        if self._request_started_at:
            elapsed_ms = int((time.time() - self._request_started_at) * 1000)
        self._metrics["last_request_ms"] = elapsed_ms
        self._metrics["request_ms_total"] += elapsed_ms
        if success:
            self._metrics["requests_success"] += 1
        else:
            self._metrics["requests_error"] += 1
        self._request_in_flight = False
        self._request_started_at = None
        if error_category:
            log.info(
                f"[METRICS] request_end status=error category={error_category} ms={elapsed_ms}"
            )
        else:
            log.info(f"[METRICS] request_end status=success ms={elapsed_ms}")

    def set_interaction_mode(self, mode: str):
        """Set the interaction mode (Agent or Ask)."""
        self._mode = mode
        log.info(f"AI Agent interaction mode switched to: {mode}")
        # Enable always allow in Agent mode for full autonomy
        if mode == "Agent":
            self._always_allowed = True
            log.info("AI Agent: Auto-approval enabled for Agent mode")
    
    def enable_human_in_loop(self, enabled: bool = True):
        """
        Enable human-in-the-loop mode for critical operations.
        
        When enabled:
        - AI must get user confirmation before executing file modifications
        - Slows down the system to safe human speed
        
        Args:
            enabled: True to enable human approval required, False for full autonomy
        """
        self._require_human_approval = enabled
        if enabled:
            log.info("👤 Human-in-the-loop ENABLED - AI will ask before critical changes")
        else:
            log.info("⚡ Human-in-the-loop DISABLED - AI has full autonomy")
    
    def enable_autogen(self, enabled: bool = True, provider: str = "deepseek", model: str = None):
        """Enable or disable AutoGen multi-agent mode with DeepSeek.
        
        Args:
            enabled: Whether to enable AutoGen
            provider: "deepseek"
            model: Model ID (defaults to "deepseek-chat")
        """
        if not enabled:
            self._use_autogen = False
            log.info("⚪ AutoGen MULTI-AGENT MODE DISABLED")
            return
        
        try:
            from src.core.key_manager import get_key_manager
            key_manager = get_key_manager()
            
            # Get API key based on provider
            api_key = key_manager.get_key("deepseek")
            model = model or "deepseek-chat"
            provider_name = "DeepSeek"
            speed_info = "Reliable reasoning"
            
            if not api_key:
                log.warning(f"❌ {provider_name} API key not found. Add to .env file first.")
                return False
            
            self._autogen_system = init_autogen_system(api_key, provider=provider, model=model)
            self._use_autogen = True
            log.info(f"✅ AutoGen MULTI-AGENT MODE ENABLED! 🤖")
            log.info(f"   🚀 Powered by {provider_name} {model} ({speed_info})")
            log.info(f"   🤖 Agents: PM + Architect + Developer + QA + Reviewer")
            log.info(f"   🔒 Safe code execution with multi-agent review")
            return True
            
        except Exception as e:
            log.error(f"Failed to enable AutoGen: {e}")
            return False
    
    def disable_autogen(self):
        """Disable AutoGen and return to single-agent mode."""
        self._use_autogen = False
        self._autogen_system = None
        log.info("ℹ️ AutoGen disabled - using single-agent mode")
    
    def is_autogen_enabled(self) -> bool:
        """Check if AutoGen multi-agent mode is active."""
        return self._use_autogen and self._autogen_system is not None
        
    def _process_via_autogen(self, user_message: str, code_context: str):
        """Process message through AutoGen multi-agent system (1-2s responses!)."""
        try:
            log.info(f"🤖 AutoGen processing: {user_message[:50]}...")
                
            # Determine if code execution should be allowed
            execute_code = any(keyword in user_message.lower() for keyword in [
                "run", "execute", "test", "calculate", "compute", "generate"
            ])
                
            # Process through multi-agent system
            result = self._autogen_system.chat(user_message, execute_code=execute_code)
                
            if result["success"]:
                # Emit response
                response_text = result["response"]
                self.response_chunk.emit(response_text)
                self.response_complete.emit("✅ Multi-agent complete")
                    
                # Add to history
                self._history.append({
                    "role": "user",
                    "content": user_message
                })
                self._history.append({
                    "role": "assistant", 
                    "content": response_text
                })
                self._save_history_to_disk()
                    
                log.info(f"✅ AutoGen response emitted ({len(response_text)} chars)")
            else:
                error_msg = f"❌ AutoGen Error: {result.get('error', 'Unknown error')}"
                log.error(error_msg)
                self.request_error.emit(error_msg)
                    
        except Exception as e:
            error_msg = f"❌ AutoGen Exception: {str(e)}"
            log.error(error_msg)
            self.request_error.emit(error_msg)
    
    def _is_greeting(self, message: str) -> bool:
        """Check if message is a simple greeting - DISABLED for context-aware responses."""
        # Always return False to ensure all messages go through the AI
        # This ensures context-aware, intelligent responses even for greetings
        return False

    def _handle_project_warmup(self):
        """Handle greeting - DEPRECATED: Now handled by AI directly for context-aware responses"""
        # This method is kept for compatibility but should not be called
        # All messages now go through the AI for intelligent, context-aware responses
        pass

    def _analyze_and_plan(self, user_message: str) -> Optional[str]:
        """
        Use decision framework to analyze problem and create action plan.
        Returns enhanced system prompt with analysis, or None if not applicable.
        """
        if not self._decision_framework:
            return None
        
        # Check if message indicates a problem to solve
        problem_indicators = [
            "error", "crash", "bug", "fix", "broken", "not working",
            "failed", "exception", "traceback", "stuck", "infinite",
            "loop", "hang", "slow", "performance", "memory", "blank"
        ]
        
        is_problem = any(indicator in user_message.lower() for indicator in problem_indicators)
        
        if not is_problem:
            return None
        
        log.info(f"Decision framework: Analyzing problem: {user_message[:100]}")
        
        # Phase 1: Gather evidence
        evidence = self._decision_framework.gather_evidence(
            error_message=user_message,
            context=f"Project: {self._project_root}"
        )
        
        # Phase 2: Analyze
        analysis = self._decision_framework.analyze_problem(evidence)
        
        # Phase 3: Create action plan
        plan = self._decision_framework.create_action_plan(analysis)
        
        # Return enhanced prompt
        return self._decision_framework.to_system_prompt()

    def _check_configuration(self):
        """Check and log AI configuration status."""
        # Default to DeepSeek as the primary provider
        provider = self._settings.get("ai", "provider") or "deepseek"
        model = self._settings.get("ai", "model") or "deepseek-chat"
        
        log.info(f"AI Agent initialized with provider: {provider}, model: {model}")
        
        # Check if API key exists for non-mock providers
        if provider != "mock":
            key_manager = get_key_manager()
            api_key = key_manager.get_key(provider)
            
            if not api_key:
                # Fallback to env
                api_key = os.getenv(f"{provider.upper()}_API_KEY", "")
            
            if api_key:
                log.info(f"API key found for {provider}")
            else:
                log.warning(f"No API key found for {provider}. Using mock mode or add key via AI -> API Key Settings")

    def set_terminal(self, terminal_widget):
        """Connect a terminal widget to the AI agent's tool registry."""
        self._tool_registry.terminal_widget = terminal_widget
        
        # Forward terminal output lines to chat as streaming chunks
        if hasattr(terminal_widget, 'terminal_line_for_chat'):
            terminal_widget.terminal_line_for_chat.connect(
                self._on_terminal_line_for_chat
            )
    
    def set_ui_parent(self, ui_parent):
        """Set the UI parent widget for permission dialogs."""
        self._tool_registry.set_ui_parent(ui_parent)
        log.info("Permission system connected to UI")

    def set_project_root(self, path: str):
        """Set project root and load project-specific history."""
        # Clear any existing context first to prevent cross-contamination
        self._history.clear()
        self._history_summary = ""
        self._active_file_path = None
        self._cursor_position = None
        self._warmup_shown = False  # Reset for new project
        self._auto_verify_attempts = 0
        self._auto_verify_in_progress = False
        self._pending_verify_files.clear()
        
        self._project_root = path
        self._tool_registry.set_project_root(path)
        
        # Initialize decision framework for this project
        self._decision_framework = get_decision_framework(path)
        reset_decision_framework()  # Start fresh for new project
        
        # Initialize AutoGen multi-agent system if enabled
        if self._autogen_enabled and self._autogen_system is None:
            try:
                from src.ai.autogen_wrapper import create_standard_team
                from src.core.key_manager import get_key_manager
                
                key_manager = get_key_manager()
                deepseek_key = key_manager.get_key("deepseek")
                
                if deepseek_key:
                    self._autogen_system = create_standard_team(deepseek_key)
                    log.info("✅ AutoGen Multi-Agent System initialized with DeepSeek")
                else:
                    log.warning("⚠️ DeepSeek API key not found - AutoGen disabled")
                    self._autogen_enabled = False
            except Exception as e:
                log.error(f"Failed to initialize AutoGen: {e}")
                self._autogen_enabled = False
        
        log.info(f"AI Agent context switched to project: {path}")
    
    def set_project_context(self, context):
        """Called when background project scan completes."""
        self._project_context = context
        log.info(f"Project context set: {context.project_type}, "
                 f"{context.source_file_count} source files")
    
    # Token budget for context window management
    TOKEN_BUDGET = {
        "system_prompt":    2000,   # SYSTEM_PROMPT constant
        "project_context":  10000,  # ProjectContext.to_system_prompt_block()
        "history_summary":  5000,    # _history_summary
        "recent_history":  25000,   # last 10-15 turns
        "current_message":  8000,    # user's current message + context
        "response_reserve": 16384,   # max_tokens for response
        # Total: ~65K — within 64K window
    }
    
    def _build_system_content(self) -> str:
        """Build system content with strict token budgets."""
        from src.ai.project_context import get_project_context
        
        parts = []
        parts.append(self.SYSTEM_PROMPT)
        
        # Project context - use cached version ALWAYS
        if self._project_root:
            # Check if we have cached context from previous message
            if hasattr(self, '_cached_project_context') and self._cached_project_context:
                parts.append(self._cached_project_context)
                log.debug("Using cached project context from previous message")
            else:
                # Try to get fresh context
                ctx = get_project_context(self._project_root)
                if ctx and ctx.is_ready:
                    ctx_block = ctx.to_system_prompt_block()
                    if len(ctx_block) > 8000:
                        ctx_block = ctx_block[:8000] + "\n... (truncated)"
                    parts.append(ctx_block)
                    self._cached_project_context = ctx_block  # Cache for next time
                    log.debug("Built and cached new project context")
                else:
                    # No context available - use minimal placeholder
                    parts.append(f"## PROJECT ROOT\n{self._project_root}")
                    log.debug("No project context available, using minimal placeholder")
        
        # 🚀 FRAMEWORK-SPECIFIC GUIDANCE (CRITICAL FOR REDUCING HALLUCINATION)
        framework_guidance = []
        ctx = get_project_context(self._project_root) if self._project_root else None
        
        if ctx and ctx.is_ready:
            fws = [fw.lower() for fw in (ctx.frameworks or [])]
            if "django" in fws:
                framework_guidance.append(
                    "## DJANGO TECHNICAL GUIDANCE\n"
                    "- Use Django template syntax: `{% static '...' %}`, `{% url '...' %}`, `{% csrf_token %}`.\n"
                    "- DO NOT use Flask's `url_for`.\n"
                    "- Check `settings.py` for INSTALLED_APPS and TEMPLATES config.\n"
                    "- Models should inherit from `models.Model`."
                )
            elif "flask" in fws:
                framework_guidance.append(
                    "## FLASK TECHNICAL GUIDANCE\n"
                    "- Use Flask's `{{ url_for('static', filename='...') }}` and `{{ url_for(...) }}`.\n"
                    "- Check `app.py` or `wsgi.py` for route definitions."
                )
            elif "react" in fws:
                framework_guidance.append(
                    "## REACT TECHNICAL GUIDANCE\n"
                    "- Use functional components and hooks (useEffect, useState).\n"
                    "- Prefer Tailwind CSS if requested or present in dependencies.\n"
                    "- Check `package.json` for React version and scripts."
                )
        
        if framework_guidance:
            parts.append("\n\n".join(framework_guidance))

        # 🖥️ OS & SHELL CONTEXT (PREVENT WINDOWS/LINUX CONFUSION)
        import platform
        os_name = platform.system()
        parts.append(
            f"## ENVIRONMENT CONTEXT\n"
            f"- **Operating System**: {os_name}\n"
            f"- **Preferred Shell**: {'PowerShell' if os_name == 'Windows' else 'Bash'}\n"
            f"- **Guidance**: You are on {os_name}. Use appropriate syntax. "
            f"{'In PowerShell, `ls`, `cat`, `rm`, `cp`, `mv` are available as aliases. Use `(Get-Content file | Measure-Object -Line).Lines` for line counting.' if os_name == 'Windows' else ''}"
        )

        # 🔄 INFINITE LOOP PROTECTION
        parts.append(
            "## INFINTIE LOOP PROTECTION\n"
            "1. **Never repeat failed tools**: If a tool fails, don't just try it again with the same arguments. Change your approach.\n"
            "2. **Verify before write**: Before using `write_file` or `edit_file`, check if the file already exists and has the desired content. Do not overwrite if no change is needed.\n"
            "3. **Detect 'Already Done' status**: If the user's goal is already met by existing files, stop and explain what you found instead of recreating them."
        )
            
        # History summary
        if self._history_summary:
            summary = self._history_summary
            if len(summary) > 4000:
                summary = summary[:4000] + "..."
            parts.append(f"## CONVERSATION SUMMARY\n{summary}")
        
        # Warmup instruction
        warmup_block = self._get_warmup_instruction()
        if warmup_block:
            parts.append(warmup_block)
        
        return "\n\n".join(parts)
    
    def _get_warmup_instruction(self) -> str:
        """Get warmup instruction for first message (returns empty string after)."""
        if self._warmup_shown or not self._project_root:
            return ""
        
        from src.ai.project_context import get_project_context
        ctx = get_project_context(self._project_root)
        
        if ctx and ctx.is_ready:
            # Context already built — instruct AI to use it, not re-scan
            return (
                "## FIRST INTERACTION — PROJECT ALREADY INDEXED\n"
                "The project context block above contains the complete project analysis.\n"
                "Use it to respond immediately without calling list_directory.\n"
                "Present a structured overview then ask what the user wants to work on."
            )
        else:
            return (
                f"## FIRST INTERACTION — EXPLORE PROJECT\n"
                f"Project root: {self._project_root}\n"
                f"1. Start with list_directory('{self._project_root}')\n"
                f"2. Read README.md and 1-2 key config files\n"
                f"3. Present: project type, stack, structure, what you can help with\n"
                f"4. Stay within the project root — do NOT read venv/node_modules"
            )
        
        # Only load history if this is not a fresh/empty project switch
        # The history will be loaded by _on_project_opened if needed
        # self._load_history_from_disk(path)
        
        # Initialize context manager with new project root
        from src.ai.context_manager import get_context_manager
        self._context_manager = get_context_manager(path)
        
        # Clear any cached context from previous project
        if self._context_manager:
            self._context_manager.set_active_file(None)
            self._context_manager._mentioned_files_history.clear()
            self._context_manager._session_context.clear()

    def set_active_file(self, file_path: str, cursor_position: tuple = None):
        """Set the currently active file in the editor for context injection."""
        self._active_file_path = file_path
        self._cursor_position = cursor_position
        if self._context_manager:
            self._context_manager.set_active_file(file_path, cursor_position)
        log.debug(f"Active file set: {file_path} at position {cursor_position}")
    
    def clear_active_file(self):
        """Clear the active file context when switching projects."""
        self._active_file_path = None
        self._cursor_position = None
        if self._context_manager:
            self._context_manager.set_active_file(None)
        log.debug("Active file cleared")

    def _on_terminal_line_for_chat(self, line: str):
        """
        Forward terminal output to aichat.html with intelligent batching.
        Batches up to 50 lines before sending to prevent UI freeze.
        """
        self._terminal_batcher.add_line(line)
    
    def _flush_terminal_output(self, output: str):
        """Flush batched terminal output to UI."""
        if output:
            self.response_chunk.emit(f"<terminal_output>{output}</terminal_output>")

    def chat(self, user_message: Optional[str], code_context: str = ""):
        """Send a message and get a streamed response with intelligent model switching."""
        
        # Reset creation mode on new user message (start fresh for new task)
        if user_message is not None:
            # Check if this is a creation task - enable creation mode immediately
            creation_keywords = ["create", "build", "make", "generate", "write", "add", "implement", "new file", "new project"]
            is_creation_task = any(kw in user_message.lower() for kw in creation_keywords)
            
            if is_creation_task:
                self._creation_mode = True
                log.info(f"[CREATION_MODE] Enabled for creation task")
            
            # Reset snapshots for new user message
            self._pre_edit_snapshots = {}
            log.debug("[CREATION_MODE] Reset for new user message")
        
        # 🧠 DYNAMIC MODEL SWITCHING (DISABLED - User selection takes priority)
        # This was causing unwanted switches to deepseek-reasoner for build tasks
        # if user_message and self._settings:
        #     words = user_message.lower().split()
        #     # Detect complexity
        #     is_complex = any(cmd in words for cmd in ["fix", "build", "create", "implement", "debug", "refactor", "error", "how", "why"])
        #     is_very_short = len(words) < 4
        #     
        #     current_provider = self._settings.get("ai", "provider")
        #     
        #     # DeepSeek: Switch between Chat (fast) and Reasoner (R1)
        #     if current_provider == "deepseek":
        #         target_model = "deepseek-reasoner" if is_complex else "deepseek-chat"
        #         self._settings.set("ai", "model", target_model)
        #         log.info(f"🔄 Task-based switch (DeepSeek): {target_model}")
            
        # 🤖 AUTOGEN MULTI-AGENT MODE CHECK
        if self._use_autogen and self._autogen_system and user_message:
            log.info("🤖 Processing via AutoGen multi-agent system...")
            self._process_via_autogen(user_message, code_context)
            return
            
        # Clean up finished worker if exists
        if self._worker and not self._worker.isRunning():
            log.debug("Cleaning up finished worker")
            self._worker.wait(100)  # Brief wait to ensure cleanup
            self._worker = None
            
        if self._worker and self._worker.isRunning():
            log.warning("AI worker already running, skipping request.")
            return
            
        if user_message is not None:
            # Check if this is a greeting - if so, do warmup instead of AI call
            if self._is_greeting(user_message):
                self._handle_project_warmup()
                return
            
            # Check for pending tool confirmation
            if self._pending_tool_calls:
                # Check if user confirmed (yes, ok, sure, proceed, etc.)
                confirmation_words = ['yes', 'yeah', 'yep', 'ok', 'okay', 'sure', 'proceed', 'confirm', 'do it', 'go ahead']
                is_confirmed = any(word in user_message.lower() for word in confirmation_words)
                
                if is_confirmed:
                    log.info("User confirmed pending tools execution")
                    self._execute_pending_tools()
                else:
                    log.info("User did not confirm, cancelling pending tools")
                    self._cancel_pending_tools()
                    self.response_chunk.emit("\n❌ Action cancelled. Let me know if you need anything else.")
                    self.response_complete.emit("Action cancelled.")
                return

            # Record start of a new user request for metrics
            self._record_request_start()
            
            # Build context-aware message using Context Manager
            if self._context_manager:
                # Get automatic context with file relevance detection
                chat_context = self._context_manager.get_context_for_query(
                    query=user_message,
                    active_file_path=self._active_file_path,
                    cursor_position=self._cursor_position
                )
                
                # Format context for AI
                context_prompt = self._context_manager.format_context_for_ai(chat_context)
                
                # Build final message with context
                content = f"{context_prompt}\n\n## USER QUERY\n{user_message}\n\nPlease provide assistance based on the above context."
                
                # Update session context
                self._context_manager.update_session_context({
                    "role": "user",
                    "content": user_message,
                    "timestamp": "now"
                })
            else:
                # Fallback to basic code context if context manager not available
                content = user_message
                if code_context.strip():
                    content = f"{user_message}\n\n**Code context:**\n```\n{code_context}\n```"
            
            self._history.append({"role": "user", "content": content})
            self._save_history_to_disk()

        # Trigger summarization if history gets too long (e.g., > 25 messages)
        # Summarize the first 10 messages if we hit 25.
        if len(self._history) >= 25:
            self._summarize_history(10)

        # Build system content with context budget enforcement
        system_content = self._build_system_content()
        
        # Apply decision framework for problem-solving scenarios
        if user_message:
            decision_prompt = self._analyze_and_plan(user_message)
            if decision_prompt:
                system_content += f"\n\n{decision_prompt}"
        
        self._warmup_shown = True  # Mark warmup as shown after building system content
            
        # Use trimmed history to prevent orphaned tool messages (Error 400)
        history_msgs = self._get_trimmed_history(20)
        
        # FINAL SANITY CHECK: Remove any leading 'tool' messages that lost their 'assistant' parent
        # This protects against cases where history was manipulated elsewhere
        while history_msgs and history_msgs[0]["role"] == "tool":
            log.warning("Dropping orphaned tool message from history start")
            history_msgs.pop(0)

        # LOGGING FOR DEEPSEEK DEBUGGING
        role_sequence = [m["role"] for m in history_msgs]
        log.debug(f"DeepSeek History Roles: {role_sequence}")
        
        # Verify tool call counts for last assistant
        for i, msg in enumerate(history_msgs):
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                count = len(msg["tool_calls"])
                responses = 0
                for j in range(i + 1, len(history_msgs)):
                    if history_msgs[j]["role"] == "tool":
                        responses += 1
                    else:
                        break
                if responses < count:
                    log.error(f"MISMATCH: Assistant has {count} tool calls but only {responses} responses followed. Trimming this block.")
                    # In a real fix, we'd handle this, but for now we log it.

        mode_hint = ""
        if self._mode == "Ask":
            mode_hint = "## MODE: ASK\nYou are in ASK mode. Focus on answering questions and explaining concepts. DO NOT use structural tags like <plan> or use tools to modify the project unless explicitly directed by the user."
        elif self._mode == "Plan":
            mode_hint = "## MODE: PLAN\nYou are in PLAN mode. Focus on architectural design and implementation strategies. ALWAYS use the <plan> tag to provide structured, step-by-step technical blueprints. DO NOT implement code yourself; guide the user instead."
        else:
            mode_hint = "## MODE: AGENT\nYou are in AGENT mode. Be proactive. Explore the codebase, identify issues, and implement fixes or new features autonomously."

        messages = [
            {"role": "system", "content": system_content},
            {"role": "system", "content": mode_hint}
        ] + history_msgs

        # Token counting guard - estimate and summarize if too large
        estimated_tokens = self._estimate_token_count(messages)
        if estimated_tokens > 50000:  # Leave room for response
            log.warning(f"Context too large ({estimated_tokens} est. tokens). Triggering summarization.")
            self._summarize_history(15)
            # Rebuild history after summarization
            history_msgs = self._get_trimmed_history(20)
            messages = [
                {"role": "system", "content": system_content},
                {"role": "system", "content": mode_hint}
            ] + history_msgs
            estimated_tokens = self._estimate_token_count(messages)
            log.info(f"After summarization: {estimated_tokens} est. tokens")

        # Get provider and model from settings
        provider = self._settings.get("ai", "provider") or "deepseek"
        model = self._settings.get("ai", "model") or "deepseek-chat"
        
        # Log which provider and model are being used
        log.info(f"[AI Agent] Using provider: {provider}, model: {model}")
        temperature = float(self._settings.get("ai", "temperature") or 0.7)
        # Increase max_tokens to 8192 for large code generation
        max_tokens = int(self._settings.get("ai", "max_tokens") or 8192)

        # Validate API key exists for non-mock providers
        if provider != "mock":
            api_key = os.getenv(f"{provider.upper()}_API_KEY", "")
            if not api_key:
                key_manager = get_key_manager()
                api_key = key_manager.get_key(provider)
            
            if not api_key:
                error_msg = (
                    f"No API key configured for {provider}.\n\n"
                    f"Please add your key via: AI → API Key Settings\n"
                    f"Or set the {provider.upper()}_API_KEY environment variable."
                )
                log.error(error_msg)
                self.request_error.emit(error_msg)
                return

        # Prepare tools for AI
        tools_list = []
        for tool in self._tool_registry.get_all_tools().values():
            # Convert to OpenAI-style tool definition
            properties = {}
            for p in tool.parameters:
                # Map Python-style types to standard JSON Schema types
                json_type = p.type
                if json_type == "int": json_type = "integer"
                elif json_type == "bool": json_type = "boolean"
                
                properties[p.name] = {
                    "type": json_type,
                    "description": p.description
                }

            tools_list.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": [p.name for p in tool.parameters if p.required]
                    }
                }
            })

        # ADAPTIVE TOOL SELECTION: Dynamically filter tools based on conversation context
        # This reduces API payload size and prevents timeouts
        original_count = len(tools_list)
        
        try:
            # Use adaptive selector to choose relevant tools
            tools_list = select_tools_adaptively(
                messages=messages,
                user_message=user_message,
                all_tools=tools_list,
                max_tools=12,  # Reduced from 39 to prevent API timeout
                creation_mode=self._creation_mode
            )
            
            selected_count = len(tools_list)
            tool_names = [t['function']['name'] for t in tools_list]
            
            log.info(f"[ADAPTIVE_TOOLS] Selected {selected_count}/{original_count} tools based on conversation context")
            log.info(f"[ADAPTIVE_TOOLS] Tools: {tool_names[:8]}{'...' if len(tool_names) > 8 else ''}")
            
            # Track tool usage for learning
            selector = get_adaptive_tool_selector()
            phase = selector.analyze_conversation_phase(messages, user_message)
            log.info(f"[ADAPTIVE_TOOLS] Conversation phase: {phase.value}")
            
        except Exception as e:
            log.warning(f"[ADAPTIVE_TOOLS] Selection failed: {e}, using fallback filtering")
            # Fallback to old method if adaptive selection fails
            
            if self._creation_mode:
                tools_list = [
                    t for t in tools_list
                    if t["function"]["name"] not in self._creation_mode_tool_blocklist
                ]
                log.info(f"[CREATION_MODE_FALLBACK] Filtered {original_count} → {len(tools_list)} tools")

        # Inject a trigger if it's an automated plan request
        if user_message == "__GENERATE_PLAN__":
            messages.append({"role": "user", "content": "Analyze the project context and generate a detailed <plan>, <tasklist>, and initial steps for implementation."})
        
        # FINAL DEEPSEEK SANITIZATION: Ensure every tool-call assistant is followed by its responses
        sanitized_messages = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            tool_calls = msg.get("tool_calls")
            if msg["role"] == "assistant" and isinstance(tool_calls, list) and tool_calls:
                call_ids = [tc["id"] for tc in tool_calls if isinstance(tc, dict) and "id" in tc]
                following_tools = []
                j = i + 1
                while j < len(messages) and messages[j]["role"] == "tool":
                    following_tools.append(messages[j])
                    j += 1
                
                # Check if all call_ids are answered
                answered_ids = [t["tool_call_id"] for t in following_tools]
                if all(cid in answered_ids for cid in call_ids):
                    # Complete block
                    sanitized_messages.append(msg)
                    sanitized_messages.extend(following_tools)
                    i = j # Skip to after the tools
                else:
                    log.warning(f"Dropping incomplete tool block at index {i}. Needs {len(call_ids)}, found {len(following_tools)}.")
                    # Drop the assistant entirely, skip the orphaned tools
                    i = j
            else:
                # User, System, or plain Assistant message
                if msg["role"] != "tool": # Tool messages MUST be handled in blocks
                    sanitized_messages.append(msg)
                else:
                    log.warning(f"Dropping orphaned tool message at index {i}")
                i += 1

        # Configure tools based on provider
        # DeepSeek: Full tool support with reliable execution
        tools_for_worker = tools_list if provider != "mock" else None
        
        log.info(f"Creating AI worker with {len(sanitized_messages)} messages, model={model}, provider={provider}")
        self._worker = AIWorker(sanitized_messages, model, temperature, max_tokens, provider, tools=tools_for_worker)
        self._worker.chunk_received.connect(self.response_chunk)
        self._worker.finished.connect(self._on_done)
        self._worker.error_occurred.connect(self._on_error)
        log.info("Starting AI worker thread...")
        self.thinking_started.emit()  # Show thinking indicator
        self._worker.start()
        log.info(f"AI worker started, isRunning={self._worker.isRunning()}")

    def _get_trimmed_history(self, limit: int = 20) -> list[dict]:
        """
        Get history trimmed to limit while ensuring tool call integrity.
        Ensures that if an assistant call is included, all its tool responses are included,
        and if a tool response is included, its assistant call is also included.
        """
        if len(self._history) <= limit:
            return self._history
            
        # Start at the limit
        start_idx = len(self._history) - limit
        
        # Expand backwards to include any parent assistant for orphaned tools
        # or forward to exclude orphaned tools/calls.
        # Simpler approach: find the first message that isn't part of an incomplete tool sequence.
        
        while start_idx > 0:
            msg = self._history[start_idx]
            role = msg.get("role")
            
            if role == "tool":
                # Must go back to find the assistant
                start_idx -= 1
                continue
            
            if role == "assistant" and msg.get("tool_calls"):
                # If we include this, we are good. If we were in the middle of tools, 
                # we've now reached the head. 
                break
                
            # If the NEXT message is a tool, we must go back to include this assistant/parent
            if start_idx + 1 < len(self._history) and self._history[start_idx+1].get("role") == "tool":
                start_idx -= 1
                continue
                
            break
            
        return self._history[start_idx:]

    def _estimate_token_count(self, messages: list) -> int:
        """Rough estimate: 1 token ≈ 4 characters (industry standard approximation)"""
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            # Also count tool calls if present
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                total_chars += len(json.dumps(tool_calls))
        return total_chars // 4

    def _summarize_history(self, count: int = 10):
        """
        Summarize the oldest part of history and remove it.
        Runs synchronously (blocking short call) for simplicity in state management.
        """
        if len(self._history) < count:
            return
            
        # Find a safe split point near 'count' that doesn't break tool call pairs
        split_idx = count
        while split_idx < len(self._history):
            msg = self._history[split_idx]
            if msg["role"] == "tool":
                # tool message must stay with its preceding assistant message
                split_idx += 1
            else:
                break
        
        # In case the message EXACTLY at split_idx-1 is an assistant with tool_calls
        # but the tool response hasn't arrived yet (unlikely but possible), 
        # we should probably wait or include it in the next summary.
        # But for now, we just take the chunk.
        
        to_summarize = self._history[:split_idx]
        self._history = self._history[split_idx:]
        
        log.info(f"Summarizing {count} messages...")
        
        # Prepare a special request to summarize
        summary_prompt = "Summarize the following conversation segment concisely, focusing on technical decisions, progress made, and current status. Preserve essential context for a coding agent."
        
        # Use provider directly to avoid recursive chat turns
        provider_name = self._settings.get("ai", "provider") or "deepseek"
        
        # Map provider name to ProviderType
        provider_type_map = {
            "deepseek": ProviderType.DEEPSEEK,
            "mistral": ProviderType.MISTRAL,
            "siliconflow": ProviderType.SILICONFLOW,
        }
        provider_type = provider_type_map.get(provider_name, ProviderType.DEEPSEEK)
        provider = get_provider_registry().get_provider(provider_type)
        
        # Format messages for summarization
        # Include previous summary if it exists
        sum_messages = []
        if self._history_summary:
            sum_messages.append(ChatMessage(role="system", content=f"Current summary: {self._history_summary}"))
        
        sum_messages.append(ChatMessage(role="user", content=f"{summary_prompt}\n\nSEGMENT:\n{json.dumps(to_summarize, indent=2)}"))
        
        try:
            # We use a non-streaming call for the summary
            response = provider.chat(
                messages=sum_messages,
                model="deepseek-chat" if provider_name != "mock" else "mock-model",
                max_tokens=500
            )
            
            if response.content:
                self._history_summary = response.content
                log.info("History summarization complete.")
                self._save_history_to_disk()
        except Exception as e:
            log.error(f"Failed to summarize history: {e}")
            # If it fails, we've already dropped messages from _history, 
            # but we didn't crash. Next turn will just proceed with partial context.

    def _get_project_id(self) -> str:
        """Create a unique stable ID based on the project path."""
        if not self._project_root:
            return "default"
        # Normalize path and hash it
        root_path = str(self._project_root)
        path_norm = os.path.normpath(root_path).lower()
        return hashlib.md5(path_norm.encode()).hexdigest()[:12]

    def _save_history_to_disk(self):
        """Persist history and summary to project-specific file."""
        if not self._project_root:
            return
            
        project_id = self._get_project_id()
        storage_dir = Path.home() / ".cortex" / "history"
        storage_dir.mkdir(parents=True, exist_ok=True)
        history_file = storage_dir / f"history_{project_id}.json"
        
        try:
            root_path = str(self._project_root)
            data = {
                "project_path": root_path,
                "summary": self._history_summary,
                "history": self._history,
                "updated_at": os.path.getmtime(root_path) if os.path.exists(root_path) else 0
            }
            history_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.error(f"Failed to save history: {e}")

    def _load_history_from_disk(self, project_path: str):
        """Restore history and summary for a specific project."""
        self._project_root = project_path
        project_id = self._get_project_id()
        history_file = Path.home() / ".cortex" / "history" / f"history_{project_id}.json"
        
        if not history_file.exists():
            log.info(f"No existing history found for project ID: {project_id}")
            self._history = []
            self._history_summary = ""
            return
            
        try:
            data = json.loads(history_file.read_text(encoding="utf-8"))
            raw_history = data.get("history", [])
            self._history_summary = data.get("summary", "")
            
            # Clean up corrupted history with mismatched tool calls
            self._history = self._sanitize_loaded_history(raw_history)
            
            if len(self._history) != len(raw_history):
                log.warning(f"Sanitized history: removed {len(raw_history) - len(self._history)} corrupted messages")
            
            log.info(f"Restored history for project {project_id} ({len(self._history)} messages)")
            
            # 🚀 RESUME INTELLIGENCE: Reparse todos and offer to continue
            if self._history:
                # Find last assistant message to restore UI state (todos, plan)
                for msg in reversed(self._history):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        log.info("Restoring UI todos from last session...")
                        self._parse_and_emit_todos(msg["content"])
                        break
                        
                # Proactively offer to resume work after a short delay (once bridge is ready)
                QTimer.singleShot(1500, self._emit_resume_hint)
                
        except Exception as e:
            log.error(f"Failed to load history: {e}")
            self._history = []
            self._history_summary = ""

    def _emit_resume_hint(self):
        """Emit a friendly nudge to resume work when project is reopened."""
        if not self._history or self._warmup_shown:
            return
            
        # Only show if the user hasn't typed anything yet
        resume_msg = "\n\n👋 **Welcome back!** I've restored your last session's context and task list. Ready to continue where we left off?"
        self.response_chunk.emit(resume_msg)
        self.response_complete.emit("Session restored.")
        self._warmup_shown = True # Prevent double warmup
    
    def _sanitize_loaded_history(self, history: list[dict]) -> list[dict]:
        """Remove corrupted messages with mismatched tool calls from loaded history."""
        sanitized = []
        skip_until = -1
        
        for i, msg in enumerate(history):
            if i <= skip_until:
                continue
                
            role = msg.get("role")
            tool_calls = msg.get("tool_calls")
            
            # If this is an assistant with tool_calls, verify all responses exist
            if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
                call_ids = [tc.get("id") for tc in tool_calls if isinstance(tc, dict)]
                expected_count = len(call_ids)
                
                # Count following tool responses
                following_tools = 0
                found_ids = set()
                j = i + 1
                while j < len(history) and history[j].get("role") == "tool":
                    tool_msg = history[j]
                    tool_call_id = tool_msg.get("tool_call_id")
                    if tool_call_id in call_ids:
                        found_ids.add(tool_call_id)
                        following_tools += 1
                    j += 1
                
                # Only keep if all tool calls have matching responses
                if len(found_ids) == expected_count:
                    sanitized.append(msg)
                    # Also add the tool responses
                    for k in range(i + 1, j):
                        if history[k].get("tool_call_id") in found_ids:
                            sanitized.append(history[k])
                    skip_until = j - 1
                else:
                    log.warning(f"Dropping corrupted assistant block at index {i}: {len(found_ids)}/{expected_count} tool responses found")
                    skip_until = j - 1  # Skip the orphaned tool responses too
            elif role == "tool":
                # Skip orphaned tool messages (they'll be handled with their parent or dropped)
                if i > 0 and history[i-1].get("role") == "assistant":
                    # This should have been handled above, but if not, skip it
                    pass
                else:
                    log.warning(f"Dropping orphaned tool message at index {i}")
            else:
                # Regular message (user, system, assistant without tool_calls)
                sanitized.append(msg)
        
        return sanitized

    def _on_done(self, full_text: str):
        log.info(f"_on_done called, full_text length={len(full_text)}, worker={self._worker}")
        self.thinking_stopped.emit()  # Hide thinking indicator
        
        # Parse and emit TODOs if present, and clean the text for UI display
        full_text = self._parse_and_emit_todos(full_text)
        
        # Clear worker reference since it's done
        worker = self._worker
        self._worker = None
        
        tool_calls = getattr(worker, "tool_calls", None)
        log.info(f"Tool calls from worker: {tool_calls is not None}")
        
        # DEBUG: Log worker attributes to see what was extracted
        if hasattr(worker, 'tool_call_buffer'):
            log.info(f"[DEBUG] Worker tool_call_buffer: {worker.tool_call_buffer}")
        if hasattr(worker, '_full_response'):
            log.info(f"[DEBUG] Worker full_response length: {len(worker._full_response)}")
            log.info(f"[DEBUG] Worker full_response preview: {worker._full_response[:300]}")
        
        if tool_calls:
            # Handle tool calls - DON'T add to history yet, wait for tool responses
            # This prevents the mismatch where assistant has tool_calls but no tool responses yet
            
            # Check if any tool requires confirmation
            requires_approval = False
            for tc in tool_calls:
                tool = self._tool_registry.get_tool(tc["function"]["name"])
                if tool and tool.requires_confirmation:
                    requires_approval = True
                    break
            
            if requires_approval and not self._always_allowed:
                # Store pending for approval
                self._pending_tool_calls = tool_calls
                self._pending_assistant_content = full_text
                
                # Emit structured permission block for UI buttons
                permission_data = []
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try: args = json.loads(tc["function"]["arguments"])
                    except: args = {}
                    permission_data.append({"name": name, "info": self._get_tool_status_info(name, args).replace("...", "")})
                
                perm_block = f"\n<permission>\n{json.dumps(permission_data)}\n</permission>\n"
                self.response_chunk.emit(perm_block)
                self.response_complete.emit(full_text + perm_block)
            else:
                # Execute tools immediately - add assistant + tools atomically
                self._execute_tools(tool_calls, full_text)
                return  # Return early - continuation will be triggered by _on_all_tools_completed
        else:
            self._history.append({"role": "assistant", "content": full_text})
            self.response_complete.emit(full_text)
            self._record_request_end(success=True)
            
        # Refactor: Save workflow tags to physical files in .cortex/
        self._save_workflow_files(full_text)
        self._save_history_to_disk()

    def _execute_tools(self, tool_calls, assistant_content=""):
        """Execute tool calls in background thread for MAXIMUM UI responsiveness."""
        
        # First, check if tool_calls is valid
        if not tool_calls:
            log.warning("[AGENTIC] No tool calls to execute")
            return
        
        if not isinstance(tool_calls, list):
            log.error(f"[AGENTIC] tool_calls is not a list: {type(tool_calls)}")
            return
        
        # AGENTIC VALIDATION: Validate and fix tool calls before execution
        validated_tool_calls = []
        validation_errors = []
        
        log.info(f"[AGENTIC] Validating {len(tool_calls)} tool calls...")
        
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name", "")
            arguments_str = tc.get("function", {}).get("arguments", "{}")
            
            try:
                # Parse arguments with repair attempt
                if isinstance(arguments_str, str):
                    try:
                        arguments = json.loads(arguments_str) if arguments_str else {}
                    except json.JSONDecodeError as je:
                        log.warning(f"[AGENTIC] JSON parse failed, attempting repair: {je}")
                        log.debug(f"[AGENTIC] Problematic JSON (first 200 chars): {arguments_str[:200]}...")
                        repaired = _try_repair_json(arguments_str)
                        if repaired:
                            log.info("[AGENTIC] JSON repair successful")
                            arguments = repaired
                        else:
                            log.error(f"[AGENTIC] JSON repair FAILED for: {arguments_str[:100]}...")
                            raise je
                else:
                    arguments = arguments_str
                
                # Get tool schema from registry
                tool = self._tool_registry.get_tool(tool_name)
                if tool:
                    # Validate required parameters
                    required_params = [p.name for p in tool.parameters if p.required]
                    missing_params = [p for p in required_params if p not in arguments or not arguments[p]]
                    
                    if missing_params:
                        error_msg = f"Tool '{tool_name}' missing required parameters: {missing_params}"
                        log.warning(f"[AGENTIC VALIDATION] {error_msg}")
                        validation_errors.append({"tool": tool_name, "error": error_msg, "missing": missing_params})
                        
                        # Try to provide intelligent defaults for common tools
                        if tool_name in ["read_file", "edit_file"] and "path" in missing_params:
                            # Cannot proceed without path - skip this tool call
                            continue
                        elif tool_name == "write_file" and "path" in missing_params:
                            continue
                        elif tool_name == "search_code" and "pattern" in missing_params:
                            continue
                        else:
                            # Skip invalid tool call
                            continue
                
                # Tool call is valid
                validated_tool_calls.append(tc)
                
            except json.JSONDecodeError as e:
                log.error(f"[AGENTIC VALIDATION] Failed to parse arguments for {tool_name}: {e}")
                validation_errors.append({"tool": tool_name, "error": f"Invalid JSON: {e}"})
            except Exception as e:
                log.error(f"[AGENTIC VALIDATION] Error validating {tool_name}: {e}")
                validation_errors.append({"tool": tool_name, "error": str(e)})
        
        # If we have validation errors, we need to inform the AI and ask it to fix them
        if validation_errors:
            # Build error feedback for the AI
            error_feedback = "\n⚠️ **TOOL VALIDATION ERRORS** ⚠️\n\n"
            error_feedback += "The following tool calls were INVALID and rejected:\n\n"
            for err in validation_errors:
                error_feedback += f"❌ `{err['tool']}`: {err['error']}\n"
                if 'missing' in err:
                    error_feedback += f"   Missing: {', '.join(err['missing'])}\n"
            
            error_feedback += "\n**HOW TO FIX:**\n"
            error_feedback += "1. Review the tool parameters required\n"
            error_feedback += "2. Provide ALL required parameters\n"
            error_feedback += "3. Use correct parameter names\n"
            error_feedback += "\nPlease retry with complete parameters.\n"
            
            # Send error feedback to user and AI
            log.error(f"[AGENTIC] Tool validation failed:\n{error_feedback}")
            self.response_chunk.emit(error_feedback)
            
            # Add to history so AI can see the error
            if assistant_content:
                self._history.append({"role": "assistant", "content": assistant_content, "tool_calls": tool_calls})
            self._history.append({"role": "system", "content": error_feedback})
            
            # Continue the conversation so AI can retry
            self.response_complete.emit(error_feedback)
            return
        
        # Log successful validation
        log.info(f"[AGENTIC] All {len(validated_tool_calls)} tool calls passed validation")
        
        # Use validated tool calls
        tool_calls = validated_tool_calls
        
        if not tool_calls:
            log.info("[AGENTIC] No valid tool calls to execute after validation")
            return
        
        # Start exploration block for UI display
        self.response_chunk.emit("\n<exploration>\n")
        
        # PERFORMANCE: Group independent tool calls for parallel execution
        independent_groups = self._group_independent_tools(tool_calls)
        
        # Define the background runner to avoid blocking main thread
        def run_in_background():
            try:
                all_results = []
                for group_idx, tool_group in enumerate(independent_groups):
                    log.debug(f"Executing tool group {group_idx + 1}/{len(independent_groups)} with {len(tool_group)} tools")
                    
                    # Create ToolWorker for this group
                    group_worker = ToolWorker(self._tool_registry, tool_group)
                    
                    # Important: Since we are in a background thread already, 
                    # we must connect signals across threads. 
                    # By default, signals from the QThread worker will still deliver to the receiving 
                    # thread (which might be the main thread if connected to 'self'/AIAgent).
                    # We can use QueuedConnection or simply rely on QObject's default thread-safe signal delivery.
                    
                    group_worker.tool_started.connect(self._on_tool_started)
                    group_worker.tool_completed.connect(lambda n, a, r: self._on_tool_completed(n, a, r))
                    
                    # Start and wait for completion (WE ARE IN BACKGROUND THREAD, SO WAIT IS SAFE)
                    group_worker.start()
                    group_worker.wait()  # Blocks background thread only
                    
                    # Collect results from the worker
                    all_results.extend(group_worker._results)
                
                # Once ALL groups are done, trigger final results processing
                log.info(f"All {len(independent_groups)} tool groups finished execution. Emitting finish signal.")
                self._tool_batch_finished.emit(all_results, tool_calls, assistant_content)
                
            except Exception as e:
                log.error(f"Error in background tool execution: {e}", exc_info=True)
                self.request_error.emit(f"Tool execution failed: {str(e)}")

        # Launch background runner
        import threading
        t = threading.Thread(target=run_in_background, daemon=True)
        t.start()
        log.info(f"🚀 Launched {len(tool_calls)} tools in background execution thread.")
    
    def _group_independent_tools(self, tool_calls: list) -> List[List[dict]]:
        """
        Group independent tool calls for parallel execution.
        
        STRATEGY:
        - Tools that read different files → Can run in parallel
        - Tools that write to same file → Must run sequentially
        - Mixed read/write operations → Group by dependency
        
        Returns:
            List of tool groups (each group can run in parallel)
        """
        if not tool_calls:
            return []
        
        # Simple heuristic: Group by tool type and path
        read_tools = []  # Can parallelize
        write_tools = []  # Must serialize
        other_tools = []  # Serialize for safety
        
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            
            if tool_name in ["read_file", "search_code", "find_function", "find_class", "find_symbol"]:
                read_tools.append(tool_call)
            elif tool_name in ["write_file", "edit_file", "delete_path"]:
                write_tools.append(tool_call)
            else:
                other_tools.append(tool_call)
        
        # Build execution groups
        groups = []
        
        # Group 1: All reads can run in parallel (up to 4 at once)
        if read_tools:
            groups.append(read_tools)
        
        # Group 2+: Writes must run one at a time
        for write_tool in write_tools:
            groups.append([write_tool])
        
        # Group 3: Other tools run one at a time
        for other_tool in other_tools:
            groups.append([other_tool])
        
        log.debug(f"Tool grouping: {len(read_tools)} reads + {len(write_tools)} writes + {len(other_tools)} others = {len(groups)} groups")
        
        return groups

    def _on_tool_started(self, name, args):
        """Called when a tool starts execution in background."""
        log.info(f"Executing tool: {name} with args: {args}")
        self._metrics["tool_calls_total"] += 1
        display_path = ""
        path = str(args.get("path") or args.get("file_path") or args.get("target") or "")
        if path:
            display_path = path.split('\\')[-1] or path.split('/')[-1] or path

        resolved_path = path
        if not resolved_path and getattr(result, "metadata", None):
            meta_path = result.metadata.get("file_path") if result.metadata else ""
            if meta_path:
                resolved_path = str(meta_path)

        edit_tools = {
            "write_file",
            "edit_file",
            "inject_after",
            "add_import",
            "delete_lines",
            "replace_lines",
            "delete_path"
        }
        lint_tools = {"check_syntax", "get_problems"}
        
        # Capture pre-edit snapshot for diff support
        if name in edit_tools and name != "delete_path":
            if path:
                canonical_path = self._normalize_path(path)
                if os.path.exists(canonical_path):
                    try:
                        from pathlib import Path as _SnapPath
                        content = _SnapPath(canonical_path).read_text(encoding="utf-8", errors="replace")
                        self._pre_edit_snapshots[canonical_path] = content
                        log.info(f"[Diff-Debug] Captured snapshot: {canonical_path} (len={len(content)})")
                    except Exception as e:
                        log.warning(f"Failed to capture snapshot for {canonical_path}: {e}")
            
        if name == "run_command":
            self.tool_activity.emit("run_command", args.get("command", "")[:60], "running")
        elif name == "write_file":
            self.tool_activity.emit(name, display_path or args.get("path", ""), "running")
            # Enter creation mode when AI starts writing files
            if not self._creation_mode:
                self._creation_mode = True
                log.info("[CREATION_MODE] Entered creation mode - blocking list_directory and check_syntax")
        elif name in ["edit_file", "read_file", "delete_path", "list_directory"]:
            self.tool_activity.emit(name, display_path or args.get("path", ""), "running")
        else:
            self.tool_activity.emit(name, str(args)[:50], "running")

    def _on_tool_completed(self, name, args, result):
        """Called when a single tool finishes in background."""
        display_path = ""
        path = str(args.get("path") or args.get("file_path") or args.get("target") or "")
        if not path and getattr(result, "metadata", None):
            meta_path = result.metadata.get("file_path") if result.metadata else ""
            if meta_path:
                path = str(meta_path)
        if path:
            display_path = path.split('\\')[-1] or path.split('/')[-1] or path

        edit_tools = {
            "write_file",
            "edit_file",
            "inject_after",
            "add_import",
            "delete_lines",
            "replace_lines",
            "delete_path"
        }
        lint_tools = {"check_syntax", "get_problems"}

        if result.success:
            self._metrics["tool_calls_success"] += 1
            if name in edit_tools:
                self._metrics["edit_calls"] += 1
                self._metrics["edit_success"] += 1
                if name != "delete_path":
                    if path:
                        resolved_path = path
                        if self._project_root and not os.path.isabs(path):
                            resolved_path = os.path.join(str(self._project_root), path)
                        if resolved_path and os.path.exists(resolved_path):
                            self._pending_verify_files.add(resolved_path)
            if name in lint_tools:
                self._metrics["lint_checks"] += 1
                content = str(result.result)
                if "No syntax errors" in content or "No problems found" in content:
                    self._metrics["lint_clean"] += 1
            if name == "list_directory":
                dir_content = str(result.result)
                file_count = dir_content.count('\n') + 1 if dir_content else 0
                print(f"[AGENT-DEBUG] list_directory completed: path={args.get('path', '.')}, items={file_count}")
                self.tool_activity.emit("list_directory", f"Found {file_count} items", "complete")
                # Emit directory contents for UI display
                if dir_content and not dir_content.startswith("Not a directory") and not dir_content.startswith("Directory is empty"):
                    print(f"[AGENT-DEBUG] Emitting directory_contents signal")
                    # Resolve to absolute path using project root
                    rel_path = args.get('path', '.')
                    if self._project_root and not os.path.isabs(rel_path):
                        abs_path = os.path.join(self._project_root, rel_path)
                    else:
                        abs_path = rel_path
                    self.directory_contents.emit(abs_path, dir_content)
                else:
                    print(f"[AGENT-DEBUG] NOT emitting - content empty or error: {dir_content[:50] if dir_content else 'empty'}")
            elif name == "read_file":
                content = str(result.result)
                line_count = content.count('\n') + 1 if content else 0
                self.tool_activity.emit("read_file", f"{display_path} ({line_count} lines)", "complete")
            elif name in edit_tools and name != "delete_path":
                try:
                    res_obj = json.loads(result.result) if isinstance(result.result, str) else result.result
                    added = res_obj.get("added_lines", 0)
                    removed = res_obj.get("removed_lines", 0)
                except:
                    added, removed = 0, 0

                # ── Robust canonical path resolution for editing tools ──
                from pathlib import Path as _Path
                canonical_path = self._normalize_path(path)
                if not canonical_path and getattr(result, "metadata", None):
                    meta_path = result.metadata.get("file_path") if result.metadata else ""
                    if meta_path:
                        canonical_path = self._normalize_path(str(meta_path))
                
                # ── Get original content using canonical key ──
                original_content = self._pre_edit_snapshots.get(canonical_path, '')
                edit_type = 'C' if not original_content else 'M'
                
                # ── Get new file content (from args first, then disk) ─────────
                new_file_content = str(args.get("content", "") or "")
                if not new_file_content and canonical_path and os.path.exists(canonical_path):
                    try:
                        new_file_content = _Path(canonical_path).read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass

                # ── Calculate line counts ──────────────────────────────────────
                if edit_type == 'C' and added == 0:
                    # New file: count lines in content
                    if new_file_content:
                        added = len(new_file_content.split('\n'))
                elif edit_type == 'M' and added == 0 and removed == 0:
                    # Modified file: compute diff stats from original vs new
                    try:
                        import difflib
                        orig_lines = original_content.splitlines()
                        new_lines  = new_file_content.splitlines()
                        diff = list(difflib.ndiff(orig_lines, new_lines))
                        added   = sum(1 for l in diff if l.startswith('+ '))
                        removed = sum(1 for l in diff if l.startswith('- '))
                    except Exception as _de:
                        log.debug(f"Diff stats error: {_de}")

                log.debug(f"File {edit_type}: {resolved_path} +{added} -{removed}")

                info = display_path
                if added > 0 or removed > 0:
                    info += f" +{added} -{removed}"
                else:
                    info += " ✓"

                self.tool_activity.emit(name, info, "complete")

                # Emit <file_edited> tag using canonical (absolute) path
                self.response_chunk.emit(
                    f"\n<file_edited>\n{canonical_path}\n+{added} -{removed}\n{edit_type}\n</file_edited>\n"
                )

                # Emit file_edited_diff signal using canonical path
                try:
                    if hasattr(self, 'file_edited_diff') and canonical_path:
                        original_snap = self._pre_edit_snapshots.pop(canonical_path, '')
                        self.file_edited_diff.emit(canonical_path, original_snap, new_file_content)
                        log.info(f"[Diff-Debug] Emitted signal for canonical path: {canonical_path}")
                except Exception as _e:
                    log.warning(f"Could not emit file_edited_diff: {_e}")
            else:
                self.tool_activity.emit(name, "Completed", "complete")
        else:
            self._metrics["tool_calls_error"] += 1
            if name in edit_tools:
                self._metrics["edit_calls"] += 1
            self.tool_activity.emit(name, f"Error: {result.error[:40]}", "error")
            self.response_chunk.emit(f"\n⚠️ Error calling {name}: {result.error}\n")

    def _on_all_tools_completed(self, results, original_tool_calls, assistant_content):
        """Called when ALL tools in the batch are finished."""
        log.info(f"Processing final results for {len(results)} tool calls")
        self.response_chunk.emit("\n</exploration>\n")
        self.thinking_stopped.emit()  # Hide spinner after tool execution
        
        # 1. Check for PENDING status (Interactive Interaction)
        pending_tool = next((r for r in results if r.get("status") == "pending"), None)
        if pending_tool:
            log.info(f"Tool {pending_tool['name']} is PENDING. Waiting for user response.")
            self._waiting_for_user_response = True
            self._pending_tool_call_id = pending_tool["tool_call_id"]
            
            # Store the current batch state to resume later
            self._pending_tool_results = results
            self._pending_original_tool_calls = original_tool_calls
            self._pending_assistant_content = assistant_content
            
            # Signal the UI to show a question/interaction card
            question = pending_tool["content"]
            metadata = pending_tool.get("metadata", {})
            self.user_question_requested.emit(self._pending_tool_call_id, question, metadata)
            
            # Important: DO NOT call response_complete or continue_chat here.
            # We are pausing the agentic loop.
            return
        
        # Generate structured summary for UI display
        summary_data = self._generate_tool_summary_structured(results)
        if summary_data:
            self.tool_summary_ready.emit(summary_data)
        
        # Add assistant message and tool responses to history
        assistant_msg = {
            "role": "assistant",
            "content": assistant_content or "",
        }
        if original_tool_calls:
            assistant_msg["tool_calls"] = original_tool_calls
        self._history.append(assistant_msg)
        
        for res in results:
            # Use raw content instead of JSON wrapper to match OpenAI-style expectations
            # (especially for models like DeepSeek which can be picky about tool content)
            content = str(res["content"])
            tool_name = res["name"]
            tool_success = res.get("success", False)
            
            # Debug logging for command results
            if tool_name == "run_command":
                log.info(f"[DEBUG] run_command result - success={tool_success}, content_preview={content[:100] if content else 'empty'}")
            
            self._history.append({
                "role": "tool",
                "tool_call_id": res["tool_call_id"],
                "name": tool_name,
                "content": content
            })
            
        self._save_history_to_disk()
        self.response_complete.emit("")
        
        # Handle auto-verify
        if self._auto_verify_in_progress:
            self._handle_auto_verify_results(results)
            return
        
        if self._should_auto_verify():
            if self._start_auto_verify():
                return
        
        # Trigger continuation after tools complete
        self._continue_after_tools_flag = True
        log.info("Triggering continuation after tools completed")
        QTimer.singleShot(200, self._continue_chat_after_tools)
    
    def _generate_tool_summary(self, results: list) -> str:
        """Generate a summary report of all tool operations."""
        if not results:
            return ""
        
        # Categorize results
        file_writes = []
        file_reads = []
        file_edits = []
        commands = []
        errors = []
        other = []
        
        for res in results:
            name = res.get("name", "")
            content = str(res.get("content", ""))[:200]  # Truncate for summary
            
            if not res.get("success"):
                errors.append({
                    "name": name,
                    "error": content
                })
                continue
            
            if name in ("write_file", "edit_file", "create_directory"):
                # Extract file path from content or args
                file_path = res.get("content", "").split("\n")[0] if res.get("content") else "Unknown"
                if "Created:" in file_path or "Written:" in file_path or "Edited:" in file_path:
                    file_writes.append({"name": name, "path": file_path})
                else:
                    file_writes.append({"name": name, "path": content})
            elif name in ("read_file", "read_multiple_files"):
                file_reads.append({"name": name, "content": content})
            elif name in ("run_command", "execute_command"):
                commands.append({"name": name, "output": content})
            elif name in ("search_code", "find_function", "find_class"):
                other.append({"name": name, "result": content})
            else:
                other.append({"name": name, "result": content})
        
        lines = []
        lines.append("\n" + "=" * 60)
        lines.append("📋 TOOL EXECUTION SUMMARY")
        lines.append("=" * 60)
        
        # File write summary
        if file_writes:
            lines.append(f"\n📁 **Files Created/Modified ({len(file_writes)}):**")
            lines.append("-" * 40)
            
            for item in file_writes:
                path = item.get("path", "Unknown")
                tool_name = item.get("name", "")
                
                # Get file details if path looks valid
                if path and path != "Unknown" and not path.startswith("Error"):
                    try:
                        import os
                        if os.path.exists(path):
                            size = os.path.getsize(path)
                            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            line_count = len(content.split('\n'))
                            
                            size_str = self._format_size(size)
                            icon = "✏️" if tool_name == "edit_file" else "✅"
                            lines.append(f"  {icon} `{path}`")
                            lines.append(f"     Size: {size_str} | Lines: {line_count}")
                        else:
                            lines.append(f"  ✅ {path}")
                    except:
                        lines.append(f"  ✅ {path}")
                else:
                    lines.append(f"  ✅ {path}")
            
            lines.append("")
        
        # File read summary
        if file_reads:
            lines.append(f"\n📖 **Files Read ({len(file_reads)}):**")
            lines.append("-" * 40)
            for item in file_reads:
                lines.append(f"  👁️ {item.get('name', 'read')}: {item.get('content', '')[:80]}...")
            lines.append("")
        
        # Command summary
        if commands:
            lines.append(f"\n⚙️ **Commands Executed ({len(commands)}):**")
            lines.append("-" * 40)
            for item in commands:
                lines.append(f"  ▶️ {item.get('name', 'command')}")
                output = item.get("output", "")
                if output:
                    lines.append(f"     Output: {output[:100]}...")
            lines.append("")
        
        # Errors
        if errors:
            lines.append(f"\n❌ **Errors ({len(errors)}):**")
            lines.append("-" * 40)
            for item in errors:
                lines.append(f"  ❌ {item.get('name', 'tool')}: {item.get('error', 'Unknown error')[:100]}")
            lines.append("")
        
        # Other operations
        if other:
            lines.append(f"\n🔧 **Other Operations ({len(other)}):**")
            lines.append("-" * 40)
            for item in other:
                lines.append(f"  ⚡ {item.get('name', 'operation')}")
            lines.append("")
        
        lines.append("=" * 60)
        lines.append("")
        
        return "\n".join(lines)
    
    def _generate_tool_summary_structured(self, results: list) -> dict:
        """Generate structured tool summary data for professional UI display."""
        if not results:
            return None
        
        summary = {
            "total": len(results),
            "file_writes": [],
            "file_reads": [],
            "commands": [],
            "errors": [],
            "other": []
        }
        
        for res in results:
            name = res.get("name", "")
            content = str(res.get("content", ""))
            success = res.get("success", False)
            
            if not success:
                summary["errors"].append({
                    "name": name,
                    "error": content[:200]
                })
                continue
            
            if name in ("write_file", "edit_file", "create_directory", "inject_after", "add_import", "delete_path"):
                # Try to extract file path and details
                file_path = "Unknown"
                line_count = 0
                size_str = ""
                lines_added = 0
                lines_removed = 0
                
                # Get metadata FIRST - this has the actual file_path and diff stats from tools
                metadata = res.get("metadata", {}) or {}
                lines_added = metadata.get("lines_added", 0) or 0
                lines_removed = metadata.get("lines_removed", 0) or 0
                # Extract file_path from metadata if available
                file_path = metadata.get("file_path", "")
                
                # Fallback: Try to extract file path from content
                if not file_path and content:
                    import re
                    # Try patterns like "Created: path", "Written: path", "Edited: path"
                    path_patterns = [
                        r'(?:Created|Written|Edited|Overwritten|File written|File created|Successfully (?:created|written|edited|overwritten)(?:\s+file)?):\s*(.+)',
                        r'\[File:\s*(.+?)\]',
                    ]
                    for pattern in path_patterns:
                        match = re.search(pattern, content, re.IGNORECASE)
                        if match:
                            file_path = match.group(1).strip()
                            break
                
                # Final fallback to Unknown
                if not file_path:
                    file_path = "Unknown"
                
                # Determine operation type for display
                op_type = "edit"
                if name == "write_file":
                    op_type = "create"
                elif name == "delete_path":
                    op_type = "delete"
                elif name == "create_directory":
                    op_type = "directory"
                
                # Parse content for file info and fallback diff stats
                if content:
                    lines = content.split('\n')
                    first_line = lines[0] if lines else ""
                    
                    # Try to extract path from "Created: path" or "Written: path" format
                    if "Created:" in first_line or "Written:" in first_line or "Edited:" in first_line:
                        parts = first_line.split(":", 1)
                        if len(parts) > 1:
                            file_path = parts[1].strip()
                    
                    # Fallback: Extract lines_added/lines_removed from text output via regex
                    # Only if not already set from metadata
                    import re
                    if lines_added == 0:
                        added_match = re.search(r'Lines\s+added[:\s]+(\d+)', content, re.IGNORECASE)
                        if added_match:
                            lines_added = int(added_match.group(1))
                    if lines_removed == 0:
                        removed_match = re.search(r'Lines\s+removed[:\s]+(\d+)', content, re.IGNORECASE)
                        if removed_match:
                            lines_removed = int(removed_match.group(1))
                    
                    # Try to get line count from content
                    if line_count == 0 and len(lines) > 1:
                        for line in lines[1:10]:  # Check first few lines
                            if "lines" in line.lower() or "line" in line.lower():
                                match = re.search(r'(\d+)\s*lines?', line, re.IGNORECASE)
                                if match:
                                    line_count = int(match.group(1))
                                    break
                
                # Try to get actual file info if path is valid
                if file_path and file_path != "Unknown" and not file_path.startswith("Error"):
                    try:
                        import os
                        if os.path.exists(file_path):
                            size = os.path.getsize(file_path)
                            size_str = self._format_size(size)
                            if line_count == 0:
                                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    file_content = f.read()
                                line_count = len(file_content.split('\n'))
                    except:
                        pass
                
                summary["file_writes"].append({
                    "name": name,
                    "path": file_path,
                    "line_count": line_count,
                    "size": size_str,
                    "type": op_type,
                    "lines_added": lines_added,
                    "lines_removed": lines_removed
                })
                
            elif name in ("read_file", "read_multiple_files"):
                # Try to extract file path from content preview
                file_path = "Unknown"
                content_preview = content[:150]
                lines = content.split('\n')
                if lines:
                    first_line = lines[0]
                    if first_line and not first_line.startswith('#'):
                        file_path = first_line[:50]
                
                summary["file_reads"].append({
                    "name": name,
                    "path": file_path,
                    "preview": content_preview
                })
                
            elif name in ("run_command", "execute_command"):
                # Extract command and output
                cmd = "Unknown"
                output = content[:200]
                
                # Try to parse command from content
                if content:
                    lines = content.split('\n')
                    for line in lines[:5]:
                        if line.startswith('$') or line.startswith('>'):
                            cmd = line[1:].strip()
                            break
                
                summary["commands"].append({
                    "name": name,
                    "command": cmd,
                    "output": output
                })
                
            else:
                summary["other"].append({
                    "name": name,
                    "result": content[:100]
                })
        
        return summary
    
    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def _should_auto_verify(self) -> bool:
        if not self._auto_verify_enabled:
            return False
        if self._auto_verify_in_progress:
            return False
        if not self._pending_verify_files:
            return False
        if self._auto_verify_attempts >= self._auto_verify_max_retries:
            return False
        return True

    def _start_auto_verify(self) -> bool:
        file_paths = [p for p in self._pending_verify_files if p and os.path.exists(p)]
        self._pending_verify_files.clear()
        if not file_paths and not self._auto_verify_command:
            return False

        import uuid

        args: dict = {}
        if self._auto_verify_command:
            args["test_command"] = self._auto_verify_command
        if file_paths:
            args["file_paths"] = file_paths

        tool_call = {
            "id": f"auto_verify_{uuid.uuid4().hex}",
            "type": "function",
            "function": {
                "name": "verify_fix",
                "arguments": json.dumps(args)
            }
        }

        self._auto_verify_in_progress = True
        self._auto_verify_attempts += 1
        log.info(f"Auto-verify attempt {self._auto_verify_attempts}/{self._auto_verify_max_retries}")
        self._execute_tools([tool_call], assistant_content="[AUTO VERIFY] Running verification.")
        return True

    def _handle_auto_verify_results(self, results):
        output = ""
        success = False
        for res in results:
            if res.get("name") == "verify_fix":
                output = str(res.get("content", ""))
                success = bool(res.get("success"))
                break

        self._auto_verify_in_progress = False

        lowered = output.lower()
        failed = (not success) or ("failed" in lowered) or ("error" in lowered) or ("traceback" in lowered)

        if failed:
            if self._auto_verify_attempts >= self._auto_verify_max_retries:
                log.warning("Auto-verify failed: max retries reached")
                self._auto_verify_attempts = 0
                final_prompt = (
                    "Auto verification failed after the maximum retries. "
                    "Summarize the failure and ask the user how to proceed."
                )
                self.chat(final_prompt)
                return

            trimmed_output = output.strip()
            if len(trimmed_output) > 4000:
                trimmed_output = trimmed_output[:4000] + "\n... (truncated)"

            prompt = (
                "Auto verification failed. Fix the errors and rerun verification.\n\n"
                f"Verification output:\n{trimmed_output}"
            )
            self.chat(prompt)
            return

        self._auto_verify_attempts = 0
        self._continue_after_tools_flag = True
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self._continue_chat_after_tools)

    def _on_tool_error(self, error_msg):
        """Handle fatal error in ToolWorker."""
        log.error(f"ToolWorker fatal error: {error_msg}")
        self._metrics["tool_calls_error"] += 1
        self._record_request_end(success=False, error_category="tool_error")
        self.response_chunk.emit(f"\n❌ Tool Execution Failed: {error_msg}\n")
        self.response_chunk.emit("\n</exploration>\n")
        self._continue_after_tools_flag = False
        self.response_complete.emit("Error during tool execution")

    def _on_tool_timeout(self, tool_name: str, recovery_hint: str):
        """
        Called when a single tool exceeds TOOL_TIMEOUT_SECONDS.
        Injects a recovery message into conversation history so the AI
        can understand what happened and resume from the next step.
        """
        log.warning(f"Tool timeout handler: {tool_name}")
        self._metrics["tool_timeouts"] += 1
        self._metrics["tool_calls_error"] += 1
        # Show warning in chat UI
        self.response_chunk.emit(
            f"\n⏱️ **Tool `{tool_name}` timed out** (>{ToolWorker.TOOL_TIMEOUT_SECONDS}s). "
            f"Recovering automatically...\n"
        )
        # Inject a synthetic system recovery note into history so AI knows what happened
        recovery_note = (
            f"[SYSTEM RECOVERY] Tool `{tool_name}` was aborted after "
            f"{ToolWorker.TOOL_TIMEOUT_SECONDS} seconds (subprocess/network hang). "
            f"The task is NOT complete. Review the tasklist and continue from the next "
            f"incomplete step. Do NOT retry the same timed-out tool immediately."
        )
        self._history.append({"role": "user", "content": recovery_note})

    def _continue_chat_after_tools(self):
        """Continue chat after tools have been executed."""
        log.info("_continue_chat_after_tools called")
        self._continue_after_tools_flag = False
        
        # Ensure worker is cleared
        if self._worker:
            log.warning("Worker still exists in _continue_chat_after_tools, clearing")
            self._worker = None
        
        log.info("Continuing chat after tools - calling chat(None)")
        # Now continue the chat
        self.chat(None)  # Continue without adding a user message

    def user_responded(self, tool_call_id: str, response: str):
        """Called when a user answers a 'pending' question in the chat."""
        if not self._waiting_for_user_response or self._pending_tool_call_id != tool_call_id:
            log.warning(f"Unexpected user response for {tool_call_id}")
            return
            
        log.info(f"User responded to {tool_call_id}: {response[:40]}...")
        self._waiting_for_user_response = False
        self._pending_tool_call_id = None
        
        # Check if this was a permission request or a general question
        is_permission_request = False
        target_tool_res = None
        for res in self._pending_tool_results:
            if res["tool_call_id"] == tool_call_id:
                target_tool_res = res
                if res.get("content") == "PENDING_PERMISSION":
                    is_permission_request = True
                break
        
        if is_permission_request and target_tool_res:
            # Handle permission response
            tool_name = target_tool_res.get("metadata", {}).get("tool_name")
            params = target_tool_res.get("metadata", {}).get("params", {})
            
            from src.ai.permission_system import get_permission_manager
            perm_manager = get_permission_manager()
            
            # Parse response - can be "allow", "always", "allow:global", "always:global", etc.
            response_parts = response.split(':')
            response_action = response_parts[0]  # "allow" or "always"
            response_scope = response_parts[1] if len(response_parts) > 1 else 'session'  # "global" or "session"
            
            if response_action in ["allow", "always"]:
                log.info(f"User GRANTED permission for {tool_name} (scope: {response_scope}). Executing now...")
                
                # CRITICAL: Inform permission manager about this approval before re-executing
                if response_action == "always" or response_scope == "global":
                    perm_manager.remember_decision(tool_name, True)
                else:
                    perm_manager.add_session_approval(tool_name)
                
                # Synchronize always_allowed flag with tool registry for this call
                old_reg_allowed = getattr(self._tool_registry, '_always_allowed', False)
                self._tool_registry._always_allowed = True 
                
                try:
                    # Now execute_tool will actually proceed because check_permission will return True
                    real_result = self._tool_registry.execute_tool(tool_name, params)
                    
                    # Update the tool result in history with actual content and metadata
                    target_tool_res["content"] = str(real_result.result) if real_result.success else f"Error: {real_result.error}"
                    target_tool_res["success"] = real_result.success
                    # Copy metadata so UI can display line count, size, etc.
                    if real_result.metadata:
                        target_tool_res["metadata"] = real_result.metadata
                finally:
                    self._tool_registry._always_allowed = old_reg_allowed
            else:
                log.info(f"User DENIED permission for {tool_name}")
                if response_action == "never": # Just in case we add this
                     perm_manager.remember_decision(tool_name, False)
                target_tool_res["content"] = "Error: User denied permission for this operation."
                target_tool_res["success"] = False
            
            target_tool_res["status"] = "completed"
        else:
            # Update the pending tool result with the user's answer (standard QuestionTool)
            if target_tool_res:
                target_tool_res["content"] = response
                target_tool_res["status"] = "completed"
                target_tool_res["success"] = True
        
        # Resume the batch processing (Turn 2 starts)
        results = self._pending_tool_results
        calls = self._pending_original_tool_calls
        content = self._pending_assistant_content
        
        # Clear stores
        self._pending_tool_results = []
        self._pending_original_tool_calls = []
        self._pending_assistant_content = ""
        
        # Re-trigger Turn 2 completion logic
        self._on_all_tools_completed(results, calls, content)

    def _execute_pending_tools(self):
        """Resume execution of tools that were awaiting confirmation."""
        if not self._pending_tool_calls:
            log.warning("No pending tools to execute")
            return
        
        tools = self._pending_tool_calls[:]
        assistant_content = getattr(self, '_pending_assistant_content', '')
        self._pending_tool_calls = []
        self._pending_assistant_content = None
        log.info(f"Executing {len(tools)} pending tools after user confirmation")
        
        # Add user confirmation to history
        self._history.append({"role": "user", "content": "yes"})
        
        # Execute tools with the stored assistant content
        self._execute_tools(tools, assistant_content)

    def _cancel_pending_tools(self):
        """Cancel the tool calls that were awaiting confirmation."""
        if not self._pending_tool_calls:
            return
            
        assistant_content = getattr(self, '_pending_assistant_content', '')
        
        # Add assistant message with tool_calls first
        self._history.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": self._pending_tool_calls
        })
        
        # Then add cancelled tool responses
        for tc in self._pending_tool_calls:
            self._history.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": tc["function"]["name"],
                "content": "Cancelled by user."
            })
        
        self._pending_tool_calls = []
        self._pending_assistant_content = None
        
        cancel_msg = "❌ Action cancelled by user."
        self.response_chunk.emit(f"\n\n{cancel_msg}")
        self.response_complete.emit(cancel_msg)
    
    def proceed_with_tools(self):
        """Public method for UI to proceed with pending tools"""
        if self._pending_tool_calls:
            log.info("UI requested to proceed with pending tools")
            self._execute_pending_tools()
        else:
            log.warning("No pending tools to proceed with")
    
    def cancel_pending_tools(self):
        """Public method for UI to cancel pending tools"""
        if self._pending_tool_calls:
            log.info("UI requested to cancel pending tools")
            self._cancel_pending_tools()
        else:
            log.warning("No pending tools to cancel")

    def _get_tool_status_info(self, name: str, args: dict) -> str:
        """Get descriptive status message for a tool call."""
        if name == "read_file":
            path = args.get("path", "")
            return f"Read `{os.path.basename(path)}`"
        elif name == "write_file":
            path = args.get("path", "")
            return f"Created `{os.path.basename(path)}`"
        elif name == "edit_file":
            path = args.get("path", "")
            return f"Edited `{os.path.basename(path)}`"
        elif name == "list_directory":
            path = args.get("path", ".")
            name_dir = os.path.basename(path) or path
            return f"List directory `{name_dir}`"
        elif name == "run_command":
            cmd = args.get("command", "")
            return f"Run command: `{cmd[:40]}...`"
        elif name == "delete_path":
            path = args.get("path", "")
            return f"Deleted `{os.path.basename(path) or path}`"
        elif name == "search_code":
            query = args.get("query", "")
            return f"Search code: `{query}`"
        elif name == "read_terminal":
            return "Read terminal output"
        return f"Execute `{name}`"

    def _on_error(self, error: str):
        """Handle AI errors gracefully with user-friendly messages."""
        log.error(f"AI error: {error}")
        category = _categorize_error_message(error)
        self._record_request_end(success=False, error_category=category)
        
        # Reset flags on error
        self._continue_after_tools_flag = False
        
        # Stop thinking indicator
        self.thinking_stopped.emit()
        
        # Clear worker reference on error
        self._worker = None
        
        # Provide user-friendly error message based on category
        user_friendly_error = error
        if category == "rate_limit":
            user_friendly_error = (
                "⚠️ **API Rate Limit Exceeded**\n\n"
                "The AI provider has temporarily rate-limited your requests. This happens when too many requests are sent in a short time.\n\n"
                "**What to do:**\n"
                "- Wait 30-60 seconds before trying again\n"
                "- Reduce request frequency\n"
                "- Check your API plan limits\n\n"
                "The IDE will remain stable. Please try again shortly."
            )
        elif category == "auth":
            user_friendly_error = (
                "🔒 **Authentication Error**\n\n"
                "Your API key is invalid or expired. Please check your API key settings."
            )
        elif category == "timeout":
            user_friendly_error = (
                "⏱️ **Request Timeout**\n\n"
                "The AI request took too long to complete. This can happen with very complex tasks.\n\n"
                "**Try:** Breaking your request into smaller steps."
            )
        elif category == "network":
            user_friendly_error = (
                "🌐 **Network Error**\n\n"
                "Unable to connect to the AI provider. Please check your internet connection."
            )
        
        # Emit user-friendly error
        self.request_error.emit(user_friendly_error)
        
        # Also emit completion to unlock UI and prevent crash
        self.response_complete.emit(f"❌ Error: {user_friendly_error}")
        
        # Log technical details for debugging
        log.error(f"Error category: {category}, Original error: {error}")

    def set_always_allowed(self, allowed: bool):
        """Set whether to always allow tool execution without confirmation"""
        self._always_allowed = allowed
        # Sync with tool registry
        if hasattr(self, '_tool_registry'):
            self._tool_registry._always_allowed = allowed
        log.info(f"AI Agent 'Always Allow' set to: {allowed}")
        if allowed:
            self.response_chunk.emit("\n🔓 **Auto-approval enabled** for this chat session. I'll execute file changes without asking.")
        else:
            self.response_chunk.emit("\n🔒 **Auto-approval disabled**. I'll ask for confirmation before making changes.")

    def enable_always_allowed(self):
        """Enable always allow mode - AI works fully autonomously"""
        self.set_always_allowed(True)
        
    def disable_always_allowed(self):
        """Disable always allow mode - AI asks for confirmation"""
        self.set_always_allowed(False)

    def clear_history(self):
        """Clear current session history."""
        self._history.clear()
        self._history_summary = ""
        self._save_history_to_disk()
        log.info("History cleared for current session")
    
    def clear_project_history(self, project_path: str = None):
        """Clear history for a specific project or current project."""
        path = project_path or self._project_root
        if not path:
            log.warning("No project path specified for history clearing")
            return
            
        project_id = self._get_project_id_for_path(path)
        history_file = Path.home() / ".cortex" / "history" / f"history_{project_id}.json"
        
        if history_file.exists():
            try:
                history_file.unlink()
                log.info(f"Deleted history file for project: {path}")
            except Exception as e:
                log.error(f"Failed to delete history file: {e}")
        
        # Also clear current session if it's the same project
        if path == self._project_root:
            self._history.clear()
            self._history_summary = ""
    
    def _get_project_id_for_path(self, path: str) -> str:
        """Create a unique stable ID based on the project path."""
        import hashlib
        path_norm = os.path.normpath(str(path)).lower()
        return hashlib.md5(path_norm.encode()).hexdigest()[:12]

    def update_settings(self, provider: str, model: str):
        self._settings.set("ai", "provider", provider)
        self._settings.set("ai", "model", model)
    
    def enable_autogen(self, enabled: bool = True):
        """Enable or disable AutoGen multi-agent system."""
        self._autogen_enabled = enabled
        
        if enabled and self._project_root and self._autogen_system is None:
            # Initialize immediately if project is already set
            self.set_project_root(self._project_root)
        
        log.info(f"AutoGen {'enabled' if enabled else 'disabled'}")
    
    def run_multi_agent_task(self, task: str, mode: str = "collaborative") -> str:
        """
        Run a task using the multi-agent system.
        
        Args:
            task: The task to complete
            mode: "collaborative" (group discussion) or "sequential" (assembly line)
        
        Returns:
            Result summary from the agents
        """
        if not self._autogen_system:
            return "Error: AutoGen system not initialized"
        
        try:
            if mode == "collaborative":
                # Set up group chat with all agents
                agent_names = list(self._autogen_system.agents.keys())
                self._autogen_system.setup_group_chat(agent_names)
                
                # Start collaborative discussion
                result = self._autogen_system.run_collaborative_task(
                    task=task,
                    initiator_name=agent_names[0]  # First agent initiates
                )
            elif mode == "sequential":
                # Define workflow: PM → Architect → Developer → QA → Reviewer
                workflow = ["PM", "Architect", "Developer", "QA", "Reviewer"]
                result = self._autogen_system.run_sequential_workflow(
                    task=task,
                    workflow=workflow
                )
            else:
                result = "Error: Unknown mode. Use 'collaborative' or 'sequential'"
            
            return result
            
        except Exception as e:
            log.error(f"Multi-agent task error: {e}")
            return f"Error during multi-agent execution: {str(e)}"
    
    def get_autogen_status(self) -> Dict[str, Any]:
        """Get AutoGen system status."""
        if not self._autogen_system:
            return {"enabled": False, "agents": []}
        
        return {
            "enabled": self._autogen_enabled,
            "agents": self._autogen_system.list_agents(),
            "active": bool(self._autogen_system.group_chat)
        }

    def is_busy(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def stop(self):
        """Stop the current AI worker."""
        if self._worker and self._worker.isRunning():
            log.info("Stopping AI worker...")
            self._worker.terminate()
            self._worker.wait()
            self._worker = None
            log.info("AI worker stopped.")

    def _parse_and_emit_todos(self, text: str) -> str:
        """Parse TODO items from response text, emit to UI, and return cleaned text."""
        import re
        
        todos = []
        main_task = ""
        cleaned_text = text
        
        log.info(f"[TODO] _parse_and_emit_todos called, text length: {len(text)}")
        
        # 1. Try to find a <tasklist> section first
        tasklist_match = re.search(r'<tasklist>(.*?)</tasklist>', text, re.DOTALL)
        content_to_parse = tasklist_match.group(1) if tasklist_match else text
        log.info(f"[TODO] tasklist_match found: {tasklist_match is not None}")
        
        # 2. Global search for [ ] or [x] items
        # Matches "- [ ] Task" or "* [x] Task" or "1. [ ] Task"
        # Relaxed regex to allow hyphens and other chars in content
        task_pattern = r'\[([ xX])\]\s*([^\[\n<]+)'
        
        matches = list(re.finditer(task_pattern, content_to_parse))
        log.info(f"[TODO] Found {len(matches)} [ ]/[x] patterns in text")
        
        task_id = 0
        
        for match in matches:
            status_char = match.group(1).lower()
            content = match.group(2).strip()
            
            # Clean up trailing hyphens or bullets if they were caught by the greedy match
            content = re.sub(r'\s*[-\*]$', '', content).strip()
            
            # Filter out noise (file extensions, very short text, UI hints)
            if any(content.lower().endswith(ext) for ext in ['.py', '.js', '.css', '.html', '.json', '.md']):
                continue
            if len(content) < 3 or "error" in content.lower():
                continue
            
            task_id += 1
            checked = status_char == 'x'
            
            log.info(f"[TODO] Parsed todo {task_id}: '{content[:50]}...' status: {'COMPLETE' if checked else 'PENDING'}")
            
            # Clean up markdown formatting
            content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
            content = re.sub(r'`(.+?)`', r'\1', content)
            
            if not main_task and task_id == 1:
                main_task = content[:50] + ('...' if len(content) > 50 else '')
                
            todos.append({
                'id': f'task_{task_id}',
                'content': content,
                'status': 'COMPLETE' if checked else 'PENDING'
            })
        
        # 3. Emit and Clean if we found actual todos
        if todos:
            log.info(f"Parsed {len(todos)} todos from response using robust extraction")
            self.todos_updated.emit(todos, main_task)
            
            # 4. Clean the text for UI bubble
            # Remove the <tasklist> block entirely
            cleaned_text = re.sub(r'<tasklist>.*?</tasklist>', '', cleaned_text, flags=re.DOTALL)
            
            # Remove each extracted todo string from the text to be absolutely sure
            # We sort by length descending to avoid partial matches causing issues
            matches_sorted = sorted(matches, key=lambda m: len(m.group(0)), reverse=True)
            for m in matches_sorted:
                match_str = m.group(0)
                # Try to remove the match plus any leading bullet/list markers
                # e.g. "- [ ] Task" or "1. [ ] Task"
                pattern = re.escape(match_str)
                # Prefix with optional bullet/numbering
                full_marker_pattern = r'^\s*[-*\d\.]*\s*' + pattern
                cleaned_text = re.sub(full_marker_pattern, '', cleaned_text, flags=re.MULTILINE)
                # Fallback: just remove the literal match if it wasn't at line start
                cleaned_text = cleaned_text.replace(match_str, "")
            
            # Flatten multiple newlines and strip
            cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text).strip()
            # Clean up trailing content markers if they were orphaned
            cleaned_text = re.sub(r'\n\s*[-*]$', '', cleaned_text).strip()
            
        elif not tasklist_match:
            # If no manual tasks found and no tasklist tag, clear the section
            self.todos_updated.emit([], "")
            
        return cleaned_text
    
    def update_todo_status(self, task_id: str, status: str):
        """Update a specific todo item's status."""
        # This can be called during tool execution to show progress
        # Status: PENDING, IN_PROGRESS, COMPLETE, CANCELLED
        pass  # UI will be updated via todos_updated signal with full list

    def _save_workflow_files(self, text: str):
        """Extract workflow tags and save to .cortex/ directory."""
        if not self._project_root:
            return

        tags = {
            "plan": ("<plan>", "</plan>", "plans"),
            "task": ("<tasklist>", "</tasklist>", "tasks"),
            "walkthrough": ("<walkthrough>", "</walkthrough>", "walkthroughs")
        }

        cortex_dir = Path(str(self._project_root)) / ".cortex"
        
        for key, (start_tag, end_tag, sub_dir) in tags.items():
            if start_tag in text and end_tag in text:
                try:
                    content = text.split(start_tag)[1].split(end_tag)[0].strip()
                    if not content:
                        continue
                    
                    # Target directory
                    target_dir = cortex_dir / sub_dir
                    target_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Generate unique filename (plan1.md, plan2.md, etc.)
                    count = 1
                    while (target_dir / f"{key}{count}.md").exists():
                        count += 1
                    
                    file_path = target_dir / f"{key}{count}.md"
                    file_path.write_text(content, encoding="utf-8")
                    log.info(f"Generated workflow file: {file_path}")
                    self.file_generated.emit(str(file_path))
                except Exception as e:
                    log.error(f"Failed to process/save workflow {key}: {e}")

    # ============================================================================
    # NEW: OpenCode Enhancement Integration
    # ============================================================================
    
    def chat_with_enhancement(self, 
                              user_message: Optional[str], 
                              intent: IntentClassification,
                              route: AgentRoute,
                              tools: List[ToolScore],
                              code_context: str = ""):
        """
        Process a message with intent classification, agent routing, and tool selection.
        This method extends the standard chat() with enhancement data.
        
        Args:
            user_message: The user's input message
            intent: Classified intent from IntentClassifier
            route: Selected agent route from AgentRouter
            tools: Selected tools from ToolSelector
            code_context: Optional code context
        """
        log.info("=" * 70)
        log.info("[AI Agent] Processing with OpenCode Enhancement")
        log.info(f"[AI Agent] Intent: {intent.primary_intent.value} (confidence: {intent.confidence:.2f})")
        log.info(f"[AI Agent] Agent: {route.agent_type.value} (confidence: {route.confidence:.2f})")
        log.info(f"[AI Agent] Tools: {[t.tool.name for t in tools]}")
        log.info("=" * 70)
        
        # Build enhanced system prompt with intent and agent info
        enhanced_context = self._build_enhanced_context(intent, route, tools)
        
        # Add enhancement info to code context
        if code_context:
            code_context = f"{enhanced_context}\n\n{code_context}"
        else:
            code_context = enhanced_context
        
        # Store last enhancement data for tool execution
        self._last_intent = intent
        self._last_route = route
        self._last_tools = tools
        
        # Call standard chat with enhanced context
        self.chat(user_message, code_context)
    
    def _build_enhanced_context(self, 
                               intent: IntentClassification,
                               route: AgentRoute,
                               tools: List[ToolScore]) -> str:
        """Build enhanced context string with intent, agent, and tool information."""
        context_parts = []
        
        # Add intent information
        context_parts.append(f"## DETECTED INTENT")
        context_parts.append(f"Primary Intent: {intent.primary_intent.value}")
        context_parts.append(f"Confidence: {intent.confidence:.0%}")
        if intent.sub_intents:
            context_parts.append(f"Sub-intents: {', '.join(s.value for s in intent.sub_intents)}")
        context_parts.append(f"Complexity: {intent.complexity}")
        context_parts.append(f"Requires Terminal: {intent.requires_terminal}")
        context_parts.append(f"Requires Code Tools: {intent.requires_code_tools}")
        
        # Add agent information
        context_parts.append(f"\n## SELECTED AGENT")
        context_parts.append(f"Agent Type: {route.agent_type.value}")
        context_parts.append(f"Confidence: {route.confidence:.0%}")
        context_parts.append(f"Routing Reason: {route.routing_reason}")
        if route.supporting_agents:
            context_parts.append(f"Supporting Agents: {', '.join(a.value for a in route.supporting_agents)}")
        
        # Add tool information
        context_parts.append(f"\n## SELECTED TOOLS")
        for tool_score in tools:
            tool = tool_score.tool
            context_parts.append(f"- {tool.name} (score: {tool_score.score:.2f})")
            context_parts.append(f"  Description: {tool.description}")
            context_parts.append(f"  Category: {tool.category.value}")
            context_parts.append(f"  Complexity: {tool_score.estimated_complexity}")
            context_parts.append(f"  Reasoning: {tool_score.reasoning}")
        
        # Add guidance based on intent
        context_parts.append(f"\n## CONTEXTUAL GUIDANCE")
        
        if intent.primary_intent.value == "terminal_command":
            context_parts.append("The user is requesting a terminal/command operation. "
                               "Use bash tool to execute commands. "
                               "Explain what each command does before executing.")
        
        elif intent.primary_intent.value == "code_generation":
            context_parts.append("The user wants code to be written or generated. "
                               "Use read tool to check existing code, "
                               "then use write or edit tools to create/modify files. "
                               "Follow best practices and add comments.")
        
        elif intent.primary_intent.value == "debugging":
            context_parts.append("The user needs help debugging an issue. "
                               "Use grep to search for errors, "
                               "read to examine relevant code, "
                               "and explain the root cause before suggesting fixes.")
        
        elif intent.primary_intent.value == "research":
            context_parts.append("The user is conducting research. "
                               "Use websearch or webfetch to find information, "
                               "then summarize findings with sources.")
        
        context_parts.append("\n## INSTRUCTIONS")
        context_parts.append("Based on the detected intent and selected tools, "
                           "proceed with the most appropriate action. "
                           "Use the selected tools in the order that makes most sense for the task.")
        
        return "\n".join(context_parts)
    
    def get_last_enhancement_data(self) -> Dict[str, Any]:
        """Get the last enhancement data for external access."""
        return {
            "intent": getattr(self, '_last_intent', None),
            "route": getattr(self, '_last_route', None),
            "tools": getattr(self, '_last_tools', [])
        }
    
    def chat_with_testing(self, 
                         user_message: Optional[str], 
                         code_changes: List[Dict] = None,
                         code_context: str = ""):
        """
        Process a message with AI-driven testing workflow.
        
        This method extends chat_with_enhancement to include:
        1. Testing need detection
        2. Test tool selection
        3. Test plan creation
        4. Test execution
        
        Args:
            user_message: The user's input message
            code_changes: List of code changes for testing analysis
            code_context: Optional code context
        """
        from src.ai.testing import get_testing_decision_engine
        from src.ai.integration import get_ai_integration_layer
        
        log.info("=" * 70)
        log.info("[AI Agent] Processing with Testing Workflow")
        log.info("=" * 70)
        
        # Get enhancement data if available
        intent = getattr(self, '_last_intent', None)
        route = getattr(self, '_last_route', None)
        tools = getattr(self, '_last_tools', [])
        
        # Step 1: Analyze testing need
        testing_engine = get_testing_decision_engine()
        code_changes = code_changes or []
        
        testing_decision = testing_engine.should_write_tests(code_changes, user_message or "")
        
        log.info(f"[AI Agent] Testing decision: {testing_decision.decision}")
        log.info(f"[AI Agent] Priority: {testing_decision.priority}")
        log.info(f"[AI Agent] Trigger: {testing_decision.trigger}")
        
        # Step 2: Build enhanced context with testing info
        enhanced_parts = []
        
        # Add existing enhancement context
        if intent and route:
            enhanced_parts.append(self._build_enhanced_context(intent, route, tools))
        
        # Add testing context
        enhanced_parts.append("\n## TESTING WORKFLOW")
        enhanced_parts.append(f"Testing Decision: {testing_decision.decision}")
        enhanced_parts.append(f"Testing Priority: {testing_decision.priority}")
        enhanced_parts.append(f"Testing Trigger: {testing_decision.trigger}")
        enhanced_parts.append(f"Testing Scope: {testing_decision.scope}")
        
        if testing_decision.decision == 'write_tests':
            enhanced_parts.append("\n### Testing Instructions")
            enhanced_parts.append("The user has made code changes that require testing.")
            enhanced_parts.append("Please:")
            enhanced_parts.append("1. Review the code changes")
            enhanced_parts.append("2. Identify what needs to be tested")
            enhanced_parts.append("3. Suggest or create appropriate tests")
            enhanced_parts.append("4. Run tests to verify the changes work correctly")
            
            # Add test tool info
            integration = get_ai_integration_layer()
            if hasattr(integration, '_workspace_path'):
                test_tools = integration.get_test_tools_for_workspace()
                if test_tools.get('primary'):
                    enhanced_parts.append(f"\nPrimary Test Tool: {test_tools['primary'].name}")
                    enhanced_parts.append(f"Test Command: {test_tools['primary'].command}")
        
        # Combine context
        testing_context = "\n".join(enhanced_parts)
        
        # Add to code context
        if code_context:
            code_context = f"{testing_context}\n\n{code_context}"
        else:
            code_context = testing_context
        
        # Store testing decision
        self._last_testing_decision = testing_decision
        
        # Call standard chat with enhanced context
        self.chat(user_message, code_context)
    
    def get_last_testing_decision(self) -> Optional[Any]:
        """Get the last testing decision for external access."""
        return getattr(self, '_last_testing_decision', None)
