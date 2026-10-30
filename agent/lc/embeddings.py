"""Embeddings for the LangChain RAG stack (Fase 2).

Embeddings are always computed locally with LangChain's
``HuggingFaceEmbeddings``, independent of which chat provider each worker uses.
No API key and no network calls once the weights are cached under
``models/embeddings``. Two models are used:

    * ``all-MiniLM-L6-v2`` (default): message history RAG;
    * ``paraphrase-multilingual-MiniLM-L12-v2`` (``TOOL_MODEL``): tool RAG,
      which matches Portuguese messages against English tool descriptions.

The LangChain embedding class is imported lazily to keep this module cheap to
import (no heavy libraries loaded unless an embedding is actually requested).
"""
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Local embeddings: LangChain's HuggingFaceEmbeddings (sentence-transformers)
# running on this machine. Weights are cached under models/embeddings.
LOCAL_PROVIDER = "local"
LOCAL_MODEL = "all-MiniLM-L6-v2"
LOCAL_DIMS = 384
TOOL_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models", "embeddings")


# One lock per model: each model is loaded only once even under concurrent
# calls, and downloading one model (the tool model is ~470 MB) never blocks
# callers of the other (e.g. history vectorization in the webhook).
EMBEDDING_LOCK = threading.Lock()  # guards _MODEL_LOCKS
_MODEL_LOCKS = {}

# After a failed load, wait this long before trying again, so a missing
# download (no network, full disk) does not stall every message.
LOAD_RETRY_SECONDS = 300
_FAILED_AT = {}


def _model_lock(model: str) -> threading.Lock:
    with EMBEDDING_LOCK:
        return _MODEL_LOCKS.setdefault(model, threading.Lock())


def _embedding_class():
    """Returns LangChain's HuggingFaceEmbeddings class (imported lazily)."""
    from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings


def get_embeddings_provider() -> str:
    """The embeddings provider: always 'local'."""
    return LOCAL_PROVIDER


def get_embeddings(model: str = LOCAL_MODEL) -> object:
    """Returns the local embedding instance for ``model``, lazily created and
    cached per model.

    Returns None when the model cannot be loaded; the caller then skips
    embedding work. A failed load is retried after ``LOAD_RETRY_SECONDS``.
    """
    cache = get_embeddings.__dict__.setdefault("_cache", {})
    if model in cache:
        return cache[model]
    with _model_lock(model):
        if model in cache:
            return cache[model]
        failed_at = _FAILED_AT.get(model)
        if failed_at is not None and time.monotonic() - failed_at < LOAD_RETRY_SECONDS:
            return None
        try:
            cache[model] = _embedding_class()(
                model_name=model, cache_folder=LOCAL_CACHE_DIR
            )
            _FAILED_AT.pop(model, None)
        except Exception as exc:
            _FAILED_AT[model] = time.monotonic()
            logger.warning(
                "Failed to load local embeddings (%r); retrying in %ds: %s",
                model,
                LOAD_RETRY_SECONDS,
                exc,
            )
    return cache.get(model)


def warm_up() -> None:
    """Loads the embedding models in use, so the first message does not wait
    for a download. Meant for a background thread at boot."""
    from agent.lc import settings as lc_settings

    get_embeddings(LOCAL_MODEL)
    if lc_settings.tool_relevance_filter():
        get_embeddings(TOOL_MODEL)


def embeddings_available() -> bool:
    """True if the local embedding model could be loaded."""
    return get_embeddings() is not None


def embeddings_model(provider: Optional[str] = None) -> str:
    """Embeddings model name (always the local model; ``provider`` is ignored)."""
    return LOCAL_MODEL
