"""Central configuration for the LangChain integration (agent.lc).

All flags live in the ``app_config`` table (SQLite) and can be set per
install via ``database.set_config`` or exported through ``.env`` (which is
migrated to app_config on first boot).

Keys:
    LLM_STACK            'legacy' (default) | 'langchain'
                         Selects the LLM execution stack. Phase 0 only
                         defines the flag; later phases switch code paths.
    LC_TOKEN_COUNTER     'tiktoken' (default, real BPE counting) | 'heuristic'
                         'heuristic' restores the legacy 1 token ~= 4 chars math.
    LC_MEMORY_TOP_K      int (default 5)   - phase 2: RAG memories injected.
    LC_TOOL_RESULT_MAX_CHARS int (default 6000) - phase 4: tool result cap.
    LC_KEEP_RECENT_MSGS  int (default 8)   - phase 3: verbatim recent messages.

Every reader degrades to its default when the config table is unavailable,
so import-time and early-startup paths never break.
"""
import logging
import os

logger = logging.getLogger(__name__)

_VALID_STACKS = ("legacy", "langchain")
_VALID_COUNTERS = ("tiktoken", "heuristic")

# Values that already triggered the "unknown counter" warning, so a
# misconfigured/mocked value is reported once per process, not per call.
_warned_counter_values = set()


def _cfg(key, default=None):
    """Reads an app_config value, returning `default` on any failure."""
    try:
        from database import get_config
        value = get_config(key, None)
    except Exception:
        return default
    if value is None or value == "":
        return default
    return value


def _cfg_int(key, default, minimum):
    """Integer setting with env override > app_config > default fallback.

    Invalid or out-of-range values fall back to `default`.
    """
    raw = os.environ.get(key) or _cfg(key, None)
    if raw is None or raw == "":
        return default
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        return default


def stack_enabled() -> bool:
    """True when LLM_STACK is explicitly set to 'langchain'."""
    raw = os.environ.get("LLM_STACK") or _cfg("LLM_STACK", "legacy")
    return str(raw).strip().lower() == "langchain"


def token_counter_mode() -> str:
    """Active token counter: 'tiktoken' (real) or 'heuristic' (legacy).

    Resolution order: env LC_TOKEN_COUNTER > app_config > default.
    Unknown values fall back to 'tiktoken' (the default), warned once per
    unique value to avoid log spam in hot paths.
    """
    raw = os.environ.get("LC_TOKEN_COUNTER") or _cfg("LC_TOKEN_COUNTER", "tiktoken")
    mode = str(raw).strip().lower()
    if mode not in _VALID_COUNTERS:
        if mode != "tiktoken" and raw not in _warned_counter_values:
            _warned_counter_values.add(raw)
            logger.warning("Unknown LC_TOKEN_COUNTER=%r; using 'tiktoken'", raw)
        return "tiktoken"
    return mode


def memory_top_k() -> int:
    """How many user memories are injected via RAG (phase 2)."""
    return _cfg_int("LC_MEMORY_TOP_K", 5, 1)


def tool_result_max_chars() -> int:
    """Character cap applied to tool results (phase 4)."""
    return _cfg_int("LC_TOOL_RESULT_MAX_CHARS", 6000, 0)


def keep_recent_messages() -> int:
    """Recent history messages kept verbatim during summarization (phase 3)."""
    return _cfg_int("LC_KEEP_RECENT_MSGS", 8, 1)
