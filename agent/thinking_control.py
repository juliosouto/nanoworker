"""Explicitly turns thinking/reasoning off when the worker has it disabled.

Sending nothing leaves the model's default, and many models think by default
(Gemini 2.5 Flash, Gemini 3, Qwen3, DeepSeek, Nemotron...). ``thinking_off_kwargs``
returns the config_kwargs entries that switch it off (or to the lowest level
the model allows) for the resolved provider:

- Gemini: ``thinking_config`` (budget 0 on 2.5, MINIMAL/LOW level on 3+);
- OpenAI-compatible providers: ``openai_extra_body``, merged into the request
  body by both the legacy loop and the LangChain ChatOpenAI/ChatGroq models.
"""

import json
import logging
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

# Gemini 3+ models that rejected thinking_level=MINIMAL; they get LOW instead.
_MINIMAL_UNSUPPORTED = set()

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_TTL = 24 * 3600
_openrouter_cache = {"at": 0.0, "models": {}}
_openrouter_lock = threading.Lock()

# Lowest first.
_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _strip(model_name, prefix):
    lower = (model_name or "").lower()
    return model_name[len(prefix):] if lower.startswith(prefix) else model_name


def _gemini_thinking_off(model_name):
    from google.genai import types

    name = (model_name or "").lower().split("/")[-1]
    if not name.startswith("gemini"):
        return None  # Gemma and other Google models have no thinking switch.
    if name.startswith("gemini-2.5"):
        # 2.5 Pro cannot turn thinking off; 128 is its minimum budget.
        return types.ThinkingConfig(thinking_budget=128 if "pro" in name else 0)
    if name.startswith(("gemini-1", "gemini-2.0")):
        return None
    # Gemini 3+ cannot turn thinking off: use the lowest level. Pro models and
    # the ones that rejected MINIMAL get LOW.
    if "pro" in name or model_name in _MINIMAL_UNSUPPORTED:
        return types.ThinkingConfig(thinking_level="LOW")
    return types.ThinkingConfig(thinking_level="MINIMAL")


def is_minimal_level_error(error) -> bool:
    """True when Gemini rejected thinking_level=MINIMAL for a model."""
    msg = str(error).lower()
    return "thinking" in msg and ("minimal" in msg or "level" in msg)


def mark_minimal_unsupported(model_name) -> bool:
    """Remembers that the model needs LOW; False when it was already known."""
    if model_name in _MINIMAL_UNSUPPORTED:
        return False
    _MINIMAL_UNSUPPORTED.add(model_name)
    return True


def _openrouter_reasoning_info(model_id):
    """The model's ``reasoning`` block from OpenRouter's public model list
    (cached for a day), or None when unknown."""
    with _openrouter_lock:
        if time.time() - _openrouter_cache["at"] > _OPENROUTER_TTL:
            try:
                with urllib.request.urlopen(_OPENROUTER_MODELS_URL, timeout=10) as response:
                    data = json.load(response).get("data") or []
                _openrouter_cache["models"] = {
                    m.get("id"): m.get("reasoning") for m in data if m.get("id")
                }
            except Exception as e:
                logger.warning(f"Could not read OpenRouter's model list: {e}")
            # Also after a failure: retry tomorrow, not on every call.
            _openrouter_cache["at"] = time.time()
        return _openrouter_cache["models"].get(model_id)


def _openrouter_reasoning_off(model_name):
    model_id = _strip(model_name, "openrouter/")
    info = _openrouter_reasoning_info(model_id) or {}
    efforts = [e for e in _EFFORT_ORDER if e in (info.get("supported_efforts") or [])]
    if info.get("mandatory"):
        # Cannot be disabled ("none" is rejected): ask for the lowest effort.
        lowest = next((e for e in efforts if e != "none"), None)
        return {"reasoning": {"effort": lowest}} if lowest else None
    if "none" in efforts:
        return {"reasoning": {"effort": "none"}}
    return {"reasoning": {"enabled": False}}


def thinking_off_kwargs(provider, model_name) -> dict:
    """config_kwargs entries that turn thinking off for this model ({} if none)."""
    from agent.lc.models import resolve_provider

    resolved = resolve_provider(provider, model_name)
    lower = (model_name or "").lower()
    try:
        if resolved == "gemini":
            config = _gemini_thinking_off(model_name)
            return {"thinking_config": config} if config is not None else {}
        if resolved == "openrouter":
            body = _openrouter_reasoning_off(model_name)
        elif resolved == "qwen":
            body = {"enable_thinking": False}
        elif resolved in ("nvidia", "cloudflare"):
            # vLLM/SGLang chat templates: Qwen3/GLM read enable_thinking,
            # DeepSeek V3.1+ reads thinking; unknown keys are ignored.
            body = {"chat_template_kwargs": {"enable_thinking": False, "thinking": False}}
            if "gpt-oss" in lower:
                body = {"reasoning_effort": "low"}  # gpt-oss always reasons
        elif resolved == "groq":
            if "qwen" in lower:
                body = {"reasoning_effort": "none"}
            elif "gpt-oss" in lower:
                body = {"reasoning_effort": "low"}
            else:
                body = None
        else:
            body = None
    except Exception as e:
        logger.warning(f"Could not build the thinking-off settings for {model_name}: {e}")
        return {}
    return {"openai_extra_body": body} if body else {}
