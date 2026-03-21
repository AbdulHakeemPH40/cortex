"""
agent.py - AI Agent
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

                self._results.append({
                    "tool_call_id": tool_call["id"],
                    "name": name,
                    "content": content,
                    "success": result.success,
                    "duration_ms": result.duration_ms
                })

                # Emit completed signal
                self.tool_completed.emit(name, args, result)

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
        provider_map = {
            "deepseek": ProviderType.DEEPSEEK,
            "together": ProviderType.TOGETHER,  # Qwen, Kimi, MiniMax, DeepSeek-R1
        }
        
        # Together AI models (use "together" provider with these model IDs):
        # - Qwen/Qwen3.5-397B-A17B
        # - moonshotai/Kimi-K2.5
        # - MiniMaxAI/MiniMax-M2.5
        # - deepseek-ai/DeepSeek-R1
        
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
        # Exponential backoff for rate limits
        max_retries = 3
        for attempt in range(max_retries):
            try:
                log.info(f"Starting to stream from provider... (attempt {attempt + 1})")
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
                                
                                # Debug: log each delta
                                args_preview = delta.get("function", {}).get("arguments", "")[:50] if delta.get("function", {}).get("arguments") else "EMPTY"
                                log.debug(f"Tool delta: idx={index}, id={delta.get('id')}, name={delta.get('function', {}).get('name')}, args={args_preview}...")
                                
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
                    log.debug(f"Tool call buffer contents: {tool_call_buffer}")
                    final_tool_calls = []
                    for idx in sorted(tool_call_buffer.keys()):
                        tc = tool_call_buffer[idx]
                        # Validate tool call has all required fields including non-empty arguments
                        if tc["id"] and tc["name"]:
                            args = tc["arguments"].strip() if tc["arguments"] else ""
                            # Skip tool calls with empty or invalid arguments
                            if not args or args == "{}" or args == "":
                                log.warning(f"Skipping incomplete tool call {tc['name']}: id={tc['id']}, args='{args[:100] if args else 'EMPTY'}'")
                                continue
                            log.debug(f"Valid tool call: {tc['name']} with args length {len(args)}")
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
                    elif tool_call_buffer:
                        # Some tool calls were skipped due to empty arguments
                        # Add a note to the response so AI knows to retry
                        self._full_response += "\n\n[SYSTEM ERROR: Tool call was rejected because arguments were empty. This is a streaming issue. Please try again and make sure to include the file path and content in your tool call.]\n"
                
                log.info(f"Emitting finished signal with response length {len(self._full_response)}")
                self.finished.emit(self._full_response)
                return  # Success, exit retry loop
            except Exception as e:
                error_msg = str(e)
                if "rate limit" in error_msg.lower() and attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    log.warning(f"Rate limit hit, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
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
    directory_contents = pyqtSignal(str, str)  # path, contents
    thinking_started = pyqtSignal()
    thinking_stopped = pyqtSignal()
    todos_updated = pyqtSignal(list, str)  # todos_list, main_task

    SYSTEM_PROMPT = """# CORTEX AI ASSISTANT — Autonomous IDE Agent

## IDENTITY
You are CORTEX, an intelligent autonomous coding assistant integrated into Cortex IDE.
You operate like a senior software engineer: read before you write, verify after you edit, match the project's existing style.

---

## CRITICAL RULES — MUST FOLLOW ALL

### RULE 1: RESPOND TO WHAT USER ACTUALLY ASKS
- "hi" or greetings → greet back warmly, do NOT list capabilities or create files
- A question → answer it; do NOT assume they want code written
- "create X" / "build X" / "fix X" → THEN take action

### RULE 2: EXPLORE BEFORE ACT (ReAct Pattern)
- ALWAYS `list_directory` on project root on first interaction to understand structure.
- BEFORE EDITING a large file (>200 lines):
  1. `get_file_outline` to find the line numbers of functions/classes.
  2. `read_file` with `start_line` and `end_line` for the relevant section to get current context with line numbers.
- NEVER edit a file you haven't read in this session.
- NEVER hallucinate files, paths, or features.
- NEVER read files inside dependency directories (performance killer) — see EXCLUSION RULES below

  ### RULE 3: THE 10 INDUSTRIAL EDIT RULES (E1-E10)
  - E1 (Explore): NEVER edit without `read_file`. Use `get_file_outline` for files >200 lines.
  - E2 (Precision): Use `edit_file` (find/replace) for most changes. `write_file` is ONLY for new files.
  - E3 (Uniqueness): `old_string` MUST be unique. Include 3+ lines of context if needed.
  - E4 (Boilerplate): Use `add_import` for imports to avoid duplication.
  - E5 (Injection): Use `inject_after` for adding code to existing functions/classes when search-replace is too brittle.
  - E6 (Truncation): Never rewrite 100+ line files. Build them incrementally (skeleton first, then `edit_file`).
  - E7 (Verification): Immediately `read_file` the changed lines after an edit to confirm success.
  - E8 (Style): Match indentation (2 vs 4 spaces) EXACTLY.
  - E9 (Failure): If an edit fails due to multiple matches, look at the line numbers provided in the error. Choose a match and add more context from that specific line to make your `old_string` unique. DO NOT retry with the same parameters.
  - E10 (Atomic): Every tool call MUST be followed by its result before the next  ### RULE 9: TASK MANAGEMENT
  - For complex tasks, ALWAYS use `<tasklist>` with `- [ ]` checkboxes.
  - Mark items `[x]` as you complete them in subsequent turns.
  - This populates the user's progress tracker.

  ### RULE 14: PATH DISCIPLINE — ALWAYS USE PROJECT-RELATIVE PATHS
  - NEVER construct paths by guessing directory names. Always start from the project root provided in the session context.
  - Correct:  `src/main.py`  or  `{project_root}/src/main.py`
  - Wrong:    `C:/Users/SomeOtherFolder/src/main.py`  or  `/home/user/projects/other/main.py`
  - When you receive a PermissionError saying "escapes the project root", it means you used a wrong path. Fix it by using the relative path from the project root.
  - If you are unsure of the correct path, call `list_directory` on the project root first.

  ### RULE 15: STUCK / TIMEOUT RECOVERY
  - If you receive a `TOOL_TIMEOUT` or `[SYSTEM RECOVERY]` message, it means a tool timed out (hung subprocess).
  - Do NOT retry the same timed-out tool immediately.
  - Instead: acknowledge the timeout, check your `<tasklist>`, mark the failed step, and move to the NEXT pending step.
  - If git or shell commands time out repeatedly, inform the user: "Git/shell appears unresponsive. You may need to check the repository manually."

  ### RULE 10: EDIT EXACTNESS (E11)
  - Your `old_string` MUST match the file content exactly, including whitespace, comments, and empty lines.
  - If you aren't 100% sure of the context, `read_file` the specific line range again.
  - Inclusion of line numbers in your thought process helps avoid errors.

  ### RULE 11: TOOL USAGE — REQUIRED PARAMETERS
  - `read_file` → path, start_line, end_line, numbered (bool)
  - `edit_file` → path, old_string, new_string, expected_occurrences
  - `inject_after` → path, anchor, new_code
  - `add_import` → path, import_statement
  - `get_file_outline` → path
  - `undo_last_action` → ()

  ### RULE 12: TASK COMPLETION — MANDATORY SUMMARY
  - End your response with a `<task_summary>` JSON block.

  ### RULE 13: INCREMENTAL DEVELOPMENT (LARGE FILES)
  - Skeleton First → `write_file`
  - Detail Addition → `edit_file` / `inject_after`

```
<tasklist>
- [ ] Task 1
- [ ] Task 2
</tasklist>

<task_summary>
{
  "title": "Brief task description",
  "files": [{"name": "file.py", "path": "/abs/path/file.py", "action": "modified"}],
  "message": "Summary"
}
</task_summary>
```

## EXCLUSION RULES — NEVER ENTER THESE DIRECTORIES

These directories contain framework dependencies, NOT user code. Entering them freezes the terminal and wastes your context window.

### BLOCKED — Python Virtual Environments
- venv/, .venv/, env/, ENV/, virtualenv/ — Python interpreter + packages
- __pycache__/, .eggs/, .tox/, .nox/ — Python cache/build
- .mypy_cache/, .pytest_cache/, .ruff_cache/ — Tool caches
- site-packages/, dist-packages/ — Inside venv

### BLOCKED — Node.js / JavaScript
- node_modules/ — NPM/Yarn packages (50,000–200,000 files!)
- .npm/, .yarn/, .pnpm-store/, .pnp/ — Package manager caches
- .next/, .nuxt/, .svelte-kit/ — Framework build output
- .parcel-cache/, .turbo/, .vercel/ — Bundler caches
- coverage/ — Test coverage reports

### BLOCKED — Flutter / Dart
- .dart_tool/, .pub-cache/ — Dart tooling cache
- .flutter-plugins/ — Plugin list
- build/ — Flutter build output (GBs)
- ios/Pods/, ios/.symlinks/ — CocoaPods (100,000+ files)
- android/.gradle/, android/app/build/ — Gradle cache

### BLOCKED — Java / Kotlin / Android
- .gradle/, build/, out/ — Gradle/IntelliJ output
- .idea/ — IDE config
- *.class, *.jar, *.war — Compiled Java

### BLOCKED — Rust
- target/ — Cargo build output (2–10 GB!)
- .cargo/registry/ — Downloaded crates

### BLOCKED — Go
- vendor/, Godeps/ — Vendored dependencies
- bin/, pkg/ — Compiled binaries

### BLOCKED — iOS / Swift
- Pods/, .cocoapods/ — CocoaPods dependencies
- .build/, DerivedData/ — Swift build output
- *.xcworkspace/, Carthage/ — Generated workspaces

### BLOCKED — Ruby
- vendor/bundle/, .bundle/ — Bundler gems

### BLOCKED — .NET / C#
- bin/, obj/ — Compiled output
- .vs/, packages/ — Visual Studio cache

### BLOCKED — Haskell
- .stack-work/, dist-newstyle/ — Stack build output

### BLOCKED — Elixir
- _build/, deps/, .elixir_ls/ — Build and language server

### BLOCKED — PHP
- vendor/ — Composer packages

### BLOCKED — Version Control & Generic
- .git/objects/, .git/refs/, .svn/, .hg/ — VCS internals
- dist/, build/, .cache/, .tmp/ — Generic build output

### BLOCKED — Binary/File Types
- *.pyc, *.pyo, *.pyd, *.so, *.dylib, *.dll — Compiled Python/libraries
- *.exe, *.bin, *.wasm, *.class, *.jar — Binaries
- *.png, *.jpg, *.gif, *.mp4, *.mp3 — Media files
- *.zip, *.tar, *.gz, *.7z — Archives
- *.min.js, *.min.css, *.map — Minified files

### WHAT YOU SHOULD EXPLORE
✅ Source files: *.py, *.js, *.ts, *.jsx, *.tsx, *.html, *.css
✅ Config files: package.json, pyproject.toml, requirements.txt, Cargo.toml
✅ Documentation: README.md, docs/
✅ Tests: test_*.py, *.test.js, *.spec.ts

If you see a blocked directory in a listing, report: "Found [dirname] — dependency directory, skipping"

Be concise, direct, and responsive. Do what the user asks — no more, no less."""

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
        self._continue_after_tools_flag: bool = False  # Reset on error
        self._check_configuration()
        self._mode = "Agent"  # Default mode
        self._always_allowed = True  # Agent mode has full autonomy by default
        self._warmup_shown = False  # Track if warmup has been shown
        self._context_manager = None  # Will be initialized when project is set
        self._active_file_path = None
        self._cursor_position = None
        self._change_orchestrator = get_change_orchestrator()
        self._pre_edit_snapshots: dict = {}  # Capture file content before edits for diff

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
        
        # Forward terminal output lines to chat as streaming chunks
        if hasattr(terminal_widget, 'terminal_line_for_chat'):
            terminal_widget.terminal_line_for_chat.connect(
                self._on_terminal_line_for_chat
            )

    def set_project_root(self, path: str):
        """Set project root and load project-specific history."""
        # Clear any existing context first to prevent cross-contamination
        self._history.clear()
        self._history_summary = ""
        self._active_file_path = None
        self._cursor_position = None
        self._warmup_shown = False  # Reset for new project
        
        self._project_root = path
        self._tool_registry.project_root = path
        log.info(f"AI Agent context switched to project: {path}")
        
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
        Forward terminal output to aichat.html so the terminal card
        updates in real time instead of showing 'running...' forever.
        Only forward if a tool is currently running.
        """
        if hasattr(self, '_tool_worker') and self._tool_worker and self._tool_worker.isRunning():
            # Wrap in special tag so JS can route it to the terminal card
            self.response_chunk.emit(f"<terminal_output>{line}</terminal_output>")

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
        
        # On first interaction, add instruction to explore project
        if not self._warmup_shown and self._project_root:
            system_content += f"""\n\n## FIRST INTERACTION - EXPLORE PROJECT
This is the first message. Use `list_directory` on '{self._project_root}' to understand the project structure.

IMPORTANT RULES:
1. After exploring, you MUST provide a clear summary to the user including:
   - What type of project this is (e.g., web app, Python package, etc.)
   - Main technologies used
   - Key files and their purposes
   - Current state (what's working, what's incomplete)

2. Do NOT keep reading files indefinitely. After 3-5 key files, STOP and provide your analysis.

3. NEVER explore or read files inside these directories (performance killer):
   # Virtual Environments (ALL frameworks)
   - venv/, .venv/, env/, virtualenv/, ENV/ (Python)
   - node_modules/, .pnpm-store/, .yarn/, .pnp/ (Node.js)
   - vendor/, Godeps/ (Go)
   - target/, .cargo/, Cargo.lock (Rust)
   - .gradle/, build/, out/ (Java/Kotlin/Gradle)
   - bin/, obj/, packages/ (C#/.NET)
   - Pods/, .cocoapods/ (iOS/Swift)
   - .bundle/, vendor/bundle/ (Ruby)
   - .stack-work/, dist-newstyle/ (Haskell)
   - _build/, deps/, .elixir_ls/ (Elixir)
   - .dart_tool/, build/, .packages/ (Dart/Flutter)
   
   # Cache & Build Artifacts
   - __pycache__/, .pytest_cache/, .mypy_cache/, .ruff_cache/ (Python cache)
   - .git/, .svn/, .hg/ (Version control)
   - dist/, build/, .egg-info/, .tox/, .nox/, pip-wheel-metadata/ (Build artifacts)
   - .next/, .nuxt/, .svelte-kit/, .vercel/, .netlify/ (Framework build output)
   - coverage/, .coverage/, htmlcov/, .hypothesis/ (Test coverage)
   
   If you need to check dependencies, ask user for permission first."""
            self._warmup_shown = True
            
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

        # FOR TESTING: Force deepseek if not mock
        provider = self._settings.get("ai", "provider") or "deepseek"
        if provider != "mock":
            provider = "deepseek"
            
        model = self._settings.get("ai", "model") or "deepseek-chat"
        # Ensure deepseek model is used for deepseek provider
        if provider == "deepseek" and "deepseek" not in model.lower():
            model = "deepseek-chat"
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
        provider = get_provider_registry().get_provider(
            ProviderType.TOGETHER if provider_name == "together" else ProviderType.DEEPSEEK
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
        
        # Parse and emit TODOs if present, and clean the text for UI display
        full_text = self._parse_and_emit_todos(full_text)
        
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
                return  # Return early - continuation will be triggered by _on_all_tools_completed
        else:
            self._history.append({"role": "assistant", "content": full_text})
            self.response_complete.emit(full_text)
            
        # Refactor: Save workflow tags to physical files in .cortex/
        self._save_workflow_files(full_text)
        self._save_history_to_disk()

    def _execute_tools(self, tool_calls, assistant_content=""):
        """Execute tool calls in a background thread and then continue the chat.
        
        Args:
            tool_calls: List of tool call objects from the assistant
            assistant_content: The assistant's message content (to be added atomically with tools)
        """
        # Start exploration block for UI display
        self.response_chunk.emit("\n<exploration>\n")
        
        # Create ToolWorker to run tools in background
        self._tool_worker = ToolWorker(self._tool_registry, tool_calls)
        
        # Connect signals
        self._tool_worker.tool_started.connect(self._on_tool_started)
        self._tool_worker.tool_completed.connect(lambda n, a, r: self._on_tool_completed(n, a, r))
        self._tool_worker.all_tools_completed.connect(lambda res: self._on_all_tools_completed(res, tool_calls, assistant_content))
        self._tool_worker.error_occurred.connect(self._on_tool_error)
        self._tool_worker.tool_timeout.connect(self._on_tool_timeout)
        
        self._tool_worker.start()

    def _on_tool_started(self, name, args):
        """Called when a tool starts execution in background."""
        log.info(f"Executing tool: {name} with args: {args}")
        display_path = ""
        if "path" in args:
            path = str(args["path"])
            display_path = path.split('\\')[-1] or path.split('/')[-1] or path
        
        # Capture pre-edit snapshot for diff support
        if name in ["write_file", "edit_file", "inject_after", "add_import"]:
            path = str(args.get("path", ""))
            # Resolve relative path against project root
            snap_path = path
            if path and self._project_root and not os.path.isabs(path):
                snap_path = os.path.join(str(self._project_root), path)
            if snap_path and os.path.exists(snap_path):
                try:
                    from pathlib import Path as _SnapPath
                    self._pre_edit_snapshots[snap_path] = _SnapPath(snap_path).read_text(encoding="utf-8", errors="replace")
                    # Also store under relative key as fallback
                    self._pre_edit_snapshots[path] = self._pre_edit_snapshots[snap_path]
                except Exception:
                    self._pre_edit_snapshots[snap_path] = ""
                    self._pre_edit_snapshots[path] = ""
            
        if name == "run_command":
            self.tool_activity.emit("run_command", args.get("command", "")[:60], "running")
        elif name in ["write_file", "edit_file", "read_file", "delete_path", "list_directory"]:
            self.tool_activity.emit(name, display_path or args.get("path", ""), "running")
        else:
            self.tool_activity.emit(name, str(args)[:50], "running")

    def _on_tool_completed(self, name, args, result):
        """Called when a single tool finishes in background."""
        display_path = ""
        if "path" in args:
            path = str(args["path"])
            display_path = path.split('\\')[-1] or path.split('/')[-1] or path

        if result.success:
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
            elif name in ["write_file", "edit_file", "inject_after", "add_import"]:
                try:
                    res_obj = json.loads(result.result) if isinstance(result.result, str) else result.result
                    added = res_obj.get("added_lines", 0)
                    removed = res_obj.get("removed_lines", 0)
                except:
                    added, removed = 0, 0

                # ── Resolve absolute path (tool args often give relative paths) ──
                from pathlib import Path as _Path
                resolved_path = path
                if self._project_root and not os.path.isabs(path):
                    resolved_path = os.path.join(str(self._project_root), path)

                # ── Get original content (try both relative & absolute key) ─────
                original_content = (self._pre_edit_snapshots.get(resolved_path, '') or
                                    self._pre_edit_snapshots.get(path, ''))
                edit_type = 'C' if not original_content else 'M'

                # ── Get new file content (from args first, then disk) ─────────
                new_file_content = str(args.get("content", "") or "")
                if not new_file_content and os.path.exists(resolved_path):
                    try:
                        new_file_content = _Path(resolved_path).read_text(encoding="utf-8", errors="replace")
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

                # Emit <file_edited> tag using RESOLVED (absolute) path so JS
                # storeDiffData key matches renderCustomTagsInto lookup key
                self.response_chunk.emit(
                    f"\n<file_edited>\n{resolved_path}\n+{added} -{removed}\n{edit_type}\n</file_edited>\n"
                )

                # Emit file_edited_diff signal for diff viewer overlay
                try:
                    if new_file_content and hasattr(self, 'file_edited_diff'):
                        original_snap = (self._pre_edit_snapshots.pop(resolved_path, '') or
                                         self._pre_edit_snapshots.pop(path, ''))
                        self.file_edited_diff.emit(resolved_path, original_snap, new_file_content)
                        log.debug(f"Emitted file_edited_diff for {resolved_path}")
                except Exception as _e:
                    log.warning(f"Could not emit file_edited_diff: {_e}")
            else:
                self.tool_activity.emit(name, "Completed", "complete")
        else:
            self.tool_activity.emit(name, f"Error: {result.error[:40]}", "error")
            self.response_chunk.emit(f"\n⚠️ Error calling {name}: {result.error}\n")

    def _on_all_tools_completed(self, results, original_tool_calls, assistant_content):
        """Called when ALL tools in the batch are finished."""
        log.info(f"All {len(results)} tools completed")
        self.response_chunk.emit("\n</exploration>\n")
        self.thinking_stopped.emit()  # Hide spinner after tool execution
        
        # Add assistant message and tool responses to history
        self._history.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": original_tool_calls
        })
        
        for res in results:
            tool_json = json.dumps({
                "success": res["success"],
                "output": str(res["content"]) if res["success"] else None,
                "error": str(res["content"]) if not res["success"] else None,
                "duration_ms": res.get("duration_ms", 0)
            })
            self._history.append({
                "role": "tool",
                "tool_call_id": res["tool_call_id"],
                "name": res["name"],
                "content": tool_json
            })
            
        self._save_history_to_disk()
        self._continue_after_tools_flag = True
        self.response_complete.emit("")
        
        # Trigger continuation
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self._continue_chat_after_tools)

    def _on_tool_error(self, error_msg):
        """Handle fatal error in ToolWorker."""
        log.error(f"ToolWorker fatal error: {error_msg}")
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
        # Reset flags on error
        self._continue_after_tools_flag = False
        # Stop thinking indicator
        self.thinking_stopped.emit()
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

    def _parse_and_emit_todos(self, text: str) -> str:
        """Parse TODO items from response text, emit to UI, and return cleaned text."""
        import re
        
        todos = []
        main_task = ""
        cleaned_text = text
        
        # 1. Try to find a <tasklist> section first
        tasklist_match = re.search(r'<tasklist>(.*?)</tasklist>', text, re.DOTALL)
        content_to_parse = tasklist_match.group(1) if tasklist_match else text
        
        # 2. Global search for [ ] or [x] items
        # Matches "- [ ] Task" or "* [x] Task" or "1. [ ] Task"
        # Relaxed regex to allow hyphens and other chars in content
        task_pattern = r'\[([ xX])\]\s*([^\[\n<]+)'
        
        matches = list(re.finditer(task_pattern, content_to_parse))
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
