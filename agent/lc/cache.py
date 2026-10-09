"""Optional LangChain SQLite LLM cache (phase 5).

When ``LC_CACHE=true``, identical LLM prompts skip the provider call by hitting
a ``SQLiteCache``. The cache is installed once per process via
``set_llm_cache`` (a langchain-core global), so it affects *every* chat model in
the process — which is exactly why it is off by default.

Import-time and early-startup paths never break: the ``langchain_community``
SQLiteCache / ``set_llm_cache`` imports are deferred to call time.
"""

import logging
import threading

from agent.lc import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_initialized = False


def maybe_init_cache() -> bool:
    """Install the SQLite LLM cache when LC_CACHE=true.

    Idempotent and thread-safe: the first call with caching enabled installs the
    process-global ``SQLiteCache``; subsequent calls are no-ops. When
    ``LC_CACHE=false`` (default) this is a pure no-op and never imports
    langchain_community.

    Returns:
        bool: True if the cache is (now) installed, False otherwise.
    """
    global _initialized
    if not settings.cache_enabled():
        return False
    with _lock:
        if _initialized:
            return True
        from langchain_community.cache import SQLiteCache
        from langchain_core.globals import set_llm_cache

        set_llm_cache(SQLiteCache(database_path=settings.cache_path()))
        _initialized = True
        logger.info("LangChain SQLite LLM cache enabled at %s", settings.cache_path())
        return True
