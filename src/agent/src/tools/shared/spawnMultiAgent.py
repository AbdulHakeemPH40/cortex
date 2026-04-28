"""
Shared spawn module for teammate creation.
Extracted from TeammateTool to allow reuse by AgentTool.

NOTE: This is a Python conversion of the TypeScript spawn system.
Some React/JSX-specific features have been simplified or commented out.
"""

import os
import time
import asyncio
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

# ============================================================================
# Defensive Imports - Some modules may not exist in Python
# ============================================================================

try:
    from bootstrap.state import (
        get_chrome_flag_override,
        get_flag_settings_path,
        get_inline_plugins,
        get_main_loop_model_override,
        get_session_bypass_permissions_mode,
        get_session_id,
    )
except ImportError:
    # Stubs for missing imports
    def get_chrome_flag_override(): return None
    def get_flag_settings_path(): return None
    def get_inline_plugins(): return []
    def get_main_loop_model_override(): return None
    def get_session_bypass_permissions_mode(): return False
    def get_session_id(): return None

try:
    from state.AppState import AppState
except ImportError:
    AppState = Any  # Type stub

try:
    from Task import create_task_state_base, generate_task_id
except ImportError:
    def create_task_state_base(*args): return {}
    def generate_task_id(prefix): return f"{prefix}_{int(time.time())}"

try:
    from Tool import ToolUseContext
except ImportError:
    ToolUseContext = Any  # Type stub

try:
    from utils.agent_id import format_agent_id
except ImportError:
    def format_agent_id(name, team): return f"{name}@{team}"

try:
    from utils.bash.shell_quote import quote
except ImportError:
    # Simple shell quote fallback
    def quote(args):
        return ' '.join(f"'{arg}'" for arg in args)

try:
    from utils.bundled_mode import is_in_bundled_mode
except ImportError:
    def is_in_bundled_mode(): return False

try:
    from utils.config import get_global_config
except ImportError:
    class FakeConfig:
        teammate_default_model = None
    def get_global_config(): return FakeConfig()

try:
    from utils.cwd import get_cwd
except ImportError:
    def get_cwd(): return os.getcwd()

try:
    from utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(msg): pass

try:
    from utils.errors import error_message
except ImportError:
    def error_message(e): return str(e)

try:
    from utils.exec_file_no_throw import exec_file_no_throw
except ImportError:
    async def exec_file_no_throw(cmd, args):
        """Stub - implement actual subprocess execution"""
        class Result:
            code = 1
            stdout = ''
            stderr = 'exec_file_no_throw not implemented'
        return Result()

try:
    from utils.model.model import parse_user_specified_model
except ImportError:
    def parse_user_specified_model(model): return model

try:
    from utils.permissions.PermissionMode import PermissionMode
except ImportError:
    PermissionMode = str  # Type stub

try:
    from utils.swarm.backends.detection import is_tmux_available
except ImportError:
    async def is_tmux_available(): return False

try:
    from utils.swarm.backends.registry import (
        detect_and_get_backend,
        get_backend_by_type,
        is_in_process_enabled,
        mark_in_process_fallback,
        reset_backend_detection,
    )
except ImportError:
    async def detect_and_get_backend(): raise NotImplementedError("Backend detection not implemented")
    def get_backend_by_type(t): raise NotImplementedError()
    def is_in_process_enabled(): return False
    def mark_in_process_fallback(): pass
    def reset_backend_detection(): pass

try:
    from utils.swarm.backends.teammate_mode_snapshot import get_teammate_mode_from_snapshot
except ImportError:
    def get_teammate_mode_from_snapshot(): return 'auto'

try:
    from utils.swarm.backends.types import BackendType, is_pane_backend
except ImportError:
    BackendType = str
    def is_pane_backend(backend): return False

try:
    from utils.swarm.constants import (
        SWARM_SESSION_NAME,
        TEAM_LEAD_NAME,
        TEAMMATE_COMMAND_ENV_VAR,
        TMUX_COMMAND,
    )
except ImportError:
    SWARM_SESSION_NAME = 'cortex-swarm'
    TEAM_LEAD_NAME = 'team-lead'
    TEAMMATE_COMMAND_ENV_VAR = 'CORTEX_TEAMMATE_COMMAND'
    TMUX_COMMAND = 'tmux'

try:
    from utils.swarm.It2SetupPrompt import It2SetupPrompt
except ImportError:
    It2SetupPrompt = None

try:
    from utils.swarm.in_process_runner import start_in_process_teammate
except ImportError:
    async def start_in_process_teammate(*args, **kwargs): pass

try:
    from utils.swarm.spawn_in_process import spawn_in_process_teammate, InProcessSpawnConfig
except ImportError:
    async def spawn_in_process_teammate(config, context):
        return {'success': False, 'error': 'Not implemented'}
    InProcessSpawnConfig = Any

try:
    from utils.swarm.spawn_utils import build_inherited_env_vars
except ImportError:
    def build_inherited_env_vars(): return ''

try:
    from utils.swarm.team_helpers import (
        read_team_file_async,
        sanitize_agent_name,
        sanitize_name,
        write_team_file_async,
    )
except ImportError:
    async def read_team_file_async(team): return None
    def sanitize_agent_name(name): return name.replace('@', '-')
    def sanitize_name(name): return name.replace(' ', '-')
    async def write_team_file_async(team, data): pass

try:
    from utils.swarm.teammate_layout_manager import (
        assign_teammate_color,
        create_teammate_pane_in_swarm_view,
        enable_pane_border_status,
        is_inside_tmux,
        send_command_to_pane,
    )
except ImportError:
    def assign_teammate_color(agent_id): return '#FFFFFF'
    async def create_teammate_pane_in_swarm_view(name, color):
        return {'paneId': 'stub', 'isFirstTeammate': True}
    async def enable_pane_border_status(): pass
    async def is_inside_tmux(): return False
    async def send_command_to_pane(pane, cmd, use_socket): pass

try:
    from utils.swarm.teammate_model import get_hardcoded_teammate_model_fallback
except ImportError:
    def get_hardcoded_teammate_model_fallback(): return 'opus'

try:
    from utils.task.framework import register_task
except ImportError:
    def register_task(task, set_state): pass

try:
    from utils.teammate_mailbox import write_to_mailbox
except ImportError:
    async def write_to_mailbox(name, msg, team): pass

try:
    from tools.AgentTool.load_agents_dir import is_custom_agent, CustomAgentDefinition
except ImportError:
    def is_custom_agent(agent): return False
    CustomAgentDefinition = Any


# ============================================================================
# Helper Functions
# ============================================================================

def _get_default_teammate_model(leader_model: Optional[str]) -> str:
    """Get default teammate model based on configuration."""
    configured = get_global_config().teammate_default_model
    if configured is None:
        # User picked "Default" in the /config picker — follow the leader.
        return leader_model or get_hardcoded_teammate_model_fallback()
    if configured is not None:
        return parse_user_specified_model(configured)
    return get_hardcoded_teammate_model_fallback()


def resolve_teammate_model(
    input_model: Optional[str],
    leader_model: Optional[str],
) -> str:
    """
    Resolve a teammate model value. Handles the 'inherit' alias (from agent
    frontmatter) by substituting the leader's model. gh-31069: 'inherit' was
    passed literally to --model, producing "It may not exist or you may not
    have access". If leader model is null (not yet set), falls through to the
    default.
    """
    if input_model == 'inherit':
        return leader_model or _get_default_teammate_model(leader_model)
    return input_model or _get_default_teammate_model(leader_model)


# ============================================================================
# Type Definitions
# ============================================================================

@dataclass
class SpawnOutput:
    teammate_id: str
    agent_id: str
    agent_type: Optional[str] = None
    model: Optional[str] = None
    name: str = ''
    color: Optional[str] = None
    tmux_session_name: str = ''
    tmux_window_name: str = ''
    tmux_pane_id: str = ''
    team_name: Optional[str] = None
    is_splitpane: Optional[bool] = None
    plan_mode_required: Optional[bool] = None


@dataclass
class SpawnTeammateConfig:
    name: str
    prompt: str
    team_name: Optional[str] = None
    cwd: Optional[str] = None
    use_splitpane: Optional[bool] = None
    plan_mode_required: Optional[bool] = None
    model: Optional[str] = None
    agent_type: Optional[str] = None
    description: Optional[str] = None
    invoking_request_id: Optional[str] = None


# Internal input type
class SpawnInput:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name', '')
        self.prompt = kwargs.get('prompt', '')
        self.team_name = kwargs.get('team_name')
        self.cwd = kwargs.get('cwd')
        self.use_splitpane = kwargs.get('use_splitpane')
        self.plan_mode_required = kwargs.get('plan_mode_required')
        self.model = kwargs.get('model')
        self.agent_type = kwargs.get('agent_type')
        self.description = kwargs.get('description')
        self.invoking_request_id = kwargs.get('invoking_request_id')


# ============================================================================
# Helper Functions
# ============================================================================

async def _has_session(session_name: str) -> bool:
    """Checks if a tmux session exists"""
    result = await exec_file_no_throw(TMUX_COMMAND, ['has-session', '-t', session_name])
    return result.code == 0


async def _ensure_session(session_name: str) -> None:
    """Creates a new tmux session if it doesn't exist"""
    exists = await _has_session(session_name)
    if not exists:
        result = await exec_file_no_throw(TMUX_COMMAND, [
            'new-session', '-d', '-s', session_name
        ])
        if result.code != 0:
            raise RuntimeError(
                f"Failed to create tmux session '{session_name}': {result.stderr or 'Unknown error'}"
            )


def _get_teammate_command() -> str:
    """
    Gets the command to spawn a teammate.
    For native builds (compiled binaries), use process.execPath.
    For non-native (node/bun running a script), use process.argv[1].
    """
    if os.environ.get(TEAMMATE_COMMAND_ENV_VAR):
        return os.environ[TEAMMATE_COMMAND_ENV_VAR]
    return process.execPath if is_in_bundled_mode() else (
        os.sys.argv[1] if len(os.sys.argv) > 1 else 'python'
    )


def _build_inherited_cli_flags(
    plan_mode_required: Optional[bool] = None,
    permission_mode: Optional[str] = None,
) -> str:
    """
    Builds AI agent flags to propagate from the current session to spawned teammates.
    This ensures teammates inherit important settings like permission mode,
    model selection, and plugin configuration from their parent.
    """
    flags = []
    
    # Propagate permission mode to teammates, but NOT if plan mode is required
    # Plan mode takes precedence over bypass permissions for safety
    if plan_mode_required:
        # Don't inherit bypass permissions when plan mode is required
        pass
    elif permission_mode == 'bypassPermissions' or get_session_bypass_permissions_mode():
        flags.append('--dangerously-skip-permissions')
    elif permission_mode == 'acceptEdits':
        flags.append('--permission-mode acceptEdits')
    elif permission_mode == 'auto':
        # Teammates inherit auto mode so the classifier auto-approves their tool
        # calls too. The teammate's own startup (permissionSetup.ts) handles
        # GrowthBook gate checks and setAutoModeActive(true) independently.
        flags.append('--permission-mode auto')
    
    # Propagate --model if explicitly set via AI agent
    model_override = get_main_loop_model_override()
    if model_override:
        flags.append(f'--model {quote([model_override])}')
    
    # Propagate --settings if set via AI agent
    settings_path = get_flag_settings_path()
    if settings_path:
        flags.append(f'--settings {quote([settings_path])}')
    
    # Propagate --plugin-dir for each inline plugin
    inline_plugins = get_inline_plugins()
    for plugin_dir in inline_plugins:
        flags.append(f'--plugin-dir {quote([plugin_dir])}')
    
    # Propagate --chrome / --no-chrome if explicitly set on the AI agent
    chrome_flag_override = get_chrome_flag_override()
    if chrome_flag_override is True:
        flags.append('--chrome')
    elif chrome_flag_override is False:
        flags.append('--no-chrome')
    
    return ' '.join(flags)


async def _generate_unique_teammate_name(
    base_name: str,
    team_name: Optional[str],
) -> str:
    """
    Generates a unique teammate name by checking existing team members.
    If the name already exists, appends a numeric suffix (e.g., tester-2, tester-3).
    """
    if not team_name:
        return base_name
    
    team_file = await read_team_file_async(team_name)
    if not team_file:
        return base_name
    
    existing_names = {m['name'].lower() for m in team_file.get('members', [])}
    
    # If the base name doesn't exist, use it as-is
    if base_name.lower() not in existing_names:
        return base_name
    
    # Find the next available suffix
    suffix = 2
    while f'{base_name}-{suffix}'.lower() in existing_names:
        suffix += 1
    
    return f'{base_name}-{suffix}'


# ============================================================================
# Spawn Handlers
# ============================================================================

async def _handle_spawn_split_pane(
    input_data: SpawnInput,
    context: ToolUseContext,
) -> Dict[str, Any]:
    """
    Handle spawn operation using split-pane view (default).
    When inside tmux: Creates teammates in a shared window with leader on left, teammates on right.
    When outside tmux: Creates a cortex-swarm session with all teammates in a tiled layout.
    """
    set_app_state = context.setAppState
    get_app_state = context.getAppState
    name = input_data.name
    prompt = input_data.prompt
    agent_type = input_data.agent_type
    cwd = input_data.cwd
    plan_mode_required = input_data.plan_mode_required
    
    # Resolve model: 'inherit' → leader's model; undefined → default Opus
    model = resolve_teammate_model(input_data.model, get_app_state().mainLoopModel)
    
    if not name or not prompt:
        raise ValueError('name and prompt are required for spawn operation')
    
    # Get team name from input or inherit from leader's team context
    app_state = get_app_state()
    team_name = input_data.team_name or (app_state.teamContext.teamName if app_state.teamContext else None)
    
    if not team_name:
        raise ValueError(
            'team_name is required for spawn operation. Either provide team_name in input or call spawnTeam first to establish team context.'
        )
    
    # Generate unique name if duplicate exists in team
    unique_name = await _generate_unique_teammate_name(name, team_name)
    
    # Sanitize the name to prevent @ in agent IDs (would break agentName@teamName format)
    sanitized_name = sanitize_agent_name(unique_name)
    
    # Generate deterministic agent ID from name and team
    teammate_id = format_agent_id(sanitized_name, team_name)
    working_dir = cwd or get_cwd()
    
    # Detect the appropriate backend and check if setup is needed
    detection_result = await detect_and_get_backend()
    
    # If in iTerm2 but it2 isn't set up, prompt the user
    # NOTE: React/JSX setup prompts not available in Python AI agent
    # This would need custom UI implementation
    
    # Check if we're inside tmux to determine session naming
    inside_tmux = await is_inside_tmux()
    
    # Assign a unique color to this teammate
    teammate_color = assign_teammate_color(teammate_id)
    
    # Create a pane in the swarm view
    pane_result = await create_teammate_pane_in_swarm_view(sanitized_name, teammate_color)
    pane_id = pane_result['paneId']
    is_first_teammate = pane_result.get('isFirstTeammate', False)
    
    # Enable pane border status on first teammate when inside tmux
    if is_first_teammate and inside_tmux:
        await enable_pane_border_status()
    
    # Build the command to spawn Cortex Code with teammate identity
    binary_path = _get_teammate_command()
    
    # Build teammate identity AI agent args
    teammate_args = ' '.join(filter(None, [
        f'--agent-id {quote([teammate_id])}',
        f'--agent-name {quote([sanitized_name])}',
        f'--team-name {quote([team_name])}',
        f'--agent-color {quote([teammate_color])}',
        f'--parent-session-id {quote([get_session_id()])}',
        '--plan-mode-required' if plan_mode_required else '',
        f'--agent-type {quote([agent_type])}' if agent_type else '',
    ]))
    
    # Build AI agent flags to propagate to teammate
    inherited_flags = _build_inherited_cli_flags(
        plan_mode_required=plan_mode_required,
        permission_mode=app_state.toolPermissionContext.mode,
    )
    
    # If teammate has a custom model, add --model flag (or replace inherited one)
    if model:
        # Remove any inherited --model flag first
        flag_parts = inherited_flags.split()
        filtered_flags = [
            f for i, f in enumerate(flag_parts)
            if f != '--model' and (i == 0 or flag_parts[i-1] != '--model')
        ]
        inherited_flags = ' '.join(filtered_flags)
        # Add the teammate's model
        inherited_flags = f'{inherited_flags} --model {quote([model])}' if inherited_flags else f'--model {quote([model])}'
    
    flags_str = f' {inherited_flags}' if inherited_flags else ''
    # Propagate env vars
    env_str = build_inherited_env_vars()
    spawn_command = f'cd {quote([working_dir])} && env {env_str} {quote([binary_path])} {teammate_args}{flags_str}'
    
    # Send the command to the new pane
    await send_command_to_pane(pane_id, spawn_command, not inside_tmux)
    
    # Determine session/window names for output
    session_name = 'current' if inside_tmux else SWARM_SESSION_NAME
    window_name = 'current' if inside_tmux else 'swarm-view'
    
    # Track the teammate in AppState's teamContext with color
    # This would need to be implemented based on your state management
    
    # Register background task
    _register_out_of_process_teammate_task(
        set_app_state,
        teammate_id=teammate_id,
        sanitized_name=sanitized_name,
        team_name=team_name,
        teammate_color=teammate_color,
        prompt=prompt,
        plan_mode_required=plan_mode_required,
        pane_id=pane_id,
        inside_tmux=inside_tmux,
        backend_type=detection_result.get('backend', {}).get('type', 'tmux'),
        tool_use_id=getattr(context, 'toolUseId', None),
    )
    
    # Register agent in the team file
    team_file = await read_team_file_async(team_name)
    if not team_file:
        raise RuntimeError(f'Team "{team_name}" does not exist. Call spawnTeam first to create the team.')
    
    team_file.setdefault('members', []).append({
        'agentId': teammate_id,
        'name': sanitized_name,
        'agentType': agent_type,
        'model': model,
        'prompt': prompt,
        'color': teammate_color,
        'planModeRequired': plan_mode_required,
        'joinedAt': int(time.time() * 1000),
        'tmuxPaneId': pane_id,
        'cwd': working_dir,
        'subscriptions': [],
        'backendType': detection_result.get('backend', {}).get('type', 'tmux'),
    })
    await write_team_file_async(team_name, team_file)
    
    # Send initial instructions to teammate via mailbox
    await write_to_mailbox(
        sanitized_name,
        {
            'from': TEAM_LEAD_NAME,
            'text': prompt,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        },
        team_name,
    )
    
    return {
        'data': {
            'teammate_id': teammate_id,
            'agent_id': teammate_id,
            'agent_type': agent_type,
            'model': model,
            'name': sanitized_name,
            'color': teammate_color,
            'tmux_session_name': session_name,
            'tmux_window_name': window_name,
            'tmux_pane_id': pane_id,
            'team_name': team_name,
            'is_splitpane': True,
            'plan_mode_required': plan_mode_required,
        },
    }


async def _handle_spawn_separate_window(
    input_data: SpawnInput,
    context: ToolUseContext,
) -> Dict[str, Any]:
    """
    Handle spawn operation using separate windows (legacy behavior).
    Creates each teammate in its own tmux window.
    """
    set_app_state = context.setAppState
    get_app_state = context.getAppState
    name = input_data.name
    prompt = input_data.prompt
    agent_type = input_data.agent_type
    cwd = input_data.cwd
    plan_mode_required = input_data.plan_mode_required
    
    # Resolve model
    model = resolve_teammate_model(input_data.model, get_app_state().mainLoopModel)
    
    if not name or not prompt:
        raise ValueError('name and prompt are required for spawn operation')
    
    # Get team name
    app_state = get_app_state()
    team_name = input_data.team_name or (app_state.teamContext.teamName if app_state.teamContext else None)
    
    if not team_name:
        raise ValueError('team_name is required for spawn operation')
    
    # Generate unique name
    unique_name = await _generate_unique_teammate_name(name, team_name)
    sanitized_name = sanitize_agent_name(unique_name)
    teammate_id = format_agent_id(sanitized_name, team_name)
    window_name = f'teammate-{sanitize_name(sanitized_name)}'
    working_dir = cwd or get_cwd()
    
    # Ensure the swarm session exists
    await _ensure_session(SWARM_SESSION_NAME)
    
    # Assign color
    teammate_color = assign_teammate_color(teammate_id)
    
    # Create a new window for this teammate
    create_window_result = await exec_file_no_throw(TMUX_COMMAND, [
        'new-window', '-t', SWARM_SESSION_NAME, '-n', window_name, '-P', '-F', '#{pane_id}'
    ])
    
    if create_window_result.code != 0:
        raise RuntimeError(f'Failed to create tmux window: {create_window_result.stderr}')
    
    pane_id = create_window_result.stdout.strip()
    
    # Build spawn command
    binary_path = _get_teammate_command()
    
    teammate_args = ' '.join(filter(None, [
        f'--agent-id {quote([teammate_id])}',
        f'--agent-name {quote([sanitized_name])}',
        f'--team-name {quote([team_name])}',
        f'--agent-color {quote([teammate_color])}',
        f'--parent-session-id {quote([get_session_id()])}',
        '--plan-mode-required' if plan_mode_required else '',
        f'--agent-type {quote([agent_type])}' if agent_type else '',
    ]))
    
    inherited_flags = _build_inherited_cli_flags(
        plan_mode_required=plan_mode_required,
        permission_mode=app_state.toolPermissionContext.mode,
    )
    
    if model:
        flag_parts = inherited_flags.split()
        filtered_flags = [
            f for i, f in enumerate(flag_parts)
            if f != '--model' and (i == 0 or flag_parts[i-1] != '--model')
        ]
        inherited_flags = ' '.join(filtered_flags)
        inherited_flags = f'{inherited_flags} --model {quote([model])}' if inherited_flags else f'--model {quote([model])}'
    
    flags_str = f' {inherited_flags}' if inherited_flags else ''
    env_str = build_inherited_env_vars()
    spawn_command = f'cd {quote([working_dir])} && env {env_str} {quote([binary_path])} {teammate_args}{flags_str}'
    
    # Send the command to the new window
    send_keys_result = await exec_file_no_throw(TMUX_COMMAND, [
        'send-keys', '-t', f'{SWARM_SESSION_NAME}:{window_name}', spawn_command, 'Enter'
    ])
    
    if send_keys_result.code != 0:
        raise RuntimeError(f'Failed to send command to tmux window: {send_keys_result.stderr}')
    
    # Track teammate and register task
    _register_out_of_process_teammate_task(
        set_app_state,
        teammate_id=teammate_id,
        sanitized_name=sanitized_name,
        team_name=team_name,
        teammate_color=teammate_color,
        prompt=prompt,
        plan_mode_required=plan_mode_required,
        pane_id=pane_id,
        inside_tmux=False,
        backend_type='tmux',
        tool_use_id=getattr(context, 'toolUseId', None),
    )
    
    # Register agent in team file
    team_file = await read_team_file_async(team_name)
    if not team_file:
        raise RuntimeError(f'Team "{team_name}" does not exist')
    
    team_file.setdefault('members', []).append({
        'agentId': teammate_id,
        'name': sanitized_name,
        'agentType': agent_type,
        'model': model,
        'prompt': prompt,
        'color': teammate_color,
        'planModeRequired': plan_mode_required,
        'joinedAt': int(time.time() * 1000),
        'tmuxPaneId': pane_id,
        'cwd': working_dir,
        'subscriptions': [],
        'backendType': 'tmux',
    })
    await write_team_file_async(team_name, team_file)
    
    # Send initial instructions via mailbox
    await write_to_mailbox(
        sanitized_name,
        {
            'from': TEAM_LEAD_NAME,
            'text': prompt,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        },
        team_name,
    )
    
    return {
        'data': {
            'teammate_id': teammate_id,
            'agent_id': teammate_id,
            'agent_type': agent_type,
            'model': model,
            'name': sanitized_name,
            'color': teammate_color,
            'tmux_session_name': SWARM_SESSION_NAME,
            'tmux_window_name': window_name,
            'tmux_pane_id': pane_id,
            'team_name': team_name,
            'is_splitpane': False,
            'plan_mode_required': plan_mode_required,
        },
    }


def _register_out_of_process_teammate_task(
    set_app_state,
    **kwargs
) -> None:
    """
    Register a background task entry for an out-of-process (tmux/iTerm2) teammate.
    This makes tmux teammates visible in the background tasks pill and dialog.
    """
    teammate_id = kwargs['teammate_id']
    sanitized_name = kwargs['sanitized_name']
    team_name = kwargs['team_name']
    teammate_color = kwargs['teammate_color']
    prompt = kwargs['prompt']
    plan_mode_required = kwargs.get('plan_mode_required')
    pane_id = kwargs['pane_id']
    inside_tmux = kwargs['inside_tmux']
    backend_type = kwargs['backend_type']
    tool_use_id = kwargs.get('tool_use_id')
    
    task_id = generate_task_id('in_process_teammate')
    description = f"{sanitized_name}: {prompt[:50]}{'...' if len(prompt) > 50 else ''}"
    
    # In Python, you'd use asyncio.Task or threading for abort control
    # For now, this is a stub
    
    task_state = {
        **create_task_state_base(task_id, 'in_process_teammate', description, tool_use_id),
        'type': 'in_process_teammate',
        'status': 'running',
        'identity': {
            'agentId': teammate_id,
            'agentName': sanitized_name,
            'teamName': team_name,
            'color': teammate_color,
            'planModeRequired': plan_mode_required or False,
            'parentSessionId': get_session_id(),
        },
        'prompt': prompt,
        'awaitingPlanApproval': False,
        'permissionMode': 'plan' if plan_mode_required else 'default',
        'isIdle': False,
        'shutdownRequested': False,
    }
    
    register_task(task_state, set_app_state)


async def _handle_spawn_in_process(
    input_data: SpawnInput,
    context: ToolUseContext,
) -> Dict[str, Any]:
    """
    Handle spawn operation for in-process teammates.
    In-process teammates run in the same Python process using async context.
    """
    set_app_state = context.setAppState
    get_app_state = context.getAppState
    name = input_data.name
    prompt = input_data.prompt
    agent_type = input_data.agent_type
    plan_mode_required = input_data.plan_mode_required
    
    # Resolve model
    model = resolve_teammate_model(input_data.model, get_app_state().mainLoopModel)
    
    if not name or not prompt:
        raise ValueError('name and prompt are required for spawn operation')
    
    # Get team name
    app_state = get_app_state()
    team_name = input_data.team_name or (app_state.teamContext.teamName if app_state.teamContext else None)
    
    if not team_name:
        raise ValueError('team_name is required for spawn operation')
    
    # Generate unique name
    unique_name = await _generate_unique_teammate_name(name, team_name)
    sanitized_name = sanitize_agent_name(unique_name)
    teammate_id = format_agent_id(sanitized_name, team_name)
    teammate_color = assign_teammate_color(teammate_id)
    
    # Look up custom agent definition
    agent_definition = None
    if agent_type:
        all_agents = context.options.agentDefinitions.activeAgents
        found_agent = next((a for a in all_agents if a.get('agentType') == agent_type), None)
        if found_agent and is_custom_agent(found_agent):
            agent_definition = found_agent
        log_for_debugging(f'[handleSpawnInProcess] agent_type={agent_type}, found={bool(agent_definition)}')
    
    # Spawn in-process teammate
    config = {
        'name': sanitized_name,
        'teamName': team_name,
        'prompt': prompt,
        'color': teammate_color,
        'planModeRequired': plan_mode_required or False,
        'model': model,
    }
    
    result = await spawn_in_process_teammate(config, context)
    
    if not result.get('success'):
        raise RuntimeError(result.get('error') or 'Failed to spawn in-process teammate')
    
    log_for_debugging(
        f'[handleSpawnInProcess] spawn result: taskId={result.get("taskId")}, hasContext={bool(result.get("teammateContext"))}'
    )
    
    # Start the agent execution loop (fire-and-forget)
    if result.get('taskId') and result.get('teammateContext') and result.get('abortController'):
        await start_in_process_teammate(
            identity={
                'agentId': teammate_id,
                'agentName': sanitized_name,
                'teamName': team_name,
                'color': teammate_color,
                'planModeRequired': plan_mode_required or False,
                'parentSessionId': result['teammateContext'].get('parentSessionId'),
            },
            taskId=result['taskId'],
            prompt=prompt,
            description=input_data.description,
            model=model,
            agentDefinition=agent_definition,
            teammateContext=result['teammateContext'],
            toolUseContext={**context.__dict__, 'messages': []} if hasattr(context, '__dict__') else {'messages': []},
            abortController=result['abortController'],
            invokingRequestId=input_data.invoking_request_id,
        )
        log_for_debugging(f'[handleSpawnInProcess] Started agent execution for {teammate_id}')
    
    # Track teammate in AppState
    # (Simplified - would need actual state management implementation)
    
    # Register agent in team file
    team_file = await read_team_file_async(team_name)
    if not team_file:
        raise RuntimeError(f'Team "{team_name}" does not exist')
    
    team_file.setdefault('members', []).append({
        'agentId': teammate_id,
        'name': sanitized_name,
        'agentType': agent_type,
        'model': model,
        'prompt': prompt,
        'color': teammate_color,
        'planModeRequired': plan_mode_required,
        'joinedAt': int(time.time() * 1000),
        'tmuxPaneId': 'in-process',
        'cwd': get_cwd(),
        'subscriptions': [],
        'backendType': 'in-process',
    })
    await write_team_file_async(team_name, team_file)
    
    return {
        'data': {
            'teammate_id': teammate_id,
            'agent_id': teammate_id,
            'agent_type': agent_type,
            'model': model,
            'name': sanitized_name,
            'color': teammate_color,
            'tmux_session_name': 'in-process',
            'tmux_window_name': 'in-process',
            'tmux_pane_id': 'in-process',
            'team_name': team_name,
            'is_splitpane': False,
            'plan_mode_required': plan_mode_required,
        },
    }


# ============================================================================
# Main Spawn Orchestrator
# ============================================================================

async def _handle_spawn(
    input_data: SpawnInput,
    context: ToolUseContext,
) -> Dict[str, Any]:
    """
    Handle spawn operation - creates a new Cortex Code instance.
    Uses in-process mode when enabled, otherwise uses tmux/iTerm2 split-pane view.
    Falls back to in-process if pane backend detection fails.
    """
    # Check if in-process mode is enabled via feature flag
    if is_in_process_enabled():
        return await _handle_spawn_in_process(input_data, context)
    
    # Pre-flight: ensure a pane backend is available
    try:
        await detect_and_get_backend()
    except Exception as error:
        # Only fall back silently in auto mode
        if get_teammate_mode_from_snapshot() != 'auto':
            raise
        
        log_for_debugging(
            f'[handleSpawn] No pane backend available, falling back to in-process: {error_message(error)}'
        )
        mark_in_process_fallback()
        return await _handle_spawn_in_process(input_data, context)
    
    # Backend is available - proceed with pane spawning
    use_split_pane = input_data.use_splitpane is not False
    if use_split_pane:
        return await _handle_spawn_split_pane(input_data, context)
    return await _handle_spawn_separate_window(input_data, context)


# ============================================================================
# Main Export
# ============================================================================

async def spawn_teammate(
    config: SpawnTeammateConfig,
    context: ToolUseContext,
) -> Dict[str, Any]:
    """
    Spawns a new teammate with the given configuration.
    This is the main entry point for teammate spawning, used by both TeammateTool and AgentTool.
    """
    input_data = SpawnInput(**config.__dict__ if hasattr(config, '__dict__') else config)
    return await _handle_spawn(input_data, context)
