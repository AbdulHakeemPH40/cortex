"""
TaskCreateTool - Create a new task in the task list.

Allows the AI agent to create structured tasks for tracking progress,
organizing complex work, and demonstrating thoroughness to users.
"""

from typing import Any, Dict, Optional, TypedDict

# Defensive imports
try:
    from ...Tool import buildTool, ToolDef
except ImportError:
    def buildTool(**kwargs):
        return kwargs
    
    class ToolDef:
        pass

try:
    from ...utils.hooks import executeTaskCreatedHooks, getTaskCreatedHookMessage
except ImportError:
    async def executeTaskCreatedHooks(*args, **kwargs):
        # Return empty generator
        for item in []:
            yield item
    
    def getTaskCreatedHookMessage(error):
        return str(error)

try:
    from ...utils.tasks import createTask, deleteTask, getTaskListId, isTodoV2Enabled
except ImportError:
    async def createTask(task_list_id, task_data):
        return 'task-123'  # Mock ID
    
    async def deleteTask(task_list_id, task_id):
        pass
    
    def getTaskListId():
        return 'default-list'
    
    def isTodoV2Enabled():
        return True

try:
    from ...utils.teammate import getAgentName, getTeamName
except ImportError:
    def getAgentName():
        return None
    
    def getTeamName():
        return None

try:
    from .constants import TASK_CREATE_TOOL_NAME
except ImportError:
    TASK_CREATE_TOOL_NAME = 'TaskCreate'

try:
    from .prompt import DESCRIPTION, getPrompt
except ImportError:
    DESCRIPTION = 'Create a new task in the task list'
    
    def getPrompt():
        return DESCRIPTION


class Input(TypedDict, total=False):
    """Input schema for TaskCreateTool."""
    subject: str
    description: str
    activeForm: Optional[str]
    metadata: Optional[Dict[str, Any]]


class Output(TypedDict):
    """Output schema for TaskCreateTool."""
    task: Dict[str, str]


async def call(input_data: Input, context) -> Dict[str, Any]:
    """Execute TaskCreateTool - create a new task."""
    subject = input_data['subject']
    description = input_data['description']
    active_form = input_data.get('activeForm')
    metadata = input_data.get('metadata')
    
    # Create the task
    task_id = await createTask(getTaskListId(), {
        'subject': subject,
        'description': description,
        'activeForm': active_form,
        'status': 'pending',
        'owner': None,
        'blocks': [],
        'blockedBy': [],
        'metadata': metadata,
    })
    
    # Execute task created hooks
    blocking_errors = []
    generator = executeTaskCreatedHooks(
        task_id,
        subject,
        description,
        getAgentName(),
        getTeamName(),
        None,  # owner
        getattr(context, 'abortController', None).signal if hasattr(context, 'abortController') and context.abortController else None,
        None,  # teammateId
        context,
    )
    
    async for result in generator:
        if result.get('blockingError'):
            blocking_errors.append(getTaskCreatedHookMessage(result['blockingError']))
    
    # If any blocking errors occurred, delete the task and raise error
    if len(blocking_errors) > 0:
        await deleteTask(getTaskListId(), task_id)
        raise Exception('\n'.join(blocking_errors))
    
    # Auto-expand task list when creating tasks
    context.setAppState(lambda prev: {
        **prev,
        'expandedView': 'tasks',
    } if prev.get('expandedView') != 'tasks' else prev)
    
    return {
        'data': {
            'task': {
                'id': task_id,
                'subject': subject,
            },
        },
    }


def mapToolResultToToolResultBlockParam(content: Output, toolUseID: str) -> Dict[str, Any]:
    """Map tool output to Anthropic API tool result block."""
    task = content['task']
    return {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': f'Task #{task["id"]} created successfully: {task["subject"]}',
    }


def toAutoClassifierInput(input_data: Input) -> str:
    """Convert input to auto-classifier format."""
    return input_data['subject']


def renderToolUseMessage(*args, **kwargs):
    """Render tool use message (suppressed for TaskCreate)."""
    return None


# Build the tool definition
TaskCreateTool = buildTool(
    name=TASK_CREATE_TOOL_NAME,
    searchHint='create a task in the task list',
    maxResultSizeChars=100_000,
    description=lambda: DESCRIPTION,
    prompt=getPrompt,
    userFacingName=lambda: 'TaskCreate',
    shouldDefer=True,
    isEnabled=isTodoV2Enabled,
    isConcurrencySafe=lambda: True,
    toAutoClassifierInput=toAutoClassifierInput,
    renderToolUseMessage=renderToolUseMessage,
    call=call,
    mapToolResultToToolResultBlockParam=mapToolResultToToolResultBlockParam,
)
