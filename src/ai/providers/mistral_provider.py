"""
Mistral Provider
Supports Mistral AI models with agent capabilities
Optimized for DeepSeek -> Mistral migration with stricter controls
"""

import os
import json
import time
from typing import List, Dict, Any, Generator, Optional, Callable
from src.ai.providers import BaseProvider, ProviderType
from src.utils.logger import get_logger

log = get_logger("mistral_provider")

# Mistral model pricing per 1M tokens (USD)
MISTRAL_PRICING = {
    "mistral-large-latest": {"input": 2.0, "output": 6.0},
    "mistral-medium-latest": {"input": 0.9, "output": 0.9},
    "mistral-small-latest": {"input": 0.2, "output": 0.6},
    "codestral-latest": {"input": 0.2, "output": 0.6},
    "mistral-embed": {"input": 0.1, "output": 0.0},
}

# Performance multipliers
MISTRAL_PERFORMANCE = {
    "mistral-large-latest": 1.5,
    "mistral-medium-latest": 1.2,
    "mistral-small-latest": 1.0,
    "codestral-latest": 1.3,
}

# Valid tool names for validation (prevents hallucinations)
# NOTE: This is now dynamically populated from registered tools to support custom tools
VALID_TOOL_NAMES = {
    "read_file", "write_file", "edit_file", "delete_file",
    "list_directory", "search_files", "execute_command",
    "run_python", "web_search", "web_fetch", "ask_user",
    "semantic_search", "git_status", "git_diff", "git_commit"
}

# Stricter system prompt for Mistral (compared to DeepSeek)
MISTRAL_SYSTEM_PROMPT = """You are a strict coding agent. You MUST follow these rules:

1. ALWAYS return ONLY valid JSON. No explanations, no markdown, no extra text.
2. Use tools ONLY from the provided list. Do not invent tool names.
3. Follow the exact output format specified in each task.
4. Be deterministic - same input should produce same output.
5. When writing code, ensure it's complete and runnable.

Response format must be valid JSON only."""


class MistralProvider(BaseProvider):
    """Mistral AI API Provider with DeepSeek migration optimizations"""
    
    def __init__(self):
        super().__init__(ProviderType.MISTRAL)
        self.api_key = os.getenv("MISTRAL_API_KEY", "")
        self.base_url = "https://api.mistral.ai/v1"
        self._token_count = {"input": 0, "output": 0}
        self._max_retries = 3
        self._retry_delay = 1.0
        self._allowed_tool_names = set(VALID_TOOL_NAMES)  # Dynamic tool name validation
        
        if not self.api_key:
            log.warning("MISTRAL_API_KEY not configured")
    
    def set_api_key(self, api_key: str):
        """Set the API key for this provider."""
        self.api_key = api_key
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available Mistral models"""
        models = []
        
        for model_id, pricing in MISTRAL_PRICING.items():
            perf = MISTRAL_PERFORMANCE.get(model_id, 1.0)
            
            models.append({
                "id": model_id,
                "name": model_id.replace("-", " ").title(),
                "pricing": pricing,
                "performance": perf,
                "category": self._get_category(model_id)
            })
        
        return models
    
    def _get_category(self, model_id: str) -> str:
        """Get model category"""
        if "large" in model_id:
            return "General"
        elif "medium" in model_id:
            return "General"
        elif "small" in model_id:
            return "Fast"
        elif "code" in model_id:
            return "Code"
        elif "embed" in model_id:
            return "Embedding"
        return "General"
        
    @property
    def available_models(self):
        """Return list of available models for this provider."""
        from src.ai.providers import ModelInfo
        return [
            ModelInfo("mistral-large-latest", "Mistral Large", "mistral", 128000, 8192, True, False, 2.0, 6.0),
            ModelInfo("mistral-medium-latest", "Mistral Medium", "mistral", 128000, 8192, True, False, 0.9, 0.9),
            ModelInfo("mistral-small-latest", "Mistral Small", "mistral", 128000, 8192, True, False, 0.2, 0.6),
            ModelInfo("codestral-latest", "Codestral", "mistral", 128000, 8192, True, False, 0.2, 0.6),
        ]
        
    def validate_api_key(self) -> bool:
        """Validate the current API key."""
        return bool(self.api_key)
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """Calculate cost for token usage"""
        pricing = MISTRAL_PRICING.get(model, MISTRAL_PRICING["mistral-medium-latest"])
        
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        total_cost = input_cost + output_cost
        
        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
            "currency": "USD"
        }
    
    def _validate_tool_name(self, tool_name: str) -> bool:
        """Validate tool name to prevent hallucinations.
        
        Uses dynamically populated allowed_tool_names which is refreshed
        for each request based on the tools actually sent to the API.
        This prevents rejecting custom tools that aren't in our hardcoded list.
        """
        if not tool_name or not isinstance(tool_name, str):
            return False
        # Check against dynamic set that's refreshed per request
        return tool_name in self._allowed_tool_names
    
    def _enforce_strict_prompt(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Enforce stricter system prompt for Mistral (migration from DeepSeek)"""
        if not messages:
            return messages
        
        # Check if first message is system prompt
        if messages[0].get("role") == "system":
            # Replace with stricter Mistral-optimized prompt
            messages[0]["content"] = MISTRAL_SYSTEM_PROMPT
        else:
            # Insert stricter system prompt at beginning
            messages.insert(0, {"role": "system", "content": MISTRAL_SYSTEM_PROMPT})
        
        return messages
    
    def _format_tools_for_mistral(self, tools: List[Any]) -> List[Dict]:
        """BUG #3 FIX: Convert ClaudeTool objects to Mistral API format.
            
        Mistral expects tools in format:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "what it does",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...],
                    "additionalProperties": false  # REQUIRED by Mistral
                }
            }
        }
        """
        formatted = []
    
        for tool in tools:
            # Check if already formatted (has 'type' key)
            if isinstance(tool, dict) and 'type' in tool:
                # Validate and fix the tool schema
                fixed_tool = self._fix_mistral_tool_schema(tool)
                if fixed_tool:
                    formatted.append(fixed_tool)
                continue
                
            # Format ClaudeTool objects
            if hasattr(tool, 'name') and hasattr(tool, 'input_schema'):
                try:
                    params = tool.input_schema() if callable(tool.input_schema) else tool.input_schema
                    # Fix the schema for Mistral
                    params = self._fix_params_for_mistral(params)
                        
                    formatted_tool = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": getattr(tool, 'description', f"Tool: {tool.name}"),
                            "parameters": params
                        }
                    }
                    formatted.append(formatted_tool)
                except Exception as e:
                    log.warning(f"Failed to format tool {getattr(tool, 'name', 'unknown')}: {e}")
                    continue
            elif isinstance(tool, dict):
                # Already a dictionary, ensure proper format
                if 'function' in tool:
                    fixed_tool = self._fix_mistral_tool_schema({
                        "type": tool.get("type", "function"),
                        "function": tool["function"]
                    })
                    if fixed_tool:
                        formatted.append(fixed_tool)
    
        log.info(f"[MISTRAL] Formatted {len(formatted)} tools for API (from {len(tools)} input tools)")
        return formatted
        
    def _fix_mistral_tool_schema(self, tool: Dict) -> Optional[Dict]:
        """Fix a tool schema for Mistral API compatibility."""
        try:
            fn = tool.get("function", {})
            params = fn.get("parameters", {})
                
            # Fix parameters
            params = self._fix_params_for_mistral(params)
                
            return {
                "type": tool.get("type", "function"),
                "function": {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": params
                }
            }
        except Exception as e:
            log.warning(f"[MISTRAL] Failed to fix tool schema: {e}")
            return None
        
    def _fix_params_for_mistral(self, params: Dict) -> Dict:
        """
        Fix parameter schema for Mistral API.
            
        Mistral requires:
        - type: "object" at top level
        - additionalProperties: false (strict validation)
        - All properties must have types
        """
        if not isinstance(params, dict):
            params = {}
            
        # Ensure type: object
        if params.get("type") != "object":
            params["type"] = "object"
            
        # Mistral requires additionalProperties: false for strict validation
        # Only add if not already set
        if "additionalProperties" not in params:
            params["additionalProperties"] = False
            
        # Ensure properties exists
        if "properties" not in params:
            params["properties"] = {}
            
        # Fix nested objects in properties
        for prop_name, prop_schema in params.get("properties", {}).items():
            if isinstance(prop_schema, dict):
                if prop_schema.get("type") == "object" and "properties" in prop_schema:
                    prop_schema = self._fix_params_for_mistral(prop_schema)
                    params["properties"][prop_name] = prop_schema
                # Fix items in arrays
                elif prop_schema.get("type") == "array" and "items" in prop_schema:
                    items = prop_schema["items"]
                    if isinstance(items, dict) and items.get("type") == "object":
                        items = self._fix_params_for_mistral(items)
                        prop_schema["items"] = items
            
        return params
    
    
    def _validate_json_output(self, content: str) -> tuple[bool, Any]:
        """Validate JSON output format"""
        try:
            # Try to parse as JSON
            parsed = json.loads(content)
            return True, parsed
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if "```json" in content:
                try:
                    json_str = content.split("```json")[1].split("```")[0].strip()
                    parsed = json.loads(json_str)
                    return True, parsed
                except (IndexError, json.JSONDecodeError):
                    pass
            
            # Try to find JSON between curly braces
            try:
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1 and end > start:
                    json_str = content[start:end+1]
                    parsed = json.loads(json_str)
                    return True, parsed
            except json.JSONDecodeError:
                pass
            
            return False, None
    
    def chat_with_retry(self, messages: List[Dict[str, str]], model: str = "mistral-medium-latest",
                       stream: bool = True, max_retries: int = 3, 
                       validate_json: bool = False, retry_callback=None, **kwargs) -> Generator[str, None, None]:
        """Chat with retry logic and optional JSON validation.

        retry_callback(attempt, max_retries, error_type) is called just before
        each retry so the caller can show UI feedback (e.g. 'API timeout, retrying 2/3...').
        error_type is 'timeout', 'rate_limit', or 'error'.
        """
        
        # Only enforce strict JSON prompt when NO tools are provided
        # When tools are present, let Mistral use tool_calls format
        if 'tools' not in kwargs or not kwargs['tools']:
            messages = self._enforce_strict_prompt(messages)
        
        # Set temperature: higher for tool calling, lower for text-only
        if "temperature" not in kwargs:
            kwargs["temperature"] = 0.7 if ('tools' in kwargs and kwargs['tools']) else 0.2
        
        last_error = None
        for attempt in range(max_retries):
            try:
                log.info(f"[Mistral] Attempt {attempt + 1}/{max_retries} with model: {model}")
                
                result_chunks = []
                for chunk in self._chat_internal(messages, model, stream, **kwargs):
                    result_chunks.append(chunk)
                    yield chunk
                
                # Validate JSON if requested
                if validate_json and result_chunks:
                    full_response = "".join(result_chunks)
                    is_valid, parsed = self._validate_json_output(full_response)
                    if not is_valid:
                        log.warning(f"[Mistral] Invalid JSON output, retrying...")
                        if attempt < max_retries - 1:
                            time.sleep(self._retry_delay * (attempt + 1))
                            continue
                
                return
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # Classify the error type for callback + logging
                if "timed out" in error_str or "timeout" in error_str or "read timed" in error_str:
                    error_type = 'timeout'
                elif "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                    error_type = 'rate_limit'
                else:
                    error_type = 'error'

                # SPECIAL HANDLING FOR 429 RATE LIMIT ERRORS
                if error_type == 'rate_limit':
                    log.warning(f"[Mistral] Rate limited (attempt {attempt + 1}/{max_retries})")
                    
                    # Exponential backoff with longer delays for rate limits
                    backoff_seconds = min(2 ** (attempt + 2), 30)  # Max 30 seconds
                    log.info(f"[Mistral] Waiting {backoff_seconds}s before retry due to rate limit...")
                    
                    if attempt < max_retries - 1:
                        if retry_callback:
                            try:
                                retry_callback(attempt + 2, max_retries, 'rate_limit')
                            except Exception:
                                pass
                        time.sleep(backoff_seconds)
                        continue
                    else:
                        # Final attempt failed - provide clear error
                        raise Exception(f"Mistral API rate limit exceeded. Please wait {backoff_seconds} seconds before trying again. (429 Too Many Requests)")
                
                # Standard error handling (timeouts, network errors, etc.)
                log.error(f"[Mistral] Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    if retry_callback:
                        try:
                            retry_callback(attempt + 2, max_retries, error_type)
                        except Exception:
                            pass
                    time.sleep(self._retry_delay * (attempt + 1))
                else:
                    raise last_error
    
    def _chat_internal(self, messages: List[Dict[str, str]], model: str = "mistral-medium-latest",
                      stream: bool = True, **kwargs) -> Generator[str, None, None]:
        """Internal chat method (actual API call)"""
        
        if not self.api_key:
            raise ValueError("MISTRAL_API_KEY not configured. Please add it to .env file.")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # BUG #3 FIX: Convert ClaudeTool objects to Mistral API format
        formatted_tools = None
        if 'tools' in kwargs and kwargs['tools']:
            formatted_tools = self._format_tools_for_mistral(kwargs['tools'])
            kwargs['tools'] = formatted_tools
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs
        }
        
        # Validate tools if present
        if 'tools' in kwargs and kwargs['tools']:
            log.info(f"[MISTRAL] Sending {len(kwargs['tools'])} tools to API")
            
            # DYNAMICALLY POPULATE allowed tool names from registered tools
            self._allowed_tool_names = set()
            tool_names = []
            for tool in kwargs['tools']:
                tool_name = tool.get('function', {}).get('name', '')
                if tool_name:
                    self._allowed_tool_names.add(tool_name)
                    tool_names.append(tool_name)
                    if not self._validate_tool_name(tool_name):
                        log.warning(f"[MISTRAL] Unusual tool name (possible hallucination): {tool_name}")
            
            # Log all tool names in a single line instead of one per tool
            log.debug(f"[MISTRAL] Tools: {', '.join(tool_names)}")
        
        url = f"{self.base_url}/chat/completions"
        
        try:
            import requests
            
            if stream:
                response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
                if not response.ok:
                    try:
                        error_body = response.json()
                        log.error(f"[Mistral] API error response: {json.dumps(error_body, indent=2)}")
                    except:
                        log.error(f"[Mistral] API error response (text): {response.text[:500]}")
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        try:
                            line_text = line.decode('utf-8', errors='replace').strip()
                        except UnicodeDecodeError as e:
                            log.warning(f"[Mistral] Unicode decode error: {e}")
                            line_text = line.decode('utf-8', errors='replace').strip()
                        
                        if line_text.startswith('data: '):
                            data_str = line_text[6:]
                            
                            if data_str.strip() == '[DONE]':
                                break
                            
                            try:
                                data = json.loads(data_str)
                                if 'choices' in data and len(data['choices']) > 0:
                                    delta = data['choices'][0].get('delta', {})
                                    content = delta.get('content', '')
                                    tool_calls = delta.get('tool_calls', [])
                                    
                                    # Yield content if available
                                    if content:
                                        # Filter out corrupted/non-printable characters
                                        import re
                                        # Remove replacement characters and control chars, BUT preserve \n (0x0a) and \t (0x09)
                                        content = re.sub(r'[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]', '', content)
                                        if content:  # yield even whitespace/newlines for proper markdown
                                            yield content
                                    
                                    # Handle tool calls with validation
                                    if tool_calls:
                                        validated_tool_calls = []
                                        for tc in tool_calls:
                                            tool_name = tc.get('function', {}).get('name', '')
                                            
                                            # Validate tool name - WARN but don't reject
                                            # This prevents false positives when AI uses valid tools not in current selection
                                            if tool_name and not self._validate_tool_name(tool_name):
                                                log.warning(f"[MISTRAL] Tool not in allowed list (may be valid): {tool_name}")
                                                # Still include it - let the agent handle invalid tools downstream
                                            
                                            tc_info = {
                                                'index': tc.get('index', 0),
                                                'id': tc.get('id', ''),
                                                'function': {
                                                    'name': tool_name,
                                                    'arguments': tc.get('function', {}).get('arguments', '')
                                                }
                                            }
                                            validated_tool_calls.append(tc_info)
                                        
                                        if validated_tool_calls:
                                            yield f"__TOOL_CALL_DELTA__:{json.dumps(validated_tool_calls)}"
                                    
                                    # Track tokens if available
                                    if 'usage' in data:
                                        self._token_count["input"] = data['usage'].get('prompt_tokens', 0)
                                        self._token_count["output"] = data['usage'].get('completion_tokens', 0)
                                        
                            except json.JSONDecodeError as e:
                                log.error(f"Failed to parse SSE data: {e}")
                                continue
                                
            else:
                response = requests.post(url, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                
                result = response.json()
                
                # Track tokens
                if 'usage' in result:
                    self._token_count["input"] = result['usage'].get('prompt_tokens', 0)
                    self._token_count["output"] = result['usage'].get('completion_tokens', 0)
                
                content = result['choices'][0]['message']['content']
                yield content
                
        except requests.exceptions.RequestException as e:
            log.error(f"Mistral API error: {e}")
            raise Exception(f"Mistral API request failed: {str(e)}")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            raise
    
    def chat(self, messages: List[Dict[str, str]], model: str = "mistral-medium-latest",
             stream: bool = True, retry_callback=None, **kwargs) -> Generator[str, None, None]:
        """Standard chat interface with retry logic"""
        yield from self.chat_with_retry(messages, model, stream, retry_callback=retry_callback, **kwargs)
    
    def chat_stream(self, messages, model, temperature=0.7, max_tokens=2000, tools=None, retry_callback=None, **kwargs):
        """Stream chat completion - delegates to chat()"""
        formatted_messages = self._format_messages_for_mistral(messages)
        # FIX: Pass tools parameter to chat() method
        yield from self.chat(formatted_messages, model, stream=True, tools=tools, retry_callback=retry_callback, **kwargs)
    
    def _format_messages_for_mistral(self, messages) -> List[Dict[str, Any]]:
        """Convert ChatMessage objects to Mistral-compatible format"""
        formatted = []
        for msg in messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                m = {"role": msg.role, "content": msg.content}
                if hasattr(msg, 'name') and msg.name:
                    m["name"] = msg.name
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    m["tool_calls"] = msg.tool_calls
                if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
                    m["tool_call_id"] = msg.tool_call_id
            else:
                m = msg
            formatted.append(m)
        return formatted
    
    def chat_structured(self, messages: List[Dict[str, str]], model: str = "mistral-medium-latest",
                       output_schema: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Chat with guaranteed structured JSON output (for tool calls/planning)"""
        
        # Enforce JSON mode
        if output_schema:
            # Add schema to system prompt
            schema_prompt = f"\n\nYou MUST return ONLY valid JSON matching this schema:\n{json.dumps(output_schema, indent=2)}"
            messages = self._enforce_strict_prompt(messages)
            messages[0]["content"] += schema_prompt
        
        kwargs["temperature"] = 0.2  # Force deterministic
        
        for attempt in range(self._max_retries):
            try:
                result_chunks = []
                for chunk in self._chat_internal(messages, model, stream=False, **kwargs):
                    result_chunks.append(chunk)
                
                full_response = "".join(result_chunks)
                is_valid, parsed = self._validate_json_output(full_response)
                
                if is_valid:
                    return {"success": True, "data": parsed, "raw": full_response}
                else:
                    log.warning(f"[Mistral] Invalid JSON on attempt {attempt + 1}")
                    if attempt < self._max_retries - 1:
                        time.sleep(self._retry_delay * (attempt + 1))
                        continue
                    else:
                        return {"success": False, "error": "Failed to get valid JSON", "raw": full_response}
                        
            except Exception as e:
                log.error(f"[Mistral] Structured chat error: {e}")
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                else:
                    return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Max retries exceeded"}
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics"""
        total_tokens = self._token_count["input"] + self._token_count["output"]
        
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "total_tokens": total_tokens,
        }
    
    def reset_usage(self):
        """Reset usage counters"""
        self._token_count = {"input": 0, "output": 0}


# Singleton instance
_mistral_provider = None


def get_mistral_provider() -> MistralProvider:
    """Get singleton Mistral provider instance"""
    global _mistral_provider
    if _mistral_provider is None:
        _mistral_provider = MistralProvider()
    return _mistral_provider
