"""Tests for the user-memory RAG retriever (Fase 2A) — agent.lc.memory_rag.

Covers:
- MemoryRetriever: rebuild, upsert (via DB sync), remove (via DB sync),
  get_relevant ranking, clear, persistence.
- get_memory_block: RAG path + fallback to legacy injection.
- settings.embeddings_provider / embeddings_model resolution.
- database hooks (add/update/delete_user_memory): never break the DB write
  when embeddings/FAISS are unavailable.
"""
from pathlib import Path

import pytest
from langchain_core.embeddings import FakeEmbeddings

from agent.lc import memory_rag, settings


@pytest.fixture
def _embed_8(monkeypatch):
    """Patches the retriever to embed into an 8-dim vector space
    (FAISS test-friendly; mirrors the dimension the real model would use)."""
    import agent.lc.memory_rag as m
    import agent.lc.embeddings as emb

    def _fn():
        return FakeEmbeddings(size=8, seed=42)

    # Patch BOTH namespaces: _embed() reads memory_rag.get_embeddings,
    # embeddings_available() reads embeddings.get_embeddings.
    monkeypatch.setattr(m, "get_embeddings", _fn)
    monkeypatch.setattr(emb, "get_embeddings", _fn)
    monkeypatch.setattr(m, "_dims_for_provider", lambda p: 8)


def _patch_embeddings(monkeypatch, size=8, seed=42):
    """Patches get_embeddings in both modules + dimension + clears poison cache."""
    import agent.lc.memory_rag as m
    import agent.lc.embeddings as emb

    def _fn():
        return FakeEmbeddings(size=size, seed=seed)

    monkeypatch.setattr(m, "get_embeddings", _fn)
    monkeypatch.setattr(emb, "get_embeddings", _fn)
    monkeypatch.setattr(m, "_dims_for_provider", lambda p: size)


@pytest.fixture(autouse=True)
def _ensure_user_memory_table(mock_db_path):
    """Fresh DB per test: create user_memory, as the real app does at boot."""
    import database

    with database.get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS user_memory "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, instruction TEXT)"
        )


class TestMemoryRetriever:
    @pytest.fixture
    def index_dir(self, tmp_path):
        return Path(tmp_path) / "lc_index_user_memory"

    def _add_rows(self, n):
        """Insert n memories into the test DB (mirrors user flow)."""
        import database

        for i in range(1, n + 1):
            database.add_user_memory(f"mem {i}")

    def test_rebuild_empty_creates_empty_index(self, index_dir):
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
        assert retriever.rebuild() is True
        assert retriever.exists()
        assert retriever.index is not None
        assert retriever.index.ntotal == 0
        assert retriever.metadata == {}

    def test_rebuild_populates_index(self, index_dir, _embed_8, monkeypatch):
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
        assert retriever.rebuild()
        self._add_rows(2)
        assert retriever.rebuild()
        assert retriever.index.ntotal == 2

    def test_upsert_increases_index_size(self, index_dir, _embed_8, monkeypatch):
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
        assert retriever.rebuild()
        self._add_rows(3)
        assert retriever.rebuild()
        assert retriever.index.ntotal == 3
        assert len(retriever.metadata) == 3

    def test_remove_from_index(self, index_dir, _embed_8, monkeypatch):
        import database

        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
        assert retriever.rebuild()
        self._add_rows(2)
        assert retriever.rebuild()
        assert retriever.index.ntotal == 2
        assert database.delete_user_memory(1) is True
        assert retriever.rebuild()
        assert retriever.index.ntotal == 1
        assert 1 not in retriever.metadata
        assert 2 in retriever.metadata

    def test_get_relevant_ranks_by_topic(self, tmp_path, monkeypatch):
        # Deterministic topic-based embeddings so ranking is asserted on
        # semantic similarity instead of a fixed random seed (M4 fix).
        import numpy as np

        class TopicEmbeddings:
            _VECS = {
                "color": np.array([1.0, 0.0, 0.0]),
                "car": np.array([0.0, 1.0, 0.0]),
                "book": np.array([0.0, 0.0, 1.0]),
            }
            def embed_documents(self, texts):
                out = []
                for t in texts:
                    for kw, vec in self._VECS.items():
                        if kw in t.split():
                            out.append(vec)
                            break
                    else:
                        out.append(np.zeros(3))
                return out

        index_dir = str(tmp_path / "idx")
        retriever = memory_rag.MemoryRetriever(index_dir=index_dir, k=2)
        monkeypatch.setattr(memory_rag, "INDEX_DIR", index_dir)
        monkeypatch.setattr(memory_rag, "get_embeddings", lambda: TopicEmbeddings())
        monkeypatch.setattr(memory_rag, "embeddings_available", lambda: True)
        monkeypatch.setattr(memory_rag, "_dims_for_provider", lambda p: 3)

        retriever.rebuild()
        import database

        database.add_user_memory("favorite color blue")
        database.add_user_memory("fast car red")
        database.add_user_memory("green book read")
        retriever.rebuild()

        ids = [mid for mid, _, _ in retriever.get_relevant("what is your favorite color")]
        assert ids == [1, 2], ids

    def test_get_relevant_empty_query_returns_recent_by_id(self, index_dir, _embed_8, monkeypatch):
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
        assert retriever.rebuild()
        self._add_rows(3)
        assert retriever.rebuild()
        res = retriever.get_relevant("")
        assert [r[0] for r in res] == [3, 2, 1]

    def test_get_relevant_no_index_triggers_rebuild(self, tmp_path):
        retriever = memory_rag.MemoryRetriever(index_dir=str(tmp_path / "x"))
        res = retriever.get_relevant("test")
        assert isinstance(res, list)

    def test_get_relevant_respects_k(self, index_dir, _embed_8, monkeypatch):
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir), k=2)
        assert retriever.rebuild()
        self._add_rows(5)
        assert retriever.rebuild()
        res = retriever.get_relevant("any")
        assert len(res) == 2

    def test_get_relevant_scores_are_floats(self, index_dir, _embed_8, monkeypatch):
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
        assert retriever.rebuild()
        self._add_rows(1)
        assert retriever.rebuild()
        _, _, score = retriever.get_relevant("world")[0]
        assert isinstance(score, float)
        # FAISS IP normalized: unit vectors -> dot product in [-1, 1] (can be negative)
        assert -1.0 <= score <= 1.0

    def test_clear_removes_persistence(self, index_dir, _embed_8, monkeypatch):
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
        assert retriever.rebuild()
        self._add_rows(1)
        assert retriever.rebuild()
        assert retriever.exists()
        retriever.clear()
        assert not retriever.exists()
        assert retriever.index is None


    def test_rebuild_load_clear_stale_does_not_deadlock(self, tmp_path, _embed_8, monkeypatch):
        # DC1 regression: rebuild_lock must be re-entrant (RLock). A reused
        # instance whose persisted meta diverges (provider mismatch) must not
        # deadlock the thread when rebuild() -> load() -> clear() happens.
        import json
        import os
        import threading

        index_dir = str(tmp_path / "idx")
        monkeypatch.setattr(memory_rag, "INDEX_DIR", index_dir)
        _patch_embeddings(monkeypatch, size=8, seed=1)
        import database

        r = memory_rag.MemoryRetriever()
        assert r.rebuild()
        assert r.index.ntotal == 0  # DB is empty

        database.add_user_memory("deadlock test a")
        database.add_user_memory("deadlock test b")
        assert r.rebuild()
        assert r.index.ntotal == 2

        meta_path = os.path.join(index_dir, "meta.json")
        meta = json.load(open(meta_path))
        meta["_provider"] = "gemini"  # active provider is 'openai' -> stale
        json.dump(meta, open(meta_path, "w"))

        result = {}
        def worker():
            try:
                r.rebuild()  # early-exit -> load() sees stale -> clear() -> done
                result["ok"] = True
            except Exception as e:
                result["err"] = repr(e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(3)
        assert not t.is_alive(), "deadlock: rebuild -> load -> clear blocked the thread"
        assert result.get("ok") is True

    def test_add_user_memory_skips_index_when_embeddings_unavailable(self, tmp_path, monkeypatch):
        # DC3: a rebuild cannot silently create an empty 1-dim index when
        # embeddings are broken; it must fail cleanly (hooks stay fail-safe).
        import os

        index_dir = str(tmp_path / "idx")
        monkeypatch.setattr(memory_rag, "INDEX_DIR", index_dir)
        import agent.lc.memory_rag as m
        import agent.lc.embeddings as emb

        monkeypatch.setattr(m, "get_embeddings", lambda: None)
        monkeypatch.setattr(emb, "get_embeddings", lambda: None)
        monkeypatch.setattr(m, "_dims_for_provider", lambda p: 8)

        import database

        # add_user_memory writes to DB but must NOT create an index.
        result = database.add_user_memory("no embeddings memory")
        assert result is not None
        assert not os.path.exists(os.path.join(index_dir, "index.faiss"))

    def test_load_rejects_stale_provider_index(self, tmp_path, _embed_8, monkeypatch):
        # DC5: a persisted index whose _provider diverges from the active one
        # must be rejected (not silently used / rebuilt).
        import json
        import os

        index_dir = str(tmp_path / "idx")
        monkeypatch.setattr(memory_rag, "INDEX_DIR", index_dir)
        _patch_embeddings(monkeypatch, size=8, seed=1)
        import database

        database.add_user_memory("stale provider memory")
        retriever = memory_rag.MemoryRetriever(index_dir=index_dir)
        assert retriever.rebuild()  # builds index, stores _provider="openai"

        meta_path = os.path.join(index_dir, "meta.json")
        meta = json.load(open(meta_path))
        meta["_provider"] = "gemini"
        json.dump(meta, open(meta_path, "w"))

        # A NEW instance must refuse to load it.
        fresh = memory_rag.MemoryRetriever(index_dir=index_dir)
        assert not fresh.load()
        assert fresh.index is None
        assert fresh.metadata == {}

class TestGetMemoryBlock:
    def test_get_memory_block_uses_rag_when_index_exists(self, tmp_path, _embed_8, mocker):
        index_dir = tmp_path / "lc_index_user_memory"
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        try:
            retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
            assert retriever.rebuild()
            import database

            database.add_user_memory("favorite color blue")
            database.add_user_memory("red cars")
            database.add_user_memory("coding with blue is great")
            retriever.rebuild()

            cursor = mocker.MagicMock()
            block = memory_rag.get_memory_block(cursor, query="what do i like")
            assert "favorite color blue" in block
            assert "(relevance" in block
        finally:
            monkeypatch.undo()

    def test_index_dir_isolation(self, tmp_path, _embed_8):
        # The DB hooks must never write outside the patched INDEX_DIR (B5).
        real_index = Path("files/lc_index/user_memory")
        real_files_before = (
            set(real_index.iterdir()) if real_index.exists() else set()
        )
        index_dir = tmp_path / "lc_index_user_memory"
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        try:
            _patch_embeddings(monkeypatch, size=8, seed=1)
            import database

            for inst in ("color blue", "car red", "book green"):
                database.add_user_memory(inst)
            assert set(real_index.iterdir()) == real_files_before, "production index dir was polluted"
            retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
            assert retriever.load()
            assert retriever.index.ntotal == 3
        finally:
            monkeypatch.undo()

    def test_get_memory_block_fallback_no_embeddings(self, tmp_path, mocker):
        retriever = memory_rag.MemoryRetriever(
            index_dir=str(tmp_path / "absent_index"))
        retriever.rebuild()

        import agent.lc.memory_rag as m
        import agent.lc.embeddings as emb

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(m, "embeddings_available", lambda: False)
        monkeypatch.setattr(emb, "embeddings_available", lambda: False)
        try:
            cursor = mocker.MagicMock()
            cursor.fetchall.return_value = [
                {"id": 1, "instruction": "legacy memory 1"},
                {"id": 2, "instruction": "legacy memory 2"}]
            block = memory_rag.get_memory_block(cursor, query="anything")
            assert "legacy memory 1" in block
            assert "legacy memory 2" in block
            assert "(relevance" not in block
        finally:
            monkeypatch.undo()

    def test_get_memory_block_fallback_no_index(self, tmp_path, mocker):
        import agent.lc.memory_rag as m
        import agent.lc.embeddings as emb

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(m, "embeddings_available", lambda: False)
        monkeypatch.setattr(emb, "embeddings_available", lambda: False)
        try:
            cursor = mocker.MagicMock()
            cursor.fetchall.return_value = [{"id": 42, "instruction": "fallback-only"}]
            block = memory_rag.get_memory_block(cursor, query="any")
            assert "fallback-only" in block
        finally:
            monkeypatch.undo()

    def test_get_memory_block_empty_no_memories(self, tmp_path, mocker):
        # No index and embeddings unavailable: get_memory_block returns the
        # empty block (B2). Isolate INDEX_DIR so a stray index from another
        # test cannot be reused.
        index_dir = tmp_path / "lc_index_user_memory"
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        monkeypatch.setattr(memory_rag, "embeddings_available", lambda: False)
        try:
            cursor = mocker.MagicMock()
            cursor.fetchall.return_value = []
            block = memory_rag.get_memory_block(cursor, query="any")
            assert block == ""
        finally:
            monkeypatch.undo()

    def test_get_memory_block_lazy_rebuilds_missing_index(self, tmp_path, _embed_8, mocker):
        # No persisted index but embeddings available + memories in DB:
        # get_memory_block rebuilds on demand before falling back to legacy (B4).
        index_dir = tmp_path / "lc_index_user_memory"
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        try:
            _patch_embeddings(monkeypatch, size=8, seed=1)
            import database

            # Mock the DB hook's upsert so the index is NOT created by the hooks
            # (otherwise the lazy path would never be exercised).
            with mocker.patch.object(memory_rag.MemoryRetriever, "upsert", return_value=True):
                database.add_user_memory("favorite color blue")
                database.add_user_memory("car red")

            # No index on disk -> get_memory_block must rebuild lazily.
            conn = database.get_db()
            cursor = conn.cursor()
            block = memory_rag.get_memory_block(cursor, query="what do i like")
            assert "(relevance" in block
            assert "favorite color blue" in block
            conn.close()
        finally:
            monkeypatch.undo()

    def test_get_memory_block_empty_query_returns_recent_by_id(self, tmp_path, _embed_8, mocker):
        # Regression for the empty-query ValueError: the recent-by-id branch must
        # return (mid, instr, 0.0) tuples that unpack cleanly, without crash.
        index_dir = tmp_path / "lc_index_user_memory"
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        try:
            _patch_embeddings(monkeypatch, size=8, seed=1)
            import database

            database.add_user_memory("z recent")
            database.add_user_memory("y mid")
            database.add_user_memory("x old")
            cursor = mocker.MagicMock()
            block = memory_rag.get_memory_block(cursor, query="")
            # Empty query -> most-recent-first with 0.0 scores, no crash.
            assert block != ""
            assert "(relevance 0.000)" in block
            assert "z recent" in block
            assert "x old" in block
            # IDs are returned in descending order (most recent first).
            assert block.index("x old") < block.index("z recent")
        finally:
            monkeypatch.undo()


class TestSettings:
    def test_embeddings_provider_default_is_auto(self):
        assert settings.embeddings_provider() == "auto"

    def test_env_override_embeddings_provider(self, monkeypatch):
        monkeypatch.setenv("LC_EMBEDDINGS_PROVIDER", "gemini")
        assert settings.embeddings_provider() == "gemini"
        monkeypatch.setenv("LC_EMBEDDINGS_PROVIDER", "openai")
        assert settings.embeddings_provider() == "openai"

    def test_invalid_embeddings_provider_warns_once(self, monkeypatch, mocker):
        monkeypatch.setenv("LC_EMBEDDINGS_PROVIDER", "banana")
        logger = mocker.patch.object(settings.logger, "warning")
        monkeypatch.setattr(settings, "_warned_embeddings_values", set())
        assert settings.embeddings_provider() == "auto"
        assert settings.embeddings_provider() == "auto"
        assert logger.call_count == 1

    def test_get_embeddings_model_names(self):
        assert settings.embeddings_model("gemini") == "models/text-embedding-004"
        assert settings.embeddings_model("openai") == "text-embedding-3-small"
        assert settings.embeddings_model() == "text-embedding-3-small"


class TestDatabaseHooks:
    def test_add_user_memory_succeeds_when_embeddings_unavailable(self, mocker):
        import agent.lc.memory_rag as m

        mocker.patch.object(m.MemoryRetriever, "upsert", side_effect=RuntimeError("no embeddings"))
        import database

        result = database.add_user_memory("This is a test instruction.")
        assert result is not None
        with database.get_db() as conn:
            rows = conn.execute("SELECT instruction FROM user_memory").fetchall()
        assert any(r[0] == "This is a test instruction." for r in rows)

    def test_add_user_memory_populates_index_when_embeddings_available(self, tmp_path):
        index_dir = tmp_path / "lc_index_user_memory"

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(index_dir))
        try:
            _patch_embeddings(monkeypatch, size=8, seed=1)
            try:
                import database

                database.add_user_memory("color blue")
                database.add_user_memory("car red")
                retriever = memory_rag.MemoryRetriever(index_dir=str(index_dir))
                assert retriever.rebuild()
                assert retriever.index.ntotal == 2
            finally:
                monkeypatch.undo()
        finally:
            monkeypatch.undo()

    def test_delete_user_memory_removes_from_index(self, mocker, tmp_path):
        import database

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(tmp_path / "idx"))
        try:
            _patch_embeddings(monkeypatch, size=8, seed=2)
            try:
                id1 = database.add_user_memory("one")
                id2 = database.add_user_memory("two")
                assert id2 == 2
                retriever = memory_rag.MemoryRetriever(index_dir=str(tmp_path / "idx"))
                retriever.rebuild()
                assert retriever.index.ntotal == 2
                assert database.delete_user_memory(id1) is True
                retriever.rebuild()
                assert retriever.index.ntotal == 1
            finally:
                monkeypatch.undo()
        finally:
            monkeypatch.undo()

    def test_update_user_memory_syncs_index(self, mocker, tmp_path):
        import database

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_rag, "INDEX_DIR", str(tmp_path / "idx"))
        try:
            _patch_embeddings(monkeypatch, size=8, seed=3)
            try:
                id1 = database.add_user_memory("old text")
                retriever = memory_rag.MemoryRetriever(index_dir=str(tmp_path / "idx"))
                retriever.rebuild()
                assert "old text" in retriever.metadata.values()
                assert database.update_user_memory(id1, "new text") is True
                retriever.rebuild()
                assert "new text" in retriever.metadata.values()
                assert "old text" not in retriever.metadata.values()
            finally:
                monkeypatch.undo()
        finally:
            monkeypatch.undo()
