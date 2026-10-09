"""Progressive conversation summarization (phase 3).

Lifecycle on every incoming message:

1. Rebuild the full Gemini-format history from messages_in/messages_out.
2. If tokens(history) + tokens(current) exceeds LC_SUMMARY_THRESHOLD_PCT% of
   MESSAGE_SLICE_SIZE_TOKENS, the oldest block of the conversation is summarized
   with a cheap model (LC_SUMMARIZER_MODEL) and the running summary is cached in
   sessions.summary with a watermark in sessions.summary_until. The last
   LC_KEEP_RECENT_MSGS messages stay verbatim.
3. If the reduced context still does not fit the budget, langchain_core's
   ``trim_messages`` with a real token counter is used as the last resort.

Below the threshold the history is passed verbatim (cheap path). Any failure
while summarizing degrades to the legacy ``slice_conversation_to_budget``
without loss of the current message.
"""

import logging

import time

from agent.lc import settings as lc_settings
from agent.lc.tokens import count_tokens, truncate_tail
from agent.llm_router import route_llm_call
from utils.message_utils import slice_conversation_to_budget

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Negative cache: if the summarizer model recently failed, skip it for this
# long. Without it, a misconfigured LC_SUMMARIZER_MODEL (e.g. rate-limited /
# wrong name -> auth failure) pays a full retry chain (5 retries, and on 429
# waits "until the next minute") on every message that crosses the threshold,
# degrading to the legacy slicer only after wasting ~1 minute per message.
# ---------------------------------------------------------------------------
_SUMMARIZER_FAIL_UNTIL = 300


class _NegativeCache:
    _value: float | None = None

    def hit(self) -> bool:
        """Return True if we are in the failure-cooldown window and must
        skip the summarizer."""
        now = time.time()
        v = self._value
        if v is not None and now < v:
            return True
        self._value = None
        return False

    def record(self) -> None:
        """Enter the cooldown window after a failure."""
        self._value = time.time() + _SUMMARIZER_FAIL_UNTIL


_negative_cache = _NegativeCache()


def _history_text(msg) -> str:
    """Plain text of a Gemini ``types.Content`` or a langchain ``BaseMessage``."""
    if hasattr(msg, "parts"):
        return " ".join(getattr(p, "text", "") or "" for p in getattr(msg, "parts", []) or [])
    if hasattr(msg, "content"):
        c = msg.content
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(x) for x in c)
    return ""


def _budget() -> int:
    """The combined conversation budget (MESSAGE_SLICE_SIZE_TOKENS)."""
    try:
        from database import get_config
        return int(get_config("MESSAGE_SLICE_SIZE_TOKENS", "2000"))
    except Exception:
        return 2000


def _fetch_conversation_between(cursor, session_id, message_in_id, watermark):
    """Return (texts, last_created_at) of conversation messages whose
    ``created_at`` is newer than the summary watermark, excluding the current
    incoming message. Empty list / None means no new messages to fold in.

    Uses ``>=`` on the watermark so that messages written in the same second as
    the last folded message (created_at has second precision) are still
    included. The boundary message is re-folded when a newer one arrives; that
    is idempotent because the running summary already covers it.
    """
    if watermark is None:
        watermark = ""
    cursor.execute(
        """
        SELECT content, created_at FROM (
            SELECT content, created_at FROM messages_in
                WHERE session_id = ? AND id != ?
            UNION ALL
            SELECT content, created_at FROM messages_out
                WHERE session_id = ?
        ) AS x
        WHERE x.created_at >= ?
        ORDER BY x.created_at ASC
        """,
        (session_id, message_in_id, session_id, watermark),
    )
    rows = cursor.fetchall()
    if not rows:
        return [], None
    return [row["content"] for row in rows], rows[-1]["created_at"]


def _summarize_block(previous_summary, new_texts, session_id, cursor):
    """Call the cheap summarizer model once to consolidate a new conversation
    block into the running summary."""
    model = lc_settings.summarizer_model()
    if not model:
        raise ValueError("summarizer disabled")

    max_tokens = lc_settings.summary_max_tokens()
    previous = (
        f"Conversation so far (target: up to {max_tokens} tokens):\n{previous_summary}\n\n"
        if previous_summary
        else ""
    )
    prompt = (
        "You are compressing a multi-turn conversation for long-term context retention.\n"
        f"{previous}"
        "New messages to fold in:\n" + "\n".join(new_texts) + "\n\n"
        "Produce a compact summary capturing established facts, decisions, and open tasks. "
        "Omit trivial small talk and verbatim dialogue. Use the same language as the "
        "conversation. Respond with ONLY the summary text - no headings, no explanation. "
        f"The final summary must be at most {max_tokens} tokens.\n\nSummary:"
    )

    try:
        return route_llm_call(
            model_name=model,
            history=[],
            config_kwargs={},
            content=prompt,
            cursor=cursor,
            session_id=session_id,
            message_in_id="summarize-0",
            is_ide=True,
            on_complete=None,
            summarize=True,
        )
    except Exception as exc:
        _negative_cache.record()
        logger.warning("Summarizer model %r failed; in cooldown for %ds: %s", model, _SUMMARIZER_FAIL_UNTIL, exc)
        raise
    finally:
        try:
            cursor.execute(
                "DELETE FROM ide_messages_out WHERE in_reply_to = ?",
                ("summarize-0",),
            )
            cursor.connection.commit()
        except Exception as exc:
            logger.warning("Could not purge summarizer feedback rows: %s", exc)





def summarize_then_trim(history, current_text, session_id, cursor, message_in_id):
    """Trim conversation history with progressive summarization instead of
    dropping oldest messages blindly.

    This replaces ``slice_conversation_to_budget`` as the conversation-budget
    controller (see ``agent/message_processor.py``).

    Returns:
        tuple: ``(reduced_history, current_text)``.
    """
    mode = lc_settings.token_counter_mode()
    budget = _budget()
    keep_n = lc_settings.keep_recent_messages()
    pct = lc_settings.summary_threshold_pct()
    max_tokens = lc_settings.summary_max_tokens()

    # Same semantics as the legacy slicer: the current message is truncated to
    # the budget but never dropped.
    current_text = truncate_tail(current_text, budget, mode=mode)
    current_tokens = count_tokens(current_text, mode=mode)

    history_text_total = sum(count_tokens(_history_text(m), mode=mode) for m in history)
    threshold_tokens = (pct * budget) // 100

    # Cheap path: below the threshold, pass the history verbatim.
    if history_text_total + current_tokens <= threshold_tokens:
        return list(history), current_text

    # Feature switch: summarizer disabled -> degrade to the legacy slicer.
    model = lc_settings.summarizer_model()
    if not model:
        logger.info("Phase-3 summarizer disabled (LC_SUMMARIZER_MODEL empty); using legacy slicer")
        return slice_conversation_to_budget(history, current_text)

    if session_id is None or cursor is None:
        logger.warning("summarize_then_trim needs session_id + cursor; using legacy slicer")
        return slice_conversation_to_budget(history, current_text)

    history = list(history)

    # Nothing can be offloaded: keep the last keep_n messages verbatim and let
    # the last-resort trimmer handle the overrun.
    if len(history) <= keep_n:
        return _trim_history_by_tokens(history, current_tokens, budget, mode), current_text

    # ---- Progressive summarization ----
    # Negative cache: skip the summarizer while it has failed recently to avoid
    # paying a full retry chain (up to 5x retry + per-minute 429 waits) on
    # every message that crosses the threshold.
    if _negative_cache.hit():
        logger.info("Phase-3 summarizer in cooldown after recent failure; using legacy slicer")
        return slice_conversation_to_budget(history, current_text)

    cached_summary = None
    watermark = None
    try:
        cursor.execute("SELECT summary, summary_until FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if row:
            cached_summary, watermark = row["summary"], row["summary_until"]
    except Exception as exc:
        logger.debug("Could not read session summary cache: %s", exc)

    new_texts, new_watermark = _fetch_conversation_between(cursor, session_id, message_in_id, watermark)

    if new_texts:
        try:
            summary = _summarize_block(cached_summary, new_texts, session_id, cursor)
            summary = truncate_tail(summary, max_tokens, mode=mode)
            final_watermark = new_watermark
        except Exception as exc:
            logger.warning("Summarization failed; falling back to legacy slicer: %s", exc)
            return slice_conversation_to_budget(history, current_text)
    else:
        # Cache hit: the cached summary already covers the whole conversation.
        summary = cached_summary or ""
        final_watermark = watermark

    # Persist the (possibly new) running summary.
    if final_watermark is not None:
        try:
            cursor.execute(
                "UPDATE sessions SET summary = ?, summary_until = ? WHERE id = ?",
                (summary, final_watermark, session_id),
            )
            cursor.connection.commit()
        except Exception as exc:
            logger.warning("Could not persist session summary: %s", exc)

    # ---- Build reduced context: summary + verbatim recent ----
    recent = history[-keep_n:]
    summary_marker = "[Summary of earlier conversation (auto-generated): "
    new_history = [
        _content("user", f"{summary_marker}{summary}]")
    ] + recent

    # ---- Last resort: trim to budget with a real token counter ----
    if (
        count_tokens(f"{summary_marker}{summary}]", mode=mode)
        + current_tokens
        + sum(count_tokens(_history_text(m), mode=mode) for m in recent)
        > budget
    ):
        new_history = _trim_history_by_tokens(new_history, current_tokens, budget, mode)

    return new_history, current_text


def _trim_history_by_tokens(history, current_tokens, budget, mode):
    """langchain_core.trim_messages as the last resort.

    We use trim_messages on BaseMessage copies only to compute the cut index;
    the original Gemini Content objects (with their media parts) are then
    the summarizer always prefixes a user-
    authored summary, and the verbatim tail starts with the latest user
    message, so slicing from the front keeps a user message on top. The
    current message has already been truncated to the budget, so it is never
    dropped.
    """
    if not history:
        return []

    from langchain_core.messages import HumanMessage, AIMessage, trim_messages

    base = []
    for c in history:
        role = getattr(c, "role", "user")
        text = _history_text(c)
        base.append(HumanMessage(content=text) if role == "user" else AIMessage(content=text))

    remaining = budget - current_tokens
    if remaining <= 0:
        return []

    def token_counter(msgs):
        return sum(count_tokens(_history_text(m), mode=mode) for m in msgs)

    kept = trim_messages(
        base, max_tokens=remaining, token_counter=token_counter, strategy="last"
    )
    # trim_messages(strategy="last") can drop everything when every message
    # exceeds `remaining` tokens (e.g. budget 60 with a 300-token message).
    if not kept:
        # `last` must be the original Content (with .role), not the BaseMessage copy.
        last = history[-1]
        last_text = _history_text(last)
        last_text = truncate_tail(last_text, remaining, mode=mode)
        kept = [
            HumanMessage(content=last_text) if getattr(last, "role", "user") == "user"
            else AIMessage(content=last_text)
        ]
    cut = len(history) - len(kept)
    reduced = list(history[cut:])
    # Edge case: a single remaining message is still too big -> truncate it.
    if reduced:
        total_after = sum(count_tokens(_history_text(c), mode=mode) for c in reduced) + current_tokens
        if total_after > budget:
            space = budget - current_tokens
            c = reduced[0]
            reduced[0] = _content(c.role, truncate_tail(_history_text(c), space, mode=mode))
    return reduced


# ---------------------------------------------------------------------------
# Content constructor (google-genai >= 2.x) with a safe fallback path.
# ---------------------------------------------------------------------------
try:
    from google.genai import types as _gtypes
except ImportError:
    _gtypes = None


def _content(role, text):
    """A Content(role=role, parts=[Part.from_text]) constructor with a safe
    fallback in case google-genai is not installed."""
    if _gtypes is None:
        raise ImportError("google-genai is required for summarize_then_trim")
    return _gtypes.Content(role=role, parts=[_gtypes.Part.from_text(text=text)])
