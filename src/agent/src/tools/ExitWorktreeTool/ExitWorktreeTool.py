"""
ExitWorktreeTool - Exit a worktree session and return to the original directory.

Allows the AI agent to exit a git worktree created by EnterWorktree, with options
to keep or remove the worktree from disk.
"""

import os
from typing import Any, Dict, Optional, TypedDict

# Defensive imports
try:
    from ...bootstrap.state import getOriginalCwd, getProjectRoot, setOriginalCwd, setProjectRoot
except ImportError:
    def getOriginalCwd():
        return os.getcwd()
    
    def getProjectRoot():
        return os.getcwd()
    
    def setOriginalCwd(cwd):
        pass
    
    def setProjectRoot(root):
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
    from ...utils.array import count
except ImportError:
    def count(iterable, predicate):
        return sum(1 for item in iterable if predicate(item))

try:
    from ...utils.cortexmd import clearMemoryFileCaches
except ImportError:
    def clearMemoryFileCaches():
        pass

try:
    from ...utils.execFileNoThrow import execFileNoThrow
except ImportError:
    async def execFileNoThrow(command, args):
        # Mock implementation
        return type('Result', (), {'code': 0, 'stdout': '', 'stderr': ''})()

try:
    from ...utils.hooks.hooksConfigSnapshot import updateHooksConfigSnapshot
except ImportError:
    def updateHooksConfigSnapshot():
        pass

try:
    from ...utils.plans import getPlansDirectory
except ImportError:
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
    from ...utils.worktree import cleanupWorktree, getCurrentWorktreeSession, keepWorktree, killTmuxSession
except ImportError:
    async def cleanupWorktree():
        pass
    
    def getCurrentWorktreeSession():
        return None
    
    async def keepWorktree():
        pass
    
    async def killTmuxSession(session_name):
        pass

try:
    from .constants import EXIT_WORKTREE_TOOL_NAME
except ImportError:
    EXIT_WORKTREE_TOOL_NAME = 'ExitWorktree'

try:
    from .prompt import getExitWorktreeToolPrompt
except ImportError:
    def getExitWorktreeToolPrompt():
        return 'Exits a worktree session created by EnterWorktree and restores the original working directory'

try:
    from .UI import renderToolResultMessage, renderToolUseMessage
except ImportError:
    def renderToolUseMessage(*args, **kwargs):
        return None
    
    def renderToolResultMessage(*args, **kwargs):
        return ''


class Input(TypedDict):
    """Input schema for ExitWorktreeTool."""
    action: str  # 'keep' or 'remove'
    discard_changes: Optional[bool]


class Output(TypedDict, total=False):
    """Output schema for ExitWorktreeTool."""
    action: str
    originalCwd: str
    worktreePath: str
    worktreeBranch: Optional[str]
    tmuxSessionName: Optional[str]
    discardedFiles: Optional[int]
    discardedCommits: Optional[int]
    message: str


class ChangeSummary:
    """Summary of worktree changes."""
    def __init__(self, changed_files: int, commits: int):
        self.changed_files = changed_files
        self.commits = commits


async def countWorktreeChanges(worktree_path: str, original_head_commit: Optional[str]) -> Optional[ChangeSummary]:
    """
    Returns None when state cannot be reliably determined — callers that use
    this as a safety gate must treat None as "unknown, assume unsafe"
    (fail-closed). A silent 0/0 would let cleanupWorktree destroy real work.
    
    None is returned when:
    - git status or rev-list exit non-zero (lock file, corrupt index, bad ref)
    - originalHeadCommit is undefined but git status succeeded — this is the
      hook-based-worktree-wrapping-git case (worktree.py:525-532 doesn't set
      originalHeadCommit). We can see the working tree is git, but cannot count
      commits without a baseline, so we cannot prove the branch is clean.
    """
    status = await execFileNoThrow('git', [
        '-C',
        worktree_path,
        'status',
        '--porcelain',
    ])
    
    if status.code != 0:
        return None
    
    changed_files = count(status.stdout.split('\n'), lambda l: l.strip() != '')
    
    if not original_head_commit:
        # git status succeeded → this is a git repo, but without a baseline
        # commit we cannot count commits. Fail-closed rather than claim 0.
        return None
    
    rev_list = await execFileNoThrow('git', [
        '-C',
        worktree_path,
        'rev-list',
        '--count',
        f'{original_head_commit}..HEAD',
    ])
    
    if rev_list.code != 0:
        return None
    
    commits = int(rev_list.stdout.strip()) if rev_list.stdout.strip().isdigit() else 0
    
    return ChangeSummary(changed_files, commits)


def restoreSessionToOriginalCwd(original_cwd: str, project_root_is_worktree: bool) -> None:
    """
    Restore session state to reflect the original directory.
    This is the inverse of the session-level mutations in EnterWorktreeTool.call().
    
    keepWorktree()/cleanupWorktree() handle process.chdir and currentWorktreeSession;
    this handles everything above the worktree utility layer.
    """
    setCwd(original_cwd)
    # EnterWorktree sets originalCwd to the *worktree* path (intentional — see
    # state.py getProjectRoot comment). Reset to the real original.
    setOriginalCwd(original_cwd)
    # --worktree startup sets projectRoot to the worktree; mid-session
    # EnterWorktreeTool does not. Only restore when it was actually changed —
    # otherwise we'd move projectRoot to wherever the user had cd'd before
    # entering the worktree (session.originalCwd), breaking the "stable project
    # identity" contract.
    if project_root_is_worktree:
        setProjectRoot(original_cwd)
        # setup.py's --worktree block called updateHooksConfigSnapshot() to re-read
        # hooks from the worktree. Restore symmetrically. (Mid-session
        # EnterWorktreeTool never touched the snapshot, so no-op there.)
        updateHooksConfigSnapshot()
    
    saveWorktreeState(None)
    clearSystemPromptSections()
    clearMemoryFileCaches()
    
    if hasattr(getPlansDirectory, 'cache') and hasattr(getPlansDirectory.cache, 'clear'):
        getPlansDirectory.cache.clear()


async def validateInput(input_data: Input, context) -> Dict[str, Any]:
    """Validate input before execution."""
    # Scope guard: getCurrentWorktreeSession() is None unless EnterWorktree
    # (specifically createWorktreeForSession) ran in THIS session. Worktrees
    # created by `git worktree add`, or by EnterWorktree in a previous
    # session, do not populate it. This is the sole entry gate — everything
    # past this point operates on a path EnterWorktree created.
    session = getCurrentWorktreeSession()
    if not session:
        return {
            'result': False,
            'message': 'No-op: there is no active EnterWorktree session to exit. This tool only operates on worktrees created by EnterWorktree in the current session — it will not touch worktrees created manually or in a previous session. No filesystem changes were made.',
            'errorCode': 1,
        }
    
    if input_data['action'] == 'remove' and not input_data.get('discard_changes'):
        summary = await countWorktreeChanges(
            session.worktreePath,
            getattr(session, 'originalHeadCommit', None),
        )
        
        if summary is None:
            return {
                'result': False,
                'message': f'Could not verify worktree state at {session.worktreePath}. Refusing to remove without explicit confirmation. Re-invoke with discard_changes: true to proceed — or use action: "keep" to preserve the worktree.',
                'errorCode': 3,
            }
        
        changed_files = summary.changed_files
        commits = summary.commits
        
        if changed_files > 0 or commits > 0:
            parts = []
            if changed_files > 0:
                parts.append(f'{changed_files} uncommitted {"file" if changed_files == 1 else "files"}')
            
            if commits > 0:
                parts.append(f'{commits} {"commit" if commits == 1 else "commits"} on {getattr(session, "worktreeBranch", None) or "the worktree branch"}')
            
            return {
                'result': False,
                'message': f'Worktree has {" and ".join(parts)}. Removing will discard this work permanently. Confirm with the user, then re-invoke with discard_changes: true — or use action: "keep" to preserve the worktree.',
                'errorCode': 2,
            }
    
    return {'result': True}


async def call(input_data: Input, context) -> Dict[str, Any]:
    """Execute ExitWorktreeTool - exit worktree and optionally remove it."""
    session = getCurrentWorktreeSession()
    if not session:
        # validateInput guards this, but the session is module-level mutable
        # state — defend against a race between validation and execution.
        raise Exception('Not in a worktree session')
    
    # Capture before keepWorktree/cleanupWorktree null out currentWorktreeSession.
    original_cwd = session.originalCwd
    worktree_path = session.worktreePath
    worktree_branch = getattr(session, 'worktreeBranch', None)
    tmux_session_name = getattr(session, 'tmuxSessionName', None)
    original_head_commit = getattr(session, 'originalHeadCommit', None)
    
    # --worktree startup calls setOriginalCwd(getCwd()) and
    # setProjectRoot(getCwd()) back-to-back right after setCwd(worktreePath)
    # (setup.py:235/239), so both hold the same realpath'd value and BashTool
    # cd never touches either. Mid-session EnterWorktreeTool sets originalCwd
    # but NOT projectRoot. (Can't use getCwd() — BashTool mutates it on every
    # cd. Can't use session.worktreePath — it's join()'d, not realpath'd.)
    project_root_is_worktree = getProjectRoot() == getOriginalCwd()
    
    # Re-count at execution time for accurate analytics and output — the
    # worktree state at validateInput time may not match now. None (git
    # failure) falls back to 0/0; safety gating already happened in
    # validateInput, so this only affects analytics + messaging.
    change_summary = await countWorktreeChanges(worktree_path, original_head_commit)
    changed_files = change_summary.changed_files if change_summary else 0
    commits = change_summary.commits if change_summary else 0
    
    if input_data['action'] == 'keep':
        await keepWorktree()
        restoreSessionToOriginalCwd(original_cwd, project_root_is_worktree)
        
        logEvent('tengu_worktree_kept', {
            'mid_session': True,
            'commits': commits,
            'changed_files': changed_files,
        })
        
        tmux_note = f' Tmux session {tmux_session_name} is still running; reattach with: tmux attach -t {tmux_session_name}' if tmux_session_name else ''
        
        branch_info = f' on branch {worktree_branch}' if worktree_branch else ''
        
        return {
            'data': {
                'action': 'keep',
                'originalCwd': original_cwd,
                'worktreePath': worktree_path,
                'worktreeBranch': worktree_branch,
                'tmuxSessionName': tmux_session_name,
                'message': f'Exited worktree. Your work is preserved at {worktree_path}{branch_info}. Session is now back in {original_cwd}.{tmux_note}',
            },
        }
    
    # action === 'remove'
    if tmux_session_name:
        await killTmuxSession(tmux_session_name)
    
    await cleanupWorktree()
    restoreSessionToOriginalCwd(original_cwd, project_root_is_worktree)
    
    logEvent('tengu_worktree_removed', {
        'mid_session': True,
        'commits': commits,
        'changed_files': changed_files,
    })
    
    discard_parts = []
    if commits > 0:
        discard_parts.append(f'{commits} {"commit" if commits == 1 else "commits"}')
    
    if changed_files > 0:
        discard_parts.append(f'{changed_files} uncommitted {"file" if changed_files == 1 else "files"}')
    
    discard_note = f' Discarded {" and ".join(discard_parts)}.' if len(discard_parts) > 0 else ''
    
    return {
        'data': {
            'action': 'remove',
            'originalCwd': original_cwd,
            'worktreePath': worktree_path,
            'worktreeBranch': worktree_branch,
            'discardedFiles': changed_files,
            'discardedCommits': commits,
            'message': f'Exited and removed worktree at {worktree_path}.{discard_note} Session is now back in {original_cwd}.',
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
    return input_data['action']


def isDestructive(input_data: Input) -> bool:
    """Check if the operation is destructive."""
    return input_data['action'] == 'remove'


# Build the tool definition
ExitWorktreeTool = buildTool(
    name=EXIT_WORKTREE_TOOL_NAME,
    searchHint='exit a worktree session and return to the original directory',
    maxResultSizeChars=100_000,
    description=lambda: 'Exits a worktree session created by EnterWorktree and restores the original working directory',
    prompt=getExitWorktreeToolPrompt,
    userFacingName=lambda: 'Exiting worktree',
    shouldDefer=True,
    isDestructive=isDestructive,
    toAutoClassifierInput=toAutoClassifierInput,
    validateInput=validateInput,
    renderToolUseMessage=renderToolUseMessage,
    renderToolResultMessage=renderToolResultMessage,
    call=call,
    mapToolResultToToolResultBlockParam=mapToolResultToToolResultBlockParam,
)
