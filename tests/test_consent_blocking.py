import pytest
import concurrent.futures
from unittest.mock import MagicMock, patch

from browser.manager import BrowserManager, _CMP_BLOCK_RE, _harden_context, _CONSENT_SWEEP_JS


def test_cmp_regex_blocks_known_cmp_domains():
    # Sourcepoint (CNN Brasil, Globo properties...) — the exact popup reported
    assert _CMP_BLOCK_RE.search("https://cdn.privacy-mgmt.com/index.html?message_id=1")
    assert _CMP_BLOCK_RE.search("https://mms.sp-prod.net/mms/get_site_data")
    assert _CMP_BLOCK_RE.search("https://sourcepoint.mgr.consensu.org/message-url")
    # Other major CMPs
    assert _CMP_BLOCK_RE.search("https://geolocation.onetrust.com/cookieconsentpub/v1/geo/location")
    assert _CMP_BLOCK_RE.search("https://consent.cookiebot.com/uc.js")
    assert _CMP_BLOCK_RE.search("https://app.termly.io/embed/script.js")
    assert _CMP_BLOCK_RE.search("https://widget.usercentrics.eu/widget/main.js")
    assert _CMP_BLOCK_RE.search("https://cdn.jsdelivr.net/npm/klaro/klaro.min.js") is None  # self-hosted klaro handled by DOM sweep


def test_cmp_regex_does_not_block_normal_pages():
    assert not _CMP_BLOCK_RE.search("https://www.cnnbrasil.com.br/politica/")
    assert not _CMP_BLOCK_RE.search("https://www.google.com/search?q=cookies")
    assert not _CMP_BLOCK_RE.search("https://example.com/consent-article.html")


def test_harden_context_installs_route_and_init_script():
    ctx = MagicMock()
    _harden_context(ctx)
    assert ctx.route.call_count == 2
    ctx.add_init_script.assert_called_once()
    assert "__nwSweepConsent" in ctx.add_init_script.call_args[0][0]


def test_harden_context_respects_config_off(mocker):
    mocker.patch("database.get_config", return_value="false")
    ctx = MagicMock()
    _harden_context(ctx)
    ctx.route.assert_not_called()
    ctx.add_init_script.assert_not_called()


def test_ads_regex_blocks_known_ad_domains():
    from browser.manager import _ADS_BLOCK_RE
    assert _ADS_BLOCK_RE.search("https://securepubads.g.doubleclick.net/gampad/ads")
    assert _ADS_BLOCK_RE.search("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js")
    assert _ADS_BLOCK_RE.search("https://ib.adnxs.com/seg?add=1")
    assert _ADS_BLOCK_RE.search("https://static.criteo.net/js/ld/ld.js")
    assert _ADS_BLOCK_RE.search("https://c.amazon-adsystem.com/aax2/apstag.js")
    assert _ADS_BLOCK_RE.search("https://widgets.outbrain.com/outbrain.js")
    assert _ADS_BLOCK_RE.search("https://cdn.taboola.com/libtrc/unip/trc.js")
    assert _ADS_BLOCK_RE.search("https://static.hotjar.com/c/hotjar-123.js")
    assert _ADS_BLOCK_RE.search("https://www.clarity.ms/tag/abc")


def test_ads_regex_does_not_block_normal_pages():
    from browser.manager import _ADS_BLOCK_RE
    assert not _ADS_BLOCK_RE.search("https://news.ycombinator.com")
    assert not _ADS_BLOCK_RE.search("https://github.com/features/actions")
    assert not _ADS_BLOCK_RE.search("https://en.wikipedia.org/wiki/Main_Page")


def test_navigate_runs_consent_sweep(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="true")
    with patch("browser.manager.sync_playwright"):
        bm = BrowserManager()
        res = bm.navigate("http://example.com")
        assert "Navigated to" in res
        sweep_calls = [
            c for c in bm.page.evaluate.call_args_list
            if "__nwSweepConsent" in str(c)
        ]
        assert sweep_calls, "navigate() must run the consent sweep after load"


def test_consent_sweep_js_is_valid_javascript():
    # The init script is embedded in Python; make sure it stays valid JS.
    import subprocess
    import tempfile
    import os

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
        tf.write(_CONSENT_SWEEP_JS)
        path = tf.name
    try:
        proc = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        assert proc.returncode == 0, f"Invalid JS: {proc.stderr}"
    finally:
        os.unlink(path)