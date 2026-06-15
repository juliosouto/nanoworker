import pytest
import subprocess
from unittest.mock import patch, MagicMock

from tools.macos import mac_notes

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

def test_list_mac_notes_no_folder(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Folder: iCloud | Note: Ideas"
    mock_run.return_value = mock_result
    
    res = mac_notes.list_mac_notes()
    assert "Ideas" in res

def test_list_mac_notes_with_folder(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "- Ideas"
    mock_run.return_value = mock_result
    
    res = mac_notes.list_mac_notes(folder_name="Work")
    assert "Ideas" in res

def test_list_mac_notes_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "AppleScript failed"
    mock_run.return_value = mock_result
    
    res = mac_notes.list_mac_notes()
    assert "Error accessing Notes: AppleScript failed" in res

def test_list_mac_notes_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_notes.list_mac_notes()
    assert "Error: Request to Notes app timed out." in res

def test_list_mac_notes_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_notes.list_mac_notes()
    assert "Error executing AppleScript: Crash" in res

def test_read_mac_note_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Note content"
    mock_run.return_value = mock_result
    
    res = mac_notes.read_mac_note("Ideas")
    assert "Note content" in res

def test_read_mac_note_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_notes.read_mac_note("Ideas")
    assert "Error accessing Notes: fail" in res

def test_read_mac_note_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_notes.read_mac_note("Ideas")
    assert "Error: Request to Notes app timed out." in res

def test_read_mac_note_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_notes.read_mac_note("Ideas")
    assert "Error executing AppleScript: Crash" in res

def test_create_mac_note_no_folder(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "created successfully"
    mock_run.return_value = mock_result
    
    res = mac_notes.create_mac_note("Ideas", "body content")
    assert "created successfully" in res

def test_create_mac_note_with_folder(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "created successfully in folder"
    mock_run.return_value = mock_result
    
    res = mac_notes.create_mac_note("Ideas", "body content", folder_name="Work")
    assert "created successfully in folder" in res

def test_create_mac_note_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_notes.create_mac_note("Ideas", "body content")
    assert "Error creating Note: fail" in res

def test_create_mac_note_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_notes.create_mac_note("Ideas", "body content")
    assert "Error: Request to Notes app timed out." in res

def test_create_mac_note_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_notes.create_mac_note("Ideas", "body content")
    assert "Error executing AppleScript: Crash" in res

def test_append_to_mac_note_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "appended successfully"
    mock_run.return_value = mock_result
    
    res = mac_notes.append_to_mac_note("Ideas", "new text")
    assert "appended successfully" in res

def test_append_to_mac_note_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "fail"
    mock_run.return_value = mock_result
    res = mac_notes.append_to_mac_note("Ideas", "new text")
    assert "Error appending to Note: fail" in res

def test_append_to_mac_note_timeout(mocker):
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_notes.append_to_mac_note("Ideas", "new text")
    assert "Error: Request to Notes app timed out." in res

def test_append_to_mac_note_exception(mocker):
    mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_notes.append_to_mac_note("Ideas", "new text")
    assert "Error executing AppleScript: Crash" in res
