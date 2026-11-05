"""
News briefing tool.

Performs a reliable, deterministic multi-step news briefing pipeline:
1. Search: Queries live web/news search for configured sources and topics (no RSS dependency).
2. Scrape: Extracts real full-text content from each discovered article.
3. Sub-LLM Summarize: Invokes the model internally to summarize each article to the target length.
4. Curate & Format: Assembles the final briefing package with standard metadata and links.

Sources and topics are FULLY USER-MANAGED from the Tools Management card:
each source is {name, domain} and each topic is {name, keywords}.
"""

import contextvars
import json
import logging
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List, Dict, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from ddgs import DDGS
import trafilatura

from database import get_tool_config, get_db
from utils.security_utils import require_permission

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in presets — seed defaults and resolution for runtime overrides.
# ---------------------------------------------------------------------------
_PRESET_SOURCES = {
    "CNN Brasil": {"domain": "cnnbrasil.com.br"},
    "CNN EUA": {"domain": "cnn.com"},
    "Reuters": {"domain": "reuters.com"},
    "BBC Brasil": {"domain": "bbc.com/portuguese"},
    "BBC News": {"domain": "bbc.com/news"},
    "Gazeta do Povo": {"domain": "gazetadopovo.com.br"},
    "Revista Oeste": {"domain": "revistaoeste.com"},
    "Folha de S.Paulo": {"domain": "folha.uol.com.br"},
    "Estadão": {"domain": "estadao.com.br"},
    "G1": {"domain": "g1.globo.com"},
    "UOL": {"domain": "uol.com.br"},
    "The Verge": {"domain": "theverge.com"},
    "TechCrunch": {"domain": "techcrunch.com"},
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

_DEFAULT_SOURCES = [
    {"name": "G1", "domain": "g1.globo.com"},
    {"name": "CNN Brasil", "domain": "cnnbrasil.com.br"},
    {"name": "BBC Brasil", "domain": "bbc.com/portuguese"},
    {"name": "Reuters", "domain": "reuters.com"},
    {"name": "Gazeta do Povo", "domain": "gazetadopovo.com.br"},
    {"name": "Revista Oeste", "domain": "revistaoeste.com"},
]
_DEFAULT_TOPICS = [
    {"name": name, "keywords": list(_PRESET_TOPICS[name])}
    for name in ("Tecnologia", "Programação", "Startups")
]

TOOL_SETTINGS_SCHEMA = [
    {
        "key": "sources",
        "label": "Fontes de notícias",
        "type": "dynamic_list",
        "add_label": "+ Adicionar fonte",
        "item_fields": [
            {"key": "name", "label": "Nome", "placeholder": "Ex.: CNN Brasil", "width": "50%"},
            {"key": "domain", "label": "Domínio", "placeholder": "Ex.: cnnbrasil.com.br", "width": "50%"},
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

_ARTICLE_SCRAPE_TIMEOUT = 12
_MAX_SEARCH_CANDIDATES = 20
_PARALLEL_WORKERS = 6
_LISTING_TIMEOUT = 15
_MIN_HEADLINE_WORDS = 4
# Paths of a site's home page that are not news articles (tags, videos, calculators, special pages, ...).
_NON_NEWS_PARTS = (
    "/tag/", "/tags/", "/video", "/podcast", "/calculadora", "/especiais", "/guia", "/login",
    "/assine", "/newsletter", "/curso", "/lp/", "/autor/", "/author/", "/busca", "/search",
    "/conheca-a-gazeta", "/cafe-com-a-gazeta",
)


def _clean_str(value) -> str:
    return str(value).strip() if value else ""


def _split_keywords(raw) -> list:
    if isinstance(raw, (list, tuple)):
        return [_clean_str(k) for k in raw if _clean_str(k)]
    return [p.strip() for p in re.split(r"[,;\n]", raw or "") if p.strip()]


def _preset_source_lookup(name: str) -> str:
    for known in _PRESET_SOURCES:
        if known.lower() == name.strip().lower():
            return known
    return ""


def _preset_topic_lookup(name: str):
    for known, keywords in _PRESET_TOPICS.items():
        if known.lower() == name.strip().lower():
            return known, list(keywords)
    return None


def _coerce_source(value):
    if isinstance(value, dict):
        raw_name = _clean_str(value.get("name"))
        if not raw_name:
            return None
        preset = _PRESET_SOURCES.get(_preset_source_lookup(raw_name), {})
        return {
            "name": _preset_source_lookup(raw_name) or raw_name,
            "domain": _clean_str(value.get("domain")) or preset.get("domain", ""),
        }
    raw_name = _clean_str(value)
    if not raw_name:
        return None
    canonical = _preset_source_lookup(raw_name)
    if not canonical and _looks_like_domain(raw_name):
        # A site given by its address ("poder360.com.br", "https://g1.globo.com/"):
        # search only inside it, under the preset name when it is a known one.
        domain = re.sub(r"^(https?://)?(www\.)?", "", raw_name.lower()).rstrip("/")
        known = next((n for n, p in _PRESET_SOURCES.items() if p["domain"] == domain), "")
        return {"name": known or domain, "domain": domain}
    preset = _PRESET_SOURCES.get(canonical, {})
    return {
        "name": canonical or raw_name,
        "domain": preset.get("domain", ""),
    }


def _looks_like_domain(value: str) -> bool:
    return bool(re.fullmatch(r"(https?://)?[\w-]+(\.[\w-]+)+(/[\w./-]*)?", value.strip(), re.IGNORECASE))


def _coerce_topic(value):
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


def _effective_config() -> dict:
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


# ===========================================================================
# STEP 1: Web Search for News Candidates (Live, No RSS dependency)
# ===========================================================================
def _fold(text: str) -> str:
    """Lowercase text without accents, for keyword matching ("Política" matches "politica")."""
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def _site_listing(domain: str) -> List[Dict[str, str]]:
    """
    Article links of a site's home page (or of a section given as domain/path), in page order.
    One plain download and HTML parse, no JavaScript: returns [] when the page cannot be read.
    """
    clean = re.sub(r"^https?://", "", domain or "").strip().strip("/")
    if not clean:
        return []
    host, _, prefix = clean.partition("/")
    prefix = "/" + prefix if prefix else ""
    host = host.lower().removeprefix("www.")
    try:
        resp = curl_requests.get(f"https://{clean}", impersonate="chrome146", timeout=_LISTING_TIMEOUT, allow_redirects=True)
        soup = BeautifulSoup(resp.text or "", "html.parser")
    except Exception as e:
        logger.debug("Listing download failed for %s: %s", domain, e)
        return []

    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        url = urljoin(resp.url, a["href"]).split("#")[0].split("?")[0]
        netloc = re.sub(r"^https?://", "", url).split("/")[0].lower().removeprefix("www.")
        path = re.sub(r"^https?://[^/]+", "", url)
        if not (netloc == host or netloc.endswith("." + host)) or not path.startswith(prefix):
            continue
        if netloc.startswith("especiais.") or any(part in path.lower() for part in _NON_NEWS_PARTS):
            continue
        if len([seg for seg in path.split("/") if seg]) < 2 or len(path) < 25 or url in seen:
            continue
        seen.add(url)
        title = " ".join(a.get_text(" ").split())
        if len(title) < 15:
            # Anchors often hold only an icon or "leia mais": use the URL slug instead.
            slug = [seg for seg in path.split("/") if seg][-1]
            title = re.sub(r"\.\w+$", "", slug).replace("-", " ").strip()
        # Headlines have several words; section names and bare slugs have one or two.
        if len(title.split()) < _MIN_HEADLINE_WORDS:
            continue
        items.append({"title": title, "url": url})
    return items


def _listing_matches(items: List[Dict[str, str]], keywords: List[str]) -> List[Dict[str, str]]:
    """Listing items whose title or URL contains one of the topic keywords."""
    folded = [kw for kw in (_fold(k).strip() for k in keywords) if kw]
    if not folded:
        return []
    return [item for item in items if any(kw in _fold(item["title"] + " " + item["url"]) for kw in folded)]


def _search_one(query: str) -> list:
    """DuckDuckGo News for ``query``, falling back to text search when the news tab is empty."""
    try:
        with DDGS() as ddgs:
            news_results = list(ddgs.news(query, max_results=5))
            if not news_results:
                news_results = list(ddgs.text(query, max_results=5))
        return news_results
    except Exception as e:
        logger.debug("DDG search failed for query %r: %s", query, e)
        return []


def _search_news_candidates(sources: List[Dict[str, str]], topics: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    """
    Finds candidate articles for each source and topic.

    A source with a domain is read from its home page: the links whose title or
    URL match the topic keywords are used. When the home page has none, the
    source and topic are searched on DuckDuckGo, as before. The downloads run in
    parallel; the candidates keep the source/topic order.
    Returns a list of candidate dicts with url, title, source, and rough date/snippet.
    """
    with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
        listings = list(pool.map(lambda src: _site_listing(src.get("domain") or ""), sources))

    plan = []  # (source_name, topic_name, matched_items or None, query)
    for source, listing in zip(sources, listings):
        source_name = source.get("name") or "News"
        domain = source.get("domain") or ""

        clean_domain = re.sub(r"^https?://", "", domain).split("/")[0].strip()
        for topic in topics:
            topic_name = topic.get("name") if isinstance(topic, dict) else str(topic)
            keywords = (topic.get("keywords") if isinstance(topic, dict) else None) or [topic_name]
            matched = _listing_matches(listing, keywords)
            if matched:
                plan.append((source_name, topic_name, matched, None))
                continue
            query = f"{topic_name} site:{clean_domain}" if clean_domain else f"{topic_name} {source_name}"
            plan.append((source_name, topic_name, None, query))

    queries = [p[3] for p in plan if p[3]]
    with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
        results = iter(pool.map(_search_one, queries))

    candidates = []
    seen_urls = set()
    seen_titles = set()
    for source_name, topic_name, matched, query in plan:
        if matched is not None:
            found = [{"url": m["url"], "title": m["title"], "body": "", "date": ""} for m in matched]
        else:
            found = next(results)
        for item in found:
            url = item.get("url") or item.get("href") or ""
            title = item.get("title") or ""
            snippet = item.get("body") or ""
            date = item.get("date") or ""

            if not url or not title:
                continue

            norm_title = re.sub(r"\W+", "", title.lower())
            if url in seen_urls or norm_title in seen_titles:
                continue

            seen_urls.add(url)
            seen_titles.add(norm_title)

            candidates.append({
                "title": title,
                "url": url,
                "source": source_name,
                "topic": topic_name,
                "date": date,
                "snippet": snippet,
            })

    return candidates


# ===========================================================================
# STEP 2: Extract Full Webpage Text (Scraping)
# ===========================================================================
def _extract_article_text(url: str) -> str:
    """
    Extracts main article text from one download: trafilatura first, BeautifulSoup paragraphs as fallback.
    """
    if not url:
        return ""
    try:
        resp = curl_requests.get(url, impersonate="chrome146", timeout=_ARTICLE_SCRAPE_TIMEOUT)
        html = resp.text or ""
    except Exception as e:
        logger.debug("Article download failed for %s: %s", url, e)
        return ""

    try:
        text = trafilatura.extract(html)
        if text and len(text.strip()) >= 80:
            return text.strip()
    except Exception as e:
        logger.debug("Trafilatura extract failed for %s: %s", url, e)

    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        paragraphs = [p.get_text(" ").strip() for p in soup.find_all("p") if len(p.get_text(" ").strip()) > 30]
        full_text = "\n\n".join(paragraphs)
        if len(full_text) >= 80:
            return full_text
    except Exception as e:
        logger.debug("BS4 fallback failed for %s: %s", url, e)

    return ""


# ===========================================================================
# STEP 3: Internal Sub-LLM Summarization (Deterministic Execution)
# ===========================================================================
def _summarize_article_with_llm(title: str, text: str, source: str, target_chars: int) -> str:
    """
    Invokes the LLM router to generate a strict, accurate summary of the scraped article text.
    Falls back to a truncated lead extract if the LLM call fails.
    """
    prompt = (
        f"Você é um redator de notícias. Escreva um resumo informativo e direto da matéria abaixo.\n\n"
        f"Título: {title}\n"
        f"Fonte: {source}\n"
        f"Texto da matéria:\n{text[:4000]}\n\n"
        f"Diretrizes obrigatórias:\n"
        f"- Resumo de aproximadamente {target_chars} caracteres (meta: {target_chars} caracteres).\n"
        f"- Destaque os fatos principais: o que aconteceu, quem, quando, onde e impacto.\n"
        f"- Responda APENAS com o texto do resumo, sem títulos, sem cabeçalhos e sem introduções."
    )

    try:
        from agent.lc import settings as lc_settings
        from agent.llm_router import route_llm_call

        model = lc_settings.summarizer_model()
        if not model:
            # Check default worker or enabled model in database
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT worker_model FROM workers_config WHERE is_default = 1 LIMIT 1")
            row = c.fetchone()
            if row and row["worker_model"]:
                model = row["worker_model"]
            else:
                c.execute("SELECT model_name FROM llm_config WHERE text_output = 1 AND enabled = 1 LIMIT 1")
                row = c.fetchone()
                model = row["model_name"] if row else None
            conn.close()

        if model:
            conn = get_db()
            cursor = conn.cursor()
            summary = route_llm_call(
                model_name=model,
                history=[],
                config_kwargs={"temperature": 0.2},
                content=prompt,
                cursor=cursor,
                session_id="news_internal",
                message_in_id="news_step3",
                is_ide=True,
                on_complete=None,
                summarize=True,
            )
            conn.close()
            if summary and len(summary.strip()) > 30:
                return summary.strip()
    except Exception as e:
        logger.warning("Internal LLM summarization failed: %s", e)

    # Fallback to pure extractive summary if LLM is unavailable
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:target_chars] + "..." if len(clean) > target_chars else clean


# ===========================================================================
# STEP 4: End-to-End Orchestrator
# ===========================================================================
@require_permission('PERM_WEB_SEARCH')
def fetch_news(topics: str = "", sources: str = "", max_news: int = 0, summary_chars: int = 0) -> str:
    """
    Gets recent news as a ready-made digest (title, source, date, summary, link) to send as is; slow, so call it ONCE per request with all filters, and when the user names a site or subject pass sources (prefer the domain, e.g. 'g1.globo.com') and topics (e.g. 'principais notícias do dia'), otherwise it uses the configured ones (by default tech topics).

    Args:
        topics: Comma-separated subjects to search for, e.g. "principais notícias
            do dia" or "Economia,Política". Empty = the configured topics
            (by default Tecnologia, Programação and Startups), so pass it
            whenever the user asks for anything else, such as the day's top news.
        sources: Comma-separated sites to search in. Prefer the site's domain
            ("g1.globo.com", "poder360.com.br"): a domain limits the search to
            that site. Known names also work (G1, CNN Brasil, CNN EUA, Reuters,
            BBC Brasil, BBC News, Gazeta do Povo, Revista Oeste, Folha de
            S.Paulo, Estadão, UOL, The Verge, TechCrunch); any other name is
            only a search term and does not restrict the site.
            Empty = every configured source.
        max_news: Number of articles in the digest (1-30); 0 = configured amount.
        summary_chars: Approximate length of each summary (100-1000); 0 = configured.

    Returns:
        str: The digest, ready to be sent as is (or trimmed), or a message
        saying that no news was found.
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

        target_count = cfg["max_news"]
        target_chars = cfg["summary_chars"]

        # STEP 1: Search live web candidates
        candidates = _search_news_candidates(cfg["sources"], cfg["topics"], target_count)
        if not candidates:
            return "Nenhuma notícia recente foi encontrada para os tópicos e fontes configurados."

        # STEP 2 & 3: Scrape full text & summarize, in parallel waves until enough articles are done
        def _process(cand):
            content = _extract_article_text(cand["url"])
            if not content or len(content.strip()) < 100:
                # If scraping was blocked or empty, use snippet if available
                content = cand.get("snippet", "")
                if not content or len(content.strip()) < 50:
                    return None
            summary = _summarize_article_with_llm(cand["title"], content, cand["source"], target_chars)
            if not summary:
                return None
            return {
                "title": cand["title"],
                "source": cand["source"],
                "date": cand.get("date") or "Recente",
                "summary": summary,
                "url": cand["url"],
            }

        completed_articles = []
        with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
            pending = list(candidates)
            while pending and len(completed_articles) < target_count:
                wave_size = target_count - len(completed_articles)
                wave, pending = pending[:wave_size], pending[wave_size:]
                # Each task gets a copy of the context so the LLM usage is still recorded for this request.
                futures = [pool.submit(contextvars.copy_context().run, _process, cand) for cand in wave]
                for future in futures:
                    item = future.result()
                    if item:
                        completed_articles.append(item)

        if not completed_articles:
            return "Não foi possível extrair o conteúdo das notícias encontradas no momento."

        # STEP 4: Assemble Final Formatted Digest
        lines = ["=== RESUMO DE NOTÍCIAS ===", ""]
        for item in completed_articles:
            date_str = f" — {item['date']}" if item['date'] else ""
            lines.append(f"📰 {item['title']} — {item['source']}{date_str}")
            lines.append(f"{item['summary']}")
            lines.append(f"🔗 {item['url']}")
            lines.append("")

        return "\n".join(lines).strip()

    except Exception as e:
        logger.exception("fetch_news pipeline failed")
        return f"Erro ao gerar resumo de notícias: {e}"


