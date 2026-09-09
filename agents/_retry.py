"""Shared retry policy; provider adapters retain command and stream handling."""

from dataclasses import replace


def session_is_invalid(result):
    """Only inspect failed runtime diagnostics, never successful model prose.

    A compact/network error alone does not establish an invalid session.
    """
    if result.returncode == 0:
        return False
    error = (result.error or "").lower()
    return any(marker in error for marker in (
        "context_window_exceeded", "context_length_exceeded",
        "ran out of room in the model's context window",
        "maximum context length", "prompt is too long", "prompt too long",
        "session not found", "invalid session", "session expired",
        "conversation not found", "thread not found",
    ))


def run_with_retry(run_once, session_id, *, retries, delay, sleep, invalidate=None):
    """Invalidate durably before retrying; allow at most one fresh-session recovery.

    The callback must propagate persistence errors, otherwise a restart could
    resurrect the invalid session. A failed fresh attempt is never persisted.
    """
    current = session_id
    recovered = False
    for attempt in range(retries + 1):
        result = run_once(current)
        if result.returncode == 0:
            return result
        if session_is_invalid(result):
            if invalidate is not None:
                invalidate()
            current = None
            result = replace(result, session_id=None)
            if recovered:
                return result
            recovered = True
        else:
            current = result.session_id or current
        if attempt == retries:
            return replace(result, session_id=None) if recovered else result
        sleep(delay)
