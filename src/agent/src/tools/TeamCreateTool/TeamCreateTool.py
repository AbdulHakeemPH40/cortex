# ------------------------------------------------------------
# TeamCreateTool.py
# Python conversion of TeamCreateTool/TeamCreateTool.ts
# 
# Team creation tool for AI agents.
# Creates multi-agent teams with task lists, team files, and member management.
# ------------------------------------------------------------

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from ...Tool import ToolDef, ToolResult, buildTool
    from ...bootstrap.state import getSessionId
    from ...services.analytics.index import logEvent
    from ...utils.agentId import formatAgentId
    from ...utils.agentSwarmsEnabled import isAgentSwarmsEnabled
    from ...utils.model.model import getDefaultMainLoopModel, parseUserSpecifiedModel
    from ...utils.swarm.backends.registry import getResolvedTeammateMode
    from ...utils.swarm.constants import TEAM_LEAD_NAME
    from ...utils.swarm.teamHelpers import (
        getTeamFilePath,
        readTeamFile,
        registerTeamForSessionCleanup,
        sanitizeName,
        writeTeamFileAsync,
    )
    from ...utils.swarm.teammateLayoutManager import assignTeammateColor
    from ...utils.tasks import ensureTasksDir, resetTaskList, setLeaderTeamName
    from ...utils.words import generateWordSlug
    from .constants import TEAM_CREATE_TOOL_NAME
    from .prompt import getPrompt
except ImportError:
    # Fallback stubs for type checking
    TEAM_CREATE_TOOL_NAME = 'TeamCreate'
    
    def getPrompt():
        return 'Create a new team for coordinating multiple agents'
    
    @dataclass
    class ToolResult:
        data: Any = None
    
    def buildTool(**kwargs):
        return kwargs
    
    def isAgentSwarmsEnabled():
        return False
    
    def getSessionId():
        return 'session-123'
    
    def formatAgentId(name: str, team_name: str) -> str:
        return f'{name}@{team_name}'
    
    def getCwd():
        return '/tmp'
    
    def getDefaultMainLoopModel():
        return 'claude-3-sonnet'
    
    def parseUserSpecifiedModel(model: str):
        return model
    
    def jsonStringify(data: Any) -> str:
        return json.dumps(data)
    
    def getResolvedTeammateMode():
        return 'tmux'
    
    TEAM_LEAD_NAME = 'team-lead'
    
    def getTeamFilePath(team_name: str) -> str:
        return f'~/.claude/teams/{team_name}/config.json'
    
    def readTeamFile(team_name: str):
        return None
    
    def writeTeamFileAsync(team_name: str, team_file: Dict):
        pass
    
    def registerTeamForSessionCleanup(team_name: str):
        pass
    
    def sanitizeName(name: str) -> str:
        return name.lower().replace(' ', '-')
    
    def assignTeammateColor(agent_id: str):
        return 'blue'
    
    async def resetTaskList(task_list_id: str):
        pass
    
    async def ensureTasksDir(task_list_id: str):
        pass
    
    def setLeaderTeamName(team_name: str):
        pass
    
    def generateWordSlug() -> str:
        return 'generated-team'
    
    def logEvent(event_name: str, metadata: Dict):
        pass


# Input schema definition
inputSchema = {
    'type': 'object',
    'properties': {
        'team_name': {
            'type': 'string',
            'description': 'Name for the new team to create.',
        },
        'description': {
            'type': 'string',
            'description': 'Team description/purpose.',
        },
        'agent_type': {
            'type': 'string',
            'description': 'Type/role of the team lead (e.g., "researcher", "test-runner"). Used for team file and inter-agent coordination.',
        },
    },
    'required': ['team_name'],
}

# Output type definition
Output = Dict[str, str]


def generate_unique_team_name(provided_name: str) -> str:
    """
    Generate a unique team name.
    
    If the provided name already exists, generates a new word slug.
    """
    # Check if team exists
    existing = readTeamFile(provided_name)
    if not existing:
        return provided_name
    
    # Team exists, generate a new unique name
    return generateWordSlug()


def to_auto_classifier_input(input_data: Dict[str, Any]) -> str:
    """
    Convert input to auto-classifier format.
    
    Returns team_name for pattern matching.
    """
    return input_data.get('team_name', '')


async def validate_input(input_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate input before creating team.
    
    Checks that team_name is provided and non-empty.
    """
    team_name = input_data.get('team_name', '').strip()
    
    if not team_name:
        return {
            'result': False,
            'message': 'team_name is required for TeamCreate',
            'errorCode': 9,
        }
    
    return {'result': True}


async def call(input_data: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """
    Create a new team for coordinating multiple agents.
    
    Creates:
    - Team file at ~/.claude/teams/{team-name}/config.json
    - Task list directory at ~/.claude/tasks/{team-name}/
    - Team lead with deterministic agent ID
    
    Returns team name, file path, and lead agent ID.
    """
    get_app_state = context.get('getAppState')
    set_app_state = context.get('setAppState')
    
    if not get_app_state or not set_app_state:
        raise ValueError('App state functions not available in context')
    
    team_name = input_data.get('team_name', '').strip()
    description = input_data.get('description')
    agent_type = input_data.get('agent_type')
    
    # Check if already in a team - restrict to one team per leader
    app_state = get_app_state()
    team_context = getattr(app_state, 'teamContext', None) or app_state.get('teamContext', {})
    existing_team = team_context.get('teamName')
    
    if existing_team:
        raise ValueError(
            f'Already leading team "{existing_team}". A leader can only manage one team at a time. '
            'Use TeamDelete to end the current team before creating a new one.'
        )
    
    # If team already exists, generate a unique name instead of failing
    final_team_name = generate_unique_team_name(team_name)
    
    # Generate a deterministic agent ID for the team lead
    lead_agent_id = formatAgentId(TEAM_LEAD_NAME, final_team_name)
    lead_agent_type = agent_type or TEAM_LEAD_NAME
    
    # Get the team lead's current model from AppState
    main_loop_model = (
        getattr(app_state, 'mainLoopModelForSession', None)
        or app_state.get('mainLoopModelForSession')
        or getattr(app_state, 'mainLoopModel', None)
        or app_state.get('mainLoopModel')
        or getDefaultMainLoopModel()
    )
    lead_model = parseUserSpecifiedModel(main_loop_model)
    
    team_file_path = getTeamFilePath(final_team_name)
    
    # Create team file structure
    team_file = {
        'name': final_team_name,
        'description': description,
        'createdAt': int(__import__('time').time() * 1000),
        'leadAgentId': lead_agent_id,
        'leadSessionId': getSessionId(),
        'members': [
            {
                'agentId': lead_agent_id,
                'name': TEAM_LEAD_NAME,
                'agentType': lead_agent_type,
                'model': lead_model,
                'joinedAt': int(__import__('time').time() * 1000),
                'tmuxPaneId': '',
                'cwd': getCwd(),
                'subscriptions': [],
            },
        ],
    }
    
    await writeTeamFileAsync(final_team_name, team_file)
    
    # Track for session-end cleanup
    registerTeamForSessionCleanup(final_team_name)
    
    # Reset and create the corresponding task list directory
    task_list_id = sanitizeName(final_team_name)
    await resetTaskList(task_list_id)
    await ensureTasksDir(task_list_id)
    
    # Register the team name so getTaskListId() returns it for the leader
    setLeaderTeamName(sanitizeName(final_team_name))
    
    # Update AppState with team context
    def update_team_context(prev):
        return {
            **prev,
            'teamContext': {
                'teamName': final_team_name,
                'teamFilePath': team_file_path,
                'leadAgentId': lead_agent_id,
                'teammates': {
                    lead_agent_id: {
                        'name': TEAM_LEAD_NAME,
                        'agentType': lead_agent_type,
                        'color': assignTeammateColor(lead_agent_id),
                        'tmuxSessionName': '',
                        'tmuxPaneId': '',
                        'cwd': getCwd(),
                        'spawnedAt': int(__import__('time').time() * 1000),
                    },
                },
            },
        }
    
    set_app_state(update_team_context)
    
    # Log analytics event
    try:
        logEvent('tengu_team_created', {
            'team_name': final_team_name,
            'teammate_count': 1,
            'lead_agent_type': lead_agent_type,
            'teammate_mode': getResolvedTeammateMode(),
        })
    except Exception:
        # Analytics failure should not break team creation
        pass
    
    return ToolResult(data={
        'team_name': final_team_name,
        'team_file_path': team_file_path,
        'lead_agent_id': lead_agent_id,
    })


def map_tool_result_to_block_param(data: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """
    Map tool result to block parameter format.
    
    Serializes team creation result as JSON.
    """
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': [
            {
                'type': 'text',
                'text': jsonStringify(data),
            },
        ],
    }


def render_tool_use_message() -> Optional[str]:
    """Render message when tool is used."""
    return None


# Tool definition
TeamCreateTool = buildTool(
    name=TEAM_CREATE_TOOL_NAME,
    searchHint='create a multi-agent swarm team',
    maxResultSizeChars=100_000,
    shouldDefer=True,
    userFacingName=lambda: '',
    inputSchema=lambda: inputSchema,
    isEnabled=lambda: isAgentSwarmsEnabled(),
    toAutoClassifierInput=to_auto_classifier_input,
    validateInput=validate_input,
    description=lambda: 'Create a new team for coordinating multiple agents',
    prompt=lambda: getPrompt(),
    mapToolResultToBlockParam=map_tool_result_to_block_param,
    renderToolUseMessage=render_tool_use_message,
    call=call,
)
