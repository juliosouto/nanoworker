"""Chat-model factory for the LangChain execution stack (phase 5).

Single source of truth for turning a resolved ``(model_name, provider)`` into a
LangChain ``BaseChatModel``. The provider precedence and the provider-specific
parameter defaults mirror ``agent.llm_router.route_llm_call`` / the legacy
``call_*_llm`` providers exactly, so ``LLM_STACK=langchain`` behaves like the
legacy loops:

    * temperature default: Gemini 2.0, every OpenAI-compatible provider 1.0;
    * Groq ``max_tokens`` default 1024 (parity with ``call_groq_llm``);
    * fixed base URLs for Qwen (DashScope), OpenRouter and NVIDIA NIM;
    * Ollama via the OpenAI-compatible endpoint (``ChatOpenAI(base_url=...)``),
      matching the legacy ``openai.OpenAI(base_url=OLLAMA_BASE_URL)`` client.

Imports of the concrete chat models are deferred to call time so that (a) the
worker boots fast and (b) importing this module never requires the optional
integration packages / API keys to be present.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Fixed base URLs for the OpenAI-compatible providers (parity with llm_providers).
PROVIDER_BASE_URLS = {
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}

# Default temperature per provider family (parity with build_config_kwargs and
# the call_*_llm providers: Gemini keeps 2.0, OpenAI-compatible uses 1.0).
_GEMINI_DEFAULT_TEMPERATURE = 2.0
_OPENAI_COMPAT_DEFAULT_TEMPERATURE = 1.0

# Groq reserves 1024 output tokens when the model has no configured max
# (parity with call_groq_llm's ``limit_tokens`` default).
_GROQ_DEFAULT_MAX_TOKENS = 1024


def resolve_provider(
    provider: Optional[str],
    model_name: str,
    default: str = "gemini",
) -> Optional[str]:
    """Resolve the effective provider name for a model.

    Single source of truth for provider detection — shared by the LangChain
    factory, the structured-output gate (``lc.outputs.resolve_provider_for_
    model``) and, transitively, the message pipeline. ``route_llm_call`` keeps
    its own dispatch chain because it also encodes which legacy loop to call.

    Precedence (identical to ``route_llm_call``):
        1. the user-configured ``provider`` column (already lower-cased);
        2. a model-name prefix, with NVIDIA checked FIRST (NIM hosts models
           whose last path segment overlaps other providers' prefixes, e.g.
           ``nvidia/qwen/...`` or ``nvidia/openai/...``), then qwen/groq/openai/
           ollama/openrouter;
        3. ``default`` ('gemini' unless the caller overrides it — e.g.
           ``lc.outputs`` passes ``None`` to express "no native branch").

    Args:
        provider: value of the ``llm_config.provider`` column (or None).
        model_name: the model name, possibly prefixed with ``<provider>/``.
        default: value returned when neither the column nor a prefix matches.

    Returns:
        str | None: the resolved provider name.
    """
    if provider:
        return str(provider).lower()

    lower = (model_name or "").lower()
    if lower.startswith("nvidia/"):
        return "nvidia"
    if lower.startswith("qwen"):
        return "qwen"
    if lower.startswith("groq/"):
        return "groq"
    if lower.startswith("openai/"):
        return "openai"
    if lower.startswith("ollama/"):
        return "ollama"
    if lower.startswith("openrouter/"):
        return "openrouter"
    return default



def make_chat_model(
    model_name: str,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    thinking_config=None,
    response_format: Optional[dict] = None,
    gemini_json_mime: bool = False,
    gemini_json_schema: Optional[dict] = None,
    has_tools: bool = False,
):
    """Build the LangChain chat model for a resolved model/provider pair.

    Args:
        model_name: provider model name (with any ``<provider>/`` prefix intact;
            the Ollama prefix is stripped here before constructing the client).
        provider: user-configured provider, or None to infer from the prefix.
        api_key: decrypted API key. Required for every provider except Ollama
            (which uses a placeholder), matching the legacy call_*_llm raises.
        temperature: sampling temperature; when None the provider default is
            used (Gemini 2.0, OpenAI-compatible 1.0).
        max_output_tokens: output token cap; Groq defaults to 1024 when None.
        thinking_config: google-genai ThinkingConfig (Gemini only, ignored
            elsewhere).
        response_format: OpenAI-compatible ``response_format`` value (from
            ``lc_outputs``), applied to ChatOpenAI / ChatGroq only.
        gemini_json_mime: when True, set Gemini ``response_mime_type`` to JSON.
        gemini_json_schema: Gemini ``response_schema``; ignored when ``has_tools``
            (Gemini rejects response_schema together with function calling).
        has_tools: whether tool calling is enabled for this call (controls the
            Gemini schema drop rule).

    Returns:
        BaseChatModel: the configured chat model.

    Raises:
        ValueError: when a required API key is missing (parity with legacy).
    """
    resolved = resolve_provider(provider, model_name)

    if resolved == "gemini":
        return _make_gemini(
            model_name,
            api_key,
            temperature,
            max_output_tokens,
            thinking_config,
            gemini_json_mime,
            gemini_json_schema,
            has_tools,
        )
    if resolved == "groq":
        return _make_groq(model_name, api_key, temperature, max_output_tokens, response_format)
    if resolved == "ollama":
        return _make_ollama(model_name, temperature, max_output_tokens, response_format)
    # 'openai', qwen/openrouter/nvidia (fixed base URL) and any future
    # OpenAI-compatible provider share the ChatOpenAI builder.
    return _make_openai_compat(
        model_name, resolved, api_key, temperature, max_output_tokens, response_format
    )


def _make_gemini(
    model_name, api_key, temperature, max_output_tokens, thinking_config,
    gemini_json_mime, gemini_json_schema, has_tools,
):
    if not api_key:
        raise ValueError("API Key for Gemini model is not set.")

    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs = {
        "model": model_name,
        "google_api_key": api_key,
        "temperature": (
            _GEMINI_DEFAULT_TEMPERATURE if temperature is None else temperature
        ),
    }
    if max_output_tokens:
        kwargs["max_output_tokens"] = int(max_output_tokens)
    if thinking_config is not None:
        kwargs["thinking_config"] = thinking_config
    # Gemini rejects response_schema when function calling is enabled; keep only
    # the JSON mime type in that case (parity with call_gemini_llm).
    if gemini_json_mime:
        kwargs["response_mime_type"] = "application/json"
        if gemini_json_schema and not has_tools:
            kwargs["response_schema"] = gemini_json_schema
    return ChatGoogleGenerativeAI(**kwargs)


def _make_openai_compat(
    model_name, provider, api_key, temperature, max_output_tokens, response_format
):
    if not api_key:
        raise ValueError(f"API Key for {provider} model is not set.")

    from langchain_openai import ChatOpenAI

    kwargs = {
        "model": model_name,
        "api_key": api_key,
        "temperature": (
            _OPENAI_COMPAT_DEFAULT_TEMPERATURE if temperature is None else temperature
        ),
    }
    base_url = PROVIDER_BASE_URLS.get(provider)
    if base_url:
        kwargs["base_url"] = base_url
    if max_output_tokens:
        kwargs["max_tokens"] = int(max_output_tokens)
    if response_format is not None:
        kwargs["response_format"] = response_format
    return ChatOpenAI(**kwargs)


def _make_groq(model_name, api_key, temperature, max_output_tokens, response_format):
    if not api_key:
        raise ValueError("API Key for Groq model is not set.")

    from langchain_groq import ChatGroq

    kwargs = {
        "model": model_name,
        "api_key": api_key,
        "temperature": (
            _OPENAI_COMPAT_DEFAULT_TEMPERATURE if temperature is None else temperature
        ),
        "max_tokens": (
            int(max_output_tokens) if max_output_tokens else _GROQ_DEFAULT_MAX_TOKENS
        ),
    }
    # ChatGroq has no first-class response_format field; route it through
    # model_kwargs so it reaches the API verbatim (json_schema / json_object).
    if response_format is not None:
        kwargs["model_kwargs"] = {"response_format": response_format}
    return ChatGroq(**kwargs)


def _make_ollama(model_name, temperature, max_output_tokens, response_format):
    from langchain_openai import ChatOpenAI

    from database import get_config

    base_url = get_config("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    # Strip an "ollama/" prefix so the model id matches the local server, while
    # still resolving the provider from the prefixed name above.
    local_model = (
        model_name.split("/", 1)[1]
        if model_name.lower().startswith("ollama/")
        else model_name
    )
    kwargs = {
        "model": local_model,
        "api_key": "ollama",  # placeholder: Ollama ignores it
        "base_url": base_url,
        "temperature": (
            _OPENAI_COMPAT_DEFAULT_TEMPERATURE if temperature is None else temperature
        ),
    }
    if max_output_tokens:
        kwargs["max_tokens"] = int(max_output_tokens)
    if response_format is not None:
        kwargs["response_format"] = response_format
    return ChatOpenAI(**kwargs)
