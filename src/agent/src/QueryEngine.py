# ------------------------------------------------------------
# QueryEngine.py
# Python conversion of QueryEngine.ts (lines 1-1296)
# 
# Core query engine class managing conversation lifecycle for multi-LLM support:
# - Cortex (Anthropic), OpenAI, Gemini, DeepSeek, Minimax, Grok
# - Session state management across multiple turns
# - SDK message formatting and streaming
# - Permission denial tracking
# - Structured output enforcement
# - Budget enforcement (USD and token limits)
# - Transcript recording and session persistence
# - File history snapshots and attribution tracking
# - Orphaned permission recovery
# - Snip compaction boundary handling
# ------------------------------------------------------------

import asyncio
import os
from typing import Any, AsyncGenerator, Dict, List, Optional, Set


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from .bootstrap.state import get_session_id, is_session_persistence_disabled
except ImportError:
    def get_session_id() -> str:
        return "default-session"
    
    def is_session_persistence_disabled() -> bool:
        return False

try:
    from .entrypoints.agent_sdk_types import (
        PermissionMode,
        SDKCompactBoundaryMessage,
        SDKMessage,
        SDKPermissionDenial,
        SDKStatus,
        SDKUserMessageReplay,
    )
except ImportError:
    PermissionMode = str
    SDKCompactBoundaryMessage = Dict[str, Any]
    SDKMessage = Dict[str, Any]
    SDKPermissionDenial = Dict[str, Any]
    SDKStatus = Dict[str, Any]
    SDKUserMessageReplay = Dict[str, Any]

try:
    from .services.api.cortex import accumulate_usage, update_usage
except ImportError:
    def accumulate_usage(total: dict, current: dict) -> dict:
        return {**total, **current}
    
    def update_usage(current: dict, delta: dict) -> dict:
        return {**current, **delta}

try:
    from .services.api.logging import EMPTY_USAGE, NonNullableUsage
except ImportError:
    EMPTY_USAGE = {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_read_input_tokens': 0,
        'cache_creation_input_tokens': 0,
    }
    NonNullableUsage = Dict[str, int]

try:
    from .commands import get_slash_command_tool_skills
except ImportError:
    async def get_slash_command_tool_skills(cwd: str) -> list:
        return []

try:
    from .constants.xml import LOCAL_COMMAND_STDERR_TAG, LOCAL_COMMAND_STDOUT_TAG
except ImportError:
    LOCAL_COMMAND_STDERR_TAG = "local_command_stderr"
    LOCAL_COMMAND_STDOUT_TAG = "local_command_stdout"

try:
    from .cost_tracker import get_model_usage, get_total_api_duration, get_total_cost
except ImportError:
    def get_model_usage() -> dict:
        return {}
    
    def get_total_api_duration() -> float:
        return 0.0
    
    def get_total_cost() -> float:
        return 0.0

try:
    from .hooks.use_can_use_tool import CanUseToolFn
except ImportError:
    CanUseToolFn = Any

try:
    from .memdir.memdir import load_memory_prompt
except ImportError:
    async def load_memory_prompt() -> str:
        return ""

try:
    from .memdir.paths import has_auto_mem_path_override
except ImportError:
    def has_auto_mem_path_override() -> bool:
        return False

try:
    from .query import query
except ImportError:
    async def query(params: dict):
        for item in []:
            yield item

try:
    from .services.api.errors import categorize_retryable_api_error
except ImportError:
    def categorize_retryable_api_error(error: Exception) -> str:
        return str(error)

try:
    from .services.mcp.types import MCPServerConnection
except ImportError:
    MCPServerConnection = Dict[str, Any]

try:
    from .state.AppState import AppState
except ImportError:
    AppState = Dict[str, Any]

try:
    from .Tool import Tools, ToolUseContext, tool_matches_name
except ImportError:
    Tools = List[Dict[str, Any]]
    ToolUseContext = Dict[str, Any]
    
    def tool_matches_name(tool: dict, name: str) -> bool:
        return tool.get('name') == name

try:
    from .tools.AgentTool.load_agents_dir import AgentDefinition
except ImportError:
    AgentDefinition = Dict[str, Any]

try:
    from .tools.SyntheticOutputTool.SyntheticOutputTool import SYNTHETIC_OUTPUT_TOOL_NAME
except ImportError:
    SYNTHETIC_OUTPUT_TOOL_NAME = "synthetic_output"

try:
    from .agent_types.message import Message
except ImportError:
    Message = Dict[str, Any]

try:
    from .agent_types.text_input_types import OrphanedPermission
except ImportError:
    OrphanedPermission = Dict[str, Any]

try:
    from .utils.abort_controller import create_abort_controller
except ImportError:
    def create_abort_controller():
        return {'signal': {'aborted': False, 'reason': None}}

try:
    from .utils.commit_attribution import AttributionState
except ImportError:
    AttributionState = Dict[str, Any]

try:
    from .utils.config import get_global_config
except ImportError:
    def get_global_config():
        class DummyConfig:
            theme = "dark"
        return DummyConfig()

try:
    from .utils.cwd import get_cwd
except ImportError:
    def get_cwd() -> str:
        return os.getcwd()

try:
    from .utils.env_utils import is_bare_mode, is_env_truthy
except ImportError:
    def is_bare_mode() -> bool:
        return False
    
    def is_env_truthy(value: Optional[str]) -> bool:
        return value and value.lower() in ["true", "1", "yes"]

try:
    from .utils.fast_mode import get_fast_mode_state
except ImportError:
    def get_fast_mode_state(model: str, fast_mode: dict) -> dict:
        return fast_mode

try:
    from .utils.file_history import (
        file_history_enabled,
        file_history_make_snapshot,
        FileHistoryState,
    )
except ImportError:
    def file_history_enabled() -> bool:
        return False
    
    async def file_history_make_snapshot(updater, uuid: str):
        pass
    
    FileHistoryState = Dict[str, Any]

try:
    from .utils.file_state_cache import clone_file_state_cache, FileStateCache
except ImportError:
    def clone_file_state_cache(cache: dict) -> dict:
        return dict(cache)
    
    FileStateCache = Dict[str, Any]

try:
    from .utils.headless_profiler import headless_profiler_checkpoint
except ImportError:
    def headless_profiler_checkpoint(label: str) -> None:
        pass

try:
    from .utils.hooks.hook_helpers import register_structured_output_enforcement
except ImportError:
    def register_structured_output_enforcement(set_app_state, session_id: str):
        pass

try:
    from .utils.log import get_in_memory_errors
except ImportError:
    def get_in_memory_errors() -> list:
        return []

try:
    from .utils.messages import count_tool_calls, SYNTHETIC_MESSAGES
except ImportError:
    def count_tool_calls(messages: list, tool_name: str) -> int:
        return 0
    
    SYNTHETIC_MESSAGES = set()

try:
    from .utils.model.model import get_main_loop_model, parse_user_specified_model
except ImportError:
    def get_main_loop_model() -> str:
        return "cortex-3-5-sonnet"
    
    def parse_user_specified_model(model: str) -> str:
        return model

try:
    from .utils.plugins.plugin_loader import load_all_plugins_cache_only
except ImportError:
    async def load_all_plugins_cache_only():
        return {'enabled': []}

try:
    from .utils.process_user_input.process_user_input import (
        process_user_input,
        ProcessUserInputContext,
    )
except ImportError:
    async def process_user_input(**kwargs):
        return {
            'messages': [],
            'shouldQuery': True,
            'allowedTools': [],
            'model': None,
            'resultText': '',
        }
    
    ProcessUserInputContext = Dict[str, Any]

try:
    from .utils.query_context import fetch_system_prompt_parts
except ImportError:
    async def fetch_system_prompt_parts(**kwargs):
        return {
            'defaultSystemPrompt': [],
            'userContext': {},
            'systemContext': {},
        }

try:
    from .utils.Shell import set_cwd
except ImportError:
    def set_cwd(cwd: str):
        pass

try:
    from .utils.session_storage import flush_session_storage, record_transcript
except ImportError:
    async def flush_session_storage():
        pass
    
    async def record_transcript(messages: list):
        pass

try:
    from .utils.system_prompt_type import as_system_prompt
except ImportError:
    def as_system_prompt(prompt: str) -> str:
        return prompt

try:
    from .utils.searchStrategy import get_search_strategy_instruction
except ImportError:
    def get_search_strategy_instruction() -> str:
        return ""

try:
    from .utils.system_theme import resolve_theme_setting
except ImportError:
    def resolve_theme_setting(theme: str) -> str:
        return theme

try:
    from .utils.thinking import should_enable_thinking_by_default, ThinkingConfig
except ImportError:
    def should_enable_thinking_by_default() -> bool:
        return True
    
    ThinkingConfig = Dict[str, Any]

try:
    from .utils.messages.mappers import (
        local_command_output_to_sdk_assistant_message,
        to_sdk_compact_metadata,
    )
except ImportError:
    def local_command_output_to_sdk_assistant_message(content: str, uuid: str):
        return {'type': 'assistant', 'content': content}
    
    def to_sdk_compact_metadata(metadata: dict):
        return metadata

try:
    from .utils.messages.system_init import build_system_init_message, sdk_compat_tool_name
except ImportError:
    def build_system_init_message(**kwargs):
        return {'type': 'system', 'subtype': 'init'}
    
    def sdk_compat_tool_name(name: str) -> str:
        return name

try:
    from .utils.permissions.filesystem import get_scratchpad_dir, is_scratchpad_enabled
except ImportError:
    def get_scratchpad_dir() -> str:
        return "/tmp/scratchpad"
    
    def is_scratchpad_enabled() -> bool:
        return False

try:
    from .utils.query_helpers import handle_orphaned_permission, is_result_successful, normalize_message
except ImportError:
    async def handle_orphaned_permission(permission, tools, messages, context):
        for item in []:
            yield item
    
    def is_result_successful(result, stop_reason: str) -> bool:
        return result is not None
    
    async def normalize_message(message: dict):
        yield message

try:
    from .coordinator.coordinator_mode import get_coordinator_user_context
except ImportError:
    def get_coordinator_user_context(mcp_clients: list, scratchpad_dir: str = None) -> dict:
        return {}

try:
    from .services.compact.snip_compact import snip_compact_if_needed
except ImportError:
    def snip_compact_if_needed(messages: list, options: dict = None):
        return {'messages': messages, 'executed': False}

try:
    from .services.compact.snip_projection import is_snip_boundary_message
except ImportError:
    def is_snip_boundary_message(message: dict) -> bool:
        return False


# ============================================================
# TYPE DEFINITIONS
# ============================================================

QueryEngineConfig = Dict[str, Any]


# ============================================================
# QUERY ENGINE CLASS
# ============================================================

class QueryEngine:
    """
    QueryEngine owns the query lifecycle and session state for a conversation.
    
    It extracts the core logic from ask() into a standalone class that can be
    used by both the headless/SDK path and (in a future phase) the REPL.
    
    One QueryEngine per conversation. Each submit_message() call starts a new
    turn within the same conversation. State (messages, file cache, usage, etc.)
    persists across turns.
    
    Supports multiple LLM providers:
    - Cortex (Anthropic)
    - OpenAI (GPT-4, GPT-3.5)
    - Google Gemini
    - DeepSeek
    - Minimax
    - Grok (xAI)
    """
    
    def __init__(self, config: QueryEngineConfig):
        """
        Initialize QueryEngine with configuration.
        
        Args:
            config: QueryEngineConfig containing:
                - cwd: Current working directory
                - tools: Available tools
                - commands: Available commands
                - mcp_clients: MCP server connections
                - agents: Agent definitions
                - can_use_tool: Permission check function
                - get_app_state: Function to get app state
                - set_app_state: Function to update app state
                - initial_messages: Starting messages (optional)
                - read_file_cache: File state cache
                - custom_system_prompt: Custom system prompt (optional)
                - append_system_prompt: Appended system prompt (optional)
                - user_specified_model: User-specified model (optional)
                - fallback_model: Fallback model on errors (optional)
                - thinking_config: Thinking configuration (optional)
                - max_turns: Maximum conversation turns (optional)
                - max_budget_usd: Maximum USD budget (optional)
                - task_budget: API task budget (optional)
                - json_schema: JSON schema for structured output (optional)
                - verbose: Verbose logging flag
                - replay_user_messages: Replay user messages flag
                - handle_elicitation: URL elicitation handler (optional)
                - include_partial_messages: Include partial stream messages
                - set_sdk_status: SDK status setter (optional)
                - abort_controller: Abort controller (optional)
                - orphaned_permission: Orphaned permission to recover (optional)
                - snip_replay: Snip boundary handler (optional)
        """
        self.config = config
        self.mutable_messages: List[Message] = config.get('initialMessages', [])
        self.abort_controller = config.get('abortController') or create_abort_controller()
        self.permission_denials: List[SDKPermissionDenial] = []
        self.total_usage: NonNullableUsage = dict(EMPTY_USAGE)
        self.has_handled_orphaned_permission = False
        self.read_file_state: FileStateCache = config['readFileCache']
        
        # Turn-scoped skill discovery tracking (feeds was_discovered on
        # tengu_skill_tool_invocation). Must persist across the two
        # processUserInputContext rebuilds inside submit_message, but is cleared
        # at the start of each submit_message to avoid unbounded growth across
        # many turns in SDK mode.
        self.discovered_skill_names: Set[str] = set()
        self.loaded_nested_memory_paths: Set[str] = set()
    
    async def submit_message(
        self,
        prompt: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[SDKMessage, None]:
        """
        Submit a message to the query engine and stream responses.
        
        This is the main entry point for sending prompts to the LLM. It handles:
        1. System prompt construction
        2. User input processing (slash commands, attachments)
        3. Query execution with the core query loop
        4. Message normalization and SDK formatting
        5. Budget enforcement and error handling
        6. Transcript recording and session persistence
        
        Args:
            prompt: User prompt (string or content blocks)
            options: Optional parameters:
                - uuid: Message UUID
                - isMeta: Whether this is a meta message
        
        Yields:
            SDK-formatted messages including:
            - System initialization
            - Assistant responses
            - User message replays
            - Progress updates
            - Attachments
            - Compact boundaries
            - Result summary
        """
        if options is None:
            options = {}
        
        config = self.config
        cwd = config['cwd']
        commands = config['commands']
        tools = config['tools']
        mcp_clients = config['mcpClients']
        verbose = config.get('verbose', False)
        thinking_config = config.get('thinkingConfig')
        max_turns = config.get('maxTurns')
        max_budget_usd = config.get('maxBudgetUsd')
        task_budget = config.get('taskBudget')
        can_use_tool = config['canUseTool']
        custom_system_prompt = config.get('customSystemPrompt')
        append_system_prompt = config.get('appendSystemPrompt')
        user_specified_model = config.get('userSpecifiedModel')
        fallback_model = config.get('fallbackModel')
        json_schema = config.get('jsonSchema')
        get_app_state = config['getAppState']
        set_app_state = config['setAppState']
        replay_user_messages = config.get('replayUserMessages', False)
        include_partial_messages = config.get('includePartialMessages', False)
        agents = config.get('agents', [])
        set_sdk_status = config.get('setSDKStatus')
        orphaned_permission = config.get('orphanedPermission')
        
        self.discovered_skill_names.clear()
        set_cwd(cwd)
        persist_session = not is_session_persistence_disabled()
        _loop = asyncio.get_running_loop()
        start_time = int(_loop.time() * 1000)
        
        # Wrap canUseTool to track permission denials
        async def wrapped_can_use_tool(
            tool,
            input_data,
            tool_use_context,
            assistant_message,
            tool_use_id,
            force_decision=False,
        ):
            result = await can_use_tool(
                tool,
                input_data,
                tool_use_context,
                assistant_message,
                tool_use_id,
                force_decision,
            )
            
            # Track denials for SDK reporting
            if result.get('behavior') != 'allow':
                self.permission_denials.append({
                    'tool_name': sdk_compat_tool_name(tool['name']),
                    'tool_use_id': tool_use_id,
                    'tool_input': input_data,
                })
            
            return result
        
        initial_app_state = get_app_state()
        initial_main_loop_model = (
            parse_user_specified_model(user_specified_model)
            if user_specified_model
            else get_main_loop_model()
        )
        
        initial_thinking_config = (
            thinking_config
            if thinking_config
            else (
                {'type': 'adaptive'}
                if should_enable_thinking_by_default() is not False
                else {'type': 'disabled'}
            )
        )
        
        headless_profiler_checkpoint('before_getSystemPrompt')
        
        # Narrow once so TS tracks the type through the conditionals below.
        custom_prompt = custom_system_prompt if isinstance(custom_system_prompt, str) else None
        
        system_prompt_data = await fetch_system_prompt_parts(
            tools=tools,
            mainLoopModel=initial_main_loop_model,
            additionalWorkingDirectories=list(
                initial_app_state['toolPermissionContext'].get('additionalWorkingDirectories', {}).keys()
            ),
            mcpClients=mcp_clients,
            customSystemPrompt=custom_prompt,
        )
        
        headless_profiler_checkpoint('after_getSystemPrompt')
        
        default_system_prompt = system_prompt_data['defaultSystemPrompt']
        base_user_context = system_prompt_data['userContext']
        system_context = system_prompt_data['systemContext']
        
        user_context = {
            **base_user_context,
            **get_coordinator_user_context(
                mcp_clients,
                get_scratchpad_dir() if is_scratchpad_enabled() else None,
            ),
        }
        
        # When an SDK caller provides a custom system prompt AND has set
        # CORTEX_COWORK_MEMORY_PATH_OVERRIDE, inject the memory-mechanics prompt.
        # The env var is an explicit opt-in signal — the caller has wired up
        # a memory directory and needs Cortex to know how to use it.
        memory_mechanics_prompt = (
            await load_memory_prompt()
            if custom_prompt is not None and has_auto_mem_path_override()
            else None
        )
        
        system_prompt = as_system_prompt([
            *([custom_prompt] if custom_prompt is not None else default_system_prompt),
            *([memory_mechanics_prompt] if memory_mechanics_prompt else []),
            get_search_strategy_instruction(),  # 🔥 Enforce thorough search strategy
            *([append_system_prompt] if append_system_prompt else []),
        ])
        
        # Register function hook for structured output enforcement
        has_structured_output_tool = any(
            tool_matches_name(t, SYNTHETIC_OUTPUT_TOOL_NAME)
            for t in tools
        )
        
        if json_schema and has_structured_output_tool:
            register_structured_output_enforcement(set_app_state, get_session_id())
        
        process_user_input_context: ProcessUserInputContext = {
            'messages': self.mutable_messages,
            'setMessages': lambda fn: setattr(self, 'mutable_messages', fn(self.mutable_messages)),
            'onChangeAPIKey': lambda: None,
            'handleElicitation': config.get('handleElicitation'),
            'options': {
                'commands': commands,
                'debug': False,  # we use stdout, so don't want to clobber it
                'tools': tools,
                'verbose': verbose,
                'mainLoopModel': initial_main_loop_model,
                'thinkingConfig': initial_thinking_config,
                'mcpClients': mcp_clients,
                'mcpResources': {},
                'ideInstallationStatus': None,
                'isNonInteractiveSession': True,
                'customSystemPrompt': custom_system_prompt,
                'appendSystemPrompt': append_system_prompt,
                'agentDefinitions': {'activeAgents': agents, 'allAgents': []},
                'theme': resolve_theme_setting(get_global_config().theme),
                'maxBudgetUsd': max_budget_usd,
            },
            'getAppState': get_app_state,
            'setAppState': set_app_state,
            'abortController': self.abort_controller,
            'readFileState': self.read_file_state,
            'nestedMemoryAttachmentTriggers': set(),
            'loadedNestedMemoryPaths': self.loaded_nested_memory_paths,
            'dynamicSkillDirTriggers': set(),
            'discoveredSkillNames': self.discovered_skill_names,
            'setInProgressToolUseIDs': lambda: None,
            'setResponseLength': lambda: None,
            'updateFileHistoryState': lambda updater: set_app_state(
                lambda prev: {
                    **prev,
                    'fileHistory': updater(prev['fileHistory']),
                }
            ),
            'updateAttributionState': lambda updater: set_app_state(
                lambda prev: {
                    **prev,
                    'attribution': updater(prev['attribution']),
                }
            ),
            'setSDKStatus': set_sdk_status,
        }
        
        # Handle orphaned permission (only once per engine lifetime)
        if orphaned_permission and not self.has_handled_orphaned_permission:
            self.has_handled_orphaned_permission = True
            async for message in handle_orphaned_permission(
                orphaned_permission,
                tools,
                self.mutable_messages,
                process_user_input_context,
            ):
                yield message
        
        user_input_result = await process_user_input(
            input=prompt,
            mode='prompt',
            setToolJSX=lambda: None,
            context={
                **process_user_input_context,
                'messages': self.mutable_messages,
            },
            messages=self.mutable_messages,
            uuid=options.get('uuid'),
            isMeta=options.get('isMeta'),
            querySource='sdk',
        )
        
        messages_from_user_input = user_input_result['messages']
        should_query = user_input_result['shouldQuery']
        allowed_tools = user_input_result['allowedTools']
        model_from_user_input = user_input_result.get('model')
        result_text = user_input_result.get('resultText')
        
        # Push new messages, including user input and any attachments
        self.mutable_messages.extend(messages_from_user_input)
        
        # Update params to reflect updates from processing /slash commands
        messages = list(self.mutable_messages)
        
        # Persist the user's message(s) to transcript BEFORE entering the query
        # loop. The for-await below only calls recordTranscript when ask() yields
        # an assistant/user/compact_boundary message — which doesn't happen until
        # the API responds. If the process is killed before that, the transcript
        # is left with only queue-operation entries; getLastSessionLog filters
        # those out, returns null, and --resume fails with "No conversation found".
        # Writing now makes the transcript resumable from the point the user
        # message was accepted, even if no API response ever arrives.
        if persist_session and len(messages_from_user_input) > 0:
            transcript_promise = record_transcript(messages)
            if is_bare_mode():
                asyncio.ensure_future(transcript_promise)
            else:
                await transcript_promise
                if (
                    is_env_truthy(os.environ.get('CORTEX_CODE_EAGER_FLUSH')) or
                    is_env_truthy(os.environ.get('CORTEX_CODE_IS_COWORK'))
                ):
                    await flush_session_storage()
        
        # Filter messages that should be acknowledged after transcript
        # Note: message_selector would go here
        replayable_messages = [
            msg for msg in messages_from_user_input
            if (
                msg.get('type') == 'user' and
                not msg.get('isMeta') and  # Skip synthetic caveat messages
                not msg.get('toolUseResult') and  # Skip tool results
                True  # selectableUserMessagesFilter(msg)
            ) or (
                msg.get('type') == 'system' and
                msg.get('subtype') == 'compact_boundary'
            )
        ]
        
        messages_to_ack = replayable_messages if replay_user_messages else []
        
        # Update the ToolPermissionContext based on user input processing
        set_app_state(lambda prev: {
            **prev,
            'toolPermissionContext': {
                **prev['toolPermissionContext'],
                'alwaysAllowRules': {
                    **prev['toolPermissionContext']['alwaysAllowRules'],
                    'command': allowed_tools,
                },
            },
        })
        
        main_loop_model = model_from_user_input or initial_main_loop_model
        
        # Recreate after processing the prompt to pick up updated messages and
        # model (from slash commands).
        process_user_input_context = {
            **process_user_input_context,
            'messages': messages,
            'setMessages': lambda: None,
            'options': {
                **process_user_input_context['options'],
                'mainLoopModel': main_loop_model,
            },
        }
        
        headless_profiler_checkpoint('before_skills_plugins')
        
        # Cache-only: headless/SDK/CCR startup must not block on network for
        # ref-tracked plugins. CCR populates the cache via CORTEX_CODE_SYNC_PLUGIN_INSTALL
        # (headlessPluginInstall) or CORTEX_CODE_PLUGIN_SEED_DIR before this runs.
        skills, enabled_plugins_data = await asyncio.gather(
            get_slash_command_tool_skills(get_cwd()),
            load_all_plugins_cache_only(),
        )
        
        enabled_plugins = enabled_plugins_data['enabled']
        
        headless_profiler_checkpoint('after_skills_plugins')
        
        yield build_system_init_message(
            tools=tools,
            mcpClients=mcp_clients,
            model=main_loop_model,
            permissionMode=initial_app_state['toolPermissionContext']['mode'],
            commands=commands,
            agents=agents,
            skills=skills,
            plugins=enabled_plugins,
            fastMode=initial_app_state.get('fastMode'),
        )
        
        # Record when system message is yielded for headless latency tracking
        headless_profiler_checkpoint('system_message_yielded')
        
        if not should_query:
            # Return the results of local slash commands.
            for msg in messages_from_user_input:
                if (
                    msg.get('type') == 'user' and
                    isinstance(msg.get('message', {}).get('content'), str) and
                    (
                        LOCAL_COMMAND_STDOUT_TAG in msg['message']['content'] or
                        LOCAL_COMMAND_STDERR_TAG in msg['message']['content'] or
                        msg.get('isCompactSummary')
                    )
                ):
                    yield {
                        'type': 'user',
                        'message': {
                            **msg['message'],
                            'content': msg['message']['content'],  # stripAnsi would go here
                        },
                        'session_id': get_session_id(),
                        'parent_tool_use_id': None,
                        'uuid': msg['uuid'],
                        'timestamp': msg['timestamp'],
                        'isReplay': not msg.get('isCompactSummary'),
                        'isSynthetic': msg.get('isMeta') or msg.get('isVisibleInTranscriptOnly'),
                    }
                
                # Local command output — yield as a synthetic assistant message
                if (
                    msg.get('type') == 'system' and
                    msg.get('subtype') == 'local_command' and
                    isinstance(msg.get('content'), str) and
                    (
                        LOCAL_COMMAND_STDOUT_TAG in msg['content'] or
                        LOCAL_COMMAND_STDERR_TAG in msg['content']
                    )
                ):
                    yield local_command_output_to_sdk_assistant_message(msg['content'], msg['uuid'])
                
                if msg.get('type') == 'system' and msg.get('subtype') == 'compact_boundary':
                    yield {
                        'type': 'system',
                        'subtype': 'compact_boundary',
                        'session_id': get_session_id(),
                        'uuid': msg['uuid'],
                        'compact_metadata': to_sdk_compact_metadata(msg.get('compactMetadata')),
                    }
            
            if persist_session:
                await record_transcript(messages)
                if (
                    is_env_truthy(os.environ.get('CORTEX_CODE_EAGER_FLUSH')) or
                    is_env_truthy(os.environ.get('CORTEX_CODE_IS_COWORK'))
                ):
                    await flush_session_storage()
            
            yield {
                'type': 'result',
                'subtype': 'success',
                'is_error': False,
                'duration_ms': int(_loop.time() * 1000) - start_time,
                'duration_api_ms': get_total_api_duration(),
                'num_turns': len(messages) - 1,
                'result': result_text or '',
                'stop_reason': None,
                'session_id': get_session_id(),
                'total_cost_usd': get_total_cost(),
                'usage': self.total_usage,
                'modelUsage': get_model_usage(),
                'permission_denials': self.permission_denials,
                'fast_mode_state': get_fast_mode_state(main_loop_model, initial_app_state.get('fastMode', {})),
                'uuid': 'random-uuid',  # randomUUID() would go here
            }
            return
        
        # File history snapshots
        if file_history_enabled() and persist_session:
            for message in messages_from_user_input:
                # Note: message_selector would go here
                asyncio.ensure_future(file_history_make_snapshot(
                    lambda updater: set_app_state(
                        lambda prev: {
                            **prev,
                            'fileHistory': updater(prev['fileHistory']),
                        }
                    ),
                    message['uuid'],
                ))
        
        # Track current message usage (reset on each message_start)
        current_message_usage: NonNullableUsage = dict(EMPTY_USAGE)
        turn_count = 1
        has_acknowledged_initial_messages = False
        
        # Track structured output from StructuredOutput tool calls
        structured_output_from_tool = None
        
        # Track the last stop_reason from assistant messages
        last_stop_reason: Optional[str] = None
        
        # Reference-based watermark so error_during_execution's errors[] is
        # turn-scoped. A length-based index breaks when the 100-entry ring buffer
        # shift()s during the turn.
        error_log_watermark = get_in_memory_errors()[-1] if get_in_memory_errors() else None
        
        # Snapshot count before this query for delta-based retry limiting
        initial_structured_output_calls = (
            count_tool_calls(self.mutable_messages, SYNTHETIC_OUTPUT_TOOL_NAME)
            if json_schema
            else 0
        )
        
        # Execute the core query loop
        async for message in query(
            messages=messages,
            systemPrompt=system_prompt,
            userContext=user_context,
            systemContext=system_context,
            canUseTool=wrapped_can_use_tool,
            toolUseContext=process_user_input_context,
            fallbackModel=fallback_model,
            querySource='sdk',
            maxTurns=max_turns,
            taskBudget=task_budget,
        ):
            # Record assistant, user, and compact boundary messages
            if (
                message.get('type') in ('assistant', 'user') or
                (message.get('type') == 'system' and message.get('subtype') == 'compact_boundary')
            ):
                # Before writing a compact boundary, flush any in-memory-only
                # messages up through the preservedSegment tail.
                if (
                    persist_session and
                    message.get('type') == 'system' and
                    message.get('subtype') == 'compact_boundary'
                ):
                    tail_uuid = message.get('compactMetadata', {}).get('preservedSegment', {}).get('tailUuid')
                    if tail_uuid:
                        tail_idx = next(
                            (i for i, m in enumerate(self.mutable_messages) if m.get('uuid') == tail_uuid),
                            -1,
                        )
                        if tail_idx != -1:
                            await record_transcript(self.mutable_messages[:tail_idx + 1])
                
                messages.append(message)
                
                if persist_session:
                    # Fire-and-forget for assistant messages
                    if message.get('type') == 'assistant':
                        asyncio.ensure_future(record_transcript(messages))
                    else:
                        await record_transcript(messages)
                
                # Acknowledge initial user messages after first transcript recording
                if not has_acknowledged_initial_messages and messages_to_ack:
                    has_acknowledged_initial_messages = True
                    for msg_to_ack in messages_to_ack:
                        if msg_to_ack.get('type') == 'user':
                            yield {
                                'type': 'user',
                                'message': msg_to_ack['message'],
                                'session_id': get_session_id(),
                                'parent_tool_use_id': None,
                                'uuid': msg_to_ack['uuid'],
                                'timestamp': msg_to_ack['timestamp'],
                                'isReplay': True,
                            }
            
            if message.get('type') == 'user':
                turn_count += 1
            
            # Message type handling
            msg_type = message.get('type')
            
            if msg_type == 'tombstone':
                # Tombstone messages are control signals for removing messages, skip them
                continue
            
            elif msg_type == 'assistant':
                # Capture stop_reason if already set (synthetic messages)
                if message.get('message', {}).get('stop_reason') is not None:
                    last_stop_reason = message['message']['stop_reason']
                
                self.mutable_messages.append(message)
                async for normalized in normalize_message(message):
                    yield normalized
            
            elif msg_type == 'progress':
                self.mutable_messages.append(message)
                # Record inline so the dedup loop in the next ask() call sees it
                if persist_session:
                    messages.append(message)
                    asyncio.ensure_future(record_transcript(messages))
                async for normalized in normalize_message(message):
                    yield normalized
            
            elif msg_type == 'user':
                self.mutable_messages.append(message)
                async for normalized in normalize_message(message):
                    yield normalized
            
            elif msg_type == 'stream_event':
                event_type = message.get('event', {}).get('type')
                
                if event_type == 'message_start':
                    # Reset current message usage for new message
                    current_message_usage = dict(EMPTY_USAGE)
                    current_message_usage = update_usage(
                        current_message_usage,
                        message['event']['message'].get('usage', {}),
                    )
                
                if event_type == 'message_delta':
                    current_message_usage = update_usage(
                        current_message_usage,
                        message['event'].get('usage', {}),
                    )
                    # Capture stop_reason from message_delta
                    if message['event'].get('delta', {}).get('stop_reason') is not None:
                        last_stop_reason = message['event']['delta']['stop_reason']
                
                if event_type == 'message_stop':
                    # Accumulate current message usage into total
                    self.total_usage = accumulate_usage(self.total_usage, current_message_usage)
                
                if include_partial_messages:
                    yield {
                        'type': 'stream_event',
                        'event': message['event'],
                        'session_id': get_session_id(),
                        'parent_tool_use_id': None,
                        'uuid': 'random-uuid',
                    }
            
            elif msg_type == 'attachment':
                self.mutable_messages.append(message)
                # Record inline
                if persist_session:
                    messages.append(message)
                    asyncio.ensure_future(record_transcript(messages))
                
                # Extract structured output from StructuredOutput tool calls
                if message['attachment'].get('type') == 'structured_output':
                    structured_output_from_tool = message['attachment']['data']
                
                # Handle max turns reached signal from query.py
                elif message['attachment'].get('type') == 'max_turns_reached':
                    if persist_session:
                        if (
                            is_env_truthy(os.environ.get('CORTEX_CODE_EAGER_FLUSH')) or
                            is_env_truthy(os.environ.get('CORTEX_CODE_IS_COWORK'))
                        ):
                            await flush_session_storage()
                    
                    yield {
                        'type': 'result',
                        'subtype': 'error_max_turns',
                        'duration_ms': int(_loop.time() * 1000) - start_time,
                        'duration_api_ms': get_total_api_duration(),
                        'is_error': True,
                        'num_turns': message['attachment']['turnCount'],
                        'stop_reason': last_stop_reason,
                        'session_id': get_session_id(),
                        'total_cost_usd': get_total_cost(),
                        'usage': self.total_usage,
                        'modelUsage': get_model_usage(),
                        'permission_denials': self.permission_denials,
                        'fast_mode_state': get_fast_mode_state(main_loop_model, initial_app_state.get('fastMode', {})),
                        'uuid': 'random-uuid',
                        'errors': [
                            f"Reached maximum number of turns ({message['attachment']['maxTurns']})"
                        ],
                    }
                    return
                
                # Yield queued_command attachments as SDK user message replays
                elif (
                    replay_user_messages and
                    message['attachment'].get('type') == 'queued_command'
                ):
                    yield {
                        'type': 'user',
                        'message': {
                            'role': 'user',
                            'content': message['attachment']['prompt'],
                        },
                        'session_id': get_session_id(),
                        'parent_tool_use_id': None,
                        'uuid': message['attachment'].get('source_uuid') or message['uuid'],
                        'timestamp': message['timestamp'],
                        'isReplay': True,
                    }
            
            elif msg_type == 'stream_request_start':
                # Don't yield stream request start messages
                continue
            
            elif msg_type == 'system':
                # Snip boundary: replay on our store to remove zombie messages
                snip_replay = config.get('snipReplay')
                if snip_replay:
                    snip_result = snip_replay(message, self.mutable_messages)
                    if snip_result is not None:
                        if snip_result['executed']:
                            self.mutable_messages.clear()
                            self.mutable_messages.extend(snip_result['messages'])
                        continue
                
                self.mutable_messages.append(message)
                
                # Yield compact boundary messages to SDK
                if (
                    message.get('subtype') == 'compact_boundary' and
                    message.get('compactMetadata')
                ):
                    # Release pre-compaction messages for GC
                    mutable_boundary_idx = len(self.mutable_messages) - 1
                    if mutable_boundary_idx > 0:
                        del self.mutable_messages[:mutable_boundary_idx]
                    
                    local_boundary_idx = len(messages) - 1
                    if local_boundary_idx > 0:
                        del messages[:local_boundary_idx]
                    
                    yield {
                        'type': 'system',
                        'subtype': 'compact_boundary',
                        'session_id': get_session_id(),
                        'uuid': message['uuid'],
                        'compact_metadata': to_sdk_compact_metadata(message['compactMetadata']),
                    }
                
                if message.get('subtype') == 'api_error':
                    yield {
                        'type': 'system',
                        'subtype': 'api_retry',
                        'attempt': message['retryAttempt'],
                        'max_retries': message['maxRetries'],
                        'retry_delay_ms': message['retryInMs'],
                        'error_status': message['error'].get('status'),
                        'error': categorize_retryable_api_error(message['error']),
                        'session_id': get_session_id(),
                        'uuid': message['uuid'],
                    }
                
                # Don't yield other system messages in headless mode
                continue
            
            elif msg_type == 'tool_use_summary':
                # Yield tool use summary messages to SDK
                yield {
                    'type': 'tool_use_summary',
                    'summary': message['summary'],
                    'preceding_tool_use_ids': message['precedingToolUseIds'],
                    'session_id': get_session_id(),
                    'uuid': message['uuid'],
                }
            
            # Check if USD budget has been exceeded
            if max_budget_usd is not None and get_total_cost() >= max_budget_usd:
                if persist_session:
                    if (
                        is_env_truthy(os.environ.get('CORTEX_CODE_EAGER_FLUSH')) or
                        is_env_truthy(os.environ.get('CORTEX_CODE_IS_COWORK'))
                    ):
                        await flush_session_storage()
                
                yield {
                    'type': 'result',
                    'subtype': 'error_max_budget_usd',
                    'duration_ms': int(_loop.time() * 1000) - start_time,
                    'duration_api_ms': get_total_api_duration(),
                    'is_error': True,
                    'num_turns': turn_count,
                    'stop_reason': last_stop_reason,
                    'session_id': get_session_id(),
                    'total_cost_usd': get_total_cost(),
                    'usage': self.total_usage,
                    'modelUsage': get_model_usage(),
                    'permission_denials': self.permission_denials,
                    'fast_mode_state': get_fast_mode_state(main_loop_model, initial_app_state.get('fastMode', {})),
                    'uuid': 'random-uuid',
                    'errors': [f'Reached maximum budget (${max_budget_usd})'],
                }
                return
            
            # Check if structured output retry limit exceeded (only on user messages)
            if message.get('type') == 'user' and json_schema:
                current_calls = count_tool_calls(
                    self.mutable_messages,
                    SYNTHETIC_OUTPUT_TOOL_NAME,
                )
                calls_this_query = current_calls - initial_structured_output_calls
                max_retries = int(os.environ.get('MAX_STRUCTURED_OUTPUT_RETRIES', '5'))
                
                if calls_this_query >= max_retries:
                    if persist_session:
                        if (
                            is_env_truthy(os.environ.get('CORTEX_CODE_EAGER_FLUSH')) or
                            is_env_truthy(os.environ.get('CORTEX_CODE_IS_COWORK'))
                        ):
                            await flush_session_storage()
                    
                    yield {
                        'type': 'result',
                        'subtype': 'error_max_structured_output_retries',
                        'duration_ms': int(_loop.time() * 1000) - start_time,
                        'duration_api_ms': get_total_api_duration(),
                        'is_error': True,
                        'num_turns': turn_count,
                        'stop_reason': last_stop_reason,
                        'session_id': get_session_id(),
                        'total_cost_usd': get_total_cost(),
                        'usage': self.total_usage,
                        'modelUsage': get_model_usage(),
                        'permission_denials': self.permission_denials,
                        'fast_mode_state': get_fast_mode_state(main_loop_model, initial_app_state.get('fastMode', {})),
                        'uuid': 'random-uuid',
                        'errors': [
                            f'Failed to provide valid structured output after {max_retries} attempts',
                        ],
                    }
                    return
        
        # Stop hooks yield progress/attachment messages AFTER the assistant
        # response. Since #23537 pushes those to `messages` inline, last(messages)
        # can be a progress/attachment instead of the assistant.
        result = next(
            (m for m in reversed(messages) if m.get('type') in ('assistant', 'user')),
            None,
        )
        
        # Capture for the error_during_execution diagnostic
        ede_result_type = result.get('type') if result else 'undefined'
        ede_last_content_type = (
            result['message']['content'][-1]['type']
            if result and result.get('type') == 'assistant' and result['message']['content']
            else 'n/a'
        )
        
        # Flush buffered transcript writes before yielding result.
        # The desktop app kills the AI agent process immediately after receiving the
        # result message, so any unflushed writes would be lost.
        if persist_session:
            if (
                is_env_truthy(os.environ.get('CORTEX_CODE_EAGER_FLUSH')) or
                is_env_truthy(os.environ.get('CORTEX_CODE_IS_COWORK'))
            ):
                await flush_session_storage()
        
        if not is_result_successful(result, last_stop_reason):
            all_errors = get_in_memory_errors()
            start_idx = (
                all_errors.index(error_log_watermark) + 1
                if error_log_watermark and error_log_watermark in all_errors
                else 0
            )
            
            yield {
                'type': 'result',
                'subtype': 'error_during_execution',
                'duration_ms': int(_loop.time() * 1000) - start_time,
                'duration_api_ms': get_total_api_duration(),
                'is_error': True,
                'num_turns': turn_count,
                'stop_reason': last_stop_reason,
                'session_id': get_session_id(),
                'total_cost_usd': get_total_cost(),
                'usage': self.total_usage,
                'modelUsage': get_model_usage(),
                'permission_denials': self.permission_denials,
                'fast_mode_state': get_fast_mode_state(main_loop_model, initial_app_state.get('fastMode', {})),
                'uuid': 'random-uuid',
                'errors': [
                    f'[ede_diagnostic] result_type={ede_result_type} last_content_type={ede_last_content_type} stop_reason={last_stop_reason}',
                    *[e.get('error') for e in all_errors[start_idx:]],
                ],
            }
            return
        
        # Extract the text result based on message type
        text_result = ''
        is_api_error = False
        
        if result and result.get('type') == 'assistant':
            last_content = result['message']['content'][-1] if result['message']['content'] else None
            if (
                last_content and
                last_content.get('type') == 'text' and
                last_content['text'] not in SYNTHETIC_MESSAGES
            ):
                text_result = last_content['text']
            is_api_error = bool(result.get('isApiErrorMessage'))
        
        yield {
            'type': 'result',
            'subtype': 'success',
            'is_error': is_api_error,
            'duration_ms': int(_loop.time() * 1000) - start_time,
            'duration_api_ms': get_total_api_duration(),
            'num_turns': turn_count,
            'result': text_result,
            'stop_reason': last_stop_reason,
            'session_id': get_session_id(),
            'total_cost_usd': get_total_cost(),
            'usage': self.total_usage,
            'modelUsage': get_model_usage(),
            'permission_denials': self.permission_denials,
            'structured_output': structured_output_from_tool,
            'fast_mode_state': get_fast_mode_state(main_loop_model, initial_app_state.get('fastMode', {})),
            'uuid': 'random-uuid',
        }
    
    def interrupt(self) -> None:
        """Interrupt the current query execution."""
        self.abort_controller['signal']['aborted'] = True
        self.abort_controller['signal']['reason'] = 'interrupt'
    
    def get_messages(self) -> List[Message]:
        """Get all messages in the conversation."""
        return list(self.mutable_messages)
    
    def get_read_file_state(self) -> FileStateCache:
        """Get the current file state cache."""
        return self.read_file_state
    
    def get_session_id(self) -> str:
        """Get the current session ID."""
        return get_session_id()
    
    def set_model(self, model: str) -> None:
        """Set the model to use for future queries."""
        self.config['userSpecifiedModel'] = model


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

async def ask(
    commands: list,
    prompt: str,
    prompt_uuid: str = None,
    is_meta: bool = False,
    cwd: str = None,
    tools: Tools = None,
    mcp_clients: Optional[List[MCPServerConnection]] = None,
    verbose: bool = False,
    thinking_config: ThinkingConfig = None,
    max_turns: int = None,
    max_budget_usd: float = None,
    task_budget: dict = None,
    can_use_tool: CanUseToolFn = None,
    mutable_messages: Optional[List[Message]] = None,
    get_read_file_cache=None,
    set_read_file_cache=None,
    custom_system_prompt: str = None,
    append_system_prompt: str = None,
    user_specified_model: str = None,
    fallback_model: str = None,
    json_schema: dict = None,
    get_app_state=None,
    set_app_state=None,
    abort_controller=None,
    replay_user_messages: bool = False,
    include_partial_messages: bool = False,
    handle_elicitation=None,
    agents: Optional[List[AgentDefinition]] = None,
    set_sdk_status=None,
    orphaned_permission: OrphanedPermission = None,
) -> AsyncGenerator[SDKMessage, None]:
    """
    Sends a single prompt to the LLM API and returns the response.
    
    Assumes that the system is being used non-interactively -- will not
    ask the user for permissions or further input.
    
    Convenience wrapper around QueryEngine for one-shot usage.
    
    Supports multiple LLM providers:
    - Cortex (Anthropic)
    - OpenAI (GPT-4, GPT-3.5)
    - Google Gemini
    - DeepSeek
    - Minimax
    - Grok (xAI)
    
    Args:
        commands: Available commands
        prompt: User prompt
        prompt_uuid: Prompt UUID (optional)
        is_meta: Whether this is a meta message
        cwd: Current working directory
        tools: Available tools
        mcp_clients: MCP server connections
        verbose: Verbose logging
        thinking_config: Thinking configuration
        max_turns: Maximum turns
        max_budget_usd: Maximum USD budget
        task_budget: API task budget
        can_use_tool: Permission check function
        mutable_messages: Initial messages
        get_read_file_cache: Function to get file cache
        set_read_file_cache: Function to set file cache
        custom_system_prompt: Custom system prompt
        append_system_prompt: Appended system prompt
        user_specified_model: User-specified model
        fallback_model: Fallback model
        json_schema: JSON schema for structured output
        get_app_state: Get app state function
        set_app_state: Set app state function
        abort_controller: Abort controller
        replay_user_messages: Replay user messages
        include_partial_messages: Include partial stream messages
        handle_elicitation: URL elicitation handler
        agents: Agent definitions
        set_sdk_status: SDK status setter
        orphaned_permission: Orphaned permission
    
    Yields:
        SDK-formatted messages
    """
    if mutable_messages is None:
        mutable_messages = []
    if agents is None:
        agents = []
    
    engine = QueryEngine({
        'cwd': cwd,
        'tools': tools,
        'commands': commands,
        'mcpClients': mcp_clients,
        'agents': agents,
        'canUseTool': can_use_tool,
        'getAppState': get_app_state,
        'setAppState': set_app_state,
        'initialMessages': mutable_messages,
        'readFileCache': clone_file_state_cache(get_read_file_cache()),
        'customSystemPrompt': custom_system_prompt,
        'appendSystemPrompt': append_system_prompt,
        'userSpecifiedModel': user_specified_model,
        'fallbackModel': fallback_model,
        'thinkingConfig': thinking_config,
        'maxTurns': max_turns,
        'maxBudgetUsd': max_budget_usd,
        'taskBudget': task_budget,
        'jsonSchema': json_schema,
        'verbose': verbose,
        'handleElicitation': handle_elicitation,
        'replayUserMessages': replay_user_messages,
        'includePartialMessages': include_partial_messages,
        'setSDKStatus': set_sdk_status,
        'abortController': abort_controller,
        'orphanedPermission': orphaned_permission,
        # Note: snipReplay would be added here if HISTORY_SNIP feature enabled
    })
    
    try:
        async for message in engine.submit_message(prompt, {
            'uuid': prompt_uuid,
            'isMeta': is_meta,
        }):
            yield message
    finally:
        set_read_file_cache(engine.get_read_file_state())


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "QueryEngine",
    "ask",
]
