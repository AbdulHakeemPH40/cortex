"""
AI Agent — Gateway to OpenAI / Anthropic / Mock responses.
Runs in a QThread to keep the UI responsive.
Uses Provider Registry and Key Manager for secure API key handling.
"""

import os
import json
from pathlib import Path
import hashlib
from typing import Optional, List, Dict, Any
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from src.utils.logger import get_logger
from src.core.key_manager import get_key_manager
from src.ai.providers import get_provider_registry, ProviderType, ChatMessage

log = get_logger("ai_agent")

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass


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

    def run(self):
        log.info("AIWorker.run() started")
        import time
        start_time = time.time()
        try:
            self._call_provider()
            elapsed = time.time() - start_time
            log.info(f"AIWorker.run() completed successfully in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - start_time
            log.error(f"AI Worker error after {elapsed:.1f}s: {e}")
            self.error_occurred.emit(str(e))

    def _call_provider(self):
        """Call AI provider using the provider registry."""
        # Map provider string to ProviderType
        # Current providers
        provider_map = {
            "openai": ProviderType.OPENAI,
            "anthropic": ProviderType.ANTHROPIC,
            "deepseek": ProviderType.DEEPSEEK,
            "mock": ProviderType.MOCK
        }
        
        # TODO: Future Together AI integration
        # Together AI supports multiple models with unified API:
        # - DeepSeek: deepseek-ai/DeepSeek-R1, deepseek-ai/DeepSeek-V3.1
        # - Qwen: Qwen/Qwen3.5-9B, Qwen/Qwen3-Coder-Next-Fp8, Qwen/Qwen3-235B-A22B
        # - Moonshot: moonshotai/Kimi-K2.5
        #
        # Usage example:
        # from together import Together
        # client = Together()
        # response = client.chat.completions.create(
        #     model="deepseek-ai/DeepSeek-R1",
        #     messages=[{"role": "user", "content": "Hello"}]
        # )
        #
        # To add Together AI:
        # 1. Create TogetherProvider in src/ai/providers/together_provider.py
        # 2. Add ProviderType.TOGETHER to providers/__init__.py
        # 3. Add "together": ProviderType.TOGETHER to this map
        
        provider_type = provider_map.get(self.provider, ProviderType.MOCK)
        
        # Get provider instance from registry
        registry = get_provider_registry()
        provider = registry.get_provider(provider_type)
        
        # Get API key - Prioritize environment variable (.env) over storage
        if provider_type != ProviderType.MOCK:
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
        
        # Stream the response with proper tool call handling
        try:
            log.info("Starting to stream from provider...")
            chunk_count = 0
            tool_call_buffer = {}  # index -> accumulated tool call data
            
            import time
            last_chunk_time = time.time()
            
            for chunk in provider.chat_stream(
                messages=chat_messages,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=self.tools
            ):
                if not chunk:
                    # Check for timeout on empty chunks
                    if time.time() - last_chunk_time > 30:  # 30 second timeout
                        log.warning("Stream timeout - no data received for 30 seconds")
                        break
                    continue
                
                last_chunk_time = time.time()
                chunk_count += 1
                
                # Handle tool call deltas
                if chunk.startswith("__TOOL_CALL_DELTA__:"):
                    try:
                        deltas = json.loads(chunk[len("__TOOL_CALL_DELTA__:"):])
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
                    except Exception as e:
                        log.error(f"Error parsing tool call delta: {e}")
                else:
                    # Regular content chunk
                    self._full_response += chunk
                    self.chunk_received.emit(chunk)
            
            log.info(f"Stream completed, received {chunk_count} chunks")
            
            # Convert tool call buffer to final format
            if tool_call_buffer:
                final_tool_calls = []
                for idx in sorted(tool_call_buffer.keys()):
                    tc = tool_call_buffer[idx]
                    if tc["id"] and tc["name"]:  # Only include complete tool calls
                        final_tool_calls.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        })
                if final_tool_calls:
                    self.tool_calls = final_tool_calls
                    log.info(f"Worker has {len(final_tool_calls)} tool calls to return")
            
            log.info(f"Emitting finished signal with response length {len(self._full_response)}")
            self.finished.emit(self._full_response)
            
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                error_msg = f"Invalid API key for {self.provider}. Please check your settings."
            elif "rate limit" in error_msg.lower():
                error_msg = f"Rate limit exceeded for {self.provider}. Please try again later."
            raise Exception(error_msg)


class AIAgent(QObject):
    """
    High-level AI agent — creates workers and manages conversation history.
    """
    response_chunk = pyqtSignal(str)
    response_complete = pyqtSignal(str)
    request_error = pyqtSignal(str)
    file_generated = pyqtSignal(str)
    file_edited_diff = pyqtSignal(str, str, str)  # file_path, original_content, new_content
    tool_activity = pyqtSignal(str, str, str)  # tool_type, info, status
    thinking_started = pyqtSignal()
    thinking_stopped = pyqtSignal()
    todos_updated = pyqtSignal(list, str)  # todos_list, main_task

    SYSTEM_PROMPT = """# CORTEX AGENTIC IDE MANAGER v3.7 - Project File Workflows

## IDENTITY
You are CORTEX, a high-performance autonomous agent fully integrated into the Cortex IDE.

## OPERATIONAL GUIDELINES (CRITICAL FOR SPEED)
1. **Project-Based Workflows**: When generating plans, tasks, or walkthroughs, use the specialized tags.
   - `<plan>`: Comprehensive implementation strategies.
   - `<tasklist>`: Detailed step-by-step checklists.
   - `<walkthrough>`: Post-implementation summaries.
   IMPORTANT: These tags will automatically be parsed by the IDE and saved as files in the `.cortex/` directory of your project. They will then be opened for the user in a new editor tab.
2. **Critical Path Reasoning**: Explain your logic briefly (1-2 sentences) and proceed immediately to implementation.
3. **Interactive Options**: Use `<options>` for numbered choices to speed up user selection.
    ```html
    <options>
    1. Quick Fix
    2. Detailed Refactor
    </options>
    ```

## AUTONOMOUS OPERATION (AGENT MODE)
- **Auto-approval ENABLED**: You have full permission to execute tools without asking for confirmation
- **File Creation**: Create files directly as needed - no permission needed
- **Code Execution**: Run commands directly - no permission needed
- **Proactive Behavior**: Don't ask "should I do X?" - just do it!
- **File Deletion**: You may delete files when necessary for the task

Maintain a professional, proactive, and highly competent engineering tone."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from src.config.settings import get_settings
        from src.ai.tools import ToolRegistry
        from src.ai.context_manager import get_context_manager
        from src.core.change_orchestrator import get_change_orchestrator
        self._settings = get_settings()
        self._project_root: Optional[str] = None
        self._tool_registry = ToolRegistry(project_root=self._project_root)
        self._history: list[dict] = []
        self._history_summary: str = ""
        self._worker: AIWorker | None = None
        self._pending_tool_calls: list[dict] = []
        self._always_allowed: bool = False
        self._check_configuration()
        self._mode = "Agent"  # Default mode
        self._always_allowed = True  # Agent mode has full autonomy by default
        self._warmup_shown = False  # Track if warmup has been shown
        self._context_manager = None  # Will be initialized when project is set
        self._active_file_path = None
        self._cursor_position = None
        self._change_orchestrator = get_change_orchestrator()

    def set_interaction_mode(self, mode: str):
        """Set the interaction mode (Agent or Ask)."""
        self._mode = mode
        log.info(f"AI Agent interaction mode switched to: {mode}")
        # Enable always allow in Agent mode for full autonomy
        if mode == "Agent":
            self._always_allowed = True
            log.info("AI Agent: Auto-approval enabled for Agent mode")

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

    def set_project_root(self, path: str):
        """Set project root and load project-specific history."""
        self._project_root = path
        self._tool_registry.project_root = path
        log.info(f"AI Agent context switched to project: {path}")
        self._load_history_from_disk(path)
        
        # Initialize context manager with new project root
        from src.ai.context_manager import get_context_manager
        self._context_manager = get_context_manager(path)

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

    def chat(self, user_message: Optional[str], code_context: str = ""):
        """Send a message and get a streamed response."""
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
            
            # Check for pending tool confirmation - auto-execute if permission system was removed
            if self._pending_tool_calls:
                # Permission system removed - auto-execute pending tools
                log.info("Auto-executing pending tools (permission system bypassed)")
                self._execute_pending_tools()
                return
            
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

        # Build system prompt with summary if available
        system_content = self.SYSTEM_PROMPT
        if self._history_summary:
            system_content += f"\n\n## CONVERSATION SUMMARY (PAST CONTEXT)\n{self._history_summary}"
            
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

        # FOR TESTING: Force deepseek if not mock
        provider = self._settings.get("ai", "provider") or "deepseek"
        if provider != "mock":
            provider = "deepseek"
            
        model = self._settings.get("ai", "model") or "deepseek-chat"
        # Ensure deepseek model is used for deepseek provider
        if provider == "deepseek" and "deepseek" not in model.lower():
            model = "deepseek-chat"
        temperature = float(self._settings.get("ai", "temperature") or 0.7)
        max_tokens = int(self._settings.get("ai", "max_tokens") or 4096)

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

        log.info(f"Creating AI worker with {len(sanitized_messages)} messages, model={model}, provider={provider}")
        self._worker = AIWorker(sanitized_messages, model, temperature, max_tokens, provider, tools=tools_list if provider != "mock" else None)
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
        provider = get_provider_registry().get_provider(
            ProviderType.DEEPSEEK if provider_name != "mock" else ProviderType.MOCK
        )
        
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
        except Exception as e:
            log.error(f"Failed to load history: {e}")
            self._history = []
            self._history_summary = ""
    
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
        
        # Parse and emit TODOs if present
        self._parse_and_emit_todos(full_text)
        
        # Clear worker reference since it's done
        worker = self._worker
        self._worker = None
        
        tool_calls = getattr(worker, "tool_calls", None)
        log.info(f"Tool calls from worker: {tool_calls is not None}")
        
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
                # _execute_tools sets _continue_after_tools_flag
                # Now trigger continuation
                log.info("Triggering continuation after tools execution")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, lambda: self._continue_chat_after_tools())
                return  # Return early - continuation scheduled via QTimer
        else:
            self._history.append({"role": "assistant", "content": full_text})
            self.response_complete.emit(full_text)
            
        # Refactor: Save workflow tags to physical files in .cortex/
        self._save_workflow_files(full_text)
        self._save_history_to_disk()

    def _execute_tools(self, tool_calls, assistant_content=""):
        """Execute tool calls and continue the chat.
        
        Args:
            tool_calls: List of tool call objects from the assistant
            assistant_content: The assistant's message content (to be added atomically with tools)
        """
        import difflib
        
        # Emit assistant content first (if any) so user sees the AI is working
        if assistant_content and assistant_content.strip():
            self.response_chunk.emit(assistant_content)
        else:
            # Emit a default message so user knows AI is using tools
            tool_names = [tc["function"]["name"] for tc in tool_calls]
            self.response_chunk.emit(f"I'll help you with that. Let me use {', '.join(tool_names)} to gather information...")
        
        # Start exploration block for UI display
        self.response_chunk.emit("\n<exploration>\n")
        
        # Collect tool results first
        tool_results = []
        
        for tool_call in tool_calls:
            name = tool_call["function"]["name"]
            try:
                args = json.loads(tool_call["function"]["arguments"])
            except:
                args = {}
            
            # Display tool activity with cards
            if name == "run_command":
                cmd = args.get("command", "")
                self.tool_activity.emit("run_command", cmd[:60], "running")
            elif name == "list_directory":
                path = args.get("path", "")
                display_path = path.split('\\')[-1] or path.split('/')[-1] or path
                self.tool_activity.emit("list_directory", display_path, "running")
            elif name == "read_file":
                path = args.get("path", "")
                display_path = path.split('\\')[-1] or path.split('/')[-1] or path
                self.tool_activity.emit("read_file", display_path, "running")
            elif name == "write_file":
                path = args.get("path", "")
                display_path = path.split('\\')[-1] or path.split('/')[-1] or path
                self.tool_activity.emit("write_file", display_path, "running")
            elif name == "edit_file":
                path = args.get("path", "")
                display_path = path.split('\\')[-1] or path.split('/')[-1] or path
                self.tool_activity.emit("edit_file", display_path, "running")
            elif name == "search_code":
                query = args.get("query", "")
                self.tool_activity.emit("search_code", query[:40], "running")
            elif name == "git_status":
                self.tool_activity.emit("git_status", "Checking status", "running")
            elif name == "git_diff":
                self.tool_activity.emit("git_diff", "Getting diff", "running")
            elif name == "delete_path":
                path = args.get("path", "")
                display_path = path.split('\\')[-1] or path.split('/')[-1] or path
                self.tool_activity.emit("delete_path", display_path, "running")
            else:
                self.tool_activity.emit(name, str(args)[:50], "running")
            
            log.info(f"Executing tool: {name} with args: {args}")
            
            # For diff tracking, read file before edit
            original_content = ""
            if name in ["write_file", "edit_file"]:
                try:
                    path = args.get("path")
                    if path and isinstance(path, str) and os.path.exists(path):
                        with open(path, 'r', encoding='utf-8') as f:
                            original_content = f.read()
                except: pass

            result = self._tool_registry.execute_tool(name, args)
            
            # Store tool result
            tool_results.append({
                "tool_call_id": tool_call["id"],
                "name": name,
                "content": str(result.result) if result.success else f"Error: {result.error}",
                "success": result.success
            })
            
            # Tool result display with activity cards
            if result.success:
                if name == "list_directory":
                    content = str(result.result)
                    file_count = content.count('\n') + 1 if content else 0
                    self.tool_activity.emit("list_directory", f"Found {file_count} items", "complete")
                elif name == "read_file":
                    path = args.get("path", "")
                    content = str(result.result)
                    line_count = content.count('\n') + 1 if content else 0
                    display_path = path.split('/')[-1] if '/' in path else path.split('\\')[-1] if '\\' in path else path
                    self.tool_activity.emit("read_file", f"{display_path} ({line_count} lines)", "complete")
                elif name in ["write_file", "edit_file"]:
                    path = args.get("path", "")
                    display_path = path.split('/')[-1] if '/' in path else path.split('\\')[-1] if '\\' in path else path
                    self.tool_activity.emit(name, f"{display_path} ✓", "complete")
                elif name == "run_command":
                    cmd = args.get("command", "")
                    self.tool_activity.emit("run_command", f"{cmd[:40]} ✓", "complete")
                elif name == "search_code":
                    self.tool_activity.emit("search_code", "Search completed", "complete")
                elif name == "git_status":
                    self.tool_activity.emit("git_status", "Status retrieved", "complete")
                elif name == "git_diff":
                    self.tool_activity.emit("git_diff", "Diff retrieved", "complete")
                else:
                    self.tool_activity.emit(name, "Completed", "complete")
            else:
                self.tool_activity.emit(name, f"Error: {result.error[:40]}", "error")

            # Hand off the file edit to the frontend tracker for the Diff popup
            if name in ["write_file", "edit_file"] and result.success:
                try:
                    new_content = ""
                    path = args.get("path")
                    if path and isinstance(path, str) and os.path.exists(path):
                        with open(path, 'r', encoding='utf-8') as f:
                            new_content = f.read()
                    
                    if path and isinstance(path, str) and original_content != new_content:
                        self.file_edited_diff.emit(path, original_content, new_content)
                        self.response_chunk.emit(f"\n</exploration>\n<file_edited>\n{path}\n</file_edited>\n<exploration>\n")
                except Exception as e:
                    log.error(f"Failed to process file edit diff: {e}")
        
        # Close exploration block
        self.response_chunk.emit("\n</exploration>\n")
        
        # NOW add assistant message and ALL tool results atomically to history
        # This ensures proper pairing - assistant with tool_calls always followed by matching tool responses
        self._history.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": tool_calls
        })
        
        for tool_result in tool_results:
            self._history.append({
                "role": "tool",
                "tool_call_id": tool_result["tool_call_id"],
                "name": tool_result["name"],
                "content": tool_result["content"]
            })
        
        # Batch save after all tools are done
        self._save_history_to_disk()
        
        # Store that we need to continue after tools
        self._continue_after_tools_flag = True
        
        # Emit completion to unlock UI - the actual continuation happens after worker cleanup
        self.response_complete.emit(assistant_content + "\n\n[Tools executed, continuing...]")
    
    def _continue_chat_after_tools(self):
        """Continue chat after tools have been executed."""
        log.info("_continue_chat_after_tools called")
        self._continue_after_tools_flag = False
        
        # Ensure worker is cleared
        if self._worker:
            log.warning("Worker still exists in _continue_chat_after_tools, clearing")
            self._worker = None
        
        # Now continue the chat
        self.chat(None)  # Continue without adding a user message

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
        log.error(f"AI error: {error}")
        # Clear worker reference on error
        self._worker = None
        self.request_error.emit(error)
        # Also emit completion to unlock UI
        self.response_complete.emit(f"❌ Error: {error}")

    def set_always_allowed(self, allowed: bool):
        """Set whether to always allow tool execution without confirmation"""
        self._always_allowed = allowed
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

    def _parse_and_emit_todos(self, text: str):
        """Parse TODO items from response text and emit to UI."""
        import re
        
        todos = []
        main_task = ""
        
        # Look for numbered task lists (1. Task description, 2. Task description, etc.)
        # Or checkbox style (- [ ] Task, - [x] Task)
        
        # Pattern for numbered tasks
        numbered_pattern = r'^\s*(\d+)\.\s*(.+)$'
        # Pattern for checkbox tasks
        checkbox_pattern = r'^\s*[-*]\s*\[([ xX])\]\s*(.+)$'
        
        lines = text.split('\n')
        task_id = 0
        
        for line in lines:
            # Check numbered tasks
            numbered_match = re.match(numbered_pattern, line)
            if numbered_match:
                task_id += 1
                content = numbered_match.group(2).strip()
                if not main_task and task_id == 1:
                    main_task = content[:50] + ('...' if len(content) > 50 else '')
                todos.append({
                    'id': f'task_{task_id}',
                    'content': content,
                    'status': 'PENDING'
                })
                continue
            
            # Check checkbox tasks
            checkbox_match = re.match(checkbox_pattern, line)
            if checkbox_match:
                task_id += 1
                checked = checkbox_match.group(1).lower() == 'x'
                content = checkbox_match.group(2).strip()
                if not main_task and task_id == 1:
                    main_task = content[:50] + ('...' if len(content) > 50 else '')
                todos.append({
                    'id': f'task_{task_id}',
                    'content': content,
                    'status': 'COMPLETE' if checked else 'PENDING'
                })
        
        # Only emit if we found meaningful todos (at least 2)
        if len(todos) >= 2:
            log.info(f"Parsed {len(todos)} todos from response")
            self.todos_updated.emit(todos, main_task)
    
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
