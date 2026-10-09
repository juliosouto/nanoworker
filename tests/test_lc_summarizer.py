"""Tests for the phase-3 progressive conversation summarizer (agent.lc.summarizer).

Covers:
- settings readers (defaults, env override, invalid fall-back)
- DB migration (summary / summary_until columns, idempotent, /new invalidation)
- summarize_then_trim: cheap path, feature switch, progressive summarization
  with watermark cache-hit, incremental block summarization, hard cap,
  LLM-failure fall-back to the legacy slicer, and the langchain_core last-resort trim.
"""

import pytest

from agent.lc import settings
from agent.lc.summarizer import (
    summarize_then_trim,
    _fetch_conversation_between,
)
from agent.lc.tokens import count_tokens
import database


# ---------------------------------------------------------------------------
# Fixtures / helpers: a fresh per-test summarizer database (uses tmp_path)
# ---------------------------------------------------------------------------
@pytest.fixture
def sum_db(mock_db_path):
    """Fresh summarizer DB per test: the full migration runs so sessions and
    message tables exist. The temporary mock database means no real DB is
    touched."""
    import database

    database.init_db()  # CREATE TABLE IF NOT EXISTS -> idempotent
    yield


def _insert_session(conn, session_id="sess-1", agent_id="agent-1", channel_id="wa:55"):
    conn.execute(
        "INSERT INTO sessions (id, agent_id, channel_id) VALUES (?,?,?)",
        (session_id, agent_id, channel_id),
    )
    conn.commit()


def _insert_messages(conn, session_id, messages, ids=None):
    """Insert messages_in rows and return [(id, created_at), ...]."""
    out = []
    for i, text in enumerate(messages):
        mid = ids[i] if ids else f"m{i+1}"
        # ISO timestamps padded so lexical ordering == insertion order.
        day = str(i + 2).zfill(2)
        created = f"2026-01-{day} 00:00:00"
        conn.execute(
            "INSERT INTO messages_in (id, session_id, content, sender_id, processed, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (mid, session_id, text, "sender-1", 1, created),
        )
        out.append((mid, created))
    conn.commit()
    return out


def _load_history(cursor, session_id, exclude_message_id=None):
    """Rebuild the Gemini-format history exactly as agent.message_processor
    does (types.Content with role user/model)."""
    from google.genai import types

    cursor.execute(
        """
        SELECT 'user' as role, content, created_at
        FROM messages_in WHERE session_id = ? AND id != ?
        UNION ALL
        SELECT 'model' as role, content, created_at
        FROM messages_out WHERE session_id = ?
        ORDER BY created_at ASC
        """,
        (session_id, exclude_message_id, session_id),
    )
    rows = cursor.fetchall()
    history = []
    for row in rows:
        # One Content per database row; tests always use text-only parts.
        # Do not merge consecutive rows — that would collapse the message
        # boundary and break count assertions.
        history.append(types.Content(role=row["role"], parts=[types.Part.from_text(text=row["content"])]))
    return history


@pytest.fixture
def route_spy(mocker):
    """Spy on the summarizer backend so we can assert what it was called with
    without ever reaching a real LLM."""
    calls = []

    def spy(model_name, history, config_kwargs, content, cursor, session_id,
            message_in_id, is_ide, on_complete=None, summarize=False):
        calls.append(dict(model_name=model_name, content=content, summarize=summarize))
        return "MOCKED_SUMMARY"

    m = mocker.patch("agent.lc.summarizer.route_llm_call", side_effect=spy)
    m.calls = calls
    yield m


# ---------------------------------------------------------------------------
# Phase-3 settings readers
# ---------------------------------------------------------------------------
class TestSettingsReaders:
    def test_summarizer_model_default_is_disabled(self, monkeypatch):
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        assert settings.summarizer_model() == ""

    def test_summarizer_model_env_override(self, monkeypatch):
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        assert settings.summarizer_model() == "qwen-2.5-7b-instruct"

    def test_summary_threshold_and_max_tokens_defaults(self, monkeypatch):
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        assert settings.summary_threshold_pct() == 80
        assert settings.summary_max_tokens() == 200

    def test_invalid_values_fall_back_to_defaults(self, monkeypatch):
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        monkeypatch.setenv("LC_SUMMARY_THRESHOLD_PCT", "garbage")
        monkeypatch.setenv("LC_SUMMARY_MAX_TOKENS", "not-a-number")
        assert settings.summary_threshold_pct() == 80
        assert settings.summary_max_tokens() == 200


# ---------------------------------------------------------------------------
# Database migration (sessions.summary / sessions.summary_until)
# ---------------------------------------------------------------------------
class TestMigration:
    def test_summary_columns_created(self, sum_db):
        import database

        cursor = database.get_db().cursor()
        cols = {r[1] for r in cursor.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "summary" in cols and "summary_until" in cols

    def test_migration_runs_idempotently(self, sum_db):
        import database

        database.init_db()
        database.init_db()  # second run must not raise

    def test_new_clears_summary_cache(self, sum_db, mocker):
        import database
        import router

        spy = mocker.patch("database.clear_session_summary", side_effect=database.clear_session_summary)
        conn = database.get_db()
        cursor = conn.cursor()
        _insert_session(conn)
        _insert_messages(conn, "sess-1", ["word " * 200 for _ in range(4)])
        cursor.execute(
            "UPDATE sessions SET summary = ?, summary_until = ? WHERE id = ?",
            ("OLD-RESUME", "2026-01-04 00:00:00", "sess-1"),
        )
        conn.commit()
        _, session_id, _ = router.route_inbound_message(
            channel_id="wa:55", content="/new", sender_id="999"
        )
        spy.assert_called_once_with(session_id)
        row = cursor.execute("SELECT summary, summary_until FROM sessions WHERE id = ?",
                             (session_id,)).fetchone()
        assert row[0] is None and row[1] is None


# ---------------------------------------------------------------------------
# Summarize-then-trim core behavior
# ---------------------------------------------------------------------------
class TestSummarizeThenTrim:
    def test_cheap_path_below_threshold(self, sum_db, monkeypatch, route_spy):
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: {"MESSAGE_SLICE_SIZE_TOKENS": "20000"}.get(k, None))
        conn = database.get_db()
        _insert_session(conn)
        small = ["word " * 10 for _ in range(6)]  # ~60 tokens total
        _insert_messages(conn, "sess-1", small, ids=["m1", "m2", "m3", "m4", "m5", "m6"])
        cursor = conn.cursor()
        history, current = summarize_then_trim(
            _load_history(cursor, "sess-1", "m6"), "word " * 10, "sess-1", cursor, "m6"
        )
        assert len(route_spy.calls) == 0
        assert len(history) == 5  # 6 inserted minus the current message
        assert all(h.role == "user" for h in history)

    def test_degrades_to_legacy_when_model_off(self, sum_db, monkeypatch, route_spy):
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "")  # explicitly disabled
        monkeypatch.setattr("database.get_config", lambda k, d=None: {"MESSAGE_SLICE_SIZE_TOKENS": "20000"}.get(k, None))
        conn = database.get_db()
        _insert_session(conn)
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        history, current = summarize_then_trim(
            _load_history(cursor, "sess-1", "m11"), "word " * 20, "sess-1", cursor, "m11"
        )
        assert len(route_spy.calls) == 0
        row = cursor.execute("SELECT summary FROM sessions WHERE id = ?", ("sess-1",)).fetchone()
        assert row[0] is None  # no summary written on degradation
        assert len(history) == 10  # 11 inserted minus the current message, kept whole at high budget

    def test_summarizes_new_block_and_persists(self, sum_db, monkeypatch, route_spy):
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        conn = database.get_db()
        _insert_session(conn)
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        history, current = summarize_then_trim(
            _load_history(cursor, "sess-1", "m11"), "word " * 20, "sess-1", cursor, "m11"
        )
        assert len(route_spy.calls) == 1
        row = cursor.execute("SELECT summary, summary_until FROM sessions WHERE id = ?",
                             ("sess-1",)).fetchone()
        assert row[0] == "MOCKED_SUMMARY"
        # watermark = created_at of m10: the newest message is the *current*
        # one being processed and is deliberately excluded from the summary.
        assert row[1] == "2026-01-11 00:00:00"
        # The last-resort trimmer produced a context that fits the budget.
        total = sum(count_tokens(h.parts[0].text) for h in history) + count_tokens(current)
        assert total <= 2000
        assert all(h.role == "user" for h in history)

    def test_reuses_cached_summary_when_no_new_messages(self, sum_db, monkeypatch, route_spy):
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        conn = database.get_db()
        _insert_session(conn)
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        # First call folds all 11 messages into the summary.
        summarize_then_trim(_load_history(cursor, "sess-1", "m11"), "word " * 20, "sess-1", cursor, "m11")
        calls_after_first = len(route_spy.calls)
        # Second call: same conversation -> the cached summary is used EXCEPT the
        # message written in the same second as the watermark is re-folded
        # (idempotent) because the watermark query is inclusive (>=).
        summarize_then_trim(_load_history(cursor, "sess-1", "m11"), "word " * 20, "sess-1", cursor, "m11")
        assert len(route_spy.calls) == calls_after_first + 1

    def test_progressive_summarization_folds_next_block(self, sum_db, monkeypatch, route_spy):
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        conn = database.get_db()
        _insert_session(conn)
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        # First call folds m1..m11 into the summary.
        summarize_then_trim(_load_history(cursor, "sess-1", "m11"), "word " * 20, "sess-1", cursor, "m11")
        calls_after_first = len(route_spy.calls)
        # Second incoming message: m12 (created_at after the watermark).
        conn.execute(
            "INSERT INTO messages_in (id, session_id, content, sender_id, processed, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("m12", "sess-1", "word " * 300, "sender-1", 1, "2026-01-13 00:00:00"),
        )
        conn.commit()
        summarize_then_trim(_load_history(cursor, "sess-1", "m12"), "word " * 20, "sess-1", cursor, "m12")
        # Summarizer called again with the previous summary + the new block.
        assert len(route_spy.calls) == calls_after_first + 1
        latest = route_spy.calls[-1]
        assert "MOCKED_SUMMARY" in latest["content"]

    def test_llm_failure_degrades_to_legacy_slicer(self, sum_db, monkeypatch, mocker):
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: {"MESSAGE_SLICE_SIZE_TOKENS": "20000"}.get(k, None))
        conn = database.get_db()
        _insert_session(conn)
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        mocker.patch("agent.lc.summarizer.route_llm_call", side_effect=ValueError("no llm"))
        history, current = summarize_then_trim(
            _load_history(cursor, "sess-1", "m11"), "word " * 20, "sess-1", cursor, "m11"
        )
        row = cursor.execute("SELECT summary FROM sessions WHERE id = ?", ("sess-1",)).fetchone()
        assert row[0] is None  # legacy path never writes the cache
        assert len(history) == 10  # 11 inserted minus the current message

    def test_summary_is_hard_capped_at_max_tokens(self, sum_db, monkeypatch, route_spy):
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        conn = database.get_db()
        _insert_session(conn)
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        route_spy.return_value = "word " * 6000  # ~6000 tokens -> should be capped at 200
        summarize_then_trim(_load_history(cursor, "sess-1", "m11"), "word " * 20, "sess-1", cursor, "m11")
        row = cursor.execute("SELECT summary FROM sessions WHERE id = ?", ("sess-1",)).fetchone()
        assert count_tokens(row[0]) <= 200

    def test_last_resort_trim_uses_real_token_counter(self, sum_db, monkeypatch, route_spy):
        """Budget so tight that even the summary + recent messages overshoot:
        langchain_core.trim_messages must compute the cut with the real counter,
        keeping the most recent messages and never dropping the current one."""
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: None)
        conn = database.get_db()
        _insert_session(conn)
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        monkeypatch.setattr("database.get_config", lambda k, d=None: {"MESSAGE_SLICE_SIZE_TOKENS": "60"}.get(k, d))
        history, current = summarize_then_trim(
            _load_history(cursor, "sess-1", "m11"), "word " * 10, "sess-1", cursor, "m11"
        )
        assert len(history) < 11  # some history was trimmed
        assert history[0].role == "user"  # no orphan model message at the top
        total = sum(count_tokens(h.parts[0].text) for h in history) + count_tokens(current)
        assert total <= 60


# ---------------------------------------------------------------------------
# Watermark helper
# ---------------------------------------------------------------------------
class TestFetchConversationBetween:
    def test_returns_messages_between_watermark(self, sum_db):
        """Watermark is inclusive (``>=``) so a message written in the same
        second as the last folded one is re-folded (idempotent)."""
        import database

        conn = database.get_db()
        _insert_session(conn)
        _insert_messages(conn, "sess-1", ["a", "b", "c", "d", "e"], ids=["m1", "m2", "m3", "m4", "m5"])
        cursor = conn.cursor()
        texts, w = _fetch_conversation_between(cursor, "sess-1", "current", "2026-01-02 00:00:00")
        # watermark == created_at of m1; with >= the boundary message 'a' is re-folded
        assert texts == ["a", "b", "c", "d", "e"]
        assert w == "2026-01-06 00:00:00"

    def test_same_second_watermark_includes_boundary(self, sum_db):
        """Same-second messages are fetched even when they tie the last-folded
        watermark; created_at has second precision."""
        import database

        conn = database.get_db()
        _insert_session(conn)
        conn.execute(
            "INSERT INTO messages_in (id, session_id, content, created_at) VALUES (?,?,?,?)",
            ("m2", "sess-1", "same-second msg", "2026-01-02 12:00:00"),
        )
        conn.commit()
        cursor = conn.cursor()
        texts, w = _fetch_conversation_between(cursor, "sess-1", "m1", "2026-01-02 12:00:00")
        assert "same-second msg" in texts

    def test_empty_when_watermark_is_current(self, sum_db):
        import database

        conn = database.get_db()
        _insert_session(conn)
        _insert_messages(conn, "sess-1", ["a", "b", "c"], ids=["m1", "m2", "m3"])
        cursor = conn.cursor()
        texts, w = _fetch_conversation_between(cursor, "sess-1", "m3", "2026-01-04 00:00:00")
        assert texts == [] and w is None

    def test_fetch_ordering_guaranteed(self, sum_db):
        """Rows are returned in created_at ASC order (with a tie-break key) so
        that rows[-1] is deterministically the newest; timestamps use
        second-precision to mirror the real created_at schema."""
        import database

        conn = database.get_db()
        _insert_session(conn)
        ts = "2026-01-05 00:00:"
        conn.execute(
            "INSERT INTO messages_in (id, session_id, content, created_at) VALUES (?,?,?,?)",
            ("m1", "sess-1", "alpha", ts + "01"),
        )
        conn.execute(
            "INSERT INTO messages_out (id, session_id, content, in_reply_to, created_at) VALUES (?,?,?,?,?)",
            ("o1", "sess-1", "model alpha", "m1", ts + "02"),
        )
        conn.execute(
            "INSERT INTO messages_in (id, session_id, content, created_at) VALUES (?,?,?,?)",
            ("m2", "sess-1", "gamma", ts + "03"),
        )
        # m3 is the CURRENT message -> excluded, must NOT appear in the result.
        conn.execute(
            "INSERT INTO messages_in (id, session_id, content, created_at) VALUES (?,?,?,?)",
            ("m3", "sess-1", "beta", ts + "04"),
        )
        conn.commit()
        cursor = conn.cursor()
        texts, w = _fetch_conversation_between(cursor, "sess-1", "m3", None)
        # chronological order with rowid tie-break; newest row = watermark
        assert texts == ["alpha", "model alpha", "gamma"], texts
        assert w == "2026-01-05 00:00:03"

# ---------------------------------------------------------------------------
# DC regression tests (double-check round: Phase-3 bug fixes)
# ---------------------------------------------------------------------------
class TestDCCorrections:
    def test_empty_history_above_threshold_no_crash(self, sum_db, monkeypatch, mocker):
        """Empty history (e.g. first message after /new) that alone exceeds the
        summarizer threshold must not crash: ``_trim_history_by_tokens`` guards
        the empty-history index case."""
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        monkeypatch.setattr("database.get_config", lambda k, d=None: {
            "MESSAGE_SLICE_SIZE_TOKENS": "2000",
            "LC_SUMMARY_THRESHOLD_PCT": "80",
            "LC_SUMMARY_MAX_TOKENS": "200",
        }.get(k, None))
        conn = database.get_db()
        _insert_session(conn)
        big = "word " * 1700  # ~1700 tokens > 80% of the 2000-token budget
        history, current = summarize_then_trim([], big, "sess-1", conn.cursor(), "m-any")
        # degrades to the legacy slicer and never drops the current message
        assert len(history) == 0
        assert current.split() == ["word"] * 1700

    def test_feedback_rows_purged_after_summarize_call(self, sum_db, monkeypatch, mocker):
        """Retries of the summarizer backend write feedback rows into
        ``ide_messages_out`` with ``in_reply_to='summarize-0'``; they are
        purged (best-effort) after the call so they never pollute the IDE
        conversation history, which reads every session row."""
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        conn = database.get_db()
        _insert_session(conn)
        # 10 messages of ~220 tokens each = 2210 tokens > 80% of the 2000-token
        # default budget (LC_SUMMARIZER_MODEL set, default MESSAGE_SLICE_SIZE),
        # so the summarization path (and its finally-cleanup) is exercised.
        _insert_messages(conn, "sess-1", ["x " * 220] * 10, ids=[f"in-{i}" for i in range(10)])
        conn.execute(
            "INSERT INTO ide_messages_out (id, session_id, content, in_reply_to, created_at) VALUES (?,?,?,?,?)",
            ("fb-1", "sess-1", "⚠️ 503 Error on attempt 1/5. Retrying...", "summarize-0", "2026-01-05 12:00:00"),
        )
        conn.commit()
        cursor = conn.cursor()
        mocker.patch("agent.lc.summarizer.route_llm_call", return_value="MOCKED_SUMMARY")
        summarize_then_trim(_load_history(cursor, "sess-1", "in-09"), "x", "sess-1", cursor, "in-09")
        remaining = cursor.execute("SELECT id FROM ide_messages_out WHERE in_reply_to = ?", ("summarize-0",)).fetchall()
        assert remaining == []

    def test_negative_cache_after_llm_failure(self, sum_db, monkeypatch, mocker):
        """A failing summarizer model enters a 300 s cooldown window: after the
        first failure the LLM must not be retried on the next message, avoiding
        a full retry chain (including per-minute 429 waits) on every message."""
        monkeypatch.setenv("LC_SUMMARIZER_MODEL", "qwen-2.5-7b-instruct")
        conn = database.get_db()
        _insert_session(conn)
        # 11 messages of ~300 tokens each = 3300 tokens > 80% of the 2000-token
        # default budget -> the summarize path runs and the failing model must
        # enter the negative cache.
        old = ["word " * 300 for _ in range(10)]
        recent = ["word " * 300]
        _insert_messages(conn, "sess-1", old + recent, ids=[f"m{i+1}" for i in range(11)])
        cursor = conn.cursor()
        spy = mocker.patch("agent.lc.summarizer.route_llm_call", side_effect=ValueError("no llm"))
        history, current = summarize_then_trim(_load_history(cursor, "sess-1", "m11"), "x", "sess-1", cursor, "m11")
        first_calls = spy.call_count
        assert first_calls >= 1
        history2, current2 = summarize_then_trim(_load_history(cursor, "sess-1", "m11"), "x", "sess-1", cursor, "m11")
        assert spy.call_count == first_calls, "second call must skip the LLM inside cooldown"
        # degraded to the legacy slicer, not a crash
        assert history2 is not None
