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
        try:
            self._call_provider()
        except Exception as e:
            log.error(f"AI Worker error: {e}")
            self.error_occurred.emit(str(e))

    def _call_provider(self):
        """Call AI provider using the provider registry."""
        # Map provider string to ProviderType
        provider_map = {
            "openai": ProviderType.OPENAI,
            "anthropic": ProviderType.ANTHROPIC,
            "deepseek": ProviderType.DEEPSEEK,
            "mock": ProviderType.MOCK
        }
        
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
        
        # Stream the response
        try:
            for chunk in provider.chat_stream(
                messages=chat_messages,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=self.tools
            ):
                if chunk:
                    if chunk.startswith("__TOOL_CALL_DELTA__:"):
                        try:
                            deltas = json.loads(chunk[len("__TOOL_CALL_DELTA__:"):])
                            for delta in deltas:
                                index = delta.get("index", 0)
                                if index not in self._tool_calls:
                                    self._tool_calls[index] = {"id": "", "name": "", "arguments": ""}
                                
                                if delta.get("id"):
                                    self._tool_calls[index]["id"] += delta["id"]
                                if delta.get("function", {}).get("name"):
                                    self._tool_calls[index]["name"] += delta["function"]["name"]
                                if delta.get("function", {}).get("arguments"):
                                    self._tool_calls[index]["arguments"] += delta["function"]["arguments"]
                        except Exception as e:
                            log.error(f"Error parsing tool call delta: {e}")
                    else:
                        self._full_response += chunk
                        self.chunk_received.emit(chunk)
            
            # Emit finished with tool calls if any
            if self._tool_calls:
                # Convert to list of tool calls
                final_tool_calls = []
                for idx in sorted(self._tool_calls.keys()):
                    tc = self._tool_calls[idx]
                    final_tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"]
                        }
                    })
                # We reuse the finished signal but AIAgent will check if it's a tool call
                # Or we could add a new signal. For simplicity, let's attach to the object.
                self.tool_calls = final_tool_calls
                
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

## SAFETY & PERMISSIONS
- **File Deletion**: Always explain WHY you are deleting something.
- **Confirmation**: The system will automatically wrap your tool calls in a permission UI. You do not need to ask for permission manually unless you want to confirm a higher-level decision.

Maintain a professional, proactive, and highly competent engineering tone."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from src.config.settings import get_settings
        from src.ai.tools import ToolRegistry
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
        self._warmup_shown = False  # Track if warmup has been shown

    def set_interaction_mode(self, mode: str):
        """Set the interaction mode (Agent or Ask)."""
        self._mode = mode
        log.info(f"AI Agent interaction mode switched to: {mode}")

    def _is_greeting(self, message: str) -> bool:
        """Check if message is a simple greeting (not a work request)"""
        import re
        message_lower = message.lower().strip()
        
        # Only match SIMPLE greetings - avoid matching work-related messages
        simple_greetings = [
            r'^\s*(hi|hello|hey|greetings|howdy|yo)\s*$',
            r'^\s*(hi|hello|hey)\s+(there|cortex|ai)\s*$',
            r'^\s*(good\s+(morning|afternoon|evening))\s*$',
        ]
        
        # Check if it's a simple greeting
        is_simple_greeting = False
        for pattern in simple_greetings:
            if re.match(pattern, message_lower):
                is_simple_greeting = True
                break
        
        # If it contains work keywords, it's NOT a greeting
        work_keywords = [
            'what', 'how', 'why', 'when', 'where', 'can', 'could', 'would', 
            'will', 'do', 'does', 'did', 'is', 'are', 'create', 'make', 'build',
            'fix', 'add', 'implement', 'write', 'edit', 'modify', 'change',
            'help', 'need', 'want', 'should', 'please', 'explain', 'show',
            'tell', 'give', 'find', 'search', 'look', 'check', 'analyze',
            'plan', 'next', 'step', 'task', 'work', 'code', 'file', 'project'
        ]
        
        # If message contains work keywords, it's a work request, not a greeting
        for keyword in work_keywords:
            if keyword in message_lower and len(message_lower) > len(keyword) + 3:
                return False
        
        return is_simple_greeting

    def _handle_project_warmup(self):
        """Handle greeting - simple and clean"""
        if not self._project_root:
            self.response_chunk.emit("👋 Hi! Please open a project first.")
            self.response_complete.emit("No project")
            return
        
        # Simple greeting only
        project_name = os.path.basename(self._project_root)
        self.response_chunk.emit(f"👋 Hi! I'm ready to help with **{project_name}**.")
        self.response_complete.emit("Greeting")

    def _check_configuration(self):
        """Check and log AI configuration status."""
        provider = self._settings.get("ai", "provider") or "mock"
        model = self._settings.get("ai", "model") or "gpt-4o-mini"
        
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

    def chat(self, user_message: Optional[str], code_context: str = ""):
        """Send a message and get a streamed response."""
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
                msg = user_message.lower().strip()
                if msg in ["yes", "y", "confirm", "ok", "do it", "approve"]:
                    self._execute_pending_tools()
                    return
                elif msg in ["no", "n", "cancel", "deny", "stop"]:
                    self._cancel_pending_tools()
                    return
                # Handle "Always allow" from text if buttons not used
                elif "always" in msg:
                    self.set_always_allowed(True)
                    self._execute_pending_tools()
                    return
                # If neither, treat as a normal message but warn
                log.warning("Tool execution pending. Please confirm with 'yes' or 'no'.")
                # Do NOT proceed to call the API with pending tools, it will cause Error 400
                return
            
            # Build context-aware message
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

        self._worker = AIWorker(sanitized_messages, model, temperature, max_tokens, provider, tools=tools_list if provider != "mock" else None)
        self._worker.chunk_received.connect(self.response_chunk)
        self._worker.finished.connect(self._on_done)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

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
            self._history = data.get("history", [])
            self._history_summary = data.get("summary", "")
            log.info(f"Restored history for project {project_id} ({len(self._history)} messages)")
        except Exception as e:
            log.error(f"Failed to load history: {e}")
            self._history = []
            self._history_summary = ""

    def _on_done(self, full_text: str):
        tool_calls = getattr(self._worker, "tool_calls", None)
        
        if tool_calls:
            # Handle tool calls
            self._history.append({
                "role": "assistant",
                "content": full_text,
                "tool_calls": tool_calls
            })
            
            # Check if any tool requires confirmation
            requires_approval = False
            for tc in tool_calls:
                tool = self._tool_registry.get_tool(tc["function"]["name"])
                if tool and tool.requires_confirmation:
                    requires_approval = True
                    break
            
            if requires_approval and not self._always_allowed:
                self._pending_tool_calls = tool_calls
                
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
                # Execute tools and continue chat
                self._execute_tools(tool_calls)
        else:
            self._history.append({"role": "assistant", "content": full_text})
            self.response_complete.emit(full_text)
            
        # Refactor: Save workflow tags to physical files in .cortex/
        self._save_workflow_files(full_text)
        self._save_history_to_disk()

    def _execute_tools(self, tool_calls):
        """Execute tool calls and continue the chat."""
        import difflib
        
        # Start exploration block
        self.response_chunk.emit("\n<exploration>\n")
        
        for tool_call in tool_calls:
            name = tool_call["function"]["name"]
            try:
                args = json.loads(tool_call["function"]["arguments"])
            except:
                args = {}
            
            # Clean, minimal status messages with emojis
            if name == "run_command":
                cmd = args.get("command", "")[:60]
                self.response_chunk.emit(f"🔧 `{cmd}{'...' if len(cmd) > 60 else ''}`\n")
            elif name == "list_directory":
                path = args.get("path", "")
                self.response_chunk.emit(f"📁 `{path.split('\\')[-1] or path}`\n")
            elif name == "read_file":
                path = args.get("path", "")
                self.response_chunk.emit(f"📄 `{path.split('\\')[-1] or path}`\n")
            elif name == "write_file":
                path = args.get("path", "")
                self.response_chunk.emit(f"✏️ Creating `{path.split('\\')[-1] or path}`\n")
            elif name == "edit_file":
                path = args.get("path", "")
                self.response_chunk.emit(f"✏️ Editing `{path.split('\\')[-1] or path}`\n")
            else:
                self.response_chunk.emit(f"⚙️ {name}\n")
            
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
            
            # Minimal tool result - only show important info
            if result.success and name == "list_directory":
                # Show file count instead of full listing
                content = str(result.result)
                file_count = content.count('\n') + 1 if content else 0
                self.response_chunk.emit(f"   → {file_count} items\n")
            elif not result.success:
                # Show error details
                self.response_chunk.emit(f"   ❌ Error: {result.error}\n")
            
            # Append tool result to history
            self._history.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": name,
                "content": str(result.result) if result.success else f"Error: {result.error}"
            })

            # Hand off the file edit to the frontend tracker for the Diff popup
            if name in ["write_file", "edit_file"] and result.success:
                try:
                    new_content = ""
                    path = args.get("path")
                    if path and isinstance(path, str) and os.path.exists(path):
                        with open(path, 'r', encoding='utf-8') as f:
                            new_content = f.read()
                    
                    if path and isinstance(path, str) and original_content != new_content:
                        # Emit signal for the backend Tracker + DiffWindow
                        self.file_edited_diff.emit(path, original_content, new_content)
                        # Emit lightweight tag for the frontend JS to render the "Edited File" card
                        self.response_chunk.emit(f"\n</exploration>\n<file_edited>\n{path}\n</file_edited>\n<exploration>\n")
                except Exception as e:
                    log.error(f"Failed to process file edit diff: {e}")
        
        # Close exploration block
        self.response_chunk.emit("\n</exploration>\n")
        
        # Batch save after all tools are done
        self._save_history_to_disk()
        
        # Trigger next turn
        self.chat(None) # Continue without adding a user message

    def _execute_pending_tools(self):
        """Resume execution of tools that were awaiting confirmation."""
        if not self._pending_tool_calls:
            log.warning("No pending tools to execute")
            return
        
        tools = self._pending_tool_calls[:]
        self._pending_tool_calls = []
        log.info(f"Executing {len(tools)} pending tools after user confirmation")
        
        # Add user confirmation to history
        self._history.append({"role": "user", "content": "yes"})
        
        self._execute_tools(tools)

    def _cancel_pending_tools(self):
        """Cancel the tool calls that were awaiting confirmation."""
        for tc in self._pending_tool_calls:
            self._history.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": tc["function"]["name"],
                "content": "Cancelled by user."
            })
        self._pending_tool_calls = []
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
        self.request_error.emit(error)

    def set_always_allowed(self, allowed: bool):
        """Set whether to always allow tool execution without confirmation"""
        self._always_allowed = allowed
        log.info(f"AI Agent 'Always Allow' set to: {allowed}")
        if allowed:
            self.response_chunk.emit("\n🔓 **Auto-approval enabled** for this chat session. I'll execute file changes without asking.")
        else:
            self.response_chunk.emit("\n🔒 **Auto-approval disabled**. I'll ask for confirmation before making changes.")

    def clear_history(self):
        self._history.clear()

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
