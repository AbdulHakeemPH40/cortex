# ------------------------------------------------------------
# readOnlyValidation.py
# Python conversion of PowerShellTool/readOnlyValidation.ts
# 
# PowerShell read-only command validation.
# 
# Cmdlets are case-insensitive; all matching is done in lowercase.
# 
# Determines which PowerShell commands the AI agent can execute
# without prompting the user (auto-allow system).
# ------------------------------------------------------------

import re
from typing import Any, Callable, Dict, List, Optional, Set

# Import dependencies
try:
    from ...utils.platform import getPlatform
except ImportError:
    def getPlatform():
        import platform
        return 'windows' if platform.system() == 'Windows' else 'posix'

try:
    from ...utils.powershell.parser import (
        COMMON_ALIASES,
        deriveSecurityFlags,
        getPipelineSegments,
        isNullRedirectionTarget,
        isPowerShellParameter,
    )
except ImportError:
    COMMON_ALIASES = {}
    
    def deriveSecurityFlags(parsed: dict) -> dict:
        return {}
    
    def getPipelineSegments(parsed: dict) -> List[dict]:
        return []
    
    def isNullRedirectionTarget(target: str) -> bool:
        return False
    
    def isPowerShellParameter(arg: str, element_type: Optional[str] = None) -> bool:
        return arg.startswith('-')

try:
    from ...utils.shell.readOnlyCommandValidation import (
        DOCKER_READ_ONLY_COMMANDS,
        EXTERNAL_READONLY_COMMANDS,
        GH_READ_ONLY_COMMANDS,
        GIT_READ_ONLY_COMMANDS,
        validateFlags,
    )
except ImportError:
    DOCKER_READ_ONLY_COMMANDS = {}
    EXTERNAL_READONLY_COMMANDS = []
    GH_READ_ONLY_COMMANDS = {}
    GIT_READ_ONLY_COMMANDS = {}
    
    def validateFlags(*args, **kwargs) -> bool:
        return False

try:
    from .commonParameters import COMMON_PARAMETERS
except ImportError:
    COMMON_PARAMETERS = frozenset()

# Type aliases
CommandConfig = Dict[str, Any]

DOTNET_READ_ONLY_FLAGS: Set[str] = {
    '--version', '--info', '--list-runtimes', '--list-sdks',
}


# =========================================================================
# Phase 1: argLeaksValue + Start of CMDLET_ALLOWLIST
# =========================================================================


def argLeaksValue(
    _cmd: str,
    element: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Shared callback for cmdlets that print or coerce their args to stdout/
    stderr. `Write-Output $env:SECRET` prints it directly; `Start-Sleep
    $env:SECRET` leaks via type-coerce error.
    
    Two checks:
    1. elementTypes whitelist — StringConstant (literals) + Parameter (flag names)
    2. Colon-bound parameter value — `-InputObject:$env:SECRET`
    """
    arg_types = (element.get('elementTypes', []) if element else [])[1:]
    args = element.get('args', []) if element else []
    children = element.get('children') if element else None
    
    for i in range(len(arg_types)):
        if arg_types[i] not in ('StringConstant', 'Parameter'):
            # ArrayLiteralAst maps to 'Other' — fall back to string-archaeology
            if not re.search(r'[$(@{\[]', args[i] if i < len(args) else ''):
                continue
            return True
        
        if arg_types[i] == 'Parameter':
            param_children = children[i] if children and i < len(children) else None
            if param_children:
                if any(c.get('type') != 'StringConstant' for c in param_children):
                    return True
            else:
                # Fallback: string-archaeology on arg text
                arg = args[i] if i < len(args) else ''
                colon_idx = arg.find(':')
                if colon_idx > 0 and re.search(r'[$(@{\[]', arg[colon_idx + 1:]):
                    return True
    
    return False


# =========================================================================
# CMDLET_ALLOWLIST - Read-only PowerShell cmdlets
# =========================================================================
# Uses dict with no prototype to prevent prototype-chain pollution.
# Attacker-controlled command names like 'constructor' must return None.

CMDLET_ALLOWLIST: Dict[str, CommandConfig] = {}

# Filesystem (read-only)
CMDLET_ALLOWLIST['get-childitem'] = {
    'safeFlags': [
        '-Path', '-LiteralPath', '-Filter', '-Include', '-Exclude',
        '-Recurse', '-Depth', '-Name', '-Force', '-Attributes',
        '-Directory', '-File', '-Hidden', '-ReadOnly', '-System',
    ],
}

CMDLET_ALLOWLIST['get-content'] = {
    'safeFlags': [
        '-Path', '-LiteralPath', '-TotalCount', '-Head', '-Tail',
        '-Raw', '-Encoding', '-Delimiter', '-ReadCount',
    ],
}

CMDLET_ALLOWLIST['get-item'] = {
    'safeFlags': ['-Path', '-LiteralPath', '-Force', '-Stream'],
}

CMDLET_ALLOWLIST['get-itemproperty'] = {
    'safeFlags': ['-Path', '-LiteralPath', '-Name'],
}

CMDLET_ALLOWLIST['test-path'] = {
    'safeFlags': [
        '-Path', '-LiteralPath', '-PathType', '-Filter', '-Include',
        '-Exclude', '-IsValid', '-NewerThan', '-OlderThan',
    ],
}

CMDLET_ALLOWLIST['resolve-path'] = {
    'safeFlags': ['-Path', '-LiteralPath', '-Relative'],
}

CMDLET_ALLOWLIST['get-filehash'] = {
    'safeFlags': ['-Path', '-LiteralPath', '-Algorithm', '-InputStream'],
}

CMDLET_ALLOWLIST['get-acl'] = {
    'safeFlags': [
        '-Path', '-LiteralPath', '-Audit', '-Filter', '-Include', '-Exclude',
    ],
}

# Navigation (read-only, just changes working directory)
CMDLET_ALLOWLIST['set-location'] = {
    'safeFlags': ['-Path', '-LiteralPath', '-PassThru', '-StackName'],
}

CMDLET_ALLOWLIST['push-location'] = {
    'safeFlags': ['-Path', '-LiteralPath', '-PassThru', '-StackName'],
}

CMDLET_ALLOWLIST['pop-location'] = {
    'safeFlags': ['-PassThru', '-StackName'],
}

# Text searching/filtering (read-only)
CMDLET_ALLOWLIST['select-string'] = {
    'safeFlags': [
        '-Path', '-LiteralPath', '-Pattern', '-InputObject',
        '-SimpleMatch', '-CaseSensitive', '-Quiet', '-List',
        '-NotMatch', '-AllMatches', '-Encoding', '-Context',
        '-Raw', '-NoEmphasis',
    ],
}

# Data conversion (pure transforms, no side effects)
CMDLET_ALLOWLIST['convertto-json'] = {
    'safeFlags': [
        '-InputObject', '-Depth', '-Compress', '-EnumsAsStrings', '-AsArray',
    ],
}

CMDLET_ALLOWLIST['convertfrom-json'] = {
    'safeFlags': ['-InputObject', '-Depth', '-AsHashtable', '-NoEnumerate'],
}

CMDLET_ALLOWLIST['convertto-csv'] = {
    'safeFlags': [
        '-InputObject', '-Delimiter', '-NoTypeInformation',
        '-NoHeader', '-UseQuotes',
    ],
}

CMDLET_ALLOWLIST['convertfrom-csv'] = {
    'safeFlags': ['-InputObject', '-Delimiter', '-Header', '-UseCulture'],
}

CMDLET_ALLOWLIST['convertto-xml'] = {
    'safeFlags': ['-InputObject', '-Depth', '-As', '-NoTypeInformation'],
}

CMDLET_ALLOWLIST['convertto-html'] = {
    'safeFlags': [
        '-InputObject', '-Property', '-Head', '-Title', '-Body',
        '-Pre', '-Post', '-As', '-Fragment',
    ],
}

CMDLET_ALLOWLIST['format-hex'] = {
    'safeFlags': [
        '-Path', '-LiteralPath', '-InputObject', '-Encoding',
        '-Count', '-Offset',
    ],
}

# Object inspection and manipulation (read-only)
CMDLET_ALLOWLIST['get-member'] = {
    'safeFlags': [
        '-InputObject', '-MemberType', '-Name', '-Static', '-View', '-Force',
    ],
}

CMDLET_ALLOWLIST['get-unique'] = {
    'safeFlags': ['-InputObject', '-AsString', '-CaseInsensitive', '-OnType'],
}

CMDLET_ALLOWLIST['compare-object'] = {
    'safeFlags': [
        '-ReferenceObject', '-DifferenceObject', '-Property',
        '-SyncWindow', '-CaseSensitive', '-Culture', '-ExcludeDifferent',
        '-IncludeEqual', '-PassThru',
    ],
}

# SECURITY: select-xml REMOVED. XXE resolution can trigger network requests.

CMDLET_ALLOWLIST['join-string'] = {
    'safeFlags': [
        '-InputObject', '-Property', '-Separator', '-OutputPrefix',
        '-OutputSuffix', '-SingleQuote', '-DoubleQuote', '-FormatString',
    ],
}

# SECURITY: Test-Json REMOVED. $ref can point to external URLs.

CMDLET_ALLOWLIST['get-random'] = {
    'safeFlags': [
        '-InputObject', '-Minimum', '-Maximum', '-Count',
        '-SetSeed', '-Shuffle',
    ],
}

# Path utilities (read-only)
CMDLET_ALLOWLIST['convert-path'] = {
    'safeFlags': ['-Path', '-LiteralPath'],
}

CMDLET_ALLOWLIST['join-path'] = {
    # -Resolve removed: touches filesystem without path validation
    'safeFlags': ['-Path', '-ChildPath', '-AdditionalChildPath'],
}

CMDLET_ALLOWLIST['split-path'] = {
    # -Resolve removed: same rationale as join-path
    'safeFlags': [
        '-Path', '-LiteralPath', '-Qualifier', '-NoQualifier',
        '-Parent', '-Leaf', '-LeafBase', '-Extension', '-IsAbsolute',
    ],
}

# Additional system info (read-only)
# NOTE: Get-Clipboard intentionally NOT included - exposes sensitive data
CMDLET_ALLOWLIST['get-hotfix'] = {
    'safeFlags': ['-Id', '-Description'],
}

CMDLET_ALLOWLIST['get-itempropertyvalue'] = {
    'safeFlags': ['-Path', '-LiteralPath', '-Name'],
}

CMDLET_ALLOWLIST['get-psprovider'] = {
    'safeFlags': ['-PSProvider'],
}

# Process/System info
CMDLET_ALLOWLIST['get-process'] = {
    'safeFlags': [
        '-Name', '-Id', '-Module', '-FileVersionInfo', '-IncludeUserName',
    ],
}

CMDLET_ALLOWLIST['get-service'] = {
    'safeFlags': [
        '-Name', '-DisplayName', '-DependentServices', '-RequiredServices',
        '-Include', '-Exclude',
    ],
}

CMDLET_ALLOWLIST['get-computerinfo'] = {
    'allowAllFlags': True,
}

CMDLET_ALLOWLIST['get-host'] = {
    'allowAllFlags': True,
}

CMDLET_ALLOWLIST['get-date'] = {
    'safeFlags': ['-Date', '-Format', '-UFormat', '-DisplayHint', '-AsUTC'],
}

CMDLET_ALLOWLIST['get-location'] = {
    'safeFlags': ['-PSProvider', '-PSDrive', '-Stack', '-StackName'],
}

CMDLET_ALLOWLIST['get-psdrive'] = {
    'safeFlags': ['-Name', '-PSProvider', '-Scope'],
}

# SECURITY: Get-Command REMOVED from allowlist. Module autoload hazard.

CMDLET_ALLOWLIST['get-module'] = {
    'safeFlags': [
        '-Name', '-ListAvailable', '-All',
        '-FullyQualifiedName', '-PSEdition',
    ],
}

# SECURITY: Get-Help REMOVED from allowlist. Same module autoload hazard.

CMDLET_ALLOWLIST['get-alias'] = {
    'safeFlags': ['-Name', '-Definition', '-Scope', '-Exclude'],
}

CMDLET_ALLOWLIST['get-history'] = {
    'safeFlags': ['-Id', '-Count'],
}

CMDLET_ALLOWLIST['get-culture'] = {
    'allowAllFlags': True,
}

CMDLET_ALLOWLIST['get-uiculture'] = {
    'allowAllFlags': True,
}

CMDLET_ALLOWLIST['get-timezone'] = {
    'safeFlags': ['-Name', '-Id', '-ListAvailable'],
}

CMDLET_ALLOWLIST['get-uptime'] = {
    'allowAllFlags': True,
}

# Output & misc (no side effects)
CMDLET_ALLOWLIST['write-output'] = {
    'safeFlags': ['-InputObject', '-NoEnumerate'],
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['write-host'] = {
    'safeFlags': [
        '-Object', '-NoNewline', '-Separator', '-ForegroundColor',
        '-BackgroundColor',
    ],
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['start-sleep'] = {
    'safeFlags': ['-Seconds', '-Milliseconds', '-Duration'],
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

# Format-* and Measure-Object with allowAllFlags + argLeaksValue
CMDLET_ALLOWLIST['format-table'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['format-list'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['format-wide'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['format-custom'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['measure-object'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

# Select/Sort/Group/Where - same calculated-property hashtable surface
CMDLET_ALLOWLIST['select-object'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['sort-object'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['group-object'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['where-object'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

# Out-String/Out-Host moved from SAFE_OUTPUT_CMDLETS
CMDLET_ALLOWLIST['out-string'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

CMDLET_ALLOWLIST['out-host'] = {
    'allowAllFlags': True,
    'additionalCommandIsDangerousCallback': argLeaksValue,
}

# Network info (read-only)
CMDLET_ALLOWLIST['get-netadapter'] = {
    'safeFlags': [
        '-Name', '-InterfaceDescription', '-InterfaceIndex', '-Physical',
    ],
}

CMDLET_ALLOWLIST['get-netipaddress'] = {
    'safeFlags': [
        '-InterfaceIndex', '-InterfaceAlias', '-AddressFamily', '-Type',
    ],
}

CMDLET_ALLOWLIST['get-netipconfiguration'] = {
    'safeFlags': ['-InterfaceIndex', '-InterfaceAlias', '-Detailed', '-All'],
}

CMDLET_ALLOWLIST['get-netroute'] = {
    'safeFlags': [
        '-InterfaceIndex', '-InterfaceAlias', '-AddressFamily',
        '-DestinationPrefix',
    ],
}

# SECURITY: -CimSession/-ThrottleLimit excluded (network requests)
CMDLET_ALLOWLIST['get-dnsclientcache'] = {
    'safeFlags': ['-Entry', '-Name', '-Type', '-Status', '-Section', '-Data'],
}

CMDLET_ALLOWLIST['get-dnsclient'] = {
    'safeFlags': ['-InterfaceIndex', '-InterfaceAlias'],
}

# Event log (read-only)
CMDLET_ALLOWLIST['get-eventlog'] = {
    'safeFlags': [
        '-LogName', '-Newest', '-After', '-Before', '-EntryType',
        '-Index', '-InstanceId', '-Message', '-Source', '-UserName',
        '-AsBaseObject', '-List',
    ],
}

# SECURITY: -FilterXml/-FilterHashtable removed (XXE hazard)
CMDLET_ALLOWLIST['get-winevent'] = {
    'safeFlags': [
        '-LogName', '-ListLog', '-ListProvider', '-ProviderName',
        '-Path', '-MaxEvents', '-FilterXPath', '-Force', '-Oldest',
    ],
}

# WMI/CIM
# SECURITY: Get-WmiObject and Get-CimInstance REMOVED (network requests)
CMDLET_ALLOWLIST['get-cimclass'] = {
    'safeFlags': [
        '-ClassName', '-Namespace', '-MethodName',
        '-PropertyName', '-QualifierName',
    ],
}

# External commands (git, gh, docker) - use shared validation
CMDLET_ALLOWLIST['git'] = {}
CMDLET_ALLOWLIST['gh'] = {}
CMDLET_ALLOWLIST['docker'] = {}

# Windows-specific system commands
def _ipconfig_is_dangerous(_cmd: str, element: Optional[Dict[str, Any]] = None) -> bool:
    """Reject positional args - macOS ipconfig can set network config."""
    return any(
        not a.startswith('/') and not a.startswith('-')
        for a in (element.get('args', []) if element else [])
    )

CMDLET_ALLOWLIST['ipconfig'] = {
    'safeFlags': ['/all', '/displaydns', '/allcompartments'],
    'additionalCommandIsDangerousCallback': _ipconfig_is_dangerous,
}

CMDLET_ALLOWLIST['netstat'] = {
    'safeFlags': [
        '-a', '-b', '-e', '-f', '-n', '-o', '-p',
        '-q', '-r', '-s', '-t', '-x', '-y',
    ],
}

CMDLET_ALLOWLIST['systeminfo'] = {
    'safeFlags': ['/FO', '/NH'],
}

CMDLET_ALLOWLIST['tasklist'] = {
    'safeFlags': ['/M', '/SVC', '/V', '/FI', '/FO', '/NH'],
}

CMDLET_ALLOWLIST['where.exe'] = {
    'allowAllFlags': True,
}


def _hostname_is_dangerous(_cmd: str, element: Optional[Dict[str, Any]] = None) -> bool:
    """Reject positional args - sets hostname on Linux/macOS."""
    return any(
        not a.startswith('-')
        for a in (element.get('args', []) if element else [])
    )

CMDLET_ALLOWLIST['hostname'] = {
    'safeFlags': ['-a', '-d', '-f', '-i', '-I', '-s', '-y', '-A'],
    'additionalCommandIsDangerousCallback': _hostname_is_dangerous,
}

CMDLET_ALLOWLIST['whoami'] = {
    'safeFlags': [
        '/user', '/groups', '/claims', '/priv',
        '/logonid', '/all', '/fo', '/nh',
    ],
}

CMDLET_ALLOWLIST['ver'] = {
    'allowAllFlags': True,
}

CMDLET_ALLOWLIST['arp'] = {
    'safeFlags': ['-a', '-g', '-v', '-N'],
}


def _route_is_dangerous(_cmd: str, element: Optional[Dict[str, Any]] = None) -> bool:
    """
    Route.exe syntax: `route [-f] [-p] [-4|-6] VERB [args...]`.
    First non-flag positional is the verb. Only 'print' is read-only.
    """
    if not element:
        return True
    verb = next((a for a in element.get('args', []) if not a.startswith('-')), None)
    return (verb or '').lower() != 'print'

CMDLET_ALLOWLIST['route'] = {
    'safeFlags': ['print', 'PRINT', '-4', '-6'],
    'additionalCommandIsDangerousCallback': _route_is_dangerous,
}

# netsh: intentionally NOT allowlisted (grammar too complex)
CMDLET_ALLOWLIST['getmac'] = {
    'safeFlags': ['/FO', '/NH', '/V'],
}

# Cross-platform AI agent tools
# SECURITY: file -C compiles magic database (writes to disk) - excluded
CMDLET_ALLOWLIST['file'] = {
    'safeFlags': [
        '-b', '--brief', '-i', '--mime', '-L', '--dereference',
        '--mime-type', '--mime-encoding', '-z', '--uncompress',
        '-p', '--preserve-date', '-k', '--keep-going', '-r', '--raw',
        '-v', '--version', '-0', '--print0', '-s', '--special-files',
        '-l', '-F', '--separator', '-e', '-P', '-N', '--no-pad',
        '-E', '--extension',
    ],
}

CMDLET_ALLOWLIST['tree'] = {
    'safeFlags': ['/F', '/A', '/Q', '/L'],
}

CMDLET_ALLOWLIST['findstr'] = {
    'safeFlags': [
        '/B', '/E', '/L', '/R', '/S', '/I', '/X', '/V',
        '/N', '/M', '/O', '/P', '/C', '/G', '/D', '/A',
    ],
}

# Package managers - uses shared external command validation
CMDLET_ALLOWLIST['dotnet'] = {}

# SECURITY: man and help direct entries REMOVED (module autoload hazard)


# =========================================================================
# Constants and Sets
# =========================================================================

SAFE_OUTPUT_CMDLETS: Set[str] = {
    'out-null',
}

PIPELINE_TAIL_CMDLETS: Set[str] = {
    'format-table', 'format-list', 'format-wide', 'format-custom',
    'measure-object', 'select-object', 'sort-object', 'group-object',
    'where-object', 'out-string', 'out-host',
}

SAFE_EXTERNAL_EXES: Set[str] = {'where.exe'}

WINDOWS_PATHEXT = re.compile(r'\.(exe|cmd|bat|com)$')


# =========================================================================
# Helper Functions
# =========================================================================

def resolveToCanonical(name: str) -> str:
    """
    Resolves a command name to its canonical cmdlet name using COMMON_ALIASES.
    Strips Windows executable extensions from path-free names.
    """
    lower = name.lower()
    # Only strip PATHEXT on bare names
    if '\\' not in lower and '/' not in lower:
        lower = WINDOWS_PATHEXT.sub('', lower)
    
    alias = COMMON_ALIASES.get(lower)
    if alias:
        return alias.lower()
    return lower


def isCwdChangingCmdlet(name: str) -> bool:
    """
    Checks if a command alters the path-resolution namespace.
    Covers CWD-changing cmdlets and PSDrive-creating cmdlets.
    """
    canonical = resolveToCanonical(name)
    if canonical in ('set-location', 'push-location', 'pop-location', 'new-psdrive'):
        return True
    # ndr/mount are PS aliases for New-PSDrive on Windows only
    if getPlatform() == 'windows' and canonical in ('ndr', 'mount'):
        return True
    return False


def isSafeOutputCommand(name: str) -> bool:
    """Checks if a command name is a safe output cmdlet."""
    return resolveToCanonical(name) in SAFE_OUTPUT_CMDLETS


def isAllowlistedPipelineTail(
    cmd: Dict[str, Any],
    originalCommand: str,
) -> bool:
    """
    Checks if a command is a pipeline-tail transformer that passes argLeaksValue.
    """
    canonical = resolveToCanonical(cmd.get('name', ''))
    if canonical not in PIPELINE_TAIL_CMDLETS:
        return False
    return isAllowlistedCommand(cmd, originalCommand)


def isProvablySafeStatement(stmt: Dict[str, Any]) -> bool:
    """
    Fail-closed gate for read-only auto-allow.
    Returns true ONLY for PipelineAst where every element is CommandAst.
    """
    if stmt.get('statementType') != 'PipelineAst':
        return False
    if len(stmt.get('commands', [])) == 0:
        return False
    return all(
        cmd.get('elementType') == 'CommandAst'
        for cmd in stmt.get('commands', [])
    )


def lookupAllowlist(name: str) -> Optional[CommandConfig]:
    """Looks up a command in the allowlist, resolving aliases first."""
    lower = name.lower()
    # Direct lookup first
    direct = CMDLET_ALLOWLIST.get(lower)
    if direct:
        return direct
    # Resolve alias to canonical and look up
    canonical = resolveToCanonical(lower)
    if canonical != lower:
        return CMDLET_ALLOWLIST.get(canonical)
    return None


def hasSyncSecurityConcerns(command: str) -> bool:
    """
    Sync regex-based check for security-concerning patterns.
    Used as a fast pre-filter before the cmdlet allowlist check.
    """
    trimmed = command.strip()
    if not trimmed:
        return False
    
    # Subexpressions: $(...)
    if re.search(r'\$\(', trimmed):
        return True
    
    # Splatting: @variable
    if re.search(r'(?:^|[^\w.])@\w+', trimmed):
        return True
    
    # Member invocations: .Method()
    if re.search(r'\.\w+\s*\(', trimmed):
        return True
    
    # Assignments: $var = ...
    if re.search(r'\$\w+\s*[+\-*/]?=', trimmed):
        return True
    
    # Stop-parsing symbol: --%
    if '--%' in trimmed:
        return True
    
    # UNC paths: \\server\share or //server/share
    if '\\\\' in trimmed or re.search(r'(?<!:)\/\/', trimmed):
        return True
    
    # Static method calls: [Type]::Method()
    if '::' in trimmed:
        return True
    
    return False


def isReadOnlyCommand(
    command: str,
    parsed: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Main entry point for read-only command validation.
    
    Determines if a PowerShell command can be executed autonomously by the AI agent
    without prompting the user for confirmation.
    
    Args:
        command: The raw PowerShell command string
        parsed: Parsed AST from PowerShell parser (optional but recommended)
    
    Returns:
        True if command is safe to auto-execute, False if user prompt required
    """
    trimmed_command = command.strip()
    if not trimmed_command:
        return False

    # If no parsed AST available, conservatively return false
    if not parsed:
        return False

    # If parsing failed, reject
    if not parsed.get('valid', False):
        return False

    security = deriveSecurityFlags(parsed)
    
    # Reject commands with script blocks — we can't verify the code inside them
    # e.g., Get-Process | ForEach-Object { Remove-Item C:\foo } looks like a safe pipeline
    # but the script block contains destructive code
    if (
        security.get('hasScriptBlocks', False) or
        security.get('hasSubExpressions', False) or
        security.get('hasExpandableStrings', False) or
        security.get('hasSplatting', False) or
        security.get('hasMemberInvocations', False) or
        security.get('hasAssignments', False) or
        security.get('hasStopParsing', False)
    ):
        return False

    segments = getPipelineSegments(parsed)

    if len(segments) == 0:
        return False

    # SECURITY: Block compound commands that contain a cwd-changing cmdlet
    # (Set-Location/Push-Location/Pop-Location/New-PSDrive) alongside any other
    # statement. This was previously scoped to cd+git only, but that overlooked
    # the isReadOnlyCommand auto-allow path for cd+read compounds (finding #27):
    #   Set-Location ~; Get-Content ./.ssh/id_rsa
    # Both cmdlets are in CMDLET_ALLOWLIST, so without this guard the compound
    # auto-allows. Path validation resolved ./.ssh/id_rsa against the STALE
    # validator cwd (e.g. /project), missing any Read(~/.ssh/**) deny rule.
    # At runtime PowerShell cd's to ~, reads ~/.ssh/id_rsa.
    #
    # Any compound containing a cwd-changing cmdlet cannot be auto-classified
    # read-only when other statements may use relative paths — those paths
    # resolve differently at runtime than at validation time. BashTool has the
    # equivalent guard via compoundCommandHasCd threading into path validation.
    total_commands = sum(len(seg.get('commands', [])) for seg in segments)
    
    if total_commands > 1:
        has_cd = any(
            any(isCwdChangingCmdlet(cmd.get('name', '')) for cmd in seg.get('commands', []))
            for seg in segments
        )
        if has_cd:
            return False

    # Check each statement individually - all must be read-only
    for pipeline in segments:
        if not pipeline or len(pipeline.get('commands', [])) == 0:
            return False

        # Reject file redirections (writing to files). `> $null` discards output
        # and is not a filesystem write, so it doesn't disqualify read-only status.
        redirections = pipeline.get('redirections', [])
        if len(redirections) > 0:
            has_file_redirection = any(
                not r.get('isMerging', False) and not isNullRedirectionTarget(r.get('target', ''))
                for r in redirections
            )
            if has_file_redirection:
                return False

        # First command must be in the allowlist
        first_cmd = pipeline['commands'][0]
        if not first_cmd:
            return False

        if not isAllowlistedCommand(first_cmd, command):
            return False

        # Remaining pipeline commands must be safe output cmdlets OR allowlisted
        # (with arg validation). Format-Table/Measure-Object moved from
        # SAFE_OUTPUT_CMDLETS to CMDLET_ALLOWLIST after security review found all
        # accept calculated-property hashtables. isAllowlistedCommand runs their
        # argLeaksValue callback: bare `| Format-Table` passes, `| Format-Table
        # $env:SECRET` fails. SECURITY: nameType gate catches 'scripts\\Out-Null'
        # (raw name has path chars → 'application'). cmd.name is stripped to
        # 'Out-Null' which would match SAFE_OUTPUT_CMDLETS, but PowerShell runs
        # scripts\\Out-Null.ps1.
        for i in range(1, len(pipeline['commands'])):
            cmd = pipeline['commands'][i]
            if not cmd or cmd.get('nameType') == 'application':
                return False
            
            # SECURITY: isSafeOutputCommand is name-only; only short-circuit for
            # zero-arg invocations. Out-String -InputObject:(rm x) — the paren is
            # evaluated when Out-String runs. With name-only check and args, the
            # colon-bound paren bypasses. Force isAllowlistedCommand (arg validation)
            # when args present — Out-String/Out-Null/Out-Host are NOT in
            # CMDLET_ALLOWLIST so any args will reject.
            #   PoC: Get-Process | Out-String -InputObject:(Remove-Item /tmp/x)
            #   → auto-allow → Remove-Item runs.
            if isSafeOutputCommand(cmd.get('name', '')) and len(cmd.get('args', [])) == 0:
                continue
            
            if not isAllowlistedCommand(cmd, command):
                return False

        # SECURITY: Reject statements with nested commands. nestedCommands are
        # CommandAst nodes found inside script block arguments, ParenExpressionAst
        # children of colon-bound parameters, or other non-top-level positions.
        # A statement with nestedCommands is by definition not a simple read-only
        # invocation — it contains executable sub-pipelines that bypass the
        # per-command allowlist check above.
        if pipeline.get('nestedCommands') and len(pipeline['nestedCommands']) > 0:
            return False

    return True


def isAllowlistedCommand(
    cmd: Dict[str, Any],
    original_command: str,
) -> bool:
    """
    Check if a single parsed command element is in the allowlist.
    
    Args:
        cmd: Parsed command element with name, args, elementTypes, children
        original_command: The raw command string
    
    Returns:
        True if command is allowlisted and passes all validation
    """
    # SECURITY: nameType is computed from the raw (pre-stripModulePrefix) name.
    # 'application' means the raw name contains path chars (. \\ /) — e.g.
    # 'scripts\\Get-Process', './git', 'node.exe'. PowerShell resolves these as
    # file paths, not as the cmdlet/command the stripped name matches. Never
    # auto-allow: the allowlist was built for cmdlets, not arbitrary scripts.
    # Known collateral: 'Microsoft.PowerShell.Management\\Get-ChildItem' also
    # classifies as 'application' (contains . and \\) and will prompt. Acceptable
    # since module-qualified names are rare in practice and prompting is safe.
    if cmd.get('nameType') == 'application':
        # Bypass for explicit safe .exe names (bash `which` parity — see
        # SAFE_EXTERNAL_EXES). SECURITY: match the raw first token of cmd.text,
        # not cmd.name. stripModulePrefix collapses scripts\where.exe →
        # cmd.name='where.exe', but cmd.text preserves 'scripts\where.exe ...'.
        cmd_text = cmd.get('text', '')
        raw_first_token = cmd_text.split()[0].lower() if cmd_text else ''
        if raw_first_token not in SAFE_EXTERNAL_EXES:
            return False
        # Fall through to lookupAllowlist — CMDLET_ALLOWLIST['where.exe'] handles
        # flag validation (empty config = all flags OK, matching bash's `which`).

    config = lookupAllowlist(cmd.get('name', ''))
    if not config:
        return False

    # If there's a regex constraint, check it against the original command
    if config.get('regex') and not config['regex'].search(original_command):
        return False

    # If there's an additional callback, check it
    additional_callback = config.get('additionalCommandIsDangerousCallback')
    if additional_callback and additional_callback(original_command, cmd):
        return False

    # SECURITY: whitelist arg elementTypes — only StringConstant and Parameter
    # are statically verifiable. Everything else expands/evaluates at runtime:
    #   'Variable'          → `Get-Process $env:AWS_SECRET_ACCESS_KEY` expands,
    #                         errors "Cannot find process 'sk-ant-...'", model
    #                         reads the secret from the error
    #   'Other' (Hashtable) → `Get-Process @{k=$env:SECRET}` same leak
    #   'Other' (Convert)   → `Get-Process [string]$env:SECRET` same leak
    #   'Other' (BinaryExpr)→ `Get-Process ($env:SECRET + '')` same leak
    #   'SubExpression'     → arbitrary code (already caught by deriveSecurityFlags
    #                         at the isReadOnlyCommand layer, but isAllowlistedCommand
    #                         is also called from checkPermissionMode directly)
    # hasSyncSecurityConcerns misses bare $var (only matches `$(`/@var/.Method(/ 
    # $var=/--%/::); deriveSecurityFlags has no 'Variable' case; the safeFlags
    # loop below validates flag NAMES but not positional arg TYPES. File cmdlets
    # (CMDLET_PATH_CONFIG) are already protected by SAFE_PATH_ELEMENT_TYPES in
    # pathValidation.ts — this closes the gap for non-file cmdlets (Get-Process,
    # Get-Service, Get-Command, ~15 others). PS equivalent of Bash's blanket `$`
    # token check at BashTool/readOnlyValidation.ts:~1356.
    #
    # Placement: BEFORE external-command dispatch so git/gh/docker/dotnet get
    # this too (defense-in-depth with their string-based `$` checks; catches
    # @{...}/[cast]/($a+$b) that `$` substring misses). In PS argument mode,
    # bare `5` tokenizes as StringConstant (BareWord), not a numeric literal,
    # so `git log -n 5` passes.
    #
    # SECURITY: elementTypes undefined → fail-closed. The real parser always
    # sets it (parser.ts:769/781/812), so undefined means an untrusted or
    # malformed element. Previously skipped (fail-open) for test-helper
    # convenience; test helpers now set elementTypes explicitly.
    # elementTypes[0] is the command name; args start at elementTypes[1].
    if 'elementTypes' not in cmd:
        return False
    
    element_types = cmd.get('elementTypes', [])
    cmd_args = cmd.get('args', [])
    cmd_children = cmd.get('children')
    
    for i in range(1, len(element_types)):
        elem_type = element_types[i]
        if elem_type not in ('StringConstant', 'Parameter'):
            # ArrayLiteralAst (`Get-Process Name, Id`) maps to 'Other'. The
            # leak vectors enumerated above all have a metachar in their extent
            # text: Hashtable `@{`, Convert `[`, BinaryExpr-with-var `$`,
            # ParenExpr `(`. A bare comma-list of identifiers has none.
            arg_text = cmd_args[i - 1] if i - 1 < len(cmd_args) else ''
            if not re.search(r'[$(@{\[]', arg_text):
                continue
            return False
        
        # Colon-bound parameter (`-Flag:$env:SECRET`) is a SINGLE
        # CommandParameterAst — the VariableExpressionAst is its .Argument
        # child, not a separate CommandElement, so elementTypes says 'Parameter'
        # and the whitelist above passes.
        #
        # Query the parser's children[] tree instead of doing
        # string-archaeology on the arg text. children[i-1] holds the
        # .Argument child's mapped type (aligned with args[i-1]).
        # Tree query catches MORE than the string check — e.g.
        # `-InputObject:@{k=v}` (HashtableAst → 'Other', no `$` in text),
        # `-Name:('payload' > file)` (ParenExpressionAst with redirection).
        # Fallback to the extended metachar check when children is undefined
        # (backward compat / test helpers that don't set it).
        if elem_type == 'Parameter':
            param_children = cmd_children[i - 1] if cmd_children and i - 1 < len(cmd_children) else None
            if param_children:
                if any(c.get('type') != 'StringConstant' for c in param_children):
                    return False
            else:
                # Fallback: string-archaeology on arg text (pre-children parsers).
                # Reject `$` (variable), `(` (ParenExpressionAst), `@` (hash/array
                # sub), `{` (scriptblock), `[` (type literal/static method).
                arg = cmd_args[i - 1] if i - 1 < len(cmd_args) else ''
                colon_idx = arg.find(':')
                if colon_idx > 0 and re.search(r'[$(@{\[]', arg[colon_idx + 1:]):
                    return False

    canonical = resolveToCanonical(cmd.get('name', ''))

    # Handle external commands via shared validation
    if canonical in ('git', 'gh', 'docker', 'dotnet'):
        return _is_external_command_safe(canonical, cmd.get('args', []))

    # On Windows, / is a valid flag prefix for native commands (e.g., findstr /S).
    # But PowerShell cmdlets always use - prefixed parameters, so /tmp is a path,
    # not a flag. We detect cmdlets by checking if the command resolves to a
    # Verb-Noun canonical name (either directly or via alias).
    is_cmdlet = '-' in canonical

    # SECURITY: if allowAllFlags is set, skip flag validation (command's entire
    # flag surface is read-only). Otherwise, missing/empty safeFlags means
    # "positional args only, reject all flags" — NOT "accept everything".
    if config.get('allowAllFlags', False):
        return True
    
    if not config.get('safeFlags') or len(config['safeFlags']) == 0:
        # No safeFlags defined and allowAllFlags not set: reject any flags.
        # Positional-only args are still allowed (the loop below won't fire).
        # This is the safe default — commands must opt in to flag acceptance.
        def has_flag(arg_idx: int) -> bool:
            arg = cmd_args[arg_idx] if arg_idx < len(cmd_args) else ''
            if is_cmdlet:
                elem_type = cmd.get('elementTypes', [])[arg_idx + 1] if arg_idx + 1 < len(cmd.get('elementTypes', [])) else None
                return isPowerShellParameter(arg, elem_type)
            return arg.startswith('-') or (getPlatform() == 'windows' and arg.startswith('/'))
        
        has_flags = any(has_flag(i) for i in range(len(cmd_args)))
        return not has_flags

    # Validate that all flags used are in the allowlist.
    # SECURITY: use elementTypes as ground
    # truth for parameter detection. PowerShell's tokenizer accepts en-dash/
    # em-dash/horizontal-bar (U+2013/2014/2015) as parameter prefixes; a raw
    # startsWith('-') check misses `–ComputerName` (en-dash). The parser maps
    # CommandParameterAst → 'Parameter' regardless of dash char.
    # elementTypes[0] is the name element; args start at elementTypes[1].
    for i in range(len(cmd_args)):
        arg = cmd_args[i]
        # For cmdlets: trust elementTypes (AST ground truth, catches Unicode dashes).
        # For native exes on Windows: also check `/` prefix (argv convention, not
        # tokenizer — the parser sees `/S` as a positional, not CommandParameterAst).
        elem_type = cmd.get('elementTypes', [])[i + 1] if i + 1 < len(cmd.get('elementTypes', [])) else None
        
        if is_cmdlet:
            is_flag = isPowerShellParameter(arg, elem_type)
        else:
            is_flag = arg.startswith('-') or (getPlatform() == 'windows' and arg.startswith('/'))
        
        if is_flag:
            # For cmdlets, normalize Unicode dash to ASCII hyphen for safeFlags
            # comparison (safeFlags entries are always written with ASCII `-`).
            # Native-exe safeFlags are stored with `/` (e.g. '/FO') — don't touch.
            param_name = '-' + arg[1:] if is_cmdlet else arg
            colon_index = param_name.find(':')
            if colon_index > 0:
                param_name = param_name[:colon_index]

            # -ErrorAction/-Verbose/-Debug etc. are accepted by every cmdlet via
            # [CmdletBinding()] and only route error/warning/progress streams —
            # they can't make a read-only cmdlet write. pathValidation.ts already
            # merges these into its per-cmdlet param sets (line ~1339); this is
            # the same merge for safeFlags. Without it, `Get-Content file.txt
            # -ErrorAction SilentlyContinue` prompts despite Get-Content being
            # allowlisted. Only for cmdlets — native exes don't have common params.
            param_lower = param_name.lower()
            if is_cmdlet and param_lower in COMMON_PARAMETERS:
                continue
            
            is_safe = any(flag.lower() == param_lower for flag in config.get('safeFlags', []))
            if not is_safe:
                return False

    return True


def _is_external_command_safe(command: str, args: List[str]) -> bool:
    """Dispatch to external command validation (git, gh, docker, dotnet)."""
    if command == 'git':
        return _is_git_safe(args)
    elif command == 'gh':
        return _is_gh_safe(args)
    elif command == 'docker':
        return _is_docker_safe(args)
    elif command == 'dotnet':
        return _is_dotnet_safe(args)
    else:
        return False


# ---------------------------------------------------------------------------
# External command validation (git, gh, docker)
# ---------------------------------------------------------------------------

DANGEROUS_GIT_GLOBAL_FLAGS: Set[str] = {
    '-c',
    '-C',
    '--exec-path',
    '--config-env',
    '--git-dir',
    '--work-tree',
    # SECURITY: --attr-source creates a parser differential. Git treat the
    # token after the tree-ish value as a pathspec (not the subcommand), but
    # our skip-by-2 loop would treat it as the subcommand:
    #   git --attr-source HEAD~10 log status
    #   validator: advances past HEAD~10, sees subcmd=log → allow
    #   git:       consumes `log` as pathspec, runs `status` as the real subcmd
    # Verified with `GIT_TRACE=1 git --attr-source HEAD~10 log status` →
    # `trace: built-in: git status`. Reject outright rather than skip-by-2.
    '--attr-source',
}

# Git global flags that accept a separate (space-separated) value argument.
# When the loop encounters one without an inline `=` value, it must skip the
# next token so the value isn't mistaken for the subcommand (e.g. `git --namespace foo status`).
#
# SECURITY: This set must be COMPLETE. Any value-consuming global flag not
# listed here creates a parser differential: validator sees the value as the
# subcommand, git consumes it and runs the NEXT token. Audited against
# `man git` + GIT_TRACE for git 2.51; --list-cmds is `=`-only, booleans
# (-p/--bare/--no-*/--*-pathspecs/--html-path/etc.) advance by 1 via the
# default path. --attr-source REMOVED: it also triggers pathspec parsing,
# creating a second differential — moved to DANGEROUS_GIT_GLOBAL_FLAGS above.
GIT_GLOBAL_FLAGS_WITH_VALUES: Set[str] = {
    '-c',
    '-C',
    '--exec-path',
    '--config-env',
    '--git-dir',
    '--work-tree',
    '--namespace',
    '--super-prefix',
    '--shallow-file',
}

# Git short global flags that accept attached-form values (no space between
# flag letter and value). Long options (--git-dir etc.) require `=` or space,
# so the split-on-`=` check handles them. But `-ccore.pager=sh` and `-C/path`
# need prefix matching: git parses `-c<name>=<value>` and `-C<path>` directly.
DANGEROUS_GIT_SHORT_FLAGS_ATTACHED: List[str] = ['-c', '-C']


def _is_git_safe(args: List[str]) -> bool:
    """Validate git command arguments for read-only safety."""
    if len(args) == 0:
        return True

    # SECURITY: Reject any arg containing `$` (variable reference). Bare
    # VariableExpressionAst positionals reach here as literal text ($env:SECRET,
    # $VAR). deriveSecurityFlags does not gate bare Variable args. The validator
    # sees `$VAR` as text; PowerShell expands it at runtime. Parser differential:
    #   git diff $VAR   where $VAR = '--output=/tmp/evil'
    #   → validator sees positional '$VAR' → validateFlags passes
    #   → PowerShell runs `git diff --output=/tmp/evil` → file write
    # This generalizes the ls-remote inline `$` guard below to all git subcommands.
    # Bash equivalent: BashTool blanket
    # `$` rejection at readOnlyValidation.ts:~1352. isGhSafe has the same guard.
    for arg in args:
        if '$' in arg:
            return False

    # Skip over global flags before the subcommand, rejecting dangerous ones.
    # Flags that take space-separated values must consume the next token so it
    # isn't mistaken for the subcommand (e.g. `git --namespace foo status`).
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if not arg or not arg.startswith('-'):
            break
        
        # SECURITY: Attached-form short flags. `-ccore.pager=sh` splits on `=` to
        # `-ccore.pager`, which isn't in DANGEROUS_GIT_GLOBAL_FLAGS. Git accepts
        # `-c<name>=<value>` and `-C<path>` with no space. We must prefix-match.
        # Note: `--cached`, `--config-env`, etc. already fail startsWith('-c') at
        # position 1 (`-` ≠ `c`). The `!== '-'` guard only applies to `-c`
        # (git config keys never start with `-`, so `-c-key` is implausible).
        # It does NOT apply to `-C` — directory paths CAN start with `-`, so
        # `git -C-trap status` must reject. `git -ccore.pager=sh log` spawns a shell.
        for short_flag in DANGEROUS_GIT_SHORT_FLAGS_ATTACHED:
            if (
                len(arg) > len(short_flag) and
                arg.startswith(short_flag) and
                (short_flag == '-C' or arg[len(short_flag)] != '-')
            ):
                return False
        
        has_inline_value = '=' in arg
        flag_name = arg.split('=')[0] if has_inline_value else arg
        
        if flag_name in DANGEROUS_GIT_GLOBAL_FLAGS:
            return False
        
        # Consume the next token if the flag takes a separate value
        if not has_inline_value and flag_name in GIT_GLOBAL_FLAGS_WITH_VALUES:
            idx += 2
        else:
            idx += 1

    if idx >= len(args):
        return True

    # Try multi-word subcommand first (e.g. 'stash list', 'config --get', 'remote show')
    first = args[idx].lower() if idx < len(args) else ''
    second = args[idx + 1].lower() if idx + 1 < len(args) else ''

    # GIT_READ_ONLY_COMMANDS keys are like 'git diff', 'git stash list'
    two_word_key = f'git {first} {second}'
    one_word_key = f'git {first}'

    config = GIT_READ_ONLY_COMMANDS.get(two_word_key)
    subcommand_tokens = 2

    if not config:
        config = GIT_READ_ONLY_COMMANDS.get(one_word_key)
        subcommand_tokens = 1

    if not config:
        return False

    flag_args = args[idx + subcommand_tokens:]

    # git ls-remote URL rejection — ported from BashTool's inline guard
    # (src/tools/BashTool/readOnlyValidation.ts:~962). ls-remote with a URL
    # is a data-exfiltration vector (encode secrets in hostname → DNS/HTTP).
    # Reject URL-like positionals: `://` (http/git protocols), `@` + `:` (SSH
    # git@host:path), and `$` (variable refs — $env:URL reaches here as the
    # literal string '$env:URL' when the arg's elementType is Variable; the
    # security-flag checks don't gate bare Variable positionals passed to
    # external commands).
    if first == 'ls-remote':
        for arg in flag_args:
            if not arg.startswith('-'):
                if '://' in arg or '@' in arg or ':' in arg or '$' in arg:
                    return False

    additional_callback = config.get('additionalCommandIsDangerousCallback')
    if additional_callback and additional_callback('', flag_args):
        return False
    
    return validateFlags(flag_args, 0, config, commandName='git')


def _is_gh_safe(args: List[str]) -> bool:
    """Validate GitHub AI agent command arguments for read-only safety."""
    # gh commands are network-dependent; only allow for ant users
    # NOTE: In Python, you may want to adjust this environment variable check
    import os
    if os.environ.get('USER_TYPE') != 'ant':
        return False

    if len(args) == 0:
        return True

    # Try two-word subcommand first (e.g. 'pr view')
    config = None
    subcommand_tokens = 0

    if len(args) >= 2:
        two_word_key = f'gh {args[0].lower()} {args[1].lower()}'
        config = GH_READ_ONLY_COMMANDS.get(two_word_key)
        subcommand_tokens = 2

    # Try single-word subcommand (e.g. 'gh version')
    if not config and len(args) >= 1:
        one_word_key = f'gh {args[0].lower()}'
        config = GH_READ_ONLY_COMMANDS.get(one_word_key)
        subcommand_tokens = 1

    if not config:
        return False

    flag_args = args[subcommand_tokens:]

    # SECURITY: Reject any arg containing `$` (variable reference). Bare
    # VariableExpressionAst positionals reach here as literal text ($env:SECRET).
    # deriveSecurityFlags does not gate bare Variable args — only subexpressions,
    # splatting, expandable strings, etc. All gh subcommands are network-facing,
    # so a variable arg is a data-exfiltration vector:
    #   gh search repos $env:SECRET_API_KEY
    #   → PowerShell expands at runtime → secret sent to GitHub API.
    # git ls-remote has an equivalent inline guard; this generalizes it for gh.
    # Bash equivalent: BashTool blanket `$` rejection at readOnlyValidation.ts:~1352.
    for arg in flag_args:
        if '$' in arg:
            return False
    
    additional_callback = config.get('additionalCommandIsDangerousCallback')
    if additional_callback and additional_callback('', flag_args):
        return False
    
    return validateFlags(flag_args, 0, config)


def _is_docker_safe(args: List[str]) -> bool:
    """Validate Docker command arguments for read-only safety."""
    if len(args) == 0:
        return True

    # SECURITY: blanket PowerShell `$` variable rejection. Same guard as
    # isGitSafe and isGhSafe. Parser differential: validator sees literal
    # '$env:X'; PowerShell expands at runtime. Runs BEFORE the fast-path
    # return — the previous location (after fast-path) never fired for
    # `docker ps`/`docker images`. The earlier comment claiming those take no
    # --format was wrong: `docker ps --format $env:AWS_SECRET_ACCESS_KEY`
    # auto-allowed, PowerShell expanded, docker errored with the secret in
    # its output, model read it. Check ALL args, not flagArgs — args[0]
    # (subcommand slot) could also be `$env:X`. elementTypes whitelist isn't
    # applicable here: this function receives string[] (post-stringify), not
    # ParsedCommandElement; the isAllowlistedCommand caller applies the
    # elementTypes gate one layer up.
    for arg in args:
        if '$' in arg:
            return False

    one_word_key = f'docker {args[0].lower()}'

    # Fast path: EXTERNAL_READONLY_COMMANDS entries ('docker ps', 'docker images')
    # have no flag constraints — allow unconditionally (after $ guard above).
    if one_word_key in EXTERNAL_READONLY_COMMANDS:
        return True

    # DOCKER_READ_ONLY_COMMANDS entries ('docker logs', 'docker inspect') have
    # per-flag configs. Mirrors isGhSafe: look up config, then validateFlags.
    config = DOCKER_READ_ONLY_COMMANDS.get(one_word_key)
    if not config:
        return False

    flag_args = args[1:]

    additional_callback = config.get('additionalCommandIsDangerousCallback')
    if additional_callback and additional_callback('', flag_args):
        return False
    
    return validateFlags(flag_args, 0, config)


def _is_dotnet_safe(args: List[str]) -> bool:
    """Validate .NET AI agent command arguments for read-only safety."""
    if len(args) == 0:
        return False

    # dotnet uses top-level flags like --version, --info, --list-runtimes
    # All args must be in the safe set
    for arg in args:
        if arg.lower() not in DOTNET_READ_ONLY_FLAGS:
            return False

    return True
