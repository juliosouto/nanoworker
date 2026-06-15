import pytest
from unittest.mock import patch, MagicMock

from tools.linux import web_scraper as linux_ws
from tools.macos import web_scraper as macos_ws
from tools.windows import web_scraper as windows_ws

@pytest.fixture(params=[linux_ws, macos_ws, windows_ws])
def ws_module(request):
    """Parameterize across OS versions of web_scraper.py."""
    return request.param

def test_extract_webpage_text_success_requests(ws_module, mocker):
    mock_response = MagicMock()
    mock_response.text = "<html><body>Hello</body></html>"
    
    mock_requests = mocker.patch.object(ws_module, 'requests')
    mock_requests.get.return_value = mock_response
    
    mock_trafilatura = mocker.patch.object(ws_module, 'trafilatura')
    mock_trafilatura.extract.return_value = "Hello"
    
    res = ws_module.extract_webpage_text("http://example.com")
    
    assert res == "Hello"
    mock_requests.get.assert_called_once_with("http://example.com", impersonate="chrome146", timeout=15)
    mock_trafilatura.extract.assert_called_once_with("<html><body>Hello</body></html>")

def test_extract_webpage_text_fallback_playwright_trafilatura_success(ws_module, mocker):
    mock_requests = mocker.patch.object(ws_module, 'requests')
    mock_requests.get.side_effect = Exception("Curl failed")
    
    mock_trafilatura = mocker.patch.object(ws_module, 'trafilatura')
    mock_trafilatura.extract.return_value = "Playwright Hello"
    
    mock_playwright = mocker.patch.object(ws_module, 'sync_playwright')
    mock_context = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()
    
    mock_page.content.return_value = "<html>Playwright</html>"
    mock_browser.new_page.return_value = mock_page
    mock_context.chromium.launch.return_value = mock_browser
    
    mock_playwright.return_value.__enter__.return_value = mock_context
    
    res = ws_module.extract_webpage_text("http://example.com")
    
    assert res == "Playwright Hello"
    mock_page.goto.assert_called_once()
    mock_page.content.assert_called_once()
    mock_browser.close.assert_called_once()

def test_extract_webpage_text_fallback_playwright_innertext(ws_module, mocker):
    mock_requests = mocker.patch.object(ws_module, 'requests')
    mock_requests.get.side_effect = Exception("Curl failed")
    
    mock_trafilatura = mocker.patch.object(ws_module, 'trafilatura')
    mock_trafilatura.extract.return_value = None  # Fails in Playwright too
    
    mock_playwright = mocker.patch.object(ws_module, 'sync_playwright')
    mock_context = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()
    
    mock_page.content.return_value = "<html><body>Fallback</body></html>"
    mock_page.locator.return_value.inner_text.return_value = "Fallback"
    mock_browser.new_page.return_value = mock_page
    mock_context.chromium.launch.return_value = mock_browser
    
    mock_playwright.return_value.__enter__.return_value = mock_context
    
    res = ws_module.extract_webpage_text("http://example.com")
    
    assert res == "Fallback"
    mock_page.locator.assert_called_with("body")

def test_extract_webpage_text_exception(ws_module, mocker):
    mock_requests = mocker.patch.object(ws_module, 'requests')
    mock_requests.get.side_effect = Exception("Curl failed")
    
    mock_playwright = mocker.patch.object(ws_module, 'sync_playwright')
    mock_playwright.side_effect = Exception("Playwright failed")
    
    res = ws_module.extract_webpage_text("http://example.com")
    
    assert "Error extracting webpage text: Playwright failed" in res
