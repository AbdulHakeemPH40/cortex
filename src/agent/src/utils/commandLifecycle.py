# ------------------------------------------------------------
# command_lifecycle.py
# Python conversion of utils/commandLifecycle.ts
#
# Notifies the command queue about command lifecycle events:
# started, completed, cancelled, etc.
# This enables the UI to show command progress and allows
# subsequent commands to wait for prerequisites.
# ------------------------------------------------------------

from typing import Literal, Optional

__all__ = ["notify_command_lifecycle"]


def notify_command_lifecycle(
    uuid: str,
    status: Literal["started", "completed", "cancelled", "failed"],
    extra: Optional[dict] = None,
) -> None:
    """
    Notify the command lifecycle system of a status change.

    Mirrors TS notifyCommandLifecycle() exactly.

    Args:
        uuid:   UUID of the command
        status: Lifecycle event ('started', 'completed', 'cancelled', 'failed')
        extra:  Optional extra data (e.g., error message)
    """
    # TODO: integrate with the command queue manager.
    # The full implementation notifies the message queue manager so that
    # queued commands can react to lifecycle events.
    # For now, this is a no-op stub.
    pass
