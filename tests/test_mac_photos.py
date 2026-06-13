import pytest
import subprocess
import os
from unittest.mock import patch, MagicMock

from tools.macos import mac_photos

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

def test_get_recent_photos_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ID: 1 | Name: photo.jpg | Date: 2023-01-01"
    mock_run.return_value = mock_result
    
    res = mac_photos.get_recent_photos(limit=5)
    assert "photo.jpg" in res

def test_get_recent_photos_error_returncode(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "AppleScript failed"
    mock_run.return_value = mock_result
    
    res = mac_photos.get_recent_photos(limit=5)
    assert "Error accessing Photos: AppleScript failed" in res

def test_get_recent_photos_timeout(mocker):
    mock_run = mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_photos.get_recent_photos(limit=5)
    assert "Error: Request to Photos app timed out." in res

def test_get_recent_photos_exception(mocker):
    mock_run = mocker.patch('subprocess.run', side_effect=Exception("System failure"))
    res = mac_photos.get_recent_photos(limit=5)
    assert "Error executing AppleScript: System failure" in res

def test_list_albums_success(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Album: Vacation | ID: 123"
    mock_run.return_value = mock_result
    
    res = mac_photos.list_albums()
    assert "Vacation" in res

def test_list_albums_error(mocker):
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "AppleScript error"
    mock_run.return_value = mock_result
    
    res = mac_photos.list_albums()
    assert "Error accessing Photos: AppleScript error" in res

def test_list_albums_timeout(mocker):
    mock_run = mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30))
    res = mac_photos.list_albums()
    assert "Error: Request to Photos app timed out." in res

def test_list_albums_exception(mocker):
    mock_run = mocker.patch('subprocess.run', side_effect=Exception("Crash"))
    res = mac_photos.list_albums()
    assert "Error executing AppleScript: Crash" in res

def test_export_photos_success(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Exported 1 photos successfully"
    mock_run.return_value = mock_result
    
    res = mac_photos.export_photos(["123"], "/tmp/photos")
    assert "Exported 1 photos successfully" in res

def test_export_photos_create_dir_error(mocker):
    mocker.patch('os.path.exists', return_value=False)
    mocker.patch('os.makedirs', side_effect=Exception("Permission denied"))
    
    res = mac_photos.export_photos(["123"], "/tmp/photos")
    assert "Error creating destination directory: Permission denied" in res

def test_export_photos_no_ids(mocker):
    mocker.patch('os.path.exists', return_value=True)
    res = mac_photos.export_photos([], "/tmp/photos")
    assert "Error: No photo IDs provided" in res

def test_export_photos_subprocess_error(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mock_run = mocker.patch('subprocess.run')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "AppleScript failed"
    mock_run.return_value = mock_result
    
    res = mac_photos.export_photos(["123"], "/tmp/photos")
    assert "Error exporting photos: AppleScript failed" in res

def test_export_photos_timeout(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=60))
    res = mac_photos.export_photos(["123"], "/tmp/photos")
    assert "Error: Request to export photos timed out." in res

def test_export_photos_exception(mocker):
    mocker.patch('os.path.exists', return_value=True)
    mocker.patch('subprocess.run', side_effect=Exception("Unknown Error"))
    res = mac_photos.export_photos(["123"], "/tmp/photos")
    assert "Error executing AppleScript: Unknown Error" in res

def test_delete_photos():
    # Since deletion is disabled
    res = mac_photos.delete_photos(["123"])
    assert "disabled for safety reasons" in res
