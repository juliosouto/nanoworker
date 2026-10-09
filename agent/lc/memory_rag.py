"""User-memory RAG retriever (Fase 2A).

Injects only the top-k most relevant user memories into the system prompt,
instead of the raw full text. The FAISS index is persisted under
``files/lc_index/user_memory`` and rebuilt from the database on every sync
(``upsert``/``remove``/``load`` mismatch), so it is always consistent with
the DB. Note that each memory write costs a full re-embedding of all memories
(N API calls per write); this is acceptable for the tens-of-memories scale
the app targets (see ``rebuild_index_all()`` for a manual build).

Fallback: if embeddings are unavailable or the index is missing,
``get_memory_block`` returns all memories (current legacy behavior), so there
is zero regression when the stack is first enabled.
"""
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np
import sqlite3
import threading

from agent.lc import settings
from agent.lc.embeddings import embeddings_available, get_embeddings, get_embeddings_provider

logger = logging.getLogger(__name__)

# Serialises rebuilds across threads (sweeper, message processing, etc.).
# RLock (re-entrant) so rebuild() -> load() -> clear() in the same thread
# does not deadlock.
rebuild_lock = threading.RLock()

INDEX_DIR = "files/lc_index/user_memory"
_EMBEDDING_DIMS = {"gemini": 768, "openai": 1536}


def _dims_for_provider(provider: str) -> int:
    """Embedding vector dimension for the provider."""
    p = (provider or settings.embeddings_provider()).lower()
    return _EMBEDDING_DIMS.get(p, 768)


class MemoryRetriever:
    """Retrieves the top-k user memories for a given query via FAISS."""

    def __init__(self, k: Optional[int] = None, index_dir: Optional[str] = None):
        self.k = k or settings.memory_top_k()
        self.index_dir = index_dir or INDEX_DIR
        self.index: Optional[faiss.Index] = None
        self.metadata: Dict[int, str] = {}
        # Resolve to the ACTIVE provider (auto > DB config > openai), not the raw flag.
        self.provider = get_embeddings_provider()
        self._initialized = False

    def exists(self) -> bool:
        """True when a persisted FAISS index is present."""
        return os.path.exists(os.path.join(self.index_dir, "index.faiss"))

    def load(self) -> bool:
        """Loads the persisted index and metadata. Returns True on success.

        If the persisted index was written with a different embedding provider
        or dimensionality than the active one (B3 fix), the index is stale and
        we force a rebuild instead.
        """
        if not self.exists() or not embeddings_available():
            return False
        try:
            self.index = faiss.read_index(os.path.join(self.index_dir, "index.faiss"))
            with open(os.path.join(self.index_dir, "meta.json"), "r") as fh:
                raw = json.load(fh)
            stored_provider = raw.get("_provider")
            stored_dims = raw.get("_dims")
            # Validate against the stored provider; for dimensionality compare
            # against the index loaded from disk (internal consistency) instead
            # of the static map (avoids N-embeds rebuilds every time if a model
            # ever diverges from the map).
            dims_match = stored_dims is None or stored_dims == self.index.d
            provider_match = stored_provider is None or stored_provider == self.provider
            if not (dims_match and provider_match):
                # Stale index: provider/dims diverge from the active config (B3).
                logger.info(
                    "Stale memory index detected: stored=%s, loaded_dims=%d, active=%s, rebuilding",
                    raw, self.index.d, self.provider,
                )
                self.clear()
                return False
            # Metadados ausentes = versão antiga do índice; confia nele
            # (o caminho de busca reconstrói se as dims divergirem).
            # JSON keys are always strings; convert back to int (memory ids),
            # but skip the _dims/_provider header.
            self.metadata = {int(k): v for k, v in raw.items() if not k.startswith("_")}
            self._initialized = True
            return True
        except Exception as exc:
            logger.warning("Failed to load memory index: %s", exc)
            self.index = None
            return False

    def _embed(self, texts: List[str]) -> np.ndarray:
        """Embeds a batch of texts; returns float32 numpy array."""
        emb = get_embeddings()
        if emb is None:
            # Embeddings not usable; let rebuild() catch this and return False.
            # (Hooks are fail-safe, so a write never fails.)
            raise ValueError("embeddings unavailable")
        return np.asarray(emb.embed_documents(texts), dtype=np.float32)

    def upsert(self, memory_id: int, instruction: str) -> bool:
        """Syncs the index to the DB after a memory was inserted/updated.

        NOTE: this performs a FULL rebuild (re-embeds ALL memories). For the
        tens-of-memories scale the app targets this keeps consistency simple;
        for very large memory stores use ``rebuild_index_all()`` instead.
        """
        try:
            return self.rebuild()
        except Exception as exc:
            logger.warning("Failed to sync memory %d into index: %s", memory_id, exc)
            return False

    def remove(self, memory_id: int) -> bool:
        """Syncs the index to the DB after a memory was deleted."""
        try:
            return self.rebuild()
        except Exception as exc:
            logger.warning("Failed to sync memory %d from index: %s", memory_id, exc)
            return False

    def rebuild(self, force: bool = False) -> bool:
        """Rebuilds the index from all user memories (used at boot / after hooks).

        On a reused instance the first call loads the persisted index; use
        ``rebuild(force=True)`` to force a full rebuild from the DB.
        """
        with rebuild_lock:
            try:
                os.makedirs(self.index_dir, exist_ok=True)

                from database import get_db

                if self.index is not None and not force:
                    if self.exists():
                        return self.load()
                conn = get_db()
                c = conn.cursor()
                try:
                    c.execute("SELECT id, instruction FROM user_memory ORDER BY id")
                    rows = c.fetchall()
                except sqlite3.OperationalError:
                    # user_memory table not created yet (e.g. fresh DB in tests):
                    # treat as empty, same as the legacy get_all_user_memories path.
                    rows = []
                conn.close()

                logger.debug("rebuild DB rows=%d", len(rows))

                if not rows:
                    # Persist an empty, ready-to-use index (same structure as a
                    # populated one), so `exists()` is truthful and the first
                    # real rebuild re-creates it with the right dimensionality.
                    dims = _dims_for_provider(self.provider) or 768
                    self.index = faiss.IndexFlatIP(dims)
                    self.metadata = {}
                    faiss.write_index(self.index, os.path.join(self.index_dir, "index.faiss"))
                    with open(os.path.join(self.index_dir, "meta.json"), "w") as fh:
                        json.dump({"_dims": dims, "_provider": self.provider}, fh)
                    self._initialized = True
                    return True

                texts = [r["instruction"] for r in rows]
                ids = [int(r["id"]) for r in rows]
                vectors = self._embed(texts)
                # Derive the actual vector dimensionality from the embedding call;
                # if unavailable, fall back to the static map (B1 fix).
                dims = vectors.shape[1] or _dims_for_provider(self.provider)
                vectors = vectors.reshape(len(vectors), dims)
                faiss.normalize_L2(vectors)

                self.index = faiss.IndexFlatIP(dims)
                self.index.add(vectors.astype(np.float32))
                self.metadata = dict(zip(ids, texts))
                os.makedirs(self.index_dir, exist_ok=True)
                faiss.write_index(self.index, os.path.join(self.index_dir, "index.faiss"))
                with open(os.path.join(self.index_dir, "meta.json"), "w") as fh:
                    json.dump({"_dims": dims, "_provider": self.provider, **self.metadata}, fh)
                self._initialized = True
                logger.info(
                    "Memory index rebuilt: %d memories (%s provider, %d dims)",
                    len(rows),
                    self.provider,
                    dims,
                )
                logger.debug("rebuild done index_dir=%s ntotal=%d", self.index_dir, self.index.ntotal)
                return True
            except Exception as exc:
                logger.warning("Failed to rebuild memory index: %s", exc)
                self.index = None
                self.metadata = {}
                self._initialized = False
                return False

    def get_relevant(self, query: str, k: Optional[int] = None) -> List[Tuple[int, str, float]]:
        """Returns the k most relevant memories (id, instruction, score)."""
        k = k or self.k
        if self.index is None or not self._initialized:
            if not self.rebuild():
                return []
        if self.index.ntotal == 0:
            return []
        if not query.strip():
            # No meaningful query: return the k most recent memories (by id).
            return [
                (mid, instr, 0.0)
                for mid, instr in sorted(self.metadata.items(), key=lambda kv: -kv[0])[:k]
            ]
        try:
            qvec = self._embed([query]).reshape(1, -1)
            faiss.normalize_L2(qvec)
            scores, _ = self.index.search(qvec, min(k, self.index.ntotal))
            results = []
            keys = list(self.metadata.keys())
            for score, vid in zip(scores[0], range(len(scores[0]))):
                if vid < 0 or vid >= len(keys):
                    continue
                results.append((keys[vid], self.metadata[keys[vid]], float(scores[0][vid])))
            return results
        except Exception as exc:
            logger.warning("Failed to search memory index for query %r; rebuilding once: %s", query, exc)
            # Likely a stale index (B3): rebuild(force=True) bypasses the
            # stale load, rebuilds from the DB, and retries the search.
            # Retried at most once to avoid an infinite loop of N embeddings.
            if not getattr(self, "_search_retried", False):
                self._search_retried = True
                try:
                    if self.rebuild(force=True):
                        return self.get_relevant(query)
                finally:
                    self._search_retried = False
            return []

    def clear(self) -> None:
        """Removes the persisted index (forces rebuild on next use)."""
        with rebuild_lock:
            try:
                if os.path.exists(os.path.join(self.index_dir, "index.faiss")):
                    os.remove(os.path.join(self.index_dir, "index.faiss"))
                if os.path.exists(os.path.join(self.index_dir, "meta.json")):
                    os.remove(os.path.join(self.index_dir, "meta.json"))
            except Exception:
                pass
            self.index = None
            self.metadata = {}
            self._initialized = False


# Module-level helper used by the prompt builder (Fase 1):
# returns the top-k relevant memory block, or all memories as fallback.
def get_memory_block(cursor, query: str = "") -> str:
    """Returns the top-k relevant user memory block for the given query.

    If embeddings are unavailable or no persisted index exists, falls back
    to injecting ALL memories (the legacy behaviour).
    """
    try:
        retriever = MemoryRetriever()
        # Embeddings unavailable -> legacy injection of all memories (no API call).
        if not embeddings_available():
            cursor.execute("SELECT id, instruction FROM user_memory")
            memories = cursor.fetchall()
            if memories:
                return "User Memory / Persistent Instructions:\n" + "\n".join(
                    f"[ID: {r['id']}] {r['instruction']}" for r in memories
                )
            return ""

        if not retriever.exists():
            # Lazy, on-demand rebuild when the index is missing but memories
            # exist in the DB (B4): build the index before deciding on legacy.
            c = cursor
            c.execute("SELECT COUNT(*) FROM user_memory")
            if c.fetchone()[0] > 0:
                if retriever.rebuild():
                    relevants = retriever.get_relevant(query)
                    if relevants:
                        return "User Memory / Persistent Instructions (most relevant):\n" + "\n".join(
                            f"[ID: {mid}] {instr} (relevance {score:.3f})" for mid, instr, score in relevants
                        )
            # No index, no memories, or rebuild failed -> legacy injection.
            cursor.execute("SELECT id, instruction FROM user_memory")
            memories = cursor.fetchall()
            if memories:
                return "User Memory / Persistent Instructions:\n" + "\n".join(
                    f"[ID: {r['id']}] {r['instruction']}" for r in memories
                )
            return ""

        if not retriever.load():
            if not retriever.rebuild():
                raise RuntimeError("index load failed")
        relevants = retriever.get_relevant(query)
        if relevants:
            return "User Memory / Persistent Instructions (most relevant):\n" + "\n".join(
                f"[ID: {mid}] {instr} (relevance {score:.3f})" for mid, instr, score in relevants
            )
        # Search returned nothing but we have memories -> stale index; rebuild once.
        if retriever.metadata:
            try:
                if retriever.rebuild():
                    relevants = retriever.get_relevant(query)
                    if relevants:
                        return "User Memory / Persistent Instructions (most relevant):\n" + "\n".join(
                            f"[ID: {mid}] {instr} (relevance {score:.3f})" for mid, instr, score in relevants
                        )
            except Exception:
                pass
        return ""
    except Exception as exc:
        logger.warning("Memory RAG failed (%r); falling back to legacy injection: %s", exc, exc)
        try:
            cursor.execute("SELECT id, instruction FROM user_memory")
            memories = cursor.fetchall()
            if memories:
                return "User Memory / Persistent Instructions:\n" + "\n".join(
                    f"[ID: {r['id']}] {r['instruction']}" for r in memories
                )
        except sqlite3.OperationalError:
            # user_memory table missing (e.g. partially migrated DB): same as
            # the legacy behaviour — return an empty block.
            pass
        return ""


def rebuild_index_all() -> bool:
    """Public helper to rebuild the index from the DB (e.g. from a shell command)."""
    retriever = MemoryRetriever()
    return retriever.rebuild()