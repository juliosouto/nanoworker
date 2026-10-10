"""
News briefing tool.

Discovers fresh articles for every configured source/topic via native RSS
feeds (falling back to Google News RSS) and returns a mandatory multi-step
protocol that instructs the agent to visit each article, extract
title/source/date and write a configurable-length summary before delivering
the digest in the channel where the user asked.

Sources and topics are FULLY USER-MANAGED from the Tools Management card:
each source is {name, domain, feed} and each topic is {name, keywords}.
They are stored in the `config_data` column of `tools_config`; the schema
below seeds the card and provides the initial defaults.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from database import get_tool_config
from utils.security_utils import require_permission

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in presets — seed defaults and resolution for runtime overrides.
# Anything stored in config_data fully replaces the defaults, and the user
# can add/remove sources and topics freely from the card.
# ---------------------------------------------------------------------------
_PRESET_SOURCES = {
    "CNN Brasil": {"domain": "cnnbrasil.com.br", "feed": "https://www.cnnbrasil.com.br/feed/"},
    "CNN EUA": {"domain": "cnn.com", "feed": "https://rss.cnn.com/rss/edition.rss"},
    "Reuters": {"domain": "reuters.com"},
    "BBC Brasil": {"domain": "bbc.com", "feed": "https://feeds.bbci.co.uk/portuguese/rss.xml"},
    "BBC News": {"domain": "bbc.com", "feed": "https://feeds.bbci.co.uk/news/rss.xml"},
    "Gazeta do Povo": {"domain": "gazetadopovo.com.br", "feed": "https://www.gazetadopovo.com.br/rss/"},
    "Revista Oeste": {"domain": "revistaoeste.com", "feed": "https://revistaoeste.com/feed/"},
    "Folha de S.Paulo": {"domain": "folha.uol.com.br", "feed": "https://feeds.folha.uol.com.br/emcimadahora/rss091.xml"},
    "Estadão": {"domain": "estadao.com.br", "feed": "https://www.estadao.com.br/rss/ultimas.xml"},
    "G1": {"domain": "g1.globo.com", "feed": "https://g1.globo.com/rss/g1/"},
    "UOL": {"domain": "uol.com.br"},
    "The Verge": {"domain": "theverge.com", "feed": "https://www.theverge.com/rss/index.xml"},
    "TechCrunch": {"domain": "techcrunch.com", "feed": "https://techcrunch.com/feed/"},
}

_PRESET_TOPICS = {
    "Tecnologia": ["tecnologia", "technology", "tech", "digital"],
    "Programação": ["programação", "programacao", "código", "codigo", "code", "coding",
                    "developer", "desenvolvedor", "dev", "software", "python", "javascript",
                    "programador"],
    "Startups": ["startup", "startups", "empreendedor", "empreendedorismo", "unicórnio"],
    "Inteligência Artificial": ["inteligência artificial", "inteligencia artificial", " ia ",
                                " ai ", "machine learning", "gpt", "llm", "modelo de linguagem"],
    "Negócios": ["negócio", "negocios", "negócios", "business", "mercado", "empresa", "companhia"],
    "Economia": ["economia", "economy", "inflação", "inflacao", "juros", "selic", "pib", "dólar", "dolar"],
    "Ciência": ["ciência", "ciencia", "science", "pesquisa", "cientista", "research", "estudo"],
    "Política": ["política", "politica", "politics", "governo", "eleição", "eleicao", "senado",
                 "congresso", "presidente"],
    "Esportes": ["esporte", "esportes", "sports", "futebol", "jogo", "campeonato", "copa"],
}

# Default sources/topics seeded into the card on first use.
_DEFAULT_SOURCES = [
    {"name": "CNN Brasil", "domain": "cnnbrasil.com.br", "feed": "https://www.cnnbrasil.com.br/feed/"},
    {"name": "CNN EUA", "domain": "cnn.com", "feed": "https://rss.cnn.com/rss/edition.rss"},
    {"name": "Reuters", "domain": "reuters.com", "feed": ""},
    {"name": "BBC Brasil", "domain": "bbc.com", "feed": "https://feeds.bbci.co.uk/portuguese/rss.xml"},
    {"name": "Gazeta do Povo", "domain": "gazetadopovo.com.br", "feed": "https://www.gazetadopovo.com.br/rss/"},
    {"name": "Revista Oeste", "domain": "revistaoeste.com", "feed": "https://revistaoeste.com/feed/"},
]
_DEFAULT_TOPICS = [
    {"name": name, "keywords": list(_PRESET_TOPICS[name])}
    for name in ("Tecnologia", "Programação", "Startups")
]

# ---------------------------------------------------------------------------
# Settings schema (rendered by the Tools Management gear-icon modal).
# `dynamic_list` fields let the user add/remove rows entirely from the card.
# ---------------------------------------------------------------------------
TOOL_SETTINGS_SCHEMA = [
    {
        "key": "sources",
        "label": "Fontes de notícias",
        "type": "dynamic_list",
        "add_label": "+ Adicionar fonte",
        "item_fields": [
            {"key": "name", "label": "Nome", "placeholder": "Ex.: CNN Brasil", "width": "34%"},
            {"key": "domain", "label": "Domínio", "placeholder": "Ex.: cnnbrasil.com.br", "width": "33%"},
            {"key": "feed", "label": "RSS (opcional)", "placeholder": "Ex.: https://site.com/feed/", "width": "33%"},
        ],
        "default": _DEFAULT_SOURCES,
    },
    {
        "key": "topics",
        "label": "Assuntos",
        "type": "dynamic_list",
        "add_label": "+ Adicionar assunto",
        "item_fields": [
            {"key": "name", "label": "Assunto", "placeholder": "Ex.: Tecnologia", "width": "30%"},
            {"key": "keywords", "label": "Palavras-chave (separadas por vírgula)",
             "placeholder": "Ex.: tecnologia, technology, tech", "list": True, "width": "70%"},
        ],
        "default": _DEFAULT_TOPICS,
    },
    {
        "key": "max_news",
        "label": "Quantidade de notícias no pacote final",
        "type": "number",
        "min": 1,
        "max": 30,
        "default": 6,
    },
    {
        "key": "summary_chars",
        "label": "Tamanho do resumo (caracteres)",
        "type": "number",
        "min": 100,
        "max": 1000,
        "default": 300,
    },
]

# Network/runtime guards
_FEED_TIMEOUT = 10
_MAX_FETCHES = 30
_MIN_PER_COMBO = 2
_EXCERPT_MAX_CHARS = 2500
_FULL_TEXT_MIN_CHARS = 500


def _http_get(url: str) -> str:
    """Fetch a URL as text with browser impersonation (curl_cffi)."""
    response = curl_requests.get(url, impersonate="chrome", timeout=_FEED_TIMEOUT)
    return response.text or ""


def _html_to_text(raw: str) -> str:
    """Strip HTML tags/entities from a feed payload into plain text."""
    if not raw:
        return ""
    soup = BeautifulSoup(unescape(raw), "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def _normalize_date(raw: str) -> str:
    """Normalize an RFC-2822 pubDate into 'YYYY-MM-DD HH:MM UTC'."""
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return raw.strip()


def _tag_text(item, tag: str) -> str:
    """Text of a direct child tag of an RSS <item> (no namespaces)."""
    el = item.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _encoded_content(item) -> str:
    """HTML of <content:encoded> when the feed provides full article text."""
    for el in item:
        if el.tag.endswith("}encoded") or el.tag == "content:encoded":
            return el.text or ""
    return ""


def _parse_rss(xml_text: str, source_name: str):
    """Parse an RSS 2.0 feed into candidate dicts (never raises)."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.debug("RSS parse failed for %s: %s", source_name, e)
        return items

    for item in root.iter("item"):
        title = _tag_text(item, "title")
        if not title:
            continue
        url = _tag_text(item, "link")
        clean = _html_to_text(_encoded_content(item) or _tag_text(item, "description"))
        items.append({
            "title": title,
            "source": source_name,
            "date": _normalize_date(_tag_text(item, "pubDate")),
            "url": url,
            "full_text_available": len(clean) >= _FULL_TEXT_MIN_CHARS,
            "text_excerpt": clean[:_EXCERPT_MAX_CHARS] if len(clean) >= 300 else "",
        })
    return items


def _google_news_rss_url(topic: str, domain: str = "") -> str:
    """Google News RSS search URL; `site:domain` only when a domain is set."""
    query = f"{topic} site:{domain}" if domain else topic
    params = urlencode({"q": query, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
    return f"https://news.google.com/rss/search?{params}"


def _clean_str(value) -> str:
    return str(value).strip() if value else ""


def _split_keywords(raw) -> list:
    """Split a comma/semicolon/newline separated keyword string."""
    if isinstance(raw, (list, tuple)):
        return [_clean_str(k) for k in raw if _clean_str(k)]
    return [p.strip() for p in re.split(r"[,;\n]", raw or "") if p.strip()]


def _preset_source_lookup(name: str) -> str:
    """Return the canonical preset name (case-insensitive) or ''."""
    for known in _PRESET_SOURCES:
        if known.lower() == name.strip().lower():
            return known
    return ""


def _preset_topic_lookup(name: str):
    """Return (canonical_name, keywords) for a preset topic or None."""
    for known, keywords in _PRESET_TOPICS.items():
        if known.lower() == name.strip().lower():
            return known, list(keywords)
    return None


def _coerce_source(value):
    """
    Normalize a source entry into {name, domain, feed}.

    Accepts a full dict (from the card), or a legacy plain-string name which
    is resolved against the built-in presets. Returns None when unusable.
    """
    if isinstance(value, dict):
        raw_name = _clean_str(value.get("name"))
        if not raw_name:
            return None
        preset = _PRESET_SOURCES.get(_preset_source_lookup(raw_name), {})
        return {
            "name": _preset_source_lookup(raw_name) or raw_name,
            "domain": _clean_str(value.get("domain")) or preset.get("domain", ""),
            "feed": _clean_str(value.get("feed")) or preset.get("feed", ""),
        }
    raw_name = _clean_str(value)
    if not raw_name:
        return None
    canonical = _preset_source_lookup(raw_name)
    preset = _PRESET_SOURCES.get(canonical, {})
    return {
        "name": canonical or raw_name,
        "domain": preset.get("domain", ""),
        "feed": preset.get("feed", ""),
    }


def _coerce_topic(value):
    """
    Normalize a topic entry into {name, keywords}.

    Accepts a dict (from the card), or a legacy plain-string name resolved
    against the built-in presets. Returns None when unusable.
    """
    if isinstance(value, dict):
        raw_name = _clean_str(value.get("name"))
        if not raw_name:
            return None
        keywords = _split_keywords(value.get("keywords"))
        preset = _preset_topic_lookup(raw_name)
        if preset and not keywords:
            keywords = preset[1]
            raw_name = preset[0]
        return {"name": raw_name, "keywords": keywords or [raw_name.lower()]}
    raw_name = _clean_str(value)
    if not raw_name:
        return None
    preset = _preset_topic_lookup(raw_name)
    if preset:
        return {"name": preset[0], "keywords": preset[1]}
    return {"name": raw_name, "keywords": [raw_name.lower()]}


def _matches_topic(item: dict, topic) -> bool:
    """
    True when the item matches a topic. `topic` is normally a dict
    {name, keywords}; legacy plain strings are coerced on the fly.
    """
    if isinstance(topic, dict):
        keywords = topic.get("keywords") or [topic.get("name", "").lower()]
    else:
        coerced = _coerce_topic(topic)
        keywords = coerced["keywords"] if coerced else []
    haystack = f"{item.get('title', '')} {item.get('text_excerpt', '')}".lower()
    return any(kw and kw in haystack for kw in keywords)


def _effective_config():
    """
    Merge the tool's stored settings with the schema defaults.

    An explicitly stored empty list is respected (the user removed every
    source/topic on purpose); the defaults only apply when the key is absent.
    """
    try:
        stored = (get_tool_config("fetch_news").get("settings") or {})
    except Exception as e:
        logger.warning("fetch_news: could not read stored settings: %s", e)
        stored = {}

    cfg = {}
    for field in TOOL_SETTINGS_SCHEMA:
        key = field["key"]
        ftype = field["type"]
        raw = stored[key] if key in stored else field.get("default")

        if ftype == "dynamic_list":
            coerce = _coerce_source if key == "sources" else _coerce_topic
            entries, seen = [], set()
            for value in (raw or []):
                entry = coerce(value)
                if entry and entry["name"].lower() not in seen:
                    seen.add(entry["name"].lower())
                    entries.append(entry)
            cfg[key] = entries
        elif ftype == "number":
            try:
                val = int(raw)
            except (TypeError, ValueError):
                val = field.get("default")
            cfg[key] = max(field.get("min", 1), min(val, field.get("max", 9999)))
        else:
            cfg[key] = raw
    return cfg


def _resolve_entries(names, configured, coerce):
    """Resolve runtime-override names against configured entries + presets."""
    resolved = []
    for name in names:
        match = next(
            (e for e in configured if e["name"].lower() == name.lower()), None
        )
        if match is None:
            match = coerce(name)
        if match and match not in resolved:
            resolved.append(match)
    return resolved


def _collect_candidates(sources, topics, max_news):
    """
    Discover candidate articles for every source × topic combination.

    Each source may declare a native `feed` and/or a `domain` (used for the
    Google News RSS fallback). Sources with neither are skipped with a note.
    Returns (selected, backups, diagnostics).
    """
    diagnostics = []
    candidates = []
    seen_urls, seen_titles = set(), set()
    fetches = 0

    def add(items):
        for it in items:
            url_key = it.get("url") or ""
            title_key = re.sub(r"\W+", "", it.get("title", "").lower())
            if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles):
                continue
            if url_key:
                seen_urls.add(url_key)
            if title_key:
                seen_titles.add(title_key)
            candidates.append(it)

    for source in sources:
        name = source.get("name") or source.get("domain") or "(fonte sem nome)"
        domain = source.get("domain") or ""
        feed = source.get("feed") or ""

        if not domain and not feed:
            diagnostics.append(f"{name}: nenhum domínio ou RSS configurado — fonte ignorada")
            continue

        native_items = []
        if feed:
            if fetches >= _MAX_FETCHES:
                diagnostics.append(f"{name}: limite de consultas RSS atingido nesta execução")
            else:
                fetches += 1
                try:
                    native_items.extend(_parse_rss(_http_get(feed), name))
                except Exception as e:
                    diagnostics.append(f"{name}: feed nativo indisponível ({e})")

        for topic in topics:
            matching = [it for it in native_items if _matches_topic(it, topic)]
            if len(matching) < _MIN_PER_COMBO and domain and fetches < _MAX_FETCHES:
                fetches += 1
                try:
                    gn_url = _google_news_rss_url(topic["name"], domain)
                    gn_items = _parse_rss(_http_get(gn_url), name)
                    matching.extend(
                        it for it in gn_items
                        if _matches_topic(it, topic) or domain in it["url"]
                    )
                except Exception as e:
                    diagnostics.append(f"{name} × {topic['name']}: Google News RSS indisponível ({e})")
            add(matching)

    if not candidates and not diagnostics:
        diagnostics.append("Nenhuma notícia encontrada para as fontes/assuntos configurados.")

    # Tag matched topics, drop items that match nothing (native general feeds).
    for c in candidates:
        c["topics"] = [t["name"] for t in topics if _matches_topic(c, t)]
    candidates = [c for c in candidates if c["topics"]]

    # Most recent first, then round-robin across sources for diversity.
    candidates.sort(key=lambda c: c.get("date", ""), reverse=True)
    by_source = defaultdict(list)
    for c in candidates:
        by_source[c["source"]].append(c)

    selected = []
    source_names = [s.get("name") or s.get("domain") or "" for s in sources]
    remaining_sources = [s for s in source_names if by_source.get(s)]
    while len(selected) < max_news and remaining_sources:
        for s in list(remaining_sources):
            if not by_source[s]:
                remaining_sources.remove(s)
                continue
            selected.append(by_source[s].pop(0))
            if len(selected) >= max_news:
                break

    backups = candidates[: 2 * max_news]
    return selected, backups, diagnostics


def _build_mission(cfg, selected, backups, diagnostics):
    """Render the candidate list + the mandatory agent execution protocol."""
    payload = json.dumps({"selected": selected, "backups": backups}, ensure_ascii=False, indent=2)
    n = cfg["summary_chars"]
    m = cfg["max_news"]
    source_names = [s["name"] for s in cfg["sources"]]
    topic_names = [t["name"] for t in cfg["topics"]]
    lines = [
        "=== NEWS BRIEFING MISSION ===",
        f"CONFIG: sources={source_names} | topics={topic_names} | "
        f"max_news={m} | summary_chars={n}",
        "",
        "STEP 1 — CANDIDATES (already discovered via RSS; do NOT run web searches "
        "yourself, this JSON is your article list):",
        payload,
        "",
        "MANDATORY EXECUTION PROTOCOL — execute every step, in order:",
        "1) For EACH item in 'selected': if 'full_text_available' is false OR "
        "'text_excerpt' is missing/too short, you MUST open the article with "
        "extract_webpage_text(url) (fallback: http_request GET). If the url is a "
        "news.google.com redirect link, extract_webpage_text resolves it via its "
        "browser fallback — that is expected. When 'full_text_available' is true, "
        "you may summarize directly from 'text_excerpt' (only open the page if the "
        "excerpt is clearly truncated).",
        "2) From the article (or text_excerpt), extract EXACTLY these fields: "
        "title, source, date. If the page shows no date, keep the candidate's date.",
        f"3) Write a summary of AT MOST {n} characters for each item — count the "
        "characters and never exceed the limit.",
        "4) Curate: drop duplicates and cap the digest at the items you completed; "
        "if an item is unreachable, replace it from 'backups' or simply deliver "
        "fewer items with an honest note. Prefer the most recent items.",
        "5) DELIVER the complete digest in the SAME channel where the user made the "
        "request (reply here — do NOT send it elsewhere), in the user's language, "
        "using this exact format per item:",
        "   📰 <title> — <source> — <date>",
        f"   <summary (≤ {n} chars)>",
        "   🔗 <url>",
        "6) If an entire source failed (paywall, offline, or was not configured "
        "with a domain/RSS), mention it briefly at the end — never abort the "
        "digest for the remaining sources.",
        "",
        "FINAL SELF-CHECK before delivering (every box must be true):",
        "[ ] every item has title, source, date and a summary",
        f"[ ] every summary is ≤ {n} characters",
        "[ ] digest delivered in the requesting channel, in the user's language",
    ]
    if diagnostics:
        lines += ["", "DISCOVERY NOTES (issues found during RSS discovery):"]
        lines += [f"- {d}" for d in diagnostics]
    return "\n".join(lines)


@require_permission('PERM_WEB_SEARCH')
def fetch_news(topics: str = "", sources: str = "", max_news: int = 0, summary_chars: int = 0) -> str:
    """
    Builds an up-to-date multi-source news briefing. Discovers articles via RSS
    (title, source and date guaranteed) and returns the mandatory multi-step
    protocol the agent must follow to visit each article, summarize it and
    deliver the digest in the requesting channel. Sources/topics/quantity/
    summary length default to the settings configured in Tools Management
    (where sources and topics can be freely added/removed) and can be
    overridden per call.

    Args:
        topics: Optional comma-separated topic names to fetch instead of the
            configured ones (e.g. "Tecnologia,Startups"). Names are resolved
            against the configured topics and the built-in presets; unknown
            names become custom topics matched by their own name.
        sources: Optional comma-separated source names to fetch instead of the
            configured ones (e.g. "CNN Brasil,Reuters").
        max_news: Optional override for how many news items the digest may contain.
        summary_chars: Optional override for the per-item summary character limit.

    Returns:
        str: A "NEWS BRIEFING MISSION" containing the discovered candidates and
        the mandatory execution protocol, or an error message.
    """
    try:
        cfg = _effective_config()

        if topics:
            names = _split_keywords(topics)
            override = _resolve_entries(names, cfg["topics"], _coerce_topic)
            if override:
                cfg["topics"] = override
        if sources:
            names = _split_keywords(sources)
            override = _resolve_entries(names, cfg["sources"], _coerce_source)
            if override:
                cfg["sources"] = override
        if max_news:
            cfg["max_news"] = max(1, min(int(max_news), 30))
        if summary_chars:
            cfg["summary_chars"] = max(100, min(int(summary_chars), 1000))

        selected, backups, diagnostics = _collect_candidates(
            cfg["sources"], cfg["topics"], cfg["max_news"]
        )
        return _build_mission(cfg, selected, backups, diagnostics)
    except Exception as e:
        logger.exception("fetch_news failed")
        return f"Error building news briefing: {e}"

