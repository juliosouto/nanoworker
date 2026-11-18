"""Decision model (Agent Behavior > Use Decision Model).

When DECISION_MODEL_ENABLED is on, one quick call to the chosen OpenRouter
model decides how each message is answered:

- "agent":  the full pipeline (tools, planner, reflection/evaluator rounds);
- "direct": one plain call with the system prompt, memory, history and RAG,
            but no tools, no plan and no extra rounds.

Fail-open: when the feature is off, no model is chosen, the call fails or the
answer cannot be parsed, the message goes to the agent (the old behavior).

The model list on the settings page comes from OpenRouter's public
/api/v1/models, cached for an hour.
"""

import json
import logging
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

ROUTE_AGENT = "agent"
ROUTE_DIRECT = "direct"

OPENROUTER_PREFIX = "openrouter/"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_MODELS_TTL = 3600
_models_cache = {"at": 0.0, "models": []}
_models_lock = threading.Lock()

DECISION_PROMPT = """You route the messages of an AI assistant. Decide how the assistant should answer the user's latest message.

"agent": the answer needs tools or several steps: searching the web or fresh data (news, prices, weather, sports, anything that changes), reading or writing files, browsing, sending messages or files, reading other chats, scheduling, reminders, calendar, e-mail, running commands, generating images or audio, saving memories, or any action in the world.
"direct": the assistant can answer right away from its own knowledge, its instructions and memory, the conversation shown and any attached image: greetings, small talk, thanks, opinions, explanations, advice, writing, rewriting, summarizing or translating text given in the message or the conversation, describing an attached image.

When in doubt, choose "agent".
Reply with only a JSON object, no markdown: {"route": "agent"} or {"route": "direct"}"""


def decision_settings():
    """(enabled, model) from app_config; model is "" when none was chosen."""
    from database import get_config

    enabled = str(get_config("DECISION_MODEL_ENABLED", "false") or "").strip().lower() == "true"
    model = str(get_config("DECISION_MODEL", "") or "").strip()
    return enabled, model


def openrouter_api_key() -> str:
    """Key for a decision model that is not registered in llm_config: the key
    of any registered OpenRouter model, else OPENROUTER_API_KEY. "" if none."""
    from database import decrypt_value, get_config, get_db

    try:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT api_key FROM llm_config WHERE api_key IS NOT NULL AND api_key != '' "
                "AND (LOWER(provider) = 'openrouter' OR LOWER(model_name) LIKE 'openrouter/%')"
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            key = decrypt_value(row["api_key"])
            if key:
                return key
    except Exception as e:
        logger.warning("Could not read the OpenRouter key from llm_config: %s", e)
    return str(get_config("OPENROUTER_API_KEY", "") or "").strip()


def build_decision_input(message, tool_names=(), last_reply="", images=0) -> str:
    parts = []
    if last_reply:
        parts.append(f"ASSISTANT'S PREVIOUS REPLY (context):\n{last_reply[-600:]}")
    note = f"\n[{images} image(s) attached]" if images else ""
    parts.append(f"USER MESSAGE:\n{message}{note}")
    if tool_names:
        parts.append("TOOLS THE AGENT CAN USE:\n" + ", ".join(tool_names))
    return "\n\n".join(parts)


def parse_route(raw_text):
    """'agent' or 'direct' from the model answer, or None when unclear."""
    from agent.autonomous_loop import _parse_json_response

    parsed = _parse_json_response(raw_text or "")
    if isinstance(parsed, dict):
        value = str(parsed.get("route", "")).strip().lower()
        if value in (ROUTE_AGENT, ROUTE_DIRECT):
            return value
    return None


def decide_route(message, cursor, session_id, message_in_id, tool_names=(), last_reply="",
                 images=0) -> str:
    """The route for one message: 'direct' only when the decision model says
    so explicitly; 'agent' otherwise (feature off, no model, any failure)."""
    enabled, model = decision_settings()
    if not enabled or not model or not (message or "").strip():
        return ROUTE_AGENT

    from agent.llm_router import route_llm_call
    from agent.llm_usage import usage_stage
    from agent.stop_check import StopRequestedError

    started = time.monotonic()
    try:
        with usage_stage("decision"):
            raw = route_llm_call(
                model, [], {"system_instruction": DECISION_PROMPT, "temperature": 0,
                        "fallback_api_key": openrouter_api_key()},
                build_decision_input(message, tool_names, last_reply, images),
                cursor, session_id, message_in_id, False, summarize=True,
            )
    except StopRequestedError:
        raise
    except Exception as e:
        logger.warning("Decision model %s failed (%s); using the agent", model, e)
        return ROUTE_AGENT
    route = parse_route(raw)
    if route is None:
        logger.warning("Decision model %s gave no valid route: %r; using the agent", model, str(raw)[:200])
        return ROUTE_AGENT
    logger.info("Decision model %s routed message %s to %s in %.1fs",
                model, message_in_id, route, time.monotonic() - started)
    return route


def _price_per_million(value):
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def _fetch_openrouter_models() -> list:
    req = urllib.request.Request(_OPENROUTER_MODELS_URL, headers={"User-Agent": "NanoWorker"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    models = []
    for m in data.get("data") or []:
        model_id = m.get("id")
        if not model_id:
            continue
        arch = m.get("architecture") or {}
        outputs = arch.get("output_modalities") or ["text"]
        if "text" not in outputs:
            continue  # image/audio generators cannot answer the route JSON
        pricing = m.get("pricing") or {}
        prompt_price = _price_per_million(pricing.get("prompt"))
        completion_price = _price_per_million(pricing.get("completion"))
        models.append({
            "id": OPENROUTER_PREFIX + model_id,
            "name": m.get("name") or model_id,
            "context_length": m.get("context_length"),
            "prompt_price": prompt_price,
            "completion_price": completion_price,
            "free": model_id.endswith(":free") or (prompt_price == 0 and completion_price == 0),
        })
    models.sort(key=lambda x: x["name"].lower())
    return models


def list_openrouter_models(force=False) -> list:
    """Text models offered by OpenRouter, cached for an hour. Raises when the
    list cannot be fetched and nothing is cached."""
    with _models_lock:
        fresh = time.time() - _models_cache["at"] < _MODELS_TTL
        if _models_cache["models"] and fresh and not force:
            return _models_cache["models"]
        try:
            models = _fetch_openrouter_models()
        except Exception:
            if _models_cache["models"]:
                logger.warning("OpenRouter model list refresh failed; using the cached list", exc_info=True)
                return _models_cache["models"]
            raise
        _models_cache.update(at=time.time(), models=models)
        return models
