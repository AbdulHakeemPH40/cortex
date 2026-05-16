# ------------------------------------------------------------
# localMainSessionTask.py
# Python conversion of LocalMainSessionTask.ts (lines 1-480)
# 
# Handles backgrounding the main session query for multi-LLM AI agent IDE:
# - Background sessions (Ctrl+B): Query continues running in background
# - Query orchestration: Spawns independent query() calls with progress tracking
# - Agent context management: Skill scoping via runWithAgentContext()
# - Transcript recording: Records background session conversations
# - Notification system: Enqueues completion notifications with XML tags
# - Foreground/background switching: Users can foreground background tasks
# - Multi-task support: Manages multiple concurrent AI sessions
# ------------------------------------------------------------

import asyncio
import os
import secrets
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from .constants.xml import (
        OUTPUT_FILE_TAG,
        STATUS_TAG,
        SUMMARY_TAG,
        TASK_ID_TAG,
        TASK_NOTIFICATION_TAG,
        TOOL_USE_ID_TAG,
    )
except ImportError:
    OUTPUT_FILE_TAG = "output_file"
    STATUS_TAG = "status"
    SUMMARY_TAG = "summary"
    TASK_ID_TAG = "task_id"
    TASK_NOTIFICATION_TAG = "task_notification"
    TOOL_USE_ID_TAG = "tool_use_id"

try:
    from .query import query
except ImportError:
    async def query(params: dict):
        """Dummy query generator - should be replaced with actual implementation."""
        for item in []:
            yield item

try:
    from .services.tokenEstimation import rough_token_count_estimation
except ImportError:
    def rough_token_count_estimation(text: str) -> int:
        """Rough token count estimation (fallback)."""
        return len(text) // 4

try:
    from .Task import create_task_state_base, SetAppState, TaskStateBase
except ImportError:
    def create_task_state_base(task_id: str, task_type: str, description: str, tool_use_id: str = None):
        return {
            'id': task_id,
            'type': task_type,
            'status': 'pending',
            'description': description,
            'toolUseId': tool_use_id,
            'startTime': int(time.time() * 1000),
        }
    
    SetAppState = Callable[[Callable[[dict], dict]], None]
    TaskStateBase = Dict[str, Any]

try:
    from .tools.AgentTool.loadAgentsDir import AgentDefinition, CustomAgentDefinition
except ImportError:
    AgentDefinition = Dict[str, Any]
    CustomAgentDefinition = Dict[str, Any]

try:
    from .agent_types.ids import asAgentId
except ImportError:
    def asAgentId(agent_id: str) -> str:
        return agent_id

try:
    from .agent_types.message import Message
except ImportError:
    Message = Dict[str, Any]

try:
    from .utils.abortController import createAbortController
except ImportError:
    def createAbortController():
        """Fallback abort controller."""
        return {'signal': {'aborted': False}}

try:
    from .utils.agentContext import runWithAgentContext, SubagentContext
except ImportError:
    class SubagentContext:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    def runWithAgentContext(context: SubagentContext, fn: Callable):
        """Fallback agent context runner."""
        import asyncio
        result = fn()
        if asyncio.iscoroutine(result):
            try:
                asyncio.get_running_loop()
                asyncio.create_task(result)
            except RuntimeError:
                asyncio.run(result)
        return result

try:
    from .utils.cleanupRegistry import registerCleanup
except ImportError:
    def registerCleanup(cleanup_fn: Callable):
        """Fallback cleanup registry."""
        def unregister():
            pass
        return unregister

try:
    from .utils.debug import logForDebugging
except ImportError:
    def logForDebugging(msg: str) -> None:
        print(f"[DEBUG] {msg}")

try:
    from .utils.log import logError
except ImportError:
    def logError(error: Exception) -> None:
        print(f"[ERROR] {error}")

try:
    from .utils.messageQueueManager import enqueue_pending_notification
except ImportError:
    def enqueue_pending_notification(notification: dict) -> None:
        """Fallback notification queue."""
        pass

try:
    from .utils.sdkEventQueue import emitTaskTerminatedSdk
except ImportError:
    def emitTaskTerminatedSdk(task_id: str, status: str, metadata: dict = None) -> None:
        """Fallback SDK event emitter."""
        pass

try:
    from .utils.sessionStorage import getAgentTranscriptPath, recordSidechainTranscript
except ImportError:
    def getAgentTranscriptPath(agent_id: str) -> str:
        return f"/tmp/agents/{agent_id}/transcript.json"
    
    async def recordSidechainTranscript(messages: list, task_id: str, last_uuid: str = None) -> None:
        """Fallback transcript recorder."""
        pass

try:
    from .utils.task.diskOutput import evictTaskOutput, getTaskOutputPath, initTaskOutputAsSymlink
except ImportError:
    def evictTaskOutput(task_id: str) -> None:
        pass
    
    def getTaskOutputPath(task_id: str) -> str:
        return f"/tmp/tasks/{task_id}.log"
    
    def initTaskOutputAsSymlink(task_id: str, target_path: str) -> None:
        pass

try:
    from .utils.task.framework import registerTask, updateTaskState
except ImportError:
    def registerTask(task_state: dict, setAppState: SetAppState) -> None:
        setAppState(lambda prev: {
            **prev,
            'tasks': {**prev.get('tasks', {}), task_state['id']: task_state}
        })
    
    def updateTaskState(task_id: str, setAppState: SetAppState, updater: Callable) -> None:
        setAppState(lambda prev: {
            **prev,
            'tasks': {
                **prev.get('tasks', {}),
                task_id: updater(prev.get('tasks', {}).get(task_id, {}))
            }
        })


# ============================================================
# TYPE DEFINITIONS
# ============================================================

LocalMainSessionTaskState = Dict[str, Any]
"""
Main session task state extends LocalAgentTaskState with:
- agentType: 'main-session'
- isBackgrounded: Whether task is running in background
- pendingMessages: Messages queued while backgrounded
- retrieved: Whether task output has been retrieved
- lastReportedToolCount: Last reported tool use count
- lastReportedTokenCount: Last reported token count
- retain: Whether to retain task in UI
- diskLoaded: Whether task messages loaded from disk
"""

ToolActivity = Dict[str, Any]
"""
Tool activity tracking:
- toolName: Name of tool used
- input: Tool input parameters
"""


# ============================================================
# CONSTANTS
# ============================================================

# Default agent definition for main session tasks when no agent is specified
DEFAULT_MAIN_SESSION_AGENT: CustomAgentDefinition = {
    'agentType': 'main-session',
    'whenToUse': 'Main session query',
    'source': 'userSettings',
    'getSystemPrompt': lambda: '',
}

# Task ID alphabet for main session tasks
TASK_ID_ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'

# Max recent activities to keep for display
MAX_RECENT_ACTIVITIES = 5


# ============================================================
# TASK ID GENERATION
# ============================================================

def generateMainSessionTaskId() -> str:
    """
    Generate a unique task ID for main session tasks.
    Uses 's' prefix to distinguish from agent tasks ('a' prefix).
    
    Returns:
        Unique task ID string (e.g., 's3k9m2x7p')
    """
    random_bytes = secrets.token_bytes(8)
    task_id = 's'
    for byte in random_bytes:
        task_id += TASK_ID_ALPHABET[byte % len(TASK_ID_ALPHABET)]
    return task_id


# ============================================================
# MAIN SESSION TASK REGISTRATION
# ============================================================

def registerMainSessionTask(
    description: str,
    setAppState: SetAppState,
    mainThreadAgentDefinition: Optional[AgentDefinition] = None,
    existingAbortController: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Register a backgrounded main session task.
    Called when the user backgrounds the current session query.
    
    Args:
        description: Description of the task
        setAppState: State setter function
        mainThreadAgentDefinition: Optional agent definition if running with --agent
        existingAbortController: Optional abort controller to reuse (for backgrounding an active query)
    
    Returns:
        Dict with taskId and abortSignal for stopping the background query
    """
    task_id = generateMainSessionTaskId()
    
    # Link output to an isolated per-task transcript file (same layout as
    # sub-agents). Do NOT use getTranscriptPath() — that's the main session's
    # file, and writing there from a background query after /clear would corrupt
    # the post-clear conversation. The isolated path lets this task survive
    # /clear: the symlink re-link in clearConversation handles session ID changes.
    initTaskOutputAsSymlink(
        task_id,
        getAgentTranscriptPath(asAgentId(task_id)),
    )
    
    # Use the existing abort controller if provided (important for backgrounding an active query)
    # This ensures that aborting the task will abort the actual query
    abortController = existingAbortController or createAbortController()
    
    def cleanup_callback():
        # Clean up on process exit
        setAppState(lambda prev: {
            **prev,
            'tasks': {k: v for k, v in prev.get('tasks', {}).items() if k != task_id}
        })
    
    unregisterCleanup = registerCleanup(cleanup_callback)
    
    # Use provided agent definition or default
    selectedAgent = mainThreadAgentDefinition or DEFAULT_MAIN_SESSION_AGENT
    
    # Create task state - already backgrounded since this is called when user backgrounds
    taskState: LocalMainSessionTaskState = {
        **create_task_state_base(task_id, 'local_agent', description),
        'type': 'local_agent',
        'status': 'running',
        'agentId': task_id,
        'prompt': description,
        'selectedAgent': selectedAgent,
        'agentType': 'main-session',
        'abortController': abortController,
        'unregisterCleanup': unregisterCleanup,
        'retrieved': False,
        'lastReportedToolCount': 0,
        'lastReportedTokenCount': 0,
        'isBackgrounded': True,  # Already backgrounded
        'pendingMessages': [],
        'retain': False,
        'diskLoaded': False,
    }
    
    logForDebugging(
        f"[LocalMainSessionTask] Registering task {task_id} with description: {description}"
    )
    registerTask(taskState, setAppState)
    
    # Verify task was registered by checking state
    def verify_registration(prev: dict) -> dict:
        has_task = task_id in prev.get('tasks', {})
        logForDebugging(
            f"[LocalMainSessionTask] After registration, task {task_id} exists in state: {has_task}"
        )
        return prev
    
    setAppState(verify_registration)
    
    return {
        'taskId': task_id,
        'abortSignal': abortController['signal'],
    }


# ============================================================
# TASK COMPLETION
# ============================================================

def completeMainSessionTask(
    task_id: str,
    success: bool,
    setAppState: SetAppState,
) -> None:
    """
    Complete the main session task and send notification.
    Called when the backgrounded query finishes.
    
    Args:
        task_id: Task ID to complete
        success: Whether task completed successfully
        setAppState: State setter function
    """
    wasBackgrounded = True
    toolUseId: Optional[str] = None
    
    def update_task(task: dict) -> dict:
        nonlocal wasBackgrounded, toolUseId
        
        if task.get('status') != 'running':
            return task
        
        # Track if task was backgrounded (for notification decision)
        wasBackgrounded = task.get('isBackgrounded', True)
        toolUseId = task.get('toolUseId')
        
        if task.get('unregisterCleanup'):
            task['unregisterCleanup']()
        
        return {
            **task,
            'status': 'completed' if success else 'failed',
            'endTime': int(time.time() * 1000),
            'messages': task.get('messages', [])[-1:] if task.get('messages') else None,
        }
    
    updateTaskState(task_id, setAppState, update_task)
    
    evictTaskOutput(task_id)
    
    # Only send notification if task is still backgrounded (not foregrounded)
    # If foregrounded, user is watching it directly - no notification needed
    if wasBackgrounded:
        enqueueMainSessionNotification(
            task_id,
            'Background session',
            'completed' if success else 'failed',
            setAppState,
            toolUseId,
        )
    else:
        # Foregrounded: no XML notification (TUI user is watching), but SDK
        # consumers still need to see the task_started bookend close.
        # Set notified so evictTerminalTask/generateTaskAttachments eviction
        # guards pass; the backgrounded path sets this inside
        # enqueueMainSessionNotification's check-and-set.
        updateTaskState(task_id, setAppState, lambda task: {**task, 'notified': True})
        emitTaskTerminatedSdk(task_id, 'completed' if success else 'failed', {
            'toolUseId': toolUseId,
            'summary': 'Background session',
        })


# ============================================================
# NOTIFICATION ENQUEUEING
# ============================================================

def enqueueMainSessionNotification(
    task_id: str,
    description: str,
    status: str,
    setAppState: SetAppState,
    toolUseId: Optional[str] = None,
) -> None:
    """
    Enqueue a notification about the backgrounded session completing.
    
    Args:
        task_id: Task ID
        description: Task description
        status: 'completed' or 'failed'
        setAppState: State setter function
        toolUseId: Associated tool use ID (optional)
    """
    # Atomically check and set notified flag to prevent duplicate notifications.
    shouldEnqueue = False
    
    def check_notified(task: dict) -> dict:
        nonlocal shouldEnqueue
        if task.get('notified'):
            return task
        shouldEnqueue = True
        return {**task, 'notified': True}
    
    updateTaskState(task_id, setAppState, check_notified)
    
    if not shouldEnqueue:
        return
    
    summary = (
        f'Background session "{description}" completed'
        if status == 'completed'
        else f'Background session "{description}" failed'
    )
    
    toolUseIdLine = (
        f'\n<{TOOL_USE_ID_TAG}>{toolUseId}</{TOOL_USE_ID_TAG}>'
        if toolUseId
        else ''
    )
    
    outputPath = getTaskOutputPath(task_id)
    message = f"""<{TASK_NOTIFICATION_TAG}>
<{TASK_ID_TAG}>{task_id}</{TASK_ID_TAG}>{toolUseIdLine}
<{OUTPUT_FILE_TAG}>{outputPath}</{OUTPUT_FILE_TAG}>
<{STATUS_TAG}>{status}</{STATUS_TAG}>
<{SUMMARY_TAG}>{summary}</{SUMMARY_TAG}>
</{TASK_NOTIFICATION_TAG}>"""
    
    enqueue_pending_notification({'value': message, 'mode': 'task-notification'})


# ============================================================
# FOREGROUND/BACKGROUND SWITCHING
# ============================================================

def foregroundMainSessionTask(
    task_id: str,
    setAppState: SetAppState,
) -> Optional[List[Message]]:
    """
    Foreground a main session task - mark it as foregrounded so its output
    appears in the main view. The background query keeps running.
    
    Args:
        task_id: Task ID to foreground
        setAppState: State setter function
    
    Returns:
        Task's accumulated messages, or None if task not found
    """
    taskMessages: Optional[List[Message]] = None
    
    def update_foreground(prev: dict) -> dict:
        nonlocal taskMessages
        
        task = prev.get('tasks', {}).get(task_id)
        if not task or task.get('type') != 'local_agent':
            return prev
        
        taskMessages = task.get('messages')
        
        # Restore previous foregrounded task to background if it exists
        prevId = prev.get('foregroundedTaskId')
        prevTask = prev.get('tasks', {}).get(prevId) if prevId else None
        restorePrev = (
            prevId and
            prevId != task_id and
            prevTask and
            prevTask.get('type') == 'local_agent'
        )
        
        updated_tasks = {**prev.get('tasks', {})}
        
        if restorePrev:
            updated_tasks[prevId] = {**prevTask, 'isBackgrounded': True}
        
        updated_tasks[task_id] = {**task, 'isBackgrounded': False}
        
        return {
            **prev,
            'foregroundedTaskId': task_id,
            'tasks': updated_tasks,
        }
    
    setAppState(update_foreground)
    
    return taskMessages


# ============================================================
# TASK TYPE CHECKING
# ============================================================

def isMainSessionTask(task: Any) -> bool:
    """
    Check if a task is a main session task (vs a regular agent task).
    
    Args:
        task: Task object to check
    
    Returns:
        True if task is a main session task
    """
    if (
        not isinstance(task, dict) or
        task is None or
        'type' not in task or
        'agentType' not in task
    ):
        return False
    
    return (
        task.get('type') == 'local_agent' and
        task.get('agentType') == 'main-session'
    )


# ============================================================
# BACKGROUND SESSION ORCHESTRATION
# ============================================================

def startBackgroundSession(
    *,
    messages: List[Message],
    queryParams: Dict[str, Any],
    description: str,
    setAppState: SetAppState,
    agentDefinition: Optional[AgentDefinition] = None,
) -> str:
    """
    Start a fresh background session with the given messages.
    
    Spawns an independent query() call with the current messages and registers it
    as a background task. The caller's foreground query continues running normally.
    
    Args:
        messages: Conversation messages to start with
        queryParams: Query parameters (excluding messages)
        description: Task description
        setAppState: State setter function
        agentDefinition: Optional agent definition
    
    Returns:
        Task ID for the background session
    """
    registration = registerMainSessionTask(
        description,
        setAppState,
        agentDefinition,
    )
    task_id = registration['taskId']
    abortSignal = registration['abortSignal']
    
    # Persist the pre-backgrounding conversation to the task's isolated
    # transcript so TaskOutput shows context immediately. Subsequent messages
    # are written incrementally below.
    async def record_initial():
        try:
            await recordSidechainTranscript(messages, task_id)
        except Exception as err:
            logForDebugging(f"bg-session initial transcript write failed: {err}")
    
    asyncio.ensure_future(record_initial())
    
    # Wrap in agent context so skill invocations scope to this task's agentId
    # (not null). This lets clearInvokedSkills(preservedAgentIds) selectively
    # preserve this task's skills across /clear. AsyncLocalStorage isolates
    # concurrent async chains — this wrapper doesn't affect the foreground.
    agentContext = SubagentContext(
        agentId=task_id,
        agentType='subagent',
        subagentName='main-session',
        isBuiltIn=True,
    )
    
    async def run_background_query():
        try:
            bgMessages: List[Message] = list(messages)
            recentActivities: List[ToolActivity] = []
            toolCount = 0
            tokenCount = 0
            lastRecordedUuid = messages[-1].get('uuid') if messages else None
            
            # Build query params with messages
            query_params = {
                'messages': bgMessages,
                **queryParams,
            }
            
            async for event in query(query_params):
                if abortSignal.get('aborted'):
                    # Aborted mid-stream — completeMainSessionTask won't be reached.
                    # chat:killAgents path already marked notified + emitted; stopTask path did not.
                    alreadyNotified = False
                    
                    def check_notified_abort(task: dict) -> dict:
                        nonlocal alreadyNotified
                        alreadyNotified = task.get('notified') is True
                        return task if alreadyNotified else {**task, 'notified': True}
                    
                    updateTaskState(task_id, setAppState, check_notified_abort)
                    
                    if not alreadyNotified:
                        emitTaskTerminatedSdk(task_id, 'stopped', {
                            'summary': description,
                        })
                    return
                
                if event.get('type') not in ('user', 'assistant', 'system'):
                    continue
                
                bgMessages.append(event)
                
                # Per-message write (matches runAgent.ts pattern) — gives live
                # TaskOutput progress and keeps the transcript file current even if
                # /clear re-links the symlink mid-run.
                async def record_event():
                    try:
                        await recordSidechainTranscript([event], task_id, lastRecordedUuid)
                    except Exception as err:
                        logForDebugging(f"bg-session transcript write failed: {err}")
                
                asyncio.ensure_future(record_event())
                lastRecordedUuid = event.get('uuid')
                
                if event.get('type') == 'assistant':
                    for block in event.get('message', {}).get('content', []):
                        if block.get('type') == 'text':
                            tokenCount += rough_token_count_estimation(block.get('text', ''))
                        elif block.get('type') == 'tool_use':
                            toolCount += 1
                            activity: ToolActivity = {
                                'toolName': block.get('name'),
                                'input': block.get('input', {}),
                            }
                            recentActivities.append(activity)
                            if len(recentActivities) > MAX_RECENT_ACTIVITIES:
                                recentActivities.pop(0)
                
                def update_progress(prev: dict) -> dict:
                    task = prev.get('tasks', {}).get(task_id)
                    if not task or task.get('type') != 'local_agent':
                        return prev
                    
                    prevProgress = task.get('progress')
                    if (
                        prevProgress and
                        prevProgress.get('tokenCount') == tokenCount and
                        prevProgress.get('toolUseCount') == toolCount and
                        task.get('messages') is bgMessages
                    ):
                        return prev
                    
                    return {
                        **prev,
                        'tasks': {
                            **prev.get('tasks', {}),
                            task_id: {
                                **task,
                                'progress': {
                                    'tokenCount': tokenCount,
                                    'toolUseCount': toolCount,
                                    'recentActivities': (
                                        prevProgress.get('recentActivities')
                                        if prevProgress and prevProgress.get('toolUseCount') == toolCount
                                        else list(recentActivities)
                                    ),
                                },
                                'messages': bgMessages,
                            },
                        },
                    }
                
                setAppState(update_progress)
            
            completeMainSessionTask(task_id, True, setAppState)
        except Exception as error:
            logError(error)
            completeMainSessionTask(task_id, False, setAppState)
    
    runWithAgentContext(agentContext, lambda: run_background_query())
    
    return task_id


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "LocalMainSessionTaskState",
    "DEFAULT_MAIN_SESSION_AGENT",
    "generateMainSessionTaskId",
    "registerMainSessionTask",
    "completeMainSessionTask",
    "enqueueMainSessionNotification",
    "foregroundMainSessionTask",
    "isMainSessionTask",
    "startBackgroundSession",
]
