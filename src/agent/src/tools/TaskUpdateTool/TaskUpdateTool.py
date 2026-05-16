# ------------------------------------------------------------
# TaskUpdateTool.py
# Python conversion of TaskUpdateTool/TaskUpdateTool.ts
# 
# Full task update tool for AI agents.
# Updates task fields, manages dependencies, handles deletion,
# auto-assigns ownership, and runs completion hooks.
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from ...Tool import ToolDef, ToolResult, buildTool
    from ...services.analytics.growthbook import getFeatureValue_CACHED_MAY_BE_STALE
    from ...utils.agentSwarmsEnabled import isAgentSwarmsEnabled
    from ...utils.hooks import executeTaskCompletedHooks, getTaskCompletedHookMessage
    from ...utils.tasks import (
        blockTask,
        deleteTask,
        getTask,
        getTaskListId,
        isTodoV2Enabled,
        listTasks,
        updateTask,
    )
    from ...utils.teammate_state import (
        getAgentId,
        getAgentName,
        getTeammateColor,
        getTeamName,
    )
    from ...utils.teammateMailbox import writeToMailbox
    from tools.AgentTool.constants import VERIFICATION_AGENT_TYPE
    from .constants import TASK_UPDATE_TOOL_NAME
    from .prompt import DESCRIPTION, PROMPT
except ImportError:
    # Fallback stubs for type checking
    TASK_UPDATE_TOOL_NAME = 'TaskUpdate'
    DESCRIPTION = 'Update a task in the task list'
    PROMPT = 'Use this tool to update a task in the task list.'
    VERIFICATION_AGENT_TYPE = 'verifier'
    
    @dataclass
    class ToolResult:
        data: Any = None
    
    def buildTool(**kwargs):
        return kwargs
    
    def isAgentSwarmsEnabled():
        return False
    
    def isTodoV2Enabled():
        return False
    
    def getTaskListId():
        return None
    
    async def getTask(task_list_id, task_id):
        return None
    
    async def updateTask(task_list_id, task_id, updates):
        pass
    
    async def deleteTask(task_list_id, task_id):
        return True
    
    async def blockTask(task_list_id, task_id, block_id):
        pass
    
    async def listTasks(task_list_id):
        return []
    
    def getAgentId():
        return None
    
    def getAgentName():
        return None
    
    def getTeammateColor():
        return None
    
    def getTeamName():
        return None
    
    async def writeToMailbox(owner, message, task_list_id):
        pass
    
    async def executeTaskCompletedHooks(*args, **kwargs):
        return []
    
    def getTaskCompletedHookMessage(result):
        return str(result)
    
    def getFeatureValue_CACHED_MAY_BE_STALE(key, default):
        return default


# Input schema definition
inputSchema = {
    'type': 'object',
    'properties': {
        'taskId': {
            'type': 'string',
            'description': 'The ID of the task to update',
        },
        'subject': {
            'type': 'string',
            'description': 'New subject for the task',
        },
        'description': {
            'type': 'string',
            'description': 'New description for the task',
        },
        'activeForm': {
            'type': 'string',
            'description': 'Present continuous form shown in spinner when in_progress (e.g., "Running tests")',
        },
        'status': {
            'type': 'string',
            'enum': ['pending', 'in_progress', 'completed', 'deleted'],
            'description': 'New status for the task',
        },
        'addBlocks': {
            'type': 'array',
            'items': {'type': 'string'},
            'description': 'Task IDs that this task blocks',
        },
        'addBlockedBy': {
            'type': 'array',
            'items': {'type': 'string'},
            'description': 'Task IDs that block this task',
        },
        'owner': {
            'type': 'string',
            'description': 'New owner for the task',
        },
        'metadata': {
            'type': 'object',
            'description': 'Metadata keys to merge into the task. Set a key to null to delete it.',
        },
    },
    'required': ['taskId'],
}

# Output schema definition
outputSchema = {
    'type': 'object',
    'properties': {
        'success': {'type': 'boolean'},
        'taskId': {'type': 'string'},
        'updatedFields': {
            'type': 'array',
            'items': {'type': 'string'},
        },
        'error': {'type': 'string'},
        'statusChange': {
            'type': 'object',
            'properties': {
                'from': {'type': 'string'},
                'to': {'type': 'string'},
            },
        },
        'verificationNudgeNeeded': {'type': 'boolean'},
    },
    'required': ['success', 'taskId', 'updatedFields'],
}


def to_auto_classifier_input(input_data: Dict[str, Any]) -> str:
    """
    Convert input to auto-classifier format.
    
    Returns taskId with optional status and subject for pattern matching.
    """
    parts = [input_data.get('taskId', '')]
    if input_data.get('status'):
        parts.append(input_data['status'])
    if input_data.get('subject'):
        parts.append(input_data['subject'])
    return ' '.join(parts)


def feature_flag_enabled(flag_name: str) -> bool:
    """Check if a feature flag is enabled."""
    # In production, this would check actual feature flags
    # For now, use environment variable fallback
    return os.environ.get(f'FEATURE_{flag_name}', '').lower() in ('1', 'true', 'yes')


async def call(
    input_data: Dict[str, Any],
    context: Dict[str, Any],
) -> ToolResult:
    """
    Update a task in the task list.
    
    Handles:
    - Basic field updates (subject, description, activeForm, owner, status)
    - Task deletion (status='deleted')
    - Dependency management (addBlocks, addBlockedBy)
    - Auto-ownership assignment for teammates
    - Task completion hooks
    - Mailbox notifications for ownership changes
    - Verification nudge for completed task lists
    
    Returns update result with success status and updated fields.
    """
    task_id = input_data.get('taskId')
    subject = input_data.get('subject')
    description = input_data.get('description')
    active_form = input_data.get('activeForm')
    status = input_data.get('status')
    owner = input_data.get('owner')
    add_blocks = input_data.get('addBlocks', [])
    add_blocked_by = input_data.get('addBlockedBy', [])
    metadata = input_data.get('metadata')
    
    task_list_id = getTaskListId()
    
    # Auto-expand task list when updating tasks
    set_app_state = context.get('setAppState')
    if set_app_state:
        def expand_tasks_view(prev):
            if prev.get('expandedView') == 'tasks':
                return prev
            return {**prev, 'expandedView': 'tasks'}
        set_app_state(expand_tasks_view)
    
    # Check if task exists
    existing_task = await getTask(task_list_id, task_id)
    if not existing_task:
        return ToolResult(data={
            'success': False,
            'taskId': task_id,
            'updatedFields': [],
            'error': 'Task not found',
        })
    
    updated_fields: List[str] = []
    
    # Build updates dict
    updates: Dict[str, Any] = {}
    
    # Update basic fields if provided and different from current
    if subject is not None and subject != getattr(existing_task, 'subject', None):
        updates['subject'] = subject
        updated_fields.append('subject')
    
    if description is not None and description != getattr(existing_task, 'description', None):
        updates['description'] = description
        updated_fields.append('description')
    
    existing_active_form = getattr(existing_task, 'activeForm', None)
    if active_form is not None and active_form != existing_active_form:
        updates['activeForm'] = active_form
        updated_fields.append('activeForm')
    
    existing_owner = getattr(existing_task, 'owner', None)
    if owner is not None and owner != existing_owner:
        updates['owner'] = owner
        updated_fields.append('owner')
    
    # Auto-set owner when a teammate marks a task as in_progress without
    # explicitly providing an owner
    if (
        isAgentSwarmsEnabled()
        and status == 'in_progress'
        and owner is None
        and not existing_owner
    ):
        agent_name = getAgentName()
        if agent_name:
            updates['owner'] = agent_name
            updated_fields.append('owner')
    
    # Handle metadata merge
    if metadata is not None:
        existing_metadata = getattr(existing_task, 'metadata', None) or {}
        merged = dict(existing_metadata)
        for key, value in metadata.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        updates['metadata'] = merged
        updated_fields.append('metadata')
    
    # Handle status changes
    existing_status = getattr(existing_task, 'status', None)
    if status is not None and status != existing_status:
        # Handle deletion
        if status == 'deleted':
            deleted = await deleteTask(task_list_id, task_id)
            return ToolResult(data={
                'success': deleted,
                'taskId': task_id,
                'updatedFields': ['deleted'] if deleted else [],
                'error': None if deleted else 'Failed to delete task',
                'statusChange': {'from': existing_status, 'to': 'deleted'} if deleted else None,
            })
        
        # Run TaskCompleted hooks when marking as completed
        if status == 'completed':
            blocking_errors: List[str] = []
            
            abort_controller = context.get('abortController')
            signal = getattr(abort_controller, 'signal', None) if abort_controller else None
            
            try:
                generator = executeTaskCompletedHooks(
                    task_id,
                    getattr(existing_task, 'subject', ''),
                    getattr(existing_task, 'description', ''),
                    getAgentName(),
                    getTeamName(),
                    None,
                    signal,
                    None,
                    context,
                )
                
                async for result in generator:
                    if getattr(result, 'blockingError', None):
                        blocking_errors.append(getTaskCompletedHookMessage(result.blockingError))
            except Exception:
                # If hooks fail, continue with completion
                pass
            
            if blocking_errors:
                return ToolResult(data={
                    'success': False,
                    'taskId': task_id,
                    'updatedFields': [],
                    'error': '\n'.join(blocking_errors),
                })
        
        updates['status'] = status
        updated_fields.append('status')
    
    # Apply updates if any
    if updates:
        await updateTask(task_list_id, task_id, updates)
    
    # Notify new owner via mailbox when ownership changes
    if updates.get('owner') and isAgentSwarmsEnabled():
        sender_name = getAgentName() or 'team-lead'
        sender_color = getTeammateColor()
        new_owner = updates['owner']
        
        assignment_message = json.dumps({
            'type': 'task_assignment',
            'taskId': task_id,
            'subject': getattr(existing_task, 'subject', ''),
            'description': getattr(existing_task, 'description', ''),
            'assignedBy': sender_name,
            'timestamp': datetime.now().isoformat(),
        })
        
        await writeToMailbox(
            new_owner,
            {
                'from': sender_name,
                'text': assignment_message,
                'timestamp': datetime.now().isoformat(),
                'color': sender_color,
            },
            task_list_id,
        )
    
    # Add blocks if provided and not already present
    if add_blocks:
        existing_blocks = getattr(existing_task, 'blocks', []) or []
        new_blocks = [id for id in add_blocks if id not in existing_blocks]
        for block_id in new_blocks:
            await blockTask(task_list_id, task_id, block_id)
        if new_blocks:
            updated_fields.append('blocks')
    
    # Add blockedBy if provided and not already present
    if add_blocked_by:
        existing_blocked_by = getattr(existing_task, 'blockedBy', []) or []
        new_blocked_by = [id for id in add_blocked_by if id not in existing_blocked_by]
        for blocker_id in new_blocked_by:
            # Reverse: the blocker blocks this task
            await blockTask(task_list_id, blocker_id, task_id)
        if new_blocked_by:
            updated_fields.append('blockedBy')
    
    # Check for verification nudge
    verification_nudge_needed = False
    if (
        feature_flag_enabled('VERIFICATION_AGENT')
        and getFeatureValue_CACHED_MAY_BE_STALE('tengu_hive_evidence', False)
        and not context.get('agentId')
        and updates.get('status') == 'completed'
    ):
        all_tasks = await listTasks(task_list_id)
        all_done = all(t.status == 'completed' for t in all_tasks if hasattr(t, 'status'))
        
        if all_done and len(all_tasks) >= 3:
            # Check if any task has "verif" in subject (case insensitive)
            has_verification = any(
                re.search(r'verif', getattr(t, 'subject', ''), re.IGNORECASE)
                for t in all_tasks
            )
            if not has_verification:
                verification_nudge_needed = True
    
    return ToolResult(data={
        'success': True,
        'taskId': task_id,
        'updatedFields': updated_fields,
        'statusChange': {
            'from': existing_status,
            'to': updates['status'],
        } if 'status' in updates else None,
        'verificationNudgeNeeded': verification_nudge_needed,
    })


def map_tool_result_to_block_param(content: Dict[str, Any], tool_use_id: str) -> Dict[str, Any]:
    """
    Map tool result to block parameter format.
    
    Formats update result with optional teammate reminders and verification nudges.
    """
    success = content.get('success', False)
    task_id = content.get('taskId', '')
    updated_fields = content.get('updatedFields', [])
    error = content.get('error')
    status_change = content.get('statusChange')
    verification_nudge_needed = content.get('verificationNudgeNeeded', False)
    
    if not success:
        # Return as non-error so it doesn't trigger sibling tool cancellation
        return {
            'tool_use_id': tool_use_id,
            'type': 'tool_result',
            'content': error or f'Task #{task_id} not found',
        }
    
    result_content = f"Updated task #{task_id} {', '.join(updated_fields)}"
    
    # Add reminder for teammates when they complete a task
    if (
        status_change
        and status_change.get('to') == 'completed'
        and getAgentId()
        and isAgentSwarmsEnabled()
    ):
        result_content += (
            '\n\nTask completed. Call TaskList now to find your next available task '
            'or see if your work unblocked others.'
        )
    
    # Add verification nudge if needed
    if verification_nudge_needed:
        result_content += (
            f'\n\nNOTE: You just closed out 3+ tasks and none of them was a verification step. '
            f'Before writing your final summary, spawn the verification agent '
            f'(subagent_type="{VERIFICATION_AGENT_TYPE}"). You cannot self-assign PARTIAL by '
            f'listing caveats in your summary — only the verifier issues a verdict.'
        )
    
    return {
        'tool_use_id': tool_use_id,
        'type': 'tool_result',
        'content': result_content,
    }


# Tool definition
TaskUpdateTool = buildTool(
    name=TASK_UPDATE_TOOL_NAME,
    searchHint='update a task',
    maxResultSizeChars=100_000,
    description=lambda: DESCRIPTION,
    prompt=lambda: PROMPT,
    inputSchema=lambda: inputSchema,
    outputSchema=lambda: outputSchema,
    userFacingName=lambda: 'TaskUpdate',
    shouldDefer=True,
    isEnabled=lambda: isTodoV2Enabled(),
    isConcurrencySafe=lambda: True,
    toAutoClassifierInput=to_auto_classifier_input,
    renderToolUseMessage=lambda: None,
    call=call,
    mapToolResultToBlockParam=map_tool_result_to_block_param,
)
