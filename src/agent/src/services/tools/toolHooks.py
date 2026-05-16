"""
Tool Lifecycle Hooks - Handles pre/post tool execution hooks and permission decisions.
TypeScript source: services/tools/toolHooks.ts (651 lines)
Manages tool execution lifecycle with permission checks, error handling, and analytics.
"""

import time
from typing import Optional, Dict, Any, List, TypedDict, Union, AsyncGenerator
from dataclasses import dataclass

# ============================================================
# PHASE 1: Imports & Type Definitions
# ============================================================

try:
    from services.analytics.index import logEvent
except ImportError:
    def logEvent(event: str, data: Dict[str, Any]) -> None:
        """Stub - logs event"""
        pass

try:
    from services.analytics.metadata import sanitizeToolNameForAnalytics
except ImportError:
    def sanitizeToolNameForAnalytics(name: str) -> str:
        """Stub - sanitizes tool name"""
        return name

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

# logError disabled - using stub
def logError(error: Exception) -> None:
    """Stub - logs error"""
    pass

try:
    from utils.hooks import (
        executePostToolHooks,
        executePostToolUseFailureHooks,
        executePreToolHooks,
        getPreToolHookBlockingMessage,
    )
except ImportError:
    async def executePostToolHooks(*args, **kwargs):
        """Stub - executes post tool hooks"""
        return
        yield  # Make it an async generator
    
    async def executePostToolUseFailureHooks(*args, **kwargs):
        """Stub - executes post tool failure hooks"""
        return
        yield
    
    async def executePreToolHooks(*args, **kwargs):
        """Stub - executes pre tool hooks"""
        return
        yield
    
    def getPreToolHookBlockingMessage(hookName: str, error: str) -> str:
        return f'{hookName} failed: {error}'

try:
    from utils.permissions.PermissionResult import (
        getRuleBehaviorDescription,
        PermissionResult,
    )
except ImportError:
    def getRuleBehaviorDescription(behavior: str) -> str:
        """Stub - describes rule behavior"""
        return behavior
    
    PermissionResult = Dict[str, Any]

try:
    from utils.permissions.permissions import checkRuleBasedPermissions
except ImportError:
    async def checkRuleBasedPermissions(tool, input, context) -> Optional[Dict[str, Any]]:
        """Stub - checks rule based permissions"""
        return None

try:
    from utils.toolErrors import formatError
except ImportError:
    def formatError(error: Exception) -> str:
        """Stub - formats error"""
        return str(error)

try:
    from services.mcp.utils import isMcpTool
except ImportError:
    def isMcpTool(tool) -> bool:
        """Stub - checks if MCP tool"""
        return tool.get('isMcp', False)


# ============================================================
# Type Definitions
# ============================================================

class HookProgress(TypedDict, total=False):
    """Progress data from hook execution"""
    command: Optional[str]
    promptText: Optional[str]


class AttachmentMessage(TypedDict):
    """Message with attachment"""
    type: str
    attachment: Dict[str, Any]


class ProgressMessage(TypedDict):
    """Progress message from hook"""
    type: str
    data: HookProgress
    toolUseID: str


class MessageUpdateLazy(TypedDict):
    """Lazy message update"""
    message: Union[AttachmentMessage, ProgressMessage]


class PostToolUseHooksResult(TypedDict, total=False):
    """Result from post-tool-use hooks"""
    message: Optional[MessageUpdateLazy]
    updatedMCPToolOutput: Optional[Any]


# ============================================================
# PHASE 2: Post-Tool-Use Hooks
# ============================================================

async def runPostToolUseHooks(
    toolUseContext: Any,
    tool: Dict[str, Any],
    toolUseID: str,
    messageId: str,
    toolInput: Dict[str, Any],
    toolResponse: Any,
    requestId: Optional[str],
    mcpServerType: Optional[str],
    mcpServerBaseUrl: Optional[str],
) -> AsyncGenerator[PostToolUseHooksResult, None]:
    """
    Run post-tool-use hooks after tool execution completes.
    
    Handles:
    - Hook execution and message/attachment generation
    - Blocking error detection
    - Hook cancellation (abort signal)
    - Updated MCP tool output
    - Error tracking with analytics
    
    TS lines 39-191 (~153 lines - full implementation)
    """
    postToolStartTime = time.time() * 1000  # milliseconds
    
    try:
        get_app_state = getattr(toolUseContext, 'get_app_state', None) or toolUseContext.get('getAppState', lambda: {})
        appState = get_app_state() if callable(get_app_state) else {}
        tool_perm_ctx = appState.get('toolPermissionContext', {}) if isinstance(appState, dict) else getattr(appState, 'toolPermissionContext', {})
        permissionMode = tool_perm_ctx.get('mode') if isinstance(tool_perm_ctx, dict) else getattr(tool_perm_ctx, 'mode', None)
        
        toolOutput = toolResponse
        
        # Get abort signal - handle both dict and object style contexts
        abort_ctrl = getattr(toolUseContext, 'abort_controller', None) or toolUseContext.get('abortController', {})
        abort_signal = getattr(abort_ctrl, 'signal', None) or abort_ctrl.get('signal') if isinstance(abort_ctrl, dict) else None
        
        async for result in executePostToolHooks(
            tool.get('name', ''),
            toolUseID,
            toolInput,
            toolOutput,
            toolUseContext,
            permissionMode,
            abort_signal,
        ):
            try:
                # Check if aborted during hook execution
                if (
                    result.get('message', {}).get('type') == 'attachment'
                    and result.get('message', {}).get('attachment', {}).get('type') == 'hook_cancelled'
                ):
                    logEvent('tengu_post_tool_hooks_cancelled', {
                        'toolName': sanitizeToolNameForAnalytics(tool.get('name', '')),
                        'queryChainId': toolUseContext.get('queryTracking', {}).get('chainId', ''),
                        'queryDepth': toolUseContext.get('queryTracking', {}).get('depth'),
                    })
                    yield {
                        'message': createAttachmentMessage({
                            'type': 'hook_cancelled',
                            'hookName': f"PostToolUse:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PostToolUse',
                        }),
                    }
                    continue
                
                # Skip hook_blocking_error in result.message
                # blockingError path below creates the same attachment (see #31301)
                if (
                    result.get('message')
                    and not (
                        result.get('message', {}).get('type') == 'attachment'
                        and result.get('message', {}).get('attachment', {}).get('type') == 'hook_blocking_error'
                    )
                ):
                    yield {'message': result.get('message')}
                
                if result.get('blockingError'):
                    yield {
                        'message': createAttachmentMessage({
                            'type': 'hook_blocking_error',
                            'hookName': f"PostToolUse:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PostToolUse',
                            'blockingError': result.get('blockingError'),
                        }),
                    }
                
                # Check if hook wants to prevent continuation
                if result.get('preventContinuation'):
                    yield {
                        'message': createAttachmentMessage({
                            'type': 'hook_stopped_continuation',
                            'message': result.get('stopReason', 'Execution stopped by PostToolUse hook'),
                            'hookName': f"PostToolUse:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PostToolUse',
                        }),
                    }
                    return
                
                # Additional contexts from hooks
                additional_contexts = result.get('additionalContexts')
                if additional_contexts and len(additional_contexts) > 0:
                    yield {
                        'message': createAttachmentMessage({
                            'type': 'hook_additional_context',
                            'content': result.get('additionalContexts'),
                            'hookName': f"PostToolUse:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PostToolUse',
                        }),
                    }
                
                # Updated MCP tool output
                if result.get('updatedMCPToolOutput') and isMcpTool(tool):
                    toolOutput = result.get('updatedMCPToolOutput')
                    yield {
                        'updatedMCPToolOutput': toolOutput,
                    }
            except Exception as error:
                postToolDurationMs = time.time() * 1000 - postToolStartTime
                logEvent('tengu_post_tool_hook_error', {
                    'messageID': messageId,
                    'toolName': sanitizeToolNameForAnalytics(tool.get('name', '')),
                    'isMcp': tool.get('isMcp', False),
                    'duration': int(postToolDurationMs),
                    'queryChainId': toolUseContext.get('queryTracking', {}).get('chainId', ''),
                    'queryDepth': toolUseContext.get('queryTracking', {}).get('depth'),
                    **({'mcpServerType': mcpServerType} if mcpServerType else {}),
                    **({'requestId': requestId} if requestId else {}),
                })
                yield {
                    'message': createAttachmentMessage({
                        'type': 'hook_error_during_execution',
                        'content': formatError(error),
                        'hookName': f"PostToolUse:{tool.get('name', '')}",
                        'toolUseID': toolUseID,
                        'hookEvent': 'PostToolUse',
                    }),
                }
    except Exception as error:
        logError(error)


# ============================================================
# PHASE 3: Post-Tool-Use Failure Hooks
# ============================================================

async def runPostToolUseFailureHooks(
    toolUseContext: Any,
    tool: Dict[str, Any],
    toolUseID: str,
    messageId: str,
    processedInput: Dict[str, Any],
    error: str,
    isInterrupt: Optional[bool],
    requestId: Optional[str],
    mcpServerType: Optional[str],
    mcpServerBaseUrl: Optional[str],
) -> AsyncGenerator[MessageUpdateLazy, None]:
    """
    Run post-tool-use failure hooks after tool execution fails.
    
    Handles:
    - Failure hook execution and error reporting
    - Hook cancellation (abort signal)
    - Blocking error detection
    - Additional context generation
    
    TS lines 193-319 (~127 lines - full implementation)
    """
    postToolStartTime = time.time() * 1000  # milliseconds
    
    try:
        get_app_state = getattr(toolUseContext, 'get_app_state', None) or toolUseContext.get('getAppState', lambda: {})
        appState = get_app_state() if callable(get_app_state) else {}
        tool_perm_ctx = appState.get('toolPermissionContext', {}) if isinstance(appState, dict) else getattr(appState, 'toolPermissionContext', {})
        permissionMode = tool_perm_ctx.get('mode') if isinstance(tool_perm_ctx, dict) else getattr(tool_perm_ctx, 'mode', None)
        
        # Get abort signal - handle both dict and object style contexts
        abort_ctrl = getattr(toolUseContext, 'abort_controller', None) or toolUseContext.get('abortController', {})
        abort_signal = getattr(abort_ctrl, 'signal', None) or abort_ctrl.get('signal') if isinstance(abort_ctrl, dict) else None
        
        async for result in executePostToolUseFailureHooks(
            tool.get('name', ''),
            toolUseID,
            processedInput,
            error,
            toolUseContext,
            isInterrupt,
            permissionMode,
            abort_signal,
        ):
            try:
                # Check if aborted during hook execution
                if (
                    result.get('message', {}).get('type') == 'attachment'
                    and result.get('message', {}).get('attachment', {}).get('type') == 'hook_cancelled'
                ):
                    logEvent('tengu_post_tool_failure_hooks_cancelled', {
                        'toolName': sanitizeToolNameForAnalytics(tool.get('name', '')),
                        'queryChainId': toolUseContext.get('queryTracking', {}).get('chainId', ''),
                        'queryDepth': toolUseContext.get('queryTracking', {}).get('depth'),
                    })
                    yield {
                        'message': createAttachmentMessage({
                            'type': 'hook_cancelled',
                            'hookName': f"PostToolUseFailure:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PostToolUseFailure',
                        }),
                    }
                    continue
                
                # Skip hook_blocking_error in result.message
                # blockingError path below creates the same attachment (see #31301)
                if (
                    result.get('message')
                    and not (
                        result.get('message', {}).get('type') == 'attachment'
                        and result.get('message', {}).get('attachment', {}).get('type') == 'hook_blocking_error'
                    )
                ):
                    yield {'message': result.get('message')}
                
                if result.get('blockingError'):
                    yield {
                        'message': createAttachmentMessage({
                            'type': 'hook_blocking_error',
                            'hookName': f"PostToolUseFailure:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PostToolUseFailure',
                            'blockingError': result.get('blockingError'),
                        }),
                    }
                
                # Additional contexts from hooks
                additional_contexts = result.get('additionalContexts')
                if additional_contexts and len(additional_contexts) > 0:
                    yield {
                        'message': createAttachmentMessage({
                            'type': 'hook_additional_context',
                            'content': result.get('additionalContexts'),
                            'hookName': f"PostToolUseFailure:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PostToolUseFailure',
                        }),
                    }
            except Exception as hookError:
                postToolDurationMs = time.time() * 1000 - postToolStartTime
                logEvent('tengu_post_tool_failure_hook_error', {
                    'messageID': messageId,
                    'toolName': sanitizeToolNameForAnalytics(tool.get('name', '')),
                    'isMcp': tool.get('isMcp', False),
                    'duration': int(postToolDurationMs),
                    'queryChainId': toolUseContext.get('queryTracking', {}).get('chainId', ''),
                    'queryDepth': toolUseContext.get('queryTracking', {}).get('depth'),
                    **({'mcpServerType': mcpServerType} if mcpServerType else {}),
                    **({'requestId': requestId} if requestId else {}),
                })
                yield {
                    'message': createAttachmentMessage({
                        'type': 'hook_error_during_execution',
                        'content': formatError(hookError),
                        'hookName': f"PostToolUseFailure:{tool.get('name', '')}",
                        'toolUseID': toolUseID,
                        'hookEvent': 'PostToolUseFailure',
                    }),
                }
    except Exception as outerError:
        logError(outerError)


# ============================================================
# PHASE 4: Hook Permission Decision Resolution
# ============================================================

async def resolveHookPermissionDecision(
    hookPermissionResult: Optional[Dict[str, Any]],
    tool: Dict[str, Any],
    input: Dict[str, Any],
    toolUseContext: Any,
    canUseTool: Any,  # CanUseToolFn
    assistantMessage: Dict[str, Any],
    toolUseID: str,
) -> Dict[str, Any]:
    """
    Resolve a PreToolUse hook's permission result into a final PermissionDecision.
    
    Encapsulates the invariant that hook 'allow' does NOT bypass settings.json
    deny/ask rules — checkRuleBasedPermissions still applies (inc-4788 analog).
    Also handles the requiresUserInteraction/requireCanUseTool guards and the
    'ask' forceDecision passthrough.
    
    TS lines 332-433 (~102 lines - full implementation)
    """
    requiresInteraction = tool.get('requiresUserInteraction', lambda: False)()
    requireCanUseTool = toolUseContext.get('requireCanUseTool')
    
    if hookPermissionResult and hookPermissionResult.get('behavior') == 'allow':
        hookInput = hookPermissionResult.get('updatedInput') or input
        
        # Hook provided updatedInput for interactive tool — the hook IS the
        # user interaction (e.g. headless wrapper that collected answers).
        # Treat as non-interactive for the rule-check path.
        interactionSatisfied = (
            requiresInteraction
            and hookPermissionResult.get('updatedInput') is not None
        )
        
        if (requiresInteraction and not interactionSatisfied) or requireCanUseTool:
            logForDebugging(
                f"Hook approved tool use for {tool.get('name', '')}, but canUseTool is required"
            )
            return {
                'decision': await canUseTool(
                    tool,
                    hookInput,
                    toolUseContext,
                    assistantMessage,
                    toolUseID,
                ),
                'input': hookInput,
            }
        
        # Hook allow skips interactive prompt, but deny/ask rules still apply.
        ruleCheck = await checkRuleBasedPermissions(
            tool,
            hookInput,
            toolUseContext,
        )
        
        if ruleCheck is None:
            logForDebugging(
                'Hook satisfied user interaction for {0} via updatedInput'.format(
                    tool.get('name', '')
                ) if interactionSatisfied else
                'Hook approved tool use for {0}, bypassing permission prompt'.format(
                    tool.get('name', '')
                )
            )
            return {'decision': hookPermissionResult, 'input': hookInput}
        
        if ruleCheck.get('behavior') == 'deny':
            logForDebugging(
                'Hook approved tool use for {0}, but deny rule overrides: {1}'.format(
                    tool.get('name', ''),
                    ruleCheck.get('message', ''),
                )
            )
            return {'decision': ruleCheck, 'input': hookInput}
        
        # ask rule — dialog required despite hook approval
        logForDebugging(
            f"Hook approved tool use for {tool.get('name', '')}, but ask rule requires prompt"
        )
        return {
            'decision': await canUseTool(
                tool,
                hookInput,
                toolUseContext,
                assistantMessage,
                toolUseID,
            ),
            'input': hookInput,
        }
    
    if hookPermissionResult and hookPermissionResult.get('behavior') == 'deny':
        logForDebugging(f"Hook denied tool use for {tool.get('name', '')}")
        return {'decision': hookPermissionResult, 'input': input}
    
    # No hook decision or 'ask' — normal permission flow
    forceDecision = None
    if hookPermissionResult and hookPermissionResult.get('behavior') == 'ask':
        forceDecision = hookPermissionResult
    
    askInput = (
        hookPermissionResult.get('updatedInput')
        if (hookPermissionResult and hookPermissionResult.get('behavior') == 'ask')
        else input
    )
    
    return {
        'decision': await canUseTool(
            tool,
            askInput,
            toolUseContext,
            assistantMessage,
            toolUseID,
            forceDecision,
        ),
        'input': askInput,
    }


# ============================================================
# PHASE 5: Pre-Tool-Use Hooks
# ============================================================

async def runPreToolUseHooks(
    toolUseContext: Any,
    tool: Dict[str, Any],
    processedInput: Dict[str, Any],
    toolUseID: str,
    messageId: str,
    requestId: Optional[str],
    mcpServerType: Optional[str],
    mcpServerBaseUrl: Optional[str],
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Run pre-tool-use hooks before tool execution.
    
    Handles:
    - Hook execution and message generation
    - Permission behavior (allow/deny/ask)
    - Updated input from hooks
    - Blocking error detection
    - Abort signal handling
    - Additional context generation
    
    Yields different result types based on hook outcomes:
    - 'message': Hook progress/info messages
    - 'hookPermissionResult': Permission decision from hook
    - 'hookUpdatedInput': Modified tool input
    - 'preventContinuation': Hook wants to stop execution
    - 'stopReason': Reason for stopping
    - 'additionalContext': Extra context from hooks
    - 'stop': Abort or error condition
    
    TS lines 435-650 (~216 lines - full implementation)
    """
    hookStartTime = time.time() * 1000  # milliseconds
    
    try:
        get_app_state = getattr(toolUseContext, 'get_app_state', None) or toolUseContext.get('getAppState', lambda: {})
        appState = get_app_state() if callable(get_app_state) else {}
        tool_perm_ctx = appState.get('toolPermissionContext', {}) if isinstance(appState, dict) else getattr(appState, 'toolPermissionContext', {})
        permissionMode = tool_perm_ctx.get('mode') if isinstance(tool_perm_ctx, dict) else getattr(tool_perm_ctx, 'mode', None)
        
        # Get abort controller and signal - handle both dict and object style contexts
        abort_ctrl = getattr(toolUseContext, 'abort_controller', None) or toolUseContext.get('abortController', {})
        abort_signal = None
        if abort_ctrl:
            abort_signal = getattr(abort_ctrl, 'signal', None) or (abort_ctrl.get('signal') if isinstance(abort_ctrl, dict) else None)
        
        # Get request prompt
        request_prompt = getattr(toolUseContext, 'request_prompt', None) or toolUseContext.get('requestPrompt')
        
        # Get tool use summary
        get_tool_use_summary = tool.get('getToolUseSummary')
        tool_use_summary = get_tool_use_summary(processedInput) if callable(get_tool_use_summary) else None
        
        async for result in executePreToolHooks(
            tool.get('name', ''),
            toolUseID,
            processedInput,
            toolUseContext,
            permissionMode,
            abort_signal,
            None,  # timeoutMs - use default
            request_prompt,
            tool_use_summary,
        ):
            try:
                if result.get('message'):
                    yield {'type': 'message', 'message': {'message': result.get('message')}}
                
                if result.get('blockingError'):
                    denialMessage = getPreToolHookBlockingMessage(
                        f"PreToolUse:{tool.get('name', '')}",
                        result.get('blockingError'),
                    )
                    yield {
                        'type': 'hookPermissionResult',
                        'hookPermissionResult': {
                            'behavior': 'deny',
                            'message': denialMessage,
                            'decisionReason': {
                                'type': 'hook',
                                'hookName': f"PreToolUse:{tool.get('name', '')}",
                                'reason': denialMessage,
                            },
                        },
                    }
                
                # Check if hook wants to prevent continuation
                if result.get('preventContinuation'):
                    yield {
                        'type': 'preventContinuation',
                        'shouldPreventContinuation': True,
                    }
                    if result.get('stopReason'):
                        yield {'type': 'stopReason', 'stopReason': result.get('stopReason')}
                
                # Check for hook-defined permission behavior
                if result.get('permissionBehavior') is not None:
                    logForDebugging(
                        f"Hook result has permissionBehavior={result.get('permissionBehavior')}"
                    )
                    decisionReason = {
                        'type': 'hook',
                        'hookName': f"PreToolUse:{tool.get('name', '')}",
                        'hookSource': result.get('hookSource'),
                        'reason': result.get('hookPermissionDecisionReason'),
                    }
                    
                    if result.get('permissionBehavior') == 'allow':
                        yield {
                            'type': 'hookPermissionResult',
                            'hookPermissionResult': {
                                'behavior': 'allow',
                                'updatedInput': result.get('updatedInput'),
                                'decisionReason': decisionReason,
                            },
                        }
                    elif result.get('permissionBehavior') == 'ask':
                        yield {
                            'type': 'hookPermissionResult',
                            'hookPermissionResult': {
                                'behavior': 'ask',
                                'updatedInput': result.get('updatedInput'),
                                'message': (
                                    result.get('hookPermissionDecisionReason')
                                    or f"Hook PreToolUse:{tool.get('name', '')} {getRuleBehaviorDescription(result.get('permissionBehavior', 'ask'))} this tool"
                                ),
                                'decisionReason': decisionReason,
                            },
                        }
                    else:
                        # deny - updatedInput is irrelevant since tool won't run
                        yield {
                            'type': 'hookPermissionResult',
                            'hookPermissionResult': {
                                'behavior': result.get('permissionBehavior'),
                                'message': (
                                    result.get('hookPermissionDecisionReason')
                                    or f"Hook PreToolUse:{tool.get('name', '')} {getRuleBehaviorDescription(result.get('permissionBehavior', 'deny'))} this tool"
                                ),
                                'decisionReason': decisionReason,
                            },
                        }
                
                # Yield updatedInput for passthrough case (no permission decision)
                # This allows hooks to modify input while letting normal permission flow continue
                if result.get('updatedInput') and result.get('permissionBehavior') is None:
                    yield {
                        'type': 'hookUpdatedInput',
                        'updatedInput': result.get('updatedInput'),
                    }
                
                # Additional contexts from hooks
                additional_contexts = result.get('additionalContexts')
                if additional_contexts and len(additional_contexts) > 0:
                    yield {
                        'type': 'additionalContext',
                        'message': {
                            'message': createAttachmentMessage({
                                'type': 'hook_additional_context',
                                'content': result.get('additionalContexts'),
                                'hookName': f"PreToolUse:{tool.get('name', '')}",
                                'toolUseID': toolUseID,
                                'hookEvent': 'PreToolUse',
                            }),
                        },
                    }
                
                # Check if aborted during hook execution
                is_aborted = False
                if abort_signal:
                    is_aborted = getattr(abort_signal, 'aborted', False) or abort_signal.get('aborted') if isinstance(abort_signal, dict) else False
                if is_aborted:
                    query_tracking = getattr(toolUseContext, 'query_tracking', None) or toolUseContext.get('queryTracking', {})
                    logEvent('tengu_pre_tool_hooks_cancelled', {
                        'toolName': sanitizeToolNameForAnalytics(tool.get('name', '')),
                        'queryChainId': query_tracking.get('chainId', '') if isinstance(query_tracking, dict) else getattr(query_tracking, 'chainId', ''),
                        'queryDepth': query_tracking.get('depth') if isinstance(query_tracking, dict) else getattr(query_tracking, 'depth', None),
                    })
                    yield {
                        'type': 'message',
                        'message': {
                            'message': createAttachmentMessage({
                                'type': 'hook_cancelled',
                                'hookName': f"PreToolUse:{tool.get('name', '')}",
                                'toolUseID': toolUseID,
                                'hookEvent': 'PreToolUse',
                            }),
                        },
                    }
                    yield {'type': 'stop'}
                    return
                
            except Exception as error:
                logError(error)
                durationMs = time.time() * 1000 - hookStartTime
                logEvent('tengu_pre_tool_hook_error', {
                    'messageID': messageId,
                    'toolName': sanitizeToolNameForAnalytics(tool.get('name', '')),
                    'isMcp': tool.get('isMcp', False),
                    'duration': int(durationMs),
                    'queryChainId': toolUseContext.get('queryTracking', {}).get('chainId', ''),
                    'queryDepth': toolUseContext.get('queryTracking', {}).get('depth'),
                    **({'mcpServerType': mcpServerType} if mcpServerType else {}),
                    **({'requestId': requestId} if requestId else {}),
                })
                yield {
                    'type': 'message',
                    'message': {
                        'message': createAttachmentMessage({
                            'type': 'hook_error_during_execution',
                            'content': formatError(error),
                            'hookName': f"PreToolUse:{tool.get('name', '')}",
                            'toolUseID': toolUseID,
                            'hookEvent': 'PreToolUse',
                        }),
                    },
                }
                yield {'type': 'stop'}
    except Exception as error:
        logError(error)
        yield {'type': 'stop'}
        return


# ============================================================
# Module Exports
# ============================================================

__all__ = [
    'HookProgress',
    'AttachmentMessage',
    'ProgressMessage',
    'MessageUpdateLazy',
    'PostToolUseHooksResult',
    'runPostToolUseHooks',
    'runPostToolUseFailureHooks',
    'resolveHookPermissionDecision',
    'runPreToolUseHooks',
]
