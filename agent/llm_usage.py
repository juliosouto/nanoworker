"""Token-usage accounting.

``llm_usage`` (Fase 6) keeps one row per agent turn for the dashboard;
``llm_calls`` keeps one row per model API call with every number the provider
reports (tokens by kind, OpenRouter's cost, upstream provider, latency) for
cost analysis, see :func:`log_llm_call`.

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

import json
import logging
import sqlite3
import threading
import time
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Agent-flow node whose LLM calls are being made (planner / executor /
# evaluator). When set, rows are logged under the stack "graph-<stage>" so
# the dashboard breaks the graph flow's cost down per node.
_usage_stage: ContextVar = ContextVar("llm_usage_stage", default=None)


# Worker answering the current message (set by process_message).
_usage_worker: ContextVar = ContextVar("llm_usage_worker", default=None)
# The route_llm_call in progress: provider, model, session/message ids and the
# API key (for OpenRouter's /generation lookup). A dict filled once the
# model's row is read; each route_llm_call gets its own.
_call_context: ContextVar = ContextVar("llm_call_context", default=None)

_GENERATION_URL = "https://openrouter.ai/api/v1/generation?id={}"
# OpenRouter takes a moment to publish a generation's stats.
_GENERATION_DELAYS = (3, 5, 10)


@contextmanager
def usage_worker(name):
    """Tag every per-call row logged inside the block with the worker's name."""
    token = _usage_worker.set(name)
    try:
        yield
    finally:
        _usage_worker.reset(token)


@contextmanager
def call_context():
    """A fresh context for one route_llm_call (see :func:`set_call_info`).

    A call made inside another one (e.g. fetch_news summarizing articles in
    the middle of a turn) keeps the outer call's prompt, so its cost is
    counted in the user's prompt that caused it."""
    parent = _call_context.get() or {}
    token = _call_context.set({"prompt": parent.get("prompt")})
    try:
        yield
    finally:
        _call_context.reset(token)


def set_call_info(**info) -> None:
    """Fill the current call context (provider, model, session_id...)."""
    ctx = _call_context.get()
    if ctx is None:
        return
    ctx.update(info)
    if ctx.get("prompt") is None and info.get("message_in_id"):
        ctx["prompt"] = (info.get("session_id"), info["message_in_id"])


@contextmanager
def usage_stage(stage: str):
    """Tag every usage row logged inside the block with an agent-flow node."""
    token = _usage_stage.set(stage)
    try:
        yield
    finally:
        _usage_stage.reset(token)


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
    stage = _usage_stage.get()
    if stage:
        stack = f"graph-{stage}"

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


# ---------------------------------------------------------------------------
# Per-call accounting (llm_calls): one row per model API call, with every
# number the provider reports, for cost analysis.
# ---------------------------------------------------------------------------
_CALL_COLUMNS = (
    "session_id", "message_in_id", "worker", "stack", "stage", "provider",
    "model", "response_model", "upstream_provider", "generation_id",
    "input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens",
    "reasoning_tokens", "total_tokens", "cost", "upstream_cost", "is_byok",
    "finish_reason", "tool_calls", "latency_ms", "usage_json",
)


def _get(obj, *path):
    """obj[path0][path1]... for dicts or attributes; None when missing."""
    for key in path:
        if obj is None:
            return None
        obj = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return obj


def _as_dict(obj):
    if obj is None or isinstance(obj, dict):
        return obj
    for method in ("model_dump", "to_json_dict", "dict"):
        fn = getattr(obj, method, None)
        if callable(fn):
            try:
                data = fn()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return None


def _int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def usage_fields(usage) -> dict:
    """Normalized fields from a usage block: OpenAI-compatible ``usage``
    (incl. OpenRouter's cost), LangChain ``usage_metadata`` or Gemini
    ``usage_metadata``. Unknown values are left out."""
    data = _as_dict(usage) or {}
    if not data:
        return {}
    fields = {
        "input_tokens": _int(data.get("prompt_tokens", data.get("input_tokens", data.get("prompt_token_count")))),
        "output_tokens": _int(data.get("completion_tokens", data.get("output_tokens", data.get("candidates_token_count")))),
        "total_tokens": _int(data.get("total_tokens", data.get("total_token_count"))),
        "cached_tokens": _int(
            _get(data, "prompt_tokens_details", "cached_tokens")
            or _get(data, "input_token_details", "cache_read")
            or data.get("cached_content_token_count")
            or data.get("prompt_cache_hit_tokens")  # DeepSeek
        ),
        "cache_write_tokens": _int(
            _get(data, "prompt_tokens_details", "cache_write_tokens")
            or _get(data, "input_token_details", "cache_creation")
        ),
        "reasoning_tokens": _int(
            _get(data, "completion_tokens_details", "reasoning_tokens")
            or _get(data, "output_token_details", "reasoning")
            or data.get("thoughts_token_count")
        ),
        "cost": _float(data.get("cost")),
        "upstream_cost": _float(_get(data, "cost_details", "upstream_inference_cost")),
        "is_byok": None if data.get("is_byok") is None else int(bool(data.get("is_byok"))),
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    try:
        fields["usage_json"] = json.dumps(data, default=str)
    except (TypeError, ValueError):
        pass
    return fields


def log_llm_call(stack: str, **fields) -> int:
    """Insert one llm_calls row; returns its id, or 0 when skipped/failed.

    Context (session, message, provider, model, worker, stage) comes from the
    current route_llm_call and process_message unless passed explicitly.
    Never raises: measurement must not break the chat.
    """
    try:
        ctx = _call_context.get() or {}
        session_id, message_in_id = ctx.get("prompt") or (None, None)
        row = {
            "session_id": session_id,
            "message_in_id": message_in_id,
            "provider": ctx.get("provider"),
            "model": ctx.get("model"),
            "worker": _usage_worker.get(),
            "stage": _usage_stage.get(),
        }
        row.update({k: v for k, v in fields.items() if v is not None})
        row["stack"] = stack
        if not any(row.get(k) is not None for k in ("input_tokens", "output_tokens", "cost")):
            return 0
        columns = [c for c in _CALL_COLUMNS if row.get(c) is not None]

        from database import get_db

        conn = get_db()
        try:
            cur = conn.execute(
                f"INSERT INTO llm_calls ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [row[c] for c in columns],
            )
            conn.commit()
            row_id = cur.lastrowid
        finally:
            conn.close()
    except Exception as e:
        logger.warning("llm_calls insert skipped (%s)", e)
        return 0

    if (row.get("provider") == "openrouter" and row.get("generation_id")
            and ctx.get("api_key")
            and (row.get("cost") is None or row.get("upstream_provider") is None)):
        _schedule_generation_lookup(row_id, row["generation_id"], ctx["api_key"])
    return row_id


def log_openai_response(response, latency_ms=None, stack="legacy") -> int:
    """Logs an OpenAI-SDK ChatCompletion (OpenRouter, Groq, Qwen, NVIDIA...)."""
    try:
        choice = (_get(response, "choices") or [None])[0]
        return log_llm_call(
            stack,
            response_model=_get(response, "model"),
            upstream_provider=_get(response, "provider"),  # OpenRouter
            generation_id=_get(response, "id"),
            finish_reason=_get(choice, "finish_reason"),
            tool_calls=len(_get(choice, "message", "tool_calls") or []),
            latency_ms=latency_ms,
            **usage_fields(_get(response, "usage")),
        )
    except Exception as e:
        logger.warning("llm_calls: could not read the response (%s)", e)
        return 0


def log_gemini_response(response, latency_ms=None, stack="legacy") -> int:
    """Logs a google-genai GenerateContentResponse."""
    try:
        candidate = (_get(response, "candidates") or [None])[0]
        finish = _get(candidate, "finish_reason")
        return log_llm_call(
            stack,
            response_model=_get(response, "model_version"),
            generation_id=_get(response, "response_id"),
            finish_reason=getattr(finish, "name", finish),
            tool_calls=len(_get(response, "function_calls") or []),
            latency_ms=latency_ms,
            **usage_fields(_get(response, "usage_metadata")),
        )
    except Exception as e:
        logger.warning("llm_calls: could not read the response (%s)", e)
        return 0


def log_langchain_result(result, latency_ms=None, stack="langchain") -> int:
    """Logs a LangChain LLMResult (from a callback's on_llm_end).

    ``llm_output.token_usage`` is the provider's raw usage (OpenRouter's cost
    included); streamed calls only carry the message's usage_metadata."""
    try:
        llm_output = _get(result, "llm_output") or {}
        generation = ((_get(result, "generations") or [[None]])[0] or [None])[0]
        message = _get(generation, "message")
        metadata = _get(message, "response_metadata") or {}
        fields = usage_fields(_get(message, "usage_metadata"))
        raw = llm_output.get("token_usage") or metadata.get("token_usage")
        if raw:
            fields.update(usage_fields(raw))
        finish = (_get(generation, "generation_info", "finish_reason")
                  or metadata.get("finish_reason") or metadata.get("stop_reason"))
        return log_llm_call(
            stack,
            response_model=llm_output.get("model_name") or metadata.get("model_name"),
            generation_id=llm_output.get("id") or metadata.get("id"),
            finish_reason=getattr(finish, "name", finish),
            tool_calls=len(_get(message, "tool_calls") or []),
            latency_ms=latency_ms,
            **fields,
        )
    except Exception as e:
        logger.warning("llm_calls: could not read the LangChain result (%s)", e)
        return 0


def _schedule_generation_lookup(row_id, generation_id, api_key) -> None:
    threading.Thread(
        target=fill_from_generation, args=(row_id, generation_id, api_key),
        name="openrouter-generation", daemon=True,
    ).start()


def fill_from_generation(row_id, generation_id, api_key, delays=_GENERATION_DELAYS) -> bool:
    """Completes a row with OpenRouter's /generation stats (cost and the
    upstream provider that served it, which LangChain drops)."""
    from database import get_db

    for delay in delays:
        time.sleep(delay)
        try:
            req = urllib.request.Request(
                _GENERATION_URL.format(generation_id),
                headers={"Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.load(response).get("data") or {}
        except Exception as e:
            logger.debug("OpenRouter generation %s not available yet: %s", generation_id, e)
            continue
        if not data:
            continue
        try:
            conn = get_db()
            try:
                conn.execute(
                    """
                    UPDATE llm_calls SET
                        cost = COALESCE(cost, ?),
                        upstream_provider = COALESCE(upstream_provider, ?),
                        upstream_cost = COALESCE(upstream_cost, ?),
                        is_byok = COALESCE(is_byok, ?),
                        generation_json = ?
                    WHERE id = ?
                    """,
                    (
                        _float(data.get("total_cost")),
                        data.get("provider_name"),
                        _float(data.get("upstream_inference_cost")),
                        None if data.get("is_byok") is None else int(bool(data.get("is_byok"))),
                        json.dumps(data, default=str),
                        row_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            return True
        except Exception as e:
            logger.warning("llm_calls: could not store generation %s (%s)", generation_id, e)
            return False
    return False


# ---------------------------------------------------------------------------
# Costs page (/costs): llm_calls grouped by the user's prompt.
# ---------------------------------------------------------------------------
_PROMPT_GROUP_SQL = """
    SELECT c.message_in_id,
           MAX(c.session_id) AS session_id,
           MIN(c.created_at) AS started_at,
           MAX(c.worker) AS worker,
           GROUP_CONCAT(DISTINCT c.model) AS models,
           COUNT(*) AS calls,
           SUM(c.cost IS NULL) AS calls_without_cost,
           SUM(c.cost) AS cost,
           COALESCE(SUM(c.input_tokens), 0) AS input_tokens,
           COALESCE(SUM(c.output_tokens), 0) AS output_tokens,
           COALESCE(SUM(c.reasoning_tokens), 0) AS reasoning_tokens,
           COALESCE(SUM(c.cached_tokens), 0) AS cached_tokens,
           COALESCE(SUM(c.tool_calls), 0) AS tool_calls,
           SUM(c.latency_ms) AS latency_ms
    FROM llm_calls c
    WHERE c.created_at >= datetime('now', '-' || ? || ' days')
      AND c.message_in_id IS NOT NULL
    GROUP BY c.message_in_id
"""


def get_prompt_costs(days=7, page=1, per_page=50, query=None) -> dict:
    """Prompts of the last ``days`` days, newest first, with the summed cost
    and tokens of every model call each one caused, plus period totals."""
    from database import get_db

    window = _days_since(days)
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 50)))
    like = f"%{query.strip()}%" if query and query.strip() else None
    base = f"""
        WITH p AS ({_PROMPT_GROUP_SQL})
        SELECT p.*,
               COALESCE(mi.content, imi.content) AS prompt,
               s.channel_id AS channel_id
        FROM p
        LEFT JOIN messages_in mi ON mi.id = p.message_in_id
        LEFT JOIN ide_messages_in imi ON imi.id = p.message_in_id
        LEFT JOIN sessions s ON s.id = p.session_id
        WHERE (? IS NULL OR COALESCE(mi.content, imi.content, '') LIKE ?
               OR p.worker LIKE ? OR p.models LIKE ?)
    """
    params = (window, like, like, like, like)
    try:
        conn = get_db()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM ({base})", params).fetchone()[0]
            rows = conn.execute(
                f"{base} ORDER BY p.started_at DESC LIMIT ? OFFSET ?",
                params + (per_page, (page - 1) * per_page),
            ).fetchall()
            totals = conn.execute(
                """
                SELECT COUNT(*) AS calls,
                       COUNT(DISTINCT message_in_id) AS prompts,
                       SUM(cost) AS cost,
                       SUM(cost IS NULL) AS calls_without_cost,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens
                FROM llm_calls
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                """,
                (window,),
            ).fetchone()
            by_model = conn.execute(
                """
                SELECT COALESCE(model, '(unknown)') AS model,
                       COUNT(*) AS calls,
                       SUM(cost) AS cost,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens
                FROM llm_calls
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY COALESCE(model, '(unknown)')
                ORDER BY COALESCE(SUM(cost), 0) DESC, calls DESC
                """,
                (window,),
            ).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("llm_calls costs unavailable (%s)", e)
        return {"days": window, "page": page, "per_page": per_page, "total": 0,
                "prompts": [], "totals": {}, "by_model": []}
    return {
        "days": window,
        "page": page,
        "per_page": per_page,
        "total": total,
        "prompts": [dict(r) for r in rows],
        "totals": dict(totals) if totals else {},
        "by_model": [dict(r) for r in by_model],
    }


def get_prompt_calls(message_in_id) -> list:
    """Every model call of one prompt, in order."""
    from database import get_db

    try:
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT id, created_at, worker, stack, stage, provider, model,
                       response_model, upstream_provider, generation_id,
                       input_tokens, output_tokens, cached_tokens,
                       cache_write_tokens, reasoning_tokens, total_tokens,
                       cost, upstream_cost, is_byok, finish_reason, tool_calls,
                       latency_ms
                FROM llm_calls WHERE message_in_id = ? ORDER BY id
                """,
                (message_in_id,),
            ).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("llm_calls unavailable (%s)", e)
        return []
    return [dict(r) for r in rows]
