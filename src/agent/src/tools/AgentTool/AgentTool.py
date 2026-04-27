# AgentTool.py
"""
AgentTool - Main agent spawning and management tool for Cortex IDE.

This is the core tool that allows spawning sub-agents with various configurations
including sync/async execution, worktree isolation, fork subagents, and teammate support.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict, Literal, Union, Set

# Core imports
from ...agent_types.message import Message as MessageType
from ...bootstrap.state import (
    clear_invoked_skills_for_agent,
    get_sdk_agent_progress_summaries_enabled,
)
from ...constants.prompts import enhance_system_prompt_with_env_details, get_system_prompt
from ...coordinator.coordinator_mode import is_coordinator_mode
from ...services.AgentSummary.agentSummary import start_agent_summarization
from ...tasks.LocalAgentTask.LocalAgentTask import (
    complete_async_agent,
    create_activity_description_resolver,
    create_progress_tracker,
    enqueue_agent_notification,
    fail_async_agent,
    get_progress_update,
    get_token_count_from_tracker,
    kill_async_agent,
    register_agent_foreground,
    register_async_agent,
    unregister_agent_foreground,
    update_agent_progress as update_async_agent_progress,
    update_progress_from_message,
)


def is_local_agent_task(task: Optional[Dict[str, Any]]) -> bool:
    """Type guard: check if task is a local agent task.
    
    Mirrors TypeScript's isLocalAgentTask() - checks if task has type='local_agent'.
    """
    return isinstance(task, dict) and task.get('type') == 'local_agent'
from ...tasks.RemoteAgentTask.RemoteAgentTask import (
    check_remote_agent_eligibility,
    format_precondition_error,
    get_remote_task_session_url,
    register_remote_agent_task,
)
from ...tool_registry import assemble_tool_pool
from ...agent_types.ids import as_agent_id
from ...utils.errors import AbortError, error_message, to_error

from ...utils.messages import (
    create_user_message,
    extract_text_content,
    is_synthetic_message,
    normalize_messages,
)
from ...utils.model.agent import get_agent_model

from ...utils.permissions.permissions import filter_denied_agents, get_deny_rule_for_agent
from ..BashTool.toolName import BASH_TOOL_NAME
# Local imports
from .agentColorManager import set_agent_color
from .agentToolUtils import (
    agent_tool_result_schema,
    classify_handoff_if_needed,
    emit_task_progress,
    extract_partial_result,
    finalize_agent_tool,
    get_last_tool_use_name,
    run_async_agent_lifecycle,
)
from .constants import AGENT_TOOL_NAME, LEGACY_AGENT_TOOL_NAME, ONE_SHOT_BUILTIN_AGENT_TYPES
from .forkSubagent import (
    build_forked_messages,
    build_worktree_notice,
    FORK_AGENT,
    is_fork_subagent_enabled,
    is_in_fork_child,
)
from .loadAgentsDir import AgentDefinition, filter_agents_by_mcp_requirements, has_required_mcp_servers, is_built_in_agent
from .prompt import get_prompt
from .runAgent import run_agent



def tool_matches_name(tool, name: str) -> bool:
    """Check if tool matches given name."""
    tool_name = getattr(tool, 'name', '')
    return tool_name == name or tool_name.startswith(f'{name}__')


# ============================================================================
# CONSTANTS AND CONFIGURATION
# ============================================================================

PROGRESS_THRESHOLD_MS = 2000  # Show background hint after 2 seconds

IS_BACKGROUND_TASKS_DISABLED = is_env_truthy(
    os.environ.get("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "")
)


def get_auto_background_ms() -> int:
    """Auto-background agent tasks after this many ms (0 = disabled)."""
    if (is_env_truthy(os.environ.get("CLAUDE_AUTO_BACKGROUND_TASKS", "")) or 
        get_feature_value_cached_may_be_stale("tengu_auto_background_agents", False)):
        return 120_000
    return 0


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

class TeammateSpawnedOutput(TypedDict, total=False):
    """Private type for teammate spawn results."""
    status: Literal["teammate_spawned"]
    prompt: str
    teammate_id: str
    agent_id: str
    agent_type: Optional[str]
    model: Optional[str]
    name: str
    color: Optional[str]
    tmux_session_name: str
    tmux_window_name: str
    tmux_pane_id: str
    team_name: Optional[str]
    is_splitpane: Optional[bool]
    plan_mode_required: Optional[bool]


class RemoteLaunchedOutput(TypedDict):
    """Private type for remote-launched results."""
    status: Literal["remote_launched"]
    task_id: str
    session_url: str
    description: str
    prompt: str
    output_file: str


# ============================================================================
# SCHEMA DEFINITIONS
# ============================================================================

def base_input_schema() -> Dict[str, Any]:
    """Base input schema without multi-agent parameters."""
    return {
        "description": str,
        "prompt": str,
        "subagent_type": Optional[str],
        "model": Optional[Literal['sonnet', 'opus', 'haiku']],
        "run_in_background": Optional[bool],
    }


def full_input_schema() -> Dict[str, Any]:
    """Full schema combining base + multi-agent params + isolation."""
    base = base_input_schema()
    base.update({
        "name": Optional[str],
        "team_name": Optional[str],
        "mode": Optional[Literal['auto', 'plan', 'acceptEdits']],
        "isolation": Optional[Literal['worktree', 'remote']],
        "cwd": Optional[str],
    })
    return base


def input_schema() -> Dict[str, Any]:
    """Dynamic input schema with feature gating."""
    
    schema = full_input_schema() if feature('KAIROS') else full_input_schema()
    
    if not feature('KAIROS'):
        schema.pop('cwd', None)
    
    if IS_BACKGROUND_TASKS_DISABLED or is_fork_subagent_enabled():
        schema.pop('run_in_background', None)
    
    return schema


def output_schema():
    """Output schema - union of sync and async results."""
    return Union[Dict[str, Any], Dict[str, Any]]


InputSchema = Dict[str, Any]
OutputSchema = Union[Dict[str, Any], TeammateSpawnedOutput, RemoteLaunchedOutput]
Progress = Dict[str, Any]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def resolve_team_name(team_name: Optional[str], app_state) -> Optional[str]:
    """Resolve team name from parameter or context."""
    if not is_agent_swarms_enabled():
        return None
    return team_name or getattr(app_state.team_context, 'team_name', None) if hasattr(app_state, 'team_context') else None


async def agent_tool_prompt(
    agents: List[AgentDefinition],
    tools: List[Any],
    get_tool_permission_context,
    allowed_agent_types: Optional[List[str]] = None
) -> str:
    """Generate the prompt for the AgentTool."""
    tool_permission_context = await get_tool_permission_context()
    
    mcp_servers_with_tools: Set[str] = set()
    for tool in tools:
        tool_name = getattr(tool, 'name', '')
        if tool_name and tool_name.startswith('mcp__'):
            parts = tool_name.split('__')
            server_name = parts[1] if len(parts) > 1 else None
            if server_name and server_name not in mcp_servers_with_tools:
                mcp_servers_with_tools.add(server_name)
    
    agents_with_mcp_met = filter_agents_by_mcp_requirements(agents, list(mcp_servers_with_tools))
    filtered_agents = filter_denied_agents(agents_with_mcp_met, tool_permission_context, AGENT_TOOL_NAME)
    
    is_coordinator = is_env_truthy(os.environ.get("CLAUDE_CODE_COORDINATOR_MODE", "")) if feature('COORDINATOR_MODE') else False
    
    return await get_prompt(filtered_agents, is_coordinator, allowed_agent_types)


async def _select_agent(
    effective_type: str,
    tool_use_context,
    app_state,
    is_fork_path: bool,
) -> AgentDefinition:
    """Select the appropriate agent based on type and permissions."""
    if is_fork_path:
        query_source = tool_use_context.options.get('query_source', '')
        messages = tool_use_context.messages
        
        if (query_source == f'agent:builtin:{FORK_AGENT.agent_type}' or 
            is_in_fork_child(messages)):
            raise Exception(
                'Fork is not available inside a forked worker. '
                'Complete your task directly using your tools.'
            )
        return FORK_AGENT
    else:
        all_agents = tool_use_context.options.agent_definitions.active_agents
        allowed_types = tool_use_context.options.agent_definitions.allowed_agent_types
        
        agents_to_check = (
            [a for a in all_agents if a.agent_type in allowed_types]
            if allowed_types else all_agents
        )
        
        filtered_agents = filter_denied_agents(
            agents_to_check,
            app_state.tool_permission_context,
            AGENT_TOOL_NAME
        )
        
        found = next((a for a in filtered_agents if a.agent_type == effective_type), None)
        
        if not found:
            agent_exists = next((a for a in all_agents if a.agent_type == effective_type), None)
            if agent_exists:
                deny_rule = get_deny_rule_for_agent(
                    app_state.tool_permission_context,
                    AGENT_TOOL_NAME,
                    effective_type
                )
                source = deny_rule.source if deny_rule else 'settings'
                raise Exception(
                    f"Agent type '{effective_type}' has been denied by permission rule "
                    f"'{AGENT_TOOL_NAME}({effective_type})' from {source}."
                )
            
            available = ', '.join(a.agent_type for a in filtered_agents)
            raise Exception(f"Agent type '{effective_type}' not found. Available agents: {available}")
        
        return found


async def _check_mcp_servers(
    selected_agent: AgentDefinition,
    app_state,
    tool_use_context,
):
    """Check if required MCP servers are available and authenticated."""
    required_mcp_servers = selected_agent.required_mcp_servers
    
    if not required_mcp_servers:
        return
    
    has_pending = any(
        c.type == 'pending' and any(
            pattern.lower() in c.name.lower() for pattern in required_mcp_servers
        )
        for c in app_state.mcp.clients
    )
    
    current_app_state = app_state
    if has_pending:
        max_wait_ms = 30_000
        poll_interval_ms = 500
        deadline = datetime.now().timestamp() * 1000 + max_wait_ms
        
        while datetime.now().timestamp() * 1000 < deadline:
            await sleep(poll_interval_ms)
            current_app_state = tool_use_context.get_app_state()
            
            has_failed = any(
                c.type == 'failed' and any(
                    pattern.lower() in c.name.lower() for pattern in required_mcp_servers
                )
                for c in current_app_state.mcp.clients
            )
            if has_failed:
                break
            
            still_pending = any(
                c.type == 'pending' and any(
                    pattern.lower() in c.name.lower() for pattern in required_mcp_servers
                )
                for c in current_app_state.mcp.clients
            )
            if not still_pending:
                break
    
    servers_with_tools = set()
    for tool in current_app_state.mcp.tools:
        tool_name = getattr(tool, 'name', '')
        if tool_name and tool_name.startswith('mcp__'):
            parts = tool_name.split('__')
            server_name = parts[1] if len(parts) > 1 else ''
            if server_name:
                servers_with_tools.add(server_name)
    
    if not has_required_mcp_servers(selected_agent, list(servers_with_tools)):
        missing = [
            p for p in required_mcp_servers
            if not any(p.lower() in s.lower() for s in servers_with_tools)
        ]
        servers_list = ', '.join(servers_with_tools) if servers_with_tools else 'none'
        raise Exception(
            f"Agent '{selected_agent.agent_type}' requires MCP servers matching: {', '.join(missing)}. "
            f"MCP servers with tools: {servers_list}. "
            f"Use /mcp to configure and authenticate the required MCP servers."
        )


def _build_run_agent_params(
    selected_agent: AgentDefinition,
    prompt_messages: List[MessageType],
    tool_use_context,
    can_use_tool,
    should_run_async: bool,
    model: Optional[str],
    is_fork_path: bool,
    fork_parent_system_prompt,
    enhanced_system_prompt: Optional[List[str]],
    worktree_info,
    cwd: Optional[str],
    worker_tools: List[Any],
    early_agent_id: str,
    description: str,
) -> Dict[str, Any]:
    """Build parameters for run_agent call."""
    override = None
    if is_fork_path:
        override = {'system_prompt': fork_parent_system_prompt}
    elif enhanced_system_prompt and not worktree_info and not cwd:
        override = {'system_prompt': as_system_prompt(enhanced_system_prompt)}
    
    params = {
        'agent_definition': selected_agent,
        'prompt_messages': prompt_messages,
        'tool_use_context': tool_use_context,
        'can_use_tool': can_use_tool,
        'is_async': should_run_async,
        'query_source': (
            tool_use_context.options.get('query_source') or
            get_query_source_for_agent(selected_agent.agent_type, is_built_in_agent(selected_agent))
        ),
        'model': None if is_fork_path else model,
        'override': override,
        'available_tools': tool_use_context.options.tools if is_fork_path else worker_tools,
        'fork_context_messages': tool_use_context.messages if is_fork_path else None,
        'worktree_path': worktree_info.worktree_path if worktree_info else None,
        'description': description,
    }
    
    if is_fork_path:
        params['use_exact_tools'] = True
    
    return params


async def _cleanup_worktree(worktree_info, early_agent_id: str, selected_agent: AgentDefinition, description: str) -> Dict[str, Optional[str]]:
    """Clean up worktree after agent completion."""
    if not worktree_info:
        return {}
    
    worktree_path = worktree_info.worktree_path
    worktree_branch = worktree_info.worktree_branch
    head_commit = worktree_info.head_commit
    git_root = worktree_info.git_root
    hook_based = worktree_info.hook_based
    
    if hook_based:
        log_for_debugging(f'Hook-based agent worktree kept at: {worktree_path}')
        return {'worktree_path': worktree_path}
    
    if head_commit:
        changed = await has_worktree_changes(worktree_path, head_commit)
        if not changed:
            await remove_agent_worktree(worktree_path, worktree_branch, git_root)
            try:
                await write_agent_metadata(
                    as_agent_id(early_agent_id),
                    {'agent_type': selected_agent.agent_type, 'description': description}
                )
            except Exception as e:
                log_for_debugging(f'Failed to clear worktree metadata: {e}')
            return {}
    
    log_for_debugging(f'Agent worktree has changes, keeping: {worktree_path}')
    return {'worktree_path': worktree_path, 'worktree_branch': worktree_branch}


# ============================================================================
# MISSING HELPER METHODS (Added to complete functionality)
# ============================================================================

@classmethod
async def _spawn_teammate(
    cls,
    name: str,
    prompt: str,
    description: str,
    team_name: str,
    spawn_mode: Optional[Literal['auto', 'plan', 'acceptEdits']],
    model: Optional[str],
    agent_type: Optional[str],
    assistant_message,
    tool_use_context,
):
    """Spawn a teammate agent with tmux integration."""
    # Set agent color if defined
    if agent_type:
        agent_def = next((a for a in tool_use_context.options.agent_definitions.active_agents if a.agent_type == agent_type), None)
        if agent_def and agent_def.color:
            set_agent_color(agent_type, agent_def.color)
    
    # Spawn teammate using multi-agent system
    result = await spawn_teammate({
        'name': name,
        'prompt': prompt,
        'description': description,
        'team_name': team_name,
        'use_splitpane': True,
        'plan_mode_required': spawn_mode == 'plan',
        'model': model,
        'agent_type': agent_type,
        'invoking_request_id': getattr(assistant_message, 'request_id', None) if assistant_message else None,
    }, tool_use_context)
    
    # Format teammate spawn result
    spawn_result: TeammateSpawnedOutput = {
        'status': 'teammate_spawned',
        'prompt': prompt,
        **result.data
    }
    
    return {'data': spawn_result}


@classmethod
async def _handle_remote_isolation(
    cls,
    selected_agent: AgentDefinition,
    effective_isolation: str,
    prompt: str,
    description: str,
    tool_use_context,
):
    """Handle remote isolation by delegating to CCR (remote execution)."""
    from ...utils.analytics import log_event
    
    # Check eligibility for remote execution
    eligibility = await check_remote_agent_eligibility()
    if not eligibility.eligible:
        reasons = '\n'.join(format_precondition_error(e) for e in eligibility.errors)
        raise Exception(f'Cannot launch remote agent:\n{reasons}')
    
    bundle_fail_hint = None
    
    # Create remote session via teleport
    session = await teleport_to_remote({
        'initial_message': prompt,
        'description': description,
        'signal': tool_use_context.abort_controller.signal,
        'on_bundle_fail': lambda msg: setattr(bundle_fail_hint, 'value', msg) if bundle_fail_hint is not None else None,
    })
    
    if not session:
        raise Exception(bundle_fail_hint or 'Failed to create remote session')
    
    # Register remote agent task
    task_info = register_remote_agent_task({
        'remote_task_type': 'remote-agent',
        'session': {
            'id': session.id,
            'title': session.title or description,
        },
        'command': prompt,
        'context': tool_use_context,
        'tool_use_id': tool_use_context.tool_use_id,
    })
    
    task_id = task_info.task_id
    session_id = task_info.session_id
    
    # Log launch event
    log_event('tengu_agent_tool_remote_launched', {
        'agent_type': selected_agent.agent_type,
    })
    
    # Format remote result
    remote_result: RemoteLaunchedOutput = {
        'status': 'remote_launched',
        'task_id': task_id,
        'session_url': get_remote_task_session_url(session_id),
        'description': description,
        'prompt': prompt,
        'output_file': get_task_output_path(task_id),
    }
    
    return {'data': remote_result}


@classmethod
async def _execute_async(
    cls,
    early_agent_id: str,
    description: str,
    prompt: str,
    selected_agent: AgentDefinition,
    root_set_app_state,
    tool_use_context,
    run_agent_params: Dict[str, Any],
    metadata: Dict[str, Any],
    wrap_with_cwd,
    cleanup_worktree_if_needed,
):
    """Execute agent asynchronously (fire-and-forget with background execution)."""
    # Register async agent task
    agent_background_task = register_async_agent({
        'agent_id': early_agent_id,
        'description': description,
        'prompt': prompt,
        'selected_agent': selected_agent,
        'set_app_state': root_set_app_state,
        'tool_use_id': tool_use_context.tool_use_id,
    })
    
    # Register name routing if provided
    name = run_agent_params.get('name')
    if name:
        def update_registry(prev):
            next_reg = dict(prev.get('agent_name_registry', {}))
            next_reg[name] = as_agent_id(early_agent_id)
            return {**prev, 'agent_name_registry': next_reg}
        
        root_set_app_state(update_registry)
    
    # Agent context for analytics
    async_agent_context = {
        'agent_id': early_agent_id,
        'parent_session_id': get_parent_session_id(),
        'agent_type': 'subagent',
        'subagent_name': selected_agent.agent_type,
        'is_built_in': is_built_in_agent(selected_agent),
        'invoking_request_id': metadata.get('assistant_message_request_id'),
        'invocation_kind': 'spawn',
        'invocation_emitted': False,
    }
    
    # Fire-and-forget execution wrapper
    async def execute():
        tracker = None  # Will be set by run_async_agent_lifecycle
        stop_foreground_summarization = None
        
        def handle_cache_safe_params(params):
            """Handle cache-safe parameters and start agent summarization if enabled."""
            nonlocal stop_foreground_summarization
            if get_sdk_agent_progress_summaries_enabled():
                result = start_agent_summarization(
                    agent_background_task.agent_id,
                    as_agent_id(agent_background_task.agent_id),
                    params,
                    root_set_app_state
                )
                stop_foreground_summarization = result['stop']
            
            return run_agent({
                **run_agent_params,
                'override': {
                    **run_agent_params.get('override', {}),
                    'agent_id': as_agent_id(agent_background_task.agent_id),
                    'abort_controller': agent_background_task.abort_controller,
                },
            })
        
        try:
            result = await run_with_agent_context(async_agent_context, lambda: wrap_with_cwd(
                run_async_agent_lifecycle({
                    'task_id': agent_background_task.agent_id,
                    'abort_controller': agent_background_task.abort_controller,
                    'make_stream': handle_cache_safe_params,
                    'metadata': metadata,
                    'description': description,
                    'tool_use_context': tool_use_context,
                    'root_set_app_state': root_set_app_state,
                    'agent_id_for_cleanup': early_agent_id,
                    'enable_summarization': (
                        is_coordinator_mode() or 
                        is_fork_subagent_enabled() or 
                        get_sdk_agent_progress_summaries_enabled()
                    ),
                    'get_worktree_result': cleanup_worktree_if_needed,
                })
            ))
            
            # Mark task completed FIRST so TaskOutput(block=true) unblocks immediately
            complete_async_agent(result, root_set_app_state)
            
            # Extract text from agent result content for the notification
            final_message = extract_text_content(result.content, '\n') if result and result.content else ''
            
            # Success: enqueue completion notification
            worktree_result = await cleanup_worktree_if_needed()
            enqueue_agent_notification({
                'taskId': agent_background_task.agent_id,
                'description': description,
                'status': 'completed',
                'setAppState': root_set_app_state,
                'finalMessage': final_message,
                'usage': {
                    'totalTokens': get_token_count_from_tracker(tracker) if tracker else 0,
                    'toolUses': result.total_tool_use_count if result else 0,
                    'durationMs': result.total_duration_ms if result else 0,
                },
                'toolUseId': tool_use_context.tool_use_id,
                **worktree_result,
            })
        except AbortError:
            # User cancelled background task
            kill_async_agent(agent_background_task.agent_id, root_set_app_state)
            log_event('tengu_agent_tool_terminated', {
                'agent_type': metadata['agent_type'],
                'model': metadata['resolved_agent_model'],
                'duration_ms': datetime.now().timestamp() * 1000 - metadata['start_time'],
                'is_async': True,
                'is_built_in_agent': metadata.get('is_built_in_agent', False),
                'reason': 'user_cancel_background',
            })
            worktree_result = await cleanup_worktree_if_needed()
            partial_result = extract_partial_result([])
            enqueue_agent_notification({
                'taskId': agent_background_task.agent_id,
                'description': description,
                'status': 'killed',
                'setAppState': root_set_app_state,
                'toolUseId': tool_use_context.tool_use_id,
                'finalMessage': partial_result,
                **worktree_result,
            })
        except Exception as error:
            # Agent failed
            error_msg = error_message(error)
            fail_async_agent(agent_background_task.agent_id, error_msg, root_set_app_state)
            worktree_result = await cleanup_worktree_if_needed()
            enqueue_agent_notification({
                'taskId': agent_background_task.agent_id,
                'description': description,
                'status': 'failed',
                'error': error_msg,
                'setAppState': root_set_app_state,
                'toolUseId': tool_use_context.tool_use_id,
                **worktree_result,
            })
        finally:
            pass  # Cleanup handled in lifecycle
    
    # Schedule without awaiting (fire-and-forget)
    asyncio.create_task(execute())
    
    # Return immediately with async_launched status
    can_read_output_file = any(
        tool_matches_name(t, FILE_READ_TOOL_NAME) or tool_matches_name(t, BASH_TOOL_NAME)
        for t in tool_use_context.options.tools
    )
    
    return {
        'data': {
            'is_async': True,
            'status': 'async_launched',
            'agent_id': agent_background_task.agent_id,
            'description': description,
            'prompt': prompt,
            'output_file': get_task_output_path(agent_background_task.agent_id),
            'can_read_output_file': can_read_output_file,
        }
    }


@classmethod
async def _execute_sync(
    cls,
    early_agent_id: str,
    description: str,
    prompt: str,
    selected_agent: AgentDefinition,
    root_set_app_state,
    tool_use_context,
    run_agent_params: Dict[str, Any],
    metadata: Dict[str, Any],
    wrap_with_cwd,
    cleanup_worktree_if_needed,
    on_progress=None,
    assistant_message=None,
):
    """Execute agent synchronously with optional background promotion."""
    sync_agent_id = as_agent_id(early_agent_id)
    
    # Agent context for analytics
    sync_agent_context = {
        'agent_id': sync_agent_id,
        'parent_session_id': get_parent_session_id(),
        'agent_type': 'subagent',
        'subagent_name': selected_agent.agent_type,
        'is_built_in': is_built_in_agent(selected_agent),
        'invoking_request_id': metadata.get('assistant_message_request_id'),
        'invocation_kind': 'spawn',
        'invocation_emitted': False,
    }
    
    async def execute_sync():
        agent_messages = []
        agent_start_time = datetime.now().timestamp() * 1000
        sync_tracker = create_progress_tracker()
        sync_resolve_activity = create_activity_description_resolver(tool_use_context.options.tools)
        
        # Initial progress message
        prompt_messages = run_agent_params.get('prompt_messages', [])
        if prompt_messages and on_progress:
            normalized = normalize_messages(prompt_messages)
            # Type guard: find first user message (normalized with content)
            def is_normalized_user_message(msg):
                """Check if message is a normalized user message (user type with valid content)."""
                return (
                    msg.type == 'user' and
                    hasattr(msg, 'content') and
                    msg.content is not None
                )
            
            first_msg = next((m for m in normalized if is_normalized_user_message(m)), None)
            if first_msg:
                on_progress({
                    'tool_use_id': f"agent_{assistant_message.message.id}",
                    'data': {
                        'message': first_msg,
                        'type': 'agent_progress',
                        'prompt': prompt,
                        'agent_id': sync_agent_id,
                    }
                })
        
        # Foreground task registration
        foreground_task_id = None
        background_promise = None
        cancel_auto_background = None
        
        if not IS_BACKGROUND_TASKS_DISABLED:
            registration = register_agent_foreground({
                'agent_id': sync_agent_id,
                'description': description,
                'prompt': prompt,
                'selected_agent': selected_agent,
                'set_app_state': root_set_app_state,
                'tool_use_id': tool_use_context.tool_use_id,
                'auto_background_ms': get_auto_background_ms() or None,
            })
            foreground_task_id = registration.task_id
            background_promise = registration.background_signal
            cancel_auto_background = registration.cancel_auto_background
        
        # UI state
        background_hint_shown = False
        was_backgrounded = False
        stop_foreground_summarization = None
        
        # Get agent iterator
        agent_iterator = run_agent({
            **run_agent_params,
            'override': {
                **run_agent_params.get('override', {}),
                'agent_id': sync_agent_id,
            },
        })
        
        sync_agent_error = None
        was_aborted = False
        worktree_result = {}
        
        try:
            async for message in agent_iterator:
                elapsed = (datetime.now().timestamp() * 1000) - agent_start_time
                
                # Show background hint after threshold
                if (not IS_BACKGROUND_TASKS_DISABLED and 
                    not background_hint_shown and 
                    elapsed >= PROGRESS_THRESHOLD_MS and 
                    hasattr(tool_use_context, 'set_tool_jsx')):
                    background_hint_shown = True
                    tool_use_context.set_tool_jsx(BackgroundHint())
                
                # Process message
                agent_messages.append(message)
                
                # Update progress
                update_progress_from_message(sync_tracker, message, sync_resolve_activity, tool_use_context.options.tools)
                
                if foreground_task_id:
                    last_tool_name = get_last_tool_use_name(message)
                    if last_tool_name:
                        emit_task_progress(
                            sync_tracker, foreground_task_id, tool_use_context.tool_use_id,
                            description, agent_start_time, last_tool_name
                        )
                        
                        if get_sdk_agent_progress_summaries_enabled():
                            update_async_agent_progress(
                                foreground_task_id,
                                get_progress_update(sync_tracker),
                                root_set_app_state
                            )
                
                # Forward bash progress
                if (getattr(message, 'type', None) == 'progress' and
                    getattr(getattr(message, 'data', None), 'type', None) in ('bash_progress', 'powershell_progress') and
                    on_progress):
                    on_progress({
                        'tool_use_id': getattr(message, 'tool_use_id', ''),
                        'data': getattr(message, 'data', {}),
                    })
                
                # Skip non-content messages
                if message.type not in ('assistant', 'user'):
                    continue
                
                # Update token count
                if message.type == 'assistant':
                    content_length = get_assistant_message_content_length(message)
                    if content_length > 0:
                        tool_use_context.set_response_length(lambda length: length + content_length)
                
                # Forward progress updates
                normalized_new = normalize_messages([message])
                for m in normalized_new:
                    for content in m.message.content:
                        if content.type not in ('tool_use', 'tool_result'):
                            continue
                        
                        if on_progress:
                            on_progress({
                                'tool_use_id': f"agent_{assistant_message.message.id}",
                                'data': {
                                    'message': m,
                                    'type': 'agent_progress',
                                    'prompt': '',
                                    'agent_id': sync_agent_id,
                                }
                            })
        
        except AbortError as e:
            was_aborted = True
            
            # Check if last message is synthetic (user cancellation pattern)
            last_message = next((m for m in reversed(agent_messages) if m.type not in ('system', 'progress')), None)
            if last_message and is_synthetic_message(last_message):
                log_event('tengu_agent_tool_terminated', {
                    'agent_type': metadata['agent_type'],
                    'model': metadata['resolved_agent_model'],
                    'duration_ms': (datetime.now().timestamp() * 1000) - metadata['start_time'],
                    'is_async': False,
                    'is_built_in_agent': metadata['is_built_in_agent'],
                    'reason': 'user_cancel_sync',
                })
                raise
        
        except Exception as e:
            log_for_debugging(f'Sync agent error: {error_message(e)}', {'level': 'error'})
            sync_agent_error = to_error(e)
        
        finally:
            # Cleanup UI
            if hasattr(tool_use_context, 'set_tool_jsx'):
                tool_use_context.set_tool_jsx(None)
            
            # Unregister foreground task
            if foreground_task_id and not was_backgrounded:
                unregister_agent_foreground(foreground_task_id, root_set_app_state)
                
                # SDK notification
                progress = get_progress_update(sync_tracker)
                enqueue_sdk_event({
                    'type': 'system',
                    'subtype': 'task_notification',
                    'task_id': foreground_task_id,
                    'tool_use_id': tool_use_context.tool_use_id,
                    'status': 'failed' if sync_agent_error else 'stopped' if was_aborted else 'completed',
                    'output_file': '',
                    'summary': description,
                    'usage': {
                        'total_tokens': progress.token_count,
                        'tool_uses': progress.tool_use_count,
                        'duration_ms': (datetime.now().timestamp() * 1000) - agent_start_time,
                    }
                })
            
            # Cleanup skills and state
            clear_invoked_skills_for_agent(sync_agent_id)
            
            if not was_backgrounded:
                clear_dump_state(sync_agent_id)
                worktree_result = await cleanup_worktree_if_needed()
            
            # Cancel auto-background timer
            if cancel_auto_background:
                cancel_auto_background()
        
        # Handle errors with partial results
        if sync_agent_error:
            has_assistant_messages = any(m.type == 'assistant' for m in agent_messages)
            if not has_assistant_messages:
                raise sync_agent_error
            
            log_for_debugging(f'Sync agent recovering with {len(agent_messages)} messages')
        
        # Finalize result
        agent_result = finalize_agent_tool(agent_messages, sync_agent_id, metadata)
        
        # Handoff classification
        if feature('TRANSCRIPT_CLASSIFIER'):
            handoff_warning = await classify_handoff_if_needed({
                'agent_messages': agent_messages,
                'tools': tool_use_context.options.tools,
                'tool_permission_context': tool_use_context.get_app_state().tool_permission_context,
                'abort_signal': tool_use_context.abort_controller.signal,
                'subagent_type': selected_agent.agent_type,
                'total_tool_use_count': agent_result.total_tool_use_count,
            })
            
            if handoff_warning:
                agent_result.content = [{'type': 'text', 'text': handoff_warning}, *agent_result.content]
        
        return {
            'data': {
                'status': 'completed',
                'prompt': prompt,
                **agent_result,
                **worktree_result,
            }
        }
    
    return await run_with_agent_context(sync_agent_context, lambda: wrap_with_cwd(execute_sync))


# ============================================================================
# MAIN AGENTTOOL CLASS
# ============================================================================

@build_tool
class AgentTool:
    """Launch a new agent - the core sub-agent spawning tool."""
    
    name = AGENT_TOOL_NAME
    search_hint = "delegate work to a subagent"
    aliases = [LEGACY_AGENT_TOOL_NAME]
    max_result_size_chars = 100_000
    
    @staticmethod
    async def description() -> str:
        return "Launch a new agent"
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        return input_schema()
    
    @property
    def output_schema(self) -> OutputSchema:
        return output_schema()
    
    @classmethod
    async def call(
        cls,
        prompt: str,
        description: str,
        subagent_type: Optional[str] = None,
        model: Optional[Literal['sonnet', 'opus', 'haiku']] = None,
        run_in_background: Optional[bool] = None,
        name: Optional[str] = None,
        team_name: Optional[str] = None,
        mode: Optional[Literal['auto', 'plan', 'acceptEdits']] = None,
        isolation: Optional[Literal['worktree', 'remote']] = None,
        cwd: Optional[str] = None,
        tool_use_context=None,
        can_use_tool=None,
        assistant_message=None,
        on_progress=None,
    ):
        """Execute the AgentTool - spawn a sub-agent."""
        start_time = datetime.now()
        model_param = None if is_coordinator_mode() else model
        
        app_state = tool_use_context.get_app_state()
        permission_mode = app_state.tool_permission_context.mode
        root_set_app_state = tool_use_context.set_app_state_for_tasks or tool_use_context.set_app_state
        
        if team_name and not is_agent_swarms_enabled():
            raise Exception('Agent Teams is not yet available on your plan.')
        
        resolved_team_name = resolve_team_name(team_name, app_state)
        
        if is_teammate() and resolved_team_name and name:
            raise Exception(
                'Teammates cannot spawn other teammates — the team roster is flat. '
                'To spawn a subagent instead, omit the `name` parameter.'
            )
        
        if is_in_process_teammate() and resolved_team_name and run_in_background is True:
            raise Exception(
                'In-process teammates cannot spawn background agents. '
                'Use run_in_background=false for synchronous subagents.'
            )
        
        if resolved_team_name and name:
            return await cls._spawn_teammate(
                name=name,
                prompt=prompt,
                description=description,
                team_name=resolved_team_name,
                spawn_mode=mode,
                model=model_param or model,
                agent_type=subagent_type,
                assistant_message=assistant_message,
                tool_use_context=tool_use_context,
            )
        
        # Determine effective agent type
        effective_type = subagent_type or (is_fork_subagent_enabled() and None or GENERAL_PURPOSE_AGENT.agent_type)
        is_fork_path = effective_type is None
        
        # Select agent
        selected_agent = await _select_agent(
            effective_type, tool_use_context, app_state, is_fork_path
        )
        
        # Check in-process teammate constraint for background agents
        if is_in_process_teammate() and resolved_team_name and selected_agent.background is True:
            raise Exception(
                f"In-process teammates cannot spawn background agents. Agent '{selected_agent.agent_type}' has background: true in its definition."
            )
        
        # Check MCP server requirements
        await _check_mcp_servers(selected_agent, app_state, tool_use_context)
        
        # Initialize agent color
        if selected_agent.color:
            set_agent_color(selected_agent.agent_type, selected_agent.color)
        
        # Resolve agent model for logging
        resolved_agent_model = get_agent_model(
            selected_agent.model, 
            tool_use_context.options.main_loop_model,
            None if is_fork_path else model,
            permission_mode
        )
        
        # Log selection event
        log_event('tengu_agent_tool_selected', {
            'agent_type': selected_agent.agent_type,
            'model': resolved_agent_model,
            'source': selected_agent.source,
            'color': selected_agent.color,
            'is_built_in_agent': is_built_in_agent(selected_agent),
            'is_resume': False,
            'is_async': (run_in_background is True or selected_agent.background is True) and not IS_BACKGROUND_TASKS_DISABLED,
            'is_fork': is_fork_path
        })
        
        # Resolve isolation mode
        effective_isolation = isolation or selected_agent.isolation
        
        # Handle remote isolation
        if effective_isolation == 'remote':
            return await cls._handle_remote_isolation(
                selected_agent, effective_isolation, prompt, description,
                tool_use_context
            )
        
        # Build system prompt and messages
        enhanced_system_prompt = None
        fork_parent_system_prompt = None
        prompt_messages = []
        
        if is_fork_path:
            if tool_use_context.rendered_system_prompt:
                fork_parent_system_prompt = tool_use_context.rendered_system_prompt
            else:
                main_thread_agent_definition = (
                    app_state.agent and 
                    app_state.agent_definitions.active_agents and
                    next((a for a in app_state.agent_definitions.active_agents if a.agent_type == app_state.agent), None)
                )
                additional_working_directories = list(app_state.tool_permission_context.additional_working_directories.keys())
                default_system_prompt = await get_system_prompt(
                    tool_use_context.options.tools,
                    tool_use_context.options.main_loop_model,
                    additional_working_directories,
                    tool_use_context.options.mcp_clients
                )
                fork_parent_system_prompt = build_effective_system_prompt({
                    'main_thread_agent_definition': main_thread_agent_definition,
                    'tool_use_context': tool_use_context,
                    'custom_system_prompt': tool_use_context.options.custom_system_prompt,
                    'default_system_prompt': default_system_prompt,
                    'append_system_prompt': tool_use_context.options.append_system_prompt
                })
            prompt_messages = build_forked_messages(prompt, assistant_message)
        else:
            try:
                additional_working_directories = list(app_state.tool_permission_context.additional_working_directories.keys())
                agent_prompt = selected_agent.get_system_prompt({'tool_use_context': tool_use_context})
                
                if selected_agent.memory:
                    log_event('tengu_agent_memory_loaded', {
                        'agent_type': selected_agent.agent_type,
                        'scope': selected_agent.memory,
                        'source': 'subagent'
                    })
                
                enhanced_system_prompt = await enhance_system_prompt_with_env_details(
                    [agent_prompt], resolved_agent_model, additional_working_directories
                )
            except Exception as e:
                log_for_debugging(f'Failed to get system prompt for agent {selected_agent.agent_type}: {error_message(e)}')
            
            prompt_messages = [create_user_message({'content': prompt})]
        
        # Build metadata
        metadata = {
            'prompt': prompt,
            'resolved_agent_model': resolved_agent_model,
            'is_built_in_agent': is_built_in_agent(selected_agent),
            'start_time': start_time.timestamp() * 1000,
            'agent_type': selected_agent.agent_type,
            'is_async': (run_in_background is True or selected_agent.background is True) and not IS_BACKGROUND_TASKS_DISABLED,
            'assistant_message_request_id': getattr(assistant_message, 'request_id', None) if assistant_message else None,
            'description': description,
            'agent_id': None,
        }
        
        # Determine if should run async
        is_coordinator = is_env_truthy(os.environ.get("CLAUDE_CODE_COORDINATOR_MODE", "")) if feature('COORDINATOR_MODE') else False
        force_async = is_fork_subagent_enabled()
        assistant_force_async = feature('KAIROS') and app_state.kairos_enabled
        proactive_active = False  # Placeholder for proactive module
        
        should_run_async = (
            run_in_background is True or 
            selected_agent.background is True or 
            is_coordinator or 
            force_async or 
            assistant_force_async or 
            proactive_active
        ) and not IS_BACKGROUND_TASKS_DISABLED
        
        # Assemble worker tools
        worker_permission_context = {
            **app_state.tool_permission_context,
            'mode': selected_agent.permission_mode or 'acceptEdits'
        }
        worker_tools = assemble_tool_pool(worker_permission_context, app_state.mcp.tools)
        
        # Create early agent ID
        early_agent_id = create_agent_id()
        
        # Set up worktree if requested
        worktree_info = None
        if effective_isolation == 'worktree':
            slug = f'agent-{early_agent_id[:8]}'
            worktree_info = await create_agent_worktree(slug)
        
        # Add worktree notice if needed
        if is_fork_path and worktree_info:
            prompt_messages.append(create_user_message({
                'content': build_worktree_notice(get_cwd(), worktree_info.worktree_path)
            }))
        
        # Build run_agent parameters
        run_agent_params = _build_run_agent_params(
            selected_agent, prompt_messages, tool_use_context, can_use_tool,
            should_run_async, model, is_fork_path, fork_parent_system_prompt,
            enhanced_system_prompt, worktree_info, cwd, worker_tools, early_agent_id, description
        )
        
        # CWD override helper - use async wrapper to ensure consistent awaiting
        cwd_override_path = cwd or (worktree_info.worktree_path if worktree_info else None)
        async def wrap_with_cwd(fn):
            if cwd_override_path:
                return await run_with_cwd_override(cwd_override_path, fn)
            return await fn()
        
        # Cleanup helper
        cleanup_worktree_if_needed = lambda: _cleanup_worktree(worktree_info, early_agent_id, selected_agent, description)
        
        # Execute async or sync
        if should_run_async:
            return await cls._execute_async(
                early_agent_id, description, prompt, selected_agent,
                root_set_app_state, tool_use_context, run_agent_params,
                metadata, wrap_with_cwd, cleanup_worktree_if_needed,
            )
        else:
            return await cls._execute_sync(
                early_agent_id, description, prompt, selected_agent,
                root_set_app_state, tool_use_context, run_agent_params,
                metadata, wrap_with_cwd, cleanup_worktree_if_needed,
                on_progress, assistant_message,
            )
    
    @staticmethod
    def is_read_only() -> bool:
        return True
    
    @staticmethod
    def to_auto_classifier_input(input_data: Dict[str, Any]) -> str:
        subagent_type = input_data.get('subagent_type')
        mode = input_data.get('mode')
        
        tags = []
        if subagent_type:
            tags.append(subagent_type)
        if mode:
            tags.append(f'mode={mode}')
        
        prefix = f"({', '.join(tags)}): " if tags else ': '
        return f"{prefix}{input_data['prompt']}"
    
    @staticmethod
    def is_concurrency_safe() -> bool:
        return True
    
    @staticmethod
    def get_activity_description(input_data: Optional[Dict[str, Any]]) -> str:
        return input_data.get('description', 'Running task') if input_data else 'Running task'
    
    @staticmethod
    async def check_permissions(input_data: Dict[str, Any], context) -> Dict[str, Any]:
        app_state = context.get_app_state()
        
        if app_state.tool_permission_context.mode == 'auto':
            return {
                'behavior': 'passthrough',
                'message': 'Agent tool requires permission to spawn sub-agents.',
            }
        
        return {
            'behavior': 'allow',
            'updated_input': input_data,
        }
    
    @staticmethod
    def map_tool_result_to_tool_result_block(data: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
        status = data.get('status')
        
        if status == 'teammate_spawned':
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': [{
                    'type': 'text',
                    'text': f"""Spawned successfully.
agent_id: {data['teammate_id']}
name: {data['name']}
team_name: {data['team_name']}
The agent is now running and will receive instructions via mailbox.""",
                }],
            }
        
        if status == 'remote_launched':
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': [{
                    'type': 'text',
                    'text': f"""Remote agent launched in CCR.
taskId: {data['task_id']}
session_url: {data['session_url']}
output_file: {data['output_file']}
The agent is running remotely. You will be notified automatically when it completes.
Briefly tell the user what you launched and end your response.""",
                }],
            }
        
        if status == 'async_launched':
            prefix = (
                f"Async agent launched successfully.\n"
                f"agentId: {data['agent_id']} (internal ID - do not mention to user. "
                f"Use SendMessage with to: '{data['agent_id']}' to continue this agent.)\n"
                f"The agent is working in the background. "
                f"You will be notified automatically when it completes."
            )
            
            can_read = data.get('can_read_output_file', False)
            if can_read:
                instructions = (
                    f"Do not duplicate this agent's work — avoid working with the same files "
                    f"or topics it is using. Work on non-overlapping tasks, or briefly tell the "
                    f"user what you launched and end your response.\n"
                    f"output_file: {data['output_file']}\n"
                    f"If asked, you can check progress before completion by using "
                    f"{FILE_READ_TOOL_NAME} or {BASH_TOOL_NAME} tail on the output file."
                )
            else:
                instructions = (
                    "Briefly tell the user what you launched and end your response. "
                    "Do not generate any other text — agent results will arrive in a subsequent message."
                )
            
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': [{
                    'type': 'text',
                    'text': f'{prefix}\n{instructions}',
                }],
            }
        
        if status == 'completed':
            worktree_path = data.get('worktree_path')
            worktree_info_text = ''
            if worktree_path:
                worktree_branch = data.get('worktree_branch', '')
                worktree_info_text = f'\nworktreePath: {worktree_path}\nworktreeBranch: {worktree_branch}'
            
            content_or_marker = data.get('content', []) or [{'type': 'text', 'text': '(Subagent completed but returned no output.)'}]
            
            agent_type = data.get('agent_type')
            if agent_type and agent_type in ONE_SHOT_BUILTIN_AGENT_TYPES and not worktree_info_text:
                return {
                    'tool_use_id': tool_use_id,
                    'type': 'tool_result',
                    'content': content_or_marker,
                }
            
            usage_block = (
                f"<usage>total_tokens: {data['total_tokens']}\n"
                f"tool_uses: {data['total_tool_use_count']}\n"
                f"duration_ms: {data['total_duration_ms']}</usage>"
            )
            
            continuation_hint = f"agentId: {data['agent_id']} (use SendMessage with to: '{data['agent_id']}' to continue this agent)"
            
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': [
                    *content_or_marker,
                    {
                        'type': 'text',
                        'text': f'{continuation_hint}{worktree_info_text}\n{usage_block}',
                    },
                ],
            }
        
        raise ValueError(f'Unexpected agent tool result status: {status}')
    
    # Aliases for render methods
    render_tool_result_message = staticmethod(render_tool_result_message)
    render_tool_use_message = staticmethod(render_tool_use_message)
    render_tool_use_tag = staticmethod(render_tool_use_tag)
    render_tool_use_progress_message = staticmethod(render_tool_use_progress_message)
    render_tool_use_rejected_message = staticmethod(render_tool_use_rejected_message)
    render_tool_use_error_message = staticmethod(render_tool_use_error_message)
    render_grouped_tool_use = staticmethod(render_grouped_agent_tool_use)
    
    # User-facing display helpers
    user_facing_name = staticmethod(user_facing_name)
    user_facing_name_background_color = staticmethod(user_facing_name_background_color)


# Export instance
agent_tool = AgentTool()
