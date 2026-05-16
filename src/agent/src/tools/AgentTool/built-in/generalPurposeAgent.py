# general_purpose_agent.py
"""
General Purpose Agent - Versatile agent for complex tasks in Cortex IDE.

Handles complex questions, code searches, and multi-step tasks.
"""

from __future__ import annotations

from typing import List
from dataclasses import dataclass


SHARED_PREFIX = """You are an agent for Cortex IDE. Given the user's message, you should use the tools available to complete the task. Complete the task fully—don't gold-plate, but don't leave it half-done."""

SHARED_GUIDELINES = """Your strengths:
- Searching for code, configurations, and patterns across large codebases
- Analyzing multiple files to understand system architecture
- Investigating complex questions that require exploring many files
- Performing multi-step research tasks

Guidelines:
- For file searches: search broadly when you don't know where something lives. Use Read when you know the specific file path.
- For analysis: Start broad and narrow down. Use multiple search strategies if the first doesn't yield results.
- Be thorough: Check multiple locations, consider different naming conventions, look for related files.
- NEVER create files unless they're absolutely necessary for achieving your goal. ALWAYS prefer editing an existing file to creating a new one.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested."""

# Note: absolute-path + emoji guidance is appended by enhance_system_prompt_with_env_details.


def get_general_purpose_system_prompt() -> str:
    """Generate the system prompt for the General Purpose agent."""
    return f"""{SHARED_PREFIX} When you complete the task, respond with a concise report covering what was done and any key findings — the caller will relay this to the user, so it only needs the essentials.

{SHARED_GUIDELINES}"""


@dataclass
class BuiltInAgentDefinition:
    """Definition for a built-in agent."""
    agent_type: str
    when_to_use: str
    tools: List[str]
    source: str
    base_dir: str
    get_system_prompt: callable = None
    model: str = None  # intentionally omitted - uses get_default_subagent_model()


GENERAL_PURPOSE_AGENT = BuiltInAgentDefinition(
    agent_type="general-purpose",
    when_to_use=(
        "General-purpose agent for researching complex questions, searching for code, "
        "and executing multi-step tasks. When you are searching for a keyword or file "
        "and are not confident that you will find the right match in the first few tries "
        "use this agent to perform the search for you."
    ),
    tools=["*"],
    source="built-in",
    base_dir="built-in",
    # model is intentionally omitted - uses get_default_subagent_model().
    get_system_prompt=get_general_purpose_system_prompt,
)
