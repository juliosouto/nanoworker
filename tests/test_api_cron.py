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

def test_toggle_cron_job_not_found(client):
    response = client.post('/api/cron/999/toggle')
    assert response.status_code == 404
    assert response.get_json()['error'] == 'Job not found'

def test_toggle_cron_job_success(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'c1')")
    cursor.execute("INSERT INTO cron_jobs (id, session_id, description, content, cron_expression, next_run, is_active) VALUES ('j1', 's1', 'job1', 'do stuff', '* * * * *', '2026-01-01 00:00:00', 1)")
    conn.commit()
    conn.close()

    response = client.post('/api/cron/j1/toggle')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['is_active'] == False

    # Toggle again
    response = client.post('/api/cron/j1/toggle')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['is_active'] == True

def test_delete_cron_job(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'c1')")
    cursor.execute("INSERT INTO cron_jobs (id, session_id, description, content, cron_expression, next_run, is_active) VALUES ('j2', 's1', 'job2', 'do stuff', '* * * * *', '2026-01-01 00:00:00', 1)")
    conn.commit()
    conn.close()

    response = client.delete('/api/cron/j2')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cron_jobs WHERE id = 'j2'")
    assert cursor.fetchone() is None
    conn.close()

def test_save_cron_preferences(client):
    from database import get_config
    payload = {
        'cron_pref_1': 'WorkerAlpha',
        'cron_pref_2': 'WorkerBeta',
        'cron_pref_3': '',
        'cron_pref_4': 'WorkerDelta',
        'cron_pref_5': ''
    }
    response = client.post('/api/cron/preferences', json=payload)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

    assert get_config('CRON_WORKER_PREF_1') == 'WorkerAlpha'
    assert get_config('CRON_WORKER_PREF_2') == 'WorkerBeta'
    assert get_config('CRON_WORKER_PREF_3') == ''
    assert get_config('CRON_WORKER_PREF_4') == 'WorkerDelta'
    assert get_config('CRON_WORKER_PREF_5') == ''
