"""Embeddings provider resolution (Fase 2).

Decides which embedding model to use based on the ``llm_config`` table and the
``LC_EMBEDDINGS_PROVIDER`` flag, following the same "inspect the DB first, then
fall back gracefully" philosophy as the rest of agent.lc.

Providers:
    - Gemini ``text-embedding-004`` (preferred when an API key is configured)
    - OpenAI ``text-embedding-3-small`` (fallback)

Lazy imports of the LangChain embedding classes keep this module cheap to
import (no heavy libraries loaded unless an embedding is actually requested).
"""
import logging
import threading
from typing import Optional

from agent.lc.settings import embeddings_provider

logger = logging.getLogger(__name__)

# Serialises the cache so the API client is created only once, even if
# get_embeddings is called concurrently (e.g. from many worker threads).
EMBEDDING_LOCK = threading.Lock()


def _embedding_class_by_provider(provider: str):
    """Returns the LangChain embedding class for a provider (imported lazily)."""
    p = provider.lower()
    if p == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings
    if p == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings
    raise ValueError(f"Unsupported embeddings provider: {provider!r}")


def get_embeddings_provider() -> str:
    """Resolves the active embeddings provider (phase 2).

    Resolution order: explicit env/config value > auto-detect from llm_config
    > 'openai' as last resort (widely available).
    """
    explicit = embeddings_provider()
    if explicit != "auto":
        return explicit

    try:
        from database import get_db

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT provider, api_key FROM llm_config WHERE provider IS NOT NULL AND api_key IS NOT NULL LIMIT 1"
        )
        row = c.fetchone()
        conn.close()
        if row:
            provider = (row.get("provider") or "").strip().lower()
            if provider in ("gemini", "google"):
                return "gemini"
            if provider in ("openai", "groq", "openrouter", "qwen", "deepseek", "nvidia"):
                return "openai"  # OpenAI-compatible client works for embeddings too
    except Exception:
        pass

    logger.info("No embeddings provider configured; falling back to 'openai'")
    return "openai"


def get_embeddings() -> object:
    """Returns the active embedding instance, lazily created and cached."""
    provider = get_embeddings_provider()
    model = embeddings_model(provider)
    cls = _embedding_class_by_provider(provider)

    # Per-process cache so the API client is not recreated per call.
    # Only successful instances are cached: a failed creation is retried on
    # the next call (B3 fix — e.g. if the API key arrives after the first access).
    cache = get_embeddings.__dict__.setdefault("_cache", {})
    with EMBEDDING_LOCK:
        if provider not in cache:
            try:
                cache[provider] = cls(model=model)
            except Exception as exc:
                logger.warning(
                    "Failed to create %s embeddings (%r); will retry next call: %s",
                    provider,
                    model,
                    exc,
                )
                cache.pop(provider, None)
    return cache.get(provider)


def embeddings_available() -> bool:
    """True if an embedding client is usable (has a valid API key)."""
    return get_embeddings() is not None


def embeddings_model(provider: Optional[str] = None) -> str:
    """Embeddings model name for the given provider (phase 2).

    When ``provider`` is None or 'auto', resolves to the actual provider via
    ``embeddings_provider`` (auto-detect prefers Gemini, falls back to OpenAI).
    """
    p = (provider or embeddings_provider()).lower()
    if p == "auto":
        p = get_embeddings_provider().lower()
    if p == "gemini":
        return "models/text-embedding-004"
    if p == "openai":
        return "text-embedding-3-small"
    return ""