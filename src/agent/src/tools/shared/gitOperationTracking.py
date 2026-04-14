"""
Shell-agnostic git operation tracking for usage metrics.

Detects `git commit`, `git push`, `gh pr create`, `glab mr create`, and
curl-based PR creation in command strings, then increments OTLP counters
and fires analytics events. The regexes operate on raw command text so they
work identically for Bash and PowerShell (both invoke git/gh/glab/curl as
external binaries with the same argv syntax).
"""

import re
from typing import Optional, Dict, Any


# ============================================================================
# Helper Functions
# ============================================================================

def _git_cmd_re(subcmd: str, suffix: str = '') -> re.Pattern:
    """
    Build a regex that matches `git <subcmd>` while tolerating git's global
    options between `git` and the subcommand (e.g. `-c key=val`, `-C path`,
    `--git-dir=path`). Common when the model retries with
    `git -c commit.gpgsign=false commit` after a signing failure.
    """
    pattern = rf'\bgit(?:\s+-[cC]\s+\S+|\s+--\S+=\S+)*\s+{subcmd}\b{suffix}'
    return re.compile(pattern)


# Pre-compiled regex patterns for git operations
GIT_COMMIT_RE = _git_cmd_re('commit')
GIT_PUSH_RE = _git_cmd_re('push')
GIT_CHERRY_PICK_RE = _git_cmd_re('cherry-pick')
GIT_MERGE_RE = _git_cmd_re('merge', '(?!-)')
GIT_REBASE_RE = _git_cmd_re('rebase')


# ============================================================================
# Type Definitions
# ============================================================================

CommitKind = str  # 'committed' | 'amended' | 'cherry-picked'
BranchAction = str  # 'merged' | 'rebased'
PrAction = str  # 'created' | 'edited' | 'merged' | 'commented' | 'closed' | 'ready'


# ============================================================================
# GitHub PR Actions
# ============================================================================

GH_PR_ACTIONS = [
    {'re': re.compile(r'\bgh\s+pr\s+create\b'), 'action': 'created', 'op': 'pr_create'},
    {'re': re.compile(r'\bgh\s+pr\s+edit\b'), 'action': 'edited', 'op': 'pr_edit'},
    {'re': re.compile(r'\bgh\s+pr\s+merge\b'), 'action': 'merged', 'op': 'pr_merge'},
    {'re': re.compile(r'\bgh\s+pr\s+comment\b'), 'action': 'commented', 'op': 'pr_comment'},
    {'re': re.compile(r'\bgh\s+pr\s+close\b'), 'action': 'closed', 'op': 'pr_close'},
    {'re': re.compile(r'\bgh\s+pr\s+ready\b'), 'action': 'ready', 'op': 'pr_ready'},
]


# ============================================================================
# URL Parsing Functions
# ============================================================================

def _parse_pr_url(url: str) -> Optional[Dict[str, Any]]:
    """
    Parse PR info from a GitHub PR URL.
    Returns { prNumber, prUrl, prRepository } or None if not a valid PR URL.
    """
    match = re.match(r'https://github\.com/([^/]+/[^/]+)/pull/(\d+)', url)
    if match and match.group(1) and match.group(2):
        return {
            'prNumber': int(match.group(2)),
            'prUrl': url,
            'prRepository': match.group(1),
        }
    return None


def _find_pr_in_stdout(stdout: str) -> Optional[Dict[str, Any]]:
    """Find a GitHub PR URL embedded anywhere in stdout and parse it."""
    match = re.search(r'https://github\.com/[^/\s]+/[^/\s]+/pull/\d+', stdout)
    return _parse_pr_url(match.group(0)) if match else None


# ============================================================================
# Exported Helper Functions
# ============================================================================

def parse_git_commit_id(stdout: str) -> Optional[str]:
    """
    Parse git commit ID from stdout.
    git commit output: [branch abc1234] message
    or for root commit: [branch (root-commit) abc1234] message
    """
    match = re.search(r'\[[\w./-]+(?: \(root-commit\))? ([0-9a-f]+)\]', stdout)
    return match.group(1) if match else None


def _parse_git_push_branch(output: str) -> Optional[str]:
    """
    Parse branch name from git push output. Push writes progress to stderr but
    the ref update line ("abc..def  branch -> branch", "* [new branch]
    branch -> branch", or " + abc...def  branch -> branch (forced update)") is
    the signal. Works on either stdout or stderr. Git prefixes each ref line
    with a status flag (space, +, -, *, !, =); the char class tolerates any.
    """
    match = re.search(
        r'^\s*[+\-*!= ]?\s*(?:\[new branch\]|\S+\.\.+\S+)\s+\S+\s*->\s*(\S+)',
        output,
        re.MULTILINE
    )
    return match.group(1) if match else None


def _parse_pr_number_from_text(stdout: str) -> Optional[int]:
    """
    gh pr merge/close/ready print "✓ <Verb> pull request owner/repo#1234" with
    no URL. Extract the PR number from the text.
    """
    match = re.search(r'[Pp]ull request (?:\S+#)?#?(\d+)', stdout)
    return int(match.group(1)) if match and match.group(1) else None


def _parse_ref_from_command(command: str, verb: str) -> Optional[str]:
    """
    Extract target ref from `git merge <ref>` / `git rebase <ref>` command.
    Skips flags and keywords — first non-flag argument is the ref.
    """
    # Split on the git command pattern
    pattern = _git_cmd_re(verb)
    match = pattern.search(command)
    if not match:
        return None
    
    after = command[match.end():]
    if not after:
        return None
    
    for token in after.strip().split():
        if re.match(r'^[&|;><]', token):
            break
        if token.startswith('-'):
            continue
        return token
    
    return None


# ============================================================================
# Main Detection Function
# ============================================================================

def detect_git_operation(
    command: str,
    output: str,
) -> Dict[str, Any]:
    """
    Scan bash command + output for git operations worth surfacing in the
    collapsed tool-use summary ("committed a1b2c3, created PR #42, ran 3 bash
    commands"). Checks the command to avoid matching SHAs/URLs that merely
    appear in unrelated output (e.g. `git log`).

    Pass stdout+stderr concatenated — git push writes the ref update to stderr.
    """
    result: Dict[str, Any] = {}
    
    # commit and cherry-pick both produce "[branch sha] msg" output
    is_cherry_pick = bool(GIT_CHERRY_PICK_RE.search(command))
    
    if GIT_COMMIT_RE.search(command) or is_cherry_pick:
        sha = parse_git_commit_id(output)
        if sha:
            if is_cherry_pick:
                kind: CommitKind = 'cherry-picked'
            elif re.search(r'--amend\b', command):
                kind = 'amended'
            else:
                kind = 'committed'
            
            result['commit'] = {
                'sha': sha[:6],
                'kind': kind,
            }
    
    if GIT_PUSH_RE.search(command):
        branch = _parse_git_push_branch(output)
        if branch:
            result['push'] = {'branch': branch}
    
    if GIT_MERGE_RE.search(command) and re.search(r'(Fast-forward|Merge made by)', output):
        ref = _parse_ref_from_command(command, 'merge')
        if ref:
            result['branch'] = {'ref': ref, 'action': 'merged'}
    
    if GIT_REBASE_RE.search(command) and re.search(r'Successfully rebased', output):
        ref = _parse_ref_from_command(command, 'rebase')
        if ref:
            result['branch'] = {'ref': ref, 'action': 'rebased'}
    
    # Check for PR actions
    pr_action_entry = next((a for a in GH_PR_ACTIONS if a['re'].search(command)), None)
    if pr_action_entry:
        pr_action = pr_action_entry['action']
        pr = _find_pr_in_stdout(output)
        if pr:
            result['pr'] = {
                'number': pr['prNumber'],
                'url': pr['prUrl'],
                'action': pr_action,
            }
        else:
            num = _parse_pr_number_from_text(output)
            if num:
                result['pr'] = {'number': num, 'action': pr_action}
    
    return result


# ============================================================================
# Analytics Tracking Functions
# ============================================================================

def track_git_operations(
    command: str,
    exit_code: int,
    stdout: Optional[str] = None,
) -> None:
    """
    Track git operations for analytics.
    
    NOTE: This function has been simplified for Python conversion.
    The original TypeScript version imports analytics and state modules
    dynamically. In Python, you'll need to implement the actual tracking
    based on your analytics infrastructure.
    """
    success = exit_code == 0
    if not success:
        return
    
    # Track git commit
    if GIT_COMMIT_RE.search(command):
        # log_event('tengu_git_operation', {'operation': 'commit'})
        if re.search(r'--amend\b', command):
            # log_event('tengu_git_operation', {'operation': 'commit_amend'})
            pass
        # get_commit_counter()?.add(1)
        pass
    
    # Track git push
    if GIT_PUSH_RE.search(command):
        # log_event('tengu_git_operation', {'operation': 'push'})
        pass
    
    # Track PR actions
    pr_hit = next((a for a in GH_PR_ACTIONS if a['re'].search(command)), None)
    if pr_hit:
        # log_event('tengu_git_operation', {'operation': pr_hit['op']})
        pass
    
    # Track PR creation and link session
    if pr_hit and pr_hit['action'] == 'created':
        # get_pr_counter()?.add(1)
        
        # Auto-link session to PR if we can extract PR URL from stdout
        if stdout:
            pr_info = _find_pr_in_stdout(stdout)
            if pr_info:
                # Import is done dynamically to avoid circular dependency
                # In Python, implement this with lazy imports:
                # from utils.session_storage import link_session_to_pr
                # from bootstrap.state import get_session_id
                # 
                # session_id = get_session_id()
                # if session_id:
                #     link_session_to_pr(
                #         session_id,
                #         pr_info['prNumber'],
                #         pr_info['prUrl'],
                #         pr_info['prRepository'],
                #     )
                pass
    
    # Track GitLab MR creation
    if re.search(r'\bglab\s+mr\s+create\b', command):
        # log_event('tengu_git_operation', {'operation': 'pr_create'})
        # get_pr_counter()?.add(1)
        pass
    
    # Detect PR creation via curl to REST APIs (Bitbucket, GitHub API, GitLab API)
    # Check for POST method and PR endpoint separately to handle any argument order
    # Also detect implicit POST when -d is used (curl defaults to POST with data)
    is_curl_post = (
        re.search(r'\bcurl\b', command) and
        (re.search(r'-X\s*POST\b', command, re.IGNORECASE) or
         re.search(r'--request\s*=?\s*POST\b', command, re.IGNORECASE) or
         re.search(r'\s-d\s', command))
    )
    
    # Match PR endpoints in URLs, but not sub-resources like /pulls/123/comments
    # Require https?:// prefix to avoid matching text in POST body or other params
    is_pr_endpoint = re.search(
        r'https?://[^\s\'"]*/(pulls|pull-requests|merge[-_]requests)(?!/\d)',
        command,
        re.IGNORECASE
    )
    
    if is_curl_post and is_pr_endpoint:
        # log_event('tengu_git_operation', {'operation': 'pr_create'})
        # get_pr_counter()?.add(1)
        pass
