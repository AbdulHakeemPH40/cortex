"""Utility script: print chat history grouped by project.

Unit tests patch `src.core.chat_history.get_chat_history`, so this module must
call that function via the module at runtime (not a directly-imported symbol).

Note: We use explicit Unicode escape sequences to avoid Windows codepage issues.
"""

from __future__ import annotations

from collections import defaultdict

import src.core.chat_history as chat_history


def main() -> None:
    history = chat_history.get_chat_history()
    conversations = history.get_conversations() if history else []

    if not conversations:
        print("❌ Database is completely empty!")
        return

    total = len(conversations)
    print(f"✅ Found {total} total chat(s) in database:")

    grouped: dict[str, int] = defaultdict(int)
    for conv in conversations:
        project_path = None
        if isinstance(conv, dict):
            project_path = conv.get('project_path')
        project_path = project_path or 'NO PATH'
        grouped[str(project_path)] += 1

    for project_path in sorted(grouped.keys()):
        print(f"📁 Project: {project_path}")
        print(f"   Chats: {grouped[project_path]}")


__all__ = ['main']


if __name__ == '__main__':
    main()
