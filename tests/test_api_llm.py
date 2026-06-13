import pytest
from app import app
from database import get_db

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    
    # Pre-populate database with some data for test manipulation
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO llm_config (model_name, provider, api_key, enabled) 
        VALUES ('TestModel', 'TestProvider', 'secret', 1)
    ''')
    cursor.execute('''
        INSERT INTO workers_config (worker_name, worker_model, worker_instructions, is_default)
        VALUES ('TestWorker', 'TestModel', 'Instructions', 1)
    ''')
    conn.commit()
    conn.close()
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.test_client() as client:
        yield client

# -- TESTS FOR LLM MODELS --

def test_add_llm_model_success(client):
    payload = {
        'model_name': 'NewModel',
        'provider': 'OpenAI',
        'api_key': '12345',
        'enabled': True,
        'json_output': True,
        'thinking': False,
        'function_calling': True,
        'context_window': 8000,
        'max_output_tokens': 4000,
        'text_input': True,
        'image_input': False,
        'audio_input': False,
        'video_input': False,
        'document_input': False,
        'rate_tpm': 10000,
        'rate_rpm': 100,
        'rate_rpd': 1000,
        'text_output': True,
        'image_output': False,
        'audio_output': False,
        'video_output': False,
        'document_output': False
    }
    response = client.post('/api/llm_models', json=payload)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_add_llm_model_missing_fields(client):
    response = client.post('/api/llm_models', json={'model_name': 'FailModel'})
    assert response.status_code == 400
    assert 'error' in response.get_json()

def test_add_llm_model_duplicate_key(client):
    payload = {
        'model_name': 'CopiedModel',
        'provider': 'TestProvider',
        'api_key': '••••••••••••',
        'duplicate_from_id': 1
    }
    response = client.post('/api/llm_models', json=payload)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_delete_llm_model_success(client):
    response = client.delete('/api/llm_models/1')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_delete_llm_model_not_found(client):
    response = client.delete('/api/llm_models/999')
    assert response.status_code == 404

def test_update_llm_model_success(client):
    payload = {
        'model_name': 'UpdatedModel',
        'provider': 'TestProvider',
        'api_key': 'new_secret'
    }
    response = client.put('/api/llm_models/1', json=payload)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_update_llm_model_keep_existing_key(client):
    payload = {
        'model_name': 'UpdatedModel',
        'provider': 'TestProvider',
        'api_key': '••••••••••••'
    }
    response = client.put('/api/llm_models/1', json=payload)
    assert response.status_code == 200

def test_update_llm_model_missing_fields(client):
    response = client.put('/api/llm_models/1', json={'model_name': 'Fail'})
    assert response.status_code == 400

def test_update_llm_model_not_found(client):
    payload = {'model_name': 'Updated', 'provider': 'Prov'}
    response = client.put('/api/llm_models/999', json=payload)
    assert response.status_code == 404

def test_toggle_llm_model_success(client):
    response = client.post('/api/llm_models/1/toggle')
    assert response.status_code == 200
    assert response.get_json()['enabled'] is False

def test_toggle_llm_model_not_found(client):
    response = client.post('/api/llm_models/999/toggle')
    assert response.status_code == 404

# -- TESTS FOR WORKERS --

def test_add_worker_success(client):
    payload = {
        'worker_name': 'NewWorker',
        'worker_model': 'TestModel',
        'worker_instructions': 'Be helpful',
        'is_default': True,
        'thinking_enabled': True,
        'tools_enabled': False,
        'show_tools_results': True
    }
    response = client.post('/api/workers', json=payload)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_add_worker_missing_fields(client):
    response = client.post('/api/workers', json={'worker_name': 'FailWorker'})
    assert response.status_code == 400

def test_update_worker_success(client):
    payload = {
        'worker_name': 'UpdatedWorker',
        'worker_model': 'TestModel',
        'worker_instructions': 'Be mean',
        'is_default': True,
        'thinking_enabled': False,
        'tools_enabled': True,
        'show_tools_results': False
    }
    response = client.put('/api/workers/1', json=payload)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_update_worker_missing_fields(client):
    response = client.put('/api/workers/1', json={'worker_name': 'Fail'})
    assert response.status_code == 400

def test_update_worker_not_found(client):
    payload = {'worker_name': 'Updated', 'worker_model': 'Test'}
    response = client.put('/api/workers/999', json=payload)
    assert response.status_code == 404

def test_delete_worker_success(client):
    response = client.delete('/api/workers/1')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

def test_delete_worker_not_found(client):
    response = client.delete('/api/workers/999')
    assert response.status_code == 404
