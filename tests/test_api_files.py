import os
import pytest
from unittest.mock import patch, MagicMock
from app import app
import state

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.fixture
def temp_workspace(tmp_path):
    # Setup some files in tmp_path
    (tmp_path / "test.txt").write_text("hello world")
    (tmp_path / "temp").mkdir()
    (tmp_path / "temp" / "temp_file.txt").write_text("temp data")
    
    # Save original state
    orig_path = state.CURRENT_PROJECT_PATH
    state.CURRENT_PROJECT_PATH = str(tmp_path)
    
    yield tmp_path
    
    # Restore original state
    state.CURRENT_PROJECT_PATH = orig_path

@patch('routes.api_files.get_file_tree')
def test_list_files(mock_get_tree, client, temp_workspace):
    mock_get_tree.return_value = [{"name": "test.txt", "type": "file"}]
    response = client.get('/api/files')
    assert response.status_code == 200
    assert response.get_json() == [{"name": "test.txt", "type": "file"}]

def test_get_file_content_missing_path(client):
    response = client.get('/api/files/content')
    assert response.status_code == 400
    assert response.get_json()['error'] == "Path is required"

def test_get_file_content_access_denied(client, temp_workspace):
    response = client.get('/api/files/content?path=../outside.txt')
    assert response.status_code == 403
    assert response.get_json()['error'] == "Access denied"

def test_get_file_content_not_found(client, temp_workspace):
    response = client.get('/api/files/content?path=missing.txt')
    assert response.status_code == 404
    assert response.get_json()['error'] == "File not found"

def test_get_file_content_success(client, temp_workspace):
    response = client.get('/api/files/content?path=test.txt')
    assert response.status_code == 200
    data = response.get_json()
    assert data['content'] == "hello world"
    assert data['path'] == "test.txt"

@patch('builtins.open', side_effect=Exception("Read error"))
def test_get_file_content_exception(mock_open, client, temp_workspace):
    response = client.get('/api/files/content?path=test.txt')
    assert response.status_code == 500
    assert "Read error" in response.get_json()['error']

def test_save_file_content_missing_data(client):
    response = client.post('/api/files/save', json={})
    assert response.status_code == 400
    assert response.get_json()['error'] == "Missing path or content"

def test_save_file_content_access_denied(client, temp_workspace):
    response = client.post('/api/files/save', json={"path": "../hack.txt", "content": "hack"})
    assert response.status_code == 403
    assert response.get_json()['error'] == "Access denied"

def test_save_file_content_success(client, temp_workspace):
    response = client.post('/api/files/save', json={"path": "new_file.txt", "content": "saved text"})
    assert response.status_code == 200
    assert response.get_json()['status'] == "success"
    
    assert (temp_workspace / "new_file.txt").read_text() == "saved text"

@patch('builtins.open', side_effect=Exception("Write error"))
def test_save_file_content_exception(mock_open, client, temp_workspace):
    response = client.post('/api/files/save', json={"path": "new_file.txt", "content": "saved text"})
    assert response.status_code == 500
    assert "Write error" in response.get_json()['error']

def test_serve_temp_file_success(client, temp_workspace):
    with patch('routes.api_files.ROOT_DIR', str(temp_workspace)):
        response = client.get('/api/temp/temp_file.txt')
        assert response.status_code == 200
        assert response.get_data(as_text=True) == "temp data"

def test_serve_temp_file_access_denied(client, temp_workspace):
    with patch('routes.api_files.ROOT_DIR', str(temp_workspace)):
        response = client.get('/api/temp/../test.txt')
        assert response.status_code == 403

def test_serve_temp_file_not_found(client, temp_workspace):
    with patch('routes.api_files.ROOT_DIR', str(temp_workspace)):
        response = client.get('/api/temp/missing.txt')
        assert response.status_code == 404

@patch('routes.api_files.set_ide_config')
def test_set_project_path_missing(mock_set, client):
    response = client.post('/api/set_project_path', json={})
    assert response.status_code == 400
    assert response.get_json()['error'] == "Missing project_path"

@patch('routes.api_files.set_ide_config')
def test_set_project_path_invalid(mock_set, client):
    response = client.post('/api/set_project_path', json={"project_path": "/invalid/dir/does/not/exist/999"})
    assert response.status_code == 400
    assert response.get_json()['error'] == "Invalid directory path"

@patch('routes.api_files.set_ide_config')
def test_set_project_path_success(mock_set, client, temp_workspace):
    response = client.post('/api/set_project_path', json={"project_path": str(temp_workspace)})
    assert response.status_code == 200
    assert response.get_json()['status'] == "success"
    assert mock_set.called

@patch('subprocess.run')
def test_select_folder_dialog_success(mock_run, client):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "/path/to/folder\n"
    mock_run.return_value = mock_result
    
    response = client.get('/api/select_folder_dialog')
    assert response.status_code == 200
    assert response.get_json()['path'] == "/path/to/folder"

@patch('subprocess.run')
def test_select_folder_dialog_cancelled(mock_run, client):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_run.return_value = mock_result
    
    response = client.get('/api/select_folder_dialog')
    assert response.status_code == 200
    assert response.get_json()['status'] == "cancelled"

@patch('subprocess.run', side_effect=Exception("AppleScript error"))
def test_select_folder_dialog_exception(mock_run, client):
    response = client.get('/api/select_folder_dialog')
    assert response.status_code == 500
    assert "AppleScript error" in response.get_json()['error']
