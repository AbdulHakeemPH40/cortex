"""
OpenAI Responses API Provider
Supports Codex models and other models that require /v1/responses endpoint.
"""
import os
import json
import logging
import requests
from typing import List, Dict, Any, Optional, Generator

log = logging.getLogger(__name__)

RESPONSES_BASE_URL = "https://api.openai.com/v1/responses"


class OpenAIResponsesProvider:
    """Provider for OpenAI's /v1/responses endpoint.
    
    Supports Codex models (gpt-5.*-codex, codex-mini-latest) and other
    models that only work with the Responses API.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = RESPONSES_BASE_URL
        self._token_count = {"input": 0, "output": 0}

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str = "gpt-5.1-codex-mini",
        max_tokens: int = 4000,
        tools: List[Dict[str, Any]] = None,
        retry_callback=None,
        **kwargs
    ) -> Generator[str, None, None]:
        """Stream response from OpenAI Responses API.

        Converts ChatMessage objects to Responses API format and handles
        tool calling, streaming, and reasoning content.
        """
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        log.info(f"[OpenAI Responses] Model: {model}")

        # Serialize messages and convert to Responses API format
        items = self._convert_messages_to_items(messages)

        # Convert tools to Responses API format
        formatted_tools = self._convert_tools_for_responses(tools) if tools else []

        if formatted_tools:
            log.info(f"[OpenAI Responses] Sending {len(formatted_tools)} tools")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Build payload - items can be a list or dict with instructions+input
        payload = {
            "model": model,
            "max_output_tokens": max_tokens,
        }
        
        # If items is a dict (has instructions), merge it into payload
        if isinstance(items, dict):
            payload.update(items)
        else:
            payload["input"] = items
        
        payload.update(kwargs)

        # Add tools if present
        if formatted_tools:
            payload["tools"] = formatted_tools

        # Check if we should stream
        stream = kwargs.get("stream", True)

        try:
            if stream:
                yield from self._stream_response(headers, payload, model)
            else:
                yield from self._non_stream_response(headers, payload)

        except requests.exceptions.RequestException as e:
            log.error(f"[OpenAI Responses] API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                log.error(f"[OpenAI Responses] Response body: {e.response.text[:500]}")
            raise Exception(f"OpenAI Responses API request failed: {str(e)}")
        except Exception as e:
            log.error(f"[OpenAI Responses] Unexpected error: {e}")
            raise

    def _convert_messages_to_items(self, messages: List) -> List[Dict[str, Any]]:
        """Convert ChatMessage objects to Responses API items format."""
        items = []
        system_instructions = None

        for msg in messages:
            # Convert object to dict if needed
            if not isinstance(msg, dict):
                msg = {
                    "role": getattr(msg, 'role', 'user'),
                    "content": getattr(msg, 'content', ''),
                    "tool_calls": getattr(msg, 'tool_calls', None),
                    "tool_call_id": getattr(msg, 'tool_call_id', None),
                }

            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                # Responses API uses 'instructions' for system prompt
                system_instructions = content
            elif role == "user":
                items.append({
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}]
                })
            elif role == "assistant":
                # Handle tool calls from assistant
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        items.append({
                            "type": "function_call",
                            "call_id": tc.get("id", f"call_{len(items)}"),
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"]
                        })
                else:
                    items.append({
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}]
                    })
            elif role == "tool":
                # Tool output
                items.append({
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": content
                })

        # Build final input with instructions at top level
        if system_instructions:
            # System prompt becomes instructions
            return {"instructions": system_instructions, "input": items}
        else:
            return items

    def _convert_tools_for_responses(self, tools: List[Dict]) -> List[Dict]:
        """Convert OpenAI chat tools format to Responses API format."""
        formatted = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool.get("function", {})
                formatted.append({
                    "type": "function",
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                    "strict": fn.get("strict", False)
                })
            else:
                formatted.append(tool)
        return formatted

    def _stream_response(self, headers, payload, model):
        """Handle streaming response from Responses API.
        
        Yields text deltas and tool call markers in the same format as
        DeepSeek/Mistral/OpenAI Chat Completions providers so the agent
        bridge can process them identically.
        """
        import re
        payload["stream"] = True

        resp = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=120
        )
        resp.raise_for_status()

        # Accumulator for Responses API tool calls
        # key = output_index, value = {call_id, name, arguments}
        _tool_acc: Dict[int, Dict[str, str]] = {}

        for line in resp.iter_lines():
            if not line:
                continue

            try:
                line_text = line.decode('utf-8', errors='replace').strip()
            except Exception:
                continue

            if not line_text.startswith('data: '):
                continue

            data_str = line_text[6:]
            if data_str.strip() == '[DONE]':
                break

            try:
                data = json.loads(data_str)
                event_type = data.get("type", "")

                # ── Text content ──────────────────────────────────
                if event_type == "response.output_text.delta":
                    delta = data.get("delta", "")
                    if delta:
                        delta = re.sub(
                            r'[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f'
                            r'\u200b-\u200f\u2060\ufeff\u00ad]',
                            '', delta
                        )
                        if delta:  # yield even whitespace/newlines for markdown
                            yield delta

                elif event_type == "response.output_text.done":
                    pass  # final text already yielded via deltas

                elif event_type == "response.output_text.annotation.added":
                    pass  # skip annotations

                # ── Tool / function calls ─────────────────────────
                elif event_type == "response.output_item.added":
                    item = data.get("item", {})
                    idx = data.get("output_index", 0)
                    if item.get("type") == "function_call":
                        _tool_acc[idx] = {
                            "call_id": item.get("call_id", ""),
                            "name":    item.get("name", ""),
                            "arguments": "",
                        }
                        log.info(f"[OpenAI Responses] Tool call started: {item.get('name')}")

                elif event_type == "response.function_call_arguments.delta":
                    # Accumulate arguments into the active tool call
                    idx = data.get("output_index", 0)
                    if idx in _tool_acc:
                        _tool_acc[idx]["arguments"] += data.get("delta", "")

                elif event_type == "response.function_call_arguments.done":
                    # Tool call arguments complete - yield in bridge-compatible format
                    idx = data.get("output_index", 0)
                    if idx in _tool_acc:
                        tc = _tool_acc[idx]
                        tool_delta = [{
                            "index": idx,
                            "id":    tc["call_id"],
                            "function": {
                                "name":      tc["name"],
                                "arguments": tc.get("arguments", data.get("arguments", "")),
                            }
                        }]
                        yield f"__TOOL_CALL_DELTA__:{json.dumps(tool_delta)}"
                        log.info(f"[OpenAI Responses] Tool call complete: {tc['name']}")

                elif event_type == "response.output_item.done":
                    # Clean up completed tool from accumulator
                    idx = data.get("output_index", 0)
                    _tool_acc.pop(idx, None)

                # ── Lifecycle events ──────────────────────────────
                elif event_type == "response.content_part.added":
                    pass

                elif event_type == "response.content_part.done":
                    pass

                elif event_type == "response.completed":
                    response_data = data.get("response", {})
                    if "usage" in response_data:
                        usage = response_data["usage"]
                        self._token_count["input"] = usage.get("input_tokens", 0)
                        self._token_count["output"] = usage.get("output_tokens", 0)

                elif event_type in (
                    "response.created", "response.in_progress",
                    "response.output_item.added",  # already handled above
                ):
                    pass  # known lifecycle events

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                log.warning(f"[OpenAI Responses] Parse error: {e}")
                continue

    def _non_stream_response(self, headers, payload):
        """Handle non-streaming response."""
        resp = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=120
        )
        resp.raise_for_status()

        result = resp.json()

        # Extract text from output
        output = result.get("output", [])
        for item in output:
            if item.get("type") == "message":
                content = item.get("content", [])
                for part in content:
                    if part.get("type") == "output_text":
                        text = part.get("text", "")
                        if text:
                            yield text

        # Track tokens
        if "usage" in result:
            usage = result["usage"]
            self._token_count["input"] = usage.get("input_tokens", 0)
            self._token_count["output"] = usage.get("output_tokens", 0)

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current usage statistics."""
        total = self._token_count["input"] + self._token_count["output"]
        return {
            "input_tokens": self._token_count["input"],
            "output_tokens": self._token_count["output"],
            "total_tokens": total
        }
