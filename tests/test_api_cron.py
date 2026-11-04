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


def _add_session_and_job(job_id='j2', cron='0 9 * * *'):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO sessions (id, agent_id, channel_id) VALUES ('s2', 'a1', 'grp@g.us')")
    conn.execute(
        "INSERT INTO cron_jobs (id, session_id, description, content, cron_expression, next_run, is_active) "
        "VALUES (?, 's2', 'old', 'old prompt', ?, '2026-01-01 09:00:00', 1)",
        (job_id, cron),
    )
    conn.commit()
    conn.close()


def test_create_recurring_cron_job(client):
    _add_session_and_job()
    response = client.post('/api/cron', json={
        'session_id': 's2', 'description': 'Check', 'content': 'look at the group',
        'cron_expression': '*/5 * * * *', 'max_executions': 3,
    })
    assert response.status_code == 201
    job_id = response.get_json()['id']
    conn = get_db()
    row = conn.execute('SELECT * FROM cron_jobs WHERE id = ?', (job_id,)).fetchone()
    conn.close()
    assert row['cron_expression'] == '*/5 * * * *'
    assert row['max_executions'] == 3
    assert row['next_run'] > '2000-01-01'


def test_create_one_time_job(client):
    _add_session_and_job()
    response = client.post('/api/cron', json={
        'session_id': 's2', 'description': 'Remind', 'content': 'call him',
        'next_run': '2030-05-01T14:30',
    })
    assert response.status_code == 201
    conn = get_db()
    row = conn.execute('SELECT next_run, cron_expression FROM cron_jobs WHERE id = ?', (response.get_json()['id'],)).fetchone()
    conn.close()
    assert row['next_run'] == '2030-05-01 14:30:00'
    assert row['cron_expression'] is None


def test_create_rejects_bad_input(client):
    _add_session_and_job()
    base = {'session_id': 's2', 'description': 'd', 'content': 'c'}
    assert client.post('/api/cron', json={**base}).status_code == 400
    assert client.post('/api/cron', json={**base, 'cron_expression': 'nope'}).status_code == 400
    assert client.post('/api/cron', json={**base, 'next_run': 'tomorrow'}).status_code == 400
    assert client.post('/api/cron', json={**base, 'cron_expression': '* * * * *', 'max_executions': 0}).status_code == 400
    assert client.post('/api/cron', json={'description': 'd', 'content': 'c', 'cron_expression': '* * * * *'}).status_code == 400
    assert client.post('/api/cron', json={**base, 'session_id': 'missing', 'cron_expression': '* * * * *'}).status_code == 400
    assert client.post('/api/cron', json={'session_id': 's2', 'description': '', 'content': 'c', 'cron_expression': '* * * * *'}).status_code == 400


def test_update_cron_job(client):
    _add_session_and_job()
    response = client.put('/api/cron/j2', json={
        'description': 'new', 'content': 'new prompt', 'cron_expression': '0 10 * * *',
        'max_executions': '', 'is_active': False,
    })
    assert response.status_code == 200
    conn = get_db()
    row = conn.execute('SELECT * FROM cron_jobs WHERE id = ?', ('j2',)).fetchone()
    conn.close()
    assert row['description'] == 'new'
    assert row['content'] == 'new prompt'
    assert row['cron_expression'] == '0 10 * * *'
    assert row['next_run'].endswith('10:00:00')
    assert row['max_executions'] is None
    assert row['is_active'] == 0


def test_update_unknown_job(client):
    response = client.put('/api/cron/nope', json={'description': 'd', 'content': 'c', 'cron_expression': '* * * * *'})
    assert response.status_code == 404


def test_cron_page_renders_modal_and_jobs(client):
    _add_session_and_job()
    response = client.get('/cron')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="cronModal"' in html
    assert 'New cron job' in html
    assert 'grp@g.us' in html
    assert '"id": "j2"' in html or '"id":"j2"' in html
