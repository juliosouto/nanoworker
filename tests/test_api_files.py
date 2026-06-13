import pytest
import os
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

@patch('routes.api_files.get_file_tree')
def test_list_files(mock_tree, client):
    mock_tree.return_value = [{"name": "file.txt"}]
    response = client.get('/api/files')
    assert response.status_code == 200
    assert response.get_json()[0]['name'] == 'file.txt'

@patch('os.path.exists')
@patch('os.path.isdir')
@patch('builtins.open', new_callable=MagicMock)
def test_get_file_content_success(mock_open, mock_isdir, mock_exists, client):
    mock_exists.return_value = True
    mock_isdir.return_value = False
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = "hello content"
    mock_open.return_value = mock_file
    
    response = client.get('/api/files/content?path=test_file.txt')
    assert response.status_code == 200
    assert response.get_json()['content'] == "hello content"

def test_get_file_content_missing_path(client):
    response = client.get('/api/files/content')
    assert response.status_code == 400

@patch('os.path.exists')
@patch('os.path.isdir')
@patch('builtins.open', new_callable=MagicMock)
def test_save_file_content_success(mock_open, mock_isdir, mock_exists, client):
    mock_exists.return_value = True
    mock_isdir.return_value = False
    mock_file = MagicMock()
    mock_open.return_value = mock_file
    
    payload = {'path': 'test_file.txt', 'content': 'new content'}
    response = client.post('/api/files/save', json=payload)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_save_file_content_missing_fields(client):
    response = client.post('/api/files/save', json={'path': 'test.txt'})
    assert response.status_code == 400

@patch('os.path.exists')
@patch('os.path.isdir')
def test_set_project_path_success(mock_isdir, mock_exists, client):
    mock_exists.return_value = True
    mock_isdir.return_value = True
    
    response = client.post('/api/set_project_path', json={'project_path': '/tmp/test_project'})
    assert response.status_code == 200
    assert state.CURRENT_PROJECT_PATH == os.path.abspath('/tmp/test_project')

def test_set_project_path_invalid(client):
    response = client.post('/api/set_project_path', json={})
    assert response.status_code == 400

@patch('subprocess.run')
def test_select_folder_dialog_success(mock_run, client):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '/selected/folder\n'
    mock_run.return_value = mock_result
    
    response = client.get('/api/select_folder_dialog')
    assert response.status_code == 200
    assert response.get_json()['path'] == '/selected/folder'

@patch('subprocess.run')
def test_select_folder_dialog_cancel(mock_run, client):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_run.return_value = mock_result
    
    response = client.get('/api/select_folder_dialog')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'cancelled'

@patch('os.path.exists')
@patch('routes.api_files.send_file')
def test_serve_temp_file(mock_send, mock_exists, client):
    mock_exists.return_value = True
    mock_send.return_value = "sent"
    
    response = client.get('/api/temp/test.txt')
    assert response.status_code == 200
