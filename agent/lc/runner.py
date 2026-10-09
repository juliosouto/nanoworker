"""LangChain execution runner (phase 5) — unifies the two legacy LLM loops.

``run_langchain_llm`` builds a single tool-calling agent (``create_tool_calling_
agent`` + ``AgentExecutor`` from ``langchain_classic.agents``) on top of the chat
model produced by :mod:`agent.lc.models`, and reproduces the real-time feedback
(⚙️ Executing / ⚙️ Executed, ⏳ rate-limit waits) that the legacy Gemini and
OpenAI-compatible loops emit inline.

Design notes:
    * The 📋 Execution Plan / 🔄 Agent reflecting feedback and the AgentResponse
      parsing live in ``autonomous_loop`` *above* this runner, so they are
      untouched here.
    * Transient 429 / 402 errors are retried with the *same* helpers used by
      ``agent.openai_tools`` so the wait feedback and back-off are identical.
    * ``/stop`` propagates as ``StopRequestedError``: the callback checks the
      stop flag before each tool, and an exception raised inside a tool bubbles
      straight out of ``AgentExecutor.invoke`` (validated in the test suite).

Import of the concrete LangChain pieces is deferred to call time so the worker
boots fast and importing this module never requires the optional packages.
"""

import logging
from typing import Optional

from agent.lc import cache as lc_cache
from agent.lc import models as lc_models
from agent.lc.tools_lc import build_lc_tools
from agent.stop_check import StopRequestedError, is_stop_requested, sleep_interruptible
from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class FeedbackCallbackHandler(BaseCallbackHandler):
    """Reproduces the legacy ⚙️ tool feedback and the fail-fast /stop check.

    Inherits ``BaseCallbackHandler`` so every unhandled LangChain callback hook
    is a safe no-op; only the tool hooks are overridden. Tool events fire because
    the handler is passed via ``invoke(..., config={'callbacks': [...]})``.
    """

    def __init__(self, cursor, table, session_id, message_in_id, show_tools_results,
                 on_complete=None):
        super().__init__()
        self.raise_error = True  # let StopRequestedError from hooks propagate
        self._cursor = cursor
        self._table = table
        self._session_id = session_id
        self._message_in_id = message_in_id
        self._show_tools_results = show_tools_results
        self._on_complete = on_complete
        # Fase 6: usage accounting. Accumulated across every LLM call the agent
        # performs in this turn (loop iterations + retries); agents report a
        # separate usage_metadata per call, and the dashboard aggregates.
        self.usage_input_tokens = 0
        self.usage_output_tokens = 0
        self.usage_calls = 0

    # -- helpers ---------------------------------------------------------
    def _feedback(self, text: str) -> None:
        from agent.db_feedback import insert_feedback

        insert_feedback(
            self._cursor, self._table, self._session_id, self._message_in_id, text
        )

    # -- LangChain callback hooks ---------------------------------------
    def on_tool_start(self, serialized, input_str=None, **kwargs) -> None:
        name = kwargs.get("name") or (serialized or {}).get("name") or "tool"
        # Fail-fast /stop: abort between tools within ~1s instead of waiting for
        # the whole agent loop to finish.
        if is_stop_requested():
            raise StopRequestedError()
        self._feedback(f"⚙️ Executing local tool: {name}...")

    def on_tool_end(self, output, **kwargs) -> None:
        name = kwargs.get("name") or "tool"
        msg = f"⚙️ Executed tools: {name}\nResults:\n- {output}"
        self._feedback(msg)
        if self._on_complete and self._show_tools_results:
            try:
                self._on_complete(msg)
            except Exception:
                pass

    def on_tool_error(self, error, **kwargs) -> None:
        # Let the executor's error handling surface the exception; a stop raised
        # inside a tool must keep propagating (never swallow it here).
        if isinstance(error, StopRequestedError):
            raise error

    def on_llm_end(self, response, **kwargs) -> None:
        # Fase 6: accumulate usage_metadata from every model call of this turn.
        # ``**kwargs`` absorbs the keyword-only ``run_id`` required by this
        # langchain-core version (calling without it raises TypeError).
        try:
            for generations in getattr(response, "generations", None) or []:
                for generation in generations or []:
                    message = getattr(generation, "message", None)
                    usage = getattr(message, "usage_metadata", None) or {}
                    in_tokens = usage.get("input_tokens")
                    out_tokens = usage.get("output_tokens")
                    if in_tokens or out_tokens:
                        self.usage_calls += 1
                        self.usage_input_tokens += in_tokens or 0
                        self.usage_output_tokens += out_tokens or 0
        except Exception:
            # Usage accounting must never break the agent turn.
            pass


def _content_to_text(content) -> str:
    """Normalize the current message content to plain text.

    Accepts a bare string, a list mixing strings and genai ``Content``/``Part``
    objects (mirrors ``execute_openai_compatible_llm``), and OpenAI-style dicts.
    Non-text parts (images) are skipped so the agent still receives the text.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for p in content:
            if isinstance(p, str):
                text_parts.append(p)
            elif getattr(p, "text", None):
                text_parts.append(p.text)
            elif isinstance(p, dict) and p.get("text"):
                text_parts.append(p["text"])
        return " ".join([t for t in text_parts if t])
    return str(content)


def _history_to_lc_messages(history):
    """Convert Gemini-style history into LangChain chat messages.

    Accepts genai ``types.Content`` objects (role 'user'/'model') and, defensively,
    OpenAI-style dicts ({'role': ..., 'content': ...}). Text parts only; images
    are dropped so the tool-calling agent keeps a clean text transcript.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    messages = []
    for msg in history or []:
        role = getattr(msg, "role", None)
        parts = getattr(msg, "parts", None)
        if role is None and isinstance(msg, dict):
            role = msg.get("role")
            text = msg.get("content", "")
            parts_text = text if isinstance(text, str) else _content_to_text(text)
        elif parts is not None:
            text_parts = [p.text for p in parts if getattr(p, "text", None)]
            parts_text = " ".join(text_parts)
        else:
            continue
        if parts_text:
            messages.append(_role_to_message(role, parts_text, HumanMessage, AIMessage))
    return messages


def _role_to_message(role, text, human_cls, ai_cls):
    """Map a role string to the matching LangChain message class."""
    if role in ("model", "assistant"):
        return ai_cls(content=text)
    return human_cls(content=text)



def _build_structured_kwargs(config_kwargs: dict, has_tools: bool) -> dict:
    """Translate the Fase-1 structured-output kwargs into make_chat_model args.

    ``route_llm_call`` injects, into ``config_kwargs``:
      * Gemini: ``response_mime_type`` / ``response_schema``;
      * OpenAI-compatible: a private ``lc_openai_response_format`` key.

    This maps them onto the factory's ``response_format`` / ``gemini_json_*``
    parameters so the chat model enforces the contract natively. The Gemini
    schema drop when tools are present is handled inside the factory.
    """
    out = {}
    rf = config_kwargs.get("lc_openai_response_format")
    if rf is not None:
        out["response_format"] = rf
    if config_kwargs.get("response_mime_type") == "application/json":
        out["gemini_json_mime"] = True
    if config_kwargs.get("response_schema") is not None:
        out["gemini_json_schema"] = config_kwargs["response_schema"]
    out["has_tools"] = has_tools
    return out


def _invoke_with_retry(executor, payload, callback, cursor, table, session_id,
                       message_in_id, on_complete):
    """Run the agent, retrying transient 429/402 errors like the legacy loops.

    Reuses the exact classification/back-off helpers from ``agent.openai_tools``
    so the ⏳ / 💳 feedback and waits are identical to the OpenAI-compatible loop.
    Permanent errors (401/400/etc.) propagate so the model fallback chain in
    ``invoke_llm_with_fallback`` can switch providers.
    """
    from agent.openai_tools import (
        _API_CALL_MAX_RETRIES,
        _PROVIDER_BALANCE_WAIT,
        _is_provider_balance_error,
        _is_rate_limit_error,
        _wait_seconds_for_rate_limit,
    )
    from agent.db_feedback import insert_feedback

    def emit(text: str) -> None:
        insert_feedback(cursor, table, session_id, message_in_id, text)
        if on_complete:
            try:
                on_complete(text)
            except Exception:
                pass

    for retry_attempt in range(_API_CALL_MAX_RETRIES):
        try:
            return executor.invoke(payload, config={"callbacks": [callback]})
        except Exception as e:
            # A user /stop must always win over retrying.
            if isinstance(e, StopRequestedError):
                raise
            if _is_provider_balance_error(e):
                if retry_attempt >= _API_CALL_MAX_RETRIES - 1:
                    raise e
                wait_seconds = _PROVIDER_BALANCE_WAIT
                retry_feedback = (
                    f"💳 Model provider temporarily unavailable (402, insufficient balance) on "
                    f"attempt {retry_attempt + 1}/{_API_CALL_MAX_RETRIES}. "
                    f"Waiting {wait_seconds:.0f}s to retry..."
                )
            elif _is_rate_limit_error(e):
                if retry_attempt >= _API_CALL_MAX_RETRIES - 1:
                    raise e
                wait_seconds = _wait_seconds_for_rate_limit(e)
                retry_feedback = (
                    f"⏳ Rate limit (429) on attempt {retry_attempt + 1}/{_API_CALL_MAX_RETRIES}. "
                    f"Waiting {wait_seconds:.0f}s to retry..."
                )
            else:
                raise e
            emit(retry_feedback)
            if sleep_interruptible(wait_seconds):
                raise StopRequestedError()



class _DirectChainExecutor:
    """Minimal ``prompt | model`` wrapper with an AgentExecutor-like interface.

    Used only on the tool-free path, where ``create_tool_calling_agent`` would
    otherwise call ``model.bind_tools([])`` (not implemented by simple fakes and
    pointless in production). Exposes ``invoke(payload, config=...) -> dict`` so
    ``_invoke_with_retry`` can drive both executors uniformly.
    """

    def __init__(self, chain):
        self._chain = chain

    def invoke(self, payload, config=None):
        message = self._chain.invoke(payload, config=config or {})
        content = getattr(message, "content", message)
        return {"output": _content_to_text(content)}


def run_langchain_llm(
    model_name: str,
    history: list,
    config_kwargs: dict,
    content,
    cursor,
    session_id: str,
    message_in_id: str,
    table: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    on_complete=None,
) -> str:
    """Execute one LLM turn through the unified LangChain tool-calling agent.

    Signature mirrors ``call_gemini_llm`` so ``route_llm_call`` can dispatch to
    it transparently. Returns the agent's final text (parsed upstream by
    ``parse_agent_response`` in the autonomous loop).
    """
    from database import get_config

    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import (
        ChatPromptTemplate,
        HumanMessagePromptTemplate,
        MessagesPlaceholder,
        SystemMessagePromptTemplate,
    )

    lc_cache.maybe_init_cache()

    show_tools_results = config_kwargs.get("show_tools_results", True)
    system_instruction = config_kwargs.get("system_instruction", "") or ""
    temperature = config_kwargs.get("temperature")
    thinking_config = config_kwargs.get("thinking_config")
    tool_funcs = config_kwargs.get("tools") or []
    has_tools = bool(tool_funcs)

    model = lc_models.make_chat_model(
        model_name,
        provider=provider,
        api_key=api_key,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking_config=thinking_config,
        **_build_structured_kwargs(config_kwargs, has_tools),
    )

    lc_tools = build_lc_tools(tool_funcs) if has_tools else []

    # Agent prompt (tool-calling path) includes the agent_scratchpad placeholder.
    agent_prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessagePromptTemplate.from_template(
                system_instruction or "You are a helpful assistant."
            ),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            HumanMessagePromptTemplate.from_template("{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    try:
        max_iterations = int(get_config("AUTONOMOUS_MODE", "10"))
    except Exception:
        max_iterations = 10

    callback = FeedbackCallbackHandler(
        cursor, table, session_id, message_in_id, show_tools_results, on_complete
    )
    payload = {
        "input": _content_to_text(content),
        "chat_history": _history_to_lc_messages(history),
    }

    if has_tools:
        agent = create_tool_calling_agent(model, lc_tools, agent_prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=lc_tools,
            max_iterations=max_iterations,
            handle_parsing_errors=True,
        )
    else:
        # No tools: skip the tool-calling agent machinery entirely (which would
        # call model.bind_tools([]) and expect an agent_scratchpad input) and run
        # a plain prompt | model chain. Cheaper and keeps simple chat models
        # usable on this path.
        direct_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    system_instruction or "You are a helpful assistant."
                ),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                HumanMessagePromptTemplate.from_template("{input}"),
            ]
        )
        executor = _DirectChainExecutor(direct_prompt | model)

    result = _invoke_with_retry(
        executor, payload, callback, cursor, table, session_id, message_in_id, on_complete
    )
    # Fase 6: one usage row per agent turn (iterations + retries already
    # summed by the callback). log_llm_usage is fail-safe by contract, so a
    # missing llm_usage table on old databases never breaks the turn.
    try:
        from agent.llm_usage import log_llm_usage

        if callback.usage_calls:
            log_llm_usage(
                session_id,
                message_in_id,
                "langchain",
                model_name,
                callback.usage_input_tokens,
                callback.usage_output_tokens,
            )
    except Exception:
        pass
    return result.get("output", "")

