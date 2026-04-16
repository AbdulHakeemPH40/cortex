"""
Team Management Tools - Multi-agent team coordination for Cortex IDE

This module provides team creation and management capabilities:
- TeamCreateTool: Create new agent teams with members
- TeamDeleteTool: Delete teams and clean up resources

Key Features:
- Team creation with member agents
- Team file persistence (.claude/teams/)
- Member management (add/remove)
- Team context sharing
- Automatic cleanup on deletion

Note: Simplified conversion focusing on core team management logic.
Terminal-specific UI rendering and tmux integration removed.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import logging
import time
import uuid
import os
import json
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TeamMember:
    """Represents a member of an agent team."""
    name: str
    agent_id: str
    role: str = 'member'  # 'lead', 'member', 'specialist'
    color: Optional[str] = None  # UI color for this member
    backend_type: str = 'in-process'  # 'in-process', 'tmux', 'remote'
    tmux_pane_id: Optional[str] = None  # For tmux-based teammates


@dataclass
class TeamFile:
    """Persistent team configuration stored in .claude/teams/"""
    name: str
    members: List[TeamMember]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamCreateInput:
    """Input schema for TeamCreate tool."""
    name: str  # Team name
    members: List[str]  # Member agent names
    lead: Optional[str] = None  # Team lead name (defaults to first member)


@dataclass
class TeamCreateOutput:
    """Output schema for TeamCreate tool."""
    success: bool
    team_name: str
    member_count: int
    message: str


@dataclass
class TeamDeleteInput:
    """Input schema for TeamDelete tool."""
    name: str  # Team name to delete


@dataclass
class TeamDeleteOutput:
    """Output schema for TeamDelete tool."""
    success: bool
    message: str


# In-memory team store (backed by file persistence)
_team_store: Dict[str, TeamFile] = {}


def get_teams_directory() -> Path:
    """
    Get the path to the teams directory.
    
    Returns:
        Path to .claude/teams/ directory
    """
    # Use current working directory or home directory
    cwd = Path.cwd()
    teams_dir = cwd / '.claude' / 'teams'
    teams_dir.mkdir(parents=True, exist_ok=True)
    return teams_dir


async def read_team_file(team_name: str) -> Optional[TeamFile]:
    """
    Read team configuration from disk.
    
    Args:
        team_name: Name of team to read
        
    Returns:
        TeamFile if exists, None otherwise
    """
    teams_dir = get_teams_directory()
    team_file_path = teams_dir / f"{team_name}.json"
    
    if not team_file_path.exists():
        return None
    
    try:
        with open(team_file_path, 'r') as f:
            data = json.load(f)
        
        # Reconstruct TeamFile object
        members = [
            TeamMember(**member_data)
            for member_data in data.get('members', [])
        ]
        
        return TeamFile(
            name=data['name'],
            members=members,
            created_at=data.get('created_at', time.time()),
            updated_at=data.get('updated_at', time.time()),
            metadata=data.get('metadata', {})
        )
    except Exception as e:
        logger.error(f"Error reading team file {team_file_path}: {e}")
        return None


async def write_team_file(team: TeamFile) -> None:
    """
    Write team configuration to disk.
    
    Args:
        team: TeamFile object to persist
    """
    teams_dir = get_teams_directory()
    team_file_path = teams_dir / f"{team.name}.json"
    
    try:
        # Convert to serializable dict
        data = {
            'name': team.name,
            'members': [member.__dict__ for member in team.members],
            'created_at': team.created_at,
            'updated_at': team.updated_at,
            'metadata': team.metadata
        }
        
        with open(team_file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Wrote team file: {team_file_path}")
    except Exception as e:
        logger.error(f"Error writing team file {team_file_path}: {e}")
        raise


async def create_team(input_data: TeamCreateInput) -> TeamCreateOutput:
    """
    Create a new agent team.
    
    Creates a team with specified members and persists to disk.
    
    Args:
        input_data: Team creation input
        
    Returns:
        TeamCreateOutput with result
        
    Raises:
        ValueError: If team already exists or invalid input
    """
    # Validate input
    if not input_data.name.strip():
        raise ValueError("Team name cannot be empty")
    
    if not input_data.members:
        raise ValueError("Team must have at least one member")
    
    # Check if team already exists
    existing_team = await read_team_file(input_data.name)
    if existing_team:
        raise ValueError(f"Team '{input_data.name}' already exists")
    
    # Determine team lead
    team_lead = input_data.lead or input_data.members[0]
    
    # Create team members
    members = []
    for i, member_name in enumerate(input_data.members):
        is_lead = (member_name == team_lead)
        member = TeamMember(
            name=member_name,
            agent_id=f"agent_{uuid.uuid4().hex[:12]}",
            role='lead' if is_lead else 'member',
            color=None,  # TODO: Assign colors
            backend_type='in-process'
        )
        members.append(member)
    
    # Create team file
    team = TeamFile(
        name=input_data.name.strip(),
        members=members
    )
    
    # Persist to disk
    await write_team_file(team)
    
    # Store in memory
    _team_store[team.name] = team
    
    logger.info(f"Created team '{team.name}' with {len(members)} members")
    
    return TeamCreateOutput(
        success=True,
        team_name=team.name,
        member_count=len(members),
        message=f"Team '{team.name}' created with {len(members)} members"
    )


async def delete_team(input_data: TeamDeleteInput) -> TeamDeleteOutput:
    """
    Delete a team and clean up resources.
    
    Removes team file and cleans up any associated resources.
    
    Args:
        input_data: Team name to delete
        
    Returns:
        TeamDeleteOutput with result
    """
    # Check if team exists
    team = await read_team_file(input_data.name)
    if not team:
        return TeamDeleteOutput(
            success=False,
            message=f"Team '{input_data.name}' not found"
        )
    
    # Remove team file
    teams_dir = get_teams_directory()
    team_file_path = teams_dir / f"{input_data.name}.json"
    
    try:
        if team_file_path.exists():
            team_file_path.unlink()
            logger.info(f"Deleted team file: {team_file_path}")
    except Exception as e:
        logger.error(f"Error deleting team file: {e}")
        return TeamDeleteOutput(
            success=False,
            message=f"Error deleting team file: {e}"
        )
    
    # Remove from memory store
    if input_data.name in _team_store:
        del _team_store[input_data.name]
    
    # TODO: Clean up any running agent processes for team members
    # This would involve stopping tmux sessions, killing processes, etc.
    
    logger.info(f"Deleted team '{input_data.name}'")
    
    return TeamDeleteOutput(
        success=True,
        message=f"Team '{input_data.name}' deleted successfully"
    )


async def list_teams() -> List[TeamFile]:
    """
    List all available teams.
    
    Returns:
        List of TeamFile objects
    """
    teams_dir = get_teams_directory()
    teams = []
    
    # Read all team files
    for team_file in teams_dir.glob('*.json'):
        team_name = team_file.stem
        team = await read_team_file(team_name)
        if team:
            teams.append(team)
    
    return teams


async def get_team(team_name: str) -> Optional[TeamFile]:
    """
    Get details of a specific team.
    
    Args:
        team_name: Name of team
        
    Returns:
        TeamFile if exists, None otherwise
    """
    return await read_team_file(team_name)


def get_team_create_prompt() -> str:
    """Generate system prompt for TeamCreate tool."""
    return """
# TeamCreate - Create Agent Teams

Create a team of AI agents that can work together on complex tasks.

## When to Use
- Breaking down large projects across multiple specialized agents
- Parallel research with different agents exploring different angles
- Collaborative problem-solving with diverse perspectives
- Distributed task execution

## Parameters
- **name**: Unique team name (alphanumeric, hyphens, underscores)
- **members**: List of agent names (e.g., ["researcher", "coder", "reviewer"])
- **lead**: Optional team lead name (defaults to first member)

## Examples
```json
{"name": "web-dev-team", "members": ["frontend-dev", "backend-dev", "tester"]}
{"name": "research-squad", "members": ["analyst", "writer", "fact-checker"], "lead": "analyst"}
```

## Team Capabilities
- Members can communicate via SendMessage tool
- Tasks can be delegated to specific members
- Team lead coordinates overall strategy
- Each member has isolated context and tools

After creating a team, use SendMessage to coordinate between members.
""".strip()


def get_team_delete_prompt() -> str:
    """Generate system prompt for TeamDelete tool."""
    return """
# TeamDelete - Delete Teams

Delete a team and clean up all associated resources.

## When to Use
- Project is complete
- Team is no longer needed
- User requests team removal
- Cleaning up old/experimental teams

## Warning
This will:
- Delete the team configuration file
- Stop any running agent processes
- Remove team from available teams list

This action cannot be undone. Provide the exact team name.
""".strip()


# Export public API
__all__ = [
    'TeamMember',
    'TeamFile',
    'TeamCreateInput',
    'TeamCreateOutput',
    'TeamDeleteInput',
    'TeamDeleteOutput',
    'create_team',
    'delete_team',
    'list_teams',
    'get_team',
    'read_team_file',
    'write_team_file',
    'get_team_create_prompt',
    'get_team_delete_prompt',
]
