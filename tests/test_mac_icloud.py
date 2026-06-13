import pytest
import os
from unittest.mock import patch, MagicMock, mock_open

from tools.macos import mac_icloud

@pytest.fixture(autouse=True)
def mock_permissions(mocker):
    mocker.patch('utils.security_utils.get_config', return_value='true')

@pytest.fixture(autouse=True)
def mock_icloud_drive_exists(mocker):
    # Ensure ICLOUD_DRIVE_PATH always "exists" so _get_absolute_icloud_path doesn't fail early
    mocker.patch('os.path.exists', return_value=True)

def test_get_absolute_icloud_path_not_exists(mocker):
    mocker.patch('os.path.exists', return_value=False)
    with pytest.raises(Exception, match="iCloud Drive folder not found at"):
        mac_icloud._get_absolute_icloud_path("file.txt")

def test_get_absolute_icloud_path_out_of_bounds(mocker):
    with pytest.raises(ValueError, match="Access to paths outside of iCloud Drive is restricted"):
        mac_icloud._get_absolute_icloud_path("../../../etc/passwd")

def test_list_icloud_files_not_dir(mocker):
    mocker.patch('os.path.isdir', return_value=False)
    with pytest.raises(NotADirectoryError, match="The path is not a directory or does not exist"):
        mac_icloud.list_icloud_files("folder")

def test_list_icloud_files_permission_error(mocker):
    mocker.patch('os.path.isdir', return_value=True)
    mocker.patch('os.listdir', side_effect=PermissionError("Access Denied"))
    with pytest.raises(PermissionError, match="Permission denied when accessing"):
        mac_icloud.list_icloud_files("folder")

def test_list_icloud_files_success(mocker):
    mocker.patch('os.path.isdir', side_effect=lambda p: p.endswith("folder") or p.endswith("dir1"))
    mocker.patch('os.path.isfile', side_effect=lambda p: p.endswith("file.txt"))
    mocker.patch('os.listdir', return_value=["file.txt", "dir1"])
    mocker.patch('os.path.getsize', return_value=1024)
    
    items = mac_icloud.list_icloud_files("folder")
    assert len(items) == 2
    assert items[0]["name"] == "file.txt"
    assert not items[0]["is_dir"]
    assert items[0]["size"] == 1024
    
    assert items[1]["name"] == "dir1"
    assert items[1]["is_dir"]
    assert items[1]["size"] is None

def test_read_icloud_file_not_found(mocker):
    mocker.patch('os.path.isfile', return_value=False)
    with pytest.raises(FileNotFoundError, match="File not found"):
        mac_icloud.read_icloud_file("test.txt")

def test_read_icloud_file_success(mocker):
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('builtins.open', mock_open(read_data="hello icloud"))
    content = mac_icloud.read_icloud_file("test.txt")
    assert content == "hello icloud"

def test_read_icloud_file_permission_error(mocker):
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('builtins.open', side_effect=PermissionError("Denied"))
    with pytest.raises(PermissionError, match="Permission denied when reading"):
        mac_icloud.read_icloud_file("test.txt")

def test_read_icloud_file_unicode_error(mocker):
    mocker.patch('os.path.isfile', return_value=True)
    mocker.patch('builtins.open', side_effect=UnicodeDecodeError('utf-8', b'', 1, 2, 'invalid start byte'))
    with pytest.raises(ValueError, match="The file appears to be binary or is not UTF-8 encoded"):
        mac_icloud.read_icloud_file("test.txt")

def test_write_icloud_file_success_new_dir(mocker):
    mocker.patch('os.path.exists', side_effect=lambda p: False if "new_dir" in p else True)
    mock_makedirs = mocker.patch('os.makedirs')
    m_open = mocker.patch('builtins.open', mock_open())
    
    res = mac_icloud.write_icloud_file("new_dir/test.txt", "hello")
    assert "File saved successfully" in res
    mock_makedirs.assert_called_once()
    m_open().write.assert_called_once_with("hello")

def test_write_icloud_file_permission_error(mocker):
    mocker.patch('os.path.exists', return_value=True) # Directory exists
    mocker.patch('builtins.open', side_effect=PermissionError("Denied"))
    with pytest.raises(PermissionError, match="Permission denied when writing"):
        mac_icloud.write_icloud_file("test.txt", "hello")
