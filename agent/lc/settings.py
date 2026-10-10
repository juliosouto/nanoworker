"""Central configuration for the LangChain integration (agent.lc).

All flags live in the ``app_config`` table (SQLite) and can be set per
install via ``database.set_config`` or exported through ``.env`` (which is
migrated to app_config on first boot).

Keys:
    LLM_STACK              'langchain' (default since Fase 6) | 'legacy'
                           Selects the LLM execution stack. 'legacy' keeps the
                           pre-LangChain provider loops (rollback hatch, kept
                           for one release).
    LC_TOKEN_COUNTER       'tiktoken' (default, real BPE counting) | 'heuristic'
                           'heuristic' restores the legacy 1 token ~= 4 chars math.
    LC_MEMORY_TOP_K        int (default 5)      - phase 2: RAG memories injected.
    LC_TOOL_RESULT_MAX_CHARS int (default 6000) - phase 4: tool result cap.
    LC_TOOL_COMPACT_SCHEMA 'on' (default) | 'off' - phase 4: use compact tool
                           schemas (first-line descriptions; biggest win in the
                           Gemini loop, which otherwise pulls the full docstring).
    LC_KEEP_RECENT_MSGS    int (default 8)      - phase 3: verbatim recent messages.
    LC_SUMMARIZER_MODEL    str (default "")     - phase 3: cheap model used to
                           summarize old conversation blocks. "" -> summarization
                           disabled; behavior falls back to the legacy slicer.
    LC_SUMMARY_THRESHOLD_PCT int (default 80)   - phase 3: when the estimated
                           conversation is over this % of MESSAGE_SLICE_SIZE_TOKENS,
                           an old block is summarized; below it the path is cheap.
    LC_SUMMARY_MAX_TOKENS  int (default 200)    - phase 3: token cap for each
                           auto-generated summary block.
    LC_CACHE               'false' (default) | 'true' - phase 5: enable the
                           LangChain SQLite LLM cache (SQLiteCache) so identical
                           prompts skip the provider call. Off by default because
                           set_llm_cache installs a process-global cache that
                           affects every BaseChatModel.invoke.
    LC_CACHE_PATH          str (default "llm_cache.sqlite") - phase 5: file used
                           by the SQLite LLM cache when LC_CACHE=true.

Every reader degrades to its default when the config table is unavailable,
so import-time and early-startup paths never break.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_VALID_STACKS = ("legacy", "langchain")
_VALID_COUNTERS = ("tiktoken", "heuristic")
_VALID_STRUCTURED = ("auto", "off")
_VALID_EMBEDDINGS = ("auto", "gemini", "openai")
_VALID_COMPACT = ("on", "off")

# Values that already triggered the "unknown" warning, so a
# misconfigured/mocked value is reported once per process, not per call.
_warned_counter_values = set()
_warned_stack_values = set()
_warned_structured_values = set()
_warned_embeddings_values = set()
_warned_compact_values = set()


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
    """True when the LangChain execution stack is active (Fase 6 default).

    Default is 'langchain' since Fase 6; an explicit ``LLM_STACK=legacy``
    keeps the pre-LangChain provider loops (kept for one release as a
    rollback hatch). Unknown values are warned once per unique value and
    fall back to the conservative legacy behaviour.
    """
    raw = os.environ.get("LLM_STACK") or _cfg("LLM_STACK", "langchain")
    value = str(raw).strip().lower()
    if value not in _VALID_STACKS:
        if raw not in _warned_stack_values:
            _warned_stack_values.add(raw)
            logger.warning("Unknown LLM_STACK=%r; using 'legacy'", raw)
        return False
    return value == "langchain"


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


def tool_compact_schema() -> bool:
    """Use compact tool schemas (phase 4).

    When on, tool descriptions use only the first line of the docstring,
    shrinking the tool payload sent to the LLM; the biggest win is in the
    Gemini loop, which otherwise pulls the full docstring as description.
    The setting is a pure win (never a loss), so unknown values are warned
    once per unique value and treated as 'on'; legacy behaviour is kept only
    when the setting is explicitly toggled off.
    """
    raw = os.environ.get("LC_TOOL_COMPACT_SCHEMA") or _cfg(
        "LC_TOOL_COMPACT_SCHEMA", "on"
    )
    value = str(raw).strip().lower()
    if value not in _VALID_COMPACT:
        if raw not in _warned_compact_values:
            _warned_compact_values.add(raw)
            logger.warning("Unknown LC_TOOL_COMPACT_SCHEMA=%r; using 'on'", raw)
        return True
    return value == "on"


def tool_relevance_filter() -> bool:
    """True when the opt-in LangChain tool-relevance filter is active.

    When enabled, a lightweight LLM call narrows the permitted tool set to the
    tools likely needed by the user's message before the main provider call
    (saves tokens and reduces tool confusion for small models). Default is OFF
    ('false'): all permitted tools are sent, exactly as before. The filter is
    fail-open — any error keeps the full tool set.
    """
    raw = os.environ.get("TOOL_RELEVANCE_FILTER") or _cfg(
        "TOOL_RELEVANCE_FILTER", "false"
    )
    return str(raw).strip().lower() == "true"


def memory_top_k() -> int:
    """How many user memories are injected via RAG (phase 2)."""
    return _cfg_int("LC_MEMORY_TOP_K", 5, 1)


def tool_result_max_chars() -> int:
    """Character cap applied to tool results (phase 4)."""
    return _cfg_int("LC_TOOL_RESULT_MAX_CHARS", 6000, 0)


def keep_recent_messages() -> int:
    """Recent history messages kept verbatim during summarization (phase 3)."""
    return _cfg_int("LC_KEEP_RECENT_MSGS", 8, 1)


def summarizer_model() -> str:
    """Model used to summarize old conversation blocks (phase 3).

    Resolution order: env LC_SUMMARIZER_MODEL > app_config > default (empty).
    An empty name disables summarization entirely and the legacy slicer is used
    instead, so this is a zero-risk feature toggle.
    """
    raw = os.environ.get("LC_SUMMARIZER_MODEL") or _cfg("LC_SUMMARIZER_MODEL", "")
    return str(raw).strip()


def summary_threshold_pct() -> int:
    """Percentage of the MESSAGE_SLICE_SIZE_TOKENS budget above which an old
    conversation block is summarized (phase 3)."""
    return _cfg_int("LC_SUMMARY_THRESHOLD_PCT", 80, 10)


def summary_max_tokens() -> int:
    """Token cap applied to each auto-generated summary block (phase 3)."""
    return _cfg_int("LC_SUMMARY_MAX_TOKENS", 200, 16)


def embeddings_provider() -> str:
    """Phase 2: embeddings provider used by the RAG retrievers.

    Resolution order: env LC_EMBEDDINGS_PROVIDER > app_config > auto-detect.
    'auto' inspects llm_config and picks the cheapest available provider
    (Gemini preferred, OpenAI as fallback). Unknown values are warned once per
    unique value and treated as 'auto'.
    """
    raw = os.environ.get("LC_EMBEDDINGS_PROVIDER") or _cfg(
        "LC_EMBEDDINGS_PROVIDER", "auto"
    )
    mode = str(raw).strip().lower()
    if mode not in ("auto", "gemini", "openai"):
        if raw not in _warned_embeddings_values:
            _warned_embeddings_values.add(raw)
            logger.warning("Unknown LC_EMBEDDINGS_PROVIDER=%r; using 'auto'", raw)
        return "auto"
    return mode


def embeddings_model(provider: Optional[str] = None) -> str:
    """Embeddings model name for the given provider (phase 2).

    Delegates to ``agent.lc.embeddings.embeddings_model`` (single source of
    truth for provider/model mapping).
    """
    from agent.lc import embeddings as _lc_embed

    return _lc_embed.embeddings_model(provider)


def structured_output_mode() -> str:
    """Phase 1: 'auto' (native structured output when supported) or 'off'
    (always keep the prose JSON-schema block in the system prompt).

    Unknown values are warned once per unique value and treated as 'auto'.
    """
    raw = os.environ.get("LC_STRUCTURED_OUTPUT") or _cfg("LC_STRUCTURED_OUTPUT", "auto")
    mode = str(raw).strip().lower()
    if mode not in _VALID_STRUCTURED:
        if raw not in _warned_structured_values:
            _warned_structured_values.add(raw)
            logger.warning("Unknown LC_STRUCTURED_OUTPUT=%r; using 'auto'", raw)
        return "auto"
    return mode


def cache_enabled() -> bool:
    """Phase 5: enable the LangChain SQLite LLM cache.

    Off by default: ``set_llm_cache`` installs a process-global cache that
    affects every ``BaseChatModel.invoke`` (including the legacy stack if it
    ever adopts chat models), so it must be an explicit opt-in. Only the
    literal value 'true' (case-insensitive) enables it; everything else is
    treated as 'false'.
    """
    raw = os.environ.get("LC_CACHE") or _cfg("LC_CACHE", "false")
    return str(raw).strip().lower() == "true"


def cache_path() -> str:
    """Phase 5: file used by the SQLite LLM cache when LC_CACHE=true.

    Resolution order: env LC_CACHE_PATH > app_config > default
    ('llm_cache.sqlite', created in the current working directory).
    """
    raw = os.environ.get("LC_CACHE_PATH") or _cfg("LC_CACHE_PATH", "llm_cache.sqlite")
    path = str(raw).strip()
    return path or "llm_cache.sqlite"
