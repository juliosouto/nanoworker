import pytest
import json
from unittest.mock import patch, MagicMock

from tools.linux import web_search as linux_ws
from tools.macos import web_search as macos_ws
from tools.windows import web_search as windows_ws

@pytest.fixture(params=[linux_ws, macos_ws, windows_ws])
def ws_module(request):
    """Parameterize across OS versions of web_search.py."""
    return request.param

def test_search_web_no_results(ws_module, mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')  # Mock security
    
    mock_ddgs = mocker.patch.object(ws_module, 'DDGS')
    mock_instance = MagicMock()
    mock_instance.text.return_value = []
    mock_ddgs.return_value.__enter__.return_value = mock_instance
    
    res = ws_module.search_web("query_with_no_results", max_results=5)
    assert "No results found for query" in res

def test_search_web_exception(ws_module, mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    mock_ddgs = mocker.patch.object(ws_module, 'DDGS')
    mock_ddgs.side_effect = Exception("API error")
    
    res = ws_module.search_web("query", max_results=5)
    assert "Error performing web search for 'query': API error" in res
