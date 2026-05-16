"""
EnterWorktreeTool - Create an isolated git worktree and switch into it.

Allows the AI agent to create a separate git worktree for isolated development,
keeping the main repository clean while working on features or experiments.
"""

import os
from typing import Any, Dict, Optional, TypedDict

# Defensive imports
try:
    from ...bootstrap.state import getSessionId, setOriginalCwd
except ImportError:
    def getSessionId():
        return 'session-123'
    
    def setOriginalCwd(cwd):
        pass

try:
    from ...constants.systemPromptSections import clearSystemPromptSections
except ImportError:
    def clearSystemPromptSections():
        pass

try:
    from ...services.analytics.index import logEvent
except ImportError:
    def logEvent(event_name, data=None):
        pass

try:
    from ...Tool import buildTool, ToolDef
except ImportError:
    def buildTool(**kwargs):
        return kwargs
    
    class ToolDef:
        pass

try:
    from ...utils.cortexmd import clearMemoryFileCaches
except ImportError:
    def clearMemoryFileCaches():
        pass

try:
    from ...utils.cwd import getCwd
except ImportError:
    def getCwd():
        return os.getcwd()

try:
    from ...utils.git import findCanonicalGitRoot
except ImportError:
    def findCanonicalGitRoot(cwd):
        return None

try:
    from ...utils.plans import getPlanSlug, getPlansDirectory
except ImportError:
    def getPlanSlug():
        import random
        import string
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    def getPlansDirectory():
        return './plans'
    
    # Add cache attribute for compatibility
    if not hasattr(getPlansDirectory, 'cache'):
        getPlansDirectory.cache = type('Cache', (), {'clear': lambda: None})()

try:
    from ...utils.Shell import setCwd
except ImportError:
    def setCwd(cwd):
        os.chdir(cwd)

try:
    from ...utils.sessionStorage import saveWorktreeState
except ImportError:
    def saveWorktreeState(state):
        pass

try:
    from ...utils.worktree import createWorktreeForSession, getCurrentWorktreeSession, validateWorktreeSlug
except ImportError:
    async def createWorktreeForSession(session_id, slug):
        return type('WorktreeSession', (), {
            'worktreePath': f'/tmp/worktree-{slug}',
            'worktreeBranch': f'worktree/{slug}',
        })()
    
    def getCurrentWorktreeSession():
        return None
    
    def validateWorktreeSlug(slug):
        if len(slug) > 64:
            raise ValueError('Slug too long')
        import re
        segments = slug.split('/')
        for segment in segments:
            if not re.match(r'^[a-zA-Z0-9._-]+$', segment):
                raise ValueError(f'Invalid segment: {segment}')

try:
    from .constants import ENTER_WORKTREE_TOOL_NAME
except ImportError:
    ENTER_WORKTREE_TOOL_NAME = 'EnterWorktree'

try:
    from .prompt import getEnterWorktreeToolPrompt
except ImportError:
    def getEnterWorktreeToolPrompt():
        return 'Creates an isolated worktree (via git or configured hooks) and switches the session into it'

try:
    from .UI import renderToolResultMessage, renderToolUseMessage
except ImportError:
    def renderToolUseMessage(*args, **kwargs):
        return None
    
    def renderToolResultMessage(*args, **kwargs):
        return ''


class Input(TypedDict, total=False):
    """Input schema for EnterWorktreeTool."""
    name: Optional[str]


class Output(TypedDict):
    """Output schema for EnterWorktreeTool."""
    worktreePath: str
    worktreeBranch: Optional[str]
    message: str


async def call(input_data: Input, context) -> Dict[str, Any]:
    """Execute EnterWorktreeTool - create and switch to a worktree."""
    # Validate not already in a worktree created by this session
    if getCurrentWorktreeSession():
        raise Exception('Already in a worktree session')
    
    # Resolve to main repo root so worktree creation works from within a worktree
    main_repo_root = findCanonicalGitRoot(getCwd())
    if main_repo_root and main_repo_root != getCwd():
        os.chdir(main_repo_root)
        setCwd(main_repo_root)
    
    slug = input_data.get('name') or getPlanSlug()
    
    worktree_session = await createWorktreeForSession(getSessionId(), slug)
    
    os.chdir(worktree_session.worktreePath)
    setCwd(worktree_session.worktreePath)
    setOriginalCwd(getCwd())
    saveWorktreeState(worktree_session)
    
    # Clear cached system prompt sections so env_info_simple recomputes with worktree context
    clearSystemPromptSections()
    
    # Clear memoized caches that depend on CWD
    clearMemoryFileCaches()
    
    if hasattr(getPlansDirectory, 'cache') and hasattr(getPlansDirectory.cache, 'clear'):
        getPlansDirectory.cache.clear()
    
    logEvent('tengu_worktree_created', {
        'mid_session': True,
    })
    
    branch_info = f' on branch {worktree_session.worktreeBranch}' if worktree_session.worktreeBranch else ''
    
    return {
        'data': {
            'worktreePath': worktree_session.worktreePath,
            'worktreeBranch': worktree_session.worktreeBranch,
            'message': f'Created worktree at {worktree_session.worktreePath}{branch_info}. The session is now working in the worktree. Use ExitWorktree to leave mid-session, or exit the session to be prompted.',
        },
    }


def mapToolResultToToolResultBlockParam(content: Output, toolUseID: str) -> Dict[str, Any]:
    """Map tool output to Anthropic API tool result block."""
    return {
        'type': 'tool_result',
        'content': content['message'],
        'tool_use_id': toolUseID,
    }


def toAutoClassifierInput(input_data: Input) -> str:
    """Convert input to auto-classifier format."""
    return input_data.get('name') or ''


# Build the tool definition
EnterWorktreeTool = buildTool(
    name=ENTER_WORKTREE_TOOL_NAME,
    searchHint='create an isolated git worktree and switch into it',
    maxResultSizeChars=100_000,
    description=lambda: 'Creates an isolated worktree (via git or configured hooks) and switches the session into it',
    prompt=getEnterWorktreeToolPrompt,
    userFacingName=lambda: 'Creating worktree',
    shouldDefer=True,
    toAutoClassifierInput=toAutoClassifierInput,
    renderToolUseMessage=renderToolUseMessage,
    renderToolResultMessage=renderToolResultMessage,
    call=call,
    mapToolResultToToolResultBlockParam=mapToolResultToToolResultBlockParam,
)
