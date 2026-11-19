"""Decision model (Agent Behavior > Use Decision Model).

When DECISION_MODEL_ENABLED is on, the OpenRouter decision model picked on the
settings page decides how each message is answered:

- "agent":  the full pipeline (tools, planner, reflection/evaluator rounds);
- "direct": one plain call with the system prompt, memory, history and RAG,
            but no tools, no plan and no extra rounds.

Decision models are not chat models: they answer typed questions with
calibrated probabilities through OpenRouter's Decisions API
(POST /api/alpha/decisions). Here one ``choice`` question with the options
"agent" and "direct" is asked over the message.

A direct reply has no tools, so the guard leans hard towards the agent:

1. a message that plainly asks for a search, fresh data, a link or an action
   (_AGENT_KEYWORDS) goes to the agent without asking the model;
2. the model sees each tool's description and strict criteria;
3. a second ``noul`` question asks whether the answer needs outside
   information; at NEEDS_INFO_MAX_PROBABILITY or above the agent runs;
4. "direct" needs DIRECT_MIN_PROBABILITY;
5. the direct reply itself may answer NEEDS_AGENT_MARKER (message_processor),
   which reruns the message with the full agent.

Fail-open: when the feature is off, no model is chosen, the call fails or the
answer is not a valid choice, the message goes to the agent (the old behavior).

The model list on the settings page comes from OpenRouter's
/api/v1/models?output_modalities=decisions, cached for an hour.
"""

import json
import re
import unicodedata
import logging
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

ROUTE_AGENT = "agent"
ROUTE_DIRECT = "direct"

# "direct" needs at least this probability (when the model reports one).
DIRECT_MIN_PROBABILITY = 0.75
# Second question: probability that answering needs information from outside
# the conversation (web, fresh data, facts to check). At or above this, the
# agent runs even when the route answer is "direct".
NEEDS_INFO_MAX_PROBABILITY = 0.3

# Words that ask for a search or fresh data: such messages go to the agent
# without asking the decision model (pt and en, lower-case, accents removed).
_AGENT_KEYWORDS = re.compile(
    r"\b("
    r"pesquis\w*|procur\w*|busc\w*|googl\w*|internet|online|site|link|url|"
    r"noticia\w*|news|hoje|agora|atual\w*|ultim\w*|recente\w*|ontem|amanha|esta semana|"
    r"cotacao|preco\w*|valor de|quanto custa|clima|previsao|tempo em|placar|resultado\w*|"
    r"search\w*|look up|latest|current\w*|today|price\w*|weather|forecast|"
    r"envi\w*|mand\w*|agend\w*|lembr\w*|salv\w*|baix\w*|abr\w* o|"
    r"https?://|www\."
    r")"
)


OPENROUTER_PREFIX = "openrouter/"
_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
_DECISION_MODELS_URL = "https://openrouter.ai/api/v1/models?output_modalities=decisions"
_MODELS_TTL = 3600
_models_cache = {"at": 0.0, "models": []}
_models_lock = threading.Lock()

QUESTION_ID = "route"
NEEDS_INFO_ID = "needs_external_info"
ROUTE_INSTRUCTIONS = (
    "An AI assistant received `message` from a user. Decide how the assistant should answer it. "
    "`previous_reply` is the assistant's last reply in the chat, `attached_images` the number of "
    "images sent with the message and `agent_tools` the tools the full agent can use (name: what "
    "it does). The direct reply has NO tools: it cannot search the internet, check facts, read "
    "files or chats, or act. A wrong direct reply makes the assistant invent an answer, which is "
    "much worse than using the agent. Choose direct only when it is certain that no tool would "
    "make the answer better; when in doubt, choose agent."
)
ROUTE_CRITERIA = {
    ROUTE_AGENT: (
        "Any tool in `agent_tools` could help, or the answer depends on facts about the world: "
        "searching the internet; news, prices, quotes, weather, sports, laws, schedules or anything "
        "that changes over time; questions about specific people, companies, products, places, "
        "events, dates or numbers; anything recent; checking whether something is true; reading "
        "links, files or other chats; sending, scheduling, reminding, saving, downloading or any "
        "other action; tasks with several steps."
    ),
    ROUTE_DIRECT: (
        "Pure conversation that only needs the messages shown: greetings, thanks, small talk, "
        "reactions; rewriting, translating, summarizing or correcting text given in the message or "
        "the conversation; describing an attached image; general, timeless explanations or advice "
        "that need no specific or current facts."
    ),
}
NEEDS_INFO_INSTRUCTIONS = (
    "Does a correct answer to `message` need information that is not in `message`, "
    "`previous_reply` or the attached images: internet search, current or recent data, or "
    "specific facts (people, companies, products, prices, dates, numbers, events) the assistant "
    "should check instead of recalling from memory?"
)


def decision_settings():
    """(enabled, model) from app_config; model is "" when none was chosen."""
    from database import get_config

    enabled = str(get_config("DECISION_MODEL_ENABLED", "false") or "").strip().lower() == "true"
    model = str(get_config("DECISION_MODEL", "") or "").strip()
    return enabled, model


def openrouter_api_key() -> str:
    """The OpenRouter key: the decision model's own llm_config row, else any
    registered OpenRouter model's key, else OPENROUTER_API_KEY. "" if none."""
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


def _api_model_id(model: str) -> str:
    """The id OpenRouter expects: the stored id without the "openrouter/" prefix."""
    return model[len(OPENROUTER_PREFIX):] if model.lower().startswith(OPENROUTER_PREFIX) else model


def asks_for_agent(message) -> bool:
    """True when the message plainly asks for a search, fresh data, a link or
    an action (see _AGENT_KEYWORDS): it goes to the agent with no decision call."""
    text = unicodedata.normalize("NFKD", str(message or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return bool(_AGENT_KEYWORDS.search(text))


def build_decision_request(model, message, tool_names=(), last_reply="", images=0) -> dict:
    """tool_names: the agent's tools, as names or as {name: description}."""
    state = {"message": message, "attached_images": int(images or 0)}
    if last_reply:
        state["previous_reply"] = last_reply[-600:]
    if tool_names:
        state["agent_tools"] = (dict(tool_names) if isinstance(tool_names, dict)
                                else list(tool_names))
    return {
        "model": _api_model_id(model),
        "state": state,
        "questions": {
            QUESTION_ID: {
                "type": "choice",
                "instructions": ROUTE_INSTRUCTIONS,
                "criteria": ROUTE_CRITERIA,
            },
            NEEDS_INFO_ID: {
                "type": "noul",
                "instructions": NEEDS_INFO_INSTRUCTIONS,
            },
        },
    }


def _needs_info_probability(response):
    """P(yes) of the needs-external-info question, or None when absent."""
    answer = (response.get("answers") or {}).get(NEEDS_INFO_ID)
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        return None
    try:
        return float(answer.get("noul"))
    except (TypeError, ValueError):
        return None


def parse_route(response):
    """'agent' or 'direct' from a Decisions API response, or None when the
    route answer is missing or not a valid choice. 'direct' becomes 'agent'
    when its probability is below DIRECT_MIN_PROBABILITY or the message
    likely needs outside information (NEEDS_INFO_MAX_PROBABILITY)."""
    if not isinstance(response, dict):
        return None
    answer = (response.get("answers") or {}).get(QUESTION_ID)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return None
    choice = str(answer.get("choice", "")).strip().lower()
    if choice not in (ROUTE_AGENT, ROUTE_DIRECT):
        return None
    if choice == ROUTE_AGENT:
        return choice
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict):
        try:
            if float(probabilities.get(ROUTE_DIRECT, 1.0)) < DIRECT_MIN_PROBABILITY:
                return ROUTE_AGENT
        except (TypeError, ValueError):
            pass
    needs_info = _needs_info_probability(response)
    if needs_info is not None and needs_info >= NEEDS_INFO_MAX_PROBABILITY:
        return ROUTE_AGENT
    return choice


def _timeout() -> int:
    try:
        from agent.lc import settings as lc_settings
        return lc_settings.llm_request_timeout()
    except Exception:
        return 45


def call_decisions_api(payload: dict, api_key: str) -> dict:
    """POST one request to OpenRouter's Decisions API; returns the JSON body."""
    req = urllib.request.Request(
        _DECISIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/nanoworker",
            "X-OpenRouter-Title": "NanoWorker",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e


def _log_usage(model, session_id, message_in_id, response, latency_ms) -> None:
    """Records the call's tokens and cost on the Costs page (stage 'decision')."""
    try:
        from agent import llm_usage

        with llm_usage.call_context(), llm_usage.usage_stage("decision"):
            llm_usage.set_call_info(provider="openrouter", model=model,
                                    session_id=session_id, message_in_id=message_in_id)
            llm_usage.log_llm_call("decisions", latency_ms=latency_ms,
                                   **llm_usage.usage_fields(response.get("usage")))
    except Exception as e:
        logger.debug("Decision usage not logged: %s", e)


def decide_route(message, cursor, session_id, message_in_id, tool_names=(), last_reply="",
                 images=0) -> str:
    """The route for one message: 'direct' only when the decision model says
    so clearly; 'agent' otherwise (feature off, no model, any failure)."""
    enabled, model = decision_settings()
    if not enabled or not model or not (message or "").strip():
        return ROUTE_AGENT
    if asks_for_agent(message):
        logger.info("Decision skipped for message %s: it asks for a search, fresh data or an "
                    "action; using the agent", message_in_id)
        return ROUTE_AGENT

    api_key = openrouter_api_key()
    if not api_key:
        logger.warning("Decision model %s skipped: no OpenRouter API key; using the agent", model)
        return ROUTE_AGENT

    payload = build_decision_request(model, message, tool_names, last_reply, images)
    started = time.monotonic()
    try:
        response = call_decisions_api(payload, api_key)
    except Exception as e:
        logger.warning("Decision model %s failed (%s); using the agent", model, e)
        return ROUTE_AGENT
    latency_ms = int((time.monotonic() - started) * 1000)
    _log_usage(model, session_id, message_in_id, response, latency_ms)

    route = parse_route(response)
    if route is None:
        logger.warning("Decision model %s gave no valid route: %r; using the agent",
                       model, json.dumps(response)[:300])
        return ROUTE_AGENT
    answer = (response.get("answers") or {}).get(QUESTION_ID) or {}
    logger.info("Decision model %s routed message %s to %s (route probabilities %s, "
                "needs outside info %s) in %dms", model, message_in_id, route,
                answer.get("probabilities"), _needs_info_probability(response), latency_ms)
    return route


def _price_per_million(value):
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def _fetch_decision_models() -> list:
    req = urllib.request.Request(_DECISION_MODELS_URL, headers={"User-Agent": "NanoWorker"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    models = []
    for m in data.get("data") or []:
        model_id = m.get("id")
        if not model_id:
            continue
        outputs = (m.get("architecture") or {}).get("output_modalities") or []
        endpoints = m.get("endpoints") or []
        # Only models the Decisions API can call (some serve extractions only).
        if endpoints:
            if "/api/alpha/decisions" not in endpoints:
                continue
        elif "decisions" not in outputs:
            continue
        pricing = m.get("pricing") or {}
        prompt_price = _price_per_million(pricing.get("prompt"))
        completion_price = _price_per_million(pricing.get("completion"))
        models.append({
            "id": OPENROUTER_PREFIX + model_id,
            "name": m.get("name") or model_id,
            "context_length": m.get("context_length"),
            "prompt_price": prompt_price if prompt_price is None or prompt_price >= 0 else None,
            "completion_price": completion_price if completion_price is None or completion_price >= 0 else None,
            "free": model_id.endswith(":free") or (prompt_price == 0 and completion_price == 0),
        })
    models.sort(key=lambda x: x["name"].lower())
    return models


def list_openrouter_models(force=False) -> list:
    """Decision models offered by OpenRouter, cached for an hour. Raises when
    the list cannot be fetched and nothing is cached."""
    with _models_lock:
        fresh = time.time() - _models_cache["at"] < _MODELS_TTL
        if _models_cache["models"] and fresh and not force:
            return _models_cache["models"]
        try:
            models = _fetch_decision_models()
        except Exception:
            if _models_cache["models"]:
                logger.warning("OpenRouter decision model list refresh failed; using the cached list", exc_info=True)
                return _models_cache["models"]
            raise
        _models_cache.update(at=time.time(), models=models)
        return models
