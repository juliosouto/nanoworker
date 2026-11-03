"""Applies the worker's quantization preference to OpenRouter requests.

The worker keeps an ordered list (first = preferred). OpenRouter's
``provider.quantizations`` only filters, it does not rank, so the model's
endpoints are read from OpenRouter's public API and sent as ``provider.order``
sorted by that list. ``quantizations`` still restricts the fallbacks to the
listed levels. Other providers have no such switch and get nothing.
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# Values OpenRouter accepts in provider.quantizations.
QUANTIZATIONS = (
    "int4", "int8", "fp4", "mxfp4", "nvfp4", "fp6", "fp8", "mxfp8",
    "fp16", "bf16", "fp32", "unknown",
)
# Umbrella values that also match their variants.
_FAMILIES = {"fp4": ("mxfp4", "nvfp4"), "fp8": ("mxfp8",)}

_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{}/endpoints"
_ENDPOINTS_TTL = 6 * 3600
_endpoints_cache = {}
_endpoints_lock = threading.Lock()


def parse_quantizations(value):
    """The ordered, de-duplicated list from a list or JSON text; None when a
    value is not in QUANTIZATIONS. Empty means no preference."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, list):
        return None
    result = []
    for item in value:
        q = str(item or "").strip().lower()
        if q not in QUANTIZATIONS:
            return None
        if q not in result:
            result.append(q)
    return result


def _model_endpoints(model_id):
    """[(endpoint slug, quantization)] for the model, cached; [] when unknown."""
    with _endpoints_lock:
        cached = _endpoints_cache.get(model_id)
        if cached and time.time() - cached[0] < _ENDPOINTS_TTL:
            return cached[1]
        endpoints = []
        try:
            url = _ENDPOINTS_URL.format(urllib.parse.quote(model_id, safe="/:"))
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.load(response).get("data") or {}
            endpoints = [
                (e["tag"], str(e.get("quantization") or "unknown").lower())
                for e in data.get("endpoints") or [] if e.get("tag")
            ]
        except Exception as e:
            logger.warning(f"Could not read OpenRouter's endpoints for {model_id}: {e}")
        # Also after a failure: retry later, not on every call.
        _endpoints_cache[model_id] = (time.time(), endpoints)
        return endpoints


def _rank(quantization, preferred):
    """Position of the endpoint's quantization in the list, or None."""
    for i, q in enumerate(preferred):
        if quantization == q or quantization in _FAMILIES.get(q, ()):
            return i
    return None


def quantization_kwargs(provider, model_name, quantizations) -> dict:
    """The openai_extra_body ``provider`` block for this model ({} if none)."""
    from agent.lc.models import resolve_provider

    preferred = parse_quantizations(quantizations) or []
    if not preferred or resolve_provider(provider, model_name) != "openrouter":
        return {}
    lower = (model_name or "").lower()
    model_id = model_name[len("openrouter/"):] if lower.startswith("openrouter/") else model_name
    routing = {"quantizations": preferred}
    ranked = [(r, slug) for slug, q in _model_endpoints(model_id)
              if (r := _rank(q, preferred)) is not None]
    if ranked:
        routing["order"] = [slug for _, slug in sorted(ranked, key=lambda x: x[0])]
    return {"provider": routing}
