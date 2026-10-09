"""Structured output support (Fase 1) — the AgentResponse contract.

Defines the single source of truth for the JSON contract the LLM must emit on
its final answer, and produces the per-provider native structured-output
configurations that enforce it at the API level (instead of the legacy prose
JSON_SCHEMA_PROMPT block).

Contract fields (mirrors the legacy prompt exactly):
    user_prompt, llm_response, is_the_user_request_completely_satisfied,
    critical_system_failure, and optionally execution_plan.
"""
import logging
from typing import Optional

from pydantic import BaseModel, field_validator

from agent.lc import settings

logger = logging.getLogger(__name__)

# Providers that support the strict "json_schema" response format.
_JSON_SCHEMA_PROVIDERS = {"openai", "groq", "openrouter"}
# Providers that only support the looser "json_object" response format.
_JSON_OBJECT_PROVIDERS = {"qwen", "deepseek"}
# Gemini is handled via its own config keys (response_mime_type/response_schema).
_GEMINI_PROVIDERS = {"gemini", "google"}


class AgentResponse(BaseModel):
    """The structured final answer contract (replaces the prose JSON schema).

    Field semantics are identical to the legacy JSON_SCHEMA_PROMPT so that
    the autonomous reflection loop keeps working unchanged.
    """
    user_prompt: str = ""
    execution_plan: Optional[str] = None
    llm_response: str = ""
    is_the_user_request_completely_satisfied: Optional[bool] = None
    critical_system_failure: Optional[bool] = None

    @field_validator(
        "is_the_user_request_completely_satisfied",
        "critical_system_failure",
        mode="before",
    )
    @classmethod
    def _coerce_optional_bool(cls, v):
        """Coerce JSON booleans that arrive as strings ("true"/"false") or ints.

        Mirrors agent.autonomous_loop._coerce_bool; unknown values become None
        (unknown == not satisfied == keep reflecting), matching the legacy loop.
        """
        if v is None or isinstance(v, bool):
            return v
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered in ("true", "1", "yes"):
                return True
            if lowered in ("false", "0", "no"):
                return False
            return None
        if isinstance(v, (int, float)) and v in (0, 1):
            return bool(v)
        return None

    def to_legacy_dict(self) -> dict:
        """Dict shape consumed by the legacy reflection loop code paths."""
        return {
            "user_prompt": self.user_prompt,
            "execution_plan": self.execution_plan,
            "llm_response": self.llm_response,
            "is_the_user_request_completely_satisfied": self.is_the_user_request_completely_satisfied,
            "critical_system_failure": self.critical_system_failure,
        }


def agent_response_json_schema() -> dict:
    """A JSON Schema for the AgentResponse contract.

    Used for providers with a json_schema response format (OpenAI, Groq,
    OpenRouter) and for Gemini's response_schema config. Kept permissive so
    it is accepted by the widest set of OpenAI-compatible gateways.
    """
    return AgentResponse.model_json_schema()


def parse_agent_response(raw_text) -> Optional[AgentResponse]:
    """Parses raw LLM output into a validated AgentResponse.

    Reuses the proven legacy extraction pipeline (_parse_json_response: fence
    stripping, fast-path, greedy regex, balanced-brace scanner) and then
    validates/coerces the result through the Pydantic model.

    Returns:
        AgentResponse | None: None when nothing parses into the contract
        (including the ``llm_response`` key requirement of the legacy loop).
    """
    from agent.autonomous_loop import _parse_json_response

    if not raw_text:
        return None
    parsed = _parse_json_response(raw_text)
    if not isinstance(parsed, dict) or "llm_response" not in parsed:
        return None
    # Mirror the legacy loop's gate exactly: it only enters the structured
    # branch when at least one reflection flag key is present.
    if (
        "is_the_user_request_completely_satisfied" not in parsed
        and "critical_system_failure" not in parsed
    ):
        return None
    try:
        return AgentResponse.model_validate(parsed)
    except Exception as exc:
        logger.debug("AgentResponse validation failed (%s); raw=%r", exc, str(raw_text)[:200])
        return None


def supports_native_structured(provider: Optional[str], model_name: str = "") -> bool:
    """True when the provider/model reliably supports native structured output.

    A None/empty provider is treated as Gemini, mirroring the default branch
    of route_llm_call.
    """
    p = (provider or "").lower()
    m = (model_name or "").lower()

    if p in _GEMINI_PROVIDERS or p == "":
        return True
    if p in _JSON_SCHEMA_PROVIDERS:
        if p == "openrouter":
            # OpenRouter forwards response_format only for OpenAI-family models.
            return "gpt-" in m or "/o1" in m or "/o3" in m or "/o4" in m or "openai/" in m
        return True
    if p in _JSON_OBJECT_PROVIDERS:
        # DashScope (Qwen) and DeepSeek support json_object mode.
        return True
    # Unknown / ollama / nvidia and anything else: fall back to the prompt.
    return False


def structured_output_enabled(provider: Optional[str], model_name: str = "") -> bool:
    """Single gate: LangChain stack active + mode auto + provider supports it."""
    if not settings.stack_enabled():
        return False
    if settings.structured_output_mode() != "auto":
        return False
    return supports_native_structured(provider, model_name)


def resolve_provider_for_model(model_name: str) -> Optional[str]:
    """Resolves the provider for a model name, consulting llm_config first.

    Mirrors the provider detection used by route_llm_call so the caller
    (message_processor) can decide native-vs-prompt BEFORE building the prompt
    without duplicating the routing logic. The prefix table is delegated to
    ``lc.models.resolve_provider`` (single source of truth); ``None`` here
    means "no native branch" (route_llm_call's default branch is Gemini).
    """
    if not model_name:
        return None
    try:
        from database import get_db
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT provider FROM llm_config WHERE model_name = ?", (model_name,))
        row = c.fetchone()
        conn.close()
        if row:
            try:
                provider = row["provider"]
            except (KeyError, IndexError, TypeError):
                provider = None
            if provider:
                return str(provider).lower()
    except Exception:
        pass

    # Fall back to the same prefix heuristics as route_llm_call, delegated to
    # the shared resolver (None = default branch, which is Gemini in the
    # legacy router and handled internally by the LangChain factory).
    from agent.lc.models import resolve_provider

    return resolve_provider(None, model_name, default=None)


def gemini_response_config() -> dict:
    """Gemini-native structured output config, injected into config_kwargs.

    These become direct kwargs of types.GenerateContentConfig in
    call_gemini_llm (which splats **config_kwargs). The schema is emitted as
    a plain dict so it is accepted by every google-genai version.
    """
    return {
        "response_mime_type": "application/json",
        "response_schema": agent_response_json_schema(),
    }


def openai_response_format() -> dict:
    """OpenAI-compatible ``response_format`` value for the AgentResponse schema.

    - ``json_schema`` (``strict: False``) for providers that enforce the schema
      (OpenAI, Groq, OpenRouter): the API validates and rejects non-conformant
      output before the reflection loop.
    - ``json_object`` for providers that only support the looser format
      (Qwen/dashscope, DeepSeek): the API guarantees valid JSON, but the shape
      is not enforced by the model — the balanced parser still recovers the
      contract and validates it through the Pydantic model.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "agent_response",
            "strict": False,  # permissive: accepted by gateways (OpenRouter, Groq...)
            "schema": agent_response_json_schema(),
        },
    }


def json_object_response_format() -> dict:
    """``json_object`` response format (no schema enforcement)."""
    return {"type": "json_object"}


def build_structured_kwargs(provider: Optional[str]) -> dict:
    """Returns the config_kwargs additions that enforce the structured contract.

    - Gemini: direct GenerateContentConfig kwargs (response_mime_type/response_schema).
    - Providers with json_schema enforcement (OpenAI, Groq, OpenRouter): a private
      ``lc_openai_response_format`` key that execute_openai_compatible_llm converts
      to response_format at call time.
    - Providers with looser json_object (Qwen, DeepSeek): ``json_object`` so the API
      still guarantees valid JSON (shape validated afterward through AgentResponse).
    - Anything else: empty dict (prompt-based fallback, i.e. the legacy path).
    """
    p = (provider or "").lower()
    if p in _GEMINI_PROVIDERS:
        return gemini_response_config()
    if p in _JSON_OBJECT_PROVIDERS:
        return {"lc_openai_response_format": json_object_response_format()}
    if p in _JSON_SCHEMA_PROVIDERS:
        return {"lc_openai_response_format": openai_response_format()}
    return {}
