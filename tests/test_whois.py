import pytest
from unittest.mock import patch, MagicMock

from tools.linux import whois_lookup as linux_whois
from tools.macos import whois_lookup as macos_whois
from tools.windows import whois_lookup as windows_whois

@pytest.fixture(params=[linux_whois, macos_whois, windows_whois])
def whois_module(request):
    """Parameterize across OS versions of whois_lookup.py."""
    return request.param

def test_get_whois_rdap_httperror(whois_module, mocker):
    mock_urlopen = mocker.patch.object(whois_module.urllib.request, 'urlopen')
    error = whois_module.urllib.error.HTTPError("url", 404, "Not Found", {}, None)
    mock_urlopen.side_effect = error
    
    res = whois_module.get_whois_rdap("example.com")
    assert "HTTP Error performing WHOIS RDAP lookup for 'example.com': 404 Not Found" in res

def test_get_whois_rdap_exception(whois_module, mocker):
    mock_urlopen = mocker.patch.object(whois_module.urllib.request, 'urlopen')
    mock_urlopen.side_effect = Exception("Network error")
    
    res = whois_module.get_whois_rdap("example.com")
    assert "Error performing WHOIS RDAP lookup for 'example.com': Network error" in res
