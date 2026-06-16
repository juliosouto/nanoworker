import os
import base64
import pytest
from unittest.mock import patch, mock_open, MagicMock
from utils import file_utils

def test_get_temp_dir(mocker):
    """Test get_temp_dir returns an absolute path and creates the dir."""
    mock_makedirs = mocker.patch('os.makedirs')
    temp_dir = file_utils.get_temp_dir()
    assert os.path.isabs(temp_dir)
    assert temp_dir.endswith(os.path.join("files", "temp"))
    mock_makedirs.assert_called_once_with(temp_dir, exist_ok=True)

def test_get_temp_file_path(mocker):
    """Test temp file path generation with and without filename."""
    mocker.patch('utils.file_utils.get_temp_dir', return_value='/mock/temp')
    mocker.patch('uuid.uuid4', return_value=MagicMock(hex='1234567890abcdef'))
    
    path_no_name = file_utils.get_temp_file_path()
    assert path_no_name == "/mock/temp/12345678"
    
    path_with_name = file_utils.get_temp_file_path("test.txt")
    assert path_with_name == "/mock/temp/12345678_test.txt"

def test_create_temp_copy(mocker):
    """Test creating a temp copy."""
    mocker.patch('utils.file_utils.get_temp_file_path', return_value='/mock/temp/copy.txt')
    mock_copy2 = mocker.patch('shutil.copy2')
    
    res = file_utils.create_temp_copy('/path/to/original.txt')
    assert res == '/mock/temp/copy.txt'
    mock_copy2.assert_called_once_with('/path/to/original.txt', '/mock/temp/copy.txt')

def test_read_file(tmp_path, mocker):
    """Test reading a file with permission mock."""
    # Since require_permission is a decorator, we must mock the config
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    p = tmp_path / "hello.txt"
    p.write_text("Hello World!")
    
    content = file_utils.read_file(str(p))
    assert content == "Hello World!"

def test_read_file_error(mocker):
    """Test reading a file that does not exist."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    content = file_utils.read_file("/does/not/exist.txt")
    assert "Error reading file" in content

def test_write_file(tmp_path, mocker):
    """Test writing to a file."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    
    p = tmp_path / "newdir" / "out.txt"
    res = file_utils.write_file(str(p), "Content")
    
    assert "Successfully wrote to" in res
    assert p.read_text() == "Content"

def test_write_file_error(mocker):
    """Test writing to an invalid path."""
    mocker.patch('utils.security_utils.get_config', return_value='true')
    mocker.patch('builtins.open', side_effect=PermissionError("Denied"))
    res = file_utils.write_file("/fake/path.txt", "Content")
    assert "Error writing to file" in res

def test_download_file(mocker):
    """Test downloading a file."""
    mock_response = MagicMock()
    mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
    mock_get = mocker.patch('requests.get', return_value=mock_response)
    mocker_open = mocker.patch('builtins.open', mock_open())
    
    file_utils.download_file("http://example.com/file", "/dest/file")
    mock_get.assert_called_once_with("http://example.com/file", stream=True)
    mock_response.raise_for_status.assert_called_once()
    mocker_open.assert_called_once_with("/dest/file", "wb")
    
    handle = mocker_open()
    handle.write.assert_any_call(b"chunk1")
    handle.write.assert_any_call(b"chunk2")

def test_save_base64_attachment(mocker):
    """Test saving base64 attachment."""
    mocker.patch('utils.file_utils.get_temp_file_path', return_value='/mock/temp/file.png')
    mocker_open = mocker.patch('builtins.open', mock_open())
    
    b64_str = base64.b64encode(b"image data").decode('utf-8')
    res = file_utils.save_base64_attachment(b64_str, "file.png")
    
    assert res == "path:/mock/temp/file.png"
    mocker_open().write.assert_called_once_with(b"image data")

def test_save_base64_attachment_error(mocker):
    """Test saving base64 attachment failure."""
    mocker.patch('utils.file_utils.get_temp_file_path', side_effect=Exception("Failed"))
    res = file_utils.save_base64_attachment("invalid", "file.png")
    assert res is None

def test_save_webhook_attachment(mocker):
    mock_save = mocker.patch('utils.file_utils.save_base64_attachment', return_value="path:/mock/file.png")
    
    res = file_utils.save_webhook_attachment({"file_base64": "b64data", "file_name": "test.png"})
    assert res == "path:/mock/file.png"
    mock_save.assert_called_once_with("b64data", "test.png")
    
    # Test without data
    assert file_utils.save_webhook_attachment({}) is None

def test_get_file_tree(tmp_path):
    """Test building a file tree."""
    d1 = tmp_path / "dir1"
    d1.mkdir()
    f1 = d1 / "file1.txt"
    f1.write_text("test")
    
    f2 = tmp_path / "file2.txt"
    f2.write_text("test")
    
    ignored_dir = tmp_path / ".git"
    ignored_dir.mkdir()
    
    tree = file_utils.get_file_tree(str(tmp_path), str(tmp_path))
    
    # We should have dir1 and file2.txt, but not .git
    assert len(tree) == 2
    
    dir1_node = next(n for n in tree if n["name"] == "dir1")
    assert dir1_node["type"] == "directory"
    assert len(dir1_node["children"]) == 1
    assert dir1_node["children"][0]["name"] == "file1.txt"
    
    file2_node = next(n for n in tree if n["name"] == "file2.txt")
    assert file2_node["type"] == "file"
