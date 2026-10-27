"""History RAG: HYBRID retrieval over the message_history timeline — semantic
vectors (sqlite-vec, cosine) fused with BM25 keyword matches (FTS5, porter +
unicode61) via Reciprocal Rank Fusion — attached to the user's prompt before
the LLM call (the worker only triggers this when it is mentioned).

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


def _fts_query_for(query):
    r"""Sanitizes the query into an FTS5 OR-of-quoted-tokens expression.

    - ``re.findall(r"\w+")`` keeps only word characters, so user-supplied FTS5
      operators (AND/OR/NEAR, quotes, parens) can never be injected;
    - tokens are joined with OR so conversational queries match documents that
      contain any of the terms — bm25() then ranks by term rarity (IDF);
    - returns None when no usable token remains (keyword leg is skipped).
    """
    import re

    tokens, seen = [], set()
    for token in re.findall(r"\w+", query, re.UNICODE):
        token = token.lower()
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)
        if len(tokens) >= 16:
            break
    if not tokens:
        return None
    return " OR ".join('"%s"' % t for t in tokens)


def _semantic_leg(conn, channel_id, query_vector, fetch_k, exclude_id=None,
                  cutoff_ts=None, max_k=None):
    """Semantic (KNN) leg: returns (candidates, ranked_ids) with ``fetch_k``
    rows that survive the exclusions.

    sqlite-vec returns the k nearest rows first; the current message and the
    verbatim window are dropped afterwards. So k is doubled until ``fetch_k``
    rows survive, the index runs out of rows, or ``max_k`` (the channel's
    vector count) is reached. Without this, excluded rows would consume the
    fetch budget and the leg could return fewer than requested.
    """
    limit = max(fetch_k, max_k or fetch_k)
    k = fetch_k
    serialized = json.dumps(query_vector)
    while True:
        rows = conn.execute(
            """
            SELECT id, distance, payload, vector
            FROM message_history_vec
            WHERE channel_id = ? AND vector MATCH ? AND k = ?
            ORDER BY distance
            """,
            [channel_id, serialized, k],
        ).fetchall()
        candidates, ranked = {}, []
        for row in rows:
            if exclude_id is not None and row["id"] == exclude_id:
                continue
            try:
                payload = json.loads(row["payload"]) if row["payload"] else {}
            except (TypeError, ValueError):
                payload = {}
            if cutoff_ts is not None and (payload.get("msg_ts") or 0) >= cutoff_ts:
                continue  # already verbatim in the recent-window context
            candidates[row["id"]] = {
                "payload": payload,
                "vector": row["vector"],
                "distance": row["distance"],
            }
            ranked.append(row["id"])
        exhausted = len(rows) < k or k >= limit
        if len(ranked) >= fetch_k or exhausted:
            return candidates, ranked[:fetch_k]
        k = min(k * 2, limit)


def _bm25_search(conn, fts_query, channel_id, exclude_id=None, cutoff_ts=None, limit=20):
    """BM25 keyword leg (FTS5, porter + unicode61). Returns message_history
    ids, best-first (most negative bm25 first). The JOIN carries the channel
    scope plus the same exclusion/cutoff filters the semantic leg applies."""
    sql = """
        SELECT message_history_fts.rowid AS rowid
        FROM message_history_fts
        JOIN message_history h ON h.id = message_history_fts.rowid
        WHERE message_history_fts MATCH ?
          AND message_history_fts.channel_id = ?
    """
    params = [fts_query, channel_id]
    if exclude_id is not None:
        sql += ' AND message_history_fts.rowid != ?'
        params.append(exclude_id)
    if cutoff_ts is not None:
        sql += ' AND h.msg_timestamp < ?'
        params.append(cutoff_ts)
    sql += ' ORDER BY bm25(message_history_fts) LIMIT ?'
    params.append(limit)
    return [row["rowid"] for row in conn.execute(sql, params).fetchall()]


def _rrf_fuse(ranked_lists, rrf_k: int = 60) -> dict:
    """Reciprocal Rank Fusion across ranked id lists (each best-first):
    score(d) = sum over legs of 1 / (rrf_k + position_of_d_in_leg)."""
    scores = {}
    for ranked in ranked_lists:
        for position, row_id in enumerate(ranked, start=1):
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (rrf_k + position)
    return scores


def retrieve_relevant_history(query, channel_id, exclude_id=None, cutoff_ts=None,
                              settings: HistoryRagSettings | None = None) -> list:
    """
    HYBRID retrieval over the channel history: the semantic vector leg
    (sqlite-vec, cosine) is fused with the BM25 keyword leg (FTS5) via
    Reciprocal Rank Fusion, then filtered/re-ranked by ``settings.search_type``.

    Degradation (fail-open): without embeddings the BM25 leg alone still
    answers; without keyword data the semantic leg alone answers; with neither,
    returns []. The query embedding is skipped entirely when the channel has no
    vectors.
    """
    settings = settings or get_settings()
    if not settings.enabled or not channel_id or not (query or "").strip():
        return []

    from database import get_db

    fts_query = _fts_query_for(query)

    # Partition sizes decide which legs can run — and avoid paying for the
    # query embedding when the channel has no vectors at all.
    conn = get_db()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(
                'SELECT COUNT(*) FROM message_history_vec WHERE channel_id = ?',
                (channel_id,),
            )
            vec_count = cursor.fetchone()[0]
        except Exception:
            vec_count = 0
    finally:
        conn.close()

    if vec_count == 0 and fts_query is None:
        # No vectors for the channel and no usable keyword tokens: neither leg
        # could return anything — skip the embedding API call entirely. (The
        # BM25 leg itself is cheap when the channel has no keyword hits, so it
        # is attempted without a pre-count — a COUNT over an FTS5 UNINDEXED
        # column would be a full table scan per retrieval.)
        return []

    query_vector = None
    if vec_count > 0:
        try:
            import agent.lc.embeddings as embeddings

            if embeddings.embeddings_available():
                query_vector = embeddings.get_embeddings().embed_query(query)
        except Exception as exc:
            logger.warning("History RAG: query embedding failed (%s); BM25-only", exc)
            query_vector = None

    semantic_candidates = {}
    semantic_ranked = []
    bm25_ranked = []
    bm25_payloads = {}

    conn = get_db()
    try:
        if query_vector is not None:
            semantic_candidates, semantic_ranked = _semantic_leg(
                conn, channel_id, query_vector, settings.fetch_k,
                exclude_id=exclude_id, cutoff_ts=cutoff_ts, max_k=vec_count,
            )

        if fts_query is not None:
            try:
                bm25_ranked = _bm25_search(
                    conn, fts_query, channel_id,
                    exclude_id=exclude_id, cutoff_ts=cutoff_ts,
                    limit=settings.fetch_k,
                )
            except Exception as exc:
                logger.warning("History RAG: BM25 leg failed (%s); semantic-only", exc)
                bm25_ranked = []
            missing = [rid for rid in bm25_ranked if rid not in semantic_candidates]
            if missing:
                placeholders = ",".join("?" * len(missing))
                for row in conn.execute(f"""
                    SELECT id, channel_id, content, sender_id, sender_name, is_bot,
                           msg_timestamp, msg_date, msg_hour, msg_minute, msg_second
                    FROM message_history
                    WHERE id IN ({placeholders})
                """, missing):
                    bm25_payloads[row["id"]] = _payload_from_row(row)
    finally:
        conn.close()

    fused = _rrf_fuse([semantic_ranked, bm25_ranked])
    fused_ids = sorted(fused, key=lambda rid: fused[rid], reverse=True)

    candidates = []
    for rid in fused_ids:
        known = semantic_candidates.get(rid)
        candidates.append({
            "id": rid,
            "payload": known["payload"] if known else bm25_payloads.get(rid, {}),
            "vector": known["vector"] if known else None,
            "distance": known["distance"] if known else None,
            "rrf": fused[rid],
        })

    if settings.search_type == "similarity_score_threshold":
        picked = [
            c for c in candidates
            if c["distance"] is not None
            and (1.0 - float(c["distance"])) >= settings.score_threshold
        ][:settings.k]
    elif settings.search_type == "mmr":
        picked = _mmr_select(candidates, settings)
    else:  # similarity
        picked = candidates[:settings.k]

    return [
        {
            "id": c["id"],
            "score": (round(1.0 - float(c["distance"]), 4)
                      if c["distance"] is not None else None),
            "payload": c["payload"],
        }
        for c in picked
    ]


def _mmr_select(candidates, settings) -> list:
    """Maximal Marginal Relevance over the fused candidate pool.

    relevance  = normalized fusion (RRF) score (semantic + keyword legs);
    redundancy = max cosine similarity to already-selected candidates that
    have vectors (BM25-only candidates carry no redundancy signal).
    """
    if not candidates:
        return []
    try:
        import numpy as np

        max_rrf = max(c["rrf"] for c in candidates) or 1.0
        vecs = {}
        for c in candidates:
            if c.get("vector"):
                v = np.frombuffer(bytes(c["vector"]), dtype="<f4")
                norm = float(np.linalg.norm(v))
                if norm:
                    vecs[c["id"]] = v / norm

        selected, remaining = [], list(candidates)
        while remaining and len(selected) < settings.k:
            best, best_score = None, float("-inf")
            for c in remaining:
                redundancy = 0.0
                if c["id"] in vecs and selected:
                    sims = [
                        float(vecs[c["id"]] @ vecs[s["id"]])
                        for s in selected if s["id"] in vecs
                    ]
                    redundancy = max(sims) if sims else 0.0
                score = (
                    settings.lambda_mult * (c["rrf"] / max_rrf)
                    - (1.0 - settings.lambda_mult) * redundancy
                )
                if score > best_score:
                    best, best_score = c, score
            selected.append(best)
            remaining.remove(best)
        return selected
    except Exception as exc:
        logger.warning("History RAG: MMR failed (%s); falling back to fusion order", exc)
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
