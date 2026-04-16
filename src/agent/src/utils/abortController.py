# ------------------------------------------------------------
# abortController.py
# Python conversion of utils/abortController.ts (lines 1-100)
#
# AbortController utilities:
# - create_abort_controller(): AbortController with listener limits
# - create_child_abort_controller(): child that auto-aborts when parent does
# ------------------------------------------------------------

import weakref
from typing import Any, Optional


class AbortController:
    """
    Python equivalent of the browser/nodish AbortController.
    Not signal-safe for subprocess termination — use for Python-side cancellation only.
    """
    def __init__(self):
        self._signal = AbortSignal(self)

    @property
    def signal(self) -> "AbortSignal":
        return self._signal

    def abort(self, reason: Any = None) -> None:
        self._signal._abort(reason)

    def __repr__(self) -> str:
        return f"AbortController(aborted={self._signal.aborted})"


class AbortSignal:
    """
    Python equivalent of AbortSignal.
    Supports addEventListener('abort', callback) and removeEventListener.
    """
    def __init__(self, controller: AbortController):
        self._controller = controller
        self._aborted = False
        self._reason: Any = None
        self._listeners: list[tuple[Any, bool]] = []  # (handler, oneshot)

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> Any:
        return self._reason

    def addEventListener(
        self,
        event: str,
        handler: Any,
        *,
        once: bool = False,
    ) -> None:
        if event != "abort":
            return
        self._listeners.append((handler, once))

    def removeEventListener(self, event: str, handler: Any) -> None:
        if event != "abort":
            return
        self._listeners = [
            (h, o) for h, o in self._listeners if h != handler
        ]

    def _abort(self, reason: Any = None) -> None:
        if self._aborted:
            return
        self._aborted = True
        self._reason = reason
        # Copy list since listeners may remove themselves during iteration
        listeners = list(self._listeners)
        self._listeners = []
        for handler, oneshot in listeners:
            try:
                handler()
            except Exception:
                pass  # Swallow handler errors

    def __repr__(self) -> str:
        return f"AbortSignal(aborted={self._aborted})"


# Module-level state for weakref cleanup tracking
_child_registry: "weakref.WeakSet[AbortController]" = weakref.WeakSet()  # type: ignore[type-arg]


def create_abort_controller(max_listeners: int = 50) -> AbortController:
    """
    Create an AbortController with proper listener management.

    Args:
        max_listeners: Unused in Python (kept for API parity with TS)

    Returns:
        AbortController instance
    """
    return AbortController()


def create_child_abort_controller(
    parent: AbortController,
    max_listeners: Optional[int] = None,
) -> AbortController:
    """
    Create a child AbortController that aborts when its parent aborts.
    Aborting the child does NOT affect the parent.

    Memory-safe: Uses WeakRef so the parent doesn't keep abandoned children alive.
    When the child IS aborted, the parent listener is removed to prevent
    accumulation of dead handlers.

    Mirrors TS createChildAbortController() exactly.

    Args:
        parent: The parent AbortController
        max_listeners: Unused (kept for API parity)

    Returns:
        Child AbortController
    """
    child = create_abort_controller(max_listeners or 50)

    # Fast path: parent already aborted
    if parent.signal.aborted:
        child.abort(parent.signal.reason)
        return child

    # Use WeakRef to avoid creating strong reference cycles
    weak_child = weakref.ref(child)
    weak_parent = weakref.ref(parent)

    def propagate_abort() -> None:
        """Called when parent aborts — abort child too."""
        parent_ref = weak_parent()
        child_ref = weak_child()
        if parent_ref and child_ref:
            child_ref.abort(parent_ref.signal.reason)

    def cleanup() -> None:
        """Called when child is aborted from any source — remove parent listener."""
        parent_ref = weak_parent()
        if parent_ref:
            parent_ref.signal.removeEventListener("abort", propagate_abort)

    parent.signal.addEventListener("abort", propagate_abort)
    child.signal.addEventListener("abort", cleanup, once=True)

    # Track child so WeakRef stays valid until abort or GC
    _child_registry.add(child)  # type: ignore[arg-type]

    return child


__all__ = [
    "AbortController",
    "AbortSignal",
    "create_abort_controller",
    "create_child_abort_controller",
]
