import pytest
from unittest.mock import MagicMock, patch
import time

from browser.manager import GlobalBrowser, BrowserManager, get_session_browser, _sessions, _cleanup_idle_sessions

@pytest.fixture(autouse=True)
def reset_globals(mocker):
    GlobalBrowser._instance = None
    _sessions.clear()
    import browser.manager
    browser.manager._cleanup_thread_started = False
    mocker.patch('threading.Thread.start')
    
@patch('browser.manager.sync_playwright')
def test_global_browser_singleton(mock_playwright):
    mock_pw_instance = MagicMock()
    mock_playwright.return_value.start.return_value = mock_pw_instance
    
    b1 = GlobalBrowser.get_instance()
    b2 = GlobalBrowser.get_instance()
    
    assert b1 is b2
    mock_playwright.assert_called_once()
    mock_pw_instance.chromium.launch.assert_called_once()

@patch('browser.manager.sync_playwright')
def test_browser_manager_init(mock_playwright):
    bm = BrowserManager()
    assert bm.context is not None
    assert bm.page is not None
    assert bm.last_activity > 0

@patch('browser.manager.sync_playwright')
def test_browser_manager_start_browser(mock_playwright):
    bm = BrowserManager()
    
    with patch.object(GlobalBrowser.get_instance(), 'new_context') as mock_new_context:
        bm.start_browser(storage_state="state.json", proxy="proxy_url", user_agent="ua")
        mock_new_context.assert_called_once_with(storage_state="state.json", proxy="proxy_url", user_agent="ua")

@patch('browser.manager.sync_playwright')
def test_navigate_success(mock_playwright):
    bm = BrowserManager()
    bm.page.goto.return_value = None
    res = bm.navigate("http://example.com")
    assert "Navigated to" in res
    bm.page.goto.assert_called_with("http://example.com", wait_until="domcontentloaded", timeout=30000)

@patch('browser.manager.sync_playwright')
def test_navigate_error(mock_playwright):
    bm = BrowserManager()
    bm.page.goto.side_effect = Exception("Nav Error")
    res = bm.navigate("http://example.com")
    assert "Error navigating" in res

@patch('browser.manager.sync_playwright')
def test_get_snapshot_success(mock_playwright):
    bm = BrowserManager()
    bm.page.evaluate.return_value = "snapshot_data"
    res = bm.get_snapshot()
    assert res == "snapshot_data"

@patch('browser.manager.sync_playwright')
def test_get_snapshot_empty(mock_playwright):
    bm = BrowserManager()
    bm.page.evaluate.return_value = ""
    res = bm.get_snapshot()
    assert "No interactive elements" in res

@patch('browser.manager.sync_playwright')
def test_get_snapshot_error(mock_playwright):
    bm = BrowserManager()
    bm.page.evaluate.side_effect = Exception("JS Error")
    res = bm.get_snapshot()
    assert "Error generating snapshot" in res

@patch('browser.manager.sync_playwright')
def test_click_success(mock_playwright):
    bm = BrowserManager()
    res = bm.click("e1")
    assert "Clicked on e1" in res

@patch('browser.manager.sync_playwright')
def test_click_error(mock_playwright):
    bm = BrowserManager()
    bm.page.locator.side_effect = Exception("Locate Error")
    res = bm.click("e1")
    assert "Error clicking" in res

@patch('browser.manager.sync_playwright')
def test_fill_success(mock_playwright):
    bm = BrowserManager()
    res = bm.fill("e1", "hello")
    assert "Filled e1" in res

@patch('browser.manager.sync_playwright')
def test_fill_error(mock_playwright):
    bm = BrowserManager()
    bm.page.locator.side_effect = Exception("Locate Error")
    res = bm.fill("e1", "hello")
    assert "Error filling" in res

@patch('browser.manager.sync_playwright')
def test_extract_success(mock_playwright):
    bm = BrowserManager()
    mock_element = MagicMock()
    mock_element.inner_text.return_value = "text val"
    mock_element.inner_html.return_value = "html val"
    mock_element.get_attribute.return_value = "attr val"
    bm.page.locator().first = mock_element
    
    assert bm.extract("e1", "text") == "text val"
    assert bm.extract("e1", "html") == "html val"
    assert bm.extract("e1", "href") == "attr val"

@patch('browser.manager.sync_playwright')
def test_extract_error(mock_playwright):
    bm = BrowserManager()
    bm.page.locator.side_effect = Exception("Extr Error")
    res = bm.extract("e1", "text")
    assert "Error extracting" in res

@patch('browser.manager.sync_playwright')
def test_run_js_success(mock_playwright):
    bm = BrowserManager()
    bm.page.evaluate.return_value = "js result"
    assert bm.run_js("1+1") == "js result"

@patch('browser.manager.sync_playwright')
def test_run_js_error(mock_playwright):
    bm = BrowserManager()
    bm.page.evaluate.side_effect = Exception("JS eval error")
    assert "Error executing JS" in bm.run_js("bad()")

@patch('browser.manager.sync_playwright')
def test_take_screenshot_success(mock_playwright):
    bm = BrowserManager()
    res = bm.take_screenshot("/tmp/test.png")
    assert "Screenshot saved" in res

@patch('browser.manager.sync_playwright')
def test_take_screenshot_error(mock_playwright):
    bm = BrowserManager()
    bm.page.screenshot.side_effect = Exception("Scr Error")
    res = bm.take_screenshot("/tmp/test.png")
    assert "Error taking screenshot" in res

@patch('browser.manager.sync_playwright')
def test_cookies(mock_playwright):
    bm = BrowserManager()
    bm.context.cookies.return_value = [{'name': 'c1'}]
    assert bm.get_cookies() == [{'name': 'c1'}]
    
    bm.add_cookies([{'name': 'c2'}])
    bm.context.add_cookies.assert_called()

@patch('browser.manager.sync_playwright')
def test_save_state(mock_playwright):
    bm = BrowserManager()
    bm.save_state("/tmp/state.json")
    bm.context.storage_state.assert_called()

@patch('browser.manager.sync_playwright')
def test_get_session_browser(mock_playwright):
    b1 = get_session_browser("sess_1")
    b2 = get_session_browser("sess_1")
    assert b1 is b2
    
    b3 = get_session_browser("sess_2")
    assert b1 is not b3

@patch('browser.manager.sync_playwright')
def test_cleanup_idle_sessions(mock_playwright):
    with patch('time.sleep', side_effect=[None, KeyboardInterrupt("Stop loop")]):
        with patch('browser.manager.logger') as mock_logger:
            with patch('time.time', return_value=time.time() + 1000):
                # get_session_browser spawns the thread internally, 
                # but we will just call the function directly to test the logic
                b1 = BrowserManager()
                b1.last_activity = time.time() - 2000
                import browser.manager
                browser.manager._sessions["idle_sess"] = b1
                try:
                    browser.manager._cleanup_idle_sessions()
                except KeyboardInterrupt as e:
                    assert str(e) == "Stop loop"
    
    assert "idle_sess" not in browser.manager._sessions
