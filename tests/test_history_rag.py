"""Tests for the message-history RAG: vectorization into sqlite-vec,
channel-scoped retrieval (similarity / mmr / similarity_score_threshold) and
the prompt context block.

The conftest autouse fixtures provide: a temp DB (mock_db_path), 8-dim
FakeEmbeddings (_embeddings_isolation) and NW_HISTORY_VEC_DIMS=8
(history_vec_dims_for_tests). These tests re-patch the embeddings with a
deterministic keyword->cluster implementation for precise assertions.
"""
import json
import sqlite3
from unittest.mock import patch

import pytest
from app import app

import database
from database import (
    clear_channel_history,
    get_missing_vector_ids,
    init_db,
    insert_message_history,
    set_config,
)

CHANNEL_A = "wa_web:gA@g.us"
CHANNEL_B = "wa_web:gB@g.us"


class ClusterEmbeddings:
    """Deterministic keyword -> cluster vectors (size 8). Orthogonal clusters
    make cosine distances exact: same keyword -> 0.0, different -> 1.0."""

    def __init__(self, size=8):
        self.size = size
        self.embed_query_calls = 0

    def _vec(self, text):
        t = str(text).lower()
        if "relatorio" in t:
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        if "futebol" in t:
            return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        if "cozinha" in t:
            return [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        return [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        self.embed_query_calls += 1
        return self._vec(text)


@pytest.fixture
def db():
    init_db()
    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as c:
        with app.app_context():
            yield c


@pytest.fixture
def cluster_embeddings(monkeypatch):
    """Re-patches the conftest FakeEmbeddings with deterministic clusters."""
    import agent.lc.embeddings as e

    fake = ClusterEmbeddings(size=8)
    monkeypatch.setattr(e, "get_embeddings", lambda: fake)
    monkeypatch.setattr(e, "embeddings_available", lambda: True)
    return fake


def _add(channel, content, ts, **kw):
    return insert_message_history(
        message_id=f"{channel}-{ts}-{abs(hash(content)) % 10**8}",
        channel_id=channel,
        remote_jid=channel.split(':', 1)[1],
        is_group=1,
        sender_name='Ana',
        content=content,
        msg_timestamp=ts,
        **kw,
    )


def _vectorize_all():
    from agent.lc.history_rag import vectorize_message

    for row_id in get_missing_vector_ids(limit=1000):
        assert vectorize_message(row_id) is True


def _connect_with_vec():
    """Raw test connection WITH the sqlite-vec extension loaded (needed to
    query the vec0 virtual table directly)."""
    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        pass
    return conn


# ---------------------------------------------------------------------------
# Schema + vectorization
# ---------------------------------------------------------------------------

def test_vec_table_has_partition_and_payload(db):
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='message_history_vec'"
    ).fetchone()
    assert row is not None
    sql = row['sql']
    assert 'partition key' in sql
    assert '+payload' in sql
    assert 'distance_metric=cosine' in sql


def test_vectorize_and_retrieve_similarity_scoped_by_channel(db, cluster_embeddings):
    rid_a1 = _add(CHANNEL_A, 'envie o relatorio Q1', 1000)
    rid_a2 = _add(CHANNEL_A, 'relatorio revisado ontem', 1001)
    _add(CHANNEL_A, 'jogo de futebol hoje', 1002)
    _add(CHANNEL_B, 'relatorio de vendas de la', 1003)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    results = retrieve_relevant_history(
        'sobre o relatorio', CHANNEL_A,
        settings=HistoryRagSettings(enabled=True, search_type='similarity',
                                    k=2, fetch_k=20, score_threshold=0.0,
                                    lambda_mult=0.5),
    )
    contents = [r['payload']['content'] for r in results]
    assert len(contents) == 2
    assert all('relatorio' in c for c in contents)
    # Channel B row must never leak into channel A retrieval.
    assert 'relatorio de vendas de la' not in contents
    assert {rid_a1, rid_a2} == {r['id'] for r in results}


def test_retrieve_excludes_current_message(db, cluster_embeddings):
    _add(CHANNEL_A, 'relatorio mensal', 1000)
    rid_current = _add(CHANNEL_A, 'relatorio mensal', 1001)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    results = retrieve_relevant_history(
        'relatorio mensal', CHANNEL_A, exclude_id=rid_current,
        settings=HistoryRagSettings(enabled=True, search_type='similarity',
                                    k=5, fetch_k=20, score_threshold=0.0,
                                    lambda_mult=0.5),
    )
    assert rid_current not in [r['id'] for r in results]
    assert len(results) == 1


def test_retrieve_cutoff_skips_recent_window(db, cluster_embeddings):
    _add(CHANNEL_A, 'relatorio antigo do arquivo', 1000)
    _add(CHANNEL_A, 'relatorio novo de agora', 2000)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    settings = HistoryRagSettings(enabled=True, search_type='similarity',
                                  k=10, fetch_k=20, score_threshold=0.0,
                                  lambda_mult=0.5)
    without_cutoff = retrieve_relevant_history('relatorio', CHANNEL_A, settings=settings)
    assert len(without_cutoff) == 2

    with_cutoff = retrieve_relevant_history(
        'relatorio', CHANNEL_A, cutoff_ts=1500, settings=settings
    )
    contents = [r['payload']['content'] for r in with_cutoff]
    assert contents == ['relatorio antigo do arquivo']


# ---------------------------------------------------------------------------
# mmr / threshold / disabled
# ---------------------------------------------------------------------------

def test_mmr_diversifies_results(db, cluster_embeddings):
    _add(CHANNEL_A, 'envie o relatorio Q1', 1000)
    _add(CHANNEL_A, 'relatorio revisado', 1001)
    _add(CHANNEL_A, 'jogo de futebol hoje', 1002)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    # Low lambda favours diversity: after picking one 'relatorio' hit, the
    # near-duplicate is penalized and the 'futebol' message is selected.
    results = retrieve_relevant_history(
        'relatorio', CHANNEL_A,
        settings=HistoryRagSettings(enabled=True, search_type='mmr',
                                    k=2, fetch_k=20, score_threshold=0.0,
                                    lambda_mult=0.3),
    )
    contents = [r['payload']['content'] for r in results]
    assert len(contents) == 2
    assert any('relatorio' in c for c in contents)
    assert any('futebol' in c for c in contents)


def test_threshold_filters_low_scores(db, cluster_embeddings):
    _add(CHANNEL_A, 'relatorio mensal', 1000)
    _add(CHANNEL_A, 'jogo de futebol hoje', 1001)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    results = retrieve_relevant_history(
        'relatorio', CHANNEL_A,
        settings=HistoryRagSettings(enabled=True,
                                    search_type='similarity_score_threshold',
                                    k=5, fetch_k=20, score_threshold=0.99,
                                    lambda_mult=0.5),
    )
    contents = [r['payload']['content'] for r in results]
    assert contents == ['relatorio mensal']
    assert all(r['score'] >= 0.99 for r in results)


def test_disabled_returns_empty(db, cluster_embeddings):
    set_config('HISTORY_RAG_ENABLED', 'false')
    _add(CHANNEL_A, 'relatorio mensal', 1000)

    from agent.lc.history_rag import retrieve_relevant_history

    # Gate off: nothing gets vectorized and retrieval short-circuits.
    assert retrieve_relevant_history('relatorio', CHANNEL_A) == []


# ---------------------------------------------------------------------------
# Backfill + webhook integration + formatting + settings
# ---------------------------------------------------------------------------

def test_backfill_missing_vectors(db, cluster_embeddings):
    _add(CHANNEL_A, 'relatorio antigo', 1000)
    _add(CHANNEL_A, 'futebol ontem', 1001)
    assert len(get_missing_vector_ids(limit=100)) == 2

    from agent.lc.history_rag import backfill_missing_vectors

    assert backfill_missing_vectors(limit=100) == 2
    assert get_missing_vector_ids(limit=100) == []


@patch('routes.webhooks.get_config', return_value='secret')
def test_webhook_vectorizes_history_only_message(mock_get, client):
    response = client.post(
        '/api/webhook',
        headers={'X-Webhook-Secret': 'secret'},
        json={
            'channel_id': CHANNEL_A,
            'remote_jid': 'gA@g.us',
            'sender_id': '5511999999999',
            'sender_name': 'Julio',
            'content': 'bom dia com relatorio em anexo',
            'message_id': 'WA-VEC-1',
            'msg_timestamp': 1700000000,
            'history_only': True,
        },
    )
    assert response.status_code == 200
    assert response.get_json()['status'] == 'saved_only'

    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Raw connections must load the sqlite-vec extension to query vec0 tables.
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        pass
    row = conn.execute(
        '''SELECT v.payload FROM message_history_vec v
           JOIN message_history h ON h.id = v.id
           WHERE h.message_id = ?''',
        ('WA-VEC-1',),
    ).fetchone()
    conn.close()
    assert row is not None
    payload = json.loads(row['payload'])
    assert payload['content'] == 'bom dia com relatorio em anexo'
    assert payload['sender_name'] == 'Julio'
    assert payload['is_bot'] is False
    assert payload['msg_ts'] == 1700000000


def test_format_history_context():
    from agent.lc.history_rag import format_history_context

    results = [
        {'id': 1, 'score': 0.9, 'payload': {
            'content': 'linha um\ne linha dois', 'sender_name': 'Bob',
            'msg_date': '2023-11-14', 'msg_time': '19:13:22'}},
        {'id': 2, 'score': 0.5, 'payload': {
            'content': 'resposta do bot', 'is_bot': True,
            'msg_date': '2023-11-14', 'msg_time': '19:14:01'}},
    ]
    block = format_history_context(results)
    lines = block.split('\n')
    assert lines[0] == '[2023-11-14 19:13:22 | Bob]: linha um e linha dois'
    assert lines[1] == '[2023-11-14 19:14:01 | bot]: resposta do bot'


def test_get_settings_clamps_invalid_values(db):
    set_config('HISTORY_RAG_K', '999')
    set_config('HISTORY_RAG_FETCH_K', '1')
    set_config('HISTORY_RAG_SEARCH_TYPE', 'banana')
    set_config('HISTORY_RAG_SCORE_THRESHOLD', '7')
    set_config('HISTORY_RAG_LAMBDA', '-2')

    from agent.lc.history_rag import get_settings

    settings = get_settings()
    assert settings.k == 50               # clamped to the upper bound
    assert settings.fetch_k == 50         # never below k
    assert settings.search_type == 'mmr'  # unknown -> default
    assert settings.score_threshold == 1.0
    assert settings.lambda_mult == 0.0


# ---------------------------------------------------------------------------
# Double-check fixes: gate, empty-partition skip, label-free query
# ---------------------------------------------------------------------------

def test_vectorize_gated_by_enabled(db, cluster_embeddings):
    set_config('HISTORY_RAG_ENABLED', 'false')
    row_id = _add(CHANNEL_A, 'relatorio com gate', 1000)

    from agent.lc.history_rag import backfill_missing_vectors, vectorize_message

    assert vectorize_message(row_id) is False
    assert get_missing_vector_ids(limit=10) == [row_id]  # stays without vector

    # Re-enabling + boot backfill covers the gap.
    set_config('HISTORY_RAG_ENABLED', 'true')
    assert backfill_missing_vectors(limit=10) == 1
    assert get_missing_vector_ids(limit=10) == []


def test_retrieve_skips_embedding_on_empty_channel(db, cluster_embeddings):
    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    settings = HistoryRagSettings(enabled=True, search_type='similarity',
                                  k=3, fetch_k=20, score_threshold=0.0,
                                  lambda_mult=0.5)

    # No vectors for the channel: no point paying for the query embedding.
    assert retrieve_relevant_history('relatorio', CHANNEL_A, settings=settings) == []
    assert cluster_embeddings.embed_query_calls == 0

    _add(CHANNEL_A, 'relatorio existe agora', 1000)
    _vectorize_all()
    results = retrieve_relevant_history('relatorio', CHANNEL_A, settings=settings)
    assert len(results) == 1
    assert cluster_embeddings.embed_query_calls >= 1


def test_rag_query_is_label_free(monkeypatch, db):
    """Regression: the retrieval query must be the mention-cleaned,
    label-free text — not the labeled user prompt."""
    from agent.message_processor import _attach_history_rag

    captured = {}

    def fake_retrieve(query, channel_id, exclude_id=None, cutoff_ts=None, settings=None):
        captured['query'] = query
        return [{'id': 9, 'score': 0.9, 'payload': {
            'content': 'msg antiga', 'sender_name': 'Bob',
            'msg_date': '2023-11-14', 'msg_time': '10:00:00'}}]

    import agent.lc.history_rag as hr
    monkeypatch.setattr(hr, 'retrieve_relevant_history', fake_retrieve)

    rag_query = '@Nano sobre o relatorio?'
    labeled = f'[Message from: Dani (444)]\n{rag_query}'
    out = _attach_history_rag(db.cursor(), CHANNEL_A, rag_query, labeled)

    assert captured['query'] == rag_query           # label-free query used for search
    assert out.startswith(labeled)                  # context APPENDED after the prompt
    assert 'Contexto relevante recuperado' in out
    assert '[2023-11-14 10:00:00 | Bob]: msg antiga' in out


# ---------------------------------------------------------------------------
# Performance double-check fixes: dims migration, scoped trim, idempotency
# ---------------------------------------------------------------------------

def test_vec_table_rebuilt_on_dims_change(db, monkeypatch):
    """Regression: switching the embeddings provider (dims change) must drop
    and recreate the vec table — otherwise every insert/KNN fails silently."""
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='message_history_vec'"
    ).fetchone()
    assert 'float[8]' in row['sql']  # conftest env

    # Simulate a provider switch to 4 dims.
    monkeypatch.setenv('NW_HISTORY_VEC_DIMS', '4')
    init_db()
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='message_history_vec'"
    ).fetchone()
    assert 'float[4]' in row['sql']

    # And back.
    monkeypatch.setenv('NW_HISTORY_VEC_DIMS', '8')
    init_db()
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='message_history_vec'"
    ).fetchone()
    assert 'float[8]' in row['sql']


def test_trim_is_channel_scoped_and_keeps_other_channels(db, cluster_embeddings):
    set_config('MESSAGE_HISTORY_SIZE', '3')

    for i in range(3):
        _add(CHANNEL_A, f'relatorio {i}', 1000 + i)
    _vectorize_all()

    rid_b = _add(CHANNEL_B, 'relatorio de outro canal', 1000)
    _vectorize_all()

    # Push channel A past the limit: trim must only touch channel A.
    _add(CHANNEL_A, 'relatorio novo', 2000)
    _vectorize_all()  # every stored message gets a vector, as in production

    conn = _connect_with_vec()
    a_hist = conn.execute(
        'SELECT COUNT(*) FROM message_history WHERE channel_id = ?', (CHANNEL_A,)
    ).fetchone()[0]
    a_vec = conn.execute(
        '''SELECT COUNT(*) FROM message_history_vec v
           JOIN message_history h ON h.id = v.id WHERE h.channel_id = ?''',
        (CHANNEL_A,),
    ).fetchone()[0]
    hist_ids = {r['id'] for r in conn.execute(
        'SELECT id FROM message_history WHERE channel_id = ?', (CHANNEL_A,))}
    vec_ids = {r['id'] for r in conn.execute(
        'SELECT id FROM message_history_vec WHERE channel_id = ?', (CHANNEL_A,))}
    b_vec = conn.execute(
        '''SELECT v.id FROM message_history_vec v
           JOIN message_history h ON h.id = v.id WHERE h.channel_id = ?''',
        (CHANNEL_B,),
    ).fetchall()

    assert a_hist == 3
    assert a_vec == 3
    assert vec_ids == hist_ids  # no orphaned vectors after the scoped cleanup
    assert [r['id'] for r in b_vec] == [rid_b]  # other channel untouched

    a_fts = conn.execute(
        'SELECT COUNT(*) FROM message_history_fts WHERE channel_id = ?', (CHANNEL_A,)
    ).fetchone()[0]
    b_fts = conn.execute(
        'SELECT COUNT(*) FROM message_history_fts WHERE channel_id = ?', (CHANNEL_B,)
    ).fetchone()[0]
    assert a_fts == 3   # FTS trimmed/scoped together with the history rows
    assert b_fts == 1   # other channel untouched
    conn.close()


def test_insert_vector_idempotent(db, cluster_embeddings):
    rid = _add(CHANNEL_A, 'relatorio idempotente', 1000)

    from database import insert_message_vector

    assert insert_message_vector(rid, CHANNEL_A, {'n': 1}, [1.0, 0, 0, 0, 0, 0, 0, 0])
    assert insert_message_vector(rid, CHANNEL_A, {'n': 2}, [1.0, 0, 0, 0, 0, 0, 0, 0])

    conn = _connect_with_vec()
    rows = conn.execute(
        'SELECT payload FROM message_history_vec WHERE id = ?', (rid,)
    ).fetchall()
    conn.close()
    assert len(rows) == 1  # DELETE+INSERT: never duplicated
    assert json.loads(rows[0]['payload'])['n'] == 2


def test_fts_table_created(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'message_history_fts' in names


def test_fts_sync_on_insert_trim_and_clear(db):
    _add(CHANNEL_A, 'relatorio A1', 1000)
    _add(CHANNEL_B, 'relatorio B1', 1000)

    def fts_ids(channel):
        conn = _connect_with_vec()
        rows = conn.execute(
            'SELECT rowid FROM message_history_fts WHERE channel_id = ? ORDER BY rowid',
            (channel,))
        ids = [r['rowid'] for r in rows]
        conn.close()
        return ids

    assert len(fts_ids(CHANNEL_A)) == 1  # synced on insert
    assert len(fts_ids(CHANNEL_B)) == 1

    # Trim channel A beyond the limit: FTS row of the trimmed message removed.
    set_config('MESSAGE_HISTORY_SIZE', '1')
    _add(CHANNEL_A, 'relatorio A2', 1001)
    assert len(fts_ids(CHANNEL_A)) == 1

    # Clear channel A: FTS emptied, channel B untouched.
    clear_channel_history(CHANNEL_A)
    assert fts_ids(CHANNEL_A) == []
    assert len(fts_ids(CHANNEL_B)) == 1


def test_fts_backfilled_on_init(db):
    # Simulate rows stored before the FTS index existed (raw insert).
    conn = _connect_with_vec()
    conn.execute(
        "INSERT INTO message_history (message_id, channel_id, content, msg_timestamp) "
        "VALUES ('raw-1', ?, 'relatorio cru pre-fts', 1)",
        (CHANNEL_A,),
    )
    conn.commit()
    before = conn.execute(
        'SELECT COUNT(*) FROM message_history_fts WHERE channel_id = ?', (CHANNEL_A,)
    ).fetchone()[0]
    conn.close()
    assert before == 0

    init_db()  # idempotent backfill
    conn = _connect_with_vec()
    after = conn.execute(
        'SELECT COUNT(*) FROM message_history_fts WHERE channel_id = ?', (CHANNEL_A,)
    ).fetchone()[0]
    conn.close()
    assert after == 1


def test_bm25_leg_works_without_embeddings(db, monkeypatch):
    """Hybrid value: when the semantic leg is dead (no embeddings), the BM25
    keyword leg alone still answers the query."""
    import agent.lc.embeddings as e
    monkeypatch.setattr(e, 'embeddings_available', lambda: False)

    _add(CHANNEL_A, 'relatorio mensal daqui', 1000)

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    results = retrieve_relevant_history(
        'relatorio', CHANNEL_A,
        settings=HistoryRagSettings(enabled=True, search_type='similarity',
                                    k=3, fetch_k=20, score_threshold=0.0,
                                    lambda_mult=0.5),
    )
    contents = [r['payload']['content'] for r in results]
    assert contents == ['relatorio mensal daqui']
    assert results[0]['score'] is None  # no semantic score available (BM25-only)


def test_query_with_operators_does_not_crash(db, cluster_embeddings):
    _add(CHANNEL_A, 'relatorio com aspas e (parenteses)', 1000)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    results = retrieve_relevant_history(
        'relatorio" OR (NEAR(a b)', CHANNEL_A,
        settings=HistoryRagSettings(enabled=True, search_type='similarity',
                                    k=5, fetch_k=20, score_threshold=0.0,
                                    lambda_mult=0.5),
    )
    contents = [r['payload']['content'] for r in results]
    assert any('relatorio' in c for c in contents)  # sanitized, no FTS5 injection


def test_hybrid_fusion_ranks_dual_leg_first(db, cluster_embeddings):
    """A document matched by BOTH legs (semantic + BM25) must rank above a
    document matched by only one leg."""
    _add(CHANNEL_A, 'relatorio semanal', 1000)
    _add(CHANNEL_A, 'futebol hoje', 1001)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    results = retrieve_relevant_history(
        'relatorio futebol', CHANNEL_A,
        settings=HistoryRagSettings(enabled=True, search_type='similarity',
                                    k=2, fetch_k=20, score_threshold=0.0,
                                    lambda_mult=0.5),
    )
    contents = [r['payload']['content'] for r in results]
    assert contents[0] == 'relatorio semanal'
    assert contents[1] == 'futebol hoje'


def test_semantic_leg_keeps_fetch_budget_after_cutoff(db, cluster_embeddings):
    """The nearest vectors sit inside the verbatim window (cutoff). They must not
    eat the KNN budget: the leg has to look further and still return fetch_k."""
    # Inserted first so they win the distance tie (lowest id) and are the
    # nearest neighbours of the query.
    for i in range(3):
        _add(CHANNEL_A, f'relatorio recente {i}', 2000 + i)
    for i in range(4):
        _add(CHANNEL_A, f'relatorio antigo {i}', 1000 + i)
    _vectorize_all()

    from agent.lc.history_rag import HistoryRagSettings, retrieve_relevant_history

    settings = HistoryRagSettings(enabled=True, search_type='similarity',
                                  k=2, fetch_k=2, score_threshold=0.0,
                                  lambda_mult=0.5)
    # 'xrelatorio' shares the cluster (substring) but no keyword token, so only
    # the semantic leg can answer: the keyword leg cannot mask the bug.
    results = retrieve_relevant_history(
        'xrelatorio', CHANNEL_A, cutoff_ts=1500, settings=settings
    )
    assert len(results) == 2
    assert all(r['payload']['content'].startswith('relatorio antigo') for r in results)
