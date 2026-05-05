# ------------------------------------------------------------
# TeamDeleteTool.py
# Python conversion of TeamDeleteTool/TeamDeleteTool.ts
# 
# Team deletion tool for AI agents.
# Safely removes team and task directories with active member checks.
# ------------------------------------------------------------

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from ...Tool import ToolDef, ToolResult, buildTool
    from ...services.analytics.index import logEvent
    from ...utils.agentSwarmsEnabled import isAgentSwarmsEnabled
    from ...utils.slowOperations import jsonStringify
    from ...utils.swarm.constants import TEAM_LEAD_NAME
    from ...utils.swarm.teamHelpers import (
        cleanupTeamDirectories,
        readTeamFile,
        unregisterTeamForSessionCleanup,
    )
    from ...utils.swarm.teammateLayoutManager import clearTeammateColors
    from ...utils.tasks import clearLeaderTeamName
    from .constants import TEAM_DELETE_TOOL_NAME
    from .prompt import getPrompt
except ImportError:
    # Fallback stubs for type checking
    TEAM_DELETE_TOOL_NAME = 'TeamDelete'
    TEAM_LEAD_NAME = 'team-lead'
    
    def getPrompt():
        return 'Clean up team and task directories when the swarm is complete'
    
    @dataclass
    class ToolResult:
        data: Any = None
    
    def buildTool(**kwargs):
        return kwargs
    
    def isAgentSwarmsEnabled():
        return False
    
    def readTeamFile(team_name: str):
        return None
    
    async def cleanupTeamDirectories(team_name: str):
        pass
    
    def unregisterTeamForSessionCleanup(team_name: str):
        pass
    
    def clearTeammateColors():
        pass
    
    def clearLeaderTeamName():
        pass
    
    def logEvent(event_name: str, metadata: Dict):
        pass
    
    def jsonStringify(data: Any) -> str:
        return json.dumps(data)


# Input schema definition (empty - no parameters needed)
inputSchema = {
    'type': 'object',
    'properties': {},
}

# Output type definition
Output = Dict[str, Any]


async def call(input_data: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
    """
    Delete a team and clean up resources.
    
    Checks for active members before deletion to prevent accidental cleanup.
    Removes team directory, task directory, and clears session state.
    
    Returns success status and cleanup message.
    """
    get_app_state = context.get('getAppState')
    set_app_state = context.get('setAppState')
    
    if not get_app_state or not set_app_state:
        raise ValueError('App state functions not available in context')
    
    app_state = get_app_state()
    team_context = getattr(app_state, 'teamContext', None) or app_state.get('teamContext', {})
    team_name = team_context.get('teamName')
    
    if team_name:
        # Read team config to check for active members
        team_file = readTeamFile(team_name)
        
        if team_file:
            members = getattr(team_file, 'members', None) or team_file.get('members', [])
            
            # Filter out the team lead - only count non-lead members
            non_lead_members = [
                m for m in members
                if (getattr(m, 'name', None) or m.get('name')) != TEAM_LEAD_NAME
            ]
            
            # Separate truly active members from idle/dead ones
            # Members with isActive === false are idle (finished their turn or crashed)
            active_members = [
                m for m in non_lead_members
                if (getattr(m, 'isActive', None) or m.get('isActive')) is not False
            ]
            
            if active_members:
                member_names = ', '.join(
                    getattr(m, 'name', m.get('name', 'unknown'))
                    for m in active_members
                )
                return ToolResult(data={
                    'success': False,
                    'message': f'Cannot cleanup team with {len(active_members)} active member(s): {member_names}. Use requestShutdown to gracefully terminate teammates first.',
                    'team_name': team_name,
                })
        
        # Clean up team directories
        await cleanupTeamDirectories(team_name)
        
        # Already cleaned — don't try again on gracefulShutdown
        unregisterTeamForSessionCleanup(team_name)
        
        # Clear color assignments so new teams start fresh
        clearTeammateColors()
        
        # Clear leader team name so getTaskListId() falls back to session ID
        clearLeaderTeamName()
        
        # Log analytics event
        try:
            logEvent('tengu_team_deleted', {
                'team_name': team_name,
            })
        except Exception:
            # Analytics failure should not break team deletion
            pass
    
    # Clear team context and inbox from app state
    def clear_team_state(prev):
        return {
            **prev,
            'teamContext': None,
            'inbox': {
                'messages': [],  # Clear any queued messages
            },
        }
    
    set_app_state(clear_team_state)
    
    return ToolResult(data={
        'success': True,
        'message': (
            f'Cleaned up directories and worktrees for team "{team_name}"'
            if team_name
            else 'No team name found, nothing to clean up'
        ),
        'team_name': team_name,
    })


def map_tool_result_to_block_param(data: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """
    Map tool result to block parameter format.
    
    Serializes deletion result as JSON.
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


def render_tool_result_message(result: Dict[str, Any]) -> Optional[str]:
    """Render message for tool result."""
    return None


# Tool definition
TeamDeleteTool = buildTool(
    name=TEAM_DELETE_TOOL_NAME,
    searchHint='disband a swarm team and clean up',
    maxResultSizeChars=100_000,
    shouldDefer=True,
    userFacingName=lambda: '',
    inputSchema=lambda: inputSchema,
    isEnabled=lambda: isAgentSwarmsEnabled(),
    description=lambda: 'Clean up team and task directories when the swarm is complete',
    prompt=lambda: getPrompt(),
    mapToolResultToBlockParam=map_tool_result_to_block_param,
    renderToolUseMessage=render_tool_use_message,
    renderToolResultMessage=render_tool_result_message,
    call=call,
)
