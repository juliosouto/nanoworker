import pytest
from unittest.mock import patch, MagicMock
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

def test_save_whatsapp_config(client):
    payload = {
        'allowed_from': '5511999999999',
        'allowed_to': '',
        'bot_enabled': True,
        'allow_mentions': True,
        'allow_audio_mentions': False,
        'rate_limit_per_minute': 10
    }
    response = client.post('/api/whatsapp/config', json=payload)
    assert response.status_code == 200
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM whatsapp_config WHERE id = 1")
    config = cursor.fetchone()
    assert config['allowed_from'] == '5511999999999'
    assert config['bot_enabled'] == 1
    assert config['rate_limit_per_minute'] == 10
    conn.close()
    # Also test ValueError path for rate_limit_per_minute
    payload_invalid = {
        'rate_limit_per_minute': 'invalid'
    }
    response2 = client.post('/api/whatsapp/config', json=payload_invalid)
    assert response2.status_code == 200
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rate_limit_per_minute FROM whatsapp_config WHERE id = 1")
    config2 = cursor.fetchone()
    assert config2['rate_limit_per_minute'] == 0
    conn.close()
@patch('subprocess.Popen')
def test_whatsapp_auth_stream(mock_popen, client):
    # Mock the process and its stdout
    mock_process = MagicMock()
    mock_process.stdout.readline.side_effect = ['qr_data1\n', 'qr_data2\n', '']
    mock_popen.return_value = mock_process
    
    response = client.get('/api/whatsapp/auth-stream')
    assert response.status_code == 200
    data = response.get_data(as_text=True)
    assert 'data: qr_data1' in data
    assert 'data: qr_data2' in data

@patch('shutil.rmtree')
@patch('os.path.exists')
def test_whatsapp_logout(mock_exists, mock_rmtree, client):
    mock_exists.return_value = True
    response = client.post('/api/whatsapp/logout')
    assert response.status_code == 200
    assert mock_rmtree.called

@patch('subprocess.Popen')
@patch('os.path.exists')
def test_whatsapp_restart_success(mock_exists, mock_popen, client):
    mock_exists.return_value = True
    response = client.post('/api/whatsapp/restart')
    assert response.status_code == 200
    assert mock_popen.called

@patch('os.path.exists')
def test_whatsapp_restart_not_found(mock_exists, client):
    mock_exists.return_value = False
    response = client.post('/api/whatsapp/restart')
    assert response.status_code == 404

@patch('os.path.exists')
def test_whatsapp_restart_exception(mock_exists, client):
    mock_exists.side_effect = Exception("Test Error")
    response = client.post('/api/whatsapp/restart')
    assert response.status_code == 500
    assert "Test Error" in response.get_data(as_text=True)

@patch('routes.api_whatsapp.wa_verify')
def test_whatsapp_webhook_verify(mock_verify, client):
    mock_verify.return_value = ("12345", 200)
    response = client.get('/whatsapp/webhook?hub.challenge=12345')
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "12345"

@patch('routes.api_whatsapp.wa_parse')
@patch('routes.api_whatsapp.should_process_wa_message')
@patch('utils.message_utils.check_rate_limit')
@patch('routes.api_whatsapp.wa_mark_read')
@patch('routes.api_whatsapp.wa_send')
@patch('routes.api_whatsapp.route_inbound_message')
def test_whatsapp_webhook_inbound(mock_route, mock_send, mock_mark, mock_check, mock_should, mock_parse, client):
    mock_parse.return_value = [{
        "sender": "123",
        "sender_name": "Test User",
        "content": "Hello",
        "message_id": "msg1"
    }]
    mock_should.return_value = True
    mock_check.return_value = True
    
    response = client.post('/whatsapp/webhook', json={})
    assert response.status_code == 200
    
    # Assert side effects
    assert mock_mark.called
    assert mock_route.called

@patch('routes.api_whatsapp.wa_parse')
@patch('routes.api_whatsapp.should_process_wa_message')
@patch('utils.message_utils.check_rate_limit')
@patch('routes.api_whatsapp.wa_send')
def test_whatsapp_webhook_inbound_rate_limited(mock_send, mock_check, mock_should, mock_parse, client):
    mock_parse.return_value = [{
        "sender": "123",
        "sender_name": "Test User",
        "content": "Hello",
        "message_id": "msg1"
    }]
    mock_should.return_value = True
    mock_check.return_value = False # Triggers rate limit code path
    
    response = client.post('/whatsapp/webhook', json={})
    assert response.status_code == 200
    
    assert mock_send.called
    args, _ = mock_send.call_args
    assert "Rate limit reached" in args[1]

@patch('routes.api_whatsapp.wa_parse')
@patch('routes.api_whatsapp.should_process_wa_message')
def test_whatsapp_webhook_inbound_ignored(mock_should, mock_parse, client):
    mock_parse.return_value = [{
        "sender": "123",
        "sender_name": "Test User",
        "content": "Hello",
        "message_id": "msg1"
    }]
    mock_should.return_value = False
    
    response = client.post('/whatsapp/webhook', json={})
    assert response.status_code == 200
    # Should ignore and not do anything further

@patch('routes.api_whatsapp.wa_parse')
@patch('routes.api_whatsapp.should_process_wa_message')
@patch('utils.message_utils.check_rate_limit')
@patch('routes.api_whatsapp.wa_mark_read')
@patch('routes.api_whatsapp.wa_send')
@patch('routes.api_whatsapp.route_inbound_message')
def test_whatsapp_webhook_inbound_callback(mock_route, mock_send, mock_mark, mock_check, mock_should, mock_parse, client):
    mock_parse.return_value = [{
        "sender": "123",
        "sender_name": "Test User",
        "content": "Hello",
        "message_id": "msg1"
    }]
    mock_should.return_value = True
    mock_check.return_value = True
    
    # We want to test the callback Execution inside route_inbound_message
    def fake_route(*args, **kwargs):
        on_complete = kwargs.get('on_complete')
        if on_complete:
            on_complete("Reply text")
            
    mock_route.side_effect = fake_route
    
    response = client.post('/whatsapp/webhook', json={})
    assert response.status_code == 200
    
    # callback should have called wa_send
    assert mock_send.called
    args, _ = mock_send.call_args
    assert args[0] == "123"
    assert args[1] == "Reply text"
