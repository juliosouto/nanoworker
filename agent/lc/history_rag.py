"""History RAG: vectorizes the message_history timeline into sqlite-vec and
retrieves relevant past messages to attach to the user's prompt before the
LLM call (the worker only triggers this when it is mentioned).

Design notes:
- ``database.py`` stays pure SQL; embeddings orchestration lives here,
  mirroring ``agent.lc.memory_rag``.
- The vec0 table is partitioned by ``channel_id`` so KNN never crosses chats.
- Embeddings provider: the same one used by the user-memory RAG
  (``agent.lc.embeddings`` — Gemini text-embedding-004 / OpenAI 3-small).
- Every failure is fail-open: vectorization/retrieval problems NEVER block
  message processing; the reply is simply produced without the extra context.
"""
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SEARCH_TYPES = ("similarity", "mmr", "similarity_score_threshold")

CONTEXT_HEADER = "[Contexto relevante recuperado do histórico do canal]"
CONTEXT_FOOTER = "[/Contexto relevante]"


@dataclass
class HistoryRagSettings:
    enabled: bool
    search_type: str
    k: int
    fetch_k: int
    score_threshold: float
    lambda_mult: float


def get_settings() -> HistoryRagSettings:
    """Reads the retriever parameters from app_config (Agent Behavior page).

    Uses ``get_all_configs`` (single connection) instead of one ``get_config``
    call per key: this runs on every vectorized message and on every mentioned
    message being processed.
    """
    from database import get_all_configs

    try:
        cfg = get_all_configs()
    except Exception:
        cfg = {}

    def _get(key, default):
        value = cfg.get(key)
        return value if value not in (None, "") else default

    def _int(key, default, lo, hi):
        try:
            v = int(float(_get(key, str(default))))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def _float(key, default, lo, hi):
        try:
            v = float(_get(key, str(default)))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    search_type = str(_get("HISTORY_RAG_SEARCH_TYPE", "mmr")).strip()
    if search_type not in SEARCH_TYPES:
        search_type = "mmr"
    k = _int("HISTORY_RAG_K", 3, 1, 50)
    fetch_k = max(k, _int("HISTORY_RAG_FETCH_K", 20, 1, 200))
    return HistoryRagSettings(
        enabled=str(_get("HISTORY_RAG_ENABLED", "true")).lower() == "true",
        search_type=search_type,
        k=k,
        fetch_k=fetch_k,
        score_threshold=_float("HISTORY_RAG_SCORE_THRESHOLD", 0.3, 0.0, 1.0),
        lambda_mult=_float("HISTORY_RAG_LAMBDA", 0.5, 0.0, 1.0),
    )


def _payload_from_row(row) -> dict:
    """Denormalized JSON snapshot stored alongside the vector (no JOIN at
    retrieval time)."""
    hour = row["msg_hour"] if row["msg_hour"] is not None else 0
    minute = row["msg_minute"] if row["msg_minute"] is not None else 0
    second = row["msg_second"] if row["msg_second"] is not None else 0
    return {
        "content": row["content"],
        "channel_id": row["channel_id"],
        "sender_name": row["sender_name"],
        "sender_id": row["sender_id"],
        "is_bot": bool(row["is_bot"]),
        "msg_date": row["msg_date"],
        "msg_time": f"{int(hour):02d}:{int(minute):02d}:{int(second):02d}",
        "msg_ts": row["msg_timestamp"],
    }


def vectorize_message(row_id) -> bool:
    """
    Embeds one ``message_history`` row and stores its vector (with the payload
    snapshot) in ``message_history_vec``.

    Gated by HISTORY_RAG_ENABLED: with the retriever disabled no embedding API
    calls are made; the boot backfill vectorizes the missing rows once it is
    re-enabled. Fail-open: any error is logged and the message simply stays
    without a vector.
    """
    if row_id is None:
        return False
    try:
        if not get_settings().enabled:
            return False

        import agent.lc.embeddings as embeddings

        if not embeddings.embeddings_available():
            return False

        from database import get_db

        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, channel_id, content, sender_id, sender_name, is_bot,
                       msg_timestamp, msg_date, msg_hour, msg_minute, msg_second
                FROM message_history
                WHERE id = ?
            ''', (row_id,))
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None or not (row["content"] or "").strip():
            return False

        payload = _payload_from_row(row)
        vectors = embeddings.get_embeddings().embed_documents([payload["content"]])
        if not vectors:
            return False

        from database import insert_message_vector
        return insert_message_vector(row_id, row["channel_id"], payload, vectors[0])
    except Exception as exc:
        logger.warning(
            "History vectorization failed for row %s (%s); the backfill will retry",
            row_id, exc,
        )
        return False


def backfill_missing_vectors(limit: int = 200) -> int:
    """Vectorizes history rows that have no vector yet (most recent first).
    Bounded by ``limit`` per call to control embedding API cost."""
    done = 0
    from database import get_missing_vector_ids

    for row_id in get_missing_vector_ids(limit):
        if vectorize_message(row_id):
            done += 1
    return done


def retrieve_relevant_history(query, channel_id, exclude_id=None, cutoff_ts=None,
                              settings: HistoryRagSettings | None = None) -> list:
    """
    Retrieves the most relevant past messages of ``channel_id`` for ``query``.

    Args:
        query: user's (mention-cleaned) message used as the search query.
        channel_id: restricts the search to the current chat (partition key).
        exclude_id: message_history.id of the message being processed now.
        cutoff_ts: skip messages already inside the verbatim N-message window
            (payload msg_ts >= cutoff_ts), so the prompt never duplicates the
            recent context.
        settings: HistoryRagSettings (read from app_config when omitted).

    Returns:
        list of {"id": int, "score": float, "payload": dict}, best first.
    """
    settings = settings or get_settings()
    if not settings.enabled or not channel_id or not (query or "").strip():
        return []

    from database import get_db

    # Cheap early exit: a partition with no vectors cannot return anything, so
    # skip paying for the query embedding. (A partition-key COUNT is a plain
    # vec0 partition query.) If the check itself fails, fall through and let
    # the KNN attempt handle it.
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM message_history_vec WHERE channel_id = ?',
            (channel_id,),
        )
        if cursor.fetchone()[0] == 0:
            return []
    except Exception as exc:
        logger.debug("History RAG partition check failed (%s); continuing", exc)
    finally:
        conn.close()

    try:
        import agent.lc.embeddings as embeddings

        if not embeddings.embeddings_available():
            return []
        query_vector = embeddings.get_embeddings().embed_query(query)
    except Exception as exc:
        logger.warning("History RAG: query embedding failed (%s); no context attached", exc)
        return []

    conn = get_db()
    try:
        sql = '''
            SELECT id, distance, payload, vector
            FROM message_history_vec
            WHERE channel_id = ? AND vector MATCH ? AND k = ?
        '''
        params = [channel_id, json.dumps(query_vector), settings.fetch_k]
        if exclude_id is not None:
            sql += ' AND id != ?'
            params.append(exclude_id)
        sql += ' ORDER BY distance'
        rows = conn.execute(sql, params).fetchall()
    except Exception as exc:
        logger.warning("History RAG query failed (%s); no context attached", exc)
        return []
    finally:
        conn.close()

    candidates = []
    for row in rows:
        try:
            payload = json.loads(row["payload"]) if row["payload"] else {}
        except (TypeError, ValueError):
            payload = {}
        if cutoff_ts is not None and (payload.get("msg_ts") or 0) >= cutoff_ts:
            continue  # already verbatim in the recent-window context
        candidates.append({
            "id": row["id"],
            "distance": row["distance"],
            "payload": payload,
            "vector": row["vector"],
        })

    if settings.search_type == "similarity_score_threshold":
        picked = [
            c for c in candidates
            if (1.0 - float(c["distance"])) >= settings.score_threshold
        ][:settings.k]
    elif settings.search_type == "mmr":
        picked = _mmr_select(query_vector, candidates, settings)
    else:  # similarity
        picked = candidates[:settings.k]

    return [
        {"id": c["id"], "score": round(1.0 - float(c["distance"]), 4), "payload": c["payload"]}
        for c in picked
    ]


def _mmr_select(query_vector, candidates, settings) -> list:
    """Maximal Marginal Relevance over the fetched candidates.

    score = lambda * sim(query, doc) - (1 - lambda) * max sim(doc, selected)
    Candidate vectors come back from vec0 as float32 little-endian blobs.
    """
    if not candidates:
        return []
    try:
        import numpy as np

        vecs = np.array(
            [np.frombuffer(bytes(c["vector"]), dtype="<f4") for c in candidates],
            dtype="f4",
        )
        qv = np.array(query_vector, dtype="f4")
        if vecs.ndim != 2 or qv.ndim != 1 or vecs.shape[1] != qv.shape[0]:
            raise ValueError("vector dimension mismatch")

        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        qnorm = float(np.linalg.norm(qv))
        if qnorm:
            qv = qv / qnorm

        selected, remaining = [], list(range(len(candidates)))
        while remaining and len(selected) < settings.k:
            best_idx, best_score = None, float("-inf")
            for idx in remaining:
                redundancy = max(
                    (float(vecs[idx] @ vecs[sel]) for sel in selected),
                    default=0.0,
                )
                score = (
                    settings.lambda_mult * (1.0 - float(candidates[idx]["distance"]))
                    - (1.0 - settings.lambda_mult) * redundancy
                )
                if score > best_score:
                    best_idx, best_score = idx, score
            selected.append(best_idx)
            remaining.remove(best_idx)
        return [candidates[i] for i in selected]
    except Exception as exc:
        logger.warning("History RAG: MMR failed (%s); falling back to plain similarity", exc)
        return candidates[:settings.k]


def format_history_context(results) -> str:
    """Renders retrieved messages as the context block appended to the user's
    prompt: ``[YYYY-MM-DD HH:MM:SS | sender]: content``."""
    lines = []
    for result in results:
        payload = result.get("payload") or {}
        stamp = " ".join(
            part for part in (payload.get("msg_date"), payload.get("msg_time")) if part
        )
        who = payload.get("sender_name") or payload.get("sender_id") or (
            "bot" if payload.get("is_bot") else "?"
        )
        content = " ".join(str(payload.get("content") or "").split())
        lines.append(f"[{stamp} | {who}]: {content}")
    return "\n".join(lines)
