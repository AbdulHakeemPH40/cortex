import os
import sys
import json
import platform
import shutil
import re
import difflib
import hashlib
import threading
import time
import requests
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QObject, pyqtSlot, QProcess, QProcessEnvironment, QTimer, QThread, QMutex
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from src.utils.logger import get_logger
from src.utils.image_processing import (
    process_images_for_api,
    validate_images_for_api,
    build_vision_messages,
    compress_image,
    IMAGE_MAX_WIDTH,
    IMAGE_MAX_HEIGHT,
    MAX_IMAGES_PER_MESSAGE,
)
from src.utils.agent_tools import (
    AgentType,
    AgentLifecycleManager,
    classify_task_type,
    should_use_parallel,
    build_worker_system_prompt,
)

from src.utils.icons import make_icon
from src.config.points_manager import get_points_manager, InsufficientPointsError

log = get_logger("ai_chat")

# Per-conversation throttling for background chat summary generation.
_CHAT_SUMMARY_LOCK = threading.Lock()
_CHAT_SUMMARY_IN_FLIGHT = set()  # conversation_id strings currently summarizing
_CHAT_SUMMARY_LAST_TS = {}       # conversation_id -> last run epoch seconds
_CHAT_SUMMARY_LAST_MSG_COUNT = {}  # conversation_id -> last msg count summarized


class PerformanceMode(Enum):
    """Performance modes for AI Chat."""
    EFFICIENT = "efficient"      # 0.3x - Power saving
    AUTO = "auto"                # 1.0x - Balanced
    PERFORMANCE = "performance"  # 1.1x - Multi-agent
    ULTIMATE = "ultimate"        # 1.6x - Max multi-agent


@dataclass
class PerformanceConfig:
    """Configuration for each performance mode.
    
    ARCHITECTURE: Mistral is the ONLY provider.
    
    Mode hierarchy:
    - Efficient: Mistral Small (text) / Medium (vision)
    - Auto: Mistral Small/Medium/Large (auto-select based on query)
    - Performance: Mistral Medium
    - Ultimate: Mistral Large
    """
    temperature: float
    multi_agent: bool
    parallel_workers: int
    vision_enabled: bool
    description: str
    token_multiplier: float  # Multiplier for model's max_output_tokens
    vision_model: str  # Mistral model for vision
    main_agent_model: str  # Main Mistral model


PERFORMANCE_CONFIGS = {
    PerformanceMode.EFFICIENT: PerformanceConfig(
        temperature=0.3,
        multi_agent=False,
        parallel_workers=0,
        vision_enabled=True,
        description="Power saving - Mistral Small (text) / Medium (vision)",
        token_multiplier=0.3,
        vision_model="mistral-medium-latest",
        main_agent_model="mistral-small-latest",
    ),
    PerformanceMode.AUTO: PerformanceConfig(
        temperature=0.7,
        multi_agent=False,
        parallel_workers=0,
        vision_enabled=True,
        description="Smart routing - Mistral auto-select based on query",
        token_multiplier=1.0,
        vision_model="mistral-medium-latest",
        main_agent_model="mistral-small-latest",  # Default, auto-upgraded based on query
    ),
    PerformanceMode.PERFORMANCE: PerformanceConfig(
        temperature=0.7,
        multi_agent=False,
        parallel_workers=0,
        vision_enabled=True,
        description="Balanced - Mistral Medium",
        token_multiplier=1.1,
        vision_model="mistral-medium-latest",
        main_agent_model="mistral-medium-latest",
    ),
    PerformanceMode.ULTIMATE: PerformanceConfig(
        temperature=0.8,
        multi_agent=False,
        parallel_workers=0,
        vision_enabled=True,
        description="Best quality - Mistral Large",
        token_multiplier=1.6,
        vision_model="mistral-large-latest",
        main_agent_model="mistral-large-latest",
    ),
}


def get_performance_mode(mode_str: str) -> PerformanceMode:
    """Convert string to PerformanceMode enum."""
    mode_map = {
        "efficient": PerformanceMode.EFFICIENT,
        "auto": PerformanceMode.AUTO,
        "performance": PerformanceMode.PERFORMANCE,
        "ultimate": PerformanceMode.ULTIMATE,
    }
    return mode_map.get(mode_str.lower(), PerformanceMode.AUTO)


def get_mode_config(mode: PerformanceMode) -> PerformanceConfig:
    """Get configuration for performance mode."""
    return PERFORMANCE_CONFIGS[mode]


def calculate_max_tokens_for_mode(model_id: str, config: PerformanceConfig) -> int:
    """Calculate max_tokens based on model_limits and performance mode multiplier.
    
    Uses the existing model_limits.py system to get the model's max_output_tokens,
    then applies the performance mode's token_multiplier.
    
    Args:
        model_id: Model identifier (e.g., 'deepseek-chat', 'mistral-large')
        config: PerformanceConfig with token_multiplier
    
    Returns:
        Calculated max_tokens for this mode and model
    """
    try:
        from src.ai.model_limits import get_model_limits
        
        # Get model's base max_output_tokens from model_limits
        limits = get_model_limits(model_id)
        base_tokens = limits.max_output_tokens
        
        # Apply performance mode multiplier
        adjusted_tokens = int(base_tokens * config.token_multiplier)
        
        log.debug(f"[AIChat] Token calculation: {model_id} base={base_tokens}, "
                  f"multiplier={config.token_multiplier}, adjusted={adjusted_tokens}")
        
        return adjusted_tokens
        
    except Exception as e:
        log.warning(f"[AIChat] Failed to calculate max_tokens: {e}, using default 4000")
        return 4000

def _compute_project_memory_dir(project_root: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\0]', "_", (project_root or os.getcwd())).strip("_ ")
    if len(sanitized) > 60:
        digest = hashlib.md5((project_root or "").encode("utf-8")).hexdigest()[:8]
        sanitized = sanitized[-52:].lstrip("_") + "_" + digest
    return os.path.join(os.path.expanduser("~"), ".cortex", "projects", sanitized, "memory")


def _ensure_memory_index(memory_dir: str) -> str:
    os.makedirs(memory_dir, exist_ok=True)
    entrypoint = os.path.join(memory_dir, "MEMORY.md")
    if not os.path.exists(entrypoint):
        Path(entrypoint).write_text("# Cortex Memory\n\n", encoding="utf-8")
    return entrypoint


def _append_index_link(entrypoint: str, rel_path: str, title: str) -> None:
    rel_path = (rel_path or "").replace("\\", "/")
    line = f"- [{title}]({rel_path})\n"
    try:
        existing = ""
        if os.path.exists(entrypoint):
            existing = Path(entrypoint).read_text(encoding="utf-8", errors="ignore")
        if rel_path and rel_path in existing:
            return
        with open(entrypoint, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(line)
    except Exception:
        pass


def _maybe_schedule_chat_summary(project_root: str, conversation_id: str, title: str, messages: list, ui_widget=None) -> None:
    try:
        from src.config.settings import get_settings

        settings = get_settings()
        if not settings.get("memory", "enabled", default=True):
            return
        if not settings.get("memory", "auto_chat_summary", default=True):
            return

        # Only summarize after an assistant response is saved. If we summarize on
        # every user-message save, it can trigger an extra LLM request exactly
        # when the user hits Send (competes with the main chat request).
        if not messages:
            return
        last_role = (messages[-1].get("role") or messages[-1].get("sender") or "").strip().lower()
        if last_role not in ("assistant", "ai"):
            return

        # Avoid running summaries too frequently for the same conversation.
        # Once a chat is "long enough" to qualify, it may be saved many times
        # (every message). Without throttling this can trigger repeated LLM calls
        # that compete with primary chat requests and slow the overall UX.
        min_interval_s = int(settings.get("memory", "auto_chat_summary_min_interval_s", default=600) or 600)
        min_new_messages = int(settings.get("memory", "auto_chat_summary_min_new_messages", default=8) or 8)

        min_chars = int(settings.get("memory", "auto_chat_summary_min_chars", default=12000) or 12000)
        min_msgs = int(settings.get("memory", "auto_chat_summary_min_messages", default=24) or 24)
        flat = " ".join((m.get("content") or m.get("text") or "") for m in (messages or []))
        if len(messages or []) < min_msgs and len(flat) < min_chars:
            return

        # Throttle per-conversation execution.
        now = time.time()
        msg_count = len(messages or [])
        with _CHAT_SUMMARY_LOCK:
            if conversation_id in _CHAT_SUMMARY_IN_FLIGHT:
                return
            last_ts = _CHAT_SUMMARY_LAST_TS.get(conversation_id, 0.0)
            last_count = _CHAT_SUMMARY_LAST_MSG_COUNT.get(conversation_id, 0)
            if (now - last_ts) < min_interval_s and (msg_count - last_count) < min_new_messages:
                return
            _CHAT_SUMMARY_IN_FLIGHT.add(conversation_id)

        def _runner():
            try:
                # Notify UI: Memory save started
                if ui_widget:
                    from PyQt6.QtCore import QMetaObject, Qt
                    QMetaObject.invokeMethod(
                        ui_widget,
                        "show_memory_saving_animation",
                        Qt.ConnectionType.QueuedConnection,
                    )
                
                _write_chat_summary_memory(project_root, conversation_id, title, messages)
                
                # Notify UI: Memory save completed
                if ui_widget:
                    QMetaObject.invokeMethod(
                        ui_widget,
                        "show_memory_saved_confirmation",
                        Qt.ConnectionType.QueuedConnection,
                        "Session summary saved",
                    )
            except Exception as e:
                log.error(f"[MEMORY] CRITICAL: Chat summary thread failed: {e}", exc_info=True)
                # Notify UI: Memory save failed
                if ui_widget:
                    QMetaObject.invokeMethod(
                        ui_widget,
                        "hide_memory_saving_animation",
                        Qt.ConnectionType.QueuedConnection,
                    )
            finally:
                with _CHAT_SUMMARY_LOCK:
                    _CHAT_SUMMARY_IN_FLIGHT.discard(conversation_id)
                    _CHAT_SUMMARY_LAST_TS[conversation_id] = time.time()
                    _CHAT_SUMMARY_LAST_MSG_COUNT[conversation_id] = msg_count

        threading.Thread(target=_runner, daemon=True).start()
    except Exception:
        return


def _write_chat_summary_memory(project_root: str, conversation_id: str, title: str, messages: list, retry_count: int = 0) -> None:
    """
    Summarize long chats into a stable, project-scoped memory file.
    Runs in a background thread to avoid blocking the UI.
    
    Enhanced with:
    - Retry logic for transient failures (max 2 retries)
    - Backup mechanism to prevent data loss
    - Detailed error categorization
    - Graceful degradation on provider failures
    """
    max_retries = 2
    
    try:
        from src.config.settings import get_settings
        from src.ai.providers import ChatMessage, ProviderType, get_provider_registry

        settings = get_settings()
        provider_name = (settings.get("ai", "provider") or "mistral").strip().lower()
        model_id = (settings.get("ai", "model") or "mistral-large-latest").strip()

        provider_map = {
            "mistral": ProviderType.MISTRAL,
            "siliconflow": ProviderType.SILICONFLOW,
        }
        provider_type = provider_map.get(provider_name, ProviderType.MISTRAL)
        
        # Validate provider availability
        try:
            provider = get_provider_registry().get_provider(provider_type)
            if not provider:
                raise ValueError(f"Provider '{provider_name}' not available in registry")
        except Exception as e:
            log.error(f"[MEMORY] Provider initialization failed: {e}")
            if retry_count < max_retries:
                log.info(f"[MEMORY] Retrying in 5s (attempt {retry_count + 1}/{max_retries})")
                import time as time_module
                time_module.sleep(5)
                _write_chat_summary_memory(project_root, conversation_id, title, messages, retry_count + 1)
            return

        # Validate messages
        if not messages or len(messages) == 0:
            log.warning("[MEMORY] No messages to summarize")
            return

        trimmed = (messages or [])[-40:]
        transcript_lines = []
        for msg in trimmed:
            role = (msg.get("role") or msg.get("sender") or "user").strip()
            content = (msg.get("content") or msg.get("text") or "").strip()
            if not content:
                continue
            if len(content) > 700:
                content = content[:700] + "…"
            transcript_lines.append(f"{role.upper()}: {content}")
        transcript = "\n".join(transcript_lines)
        
        if not transcript:
            log.warning("[MEMORY] No valid transcript content after filtering")
            return

        system = (
            "You are converting a long coding chat into a persistent memory file for an IDE.\n"
            "Output MUST be Markdown with YAML frontmatter, exactly like:\n"
            "---\n"
            "name: \"...\"\n"
            "description: \"comma,separated,keywords\"\n"
            "type: \"project\"\n"
            "---\n"
            "Then write concise bullet points useful in future sessions.\n"
            "Avoid personal data. Avoid transient steps. Prefer stable decisions, preferences, constraints, and project facts.\n"
        )
        user = (
            f"Chat title: {title}\n"
            f"Conversation id: {conversation_id}\n\n"
            "Transcript (most recent messages):\n"
            f"{transcript}\n"
        )

        # Call LLM provider with timeout handling
        try:
            resp = provider.chat(
                messages=[
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user),
                ],
                model=model_id,
                temperature=0.2,
                max_tokens=900,
                stream=False,
            )
        except Exception as e:
            error_msg = str(e).lower()
            is_transient = any(keyword in error_msg for keyword in [
                'timeout', 'connection', 'rate limit', '503', '502', '504', 'temporary'
            ])
            
            if is_transient and retry_count < max_retries:
                wait_time = 5 * (retry_count + 1)  # Exponential backoff: 5s, 10s
                log.warning(f"[MEMORY] Transient LLM error ({e}), retrying in {wait_time}s (attempt {retry_count + 1}/{max_retries})")
                import time as time_module
                time_module.sleep(wait_time)
                _write_chat_summary_memory(project_root, conversation_id, title, messages, retry_count + 1)
                return
            else:
                log.error(f"[MEMORY] LLM chat failed after {retry_count + 1} attempts: {e}")
                _save_fallback_summary(project_root, conversation_id, title, messages)
                return
        
        content = (resp.content or "").strip()
        if not content:
            log.warning("[MEMORY] LLM returned empty content")
            _save_fallback_summary(project_root, conversation_id, title, messages)
            return

        # Validate and fix frontmatter
        if not content.startswith("---"):
            log.warning("[MEMORY] LLM response missing frontmatter, adding fallback")
            now = datetime.utcnow().strftime("%Y-%m-%d")
            safe_title = (title or conversation_id[:8]).replace('"', "'")
            content = (
                "---\n"
                f"name: \"Chat Summary: {safe_title}\"\n"
                f"description: \"chat,summary,{now}\"\n"
                "type: \"project\"\n"
                "---\n\n"
                + content
            )

        # Save to memory directory with error handling
        try:
            memory_dir = _compute_project_memory_dir(project_root)
            auto_dir = os.path.join(memory_dir, "auto", "chat_summaries")
            os.makedirs(auto_dir, exist_ok=True)
            out_path = os.path.join(auto_dir, f"{conversation_id}.md")
            
            # Create backup before overwriting
            if os.path.exists(out_path):
                backup_path = out_path + ".backup"
                try:
                    import shutil
                    shutil.copy2(out_path, backup_path)
                except Exception as backup_err:
                    log.warning(f"[MEMORY] Failed to create backup: {backup_err}")
            
            Path(out_path).write_text(content, encoding="utf-8")
            
            # Verify write succeeded
            if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                raise IOError(f"File write verification failed: {out_path}")

            entrypoint = _ensure_memory_index(memory_dir)
            rel = os.path.relpath(out_path, memory_dir).replace("\\", "/")
            label = f"Chat summary: {title or conversation_id[:8]}"
            _append_index_link(entrypoint, rel, label)
            log.info(f"[MEMORY] ✅ Auto-saved chat summary to {out_path} ({len(content)} chars)")
            
            # Clean up backup if successful
            backup_path = out_path + ".backup"
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except Exception:
                    pass
                    
        except IOError as e:
            log.error(f"[MEMORY] File I/O error: {e}")
            _save_emergency_backup(project_root, conversation_id, title, content)
        except Exception as e:
            log.error(f"[MEMORY] Unexpected error saving memory: {e}", exc_info=True)
            _save_emergency_backup(project_root, conversation_id, title, content)
            
    except ImportError as e:
        log.error(f"[MEMORY] Import error (missing dependency): {e}")
    except Exception as e:
        log.error(f"[MEMORY] CRITICAL: Unexpected error in chat summary: {e}", exc_info=True)
        if retry_count < max_retries:
            log.info(f"[MEMORY] Retrying after critical error (attempt {retry_count + 1}/{max_retries})")
            import time as time_module
            time_module.sleep(3)
            _write_chat_summary_memory(project_root, conversation_id, title, messages, retry_count + 1)


def _save_fallback_summary(project_root: str, conversation_id: str, title: str, messages: list) -> None:
    """Save a basic fallback summary when LLM fails."""
    try:
        memory_dir = _compute_project_memory_dir(project_root)
        auto_dir = os.path.join(memory_dir, "auto", "chat_summaries")
        os.makedirs(auto_dir, exist_ok=True)
        out_path = os.path.join(auto_dir, f"{conversation_id}.md")
        
        # Create simple summary from message metadata
        msg_count = len(messages)
        roles = {}
        for msg in messages:
            role = (msg.get("role") or msg.get("sender") or "unknown").lower()
            roles[role] = roles.get(role, 0) + 1
        
        fallback_content = (
            f"---\n"
            f"name: \"Chat Summary: {title or conversation_id[:8]}\"\n"
            f"description: \"chat,summary,fallback,{datetime.utcnow().strftime('%Y-%m-%d')}\"\n"
            "type: \"project\"\n"
            "---\n\n"
            f"## Auto-Generated Summary (Fallback)\n\n"
            f"**Note:** LLM summarization failed, saving metadata only.\n\n"
            f"- **Conversation ID:** {conversation_id}\n"
            f"- **Title:** {title or 'Untitled'}\n"
            f"- **Total Messages:** {msg_count}\n"
            f"- **Message Breakdown:** {', '.join(f'{k}: {v}' for k, v in roles.items())}\n"
            f"- **Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"## Recent Topics\n\n"
        )
        
        # Extract key topics from last 10 messages
        recent_msgs = messages[-10:]
        topics = []
        for msg in recent_msgs:
            content = (msg.get("content") or msg.get("text") or "").strip()
            if len(content) > 50:
                # Extract first sentence or 100 chars
                first_sentence = content.split('.')[0][:100]
                if first_sentence:
                    topics.append(f"- {first_sentence}")
        
        fallback_content += "\n".join(topics[:5]) if topics else "- No extractable topics"
        
        Path(out_path).write_text(fallback_content, encoding="utf-8")
        log.warning(f"[MEMORY] ⚠️ Saved fallback summary (LLM failed): {out_path}")
        
    except Exception as e:
        log.error(f"[MEMORY] Failed to save fallback summary: {e}")


def _save_emergency_backup(project_root: str, conversation_id: str, title: str, content: str) -> None:
    """Emergency backup when normal save fails."""
    try:
        emergency_dir = os.path.join(os.path.expanduser("~"), ".cortex", "emergency_backups", "memory")
        os.makedirs(emergency_dir, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(emergency_dir, f"{conversation_id}_{timestamp}.md")
        
        Path(backup_path).write_text(content, encoding="utf-8")
        log.critical(f"[MEMORY] 🚨 Emergency backup saved: {backup_path}")
        
    except Exception as e:
        log.critical(f"[MEMORY] 💥 CRITICAL: Even emergency backup failed: {e}")


class VisionWorker(QObject):
    """Worker for processing vision requests in background thread."""
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, task: Callable):
        super().__init__()
        self._task = task
    
    def run(self):
        try:
            self._task()
        except Exception as e:
            self.error_occurred.emit(str(e))


class FileSearchWorker(QThread):
    """Background worker for file search to avoid blocking UI."""
    results_ready = pyqtSignal(list)
    
    def __init__(self, project_root: str, query: str, max_results: int = 10):
        super().__init__()
        self._project_root = project_root
        self._query = query
        self._max_results = max_results
    
    def run(self):
        try:
            results = []
            count = 0
            for root, dirs, files in os.walk(self._project_root):
                if '.git' in dirs: dirs.remove('.git')
                if 'node_modules' in dirs: dirs.remove('node_modules')
                if '__pycache__' in dirs: dirs.remove('__pycache__')
                if 'venv' in dirs: dirs.remove('venv')
                if '.venv' in dirs: dirs.remove('.venv')
                
                for file in files:
                    if self._query.lower() in file.lower():
                        rel_path = os.path.relpath(os.path.join(root, file), self._project_root)
                        results.append(rel_path.replace("\\", "/"))
                        count += 1
                        if count >= self._max_results:
                            self.results_ready.emit(results)
                            return
                if count >= self._max_results:
                    break
            
            self.results_ready.emit(results)
        except Exception as e:
            log.error(f"FileSearchWorker error: {e}")
            self.results_ready.emit([])


class ChatBridge(QObject):
    """Bridge for communication between JS and Python."""
    def __init__(self, view, parent_widget=None):
        super().__init__()
        self._view = view
        self._parent_widget = parent_widget  # Reference to AIChatWidget for accessing _current_project_path
    message_submitted = pyqtSignal(str)
    message_with_images = pyqtSignal(str, str)  # text, image_data_json
    clear_chat_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    run_command_requested = pyqtSignal(str)
    proceed_requested = pyqtSignal()
    generate_plan_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    always_allow_changed = pyqtSignal(bool)
    model_changed = pyqtSignal(str, str, str)  # model_id, perf, cost
    
    open_file_requested = pyqtSignal(str)
    open_file_at_line_requested = pyqtSignal(str, int)  # file_path, line number
    show_diff_requested = pyqtSignal(str)
    accept_file_edit_requested = pyqtSignal(str)  # file_path
    reject_file_edit_requested = pyqtSignal(str)  # file_path
    
    # Terminal Signals
    terminal_input = pyqtSignal(str)
    terminal_output = pyqtSignal(str)
    terminal_resize = pyqtSignal(int, int)
    open_terminal_requested = pyqtSignal()  # Request to open terminal panel
    run_in_terminal_requested = pyqtSignal(str)  # Request to open terminal and run command
    navigate_to_line = pyqtSignal(str, int)  # file_path, line_number
    
    # Smart paste signal
    smart_paste_check_requested = pyqtSignal(str)  # pasted_text
    search_files_requested = pyqtSignal(str)       # @ mention file search
    
    # Vision response signal
    _vision_response_received = pyqtSignal(str)  # response text
    
    # Chat persistence signals
    save_chats_requested = pyqtSignal(str, str)  # storage_key, json_data
    load_chats_requested = pyqtSignal(str)       # storage_key
    chat_list_updated = pyqtSignal()              # Emitted when chat list changes
    chat_list_updated_with_data = pyqtSignal(str) # Emitted with chat list JSON data
    load_full_chat_requested = pyqtSignal(str)   # conversation_id (lazy load full chat)
    save_finished = pyqtSignal(str)              # status
    
    # Permission system signal (NEW!)
    on_permission_response = pyqtSignal(bool, bool)  # approved, remember
    answer_question_requested = pyqtSignal(str, str) # tool_call_id, answer
    
    # NEW: Permission response from chat UI (OpenCode enhancement)
    permission_response = pyqtSignal(str, bool, str, bool)  # request_id, approved, scope, remember
    
    # Code Completion signals (OpenCode-style)
    code_completion_requested = pyqtSignal(dict)  # {code, language, cursorPosition}
    
    # Todo Management signals
    toggle_todo_requested = pyqtSignal(str, bool)  # task_id, completed
    code_completion_selected = pyqtSignal(dict)   # {requestId, index, completion}
    code_completion_accepted = pyqtSignal(dict)   # {requestId, completedCode}
    code_completion_dismissed = pyqtSignal(dict)  # {requestId}
    
    # Inline Diff Viewer signals (OpenCode-style)
    diff_line_accepted = pyqtSignal(dict)   # {filePath, lineNumber}
    diff_line_rejected = pyqtSignal(dict)   # {filePath, lineNumber}
    diff_line_commented = pyqtSignal(dict)  # {filePath, lineNumber, comment}
    
    @pyqtSlot(str, str, str)
    def on_model_changed(self, model_id, perf, cost):
        self.model_changed.emit(model_id, perf, cost)
    
    @pyqtSlot(str)
    def on_message_submitted(self, text):
        self.message_submitted.emit(text)
    
    @pyqtSlot(str, str)
    def on_message_with_images(self, text, image_data):
        self.message_with_images.emit(text, image_data)
        
    @pyqtSlot()
    def on_clear_chat(self):
        self.clear_chat_requested.emit()

    @pyqtSlot(str)
    def on_run_command(self, command):
        self.run_command_requested.emit(command)

    @pyqtSlot()
    def on_stop(self):
        self.stop_requested.emit()

    @pyqtSlot(str)
    def on_terminal_input(self, data):
        self.terminal_input.emit(data)

    @pyqtSlot(int, int)
    def on_terminal_resize(self, cols, rows):
        self.terminal_resize.emit(cols, rows)

    @pyqtSlot()
    def on_proceed_requested(self):
        self.proceed_requested.emit()

    @pyqtSlot(bool)
    def on_always_allow_changed(self, allowed):
        self.always_allow_changed.emit(allowed)

    @pyqtSlot()
    def on_generate_plan(self):
        self.generate_plan_requested.emit()

    @pyqtSlot(str)
    def on_mode_changed(self, mode):
        self.mode_changed.emit(mode)

    @pyqtSlot(str)
    def on_open_file(self, file_path):
        self.open_file_requested.emit(file_path)

    @pyqtSlot(str, int)
    def on_open_file_at_line(self, file_path, line_number):
        """Open file at specific line number."""
        self.open_file_at_line_requested.emit(file_path, line_number)

    def show_question(self, question_info: dict):
        """Send a question to the JS chat UI for user response."""
        # Ensure all required fields are present
        normalized_info = {
            "id": question_info.get("id", str(_uuid.uuid4())),
            "text": question_info.get("text", ""),
            "type": question_info.get("type", "text"),
            "choices": question_info.get("choices", []),
            "default": question_info.get("default", ""),
            "details": question_info.get("details", ""),
            "scope": question_info.get("scope", "user"),
            "tool_name": question_info.get("tool_name", "AskUserQuestion")
        }
        js_data = json.dumps(normalized_info)
        self._view.page().runJavaScript(f"if(window.showQuestionCard) window.showQuestionCard({js_data});")

    @pyqtSlot(str, str)
    def on_answer_question(self, id, answer):
        """User answered a pending question from the AI."""
        self.answer_question_requested.emit(id, answer)

    @pyqtSlot(str)
    def on_show_diff(self, file_path):
        log.info(f"[Diff-Debug] on_show_diff called with: {file_path}")
        log.info(f"[Diff-Debug] show_diff_requested signal exists: {hasattr(self, 'show_diff_requested')}")
        self.show_diff_requested.emit(file_path)
        log.info(f"[Diff-Debug] show_diff_requested.emit() called")

    @pyqtSlot(str)
    def on_request_diff_data(self, file_path):
        """Request diff data for a file - called when JS needs diff content."""
        log.debug(f"Diff data requested for: {file_path}")
        # Emit signal to main_window to provide diff data
        self.show_diff_requested.emit(file_path)

    @pyqtSlot(str)
    def on_check_smart_paste(self, pasted_text):
        """Check if pasted text matches current editor selection."""
        self.smart_paste_check_requested.emit(pasted_text)
    
    @pyqtSlot()
    def on_toggle_autogen(self):
        """Toggle AutoGen multi-agent mode."""
        # Emit signal to main_window to handle AutoGen toggle
        # The actual multi-agent logic is handled by the performance mode system
        self.toggle_autogen_requested.emit()
    
    # Add new signal for AutoGen toggle
    toggle_autogen_requested = pyqtSignal()

    @pyqtSlot(bool)
    def handle_permission_response(self, allowed):
        """Handle permission response from JS (Allow/Deny tool execution)."""
        # Emit proceed signal if allowed, otherwise just log
        if allowed:
            self.proceed_requested.emit()
        else:
            log.info("User denied tool execution permission")

    @pyqtSlot(str, bool, str, bool)
    def on_permission_card_response(self, request_id: str, approved: bool, scope: str, remember: bool = False):
        """Handle permission card response from JS (OpenCode enhancement)."""
        log.info(f"Permission card response: {request_id} - approved={approved}, scope={scope}, remember={remember}")
        self.permission_response.emit(request_id, approved, scope, remember)

    # â”€â”€ CODE COMPLETION SLOTS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    @pyqtSlot(dict)
    def on_request_code_completion(self, data: dict):
        """Handle code completion request from JS."""
        log.info(f"Code completion requested for {data.get('language', 'python')}")
        self.code_completion_requested.emit(data)
    
    @pyqtSlot(dict)
    def on_code_completion_selected(self, data: dict):
        """Handle code completion selection from JS."""
        log.info(f"Code completion selected: {data.get('index', 0)}")
        self.code_completion_selected.emit(data)
    
    @pyqtSlot(dict)
    def on_code_completion_accepted(self, data: dict):
        """Handle code completion acceptance from JS."""
        log.info(f"Code completion accepted: {data.get('requestId', 'unknown')}")
        self.code_completion_accepted.emit(data)
    
    @pyqtSlot(dict)
    def on_code_completion_dismissed(self, data: dict):
        """Handle code completion dismissal from JS."""
        log.info(f"Code completion dismissed: {data.get('requestId', 'unknown')}")
        self.code_completion_dismissed.emit(data)
    
    # â”€â”€ INLINE DIFF VIEWER SLOTS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    @pyqtSlot(dict)
    def on_diff_line_accepted(self, data: dict):
        """Handle diff line acceptance from JS."""
        log.info(f"Diff line accepted: {data.get('filePath')}:{data.get('lineNumber')}")
        self.diff_line_accepted.emit(data)
    
    @pyqtSlot(dict)
    def on_diff_line_rejected(self, data: dict):
        """Handle diff line rejection from JS."""
        log.info(f"Diff line rejected: {data.get('filePath')}:{data.get('lineNumber')}")
        self.diff_line_rejected.emit(data)
    
    @pyqtSlot(dict)
    def on_diff_line_commented(self, data: dict):
        """Handle diff line comment from JS."""
        log.info(f"Diff line commented: {data.get('filePath')}:{data.get('lineNumber')}")
        self.diff_line_commented.emit(data)

    # â”€â”€ ENHANCEMENT GUIDE: Missing Bridge Slots â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @pyqtSlot(str, bool)
    def on_toggle_todo(self, task_id: str, completed: bool):
        """User toggled a todo item in the UI."""
        log.info(f"Todo toggled: {task_id} -> {'completed' if completed else 'pending'}")
        self.toggle_todo_requested.emit(task_id, completed)

    @pyqtSlot()
    def on_stop_generation(self):
        """Stop AI generation â€” called from Escape key or stop button in JS."""
        self.stop_requested.emit()

    @pyqtSlot(str)
    def on_search_files(self, query: str):
        """Search project files for @ mention autocomplete."""
        # Emit a signal so AIChatWidget can handle the view.runJavaScript call
        self.search_files_requested.emit(query)

    @pyqtSlot(str)
    def on_add_context_file(self, file_path: str):
        """Add a file to the AI context for this turn."""
        log.info(f'Context file added: {file_path}')
        # Will be picked up by agent's context manager on next message

    @pyqtSlot(str)
    def on_accept_file_edit(self, file_path: str):
        """User accepted a file edit from the card UI."""
        log.info(f'File edit accepted: {file_path}')
        # Only emit accept signal — main_window handler opens the file
        self.accept_file_edit_requested.emit(file_path)
    
    # ========== PERMISSION DIALOG BRIDGE (NEW) ==========
    
    # Signal to request permission from user
    permission_requested = pyqtSignal(str, str, object)  # tool_name, details_html, callback
    
    @pyqtSlot(str, str)
    def request_permission(self, tool_name: str, details_html: str):
        """
        Request permission from user via web dialog.
        Called by ToolRegistry when tool requires confirmation.
        
        Args:
            tool_name: Name of the tool (e.g., 'edit_file', 'write_file')
            details_html: HTML content showing what will be changed
        """
        log.info(f"Permission requested for: {tool_name}")
        # Emit signal with callback to handle response
        self.permission_requested.emit(tool_name, details_html, self._handle_permission_response)
    
    def _handle_permission_response(self, approved: bool, remember: bool):
        """
        Handle permission response from user.
        This is called by JavaScript when user clicks Approve/Deny.
        
        Args:
            approved: True if user approved, False if denied
            remember: True if user wants to remember choice
        """
        log.info(f"Permission response: approved={approved}, remember={remember}")
        # Store response for ToolRegistry to pick up
        # This will be handled by a waiting mechanism in ToolRegistry

    @pyqtSlot(str)
    def on_reject_file_edit(self, file_path: str):
        """User rejected a file edit — optionally restore from pre-edit snapshot."""
        log.info(f'File edit rejected: {file_path}')
        # Only emit reject signal — main_window handler opens the file and reverts
        self.reject_file_edit_requested.emit(file_path)

    @pyqtSlot()
    def on_accept_all_files(self):
        """User accepted all pending file edits."""
        log.info('Accept all files requested')
        # Signal to main_window to accept all pending edits
        # This will be handled by the sidebar's changed files panel
        self.accept_file_edit_requested.emit("__ALL__")

    @pyqtSlot()
    def on_reject_all_files(self):
        """User rejected all pending file edits."""
        log.info('Reject all files requested')
        # Signal to main_window to reject all pending edits
        self.reject_file_edit_requested.emit("__ALL__")

    @pyqtSlot()
    def on_approve_tools(self):
        """User approved pending tool actions."""
        self.proceed_requested.emit()

    @pyqtSlot()
    def on_deny_tools(self):
        """User denied pending tool actions."""
        log.info('User denied tool execution')

    @pyqtSlot()
    def on_always_allow(self):
        """User enabled always-allow for tools."""
        self.always_allow_changed.emit(True)

    @pyqtSlot()
    def on_undo_action(self):
        """Undo the last AI action."""
        log.info('Undo action requested')
        # Will be routed through main_window to agent tool registry

    @pyqtSlot(str, str)
    def on_insert_code(self, code: str, language: str):
        """Insert code at the editor cursor."""
        log.info(f'Insert code requested: {len(code)} chars, lang={language}')
        # Forwarded to main_window.insert_code_at_cursor via signal

    @pyqtSlot(str)
    def on_js_error(self, error_json: str):
        """Handle JavaScript errors reported from the page."""
        log.warning(f'JS Error: {error_json}')
    
    def update_points_balance(self, result: dict):
        """Update UI with current points balance after consumption.
        
        Args:
            result: Dict from points_manager.consume_points() with:
                - remaining_balance: Points remaining
                - remaining_tokens: Token equivalent
                - points_consumed: Points just used
        """
        try:
            # Send points update to JavaScript UI
            points_data = {
                "balance": result.get("remaining_balance", 0),
                "tokens_equivalent": result.get("remaining_tokens", 0),
                "points_consumed": result.get("points_consumed", 0),
            }
            
            # Call JavaScript to update UI
            js_code = f"""
            if (window.updatePointsBalance) {{
                window.updatePointsBalance({json.dumps(points_data)});
            }}
            """
            self._view.page().runJavaScript(js_code)
            
            log.info(f"[AIChat] Points balance updated: {result.get('remaining_balance', 0):,} points")
        except Exception as e:
            log.warning(f"[AIChat] Failed to update points balance UI: {e}")

    @pyqtSlot(str)
    def delete_chat_from_sqlite(self, conversation_id: str):
        """Delete a conversation from SQLite."""
        try:
            from src.core.chat_history import get_chat_history
            history = get_chat_history()
            history.delete_conversation(conversation_id)
            log.info(f"âœ“ Deleted conversation {conversation_id} from SQLite")
        except Exception as e:
            log.error(f"âœ— Failed to delete conversation {conversation_id}: {e}")

    @pyqtSlot(str)
    def load_full_chat(self, conversation_id: str):
        """Trigger loading of full chat messages for a specific conversation."""
        try:
            # This will be handled by the signal connection in AIChatWidget
            self.load_full_chat_requested.emit(conversation_id)
            log.debug(f"Requested full chat load for {conversation_id}")
        except Exception as e:
            log.error(f"Failed to request full chat {conversation_id}: {e}")

    # â”€â”€ THREE FEATURES: Project Tree, Terminal, Todo Bridge Slots â”€â”€â”€â”€â”€

    @pyqtSlot(str)
    def on_open_folder(self, folder_path: str):
        """Open folder in OS file explorer."""
        try:
            import subprocess
            # FIX: Prevent console window popup in PyInstaller builds
            startupinfo = None
            creationflags = 0
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
                subprocess.Popen(['explorer', folder_path], startupinfo=startupinfo, creationflags=creationflags)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder_path])
            else:
                subprocess.Popen(['xdg-open', folder_path])
        except Exception as e:
            log.error(f"Cannot open folder: {e}")

    @pyqtSlot()
    def on_open_terminal(self):
        """Open terminal panel."""
        log.info("Open terminal requested from chat")
        self.open_terminal_requested.emit()

    @pyqtSlot(str)
    def on_run_in_terminal(self, command: str):
        """Open terminal panel and run the given command inside it."""
        log.info(f"Run in terminal requested: {command[:80]}")
        self.run_in_terminal_requested.emit(command)

    # Permission response from user (Accept / Reject on dangerous-command card)
    permission_decided = pyqtSignal(str)  # 'accept' or 'reject'

    @pyqtSlot(str)
    def on_permission_respond(self, decision: str):
        """Called from JS when user clicks Accept or Reject on a permission card."""
        log.info(f"[BRIDGE] Permission card response: {decision}")
        self.permission_decided.emit(decision)

    # â”€â”€ CHAT PERSISTENCE: File-based storage fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    @pyqtSlot(str, str, result=str)
    def save_single_chat_to_sqlite(self, storage_key: str, json_data: str) -> str:
        """
        Save a SINGLE chat's data to SQLite database.
        This provides high-performance persistent storage without full-history payload overhead.
        """
        try:
            from src.core.chat_history import get_chat_history
            chat = json.loads(json_data)
            history = get_chat_history()
            
            if not isinstance(chat, dict):
                return "ERROR: Invalid chat data"
                
            conversation_id = str(chat.get('id', storage_key))
            
            # Use actual project path from parent widget's _current_project_path
            if self._parent_widget and hasattr(self._parent_widget, '_current_project_path'):
                project_path = self._parent_widget._current_project_path or f"project_{storage_key}"
            else:
                project_path = f"project_{storage_key}"
            
            title = chat.get('title', f"Chat {conversation_id[:8]}")
            messages = chat.get('messages', [])
            
            # Skip saving if no messages
            if not messages:
                log.debug(f"Skipping save for empty conversation {conversation_id}")
                return "OK - Skipped empty"
                
            # Create conversation if not exists
            history.create_conversation(project_path, title, conversation_id=conversation_id)

            total_messages = len(messages)
            existing_count = history.db.get_message_count(conversation_id)
            if existing_count > total_messages:
                history.clear_conversation_messages(conversation_id)
                existing_count = 0
            
            if existing_count == total_messages:
                log.debug(f"Skipping save for conversation {conversation_id} (no new messages)")
                return "OK - No new messages"
            
            # Add only new messages
            for msg in messages[existing_count:]:
                # Handle both 'content' (new) and 'text' (legacy) keys
                msg_content = msg.get('content') or msg.get('text', '')
                msg_role = msg.get('role') or msg.get('sender') or 'user'
                history.add_message(
                    conversation_id=conversation_id,
                    role=msg_role,
                    content=msg_content,
                    files_accessed=msg.get('files_accessed', []),
                    tools_used=msg.get('tools_used', [])
                )
            
            log.debug(f'âœ" Saved single chat {conversation_id} to SQLite (storage_key: {storage_key})')
            _maybe_schedule_chat_summary(project_path, conversation_id, title, messages, self)
            return "OK"
            
        except Exception as e:
            log.error(f'âœ— Failed to save single chat to SQLite: {e}')
            return f"ERROR: {str(e)}"

    @pyqtSlot(str, str, result=str)
    def save_chats_to_sqlite(self, storage_key: str, json_data: str) -> str:
        """
        Save ALL chat data to SQLite database. (Legacy full-sync fallback)
        Returns: "OK" or error message.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            # Parse JSON data
            chats = json.loads(json_data)
            history = get_chat_history()
            
            # Save each conversation
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                
                conversation_id = str(chat.get('id', storage_key))
                
                # Use actual project path from parent widget's _current_project_path
                if self._parent_widget and hasattr(self._parent_widget, '_current_project_path'):
                    project_path = self._parent_widget._current_project_path or f"project_{storage_key}"
                else:
                    project_path = f"project_{storage_key}"
                
                title = chat.get('title', f"Chat {conversation_id[:8]}")
                messages = chat.get('messages', [])
                
                # Create conversation if not exists
                history.create_conversation(project_path, title, conversation_id=conversation_id)

                total_messages = len(messages)
                existing_count = history.db.get_message_count(conversation_id)
                if existing_count > total_messages:
                    history.clear_conversation_messages(conversation_id)
                    existing_count = 0
                
                if existing_count == total_messages:
                    continue
                
                # Add only new messages
                for msg in messages[existing_count:]:
                    history.add_message(
                        conversation_id=conversation_id,
                        role=msg.get('role', msg.get('sender', 'user')),
                        content=msg.get('content', msg.get('text', '')),
                        files_accessed=msg.get('files_accessed', []),
                        tools_used=msg.get('tools_used', [])
                    )
                _maybe_schedule_chat_summary(project_path, conversation_id, title, messages, self)
                        
            log.debug(f'âœ" Saved {len(chats)} chats to SQLite (storage_key: {storage_key})')
            return "OK"
            
        except Exception as e:
            log.error(f'âœ— Failed to save chats to SQLite: {e}')
            return f"ERROR: {str(e)}"
    
    @pyqtSlot(str, str)
    def show_notification(self, title: str, message: str):
        """Show a native Windows notification."""
        try:
            from src.utils.notifications import show_toast_notification
            show_toast_notification(title, message)
        except Exception as e:
            log.error(f"Failed to show notification: {e}")

    @pyqtSlot(str)
    def on_save_finished(self, status: str):
        """Called by JS when save process is completed (success or error)."""
        log.info(f"JS Save finished signal received from bridge: {status}")
        # Emit signal to notify waiting components (like MainWindow.closeEvent)
        self.save_finished.emit(status)
    
    @pyqtSlot(str)
    def notify_chat_list_updated(self, chat_list_json: str):
        """Called by JS to notify that chat list has been updated, passing the chat list data directly."""
        log.info("[ChatList] JS notified chat list updated with data")
        self.chat_list_updated_with_data.emit(chat_list_json)
        log.info("[ChatList] chat_list_updated_with_data signal emitted")
    
    @pyqtSlot(str, result=str)
    def load_chats_from_sqlite(self, storage_key: str) -> str:
        """
        Load ONLY chat metadata (not full messages) for fast sidebar rendering.
        Returns: JSON string with conversation list or empty array.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            # Get chat history manager
            history = get_chat_history()
            
            # Get project path
            project_path = f"project_{storage_key}"
            
            # Get all conversations for this project
            conversations = history.get_conversations(project_path)
            
            if not conversations:
                log.debug(f'No chats found in SQLite for storage_key: {storage_key}')
                return "[]"
            
            # OPTIMIZATION 1: Return only metadata (id, title, created_at) - NOT full messages
            # Full messages loaded on-demand when user clicks a chat
            
            # OPTIMIZATION 2: Limit to recent 50 chats for performance
            MAX_CHATS_DISPLAY = 50
            if len(conversations) > MAX_CHATS_DISPLAY:
                conversations = conversations[:MAX_CHATS_DISPLAY]
                log.info(f'âš¡ Limited to {MAX_CHATS_DISPLAY} most recent chats for performance')
            
            result = []
            for conv in conversations:
                chat_data = {
                    'id': conv['conversation_id'],
                    'title': conv['title'],
                    'created_at': conv.get('created_at'),
                    'message_count': conv.get('message_count', 0)  # Just count, not content
                }
                result.append(chat_data)
            
            json_result = json.dumps(result)
            log.debug(f'âœ" Loaded {len(result)} chat metadata ({len(json_result)} chars)')
                        
            # Emit signal to update sidebar chat list
            self.chat_list_updated.emit()
                        
            return json_result
            
        except Exception as e:
            log.error(f'âœ— Failed to load chats from SQLite: {e}')
            return "[]"
    
    @pyqtSlot(str, result=str)
    def load_full_chat_from_sqlite(self, conversation_id: str) -> str:
        """
        Load full chat messages for a specific conversation (on-demand).
        Returns: JSON string with complete conversation or empty object.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            history = get_chat_history()
            messages = history.get_messages(conversation_id)
            
            if not messages:
                return "{}"
            
            result = {
                'id': conversation_id,
                'messages': messages
            }
            
            json_result = json.dumps(result)
            log.debug(f'âœ“ Loaded full chat {conversation_id} ({len(json_result)} chars)')
            return json_result
            
        except Exception as e:
            log.error(f'âœ— Failed to load full chat: {e}')
            return "{}"


from PyQt6.QtWebEngineCore import QWebEnginePage

class ConsolePage(QWebEnginePage):
    """Custom page that captures JavaScript console messages."""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # level is an enum: InfoMessageLevel=0, WarningMessageLevel=1, ErrorMessageLevel=2
        level_val = level.value if hasattr(level, 'value') else int(level)
        level_names = {0: 'INFO', 1: 'WARN', 2: 'ERROR'}
        level_name = level_names.get(level_val, 'LOG')
        # Show [CHAT] tagged messages or errors - these are important for debugging
        if '[CHAT]' in message or level_val >= 2:
            # Use bright colors for [CHAT] messages to make them visible
            try:
                if '[CHAT]' in message:
                    print(f"\033[96m[JS {level_name}] {message}\033[0m")  # Cyan color
                else:
                    print(f"[JS {level_name}] {message}")
            except UnicodeEncodeError:
                # Fallback for Windows console encoding issues
                safe_message = message.encode('ascii', 'ignore').decode('ascii')
                if '[CHAT]' in message:
                    print(f"[JS {level_name}] {safe_message}")
                else:
                    print(f"[JS {level_name}] {safe_message}")


class AIChatWidget(QWidget):
    """Web-based AI chat widget using QWebEngineView."""
    message_sent = pyqtSignal(str, str)  # user_message, code_context
    run_command = pyqtSignal(str)
    stop_requested = pyqtSignal()
    proceed_requested = pyqtSignal()
    always_allow_changed = pyqtSignal(bool)
    generate_plan_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    model_changed = pyqtSignal(str, str, str)  # model_id, perf, cost
    
    open_file_requested = pyqtSignal(str)
    open_file_at_line_requested = pyqtSignal(str, int)  # file_path, line_number
    answer_question_requested = pyqtSignal(str, str)   # tool_call_id, answer
    show_diff_requested = pyqtSignal(str)
    
    # Permission response signal (forwarded from bridge)
    permission_response = pyqtSignal(str, bool, str)  # request_id, approved, scope

    # File edit accept/reject signals
    accept_file_edit_requested = pyqtSignal(str)  # file_path
    reject_file_edit_requested = pyqtSignal(str)  # file_path
    
    # Vision processing signal
    _vision_response_received = pyqtSignal(str)
    
    # Sync vision exchange to agent_bridge conversation history
    # (user_text, assistant_response) — so follow-up messages have context
    vision_history_sync = pyqtSignal(str, str)

    # Terminal panel signal
    open_terminal_requested = pyqtSignal()  # Request main window to open terminal panel
    run_in_terminal_requested = pyqtSignal(str)  # Request to open terminal and run command
    permission_decided = pyqtSignal(str)  # 'accept'/'reject' from permission card

    # Smart paste signal - emitted when user pastes code, to check if it matches editor selection
    smart_paste_check_requested = pyqtSignal(str)  # pasted_text
    
    # Chat list update signal - emitted when chats are loaded/created/updated
    chat_list_updated = pyqtSignal()
    chat_list_updated_with_data = pyqtSignal(str)  # emitted with chat list JSON
    
    # AutoGen multi-agent toggle signal
    toggle_autogen_requested = pyqtSignal()
    
    # Load full chat from database signal
    load_full_chat_requested = pyqtSignal(str)  # conversation_id
    save_finished = pyqtSignal(str)             # status
    
    # Todo management signal
    toggle_todo_requested = pyqtSignal(str, bool)  # task_id, completed
    
    # Memory save status signals
    memory_save_started = pyqtSignal(str)  # memory_name
    memory_save_completed = pyqtSignal(str)  # memory_name
    memory_save_failed = pyqtSignal(str)  # error_message
    
    def show_question(self, info: dict):
        """Show a question card in the chat UI."""
        self._bridge.show_question(info)

    def show_indexing_status(self, message: str, auto_hide: bool = False):
        """Show indexing status in the chat UI."""
        js_bool = 'true' if auto_hide else 'false'
        safe_message = json.dumps(message)
        self._view.page().runJavaScript(f"if(window.showIndexingStatus) window.showIndexingStatus({safe_message}, {js_bool});")

    def hide_indexing_status(self):
        """Hide indexing status in the chat UI."""
        self._view.page().runJavaScript("if(window.hideIndexingStatus) window.hideIndexingStatus();")

    # ================================================
    # AGENT MODE GRID - Dynamic Tool Activation
    # ================================================

    def show_agent_mode(self):
        """Show the Agent Mode grid indicator in chat UI."""
        self._view.page().runJavaScript("if(window.showAgentMode) window.showAgentMode();")

    def hide_agent_mode(self):
        """Hide the Agent Mode grid indicator in chat UI."""
        self._view.page().runJavaScript("if(window.hideAgentMode) window.hideAgentMode();")
    
    @pyqtSlot()
    def show_memory_saving_animation(self):
        memory_name = "Session insights"
        safe_name = json.dumps(memory_name)
        self._view.page().runJavaScript(f"if(window.showMemorySavingAnimation) window.showMemorySavingAnimation({safe_name});")
    
    @pyqtSlot(str)
    def show_memory_saved_confirmation(self, memory_name: str = "Session insights"):
        safe_name = json.dumps(memory_name)
        self._view.page().runJavaScript(f"if(window.showMemorySavedConfirmation) window.showMemorySavedConfirmation({safe_name});")
    
    @pyqtSlot()
    def hide_memory_saving_animation(self):
        self._view.page().runJavaScript("if(window.hideMemorySavingAnimation) window.hideMemorySavingAnimation();")

    def set_active_agent_mode(self, mode: str):
        """Activate a specific agent mode in the grid.
        
        Args:
            mode: One of: think, read, search, grep, find, explore, surf, dive
        """
        safe_mode = json.dumps(mode)
        self._view.page().runJavaScript(f"if(window.setActiveAgentMode) window.setActiveAgentMode({safe_mode});")

    def clear_active_agent_mode(self):
        """Clear all active agent mode highlights."""
        self._view.page().runJavaScript("if(window.clearActiveAgentMode) window.clearActiveAgentMode();")

    def flash_agent_mode(self, mode: str, duration_ms: int = 3000):
        """Flash an agent mode for a short duration.
        
        Args:
            mode: Mode to activate
            duration_ms: Duration in milliseconds (default: 3000)
        """
        safe_mode = json.dumps(mode)
        js_code = f"if(window.flashAgentMode) window.flashAgentMode({safe_mode}, {duration_ms});"
        self._view.page().runJavaScript(js_code)

    def activate_mode_for_tool(self, tool_name: str, custom_label: str = None):
        """Automatically activate the appropriate mode for a tool.
        
        Args:
            tool_name: Name of the tool being used (e.g., 'code_search', 'read_file')
            custom_label: Optional custom label to display
        """
        safe_tool = json.dumps(tool_name)
        if custom_label:
            safe_label = json.dumps(custom_label)
            js_code = f"if(window.activateModeForTool) window.activateModeForTool({safe_tool}, {safe_label});"
        else:
            js_code = f"if(window.activateModeForTool) window.activateModeForTool({safe_tool});"
        self._view.page().runJavaScript(js_code)

    def show_tool_execution(self, tool_name: str, file_name: str = None, status: str = "running"):
        """Show tool execution in the agent mode grid with dynamic labeling.
        
        Args:
            tool_name: Name of the tool being executed
            file_name: Optional file being operated on
            status: Execution status (running, completed, error)
        """
        safe_tool = json.dumps(tool_name)
        safe_file = json.dumps(file_name or "")
        safe_status = json.dumps(status)
        js_code = f"if(window.showToolExecution) window.showToolExecution({safe_tool}, {safe_file}, {safe_status});"
        self._view.page().runJavaScript(js_code)

    def update_agent_mode_label(self, mode: str, label: str):
        """Update the display label for an agent mode.
        
        Args:
            mode: Mode to update (think, read, search, grep, find, explore, surf, dive)
            label: New label text
        """
        safe_mode = json.dumps(mode)
        safe_label = json.dumps(label)
        js_code = f"if(window.updateAgentModeLabel) window.updateAgentModeLabel({safe_mode}, {safe_label});"
        self._view.page().runJavaScript(js_code)

    def reset_agent_mode_labels(self):
        """Reset all agent mode labels to their defaults."""
        self._view.page().runJavaScript("if(window.resetAgentModeLabels) window.resetAgentModeLabels();")

    def clear_project_info(self):
        """Clear project-specific info from the chat UI."""
        self._current_project_path = ""
        self._view.page().runJavaScript("if(window.clearProjectInfo) window.clearProjectInfo();")

    def _add_ai_bubble_streaming(self):
        """Pre-emptively show assistant thinking/bubble for streaming."""
        self.show_thinking()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Initialize with actual current theme from theme manager
        try:
            from src.config.theme_manager import get_theme_manager
            self._is_dark = get_theme_manager().is_dark
        except Exception:
            self._is_dark = True  # fallback to dark
        self._get_code_context = None
        self._terminal_process = None
        self._pty_process = None
        self._terminal_reader = None
        self._project_root = None  # Set via set_project_root() for @ mention search
        self._vision_thread = None
        self._vision_worker = None
        # Connect vision response signal
        self._vision_response_received.connect(self._on_vision_response)
        
        # Terminal state
        self._terminal_output_buffer = ""
        self._terminal_last_emit = 0
        self._terminal_emit_interval = 0.05
        self._current_project_path = ""
        
        # NEW: Store last user message for permission retry (OpenCode enhancement)
        self._last_user_message = ""
        
        # Track current interaction mode: 'Agent', 'Ask', or 'Plan'
        self._current_interaction_mode = "Agent"
        
        self._build_ui()
        # Terminal backend starts lazily when first requested
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # CRITICAL: Configure persistent storage profile for localStorage to survive app restarts
        from PyQt6.QtWebEngineCore import QWebEngineProfile
        from pathlib import Path
        
        # Get or create persistent storage profile
        profile = QWebEngineProfile.defaultProfile()
        
        # Set persistent storage path - THIS IS CRITICAL FOR CHAT PERSISTENCE
        storage_path = str(Path.home() / ".cortex" / "webengine_storage")
        print(f"[WEBVIEW] Setting persistent storage path: {storage_path}")
        
        # These settings ensure data persists across app restarts
        try:
            # Clear any existing cache to ensure fresh HTML/JS loads
            profile.clearHttpCache()
            print("[WEBVIEW] HTTP cache cleared")
            # Set cache type to disk (not memory)
            profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            print("[WEBVIEW] HTTP cache set to disk")
        except Exception as e:
            print(f"[WEBVIEW] Could not set HTTP cache: {e}")
        
        # Enable persistent storage
        try:
            profile.setPersistentStoragePath(storage_path)
            print(f"[WEBVIEW] Persistent storage path set: {storage_path}")
        except Exception as e:
            print(f"[WEBVIEW] Could not set persistent storage: {e}")
        
        # Web View with custom page for console logging
        self._view = QWebEngineView()
        self._page = ConsolePage(self._view)
        self._view.setPage(self._page)
        
        # Enable standard context menu and selection features
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.JavascriptCanAccessClipboard, True
        )
        # Enable localStorage persistence (critical for chat history)
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.LocalStorageEnabled, True
        )
        
        # CRITICAL: Enable SVG rendering and local file access for icons
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.LocalContentCanAccessFileUrls, True
        )
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.AllowRunningInsecureContent, True
        )
        self._view.settings().setAttribute(
            self._view.settings().WebAttribute.PluginsEnabled, True
        )
        # Enable WebGL for better graphics rendering
        try:
            self._view.settings().setAttribute(
                self._view.settings().WebAttribute.WebGLEnabled, True
            )
        except AttributeError:
            pass  # WebGL may not be available on all systems
        
        # Setup Channel
        self._channel = QWebChannel()
        self._bridge = ChatBridge(self._view, parent_widget=self)
        self._bridge.message_submitted.connect(self._on_js_message)
        self._bridge.message_with_images.connect(self._on_js_message_with_images)
        self._bridge.clear_chat_requested.connect(self.clear_chat)
        self._bridge.stop_requested.connect(self.stop_requested.emit)
        self._bridge.run_command_requested.connect(self.run_command.emit)
        self._bridge.proceed_requested.connect(self.proceed_requested.emit)
        self._bridge.always_allow_changed.connect(self.always_allow_changed.emit)
        self._bridge.generate_plan_requested.connect(self.generate_plan_requested.emit)
        self._bridge.mode_changed.connect(self._on_mode_changed_internal)
        self._bridge.mode_changed.connect(self.mode_changed.emit)
        self._bridge.model_changed.connect(self.model_changed.emit)
        self._bridge.open_file_requested.connect(self.open_file_requested.emit)
        self._bridge.open_file_at_line_requested.connect(self.open_file_at_line_requested.emit)
        self._bridge.show_diff_requested.connect(self.show_diff_requested.emit)
        self._bridge.accept_file_edit_requested.connect(self.accept_file_edit_requested.emit)
        self._bridge.reject_file_edit_requested.connect(self.reject_file_edit_requested.emit)
        self._bridge.open_terminal_requested.connect(self.open_terminal_requested.emit)
        self._bridge.run_in_terminal_requested.connect(self.run_in_terminal_requested.emit)
        self._bridge.permission_decided.connect(self.permission_decided.emit)
        self._bridge.search_files_requested.connect(self._on_search_files)
        self._bridge.answer_question_requested.connect(self.answer_question_requested.emit)
        self._bridge.smart_paste_check_requested.connect(self.smart_paste_check_requested.emit)
        
        # Connect permission response signal from bridge
        self._bridge.permission_response.connect(self.permission_response.emit)
        
        # Connect code completion signals from bridge
        self._bridge.code_completion_requested.connect(self._on_code_completion_requested)
        self._bridge.code_completion_selected.connect(self._on_code_completion_selected)
        self._bridge.code_completion_accepted.connect(self._on_code_completion_accepted)
        self._bridge.code_completion_dismissed.connect(self._on_code_completion_dismissed)
        
        # Connect inline diff viewer signals from bridge
        self._bridge.diff_line_accepted.connect(self._on_diff_line_accepted)
        self._bridge.diff_line_rejected.connect(self._on_diff_line_rejected)
        self._bridge.diff_line_commented.connect(self._on_diff_line_commented)
        
        self._bridge.save_finished.connect(self.save_finished.emit)
        
        # Forward chat list updated signal from bridge to widget
        self._bridge.chat_list_updated.connect(self.chat_list_updated.emit)
        self._bridge.chat_list_updated_with_data.connect(self.chat_list_updated_with_data.emit)
        
        # NEW: Lazy load full chat when JS requests it
        self._bridge.load_full_chat_requested.connect(self._on_load_full_chat_requested)
        
        # NEW: Connect todo toggle from bridge to widget
        self._bridge.toggle_todo_requested.connect(self.toggle_todo_requested.emit)
        
        # Terminal signals
        self._bridge.terminal_input.connect(lambda d: self._pty_process.write(d) if self._pty_process else (self._terminal_process.write(d.encode()) if self._terminal_process else None))
        self._bridge.terminal_resize.connect(lambda c, r: self._pty_process.setwinsize(r, c) if self._pty_process else None)
        
        # Connect vision response signal
        self._bridge._vision_response_received.connect(self._on_vision_response)
        
        self._channel.registerObject("bridge", self._bridge)

        self._page.setWebChannel(self._channel)
        
        # Apply initial theme once the page has finished loading
        self._view.loadFinished.connect(self._on_page_loaded)
        self._page_loaded = False
        self._pending_project_info = None
        layout.addWidget(self._view)
        
        # DEFERRED LOAD: Minimal delay for cache clearing to flush
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self._delayed_load_page)
        
    def run_javascript(self, script: str):
        """Execute JavaScript in the chat context."""
        if hasattr(self, '_view') and self._view.page():
            self._view.page().runJavaScript(script)
    
    def _delayed_load_page(self):
        """Load the HTML page after cache clearing delay."""
        print("[WEBVIEW] Loading page after cache clearing delay...")
        
        # Load local HTML with aggressive cache-busting
        html_path = os.path.join(os.path.dirname(__file__), "..", "html", "ai_chat", "aichat.html")
        abs_path = os.path.abspath(html_path)
        
        # Multiple cache busting techniques
        import time
        cache_buster = int(time.time())
        url = QUrl.fromLocalFile(abs_path)
        url.setQuery(f"v={cache_buster}&nocache=1")
        
        # Force reload by triggering cache clear again
        profile = self._view.page().profile()
        if hasattr(profile, 'clearHttpCache'):
            profile.clearHttpCache()
        
        self._view.setUrl(url)
        print(f"[WEBVIEW] URL set: {url.toString()}")
        
    def _on_page_loaded(self, ok):
        """Apply the current theme immediately after the page finishes loading."""
        import logging as _log
        if ok:
            self._page_loaded = True
            _log.info(f"[AI_CHAT] Page loaded successfully, applying theme (is_dark={self._is_dark})")
            # Use set_theme with retry logic
            self.set_theme(self._is_dark)
            # Apply pending project info after page load (only if not already applied)
            if self._pending_project_info and not getattr(self, '_project_info_applied', False):
                name, path, chats_json = self._pending_project_info
                self._apply_project_info(name, path, chats_json)
        else:
            _log.error("[AI_CHAT] Page load failed!")

    def on_chunk(self, chunk):
        """Handle AI streaming chunk - async to prevent UI blocking."""
        # Use JSON encoding to properly escape for JavaScript
        safe_chunk = json.dumps(chunk)
        self._view.page().runJavaScript(
            f"if(window.onChunk) window.onChunk({safe_chunk});",
            lambda result: None  # Async callback
        )

    def on_complete(self, full_response: str):
        """Handle completion of the AI response."""
        self._view.page().runJavaScript("if(window.onComplete) window.onComplete();")

    def _on_mode_changed_internal(self, mode: str):
        """Track the current interaction mode internally."""
        self._current_interaction_mode = mode
        log.info(f"[AIChat] Interaction mode changed to: {mode}")

    def _on_js_message(self, text):
        """Handle message from JS.
        
        Routes to performance mode system if performance mode is enabled.
        If Plan mode is active, generates a .md plan file instead of chat.
        This ensures ALL messages (text-only or with images) use the correct
        model selection based on performance mode.
        """
        # NEW: Store last user message for permission retry
        self._last_user_message = text
        
        # ── PLAN MODE: generate .md file instead of chat response ──────────
        if getattr(self, '_current_interaction_mode', 'Agent') == 'Plan':
            log.info(f"[AIChat] Plan mode: generating .md plan file for: {text[:80]}")
            self._generate_plan_file(text)
            return
        
        # Check if performance mode routing should be used
        perf_mode_str = self._get_performance_mode_from_settings()
        perf_mode = get_performance_mode(perf_mode_str)
        config = get_mode_config(perf_mode)
        
        # If performance mode is not 'auto' or has special model selection, route through performance system
        if perf_mode != PerformanceMode.AUTO or config.main_agent_model or config.vision_model:
            log.info(f"[AIChat] Routing text-only message through performance mode: {perf_mode.value}")
            # Process through performance mode (even without images)
            self._process_text_message_through_performance(text, config)
            return
        
        # Otherwise, use standard agent_bridge path (Auto mode with user's configured model)
        context = ""
        if self._get_code_context:
            context = self._get_code_context()
        self.message_sent.emit(text, context)
    
    def _on_js_message_with_images(self, text, image_data_json):
        """Handle message with images (vision/OCR).

        Note: This path currently bypasses the agentic tool loop and runs a single
        multimodal chat completion, then appends the assistant response to chat.
        If Plan mode is active, generates a .md plan file based on image analysis.
        """
        import json
        import requests
        import os
        from PyQt6.QtCore import QThread
        
        log.info(f"[AIChat] Message with images received, text length: {len(text)}")
        
        # Parse image data
        try:
            images = json.loads(image_data_json) if image_data_json else []
            log.info(f"[AIChat] Number of images: {len(images)}")
        except Exception as e:
            log.error(f"[AIChat] Failed to parse image data: {e}")
            images = []
        
        if not images:
            # No valid images, treat as regular message
            self._on_js_message(text)
            return
        
        # ── PLAN MODE + IMAGES: analyze image then create .md plan file ───
        # Trigger if: Plan dropdown selected, OR text mentions "plan" keywords
        _plan_keywords = ["plan", "design", "blueprint", "architecture", "spec", "wireframe", "mockup", "layout"]
        _is_plan_mode = getattr(self, '_current_interaction_mode', 'Agent') == 'Plan'
        _text_wants_plan = any(kw in text.lower() for kw in _plan_keywords)
        
        if _is_plan_mode or _text_wants_plan:
            log.info(f"[AIChat] Plan mode + images: generating .md plan from image analysis "
                     f"(dropdown={'Plan' if _is_plan_mode else 'Agent'}, text_match={_text_wants_plan})")
            self._show_thinking_in_js()
            self._vision_user_text = text
            import threading
            threading.Thread(
                target=self._generate_plan_file_with_images,
                args=(text, images),
                daemon=True,
            ).start()
            return
        
        # Show thinking indicator
        self._show_thinking_in_js()
        
        # Store user text for history sync after vision response completes
        self._vision_user_text = text
        
        # Process in a separate thread to not block UI
        def process_vision():
            """Process vision request.
            
            FIXED: All modes now use single agent (direct Mistral API).
            Multi-agent coordination was adding 30-60s overhead per call.
            The quality comes from mistral-large vision, not from extra LLM calls.
            """
            try:
                perf_mode_str = self._get_performance_mode_from_settings()
                perf_mode = get_performance_mode(perf_mode_str)
                config = get_mode_config(perf_mode)
                
                log.info(f"[AIChat] Vision mode: {perf_mode.value} -> single agent (direct API)")
                self._process_message_single_agent(images, text, config)
                    
            except Exception as e:
                log.error(f"[AIChat] Vision processing error: {e}", exc_info=True)
                self._vision_response_received.emit(f"Error: {str(e)}")
        
        # Cleanup previous thread if exists and running
        if hasattr(self, '_vision_thread') and self._vision_thread is not None and self._vision_thread.isRunning():
            log.warning("Cleaning up previous vision thread...")
            self._vision_thread.quit()
            self._vision_thread.wait(3000)  # Wait up to 3s
        
        # Create thread for vision processing
        self._vision_thread = QThread()
        self._vision_worker = VisionWorker(process_vision)
        self._vision_worker.response_ready.connect(self._on_vision_response)
        self._vision_worker.error_occurred.connect(self._on_vision_error)
        self._vision_worker.moveToThread(self._vision_thread)
        self._vision_thread.started.connect(self._vision_worker.run)
        self._vision_thread.start()
        log.info("Vision thread started")
    
    def _execute_vision_agent(self, images, text, session_id):
        """Execute Vision Agent for image analysis.
        
        This is the FIRST step in the coordination layer.
        Vision Agent MUST complete before Main Agent is called.
        
        Args:
            images: List of image dicts with 'data' key (base64)
            text: User's text query
            session_id: Session identifier for memory storage
            
        Returns:
            Dictionary with vision analysis results
        """
        try:
            from src.agent.src.tools.VisionAgentTool.vision_agent import VisionAgentTool
            import asyncio
            
            # Get current performance mode to determine vision model
            perf_mode_str = self._get_performance_mode_from_settings()
            perf_mode = get_performance_mode(perf_mode_str)
            config = get_mode_config(perf_mode)
            vision_model = config.vision_model
            
            log.info(f"[AIChat] Spawning Vision Agent for image analysis (model={vision_model})")
            
            # Use first image for analysis
            image_data = images[0]['data']
            
            # Create Vision Agent instance
            agent = VisionAgentTool()
            
            # Execute vision analysis (synchronous in this thread)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    agent.execute(
                        image_data=image_data,
                        analysis_type="full",
                        store_in_memory=True,
                        session_id=session_id,
                        vision_model=vision_model  # Pass the model from config
                    )
                )
            finally:
                loop.close()
            
            log.info(f"[AIChat] Vision Agent execution complete: success={result.get('success')}, model={vision_model}")
            return result
            
        except Exception as e:
            log.error(f"[AIChat] Vision Agent execution failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def _build_vision_enhanced_prompt(self, user_text, vision_context):
        """Build enhanced prompt with vision context injected.
        
        This ensures Main Agent has full context from Vision Agent's analysis.
        
        Args:
            user_text: Original user query
            vision_context: Dictionary with vision analysis results
            
        Returns:
            Enhanced prompt string
        """
        prompt_parts = []
        
        # Add user's original question
        prompt_parts.append(user_text)
        
        # Add vision context section
        prompt_parts.append("\n\n## Image Analysis Context\n")
        prompt_parts.append("The following image has been analyzed and the results are provided for your reference:\n")
        
        # OCR Text
        ocr_text = vision_context.get('ocr_text', '')
        if ocr_text:
            prompt_parts.append(f"\n### OCR Extracted Text:\n{ocr_text}\n")
        
        # Image Description
        description = vision_context.get('image_description', '')
        if description:
            prompt_parts.append(f"\n### Image Description:\n{description}\n")
        
        # Detected Objects
        objects = vision_context.get('detected_objects', [])
        if objects:
            objects_str = ", ".join(objects)
            prompt_parts.append(f"\n### Detected Objects:\n{objects_str}\n")
        
        # Analysis metadata
        model_used = vision_context.get('vision_model_used', 'unknown')
        confidence = vision_context.get('confidence_score', 0.0)
        prompt_parts.append(f"\n### Analysis Details:\n")
        prompt_parts.append(f"- Model: {model_used}\n")
        prompt_parts.append(f"- Confidence: {confidence:.2f}\n")
        
        # Instruction to use context
        prompt_parts.append("\n**IMPORTANT**: Use the above image analysis to inform your response. "
                          "Do not ask the user to describe the image - you already have the analysis. "
                          "Reference specific details from the analysis in your answer.\n")
        
        return "\n".join(prompt_parts)
    
    def _call_main_agent_with_vision_context(self, prompt, provider_name, model_id, config=None):
        """Call Main Agent with vision-enhanced prompt.
        
        ARCHITECTURE: Mistral is ALWAYS the main provider.
        This is the SECOND step in the coordination layer.
        Main Agent receives vision context and provides informed response.
        
        Args:
            prompt: Enhanced prompt with vision context
            provider_name: LLM provider (always 'mistral' per architecture)
            model_id: Model identifier
            config: PerformanceConfig (optional, for token calculation)
            
        Returns:
            Response string from Main Agent
        """
        try:
            from src.config.settings import get_settings
            settings = get_settings()
            
            # ARCHITECTURE: Force Mistral as provider regardless of what's passed
            provider_name = "mistral"
            
            # Get API configuration
            temperature = float(settings.get("ai", "temperature", default=0.7) or 0.7)
            
            # Calculate max_tokens from model_limits with performance multiplier
            if config:
                max_tokens = calculate_max_tokens_for_mode(model_id, config)
            else:
                # Fallback to settings if no config provided
                max_tokens = int(settings.get("ai", "max_tokens", default=4000) or 4000)
            
            # Build messages for Main Agent
            messages = [{"role": "user", "content": prompt}]
            
            log.info(f"[AIChat] Main Agent: provider=mistral, model={model_id}, max_tokens={max_tokens}")
            
            # ALWAYS route to Mistral as the main provider
            return self._call_mistral_with_context(messages, temperature, max_tokens, model_id)
                
        except Exception as e:
            log.error(f"[AIChat] Main Agent call failed: {e}", exc_info=True)
            return f"Error calling Main Agent: {str(e)}"
    
    def _call_mistral_with_context(self, messages, temperature, max_tokens, model_id):
        """Call Mistral API with vision context."""
        api_key = os.getenv("MISTRAL_API_KEY", "")
        if not api_key:
            return "Error: MISTRAL_API_KEY not set"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_id or "mistral-large-latest",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=(30, 180)
        )
        
        if response.status_code == 200:
            data = response.json()
            content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            # Mistral can return content as list of blocks for multimodal
            if isinstance(content, list):
                content = ''.join(
                    c.get('text', '') if isinstance(c, dict) else str(c)
                    for c in content
                )
            return content or ''
        else:
            return f"Mistral API error {response.status_code}: {response.text[:200]}"
    
    def _call_siliconflow_with_context(self, messages, temperature, max_tokens, model_id):
        """Call SiliconFlow API with vision context."""
        api_key = os.getenv("SILICONFLOW_API_KEY", "")
        if not api_key:
            return "Error: SILICONFLOW_API_KEY not set"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_id or "Qwen/Qwen2.5-72B-Instruct",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        response = requests.post(
            "https://api.siliconflow.cn/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=(30, 180)
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content', '')
        else:
            return f"SiliconFlow API error {response.status_code}: {response.text[:200]}"
    
    # ==================== PERFORMANCE MODE METHODS ====================
    
    def _get_performance_mode_from_settings(self) -> str:
        """Get current performance mode from settings.
        
        Returns:
            Mode string: 'efficient', 'auto', 'performance', or 'ultimate'
        """
        try:
            from src.config.settings import get_settings
            settings = get_settings()
            mode = settings.get("ai", "performance_mode", default="auto")
            return mode or "auto"
        except Exception as e:
            log.warning(f"[AIChat] Failed to get performance mode: {e}, defaulting to 'auto'")
            return "auto"
    
    def _process_message_single_agent(self, images, text, config):
        """Process message with single agent.
        
        ARCHITECTURE: Mistral is ALWAYS the main provider.
        
        For IMAGE messages:
          Step 1: Call Mistral Vision to analyze the image (direct API)
          Step 2: Build enhanced prompt with image description
          Step 3: Route to agentic tool loop so AI can CREATE files
        
        For TEXT-only messages:
          Direct to agentic tool loop (standard path)
        
        This ensures the agent actually SEES the image content and can
        use tools (create_file, edit_file, etc.) to build what the user wants.
        """
        try:
            from src.config.settings import get_settings
            settings = get_settings()
            
            has_images = images and len(images) > 0
            provider_name = "mistral"
            
            if not has_images:
                # Text-only: standard agentic loop
                model_id = self._auto_select_mistral_model(text)
                max_tokens = calculate_max_tokens_for_mode(model_id, config)
                log.info(f"[AIChat] Single agent text: {model_id}, max_tokens={max_tokens}")
                self._call_agent_and_respond(text, provider_name, model_id, max_tokens, config.temperature)
                return
            
            # ── IMAGE PATH: Analyze image first, then route to agentic loop ──
            vision_model = config.vision_model or "mistral-medium-latest"
            agent_model = config.main_agent_model or "mistral-small-latest"
            log.info(f"[AIChat] Vision Step 1: Analyzing image with {vision_model}")
            
            # Step 1: Call Mistral Vision to get detailed image description
            pipeline_result = process_images_for_api(images, text, provider=provider_name)
            
            for warn in pipeline_result.get("warnings", []):
                log.warning(f"[AIChat] Image pipeline warning: {warn}")
            for err in pipeline_result.get("errors", []):
                log.warning(f"[AIChat] Image pipeline: {err}")
            
            messages = pipeline_result["messages"]
            img_count = pipeline_result.get("image_count", 0)
            log.info(f"[AIChat] Vision: {img_count} image(s) processed")
            
            # Direct Mistral vision call to describe the image
            max_tokens_vision = 4096  # Enough for a detailed description
            image_description = self._call_mistral_with_context(
                messages, config.temperature, max_tokens_vision, vision_model
            )
            
            if not image_description or image_description.startswith("Error"):
                log.warning(f"[AIChat] Vision analysis failed: {image_description}")
                self._vision_response_received.emit(
                    image_description or "Error: Vision analysis failed"
                )
                return
            
            log.info(f"[AIChat] Vision Step 1 complete: {len(image_description)} chars description")
            
            # Step 2: Build enhanced prompt for the agentic loop
            # The agent will see exactly what the image contains and can create files
            enhanced_prompt = (
                f"{text}\n\n"
                f"## Image Analysis (what the user's image shows)\n"
                f"{image_description}\n\n"
                f"IMPORTANT: The image description above is what the user shared. "
                f"Use this description to fulfill their request. "
                f"Create files, write code, or take actions based on what the image shows."
            )
            
            # Step 3: Route to agentic tool loop with mode's model
            max_tokens = calculate_max_tokens_for_mode(agent_model, config)
            log.info(f"[AIChat] Vision Step 2: Routing to agentic loop with {agent_model}")
            
            # Inject vision context into agent_bridge history for follow-ups
            if hasattr(self, '_bridge') and hasattr(self._bridge, 'inject_vision_history'):
                self._bridge.inject_vision_history(
                    f"[User sent image with text: {text}]",
                    f"[Image analysis: {image_description[:2000]}]"
                )
            
            self._call_agent_and_respond(enhanced_prompt, provider_name, agent_model, max_tokens, config.temperature)
            
        except Exception as e:
            log.error(f"[AIChat] Single agent error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Error: {str(e)}")
    
    def _process_message_performance(self, images, text, config):
        """Process message with sequential multi-agent (Performance mode).
        
        Uses CoordinationEngine (ported from Claude Code's coordinatorMode.ts):
        1. Vision Agent analyzes image FIRST (sequential - MUST complete)
        2. Vision context stored via VisionContextStore + Scratchpad
        3. Main Agent receives vision context and responds
        4. Results aggregated with worker lifecycle tracking
        """
        try:
            from src.config.settings import get_settings
            from src.coordinator.coordinator_system import CoordinationEngine, get_vision_store
            
            settings = get_settings()
            # ARCHITECTURE: Mistral is ALWAYS the main provider. Never read provider from settings.
            provider_name = "mistral"
            session_id = getattr(self, 'current_session_id', None) or "default-session"
            project_path = None
            if hasattr(self, '_pending_project_info') and self._pending_project_info:
                _, project_path, _ = self._pending_project_info
            
            log.info(f"[AIChat] Performance mode: Sequential multi-agent via CoordinationEngine")
            
            # Create coordination engine
            engine = CoordinationEngine(project_path=project_path, session_id=session_id)
            
            # Define vision callback (uses image pipeline)
            def call_vision(imgs, txt):
                # First try the VisionAgentTool
                result = self._execute_vision_agent(imgs, txt, session_id)
                if result.get("success"):
                    return result.get("vision_context", {})
                # Fallback: direct Mistral vision call with image pipeline
                pipeline_result = process_images_for_api(imgs, txt, provider="mistral")
                if pipeline_result["provider_supports_vision"]:
                    messages = pipeline_result["messages"]
                    vision_model = config.vision_model or "mistral-medium-latest"
                    max_tok = calculate_max_tokens_for_mode(vision_model, config)
                    raw_response = self._call_mistral_with_context(messages, config.temperature, max_tok, vision_model)
                    return {"description": raw_response, "ocr_text": "", "raw": raw_response}
                return {"error": "Vision not available"}
            
            # Define main LLM callback — ALWAYS uses Mistral
            def call_llm(enhanced_prompt):
                main_model = config.main_agent_model or "mistral-medium-latest"
                log.info(f"[AIChat] Performance mode: Main Agent using mistral/{main_model}")
                return self._call_main_agent_with_vision_context(
                    enhanced_prompt, "mistral", main_model, config
                )
            
            # Run coordination
            result = engine.coordinate(
                text=text,
                images=images,
                mode="performance",
                call_vision=call_vision,
                call_llm=call_llm,
                get_code_context=self._get_code_context,
            )
            
            if result.success:
                log.info(f"[AIChat] Performance mode complete: {result.total_duration:.1f}s, "
                        f"{len(result.worker_results)} workers")
                self._vision_response_received.emit(result.response)
            else:
                log.warning(f"[AIChat] Performance mode failed, falling back to single agent")
                self._process_message_single_agent(images, text, config)
            
        except Exception as e:
            log.error(f"[AIChat] Performance mode error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Error: {str(e)}")
    
    def _process_message_ultimate(self, images, text, config):
        """Process message with parallel multi-agent (Ultimate mode).
        
        Uses CoordinationEngine (ported from Claude Code's coordinatorMode.ts):
        - Vision Agent runs FIRST (sequential) when images present
        - Code + Context workers run in PARALLEL
        - All contexts aggregated via Scratchpad
        - Main Agent synthesizes final response
        - Full worker lifecycle tracking via AgentLifecycleManager
        """
        try:
            from src.config.settings import get_settings
            from src.coordinator.coordinator_system import CoordinationEngine, get_vision_store
            import concurrent.futures
            
            settings = get_settings()
            # ARCHITECTURE: Mistral is ALWAYS the main provider. Never read provider from settings.
            provider_name = "mistral"
            session_id = getattr(self, 'current_session_id', None) or "default-session"
            project_path = None
            if hasattr(self, '_pending_project_info') and self._pending_project_info:
                _, project_path, _ = self._pending_project_info
            
            log.info(f"[AIChat] Ultimate mode: Parallel multi-agent via CoordinationEngine ({config.parallel_workers} workers)")
            
            # Create coordination engine
            engine = CoordinationEngine(project_path=project_path, session_id=session_id)
            
            # Define vision callback
            def call_vision(imgs, txt):
                result = self._execute_vision_agent(imgs, txt, session_id)
                if result.get("success"):
                    return result.get("vision_context", {})
                # Fallback: direct Mistral vision via image pipeline
                pipeline_result = process_images_for_api(imgs, txt, provider="mistral")
                if pipeline_result["provider_supports_vision"]:
                    messages = pipeline_result["messages"]
                    vision_model = config.vision_model or "mistral-large-latest"
                    max_tok = calculate_max_tokens_for_mode(vision_model, config)
                    raw_response = self._call_mistral_with_context(messages, config.temperature, max_tok, vision_model)
                    return {"description": raw_response, "ocr_text": "", "raw": raw_response}
                return {"error": "Vision not available"}
            
            # Define main LLM callback — ALWAYS uses Mistral
            def call_llm(enhanced_prompt):
                main_model = config.main_agent_model or "mistral-large-latest"
                log.info(f"[AIChat] Ultimate mode: Main Agent using mistral/{main_model}")
                return self._call_main_agent_with_vision_context(
                    enhanced_prompt, "mistral", main_model, config
                )
            
            # Run coordination (engine handles parallel workers internally)
            result = engine.coordinate(
                text=text,
                images=images,
                mode="ultimate",
                call_vision=call_vision,
                call_llm=call_llm,
                get_code_context=self._get_code_context,
            )
            
            if result.success:
                log.info(f"[AIChat] Ultimate mode complete: {result.total_duration:.1f}s, "
                        f"{len(result.worker_results)} workers")
                self._vision_response_received.emit(result.response)
            else:
                log.warning(f"[AIChat] Ultimate mode failed, falling back to single agent")
                self._process_message_single_agent(images, text, config)
            
        except Exception as e:
            log.error(f"[AIChat] Ultimate mode error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Error: {str(e)}")
    
    # ==================== END PERFORMANCE MODE METHODS ====================
    
    # ==================== PLAN MODE: .md FILE GENERATION ====================
    
    def _generate_plan_file(self, user_text: str):
        """Generate a plan as a .md file instead of dumping it into the chat.
        
        Flow:
        1. Show thinking indicator
        2. Call Mistral LLM to produce a structured plan (markdown)
        3. Write the plan to {project_root}/plans/<slug>.md
        4. Show a brief notification in chat with the file path
        5. Open the file in the editor
        """
        import threading
        self._show_thinking_in_js()
        threading.Thread(
            target=self._generate_plan_file_worker,
            args=(user_text,),
            daemon=True,
        ).start()
    
    def _generate_plan_file_worker(self, user_text: str):
        """Background worker that calls LLM and writes plan .md file."""
        import re, time, os
        from pathlib import Path
        
        try:
            # Determine project root
            project_root = getattr(self, '_current_project_path', '') or os.getcwd()
            plans_dir = Path(project_root) / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            
            # Derive a short filename slug from the user text
            slug = re.sub(r'[^a-z0-9]+', '_', user_text[:60].lower()).strip('_') or 'plan'
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            plan_filename = f"{slug}_{timestamp}.md"
            plan_path = plans_dir / plan_filename
            
            # Build the LLM prompt
            system_prompt = (
                "You are an expert software architect. The user wants a detailed, "
                "actionable plan written as a Markdown document.\n\n"
                "Rules:\n"
                "- Start with a level-1 heading (# Title).\n"
                "- Break down tasks with numbered sub-headings (## Task 1, ## Task 2, ...).\n"
                "- For each task include: goal, files involved, key implementation details.\n"
                "- Keep it concise but thorough — no filler.\n"
                "- Do NOT wrap the whole output in a code fence. Output raw Markdown directly.\n"
                f"- Project root: {project_root}\n"
            )
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ]
            
            # Call Mistral (large model for quality plans)
            plan_content = self._call_mistral_with_context(
                messages,
                temperature=0.7,
                max_tokens=4096,
                model_id="mistral-large-latest",
            )
            
            if not plan_content or plan_content.startswith("Error"):
                log.error(f"[AIChat] Plan generation LLM error: {plan_content}")
                self._vision_response_received.emit(f"Plan generation failed: {plan_content}")
                return
            
            # Strip any accidental code-fence wrapping
            if plan_content.startswith("```"):
                # Remove leading ```markdown and trailing ```
                plan_content = re.sub(r'^```(?:markdown|md)?\s*\n?', '', plan_content)
                plan_content = re.sub(r'\n?```\s*$', '', plan_content)
            
            # Write the file
            plan_path.write_text(plan_content.strip() + '\n', encoding='utf-8')
            log.info(f"[AIChat] Plan file created: {plan_path}")
            
            # Notify chat with a brief message (not the full plan)
            rel_path = str(plan_path.relative_to(project_root)).replace('\\', '/')
            abs_path_str = str(plan_path).replace('\\', '/')
            notice = (
                f"Plan created: **{rel_path}**\n\n"
                f"Click to open: [{rel_path}]({abs_path_str})"
            )
            self._vision_response_received.emit(notice)
            
            # Open the file in editor
            self.open_file_requested.emit(str(plan_path))
            
        except Exception as e:
            log.error(f"[AIChat] Plan file generation error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Plan generation error: {str(e)}")
    
    def _generate_plan_file_with_images(self, user_text: str, images: list):
        """Generate a plan .md file from image analysis + user text.
        
        Flow:
        1. Send image(s) to Mistral vision to get a detailed description
        2. Use that description + user text to generate a structured plan
        3. Write .md file, show notification, open in editor
        """
        import re, time, os
        from pathlib import Path
        
        try:
            # Step 1: Analyze image(s) with Mistral vision
            log.info("[AIChat] Plan+Image Step 1: Analyzing image via Mistral vision")
            
            vision_prompt = (
                "Describe this image in detail. Focus on:\n"
                "- UI layout, components, sections\n"
                "- Colors, fonts, spacing\n"
                "- Functionality and interactive elements\n"
                "- Any text or labels visible\n"
                "- Overall design pattern / style\n\n"
                "Be thorough — this description will be used to create an implementation plan."
            )
            if user_text.strip():
                vision_prompt += f"\n\nUser's notes: {user_text}"
            
            # Build multimodal messages via image pipeline
            pipeline_result = process_images_for_api(images, vision_prompt, provider="mistral")
            messages = pipeline_result["messages"]
            
            image_description = self._call_mistral_with_context(
                messages,
                temperature=0.5,
                max_tokens=2000,
                model_id="mistral-large-latest",
            )
            
            if not image_description or image_description.startswith("Error"):
                log.error(f"[AIChat] Vision analysis failed: {image_description}")
                self._vision_response_received.emit(f"Plan generation failed (vision): {image_description}")
                return
            
            log.info(f"[AIChat] Plan+Image Step 2: Generating plan from description ({len(image_description)} chars)")
            
            # Step 2: Generate structured plan from the description
            project_root = getattr(self, '_current_project_path', '') or os.getcwd()
            
            system_prompt = (
                "You are an expert software architect. Based on the image analysis below, "
                "create a detailed, actionable implementation plan as a Markdown document.\n\n"
                "Rules:\n"
                "- Start with a level-1 heading (# Title).\n"
                "- Break down tasks with numbered sub-headings (## Task 1, ## Task 2, ...).\n"
                "- For each task include: goal, files to create/modify, key implementation details.\n"
                "- Include specific HTML/CSS/JS details based on the visual design.\n"
                "- Keep it concise but thorough \u2014 no filler.\n"
                "- Do NOT wrap the whole output in a code fence. Output raw Markdown directly.\n"
                f"- Project root: {project_root}\n"
            )
            
            plan_user_prompt = (
                f"=== Image Analysis ===\n{image_description}\n=== End Image Analysis ===\n\n"
            )
            if user_text.strip():
                plan_user_prompt += f"User request: {user_text}\n\n"
            plan_user_prompt += "Create a detailed implementation plan based on this design."
            
            plan_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": plan_user_prompt},
            ]
            
            plan_content = self._call_mistral_with_context(
                plan_messages,
                temperature=0.7,
                max_tokens=4096,
                model_id="mistral-large-latest",
            )
            
            if not plan_content or plan_content.startswith("Error"):
                log.error(f"[AIChat] Plan generation LLM error: {plan_content}")
                self._vision_response_received.emit(f"Plan generation failed: {plan_content}")
                return
            
            # Strip accidental code-fence wrapping
            if plan_content.startswith("```"):
                plan_content = re.sub(r'^```(?:markdown|md)?\s*\n?', '', plan_content)
                plan_content = re.sub(r'\n?```\s*$', '', plan_content)
            
            # Step 3: Write the file
            plans_dir = Path(project_root) / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            
            slug = re.sub(r'[^a-z0-9]+', '_', user_text[:60].lower()).strip('_') or 'image_plan'
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            plan_filename = f"{slug}_{timestamp}.md"
            plan_path = plans_dir / plan_filename
            
            plan_path.write_text(plan_content.strip() + '\n', encoding='utf-8')
            log.info(f"[AIChat] Plan file created from image: {plan_path}")
            
            # Brief notification in chat
            rel_path = str(plan_path.relative_to(project_root)).replace('\\', '/')
            abs_path_str = str(plan_path).replace('\\', '/')
            notice = (
                f"Plan created from image analysis: **{rel_path}**\n\n"
                f"Click to open: [{rel_path}]({abs_path_str})"
            )
            self._vision_response_received.emit(notice)
            
            # Open in editor
            self.open_file_requested.emit(str(plan_path))
            
        except Exception as e:
            log.error(f"[AIChat] Plan+Image generation error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Plan generation error: {str(e)}")
    
    # ==================== END PLAN MODE ====================
    
    def _process_text_message_through_performance(self, text, config):
        """Process text-only message through performance mode system.
        
        ARCHITECTURE: Mistral is the ONLY provider.
        All modes route through single agent with the mode's configured model.
        
        Args:
            text: User message text
            config: PerformanceConfig for current mode
        """
        try:
            from src.config.settings import get_settings
            from PyQt6.QtCore import QThread
            
            settings = get_settings()
            provider_name = "mistral"
            model_id = config.main_agent_model or "mistral-small-latest"
            session_id = (settings.get("ai", "session_id") or "default").strip()
            
            log.info(f"[AIChat] Text routing: provider={provider_name}, model={model_id}, mode={self._get_performance_mode_from_settings()}")
            
            # Show thinking indicator
            self._show_thinking_in_js()
            
            # All modes: Single agent with mode's model
            threading.Thread(
                target=self._process_text_single_agent,
                args=(text, config, provider_name, model_id, session_id),
                daemon=True
            ).start()
                
        except Exception as e:
            log.error(f"[AIChat] Text message performance routing error: {e}", exc_info=True)
            # Fallback to standard path
            context = ""
            if self._get_code_context:
                context = self._get_code_context()
            self.message_sent.emit(text, context)
    
    def _process_text_single_agent(self, text, config, provider_name, model_id, session_id):
        """Process text message with single agent (ALL modes).
        
        ARCHITECTURE: Mistral is the ONLY provider.
        - Efficient: Mistral Small
        - Auto: Mistral Small/Medium/Large auto-select based on query
        - Performance: Mistral Medium
        - Ultimate: Mistral Large
        """
        try:
            perf_mode_str = self._get_performance_mode_from_settings()
            perf_mode = get_performance_mode(perf_mode_str)
            
            provider_name = "mistral"
            
            if perf_mode == PerformanceMode.AUTO:
                # Auto mode: smart Mistral model selection based on query complexity
                model_id = self._auto_select_mistral_model(text)
                log.info(f"[AIChat] Auto mode text: auto-selected {model_id}")
            else:
                # All other modes: use the config's model directly
                model_id = config.main_agent_model or "mistral-small-latest"
                log.info(f"[AIChat] {perf_mode.value} mode text: {model_id}")
            
            max_tokens = calculate_max_tokens_for_mode(model_id, config)
            log.info(f"[AIChat] Single agent text: provider={provider_name}, model={model_id}, max_tokens={max_tokens}")
            
            self._call_agent_and_respond(text, provider_name, model_id, max_tokens, config.temperature)
            
        except Exception as e:
            log.error(f"[AIChat] Single agent text error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Error: {str(e)}")
    
    def _process_text_performance(self, text, config, provider_name, model_id, session_id):
        """Process text message in Performance mode.
        
        FIXED: No more DeepSeek supporter pre-analysis.
        The supporter was adding 30-60s overhead and bloating the prompt.
        
        Now: User message goes DIRECTLY to Mistral Medium via the agentic
        tool loop. Performance mode = mistral-medium (faster, cheaper than large).
        """
        try:
            main_model_id = "mistral-medium-latest"
            max_tokens = calculate_max_tokens_for_mode(main_model_id, config)
            log.info(f"[AIChat] Performance mode: Direct to agentic loop with {main_model_id}, max_tokens={max_tokens}")
            self._call_agent_and_respond(text, "mistral", main_model_id, max_tokens, config.temperature)
        except Exception as e:
            log.error(f"[AIChat] Performance mode error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Error: {str(e)}")
    
    def _auto_select_mistral_model(self, text: str) -> str:
        """Auto-select Mistral model based on query complexity.
        
        Auto mode smart routing:
        - Pure greetings/acks only -> mistral-small-latest (fast, cheap)
        - Coding / tool-requiring tasks -> mistral-medium-latest minimum
        - Complex/long queries -> mistral-large-latest (maximum quality)
        
        IMPORTANT: mistral-small has only 32K context (hist_cap=4K) which is
        too small for ANY coding task.  Reserve it ONLY for greetings.
        
        Returns:
            Mistral model ID string
        """
        import re
        text_stripped = text.strip()
        text_lower = text_stripped.lower()
        word_count = len(text_stripped.split())
        
        # ── "Continue the task" auto-messages always get large model ───────
        # These carry forward accumulated context and need maximum headroom.
        if text_lower.startswith("continue the task") or text_lower.startswith("continue task"):
            return "mistral-large-latest"
        
        # ── Pure greetings/acks → small (same patterns as _is_simple_query) ──
        greeting_patterns = [
            r'^(hi|hello|hey|yo|sup|greetings)[!.\s]*$',
            r'^(thanks?|thank you|thx)[!.\s]*$',
            r'^(ok|okay|got it|sure|alright)[!.\s]*$',
            r'^(bye|goodbye|see you|good night)[!.\s]*$',
            r'^(good (morning|afternoon|evening))[!.\s]*$',
            r'^how are you[?!.\s]*$',
            r'^what\'?s up[?!.\s]*$',
        ]
        for pattern in greeting_patterns:
            if re.match(pattern, text_lower):
                return "mistral-small-latest"
        
        # ── Messages with code blocks or file references → large ──────────
        if '```' in text_stripped or '`' in text_stripped:
            return "mistral-large-latest"
        
        # ── Complex indicators: code keywords, debugging, architecture ────
        complex_keywords = [
            "debug", "error", "fix", "implement", "refactor", "architecture",
            "explain", "analyze", "review", "optimize", "performance",
            "function", "class", "module", "database", "api", "security",
            "algorithm", "design pattern", "migration", "deploy",
            "traceback", "exception", "stack trace", "bug",
            "create", "build", "make", "write", "code", "file", "html",
            "css", "js", "python", "react", "tailwind", "plan",
        ]
        complex_match = sum(1 for kw in complex_keywords if kw in text_lower)
        
        # High complexity: many keywords or very long query
        if complex_match >= 3 or word_count > 80:
            return "mistral-large-latest"
        
        # Medium complexity: any coding keyword or moderate length
        if complex_match >= 1 or word_count > 15:
            return "mistral-medium-latest"
        
        # Default: medium for anything that isn't a greeting
        # mistral-small (32K) is too tight for tool-based interactions
        return "mistral-medium-latest"
    
    def _is_simple_query(self, text: str) -> bool:
        """Check if query is simple enough to skip multi-agent collaboration.
        
        Simple queries: greetings, short questions, continuation commands,
        file creation/editing tasks, common coding commands.
        Complex queries: architecture design, deep debugging, long explanations.
        
        The DeepSeek Reasoner supporter adds ~60s overhead per call.
        Only use it for genuinely complex reasoning tasks.
        
        Returns:
            True if simple (use single agent), False if complex (use multi-agent)
        """
        # Strip and check
        text = text.strip()
        text_lower = text.lower()
        
        # Very short messages (greetings, etc.)
        if len(text) < 15:
            return True
        
        # Continuation commands should ALWAYS skip multi-agent
        continuation_patterns = [
            "continue the task", "continue working", "continue from where",
            "keep going", "proceed with", "remaining todos",
            "continue the implementation", "continue building",
        ]
        for cp in continuation_patterns:
            if cp in text_lower:
                return True
        
        # Word count check
        word_count = len(text.split())
        if word_count < 5:
            return True
        
        # File creation/editing tasks — single agent is enough
        # These keywords ANYWHERE in text mean it's a direct coding task
        coding_action_keywords = [
            "create", "make", "build", "write", "generate", "fix",
            "update", "edit", "modify", "add", "remove", "delete",
            "rename", "move", "copy", "install", "setup", "init",
            "plan", "implement", "code", "file", ".md", ".html",
            ".css", ".js", ".py", ".json", ".ts", ".tsx",
        ]
        for kw in coding_action_keywords:
            if kw in text_lower:
                return True
        
        # Common simple patterns
        simple_patterns = [
            "hi", "hello", "hey", "thanks", "thank you", "good morning",
            "good afternoon", "good evening", "bye", "goodbye", "see you",
            "how are you", "what's up", "help me", "please",
        ]
        
        for pattern in simple_patterns:
            if text_lower.startswith(pattern) or text_lower == pattern:
                return True
        
        # If question mark and short, might be simple
        if '?' in text and word_count < 10:
            simple_questions = ["how", "what", "where", "when", "who", "why"]
            first_word = text_lower.split()[0] if text_lower.split() else ""
            if first_word in simple_questions and word_count < 8:
                return True
        
        # Short-to-medium messages (< 30 words) are unlikely to need deep reasoning
        if word_count < 30:
            return True
        
        # Default: complex query, use multi-agent
        return False
    
    def _process_text_ultimate(self, text, config, provider_name, session_id):
        """Process text message in Ultimate mode.
        
        FIXED: No more DeepSeek supporter pre-analysis.
        The supporter was adding 60s overhead and bloating the prompt,
        causing Mistral API timeouts.
        
        Now: User message goes DIRECTLY to Mistral Large via the agentic
        tool loop (same as Qoder/VS Code architecture).
        The quality comes from using mistral-large + full tool suite,
        NOT from pre-analysis by another LLM.
        """
        try:
            main_model_id = "mistral-large-latest"
            max_tokens = calculate_max_tokens_for_mode(main_model_id, config)
            log.info(f"[AIChat] Ultimate mode: Direct to agentic loop with {main_model_id}, max_tokens={max_tokens}")
            self._call_agent_and_respond(text, "mistral", main_model_id, max_tokens, config.temperature)
        except Exception as e:
            log.error(f"[AIChat] Ultimate mode error: {e}", exc_info=True)
            self._vision_response_received.emit(f"Error: {str(e)}")
    
    def _call_llm_direct(self, prompt: str, provider: str, model_id: str, temperature: float, max_tokens: int) -> str:
        """Call LLM API directly.
        
        Args:
            prompt: The prompt to send
            provider: 'mistral' (only provider)
            model_id: Model identifier
            temperature: Temperature setting
            max_tokens: Maximum tokens to generate
            
        Returns:
            Response string or error message
        """
        try:
            messages = [{"role": "user", "content": prompt}]
            return self._call_mistral_with_context(messages, temperature, max_tokens, model_id)
                
        except Exception as e:
            log.error(f"[AIChat] Direct LLM call failed: {e}", exc_info=True)
            return f"Error: {str(e)}"
    
    def _call_agent_and_respond(self, text, provider_name, model_id, max_tokens, temperature):
        """Call agent with specified model and append response to chat.
        
        This uses the model_changed signal to update the agent_bridge
        with the performance mode's selected model before sending the message.
        Also saves the token_multiplier to settings for agent_bridge to use.
        """
        try:
            from src.config.settings import get_settings
            
            settings = get_settings()
            
            # Calculate the token multiplier from max_tokens
            # We need to get the base max_output_tokens from model_limits to find the multiplier
            try:
                from src.ai.model_limits import get_model_limits
                base_limits = get_model_limits(model_id)
                base_max_tokens = base_limits.max_output_tokens
                token_multiplier = max_tokens / base_max_tokens if base_max_tokens > 0 else 1.0
            except Exception:
                # Fallback: calculate from the perf string
                token_multiplier = max_tokens / 4096.0
            
            # Save token_multiplier to settings so agent_bridge can read it
            settings.set("ai", "token_multiplier", str(token_multiplier))
            
            log.info(f"[AIChat] Token multiplier: {token_multiplier}x (max_tokens: {max_tokens})")
            
            # Use the model_changed signal to update agent_bridge
            # This is the proper way to switch models (same as dropdown selection)
            perf = str(int(token_multiplier * 10) / 10) + "x"  # e.g., "0.3x", "1.6x"
            cost = f"${temperature}/msg"  # Approximate cost indicator
            
            log.info(f"[AIChat] Emitting model_changed signal: {model_id} (provider: {provider_name})")
            
            # Emit signal to update agent_bridge (goes through main_window._on_model_changed)
            self.model_changed.emit(model_id, perf, cost)
            
            # Small delay to ensure settings are updated before sending message
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
            
            # Now send the message through standard path
            context = ""
            if self._get_code_context:
                context = self._get_code_context()
            
            log.info(f"[AIChat] Sending message with model: {model_id}, token_multiplier: {token_multiplier}x")
            self.message_sent.emit(text, context)
            
        except Exception as e:
            log.error(f"[AIChat] Agent call error: {e}", exc_info=True)
            # Fallback to standard path
            context = ""
            if self._get_code_context:
                context = self._get_code_context()
            self.message_sent.emit(text, context)
    
    def _fallback_direct_vision_api(self, images, text, provider_name, model_id):
        """Fallback to direct vision API if Vision Agent fails.
        
        This maintains backward compatibility with the original implementation.
        """
        # Reuse the original vision processing logic
        # This is a simplified version - you can copy the full original code here
        try:
            log.warning("[AIChat] Using fallback direct vision API")
            
            temperature = 0.7
            max_tokens = 2000
            
            if provider_name == "mistral":
                content_parts = [{"type": "text", "text": text}]
                for img in images:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": img.get("data", "")
                    })
                
                messages = [{"role": "user", "content": content_parts}]
                api_key = os.getenv("MISTRAL_API_KEY", "")
                
                response = requests.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id or "mistral-small-latest", "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                    timeout=(30, 180)
                )
                
                if response.status_code == 200:
                    data = response.json()
                    result = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                    self._vision_response_received.emit(result)
                else:
                    self._vision_response_received.emit(f"Error: {response.status_code}")
            else:
                self._vision_response_received.emit("Error: Vision Agent failed and no fallback provider available")
                
        except Exception as e:
            log.error(f"[AIChat] Fallback vision API failed: {e}")
            self._vision_response_received.emit(f"Error: {str(e)}")
    
    def _show_thinking_in_js(self):
        """Show thinking indicator in JS chat."""
        try:
            js_code = "if(window.showThinkingIndicator) window.showThinkingIndicator();"
            self._view.page().runJavaScript(js_code)
        except Exception:
            pass
    
    def _on_vision_response(self, response: str):
        """Handle vision response and display in chat.
        
        CRITICAL: Must call _onGenerationComplete() in JS to:
        - Reset _isGenerating = false
        - Show send button, hide stop button
        - Release input for next user prompt
        - Process any queued messages
        """
        try:
            # Hide thinking indicator
            js_code = "if(window.hideThinkingIndicator) window.hideThinkingIndicator();"
            self._view.page().runJavaScript(js_code)
            
            # Add response as assistant message
            js_code = f"if(window.appendMessage) window.appendMessage({json.dumps(response)}, 'assistant', true);"
            self._view.page().runJavaScript(js_code)
            
            # CRITICAL: Signal generation complete to release UI
            js_code = "if(window._onGenerationComplete) window._onGenerationComplete();"
            self._view.page().runJavaScript(js_code)
            
            # Sync vision exchange to agent_bridge conversation history
            # so follow-up text messages have context about what was in the image
            user_text = getattr(self, '_vision_user_text', None) or 'Analyze this image'
            self.vision_history_sync.emit(user_text, response)
            self._vision_user_text = None
            
            # Show Windows push notification for completed vision response
            try:
                from src.utils.notifications import show_toast_notification
                preview = response[:80] + '...' if len(response) > 80 else response
                show_toast_notification("Cortex AI", f"Vision analysis complete: {preview}")
            except Exception:
                pass
            
            # Cleanup thread after response
            self._cleanup_vision_thread()
        except Exception as e:
            log.error(f"[AIChat] Vision response handling error: {e}")
    
    def _on_vision_error(self, error: str):
        """Handle vision error."""
        try:
            # Hide thinking
            js_code = "if(window.hideThinkingIndicator) window.hideThinkingIndicator();"
            self._view.page().runJavaScript(js_code)
            
            # Add error as assistant message
            js_code = f"if(window.appendMessage) window.appendMessage({json.dumps('Error: ' + error)}, 'assistant', true);"
            self._view.page().runJavaScript(js_code)
            
            # CRITICAL: Signal generation complete to release UI
            js_code = "if(window._onGenerationComplete) window._onGenerationComplete();"
            self._view.page().runJavaScript(js_code)
            
            # Cleanup thread after error
            self._cleanup_vision_thread()
        except Exception as e:
            log.error(f"[AIChat] Vision error handling error: {e}")
    
    def _cleanup_vision_thread(self):
        """Cleanup vision thread after worker finishes."""
        if hasattr(self, '_vision_thread') and self._vision_thread:
            log.debug("Cleaning up vision thread...")
            self._vision_thread.quit()
            self._vision_thread.wait(3000)  # Wait up to 3s for thread to finish
    
    def _on_load_full_chat_requested(self, conversation_id: str):
        """Handle lazy load request for full chat messages from JS."""
        try:
            # Load full chat data from SQLite via bridge (returns JSON string)
            full_chat_json_str = self._bridge.load_full_chat_from_sqlite(conversation_id)
            
            # Parse it so we can pass components to the JS function signature: (id, messages)
            import json
            chat_data = json.loads(full_chat_json_str)
            messages = chat_data.get('messages', [])
            
            safe_id = json.dumps(conversation_id)
            safe_msgs = json.dumps(messages)
            
            # Direct function call to JS global
            js_code = f"if(window.chatFullLoadHandler) window.chatFullLoadHandler({safe_id}, {safe_msgs});"
            
            self._view.page().runJavaScript(js_code)
            log.info(f"âœ“ Restored {len(messages)} messages for chat {conversation_id}")
        except Exception as e:
            log.error(f"âœ— Failed to handle chat load for {conversation_id}: {e}")

    def _on_search_files(self, query: str):
        """Search for files matching the query for @ citations."""
        if not self._project_root:
            return
            
        try:
            self._file_search_worker = FileSearchWorker(self._project_root, query, 10)
            self._file_search_worker.results_ready.connect(self._on_file_search_results)
            self._file_search_worker.start()
        except Exception as e:
            log.error(f"Error starting file search: {e}")
    
    def _on_file_search_results(self, results: list):
        """Handle file search results from background thread."""
        js_results = json.dumps(results)
        self._view.page().runJavaScript(f"if(window.onFileSearchResults) window.onFileSearchResults({js_results});")
        if self._file_search_worker:
            self._file_search_worker.deleteLater()
            self._file_search_worker = None

    def set_project_root(self, path: str):
        """Set the project root for file searching."""
        self._project_root = path
        
        # Sync global memories to this project (cross-project sharing)
        self._sync_global_memories_to_project(path)
    
    def _sync_global_memories_to_project(self, project_root: str):
        """Sync global memories to project in background thread."""
        def _runner():
            try:
                from src.agent.src.memdir.crossProjectMemory import get_cross_project_manager
                
                manager = get_cross_project_manager()
                report = manager.sync_memories_to_project(project_root, auto_merge=True)
                
                if report.global_memories_loaded > 0:
                    log.info(f"[AI_CHAT] Synced {report.global_memories_loaded} global memories to project")
            except Exception as e:
                log.debug(f"[AI_CHAT] Cross-project memory sync failed (non-critical): {e}")
        
        # Run in background to avoid blocking UI
        import threading
        threading.Thread(target=_runner, daemon=True).start()

    def set_code_context_callback(self, callback):
        """Used by main_window to provide editor code context."""
        self._get_code_context = callback

    def set_theme(self, is_dark: bool, retry_count: int = 0):
        """Update the UI theme. Matches MainWindow naming convention."""
        import logging as _log
        self._is_dark = is_dark
        js_bool = 'true' if is_dark else 'false'
        
        # Only log on first attempt to reduce log spam
        if retry_count == 0:
            _log.info(f"[AI_CHAT] Setting theme to {'dark' if is_dark else 'light'}")
        
        def on_js_result(result):
            if result == 'success':
                _log.info(f"[AI_CHAT] Theme set successfully to {'dark' if is_dark else 'light'}")
            elif retry_count < 5:  # Reduced from 10 retries to 5
                # Retry with increasing delay: 200ms, 400ms, 600ms...
                delay = 200 * (retry_count + 1)
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(delay, lambda: self.set_theme(is_dark, retry_count + 1))
            else:
                _log.warning(f"[AI_CHAT] setTheme failed after {retry_count + 1} attempts")
        
        js_code = f"""
        (function() {{
            try {{
                if (typeof window.setTheme === 'function') {{
                    window.setTheme({js_bool});
                    return 'success';
                }} else {{
                    return 'not_found';
                }}
            }} catch (e) {{
                return 'error: ' + e.message;
            }}
        }})()
        """
        self._view.page().runJavaScript(js_code, on_js_result)

    def update_theme(self, is_dark: bool):
        """Alias for set_theme."""
        self.set_theme(is_dark)

    def on_error(self, error_message: str):
        """Handle an error from the AI agent."""
        safe_error = json.dumps(error_message)
        self._view.page().runJavaScript(f"if(window.onError) window.onError({safe_error});")

    def show_thinking(self):
        """Show the thinking indicator."""
        self._view.page().runJavaScript("if(window.showThinking) window.showThinking();")

    def _on_permission_request(self, command: str, warning: str, files_json: str):
        """Show a permission-request card in the chat UI before a dangerous command runs."""
        import json as _json
        safe_cmd  = _json.dumps(command)
        safe_warn = _json.dumps(warning)
        self._view.page().runJavaScript(
            f"if(window.showPermissionCard) window.showPermissionCard({safe_cmd}, {safe_warn}, {files_json});"
        )

    def hide_thinking(self):
        """Hide the thinking indicator."""
        self._view.page().runJavaScript("if(window.hideThinking) window.hideThinking();")

    def update_todos(self, todos: list, main_task: str = ""):
        """Update the todo list in the UI."""
        import logging
        log = logging.getLogger('cortex.chat')
        log.info(f"[TODO] update_todos called with {len(todos)} todos, main_task: '{main_task}'")
        
        status_mapping = {
            'pending': 'PENDING',
            'in_progress': 'IN_PROGRESS',
            'completed': 'COMPLETE',
            'cancelled': 'CANCELLED'
        }
        
        formatted_todos = []
        for todo in todos:
            formatted_todo = {
                'id': todo.get('id', todo.get('description', '')),
                'content': todo.get('content', todo.get('description', '')),
                'activeForm': todo.get('activeForm', todo.get('content', todo.get('description', ''))),
                'status': status_mapping.get(todo.get('status', 'PENDING').lower(), todo.get('status', 'PENDING'))
            }
            formatted_todos.append(formatted_todo)
        
        safe_todos = json.dumps(formatted_todos)
        safe_task = json.dumps(main_task)
        self._view.page().runJavaScript(f"if(window.updateTodos) window.updateTodos({safe_todos}, {safe_task});")

    def show_tool_activity(self, tool_type: str, info: str, status: str):
        """Show tool execution progress with structured info.
        
        Args:
            tool_type: Type of tool (e.g., 'read_file', 'write_file', 'search')
            info: JSON string with structured tool details
            status: Status of execution ('running', 'complete', 'error')
        """
        activity = {
            'tool_type': tool_type,
            'info': info,
            'status': status
        }
        safe_activity = json.dumps(activity)
        log.debug(f"[ToolActivity] {tool_type} [{status}] {info[:120]}")
        self._view.page().runJavaScript(f"if(window.showToolActivity) window.showToolActivity({safe_activity});")

    def show_directory_contents(self, data: dict):
        """Show directory contents for the 'ls' command."""
        safe_data = json.dumps(data)
        self._view.page().runJavaScript(f"if(window.showDirectoryContents) window.showDirectoryContents({safe_data});")

    def show_tool_summary(self, summary_data: dict):
        """Show professional tool execution summary.
        
        Args:
            summary_data: Structured dict with file_writes, file_reads, commands, errors, other
        """
        safe_data = json.dumps(summary_data)
        self._view.page().runJavaScript(f"if(window.showToolSummary) window.showToolSummary({safe_data});")

    def add_system_message(self, message: str):
        """Append a system notification message to the chat view."""
        self._view.page().runJavaScript(f"if(window.appendMessage) window.appendMessage({json.dumps(message)}, 'system');")

    def on_agent_status_update(self, status_type: str, message: str):
        """Show an inline recovery-status note in chat (compacting / retrying / failover)."""
        safe_type = json.dumps(status_type)
        safe_msg  = json.dumps(message)
        self._view.page().runJavaScript(
            f"if(window.onAgentStatus) window.onAgentStatus({safe_type}, {safe_msg});"
        )

    def on_context_budget_update(self, used: int, total: int, provider: str):
        """Push real-time token budget data to the UI budget bar."""
        self._view.page().runJavaScript(
            f"if(window.onContextBudgetUpdate) window.onContextBudgetUpdate({used}, {total}, {json.dumps(provider)});"
        )

    def on_turn_limit_hit(self, pending_todos: list):
        """Show a 'Continue?' banner when the agent has unfinished todos."""
        safe_todos = json.dumps(pending_todos)
        self._view.page().runJavaScript(
            f"if(window.onTurnLimitHit) window.onTurnLimitHit({safe_todos});"
        )

    def show_permission_card(self, request_id: str, html_card: str):
        """Display a permission card in the chat (OpenCode enhancement)."""
        import json
        safe_request_id = json.dumps(request_id)
        safe_html = json.dumps(html_card)
        self._view.page().runJavaScript(
            f"if(window.showPermissionCard) window.showPermissionCard({safe_request_id}, {safe_html});"
        )

    def show_testing_card(self, test_info: dict):
        """Display a testing status card in the chat."""
        import json
        safe_info = json.dumps(test_info)
        self._view.page().runJavaScript(
            f"if(window.showTestingCard) window.showTestingCard({safe_info});"
        )

    def show_test_results(self, results: dict):
        """Display test results in the chat."""
        import json
        safe_results = json.dumps(results)
        self._view.page().runJavaScript(
            f"if(window.showTestResults) window.showTestResults({safe_results});"
        )

    def _apply_project_info(self, name: str, path: str, chats_json: str = "[]"):
        import json
        safe_name = json.dumps(name)
        safe_path = json.dumps(path)
        log.info(f'set_project_info called: name={name}, path={path}, chats_json length={len(chats_json)}')
        # Ensure chats_json is passed correctly to JS (avoid double-stringified data)
        try:
            # Parse it first if it's a string, then JSON-ify properly for the JS call
            chats_data = json.loads(chats_json) if isinstance(chats_json, str) else chats_json
            safe_chats = json.dumps(chats_data)
            log.info(f'Parsed {len(chats_data) if isinstance(chats_data, list) else 0} chats for JS')
        except Exception as e:
            log.warning(f'Failed to parse chats_json: {e}')
            safe_chats = "[]"
        js_code = (
            f"if(window.trySetProjectInfoWithChats) window.trySetProjectInfoWithChats({safe_name}, {safe_path}, {safe_chats}); "
            f"else if(window.setProjectInfoWithChats) window.setProjectInfoWithChats({safe_name}, {safe_path}, {safe_chats}); "
            f"else if(window.trySetProjectInfo) window.trySetProjectInfo({safe_name}, {safe_path}); "
            f"else window._pendingProjectInfoWithChats = {{ name: {safe_name}, path: {safe_path}, chatsJson: {safe_chats} }};"
        )
        log.info(f'Calling JavaScript: trySetProjectInfoWithChats(...)')
        self._project_info_applied = True
        
        # Smart retry: only retry if JS function wasn't available on first call
        def _on_first_result(result):
            if result is None:
                # JS function wasn't found, retry once after 500ms
                log.info('[AI_CHAT] JS function not ready, scheduling single retry...')
                QTimer.singleShot(500, lambda: self._view.page().runJavaScript(js_code))
        
        self._view.page().runJavaScript(js_code, _on_first_result)
        
        # Emit signal to refresh sidebar chat list after project info is applied
        QTimer.singleShot(1000, self.chat_list_updated.emit)

    def clear_chat(self):
        """Clear the chat window."""
        self._view.page().runJavaScript("if(window.clearChat) window.clearChat();")

    def set_input_text(self, text: str):
        """Set the input field text."""
        import json
        safe_text = json.dumps(text)
        self._view.page().runJavaScript(f"if(window.setInputText) window.setInputText({safe_text});")

    def send_message(self):
        """Trigger sending the current message."""
        self._view.page().runJavaScript("if(window.sendMessage) window.sendMessage();")

    def set_project_info(self, name: str, path: str, chats_json: str = "[]"):
        """Initialize chat with project details and history."""
        # Always remember latest project info in case the page isn't loaded yet
        self._pending_project_info = (name, path, chats_json)
        self._current_project_path = path
        self._project_info_applied = False  # Reset for new project
        if not getattr(self, '_page_loaded', False):
            log.info('Chat page not loaded yet; deferring project info')
            return
        self._apply_project_info(name, path, chats_json)

    def load_chats_for_project(self, project_path: str) -> str:
        """
        Load all chat metadata for a specific project path.
        Returns: JSON string array of chat metadata or empty array.
        """
        try:
            from src.core.chat_history import get_chat_history
            
            history = get_chat_history()
            conversations = history.get_conversations(project_path)
            
            log.info(f'ðŸ“¥ Found {len(conversations) if conversations else 0} conversations for project {project_path}')
            
            if not conversations:
                log.warning(f'No chats found in database for project {project_path}')
                return "[]"
            
            # Convert to format expected by JS
            result = []
            for conv in conversations:
                result.append({
                    'id': conv.get('conversation_id') or conv.get('id'),
                    'title': conv.get('title'),
                    'created_at': conv.get('created_at'),
                    'message_count': conv.get('message_count', 0),
                    'messages': [],  # Empty - lazy loaded
                    'loaded': False
                })
            
            json_result = json.dumps(result)
            log.info(f'âœ… Loaded {len(result)} chat(s) for project {project_path} ({len(json_result)} chars)')
            return json_result
            
        except Exception as e:
            log.error(f'âŒ Failed to load chats for project {project_path}: {e}')
            import traceback
            log.error(traceback.format_exc())
            return "[]"

    def on_file_edited_diff(self, path: str, original: str, new_content: str):
        """Called when the agent edits a file to show +/- diff line counts."""
        import difflib
        orig_lines = original.splitlines()
        new_lines  = new_content.splitlines()
        diff = list(difflib.ndiff(orig_lines, new_lines))
        added   = sum(1 for l in diff if l.startswith('+ '))
        removed = sum(1 for l in diff if l.startswith('- '))
        p = json.dumps(path)
        self._view.page().runJavaScript(f"if(window.addChangedFile) addChangedFile({p}, {added}, {removed}, 'M');")

    def show_diff_card(self, file_path: str, original: str, new_content: str):
        """Show a diff viewer card in chat after AI edits a file."""
        import difflib, uuid
        try:
            orig_lines = original.splitlines()
            new_lines  = new_content.splitlines()
            ud = list(difflib.unified_diff(orig_lines, new_lines))
            added   = sum(1 for l in ud if l.startswith('+') and not l.startswith('+++'))
            removed = sum(1 for l in ud if l.startswith('-') and not l.startswith('---'))
            # Build structured line list for JS (skip the --- +++ header lines)
            lines_data = []
            for l in ud[2:]:
                if l.startswith('+') and not l.startswith('+++'):
                    lines_data.append({'type': 'added',   'text': l[1:].rstrip()})
                elif l.startswith('-') and not l.startswith('---'):
                    lines_data.append({'type': 'removed', 'text': l[1:].rstrip()})
                elif l.startswith('@@'):
                    lines_data.append({'type': 'info',    'text': l.rstrip()})
                else:
                    lines_data.append({'type': 'context', 'text': (l[1:] if l.startswith(' ') else l).rstrip()})
            card_id = f"diff-card-{uuid.uuid4().hex[:8]}"
            js = (f"if(window.showDiffCard) window.showDiffCard({json.dumps(card_id)}, "
                  f"{json.dumps(file_path)}, {json.dumps(lines_data)}, {added}, {removed});"
                  f" else console.error('[DiffCard] window.showDiffCard NOT FOUND!');")
            log.debug(f"[DiffCard] Calling showDiffCard card_id={card_id} +{added} -{removed}")
            self._view.page().runJavaScript(js)
        except Exception as e:
            log.debug(f"[DiffCard] Failed to show diff card: {e}")

    # ============================================================
    # FILE OPERATION CARDS (Create/Edit with animation)
    # ============================================================
    
    def show_file_creating_card(self, file_path: str) -> str:
        """Show a 'Creating file...' card with pulse animation. Returns card ID."""
        import uuid
        card_id = f"file-op-{uuid.uuid4().hex[:8]}"
        p = json.dumps(file_path)
        js = f"if(window.showFileOperationCard) window.showFileOperationCard({json.dumps(card_id)}, {p}, 'create'); else console.error('[FileOpCard] window.showFileOperationCard NOT FOUND!');"
        log.debug(f"[FileOpCard] Calling JS showFileOperationCard with card_id={card_id}")
        self._view.page().runJavaScript(js)
        return card_id
    
    def show_file_editing_card(self, file_path: str) -> str:
        """Show an 'Editing file...' card with pulse animation. Returns card ID."""
        import uuid
        card_id = f"file-op-{uuid.uuid4().hex[:8]}"
        p = json.dumps(file_path)
        js = f"if(window.showFileOperationCard) window.showFileOperationCard({json.dumps(card_id)}, {p}, 'edit'); else console.error('[FileOpCard] window.showFileOperationCard NOT FOUND!');"
        log.debug(f"[FileOpCard] Calling JS showFileOperationCard(edit) with card_id={card_id}")
        self._view.page().runJavaScript(js)
        return card_id
    
    def complete_file_creating_card(self, card_id: str, file_path: str, content: str):
        """Transform 'Creating...' card to show completed file with line count."""
        js = f"if(window.completeFileCreatingCard) window.completeFileCreatingCard({json.dumps(card_id)}, {json.dumps(file_path)}, {json.dumps(content)}); else console.error('[FileOpCard] window.completeFileCreatingCard NOT FOUND!');"
        log.debug(f"[FileOpCard] Calling JS completeFileCreatingCard with card_id={card_id}, contentLen={len(content)}")
        self._view.page().runJavaScript(js)
    
    def complete_file_editing_card(self, card_id: str, file_path: str, original: str, new_content: str):
        """Transform 'Editing...' card to show completed edit with line count."""
        js = f"if(window.completeFileEditingCard) window.completeFileEditingCard({json.dumps(card_id)}, {json.dumps(file_path)}, {json.dumps(original)}, {json.dumps(new_content)}); else console.error('[FileOpCard] window.completeFileEditingCard NOT FOUND!');"
        log.debug(f"[FileOpCard] Calling JS completeFileEditingCard with card_id={card_id}, newContentLen={len(new_content)}")
        self._view.page().runJavaScript(js)

    def dismiss_file_op_card(self, card_id: str):
        """Remove a stale file operation card (e.g. duplicate from retry)."""
        js = f"if(window.dismissFileOpCard) window.dismissFileOpCard({json.dumps(card_id)});"
        log.debug(f"[FileOpCard] Dismissing stale card: {card_id}")
        self._view.page().runJavaScript(js)

    def emit_directory_tree(self, root_path: str, listing_text: str):
        """Send hierarchical tree data to JS for tree card rendering."""
        items = self._parse_listing(root_path, listing_text)
        root_js  = json.dumps(root_path)
        items_js = json.dumps(items)
        self._view.page().runJavaScript(f"if(window.showDirectoryTree) window.showDirectoryTree({root_js}, {items_js});")

    def _parse_listing(self, root_path: str, text: str) -> list:
        """Convert list_directory output to hierarchical tree structure."""
        import re
        lines = [l for l in text.split('\n') if l.strip()]
        items = []
        root = root_path.rstrip('/\\')
        sep = '\\' if '\\' in root else '/'
        parent_stack = [root]

        for i, line in enumerate(lines):
            leading = len(line) - len(line.lstrip())
            depth = leading // 2
            stripped = line.strip()
            if not stripped: continue

            is_dir = stripped.startswith('ðŸ“') or stripped.endswith('/')
            name = stripped
            for prefix in ['â”œâ”€â”€', 'â””â”€â”€', 'â”‚']:
                name = name.replace(prefix, '')
            name = name.lstrip('ðŸ“ðŸ“„').strip()

            size = ''
            desc = ''
            m = re.match(r'^(.*?)\s*\(([^)]+)\)\s*(?:-\s*(.+))?$', name)
            if m:
                name = m.group(1).strip().rstrip('/')
                size = m.group(2)
                desc = m.group(3) or ''
            else:
                name = name.rstrip('/')

            while len(parent_stack) > depth + 1:
                parent_stack.pop()
            current_path = sep.join(parent_stack) + sep + name

            is_last = True
            if i < len(lines) - 1:
                next_leading = len(lines[i + 1]) - len(lines[i + 1].lstrip())
                if (next_leading // 2) >= depth: is_last = False

            items.append({'name': name, 'path': current_path, 'size': size, 'description': desc, 'isDir': is_dir, 'isLast': is_last, 'depth': depth})
            if is_dir:
                if len(parent_stack) <= depth + 1: parent_stack.append(name)
                else: parent_stack[depth + 1] = name
        return items

    def emit_terminal_result(self, card_id: str, output: str, exit_code: int):
        """Update terminal card with result."""
        self._view.page().runJavaScript(f"if(window.setTerminalOutput) window.setTerminalOutput({json.dumps(card_id)}, {json.dumps(output[:3000])}, {exit_code});")

    def _ensure_terminal_backend(self):
        """Lazy initialization of terminal backend."""
        if self._pty_process is not None or self._terminal_process is not None: return
        shell = "powershell.exe" if platform.system() == "Windows" else "bash"
        try:
            import winpty
            import time
            from PyQt6.QtCore import Qt, QThread, pyqtSignal
            self._pty_process = winpty.PtyProcess.spawn(shell, dimensions=(24, 80), backend=winpty.Backend.WinPTY)
            class Reader(QThread):
                data = pyqtSignal(str)
                def __init__(self, pty):
                    super().__init__(); self.pty = pty; self._running = True
                def run(self):
                    while self._running and self.pty.isalive():
                        try:
                            d = self.pty.read(timeout=0.05)
                            if d: self.data.emit(d)
                        except: time.sleep(0.01)
                def stop(self): self._running = False; self.wait(500)
            self._terminal_reader = Reader(self._pty_process)
            def _emit_terminal_data(data):
                self._terminal_output_buffer += data
                if len(self._terminal_output_buffer) > 2048:
                    self._bridge.terminal_output.emit(self._terminal_output_buffer)
                    self._terminal_output_buffer = ""
            self._terminal_reader.data.connect(_emit_terminal_data, Qt.ConnectionType.QueuedConnection)
            self._terminal_reader.start()
        except Exception as e:
            log.warning(f"WinPTY not available ({e}), falling back to QProcess")
            self._terminal_process = QProcess(self)
            self._terminal_process.readyReadStandardOutput.connect(self._on_terminal_output)
            self._terminal_process.start(shell)

    def _on_terminal_output(self):
        """Handle output from terminal process."""
        if self._terminal_process:
            data = self._terminal_process.readAllStandardOutput().data().decode(errors="replace")
            if data: self._bridge.terminal_output.emit(data)

    # â”€â”€ CODE COMPLETION HANDLERS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    def _on_code_completion_requested(self, data: dict):
        """Handle code completion request from bridge."""
        log.info(f"Code completion requested for {data.get('language', 'python')}")
        # Forward to main window for processing
        self._view.page().runJavaScript(f"window.showCompletionIndicator && window.showCompletionIndicator();")
    
    def _on_code_completion_selected(self, data: dict):
        """Handle code completion selection from bridge."""
        log.info(f"Code completion selected: index {data.get('index', 0)}")
        # Forward to main window
    
    def _on_code_completion_accepted(self, data: dict):
        """Handle code completion acceptance from bridge."""
        log.info(f"Code completion accepted: {data.get('requestId', 'unknown')}")
        # Hide indicator
        self._view.page().runJavaScript(f"window.hideCompletionIndicator && window.hideCompletionIndicator();")
    
    def _on_code_completion_dismissed(self, data: dict):
        """Handle code completion dismissal from bridge."""
        log.info(f"Code completion dismissed: {data.get('requestId', 'unknown')}")
        # Hide indicator and popup
        self._view.page().runJavaScript(f"window.hideCompletionIndicator && window.hideCompletionIndicator();")
        self._view.page().runJavaScript(f"window.dismissCodeCompletion && window.dismissCodeCompletion();")
    
    def show_code_completion_popup(self, completions: list, request_id: str):
        """Show code completion popup in chat UI."""
        import json
        completions_json = json.dumps(completions)
        js_code = f"""
            if (window.showCodeCompletionPopup) {{
                window.showCodeCompletionPopup({completions_json}, '{request_id}');
            }}
        """
        self._view.page().runJavaScript(js_code)
    
    def show_code_completion_card(self, completion_data: dict):
        """Show code completion card in chat."""
        import json
        data_json = json.dumps(completion_data)
        js_code = f"""
            if (window.showCodeCompletionCard) {{
                window.showCodeCompletionCard({data_json});
            }}
        """
        self._view.page().runJavaScript(js_code)
    
    def hide_code_completion(self):
        """Hide code completion popup."""
        self._view.page().runJavaScript("window.dismissCodeCompletion && window.dismissCodeCompletion();")
    
    # â”€â”€ INLINE DIFF VIEWER HANDLERS (OpenCode-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    def _on_diff_line_accepted(self, data: dict):
        """Handle diff line acceptance from bridge."""
        log.info(f"Diff line accepted: {data.get('filePath')}:{data.get('lineNumber')}")
        # Forward to main window for processing
        # This allows per-line acceptance in the future
        self.accept_file_edit_requested.emit(data.get('filePath'))
    
    def _on_diff_line_rejected(self, data: dict):
        """Handle diff line rejection from bridge."""
        log.info(f"Diff line rejected: {data.get('filePath')}:{data.get('lineNumber')}")
        # Forward to main window for processing
        # This allows per-line rejection in the future
        self.reject_file_edit_requested.emit(data.get('filePath'))
    
    def _on_diff_line_commented(self, data: dict):
        """Handle diff line comment from bridge."""
        log.info(f"Diff line commented: {data.get('filePath')}:{data.get('lineNumber')}")
        # Store comment for future use
        # TODO: Implement comment storage and display
    
    def show_inline_diff(self, diff_data: dict):
        """Show inline diff in chat UI."""
        import json
        data_json = json.dumps(diff_data)
        js_code = f"""
            if (window.showInlineDiff) {{
                window.showInlineDiff({data_json});
            }}
        """
        self._view.page().runJavaScript(js_code)

    def closeEvent(self, event):
        """Cleanup on close."""
        self._cleanup_vision_thread()
        if self._pty_process:
            self._pty_process.terminate()
        if self._terminal_process:
            self._terminal_process.terminate()
        super().closeEvent(event)











