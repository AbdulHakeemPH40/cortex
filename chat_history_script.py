"""Convenience entrypoint for chat history listing.

Tests import `chat_history_script` from the repo root.
"""

from __future__ import annotations

from src.agent.src.chat_history_script import main

__all__ = ['main']


if __name__ == '__main__':
    main()
