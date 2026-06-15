import pytest
from unittest.mock import patch, MagicMock

from tools.windows import windows_screenshot

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

def test_take_windows_screenshot_success_custom_path(mocker):
    mocker.patch('time.sleep')
    mock_grab = mocker.patch('PIL.ImageGrab.grab')
    mock_img = MagicMock()
    mock_grab.return_value = mock_img
    
    res = windows_screenshot.take_windows_screenshot("/custom/path.png")
    mock_img.save.assert_called_once_with("/custom/path.png")
    assert "/custom/path.png" in res

def test_take_windows_screenshot_success_default_path(mocker):
    mocker.patch('time.sleep')
    mocker.patch('os.makedirs')
    mock_grab = mocker.patch('PIL.ImageGrab.grab')
    mock_img = MagicMock()
    mock_grab.return_value = mock_img
    
    res = windows_screenshot.take_windows_screenshot()
    assert "temp/screenshots/screenshot_" in res
    assert mock_img.save.call_count == 1

def test_take_windows_screenshot_exception(mocker):
    mocker.patch('time.sleep')
    mocker.patch('os.makedirs')
    mocker.patch('PIL.ImageGrab.grab', side_effect=Exception("Grab failed"))
    
    res = windows_screenshot.take_windows_screenshot()
    assert "Error taking screenshot: Grab failed" in res
