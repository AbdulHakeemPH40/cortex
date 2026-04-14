"""
Stop Hooks - Handles stop condition hooks and cleanup logic.
TypeScript source: query/stopHooks.ts (474 lines)
Converts query stop/continuation conditions through async generators.

NOTE: Python async generators cannot use 'return value' syntax.
Use 'return' alone to exit the generator, which implicitly returns StopIteration.
The yield/return value is handled at the call site via StopAsyncIteration exception.
"""

import os
import asyncio
import time
from typing import Optional, Dict, Any, List, TypedDict, AsyncGenerator
from dataclasses import dataclass

# ============================================================
# PHASE 1: Imports & Type Definitions
# ============================================================

try:
    from bun.bundle import feature
except ImportError:
    def feature(name: str) -> bool:
        """Stub feature flag - always returns False"""
        return False

try:
    from keybindings.shortcutFormat import getShortcutDisplay
except ImportError:
    def getShortcutDisplay(command: str, scope: str, default: str) -> str:
        """Stub - returns shortcut display"""
        return default

try:
    from memdir.paths import isExtractModeActive
except ImportError:
    def isExtractModeActive() -> bool:
        """Stub - extract mode not active"""
        return False

try:
    from services.analytics.index import logEvent
except ImportError:
    def logEvent(event: str, data: Dict[str, Any]) -> None:
        """Stub - logs event"""
        pass

try:
    from utils.attachments import createAttachmentMessage
except ImportError:
    def createAttachmentMessage(attachment: Dict[str, Any]) -> Dict[str, Any]:
        """Stub - creates attachment message"""
        return {'type': 'attachment', 'attachment': attachment}

try:
    from utils.debug import logForDebugging
except ImportError:
    def logForDebugging(msg: str, **kwargs) -> None:
        """Stub - logs for debugging"""
        pass

try:
    from utils.errors import errorMessage
except ImportError:
    def errorMessage(error: Exception) -> str:
        """Stub - converts error to message"""
        return str(error)

try:
    from utils.hooks import (
        executeStopHooks,
        executeTaskCompletedHooks,
        executeTeammateIdleHooks,
        getStopHookMessage,
        getTaskCompletedHookMessage,
        getTeammateIdleHookMessage,
    )
except ImportError:
    async def executeStopHooks(*args, **kwargs):
        """Stub - executes stop hooks"""
        return
        yield  # Make it an async generator
    
    async def executeTaskCompletedHooks(*args, **kwargs):
        """Stub - executes task completed hooks"""
        return
        yield
    
    async def executeTeammateIdleHooks(*args, **kwargs):
        """Stub - executes teammate idle hooks"""
        return
        yield
    
    def getStopHookMessage(error) -> str:
        return str(error)
    
    def getTaskCompletedHookMessage(error) -> str:
        return str(error)
    
    def getTeammateIdleHookMessage(error) -> str:
        return str(error)

try:
    from utils.messages import (
        createStopHookSummaryMessage,
        createSystemMessage,
        createUserInterruptionMessage,
        createUserMessage,
    )
except ImportError:
    def createStopHookSummaryMessage(*args, **kwargs) -> Dict[str, Any]:
        """Stub - creates stop hook summary"""
        return {'type': 'system', 'summary': 'hooks completed'}
    
    def createSystemMessage(content: str, level: str = 'info') -> Dict[str, Any]:
        """Stub - creates system message"""
        return {'type': 'system', 'content': content, 'level': level}
    
    def createUserInterruptionMessage(toolUse: bool = False) -> Dict[str, Any]:
        """Stub - creates user interruption message"""
        return {'type': 'user', 'interrupted': True, 'toolUse': toolUse}
    
    def createUserMessage(content: str = '', **kwargs) -> Dict[str, Any]:
        """Stub - creates user message"""
        return {'type': 'user', 'message': {'content': content}, **kwargs}

try:
    from utils.tasks import getTaskListId, listTasks
except ImportError:
    def getTaskListId() -> str:
        """Stub - gets task list ID"""
        return ''
    
    async def listTasks(taskListId: str) -> List[Dict[str, Any]]:
        """Stub - lists tasks"""
        return []

try:
    from utils.teammate import getAgentName, getTeamName, isTeammate
except ImportError:
    def getAgentName() -> Optional[str]:
        """Stub - gets agent name"""
        return None
    
    def getTeamName() -> Optional[str]:
        """Stub - gets team name"""
        return None
    
    def isTeammate() -> bool:
        """Stub - checks if teammate"""
        return False

try:
    from utils.envUtils import isBareMode, isEnvDefinedFalsy
except ImportError:
    def isBareMode() -> bool:
        """Stub - checks bare mode"""
        return False
    
    def isEnvDefinedFalsy(env_var: Optional[str]) -> bool:
        """Stub - checks if env var is falsy"""
        return env_var == 'false' or env_var == '0'

try:
    from utils.forkedAgent import createCacheSafeParams, saveCacheSafeParams
except ImportError:
    def createCacheSafeParams(context: Dict[str, Any]) -> Dict[str, Any]:
        """Stub - creates cache safe params"""
        return {}
    
    def saveCacheSafeParams(params: Dict[str, Any]) -> None:
        """Stub - saves cache safe params"""
        pass

try:
    from services.autoDream.autoDream import executeAutoDream
except ImportError:
    async def executeAutoDream(context: Dict[str, Any], appendMessage=None) -> None:
        """Stub - executes auto dream"""
        pass

try:
    from services.PromptSuggestion.promptSuggestion import executePromptSuggestion
except ImportError:
    async def executePromptSuggestion(context: Dict[str, Any]) -> None:
        """Stub - executes prompt suggestion"""
        pass

# ============================================================
# Feature-gated module imports
# ============================================================

_extractMemoriesModule = None
if feature('EXTRACT_MEMORIES'):
    try:
        from services.extractMemories.extractMemories import executeExtractMemories
        _extractMemoriesModule = True
    except ImportError:
        _extractMemoriesModule = None

_jobClassifierModule = None
if feature('TEMPLATES'):
    try:
        from jobs.classifier import classifyAndWriteState
        _jobClassifierModule = True
    except ImportError:
        _jobClassifierModule = None


# ============================================================
# Type Definitions
# ============================================================

class StopHookInfo(TypedDict, total=False):
    """Information about a single stop hook execution"""
    command: str
    promptText: Optional[str]
    durationMs: Optional[int]


class StopHookResult(TypedDict):
    """Result from stop hook execution"""
    blockingErrors: List[Dict[str, Any]]
    preventContinuation: bool


class HookProgress(TypedDict, total=False):
    """Progress data from hook execution"""
    command: Optional[str]
    promptText: Optional[str]


# ============================================================
# Main Async Generator Function
# ============================================================

async def handleStopHooks(
    messagesForQuery: List[Dict[str, Any]],
    assistantMessages: List[Dict[str, Any]],
    systemPrompt: str,
    userContext: Dict[str, str],
    systemContext: Dict[str, str],
    toolUseContext: Any,  # ToolUseContext
    querySource: str,
    stopHookActive: Optional[bool] = None,
):
    """
    Handle stop condition hooks and cleanup logic.
    
    This async generator:
    1. Saves cache-safe params for main session queries
    2. Runs template job classification if applicable
    3. Executes background bookkeeping (prompt suggestion, memory extraction, auto-dream)
    4. Handles Chicago MCP cleanup
    5. Executes stop hooks and processes results
    6. For teammates: runs TaskCompleted and TeammateIdle hooks
    
    Yields: Stream events, messages, and hook progress
    Returns: StopHookResult with blocking errors and continuation status
    
    TS lines 65-473 (~409 lines - full implementation)
    """
    hookStartTime = time.time() * 1000  # milliseconds
    
    stopHookContext = {
        'messages': messagesForQuery + assistantMessages,
        'systemPrompt': systemPrompt,
        'userContext': userContext,
        'systemContext': systemContext,
        'toolUseContext': toolUseContext,
        'querySource': querySource,
    }
    
    # Save cache params for main session / SDK queries
    # (not for subagents which must not overwrite)
    if querySource == 'repl_main_thread' or querySource == 'sdk':
        saveCacheSafeParams(createCacheSafeParams(stopHookContext))
    
    # Template job classification
    if (
        feature('TEMPLATES')
        and os.environ.get('CLAUDE_JOB_DIR')
        and querySource.startswith('repl_main_thread')
        and not toolUseContext.get('agentId')
    ):
        # Full turn history - assistantMessages resets each iteration
        turnAssistantMessages = [
            m for m in stopHookContext['messages']
            if m.get('type') == 'assistant'
        ]
        
        async def classify_and_write():
            try:
                if _jobClassifierModule:
                    await classifyAndWriteState(
                        os.environ.get('CLAUDE_JOB_DIR'),
                        turnAssistantMessages,
                    )
            except Exception as err:
                logForDebugging(
                    f'[job] classifier error: {errorMessage(err)}',
                    level='error'
                )
        
        try:
            # Race between classification and 60s timeout
            await asyncio.wait_for(
                classify_and_write(),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            pass
    
    # Skip background bookkeeping in bare mode
    if not isBareMode():
        # Prompt suggestion
        if not isEnvDefinedFalsy(os.environ.get('CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION')):
            try:
                asyncio.create_task(executePromptSuggestion(stopHookContext))
            except:
                pass
        
        # Extract memories
        if (
            feature('EXTRACT_MEMORIES')
            and not toolUseContext.get('agentId')
            and isExtractModeActive()
        ):
            try:
                if _extractMemoriesModule:
                    asyncio.create_task(
                        executeExtractMemories(
                            stopHookContext,
                            toolUseContext.get('appendSystemMessage'),
                        )
                    )
            except:
                pass
        
        # Auto-dream
        if not toolUseContext.get('agentId'):
            try:
                asyncio.create_task(
                    executeAutoDream(
                        stopHookContext,
                        toolUseContext.get('appendSystemMessage'),
                    )
                )
            except:
                pass
    
    # Chicago MCP cleanup (main thread only)
    if feature('CHICAGO_MCP') and not toolUseContext.get('agentId'):
        try:
            # Async import at runtime
            async def cleanup_computer_use():
                try:
                    from utils.computerUse.cleanup import cleanupComputerUseAfterTurn
                    await cleanupComputerUseAfterTurn(toolUseContext)
                except:
                    # Failures are silent - this is dogfooding cleanup
                    pass
            
            asyncio.create_task(cleanup_computer_use())
        except:
            pass
    
    # Main try-except for hook execution
    try:
        blockingErrors = []
        appState = toolUseContext.get('getAppState', lambda: {})()
        permissionMode = appState.get('toolPermissionContext', {}).get('mode')
        
        generator = executeStopHooks(
            permissionMode,
            toolUseContext.get('abortController', {}).get('signal'),
            None,  # undefined
            stopHookActive if stopHookActive is not None else False,
            toolUseContext.get('agentId'),
            toolUseContext,
            messagesForQuery + assistantMessages,
            toolUseContext.get('agentType'),
        )
        
        # Consume all progress messages and get blocking errors
        stopHookToolUseID = ''
        hookCount = 0
        preventedContinuation = False
        stopReason = ''
        hasOutput = False
        hookErrors: List[str] = []
        hookInfos: List[StopHookInfo] = []
        
        async for result in generator:
            if result.get('message'):
                message = result['message']
                yield message
                
                # Track toolUseID from progress messages
                if (message.get('type') == 'progress' 
                    and message.get('toolUseID')):
                    stopHookToolUseID = message['toolUseID']
                    hookCount += 1
                    
                    # Extract hook command and prompt text
                    progressData = message.get('data', {})
                    if progressData.get('command'):
                        hookInfos.append({
                            'command': progressData['command'],
                            'promptText': progressData.get('promptText'),
                        })
                
                # Track errors and output from attachments
                if message.get('type') == 'attachment':
                    attachment = message.get('attachment', {})
                    hookEvent = attachment.get('hookEvent')
                    
                    if hookEvent in ('Stop', 'SubagentStop'):
                        if attachment.get('type') == 'hook_non_blocking_error':
                            hookErrors.append(
                                attachment.get('stderr')
                                or f"Exit code {attachment.get('exitCode')}"
                            )
                            hasOutput = True
                        elif attachment.get('type') == 'hook_error_during_execution':
                            hookErrors.append(attachment.get('content', ''))
                            hasOutput = True
                        elif attachment.get('type') == 'hook_success':
                            # Check if hook produced output
                            stdout = attachment.get('stdout', '')
                            stderr = attachment.get('stderr', '')
                            if (stdout and stdout.strip()) or (stderr and stderr.strip()):
                                hasOutput = True
                        
                        # Extract per-hook duration
                        if (attachment.get('durationMs') is not None
                            and attachment.get('command')):
                            for info in hookInfos:
                                if (info.get('command') == attachment.get('command')
                                    and info.get('durationMs') is None):
                                    info['durationMs'] = attachment.get('durationMs')
                                    break
            
            if result.get('blockingError'):
                userMessage = createUserMessage(
                    content=getStopHookMessage(result['blockingError']),
                    isMeta=True,  # Hide from UI
                )
                blockingErrors.append(userMessage)
                yield userMessage
                hasOutput = True
                hookErrors.append(result['blockingError'].get('blockingError', ''))
            
            # Check if hook wants to prevent continuation
            if result.get('preventContinuation'):
                preventedContinuation = True
                stopReason = result.get('stopReason', 'Stop hook prevented continuation')
                yield createAttachmentMessage({
                    'type': 'hook_stopped_continuation',
                    'message': stopReason,
                    'hookName': 'Stop',
                    'toolUseID': stopHookToolUseID,
                    'hookEvent': 'Stop',
                })
            
            # Check if aborted
            if toolUseContext.get('abortController', {}).get('signal', {}).get('aborted'):
                logEvent('tengu_pre_stop_hooks_cancelled', {
                    'queryChainId': toolUseContext.get('queryTracking', {}).get('chainId', ''),
                    'queryDepth': toolUseContext.get('queryTracking', {}).get('depth'),
                })
                yield createUserInterruptionMessage(toolUse=False)
                return
        
        # Create summary if hooks ran
        if hookCount > 0:
            yield createStopHookSummaryMessage(
                hookCount,
                hookInfos,
                hookErrors,
                preventedContinuation,
                stopReason,
                hasOutput,
                'suggestion',
                stopHookToolUseID,
            )
            
            # Notification about errors
            if hookErrors:
                expandShortcut = getShortcutDisplay(
                    'app:toggleTranscript',
                    'Global',
                    'ctrl+o',
                )
                toolUseContext.get('addNotification', lambda x: None)({
                    'key': 'stop-hook-error',
                    'text': f'Stop hook error occurred · {expandShortcut} to see',
                    'priority': 'immediate',
                })
        
        if preventedContinuation:
            return
        
        if blockingErrors:
            return
        
        # After Stop hooks pass, run TeammateIdle and TaskCompleted hooks
        if isTeammate():
            teammateName = getAgentName() or ''
            teamName = getTeamName() or ''
            teammateBlockingErrors: List[Dict[str, Any]] = []
            teammatePreventedContinuation = False
            teammateStopReason: Optional[str] = None
            teammateHookToolUseID = ''
            
            # Run TaskCompleted hooks for in-progress tasks
            taskListId = getTaskListId()
            tasks = await listTasks(taskListId)
            inProgressTasks = [
                t for t in tasks
                if t.get('status') == 'in_progress'
                and t.get('owner') == teammateName
            ]
            
            for task in inProgressTasks:
                taskCompletedGenerator = executeTaskCompletedHooks(
                    task.get('id'),
                    task.get('subject'),
                    task.get('description'),
                    teammateName,
                    teamName,
                    permissionMode,
                    toolUseContext.get('abortController', {}).get('signal'),
                    None,
                    toolUseContext,
                )
                
                async for result in taskCompletedGenerator:
                    if result.get('message'):
                        message = result['message']
                        if (message.get('type') == 'progress'
                            and message.get('toolUseID')):
                            teammateHookToolUseID = message['toolUseID']
                        yield message
                    
                    if result.get('blockingError'):
                        userMessage = createUserMessage(
                            content=getTaskCompletedHookMessage(result['blockingError']),
                            isMeta=True,
                        )
                        teammateBlockingErrors.append(userMessage)
                        yield userMessage
                    
                    if result.get('preventContinuation'):
                        teammatePreventedContinuation = True
                        teammateStopReason = (
                            result.get('stopReason')
                            or 'TaskCompleted hook prevented continuation'
                        )
                        yield createAttachmentMessage({
                            'type': 'hook_stopped_continuation',
                            'message': teammateStopReason,
                            'hookName': 'TaskCompleted',
                            'toolUseID': teammateHookToolUseID,
                            'hookEvent': 'TaskCompleted',
                        })
                    
                    if toolUseContext.get('abortController', {}).get('signal', {}).get('aborted'):
                        return
            
            # Run TeammateIdle hooks
            teammateIdleGenerator = executeTeammateIdleHooks(
                teammateName,
                teamName,
                permissionMode,
                toolUseContext.get('abortController', {}).get('signal'),
            )
            
            async for result in teammateIdleGenerator:
                if result.get('message'):
                    message = result['message']
                    if (message.get('type') == 'progress'
                        and message.get('toolUseID')):
                        teammateHookToolUseID = message['toolUseID']
                    yield message
                
                if result.get('blockingError'):
                    userMessage = createUserMessage(
                        content=getTeammateIdleHookMessage(result['blockingError']),
                        isMeta=True,
                    )
                    teammateBlockingErrors.append(userMessage)
                    yield userMessage
                
                if result.get('preventContinuation'):
                    teammatePreventedContinuation = True
                    teammateStopReason = (
                        result.get('stopReason')
                        or 'TeammateIdle hook prevented continuation'
                    )
                    yield createAttachmentMessage({
                        'type': 'hook_stopped_continuation',
                        'message': teammateStopReason,
                        'hookName': 'TeammateIdle',
                        'toolUseID': teammateHookToolUseID,
                        'hookEvent': 'TeammateIdle',
                    })
                
                if toolUseContext.get('abortController', {}).get('signal', {}).get('aborted'):
                    return
            
            if teammatePreventedContinuation:
                return
            
            if teammateBlockingErrors:
                return
    
    except Exception as error:
        durationMs = (time.time() * 1000) - hookStartTime
        logEvent('tengu_stop_hook_error', {
            'duration': int(durationMs),
            'queryChainId': toolUseContext.get('queryTracking', {}).get('chainId', ''),
            'queryDepth': toolUseContext.get('queryTracking', {}).get('depth'),
        })
        
        # Yield system message for debugging (not visible to model)
        yield createSystemMessage(
            f'Stop hook failed: {errorMessage(error)}',
            'warning',
        )


# ============================================================
# Module Exports
# ============================================================

__all__ = [
    'StopHookInfo',
    'StopHookResult',
    'HookProgress',
    'handleStopHooks',
]
