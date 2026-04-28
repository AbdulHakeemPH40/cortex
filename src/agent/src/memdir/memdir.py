"""
memdir - Memory directory management.

Core memory system for managing persistent, file-based memories with support
for individual and team memory directories.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

# Defensive imports
try:
    from ..bootstrap.state import getKairosActive, getOriginalCwd
except ImportError:
    def getKairosActive():
        return False
    
    def getOriginalCwd():
        return os.getcwd()

try:
    from ..services.analytics.growthbook import getFeatureValue_CACHED_MAY_BE_STALE
except ImportError:
    def getFeatureValue_CACHED_MAY_BE_STALE(feature_name, default):
        return default

try:
    from ..services.analytics.index import logEvent
except ImportError:
    def logEvent(event_name, data=None):
        pass

try:
    from ..tools.GrepTool.prompt import GREP_TOOL_NAME
except ImportError:
    GREP_TOOL_NAME = 'Grep'

try:
    from ..tools.REPLTool.constants import isReplModeEnabled
except ImportError:
    def isReplModeEnabled():
        return False

try:
    from ..utils.debug import logForDebugging
except ImportError:
    def logForDebugging(msg, **kwargs):
        pass

try:
    from ..utils.embeddedTools import hasEmbeddedSearchTools
except ImportError:
    def hasEmbeddedSearchTools():
        return False

try:
    from ..utils.envUtils import isEnvTruthy
except ImportError:
    def isEnvTruthy(value):
        if value is None:
            return False
        return str(value).lower() in ('true', '1', 'yes')

try:
    from ..utils.format import formatFileSize
except ImportError:
    def formatFileSize(size_bytes):
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f'{size_bytes:.1f} {unit}'
            size_bytes /= 1024
        return f'{size_bytes:.1f} TB'

try:
    from ..utils.fsOperations import getFsImplementation
except ImportError:
    class MockFs:
        async def mkdir(self, path, parents=True):
            os.makedirs(path, exist_ok=parents)
        
        def readFileSync(self, path, encoding='utf-8'):
            with open(path, 'r', encoding=encoding) as f:
                return f.read()
        
        async def readdir(self, path):
            entries = []
            for item in os.listdir(path):
                full_path = os.path.join(path, item)
                is_file = os.path.isfile(full_path)
                entries.append(type('Dirent', (), {
                    'name': item,
                    'isFile': lambda: is_file,
                    'isDirectory': lambda: not is_file,
                })())
            return entries
    
    def getFsImplementation():
        return MockFs()

try:
    from ..utils.sessionStorage import getProjectDir
except ImportError:
    def getProjectDir(original_cwd):
        return original_cwd or os.getcwd()

try:
    from ..utils.settings.settings import getInitialSettings
except ImportError:
    def getInitialSettings():
        return type('Settings', (), {'autoMemoryEnabled': True})()

try:
    from .memoryTypes import (
        MEMORY_FRONTMATTER_EXAMPLE,
        TRUSTING_RECALL_SECTION,
        TYPES_SECTION_INDIVIDUAL,
        WHAT_NOT_TO_SAVE_SECTION,
        WHEN_TO_ACCESS_SECTION,
    )
except ImportError:
    MEMORY_FRONTMATTER_EXAMPLE = []
    TRUSTING_RECALL_SECTION = []
    TYPES_SECTION_INDIVIDUAL = []
    WHAT_NOT_TO_SAVE_SECTION = []
    WHEN_TO_ACCESS_SECTION = []

try:
    from .paths import getAutoMemPath, isAutoMemoryEnabled
except ImportError:
    def getAutoMemPath():
        return os.path.join(os.getcwd(), '.cortex', 'memory')
    
    def isAutoMemoryEnabled():
        return not isEnvTruthy(os.environ.get('CORTEX_DISABLE_AUTO_MEMORY'))


ENTRYPOINT_NAME = 'MEMORY.md'
MAX_ENTRYPOINT_LINES = 200
# ~125 chars/line at 200 lines. At p97 today; catches long-line indexes that
# slip past the line cap (p100 observed: 197KB under 200 lines).
MAX_ENTRYPOINT_BYTES = 25_000
AUTO_MEM_DISPLAY_NAME = 'auto memory'


async def load_memory_prompt() -> str:
    return ""


class EntrypointTruncation(TypedDict):
    """Truncation result for MEMORY.md content."""
    content: str
    lineCount: int
    byteCount: int
    wasLineTruncated: bool
    wasByteTruncated: bool


def truncateEntrypointContent(raw: str) -> EntrypointTruncation:
    """
    Truncate MEMORY.md content to the line AND byte caps, appending a warning
    that names which cap fired. Line-truncates first (natural boundary), then
    byte-truncates at the last newline before the cap so we don't cut mid-line.
    
    Shared by buildMemoryPrompt and cortexmd getMemoryFiles (previously
    duplicated the line-only logic).
    """
    trimmed = raw.strip()
    content_lines = trimmed.split('\n')
    line_count = len(content_lines)
    byte_count = len(trimmed)
    
    was_line_truncated = line_count > MAX_ENTRYPOINT_LINES
    # Check original byte count — long lines are the failure mode the byte cap
    # targets, so post-line-truncation size would understate the warning.
    was_byte_truncated = byte_count > MAX_ENTRYPOINT_BYTES
    
    if not was_line_truncated and not was_byte_truncated:
        return {
            'content': trimmed,
            'lineCount': line_count,
            'byteCount': byte_count,
            'wasLineTruncated': was_line_truncated,
            'wasByteTruncated': was_byte_truncated,
        }
    
    truncated = '\n'.join(content_lines[:MAX_ENTRYPOINT_LINES]) if was_line_truncated else trimmed
    
    if len(truncated) > MAX_ENTRYPOINT_BYTES:
        cut_at = truncated.rfind('\n', 0, MAX_ENTRYPOINT_BYTES)
        truncated = truncated[:cut_at] if cut_at > 0 else truncated[:MAX_ENTRYPOINT_BYTES]
    
    if was_byte_truncated and not was_line_truncated:
        reason = f'{formatFileSize(byte_count)} (limit: {formatFileSize(MAX_ENTRYPOINT_BYTES)}) — index entries are too long'
    elif was_line_truncated and not was_byte_truncated:
        reason = f'{line_count} lines (limit: {MAX_ENTRYPOINT_LINES})'
    else:
        reason = f'{line_count} lines and {formatFileSize(byte_count)}'
    
    return {
        'content': truncated + f'\n\n> WARNING: {ENTRYPOINT_NAME} is {reason}. Only part of it was loaded. Keep index entries to one line under ~200 chars; move detail into topic files.',
        'lineCount': line_count,
        'byteCount': byte_count,
        'wasLineTruncated': was_line_truncated,
        'wasByteTruncated': was_byte_truncated,
    }


def _load_rules_snapshot() -> List[str]:
    """
    Read project + global rules and format them for prompt inclusion.
    Rules must override memory when there is a conflict.
    """
    lines: List[str] = []
    try:
        from .paths import getGlobalRulesDir, getProjectRulesDir
        global_rules_dir = getGlobalRulesDir()
        project_rules_dir = getProjectRulesDir()
    except Exception:
        home = os.path.expanduser("~")
        global_rules_dir = os.path.join(home, ".cortex", "rules")
        project_rules_dir = os.path.join(getProjectDir(getOriginalCwd()), ".cortex", "rules")

    def collect_rule_files(base_dir: str) -> List[str]:
        if not os.path.isdir(base_dir):
            return []
        files: List[str] = []
        for root, _dirs, names in os.walk(base_dir):
            for name in names:
                lname = name.lower()
                if lname.endswith(".md") or lname.endswith(".txt"):
                    files.append(os.path.join(root, name))
        files.sort()
        return files[:25]

    def read_rules_block(scope_name: str, base_dir: str) -> List[str]:
        result: List[str] = []
        files = collect_rule_files(base_dir)
        if not files:
            return result
        result.extend([f"### {scope_name} Rules", f"Directory: `{base_dir}`", ""])
        for path in files:
            rel = os.path.relpath(path, base_dir).replace("\\", "/")
            try:
                text = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                continue
            if not text:
                continue
            clipped = text[:1200]
            if len(text) > len(clipped):
                clipped += "\n..."
            result.extend([f"#### {rel}", "```md", clipped, "```", ""])
        return result

    global_block = read_rules_block("Global", global_rules_dir)
    project_block = read_rules_block("Current Project", project_rules_dir)
    if not global_block and not project_block:
        return lines

    lines.extend([
        "## Rules (Higher Priority Than Memory)",
        "When rules and memory conflict, follow rules.",
        "Priority order: Current Project Rules > Global Rules > Memory.",
        "",
    ])
    lines.extend(project_block)
    lines.extend(global_block)
    return lines


DIR_EXISTS_GUIDANCE = 'This directory already exists — write to it directly with the Write tool (do not run mkdir or check for its existence).'
DIRS_EXIST_GUIDANCE = 'Both directories already exist — write to them directly with the Write tool (do not run mkdir or check for their existence).'


async def ensureMemoryDirExists(memory_dir: str) -> None:
    """
    Ensure a memory directory exists. Idempotent — called from loadMemoryPrompt
    (once per session via systemPromptSection cache) so the model can always
    write without checking existence first. FsOperations.mkdir is recursive
    by default and already swallows EEXIST, so the full parent chain
    (~/.cortex/projects/<slug>/memory/) is created in one call with no
    try/catch needed for the happy path.
    """
    fs = getFsImplementation()
    try:
        await fs.mkdir(memory_dir)
    except Exception as e:
        # fs.mkdir already handles EEXIST internally. Anything reaching here is
        # a real problem (EACCES/EPERM/EROFS) — log so --debug shows why. Prompt
        # building continues either way; the model's Write will surface the
        # real perm error (and FileWriteTool does its own mkdir of the parent).
        code = getattr(e, 'code', None)
        logForDebugging(
            f'ensureMemoryDirExists failed for {memory_dir}: {code or str(e)}',
            {'level': 'debug'},
        )


async def ensureRulesDirsExist() -> None:
    """
    Ensure global and project rules directories exist.
    Mirrors Qoder-style behavior: global rules always available; project rules
    created for the active project when memory prompt is loaded.
    """
    try:
        from .paths import getGlobalRulesDir, getProjectRulesDir
        global_dir = getGlobalRulesDir()
        project_dir = getProjectRulesDir()
    except Exception:
        home = os.path.expanduser("~")
        global_dir = os.path.join(home, ".cortex", "rules")
        project_dir = os.path.join(getProjectDir(getOriginalCwd()), ".cortex", "rules")

    fs = getFsImplementation()
    for d in (global_dir, project_dir):
        try:
            await fs.mkdir(d)
        except Exception as e:
            code = getattr(e, "code", None)
            logForDebugging(
                f"ensureRulesDirsExist failed for {d}: {code or str(e)}",
                {"level": "debug"},
            )


def logMemoryDirCounts(memory_dir: str, base_metadata: Dict) -> None:
    """
    Log memory directory file/subdir counts asynchronously.
    Fire-and-forget — doesn't block prompt building.
    """
    import asyncio
    
    async def count_files():
        fs = getFsImplementation()
        try:
            dirents = await fs.readdir(memory_dir)
            file_count = sum(1 for d in dirents if d.isFile())
            subdir_count = sum(1 for d in dirents if d.isDirectory())
            
            logEvent('tengu_memdir_loaded', {
                **base_metadata,
                'total_file_count': file_count,
                'total_subdir_count': subdir_count,
            })
        except Exception:
            # Directory unreadable — log without counts
            logEvent('tengu_memdir_loaded', base_metadata)
    
    asyncio.create_task(count_files())


def buildSearchingPastContextSection(auto_mem_dir: str) -> List[str]:
    """Build the "Searching past context" section if the feature gate is enabled."""
    if not getFeatureValue_CACHED_MAY_BE_STALE('tengu_coral_fern', False):
        return []
    
    project_dir = getProjectDir(getOriginalCwd())
    # Ant-native builds alias grep to embedded ugrep and remove the dedicated
    # Grep tool, so give the model a real shell invocation there.
    # In REPL mode, both Grep and Bash are hidden from direct use — the model
    # calls them from inside REPL scripts, so the grep shell form is what it
    # will write in the script anyway.
    embedded = hasEmbeddedSearchTools() or isReplModeEnabled()
    
    mem_search = (
        f'grep -rn "<search term>" {auto_mem_dir} --include="*.md"'
        if embedded
        else f'{GREP_TOOL_NAME} with pattern="<search term>" path="{auto_mem_dir}" glob="*.md"'
    )
    
    transcript_search = (
        f'grep -rn "<search term>" {project_dir}/ --include="*.jsonl"'
        if embedded
        else f'{GREP_TOOL_NAME} with pattern="<search term>" path="{project_dir}/" glob="*.jsonl"'
    )
    
    return [
        '## Searching past context',
        '',
        'When looking for past context:',
        '1. Search topic files in your memory directory:',
        '```',
        mem_search,
        '```',
        '2. Session transcript logs (last resort — large files, slow):',
        '```',
        transcript_search,
        '```',
        'Use narrow search terms (error messages, file paths, function names) rather than broad keywords.',
        '',
    ]


def buildMemoryLines(
    display_name: str,
    memory_dir: str,
    extra_guidelines: Optional[List[str]] = None,
    skip_index: bool = False,
) -> List[str]:
    """
    Build the typed-memory behavioral instructions (without MEMORY.md content).
    Constrains memories to a closed four-type taxonomy (user / feedback / project /
    reference) — content that is derivable from the current project state (code
    patterns, architecture, git history) is explicitly excluded.
    
    Individual-only variant: no `## Memory scope` section, no <scope> tags
    in type blocks, and team/private qualifiers stripped from examples.
    
    Used by both buildMemoryPrompt (agent memory, includes content) and
    loadMemoryPrompt (system prompt, content injected via user context instead).
    """
    how_to_save = (
        [
            '## How to save memories',
            '',
            'Write each memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:',
            '',
            *MEMORY_FRONTMATTER_EXAMPLE,
            '',
            '- Keep the name, description, and type fields in memory files up-to-date with the content',
            '- Organize memory semantically by topic, not chronologically',
            '- Update or remove memories that turn out to be wrong or outdated',
            '- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one.',
        ]
        if skip_index
        else [
            '## How to save memories',
            '',
            'Saving a memory is a two-step process:',
            '',
            '**Step 1** — write the memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:',
            '',
            *MEMORY_FRONTMATTER_EXAMPLE,
            '',
            f'**Step 2** — add a pointer to that file in `{ENTRYPOINT_NAME}`. `{ENTRYPOINT_NAME}` is an index, not a memory — each entry should be one line, under ~150 characters: `- [Title](file.md) — one-line hook`. It has no frontmatter. Never write memory content directly into `{ENTRYPOINT_NAME}`.',
            '',
            f'- `{ENTRYPOINT_NAME}` is always loaded into your conversation context — lines after {MAX_ENTRYPOINT_LINES} will be truncated, so keep the index concise',
            '- Keep the name, description, and type fields in memory files up-to-date with the content',
            '- Organize memory semantically by topic, not chronologically',
            '- Update or remove memories that turn out to be wrong or outdated',
            '- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one.',
        ]
    )
    
    rules_section = _load_rules_snapshot()
    lines = [
        f'# {display_name}',
        '',
        f'You have a persistent, file-based memory system at `{memory_dir}`. {DIR_EXISTS_GUIDANCE}',
        '',
        'Memory scope model:',
        '- Current Project memory is isolated to the active project.',
        '- Global memory applies to all projects.',
        '',
        *rules_section,
        '',
        "You should build up this memory system over time so that future conversations can have a complete picture of who the user is, how they'd like to collaborate with you, what behaviors to avoid or repeat, and the context behind the work the user gives you.",
        '',
        'If the user explicitly asks you to remember something, save it immediately as whichever type fits best. If they ask you to forget something, find and remove the relevant entry.',
        '',
        *TYPES_SECTION_INDIVIDUAL,
        *WHAT_NOT_TO_SAVE_SECTION,
        '',
        *how_to_save,
        '',
        *WHEN_TO_ACCESS_SECTION,
        '',
        *TRUSTING_RECALL_SECTION,
        '',
        '## Memory and other forms of persistence',
        'Memory is one of several persistence mechanisms available to you as you assist the user in a given conversation. The distinction is often that memory can be recalled in future conversations and should not be used for persisting information that is only useful within the scope of the current conversation.',
        '- When to use or update a plan instead of memory: If you are about to start a non-trivial implementation task and would like to reach alignment with the user on your approach you should use a Plan rather than saving this information to memory. Similarly, if you already have a plan within the conversation and you have changed your approach persist that change by updating the plan rather than saving a memory.',
        '- When to use or update tasks instead of memory: When you need to break your work in current conversation into discrete steps or keep track of your progress use tasks instead of saving to memory. Tasks are great for persisting information about the work that needs to be done in the current conversation, but memory should be reserved for information that will be useful in future conversations.',
        '',
        *(extra_guidelines or []),
        '',
    ]
    
    lines.extend(buildSearchingPastContextSection(memory_dir))
    
    return lines


def buildMemoryPrompt(params: Dict) -> str:
    """
    Build the typed-memory prompt with MEMORY.md content included.
    Used by agent memory (which has no getCortexMds() equivalent).
    """
    display_name = params['displayName']
    memory_dir = params['memoryDir']
    extra_guidelines = params.get('extraGuidelines')
    
    fs = getFsImplementation()
    entrypoint = os.path.join(memory_dir, ENTRYPOINT_NAME)
    
    # Directory creation is the caller's responsibility (loadMemoryPrompt /
    # loadAgentMemoryPrompt). Builders only read, they don't mkdir.
    
    # Read existing memory entrypoint (sync: prompt building is synchronous)
    entrypoint_content = ''
    try:
        entrypoint_content = fs.readFileSync(entrypoint, {'encoding': 'utf-8'})
    except Exception:
        # No memory file yet
        pass
    
    lines = buildMemoryLines(display_name, memory_dir, extra_guidelines)
    
    if entrypoint_content.strip():
        t = truncateEntrypointContent(entrypoint_content)
        memory_type = 'auto' if display_name == AUTO_MEM_DISPLAY_NAME else 'agent'
        logMemoryDirCounts(memory_dir, {
            'content_length': t['byteCount'],
            'line_count': t['lineCount'],
            'was_truncated': t['wasLineTruncated'],
            'was_byte_truncated': t['wasByteTruncated'],
            'memory_type': memory_type,
        })
        lines.extend([f'## {ENTRYPOINT_NAME}', '', t['content']])
    else:
        lines.extend([
            f'## {ENTRYPOINT_NAME}',
            '',
            f'Your {ENTRYPOINT_NAME} is currently empty. When you save new memories, they will appear here.',
        ])
    
    return '\n'.join(lines)


def buildAssistantDailyLogPrompt(skip_index: bool = False) -> str:
    """
    Assistant-mode daily-log prompt. Gated behind feature('KAIROS').
    
    Assistant sessions are effectively perpetual, so the agent writes memories
    append-only to a date-named log file rather than maintaining MEMORY.md as
    a live index. A separate nightly /dream skill distills logs into topic
    files + MEMORY.md. MEMORY.md is still loaded into context (via cortexmd.ts)
    as the distilled index — this prompt only changes where NEW memories go.
    """
    memory_dir = getAutoMemPath()
    # Describe the path as a pattern rather than inlining today's literal path:
    # this prompt is cached by systemPromptSection('memory', ...) and NOT
    # invalidated on date change. The model derives the current date from the
    # date_change attachment (appended at the tail on midnight rollover) rather
    # than the user-context message — the latter is intentionally left stale to
    # preserve the prompt cache prefix across midnight.
    log_path_pattern = os.path.join(memory_dir, 'logs', 'YYYY', 'MM', 'YYYY-MM-DD.md')
    
    lines = [
        '# auto memory',
        '',
        f'You have a persistent, file-based memory system found at: `{memory_dir}`',
        '',
        "This session is long-lived. As you work, record anything worth remembering by **appending** to today's daily log file:",
        '',
        f'`{log_path_pattern}`',
        '',
        "Substitute today's date (from `currentDate` in your context) for `YYYY-MM-DD`. When the date rolls over mid-session, start appending to the new day's file.",
        '',
        'Write each entry as a short timestamped bullet. Create the file (and parent directories) on first write if it does not exist. Do not rewrite or reorganize the log — it is append-only. A separate nightly process distills these logs into `MEMORY.md` and topic files.',
        '',
        '## What to log',
        '- User corrections and preferences ("use bun, not npm"; "stop summarizing diffs")',
        '- Facts about the user, their role, or their goals',
        '- Project context that is not derivable from the code (deadlines, incidents, decisions and their rationale)',
        '- Pointers to external systems (dashboards, Linear projects, Slack channels)',
        '- Anything the user explicitly asks you to remember',
        '',
        *WHAT_NOT_TO_SAVE_SECTION,
        '',
    ]
    
    if not skip_index:
        lines.extend([
            f'## {ENTRYPOINT_NAME}',
            f'`{ENTRYPOINT_NAME}` is the distilled index (maintained nightly from your logs) and is loaded into your context automatically. Read it for orientation, but do not edit it directly — record new information in today\'s log instead.',
            '',
        ])
    
    lines.extend(buildSearchingPastContextSection(memory_dir))
    
    return '\n'.join(lines)


async def loadMemoryPrompt() -> Optional[str]:
    """
    Load the unified memory prompt for inclusion in the system prompt.
    Dispatches based on which memory systems are enabled:
      - auto + team: combined prompt (both directories)
      - auto only: memory lines (single directory)
    Team memory requires auto memory (enforced by isTeamMemoryEnabled), so
    there is no team-only branch.
    
    Returns None when auto memory is disabled.
    """
    auto_enabled = isAutoMemoryEnabled()

    skip_index = getFeatureValue_CACHED_MAY_BE_STALE('tengu_moth_copse', False)
    
    # KAIROS daily-log mode takes precedence over TEAMMEM: the append-only
    # log paradigm does not compose with team sync (which expects a shared
    # MEMORY.md that both sides read + write). Gating on `autoEnabled` here
    # means the !autoEnabled case falls through to the tengu_memdir_disabled
    # telemetry block below, matching the non-KAIROS path.
    kairos_enabled = os.environ.get('KAIROS', '').lower() in ('true', '1', 'yes')
    if kairos_enabled and auto_enabled and getKairosActive():
        await ensureRulesDirsExist()
        logMemoryDirCounts(getAutoMemPath(), {
            'memory_type': 'auto',
        })
        return buildAssistantDailyLogPrompt(skip_index)
    
    # Cowork injects memory-policy text via env var; thread into all builders.
    cowork_extra_guidelines = (
        os.environ.get('CORTEX_MEMORY_EXTRA_GUIDELINES')
        or os.environ.get('CORTEX_COWORK_MEMORY_EXTRA_GUIDELINES')
    )
    extra_guidelines = (
        [cowork_extra_guidelines]
        if cowork_extra_guidelines and cowork_extra_guidelines.strip()
        else None
    )
    
    team_mem_enabled = os.environ.get('TEAMMEM', '').lower() in ('true', '1', 'yes')
    if team_mem_enabled:
        try:
            from .teamMemPaths import isTeamMemoryEnabled, getTeamMemPath
            from .teamMemPrompts import buildCombinedMemoryPrompt

            if isTeamMemoryEnabled():
                await ensureRulesDirsExist()
                auto_dir = getAutoMemPath()
                team_dir = getTeamMemPath()
                # Harness guarantees these directories exist so the model can write
                # without checking. The prompt text reflects this ("already exists").
                # Only creating teamDir is sufficient: getTeamMemPath() is defined as
                # join(getAutoMemPath(), 'team'), so recursive mkdir of the team dir
                # creates the auto dir as a side effect. If the team dir ever moves
                # out from under the auto dir, add a second ensureMemoryDirExists call
                # for autoDir here.
                await ensureMemoryDirExists(team_dir)
                logMemoryDirCounts(auto_dir, {
                    'memory_type': 'auto',
                })
                logMemoryDirCounts(team_dir, {
                    'memory_type': 'team',
                })
                return buildCombinedMemoryPrompt(extra_guidelines, skip_index)
        except ImportError:
            pass
    
    if auto_enabled:
        await ensureRulesDirsExist()
        auto_dir = getAutoMemPath()
        # Harness guarantees the directory exists so the model can write without
        # checking. The prompt text reflects this ("already exists").
        await ensureMemoryDirExists(auto_dir)
        logMemoryDirCounts(auto_dir, {
            'memory_type': 'auto',
        })
        return '\n'.join(buildMemoryLines('auto memory', auto_dir, extra_guidelines, skip_index))
    
    settings_obj = getInitialSettings()
    if isinstance(settings_obj, dict):
        settings_enabled = settings_obj.get('autoMemoryEnabled')
    else:
        settings_enabled = getattr(settings_obj, 'autoMemoryEnabled', None)
    disabled_env = (
        isEnvTruthy(os.environ.get('CORTEX_DISABLE_AUTO_MEMORY'))
        or isEnvTruthy(os.environ.get('CORTEX_CODE_DISABLE_AUTO_MEMORY'))
    )
    logEvent('tengu_memdir_disabled', {
        'disabled_by_env_var': disabled_env,
        'disabled_by_setting': (not disabled_env and settings_enabled is False),
    })
    # Gate on the GB flag directly, not isTeamMemoryEnabled() — that function
    # checks isAutoMemoryEnabled() first, which is definitionally false in this
    # branch. We want "was this user in the team-memory cohort at all."
    if getFeatureValue_CACHED_MAY_BE_STALE('tengu_herring_clock', False):
        logEvent('tengu_team_memdir_disabled', {})
    
    return None
