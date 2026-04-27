# ------------------------------------------------------------
# transitions.py (query)
# Python conversion of query/ transitions type exports
#
# Terminal state and Continue sentinel types.
# These represent the two possible "return" values from query():
#   - Terminal: a dict describing why the query ended (completed, error, etc.)
#   - Continue: sentinel meaning the generator should keep going
# ------------------------------------------------------------

from typing import Any, Dict, Literal, Union

__all__ = ["Terminal", "Continue"]


# Terminal state: query ended for a specific reason
Terminal = Dict[str, Any]

# Continue sentinel: loop should keep iterating
# (In Python, we just return None from the async generator to signal continue)
Continue = None


# For type narrowing — used when you need to distinguish between terminal
# and continue cases in the same union
TerminalOrContinue = Union[Terminal, Continue]
