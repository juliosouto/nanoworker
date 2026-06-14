import pytest
from unittest.mock import patch
from app import app

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.mark.parametrize("perm_type", [
    'calendar', 'contacts', 'terminal', 'safari', 'fs', 'photos', 'notes', 'reminders', 'icloud', 'mail', 'system_data', 'unknown'
])
@patch('subprocess.run')
@patch('os.path.exists', return_value=True)
def test_request_os_permission_macos(mock_exists, mock_run, client, perm_type):
    response = client.post('/api/permissions/request/macos', json={'permission': perm_type})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert f"Permission requested for {perm_type}" in data['message']

@patch('subprocess.run')
@patch('os.path.exists', return_value=True)
def test_request_os_permission_macos_exception(mock_exists, mock_run, client):
    mock_run.side_effect = Exception("OS Error")
    response = client.post('/api/permissions/request/macos', json={'permission': 'calendar'})
    assert response.status_code == 500
    data = response.get_json()
    assert "OS Error" in data['error']

def test_request_os_permission_linux(client):
    response = client.post('/api/permissions/request/linux', json={'permission': 'fs'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert 'fs' in data['message']

def test_request_os_permission_windows(client):
    response = client.post('/api/permissions/request/windows', json={'permission': 'terminal'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert 'terminal' in data['message']

@patch('routes.api_permissions.jsonify')
def test_request_os_permission_linux_exception(mock_jsonify, client):
    import flask
    def custom_side_effect(*args, **kwargs):
        if not hasattr(custom_side_effect, "called"):
            custom_side_effect.called = True
            raise Exception("Linux Error")
        return flask.jsonify(*args, **kwargs)
    mock_jsonify.side_effect = custom_side_effect
    response = client.post('/api/permissions/request/linux', json={'permission': 'fs'})
    assert response.status_code == 500

@patch('routes.api_permissions.jsonify')
def test_request_os_permission_windows_exception(mock_jsonify, client):
    import flask
    def custom_side_effect(*args, **kwargs):
        if not hasattr(custom_side_effect, "called"):
            custom_side_effect.called = True
            raise Exception("Windows Error")
        return flask.jsonify(*args, **kwargs)
    mock_jsonify.side_effect = custom_side_effect
    response = client.post('/api/permissions/request/windows', json={'permission': 'terminal'})
    assert response.status_code == 500
