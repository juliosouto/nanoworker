import json

import pytest

from tools import news_tools
from tools.news_tools import fetch_news, TOOL_SETTINGS_SCHEMA

# ---------------------------------------------------------------------------
# Fixtures / sample feeds
# ---------------------------------------------------------------------------
BBC_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>BBC Brasil</title>
<item>
  <title>Nova startup de IA levanta US$ 100 milhões</title>
  <description>Uma startup brasileira de inteligência artificial anunciou investimento. Tecnologia em alta.</description>
  <link>https://www.bbc.com/portuguese/articles/abc123</link>
  <pubDate>Sat, 10 Oct 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Pesquisas eleitorais</title>
  <description>Analise politica.</description>
  <link>https://www.bbc.com/portuguese/articles/def456</link>
  <pubDate>Fri, 09 Oct 2026 10:00:00 GMT</pubDate>
</item>
</channel>
</rss>"""

CNN_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>CNN Brasil</title>
<item>
  <title>Startups de tecnologia crescem no Brasil</title>
  <description>Resumo curto.</description>
  <link>https://www.cnnbrasil.com.br/economia/startups/</link>
  <pubDate>Sat, 10 Oct 2026 12:00:00 GMT</pubDate>
  <content:encoded><![CDATA[<p>Startups de programação e tecnologia estão crescendo no Brasil. {PADDING} O ecossistema de desenvolvimento de software e startups brasileiro atrai cada vez mais investidores estrangeiros interessados em código aberto e novas plataformas digitais.</p>]]></content:encoded>
</item>
</channel>
</rss>""".replace("{PADDING}", "lorem ipsum dolor sit amet " * 12)

GOOGLE_NEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel><title>Reuters - tecnologia</title>
<item>
  <title>Reuters: nova tecnologia de chips promete revolucionar mercado</title>
  <link>https://news.google.com/rss/articles/CBMiABC123</link>
  <pubDate>Sat, 10 Oct 2026 09:00:00 GMT</pubDate>
  <description>Reportagem sobre tecnologia de semicondutores.</description>
</item>
</channel>
</rss>"""

DEFAULT_CFG = {
    "enabled": True,
    "allow_others_from_direct_msgs": False,
    "allow_others_from_group_msgs": False,
    # Deliberately uses the LEGACY plain-string format to exercise the
    # coercion path (dict entries are the current on-card format).
    "settings": {
        "sources": ["BBC Brasil"],
        "topics": ["Startups"],
        "max_news": 3,
        "summary_chars": 200,
    },
}

NEW_FORMAT_SETTINGS = {
    "sources": [
        {"name": "Canaltech", "domain": "canaltech.com.br", "feed": ""},
        {"name": "Tecnoblog", "domain": "tecnoblog.com", "feed": "https://tecnoblog.com/feed/"},
    ],
    "topics": [
        {"name": "Hardware", "keywords": ["gpu", "placa de vídeo", "processador"]},
        {"name": "Lançamentos", "keywords": ["lançamento", "lancamento", "anúncio"]},
    ],
    "max_news": 4,
    "summary_chars": 400,
}


def _patch_tool(mocker, feeds):
    """Mock security + DB config + HTTP fetches for fetch_news calls."""
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mocker.patch("tools.news_tools.get_tool_config", return_value=dict(DEFAULT_CFG))
    mocker.patch("tools.news_tools._http_get", side_effect=lambda url: feeds.get(url, ""))


# ---------------------------------------------------------------------------
# Schema / config tests
# ---------------------------------------------------------------------------
def test_tool_registered():
    import tools
    names = [t.__name__ for t in tools.AVAILABLE_TOOLS]
    assert "fetch_news" in names


def test_schema_has_expected_fields():
    keys = {f["key"]: f for f in TOOL_SETTINGS_SCHEMA}
    assert set(keys) == {"sources", "topics", "max_news", "summary_chars"}
    assert keys["sources"]["type"] == "dynamic_list"
    assert keys["topics"]["type"] == "dynamic_list"
    src_fields = {f["key"] for f in keys["sources"]["item_fields"]}
    assert src_fields == {"name", "domain"}
    topic_fields = {f["key"] for f in keys["topics"]["item_fields"]}
    assert topic_fields == {"name", "keywords"}
    assert keys["sources"]["default"][0]["name"] == "G1"
    assert {"name": "Tecnologia", "keywords": news_tools._PRESET_TOPICS["Tecnologia"]} in keys["topics"]["default"]
    assert keys["summary_chars"]["default"] == 300
    assert keys["max_news"]["default"] == 6


def test_effective_config_uses_schema_defaults(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={"enabled": True, "settings": {}})
    cfg = news_tools._effective_config()
    assert cfg["summary_chars"] == 300
    assert cfg["max_news"] == 6
    assert cfg["sources"][0]["name"] == "G1"
    assert cfg["sources"][0]["domain"] == "g1.globo.com"
    assert any(t["name"] == "Startups" for t in cfg["topics"])


def test_effective_config_coerces_legacy_string_entries(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {"sources": ["BBC Brasil"], "topics": ["Startups"]},
    })
    cfg = news_tools._effective_config()
    assert cfg["sources"] == [{
        "name": "BBC Brasil",
        "domain": "bbc.com/portuguese",
    }]
    assert cfg["topics"] == [{
        "name": "Startups",
        "keywords": news_tools._PRESET_TOPICS["Startups"],
    }]


def test_effective_config_keeps_user_defined_entries(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {
            "sources": [{"name": "Canaltech", "domain": "canaltech.com.br"}],
            "topics": [{"name": "Hardware", "keywords": ["gpu", "processador"]}],
        },
    })
    cfg = news_tools._effective_config()
    assert cfg["sources"] == [{"name": "Canaltech", "domain": "canaltech.com.br"}]
    assert cfg["topics"] == [{"name": "Hardware", "keywords": ["gpu", "processador"]}]


def test_effective_config_respects_explicitly_empty_lists(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {"sources": [], "topics": []},
    })
    cfg = news_tools._effective_config()
    assert cfg["sources"] == []
    assert cfg["topics"] == []


def test_effective_config_clamps_numbers(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {"summary_chars": "99999", "max_news": -5},
    })
    cfg = news_tools._effective_config()
    assert cfg["summary_chars"] == 1000  # clamped to schema max
    assert cfg["max_news"] == 1          # clamped to schema min


# ---------------------------------------------------------------------------
# Pipeline Step Tests: Search, Scrape, Summarize, Format
# ---------------------------------------------------------------------------
def test_search_news_candidates_uses_ddgs(mocker):
    mock_ddg = mocker.MagicMock()
    mock_ddg.__enter__.return_value.news.return_value = [
        {"title": "G1: Avanços em IA", "url": "https://g1.globo.com/ia", "body": "Snippet IA", "date": "2026-10-10"}
    ]
    mocker.patch("tools.news_tools.DDGS", return_value=mock_ddg)

    candidates = news_tools._search_news_candidates(
        sources=[{"name": "G1", "domain": "g1.globo.com"}],
        topics=[{"name": "Tecnologia"}],
        target_count=2,
    )
    assert len(candidates) == 1
    assert candidates[0]["title"] == "G1: Avanços em IA"
    assert candidates[0]["source"] == "G1"
    assert candidates[0]["url"] == "https://g1.globo.com/ia"


def test_extract_article_text_with_trafilatura(mocker):
    mocker.patch("tools.news_tools.curl_requests.get", return_value=mocker.MagicMock(text="<html><body><p>Conteudo principal da noticia.</p></body></html>"))
    mocker.patch("tools.news_tools.trafilatura.extract", return_value="Conteudo extraído completo da matéria com mais de cento e cinquenta caracteres para validar o scraping real da página de notícias sem problemas.")
    text = news_tools._extract_article_text("https://exemplo.com/noticia")
    assert "Conteudo extraído" in text


def test_summarize_article_with_llm(mocker):
    mocker.patch("agent.lc.settings.summarizer_model", return_value="test-model")
    mocker.patch("tools.news_tools.get_db")
    mocker.patch("agent.llm_router.route_llm_call", return_value="Este é o resumo gerado pelo modelo sobre a notícia de IA.")
    summary = news_tools._summarize_article_with_llm("Título", "Texto longo da matéria...", "G1", 200)
    assert "resumo gerado" in summary


def test_fetch_news_complete_flow(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {"sources": [{"name": "G1", "domain": "g1.globo.com"}], "topics": [{"name": "Tecnologia", "keywords": ["tecnologia"]}], "max_news": 1, "summary_chars": 200},
    })
    
    mock_ddg = mocker.MagicMock()
    mock_ddg.__enter__.return_value.news.return_value = [
        {"title": "Lançamento Tecnológico", "url": "https://g1.globo.com/tech", "body": "Snippet longo com mais de cem caracteres para garantir que passe no filtro de tamanho do conteúdo da notícia sem problemas.", "date": "2026-10-10"}
    ]
    mocker.patch("tools.news_tools.DDGS", return_value=mock_ddg)
    mocker.patch("tools.news_tools._extract_article_text", return_value="Texto completo da matéria extraído com sucesso pela ferramenta...")
    mocker.patch("tools.news_tools._summarize_article_with_llm", return_value="Resumo conciso dos pontos chave da matéria.")

    out = fetch_news()
    assert "=== RESUMO DE NOTÍCIAS ===" in out
    assert "📰 Lançamento Tecnológico — G1" in out
    assert "Resumo conciso dos pontos chave da matéria." in out
    assert "🔗 https://g1.globo.com/tech" in out


def test_fetch_news_permission_denied(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="false")
    out = fetch_news()
    assert "Access denied" in out
    assert "PERM_WEB_SEARCH" in out


# ---------------------------------------------------------------------------
# Database / API / page integration tests
# ---------------------------------------------------------------------------
@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


def test_update_and_get_tool_config_settings_roundtrip(client):
    from database import update_tool_config, get_tool_config
    update_tool_config("fetch_news", {
        "config_data": {
            "sources": [{"name": "G1", "domain": "g1.globo.com"}],
            "topics": [{"name": "Esportes", "keywords": ["futebol", "copa"]}],
            "max_news": 4,
            "summary_chars": 150,
        }
    })
    cfg = get_tool_config("fetch_news")
    assert cfg["settings"]["sources"][0]["name"] == "G1"
    assert cfg["settings"]["max_news"] == 4


def test_api_saves_tool_settings(client):
    settings = NEW_FORMAT_SETTINGS
    resp = client.post("/api/settings/tools", json={"tool_name": "fetch_news", "settings": settings})
    assert resp.status_code == 200

    from database import get_tool_config
    assert get_tool_config("fetch_news")["settings"] == settings


def test_tools_management_page_renders_news_card_and_schema(client):
    resp = client.get("/settings/tools")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Fetch News" in html
    assert "summary_chars" in html
    assert "dynamic_list" in html
