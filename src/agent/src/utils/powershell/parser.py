"""
PowerShell AST parser - converts PowerShell commands to structured JSON via native parser.

This module spawns pwsh to parse commands using System.Management.Automation.Language.Parser
and returns structured results for security analysis.
"""

import asyncio
import base64
import json
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

# Defensive imports
try:
    from execa import execa
except ImportError:
    execa = None

try:
    from ..debug import logForDebugging
except ImportError:
    def logForDebugging(msg: str) -> None:
        pass

try:
    from ..memoize import memoizeWithLRU
except ImportError:
    def memoizeWithLRU(func, key_fn=None, max_size=256):
        return func

try:
    from ..shell.powershellDetection import getCachedPowerShellPath
except ImportError:
    async def getCachedPowerShellPath():
        return None

try:
    from ..slowOperations import jsonParse
except ImportError:
    def jsonParse(text: str):
        return json.loads(text)


# ---------------------------------------------------------------------------
# Public types describing the parsed output returned to callers.
# These map to System.Management.Automation.Language AST classes.
# ---------------------------------------------------------------------------

# The PowerShell AST element type for pipeline elements.
PipelineElementType = Union[
    'CommandAst',
    'CommandExpressionAst',
    'ParenExpressionAst'
]

# The AST node type for individual command elements (arguments, expressions).
CommandElementType = Union[
    'ScriptBlock',
    'SubExpression',
    'ExpandableString',
    'MemberInvocation',
    'Variable',
    'StringConstant',
    'Parameter',
    'Other'
]

# A child node of a command element (one level deep).
class CommandElementChild(TypedDict):
    type: CommandElementType
    text: str

# The PowerShell AST statement type.
StatementType = Union[
    'PipelineAst',
    'PipelineChainAst',
    'AssignmentStatementAst',
    'IfStatementAst',
    'ForStatementAst',
    'ForEachStatementAst',
    'WhileStatementAst',
    'DoWhileStatementAst',
    'DoUntilStatementAst',
    'SwitchStatementAst',
    'TryStatementAst',
    'TrapStatementAst',
    'FunctionDefinitionAst',
    'DataStatementAst',
    'UnknownStatementAst'
]

# A command invocation within a pipeline segment.
class ParsedCommandElement(TypedDict, total=False):
    """A command invocation within a pipeline segment."""
    name: str  # The command/cmdlet name (e.g., "Get-ChildItem", "git")
    nameType: Union['cmdlet', 'application', 'unknown']  # Command name type
    elementType: PipelineElementType  # The AST element type from PowerShell's parser
    args: List[str]  # All arguments as strings (includes flags like "-Recurse")
    text: str  # The full text of this command element
    elementTypes: Optional[List[CommandElementType]]  # AST node types for each element
    children: Optional[List[Optional[List[CommandElementChild]]]]  # Child nodes
    redirections: Optional[List['ParsedRedirection']]  # Redirections on this command

# A redirection found in the command.
class ParsedRedirection(TypedDict):
    """A redirection found in the command."""
    operator: Literal['>', '>>', '2>', '2>>', '*>', '*>>', '2>&1']
    target: str
    isMerging: bool

# A parsed statement from PowerShell.
class ParsedStatement(TypedDict, total=False):
    """A parsed statement from PowerShell."""
    statementType: StatementType
    commands: List[ParsedCommandElement]
    redirections: List[ParsedRedirection]
    text: str
    nestedCommands: Optional[List[ParsedCommandElement]]
    securityPatterns: Optional[Dict[str, bool]]

# A variable reference found in the command.
class ParsedVariable(TypedDict):
    """A variable reference found in the command."""
    path: str
    isSplatted: bool

# A parse error from PowerShell's parser.
class ParseError(TypedDict):
    """A parse error from PowerShell's parser."""
    message: str
    errorId: str

# The complete parsed result from the PowerShell AST parser.
class ParsedPowerShellCommand(TypedDict, total=False):
    """The complete parsed result from the PowerShell AST parser."""
    valid: bool
    errors: List[ParseError]
    statements: List[ParsedStatement]
    variables: List[ParsedVariable]
    hasStopParsing: bool
    originalCommand: str
    typeLiterals: Optional[List[str]]
    hasUsingStatements: Optional[bool]
    hasScriptRequirements: Optional[bool]

# ---------------------------------------------------------------------------
# Raw types describing PS script JSON output (exported for testing)
# ---------------------------------------------------------------------------

class RawCommandElement(TypedDict, total=False):
    type: str  # .GetType().Name e.g. "StringConstantExpressionAst"
    text: str  # .Extent.Text
    value: Optional[str]  # .Value if available (resolves backtick escapes)
    expressionType: Optional[str]  # .Expression.GetType().Name for CommandExpressionAst
    children: Optional[List[Dict[str, str]]]  # CommandParameterAst.Argument, one level

class RawRedirection(TypedDict, total=False):
    type: str  # "FileRedirectionAst" or "MergingRedirectionAst"
    append: Optional[bool]  # .Append (FileRedirectionAst only)
    fromStream: Optional[str]  # .FromStream.ToString() e.g. "Output", "Error", "All"
    locationText: Optional[str]  # .Location.Extent.Text (FileRedirectionAst only)

class RawPipelineElement(TypedDict, total=False):
    type: str  # .GetType().Name e.g. "CommandAst", "CommandExpressionAst"
    text: str  # .Extent.Text
    commandElements: Optional[List[RawCommandElement]]
    redirections: Optional[List[RawRedirection]]
    expressionType: Optional[str]  # for CommandExpressionAst

class RawStatement(TypedDict, total=False):
    type: str  # .GetType().Name e.g. "PipelineAst", "IfStatementAst"
    text: str  # .Extent.Text
    elements: Optional[List[RawPipelineElement]]  # for PipelineAst
    nestedCommands: Optional[List[RawPipelineElement]]  # commands found via FindAll
    redirections: Optional[List[RawRedirection]]  # FileRedirectionAst found via FindAll
    securityPatterns: Optional[Dict[str, bool]]

class RawParsedOutput(TypedDict, total=False):
    valid: bool
    errors: List[Dict[str, str]]
    statements: List[RawStatement]
    variables: List[Dict[str, Union[str, bool]]]
    hasStopParsing: bool
    originalCommand: str
    typeLiterals: Optional[List[str]]
    hasUsingStatements: Optional[bool]
    hasScriptRequirements: Optional[bool]


# ---------------------------------------------------------------------------
# Constants and configuration
# ---------------------------------------------------------------------------

# Default 5s is fine for interactive use (warm pwsh spawn is ~450ms). Windows
# CI under Defender/AMSI load can exceed 5s on consecutive spawns even after
# CAN_SPAWN_PARSE_SCRIPT() warms the JIT.
DEFAULT_PARSE_TIMEOUT_MS = 5_000

def getParseTimeoutMs() -> int:
    """Get PowerShell parse timeout from environment or default."""
    import os
    env = os.environ.get('CORTEX_CODE_PWSH_PARSE_TIMEOUT_MS')
    if env:
        try:
            parsed = int(env)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return DEFAULT_PARSE_TIMEOUT_MS


# The PowerShell parse script inlined as a string constant.
# This avoids needing to read from disk at runtime (the file may not exist
# in bundled builds). The script uses the native PowerShell AST parser to
# analyze a command and output structured JSON.
PARSE_SCRIPT_BODY = r"""
if (-not $EncodedCommand) {
    Write-Output '{"valid":false,"errors":[{"message":"No command provided","errorId":"NoInput"}],"statements":[],"variables":[],"hasStopParsing":false,"originalCommand":""}'
    exit 0
}

$Command = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($EncodedCommand))

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput(
    $Command,
    [ref]$tokens,
    [ref]$parseErrors
)

$allVariables = [System.Collections.ArrayList]::new()

function Get-RawCommandElements {
    param([System.Management.Automation.Language.CommandAst]$CmdAst)
    $elems = [System.Collections.ArrayList]::new()
    foreach ($ce in $CmdAst.CommandElements) {
        $ceData = @{ type = $ce.GetType().Name; text = $ce.Extent.Text }
        if ($ce.PSObject.Properties['Value'] -and $null -ne $ce.Value -and $ce.Value -is [string]) {
            $ceData.value = $ce.Value
        }
        if ($ce -is [System.Management.Automation.Language.CommandExpressionAst]) {
            $ceData.expressionType = $ce.Expression.GetType().Name
        }
        $a=$ce.Argument;if($a){$ceData.children=@(@{type=$a.GetType().Name;text=$a.Extent.Text})}
        [void]$elems.Add($ceData)
    }
    return $elems
}

function Get-RawRedirections {
    param($Redirections)
    $result = [System.Collections.ArrayList]::new()
    foreach ($redir in $Redirections) {
        $redirData = @{ type = $redir.GetType().Name }
        if ($redir -is [System.Management.Automation.Language.FileRedirectionAst]) {
            $redirData.append = [bool]$redir.Append
            $redirData.fromStream = $redir.FromStream.ToString()
            $redirData.locationText = $redir.Location.Extent.Text
        }
        [void]$result.Add($redirData)
    }
    return $result
}

function Get-SecurityPatterns($A) {
    $p = @{}
    foreach ($n in $A.FindAll({ param($x)
        $x -is [System.Management.Automation.Language.MemberExpressionAst] -or
        $x -is [System.Management.Automation.Language.SubExpressionAst] -or
        $x -is [System.Management.Automation.Language.ArrayExpressionAst] -or
        $x -is [System.Management.Automation.Language.ExpandableStringExpressionAst] -or
        $x -is [System.Management.Automation.Language.ScriptBlockExpressionAst] -or
        $x -is [System.Management.Automation.Language.ParenExpressionAst]
    }, $true)) { switch ($n.GetType().Name) {
        'InvokeMemberExpressionAst' { $p.hasMemberInvocations = $true }
        'MemberExpressionAst' { $p.hasMemberInvocations = $true }
        'SubExpressionAst' { $p.hasSubExpressions = $true }
        'ArrayExpressionAst' { $p.hasSubExpressions = $true }
        'ParenExpressionAst' { $p.hasSubExpressions = $true }
        'ExpandableStringExpressionAst' { $p.hasExpandableStrings = $true }
        'ScriptBlockExpressionAst' { $p.hasScriptBlocks = $true }
    }}
    if ($p.Count -gt 0) { return $p }
    return $null
}

$varExprs = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)
foreach ($v in $varExprs) {
    [void]$allVariables.Add(@{
        path = $v.VariablePath.ToString()
        isSplatted = [bool]$v.Splatted
    })
}

$typeLiterals = [System.Collections.ArrayList]::new()
foreach ($t in $ast.FindAll({ param($n)
    $n -is [System.Management.Automation.Language.TypeExpressionAst] -or
    $n -is [System.Management.Automation.Language.TypeConstraintAst]
}, $true)) { [void]$typeLiterals.Add($t.TypeName.FullName) }

$hasStopParsing = $false
$tk = [System.Management.Automation.Language.TokenKind]
foreach ($tok in $tokens) {
    if ($tok.Kind -eq $tk::MinusMinus) { $hasStopParsing = $true; break }
    if ($tok.Kind -eq $tk::Generic -and ($tok.Text -replace '[\u2013\u2014\u2015]','-') -eq '--%') {
        $hasStopParsing = $true; break
    }
}

$statements = [System.Collections.ArrayList]::new()

function Process-BlockStatements {
    param($Block)
    if (-not $Block) { return }

    foreach ($stmt in $Block.Statements) {
        $statement = @{
            type = $stmt.GetType().Name
            text = $stmt.Extent.Text
        }

        if ($stmt -is [System.Management.Automation.Language.PipelineAst]) {
            $elements = [System.Collections.ArrayList]::new()
            foreach ($element in $stmt.PipelineElements) {
                $elemData = @{
                    type = $element.GetType().Name
                    text = $element.Extent.Text
                }

                if ($element -is [System.Management.Automation.Language.CommandAst]) {
                    $elemData.commandElements = @(Get-RawCommandElements -CmdAst $element)
                    $elemData.redirections = @(Get-RawRedirections -Redirections $element.Redirections)
                } elseif ($element -is [System.Management.Automation.Language.CommandExpressionAst]) {
                    $elemData.expressionType = $element.Expression.GetType().Name
                    $elemData.redirections = @(Get-RawRedirections -Redirections $element.Redirections)
                }

                [void]$elements.Add($elemData)
            }
            $statement.elements = @($elements)

            $allNestedCmds = $stmt.FindAll(
                { param($node) $node -is [System.Management.Automation.Language.CommandAst] },
                $true
            )
            $nestedCmds = [System.Collections.ArrayList]::new()
            foreach ($cmd in $allNestedCmds) {
                if ($cmd.Parent -eq $stmt) { continue }
                $nested = @{
                    type = $cmd.GetType().Name
                    text = $cmd.Extent.Text
                    commandElements = @(Get-RawCommandElements -CmdAst $cmd)
                    redirections = @(Get-RawRedirections -Redirections $cmd.Redirections)
                }
                [void]$nestedCmds.Add($nested)
            }
            if ($nestedCmds.Count -gt 0) {
                $statement.nestedCommands = @($nestedCmds)
            }
            $r = $stmt.FindAll({param($n) $n -is [System.Management.Automation.Language.FileRedirectionAst]}, $true)
            if ($r.Count -gt 0) {
                $rr = @(Get-RawRedirections -Redirections $r)
                $statement.redirections = if ($statement.redirections) { @($statement.redirections) + $rr } else { $rr }
            }
        } else {
            $nestedCmdAsts = $stmt.FindAll(
                { param($node) $node -is [System.Management.Automation.Language.CommandAst] },
                $true
            )
            $nested = [System.Collections.ArrayList]::new()
            foreach ($cmd in $nestedCmdAsts) {
                [void]$nested.Add(@{
                    type = 'CommandAst'
                    text = $cmd.Extent.Text
                    commandElements = @(Get-RawCommandElements -CmdAst $cmd)
                    redirections = @(Get-RawRedirections -Redirections $cmd.Redirections)
                })
            }
            if ($nested.Count -gt 0) {
                $statement.nestedCommands = @($nested)
            }
            $r = $stmt.FindAll({param($n) $n -is [System.Management.Automation.Language.FileRedirectionAst]}, $true)
            if ($r.Count -gt 0) { $statement.redirections = @(Get-RawRedirections -Redirections $r) }
        }

        $sp = Get-SecurityPatterns $stmt
        if ($sp) { $statement.securityPatterns = $sp }

        [void]$statements.Add($statement)
    }

    if ($Block.Traps) {
        foreach ($trap in $Block.Traps) {
            $statement = @{
                type = 'TrapStatementAst'
                text = $trap.Extent.Text
            }
            $nestedCmdAsts = $trap.FindAll(
                { param($node) $node -is [System.Management.Automation.Language.CommandAst] },
                $true
            )
            $nestedCmds = [System.Collections.ArrayList]::new()
            foreach ($cmd in $nestedCmdAsts) {
                $nested = @{
                    type = $cmd.GetType().Name
                    text = $cmd.Extent.Text
                    commandElements = @(Get-RawCommandElements -CmdAst $cmd)
                    redirections = @(Get-RawRedirections -Redirections $cmd.Redirections)
                }
                [void]$nestedCmds.Add($nested)
            }
            if ($nestedCmds.Count -gt 0) {
                $statement.nestedCommands = @($nestedCmds)
            }
            $r = $trap.FindAll({param($n) $n -is [System.Management.Automation.Language.FileRedirectionAst]}, $true)
            if ($r.Count -gt 0) { $statement.redirections = @(Get-RawRedirections -Redirections $r) }
            $sp = Get-SecurityPatterns $trap
            if ($sp) { $statement.securityPatterns = $sp }
            [void]$statements.Add($statement)
        }
    }
}

Process-BlockStatements -Block $ast.BeginBlock
Process-BlockStatements -Block $ast.ProcessBlock
Process-BlockStatements -Block $ast.EndBlock
Process-BlockStatements -Block $ast.CleanBlock
Process-BlockStatements -Block $ast.DynamicParamBlock

if ($ast.ParamBlock) {
  $pb = $ast.ParamBlock
  $pn = [System.Collections.ArrayList]::new()
  foreach ($c in $pb.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]}, $true)) {
    [void]$pn.Add(@{type='CommandAst';text=$c.Extent.Text;commandElements=@(Get-RawCommandElements -CmdAst $c);redirections=@(Get-RawRedirections -Redirections $c.Redirections)})
  }
  $pr = $pb.FindAll({param($n) $n -is [System.Management.Automation.Language.FileRedirectionAst]}, $true)
  $ps = Get-SecurityPatterns $pb
  if ($pn.Count -gt 0 -or $pr.Count -gt 0 -or $ps) {
    $st = @{type='ParamBlockAst';text=$pb.Extent.Text}
    if ($pn.Count -gt 0) { $st.nestedCommands = @($pn) }
    if ($pr.Count -gt 0) { $st.redirections = @(Get-RawRedirections -Redirections $pr) }
    if ($ps) { $st.securityPatterns = $ps }
    [void]$statements.Add($st)
  }
}

$hasUsingStatements = $ast.UsingStatements -and $ast.UsingStatements.Count -gt 0
$hasScriptRequirements = $ast.ScriptRequirements -ne $null

$output = @{
    valid = ($parseErrors.Count -eq 0)
    errors = @($parseErrors | ForEach-Object {
        @{
            message = $_.Message
            errorId = $_.ErrorId
        }
    })
    statements = @($statements)
    variables = @($allVariables)
    hasStopParsing = $hasStopParsing
    originalCommand = $Command
    typeLiterals = @($typeLiterals)
    hasUsingStatements = [bool]$hasUsingStatements
    hasScriptRequirements = [bool]$hasScriptRequirements
}

$output | ConvertTo-Json -Depth 10 -Compress
"""

# ---------------------------------------------------------------------------
# Windows CreateProcess has a 32,767 char runtime limit.
# See detailed derivation in TypeScript comments above.
# ---------------------------------------------------------------------------
WINDOWS_ARGV_CAP = 32_767
FIXED_ARGV_OVERHEAD = 200
ENCODED_CMD_WRAPPER = len("$EncodedCommand = ''\n")
SAFETY_MARGIN = 100
SCRIPT_CHARS_BUDGET = ((WINDOWS_ARGV_CAP - FIXED_ARGV_OVERHEAD) * 3) / 8
CMD_B64_BUDGET = SCRIPT_CHARS_BUDGET - len(PARSE_SCRIPT_BODY) - ENCODED_CMD_WRAPPER

# Unit: UTF-8 BYTES. Compare against len(command.encode('utf-8')), not len(command).
WINDOWS_MAX_COMMAND_LENGTH = max(
    0,
    int((CMD_B64_BUDGET * 3) / 4) - SAFETY_MARGIN
)

# Pre-existing value, known to work on Unix.
UNIX_MAX_COMMAND_LENGTH = 4_500

# Unit: UTF-8 BYTES.
import platform
MAX_COMMAND_LENGTH = WINDOWS_MAX_COMMAND_LENGTH if platform.system() == 'Windows' else UNIX_MAX_COMMAND_LENGTH


# ---------------------------------------------------------------------------
# Core parsing logic
# ---------------------------------------------------------------------------

INVALID_RESULT_BASE = {
    'valid': False,
    'statements': [],
    'variables': [],
    'hasStopParsing': False,
}

def makeInvalidResult(command: str, message: str, errorId: str) -> ParsedPowerShellCommand:
    """Create an invalid parse result with error information."""
    return {
        **INVALID_RESULT_BASE,
        'errors': [{'message': message, 'errorId': errorId}],
        'originalCommand': command,
    }

def toUtf16LeBase64(text: str) -> str:
    """Base64-encode a string as UTF-16LE for PowerShell's -EncodedCommand."""
    utf16_bytes = text.encode('utf-16-le')
    return base64.b64encode(utf16_bytes).decode('ascii')

def buildParseScript(command: str) -> str:
    """Build the full PowerShell script that parses a command."""
    encoded = base64.b64encode(command.encode('utf-8')).decode('ascii')
    return f"$EncodedCommand = '{encoded}'\n{PARSE_SCRIPT_BODY}"

def ensureArray(value):
    """Ensure a value is an array. PowerShell may unwrap single-element arrays."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]

def mapStatementType(rawType: str) -> StatementType:
    """Map raw .NET AST type name to our StatementType union."""
    mapping = {
        'PipelineAst': 'PipelineAst',
        'PipelineChainAst': 'PipelineChainAst',
        'AssignmentStatementAst': 'AssignmentStatementAst',
        'IfStatementAst': 'IfStatementAst',
        'ForStatementAst': 'ForStatementAst',
        'ForEachStatementAst': 'ForEachStatementAst',
        'WhileStatementAst': 'WhileStatementAst',
        'DoWhileStatementAst': 'DoWhileStatementAst',
        'DoUntilStatementAst': 'DoUntilStatementAst',
        'SwitchStatementAst': 'SwitchStatementAst',
        'TryStatementAst': 'TryStatementAst',
        'TrapStatementAst': 'TrapStatementAst',
        'FunctionDefinitionAst': 'FunctionDefinitionAst',
        'DataStatementAst': 'DataStatementAst',
    }
    return mapping.get(rawType, 'UnknownStatementAst')

def mapElementType(rawType: str, expressionType: Optional[str] = None) -> CommandElementType:
    """Map raw .NET AST type name to our CommandElementType union."""
    if rawType == 'ScriptBlockExpressionAst':
        return 'ScriptBlock'
    elif rawType in ('SubExpressionAst', 'ArrayExpressionAst'):
        return 'SubExpression'
    elif rawType == 'ExpandableStringExpressionAst':
        return 'ExpandableString'
    elif rawType in ('InvokeMemberExpressionAst', 'MemberExpressionAst'):
        return 'MemberInvocation'
    elif rawType == 'VariableExpressionAst':
        return 'Variable'
    elif rawType in ('StringConstantExpressionAst', 'ConstantExpressionAst'):
        return 'StringConstant'
    elif rawType == 'CommandParameterAst':
        return 'Parameter'
    elif rawType == 'ParenExpressionAst':
        return 'SubExpression'
    elif rawType == 'CommandExpressionAst':
        # Delegate to the wrapped expression type
        if expressionType:
            return mapElementType(expressionType)
        return 'Other'
    else:
        return 'Other'

def classifyCommandName(name: str) -> Union['cmdlet', 'application', 'unknown']:
    """Classify command name as cmdlet, application, or unknown."""
    import re
    if re.match(r'^[A-Za-z]+-[A-Za-z][A-Za-z0-9_]*$', name):
        return 'cmdlet'
    if any(c in name for c in ['.', '\\', '/']):
        return 'application'
    return 'unknown'

def stripModulePrefix(name: str) -> str:
    """Strip module prefix from command name (e.g. 'Module\\Cmdlet' -> 'Cmdlet')."""
    idx = name.rfind('\\')
    if idx < 0:
        return name
    # Don't strip file paths: drive letters, UNC paths, or relative paths
    if (name[0:2].endswith(':') or 
        name.startswith('\\\\') or 
        name.startswith('.\\') or 
        name.startswith('..\\')):
        return name
    return name[idx + 1:]


# ---------------------------------------------------------------------------
# Main parsing function with LRU caching
# ---------------------------------------------------------------------------

TRANSIENT_ERROR_IDS = {
    'PwshSpawnError',
    'PwshError', 
    'PwshTimeout',
    'EmptyOutput',
    'InvalidJson',
}

async def parsePowerShellCommandImpl(command: str) -> ParsedPowerShellCommand:
    """Parse a PowerShell command using the native AST parser."""
    # Check command length (UTF-8 bytes)
    commandBytes = len(command.encode('utf-8'))
    if commandBytes > MAX_COMMAND_LENGTH:
        logForDebugging(
            f'PowerShell parser: command too long ({commandBytes} bytes, max {MAX_COMMAND_LENGTH})'
        )
        return makeInvalidResult(
            command,
            f'Command too long for parsing ({commandBytes} bytes). Maximum supported length is {MAX_COMMAND_LENGTH} bytes.',
            'CommandTooLong',
        )

    pwshPath = await getCachedPowerShellPath()
    if not pwshPath:
        return makeInvalidResult(
            command,
            'PowerShell is not available',
            'NoPowerShell',
        )

    script = buildParseScript(command)
    encodedScript = toUtf16LeBase64(script)
    args = [
        '-NoProfile',
        '-NonInteractive',
        '-NoLogo',
        '-EncodedCommand',
        encodedScript,
    ]

    # Spawn pwsh with retry on timeout
    parseTimeoutMs = getParseTimeoutMs()
    stdout = ''
    stderr = ''
    code = None
    timedOut = False
    
    for attempt in range(2):
        try:
            if execa is None:
                # Stub for when execa is not available
                return makeInvalidResult(
                    command,
                    'execa not available - stub implementation',
                    'StubImplementation',
                )
            result = await execa(pwshPath, args, timeout=parseTimeoutMs, reject=False)
            stdout = result.stdout
            stderr = result.stderr
            timedOut = getattr(result, 'timedOut', False)
            code = result.exitCode if result.failed else 0
        except Exception as e:
            logForDebugging(f'PowerShell parser: failed to spawn pwsh: {e}')
            return makeInvalidResult(
                command,
                f'Failed to spawn PowerShell: {e}',
                'PwshSpawnError',
            )
        if not timedOut:
            break
        logForDebugging(
            f'PowerShell parser: pwsh timed out after {parseTimeoutMs}ms (attempt {attempt + 1})'
        )

    if timedOut:
        return makeInvalidResult(
            command,
            f'pwsh timed out after {parseTimeoutMs}ms (2 attempts)',
            'PwshTimeout',
        )

    if code != 0:
        logForDebugging(f'PowerShell parser: pwsh exited with code {code}, stderr: {stderr}')
        return makeInvalidResult(
            command,
            f'pwsh exited with code {code}: {stderr}',
            'PwshError',
        )

    trimmed = stdout.strip()
    if not trimmed:
        logForDebugging('PowerShell parser: empty stdout from pwsh')
        return makeInvalidResult(
            command,
            'No output from PowerShell parser',
            'EmptyOutput',
        )

    try:
        raw = jsonParse(trimmed)
        return transformRawOutput(raw)
    except Exception:
        logForDebugging(f'PowerShell parser: invalid JSON output: {trimmed[:200]}')
        return makeInvalidResult(
            command,
            'Invalid JSON from PowerShell parser',
            'InvalidJson',
        )

# Memoized version with transient error eviction
_parsePowerShellCommandCached = memoizeWithLRU(
    lambda command: parsePowerShellCommandImpl(command),
    lambda command: command,
    256
)

async def parsePowerShellCommand(command: str) -> ParsedPowerShellCommand:
    """Parse a PowerShell command with LRU caching."""
    result = await _parsePowerShellCommandCached(command)
    # Evict transient failures so they can be retried
    if not result['valid'] and result.get('errors', [{}])[0].get('errorId', '') in TRANSIENT_ERROR_IDS:
        _parsePowerShellCommandCached.cache.pop(command, None)
    return result


# ---------------------------------------------------------------------------
# Analysis helpers & constants
# ---------------------------------------------------------------------------

# Common PowerShell aliases mapped to their canonical cmdlet names.
COMMON_ALIASES = {
    # Directory listing
    'ls': 'Get-ChildItem',
    'dir': 'Get-ChildItem',
    'gci': 'Get-ChildItem',
    # Content
    'cat': 'Get-Content',
    'type': 'Get-Content',
    'gc': 'Get-Content',
    # Navigation
    'cd': 'Set-Location',
    'sl': 'Set-Location',
    'chdir': 'Set-Location',
    'pushd': 'Push-Location',
    'popd': 'Pop-Location',
    'pwd': 'Get-Location',
    'gl': 'Get-Location',
    # Items
    'gi': 'Get-Item',
    'gp': 'Get-ItemProperty',
    'ni': 'New-Item',
    'mkdir': 'New-Item',
    'md': 'New-Item',
    'ri': 'Remove-Item',
    'del': 'Remove-Item',
    'rd': 'Remove-Item',
    'rmdir': 'Remove-Item',
    'rm': 'Remove-Item',
    'erase': 'Remove-Item',
    'mi': 'Move-Item',
    'mv': 'Move-Item',
    'move': 'Move-Item',
    'ci': 'Copy-Item',
    'cp': 'Copy-Item',
    'copy': 'Copy-Item',
    'cpi': 'Copy-Item',
    'si': 'Set-Item',
    'rni': 'Rename-Item',
    'ren': 'Rename-Item',
    # Process
    'ps': 'Get-Process',
    'gps': 'Get-Process',
    'kill': 'Stop-Process',
    'spps': 'Stop-Process',
    'start': 'Start-Process',
    'saps': 'Start-Process',
    'sajb': 'Start-Job',
    'ipmo': 'Import-Module',
    # Output
    'echo': 'Write-Output',
    'write': 'Write-Output',
    'sleep': 'Start-Sleep',
    # Help
    'help': 'Get-Help',
    'man': 'Get-Help',
    'gcm': 'Get-Command',
    # Service
    'gsv': 'Get-Service',
    # Variables
    'gv': 'Get-Variable',
    'sv': 'Set-Variable',
    # History
    'h': 'Get-History',
    'history': 'Get-History',
    # Invoke
    'iex': 'Invoke-Expression',
    'iwr': 'Invoke-WebRequest',
    'irm': 'Invoke-RestMethod',
    'icm': 'Invoke-Command',
    'ii': 'Invoke-Item',
    # PSSession — remote code execution surface
    'nsn': 'New-PSSession',
    'etsn': 'Enter-PSSession',
    'exsn': 'Exit-PSSession',
    'gsn': 'Get-PSSession',
    'rsn': 'Remove-PSSession',
    # Misc
    'cls': 'Clear-Host',
    'clear': 'Clear-Host',
    'select': 'Select-Object',
    'where': 'Where-Object',
    'foreach': 'ForEach-Object',
    '%': 'ForEach-Object',
    '?': 'Where-Object',
    'measure': 'Measure-Object',
    'ft': 'Format-Table',
    'fl': 'Format-List',
    'fw': 'Format-Wide',
    'oh': 'Out-Host',
    'ogv': 'Out-GridView',
    'ac': 'Add-Content',
    'clc': 'Clear-Content',
    'tee': 'Tee-Object',
    'epcsv': 'Export-Csv',
    'sp': 'Set-ItemProperty',
    'rp': 'Remove-ItemProperty',
    'cli': 'Clear-Item',
    'epal': 'Export-Alias',
    # Text search
    'sls': 'Select-String',
}

DIRECTORY_CHANGE_CMDLETS = {
    'set-location',
    'push-location',
    'pop-location',
}

DIRECTORY_CHANGE_ALIASES = {'cd', 'sl', 'chdir', 'pushd', 'popd'}

PS_TOKENIZER_DASH_CHARS = {'-', '\u2013', '\u2014', '\u2015'}


def getAllCommandNames(parsed: ParsedPowerShellCommand) -> List[str]:
    """Get all command names across all statements, pipeline segments, and nested commands."""
    names = []
    for statement in parsed.get('statements', []):
        for cmd in statement.get('commands', []):
            names.append(cmd['name'].lower())
        if statement.get('nestedCommands'):
            for cmd in statement['nestedCommands']:
                names.append(cmd['name'].lower())
    return names

def getAllCommands(parsed: ParsedPowerShellCommand) -> List[ParsedCommandElement]:
    """Get all pipeline segments as flat list of commands."""
    commands = []
    for statement in parsed.get('statements', []):
        for cmd in statement.get('commands', []):
            commands.append(cmd)
        if statement.get('nestedCommands'):
            for cmd in statement['nestedCommands']:
                commands.append(cmd)
    return commands

def getAllRedirections(parsed: ParsedPowerShellCommand) -> List[ParsedRedirection]:
    """Get all redirections across all statements."""
    redirections = []
    for statement in parsed.get('statements', []):
        for redir in statement.get('redirections', []):
            redirections.append(redir)
        if statement.get('nestedCommands'):
            for cmd in statement['nestedCommands']:
                if cmd.get('redirections'):
                    for redir in cmd['redirections']:
                        redirections.append(redir)
    return redirections

def getVariablesByScope(parsed: ParsedPowerShellCommand, scope: str) -> List[ParsedVariable]:
    """Get all variables, optionally filtered by scope (e.g., 'env')."""
    prefix = scope.lower() + ':'
    return [v for v in parsed.get('variables', []) if v['path'].lower().startswith(prefix)]

def hasCommandNamed(parsed: ParsedPowerShellCommand, name: str) -> bool:
    """Check if any command matches a given name (case-insensitive), handling aliases."""
    lowerName = name.lower()
    canonicalFromAlias = COMMON_ALIASES.get(lowerName, '').lower()

    for cmdName in getAllCommandNames(parsed):
        if cmdName == lowerName:
            return True
        canonical = COMMON_ALIASES.get(cmdName, '').lower()
        if canonical == lowerName:
            return True
        if canonicalFromAlias and cmdName == canonicalFromAlias:
            return True
        if canonical and canonicalFromAlias and canonical == canonicalFromAlias:
            return True
    return False

def hasDirectoryChange(parsed: ParsedPowerShellCommand) -> bool:
    """Check if the command contains any directory-changing commands."""
    for cmdName in getAllCommandNames(parsed):
        if cmdName in DIRECTORY_CHANGE_CMDLETS or cmdName in DIRECTORY_CHANGE_ALIASES:
            return True
    return False

def isSingleCommand(parsed: ParsedPowerShellCommand) -> bool:
    """Check if the command is a single simple command (no pipes, no semicolons)."""
    stmt = parsed.get('statements', [None])[0]
    return (
        len(parsed.get('statements', [])) == 1 and
        stmt is not None and
        len(stmt.get('commands', [])) == 1 and
        (not stmt.get('nestedCommands') or len(stmt['nestedCommands']) == 0)
    )

def commandHasArg(command: ParsedCommandElement, arg: str) -> bool:
    """Check if a specific command has a given argument/flag (case-insensitive)."""
    lowerArg = arg.lower()
    return any(a.lower() == lowerArg for a in command.get('args', []))

def isPowerShellParameter(arg: str, elementType: Optional[CommandElementType] = None) -> bool:
    """Determines if an argument is a PowerShell parameter (flag)."""
    if elementType is not None:
        return elementType == 'Parameter'
    return len(arg) > 0 and arg[0] in PS_TOKENIZER_DASH_CHARS

def commandHasArgAbbreviation(
    command: ParsedCommandElement,
    fullParam: str,
    minPrefix: str
) -> bool:
    """Check if any argument is an unambiguous abbreviation of a PowerShell parameter."""
    lowerFull = fullParam.lower()
    lowerMin = minPrefix.lower()
    
    def check_arg(a: str) -> bool:
        colonIndex = a.find(':', 1)
        paramPart = a[:colonIndex] if colonIndex > 0 else a
        lower = paramPart.replace('`', '').lower()
        return (
            lower.startswith(lowerMin) and
            lowerFull.startswith(lower) and
            len(lower) <= len(lowerFull)
        )
    
    return any(check_arg(a) for a in command.get('args', []))

def getPipelineSegments(parsed: ParsedPowerShellCommand) -> List[ParsedStatement]:
    """Split a parsed command into its pipeline segments."""
    return parsed.get('statements', [])

def isNullRedirectionTarget(target: str) -> bool:
    """True if a redirection target is PowerShell's $null automatic variable."""
    t = target.strip().lower()
    return t == '$null' or t == '${null}'

def getFileRedirections(parsed: ParsedPowerShellCommand) -> List[ParsedRedirection]:
    """Get output redirections (file redirections, not merging redirections)."""
    return [
        r for r in getAllRedirections(parsed)
        if not r['isMerging'] and not isNullRedirectionTarget(r['target'])
    ]


def deriveSecurityFlags(parsed: ParsedPowerShellCommand) -> Dict[str, bool]:
    """Derive security-relevant flags from the parsed command structure."""
    flags = {
        'hasSubExpressions': False,
        'hasScriptBlocks': False,
        'hasSplatting': False,
        'hasExpandableStrings': False,
        'hasMemberInvocations': False,
        'hasAssignments': False,
        'hasStopParsing': parsed.get('hasStopParsing', False),
    }

    def checkElements(cmd: ParsedCommandElement):
        if not cmd.get('elementTypes'):
            return
        for et in cmd['elementTypes']:
            if et == 'ScriptBlock':
                flags['hasScriptBlocks'] = True
            elif et == 'SubExpression':
                flags['hasSubExpressions'] = True
            elif et == 'ExpandableString':
                flags['hasExpandableStrings'] = True
            elif et == 'MemberInvocation':
                flags['hasMemberInvocations'] = True

    for stmt in parsed.get('statements', []):
        if stmt.get('statementType') == 'AssignmentStatementAst':
            flags['hasAssignments'] = True
        for cmd in stmt.get('commands', []):
            checkElements(cmd)
        if stmt.get('nestedCommands'):
            for cmd in stmt['nestedCommands']:
                checkElements(cmd)
        # securityPatterns provides belt-and-suspenders check
        if stmt.get('securityPatterns'):
            sp = stmt['securityPatterns']
            if sp.get('hasMemberInvocations'):
                flags['hasMemberInvocations'] = True
            if sp.get('hasSubExpressions'):
                flags['hasSubExpressions'] = True
            if sp.get('hasExpandableStrings'):
                flags['hasExpandableStrings'] = True
            if sp.get('hasScriptBlocks'):
                flags['hasScriptBlocks'] = True

    for v in parsed.get('variables', []):
        if v.get('isSplatted'):
            flags['hasSplatting'] = True
            break

    return flags


# ---------------------------------------------------------------------------
# Transform functions - convert raw PS output to typed structures
# ---------------------------------------------------------------------------

def transformRedirection(raw: RawRedirection) -> ParsedRedirection:
    """Map raw redirection to ParsedRedirection."""
    if raw.get('type') == 'MergingRedirectionAst':
        return {'operator': '2>&1', 'target': '', 'isMerging': True}

    append = raw.get('append', False)
    fromStream = raw.get('fromStream', 'Output')

    if append:
        if fromStream == 'Error':
            operator = '2>>'
        elif fromStream == 'All':
            operator = '*>>'
        else:
            operator = '>>'
    else:
        if fromStream == 'Error':
            operator = '2>'
        elif fromStream == 'All':
            operator = '*>'
        else:
            operator = '>'

    return {
        'operator': operator,
        'target': raw.get('locationText', ''),
        'isMerging': False
    }

def transformCommandAst(raw: RawPipelineElement) -> ParsedCommandElement:
    """Transform a raw CommandAst pipeline element into ParsedCommandElement."""
    cmdElements = ensureArray(raw.get('commandElements'))
    name = ''
    args = []
    elementTypes = []
    children = []
    hasChildren = False
    nameType = 'unknown'

    if len(cmdElements) > 0:
        first = cmdElements[0]
        # Use .value for string literals, otherwise .text
        isFirstStringLiteral = first['type'] in ('StringConstantExpressionAst', 'ExpandableStringExpressionAst')
        rawNameUnstripped = first.get('value', '') if (isFirstStringLiteral and isinstance(first.get('value'), str)) else first['text']
        
        # Strip surrounding quotes
        rawName = rawNameUnstripped.strip("'\"")
        
        # Check for non-ASCII characters (suspicious)
        import re
        if re.search(r'[\u0080-\uFFFF]', rawName):
            nameType = 'application'
        else:
            nameType = classifyCommandName(rawName)
        
        name = stripModulePrefix(rawName)
        elementTypes.append(mapElementType(first['type'], first.get('expressionType')))

        for i in range(1, len(cmdElements)):
            ce = cmdElements[i]
            isStringLiteral = ce['type'] in ('StringConstantExpressionAst', 'ExpandableStringExpressionAst')
            args.append(ce.get('value', '') if (isStringLiteral and ce.get('value') is not None) else ce['text'])
            elementTypes.append(mapElementType(ce['type'], ce.get('expressionType')))
            
            rawChildren = ensureArray(ce.get('children'))
            if len(rawChildren) > 0:
                hasChildren = True
                children.append([
                    {'type': mapElementType(c['type']), 'text': c['text']}
                    for c in rawChildren
                ])
            else:
                children.append(None)

    result: ParsedCommandElement = {
        'name': name,
        'nameType': nameType,
        'elementType': 'CommandAst',
        'args': args,
        'text': raw['text'],
        'elementTypes': elementTypes,
    }

    if hasChildren:
        result['children'] = children

    # Preserve redirections
    rawRedirs = ensureArray(raw.get('redirections'))
    if len(rawRedirs) > 0:
        result['redirections'] = [transformRedirection(r) for r in rawRedirs]

    return result

def transformExpressionElement(raw: RawPipelineElement) -> ParsedCommandElement:
    """Transform a non-CommandAst pipeline element into ParsedCommandElement."""
    elementType = 'ParenExpressionAst' if raw['type'] == 'ParenExpressionAst' else 'CommandExpressionAst'
    elementTypes = [mapElementType(raw['type'], raw.get('expressionType'))]

    return {
        'name': raw['text'],
        'nameType': 'unknown',
        'elementType': elementType,
        'args': [],
        'text': raw['text'],
        'elementTypes': elementTypes,
    }

def transformStatement(raw: RawStatement) -> ParsedStatement:
    """Transform a raw statement into ParsedStatement."""
    statementType = mapStatementType(raw['type'])
    commands = []
    redirections = []

    if raw.get('elements'):
        # PipelineAst: walk pipeline elements
        for elem in ensureArray(raw['elements']):
            if elem['type'] == 'CommandAst':
                commands.append(transformCommandAst(elem))
                for redir in ensureArray(elem.get('redirections')):
                    redirections.append(transformRedirection(redir))
            else:
                commands.append(transformExpressionElement(elem))
                for redir in ensureArray(elem.get('redirections')):
                    redirections.append(transformRedirection(redir))
        
        # Deduplicate redirections
        seen = set()
        unique_redirections = []
        for r in redirections:
            key = f"{r['operator']}\0{r['target']}"
            if key not in seen:
                seen.add(key)
                unique_redirections.append(r)
        redirections = unique_redirections
        
        # Add deep FindAll redirections
        for redir in ensureArray(raw.get('redirections')):
            r = transformRedirection(redir)
            key = f"{r['operator']}\0{r['target']}"
            if key not in seen:
                seen.add(key)
                redirections.append(r)
    else:
        # Non-pipeline statement
        commands.append({
            'name': raw['text'],
            'nameType': 'unknown',
            'elementType': 'CommandExpressionAst',
            'args': [],
            'text': raw['text'],
        })
        for redir in ensureArray(raw.get('redirections')):
            redirections.append(transformRedirection(redir))

    nestedCommands = None
    rawNested = ensureArray(raw.get('nestedCommands'))
    if len(rawNested) > 0:
        nestedCommands = [transformCommandAst(cmd) for cmd in rawNested]

    result: ParsedStatement = {
        'statementType': statementType,
        'commands': commands,
        'redirections': redirections,
        'text': raw['text'],
    }

    if nestedCommands:
        result['nestedCommands'] = nestedCommands

    if raw.get('securityPatterns'):
        result['securityPatterns'] = raw['securityPatterns']

    return result

def transformRawOutput(raw: RawParsedOutput) -> ParsedPowerShellCommand:
    """Transform the complete raw PS output into ParsedPowerShellCommand."""
    result: ParsedPowerShellCommand = {
        'valid': raw['valid'],
        'errors': ensureArray(raw.get('errors')),
        'statements': [transformStatement(s) for s in ensureArray(raw.get('statements'))],
        'variables': ensureArray(raw.get('variables')),
        'hasStopParsing': raw['hasStopParsing'],
        'originalCommand': raw['originalCommand'],
    }
    
    tl = ensureArray(raw.get('typeLiterals'))
    if len(tl) > 0:
        result['typeLiterals'] = tl
    
    if raw.get('hasUsingStatements'):
        result['hasUsingStatements'] = True
    
    if raw.get('hasScriptRequirements'):
        result['hasScriptRequirements'] = True
    
    return result
