"""
LSPTool schemas and input validation.

Defines the discriminated union of all LSP operations with their parameters.
"""

from typing import Literal, TypedDict


# Valid LSP operations
LSPOperation = Literal[
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


class GoToDefinitionInput(TypedDict):
    """Go to Definition operation - finds where a symbol is defined."""
    operation: Literal['goToDefinition']
    filePath: str
    line: int
    character: int


class FindReferencesInput(TypedDict):
    """Find References operation - finds all references to a symbol."""
    operation: Literal['findReferences']
    filePath: str
    line: int
    character: int


class HoverInput(TypedDict):
    """Hover operation - gets hover information (documentation, type info)."""
    operation: Literal['hover']
    filePath: str
    line: int
    character: int


class DocumentSymbolInput(TypedDict):
    """Document Symbol operation - gets all symbols in a document."""
    operation: Literal['documentSymbol']
    filePath: str
    line: int
    character: int


class WorkspaceSymbolInput(TypedDict):
    """Workspace Symbol operation - searches for symbols across workspace."""
    operation: Literal['workspaceSymbol']
    filePath: str
    line: int
    character: int


class GoToImplementationInput(TypedDict):
    """Go to Implementation operation - finds implementations of interface/abstract method."""
    operation: Literal['goToImplementation']
    filePath: str
    line: int
    character: int


class PrepareCallHierarchyInput(TypedDict):
    """Prepare Call Hierarchy operation - prepares call hierarchy item at position."""
    operation: Literal['prepareCallHierarchy']
    filePath: str
    line: int
    character: int


class IncomingCallsInput(TypedDict):
    """Incoming Calls operation - finds functions/methods that call the function at position."""
    operation: Literal['incomingCalls']
    filePath: str
    line: int
    character: int


class OutgoingCallsInput(TypedDict):
    """Outgoing Calls operation - finds functions/methods called by the function at position."""
    operation: Literal['outgoingCalls']
    filePath: str
    line: int
    character: int


# Union type for all LSP inputs
LSPToolInput = (
    GoToDefinitionInput
    | FindReferencesInput
    | HoverInput
    | DocumentSymbolInput
    | WorkspaceSymbolInput
    | GoToImplementationInput
    | PrepareCallHierarchyInput
    | IncomingCallsInput
    | OutgoingCallsInput
)


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


def isValidLSPOperation(operation: str) -> bool:
    """Type guard to check if an operation is a valid LSP operation."""
    return operation in VALID_OPERATIONS
