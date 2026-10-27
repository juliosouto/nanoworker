"""Embeddings provider resolution (Fase 2).

Decides which embedding model to use based on the ``llm_config`` table and the
``LC_EMBEDDINGS_PROVIDER`` flag, following the same "inspect the DB first, then
fall back gracefully" philosophy as the rest of agent.lc.

Providers:
    - ``local`` (default): LangChain ``HuggingFaceEmbeddings`` with
      ``all-MiniLM-L6-v2``, computed on this machine. No API key and no
      network calls once the weights are cached under ``models/embeddings``.
    - Gemini ``text-embedding-004`` and OpenAI ``text-embedding-3-small``: cloud
      providers, used only when explicitly selected with LC_EMBEDDINGS_PROVIDER.

Lazy imports of the LangChain embedding classes keep this module cheap to
import (no heavy libraries loaded unless an embedding is actually requested).
"""
import logging
import os
import threading
from typing import Optional

from agent.lc.settings import embeddings_provider

logger = logging.getLogger(__name__)

# Local embeddings: LangChain's HuggingFaceEmbeddings (sentence-transformers)
# running on this machine. Weights are cached under models/embeddings.
LOCAL_MODEL = "all-MiniLM-L6-v2"
LOCAL_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models", "embeddings")


# Serialises the cache so the API client is created only once, even if
# get_embeddings is called concurrently (e.g. from many worker threads).
EMBEDDING_LOCK = threading.Lock()


def _embedding_class_by_provider(provider: str):
    """Returns the LangChain embedding class for a provider (imported lazily)."""
    p = provider.lower()
    if p == "local":
        from langchain_community.embeddings import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings
    if p == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings
    if p == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings
    raise ValueError(f"Unsupported embeddings provider: {provider!r}")


def _llm_api_key(providers) -> Optional[str]:
    """Decrypted API key of the first llm_config row for one of ``providers``."""
    try:
        from database import decrypt_value, get_db

        conn = get_db()
        try:
            c = conn.cursor()
            placeholders = ",".join("?" * len(providers))
            c.execute(
                f"SELECT api_key FROM llm_config WHERE lower(provider) IN ({placeholders}) "
                "AND api_key IS NOT NULL AND api_key != '' LIMIT 1",
                list(providers),
            )
            row = c.fetchone()
        finally:
            conn.close()
        return decrypt_value(row["api_key"]) if row else None
    except Exception:
        return None


def _embedding_api_key(provider: str) -> Optional[str]:
    """Credential for an embeddings provider, taken from the keys the app already
    stores (llm_config, then the Gemini key in app_config). No environment
    variables are read, so the embedding stack depends only on the app config."""
    if provider == "gemini":
        key = _llm_api_key(("gemini", "google"))
        if not key:
            try:
                from database import get_config

                key = get_config("GEMINI_API_KEY", None)
            except Exception:
                key = None
        return key or None
    if provider == "openai":
        return _llm_api_key(("openai",)) or None
    return None


def get_embeddings_provider() -> str:
    """Resolves the active embeddings provider.

    Resolution order: explicit env/config value > 'local'. Cloud providers are
    never picked automatically, so the default stack sends no data out.
    """
    explicit = embeddings_provider()
    if explicit != "auto":
        return explicit
    return "local"


_missing_credential_warned = False


def _warn_missing_credential_once(provider: str) -> None:
    global _missing_credential_warned
    if _missing_credential_warned:
        return
    _missing_credential_warned = True
    logger.warning(
        "No %s API key found for embeddings (llm_config%s); message vectorization is disabled "
        "until one is saved in the LLM settings.",
        provider,
        " or app_config GEMINI_API_KEY" if provider == "gemini" else "",
    )


def get_embeddings() -> object:
    """Returns the active embedding instance, lazily created and cached.

    Returns None when the provider has no stored credential or the client
    cannot be created; the caller then skips embedding work.
    """
    provider = get_embeddings_provider()
    model = embeddings_model(provider)

    # Per-process cache so the model or client is not recreated per call.
    # Only successful instances are cached: a failed creation is retried on
    # the next call.
    cache = get_embeddings.__dict__.setdefault("_cache", {})
    with EMBEDDING_LOCK:
        if provider not in cache:
            kwargs = {"model": model}
            if provider == "local":
                kwargs = {"model_name": model, "cache_folder": LOCAL_CACHE_DIR}
            else:
                api_key = _embedding_api_key(provider)
                if not api_key:
                    _warn_missing_credential_once(provider)
                    return None
                kwargs["google_api_key" if provider == "gemini" else "api_key"] = api_key
            try:
                cache[provider] = _embedding_class_by_provider(provider)(**kwargs)
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
    if p == "local":
        return LOCAL_MODEL
    if p == "gemini":
        return "models/text-embedding-004"
    if p == "openai":
        return "text-embedding-3-small"
    return ""