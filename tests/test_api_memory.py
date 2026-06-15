import pytest
from app import app
from database import get_db

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_get_user_memory_api(client):
    response = client.get('/api/user_memory')
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)

def test_add_user_memory_api(client):
    # Missing field
    response = client.post('/api/user_memory', json={})
    assert response.status_code == 400
    
    # Empty string
    response = client.post('/api/user_memory', json={'instruction': '   '})
    assert response.status_code == 400
    
    # Success
    response = client.post('/api/user_memory', json={'instruction': 'Remember this test'})
    assert response.status_code == 201
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['instruction'] == 'Remember this test'

def test_delete_user_memory_api(client):
    # Add one first
    response = client.post('/api/user_memory', json={'instruction': 'To be deleted'})
    mem_id = response.get_json()['id']
    
    # Delete success
    response = client.delete(f'/api/user_memory/{mem_id}')
    assert response.status_code == 200
    
    # Delete not found
    response = client.delete(f'/api/user_memory/999')
    assert response.status_code == 404

def test_update_user_memory_api(client):
    # Add one first
    response = client.post('/api/user_memory', json={'instruction': 'To be updated'})
    mem_id = response.get_json()['id']
    
    # Missing field
    response = client.put(f'/api/user_memory/{mem_id}', json={})
    assert response.status_code == 400
    
    # Empty field
    response = client.put(f'/api/user_memory/{mem_id}', json={'instruction': '   '})
    assert response.status_code == 400
    
    # Success
    response = client.put(f'/api/user_memory/{mem_id}', json={'instruction': 'Updated test'})
    assert response.status_code == 200
    
    # Not found
    response = client.put(f'/api/user_memory/999', json={'instruction': 'Does not exist'})
    assert response.status_code == 404
