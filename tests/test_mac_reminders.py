import pytest
import subprocess
from unittest.mock import patch, MagicMock

from tools.macos import mac_reminders

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

def test_list_mac_reminders_no_list(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "List: Tasks | Reminder: Buy milk"
    mock_run.return_value = mock_result
    
    res = mac_reminders.list_mac_reminders()
    assert "Buy milk" in res

def test_list_mac_reminders_with_list(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "- Buy milk"
    mock_run.return_value = mock_result
    
    res = mac_reminders.list_mac_reminders(list_name="Groceries")
    assert "Buy milk" in res

def test_list_mac_reminders_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "AppleScript failed"
    mock_run.return_value = mock_result
    
    res = mac_reminders.list_mac_reminders()
    assert "Error accessing Reminders: AppleScript failed" in res

def test_list_mac_reminders_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_reminders.list_mac_reminders()
    assert "Error: Request to Reminders app timed out." in res

def test_list_mac_reminders_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("System failure"))
    res = mac_reminders.list_mac_reminders()
    assert "Error executing AppleScript: System failure" in res

def test_create_mac_reminder_no_list_no_notes(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "created successfully"
    mock_run.return_value = mock_result
    
    res = mac_reminders.create_mac_reminder("Buy milk")
    assert "created successfully" in res

def test_create_mac_reminder_with_list_and_notes(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "created successfully in list"
    mock_run.return_value = mock_result
    
    res = mac_reminders.create_mac_reminder("Buy milk", notes="2 liters", list_name="Groceries")
    assert "created successfully in list" in res

def test_create_mac_reminder_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Error creating"
    mock_run.return_value = mock_result
    res = mac_reminders.create_mac_reminder("Buy milk")
    assert "Error creating Reminder: Error creating" in res

def test_create_mac_reminder_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_reminders.create_mac_reminder("Buy milk")
    assert "Error: Request to Reminders app timed out." in res

def test_create_mac_reminder_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_reminders.create_mac_reminder("Buy milk")
    assert "Error executing AppleScript: Crash" in res

def test_complete_mac_reminder_no_list(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "completed successfully"
    mock_run.return_value = mock_result
    
    res = mac_reminders.complete_mac_reminder("Buy milk")
    assert "completed successfully" in res

def test_complete_mac_reminder_with_list(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "completed successfully"
    mock_run.return_value = mock_result
    
    res = mac_reminders.complete_mac_reminder("Buy milk", list_name="Groceries")
    assert "completed successfully" in res

def test_complete_mac_reminder_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_reminders.complete_mac_reminder("Buy milk")
    assert "Error completing Reminder: fail" in res

def test_complete_mac_reminder_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_reminders.complete_mac_reminder("Buy milk")
    assert "Error: Request to Reminders app timed out." in res

def test_complete_mac_reminder_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_reminders.complete_mac_reminder("Buy milk")
    assert "Error executing AppleScript: Crash" in res

def test_delete_mac_reminder_no_list(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "deleted successfully"
    mock_run.return_value = mock_result
    
    res = mac_reminders.delete_mac_reminder("Buy milk")
    assert "deleted successfully" in res

def test_delete_mac_reminder_with_list(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "deleted successfully"
    mock_run.return_value = mock_result
    
    res = mac_reminders.delete_mac_reminder("Buy milk", list_name="Groceries")
    assert "deleted successfully" in res

def test_delete_mac_reminder_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_reminders.delete_mac_reminder("Buy milk")
    assert "Error deleting Reminder: fail" in res

def test_delete_mac_reminder_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_reminders.delete_mac_reminder("Buy milk")
    assert "Error: Request to Reminders app timed out." in res

def test_delete_mac_reminder_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_reminders.delete_mac_reminder("Buy milk")
    assert "Error executing AppleScript: Crash" in res
