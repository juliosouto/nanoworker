import pytest
from unittest.mock import patch, MagicMock

from tools.linux import browser as linux_br
from tools.macos import browser as macos_br
from tools.windows import browser as windows_br
from utils.session import current_session_id

@pytest.fixture(params=[
    ("linux", linux_br),
    ("macos", macos_br),
    ("windows", windows_br)
])
def br_setup(request):
    return request.param

def test_browser_navigate(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = current_session_id.set("sess-mock")
    
    mock_bm = MagicMock()
    mock_bm.navigate.return_value = "Navigated"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)
    
    res = br_module.browser_navigate("https://example.com")
    assert res == "Navigated"
    mock_bm.navigate.assert_called_with("https://example.com")
    current_session_id.reset(token)

def test_browser_snapshot(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = current_session_id.set("sess-mock")
    
    mock_bm = MagicMock()
    mock_bm.get_snapshot.return_value = "Snapshot"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)
    
    res = br_module.browser_snapshot(interactive_only=True)
    assert res == "Snapshot"
    mock_bm.get_snapshot.assert_called_with(interactive_only=True)
    current_session_id.reset(token)

def test_browser_click(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = current_session_id.set("sess-mock")
    
    mock_bm = MagicMock()
    mock_bm.click.return_value = "Clicked"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)
    
    res = br_module.browser_click("@e1")
    assert res == "Clicked"
    mock_bm.click.assert_called_with("@e1")
    current_session_id.reset(token)

def test_browser_fill(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = current_session_id.set("sess-mock")
    
    mock_bm = MagicMock()
    mock_bm.fill.return_value = "Filled"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)
    
    res = br_module.browser_fill("@e1", "mytext")
    assert res == "Filled"
    mock_bm.fill.assert_called_with("@e1", "mytext")
    current_session_id.reset(token)

def test_browser_extract(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = current_session_id.set("sess-mock")
    
    mock_bm = MagicMock()
    mock_bm.extract.return_value = "ExtractedText"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)
    
    res = br_module.browser_extract("@e1", "text")
    assert res == "ExtractedText"
    mock_bm.extract.assert_called_with("@e1", "text")
    current_session_id.reset(token)

def test_browser_run_js(br_setup, mocker):
    os_name, br_module = br_setup
    mocker.patch('utils.security_utils.get_config', return_value='true')
    token = current_session_id.set(None)
    
    mock_bm = MagicMock()
    mock_bm.run_js.return_value = "JSResult"
    mocker.patch(f'tools.{os_name}.browser.get_session_browser', return_value=mock_bm)
    
    res = br_module.browser_run_js("return 1+1;")
    assert res == "JSResult"
    mock_bm.run_js.assert_called_with("return 1+1;")
    current_session_id.reset(token)
