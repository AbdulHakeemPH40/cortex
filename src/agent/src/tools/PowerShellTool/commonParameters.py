"""
PowerShell Common Parameters.

Common parameters available on all cmdlets via [CmdletBinding()].
Source: about_CommonParameters (PowerShell docs) + Get-Command output.

Shared between pathValidation.py (merges into per-cmdlet known-param sets)
and readOnlyValidation.py (merges into safeFlags check). Split out to break
what would otherwise be an import cycle between those two files.

Stored lowercase with leading dash — callers `.lower()` their input.
"""

COMMON_SWITCHES = ['-verbose', '-debug']

COMMON_VALUE_PARAMS = [
    '-erroraction',
    '-warningaction',
    '-informationaction',
    '-progressaction',
    '-errorvariable',
    '-warningvariable',
    '-informationvariable',
    '-outvariable',
    '-outbuffer',
    '-pipelinevariable',
]

COMMON_PARAMETERS = frozenset([
    *COMMON_SWITCHES,
    *COMMON_VALUE_PARAMS,
])
