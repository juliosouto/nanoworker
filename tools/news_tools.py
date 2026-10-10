"""
News briefing tool.

Discovers fresh articles per configured source/topic via native RSS feeds
(falling back to Google News RSS) and returns a mandatory multi-step protocol
that instructs the agent to visit each article, extract title/source/date and
write a configurable-length summary before delivering the digest in the
channel where the user asked.

Per-tool settings (sources, topics, quantity, summary length) are stored in
the `config_data` column of `tools_config` and edited from the Tools
Management gear-icon modal. The schema below drives that modal.
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
# Settings schema (rendered by the Tools Management gear-icon modal)
# ---------------------------------------------------------------------------
TOOL_SETTINGS_SCHEMA = [
    {
        "key": "sources",
        "label": "Fontes de notícias",
        "type": "multi_select",
        "options": [
            "CNN Brasil",
            "CNN EUA",
            "Reuters",
            "BBC Brasil",
            "BBC News",
            "Gazeta do Povo",
            "Revista Oeste",
            "Folha de S.Paulo",
            "Estadão",
            "G1",
            "UOL",
            "The Verge",
            "TechCrunch",
        ],
        "default": [
            "CNN Brasil",
            "CNN EUA",
            "Reuters",
            "BBC Brasil",
            "Gazeta do Povo",
            "Revista Oeste",
        ],
    },
    {
        "key": "topics",
        "label": "Assuntos",
        "type": "multi_select",
        "options": [
            "Tecnologia",
            "Programação",
            "Startups",
            "Inteligência Artificial",
            "Negócios",
            "Economia",
            "Ciência",
            "Política",
            "Esportes",
        ],
        "default": [
            "Tecnologia",
            "Programação",
            "Startups",
        ],
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

# Native RSS feeds per source (tried first). Sources without a public feed
# (e.g. Reuters, UOL) are discovered via the Google News RSS fallback.
_SOURCE_FEEDS = {
    "CNN Brasil": ["https://www.cnnbrasil.com.br/feed/"],
    "CNN EUA": [
        "https://rss.cnn.com/rss/edition.rss",
        "https://rss.cnn.com/rss/edition_technology.rss",
    ],
    "BBC Brasil": ["https://feeds.bbci.co.uk/portuguese/rss.xml"],
    "BBC News": ["https://feeds.bbci.co.uk/news/rss.xml"],
    "Gazeta do Povo": ["https://www.gazetadopovo.com.br/rss/"],
    "Revista Oeste": ["https://revistaoeste.com/feed/"],
    "Folha de S.Paulo": ["https://feeds.folha.uol.com.br/emcimadahora/rss091.xml"],
    "Estadão": ["https://www.estadao.com.br/rss/ultimas.xml"],
    "G1": ["https://g1.globo.com/rss/g1/"],
    "UOL": [],
    "The Verge": ["https://www.theverge.com/rss/index.xml"],
    "TechCrunch": ["https://techcrunch.com/feed/"],
    "Reuters": [],
}

# Domains used by the Google News RSS fallback (`site:` operator).
_SOURCE_DOMAINS = {
    "CNN Brasil": "cnnbrasil.com.br",
    "CNN EUA": "cnn.com",
    "Reuters": "reuters.com",
    "BBC Brasil": "bbc.com",
    "BBC News": "bbc.com",
    "Gazeta do Povo": "gazetadopovo.com.br",
    "Revista Oeste": "revistaoeste.com",
    "Folha de S.Paulo": "folha.uol.com.br",
    "Estadão": "estadao.com.br",
    "G1": "g1.globo.com",
    "UOL": "uol.com.br",
    "The Verge": "theverge.com",
    "TechCrunch": "techcrunch.com",
}

# Keywords (PT + EN aliases) used to filter feed items by topic. Unknown /
# custom topics fall back to the topic name itself.
_TOPIC_KEYWORDS = {
    "Tecnologia": ["tecnologia", "technology", "tech", "digital"],
    "Programação": [
        "programação", "programacao", "código", "codigo", "code", "coding",
        "developer", "desenvolvedor", "dev", "software", "python",
        "javascript", "programador",
    ],
    "Startups": ["startup", "startups", "empreendedor", "empreendedorismo", "unicórnio"],
    "Inteligência Artificial": [
        "inteligência artificial", "inteligencia artificial", " ia ", " ai ",
        "machine learning", "gpt", "llm", "modelo de linguagem",
    ],
    "Negócios": ["negócio", "negocios", "negócios", "business", "mercado", "empresa", "companhia"],
    "Economia": ["economia", "economy", "inflação", "inflacao", "juros", "selic", "pib", "dólar", "dolar"],
    "Ciência": ["ciência", "ciencia", "science", "pesquisa", "cientista", "research", "estudo"],
    "Política": ["política", "politica", "politics", "governo", "eleição", "eleicao", "senado", "congresso", "presidente"],
    "Esportes": ["esporte", "esportes", "sports", "futebol", "jogo", "campeonato", "copa"],
}

# Network/runtime guards
_FEED_TIMEOUT = 10
_MAX_FETCHES = 20
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


def _google_news_rss_url(topic: str, domain: str) -> str:
    params = urlencode({
        "q": f"{topic} site:{domain}",
        "hl": "pt-BR",
        "gl": "BR",
        "ceid": "BR:pt-419",
    })
    return f"https://news.google.com/rss/search?{params}"


def _parse_list_arg(value, canonicalizer=None):
    """Parse a comma/newline separated runtime override into a clean list."""
    parts = [p.strip() for p in re.split(r"[,;\n]", value or "") if p.strip()]
    out = []
    for p in parts:
        canon = canonicalizer(p) if canonicalizer else p
        if canon and canon not in out:
            out.append(canon)
    return out or None


def _effective_config():
    """Merge the tool's stored settings with the schema defaults."""
    try:
        stored = (get_tool_config("fetch_news").get("settings") or {})
    except Exception as e:
        logger.warning("fetch_news: could not read stored settings: %s", e)
        stored = {}
    cfg = {}
    for field in TOOL_SETTINGS_SCHEMA:
        val = stored.get(field["key"], field.get("default"))
        if field["type"] == "multi_select":
            val = [v for v in val if v in field["options"]] or list(field.get("default", []))
        elif field["type"] == "number":
            try:
                val = int(val)
            except (TypeError, ValueError):
                val = field.get("default")
            val = max(field.get("min", 1), min(val, field.get("max", 9999)))
        cfg[field["key"]] = val
    return cfg


def _collect_candidates(sources, topics, max_news):
    """
    Discover candidate articles for every source × topic combination.

    Native RSS feeds are preferred; Google News RSS is the fallback when a
    source has no feed or the feed yielded nothing for a topic. Returns
    (selected, backups, diagnostics).
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
        native_items = []
        for feed_url in _SOURCE_FEEDS.get(source, []):
            if fetches >= _MAX_FETCHES:
                diagnostics.append(f"{source}: limite de consultas RSS atingido nesta execução")
                break
            fetches += 1
            try:
                native_items.extend(_parse_rss(_http_get(feed_url), source))
            except Exception as e:
                diagnostics.append(f"{source}: feed nativo indisponível ({e})")

        for topic in topics:
            matching = [it for it in native_items if _matches_topic(it, topic)]
            if len(matching) < _MIN_PER_COMBO:
                domain = _SOURCE_DOMAINS.get(source)
                if domain and fetches < _MAX_FETCHES:
                    fetches += 1
                    try:
                        gn_url = _google_news_rss_url(topic, domain)
                        gn_items = _parse_rss(_http_get(gn_url), source)
                        matching.extend(
                            it for it in gn_items
                            if _matches_topic(it, topic) or domain in it["url"]
                        )
                    except Exception as e:
                        diagnostics.append(f"{source} × {topic}: Google News RSS indisponível ({e})")
            add(matching)

    if not candidates and not diagnostics:
        diagnostics.append("Nenhuma notícia encontrada para as fontes/assuntos configurados.")

    # Tag matched topics, drop items that match nothing (native general feeds).
    for c in candidates:
        c["topics"] = [t for t in topics if _matches_topic(c, t)]
    candidates = [c for c in candidates if c["topics"]]

    # Most recent first, then round-robin across sources for diversity.
    candidates.sort(key=lambda c: c.get("date", ""), reverse=True)
    by_source = defaultdict(list)
    for c in candidates:
        by_source[c["source"]].append(c)

    selected = []
    remaining_sources = [s for s in sources if by_source.get(s)]
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


def _matches_topic(item: dict, topic: str) -> bool:
    keywords = _TOPIC_KEYWORDS.get(topic, [topic.lower()])
    haystack = f"{item.get('title', '')} {item.get('text_excerpt', '')}".lower()
    return any(kw in haystack for kw in keywords)


def _normalize_source(name: str):
    """Map a user-provided source name to its canonical spelling."""
    for known in _SOURCE_DOMAINS:
        if known.lower() == name.strip().lower():
            return known
    return None


def _build_mission(cfg, selected, backups, diagnostics):
    """Render the candidate list + the mandatory agent execution protocol."""
    payload = json.dumps({"selected": selected, "backups": backups}, ensure_ascii=False, indent=2)
    n = cfg["summary_chars"]
    m = cfg["max_news"]
    lines = [
        "=== NEWS BRIEFING MISSION ===",
        f"CONFIG: sources={cfg['sources']} | topics={cfg['topics']} | "
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
        "6) If an entire source failed (paywall, offline), mention it briefly at the "
        "end — never abort the digest for the remaining sources.",
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
    summary length default to the settings configured in Tools Management and
    can be overridden per call.

    Args:
        topics: Optional comma-separated topics to fetch instead of the
            configured ones (e.g. "Tecnologia,Startups"). Custom topics are
            accepted too.
        sources: Optional comma-separated sources to fetch instead of the
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
            override = _parse_list_arg(topics)
            if override:
                cfg["topics"] = override
        if sources:
            override = _parse_list_arg(sources, canonicalizer=_normalize_source)
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

