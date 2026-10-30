"""Tests for the Messages page: listing, keyword/channel filters, duplicate and
similar detection, and deletion of messages together with their vectors and
keyword-index entries.

Vectors are 8-dim (see the conftest autouse fixtures). Identical vectors give
cosine similarity 1.0; orthogonal vectors give 0.0.
"""
import pytest

import database
from database import (
    init_db,
    insert_message_history,
    insert_message_vector,
    sqlite_vec_available,
)

CHANNEL_A = "wa_web:gA@g.us"
CHANNEL_B = "wa_web:gB@g.us"

VEC_X = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
VEC_Y = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

pytestmark = pytest.mark.skipif(not sqlite_vec_available(), reason="sqlite-vec not available")


def _insert(channel, content, vector, msg_id, ts=1_700_000_000):
    row_id = insert_message_history(
        message_id=msg_id,
        channel_id=channel,
        remote_jid=channel,
        sender_name="Alice",
        sender_id="alice@s.whatsapp.net",
        content=content,
        msg_timestamp=ts,
    )
    if vector is not None:
        insert_message_vector(row_id, channel, {"content": content}, vector)
    return row_id


@pytest.fixture(autouse=True)
def _ready_db_without_csrf(app):
    init_db()
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = True


@pytest.fixture
def seeded():
    init_db()
    ids = {
        "dup_1": _insert(CHANNEL_A, "Bom dia pessoal", VEC_X, "m1", ts=1_700_000_001),
        "dup_2": _insert(CHANNEL_A, "  bom DIA pessoal ", VEC_Y, "m2", ts=1_700_000_002),
        "sim_1": _insert(CHANNEL_B, "Relatorio trimestral pronto", VEC_X, "m3", ts=1_700_000_003),
        "sim_2": _insert(CHANNEL_B, "O relatorio trimestral esta pronto", VEC_X, "m4", ts=1_700_000_004),
        "other": _insert(CHANNEL_B, "Vamos ao futebol", VEC_Y, "m5", ts=1_700_000_005),
        "no_vec": _insert(CHANNEL_A, "Mensagem sem vetor", None, "m6", ts=1_700_000_006),
    }
    return ids


def _vector_ids():
    conn = database.get_db()  # loads sqlite-vec so the vec0 table is readable
    try:
        return {r[0] for r in conn.execute("SELECT id FROM message_history_vec").fetchall()}
    finally:
        conn.close()


def _fts_ids():
    conn = database.get_db()
    try:
        return {r[0] for r in conn.execute("SELECT rowid FROM message_history_fts").fetchall()}
    finally:
        conn.close()


def test_list_all_newest_first_with_vector_flag(client, seeded):
    res = client.get("/api/messages")
    assert res.status_code == 200
    body = res.get_json()
    assert body["mode"] == "all"
    assert body["total"] == 6
    assert [m["id"] for m in body["messages"]][0] == seeded["no_vec"]
    flags = {m["id"]: m["has_vector"] for m in body["messages"]}
    assert flags[seeded["no_vec"]] is False
    assert flags[seeded["dup_1"]] is True
    assert sorted(body["channels"]) == sorted([CHANNEL_A, CHANNEL_B])


def test_filter_by_channel_and_keyword(client, seeded):
    body = client.get(f"/api/messages?channel_id={CHANNEL_B}").get_json()
    assert body["total"] == 3
    assert all(m["channel_id"] == CHANNEL_B for m in body["messages"])

    body = client.get("/api/messages?q=futebol").get_json()
    assert [m["id"] for m in body["messages"]] == [seeded["other"]]


def test_keyword_treats_like_wildcards_literally(client, seeded):
    body = client.get("/api/messages?q=%25").get_json()
    assert body["total"] == 0


def test_duplicates_group_identical_text_ignoring_case_and_spacing(client, seeded):
    body = client.get("/api/messages?mode=duplicates").get_json()
    assert body["total"] == 1
    group = body["groups"][0]
    assert group["count"] == 2
    assert {m["id"] for m in group["messages"]} == {seeded["dup_1"], seeded["dup_2"]}


def test_similar_groups_respect_threshold(client, seeded):
    body = client.get("/api/messages?mode=similar&threshold=0.9").get_json()
    assert body["total"] == 1
    group = body["groups"][0]
    assert {m["id"] for m in group["messages"]} == {seeded["sim_1"], seeded["sim_2"]}
    for member in group["messages"]:
        assert member["similarity"] == pytest.approx(1.0, abs=1e-3)
        assert member["best_match_id"] in {seeded["sim_1"], seeded["sim_2"]}


def test_similar_keyword_keeps_groups_with_a_match(client, seeded):
    body = client.get("/api/messages?mode=similar&q=trimestral").get_json()
    assert body["total"] == 1
    body = client.get("/api/messages?mode=similar&q=futebol").get_json()
    assert body["total"] == 0


def test_invalid_mode_and_threshold_are_rejected(client):
    assert client.get("/api/messages?mode=bogus").status_code == 400
    assert client.get("/api/messages?mode=similar&threshold=0.1").status_code == 400
    assert client.get("/api/messages?mode=similar&threshold=abc").status_code == 400


def test_delete_single_removes_row_vector_and_keyword_entry(client, seeded):
    target = seeded["dup_1"]
    assert target in _vector_ids()
    assert target in _fts_ids()

    res = client.delete(f"/api/messages/{target}")
    assert res.status_code == 200
    body = res.get_json()
    assert body["deleted"] == 1
    assert body["vectors_deleted"] == 1

    conn = database.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM message_history WHERE id = ?", (target,)).fetchone()[0] == 0
    finally:
        conn.close()
    assert target not in _vector_ids()
    assert target not in _fts_ids()


def test_delete_missing_message_returns_404(client, seeded):
    assert client.delete("/api/messages/999999").status_code == 404


def test_bulk_delete_removes_selected_only(client, seeded):
    ids = [seeded["dup_1"], seeded["sim_1"]]
    res = client.post("/api/messages/delete", json={"ids": ids})
    assert res.status_code == 200
    body = res.get_json()
    assert body["deleted"] == 2
    assert body["vectors_deleted"] == 2

    remaining = client.get("/api/messages").get_json()
    remaining_ids = {m["id"] for m in remaining["messages"]}
    assert remaining_ids == {seeded["dup_2"], seeded["sim_2"], seeded["other"], seeded["no_vec"]}
    assert not (set(ids) & _vector_ids())


def test_bulk_delete_validates_payload(client, seeded):
    assert client.post("/api/messages/delete", json={}).status_code == 400
    assert client.post("/api/messages/delete", json={"ids": []}).status_code == 400
    assert client.post("/api/messages/delete", json={"ids": ["x"]}).status_code == 400


def test_messages_page_renders(client):
    res = client.get("/messages")
    assert res.status_code == 200
    assert b"Messages" in res.data
    assert b"/static/js/messages.js" in res.data
