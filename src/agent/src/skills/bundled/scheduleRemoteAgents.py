"""
Schedule Remote Agents skill for cloud agent orchestration.

Converts scheduleRemoteAgents.ts to Python with multi-LLM compatibility for Cortex IDE.
Manages remote Claude Code agents in Anthropic's cloud with MCP connectors.
"""

from typing import List, Dict, Any, Optional, TypedDict
import os
import asyncio

# Defensive imports with fallback stubs
try:
    from ...services.analytics.growthbook import get_feature_value_cached_may_be_stale
except ImportError:
    def get_feature_value_cached_may_be_stale(key: str, default: Any) -> Any:
        """Fallback feature flag check."""
        return default

try:
    from ...services.policyLimits.index import is_policy_allowed
except ImportError:
    def is_policy_allowed(policy: str) -> bool:
        """Fallback policy check - returns False."""
        return False

try:
    from ...tools.AskUserQuestionTool.prompt import ASK_USER_QUESTION_TOOL_NAME
except ImportError:
    ASK_USER_QUESTION_TOOL_NAME = "AskUserQuestion"

try:
    from ...tools.RemoteTriggerTool.prompt import REMOTE_TRIGGER_TOOL_NAME
except ImportError:
    REMOTE_TRIGGER_TOOL_NAME = "RemoteTrigger"

try:
    from ...utils.auth import get_cloud_ai_oauth_tokens
except ImportError:
    def get_cloud_ai_oauth_tokens() -> Optional[Dict[str, str]]:
        """Fallback OAuth token retrieval."""
        return None

try:
    from ...utils.background.remote.preconditions import check_repo_for_remote_access
except ImportError:
    async def check_repo_for_remote_access(owner: str, name: str) -> Dict[str, Any]:
        """Fallback repo access check."""
        return {"hasAccess": False}

try:
    from ...utils.debug import log_for_debugging
except ImportError:
    def log_for_debugging(message: str, meta: Optional[Dict] = None) -> None:
        """Fallback debug logging."""
        pass

try:
    from ...utils.detectRepository import detect_current_repository_with_host, parse_git_remote
except ImportError:
    async def detect_current_repository_with_host() -> Optional[Dict[str, str]]:
        """Fallback repo detection."""
        return None
    
    def parse_git_remote(url: str) -> Optional[Dict[str, str]]:
        """Fallback git remote parser."""
        return None

try:
    from ...utils.git import get_remote_url
except ImportError:
    async def get_remote_url() -> Optional[str]:
        """Fallback remote URL getter."""
        return None

try:
    from ...utils.slowOperations import json_stringify
except ImportError:
    import json
    def json_stringify(obj: Any, indent: Optional[int] = None) -> str:
        """Fallback JSON stringification."""
        return json.dumps(obj, indent=indent)

try:
    from ...utils.teleport.environments import (
        fetch_environments,
        create_default_cloud_environment,
        EnvironmentResource,
    )
except ImportError:
    EnvironmentResource = Dict[str, Any]
    
    async def fetch_environments() -> List[EnvironmentResource]:
        """Fallback environments fetcher."""
        return []
    
    async def create_default_cloud_environment(name: str) -> EnvironmentResource:
        """Fallback environment creator."""
        raise Exception("Environment creation not available")

try:
    from ...skills.bundledSkills import register_bundled_skill
except ImportError:
    def register_bundled_skill(definition: Dict[str, Any]) -> None:
        """Fallback stub for skill registration."""
        pass


# Base58 alphabet for tagged ID decoding
BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


class ConnectorInfo(TypedDict):
    """MCP connector information."""
    uuid: str
    name: str
    url: str


def tagged_id_to_uuid(tagged_id: str) -> Optional[str]:
    """
    Decode a mcpsrv_ tagged ID to a UUID string.
    Tagged IDs have format: mcpsrv_01{base58(uuid.int)}
    where 01 is the version prefix.
    
    Args:
        tagged_id: The tagged ID string
        
    Returns:
        UUID string or None if invalid
    """
    prefix = 'mcpsrv_'
    if not tagged_id.startswith(prefix):
        return None
    
    rest = tagged_id[len(prefix):]
    # Skip version prefix (2 chars, always "01")
    base58_data = rest[2:]
    
    # Decode base58 to int
    n = 0
    for c in base58_data:
        idx = BASE58.find(c)
        if idx == -1:
            return None
        n = n * 58 + idx
    
    # Convert to UUID hex string
    hex_str = format(n, '032x')
    return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


def get_connected_cloud_ai_connectors(mcp_clients: List[Dict[str, Any]]) -> List[ConnectorInfo]:
    """
    Extract connected Claude AI MCP connectors from client list.
    
    Args:
        mcp_clients: List of MCP server connections
        
    Returns:
        List of connector info dicts
    """
    connectors: List[ConnectorInfo] = []
    
    for client in mcp_clients:
        if client.get("type") != "connected":
            continue
        
        config = client.get("config", {})
        if config.get("type") != "claudeai-proxy":
            continue
        
        uuid = tagged_id_to_uuid(config.get("id", ""))
        if not uuid:
            continue
        
        connectors.append({
            "uuid": uuid,
            "name": client.get("name", ""),
            "url": config.get("url", ""),
        })
    
    return connectors


def sanitize_connector_name(name: str) -> str:
    """
    Sanitize connector name for use in API calls.
    
    Args:
        name: Raw connector name
        
    Returns:
        Sanitized name
    """
    import re
    # Remove claude.ai prefix
    result = re.sub(r'^claude[.\s-]ai[.\s-]', '', name, flags=re.IGNORECASE)
    # Replace invalid chars with hyphens
    result = re.sub(r'[^a-zA-Z0-9_-]', '-', result)
    # Collapse multiple hyphens
    result = re.sub(r'-+', '-', result)
    # Trim hyphens from ends
    result = result.strip('-')
    return result


def format_connectors_info(connectors: List[ConnectorInfo]) -> str:
    """
    Format connector list for display in prompt.
    
    Args:
        connectors: List of connector info
        
    Returns:
        Formatted string
    """
    if not connectors:
        return "No connected MCP connectors found. The user may need to connect servers at https://claude.ai/settings/connectors"
    
    lines = ["Connected connectors (available for triggers):"]
    for c in connectors:
        safe_name = sanitize_connector_name(c["name"])
        lines.append(f"- {c['name']} (connector_uuid: {c['uuid']}, name: {safe_name}, url: {c['url']})")
    
    return "\n".join(lines)


BASE_QUESTION = "What would you like to do with scheduled remote agents?"


def format_setup_notes(notes: List[str]) -> str:
    """
    Format setup notes as a bulleted Heads-up block.
    
    Args:
        notes: List of note strings
        
    Returns:
        Formatted string
    """
    items = "\n".join(f"- {n}" for n in notes)
    return f"⚠ Heads-up:\n{items}"


async def get_current_repo_https_url() -> Optional[str]:
    """Get the current repo's HTTPS URL."""
    remote_url = await get_remote_url()
    if not remote_url:
        return None
    
    parsed = parse_git_remote(remote_url)
    if not parsed:
        return None
    
    return f"https://{parsed['host']}/{parsed['owner']}/{parsed['name']}"


def build_prompt(opts: Dict[str, Any]) -> str:
    """
    Build the schedule remote agents prompt.
    
    Args:
        opts: Options dict with all prompt variables
        
    Returns:
        Complete prompt string
    """
    user_timezone = opts.get("user_timezone", "UTC")
    connectors_info = opts.get("connectors_info", "")
    git_repo_url = opts.get("git_repo_url")
    environments_info = opts.get("environments_info", "")
    created_environment = opts.get("created_environment")
    setup_notes = opts.get("setup_notes", [])
    needs_github_access_reminder = opts.get("needs_github_access_reminder", False)
    user_args = opts.get("user_args", "")
    
    # When the user passes args, the initial AskUserQuestion dialog is skipped.
    # Setup notes must surface in the prompt body instead.
    setup_notes_section = ""
    if user_args and setup_notes:
        setup_notes_section = f"\n## Setup Notes\n\n{format_setup_notes(setup_notes)}\n"
    
    if setup_notes:
        initial_question = f"{format_setup_notes(setup_notes)}\n\n{BASE_QUESTION}"
    else:
        initial_question = BASE_QUESTION
    
    if user_args:
        first_step = "The user has already told you what they want (see User Request at the bottom). Skip the initial question and go directly to the matching workflow."
    else:
        first_step = f"""Your FIRST action must be a single {ASK_USER_QUESTION_TOOL_NAME} tool call (no preamble). Use this EXACT string for the `question` field — do not paraphrase or shorten it:

{json_stringify(initial_question)}

Set `header: "Action"` and offer the four actions (create/list/update/run) as options. After the user picks, follow the matching workflow below."""
    
    # GitHub access reminder text
    github_reminder = ""
    if needs_github_access_reminder:
        web_setup_enabled = get_feature_value_cached_may_be_stale('tengu_cobalt_lantern', False)
        if web_setup_enabled:
            github_reminder = "\n- If the user's request seems to require GitHub repo access (e.g. cloning a repo, opening PRs, reading code), remind them that they should run /web-setup to connect their GitHub account (or install the Claude GitHub App on the repo as an alternative) — otherwise the remote agent won't be able to access it."
        else:
            github_reminder = "\n- If the user's request seems to require GitHub repo access (e.g. cloning a repo, opening PRs, reading code), remind them that they need the Claude GitHub App installed on the repo — otherwise the remote agent won't be able to access it."
    
    # Environment creation note
    env_creation_note = ""
    if created_environment:
        env_creation_note = f"\n**Note:** A new environment `{created_environment['name']}` (id: `{created_environment['environment_id']}`) was just created for the user because they had none. Use this id for `job_config.ccr.environment_id` and mention the creation when you confirm the trigger config.\n"
    
    # Git repo URL note
    git_repo_note = ""
    if git_repo_url:
        git_repo_note = f" The default git repo is already set to `{git_repo_url}`. Ask the user if this is the right repo or if they need a different one."
    else:
        git_repo_note = " Ask which git repos the remote agent needs cloned into its environment."
    
    user_request_section = ""
    if user_args:
        user_request_section = f"""
## User Request

The user said: "{user_args}"

Start by understanding their intent and working through the appropriate workflow above."""
    
    return f"""# Schedule Remote Agents

You are helping the user schedule, update, list, or run **remote** Claude Code agents. These are NOT local cron jobs — each trigger spawns a fully isolated remote session (CCR) in Anthropic's cloud infrastructure on a cron schedule. The agent runs in a sandboxed environment with its own git checkout, tools, and optional MCP connections.

## First Step

{first_step}{setup_notes_section}

## What You Can Do

Use the `{REMOTE_TRIGGER_TOOL_NAME}` tool (load it first with `ToolSearch select:{REMOTE_TRIGGER_TOOL_NAME}`; auth is handled in-process — do not use curl):

- `{{"action": "list"}}` — list all triggers
- `{{"action": "get", "trigger_id": "..."}}` — fetch one trigger
- `{{"action": "create", "body": {{...}}}}` — create a trigger
- `{{"action": "update", "trigger_id": "...", "body": {{...}}}}` — partial update
- `{{"action": "run", "trigger_id": "..."}}` — run a trigger now

You CANNOT delete triggers. If the user asks to delete, direct them to: https://claude.ai/code/scheduled

## Create body shape

```json
{{
  "name": "AGENT_NAME",
  "cron_expression": "CRON_EXPR",
  "enabled": true,
  "job_config": {{
    "ccr": {{
      "environment_id": "ENVIRONMENT_ID",
      "session_context": {{
        "model": "claude-sonnet-4-6",
        "sources": [
          {{"git_repository": {{"url": "{git_repo_url or 'https://github.com/ORG/REPO'}"}}}}
        ],
        "allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
      }},
      "events": [
        {{"data": {{
          "uuid": "<lowercase v4 uuid>",
          "session_id": "",
          "type": "user",
          "parent_tool_use_id": null,
          "message": {{"content": "PROMPT_HERE", "role": "user"}}
        }}}}
      ]
    }}
  }}
}}
```

Generate a fresh lowercase UUID for `events[].data.uuid` yourself.

## Available MCP Connectors

These are the user's currently connected claude.ai MCP connectors:

{connectors_info}

When attaching connectors to a trigger, use the `connector_uuid` and `name` shown above (the name is already sanitized to only contain letters, numbers, hyphens, and underscores), and the connector's URL. The `name` field in `mcp_connections` must only contain `[a-zA-Z0-9_-]` — dots and spaces are NOT allowed.

**Important:** Infer what services the agent needs from the user's description. For example, if they say "check Datadog and Slack me errors," the agent needs both Datadog and Slack connectors. Cross-reference against the list above and warn if any required service isn't connected. If a needed connector is missing, direct the user to https://claude.ai/settings/connectors to connect it first.

## Environments

Every trigger requires an `environment_id` in the job config. This determines where the remote agent runs. Ask the user which environment to use.

{environments_info}

Use the `id` value as the `environment_id` in `job_config.ccr.environment_id`.{env_creation_note}

## API Field Reference

### Create Trigger — Required Fields
- `name` (string) — A descriptive name
- `cron_expression` (string) — 5-field cron. **Minimum interval is 1 hour.**
- `job_config` (object) — Session configuration (see structure above)

### Create Trigger — Optional Fields
- `enabled` (boolean, default: true)
- `mcp_connections` (array) — MCP servers to attach:
  ```json
  [{{"connector_uuid": "uuid", "name": "server-name", "url": "https://..."}}]
  ```

### Update Trigger — Optional Fields
All fields optional (partial update):
- `name`, `cron_expression`, `enabled`, `job_config`
- `mcp_connections` — Replace MCP connections
- `clear_mcp_connections` (boolean) — Remove all MCP connections

### Cron Expression Examples

The user's local timezone is **{user_timezone}**. Cron expressions are always in UTC. When the user says a local time, convert it to UTC for the cron expression but confirm with them: "9am {user_timezone} = Xam UTC, so the cron would be `0 X * * 1-5`."

- `0 9 * * 1-5` — Every weekday at 9am **UTC**
- `0 */2 * * *` — Every 2 hours
- `0 0 * * *` — Daily at midnight **UTC**
- `30 14 * * 1` — Every Monday at 2:30pm **UTC**
- `0 8 1 * *` — First of every month at 8am **UTC**

Minimum interval is 1 hour. `*/30 * * * *` will be rejected.

## Workflow

### CREATE a new trigger:

1. **Understand the goal** — Ask what they want the remote agent to do. What repo(s)? What task? Remind them that the agent runs remotely — it won't have access to their local machine, local files, or local environment variables.
2. **Craft the prompt** — Help them write an effective agent prompt. Good prompts are:
   - Specific about what to do and what success looks like
   - Clear about which files/areas to focus on
   - Explicit about what actions to take (open PRs, commit, just analyze, etc.)
3. **Set the schedule** — Ask when and how often. The user's timezone is {user_timezone}. When they say a time (e.g., "every morning at 9am"), assume they mean their local time and convert to UTC for the cron expression. Always confirm the conversion: "9am {user_timezone} = Xam UTC."
4. **Choose the model** — Default to `claude-sonnet-4-6`. Tell the user which model you're defaulting to and ask if they want a different one.
5. **Validate connections** — Infer what services the agent will need from the user's description. For example, if they say "check Datadog and Slack me errors," the agent needs both Datadog and Slack MCP connectors. Cross-reference with the connectors list above. If any are missing, warn the user and link them to https://claude.ai/settings/connectors to connect first.{git_repo_note}
6. **Review and confirm** — Show the full configuration before creating. Let them adjust.
7. **Create it** — Call `{REMOTE_TRIGGER_TOOL_NAME}` with `action: "create"` and show the result. The response includes the trigger ID. Always output a link at the end: `https://claude.ai/code/scheduled/{{TRIGGER_ID}}`

### UPDATE a trigger:

1. List triggers first so they can pick one
2. Ask what they want to change
3. Show current vs proposed value
4. Confirm and update

### LIST triggers:

1. Fetch and display in a readable format
2. Show: name, schedule (human-readable), enabled/disabled, next run, repo(s)

### RUN NOW:

1. List triggers if they haven't specified which one
2. Confirm which trigger
3. Execute and confirm

## Important Notes

- These are REMOTE agents — they run in Anthropic's cloud, not on the user's machine. They cannot access local files, local services, or local environment variables.
- Always convert cron to human-readable when displaying
- Default to `enabled: true` unless user says otherwise
- Accept GitHub URLs in any format (https://github.com/org/repo, org/repo, etc.) and normalize to the full HTTPS URL (without .git suffix)
- The prompt is the most important part — spend time getting it right. The remote agent starts with zero context, so the prompt must be self-contained.
- To delete a trigger, direct users to https://claude.ai/code/scheduled
{github_reminder}{user_request_section}"""


async def get_prompt_for_command(args: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate the prompt for the schedule remote agents command.
    
    Args:
        args: User arguments
        context: Tool use context
        
    Returns:
        List of content blocks
    """
    # Check OAuth authentication
    tokens = get_cloud_ai_oauth_tokens()
    if not tokens or not tokens.get("accessToken"):
        return [{
            "type": "text",
            "text": "You need to authenticate with a claude.ai account first. API accounts are not supported. Run /login, then try /schedule again.",
        }]
    
    # Fetch environments
    try:
        environments = await fetch_environments()
    except Exception as err:
        log_for_debugging(f"[schedule] Failed to fetch environments: {err}", {"level": "warn"})
        return [{
            "type": "text",
            "text": "We're having trouble connecting with your remote claude.ai account to set up a scheduled task. Please try /schedule again in a few minutes.",
        }]
    
    # Create default environment if none exist
    created_environment = None
    if not environments:
        try:
            created_environment = await create_default_cloud_environment("claude-code-default")
            environments = [created_environment]
        except Exception as err:
            log_for_debugging(f"[schedule] Failed to create environment: {err}", {"level": "warn"})
            return [{
                "type": "text",
                "text": "No remote environments found, and we could not create one automatically. Visit https://claude.ai/code to set one up, then run /schedule again.",
            }]
    
    # Collect setup notes
    setup_notes: List[str] = []
    needs_github_access_reminder = False
    
    repo = await detect_current_repository_with_host()
    if repo is None:
        setup_notes.append("Not in a git repo — you'll need to specify a repo URL manually (or skip repos entirely).")
    elif repo.get("host") == "github.com":
        access_result = await check_repo_for_remote_access(repo["owner"], repo["name"])
        if not access_result.get("hasAccess"):
            needs_github_access_reminder = True
            web_setup_enabled = get_feature_value_cached_may_be_stale('tengu_cobalt_lantern', False)
            if web_setup_enabled:
                msg = f"GitHub not connected for {repo['owner']}/{repo['name']} — run /web-setup to sync your GitHub credentials, or install the Claude GitHub App at https://claude.ai/code/onboarding?magic=github-app-setup."
            else:
                msg = f"Claude GitHub App not installed on {repo['owner']}/{repo['name']} — install at https://claude.ai/code/onboarding?magic=github-app-setup if your trigger needs this repo."
            setup_notes.append(msg)
    
    # Get MCP connectors
    mcp_clients = context.get("options", {}).get("mcpClients", [])
    connectors = get_connected_cloud_ai_connectors(mcp_clients)
    if not connectors:
        setup_notes.append("No MCP connectors — connect at https://claude.ai/settings/connectors if needed.")
    
    # Get timezone
    import locale
    try:
        user_timezone = locale.getdefaultlocale()[0] or "UTC"
    except:
        user_timezone = "UTC"
    
    connectors_info = format_connectors_info(connectors)
    git_repo_url = await get_current_repo_https_url()
    
    # Format environments info
    env_lines = ["Available environments:"]
    for env in environments:
        env_lines.append(f"- {env.get('name')} (id: {env.get('environment_id')}, kind: {env.get('kind')})")
    environments_info = "\n".join(env_lines)
    
    # Build prompt
    prompt = build_prompt({
        "user_timezone": user_timezone,
        "connectors_info": connectors_info,
        "git_repo_url": git_repo_url,
        "environments_info": environments_info,
        "created_environment": created_environment,
        "setup_notes": setup_notes,
        "needs_github_access_reminder": needs_github_access_reminder,
        "user_args": args,
    })
    
    return [{"type": "text", "text": prompt}]


def is_skill_enabled() -> bool:
    """Check if the schedule skill is enabled."""
    return (
        get_feature_value_cached_may_be_stale('tengu_surreal_dali', False) and
        is_policy_allowed('allow_remote_sessions')
    )


def register_schedule_remote_agents_skill() -> None:
    """Register the schedule remote agents skill."""
    register_bundled_skill({
        "name": "schedule",
        "description": "Create, update, list, or run scheduled remote agents (triggers) that execute on a cron schedule.",
        "when_to_use": "When the user wants to schedule a recurring remote agent, set up automated tasks, create a cron job for Claude Code, or manage their scheduled agents/triggers.",
        "user_invocable": True,
        "is_enabled": is_skill_enabled,
        "allowed_tools": [REMOTE_TRIGGER_TOOL_NAME, ASK_USER_QUESTION_TOOL_NAME],
        "get_prompt_for_command": get_prompt_for_command,
    })


# For direct execution/testing
if __name__ == "__main__":
    import asyncio
    
    async def test():
        context = {"options": {"mcpClients": []}}
        result = await get_prompt_for_command("", context)
        print(result[0]["text"][:500] + "...")
    
    asyncio.run(test())
