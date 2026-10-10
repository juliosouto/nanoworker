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
    "settings": {
        "sources": ["BBC Brasil"],
        "topics": ["Startups"],
        "max_news": 3,
        "summary_chars": 200,
    },
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
    assert "CNN Brasil" in keys["sources"]["options"]
    assert "Reuters" in keys["sources"]["options"]
    assert "Revista Oeste" in keys["sources"]["options"]
    assert "Tecnologia" in keys["topics"]["options"]
    assert "Programação" in keys["topics"]["options"]
    assert "Startups" in keys["topics"]["options"]
    assert keys["summary_chars"]["default"] == 300
    assert keys["max_news"]["default"] == 6


def test_effective_config_uses_schema_defaults(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={"enabled": True, "settings": {}})
    cfg = news_tools._effective_config()
    assert cfg["summary_chars"] == 300
    assert cfg["max_news"] == 6
    assert "CNN Brasil" in cfg["sources"]
    assert "Startups" in cfg["topics"]


def test_effective_config_clamps_and_filters(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {
            "summary_chars": "99999",
            "max_news": -5,
            "sources": ["Fonte Inexistente"],
        },
    })
    cfg = news_tools._effective_config()
    assert cfg["summary_chars"] == 1000  # clamped to schema max
    assert cfg["max_news"] == 1          # clamped to schema min
    assert cfg["sources"] == ["CNN Brasil", "CNN EUA", "Reuters",
                              "BBC Brasil", "Gazeta do Povo", "Revista Oeste"]  # invalid filtered → defaults


# ---------------------------------------------------------------------------
# RSS parsing / discovery tests
# ---------------------------------------------------------------------------
def test_parse_rss_excerpt_source():
    items = news_tools._parse_rss(BBC_RSS, "BBC Brasil")
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Nova startup de IA levanta US$ 100 milhões"
    assert first["source"] == "BBC Brasil"
    assert first["date"] == "2026-10-10 10:00 UTC"
    assert first["url"] == "https://www.bbc.com/portuguese/articles/abc123"
    # Short description → no full text → agent must open the page.
    assert first["full_text_available"] is False
    assert first["text_excerpt"] == ""


def test_parse_rss_full_text_source():
    items = news_tools._parse_rss(CNN_RSS, "CNN Brasil")
    assert len(items) == 1
    item = items[0]
    # content:encoded carries the whole article → agent may summarize directly.
    assert item["full_text_available"] is True
    assert "programação" in item["text_excerpt"]
    assert "<p>" not in item["text_excerpt"]  # HTML stripped


def test_parse_rss_invalid_xml_returns_empty():
    assert news_tools._parse_rss("<not-valid-xml", "BBC Brasil") == []


def test_matches_topic():
    item = {"title": "Nova startup de IA levanta US$ 100 milhões", "text_excerpt": ""}
    assert news_tools._matches_topic(item, "Startups")
    assert not news_tools._matches_topic(item, "Política")
    custom = {"title": "Copa do mundo feminina", "text_excerpt": ""}
    assert news_tools._matches_topic(custom, "Copa do mundo feminina")  # custom topic fallback


# ---------------------------------------------------------------------------
# fetch_news protocol tests
# ---------------------------------------------------------------------------
def test_fetch_news_returns_mission_with_candidates(mocker):
    _patch_tool(mocker, {"https://feeds.bbci.co.uk/portuguese/rss.xml": BBC_RSS})
    out = fetch_news()
    assert "NEWS BRIEFING MISSION" in out
    assert "CANDIDATES" in out
    assert "MANDATORY EXECUTION PROTOCOL" in out
    # Candidate data (title/source/date/url) is in the JSON payload.
    assert "Nova startup de IA levanta US$ 100 milhões" in out
    assert "BBC Brasil" in out
    assert "2026-10-10 10:00 UTC" in out
    # Config echo from stored settings.
    assert "max_news=3" in out
    assert "summary_chars=200" in out
    # Non-matching item filtered out.
    assert "Pesquisas eleitorais" not in out


def test_fetch_news_candidates_json_is_parseable(mocker):
    _patch_tool(mocker, {"https://feeds.bbci.co.uk/portuguese/rss.xml": BBC_RSS})
    out = fetch_news()
    json_str = out.split("your article list):\n", 1)[1].split("\n\nMANDATORY", 1)[0]
    payload = json.loads(json_str)
    item = payload["selected"][0]
    assert item["title"] == "Nova startup de IA levanta US$ 100 milhões"
    assert item["source"] == "BBC Brasil"
    assert item["date"] == "2026-10-10 10:00 UTC"
    assert item["url"].startswith("https://www.bbc.com/portuguese/articles/")
    assert item["full_text_available"] is False


def test_fetch_news_google_news_fallback(mocker):
    # Reuters has no native feed → Google News RSS must be used.
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {"sources": ["Reuters"], "topics": ["Tecnologia"], "max_news": 3, "summary_chars": 300},
    })
    http_get = mocker.patch("tools.news_tools._http_get", return_value=GOOGLE_NEWS_RSS)
    out = fetch_news()
    assert "news.google.com/rss/search" in http_get.call_args[0][0]
    assert "reuters.com" in http_get.call_args[0][0]
    assert "Reuters: nova tecnologia de chips" in out


def test_fetch_news_runtime_overrides(mocker):
    _patch_tool(mocker, {"https://g1.globo.com/rss/g1/": BBC_RSS})
    out = fetch_news(topics="Programação", sources="g1", max_news=2, summary_chars=150)
    assert "max_news=2" in out
    assert "summary_chars=150" in out
    assert "['G1']" in out          # canonicalized source name
    assert "['Programação']" in out  # overridden topic


def test_fetch_news_permission_denied(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="false")
    mocker.patch("tools.news_tools.get_tool_config", return_value=dict(DEFAULT_CFG))
    mocker.patch("tools.news_tools._http_get", return_value="")
    out = fetch_news()
    assert "Access denied" in out
    assert "PERM_WEB_SEARCH" in out


def test_fetch_news_handles_dead_feed(mocker):
    def boom(url):
        raise ConnectionError("timeout")
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {"sources": ["BBC Brasil"], "topics": ["Startups"], "max_news": 3, "summary_chars": 300},
    })
    mocker.patch("tools.news_tools._http_get", side_effect=boom)
    out = fetch_news()
    # Must never crash: returns the mission with a discovery note.
    assert "NEWS BRIEFING MISSION" in out
    assert "DISCOVERY NOTES" in out
    assert "indisponível" in out

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
        "config_data": {"sources": ["G1"], "topics": ["Esportes"], "max_news": 4, "summary_chars": 150}
    })
    cfg = get_tool_config("fetch_news")
    assert cfg["settings"]["sources"] == ["G1"]
    assert cfg["settings"]["max_news"] == 4


def test_get_tool_config_missing_row_returns_settings_key(client):
    from database import get_tool_config
    cfg = get_tool_config("some_unknown_tool")
    assert cfg["enabled"] is True
    assert cfg["settings"] == {}


def test_api_saves_tool_settings(client):
    settings = {"sources": ["Reuters", "G1"], "topics": ["Economia"], "max_news": 8, "summary_chars": 400}
    resp = client.post("/api/settings/tools", json={"tool_name": "fetch_news", "settings": settings})
    assert resp.status_code == 200

    from database import get_tool_config
    assert get_tool_config("fetch_news")["settings"] == settings


def test_api_rejects_non_dict_settings(client):
    resp = client.post("/api/settings/tools", json={"tool_name": "fetch_news", "settings": "nope"})
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


def test_setup_tools_config_preserves_custom_settings(client):
    from database import update_tool_config, get_tool_config
    from utils.setup_utils import setup_tools_config

    update_tool_config("fetch_news", {"config_data": {"sources": ["G1"], "summary_chars": 200}})
    setup_tools_config()  # simulates a fresh /api/setup re-seed

    cfg = get_tool_config("fetch_news")
    assert cfg["settings"] == {"sources": ["G1"], "summary_chars": 200}
    # The re-seed still resets the toggles to the defaults.
    assert cfg["enabled"] is True
    assert cfg["allow_others_from_group_msgs"] is False


def test_tools_management_page_renders_news_card_and_schema(client):
    resp = client.get("/settings/tools")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Fetch News" in html
    assert 'id="toolSettingsData"' in html
    # Schema is embedded as JSON (Flask's tojson escapes non-ASCII as \uXXXX).
    assert "summary_chars" in html
    assert "multi_select" in html
    assert "max_news" in html


def test_google_news_rss_url_format():
    url = news_tools._google_news_rss_url("Tecnologia", "reuters.com")
    assert "news.google.com/rss/search" in url
    assert "Tecnologia+site%3Areuters.com" in url
