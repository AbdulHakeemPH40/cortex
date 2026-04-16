# cortex_code_guide_agent.py
"""
Cortex IDE Guide agent - helps users understand and use the Cortex IDE.

Features:
- Agent type: ``cortex-code-guide``.
- Multi‑LLM support: Claude (Anthropic), GPT/Codex (OpenAI), Gemini (Google), 
  Grok, and DeepSeek (via OpenAI SDK compatibility).
- Conditional tool list based on embedded search support.
- Dynamic system prompt incorporating custom skills, agents, MCP servers,
  plugin commands, and user settings.
- Focuses on Cortex IDE features and LLM provider integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

# ----------------------------------------------------------------------
# Project‑specific imports – replace with actual paths in your repository
# ----------------------------------------------------------------------
from ...BashTool.toolName import BASH_TOOL_NAME
from ...GlobTool.prompt import GLOB_TOOL_NAME
from ...GrepTool.prompt import GREP_TOOL_NAME
from ...SendMessageTool.constants import SEND_MESSAGE_TOOL_NAME
from ...WebFetchTool.prompt import WEB_FETCH_TOOL_NAME
from ...WebSearchTool.prompt import WEB_SEARCH_TOOL_NAME
from ....utils.settings.settings import get_settings_deprecated

# ----------------------------------------------------------------------
# Documentation URLs (placeholders – replace with real URLs)
# ----------------------------------------------------------------------
CLAUDE_CODE_DOCS_MAP_URL = "https://code.claude.com/docs/en/claude_code_docs_map.md"
CDP_DOCS_MAP_URL = "https://platform.claude.com/llms.txt"

# ----------------------------------------------------------------------
# Agent identifiers
# ----------------------------------------------------------------------
CLAUDE_CODE_GUIDE_AGENT_TYPE = "claude-code-guide"

# ----------------------------------------------------------------------
# Multi‑LLM support
# ----------------------------------------------------------------------
SUPPORTED_MODELS: Dict[str, str] = {
    "anthropic": "Claude (Anthropic)",
    "openai-codex": "OpenAI Codex",
    "mistral": "Mistral",
    "deepseek": "DeepSeek (uses OpenAI SDK)",
    "grok": "Grok",
    "gemini": "Google Gemini",
}
DEFAULT_MODEL = "anthropic"

def choose_model(preferred: Optional[str] = None) -> str:
    """Return the model identifier to use, falling back to the default."""
    if preferred and preferred.lower() in SUPPORTED_MODELS:
        return preferred.lower()
    return DEFAULT_MODEL

# ----------------------------------------------------------------------
# Prompt helpers
# ----------------------------------------------------------------------
def _local_search_hint() -> str:
    """Hint that lists the available local file‑search tools."""
    if has_embedded_search_tools():
        # Embedded bfs/ugrep aliases replace dedicated Glob/Grep tools.
        return f"{FILE_READ_TOOL_NAME}, `find`, and `grep`"
    return f"{FILE_READ_TOOL_NAME}, {GLOB_TOOL_NAME}, and {GREP_TOOL_NAME}"

def get_cortex_code_guide_base_prompt() -> str:
    """Core system prompt describing Cortex IDE's expertise and docs sources."""
    local_search = _local_search_hint()
    return f"""You are the Cortex guide agent. Your primary responsibility is helping users understand
and use the Cortex IDE effectively.

Cortex is an intelligent development environment that connects to industry-leading LLM providers
including Claude (Anthropic), GPT/Codex (OpenAI), Gemini (Google), Grok, and DeepSeek.
Each model uses its native SDK - DeepSeek uses the OpenAI SDK compatibility layer.

**Your expertise:**

1. **Cortex IDE Features**: Installation, configuration, custom skills, MCP servers,
   keyboard shortcuts, settings, workflows, and multi-model support.

2. **Model Integration**: How Cortex connects to different LLM providers through their
   official SDKs (Anthropic SDK, OpenAI SDK, Google AI SDK, etc.).

3. **Development Workflow**: Using AI assistance for coding, debugging, refactoring,
   testing, and documentation within the Cortex IDE.

**Documentation sources:**

- **Cortex IDE docs** ({CLAUDE_CODE_DOCS_MAP_URL}): Installation, setup, configuration,
  custom skills, MCP servers, settings, keyboard shortcuts, model switching, plugins,
  and security.

- **Model-specific docs**: Official SDK documentation for each supported provider
  (Claude, OpenAI, Gemini, Grok, DeepSeek) accessible via {WEB_FETCH_TOOL_NAME}.

**Approach:**
1. Understand if the question is about Cortex IDE features or specific model usage.
2. Use {WEB_FETCH_TOOL_NAME} to fetch relevant documentation.
3. Provide clear, practical guidance with examples.
4. For model-specific questions, reference the appropriate SDK docs.
5. Use {WEB_SEARCH_TOOL_NAME} if documentation doesn't cover the topic.
6. Reference local project files using {local_search}.

**Guidelines:**
- Always prioritize official documentation.
- Keep responses practical and actionable.
- Include working code examples when relevant.
- Cite exact documentation URLs.
- Suggest related Cortex features proactively.

**Supported LLM Providers:** {', '.join(f'{k} ({v})' for k, v in SUPPORTED_MODELS.items())}."""

def get_feedback_guideline() -> str:
    """Return the feedback instruction, handling third‑party services."""
    if is_using_3p_services():
        return "- When you cannot find an answer or the feature doesn't exist, direct the user to ${MACRO.ISSUES_EXPLAINER}"
    return "- When you cannot find an answer or the feature doesn't exist, direct the user to use /feedback to report a feature request or bug"

# ----------------------------------------------------------------------
# Data structures for the built‑in agent definition
# ----------------------------------------------------------------------
@dataclass
class BuiltInAgentDefinition:
    """Immutable definition of a built‑in Cortex agent."""
    agent_type: str
    when_to_use: str
    tools: List[str]
    source: str = "built-in"
    base_dir: str = "built-in"
    model: str = field(default_factory=choose_model) # resolved lazily
    permission_mode: str = "dontAsk"
    system_prompt: str = "" # populated by ``get_system_prompt``

    def get_system_prompt(self, tool_use_context: Any) -> str:
        """Assemble the final system prompt with dynamic context sections."""
        commands = tool_use_context.options.commands
        context_sections: List[str] = []

        # 1️⃣ Custom skills (prompt‑type commands)
        custom_skills = [c for c in commands if c.type == "prompt"]
        if custom_skills:
            skill_list = "\n".join(f"- /{c.name}: {c.description}" for c in custom_skills)
            context_sections.append(
                f"**Available custom skills in this project:**\n{skill_list}"
            )

        # 2️⃣ Custom agents from .cortex/agents/
        custom_agents = [
            a
            for a in tool_use_context.options.agent_definitions.active_agents
            if a.source != "built-in"
        ]
        if custom_agents:
            agent_list = "\n".join(f"- {a.agent_type}: {a.when_to_use}" for a in custom_agents)
            context_sections.append(
                f"**Available custom agents configured:**\n{agent_list}"
            )

        # 3️⃣ MCP servers
        mcp_clients = getattr(tool_use_context.options, "mcp_clients", [])
        if mcp_clients:
            mcp_list = "\n".join(f"- {c.name}" for c in mcp_clients)
            context_sections.append(f"**Configured MCP servers:**\n{mcp_list}")

        # 4️⃣ Plugin commands (prompt‑type, source == "plugin")
        plugin_cmds = [
            c for c in commands if c.type == "prompt" and getattr(c, "source", None) == "plugin"
        ]
        if plugin_cmds:
            plugin_list = "\n".join(f"- /{c.name}: {c.description}" for c in plugin_cmds)
            context_sections.append(f"**Available plugin skills:**\n{plugin_list}")

        # 5️⃣ User settings (settings.json)
        settings = get_settings_deprecated()
        if settings:
            settings_json = json_stringify(settings, None, 2)
            context_sections.append(
                f"**User's settings.json:**\n```json$\n{settings_json}\n```"
            )

        # Base prompt + feedback guideline
        base_with_feedback = f"{get_cortex_code_guide_base_prompt()}\n{get_feedback_guideline()}"

        # Append dynamic sections if any exist
        if context_sections:
            extra = "\n\n---\n\n# User's Current Configuration\n\nThe user has the following custom setup in their environment:\n\n"
            extra += "\n\n".join(context_sections)
            return (
                f"{base_with_feedback}{extra}\n\nWhen answering questions, consider these configured features and proactively suggest them when relevant."
            )
        return base_with_feedback

# ----------------------------------------------------------------------
# Helper to decide which tool list to expose
# ----------------------------------------------------------------------
def _determine_tool_list() -> List[str]:
    """Return the appropriate tool list based on embedded‑search support."""
    if has_embedded_search_tools():
        return [
            BASH_TOOL_NAME,
            FILE_READ_TOOL_NAME,
            WEB_FETCH_TOOL_NAME,
            WEB_SEARCH_TOOL_NAME,
        ]
    return [
        GLOB_TOOL_NAME,
        GREP_TOOL_NAME,
        FILE_READ_TOOL_NAME,
        WEB_FETCH_TOOL_NAME,
        WEB_SEARCH_TOOL_NAME,
    ]

# ----------------------------------------------------------------------
# Exported agent definition
# ----------------------------------------------------------------------
CLAUDE_CODE_GUIDE_AGENT = BuiltInAgentDefinition(
    agent_type=CLAUDE_CODE_GUIDE_AGENT_TYPE,
    when_to_use=(
        "Use this agent when the user asks questions (e.g., \"Can Cortex...\", "
        "\"Does Cortex...\", \"How do I...\") about: (1) Cortex IDE features – "
        "installation, configuration, custom skills, MCP servers, settings, shortcuts, "
        "model switching; (2) LLM provider integration – using Claude, OpenAI, Gemini, "
        "Grok, or DeepSeek within Cortex; (3) Development workflows – coding, debugging, "
        "refactoring with AI assistance. "
        f"**IMPORTANT:** Before spawning a new agent, check if there is already a running "
        f"or recently completed cortex-code-guide agent that you can continue via {SEND_MESSAGE_TOOL_NAME}."
    ),
    tools=_determine_tool_list(),
    # ``model`` resolves lazily via ``choose_model``; callers may override it.
)

# ----------------------------------------------------------------------
# Example usage (for quick testing)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Minimal mock context to illustrate prompt generation
    class MockOptions:
        commands = [] # populate with mock command objects if needed
        agent_definitions = type("AgentDefs", (), {"active_agents": []})()
        mcp_clients = []

    class MockToolUseContext:
        options = MockOptions()

    prompt = CORTEX_CODE_GUIDE_AGENT.get_system_prompt(MockToolUseContext())
    print("=== Cortex System Prompt ===")
    print(prompt)