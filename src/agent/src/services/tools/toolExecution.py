# ------------------------------------------------------------
# toolExecution.py
# Python conversion of services/tools/toolExecution.ts (1746 lines)
# Phase 1: Imports, Constants, Type Stubs, Core Helpers
# ------------------------------------------------------------

import asyncio
import json
import os
import re
import time
from typing import (
    Any, AsyncGenerator, Callable, Dict, List, Literal,
    Optional, Sequence, TypeVar, Union,
)

T = TypeVar("T")

# ============================================================
# DEPS — defensive fallbacks for unconverted cross-modules
# ============================================================

try:
    from bun.bundle import feature
except ImportError:
    def feature(_: str) -> bool:
        return False


try:
    from ...services.analytics.index import log_event
except ImportError:
    def log_event(_: str, __: Dict) -> None:
        pass


try:
    from ...services.analytics.metadata import (
        extract_mcp_tool_details,
        extract_skill_name,
        extract_tool_input_for_telemetry,
        get_file_extension_for_analytics,
        get_file_extensions_from_bash_command,
        is_tool_details_logging_enabled,
        mcp_tool_details_for_analytics,
        sanitize_tool_name_for_analytics,
    )
except ImportError:
    sanitize_tool_name_for_analytics = lambda n: n
    extract_tool_input_for_telemetry = lambda _: None
    extract_skill_name = lambda *_: None
    extract_mcp_tool_details = lambda _: None
    mcp_tool_details_for_analytics = lambda *_, **__: {}
    get_file_extension_for_analytics = lambda _: None
    get_file_extensions_from_bash_command = lambda *_, **__: None
    is_tool_details_logging_enabled = lambda: False


try:
    from ...bootstrap.state import add_to_tool_duration, get_code_edit_tool_decision_counter, get_stats_store
except ImportError:
    add_to_tool_duration = lambda *_: None
    get_stats_store = lambda: None
    get_code_edit_tool_decision_counter = lambda: None


try:
    from ...hooks.toolPermission.permissionLogging import build_code_edit_tool_attributes, is_code_editing_tool
except ImportError:
    is_code_editing_tool = lambda _: False
    build_code_edit_tool_attributes = lambda *_, **__: {}


try:
    from ...Tool import find_tool_by_name, Tool, ToolProgress, ToolUseContext
except ImportError:
    Tool = Any
    ToolProgress = Dict
    ToolUseContext = Dict

    def find_tool_by_name(tools: Any, name: str) -> Optional[Any]:
        if not tools:
            return None
        for t in tools:
            if getattr(t, "name", None) == name:
                return t
        return None


try:
    from ...tools.BashTool.BashTool import BashToolInput
except ImportError:
    BashToolInput = Dict[str, Any]


try:
    from ...tools.BashTool.bashPermissions import start_speculative_classifier_check
except ImportError:
    def start_speculative_classifier_check(*_, **__): pass


try:
    from ...tools.BashTool.toolName import BASH_TOOL_NAME
except ImportError:
    BASH_TOOL_NAME = "Bash"


try:
    from ...tools.FileEditTool.completed.constants import FILE_EDIT_TOOL_NAME
except ImportError:
    FILE_EDIT_TOOL_NAME = "Edit"


try:
    from ...tools.FileReadTool.prompt import FILE_READ_TOOL_NAME
except ImportError:
    FILE_READ_TOOL_NAME = "Read"


try:
    from ...tools.FileWriteTool.prompt import FILE_WRITE_TOOL_NAME
except ImportError:
    FILE_WRITE_TOOL_NAME = "Write"


try:
    from ...tools.NotebookEditTool.constants import NOTEBOOK_EDIT_TOOL_NAME
except ImportError:
    NOTEBOOK_EDIT_TOOL_NAME = "NotebookEdit"


try:
    from ...tools.PowerShellTool.toolName import POWERSHELL_TOOL_NAME
except ImportError:
    POWERSHELL_TOOL_NAME = "PowerShell"


try:
    from ...tools.shared.gitOperationTracking import parse_git_commit_id
except ImportError:
    def parse_git_commit_id(_: str) -> Optional[str]:
        return None


try:
    from ...tools.ToolSearchTool.prompt import is_deferred_tool, TOOL_SEARCH_TOOL_NAME
except ImportError:
    is_deferred_tool = lambda _: False
    TOOL_SEARCH_TOOL_NAME = "ToolSearch"


try:
    from ...tool_registry import get_all_base_tools
except ImportError:
    def get_all_base_tools() -> List:
        return []


try:
    from ...agent_types.hooks import HookProgress
except ImportError:
    HookProgress = Dict[str, Any]


try:
    from ...agent_types.message import (
        AssistantMessage, AttachmentMessage, Message, ProgressMessage, StopHookInfo,
    )
except ImportError:
    AssistantMessage = Dict
    AttachmentMessage = Dict
    Message = Dict
    ProgressMessage = Dict
    StopHookInfo = Dict


try:
    from ...utils.array import count as array_count
except ImportError:
    def array_count(items: List, pred: Callable) -> int:
        return sum(1 for x in items if pred(x))


try:
    from ...utils.attachments import create_attachment_message
except ImportError:
    def create_attachment_message(attachment: Dict) -> Dict:
        return {"type": "attachment", "attachment": attachment}


try:
    from ...utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(msg: str, **kw) -> None:
        print(f"[DEBUG] {msg}", flush=True)


try:
    from ...utils.errors import AbortError, ShellError, TelemetrySafeError, error_message, get_errno_code
except ImportError:
    class AbortError(Exception): pass
    class ShellError(Exception): pass
    class TelemetrySafeError(Exception):
        telemetry_message = ""
    def error_message(e: Any) -> str:
        if isinstance(e, Exception):
            return str(getattr(e, "message", "") or e)
        return str(e) if e else ""
    def get_errno_code(e: Exception) -> Optional[str]:
        return getattr(e, "code", None)


try:
    from ...utils.hooks import execute_permission_denied_hooks
except ImportError:
    async def execute_permission_denied_hooks(*_, **__):
        return
        yield


try:
    from ...utils.log import log_error
except ImportError:
    def log_error(e: Any) -> None:
        print(f"[ERROR] {e}", flush=True)


try:
    from ...utils.messages import (
        CANCEL_MESSAGE,
        create_progress_message,
        create_stop_hook_summary_message,
        create_tool_result_stop_message,
        create_user_message,
        with_memory_correction_hint,
    )
except ImportError:
    CANCEL_MESSAGE = "Cancelled."

    def with_memory_correction_hint(msg: str) -> str:
        return msg

    def create_progress_message(**kw) -> Dict:
        return {"type": "progress", **kw}

    def create_tool_result_stop_message(tool_use_id: str) -> Dict:
        return {"type": "tool_result", "content": "Stopped.", "tool_use_id": tool_use_id}

    def create_user_message(**kw) -> Dict:
        return {"type": "user", **kw}

    def create_stop_hook_summary_message(*_, **__):
        return {"type": "stop_hook_summary"}


try:
    from ...utils.permissions.PermissionResult import PermissionDecisionReason, PermissionResult
except ImportError:
    PermissionResult = Dict[str, Any]
    PermissionDecisionReason = Dict[str, Any]


try:
    from ...utils.sessionActivity import start_session_activity, stop_session_activity
except ImportError:
    start_session_activity = stop_session_activity = lambda *_: None


try:
    from ...utils.slowOperations import json_stringify
except ImportError:
    def json_stringify(obj: Any) -> str:
        if isinstance(obj, str):
            return obj
        return json.dumps(obj, default=str)


try:
    from ...utils.stream import Stream
except ImportError:
    class Stream(AsyncGenerator[T, None]):
        def __init__(self, _=None):
            self._queue: List[T] = []
            self._is_done = False
            self._has_error: Any = None
            self._started = False
            self._read_resolve: Any = None
            self._read_reject: Any = None

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._is_done:
                raise StopAsyncIteration
            if self._has_error:
                raise self._has_error
            if self._queue:
                return self._queue.pop(0)
            future = asyncio.get_running_loop().create_future()
            self._read_resolve = future.set_result
            self._read_reject = future.set_exception
            try:
                return await future
            finally:
                self._read_resolve = None
                self._read_reject = None

        def enqueue(self, value: T):
            self._queue.append(value)

        def done(self):
            self._is_done = True

        def error(self, err: Exception):
            self._has_error = err


try:
    from ...utils.telemetry.events import log_otel_event
except ImportError:
    def log_otel_event(_: str, __: Dict) -> None:
        pass


try:
    from ...utils.telemetry.sessionTracing import (
        add_tool_content_event,
        end_tool_blocked_on_user_span,
        end_tool_execution_span,
        end_tool_span,
        is_beta_tracing_enabled,
        start_tool_blocked_on_user_span,
        start_tool_execution_span,
        start_tool_span,
    )
except ImportError:
    def is_beta_tracing_enabled() -> bool:
        return False
    start_tool_span = end_tool_span = start_tool_blocked_on_user_span = \
    end_tool_blocked_on_user_span = start_tool_execution_span = \
    end_tool_execution_span = add_tool_content_event = lambda *_, **__: None


try:
    from ...utils.toolErrors import format_error, format_zod_validation_error
except ImportError:
    def format_error(e: Any) -> str:
        return str(e) if e else "Unknown error"
    def format_zod_validation_error(_: str, e: Any) -> str:
        return str(e)


try:
    from ...utils.toolResultStorage import (
        process_pre_mapped_tool_result_block,
        process_tool_result_block,
    )
except ImportError:
    async def process_tool_result_block(*_) -> Dict:
        return {"type": "tool_result", "content": ""}
    async def process_pre_mapped_tool_result_block(block: Dict, *_) -> Dict:
        return block


try:
    from ...utils.toolSearch import (
        extract_discovered_tool_names,
        is_tool_search_enabled_optimistic,
        is_tool_search_tool_available,
    )
except ImportError:
    is_tool_search_enabled_optimistic = lambda: False
    is_tool_search_tool_available = lambda _: False
    def extract_discovered_tool_names(_: List) -> set:
        return set()


try:
    from ...services.mcp.client import McpAuthError, McpToolCallError
except ImportError:
    class McpAuthError(Exception):
        server_name = ""
    class McpToolCallError(Exception):
        mcp_meta: Any = None


try:
    from ...services.mcp.mcpStringUtils import mcp_info_from_string
except ImportError:
    def mcp_info_from_string(tool_name: str) -> Optional[Dict]:
        if not tool_name.startswith("mcp__"):
            return None
        return {"serverName": tool_name.split("__")[1].split("__")[0]}


try:
    from ...services.mcp.normalization import normalize_name_for_mcp
except ImportError:
    def normalize_name_for_mcp(name: str) -> str:
        return name.lower().replace(" ", "_")


try:
    from ...services.mcp.types import MCPServerConnection
except ImportError:
    MCPServerConnection = Dict[str, Any]


try:
    from ...services.mcp.utils import (
        get_logging_safe_mcp_base_url,
        get_mcp_server_scope_from_tool_name,
        is_mcp_tool,
    )
except ImportError:
    def get_logging_safe_mcp_base_url(_: Dict) -> Optional[str]:
        return None
    def get_mcp_server_scope_from_tool_name(_: str) -> Optional[str]:
        return None
    def is_mcp_tool(tool: Any) -> bool:
        return getattr(tool, "is_mcp", False)


try:
    from ...services.tools.toolHooks import (
        resolve_hook_permission_decision,
        run_post_tool_use_failure_hooks,
        run_post_tool_use_hooks,
        run_pre_tool_use_hooks,
    )
except ImportError:
    async def run_pre_tool_use_hooks(*_, **__):
        return
        yield
    async def run_post_tool_use_hooks(*_, **__):
        return
        yield
    async def run_post_tool_use_failure_hooks(*_, **__):
        return
        yield
    def resolve_hook_permission_decision(*args) -> Dict:
        return {
            "decision": {"behavior": "allow"},
            "input": args[2] if len(args) > 2 else {},
        }


# ============================================================
# CONSTANTS
# ============================================================

HOOK_TIMING_DISPLAY_THRESHOLD_MS = 500
SLOW_PHASE_LOG_THRESHOLD_MS = 2000


# ============================================================
# CORE HELPERS
# ============================================================

def classify_tool_error(error: Any) -> str:
    """
    Classify a tool execution error into a telemetry-safe string.

    - TelemetrySafeError: use its telemetryMessage
    - Node.js fs errors: log the error code (ENOENT, EACCES, etc.)
    - Known error types with stable .name: use unminified name
    - Fallback: "Error"
    - Non-Error: "UnknownError"
    """
    if isinstance(error, TelemetrySafeError):
        return error.telemetry_message[:200]
    if isinstance(error, Exception):
        errno_code = get_errno_code(error)
        if isinstance(errno_code, str):
            return f"Error:{errno_code}"
        error_name = getattr(error, "name", None)
        if error_name and error_name != "Error" and len(error_name) > 3:
            return error_name[:60]
        return "Error"
    return "UnknownError"


def rule_source_to_otel_source(
    rule_source: str,
    behavior: Literal["allow", "deny"],
) -> str:
    """Map a rule's origin to OTel source vocabulary."""
    if rule_source == "session":
        return "user_temporary" if behavior == "allow" else "user_reject"
    elif rule_source in ("localSettings", "userSettings"):
        return "user_permanent" if behavior == "allow" else "user_reject"
    return "config"


def decision_reason_to_otel_source(
    reason: Optional[PermissionDecisionReason],
    behavior: Literal["allow", "deny"],
) -> str:
    """
    Map a PermissionDecisionReason to OTel source label.

    For permissionPromptTool: uses decisionClassification if available.
    For rule: delegates to ruleSourceToOTelSource.
    For hook: returns 'hook'.
    For everything else: returns 'config'.
    """
    if not reason:
        return "config"

    reason_type = reason.get("type")

    if reason_type == "permissionPromptTool":
        tool_result: Optional[Dict] = reason.get("toolResult")
        classified: Optional[str] = (
            tool_result.get("decisionClassification")
            if tool_result
            else None
        )
        if classified in ("user_temporary", "user_permanent", "user_reject"):
            return classified
        return "user_temporary" if behavior == "allow" else "user_reject"

    elif reason_type == "rule":
        return rule_source_to_otel_source(
            reason.get("rule", {}).get("source", ""),
            behavior,
        )

    elif reason_type == "hook":
        return "hook"

    elif reason_type in (
        "mode", "classifier", "subcommandResults", "asyncAgent",
        "sandboxOverride", "workingDir", "safetyCheck", "other"
    ):
        return "config"

    else:
        return "config"


def get_next_image_paste_id(messages: List[Message]) -> int:
    """Generate the next available image paste ID from existing messages."""
    max_id = 0
    for message in messages:
        if message.get("type") == "user":
            for id_val in message.get("imagePasteIds", []):
                if id_val > max_id:
                    max_id = id_val
    return max_id + 1


# ============================================================
# MCP SERVER UTILITIES
# ============================================================

McpServerType = Optional[
    Literal[
        "stdio", "sse", "http", "ws", "sdk",
        "sse-ide", "ws-ide", "claudeai-proxy",
    ]
]


def find_mcp_server_connection(
    tool_name: str,
    mcp_clients: List[MCPServerConnection],
) -> Optional[MCPServerConnection]:
    """Find an MCP server connection by tool name prefix 'mcp__'."""
    if not tool_name.startswith("mcp__"):
        return None

    mcp_info = mcp_info_from_string(tool_name)
    if not mcp_info:
        return None

    server_name: str = mcp_info.get("serverName", "")

    for client in mcp_clients:
        if normalize_name_for_mcp(client.get("name", "")) == server_name:
            return client

    return None


def get_mcp_server_type(
    tool_name: str,
    mcp_clients: List[MCPServerConnection],
) -> McpServerType:
    """Get the MCP server transport type for a tool, or None if not an MCP tool."""
    server_connection = find_mcp_server_connection(tool_name, mcp_clients)

    if server_connection and server_connection.get("type") == "connected":
        config: Dict = server_connection.get("config", {})
        # stdio configs may omit the type field — defaults to 'stdio'
        return config.get("type") or "stdio"

    return None


def get_mcp_server_base_url_from_tool_name(
    tool_name: str,
    mcp_clients: List[MCPServerConnection],
) -> Optional[str]:
    """
    Get the MCP server base URL for a tool.

    Returns None for stdio servers, built-in tools, or disconnected servers.
    """
    server_connection = find_mcp_server_connection(tool_name, mcp_clients)
    if not server_connection or server_connection.get("type") != "connected":
        return None
    return get_logging_safe_mcp_base_url(server_connection.get("config", {}))


# ============================================================
# ANALYTICS KWARGS HELPER
# ============================================================

def _build_analytics_kwargs(
    tool_name: str,
    tool_use_id: str,
    tool: Any,
    mcp_server_type: McpServerType,
    mcp_server_base_url: Optional[str],
    request_id: Optional[str],
    query_tracking: Optional[Dict],
) -> Dict:
    """Build shared analytics kwargs, skipping None values."""
    result: Dict = {
        "toolName": sanitize_tool_name_for_analytics(tool_name),
        "isMcp": getattr(tool, "is_mcp", False),
        "toolUseID": tool_use_id,
        **mcp_tool_details_for_analytics(tool_name, mcp_server_type, mcp_server_base_url),
    }

    if request_id:
        result["requestId"] = request_id
    if query_tracking:
        result["queryChainId"] = query_tracking.get("chainId")
        result["queryDepth"] = query_tracking.get("depth")
    if mcp_server_type:
        result["mcpServerType"] = mcp_server_type
    if mcp_server_base_url:
        result["mcpServerBaseUrl"] = mcp_server_base_url

    return result


# ============================================================
# SCHEMA NOT-SENT HINT
# ============================================================

def build_schema_not_sent_hint(
    tool: Tool,
    messages: List[Message],
    tools: Sequence[Any],
) -> Optional[str]:
    """
    Appended to Zod errors when a deferred tool wasn't in the discovered-tool set.

    Re-runs the tool-search scan dispatch-time to detect the mismatch.
    Returns None if the schema was sent (tool is in discovered set).
    """
    if not is_tool_search_enabled_optimistic():
        return None
    if not is_tool_search_tool_available(list(tools)):
        return None
    if not is_deferred_tool(tool):
        return None

    discovered = extract_discovered_tool_names(messages)
    if tool.name in discovered:
        return None

    return (
        f"\n\nThis tool's schema was not sent to the API — it was not in the "
        f"discovered-tool set derived from message history. "
        f"Without the schema in your prompt, typed parameters (arrays, numbers, "
        f"booleans) get emitted as strings and the client-side parser rejects them. "
        f'Load the tool first: call {TOOL_SEARCH_TOOL_NAME} with query "select:{tool.name}", '
        f"then retry this call."
    )


# ============================================================
# INPUT VALIDATION (ZOD EQUIVALENT)
# ============================================================

def _safe_parse_input(tool: Tool, input: Dict) -> Dict[str, Any]:
    """
    Validate tool input using the tool's inputSchema.

    Returns {success: bool, data: Any, error: Any}.
    Falls back to accepting input as-is if no schema exists.
    """
    parser = getattr(tool, "input_schema", None)
    if parser is None:
        return {"success": True, "data": input, "error": None}

    try:
        result = parser.safe_parse(input) if hasattr(parser, "safe_parse") else parser(input)
        if hasattr(result, "success"):
            return {
                "success": result.success,
                "data": getattr(result, "data", input),
                "error": getattr(result, "error", None),
            }
        elif isinstance(result, dict):
            return result
        else:
            return {"success": True, "data": input, "error": None}
    except Exception:
        return {"success": True, "data": input, "error": None}


# ============================================================
# PROGRESS HANDLER (for streamed wrapper)
# ============================================================

def _make_progress_handler(
    stream: Stream,
    tool: Any,
    tool_use_id: str,
    tool_use_context: ToolUseContext,
    message_id: str,
    request_id: Optional[str],
    mcp_server_type: McpServerType,
    mcp_server_base_url: Optional[str],
) -> Callable[[ToolProgress], None]:
    """Build the on_tool_progress callback for checkPermissionsAndCallTool."""
    def on_tool_progress(progress: ToolProgress) -> None:
        log_event(
            "tengu_tool_use_progress",
            {
                **_build_analytics_kwargs(
                    tool.name, tool_use_id, tool, mcp_server_type,
                    mcp_server_base_url, request_id,
                    tool_use_context.get("queryTracking"),
                ),
                "messageID": message_id,
            },
        )
        stream.enqueue({
            "message": create_progress_message({
                "toolUseID": progress.get("toolUseID"),
                "parentToolUseID": tool_use_id,
                "data": progress.get("data"),
            }),
        })
    return on_tool_progress


# ============================================================
# ASYNC PROMISE-LIKE FOR STREAMED CALL
# ============================================================

class _AsyncPromise:
    """
    Minimal promise implementation wrapping asyncio.Future.

    Mirrors the TypeScript pattern of chaining .then/.catch/.finally
    on a pending operation to feed results into a Stream.
    """
    def __init__(self):
        self._future: asyncio.Future = asyncio.get_running_loop().create_future()

    def resolve(self, value: Any) -> None:
        if not self._future.done():
            self._future.set_result(value)

    def reject(self, error: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(error)

    def then(
        self,
        on_fulfilled: Callable,
        on_rejected: Optional[Callable] = None,
    ) -> "_AsyncPromise":
        async def _run() -> Any:
            try:
                result = await self._future
                return on_fulfilled(result)
            except Exception as e:
                if on_rejected:
                    return on_rejected(e)
                raise

        asyncio.create_task(_run())
        return self

    def catch(self, on_rejected: Callable) -> "_AsyncPromise":
        return self.then(lambda x: x, on_rejected)

    def finally_(self, on_finally: Callable) -> "_AsyncPromise":
        async def _run() -> Any:
            try:
                return await self._future
            finally:
                on_finally()

        asyncio.create_task(_run())
        return self


# ============================================================
# STREAMED PERMISSIONS + TOOL CALL WRAPPER
# ============================================================

def streamed_check_permissions_and_call_tool(
    tool: Tool,
    tool_use_id: str,
    input: Dict[str, Union[bool, str, int, float]],
    tool_use_context: ToolUseContext,
    can_use_tool: Callable,
    assistant_message: AssistantMessage,
    message_id: str,
    request_id: Optional[str],
    mcp_server_type: McpServerType,
    mcp_server_base_url: Optional[str],
) -> Stream:
    """
    Wrap checkPermissionsAndCallTool (async Promise) with the Stream class
    so its progress updates and final results come through as one
    AsyncIterable — mirrors the TypeScript pattern exactly.
    """
    stream: Stream[Dict] = Stream[Dict]()

    promise = _AsyncPromise()

    async def _run() -> None:
        try:
            results = await check_permissions_and_call_tool(
                tool=tool,
                tool_use_id=tool_use_id,
                input=input,
                tool_use_context=tool_use_context,
                can_use_tool=can_use_tool,
                assistant_message=assistant_message,
                message_id=message_id,
                request_id=request_id,
                mcp_server_type=mcp_server_type,
                mcp_server_base_url=mcp_server_base_url,
                on_tool_progress=_make_progress_handler(
                    stream, tool, tool_use_id, tool_use_context,
                    message_id, request_id, mcp_server_type, mcp_server_base_url,
                ),
            )
            for r in results:
                stream.enqueue(r)
        except Exception as e:
            stream.error(e)
        finally:
            stream.done()

    asyncio.create_task(_run())
    return stream


# ============================================================
# MAIN ENTRY POINT: runToolUse
# ============================================================

async def run_tool_use(
    tool_use: Dict,
    assistant_message: AssistantMessage,
    can_use_tool: Callable,
    tool_use_context: ToolUseContext,
) -> AsyncGenerator[Dict, None]:
    """
    Run a single tool use from an assistant message.

    Yields MessageUpdateLazy messages as the tool executes:
    - Progress messages during tool execution
    - Tool result messages on completion
    - Error messages on failure
    """
    tool_name = tool_use.get("name", "")
    tool_use_id = tool_use.get("id", "")

    # First try to find in the available tools (what the model sees)
    tools: List = tool_use_context.get("options", {}).get("tools", [])
    tool = find_tool_by_name(tools, tool_name)

    # Fall back to deprecated alias lookup
    # (e.g. old transcripts calling "KillShell" which is now an alias for "TaskStop")
    if not tool:
        fallback = find_tool_by_name(get_all_base_tools(), tool_name)
        if fallback and tool_name in getattr(fallback, "aliases", []):
            tool = fallback

    message_id = assistant_message.get("message", {}).get("id", "")
    request_id = assistant_message.get("requestId")

    mcp_clients: List = tool_use_context.get("options", {}).get("mcpClients", [])
    mcp_server_type = get_mcp_server_type(tool_name, mcp_clients)
    mcp_server_base_url = get_mcp_server_base_url_from_tool_name(tool_name, mcp_clients)

    # ---- Tool not found ----
    if not tool:
        log_for_debugging(f"Unknown tool {tool_name}: {tool_use_id}")
        log_event(
            "tengu_tool_use_error",
            {
                "error": f"No such tool available: {sanitize_tool_name_for_analytics(tool_name)}",
                **_build_analytics_kwargs(
                    tool_name, tool_use_id, tool, mcp_server_type,
                    mcp_server_base_url, request_id,
                    tool_use_context.get("queryTracking"),
                ),
            },
        )
        yield {
            "message": create_user_message({
                "content": [
                    {
                        "type": "tool_result",
                        "content": f"<tool_use_error>Error: No such tool available: {tool_name}</tool_use_error>",
                        "is_error": True,
                        "tool_use_id": tool_use_id,
                    },
                ],
                "toolUseResult": f"Error: No such tool available: {tool_name}",
                "sourceToolAssistantUUID": assistant_message.get("uuid"),
            }),
        }
        return

    tool_input: Dict = tool_use.get("input", {})

    # ---- Abort check ----
    abort_controller = tool_use_context.get("abortController")
    if abort_controller and getattr(abort_controller.signal, "aborted", False):
        log_event(
            "tengu_tool_use_cancelled",
            _build_analytics_kwargs(
                tool_name, tool_use_id, tool, mcp_server_type,
                mcp_server_base_url, request_id,
                tool_use_context.get("queryTracking"),
            ),
        )
        content = create_tool_result_stop_message(tool_use_id)
        content["content"] = with_memory_correction_hint(CANCEL_MESSAGE)
        yield {
            "message": create_user_message({
                "content": [content],
                "toolUseResult": CANCEL_MESSAGE,
                "sourceToolAssistantUUID": assistant_message.get("uuid"),
            }),
        }
        return

    # ---- Streamed permissions + tool call ----
    try:
        stream = streamed_check_permissions_and_call_tool(
            tool=tool,
            tool_use_id=tool_use_id,
            input=tool_input,
            tool_use_context=tool_use_context,
            can_use_tool=can_use_tool,
            assistant_message=assistant_message,
            message_id=message_id,
            request_id=request_id,
            mcp_server_type=mcp_server_type,
            mcp_server_base_url=mcp_server_base_url,
        )
        async for update in stream:
            yield update
    except Exception as error:
        log_error(error)
        error_msg = error_message(error)
        tool_info = f" ({tool.name})" if tool else ""
        detailed_error = f"Error calling tool{tool_info}: {error_msg}"

        yield {
            "message": create_user_message({
                "content": [
                    {
                        "type": "tool_result",
                        "content": f"<tool_use_error>{detailed_error}</tool_use_error>",
                        "is_error": True,
                        "tool_use_id": tool_use_id,
                    },
                ],
                "toolUseResult": detailed_error,
                "sourceToolAssistantUUID": assistant_message.get("uuid"),
            }),
        }


# ============================================================
# CORE: checkPermissionsAndCallTool
# ============================================================

def _process_hook_attachment(hook_result: Dict, hook_infos: List[StopHookInfo]) -> None:
    """Extract command+duration from a hook attachment into hook_infos list."""
    if hook_result.get("message", {}).get("type") != "attachment":
        return
    att = hook_result.get("message", {}).get("attachment", {})
    if (
        "command" in att
        and att.get("command") is not None
        and "durationMs" in att
        and att.get("durationMs") is not None
    ):
        hook_infos.append({
            "command": att["command"],
            "durationMs": att["durationMs"],
        })


async def check_permissions_and_call_tool(
    tool: Tool,
    tool_use_id: str,
    input: Dict[str, Union[bool, str, int, float]],
    tool_use_context: ToolUseContext,
    can_use_tool: Callable,
    assistant_message: AssistantMessage,
    message_id: str,
    request_id: Optional[str],
    mcp_server_type: McpServerType,
    mcp_server_base_url: Optional[str],
    on_tool_progress: Callable[[ToolProgress], None],
) -> List[Dict]:
    """
    Core tool execution pipeline:
      1. Validate input (Zod schema)
      2. Run PreToolUse hooks
      3. Check permissions (allow/ask/deny)
      4. Execute the tool
      5. Run PostToolUse hooks
      6. Return result messages
    """
    # ----------------------------------------------------------------
    # Step 1a: Zod input validation
    # ----------------------------------------------------------------
    parsed_input = _safe_parse_input(tool, input)

    if not parsed_input["success"]:
        error_content = format_zod_validation_error(tool.name, parsed_input["error"])

        schema_hint = build_schema_not_sent_hint(
            tool,
            tool_use_context.get("messages", []),
            tool_use_context.get("options", {}).get("tools", []),
        )
        if schema_hint:
            log_event("tengu_deferred_tool_schema_not_sent", {
                "toolName": sanitize_tool_name_for_analytics(tool.name),
                "isMcp": getattr(tool, "is_mcp", False),
            })
            error_content += schema_hint

        log_for_debugging(f"{tool.name} tool input error: {error_content[:200]}")
        log_event(
            "tengu_tool_use_error",
            {
                "error": "InputValidationError",
                "errorDetails": error_content[:2000],
                "messageID": message_id,
                **_build_analytics_kwargs(
                    tool.name, tool_use_id, tool, mcp_server_type,
                    mcp_server_base_url, request_id,
                    tool_use_context.get("queryTracking"),
                ),
            },
        )
        return [
            {
                "message": create_user_message({
                    "content": [
                        {
                            "type": "tool_result",
                            "content": f"<tool_use_error>InputValidationError: {error_content}</tool_use_error>",
                            "is_error": True,
                            "tool_use_id": tool_use_id,
                        },
                    ],
                    "toolUseResult": f"InputValidationError: {parsed_input['error']}",
                    "sourceToolAssistantUUID": assistant_message.get("uuid"),
                }),
            },
        ]

    processed_input: Any = parsed_input["data"]

    # ----------------------------------------------------------------
    # Step 1b: Tool-level input validation
    # ----------------------------------------------------------------
    validate_input_fn = getattr(tool, "validate_input", None)
    if validate_input_fn:
        is_valid_call = await validate_input_fn(processed_input, tool_use_context)
        if is_valid_call and is_valid_call.get("result") is False:
            log_for_debugging(
                f"{tool.name} tool validation error: {is_valid_call.get('message', '')[:200]}",
            )
            log_event(
                "tengu_tool_use_error",
                {
                    "messageID": message_id,
                    "error": is_valid_call.get("message"),
                    "errorCode": is_valid_call.get("errorCode"),
                    **_build_analytics_kwargs(
                        tool.name, tool_use_id, tool, mcp_server_type,
                        mcp_server_base_url, request_id,
                        tool_use_context.get("queryTracking"),
                    ),
                },
            )
            return [
                {
                    "message": create_user_message({
                        "content": [
                            {
                                "type": "tool_result",
                                "content": f"<tool_use_error>{is_valid_call.get('message')}</tool_use_error>",
                                "is_error": True,
                                "tool_use_id": tool_use_id,
                            },
                        ],
                        "toolUseResult": f"Error: {is_valid_call.get('message')}",
                        "sourceToolAssistantUUID": assistant_message.get("uuid"),
                    }),
                },
            ]

    # ----------------------------------------------------------------
    # Speculative bash classifier check (runs in parallel with hooks)
    # ----------------------------------------------------------------
    if (
        tool.name == BASH_TOOL_NAME
        and processed_input
        and isinstance(processed_input, dict)
        and "command" in processed_input
    ):
        app_state = tool_use_context.get("get_app_state", lambda: {})()
        tool_permission_context = getattr(app_state, "toolPermissionContext", None)
        if tool_permission_context:
            start_speculative_classifier_check(
                processed_input["command"],
                tool_permission_context,
                getattr(tool_use_context.get("abortController", {}), "signal", None),
                tool_use_context.get("options", {}).get("isNonInteractiveSession"),
            )

    resulting_messages: List[Dict] = []
    call_input = processed_input

    # ----------------------------------------------------------------
    # Defense: strip _simulatedSedEdit from Bash input
    # (internal-only field injected by permission system after user approval)
    # ----------------------------------------------------------------
    if (
        tool.name == BASH_TOOL_NAME
        and processed_input
        and isinstance(processed_input, dict)
        and "_simulatedSedEdit" in processed_input
    ):
        processed_input = {k: v for k, v in processed_input.items() if k != "_simulatedSedEdit"}

    # ----------------------------------------------------------------
    # Backfill observable input (shallow clone for hooks/canUseTool)
    # SendMessageTool adds fields; file tools overwrite file_path with expandPath.
    # That mutation must not reach call() — keep callInput as the model's original.
    # ----------------------------------------------------------------
    backfilled_clone: Optional[Dict] = None
    backfill_fn = getattr(tool, "backfill_observable_input", None)
    if backfill_fn and isinstance(processed_input, dict) and processed_input is not None:
        backfilled_clone = {**processed_input}
        backfill_fn(backfilled_clone)
        processed_input = backfilled_clone

    # ----------------------------------------------------------------
    # State for PreToolUse hooks
    # ----------------------------------------------------------------
    should_prevent_continuation = False
    stop_reason: Optional[str] = None
    hook_permission_result: Optional[PermissionResult] = None
    pre_tool_hook_infos: List[StopHookInfo] = []
    pre_tool_hook_start_ms = time.time() * 1000

    # ----------------------------------------------------------------
    # Step 2: PreToolUse hooks
    # ----------------------------------------------------------------
    async for result in run_pre_tool_use_hooks(
        tool_use_context,
        tool,
        processed_input,
        tool_use_id,
        assistant_message.get("message", {}).get("id", ""),
        request_id,
        mcp_server_type,
        mcp_server_base_url,
    ):
        result_type = result.get("type")

        if result_type == "message":
            msg = result["message"]
            msg_type = msg.get("message", {}).get("type")
            if msg_type == "progress":
                on_tool_progress(msg["message"])
            else:
                resulting_messages.append(msg)
                _process_hook_attachment(msg, pre_tool_hook_infos)

        elif result_type == "hookPermissionResult":
            hook_permission_result = result["hookPermissionResult"]

        elif result_type == "hookUpdatedInput":
            processed_input = result["updatedInput"]

        elif result_type == "preventContinuation":
            should_prevent_continuation = result["shouldPreventContinuation"]

        elif result_type == "stopReason":
            stop_reason = result["stopReason"]

        elif result_type == "additionalContext":
            resulting_messages.append(result["message"])

        elif result_type == "stop":
            stats = get_stats_store()
            if stats:
                stats.observe("pre_tool_hook_duration_ms", time.time() * 1000 - pre_tool_hook_start_ms)
            resulting_messages.append({
                "message": create_user_message({
                    "content": [create_tool_result_stop_message(tool_use_id)],
                    "toolUseResult": f"Error: {stop_reason}",
                    "sourceToolAssistantUUID": assistant_message.get("uuid"),
                }),
            })
            return resulting_messages

    # ----------------------------------------------------------------
    # PreToolUse hook duration tracking
    # ----------------------------------------------------------------
    pre_tool_hook_duration_ms = (time.time() * 1000) - pre_tool_hook_start_ms
    stats = get_stats_store()
    if stats:
        stats.observe("pre_tool_hook_duration_ms", pre_tool_hook_duration_ms)

    if pre_tool_hook_duration_ms >= SLOW_PHASE_LOG_THRESHOLD_MS:
        log_for_debugging(
            f"Slow PreToolUse hooks: {pre_tool_hook_duration_ms}ms for {tool.name} "
            f"({len(pre_tool_hook_infos)} hooks)",
            level="info",
        )

    # Emit PreToolUse summary inline when > 500ms
    if os.environ.get("USER_TYPE") == "ant" and pre_tool_hook_infos:
        if pre_tool_hook_duration_ms > HOOK_TIMING_DISPLAY_THRESHOLD_MS:
            resulting_messages.append({
                "message": create_stop_hook_summary_message(
                    len(pre_tool_hook_infos),
                    pre_tool_hook_infos,
                    [],
                    False,
                    None,
                    False,
                    "suggestion",
                    None,
                    "PreToolUse",
                    pre_tool_hook_duration_ms,
                ),
            })

    # ----------------------------------------------------------------
    # Build tool attributes for telemetry
    # ----------------------------------------------------------------
    tool_attributes: Dict[str, Any] = {}
    if processed_input and isinstance(processed_input, dict):
        if tool.name == FILE_READ_TOOL_NAME and "file_path" in processed_input:
            tool_attributes["file_path"] = str(processed_input["file_path"])
        elif tool.name in (FILE_EDIT_TOOL_NAME, FILE_WRITE_TOOL_NAME) and "file_path" in processed_input:
            tool_attributes["file_path"] = str(processed_input["file_path"])
        elif tool.name == BASH_TOOL_NAME and "command" in processed_input:
            tool_attributes["full_command"] = str(processed_input["command"])

    start_tool_span(
        tool.name,
        tool_attributes,
        json_stringify(processed_input) if is_beta_tracing_enabled() else None,
    )
    start_tool_blocked_on_user_span()

    # ----------------------------------------------------------------
    # Phase 3 complete — Permission check starts here
    # ----------------------------------------------------------------
    app_state = tool_use_context.get("get_app_state", lambda: {})()
    tool_permission_context = getattr(app_state, "toolPermissionContext", None)
    permission_mode = getattr(tool_permission_context, "mode", "auto") if tool_permission_context else "auto"
    permission_start_ms = time.time() * 1000

    resolved = resolve_hook_permission_decision(
        hook_permission_result,
        tool,
        processed_input,
        tool_use_context,
        can_use_tool,
        assistant_message,
        tool_use_id,
    )
    permission_decision: PermissionResult = resolved.get("decision", {})
    processed_input = resolved.get("input", processed_input)
    permission_duration_ms = (time.time() * 1000) - permission_start_ms

    if permission_duration_ms >= SLOW_PHASE_LOG_THRESHOLD_MS and permission_mode == "auto":
        log_for_debugging(
            f"Slow permission decision: {permission_duration_ms}ms for {tool.name} "
            f"(mode={permission_mode}, behavior={permission_decision.get('behavior')})",
            level="info",
        )

    # ---- OTel tool_decision event + code-edit counter for non-ask paths ----
    behavior = permission_decision.get("behavior", "ask")
    if (
        behavior != "ask"
        and not tool_use_context.get("toolDecisions", {}).get(tool_use_id)
    ):
        decision = "accept" if behavior == "allow" else "reject"
        source = decision_reason_to_otel_source(
            permission_decision.get("decisionReason"),
            behavior,
        )
        log_otel_event("tool_decision", {
            "decision": decision,
            "source": source,
            "tool_name": sanitize_tool_name_for_analytics(tool.name),
        })

        if is_code_editing_tool(tool.name):
            attrs = build_code_edit_tool_attributes(
                tool, processed_input, decision, source,
            )
            counter = get_code_edit_tool_decision_counter()
            if counter and attrs is not None:
                counter.add(1, attrs)

    # ---- Permission granted/denied hook message ----
    decision_reason: Optional[Dict] = permission_decision.get("decisionReason")
    if (
        decision_reason
        and decision_reason.get("type") == "hook"
        and decision_reason.get("hookName") == "PermissionRequest"
        and behavior != "ask"
    ):
        resulting_messages.append({
            "message": create_attachment_message({
                "type": "hook_permission_decision",
                "decision": behavior,
                "toolUseID": tool_use_id,
                "hookEvent": "PermissionRequest",
            }),
        })

    # ----------------------------------------------------------------
    # PERMISSION DENIED
    # ----------------------------------------------------------------
    if behavior != "allow":
        log_for_debugging(f"{tool.name} tool permission denied")

        decision_info = tool_use_context.get("toolDecisions", {}).get(tool_use_id)
        end_tool_blocked_on_user_span(
            decision_info.get("source", "unknown") if decision_info else "unknown",
            decision_info.get("decision", "unknown") if decision_info else "unknown",
        )
        end_tool_span()

        log_event(
            "tengu_tool_use_can_use_tool_rejected",
            {
                "messageID": message_id,
                **_build_analytics_kwargs(
                    tool.name, tool_use_id, tool, mcp_server_type,
                    mcp_server_base_url, request_id,
                    tool_use_context.get("queryTracking"),
                ),
            },
        )

        error_msg: Optional[str] = permission_decision.get("message")
        if should_prevent_continuation and not error_msg:
            reason_suffix = f": {stop_reason}" if stop_reason else ""
            error_msg = f"Execution stopped by PreToolUse hook{reason_suffix}"

        message_content: List[Dict] = [
            {
                "type": "tool_result",
                "content": error_msg or "",
                "is_error": True,
                "tool_use_id": tool_use_id,
            },
        ]

        reject_content_blocks: Optional[List] = (
            permission_decision.get("contentBlocks")
            if behavior == "ask"
            else None
        )
        if reject_content_blocks:
            message_content.extend(reject_content_blocks)

        reject_image_ids: Optional[List[int]] = None
        if reject_content_blocks:
            image_count = array_count(
                reject_content_blocks,
                lambda b: b.get("type") == "image",
            )
            if image_count > 0:
                start_id = get_next_image_paste_id(tool_use_context.get("messages", []))
                reject_image_ids = list(range(start_id, start_id + image_count))

        resulting_messages.append({
            "message": create_user_message({
                "content": message_content,
                "imagePasteIds": reject_image_ids,
                "toolUseResult": f"Error: {error_msg}" if error_msg else None,
                "sourceToolAssistantUUID": assistant_message.get("uuid"),
            }),
        })

        # ---- PermissionDenied hooks for auto-mode classifier denials ----
        if (
            feature("TRANSCRIPT_CLASSIFIER")
            and decision_reason
            and decision_reason.get("type") == "classifier"
            and decision_reason.get("classifier") == "auto-mode"
        ):
            hook_says_retry = False
            async for result in execute_permission_denied_hooks(
                tool.name,
                tool_use_id,
                processed_input,
                decision_reason.get("reason", "Permission denied"),
                tool_use_context,
                permission_mode,
                getattr(tool_use_context.get("abortController", {}), "signal", None),
            ):
                if result.get("retry"):
                    hook_says_retry = True

            if hook_says_retry:
                resulting_messages.append({
                    "message": create_user_message({
                        "content": "The PermissionDenied hook indicated this command is now approved. You may retry it if you would like.",
                        "isMeta": True,
                    }),
                })

        return resulting_messages

    # ----------------------------------------------------------------
    # PERMISSION GRANTED
    # ----------------------------------------------------------------
    log_event(
        "tengu_tool_use_can_use_tool_allowed",
        {
            "messageID": message_id,
            **_build_analytics_kwargs(
                tool.name, tool_use_id, tool, mcp_server_type,
                mcp_server_base_url, request_id,
                tool_use_context.get("queryTracking"),
            ),
        },
    )

    # Use updated input from permissions if provided
    if permission_decision.get("updatedInput") is not None:
        processed_input = permission_decision["updatedInput"]

    # ---- Build tool parameters for telemetry ----
    telemetry_tool_input = extract_tool_input_for_telemetry(processed_input)
    tool_parameters: Dict[str, Any] = {}

    if is_tool_details_logging_enabled() and processed_input and isinstance(processed_input, dict):
        if tool.name == BASH_TOOL_NAME and "command" in processed_input:
            bash_input = processed_input
            cmd_parts = bash_input["command"].strip().split()
            tool_parameters = {
                "bash_command": cmd_parts[0] if cmd_parts else "",
                "full_command": bash_input["command"],
            }
            if bash_input.get("timeout") is not None:
                tool_parameters["timeout"] = bash_input["timeout"]
            if bash_input.get("description") is not None:
                tool_parameters["description"] = bash_input["description"]
            if "dangerouslyDisableSandbox" in bash_input:
                tool_parameters["dangerouslyDisableSandbox"] = bash_input["dangerouslyDisableSandbox"]

        mcp_details = extract_mcp_tool_details(tool.name)
        if mcp_details:
            tool_parameters["mcp_server_name"] = mcp_details.get("serverName")
            tool_parameters["mcp_tool_name"] = mcp_details.get("mcpToolName")

        skill_name = extract_skill_name(tool.name, processed_input)
        if skill_name:
            tool_parameters["skill_name"] = skill_name

    # End blocked span, start execution span
    decision_info = tool_use_context.get("toolDecisions", {}).get(tool_use_id)
    end_tool_blocked_on_user_span(
        decision_info.get("decision", "unknown") if decision_info else "unknown",
        decision_info.get("source", "unknown") if decision_info else "unknown",
    )
    start_tool_execution_span()
    start_time_ms = time.time() * 1000
    start_session_activity("tool_exec")

    # ----------------------------------------------------------------
    # Determine callInput: backfill clone vs original
    # Restore model's original file_path if it matches backfill-expanded value
    # (keeps transcript/VCR hashes stable)
    # ----------------------------------------------------------------
    fp_key = "file_path"
    if (
        backfilled_clone
        and processed_input != call_input
        and isinstance(processed_input, dict)
        and fp_key in processed_input
        and isinstance(call_input, dict)
        and fp_key in call_input
        and processed_input.get(fp_key) == backfilled_clone.get(fp_key)
    ):
        call_input = {**processed_input, fp_key: call_input.get(fp_key)}
    elif processed_input != backfilled_clone:
        call_input = processed_input

    # ----------------------------------------------------------------
    # TOOL EXECUTION
    # ----------------------------------------------------------------
    try:
        tool_call_fn = getattr(tool, "call", None)

        def progress_callback(progress: ToolProgress) -> None:
            on_tool_progress({
                "toolUseID": progress.get("toolUseID"),
                "data": progress.get("data"),
            })

        tid_key = "toolUseId"
        result = await tool_call_fn(
            call_input,
            {
                **tool_use_context,
                tid_key: tool_use_id,
                "userModified": permission_decision.get("userModified", False),
            },
            can_use_tool,
            assistant_message,
            progress_callback,
        )

        duration_ms = (time.time() * 1000) - start_time_ms
        add_to_tool_duration(duration_ms)

        # ---- Log tool output as span event ----
        result_data: Any = getattr(result, "data", None)
        if result_data and isinstance(result_data, dict):
            content_attrs: Dict[str, Any] = {}

            if tool.name == FILE_READ_TOOL_NAME and "content" in result_data:
                if isinstance(processed_input, dict) and "file_path" in processed_input:
                    content_attrs["file_path"] = str(processed_input["file_path"])
                content_attrs["content"] = str(result_data["content"])

            elif tool.name in (FILE_EDIT_TOOL_NAME, FILE_WRITE_TOOL_NAME):
                if isinstance(processed_input, dict) and "file_path" in processed_input:
                    content_attrs["file_path"] = str(processed_input["file_path"])
                if tool.name == FILE_EDIT_TOOL_NAME and "diff" in result_data:
                    content_attrs["diff"] = str(result_data["diff"])
                if (
                    tool.name == FILE_WRITE_TOOL_NAME
                    and isinstance(processed_input, dict)
                    and "content" in processed_input
                ):
                    content_attrs["content"] = str(processed_input["content"])

            elif tool.name == BASH_TOOL_NAME and isinstance(processed_input, dict) and "command" in processed_input:
                content_attrs["bash_command"] = str(processed_input["command"])
                if "output" in result_data:
                    content_attrs["output"] = str(result_data["output"])

            if content_attrs:
                add_tool_content_event("tool.output", content_attrs)

        # ---- Structured output attachment ----
        if isinstance(result, dict) and "structured_output" in result:
            resulting_messages.append({
                "message": create_attachment_message({
                    "type": "structured_output",
                    "data": result["structured_output"],
                }),
            })

        end_tool_execution_span(success=True)

        tool_result_str = (
            json_stringify(result_data)
            if result_data and isinstance(result_data, dict)
            else str(result_data if result_data is not None else "")
        )
        end_tool_span(tool_result_str)

        # ---- Map tool result to API format (cached) ----
        map_fn = getattr(tool, "map_tool_result_to_block_param", None)
        if map_fn:
            mapped_block = map_fn(result_data, tool_use_id)
        else:
            mapped_block = {
                "type": "tool_result",
                "content": str(result_data) if result_data is not None else "",
                "tool_use_id": tool_use_id,
            }

        mapped_content = mapped_block.get("content")
        tool_result_size_bytes = (
            len(mapped_content)
            if mapped_content is not None
            else 0
        )

        # ---- Extract file extension ----
        file_extension: Optional[str] = None
        if processed_input and isinstance(processed_input, dict):
            fp_val: Optional[str] = None
            if tool.name in (FILE_READ_TOOL_NAME, FILE_EDIT_TOOL_NAME, FILE_WRITE_TOOL_NAME) and "file_path" in processed_input:
                fp_val = str(processed_input["file_path"])
                file_extension = get_file_extension_for_analytics(fp_val)
            elif tool.name == NOTEBOOK_EDIT_TOOL_NAME and "notebook_path" in processed_input:
                fp_val = str(processed_input["notebook_path"])
                file_extension = get_file_extension_for_analytics(fp_val)
            elif tool.name == BASH_TOOL_NAME and "command" in processed_input:
                sim_path = None
                sim_ed = processed_input.get("_simulatedSedEdit")
                if isinstance(sim_ed, dict):
                    sim_path = sim_ed.get("filePath")
                file_extension = get_file_extensions_from_bash_command(
                    processed_input["command"],
                    sim_path,
                )

        log_event(
            "tengu_tool_use_success",
            {
                "messageID": message_id,
                "toolName": sanitize_tool_name_for_analytics(tool.name),
                "isMcp": getattr(tool, "is_mcp", False),
                "durationMs": duration_ms,
                "preToolHookDurationMs": pre_tool_hook_duration_ms,
                "toolResultSizeBytes": tool_result_size_bytes,
                **({"fileExtension": file_extension} if file_extension else {}),
                **_build_analytics_kwargs(
                    tool.name, tool_use_id, tool, mcp_server_type,
                    mcp_server_base_url, request_id,
                    tool_use_context.get("queryTracking"),
                ),
            },
        )

        # ---- Enrich with git commit ID ----
        if (
            is_tool_details_logging_enabled()
            and tool.name in (BASH_TOOL_NAME, POWERSHELL_TOOL_NAME)
            and isinstance(processed_input, dict)
            and "command" in processed_input
            and isinstance(processed_input["command"], str)
            and re.search(r"\bgit\s+commit\b", processed_input["command"])
            and result_data
            and isinstance(result_data, dict)
            and "stdout" in result_data
        ):
            git_commit_id = parse_git_commit_id(str(result_data["stdout"]))
            if git_commit_id:
                tool_parameters["git_commit_id"] = git_commit_id

        # ---- OTel tool_result event ----
        mcp_server_scope = (
            get_mcp_server_scope_from_tool_name(tool.name)
            if is_mcp_tool(tool)
            else None
        )

        otel_data: Dict[str, Any] = {
            "tool_name": sanitize_tool_name_for_analytics(tool.name),
            "success": "true",
            "duration_ms": str(duration_ms),
            "tool_result_size_bytes": str(tool_result_size_bytes),
        }
        if tool_parameters:
            otel_data["tool_parameters"] = json_stringify(tool_parameters)
        if telemetry_tool_input:
            otel_data["tool_input"] = telemetry_tool_input
        if decision_info:
            otel_data["decision_source"] = decision_info.get("source", "")
            otel_data["decision_type"] = decision_info.get("decision", "")
        if mcp_server_scope:
            otel_data["mcp_server_scope"] = mcp_server_scope
        log_otel_event("tool_result", otel_data)

        # ----------------------------------------------------------------
        # addToolResult helper
        # ----------------------------------------------------------------
        tool_output: Any = result_data
        tool_context_modifier: Any = getattr(result, "contextModifier", None)
        mcp_meta: Any = getattr(result, "mcp_meta", None)

        async def add_tool_result(
            tool_use_result: Any,
            pre_mapped_block: Optional[Dict] = None,
        ) -> None:
            """Add a tool result message to resultingMessages."""
            if pre_mapped_block:
                tool_result_block = await process_pre_mapped_tool_result_block(
                    pre_mapped_block,
                    tool.name,
                    getattr(tool, "max_result_size_chars", None),
                )
            else:
                tool_result_block = await process_tool_result_block(
                    tool, tool_use_result, tool_use_id
                )

            content_blocks: List[Dict] = [tool_result_block]

            accept_feedback = None
            if hasattr(permission_decision, "acceptFeedback"):
                accept_feedback = permission_decision.get("acceptFeedback")
            elif "acceptFeedback" in permission_decision:
                accept_feedback = permission_decision.get("acceptFeedback")

            if accept_feedback:
                content_blocks.append({"type": "text", "text": accept_feedback})

            allow_content_blocks: Optional[List] = permission_decision.get("contentBlocks")
            if allow_content_blocks:
                content_blocks.extend(allow_content_blocks)

            allow_image_ids: Optional[List[int]] = None
            if allow_content_blocks:
                image_count = array_count(
                    allow_content_blocks,
                    lambda b: b.get("type") == "image",
                )
                if image_count > 0:
                    start_id = get_next_image_paste_id(tool_use_context.get("messages", []))
                    allow_image_ids = list(range(start_id, start_id + image_count))

            agent_id = tool_use_context.get("agentId")
            preserve_results = tool_use_context.get("preserveToolUseResults")

            resulting_messages.append({
                "message": create_user_message({
                    "content": content_blocks,
                    "imagePasteIds": allow_image_ids,
                    "toolUseResult": (
                        None
                        if agent_id and not preserve_results
                        else tool_use_result
                    ),
                    "mcpMeta": None if agent_id else mcp_meta,
                    "sourceToolAssistantUUID": assistant_message.get("uuid"),
                }),
                "contextModifier": (
                    {
                        "toolUseID": tool_use_id,
                        "modifyContext": tool_context_modifier,
                    }
                    if tool_context_modifier
                    else None
                ),
            })

        # ---- Non-MCP tools: add result immediately ----
        if not is_mcp_tool(tool):
            await add_tool_result(tool_output, mapped_block)

        # ----------------------------------------------------------------
        # Phase 5: PostToolUse hooks
        # ----------------------------------------------------------------
        post_tool_hook_infos: List[StopHookInfo] = []
        post_tool_hook_start_ms = time.time() * 1000
        hook_results: List[Dict] = []

        async for hook_result in run_post_tool_use_hooks(
            tool_use_context,
            tool,
            tool_use_id,
            assistant_message.get("message", {}).get("id", ""),
            processed_input,
            tool_output,
            request_id,
            mcp_server_type,
            mcp_server_base_url,
        ):
            if "updatedMCPToolOutput" in hook_result:
                if is_mcp_tool(tool):
                    tool_output = hook_result["updatedMCPToolOutput"]
            elif is_mcp_tool(tool):
                # MCP path for hook results without updatedMCPToolOutput
                hook_results.append(hook_result)
                _process_hook_attachment(hook_result, post_tool_hook_infos)
            else:
                resulting_messages.append(hook_result)
                _process_hook_attachment(hook_result, post_tool_hook_infos)

        post_tool_hook_duration_ms = (time.time() * 1000) - post_tool_hook_start_ms

        if post_tool_hook_duration_ms >= SLOW_PHASE_LOG_THRESHOLD_MS:
            log_for_debugging(
                f"Slow PostToolUse hooks: {post_tool_hook_duration_ms}ms for {tool.name} "
                f"({len(post_tool_hook_infos)} hooks)",
                level="info",
            )

        # ---- MCP tools: add result after PostToolUse hooks ----
        if is_mcp_tool(tool):
            await add_tool_result(tool_output)

        # ---- PostToolUse summary inline when > 500ms ----
        if os.environ.get("USER_TYPE") == "ant" and post_tool_hook_infos:
            if post_tool_hook_duration_ms > HOOK_TIMING_DISPLAY_THRESHOLD_MS:
                resulting_messages.append({
                    "message": create_stop_hook_summary_message(
                        len(post_tool_hook_infos),
                        post_tool_hook_infos,
                        [],
                        False,
                        None,
                        False,
                        "suggestion",
                        None,
                        "PostToolUse",
                        post_tool_hook_duration_ms,
                    ),
                })

        # ---- New messages from tool ----
        new_messages = getattr(result, "newMessages", None)
        if new_messages and len(new_messages) > 0:
            for msg in new_messages:
                resulting_messages.append({"message": msg})

        # ---- Hook indicated to prevent continuation ----
        if should_prevent_continuation:
            resulting_messages.append({
                "message": create_attachment_message({
                    "type": "hook_stopped_continuation",
                    "message": stop_reason or "Execution stopped by hook",
                    "hookName": f"PreToolUse:{tool.name}",
                    "toolUseID": tool_use_id,
                    "hookEvent": "PreToolUse",
                }),
            })

        # ---- Yield remaining MCP hook results ----
        for hr in hook_results:
            resulting_messages.append(hr)

        return resulting_messages

    except Exception as error:
        duration_ms = (time.time() * 1000) - start_time_ms
        add_to_tool_duration(duration_ms)

        end_tool_execution_span(success=False, error=error_message(error))
        end_tool_span()

        # ---- Handle MCP auth errors ----
        if isinstance(error, McpAuthError):
            server_name = error.server_name
            set_app_state_fn = tool_use_context.get("setAppState")
            if set_app_state_fn:
                def update_clients(prev_state: Dict) -> Dict:
                    clients: List = prev_state.get("mcp", {}).get("clients", [])
                    existing_index = -1
                    for i, c in enumerate(clients):
                        if c.get("name") == server_name:
                            existing_index = i
                            break
                    if existing_index == -1:
                        return prev_state
                    existing_client: Dict = clients[existing_index]
                    if existing_client.get("type") != "connected":
                        return prev_state
                    updated_clients = list(clients)
                    updated_clients[existing_index] = {
                        "name": server_name,
                        "type": "needs-auth",
                        "config": existing_client.get("config", {}),
                    }
                    return {
                        **prev_state,
                        "mcp": {**prev_state.get("mcp", {}), "clients": updated_clients},
                    }
                set_app_state_fn(update_clients)

        # ---- Log errors (skip AbortError — expected) ----
        if not isinstance(error, AbortError):
            error_msg = error_message(error)
            log_for_debugging(
                f"{tool.name} tool error ({duration_ms}ms): {error_msg[:200]}",
            )
            if not isinstance(error, ShellError):
                log_error(error)

            log_event(
                "tengu_tool_use_error",
                {
                    "messageID": message_id,
                    "toolName": sanitize_tool_name_for_analytics(tool.name),
                    "error": classify_tool_error(error),
                    "isMcp": getattr(tool, "is_mcp", False),
                    **_build_analytics_kwargs(
                        tool.name, tool_use_id, tool, mcp_server_type,
                        mcp_server_base_url, request_id,
                        tool_use_context.get("queryTracking"),
                    ),
                },
            )

            # ---- OTel tool_result error event ----
            mcp_server_scope = (
                get_mcp_server_scope_from_tool_name(tool.name)
                if is_mcp_tool(tool)
                else None
            )
            otel_err: Dict[str, Any] = {
                "tool_name": sanitize_tool_name_for_analytics(tool.name),
                "use_id": tool_use_id,
                "success": "false",
                "duration_ms": str(duration_ms),
                "error": error_message(error),
            }
            if tool_parameters:
                otel_err["tool_parameters"] = json_stringify(tool_parameters)
            if telemetry_tool_input:
                otel_err["tool_input"] = telemetry_tool_input
            if decision_info:
                otel_err["decision_source"] = decision_info.get("source", "")
                otel_err["decision_type"] = decision_info.get("decision", "")
            if mcp_server_scope:
                otel_err["mcp_server_scope"] = mcp_server_scope
            log_otel_event("tool_result", otel_err)

        formatted_error = format_error(error)
        is_interrupt = isinstance(error, AbortError)

        # ---- PostToolUseFailure hooks ----
        hook_messages: List[Dict] = []
        async for hook_result in run_post_tool_use_failure_hooks(
            tool_use_context,
            tool,
            tool_use_id,
            message_id,
            processed_input,
            formatted_error,
            is_interrupt,
            request_id,
            mcp_server_type,
            mcp_server_base_url,
        ):
            hook_messages.append(hook_result)

        # ---- mcpMeta for tool result ----
        mcp_meta_result: Any = None
        if tool_use_context.get("agentId"):
            mcp_meta_result = None
        elif isinstance(error, McpToolCallError):
            mcp_meta_result = error.mcp_meta
        else:
            mcp_meta_result = None

        tool_result_msg: Dict = {
            "message": create_user_message({
                "content": [
                    {
                        "type": "tool_result",
                        "content": formatted_error,
                        "is_error": True,
                        "tool_use_id": tool_use_id,
                    },
                ],
                "toolUseResult": f"Error: {formatted_error}",
                "mcpMeta": mcp_meta_result,
                "sourceToolAssistantUUID": assistant_message.get("uuid"),
            }),
        }

        return [tool_result_msg, *hook_messages]

    finally:
        stop_session_activity("tool_exec")
        # Clean up decision info after logging
        if decision_info:
            tool_decisions = tool_use_context.get("toolDecisions")
            if tool_decisions and hasattr(tool_decisions, "delete"):
                tool_decisions.delete(tool_use_id)
            elif tool_decisions and isinstance(tool_decisions, dict):
                tool_decisions.pop(tool_use_id, None)


# ============================================================
# Exports
# ============================================================
__all__ = [
    "run_tool_use",
    "check_permissions_and_call_tool",
    "build_schema_not_sent_hint",
    "classify_tool_error",
    "rule_source_to_otel_source",
    "decision_reason_to_otel_source",
    "get_next_image_paste_id",
    "find_mcp_server_connection",
    "get_mcp_server_type",
    "get_mcp_server_base_url_from_tool_name",
    "HOOK_TIMING_DISPLAY_THRESHOLD_MS",
    "SLOW_PHASE_LOG_THRESHOLD_MS",
]
