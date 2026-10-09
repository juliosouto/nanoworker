"""LangChain integration layer (Fase 0+ do plano de migração LangChain).

Módulos desta fase:
    - settings: flags centralizadas da integração (LLM_STACK, LC_*)
    - tokens: contagem real de tokens (tiktoken) com fallback legado
    - embeddings: resolvedor de embeddings (Gemini/OpenAI)
    - memory_rag: retriever semântico de user_memory (FAISS)
    - tools_lc / outputs / prompts: suporte de tools, structured output, prompts
    - models / runner / cache: stack de execução LangChain (Fase 5)

``runner`` e ``cache`` são expostos por import lazy (PEP 562): importá-los de
forma eager aqui criaria um import circular, já que ``agent.lc.runner`` importa
``agent.openai_tools``, que por sua vez faz ``from agent.lc import settings``.
Assim, ``from agent.lc import settings`` continua leve e sem ciclos.
"""


from agent.lc.models import make_chat_model, resolve_provider
from agent.lc.settings import (
    cache_enabled,
    cache_path,
    keep_recent_messages,
    memory_top_k,
    stack_enabled,
    structured_output_mode,
    summarizer_model,
    summary_max_tokens,
    summary_threshold_pct,
    token_counter_mode,
    tool_compact_schema,
    tool_result_max_chars,
)
from agent.lc.tools_lc import (
    cap_tools,
    first_line_description,
    gemini_tool_declarations,
    lc_tool,
    tool_param_schema,
)
from agent.lc.tokens import count_tokens, truncate_tail

# Simbolos resolvidos de forma lazy para evitar o import circular descrito acima.
_LAZY_EXPORTS = {
    "run_langchain_llm": ("agent.lc.runner", "run_langchain_llm"),
    "maybe_init_cache": ("agent.lc.cache", "maybe_init_cache"),
}

__all__ = [
    "stack_enabled",
    "token_counter_mode",
    "memory_top_k",
    "tool_result_max_chars",
    "tool_compact_schema",
    "keep_recent_messages",
    "summarizer_model",
    "summary_threshold_pct",
    "summary_max_tokens",
    "structured_output_mode",
    "cache_enabled",
    "cache_path",
    "make_chat_model",
    "resolve_provider",
    "cap_tools",
    "first_line_description",
    "gemini_tool_declarations",
    "lc_tool",
    "tool_param_schema",
    "count_tokens",
    "truncate_tail",
    "run_langchain_llm",
    "maybe_init_cache",
]


def __getattr__(name):
    """PEP 562 lazy import for runner/cache symbols (avoids circular import)."""
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib

    module = importlib.import_module(module_name)
    value = getattr(module, attr)
    globals()[name] = value  # cache for subsequent lookups
    return value
