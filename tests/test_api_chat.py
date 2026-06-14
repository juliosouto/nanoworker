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

def test_poll_messages_missing_id(client):
    response = client.get('/api/messages/poll')
    assert response.status_code == 400
    assert response.get_json()['error'] == 'message_in_id is required'

def test_poll_messages_chat(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'c1')")
    cursor.execute("INSERT INTO messages_in (id, session_id, content, processed) VALUES ('msg_in_1', 's1', 'query', 2)")
    cursor.execute("INSERT INTO messages_out (id, session_id, content, in_reply_to) VALUES ('msg_out_1', 's1', 'response', 'msg_in_1')")
    conn.commit()
    conn.close()

    response = client.get('/api/messages/poll?message_in_id=msg_in_1&type=chat')
    assert response.status_code == 200
    data = response.get_json()
    assert data['is_done'] == True
    assert len(data['messages']) == 1
    assert data['messages'][0]['content'] == 'response'

def test_poll_messages_ide(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'c1')")
    cursor.execute("INSERT INTO ide_messages_in (id, session_id, content, processed) VALUES ('msg_in_2', 's1', 'ide_query', 1)")
    cursor.execute("INSERT INTO ide_messages_out (id, session_id, content, in_reply_to) VALUES ('msg_out_2', 's1', 'ide_response', 'msg_in_2')")
    conn.commit()
    conn.close()

    response = client.get('/api/messages/poll?message_in_id=msg_in_2&type=ide')
    assert response.status_code == 200
    data = response.get_json()
    assert data['is_done'] == False
    assert len(data['messages']) == 1
    assert data['messages'][0]['content'] == 'ide_response'

def test_search_chat_sessions_empty(client):
    response = client.get('/api/chat/search')
    assert response.status_code == 200
    assert response.get_json()['matching_channels'] == []

def test_search_chat_sessions_matches(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'web-chat-1')")
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s2', 'a1', 'web-chat-2')")
    cursor.execute("INSERT INTO messages_in (id, session_id, content) VALUES ('m1', 's1', 'hello world')")
    cursor.execute("INSERT INTO messages_out (id, session_id, content) VALUES ('m2', 's2', 'hello there')")
    conn.commit()
    conn.close()

    response = client.get('/api/chat/search?q=hello')
    assert response.status_code == 200
    data = response.get_json()
    assert len(data['matching_channels']) == 2
    assert 'web-chat-1' in data['matching_channels']
    assert 'web-chat-2' in data['matching_channels']

def test_delete_chat(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'web-chat-123')")
    cursor.execute("INSERT INTO messages_in (id, session_id, content) VALUES ('m1', 's1', 'hi')")
    cursor.execute("INSERT INTO messages_out (id, session_id, content) VALUES ('m2', 's1', 'hello')")
    conn.commit()
    conn.close()

    response = client.delete('/api/chat/123')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

    # Verify deletion
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE id = 's1'")
    assert cursor.fetchone() is None
    cursor.execute("SELECT * FROM messages_in WHERE session_id = 's1'")
    assert len(cursor.fetchall()) == 0
    conn.close()

def test_delete_chat_default(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s2', 'a1', 'web-chat')")
    conn.commit()
    conn.close()

    response = client.delete('/api/chat/default')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE id = 's2'")
    assert cursor.fetchone() is None
    conn.close()

def test_delete_chat_not_found(client):
    response = client.delete('/api/chat/999')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'
