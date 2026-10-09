"""
In-flight /stop detection for long-running LLM retries.

The /stop command must interrupt not only the autonomous loop iterations
(between LLM calls) but also the rate-limit/quota retry waits that can block a
worker for several minutes inside provider calls. The autonomous loop registers
a per-thread stop-check callable here; providers consult it while waiting
(sleep_interruptible) and abort by raising StopRequestedError.
"""
import time
from contextvars import ContextVar


class StopRequestedError(Exception):
    """Raised when the user issued /stop while an LLM call was in flight."""


_stop_check: ContextVar = ContextVar("nanoworker_stop_check", default=None)


def set_stop_check(check):
    """
    Registers the callable that returns True when /stop was requested for the
    message currently being processed. Returns the reset token to pass to
    reset_stop_check (call it in a finally block).
    """
    return _stop_check.set(check)


def reset_stop_check(token):
    """Restores the previous stop-check state after processing finishes."""
    _stop_check.reset(token)


def is_stop_requested() -> bool:
    """
    True when a stop check is registered and it reports /stop. A checker that
    fails is treated as "no stop" so a broken check never wedges the retries.
    """
    check = _stop_check.get()
    if check is None:
        return False
    try:
        return bool(check())
    except Exception:
        return False


def sleep_interruptible(seconds: float, poll_interval: float = 1.0) -> bool:
    """
    Sleeps for `seconds` in small chunks, polling for /stop between chunks so
    the command takes effect within ~1s even during multi-minute retry waits.

    Returns:
        bool: True if a stop was requested during the wait (the caller must
            abort), False if the full wait elapsed without a stop.
    """
    remaining = float(seconds)
    while remaining > 0:
        if is_stop_requested():
            return True
        chunk = min(poll_interval, remaining)
        time.sleep(chunk)
        remaining -= chunk
    return is_stop_requested()