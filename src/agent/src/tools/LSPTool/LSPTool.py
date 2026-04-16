"""
LSPTool - Language Server Protocol tool for code intelligence.

Provides access to LSP features like go-to-definition, find-references,
hover information, document symbols, and call hierarchy.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Union

# Defensive imports
try:
    from ...services.lsp.lspManager import (
        get_initialization_status,
        get_lsp_server_manager,
        is_lsp_connected,
        wait_for_initialization,
    )
    # Camel-case wrappers for backward compatibility
    getInitializationStatus = get_initialization_status
    getLspServerManager = get_lsp_server_manager
    isLspConnected = is_lsp_connected
    waitForInitialization = wait_for_initialization
except ImportError:
    def getInitializationStatus():
        return {'initialized': False}
    
    def getLspServerManager():
        return None
    
    def isLspConnected():
        return False
    
    async def waitForInitialization(timeout=5000):
        return False

try:
    from ...Tool import buildTool, ToolDef, ValidationResult
except ImportError:
    class ValidationResult(TypedDict, total=False):
        result: bool
        message: str
        errorCode: int
    
    def buildTool(**kwargs):
        return kwargs

try:
    from ...utils.array import uniq
except ImportError:
    def uniq(lst):
        return list(dict.fromkeys(lst))

try:
    from ...utils.cwd import getCwd
except ImportError:
    def getCwd():
        return os.getcwd()

try:
    from ...utils.debug import logForDebugging
except ImportError:
    def logForDebugging(msg, **kwargs):
        pass

try:
    from ...utils.errors import isENOENT, toError, errorMessage
except ImportError:
    def isENOENT(error):
        return getattr(error, 'errno', None) == 2
    
    def toError(value):
        return value if isinstance(value, Exception) else Exception(str(value))
    
    def errorMessage(error):
        return str(error)

try:
    from ...utils.execFileNoThrow import execFileNoThrowWithCwd
except ImportError:
    async def execFileNoThrowWithCwd(cmd, args, cwd=None):
        return {'stdout': '', 'stderr': '', 'exitCode': 1}

try:
    from ...utils.fsOperations import getFsImplementation
except ImportError:
    def getFsImplementation():
        import os as _os
        class MockFS:
            def readSync(self, path, options=None):
                with open(path, 'rb') as f:
                    length = options.get('length') if options else None
                    data = f.read(length) if length else f.read()
                    from types import SimpleNamespace
                    return SimpleNamespace(buffer=data, bytesRead=len(data))
        return MockFS()

try:
    from ...utils.path import expandPath
except ImportError:
    def expandPath(path):
        return os.path.expanduser(os.path.expandvars(path))

try:
    from ...utils.permissions.filesystem import checkReadPermissionForTool
except ImportError:
    async def checkReadPermissionForTool(file_path, context):
        return {'decision': 'allow'}

try:
    from .formatters import (
        formatDocumentSymbolResult,
        formatFindReferencesResult,
        formatGoToDefinitionResult,
        formatHoverResult,
        formatIncomingCallsResult,
        formatOutgoingCallsResult,
        formatPrepareCallHierarchyResult,
        formatWorkspaceSymbolResult,
    )
except ImportError:
    def formatGoToDefinitionResult(*args, **kwargs):
        return ''
    
    def formatFindReferencesResult(*args, **kwargs):
        return ''
    
    def formatHoverResult(*args, **kwargs):
        return ''
    
    def formatDocumentSymbolResult(*args, **kwargs):
        return ''
    
    def formatWorkspaceSymbolResult(*args, **kwargs):
        return ''
    
    def formatPrepareCallHierarchyResult(*args, **kwargs):
        return ''
    
    def formatIncomingCallsResult(*args, **kwargs):
        return ''
    
    def formatOutgoingCallsResult(*args, **kwargs):
        return ''

try:
    from .prompt import DESCRIPTION, LSP_TOOL_NAME
except ImportError:
    LSP_TOOL_NAME = 'LSP'
    DESCRIPTION = '''Interact with Language Server Protocol (LSP) servers to get code intelligence features.

Supported operations:
- goToDefinition: Find where a symbol is defined
- findReferences: Find all references to a symbol
- hover: Get hover information (documentation, type info) for a symbol
- documentSymbol: Get all symbols (functions, classes, variables) in a document
- workspaceSymbol: Search for symbols across the entire workspace
- goToImplementation: Find implementations of an interface or abstract method
- prepareCallHierarchy: Get call hierarchy item at a position (functions/methods)
- incomingCalls: Find all functions/methods that call the function at a position
- outgoingCalls: Find all functions/methods called by the function at a position

All operations require:
- filePath: The file to operate on
- line: The line number (1-based, as shown in editors)
- character: The character offset (1-based, as shown in editors)

Note: LSP servers must be configured for the file type. If no server is available, an error will be returned.'''

try:
    from .schemas import lspToolInputSchema, isValidLSPOperation
except ImportError:
    VALID_OPERATIONS = [
        'goToDefinition',
        'findReferences',
        'hover',
        'documentSymbol',
        'workspaceSymbol',
        'goToImplementation',
        'prepareCallHierarchy',
        'incomingCalls',
        'outgoingCalls',
    ]
    
    def isValidLSPOperation(operation):
        return operation in VALID_OPERATIONS

try:
    from .UI import (
        renderToolResultMessage,
        renderToolUseErrorMessage,
        renderToolUseMessage,
        userFacingName,
    )
except ImportError:
    def renderToolUseMessage(*args, **kwargs):
        return ''
    
    def renderToolResultMessage(*args, **kwargs):
        return ''
    
    def renderToolUseErrorMessage(*args, **kwargs):
        return ''
    
    def userFacingName():
        return 'LSP'


MAX_LSP_FILE_SIZE_BYTES = 10_000_000  # 10 MB


class Input(TypedDict):
    """Input schema for LSPTool."""
    operation: str
    filePath: str
    line: int
    character: int


class Output(TypedDict, total=False):
    """Output schema for LSPTool."""
    operation: str
    success: bool
    result: Optional[str]
    error: Optional[str]


async def validateInput(input_data: Input, context) -> ValidationResult:
    """Validate LSP tool input."""
    operation = input_data.get('operation')
    file_path = input_data.get('filePath')
    line = input_data.get('line')
    character = input_data.get('character')
    
    # Validate operation
    if not isValidLSPOperation(operation):
        return {
            'result': False,
            'message': f'Invalid operation: {operation}. Valid operations: {", ".join(VALID_OPERATIONS if "VALID_OPERATIONS" in globals() else ["goToDefinition", "findReferences", "hover"])}',
            'errorCode': 1,
        }
    
    # Validate file path
    if not file_path:
        return {
            'result': False,
            'message': 'filePath is required',
            'errorCode': 1,
        }
    
    # Validate line and character
    if line is None or line < 1:
        return {
            'result': False,
            'message': 'line must be a positive integer (1-based)',
            'errorCode': 1,
        }
    
    if character is None or character < 1:
        return {
            'result': False,
            'message': 'character must be a positive integer (1-based)',
            'errorCode': 1,
        }
    
    # Check file exists and is readable
    try:
        absolute_path = expandPath(file_path)
        path_obj = Path(absolute_path)
        
        if not path_obj.exists():
            return {
                'result': False,
                'message': f'File not found: {file_path}',
                'errorCode': 1,
            }
        
        if not path_obj.is_file():
            return {
                'result': False,
                'message': f'Not a file: {file_path}',
                'errorCode': 1,
            }
        
        # Check file size
        file_size = path_obj.stat().st_size
        if file_size > MAX_LSP_FILE_SIZE_BYTES:
            return {
                'result': False,
                'message': f'File too large ({file_size} bytes). Maximum size: {MAX_LSP_FILE_SIZE_BYTES} bytes',
                'errorCode': 1,
            }
        
    except Exception as e:
        return {
            'result': False,
            'message': f'Error accessing file: {errorMessage(e)}',
            'errorCode': 1,
        }
    
    return {'result': True}


async def call(input_data: Input, context) -> Dict[str, Any]:
    """Execute LSP operation."""
    operation = input_data['operation']
    file_path = input_data['filePath']
    line = input_data['line']  # 1-based
    character = input_data['character']  # 1-based
    
    # Convert to 0-based for LSP protocol
    zero_based_line = line - 1
    zero_based_character = character - 1
    
    try:
        # Wait for LSP initialization
        initialized = await waitForInitialization(timeout=5000)
        if not initialized:
            return {
                'data': {
                    'operation': operation,
                    'success': False,
                    'error': 'LSP server not initialized. Please wait for language server to start.',
                },
            }
        
        # Check if LSP is connected
        if not isLspConnected():
            return {
                'data': {
                    'operation': operation,
                    'success': False,
                    'error': 'LSP server not connected. No language server available for this file type.',
                },
            }
        
        # Expand file path
        absolute_path = expandPath(file_path)
        
        # Get LSP server manager
        manager = getLspServerManager()
        if not manager:
            return {
                'data': {
                    'operation': operation,
                    'success': False,
                    'error': 'LSP server manager not available',
                },
            }
        
        # Execute the requested operation
        result = await executeLSPOperation(
            manager,
            operation,
            absolute_path,
            zero_based_line,
            zero_based_character,
        )
        
        return {
            'data': {
                'operation': operation,
                'success': True,
                'result': result,
            },
        }
    
    except Exception as error:
        logForDebugging(f'LSP operation failed: {errorMessage(error)}', {'level': 'error'})
        return {
            'data': {
                'operation': operation,
                'success': False,
                'error': f'LSP operation failed: {errorMessage(error)}',
            },
        }


async def executeLSPOperation(
    manager,
    operation: str,
    file_path: str,
    line: int,
    character: int,
) -> str:
    """Execute a specific LSP operation and format the result."""
    # This would call the actual LSP methods via the manager
    # For now, return placeholder - actual implementation depends on LSP client library
    
    if operation == 'goToDefinition':
        # result = await manager.goToDefinition(file_path, line, character)
        # return formatGoToDefinitionResult(result, getCwd())
        return 'goToDefinition: Not yet implemented - requires LSP client integration'
    
    elif operation == 'findReferences':
        return 'findReferences: Not yet implemented - requires LSP client integration'
    
    elif operation == 'hover':
        return 'hover: Not yet implemented - requires LSP client integration'
    
    elif operation == 'documentSymbol':
        return 'documentSymbol: Not yet implemented - requires LSP client integration'
    
    elif operation == 'workspaceSymbol':
        return 'workspaceSymbol: Not yet implemented - requires LSP client integration'
    
    elif operation == 'goToImplementation':
        return 'goToImplementation: Not yet implemented - requires LSP client integration'
    
    elif operation == 'prepareCallHierarchy':
        return 'prepareCallHierarchy: Not yet implemented - requires LSP client integration'
    
    elif operation == 'incomingCalls':
        return 'incomingCalls: Not yet implemented - requires LSP client integration'
    
    elif operation == 'outgoingCalls':
        return 'outgoingCalls: Not yet implemented - requires LSP client integration'
    
    else:
        return f'Unknown operation: {operation}'


def mapToolResultToToolResultBlockParam(content: Output, toolUseID: str) -> Dict[str, Any]:
    """Map tool output to Anthropic API tool result block."""
    if content.get('success'):
        return {
            'tool_use_id': toolUseID,
            'type': 'tool_result',
            'content': content.get('result', ''),
        }
    
    return {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': f'Error: {content.get("error")}',
        'is_error': True,
    }


# Build the tool definition
LSPTool = buildTool(
    name=LSP_TOOL_NAME,
    searchHint='get code intelligence via Language Server Protocol (go to definition, find references, etc.)',
    maxResultSizeChars=100_000,
    description=lambda: DESCRIPTION,
    prompt=lambda: DESCRIPTION,
    userFacingName=userFacingName,
    isConcurrencySafe=lambda: True,
    isReadOnly=lambda input_data: True,  # All LSP operations are read-only
    toAutoClassifierInput=lambda input_data: f'{input_data["operation"]} {input_data["filePath"]}:{input_data["line"]}:{input_data["character"]}',
    validateInput=validateInput,
    renderToolUseMessage=renderToolUseMessage,
    renderToolResultMessage=renderToolResultMessage,
    renderToolUseErrorMessage=renderToolUseErrorMessage,
    call=call,
    mapToolResultToToolResultBlockParam=mapToolResultToToolResultBlockParam,
)
