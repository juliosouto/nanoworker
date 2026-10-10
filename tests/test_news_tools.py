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
    # Sources/topics are fully user-managed dynamic lists (add/remove on card).
    assert keys["sources"]["type"] == "dynamic_list"
    assert keys["topics"]["type"] == "dynamic_list"
    src_fields = {f["key"] for f in keys["sources"]["item_fields"]}
    assert src_fields == {"name", "domain", "feed"}
    topic_fields = {f["key"] for f in keys["topics"]["item_fields"]}
    assert topic_fields == {"name", "keywords"}
    # Seeded defaults are full entries, not bare strings.
    assert keys["sources"]["default"][0]["name"] == "CNN Brasil"
    assert keys["sources"]["default"][0]["feed"].startswith("http")
    assert {"name": "Tecnologia", "keywords": news_tools._PRESET_TOPICS["Tecnologia"]} in keys["topics"]["default"]
    assert keys["summary_chars"]["default"] == 300
    assert keys["max_news"]["default"] == 6


def test_effective_config_uses_schema_defaults(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={"enabled": True, "settings": {}})
    cfg = news_tools._effective_config()
    assert cfg["summary_chars"] == 300
    assert cfg["max_news"] == 6
    assert cfg["sources"][0]["name"] == "CNN Brasil"
    assert cfg["sources"][0]["domain"] == "cnnbrasil.com.br"
    assert any(t["name"] == "Startups" for t in cfg["topics"])


def test_effective_config_coerces_legacy_string_entries(mocker):
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": {"sources": ["BBC Brasil"], "topics": ["Startups"]},
    })
    cfg = news_tools._effective_config()
    assert cfg["sources"] == [{
        "name": "BBC Brasil",
        "domain": "bbc.com",
        "feed": "https://feeds.bbci.co.uk/portuguese/rss.xml",
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
    assert cfg["sources"] == [{"name": "Canaltech", "domain": "canaltech.com.br", "feed": ""}]
    assert cfg["topics"] == [{"name": "Hardware", "keywords": ["gpu", "processador"]}]


def test_effective_config_respects_explicitly_empty_lists(mocker):
    # The user removed every source/topic on purpose — do not resurrect defaults.
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
    assert news_tools._matches_topic(item, "Startups")          # legacy string
    assert news_tools._matches_topic(item, {"name": "Startups", "keywords": ["startup"]})  # dict entry
    assert not news_tools._matches_topic(item, "Política")
    custom = {"title": "Copa do mundo feminina", "text_excerpt": ""}
    assert news_tools._matches_topic(custom, "Copa do mundo feminina")  # custom topic fallback


def test_coerce_source_merges_preset_fields():
    entry = news_tools._coerce_source({"name": "bbc brasil"})  # case-insensitive name
    assert entry == {"name": "BBC Brasil", "domain": "bbc.com",
                     "feed": "https://feeds.bbci.co.uk/portuguese/rss.xml"}
    # User-defined source: kept as-is, empty feed filled with ''.
    custom = news_tools._coerce_source({"name": "Canaltech", "domain": "canaltech.com.br"})
    assert custom == {"name": "Canaltech", "domain": "canaltech.com.br", "feed": ""}
    # Legacy plain string resolves via presets; unknown names become bare entries.
    assert news_tools._coerce_source("Reuters") == {"name": "Reuters", "domain": "reuters.com", "feed": ""}
    assert news_tools._coerce_source("Portal X") == {"name": "Portal X", "domain": "", "feed": ""}
    assert news_tools._coerce_source({}) is None
    assert news_tools._coerce_source("") is None


def test_coerce_topic_handles_strings_and_keywords():
    entry = news_tools._coerce_topic({"name": "Hardware", "keywords": "gpu, processador"})
    assert entry == {"name": "Hardware", "keywords": ["gpu", "processador"]}
    empty = news_tools._coerce_topic({"name": "Custom"})
    assert empty == {"name": "Custom", "keywords": ["custom"]}
    preset = news_tools._coerce_topic("Tecnologia")
    assert preset["keywords"] == news_tools._PRESET_TOPICS["Tecnologia"]


def test_collect_candidates_uses_custom_source_domain(mocker):
    # A user-added source (not in presets) must drive the Google News query.
    http_get = mocker.patch("tools.news_tools._http_get", return_value=GOOGLE_NEWS_RSS.replace(
        "Reuters cobre nova tecnologia de chips", "Canaltech cobre nova tecnologia de chips"))
    selected, _, diagnostics = news_tools._collect_candidates(
        sources=[{"name": "Canaltech", "domain": "canaltech.com.br", "feed": ""}],
        topics=[{"name": "Tecnologia", "keywords": ["tecnologia"]}],
        max_news=3,
    )
    url = http_get.call_args[0][0]
    assert "news.google.com/rss/search" in url
    assert "canaltech.com.br" in url
    assert selected and selected[0]["source"] == "Canaltech"


def test_collect_candidates_skips_source_without_domain_or_feed():
    selected, _, diagnostics = news_tools._collect_candidates(
        sources=[{"name": "Fonte Quebrada", "domain": "", "feed": ""}],
        topics=[{"name": "Tecnologia", "keywords": ["tecnologia"]}],
        max_news=3,
    )
    assert selected == []
    assert any("Fonte Quebrada" in d and "configurado" in d for d in diagnostics)


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
    # The configured quantity is explicit in the protocol and the checklist.
    assert "APPROXIMATELY 3 items" in out
    assert "digest contains approximately 3 items" in out
    # Summary length is a target, not a ceiling.
    assert "APPROXIMATELY 200 characters" in out
    assert "TARGET length, not a ceiling" in out
    assert "every summary is approximately 200 characters" in out
    # Non-matching item filtered out.
    assert "Pesquisas eleitorais" not in out


def test_fetch_news_protocol_precedes_candidates_and_fits_cap(mocker):
    # Regression for the truncated-protocol bug: the protocol and self-check
    # must sit ABOVE the candidates JSON so LC_TOOL_RESULT_MAX_CHARS (6000)
    # can never cut the rules off; with short-description feeds the whole
    # mission must also fit under the cap.
    _patch_tool(mocker, {"https://feeds.bbci.co.uk/portuguese/rss.xml": BBC_RSS})
    out = fetch_news()
    protocol_idx = out.index("MANDATORY EXECUTION PROTOCOL")
    check_idx = out.index("FINAL SELF-CHECK")
    candidates_idx = out.index("your article list):")
    assert protocol_idx < check_idx < candidates_idx
    assert len(out) <= 6000


def test_build_mission_strips_excerpt_from_backup_only_items():
    # Backups outside `selected` drop their (huge) excerpt; selected keep it.
    cfg = {
        "sources": [{"name": "G1"}],
        "topics": [{"name": "Tecnologia"}],
        "max_news": 1,
        "summary_chars": 300,
    }

    def item(title):
        return {
            "title": title, "source": "G1", "date": "2026-10-10 10:00 UTC",
            "url": f"https://g1.globo.com/{title}", "full_text_available": True,
            "text_excerpt": "x" * 1000, "topics": ["Tecnologia"],
        }

    picked = item("selecionada")
    extra = item("apenas-backup")
    out = news_tools._build_mission(cfg, [picked], [picked, extra], [])
    payload = json.loads(out.split("your article list):\n", 1)[1])
    assert payload["selected"][0]["text_excerpt"] == "x" * 1000
    assert payload["backups"][0]["text_excerpt"] == "x" * 1000  # also selected
    assert "text_excerpt" not in payload["backups"][1]          # backup-only


def test_collect_candidates_backups_capped_at_max_news(mocker):
    # Backups were 2x max_news; they are capped at max_news so the mission
    # payload stays within the tool-result cap.
    def fake_feed(url):
        items = "".join(
            f"<item><title>noticia tecnologia numero {i}</title>"
            f"<link>https://g1.globo.com/tecnologia/{i}</link>"
            f"<pubDate>Sat, 10 Oct 2026 1{i}:00:00 GMT</pubDate>"
            f"<description>Reportagem de tecnologia numero {i}</description></item>"
            for i in range(6)
        )
        return f"<rss><channel><title>G1</title>{items}</channel></rss>"

    mocker.patch("tools.news_tools._http_get", side_effect=fake_feed)
    selected, backups, _ = news_tools._collect_candidates(
        sources=[{"name": "G1", "domain": "g1.globo.com", "feed": ""}],
        topics=[{"name": "tecnologia", "keywords": ["tecnologia"]}],
        max_news=2,
    )
    assert len(selected) <= 2
    assert len(backups) <= 2


def test_fetch_news_candidates_json_is_parseable(mocker):
    _patch_tool(mocker, {"https://feeds.bbci.co.uk/portuguese/rss.xml": BBC_RSS})
    out = fetch_news()
    json_str = out.split("your article list):\n", 1)[1].split("\n\nDISCOVERY NOTES", 1)[0]
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
        "config_data": {
            "sources": [{"name": "G1", "domain": "g1.globo.com", "feed": "https://g1.globo.com/rss/g1/"}],
            "topics": [{"name": "Esportes", "keywords": ["futebol", "copa"]}],
            "max_news": 4,
            "summary_chars": 150,
        }
    })
    cfg = get_tool_config("fetch_news")
    assert cfg["settings"]["sources"][0]["name"] == "G1"
    assert cfg["settings"]["max_news"] == 4


def test_get_tool_config_missing_row_returns_settings_key(client):
    from database import get_tool_config
    cfg = get_tool_config("some_unknown_tool")
    assert cfg["enabled"] is True
    assert cfg["settings"] == {}


def test_api_saves_tool_settings(client):
    settings = NEW_FORMAT_SETTINGS
    resp = client.post("/api/settings/tools", json={"tool_name": "fetch_news", "settings": settings})
    assert resp.status_code == 200

    from database import get_tool_config
    assert get_tool_config("fetch_news")["settings"] == settings


def test_api_saves_empty_dynamic_lists(client):
    # Removing every source/topic on the card must persist as [] (not defaults).
    settings = {"sources": [], "topics": [], "max_news": 5, "summary_chars": 300}
    resp = client.post("/api/settings/tools", json={"tool_name": "fetch_news", "settings": settings})
    assert resp.status_code == 200

    from database import get_tool_config
    assert get_tool_config("fetch_news")["settings"]["sources"] == []


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
    assert "dynamic_list" in html
    assert "max_news" in html
    assert "Adicionar fonte" in html
    assert "Adicionar assunto" in html


def test_google_news_rss_url_format():
    url = news_tools._google_news_rss_url("Tecnologia", "reuters.com")
    assert "news.google.com/rss/search" in url
    assert "Tecnologia+site%3Areuters.com" in url
    # Domain is optional: custom sources without one fall back to a plain query.
    plain = news_tools._google_news_rss_url("Hardware")
    assert "site%3A" not in plain
    assert "Hardware" in plain


def test_fetch_news_end_to_end_with_custom_entries(mocker):
    # Full pipeline with user-added (non-preset) sources and topics.
    tech_rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Tecnoblog</title>
<item>
  <title>Tecnoblog lista as melhores GPUs para monitores 4K</title>
  <link>https://tecnoblog.net/noticias/gpus/</link>
  <pubDate>Sat, 10 Oct 2026 11:00:00 GMT</pubDate>
  <description>Guia de placas de vídeo (gpu) e processadores para jogos em monitores 4K.</description>
</item>
</channel></rss>"""
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mocker.patch("tools.news_tools.get_tool_config", return_value={
        "enabled": True,
        "settings": dict(NEW_FORMAT_SETTINGS),
    })
    mocker.patch("tools.news_tools._http_get", side_effect=lambda url: tech_rss if "tecnoblog" in url else "")
    out = fetch_news(topics="Hardware")
    # Config echo uses the custom entries.
    assert "Canaltech" in out
    assert "Tecnoblog" in out
    assert "Hardware" in out
    # Feed item matched the custom 'Hardware' keywords (gpu/processador).
    assert "melhores GPUs" in out
    # Custom summary limit echoed.
    assert "summary_chars=400" in out
    assert "max_news=4" in out
