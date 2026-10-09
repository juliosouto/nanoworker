"""Token-usage accounting (Fase 6) — one row per agent turn.

Every execution stack (LangChain runner + the two legacy provider loops) logs
its consumed tokens here via :func:`log_llm_usage`, and
:func:`get_usage_summary` / :func:`get_usage_by_model` feed the before/after
(legacy vs langchain) card on the dashboard.

Measurement must never break the chat: :func:`log_llm_usage` opens its own
short-lived connection (no caller cursor needed) and swallows every database
error, surfacing it only as a ``logger.warning``.

Known limitation: turns aborted by an exception (user /stop, exhausted 429
retries) are NOT logged — every stack logs only on its normal exit paths, so
tokens spent on aborted turns stay unaccounted.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def log_llm_usage(
    session_id,
    message_in_id,
    stack: str,
    model,
    input_tokens=None,
    output_tokens=None,
) -> bool:
    """Insert one usage row for a finished agent turn.

    Args:
        session_id: chat session id (may be None for internal calls).
        message_in_id: the input message that triggered the turn.
        stack: 'legacy' | 'langchain' (stored verbatim if unknown).
        model: provider model name (kept as passed, incl. any prefix).
        input_tokens: prompt tokens consumed, or None when unavailable.
        output_tokens: completion tokens consumed, or None when unavailable.

    Returns:
        bool: True when the row was written, False when skipped (both counts
        None) or when the insert failed (measurement must never raise).
    """
    if input_tokens is None and output_tokens is None:
        return False

    from database import get_db

    try:
        conn = get_db()
        try:
            conn.execute(
                """
                INSERT INTO llm_usage
                    (session_id, message_in_id, stack, model,
                     input_tokens, output_tokens)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message_in_id,
                    stack,  # stored verbatim ('legacy' | 'langchain' | future)
                    model,
                    input_tokens,
                    output_tokens,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        # The llm_usage table may not exist on databases whose init_db ran
        # before Fase 6 was deployed (the app creates it on next boot), or the
        # disk may be temporarily unavailable: log and move on.
        logger.warning("llm_usage insert skipped (%s)", e)
        return False
    return True


def _days_since(days: int) -> int:
    """Clamp the dashboard window to a sane range (1..90 days)."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 14
    return max(1, min(90, days))


def get_usage_summary(days: int = 14) -> list:
    """Aggregate usage per stack for the dashboard before/after card.

    Args:
        days: look-back window in days (clamped to 1..90, default 14).

    Returns:
        list of dicts: stack, turns, input_tokens, output_tokens,
        total_tokens, avg_tokens_per_turn. Empty list when the table is
        missing (pre-Fase-6 database that has not run init_db yet).
    """
    from database import get_db

    window = _days_since(days)
    try:
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT stack,
                       COUNT(*) AS turns,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens
                FROM llm_usage
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY stack
                ORDER BY stack
                """,
                (window,),
            ).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("llm_usage summary unavailable (%s)", e)
        return []
    out = []
    for row in rows:
        total = (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
        turns = row["turns"] or 0
        out.append(
            {
                "stack": row["stack"],
                "turns": turns,
                "input_tokens": row["input_tokens"] or 0,
                "output_tokens": row["output_tokens"] or 0,
                "total_tokens": total,
                "avg_tokens_per_turn": round(total / turns, 1) if turns else 0.0,
            }
        )
    return out


def get_usage_by_model(days: int = 14, limit: int = 12) -> list:
    """Aggregate usage per (stack, model) for the dashboard breakdown table.

    Args:
        days: look-back window (same clamping as get_usage_summary).
        limit: maximum number of rows returned (top consumers by total).

    Returns:
        list of dicts: stack, model, turns, input_tokens, output_tokens,
        total_tokens. Empty list when the table is missing.
    """
    from database import get_db

    window = _days_since(days)
    try:
        limit_int = int(limit)
    except (TypeError, ValueError):
        limit_int = 12
    limit = max(1, min(50, limit_int))
    try:
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT stack,
                       COALESCE(model, '(unknown)') AS model,
                       COUNT(*) AS turns,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(COALESCE(input_tokens, 0)
                                    + COALESCE(output_tokens, 0)), 0) AS total_tokens
                FROM llm_usage
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY stack, COALESCE(model, '(unknown)')
                ORDER BY total_tokens DESC
                LIMIT ?
                """,
                (window, limit),
            ).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("llm_usage per-model summary unavailable (%s)", e)
        return []
    return [
        {
            "stack": row["stack"],
            "model": row["model"],
            "turns": row["turns"] or 0,
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "total_tokens": row["total_tokens"] or 0,
        }
        for row in rows
    ]
