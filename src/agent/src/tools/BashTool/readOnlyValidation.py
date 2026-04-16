# ------------------------------------------------------------
# readOnlyValidation.py
# Python conversion of readOnlyValidation.ts (lines 1-1991)
# 
# Validates bash commands for read-only safety using allowlists,
# flag parsing, and security checks.
# ------------------------------------------------------------

import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

try:
    from ...bootstrap.state import get_original_cwd
except ImportError:
    def get_original_cwd() -> str:
        return "/stub/original/cwd"

try:
    from ...utils.bash.commands import extract_output_redirections, split_command_deprecated
except ImportError:
    def extract_output_redirections(command: str) -> Dict[str, Any]:
        return {"redirections": []}
    
    def split_command_deprecated(command: str) -> List[str]:
        import re
        return re.split(r'\s*(&&|\|\|)\s*', command)

try:
    from ...utils.bash.shell_quote import try_parse_shell_command
except ImportError:
    def try_parse_shell_command(command: str, env_callback=None) -> Dict[str, Any]:
        return {
            "success": True,
            "tokens": command.split(),
        }

try:
    from ...utils.cwd import get_cwd
except ImportError:
    def get_cwd() -> str:
        import os
        return os.getcwd()

try:
    from ...utils.git import is_current_directory_bare_git_repo
except ImportError:
    def is_current_directory_bare_git_repo() -> bool:
        return False

try:
    from ...utils.permissions.PermissionResult import PermissionResult
except ImportError:
    class PermissionResult:
        """Type alias for permission result dictionaries."""
        pass

try:
    from ...utils.platform import get_platform
except ImportError:
    def get_platform() -> str:
        import sys
        return "win32" if sys.platform == "win32" else "linux"

try:
    from ...utils.sandbox.sandbox_adapter import SandboxManager
except ImportError:
    class SandboxManager:
        @staticmethod
        def is_sandboxing_enabled() -> bool:
            return False

try:
    from ...utils.shell.readOnlyCommandValidation import (
        contains_vulnerable_unc_path,
        DOCKER_READ_ONLY_COMMANDS,
        EXTERNAL_READONLY_COMMANDS,
        GH_READ_ONLY_COMMANDS,
        GIT_READ_ONLY_COMMANDS,
        PYRIGHT_READ_ONLY_COMMANDS,
        RIPGREP_READ_ONLY_COMMANDS,
        validate_flags,
    )
except ImportError:
    # Stubs for shared validation utilities
    def contains_vulnerable_unc_path(path: str) -> bool:
        return False
    
    DOCKER_READ_ONLY_COMMANDS = {}
    EXTERNAL_READONLY_COMMANDS = []
    GH_READ_ONLY_COMMANDS = {}
    GIT_READ_ONLY_COMMANDS = {}
    PYRIGHT_READ_ONLY_COMMANDS = {}
    RIPGREP_READ_ONLY_COMMANDS = {}
    
    def validate_flags(*args, **kwargs) -> bool:
        return True

try:
    from .bashPermissions import is_normalized_git_command
except ImportError:
    def is_normalized_git_command(cmd: str) -> bool:
        return cmd.strip().startswith("git ")

try:
    from .bashSecurity import bash_command_is_safe_deprecated
except ImportError:
    def bash_command_is_safe_deprecated(command: str) -> Dict[str, Any]:
        return {"behavior": "passthrough"}

try:
    from .pathValidation import COMMAND_OPERATION_TYPE, PATH_EXTRACTORS, PathCommand
except ImportError:
    COMMAND_OPERATION_TYPE = {}
    PATH_EXTRACTORS = {}
    PathCommand = str

try:
    from .sedValidation import sed_command_is_allowed_by_allowlist
except ImportError:
    def sed_command_is_allowed_by_allowlist(command: str, options=None) -> bool:
        return True


# ============================================================
# TYPE DEFINITIONS
# ============================================================

FlagArgType = str  # 'none', 'string', 'number', 'char', 'EOF', '{}'

class CommandConfig:
    """Configuration for command validation."""
    
    def __init__(
        self,
        safe_flags: Dict[str, FlagArgType],
        regex: Optional[re.Pattern] = None,
        additional_command_is_dangerous_callback: Optional[Callable[[str, List[str]], bool]] = None,
        respects_double_dash: bool = True,
    ):
        self.safe_flags = safe_flags
        self.regex = regex
        self.additional_command_is_dangerous_callback = additional_command_is_dangerous_callback
        self.respects_double_dash = respects_double_dash


# ============================================================
# SHARED SAFE FLAGS
# ============================================================

# Shared safe flags for fd and fdfind (Debian/Ubuntu package name)
FD_SAFE_FLAGS: Dict[str, FlagArgType] = {
    '-h': 'none',
    '--help': 'none',
    '-V': 'none',
    '--version': 'none',
    '-H': 'none',
    '--hidden': 'none',
    '-I': 'none',
    '--no-ignore': 'none',
    '--no-ignore-vcs': 'none',
    '--no-ignore-parent': 'none',
    '-s': 'none',
    '--case-sensitive': 'none',
    '-i': 'none',
    '--ignore-case': 'none',
    '-g': 'none',
    '--glob': 'none',
    '--regex': 'none',
    '-F': 'none',
    '--fixed-strings': 'none',
    '-a': 'none',
    '--absolute-path': 'none',
    '-L': 'none',
    '--follow': 'none',
    '-p': 'none',
    '--full-path': 'none',
    '-0': 'none',
    '--print0': 'none',
    '-d': 'number',
    '--max-depth': 'number',
    '--min-depth': 'number',
    '--exact-depth': 'number',
    '-t': 'string',
    '--type': 'string',
    '-e': 'string',
    '--extension': 'string',
    '-S': 'string',
    '--size': 'string',
    '--changed-within': 'string',
    '--changed-before': 'string',
    '-o': 'string',
    '--owner': 'string',
    '-E': 'string',
    '--exclude': 'string',
    '--ignore-file': 'string',
    '-c': 'string',
    '--color': 'string',
    '-j': 'number',
    '--threads': 'number',
    '--max-buffer-time': 'string',
    '--max-results': 'number',
    '-1': 'none',
    '-q': 'none',
    '--quiet': 'none',
    '--show-errors': 'none',
    '--strip-cwd-prefix': 'none',
    '--one-file-system': 'none',
    '--prune': 'none',
    '--search-path': 'string',
    '--base-directory': 'string',
    '--path-separator': 'string',
    '--batch-size': 'number',
    '--no-require-git': 'none',
    '--hyperlink': 'string',
    '--and': 'string',
    '--format': 'string',
}


# ============================================================
# COMMAND ALLOWLIST
# ============================================================

def build_command_allowlist() -> Dict[str, CommandConfig]:
    """Build the central command allowlist configuration."""
    
    allowlist: Dict[str, CommandConfig] = {
        'xargs': CommandConfig(
            safe_flags={
                '-I': '{}',
                '-n': 'number',
                '-P': 'number',
                '-L': 'number',
                '-s': 'number',
                '-E': 'EOF',
                '-0': 'none',
                '-t': 'none',
                '-r': 'none',
                '-x': 'none',
                '-d': 'char',
            },
        ),
        
        **GIT_READ_ONLY_COMMANDS,
        
        'file': CommandConfig(
            safe_flags={
                '--brief': 'none', '-b': 'none',
                '--mime': 'none', '-i': 'none',
                '--mime-type': 'none',
                '--mime-encoding': 'none',
                '--apple': 'none',
                '--check-encoding': 'none', '-c': 'none',
                '--exclude': 'string', '--exclude-quiet': 'string',
                '--print0': 'none', '-0': 'none',
                '-f': 'string', '-F': 'string',
                '--separator': 'string',
                '--help': 'none', '--version': 'none', '-v': 'none',
                '--no-dereference': 'none', '-h': 'none',
                '--dereference': 'none', '-L': 'none',
                '--magic-file': 'string', '-m': 'string',
                '--keep-going': 'none', '-k': 'none',
                '--list': 'none', '-l': 'none',
                '--no-buffer': 'none', '-n': 'none',
                '--preserve-date': 'none', '-p': 'none',
                '--raw': 'none', '-r': 'none', '-s': 'none',
                '--special-files': 'none',
                '--uncompress': 'none', '-z': 'none',
            },
        ),
        
        'sed': CommandConfig(
            safe_flags={
                '--expression': 'string', '-e': 'string',
                '--quiet': 'none', '--silent': 'none', '-n': 'none',
                '--regexp-extended': 'none', '-r': 'none',
                '--posix': 'none', '-E': 'none',
                '--line-length': 'number', '-l': 'number',
                '--zero-terminated': 'none', '-z': 'none',
                '--separate': 'none', '-s': 'none',
                '--unbuffered': 'none', '-u': 'none',
                '--debug': 'none', '--help': 'none', '--version': 'none',
            },
            additional_command_is_dangerous_callback=lambda raw_cmd, args: not sed_command_is_allowed_by_allowlist(raw_cmd),
        ),
        
        'sort': CommandConfig(
            safe_flags={
                '--ignore-leading-blanks': 'none', '-b': 'none',
                '--dictionary-order': 'none', '-d': 'none',
                '--ignore-case': 'none', '-f': 'none',
                '--general-numeric-sort': 'none', '-g': 'none',
                '--human-numeric-sort': 'none', '-h': 'none',
                '--ignore-nonprinting': 'none', '-i': 'none',
                '--month-sort': 'none', '-M': 'none',
                '--numeric-sort': 'none', '-n': 'none',
                '--random-sort': 'none', '-R': 'none',
                '--reverse': 'none', '-r': 'none',
                '--sort': 'string', '--stable': 'none', '-s': 'none',
                '--unique': 'none', '-u': 'none',
                '--version-sort': 'none', '-V': 'none',
                '--zero-terminated': 'none', '-z': 'none',
                '--key': 'string', '-k': 'string',
                '--field-separator': 'string', '-t': 'string',
                '--check': 'none', '-c': 'none',
                '--check-char-order': 'none', '-C': 'none',
                '--merge': 'none', '-m': 'none',
                '--buffer-size': 'string', '-S': 'string',
                '--parallel': 'number',
                '--batch-size': 'number',
                '--help': 'none', '--version': 'none',
            },
        ),
        
        'man': CommandConfig(
            safe_flags={
                '-a': 'none', '--all': 'none',
                '-d': 'none', '-f': 'none', '--whatis': 'none',
                '-h': 'none', '-k': 'none', '--apropos': 'none',
                '-l': 'string', '-w': 'none',
                '-S': 'string', '-s': 'string',
            },
        ),
        
        'help': CommandConfig(
            safe_flags={
                '-d': 'none', '-m': 'none', '-s': 'none',
            },
        ),
        
        'netstat': CommandConfig(
            safe_flags={
                '-a': 'none', '-L': 'none', '-l': 'none', '-n': 'none',
                '-f': 'string',
                '-g': 'none', '-i': 'none', '-I': 'string',
                '-s': 'none',
                '-r': 'none',
                '-m': 'none',
                '-v': 'none',
            },
        ),
        
        'ps': CommandConfig(
            safe_flags={
                '-e': 'none', '-A': 'none', '-a': 'none', '-d': 'none',
                '-N': 'none', '--deselect': 'none',
                '-f': 'none', '-F': 'none', '-l': 'none', '-j': 'none',
                '-y': 'none',
                '-w': 'none', '-ww': 'none', '--width': 'number',
                '-c': 'none', '-H': 'none', '--forest': 'none',
                '--headers': 'none', '--no-headers': 'none',
                '-n': 'string', '--sort': 'string',
                '-L': 'none', '-T': 'none', '-m': 'none',
                '-C': 'string', '-G': 'string', '-g': 'string',
                '-p': 'string', '--pid': 'string',
                '-q': 'string', '--quick-pid': 'string',
                '-s': 'string', '--sid': 'string',
                '-t': 'string', '--tty': 'string',
                '-U': 'string', '-u': 'string', '--user': 'string',
                '--help': 'none', '--info': 'none',
                '-V': 'none', '--version': 'none',
            },
            additional_command_is_dangerous_callback=lambda _, args: any(
                not arg.startswith('-') and re.match(r'^[a-zA-Z]*e[a-zA-Z]*$', arg)
                for arg in args
            ),
        ),
        
        'base64': CommandConfig(
            respects_double_dash=False,
            safe_flags={
                '-d': 'none', '-D': 'none', '--decode': 'none',
                '-b': 'number', '--break': 'number',
                '-w': 'number', '--wrap': 'number',
                '-i': 'string', '--input': 'string',
                '--ignore-garbage': 'none',
                '-h': 'none', '--help': 'none', '--version': 'none',
            },
        ),
        
        'grep': CommandConfig(
            safe_flags={
                '-e': 'string', '--regexp': 'string',
                '-f': 'string', '--file': 'string',
                '-F': 'none', '--fixed-strings': 'none',
                '-G': 'none', '--basic-regexp': 'none',
                '-E': 'none', '--extended-regexp': 'none',
                '-P': 'none', '--perl-regexp': 'none',
                '-i': 'none', '--ignore-case': 'none',
                '--no-ignore-case': 'none',
                '-v': 'none', '--invert-match': 'none',
                '-w': 'none', '--word-regexp': 'none',
                '-x': 'none', '--line-regexp': 'none',
                '-c': 'none', '--count': 'none',
                '--color': 'string', '--colour': 'string',
                '-L': 'none', '--files-without-match': 'none',
                '-l': 'none', '--files-with-matches': 'none',
                '-m': 'number', '--max-count': 'number',
                '-o': 'none', '--only-matching': 'none',
                '-q': 'none', '--quiet': 'none', '--silent': 'none',
                '-s': 'none', '--no-messages': 'none',
                '-b': 'none', '--byte-offset': 'none',
                '-H': 'none', '--with-filename': 'none',
                '-h': 'none', '--no-filename': 'none',
                '--label': 'string',
                '-n': 'none', '--line-number': 'none',
                '-T': 'none', '--initial-tab': 'none',
                '-u': 'none', '--unix-byte-offsets': 'none',
                '-Z': 'none', '--null': 'none',
                '-z': 'none', '--null-data': 'none',
                '-A': 'number', '--after-context': 'number',
                '-B': 'number', '--before-context': 'number',
                '-C': 'number', '--context': 'number',
                '--group-separator': 'string',
                '--no-group-separator': 'none',
                '-a': 'none', '--text': 'none',
                '--binary-files': 'string',
                '-D': 'string', '--devices': 'string',
                '-d': 'string', '--directories': 'string',
                '--exclude': 'string', '--exclude-from': 'string',
                '--exclude-dir': 'string', '--include': 'string',
                '-r': 'none', '--recursive': 'none',
                '-R': 'none', '--dereference-recursive': 'none',
                '--line-buffered': 'none',
                '-U': 'none', '--binary': 'none',
                '--help': 'none', '-V': 'none', '--version': 'none',
            },
        ),
        
        **RIPGREP_READ_ONLY_COMMANDS,
        
        'sha256sum': CommandConfig(
            safe_flags={
                '-b': 'none', '--binary': 'none',
                '-t': 'none', '--text': 'none',
                '-c': 'none', '--check': 'none',
                '--ignore-missing': 'none',
                '--quiet': 'none', '--status': 'none',
                '--strict': 'none',
                '-w': 'none', '--warn': 'none',
                '--tag': 'none',
                '-z': 'none', '--zero': 'none',
                '--help': 'none', '--version': 'none',
            },
        ),
        
        'sha1sum': CommandConfig(
            safe_flags={
                '-b': 'none', '--binary': 'none',
                '-t': 'none', '--text': 'none',
                '-c': 'none', '--check': 'none',
                '--ignore-missing': 'none',
                '--quiet': 'none', '--status': 'none',
                '--strict': 'none',
                '-w': 'none', '--warn': 'none',
                '--tag': 'none',
                '-z': 'none', '--zero': 'none',
                '--help': 'none', '--version': 'none',
            },
        ),
        
        'md5sum': CommandConfig(
            safe_flags={
                '-b': 'none', '--binary': 'none',
                '-t': 'none', '--text': 'none',
                '-c': 'none', '--check': 'none',
                '--ignore-missing': 'none',
                '--quiet': 'none', '--status': 'none',
                '--strict': 'none',
                '-w': 'none', '--warn': 'none',
                '--tag': 'none',
                '-z': 'none', '--zero': 'none',
                '--help': 'none', '--version': 'none',
            },
        ),
        
        'tree': CommandConfig(
            safe_flags={
                '-a': 'none', '-d': 'none', '-l': 'none', '-f': 'none',
                '-x': 'none', '-L': 'number',
                '-P': 'string', '-I': 'string',
                '--gitignore': 'none', '--gitfile': 'string',
                '--ignore-case': 'none', '--matchdirs': 'none',
                '--metafirst': 'none', '--prune': 'none',
                '--info': 'none', '--infofile': 'string',
                '--noreport': 'none', '--charset': 'string',
                '--filelimit': 'number',
                '-q': 'none', '-N': 'none', '-Q': 'none',
                '-p': 'none', '-u': 'none', '-g': 'none',
                '-s': 'none', '-h': 'none', '--si': 'none',
                '--du': 'none', '-D': 'none',
                '--timefmt': 'string', '-F': 'none',
                '--inodes': 'none', '--device': 'none',
                '-v': 'none', '-t': 'none', '-c': 'none',
                '-U': 'none', '-r': 'none',
                '--dirsfirst': 'none', '--filesfirst': 'none',
                '--sort': 'string',
                '-i': 'none', '-A': 'none', '-S': 'none',
                '-n': 'none', '-C': 'none',
                '-X': 'none', '-J': 'none',
                '-H': 'string', '--nolinks': 'none',
                '--hintro': 'string', '--houtro': 'string',
                '-T': 'string', '--hyperlink': 'none',
                '--scheme': 'string', '--authority': 'string',
                '--fromfile': 'none', '--fromtabfile': 'none',
                '--fflinks': 'none',
                '--help': 'none', '--version': 'none',
            },
        ),
        
        'date': CommandConfig(
            safe_flags={
                '-d': 'string', '--date': 'string',
                '-r': 'string', '--reference': 'string',
                '-u': 'none', '--utc': 'none', '--universal': 'none',
                '-I': 'none', '--iso-8601': 'string',
                '-R': 'none', '--rfc-email': 'none',
                '--rfc-3339': 'string',
                '--debug': 'none', '--help': 'none', '--version': 'none',
            },
            additional_command_is_dangerous_callback=lambda _, args: _is_date_positional_dangerous(args),
        ),
        
        'hostname': CommandConfig(
            safe_flags={
                '-f': 'none', '--fqdn': 'none', '--long': 'none',
                '-s': 'none', '--short': 'none',
                '-i': 'none', '--ip-address': 'none',
                '-I': 'none', '--all-ip-addresses': 'none',
                '-a': 'none', '--alias': 'none',
                '-d': 'none', '--domain': 'none',
                '-A': 'none', '--all-fqdns': 'none',
                '-v': 'none', '--verbose': 'none',
                '-h': 'none', '--help': 'none',
                '-V': 'none', '--version': 'none',
            },
            regex=re.compile(r'^hostname(?:\s+(?:-[a-zA-Z]|--[a-zA-Z-]+))*\s*$'),
        ),
        
        'info': CommandConfig(
            safe_flags={
                '-f': 'string', '--file': 'string',
                '-d': 'string', '--directory': 'string',
                '-n': 'string', '--node': 'string',
                '-a': 'none', '--all': 'none',
                '-k': 'string', '--apropos': 'string',
                '-w': 'none', '--where': 'none',
                '--location': 'none', '--show-options': 'none',
                '--vi-keys': 'none', '--subnodes': 'none',
                '-h': 'none', '--help': 'none',
                '--usage': 'none', '--version': 'none',
            },
        ),
        
        'lsof': CommandConfig(
            safe_flags={
                '-?': 'none', '-h': 'none', '-v': 'none',
                '-a': 'none', '-b': 'none', '-C': 'none',
                '-l': 'none', '-n': 'none', '-N': 'none',
                '-O': 'none', '-P': 'none', '-Q': 'none',
                '-R': 'none', '-t': 'none', '-U': 'none',
                '-V': 'none', '-X': 'none', '-H': 'none',
                '-E': 'none', '-F': 'none', '-g': 'none',
                '-i': 'none', '-K': 'none', '-L': 'none',
                '-o': 'none', '-r': 'none', '-s': 'none',
                '-S': 'none', '-T': 'none', '-x': 'none',
                '-A': 'string', '-c': 'string',
                '-d': 'string', '-e': 'string',
                '-k': 'string', '-p': 'string', '-u': 'string',
            },
            additional_command_is_dangerous_callback=lambda _, args: any(a == '+m' or a.startswith('+m') for a in args),
        ),
        
        'pgrep': CommandConfig(
            safe_flags={
                '-d': 'string', '--delimiter': 'string',
                '-l': 'none', '--list-name': 'none',
                '-a': 'none', '--list-full': 'none',
                '-v': 'none', '--inverse': 'none',
                '-w': 'none', '--lightweight': 'none',
                '-c': 'none', '--count': 'none',
                '-f': 'none', '--full': 'none',
                '-g': 'string', '--pgroup': 'string',
                '-G': 'string', '--group': 'string',
                '-i': 'none', '--ignore-case': 'none',
                '-n': 'none', '--newest': 'none',
                '-o': 'none', '--oldest': 'none',
                '-O': 'string', '--older': 'string',
                '-P': 'string', '--parent': 'string',
                '-s': 'string', '--session': 'string',
                '-t': 'string', '--terminal': 'string',
                '-u': 'string', '--euid': 'string',
                '-U': 'string', '--uid': 'string',
                '-x': 'none', '--exact': 'none',
                '-F': 'string', '--pidfile': 'string',
                '-L': 'none', '--logpidfile': 'none',
                '-r': 'string', '--runstates': 'string',
                '--ns': 'string', '--nslist': 'string',
                '--help': 'none', '-V': 'none', '--version': 'none',
            },
        ),
        
        'tput': CommandConfig(
            safe_flags={
                '-T': 'string', '-V': 'none', '-x': 'none',
            },
            additional_command_is_dangerous_callback=lambda _, args: _is_tput_dangerous(args),
        ),
        
        'ss': CommandConfig(
            safe_flags={
                '-h': 'none', '--help': 'none',
                '-V': 'none', '--version': 'none',
                '-n': 'none', '--numeric': 'none',
                '-r': 'none', '--resolve': 'none',
                '-a': 'none', '--all': 'none',
                '-l': 'none', '--listening': 'none',
                '-o': 'none', '--options': 'none',
                '-e': 'none', '--extended': 'none',
                '-m': 'none', '--memory': 'none',
                '-p': 'none', '--processes': 'none',
                '-i': 'none', '--info': 'none',
                '-s': 'none', '--summary': 'none',
                '-4': 'none', '--ipv4': 'none',
                '-6': 'none', '--ipv6': 'none',
                '-0': 'none', '--packet': 'none',
                '-t': 'none', '--tcp': 'none',
                '-M': 'none', '--mptcp': 'none',
                '-S': 'none', '--sctp': 'none',
                '-u': 'none', '--udp': 'none',
                '-d': 'none', '--dccp': 'none',
                '-w': 'none', '--raw': 'none',
                '-x': 'none', '--unix': 'none',
                '--tipc': 'none', '--vsock': 'none',
                '-f': 'string', '--family': 'string',
                '-A': 'string', '--query': 'string',
                '--socket': 'string',
                '-Z': 'none', '--context': 'none',
                '-z': 'none', '--contexts': 'none',
                '-b': 'none', '--bpf': 'none',
                '-E': 'none', '--events': 'none',
                '-H': 'none', '--no-header': 'none',
                '-O': 'none', '--oneline': 'none',
                '--tipcinfo': 'none', '--tos': 'none',
                '--cgroup': 'none', '--inet-sockopt': 'none',
            },
        ),
        
        'fd': CommandConfig(safe_flags={**FD_SAFE_FLAGS}),
        'fdfind': CommandConfig(safe_flags={**FD_SAFE_FLAGS}),
        
        **PYRIGHT_READ_ONLY_COMMANDS,
        **DOCKER_READ_ONLY_COMMANDS,
    }
    
    return allowlist


# ============================================================
# HELPER FUNCTIONS FOR CALLBACKS
# ============================================================

def _is_date_positional_dangerous(args: List[str]) -> bool:
    """Check if date command has dangerous positional arguments."""
    flags_with_args = {'-d', '--date', '-r', '--reference', '--iso-8601', '--rfc-3339'}
    
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith('--') and '=' in token:
            i += 1
        elif token.startswith('-'):
            if token in flags_with_args:
                i += 2
            else:
                i += 1
        else:
            # Positional argument - must start with + for format strings
            if not token.startswith('+'):
                return True
            i += 1
    
    return False


def _is_tput_dangerous(args: List[str]) -> bool:
    """Check if tput command has dangerous capabilities."""
    DANGEROUS_CAPABILITIES = {
        'init', 'reset', 'rs1', 'rs2', 'rs3',
        'is1', 'is2', 'is3', 'iprog', 'if', 'rf',
        'clear', 'flash', 'mc0', 'mc4', 'mc5', 'mc5i', 'mc5p',
        'pfkey', 'pfloc', 'pfx', 'pfxl', 'smcup', 'rmcup',
    }
    
    flags_with_args = {'-T'}
    after_double_dash = False
    i = 0
    
    while i < len(args):
        token = args[i]
        
        if token == '--':
            after_double_dash = True
            i += 1
        elif not after_double_dash and token.startswith('-'):
            if token == '-S':
                return True
            if not token.startswith('--') and len(token) > 2 and 'S' in token:
                return True
            if token in flags_with_args:
                i += 2
            else:
                i += 1
        else:
            if token in DANGEROUS_CAPABILITIES:
                return True
            i += 1
    
    return False


def get_command_allowlist() -> Dict[str, CommandConfig]:
    """Get the appropriate command allowlist based on platform and user type."""
    import os
    
    allowlist = build_command_allowlist()
    
    # On Windows, remove xargs due to UNC path vulnerability
    if get_platform() == 'windows':
        allowlist.pop('xargs', None)
    
    # Add ant-only commands for USER_TYPE=ant
    if os.environ.get("USER_TYPE") == "ant":
        ant_only = {
            **GH_READ_ONLY_COMMANDS,
            'aki': CommandConfig(
                safe_flags={
                    '-h': 'none', '--help': 'none',
                    '-k': 'none', '--keyword': 'none',
                    '-s': 'none', '--semantic': 'none',
                    '--no-adaptive': 'none',
                    '-n': 'number', '--limit': 'number',
                    '-o': 'number', '--offset': 'number',
                    '--source': 'string', '--exclude-source': 'string',
                    '-a': 'string', '--after': 'string',
                    '-b': 'string', '--before': 'string',
                    '--collection': 'string', '--drive': 'string',
                    '--folder': 'string', '--descendants': 'none',
                    '-m': 'string', '--meta': 'string',
                    '-t': 'string', '--threshold': 'string',
                    '--kw-weight': 'string', '--sem-weight': 'string',
                    '-j': 'none', '--json': 'none',
                    '-c': 'none', '--chunk': 'none',
                    '--preview': 'none', '-d': 'none',
                    '--full-doc': 'none', '-v': 'none',
                    '--verbose': 'none', '--stats': 'none',
                    '-S': 'number', '--summarize': 'number',
                    '--explain': 'none', '--examine': 'string',
                    '--url': 'string', '--multi-turn': 'number',
                    '--multi-turn-model': 'string',
                    '--multi-turn-context': 'string',
                    '--no-rerank': 'none', '--audit': 'none',
                    '--local': 'none', '--staging': 'none',
                },
            ),
        }
        allowlist.update(ant_only)
    
    return allowlist


# ============================================================
# SAFE TARGET COMMANDS FOR XARGS
# ============================================================

SAFE_TARGET_COMMANDS_FOR_XARGS = [
    'echo',
    'printf',
    'wc',
    'grep',
    'head',
    'tail',
]


# ============================================================
# FLAG VALIDATION
# ============================================================

def validate_flags_for_command(
    tokens: List[str],
    command_start: int,
    config: CommandConfig,
    options: Optional[Dict[str, Any]] = None,
) -> bool:
    """Validate flags for a command based on its configuration."""
    # This would need the full validate_flags implementation
    # For now, use the imported stub
    return validate_flags(tokens, command_start, config, options)


# ============================================================
# MAIN VALIDATION FUNCTIONS
# ============================================================

def is_command_safe_via_flag_parsing(command: str) -> bool:
    """Check if a command is safe via flag parsing against allowlist."""
    parse_result = try_parse_shell_command(command, lambda env: f"${env}")
    
    if not parse_result.get("success"):
        return False
    
    parsed = parse_result.get("tokens", [])
    
    # Convert glob operators to strings
    tokens = []
    for token in parsed:
        if isinstance(token, dict) and token.get("op") == "glob":
            tokens.append(token.get("pattern", ""))
        elif isinstance(token, str):
            tokens.append(token)
        else:
            return False  # Has operators
    
    if not tokens:
        return False
    
    # Find matching command configuration
    allowlist = get_command_allowlist()
    command_config: Optional[CommandConfig] = None
    command_tokens_count = 0
    
    for cmd_pattern, config in allowlist.items():
        cmd_parts = cmd_pattern.split()
        if len(tokens) >= len(cmd_parts):
            matches = all(tokens[i] == cmd_parts[i] for i in range(len(cmd_parts)))
            if matches:
                command_config = config
                command_tokens_count = len(cmd_parts)
                break
    
    if not command_config:
        return False
    
    # Special handling for git ls-remote
    if tokens[0] == 'git' and len(tokens) > 1 and tokens[1] == 'ls-remote':
        for i in range(2, len(tokens)):
            token = tokens[i]
            if token and not token.startswith('-'):
                if '://' in token or '@' in token or ':' in token or '$' in token:
                    return False
    
    # Check for variable expansion ($) in any token
    for i in range(command_tokens_count, len(tokens)):
        token = tokens[i]
        if not token:
            continue
        if '$' in token:
            return False
        # Check for brace expansion
        if '{' in token and (',' in token or '..' in token):
            return False
    
    # Validate flags
    if not validate_flags_for_command(
        tokens,
        command_tokens_count,
        command_config,
        {
            "commandName": tokens[0] if tokens else None,
            "rawCommand": command,
            "xargsTargetCommands": SAFE_TARGET_COMMANDS_FOR_XARGS if tokens[0] == 'xargs' else None,
        },
    ):
        return False
    
    # Check regex if present
    if command_config.regex and not command_config.regex.match(command):
        return False
    
    # Check for backticks if no regex
    if not command_config.regex and '`' in command:
        return False
    
    # Block newlines in grep/rg patterns
    if not command_config.regex and tokens[0] in ['rg', 'grep'] and ('\n' in command or '\r' in command):
        return False
    
    # Run dangerous callback if present
    if command_config.additional_command_is_dangerous_callback:
        if command_config.additional_command_is_dangerous_callback(command, tokens[command_tokens_count:]):
            return False
    
    return True


def make_regex_for_safe_command(command: str) -> re.Pattern:
    """Create a regex pattern that matches safe invocations of a command."""
    return re.compile(f'^{re.escape(command)}(?:\\s|$)[^<>()$`|{{}}&;\\n\\r]*$')


# ============================================================
# READ-ONLY COMMAND LISTS
# ============================================================

READONLY_COMMANDS = [
    *EXTERNAL_READONLY_COMMANDS,
    'cal', 'uptime',
    'cat', 'head', 'tail', 'wc', 'stat', 'strings', 'hexdump', 'od', 'nl',
    'id', 'uname', 'free', 'df', 'du', 'locale', 'groups', 'nproc',
    'basename', 'dirname', 'realpath',
    'cut', 'paste', 'tr', 'column', 'tac', 'rev', 'fold',
    'expand', 'unexpand', 'fmt', 'comm', 'cmp', 'numfmt',
    'readlink',
    'diff',
    'true', 'false',
    'sleep', 'which', 'type', 'expr', 'test', 'getconf', 'seq', 'tsort', 'pr',
]

READONLY_COMMAND_REGEXES = [
    *[make_regex_for_safe_command(cmd) for cmd in READONLY_COMMANDS],
    # Echo with optional stderr redirection
    re.compile(r"^echo(?:\s+(?:'[^']*'|\"[^\"$<>\n\r]*\"|[^|;&`$(){{}}><#!'\\\"\s]+))*(?:\s+2>&1)?\s*$"),
    # Cortex IDE help
    re.compile(r'^claude -h$'),
    re.compile(r'^claude --help$'),
    # Uniq
    re.compile(r'^uniq(?:\s+(?:-[a-zA-Z]+|--[a-zA-Z-]+(?:=\S+)?|-[fsw]\s+\d+))*(?:\s|$)\s*$'),
    # System info
    re.compile(r'^pwd$'),
    re.compile(r'^whoami$'),
    # Version checks
    re.compile(r'^node -v$'),
    re.compile(r'^node --version$'),
    re.compile(r'^python --version$'),
    re.compile(r'^python3 --version$'),
    # Misc
    re.compile(r'^history(?:\s+\d+)?\s*$'),
    re.compile(r'^alias$'),
    re.compile(r'^arch(?:\s+(?:--help|-h))?\s*$'),
    # Network
    re.compile(r'^ip addr$'),
    re.compile(r'^ifconfig(?:\s+[a-zA-Z][a-zA-Z0-9_-]*)?\s*$'),
    # jq
    re.compile(r'^jq(?!\s+.*(?:-f\b|--from-file|--rawfile|--slurpfile|--run-tests|-L\b|--library-path|\benv\b|\$ENV\b))(?:\s+(?:-[a-zA-Z]+|--[a-zA-Z-]+(?:=\S+)?))*(?:\s+\'[^\'`]*\'|\s+"[^"`]*"|\s+[^-\s\'"][^\s]*)+\s*$'),
    # cd
    re.compile(r'^cd(?:\s+(?:\'[^\']*\'|"[^"]*"|[^\s;|&`$(){}><#\\]+))?$'),
    # ls
    re.compile(r'^ls(?:\s+[^<>()$`|{}&;\n\r]*)?$'),
    # find (blocks dangerous flags)
    re.compile(r'^find(?:\s+(?:\\[()]|(?!-delete\b|-exec\b|-execdir\b|-ok\b|-okdir\b|-fprint0?\b|-fls\b|-fprintf\b)[^<>()$`|{}&;\n\r\s]|\s)+)?$'),
]


# ============================================================
# UNQUOTED EXPANSION CHECK
# ============================================================

def contains_unquoted_expansion(command: str) -> bool:
    """Check for unquoted glob characters and expandable $ variables."""
    in_single_quote = False
    in_double_quote = False
    escaped = False
    
    for i, char in enumerate(command):
        if escaped:
            escaped = False
            continue
        
        # Backslash is only escape outside single quotes
        if char == '\\' and not in_single_quote:
            escaped = True
            continue
        
        # Update quote state
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        
        # Inside single quotes: everything literal
        if in_single_quote:
            continue
        
        # Check $ followed by variable-name character
        if char == '$':
            next_char = command[i + 1] if i + 1 < len(command) else None
            if next_char and re.match(r'[A-Za-z_@*#?!$0-9-]', next_char):
                return True
        
        # Globs are literal inside double quotes too
        if in_double_quote:
            continue
        
        # Check for glob characters outside all quotes
        if char and re.match(r'[?*[\]]', char):
            return True
    
    return False


# ============================================================
# READ-ONLY CHECK
# ============================================================

def is_command_read_only(command: str) -> bool:
    """Check if a command is read-only."""
    test_command = command.strip()
    
    # Remove stderr redirection for pattern matching
    if test_command.endswith(' 2>&1'):
        test_command = test_command[:-5].strip()
    
    # Check for vulnerable UNC paths
    if contains_vulnerable_unc_path(test_command):
        return False
    
    # Check for unquoted expansion
    if contains_unquoted_expansion(test_command):
        return False
    
    # Check via flag parsing
    if is_command_safe_via_flag_parsing(test_command):
        return True
    
    # Check against regex list
    for regex in READONLY_COMMAND_REGEXES:
        if regex.match(test_command):
            # Additional git safety checks
            if 'git' in test_command:
                if re.search(r'\s-c[\s=]', test_command):
                    return False
                if re.search(r'\s--exec-path[\s=]', test_command):
                    return False
                if re.search(r'\s--config-env[\s=]', test_command):
                    return False
            return True
    
    return False


def command_has_any_git(command: str) -> bool:
    """Check if compound command contains any git command."""
    return any(is_normalized_git_command(subcmd.strip()) for subcmd in split_command_deprecated(command))


# ============================================================
# GIT INTERNAL PATH CHECKS
# ============================================================

GIT_INTERNAL_PATTERNS = [
    re.compile(r'^HEAD$'),
    re.compile(r'^objects(?:\/|$)'),
    re.compile(r'^refs(?:\/|$)'),
    re.compile(r'^hooks(?:\/|$)'),
]

NON_CREATING_WRITE_COMMANDS = {'rm', 'rmdir', 'sed'}


def is_git_internal_path(path: str) -> bool:
    """Check if a path is a git-internal path."""
    normalized = re.sub(r'^\.?/', '', path)
    return any(pattern.match(normalized) for pattern in GIT_INTERNAL_PATTERNS)


def extract_write_paths_from_subcommand(subcommand: str) -> List[str]:
    """Extract write paths from a subcommand."""
    parse_result = try_parse_shell_command(subcommand, lambda env: f"${env}")
    
    if not parse_result.get("success"):
        return []
    
    tokens = [t for t in parse_result.get("tokens", []) if isinstance(t, str)]
    
    if not tokens:
        return []
    
    base_cmd = tokens[0]
    if not base_cmd or base_cmd not in COMMAND_OPERATION_TYPE:
        return []
    
    op_type = COMMAND_OPERATION_TYPE.get(base_cmd)
    if op_type not in ['write', 'create'] or base_cmd in NON_CREATING_WRITE_COMMANDS:
        return []
    
    extractor = PATH_EXTRACTORS.get(base_cmd)
    if not extractor:
        return []
    
    return extractor(tokens[1:])


def command_writes_to_git_internal_paths(command: str) -> bool:
    """Check if command writes to git-internal paths."""
    subcommands = split_command_deprecated(command)
    
    for subcmd in subcommands:
        trimmed = subcmd.strip()
        
        # Check write paths
        write_paths = extract_write_paths_from_subcommand(trimmed)
        for path in write_paths:
            if is_git_internal_path(path):
                return True
        
        # Check output redirections
        redir_info = extract_output_redirections(trimmed)
        for redirection in redir_info.get("redirections", []):
            target = redirection.get("target", "")
            if is_git_internal_path(target):
                return True
    
    return False


# ============================================================
# MAIN PERMISSION CHECK FUNCTION
# ============================================================

def check_read_only_constraints(
    input_data: Dict[str, str],
    compound_command_has_cd: bool,
) -> Dict[str, Any]:
    """
    Check read-only constraints for bash commands.
    
    Args:
        input_data: Dict with 'command' key
        compound_command_has_cd: Pre-computed flag indicating if cd exists
        
    Returns:
        Permission result dict with 'behavior' and 'message' keys
    """
    command = input_data.get("command", "")
    
    # Detect if command is not parseable
    result = try_parse_shell_command(command, lambda env: f"${env}")
    if not result.get("success"):
        return {
            "behavior": "passthrough",
            "message": "Command cannot be parsed, requires further permission checks",
        }
    
    # Check original command for safety
    safety_check = bash_command_is_safe_deprecated(command)
    if safety_check.get("behavior") != "passthrough":
        return {
            "behavior": "passthrough",
            "message": "Command is not read-only, requires further permission checks",
        }
    
    # Check for Windows UNC paths
    if contains_vulnerable_unc_path(command):
        return {
            "behavior": "ask",
            "message": "Command contains Windows UNC path that could be vulnerable to WebDAV attacks",
        }
    
    # Check if any subcommand is git
    has_git_command = command_has_any_git(command)
    
    # Block compound commands with both cd AND git
    if compound_command_has_cd and has_git_command:
        return {
            "behavior": "passthrough",
            "message": "Compound commands with cd and git require permission checks for enhanced security",
        }
    
    # Block git commands in bare git repo directories
    if has_git_command and is_current_directory_bare_git_repo():
        return {
            "behavior": "passthrough",
            "message": "Git commands in directories with bare repository structure require permission checks for enhanced security",
        }
    
    # Block compound commands that write to git-internal paths AND run git
    if has_git_command and command_writes_to_git_internal_paths(command):
        return {
            "behavior": "passthrough",
            "message": "Compound commands that create git internal files and run git require permission checks for enhanced security",
        }
    
    # Block git commands outside original cwd when sandbox enabled
    if (
        has_git_command and
        SandboxManager.is_sandboxing_enabled() and
        get_cwd() != get_original_cwd()
    ):
        return {
            "behavior": "passthrough",
            "message": "Git commands outside the original working directory require permission checks when sandbox is enabled",
        }
    
    # Check if all subcommands are read-only
    all_read_only = all(
        bash_command_is_safe_deprecated(subcmd).get("behavior") == "passthrough"
        and is_command_read_only(subcmd)
        for subcmd in split_command_deprecated(command)
    )
    
    if all_read_only:
        return {
            "behavior": "allow",
            "updatedInput": input_data,
        }
    
    return {
        "behavior": "passthrough",
        "message": "Command is not read-only, requires further permission checks",
    }


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    "CommandConfig",
    "FlagArgType",
    "build_command_allowlist",
    "get_command_allowlist",
    "is_command_safe_via_flag_parsing",
    "make_regex_for_safe_command",
    "contains_unquoted_expansion",
    "is_command_read_only",
    "command_has_any_git",
    "is_git_internal_path",
    "extract_write_paths_from_subcommand",
    "command_writes_to_git_internal_paths",
    "check_read_only_constraints",
    "SAFE_TARGET_COMMANDS_FOR_XARGS",
    "READONLY_COMMANDS",
    "READONLY_COMMAND_REGEXES",
]
