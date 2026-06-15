import pytest
import subprocess
from unittest.mock import patch, MagicMock

from tools.macos import mac_mail

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

def test_search_mac_mail_short_query(mocker):
    res = mac_mail.search_mac_mail("a")
    assert "Error: Please provide a valid query string" in res

def test_search_mac_mail_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ID: 123 | Sender: test@test.com"
    mock_run.return_value = mock_result
    
    res = mac_mail.search_mac_mail("test")
    assert "test@test.com" in res

def test_search_mac_mail_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "AppleScript failed"
    mock_run.return_value = mock_result
    
    res = mac_mail.search_mac_mail("test")
    assert "Error searching Mail: AppleScript failed" in res

def test_search_mac_mail_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_mail.search_mac_mail("test")
    assert "Error: Request to Mail app timed out." in res

def test_search_mac_mail_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("System failure"))
    res = mac_mail.search_mac_mail("test")
    assert "Error executing AppleScript: System failure" in res

def test_read_mac_mail_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Sender: test@test.com\nSubject: Hello\n---\nHello there"
    mock_run.return_value = mock_result
    
    res = mac_mail.read_mac_mail(123)
    assert "Hello there" in res

def test_read_mac_mail_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Error reading email"
    mock_run.return_value = mock_result
    res = mac_mail.read_mac_mail(123)
    assert "Error reading Mail: Error reading email" in res

def test_read_mac_mail_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_mail.read_mac_mail(123)
    assert "Error: Request to Mail app timed out." in res

def test_read_mac_mail_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("System failure"))
    res = mac_mail.read_mac_mail(123)
    assert "Error executing AppleScript: System failure" in res

def test_get_recent_mac_mail_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ID: 123 | Sender: recent@test.com"
    mock_run.return_value = mock_result
    
    res = mac_mail.get_recent_mac_mail()
    assert "recent@test.com" in res

def test_get_recent_mac_mail_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_mail.get_recent_mac_mail()
    assert "Error fetching recent Mail: fail" in res

def test_get_recent_mac_mail_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_mail.get_recent_mac_mail()
    assert "Error: Request to Mail app timed out." in res

def test_get_recent_mac_mail_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("System failure"))
    res = mac_mail.get_recent_mac_mail()
    assert "Error executing AppleScript: System failure" in res
