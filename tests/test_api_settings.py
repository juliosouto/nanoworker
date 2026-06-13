import pytest
from app import app
from unittest.mock import patch, MagicMock

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.test_client() as client:
        yield client

def test_get_agent_name_api(client):
    response = client.get('/api/config/agent_name')
    assert response.status_code == 200
    data = response.get_json()
    assert 'agent_name' in data
    assert 'worker_names' in data

def test_save_settings(client):
    payload = {
        'gemini_api_key': 'test_key',
        'require_at_prefix': True,
        'perm_terminal': False
    }
    response = client.post('/api/settings', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'

def test_save_tool_setting_valid(client):
    payload = {
        'tool_name': 'test_tool',
        'enabled': True,
        'allow_others_from_direct_msgs': False
    }
    response = client.post('/api/settings/tools', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'

def test_save_tool_setting_invalid(client):
    response = client.post('/api/settings/tools', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert data['status'] == 'error'

def test_toggle_login_enable(client):
    response = client.post('/api/login/toggle', json={'enabled': True})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['enabled'] is True
    assert 'token' in data

def test_toggle_login_disable(client):
    response = client.post('/api/login/toggle', json={'enabled': False})
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['enabled'] is False

def test_delete_self_developed_tool_invalid_name(client):
    response = client.delete('/api/settings/tools/bad..tool')
    assert response.status_code == 400

@patch('os.path.exists')
@patch('os.remove')
def test_delete_self_developed_tool_success(mock_remove, mock_exists, client):
    # Mock exists so it thinks the file is there
    mock_exists.return_value = True
    response = client.delete('/api/settings/tools/my_tool')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'

@patch('os.path.exists')
def test_delete_self_developed_tool_not_found(mock_exists, client):
    mock_exists.return_value = False
    response = client.delete('/api/settings/tools/my_tool')
    assert response.status_code == 404

@patch('os.path.exists')
@patch('os.remove')
def test_delete_self_developed_tool_error(mock_remove, mock_exists, client):
    mock_exists.return_value = True
    mock_remove.side_effect = Exception("OS Error")
    response = client.delete('/api/settings/tools/my_tool')
    assert response.status_code == 500

@patch('utils.setup_utils.backup_database')
@patch('utils.setup_utils.setup_app_config')
@patch('utils.setup_utils.setup_ide_prompt')
@patch('utils.setup_utils.setup_ide_settings')
@patch('utils.setup_utils.setup_llm_config')
@patch('utils.setup_utils.setup_agents')
@patch('utils.setup_utils.setup_whatsapp_config')
@patch('utils.setup_utils.setup_workers_config')
@patch('utils.setup_utils.setup_tools_config')
def test_initial_setup_success(mock_tools, mock_workers, mock_whatsapp, mock_agents, mock_llm, mock_ide_set, mock_ide_prmpt, mock_app, mock_backup, client):
    mock_backup.return_value = "backup.db"
    
    # We must prepopulate the llm_config so the UPDATE queries won't fail (they just won't update any rows if empty, but we want it to run without error)
    import database
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO llm_config (provider, model_name, api_key) VALUES ('Google', 'gemini', 'old')")
    cursor.execute("INSERT INTO llm_config (provider, model_name, api_key) VALUES ('OpenAI', 'gpt-4', 'old')")
    conn.commit()
    conn.close()

    payload = {
        'gemini_api_key': 'gemini_test',
        'openai_api_key': 'openai_test',
        'groq_api_key': 'groq_test',
        'qwen_api_key': 'qwen_test',
        'openrouter_api_key': 'openrouter_test'
    }
    response = client.post('/api/setup', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'

@patch('utils.setup_utils.backup_database')
def test_initial_setup_exception(mock_backup, client):
    mock_backup.side_effect = Exception("Backup Failed")
    response = client.post('/api/setup', json={})
    assert response.status_code == 500
    data = response.get_json()
    assert data['status'] == 'error'
