import pytest
import subprocess
from unittest.mock import patch, MagicMock

from tools.macos import mac_contacts

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

def test_get_mac_contacts_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Name: John Doe | Phones: 12345 | Emails: john@doe.com"
    mock_run.return_value = mock_result
    
    res = mac_contacts.get_mac_contacts()
    assert "John Doe" in res

def test_get_mac_contacts_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "AppleScript failed"
    mock_run.return_value = mock_result
    
    res = mac_contacts.get_mac_contacts()
    assert "Error accessing Contacts: AppleScript failed" in res

def test_get_mac_contacts_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_contacts.get_mac_contacts()
    assert "Error: Request to Contacts app timed out." in res

def test_get_mac_contacts_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("System failure"))
    res = mac_contacts.get_mac_contacts()
    assert "Error executing AppleScript: System failure" in res

def test_search_mac_contacts_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Name: John Doe"
    mock_run.return_value = mock_result
    
    res = mac_contacts.search_mac_contacts("John")
    assert "John Doe" in res

def test_search_mac_contacts_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    
    res = mac_contacts.search_mac_contacts("John")
    assert "Error searching Contacts: fail" in res

def test_search_mac_contacts_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_contacts.search_mac_contacts("John")
    assert "Error: Request to Contacts app timed out." in res

def test_search_mac_contacts_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_contacts.search_mac_contacts("John")
    assert "Error executing AppleScript: Crash" in res

def test_create_mac_contact_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "created successfully"
    mock_run.return_value = mock_result
    
    res = mac_contacts.create_mac_contact("Jane", "Doe", "555-1234", "jane@doe.com")
    assert "created successfully" in res

def test_create_mac_contact_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    
    res = mac_contacts.create_mac_contact("Jane")
    assert "Error creating contact: fail" in res

def test_create_mac_contact_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_contacts.create_mac_contact("Jane")
    assert "Error: Request to Contacts app timed out." in res

def test_create_mac_contact_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_contacts.create_mac_contact("Jane")
    assert "Error executing AppleScript: Crash" in res
