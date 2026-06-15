import pytest
from unittest.mock import patch, MagicMock

# Import gatherers (for linux/macos/windows)
from tools.linux import binance_crypto_price as linux_binance
from tools.macos import binance_crypto_price as macos_binance
from tools.windows import binance_crypto_price as windows_binance

from tools.linux import get_currency_or_metal_price as linux_currency
from tools.macos import get_currency_or_metal_price as macos_currency
from tools.windows import get_currency_or_metal_price as windows_currency

from tools.linux import web_search as linux_search
from tools.macos import web_search as macos_search
from tools.windows import web_search as windows_search

from tools.linux import web_scraper as linux_scraper
from tools.macos import web_scraper as macos_scraper
from tools.windows import web_scraper as windows_scraper

from tools.linux import whois_lookup as linux_whois
from tools.macos import whois_lookup as macos_whois
from tools.windows import whois_lookup as windows_whois

@pytest.fixture(params=[
    (linux_binance, linux_currency, linux_search, linux_scraper, linux_whois),
    (macos_binance, macos_currency, macos_search, macos_scraper, macos_whois),
    (windows_binance, windows_currency, windows_search, windows_scraper, windows_whois)
])
def gatherer_setup(request):
    return request.param

def test_binance_success(gatherer_setup, mocker):
    binance, _, _, _, _ = gatherer_setup
    mock_resp = MagicMock()
    mock_resp.json.return_value = {'symbol': 'BTCUSDT', 'price': '60000'}
    mocker.patch('requests.get', return_value=mock_resp)
    res = binance.get_binance_crypto_price("BTCUSDT")
    assert "60000" in res

def test_binance_error(gatherer_setup, mocker):
    import requests
    binance, _, _, _, _ = gatherer_setup
    mocker.patch('requests.get', side_effect=requests.exceptions.RequestException("API Down"))
    res = binance.get_binance_crypto_price("BTCUSDT")
    assert "Error fetching price" in res

def test_currency_success(gatherer_setup, mocker):
    _, currency, _, _, _ = gatherer_setup
    mock_resp = MagicMock()
    mock_resp.json.return_value = {'USDBRL': {'name': 'Dolar', 'bid': '5.00'}}
    mocker.patch('requests.get', return_value=mock_resp)
    res = currency.get_currency_or_metal_price("USD-BRL")
    assert "5.00" in res

def test_currency_error(gatherer_setup, mocker):
    import requests
    _, currency, _, _, _ = gatherer_setup
    mocker.patch('requests.get', side_effect=requests.exceptions.RequestException("API Down"))
    res = currency.get_currency_or_metal_price("USD-BRL")
    assert "Error fetching price" in res

def test_web_search_success(gatherer_setup, mocker):
    _, _, search, _, _ = gatherer_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    mock_ddgs = MagicMock()
    mock_ddgs.text.return_value = [{'title': 'Python', 'href': 'url', 'body': 'code'}]
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_ddgs
    
    mocker.patch('tools.linux.web_search.DDGS', return_value=mock_context)
    mocker.patch('tools.macos.web_search.DDGS', return_value=mock_context)
    mocker.patch('tools.windows.web_search.DDGS', return_value=mock_context)

    res = search.search_web("python", 1)
    assert "Python" in res

def test_web_scraper_success(gatherer_setup, mocker):
    _, _, _, scraper, _ = gatherer_setup
    mock_resp = MagicMock()
    mock_resp.text = "<html><body>Text</body></html>"
    
    mocker.patch('tools.linux.web_scraper.requests.get', return_value=mock_resp)
    mocker.patch('tools.macos.web_scraper.requests.get', return_value=mock_resp)
    mocker.patch('tools.windows.web_scraper.requests.get', return_value=mock_resp)
    
    mocker.patch('tools.linux.web_scraper.trafilatura.extract', return_value="Text")
    mocker.patch('tools.macos.web_scraper.trafilatura.extract', return_value="Text")
    mocker.patch('tools.windows.web_scraper.trafilatura.extract', return_value="Text")

    res = scraper.extract_webpage_text("http://test.com")
    assert "Text" in res

def test_whois_success(gatherer_setup, mocker):
    _, _, _, _, whois_mod = gatherer_setup
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"domain": "test.com"}'
    
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_resp
    mocker.patch('urllib.request.urlopen', return_value=mock_context)
    
    res = whois_mod.get_whois_rdap("test.com")
    assert "test.com" in res
