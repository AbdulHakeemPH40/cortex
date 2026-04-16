"""
debug - Logging utility for the agent/memdir subsystems.

Provides logForDebugging() which the memdir package uses for internal tracing.
Routes to Python's standard logging at DEBUG level so it's visible when
log level is set to DEBUG but silent in normal operation.
"""

import logging

_log = logging.getLogger('cortex.agent')


def logForDebugging(msg: str, **kwargs) -> None:
    """
    Emit a debug-level log message.

    kwargs may include:
        level: 'warn' | 'info' | 'debug'  (default: 'debug')
        data:  any extra context dict
    """
    level = str(kwargs.get('level', 'debug')).lower()
    if level == 'warn':
        _log.warning('[memdir] %s', msg)
    elif level == 'info':
        _log.info('[memdir] %s', msg)
    else:
        _log.debug('[memdir] %s', msg)
