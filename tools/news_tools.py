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

import json
import logging
import re
from collections import defaultdict
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List, Dict, Any

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
    preset = _PRESET_SOURCES.get(canonical, {})
    return {
        "name": canonical or raw_name,
        "domain": preset.get("domain", ""),
    }


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
def _search_news_candidates(sources: List[Dict[str, str]], topics: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    """
    Searches DuckDuckGo News/Text for recent articles across the requested sources and topics.
    Returns a list of candidate dicts with url, title, source, and rough date/snippet.
    """
    candidates = []
    seen_urls = set()
    seen_titles = set()

    for source in sources:
        source_name = source.get("name") or "News"
        domain = source.get("domain") or ""

        for topic in topics:
            topic_name = topic.get("name") if isinstance(topic, dict) else str(topic)
            query = f"{topic_name} site:{domain}" if domain else f"{topic_name} {source_name}"
            
            # 1. Try DuckDuckGo News search first
            try:
                with DDGS() as ddgs:
                    news_results = list(ddgs.news(query, max_results=5))
                    if not news_results:
                        # Fallback to general text search if news tab returns empty
                        news_results = list(ddgs.text(query, max_results=5))
            except Exception as e:
                logger.debug("DDG search failed for query %r: %s", query, e)
                news_results = []

            for item in news_results:
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
    Extracts main article text using curl_cffi + trafilatura, falling back to BeautifulSoup.
    """
    if not url:
        return ""
    try:
        resp = curl_requests.get(url, impersonate="chrome146", timeout=_ARTICLE_SCRAPE_TIMEOUT)
        html = resp.text or ""
        text = trafilatura.extract(html)
        if text and len(text.strip()) >= 80:
            return text.strip()
    except Exception as e:
        logger.debug("Trafilatura extract failed for %s: %s", url, e)

    # Secondary lightweight fallback with BeautifulSoup
    try:
        resp = curl_requests.get(url, impersonate="chrome146", timeout=_ARTICLE_SCRAPE_TIMEOUT)
        soup = BeautifulSoup(resp.text or "", "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        # Find paragraphs
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
            # Check default model in database
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT model_name FROM llm_config WHERE text_output = 1 ORDER BY priority ASC LIMIT 1")
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
    Executes a complete multi-step news briefing pipeline:
    1. Searches live news for configured topics & sources without RSS reliance.
    2. Scrapes the full webpage text for each article.
    3. Summarizes each article using an internal LLM call to match target length.
    4. Compiles and returns the finalized, structured news digest ready for presentation.

    Args:
        topics: Optional comma-separated topic names to override (e.g. "Tecnologia,Startups").
        sources: Optional comma-separated source names to override (e.g. "G1,CNN Brasil").
        max_news: Optional override for total news count in the final digest.
        summary_chars: Optional override for character length per summary.

    Returns:
        str: The final structured news briefing with titles, dates, sources, summaries, and links.
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

        # STEP 2 & 3: Scrape full text & Summarize each article
        completed_articles = []
        for cand in candidates:
            if len(completed_articles) >= target_count:
                break

            url = cand["url"]
            title = cand["title"]
            source = cand["source"]
            date = cand.get("date") or "Recente"

            # Scrape real content
            content = _extract_article_text(url)
            if not content or len(content.strip()) < 100:
                # If scraping was blocked or empty, use snippet if available
                content = cand.get("snippet", "")
                if not content or len(content.strip()) < 50:
                    continue

            # Summarize content
            summary = _summarize_article_with_llm(title, content, source, target_chars)
            if not summary:
                continue

            completed_articles.append({
                "title": title,
                "source": source,
                "date": date,
                "summary": summary,
                "url": url,
            })

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


