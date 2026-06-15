import pytest
import subprocess
from datetime import datetime
from unittest.mock import patch, MagicMock

from tools.macos import mac_calendar

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

def test_get_mac_calendar_events_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Calendar: Work | Event: Meeting | Start: 10:00 | End: 11:00"
    mock_run.return_value = mock_result
    
    res = mac_calendar.get_mac_calendar_events(1)
    assert "Meeting" in res

def test_get_mac_calendar_events_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_calendar.get_mac_calendar_events(1)
    assert "Error accessing Calendar: fail" in res

def test_get_mac_calendar_events_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_calendar.get_mac_calendar_events()
    assert "Error: Request to Calendar app timed out." in res

def test_get_mac_calendar_events_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_calendar.get_mac_calendar_events()
    assert "Error executing AppleScript: Crash" in res

def test_create_mac_calendar_event_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Event created successfully"
    mock_run.return_value = mock_result
    
    res = mac_calendar.create_mac_calendar_event("Work", "Meeting", "2026-05-21T10:00:00Z", "2026-05-21T11:00:00Z")
    assert "Event created successfully" in res

def test_create_mac_calendar_event_invalid_date():
    res = mac_calendar.create_mac_calendar_event("Work", "Meeting", "bad date", "2026-05-21T11:00:00Z")
    assert "Error parsing dates" in res

def test_create_mac_calendar_event_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_calendar.create_mac_calendar_event("Work", "Meeting", "2026-05-21T10:00:00Z", "2026-05-21T11:00:00Z")
    assert "Error creating event: fail" in res

def test_create_mac_calendar_event_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_calendar.create_mac_calendar_event("Work", "Meeting", "2026-05-21T10:00:00Z", "2026-05-21T11:00:00Z")
    assert "Error: Request to Calendar app timed out." in res

def test_create_mac_calendar_event_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_calendar.create_mac_calendar_event("Work", "Meeting", "2026-05-21T10:00:00Z", "2026-05-21T11:00:00Z")
    assert "Error executing AppleScript: Crash" in res
