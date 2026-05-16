"""Adaptive tool selection helpers for agent workflows."""

from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, List, Sequence


class ConversationPhase(Enum):
    EXPLORATION = "exploration"
    CREATION = "creation"
    MODIFICATION = "modification"
    DEBUGGING = "debugging"
    EXECUTION = "execution"


_PHASE_KEYWORDS: Dict[ConversationPhase, tuple[str, ...]] = {
    ConversationPhase.CREATION: (
        "create", "new file", "generate", "build", "make", "scaffold", "add file",
    ),
    ConversationPhase.EXECUTION: (
        "run", "execute", "test it", "launch", "start", "migrate", "command",
    ),
    ConversationPhase.DEBUGGING: (
        "fix", "debug", "error", "crash", "failing", "broken", "issue", "bug",
    ),
    ConversationPhase.EXPLORATION: (
        "show", "explore", "inspect", "structure", "list", "find", "search", "open",
    ),
    ConversationPhase.MODIFICATION: (
        "edit", "modify", "update", "change", "refactor", "rewrite", "add logging",
    ),
}

_PHASE_TOOL_PRIORITIES: Dict[ConversationPhase, tuple[str, ...]] = {
    ConversationPhase.CREATION: (
        "write_file", "read_file", "edit_file", "get_file_outline",
    ),
    ConversationPhase.EXECUTION: (
        "run_command", "bash", "check_syntax", "read_file",
    ),
    ConversationPhase.DEBUGGING: (
        "read_file", "grep", "search_codebase", "check_syntax", "edit_file", "get_file_outline",
    ),
    ConversationPhase.EXPLORATION: (
        "list_directory", "read_file", "search_codebase", "grep", "get_file_outline",
    ),
    ConversationPhase.MODIFICATION: (
        "read_file", "edit_file", "write_file", "grep", "get_file_outline",
    ),
}


class AdaptiveToolSelector:
    """Select a smaller, phase-appropriate subset of tools."""

    def analyze_conversation_phase(
        self,
        messages: Sequence[dict] | None,
        user_message: str,
    ) -> ConversationPhase:
        text_parts: List[str] = []
        if messages:
            text_parts.extend(str(message.get("content", "")) for message in messages[-6:])
        text_parts.append(user_message or "")
        haystack = " ".join(text_parts).lower()

        for phase in (
            ConversationPhase.DEBUGGING,
            ConversationPhase.EXECUTION,
            ConversationPhase.CREATION,
            ConversationPhase.MODIFICATION,
            ConversationPhase.EXPLORATION,
        ):
            if any(keyword in haystack for keyword in _PHASE_KEYWORDS[phase]):
                return phase

        return ConversationPhase.EXPLORATION

    def get_tools_for_phase(
        self,
        phase: ConversationPhase,
        all_tools: Sequence[dict],
        max_tools: int = 8,
    ) -> List[dict]:
        prioritized_names = _PHASE_TOOL_PRIORITIES.get(phase, ())
        selected: List[dict] = []
        seen_names = set()

        def add_matching_tools(names: Iterable[str]) -> None:
            for desired_name in names:
                for tool in all_tools:
                    tool_name = tool.get("function", {}).get("name")
                    if tool_name == desired_name and tool_name not in seen_names:
                        selected.append(tool)
                        seen_names.add(tool_name)
                        if len(selected) >= max_tools:
                            return
                if len(selected) >= max_tools:
                    return

        add_matching_tools(prioritized_names)
        return selected


def select_tools_adaptively(
    messages: Sequence[dict] | None,
    user_message: str,
    all_tools: Sequence[dict],
    max_tools: int = 8,
) -> List[dict]:
    selector = AdaptiveToolSelector()
    phase = selector.analyze_conversation_phase(messages, user_message)
    return selector.get_tools_for_phase(phase, all_tools, max_tools=max_tools)
