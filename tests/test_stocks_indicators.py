import pytest
import json
from unittest.mock import patch, MagicMock

from tools.linux import stocks_indicators_and_analysis as linux_sia
from tools.macos import stocks_indicators_and_analysis as macos_sia
from tools.windows import stocks_indicators_and_analysis as windows_sia

@pytest.fixture(params=[linux_sia, macos_sia, windows_sia])
def sia_module(request):
    """Parameterize across OS versions of stocks_indicators_and_analysis.py."""
    return request.param

def test_stocks_not_installed(sia_module, mocker):
    mocker.patch.object(sia_module, 'TA_Handler', None)
    res = sia_module.get_stocks_indicators_and_analysis("TSLA")
    assert "Error: tradingview_ta is not installed" in res

def test_stocks_success(sia_module, mocker):
    mock_ta = MagicMock()
    mock_handler_instance = MagicMock()
    
    mock_analise = MagicMock()
    mock_analise.summary = {"RECOMMENDATION": "BUY"}
    mock_analise.indicators = {"RSI": 60}
    mock_handler_instance.get_analysis.return_value = mock_analise
    
    mock_ta.return_value = mock_handler_instance
    mocker.patch.object(sia_module, 'TA_Handler', mock_ta)
    
    mock_interval = MagicMock()
    mock_interval.INTERVAL_1_DAY = "1d"
    mocker.patch.object(sia_module, 'Interval', mock_interval)
    
    res = sia_module.get_stocks_indicators_and_analysis("TSLA", interval="1d")
    
    data = json.loads(res)
    assert data["summary"]["RECOMMENDATION"] == "BUY"
    assert data["indicators"]["RSI"] == 60
    
    mock_ta.assert_called_once_with(symbol="TSLA", screener="america", exchange="NASDAQ", interval="1d")

def test_stocks_exception(sia_module, mocker):
    mock_ta = MagicMock()
    mock_ta.side_effect = Exception("API error")
    mocker.patch.object(sia_module, 'TA_Handler', mock_ta)
    
    mock_interval = MagicMock()
    mock_interval.INTERVAL_1_DAY = "1d"
    mocker.patch.object(sia_module, 'Interval', mock_interval)
    
    res = sia_module.get_stocks_indicators_and_analysis("TSLA")
    assert "Error fetching analysis for TSLA: API error" in res
