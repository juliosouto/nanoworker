"""Applies the worker's thinking level to each provider's request.

Levels: disabled, minimal, low, medium, high. ``disabled`` is sent explicitly
(off switch, or the lowest level the model allows): sending nothing leaves the
model's default, and many models think by default (Gemini 2.5 Flash, Gemini 3,
Qwen3, DeepSeek, Nemotron...). ``thinking_kwargs`` returns the config_kwargs
entries for the resolved provider:

- Gemini: ``thinking_config`` (budget on 2.5, thinking_level on 3+);
- OpenAI-compatible providers: ``openai_extra_body``, merged into the request
  body by both the legacy loop and the LangChain ChatOpenAI/ChatGroq models.
"""

import json
import logging
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

THINKING_LEVELS = ("disabled", "minimal", "low", "medium", "high")
# Level used for workers saved before levels existed (thinking_enabled=1).
LEGACY_ENABLED_LEVEL = "medium"

# Gemini 2.5 thinking budgets per level (2.5 Pro cannot go below 128).
_GEMINI_25_BUDGETS = {"minimal": 512, "low": 2048, "medium": 8192, "high": 24576}

# Gemini 3+ models that rejected thinking_level=MINIMAL; they get LOW instead.
_MINIMAL_UNSUPPORTED = set()

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_TTL = 24 * 3600
_openrouter_cache = {"at": 0.0, "models": {}}
_openrouter_lock = threading.Lock()

# Lowest first.
_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def normalize_level(level, thinking_enabled=False) -> str:
    """A valid level; unknown or empty values fall back to the legacy flag."""
    value = str(level or "").strip().lower()
    if value in THINKING_LEVELS:
        return value
    return LEGACY_ENABLED_LEVEL if thinking_enabled else "disabled"


def _strip(model_name, prefix):
    lower = (model_name or "").lower()
    return model_name[len(prefix):] if lower.startswith(prefix) else model_name


def _gemini_config(model_name, level):
    from google.genai import types

    name = (model_name or "").lower().split("/")[-1]
    if not name.startswith("gemini") or name.startswith(("gemini-1", "gemini-2.0")):
        return None  # Gemma and older models have no thinking switch.
    if name.startswith("gemini-2.5"):
        if level == "disabled":
            # 2.5 Pro cannot turn thinking off; 128 is its minimum budget.
            return types.ThinkingConfig(thinking_budget=128 if "pro" in name else 0)
        return types.ThinkingConfig(thinking_budget=_GEMINI_25_BUDGETS[level])
    # Gemini 3+ cannot turn thinking off: "disabled" is the lowest level. Pro
    # models and the ones that rejected MINIMAL get LOW instead of MINIMAL.
    wanted = "minimal" if level == "disabled" else level
    if wanted == "minimal" and ("pro" in name or model_name in _MINIMAL_UNSUPPORTED):
        wanted = "low"
    return types.ThinkingConfig(thinking_level=wanted.upper())


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


def _openrouter_reasoning(model_name, level):
    model_id = _strip(model_name, "openrouter/")
    info = _openrouter_reasoning_info(model_id) or {}
    efforts = [e for e in _EFFORT_ORDER if e in (info.get("supported_efforts") or [])]
    if level == "disabled":
        if info.get("mandatory"):
            # Cannot be disabled ("none" is rejected): ask for the lowest effort.
            lowest = next((e for e in efforts if e != "none"), None)
            return {"reasoning": {"effort": lowest}} if lowest else None
        if "none" in efforts:
            return {"reasoning": {"effort": "none"}}
        return {"reasoning": {"enabled": False}}
    if efforts:
        # The requested effort, or the nearest one above it the model has.
        rank = _EFFORT_ORDER.index(level)
        above = [e for e in efforts if _EFFORT_ORDER.index(e) >= rank]
        level = above[0] if above else efforts[-1]
    return {"reasoning": {"effort": level}}


def _gpt_oss_effort(level):
    """gpt-oss always reasons: low/medium/high only."""
    return "low" if level in ("disabled", "minimal") else level


def thinking_kwargs(provider, model_name, level) -> dict:
    """config_kwargs entries that apply ``level`` to this model ({} if none)."""
    from agent.lc.models import resolve_provider

    level = normalize_level(level)
    resolved = resolve_provider(provider, model_name)
    lower = (model_name or "").lower()
    on = level != "disabled"
    try:
        if resolved == "gemini":
            config = _gemini_config(model_name, level)
            return {"thinking_config": config} if config is not None else {}
        if resolved == "openrouter":
            body = _openrouter_reasoning(model_name, level)
        elif resolved == "qwen":
            body = {"enable_thinking": on}
        elif resolved in ("nvidia", "cloudflare"):
            # vLLM/SGLang chat templates: Qwen3/GLM read enable_thinking,
            # DeepSeek V3.1+ reads thinking; unknown keys are ignored.
            body = {"chat_template_kwargs": {"enable_thinking": on, "thinking": on}}
            if "gpt-oss" in lower:
                body = {"reasoning_effort": _gpt_oss_effort(level)}
        elif resolved == "groq":
            if "qwen" in lower:
                body = {"reasoning_effort": "default" if on else "none"}
            elif "gpt-oss" in lower:
                body = {"reasoning_effort": _gpt_oss_effort(level)}
            else:
                body = None
        else:
            body = None
    except Exception as e:
        logger.warning(f"Could not build the thinking settings for {model_name}: {e}")
        return {}
    return {"openai_extra_body": body} if body else {}


def thinking_off_kwargs(provider, model_name) -> dict:
    """config_kwargs entries that turn thinking off for this model ({} if none)."""
    return thinking_kwargs(provider, model_name, "disabled")
