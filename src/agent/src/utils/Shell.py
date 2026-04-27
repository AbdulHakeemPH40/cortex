"""
Shell utilities - TypeScript to Python conversion.
Provides shell execution, configuration, and CWD management.

Source: utils/Shell.ts
"""

import asyncio
import os
import sys
import tempfile
import platform
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Tuple
from functools import lru_cache

# ============================================================
# IMPORTS - With defensive fallbacks for missing modules
# ============================================================

# Shell command and provider
try:
    from .ShellCommand import (
        ShellCommand,
        ExecResult,
        createAbortedCommand,
        createFailedCommand,
        wrapSpawn,
    )
except ImportError:
    class ShellCommand:
        """Stub - convert ShellCommand.ts first"""
        pass

    class ExecResult(dict):
        pass

    def createAbortedCommand(*args, **kwargs):
        return None

    def createFailedCommand(*args, **kwargs):
        return None

    def wrapSpawn(*args, **kwargs):
        return None

try:
    from .shell.shellProvider import ShellProvider, ShellType
except ImportError:
    class ShellProvider:
        """Stub - convert shellProvider.ts first"""
        pass

    ShellType = str  # 'bash' | 'powershell'

# State and config
try:
    from .bootstrap.state import getOriginalCwd, getSessionId, setCwdState
except ImportError:
    def getOriginalCwd() -> str:
        return os.getcwd()

    def getSessionId() -> str:
        return "default"

    def setCwdState(cwd: str) -> None:
        pass

# Shell providers
try:
    from .shell.bashProvider import createBashShellProvider
except ImportError:
    async def createBashShellProvider(shell_path: str):
        return ShellProvider()

try:
    from .shell.powershellDetection import getCachedPowerShellPath
except ImportError:
    async def getCachedPowerShellPath() -> Optional[str]:
        return None

try:
    from .shell.powershellProvider import createPowerShellProvider
except ImportError:
    def createPowerShellProvider(ps_path: str):
        return ShellProvider()

# Utilities
try:
    from .cwd import pwd
except ImportError:
    def pwd() -> str:
        return os.getcwd()

try:
    from .debug import logForDebugging
except ImportError:
    def logForDebugging(msg: str) -> None:
        print(f"[DEBUG] {msg}")

try:
    from .errors import errorMessage, isENOENT
except ImportError:
    def errorMessage(error: Exception) -> str:
        return str(error)

    def isENOENT(error: Exception) -> bool:
        return getattr(error, 'errno', None) == 2

try:
    from .fsOperations import getFsImplementation
except ImportError:
    class FsOperations:
        def cwd(self) -> str:
            return os.getcwd()

        def realpathSync(self, path: str) -> str:
            return str(Path(path).resolve())

    def getFsImplementation() -> FsOperations:
        return FsOperations()

try:
    from .log import logError
except ImportError:
    def logError(error: Exception) -> None:
        print(f"[ERROR] {error}", file=sys.stderr)

try:
    from .task.diskOutput import getTaskOutputDir
except ImportError:
    def getTaskOutputDir() -> str:
        return os.path.join(tempfile.gettempdir(), "cortex_tasks")

try:
    from .task.TaskOutput import TaskOutput
except ImportError:
    class TaskOutput:
        """Stub - convert TaskOutput.ts first"""
        def __init__(self, task_id: str, onProgress, use_file: bool):
            self.task_id = task_id
            self.path = os.path.join(tempfile.gettempdir(), f"task_{task_id}.txt")

try:
    from .which import which
except ImportError:
    async def which(command: str) -> Optional[str]:
        import shutil
        return shutil.which(command)

try:
    from .hooks.fileChangedWatcher import onCwdChangedForHooks
except ImportError:
    async def onCwdChangedForHooks(old_cwd: str, new_cwd: str) -> None:
        pass

try:
    from .permissions.filesystem import get_cortex_temp_dir_name
except ImportError:
    def get_cortex_temp_dir_name() -> str:
        return "cortex_tmp"

try:
    from .platform import getPlatform
except ImportError:
    def getPlatform() -> str:
        return sys.platform

try:
    from .sandbox.sandbox_adapter import SandboxManager
except ImportError:
    class SandboxManager:
        @staticmethod
        async def wrapWithSandbox(command: str, shell: str, tmp_dir: Optional[str], abort_signal):
            return command

        @staticmethod
        def cleanupAfterCommand() -> None:
            pass

try:
    from .sessionEnvironment import invalidateSessionEnvCache
except ImportError:
    def invalidateSessionEnvCache() -> None:
        pass

try:
    from .subprocessEnv import subprocessEnv
except ImportError:
    def subprocessEnv() -> dict:
        return dict(os.environ)

try:
    from .windowsPaths import posixPathToWindowsPath
except ImportError:
    def posixPathToWindowsPath(posix_path: str) -> str:
        return posix_path

try:
    from .Task import generateTaskId
except ImportError:
    def generateTaskId(prefix: str = "task") -> str:
        import uuid
        return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_TIMEOUT = 30 * 60  # 30 minutes in seconds


# ============================================================
# TYPES
# ============================================================

class ShellConfig:
    """Shell configuration with provider"""
    def __init__(self, provider: ShellProvider):
        self.provider = provider


class ExecOptions:
    """Options for exec execution"""
    def __init__(
        self,
        timeout: Optional[int] = None,
        onProgress: Optional[Callable] = None,
        preventCwdChanges: bool = False,
        shouldUseSandbox: bool = False,
        shouldAutoBackground: bool = False,
        onStdout: Optional[Callable[[str], None]] = None,
    ):
        self.timeout = timeout
        self.onProgress = onProgress
        self.preventCwdChanges = preventCwdChanges
        self.shouldUseSandbox = shouldUseSandbox
        self.shouldAutoBackground = shouldAutoBackground
        self.onStdout = onStdout


# ============================================================
# SHELL DETECTION
# ============================================================

def isExecutable(shellPath: str) -> bool:
    """Check if shell path is executable"""
    try:
        if os.access(shellPath, os.X_OK):
            return True
    except (OSError, PermissionError):
        pass

    # Fallback: try to execute with --version
    try:
        import subprocess
        result = subprocess.run(
            [shellPath, '--version'],
            timeout=1,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False


async def findSuitableShell() -> str:
    """Determines the best available shell to use."""
    # Check for explicit shell override first
    shellOverride = os.environ.get('CORTEX_CODE_SHELL')
    if shellOverride:
        # Validate it's a supported shell type
        isSupported = 'bash' in shellOverride or 'zsh' in shellOverride
        if isSupported and isExecutable(shellOverride):
            logForDebugging(f"Using shell override: {shellOverride}")
            return shellOverride
        else:
            logForDebugging(
                f'CORTEX_CODE_SHELL="{shellOverride}" is not a valid bash/zsh path, '
                f'falling back to detection'
            )

    # Check user's preferred shell from environment
    env_shell = os.environ.get('SHELL')
    # Only consider SHELL if it's bash or zsh
    isEnvShellSupported = env_shell and ('bash' in env_shell or 'zsh' in env_shell)
    preferBash = 'bash' in (env_shell or '')

    # Try to locate shells using which
    zshPath, bashPath = await asyncio.gather(
        which('zsh'),
        which('bash')
    )

    # Populate shell paths from which results and fallback locations
    shellPaths = ['/bin', '/usr/bin', '/usr/local/bin', '/opt/homebrew/bin']

    # Order shells based on user preference
    shellOrder = ['bash', 'zsh'] if preferBash else ['zsh', 'bash']
    supportedShells = []
    for shell in shellOrder:
        for path in shellPaths:
            supportedShells.append(f"{path}/{shell}")

    # Add discovered paths to the beginning of our search list
    # Put the user's preferred shell type first
    if preferBash:
        if bashPath:
            supportedShells.insert(0, bashPath)
        if zshPath:
            supportedShells.append(zshPath)
    else:
        if zshPath:
            supportedShells.insert(0, zshPath)
        if bashPath:
            supportedShells.append(bashPath)

    # Always prioritize SHELL env variable if it's a supported shell type
    if isEnvShellSupported and isExecutable(env_shell):
        supportedShells.insert(0, env_shell)

    # Find first valid executable shell
    shellPath = None
    for shell in supportedShells:
        if shell and isExecutable(shell):
            shellPath = shell
            break

    # If no valid shell found, throw a helpful error
    if not shellPath:
        errorMsg = (
            'No suitable shell found. Cortex IDE requires a Posix shell environment. '
            'Please ensure you have a valid shell installed and the SHELL environment variable set.'
        )
        logError(Exception(errorMsg))
        raise Exception(errorMsg)

    return shellPath


@lru_cache(maxsize=None)
async def getShellConfig() -> ShellConfig:
    """Get shell configuration (memoized per session)"""
    binShell = await findSuitableShell()
    provider = await createBashShellProvider(binShell)
    return ShellConfig(provider)


@lru_cache(maxsize=None)
async def getPsProvider() -> ShellProvider:
    """Get PowerShell provider (memoized per session)"""
    psPath = await getCachedPowerShellPath()
    if not psPath:
        raise Exception('PowerShell is not available')
    return createPowerShellProvider(psPath)


# Provider resolver
async def resolveProvider(shellType: ShellType) -> ShellProvider:
    """Resolve shell provider by type"""
    if shellType == 'bash':
        config = await getShellConfig()
        return config.provider
    elif shellType == 'powershell':
        return await getPsProvider()
    else:
        raise ValueError(f"Unknown shell type: {shellType}")


# ============================================================
# SHELL EXECUTION
# ============================================================

async def exec(
    command: str,
    abortSignal: asyncio.Event,
    shellType: ShellType,
    options: Optional[ExecOptions] = None,
) -> ShellCommand:
    """
    Execute a shell command using the environment snapshot.
    Creates a new shell process for each command execution.
    """
    if options is None:
        options = ExecOptions()

    timeout = options.timeout or DEFAULT_TIMEOUT

    provider = await resolveProvider(shellType)

    id = f"{hash(command) & 0xFFFF:04x}"

    # Sandbox temp directory
    tmp_base = os.environ.get('CORTEX_CODE_TMPDIR', '/tmp')
    sandboxTmpDir = os.path.join(tmp_base, get_cortex_temp_dir_name())

    # Build the command string
    buildResult = await provider.buildExecCommand(command, {
        'id': id,
        'sandboxTmpDir': sandboxTmpDir if options.shouldUseSandbox else None,
        'useSandbox': options.shouldUseSandbox or False,
    })
    commandString = buildResult['commandString']
    cwdFilePath = buildResult.get('cwdFilePath')

    cwd = pwd()

    # Recover if the current working directory no longer exists on disk
    try:
        Path(cwd).resolve(strict=True)
    except (OSError, RuntimeError):
        fallback = getOriginalCwd()
        logForDebugging(f'Shell CWD "{cwd}" no longer exists, recovering to "{fallback}"')
        try:
            Path(fallback).resolve(strict=True)
            setCwdState(fallback)
            cwd = fallback
        except (OSError, RuntimeError):
            return createFailedCommand(
                f'Working directory "{cwd}" no longer exists. Please restart Cortex from an existing directory.'
            )

    # If already aborted, don't spawn the process at all
    if abortSignal.is_set():
        return createAbortedCommand()

    binShell = provider.shellPath

    # Sandboxed PowerShell handling
    isSandboxedPowerShell = options.shouldUseSandbox and shellType == 'powershell'
    sandboxBinShell = '/bin/sh' if isSandboxedPowerShell else binShell

    if options.shouldUseSandbox:
        commandString = await SandboxManager.wrapWithSandbox(
            commandString,
            sandboxBinShell,
            None,
            abortSignal,
        )
        # Create sandbox temp directory
        try:
            os.makedirs(sandboxTmpDir, mode=0o700, exist_ok=True)
        except Exception as error:
            logForDebugging(f"Failed to create {sandboxTmpDir} directory: {error}")

    spawnBinary = '/bin/sh' if isSandboxedPowerShell else binShell
    shellArgs = ['-c', commandString] if isSandboxedPowerShell else provider.getSpawnArgs(commandString)
    envOverrides = await provider.getEnvironmentOverrides(command)

    # When onStdout is provided, use pipe mode
    usePipeMode = options.onStdout is not None
    taskId = generateTaskId('local_bash')
    taskOutput = TaskOutput(taskId, options.onProgress, not usePipeMode)
    os.makedirs(getTaskOutputDir(), exist_ok=True)

    # Note: File mode output handle not implemented in stub
    # Would need async file operations

    try:
        # Create subprocess
        childProcess = await asyncio.create_subprocess_exec(
            spawnBinary,
            *shellArgs,
            env={
                **subprocessEnv(),
                **({'SHELL': binShell} if shellType == 'bash' else {}),
                'GIT_EDITOR': 'true',
                'CORTEXCODE': '1',
                **envOverrides,
                **(
                    {'CORTEX_CODE_SESSION_ID': getSessionId()}
                    if os.environ.get('USER_TYPE') == 'ant'
                    else {}
                ),
            },
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE if usePipeMode else None,
            stderr=asyncio.subprocess.PIPE if usePipeMode else None,
        )

        shellCommand = wrapSpawn(
            childProcess,
            abortSignal,
            timeout,
            taskOutput,
            options.shouldAutoBackground,
        )

        # In pipe mode, attach the caller's callbacks
        if childProcess.stdout and options.onStdout:
            async def read_stdout():
                while True:
                    chunk = await childProcess.stdout.readline()
                    if not chunk:
                        break
                    options.onStdout(chunk.decode('utf-8', errors='replace'))

            asyncio.create_task(read_stdout())

        # Attach cleanup to the command result
        async def cleanup():
            # Cleanup sandbox
            if options.shouldUseSandbox:
                SandboxManager.cleanupAfterCommand()

            # Update CWD if needed
            # Note: This would need the actual result object
            if not options.preventCwdChanges:
                try:
                    nativeCwdFilePath = (
                        posixPathToWindowsPath(cwdFilePath)
                        if getPlatform() == 'windows'
                        else cwdFilePath
                    )

                    if os.path.exists(nativeCwdFilePath):
                        with open(nativeCwdFilePath, 'r', encoding='utf-8') as f:
                            newCwd = f.read().strip()

                        if getPlatform() == 'windows':
                            newCwd = posixPathToWindowsPath(newCwd)

                        # Normalize for comparison
                        if Path(newCwd).resolve() != Path(cwd).resolve():
                            setCwd(newCwd, cwd)
                            invalidateSessionEnvCache()
                            await onCwdChangedForHooks(cwd, newCwd)
                except Exception:
                    pass

            # Clean up temp file
            try:
                nativeCwdFilePath = (
                    posixPathToWindowsPath(cwdFilePath)
                    if getPlatform() == 'windows'
                    else cwdFilePath
                )
                if os.path.exists(nativeCwdFilePath):
                    os.unlink(nativeCwdFilePath)
            except Exception:
                pass

        # Schedule cleanup (would need proper integration with shellCommand.result)
        # For now, we'll schedule it but note this is incomplete

        return shellCommand

    except Exception as error:
        logForDebugging(f"Shell exec error: {errorMessage(error)}")
        return createAbortedCommand(
            code=126,  # Standard Unix code for execution errors
            stderr=errorMessage(error)
        )


# ============================================================
# CWD MANAGEMENT
# ============================================================

def setCwd(path: str, relativeTo: Optional[str] = None) -> None:
    """Set the current working directory"""
    fs = getFsImplementation()

    if os.path.isabs(path):
        resolved = path
    else:
        resolved = os.path.join(relativeTo or fs.cwd(), path)
        resolved = os.path.abspath(resolved)

    # Resolve symlinks to match the behavior of pwd -P
    try:
        physicalPath = fs.realpathSync(resolved)
    except Exception as e:
        if isENOENT(e):
            raise Exception(f'Path "{resolved}" does not exist')
        raise

    setCwdState(physicalPath)

    if os.environ.get('NODE_ENV') != 'test':
        try:
            from .analytics import logEvent
            logEvent('tengu_shell_set_cwd', {'success': True})
        except Exception:
            # Ignore logging errors
            pass
