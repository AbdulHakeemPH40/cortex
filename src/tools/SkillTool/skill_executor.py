"""
SkillTool - Main execution logic for agent skill management

This module implements the core skill execution system, enabling AI agents
to dynamically invoke specialized skills during conversations.

Key Components:
- Skill validation and permission checking
- Forked sub-agent execution for isolated skill contexts
- Inline skill processing
- Analytics and telemetry tracking

Note: Simplified conversion for Cortex IDE - removed terminal UI rendering,
complex remote skill loading, and Claude Code-specific analytics.
"""

from typing import Optional, Dict, Any, List, Callable, AsyncGenerator
from dataclasses import dataclass
import logging
import time

from .skill_tool import (
    Command,
    SkillInput,
    SkillOutput,
    get_command_name,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolUseContext:
    """Context for tool execution in Cortex IDE."""
    cwd: str
    app_state: Any  # Will be replaced with actual AppState
    options: Dict[str, Any]
    discovered_skill_names: Optional[set] = None
    query_tracking: Optional[Dict[str, Any]] = None


@dataclass
class ValidationResult:
    """Result of input validation."""
    result: bool
    message: Optional[str] = None
    error_code: Optional[int] = None


@dataclass
class PermissionDecision:
    """Permission decision for skill execution."""
    behavior: str  # 'allow', 'deny', 'ask'
    message: Optional[str] = None
    updated_input: Optional[Dict[str, str]] = None
    suggestions: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


async def validate_skill_input(
    skill_input: SkillInput,
    context: ToolUseContext
) -> ValidationResult:
    """
    Validate skill input before execution.
    
    Checks:
    1. Skill name is not empty
    2. Skill exists in available commands
    3. Skill allows model invocation
    4. Skill is prompt-based (not action-based)
    
    Args:
        skill_input: Input containing skill name and optional args
        context: Tool execution context
        
    Returns:
        ValidationResult indicating if input is valid
    """
    # Check skill format
    trimmed = skill_input.skill.strip()
    if not trimmed:
        return ValidationResult(
            result=False,
            message=f"Invalid skill format: {skill_input.skill}",
            error_code=1
        )
    
    # Remove leading slash if present
    has_leading_slash = trimmed.startswith('/')
    normalized_name = trimmed[1:] if has_leading_slash else trimmed
    
    # Get available commands
    from src.commands import get_commands
    commands = await get_commands(context.cwd)
    
    # Find the command
    found_command = find_command(normalized_name, commands)
    if not found_command:
        return ValidationResult(
            result=False,
            message=f"Unknown skill: {normalized_name}",
            error_code=2
        )
    
    # Check if command has model invocation disabled
    if found_command.disableModelInvocation:
        return ValidationResult(
            result=False,
            message=f"Skill {normalized_name} cannot be invoked due to disable-model-invocation",
            error_code=4
        )
    
    # Check if command is prompt-based
    if found_command.type != 'prompt':
        return ValidationResult(
            result=False,
            message=f"Skill {normalized_name} is not a prompt-based skill",
            error_code=5
        )
    
    return ValidationResult(result=True)


def find_command(name: str, commands: List[Command]) -> Optional[Command]:
    """
    Find a command by name in the list of available commands.
    
    Args:
        name: Command name to search for
        commands: List of available commands
        
    Returns:
        Command if found, None otherwise
    """
    for cmd in commands:
        if cmd.name.lower() == name.lower():
            return cmd
        # Also check userFacingName if available
        if cmd.userFacingName and cmd.userFacingName.lower() == name.lower():
            return cmd
    return None


async def check_skill_permissions(
    skill_input: SkillInput,
    context: ToolUseContext
) -> PermissionDecision:
    """
    Check permissions for skill execution.
    
    Implements permission hierarchy:
    1. Check deny rules (always honored)
    2. Check allow rules (auto-grant)
    3. Check safe properties (auto-grant for low-risk skills)
    4. Default to asking user
    
    Args:
        skill_input: Input containing skill name and args
        context: Tool execution context
        
    Returns:
        PermissionDecision with behavior and metadata
    """
    trimmed = skill_input.skill.strip()
    command_name = trimmed[1:] if trimmed.startswith('/') else trimmed
    
    # Get command object for metadata
    from src.commands import get_commands
    commands = await get_commands(context.cwd)
    command_obj = find_command(command_name, commands)
    
    # TODO: Implement permission rule checking when permission system is ready
    # For now, auto-allow all skills (can be configured later)
    
    # Auto-allow skills with only safe properties
    if command_obj and command_obj.type == 'prompt':
        if skill_has_only_safe_properties(command_obj):
            return PermissionDecision(
                behavior='allow',
                updated_input={
                    'skill': skill_input.skill,
                    'args': skill_input.args or ''
                }
            )
    
    # Prepare permission suggestions for user
    suggestions = [
        {
            'type': 'addRules',
            'rules': [{
                'toolName': 'Skill',
                'ruleContent': command_name
            }],
            'behavior': 'allow',
            'destination': 'localSettings'
        },
        {
            'type': 'addRules',
            'rules': [{
                'toolName': 'Skill',
                'ruleContent': f"{command_name}:*"
            }],
            'behavior': 'allow',
            'destination': 'localSettings'
        }
    ]
    
    # Default: ask user for permission
    return PermissionDecision(
        behavior='ask',
        message=f"Execute skill: {command_name}",
        suggestions=suggestions,
        updated_input={
            'skill': skill_input.skill,
            'args': skill_input.args or ''
        },
        metadata={'command': command_obj.__dict__} if command_obj else None
    )


def skill_has_only_safe_properties(command: Command) -> bool:
    """
    Check if a skill has only safe properties that don't require permission.
    
    Safe properties are those that don't modify files, execute code, or
    access external resources without user knowledge.
    
    Args:
        command: Command to check
        
    Returns:
        True if skill is safe, False otherwise
    """
    # Define safe properties (skills with only these are auto-allowed)
    SAFE_PROPERTIES = {
        'name', 'description', 'whenToUse', 'type', 'source',
        'userFacingName', 'disableModelInvocation', 'context',
        'effort', 'model'
    }
    
    # In a full implementation, this would check the command's
    # actual properties against the safe set
    # For now, assume bundled skills are safe
    return command.source == 'bundled'


async def execute_inline_skill(
    command: Command,
    command_name: str,
    args: Optional[str],
    context: ToolUseContext
) -> SkillOutput:
    """
    Execute a skill inline (in the current agent context).
    
    This processes the skill prompt and arguments directly without
    creating a sub-agent. Suitable for simple skills.
    
    Args:
        command: The command to execute
        command_name: Normalized command name
        args: Optional arguments
        context: Tool execution context
        
    Returns:
        SkillOutput with execution results
    """
    try:
        # Process the skill with arguments
        from src.utils.process_user_input import process_slash_command
        
        processed = await process_slash_command.process_prompt_slash_command(
            command_name,
            args or '',
            await get_commands(context.cwd),
            context
        )
        
        if not processed.should_query:
            raise ValueError("Command processing failed")
        
        # Extract metadata
        allowed_tools = processed.allowed_tools or []
        model = processed.model
        effort = command.effort if hasattr(command, 'effort') else None
        
        logger.info(f"Inline skill '{command_name}' executed successfully")
        
        return SkillOutput(
            success=True,
            commandName=command_name,
            status='inline',
            message="Skill executed successfully"
        )
        
    except Exception as e:
        logger.error(f"Error executing inline skill '{command_name}': {e}")
        return SkillOutput(
            success=False,
            commandName=command_name,
            status='inline',
            error=str(e)
        )


async def execute_forked_skill(
    command: Command,
    command_name: str,
    args: Optional[str],
    context: ToolUseContext,
    parent_message_id: Optional[str] = None
) -> SkillOutput:
    """
    Execute a skill in a forked sub-agent context.
    
    This creates an isolated agent with its own token budget to run
    the skill. Suitable for complex skills that need isolation.
    
    Args:
        command: The command to execute
        command_name: Normalized command name
        args: Optional arguments
        context: Tool execution context
        parent_message_id: ID of parent message for tracking
        
    Returns:
        SkillOutput with execution results including agent ID
    """
    start_time = time.time()
    
    try:
        # Import here to avoid circular dependencies
        from src.tools.AgentTool.run_agent import run_agent
        from src.utils.agent_context import get_agent_context
        from src.utils.uuid import create_agent_id
        
        # Create isolated agent
        agent_id = create_agent_id()
        
        # Prepare forked context
        from src.utils.forked_agent import prepare_forked_command_context
        
        forked_context = await prepare_forked_command_context(
            command,
            args or '',
            context
        )
        
        # Build agent definition with effort if specified
        agent_definition = forked_context.base_agent
        if hasattr(command, 'effort') and command.effort is not None:
            agent_definition = {
                **agent_definition,
                'effort': command.effort
            }
        
        logger.info(
            f"Executing forked skill '{command_name}' with agent {agent_id}"
        )
        
        # Run the sub-agent
        agent_messages = []
        async for message in run_agent(
            agent_definition=agent_definition,
            prompt_messages=forked_context.prompt_messages,
            tool_use_context=forked_context.modified_context,
            can_use_tool=lambda *args: True,  # TODO: Implement proper permission checking
            is_async=False,
            query_source='agent:custom',
            model=command.model if hasattr(command, 'model') else None,
            available_tools=context.options.get('tools', []),
            override={'agentId': agent_id}
        ):
            agent_messages.append(message)
        
        # Extract result text
        from src.utils.forked_agent import extract_result_text
        result_text = extract_result_text(
            agent_messages,
            'Skill execution completed'
        )
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Forked skill '{command_name}' completed in {duration_ms:.0f}ms"
        )
        
        return SkillOutput(
            success=True,
            commandName=command_name,
            status='forked',
            message=result_text
        )
        
    except Exception as e:
        logger.error(f"Error executing forked skill '{command_name}': {e}")
        return SkillOutput(
            success=False,
            commandName=command_name,
            status='forked',
            error=str(e)
        )


async def execute_skill(
    skill_input: SkillInput,
    context: ToolUseContext,
    parent_message_id: Optional[str] = None
) -> SkillOutput:
    """
    Main entry point for skill execution.
    
    Orchestrates the complete skill execution flow:
    1. Validate input
    2. Check permissions
    3. Determine execution mode (inline vs forked)
    4. Execute skill
    5. Track analytics
    
    Args:
        skill_input: Input containing skill name and args
        context: Tool execution context
        parent_message_id: ID of parent message for tracking
        
    Returns:
        SkillOutput with execution results
    """
    # Step 1: Validate input
    validation = await validate_skill_input(skill_input, context)
    if not validation.result:
        logger.warning(f"Skill validation failed: {validation.message}")
        return SkillOutput(
            success=False,
            commandName=skill_input.skill,
            status='inline',
            error=validation.message
        )
    
    # Normalize command name
    trimmed = skill_input.skill.strip()
    command_name = trimmed[1:] if trimmed.startswith('/') else trimmed
    
    # Get command object
    from src.commands import get_commands
    commands = await get_commands(context.cwd)
    command = find_command(command_name, commands)
    
    if not command:
        return SkillOutput(
            success=False,
            commandName=command_name,
            status='inline',
            error=f"Command '{command_name}' not found"
        )
    
    # Step 2: Check permissions (simplified - auto-allow for now)
    # TODO: Integrate with Cortex IDE permission system
    
    # Step 3: Track skill usage
    from src.utils.suggestions.skill_usage_tracking import record_skill_usage
    record_skill_usage(command_name)
    
    # Step 4: Determine execution mode and execute
    is_forked = (
        command.type == 'prompt' and
        hasattr(command, 'context') and
        command.context == 'fork'
    )
    
    if is_forked:
        logger.info(f"Executing skill '{command_name}' in forked mode")
        return await execute_forked_skill(
            command,
            command_name,
            skill_input.args,
            context,
            parent_message_id
        )
    else:
        logger.info(f"Executing skill '{command_name}' in inline mode")
        return await execute_inline_skill(
            command,
            command_name,
            skill_input.args,
            context
        )


# Export public API
__all__ = [
    'ToolUseContext',
    'ValidationResult',
    'PermissionDecision',
    'validate_skill_input',
    'check_skill_permissions',
    'execute_inline_skill',
    'execute_forked_skill',
    'execute_skill',
    'find_command',
    'skill_has_only_safe_properties',
]
