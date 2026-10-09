import pytest
from unittest.mock import MagicMock

import tools.linux.browser as linux_browser
import tools.macos.browser as macos_browser


@pytest.fixture
def perm_enabled(mocker):
    # require_permission binds get_config from database at import time, so the
    # patch must target utils.security_utils.get_config (same pattern used by
    # the existing file-utils tests).
    mocker.patch("utils.security_utils.get_config", return_value="true")


def test_linux_browser_screenshot_returns_saved_path(mocker, perm_enabled):
    mocker.patch("tools.linux.browser.get_temp_file_path", return_value="/tmp/shot.png")
    mock_bm = MagicMock()
    mock_bm.take_screenshot.return_value = "Screenshot saved to /tmp/shot.png"
    mocker.patch("tools.linux.browser.get_browser_manager", return_value=mock_bm)

    result = linux_browser.browser_screenshot(full_page=True)

    assert result == "Screenshot saved to /tmp/shot.png"
    mock_bm.take_screenshot.assert_called_once_with("/tmp/shot.png")


def test_linux_browser_screenshot_passes_through_error(mocker, perm_enabled):
    mocker.patch("tools.linux.browser.get_temp_file_path", return_value="/tmp/shot.png")
    mock_bm = MagicMock()
    mock_bm.take_screenshot.return_value = "Error taking screenshot: no page open"
    mocker.patch("tools.linux.browser.get_browser_manager", return_value=mock_bm)

    result = linux_browser.browser_screenshot()
    assert result.startswith("Error taking screenshot")


def test_linux_browser_screenshot_denied_without_permission(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="false")
    result = linux_browser.browser_screenshot()
    assert "Access denied" in result
    assert "PERM_PLAYWRIGHT" in result


def test_macos_browser_screenshot_returns_saved_path(mocker, perm_enabled):
    mocker.patch("tools.macos.browser.get_temp_file_path", return_value="/tmp/shot.png")
    mock_bm = MagicMock()
    mock_bm.take_screenshot.return_value = "Screenshot saved to /tmp/shot.png"
    mocker.patch("tools.macos.browser.get_browser_manager", return_value=mock_bm)

    result = macos_browser.browser_screenshot()
    assert result == "Screenshot saved to /tmp/shot.png"


def test_browser_screenshot_is_registered_as_tool():
    """The new tool must be auto-discovered by the tools loader on Linux and
    macOS so the agent can actually call it (this was the root cause of the
    X11/scrot failure: take_screenshot existed in the manager but was never
    exposed as a tool)."""
    import platform

    from tools import AVAILABLE_TOOLS

    tool_names = [getattr(t, "__name__", "") for t in AVAILABLE_TOOLS]
    assert "browser_screenshot" in tool_names