"""LangChain integration layer (Fase 0+ do plano de migração LangChain).

Módulos desta fase:
    - settings: flags centralizadas da integração (LLM_STACK, LC_*)
    - tokens: contagem real de tokens (tiktoken) com fallback legado

Módulos das fases seguintes (prompts, outputs, RAG, runner) serão
adicionados aqui conforme a migração avança.
"""

from agent.lc.settings import (
    keep_recent_messages,
    memory_top_k,
    stack_enabled,
    token_counter_mode,
    tool_result_max_chars,
)
from agent.lc.tokens import count_tokens, truncate_tail

__all__ = [
    "stack_enabled",
    "token_counter_mode",
    "memory_top_k",
    "tool_result_max_chars",
    "keep_recent_messages",
    "count_tokens",
    "truncate_tail",
]
