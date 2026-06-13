import pytest
from app import app
from database import get_db

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sessions (channel_id, agent_id) VALUES ('web-chat', 1)
    ''')
    session_id = cursor.lastrowid
    
    import datetime
    next_run = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        INSERT INTO cron_jobs (id, session_id, description, content, cron_expression, next_run, is_active) 
        VALUES ('cron_1', ?, 'desc', 'content', '* * * * *', ?, 1)
    ''', (session_id, next_run))
    
    conn.commit()
    conn.close()
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

def test_toggle_cron_job_success(client):
    response = client.post('/api/cron/cron_1/toggle')
    assert response.status_code == 200
    assert response.get_json()['is_active'] is False

def test_toggle_cron_job_not_found(client):
    response = client.post('/api/cron/cron_99/toggle')
    assert response.status_code == 404

def test_delete_cron_job_success(client):
    response = client.delete('/api/cron/cron_1')
    assert response.status_code == 200
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM cron_jobs WHERE id='cron_1'")
    assert cursor.fetchone()['c'] == 0
    conn.close()
