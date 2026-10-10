"""Tests for the mobile (smartphone) Playwright browsing tool.

Covers three layers, mirroring how the rest of the browser tools are tested:
  * browser.manager._resolve_mobile_device / navigate_mobile (the engine)
  * tools.<os>.browser.browser_navigate_mobile (the OS wrappers, all 3)
  * auto-discovery of the tool + Windows parity (so the agent can actually call it)
"""
from unittest.mock import MagicMock, patch

import pytest

import browser.manager as bm_mod
from browser.manager import BrowserManager, GlobalBrowser, _MOBILE_DEVICES, _resolve_mobile_device

from tools.linux import browser as linux_br
from tools.macos import browser as macos_br
from tools.windows import browser as windows_br


@pytest.fixture(params=[
    ("linux", linux_br),
    ("macos", macos_br),
    ("windows", windows_br),
])
def br_setup(request):
    return request.param


@pytest.fixture(autouse=True)
def reset_globals(mocker):
    GlobalBrowser._instance = None
    bm_mod._sessions.clear()
    bm_mod._cleanup_thread_started = False


# --------------------------------------------------------------------------- #
# _resolve_mobile_device / curated presets
# --------------------------------------------------------------------------- #

def test_curated_presets_are_all_mobile():
    """Every curated device must actually look like a phone (touch + is_mobile)."""
    assert _MOBILE_DEVICES  # non-empty
    for name, opts in _MOBILE_DEVICES.items():
        assert opts.get("is_mobile") is True, name
        assert opts.get("has_touch") is True, name
        assert "Mozilla" in opts["user_agent"], name
        assert opts["viewport"]["width"] > 0 and opts["viewport"]["height"] > 0, name


def test_resolve_mobile_device_known_preset():
    opts = _resolve_mobile_device("Pixel 7")
    assert opts == _MOBILE_DEVICES["Pixel 7"]
    # Must be a copy so callers can't mutate the shared presets.
    assert opts is not _MOBILE_DEVICES["Pixel 7"]


def test_resolve_mobile_device_unknown_without_catalog(monkeypatch):
    """When the live catalog is unavailable, an unknown device returns None."""
    monkeypatch.setattr(
        GlobalBrowser, "get_instance",
        lambda: (_ for _ in ()).throw(RuntimeError("no browser")),
    )
    assert _resolve_mobile_device("Definitely Not A Phone") is None


@patch('browser.manager.sync_playwright')
def test_resolve_mobile_device_falls_back_to_live_catalog(mock_playwright):
    """A device not in the curated presets can still resolve via Playwright's catalog."""
    gb = GlobalBrowser.get_instance()
    gb.playwright.devices = {
        "Mystery Phone": {
            "user_agent": "Mozilla/5.0 (Linux; Android 99) Mobile",
            "viewport": {"width": 300, "height": 700},
            "device_scale_factor": 2,
            "is_mobile": True,
            "has_touch": True,
        }
    }
    opts = _resolve_mobile_device("Mystery Phone")
    assert opts is not None
    assert opts["viewport"] == {"width": 300, "height": 700}
    assert opts["is_mobile"] is True


# --------------------------------------------------------------------------- #
# BrowserManager.navigate_mobile (engine)
# --------------------------------------------------------------------------- #

@patch('browser.manager.sync_playwright')
def test_navigate_mobile_success(mock_playwright):
    bm = BrowserManager()
    gb = GlobalBrowser.get_instance()

    # A fresh mobile context/page should be created from the shared browser.
    mobile_context = MagicMock()
    mobile_page = MagicMock()
    gb.browser.new_context.return_value = mobile_context
    mobile_context.new_page.return_value = mobile_page

    res = bm.navigate_mobile("https://example.com", device_name="Pixel 7")

    assert "Navigated to https://example.com in mobile mode" in res
    assert "Pixel 7" in res
    assert "412x839" in res  # Pixel 7 viewport
    # new_context received mobile emulation options
    _, kwargs = gb.browser.new_context.call_args
    assert kwargs["is_mobile"] is True
    assert kwargs["has_touch"] is True
    assert kwargs["viewport"] == {"width": 412, "height": 839}
    assert "Android" in kwargs["user_agent"]
    mobile_page.goto.assert_called_once_with(
        "https://example.com", wait_until="domcontentloaded", timeout=10000
    )


@patch('browser.manager.sync_playwright')
def test_navigate_mobile_defaults_to_iphone(mock_playwright):
    bm = BrowserManager()
    gb = GlobalBrowser.get_instance()
    gb.browser.new_context.return_value = MagicMock()
    gb.browser.new_context.return_value.new_page.return_value = MagicMock()

    res = bm.navigate_mobile("https://example.com")

    assert "iPhone 13" in res
    assert "390x664" in res


@patch('browser.manager.sync_playwright')
def test_navigate_mobile_unknown_device(mock_playwright):
    bm = BrowserManager()

    res = bm.navigate_mobile("https://example.com", device_name="Nope")
    assert res.startswith("Error: unknown mobile device 'Nope'")
    assert "iPhone 13" in res  # lists available devices


@patch('browser.manager.sync_playwright')
def test_navigate_mobile_navigation_error(mock_playwright):
    bm = BrowserManager()
    gb = GlobalBrowser.get_instance()
    mobile_page = MagicMock()
    mobile_page.goto.side_effect = Exception("boom")
    mobile_context = MagicMock()
    mobile_context.new_page.return_value = mobile_page
    gb.browser.new_context.return_value = mobile_context

    res = bm.navigate_mobile("https://example.com")
    assert res.startswith("Error navigating to https://example.com in mobile mode")
    assert "boom" in res



# --------------------------------------------------------------------------- #
# tools.<os>.browser.browser_navigate_mobile (wrappers)
# --------------------------------------------------------------------------- #

def test_browser_navigate_mobile_wrapper(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = br_module.current_session_id.set("sess-mock")

    mock_bm = MagicMock()
    mock_bm.navigate_mobile.return_value = "Navigated in mobile mode"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)

    res = br_module.browser_navigate_mobile("https://example.com", device_name="Galaxy S24")
    assert res == "Navigated in mobile mode"
    mock_bm.navigate_mobile.assert_called_once_with(
        "https://example.com", device_name="Galaxy S24"
    )
    br_module.current_session_id.reset(token)


def test_browser_navigate_mobile_default_device(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = br_module.current_session_id.set("sess-mock")

    mock_bm = MagicMock()
    mock_bm.navigate_mobile.return_value = "ok"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)

    br_module.browser_navigate_mobile("https://example.com")
    mock_bm.navigate_mobile.assert_called_once_with(
        "https://example.com", device_name="iPhone 13"
    )
    br_module.current_session_id.reset(token)


def test_browser_navigate_mobile_requires_permission(br_setup, mocker):
    """Without PERM_PLAYWRIGHT the wrapper must not touch the browser manager."""
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='false')
    token = br_module.current_session_id.set("sess-mock")

    mock_bm = MagicMock()
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)

    res = br_module.browser_navigate_mobile("https://example.com")
    assert "Access denied" in res
    assert "PERM_PLAYWRIGHT" in res
    mock_bm.navigate_mobile.assert_not_called()
    br_module.current_session_id.reset(token)


def test_browser_navigate_mobile_is_registered_as_tool():
    """The tool must be auto-discovered so the agent can actually call it."""
    from tools import AVAILABLE_TOOLS
    names = [getattr(t, "__name__", "") for t in AVAILABLE_TOOLS]
    assert "browser_navigate_mobile" in names


def test_windows_parity_browser_navigate_mobile():
    """Windows exposes the same mobile-browsing capability as macOS/Linux."""
    from tools.linux.browser import browser_navigate_mobile as lin
    from tools.macos.browser import browser_navigate_mobile as mac
    from tools.windows.browser import browser_navigate_mobile as win

    assert callable(win)
    assert "mobile" in win.__doc__.lower()
    # Identical signature across the three OS variants (verbatim copy).
    assert (
        list(win.__annotations__.keys())
        == list(lin.__annotations__.keys())
        == list(mac.__annotations__.keys())
    )

