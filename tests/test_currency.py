import pytest
from unittest.mock import patch, MagicMock

from tools.linux import get_currency_or_metal_price as linux_curr
from tools.macos import get_currency_or_metal_price as macos_curr
from tools.windows import get_currency_or_metal_price as windows_curr

@pytest.fixture(params=[linux_curr, macos_curr, windows_curr])
def curr_module(request):
    """Parameterize across OS versions."""
    return request.param

def test_get_currency_not_found(curr_module, mocker):
    mock_get = mocker.patch.object(curr_module.requests, 'get')
    mock_response = MagicMock()
    mock_response.json.return_value = {"OTHER": {"name": "Other", "bid": "1.0"}}
    mock_get.return_value = mock_response
    
    res = curr_module.get_currency_or_metal_price("XAU-BRL")
    assert "Error: Could not find data for the pair XAU-BRL." in res

def test_get_currency_json_value_error(curr_module, mocker):
    mock_get = mocker.patch.object(curr_module.requests, 'get')
    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("Bad JSON")
    mock_get.return_value = mock_response
    
    res = curr_module.get_currency_or_metal_price("XAU-BRL")
    assert "Error parsing the API response: Bad JSON" in res
