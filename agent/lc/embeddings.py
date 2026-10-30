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
from typing import Optional

logger = logging.getLogger(__name__)

# Local embeddings: LangChain's HuggingFaceEmbeddings (sentence-transformers)
# running on this machine. Weights are cached under models/embeddings.
LOCAL_PROVIDER = "local"
LOCAL_MODEL = "all-MiniLM-L6-v2"
LOCAL_DIMS = 384
TOOL_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models", "embeddings")


# Serialises the cache so the model is loaded only once, even if
# get_embeddings is called concurrently (e.g. from many worker threads).
EMBEDDING_LOCK = threading.Lock()


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
    embedding work. A failed load is retried on the next call.
    """
    cache = get_embeddings.__dict__.setdefault("_cache", {})
    with EMBEDDING_LOCK:
        if model not in cache:
            try:
                cache[model] = _embedding_class()(
                    model_name=model, cache_folder=LOCAL_CACHE_DIR
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load local embeddings (%r); will retry next call: %s",
                    model,
                    exc,
                )
    return cache.get(model)


def embeddings_available() -> bool:
    """True if the local embedding model could be loaded."""
    return get_embeddings() is not None


def embeddings_model(provider: Optional[str] = None) -> str:
    """Embeddings model name (always the local model; ``provider`` is ignored)."""
    return LOCAL_MODEL
