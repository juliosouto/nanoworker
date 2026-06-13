import pytest
from app import app
from unittest.mock import patch, MagicMock
from database import get_db

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    
    # We must yield the client so it can be used
    with app.test_client() as client:
        yield client

def test_index_redirects(client):
    response = client.get('/')
    assert response.status_code == 302
    assert '/dashboard' in response.location

def test_login_page_get(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b'<form' in response.data or b'login' in response.data.lower()

def test_login_page_post_success(client):
    # Insert token into mock db
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('LOGIN_TOKEN', 'supersecret')")
    conn.commit()
    conn.close()
    
    response = client.post('/login', data={'token': 'supersecret'})
    assert response.status_code == 302
    assert '/dashboard' in response.location

def test_login_page_post_fail(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('LOGIN_TOKEN', 'supersecret')")
    conn.commit()
    conn.close()
    
    response = client.post('/login', data={'token': 'wrong'})
    assert response.status_code == 200
    assert b'Invalid token' in response.data

def test_chat_page(client):
    response = client.get('/chat')
    assert response.status_code == 200

def test_ide_page(client):
    response = client.get('/ide')
    assert response.status_code == 200

def test_settings_page(client):
    response = client.get('/settings')
    assert response.status_code == 200

def test_whatsapp_settings_page(client):
    response = client.get('/settings/whatsapp')
    assert response.status_code == 200

def test_general_config_page(client):
    response = client.get('/settings/general')
    assert response.status_code == 200

@patch('utils.message_utils.get_default_worker')
def test_agent_behavior_config_page(mock_get_default_worker, client):
    mock_get_default_worker.return_value = {'worker_name': 'TestWorker'}
    response = client.get('/settings/agent_behavior')
    assert response.status_code == 200

def test_permissions_config_page(client):
    response = client.get('/settings/permissions')
    assert response.status_code == 200

def test_advanced_settings_page(client):
    response = client.get('/settings/advanced')
    assert response.status_code == 200

def test_tools_management_page(client):
    response = client.get('/settings/tools')
    assert response.status_code == 200

def test_llm_config_page(client):
    response = client.get('/settings/llm')
    assert response.status_code == 200

def test_llm_models_page(client):
    response = client.get('/llm-models')
    assert response.status_code == 200

def test_workers_page(client):
    response = client.get('/workers')
    assert response.status_code == 200

def test_cron_jobs_page(client):
    response = client.get('/cron')
    assert response.status_code == 200

@patch('utils.message_utils.get_default_worker')
@patch('tools.get_permitted_tools')
def test_dashboard_page(mock_get_permitted_tools, mock_get_default_worker, client):
    mock_get_default_worker.return_value = {'worker_name': 'Test', 'worker_instructions': 'System Prompt'}
    
    def dummy_tool():
        """Docstring"""
        pass
    mock_get_permitted_tools.return_value = [dummy_tool]
    
    response = client.get('/dashboard')
    assert response.status_code == 200
