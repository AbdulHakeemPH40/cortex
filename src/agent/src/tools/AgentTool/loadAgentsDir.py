# loadAgentsDir.py
"""
Load and parse agent definitions for Cortex IDE.

Provides functions to load agents from:
- Built-in definitions
- Plugin agents
- User/project/policy settings (JSON/Markdown)
- Managed/flag settings

Handles memoization, MCP server requirements, and agent memory initialization.
"""

from __future__ import annotations

import os
from typing import List, Dict, Any, Optional, Union, TypedDict, Set, Literal
from dataclasses import dataclass
from pathlib import Path
import functools

from ...memdir.paths import is_auto_memory_enabled
from ...utils.log import log_error
from ...utils.permissions.PermissionMode import PERMISSION_MODES, PermissionMode
from ..FileEditTool.constants import FILE_EDIT_TOOL_NAME
from ..FileWriteTool.prompt import FILE_WRITE_TOOL_NAME
from .agentColorManager import AGENT_COLORS, AgentColorName, set_agent_color
from .agentMemory import AgentMemoryScope, load_agent_memory_prompt
from .agentMemorySnapshot import check_agent_memory_snapshot, initialize_from_snapshot
from .builtInAgents import get_built_in_agents


# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

# MCP server specification in agent definitions
AgentMcpServerSpec = Union[
    str,  # Reference to existing server by name (e.g., "slack")
    Dict[str, McpServerConfig]  # Inline definition as {name: config}
]


# Base type with common fields for all agents
@dataclass
class BaseAgentDefinition:
    """Base agent definition with common fields."""
    agentType: str
    whenToUse: str
    tools: Optional[List[str]] = None
    disallowedTools: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    mcpServers: Optional[List[AgentMcpServerSpec]] = None
    hooks: Optional[HooksSettings] = None
    color: Optional[AgentColorName] = None
    model: Optional[str] = None
    effort: Optional[EffortValue] = None
    permissionMode: Optional[PermissionMode] = None
    maxTurns: Optional[int] = None
    filename: Optional[str] = None
    baseDir: Optional[str] = None
    criticalSystemReminder_EXPERIMENTAL: Optional[str] = None
    requiredMcpServers: Optional[List[str]] = None
    background: Optional[bool] = None
    initialPrompt: Optional[str] = None
    memory: Optional[AgentMemoryScope] = None
    isolation: Optional[Literal['worktree', 'remote']] = None
    pendingSnapshotUpdate: Optional[Dict[str, str]] = None
    omitCortexMd: Optional[bool] = None


# Built-in agents - dynamic prompts only
@dataclass
class BuiltInAgentDefinition(BaseAgentDefinition):
    """Built-in agent definition."""
    source: Literal['built-in'] = 'built-in'
    baseDir: Literal['built-in'] = 'built-in'
    callback: Optional[callable] = None
    getSystemPrompt: Optional[callable] = None


# Custom agents from user/project/policy settings
@dataclass
class CustomAgentDefinition(BaseAgentDefinition):
    """Custom agent definition from settings."""
    getSystemPrompt: Optional[callable] = None
    source: Optional[str] = None
    filename: Optional[str] = None
    baseDir: Optional[str] = None


# Plugin agents
@dataclass
class PluginAgentDefinition(BaseAgentDefinition):
    """Plugin agent definition."""
    getSystemPrompt: Optional[callable] = None
    source: Literal['plugin'] = 'plugin'
    filename: Optional[str] = None
    plugin: Optional[str] = None


# Union type for all agent types
AgentDefinition = Union[
    BuiltInAgentDefinition,
    CustomAgentDefinition,
    PluginAgentDefinition,
]


@dataclass
class AgentDefinitionsResult:
    """Result of loading agent definitions."""
    activeAgents: List[AgentDefinition]
    allAgents: List[AgentDefinition]
    failedFiles: Optional[List[Dict[str, str]]] = None
    allowedAgentTypes: Optional[List[str]] = None


# ============================================================================
# MCP SERVER REQUIREMENTS
# ============================================================================

def has_required_mcp_servers(
    agent: AgentDefinition,
    available_servers: List[str],
) -> bool:
    """
    Check if agent's required MCP servers are available.
    
    Args:
        agent: Agent definition to check
        available_servers: List of available MCP server names
    
    Returns:
        True if no requirements or all requirements met
    """
    required = getattr(agent, 'requiredMcpServers', None)
    if not required:
        return True
    
    # Each required pattern must match at least one available server
    for pattern in required:
        if not any(
            pattern.lower() in server.lower()
            for server in available_servers
        ):
            return False
    
    return True


def filter_agents_by_mcp_requirements(
    agents: List[AgentDefinition],
    available_servers: List[str],
) -> List[AgentDefinition]:
    """
    Filter agents based on MCP server requirements.
    
    Args:
        agents: List of agents to filter
        available_servers: Available MCP server names
    
    Returns:
        Filtered list of agents
    """
    return [
        agent for agent in agents
        if has_required_mcp_servers(agent, available_servers)
    ]


# ============================================================================
# AGENT MEMORY INITIALIZATION
# ============================================================================

async def initialize_agent_memory_snapshots(
    agents: List[CustomAgentDefinition],
) -> None:
    """
    Initialize agent memory from project snapshots.
    
    For agents with memory enabled, copies snapshot to local if no local memory exists.
    For agents with newer snapshots, logs debug message.
    """
    import asyncio
    
    async def process_agent(agent: CustomAgentDefinition):
        if agent.memory != 'user':
            return
        
        result = await check_agent_memory_snapshot(agent.agentType, agent.memory)
        
        if result.get('action') == 'initialize':
            log_for_debugging(
                f"Initializing {agent.agentType} memory from project snapshot"
            )
            await initialize_from_snapshot(
                agent.agentType,
                agent.memory,
                result.get('snapshot_timestamp'),
            )
        elif result.get('action') == 'prompt-update':
            agent.pendingSnapshotUpdate = {
                'snapshotTimestamp': result.get('snapshot_timestamp'),
            }
            log_for_debugging(
                f"Newer snapshot available for {agent.agentType} memory "
                f"(snapshot: {result.get('snapshot_timestamp')})"
            )
    
    await asyncio.gather(*[process_agent(agent) for agent in agents])


# ============================================================================
# AGENT LOADING AND PARSING
# ============================================================================

@functools.lru_cache(maxsize=None)
def get_active_agents_from_list(
    all_agents_tuple: tuple,
) -> List[AgentDefinition]:
    """
    Get active agents from list using priority-based deduplication.
    
    Priority order: built-in → plugin → user → project → flag → managed
    """
    all_agents = list(all_agents_tuple)
    
    # Group by source
    source_groups = {
        'built-in': [],
        'plugin': [],
        'userSettings': [],
        'projectSettings': [],
        'managedAgents': [],
        'flagSettings': [],
    }
    
    for agent in all_agents:
        source = getattr(agent, 'source', 'unknown')
        if source in source_groups:
            source_groups[source].append(agent)
    
    # Build map with priority ordering
    agent_map = {}
    for source in ['built-in', 'plugin', 'userSettings', 'projectSettings', 'flagSettings', 'managedAgents']:
        for agent in source_groups.get(source, []):
            agent_map[agent.agentType] = agent
    
    return list(agent_map.values())


async def get_agent_definitions_with_overrides(cwd: str) -> AgentDefinitionsResult:
    """
    Load agent definitions with overrides.
    
    Memoized function that loads:
    - Built-in agents
    - Plugin agents
    - Custom agents from markdown files
    - Initializes agent memory snapshots
    
    Args:
        cwd: Current working directory
    
    Returns:
        AgentDefinitionsResult with active/all agents and any errors
    """
    # Simple mode: skip custom agents, only return built-ins
    if is_env_truthy(os.environ.get('CORTEX_CODE_SIMPLE')):
        built_ins = get_built_in_agents()
        return AgentDefinitionsResult(
            activeAgents=built_ins,
            allAgents=built_ins,
        )
    
    try:
        # Load markdown files
        markdown_files = await load_markdown_files_for_subdir('agents', cwd)
        
        failed_files = []
        custom_agents = []
        
        for file_data in markdown_files:
            agent = parse_agent_from_markdown(
                file_data['filePath'],
                file_data['baseDir'],
                file_data['frontmatter'],
                file_data['content'],
                file_data['source'],
            )
            
            if agent is None:
                # Skip non-agent markdown files silently
                if not file_data['frontmatter'].get('name'):
                    continue
                
                error_msg = get_parse_error(file_data['frontmatter'])
                failed_files.append({
                    'path': file_data['filePath'],
                    'error': error_msg,
                })
                log_for_debugging(
                    f"Failed to parse agent from {file_data['filePath']}: {error_msg}"
                )
                log_event('tengu_agent_parse_error', {
                    'error': error_msg,
                    'location': file_data['source'],
                })
                continue
            
            custom_agents.append(agent)
        
        # Load plugin agents and initialize memory snapshots concurrently
        plugin_agents_future = load_plugin_agents()
        
        if is_auto_memory_enabled():
            plugin_agents, _ = await asyncio.gather(
                plugin_agents_future,
                initialize_agent_memory_snapshots(custom_agents),
            )
        else:
            plugin_agents = await plugin_agents_future
        
        built_ins = get_built_in_agents()
        
        all_agents_list = [*built_ins, *plugin_agents, *custom_agents]
        active_agents = get_active_agents_from_list(tuple(all_agents_list))
        
        # Initialize colors
        for agent in active_agents:
            if agent.color:
                set_agent_color(agent.agentType, agent.color)
        
        return AgentDefinitionsResult(
            activeAgents=active_agents,
            allAgents=all_agents_list,
            failedFiles=failed_files if failed_files else None,
        )
    
    except Exception as e:
        error_message = str(e) if isinstance(e, Exception) else repr(e)
        log_for_debugging(f"Error loading agent definitions: {error_message}")
        log_error(e)
        
        # Return built-in agents even on error
        built_ins = get_built_in_agents()
        return AgentDefinitionsResult(
            activeAgents=built_ins,
            allAgents=built_ins,
            failedFiles=[{'path': 'unknown', 'error': error_message}],
        )


def clear_agent_definitions_cache() -> None:
    """Clear cached agent definitions."""
    get_agent_definitions_with_overrides.cache_clear()
    clear_plugin_agent_cache()


# ============================================================================
# PARSING HELPERS
# ============================================================================

def get_parse_error(frontmatter: Dict[str, Any]) -> str:
    """Determine specific parsing error for agent file."""
    agent_type = frontmatter.get('name')
    description = frontmatter.get('description')
    
    if not agent_type or not isinstance(agent_type, str):
        return 'Missing required "name" field in frontmatter'
    
    if not description or not isinstance(description, str):
        return 'Missing required "description" field in frontmatter'
    
    return 'Unknown parsing error'


def parse_hooks_from_frontmatter(
    frontmatter: Dict[str, Any],
    agent_type: str,
) -> Optional[HooksSettings]:
    """Parse hooks from frontmatter using HooksSchema."""
    if 'hooks' not in frontmatter:
        return None
    
    result = HooksSchema().safe_parse(frontmatter['hooks'])
    if not result.success:
        log_for_debugging(
            f"Invalid hooks in agent '{agent_type}': {result.error_message}"
        )
        return None
    
    return result.data


def parse_agent_from_json(
    name: str,
    definition: Dict[str, Any],
    source: str = 'flagSettings',
) -> Optional[CustomAgentDefinition]:
    """Parse agent definition from JSON data."""
    try:
        # Validate against schema (would need pydantic/zod equivalent)
        tools = parse_agent_tools_from_frontmatter(definition.get('tools'))
        
        # Inject file tools if memory enabled
        if is_auto_memory_enabled() and definition.get('memory') and tools:
            tool_set = set(tools)
            for tool in [FILE_WRITE_TOOL_NAME, FILE_EDIT_TOOL_NAME, FILE_READ_TOOL_NAME]:
                if tool not in tool_set:
                    tools = [*tools, tool]
        
        disallowed_tools = (
            parse_agent_tools_from_frontmatter(definition.get('disallowedTools'))
            if definition.get('disallowedTools') is not None
            else None
        )
        
        system_prompt = definition.get('prompt', '')
        
        def get_system_prompt():
            if is_auto_memory_enabled() and definition.get('memory'):
                return system_prompt + '\n\n' + load_agent_memory_prompt(name, definition['memory'])
            return system_prompt
        
        return CustomAgentDefinition(
            agentType=name,
            whenToUse=definition.get('description', ''),
            tools=tools,
            disallowedTools=disallowed_tools,
            getSystemPrompt=get_system_prompt,
            source=source,
            model=definition.get('model'),
            effort=definition.get('effort'),
            permissionMode=definition.get('permissionMode'),
            mcpServers=definition.get('mcpServers'),
            hooks=definition.get('hooks'),
            maxTurns=definition.get('maxTurns'),
            skills=definition.get('skills'),
            initialPrompt=definition.get('initialPrompt'),
            background=definition.get('background'),
            memory=definition.get('memory'),
            isolation=definition.get('isolation'),
        )
    
    except Exception as e:
        error_message = str(e) if isinstance(e, Exception) else repr(e)
        log_for_debugging(f"Error parsing agent '{name}' from JSON: {error_message}")
        log_error(e)
        return None


def parse_agents_from_json(
    agents_json: Dict[str, Any],
    source: str = 'flagSettings',
) -> List[CustomAgentDefinition]:
    """Parse multiple agents from JSON object."""
    try:
        agents = []
        for name, definition in agents_json.items():
            agent = parse_agent_from_json(name, definition, source)
            if agent:
                agents.append(agent)
        return agents
    except Exception as e:
        error_message = str(e) if isinstance(e, Exception) else repr(e)
        log_for_debugging(f"Error parsing agents from JSON: {error_message}")
        log_error(e)
        return []


def parse_agent_from_markdown(
    file_path: str,
    base_dir: str,
    frontmatter: Dict[str, Any],
    content: str,
    source: str,
) -> Optional[CustomAgentDefinition]:
    """Parse agent definition from markdown file data."""
    try:
        agent_type = frontmatter.get('name')
        when_to_use = frontmatter.get('description')
        
        # Validate required fields
        if not agent_type or not isinstance(agent_type, str):
            return None
        
        if not when_to_use or not isinstance(when_to_use, str):
            log_for_debugging(
                f"Agent file {file_path} is missing required 'description' in frontmatter"
            )
            return None
        
        # Unescape newlines
        when_to_use = when_to_use.replace('\\n', '\n')
        
        # Parse optional fields
        color = frontmatter.get('color')
        model_raw = frontmatter.get('model')
        model = None
        if isinstance(model_raw, str) and model_raw.strip():
            trimmed = model_raw.strip()
            model = 'inherit' if trimmed.lower() == 'inherit' else trimmed
        
        # Parse background
        background_raw = frontmatter.get('background')
        background = None
        if background_raw in ('true', True):
            background = True
        elif background_raw not in (None, 'false', False):
            log_for_debugging(
                f"Agent file {file_path} has invalid background value '{background_raw}'"
            )
        
        # Parse memory scope
        memory_raw = frontmatter.get('memory')
        memory = None
        valid_memory_scopes = ['user', 'project', 'local']
        if memory_raw in valid_memory_scopes:
            memory = memory_raw
        elif memory_raw:
            log_for_debugging(
                f"Agent file {file_path} has invalid memory value '{memory_raw}'"
            )
        
        # Parse isolation mode
        isolation_raw = frontmatter.get('isolation')
        isolation = None
        user_type = os.environ.get('USER_TYPE')
        valid_isolation_modes = ['worktree', 'remote'] if user_type == 'ant' else ['worktree']
        if isolation_raw in valid_isolation_modes:
            isolation = isolation_raw
        elif isolation_raw:
            log_for_debugging(
                f"Agent file {file_path} has invalid isolation value '{isolation_raw}'"
            )
        
        # Parse effort
        effort_raw = frontmatter.get('effort')
        parsed_effort = parse_effort_value(effort_raw) if effort_raw else None
        
        if effort_raw and parsed_effort is None:
            log_for_debugging(
                f"Agent file {file_path} has invalid effort '{effort_raw}'"
            )
        
        # Parse permissionMode
        permission_mode_raw = frontmatter.get('permissionMode')
        permission_mode = None
        if permission_mode_raw and permission_mode_raw in PERMISSION_MODES:
            permission_mode = permission_mode_raw
        elif permission_mode_raw:
            log_for_debugging(
                f"Agent file {file_path} has invalid permissionMode '{permission_mode_raw}'"
            )
        
        # Parse maxTurns
        max_turns_raw = frontmatter.get('maxTurns')
        max_turns = parse_positive_int_from_frontmatter(max_turns_raw)
        
        if max_turns_raw and max_turns is None:
            log_for_debugging(
                f"Agent file {file_path} has invalid maxTurns '{max_turns_raw}'"
            )
        
        # Extract filename
        filename = Path(file_path).stem
        
        # Parse tools
        tools = parse_agent_tools_from_frontmatter(frontmatter.get('tools'))
        
        # Inject file tools if memory enabled
        if is_auto_memory_enabled() and memory and tools:
            tool_set = set(tools)
            for tool in [FILE_WRITE_TOOL_NAME, FILE_EDIT_TOOL_NAME, FILE_READ_TOOL_NAME]:
                if tool not in tool_set:
                    tools = [*tools, tool]
        
        # Parse disallowedTools
        disallowed_tools_raw = frontmatter.get('disallowedTools')
        disallowed_tools = (
            parse_agent_tools_from_frontmatter(disallowed_tools_raw)
            if disallowed_tools_raw is not None
            else None
        )
        
        # Parse skills
        skills = parse_slash_command_tools_from_frontmatter(frontmatter.get('skills'))
        
        # Parse initialPrompt
        initial_prompt_raw = frontmatter.get('initialPrompt')
        initial_prompt = (
            initial_prompt_raw.strip()
            if isinstance(initial_prompt_raw, str) and initial_prompt_raw.strip()
            else None
        )
        
        # Parse mcpServers
        mcp_servers_raw = frontmatter.get('mcpServers')
        mcp_servers = None
        if isinstance(mcp_servers_raw, list):
            mcp_servers = [
                item for item in mcp_servers_raw
                if isinstance(item, (str, dict))
            ]
        
        # Parse hooks
        hooks = parse_hooks_from_frontmatter(frontmatter, agent_type)
        
        # Build system prompt
        system_prompt = content.strip()
        
        def get_system_prompt():
            if is_auto_memory_enabled() and memory:
                return system_prompt + '\n\n' + load_agent_memory_prompt(agent_type, memory)
            return system_prompt
        
        # Build agent definition
        return CustomAgentDefinition(
            baseDir=base_dir,
            agentType=agent_type,
            whenToUse=when_to_use,
            tools=tools,
            disallowedTools=disallowed_tools,
            skills=skills,
            initialPrompt=initial_prompt,
            mcpServers=mcp_servers,
            hooks=hooks,
            getSystemPrompt=get_system_prompt,
            source=source,
            filename=filename,
            color=color if color and color in AGENT_COLORS else None,
            model=model,
            effort=parsed_effort,
            permissionMode=permission_mode,
            maxTurns=max_turns,
            background=background,
            memory=memory,
            isolation=isolation,
        )
    
    except Exception as e:
        error_message = str(e) if isinstance(e, Exception) else repr(e)
        log_for_debugging(f"Error parsing agent from {file_path}: {error_message}")
        log_error(e)
        return None
