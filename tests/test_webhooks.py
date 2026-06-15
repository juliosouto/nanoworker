import pytest
from unittest.mock import patch, MagicMock
from app import app
from database import get_db
import flask

@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.test_client() as client:
        with app.app_context():
            yield client

# ----------------- Helper tests -----------------

@patch('requests.post')
@patch('utils.audio_utils.extract_and_generate_audio')
def test_build_wa_callback(mock_extract, mock_post):
    from routes.webhooks import _build_wa_callback
    
    # Test text + audio
    mock_extract.return_value = ("hello text", "/path/to/audio.ogg")
    cb = _build_wa_callback("test_jid")
    cb("some response")
    assert mock_post.call_count == 2
    
    # Test text only
    mock_post.reset_mock()
    mock_extract.return_value = ("hello text", None)
    cb = _build_wa_callback("test_jid")
    cb("some response")
    assert mock_post.call_count == 1
    
    # Test <audio> tag error
    mock_post.reset_mock()
    mock_extract.return_value = (None, None)
    cb = _build_wa_callback("test_jid")
    cb("some <audio> response")
    assert mock_post.call_count == 1
    args, kwargs = mock_post.call_args
    assert kwargs['json']['text'] == "[Error generating audio]"
    
    # Test exception
    mock_post.reset_mock()
    mock_extract.side_effect = Exception("Audio extraction failed")
    cb = _build_wa_callback("test_jid")
    cb("some response") # Should catch the error silently
    assert mock_post.call_count == 0

@patch('requests.post')
def test_send_composing_presence(mock_post):
    from routes.webhooks import _send_composing_presence
    _send_composing_presence("test_jid")
    assert mock_post.called

@patch('requests.post', side_effect=Exception("Timeout"))
def test_send_composing_presence_exception(mock_post):
    from routes.webhooks import _send_composing_presence
    _send_composing_presence("test_jid") # should swallow exception

# ----------------- Auth checks -----------------

def test_webhook_auth_unauthorized(client):
    # Without secret or session, should fail
    response = client.post('/api/webhook', json={})
    assert response.status_code == 401
    
@patch('routes.webhooks.get_config')
def test_webhook_auth_secret(mock_get_config, client):
    mock_get_config.return_value = "my_secret"
    response = client.post('/api/webhook', headers={'X-Webhook-Secret': 'my_secret'}, json={})
    assert response.status_code == 400 # Auth passes, but missing fields

@patch('flask_wtf.csrf.validate_csrf')
def test_webhook_auth_session(mock_validate, client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    response = client.post('/api/webhook', headers={'X-CSRFToken': 'token'}, json={})
    assert response.status_code == 400

@patch('flask_wtf.csrf.validate_csrf', side_effect=Exception("Invalid csrf"))
def test_webhook_auth_session_invalid_csrf(mock_validate, client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    response = client.post('/api/webhook', headers={'X-CSRFToken': 'token'}, json={})
    assert response.status_code == 403

# ----------------- Route logic -----------------

@patch('routes.webhooks.get_config', return_value="secret")
def test_ide_webhook_missing_fields(mock_get, client):
    response = client.post('/api/ide-webhook', headers={'X-Webhook-Secret': 'secret'}, json={})
    assert response.status_code == 400

@patch('routes.webhooks.get_config', return_value="secret")
@patch('routes.webhooks.route_ide_message', return_value=("in_id_1", "session_1"))
def test_ide_webhook_success(mock_route, mock_get, client):
    response = client.post('/api/ide-webhook', headers={'X-Webhook-Secret': 'secret'}, json={
        "content": "test ide", "channel_id": "ide_channel"
    })
    assert response.status_code == 202
    data = response.get_json()
    assert data['message_in_id'] == "in_id_1"

@patch('routes.webhooks.get_config', return_value="secret")
@patch('routes.webhooks.transcribe_webhook_audio', return_value="transcribed audio")
@patch('routes.webhooks.save_webhook_attachment', return_value="/saved/file")
@patch('routes.webhooks.route_inbound_message', return_value=("in_1", "s1", False))
def test_webhook_success(mock_route, mock_save, mock_transcribe, mock_get, client):
    response = client.post('/api/webhook', headers={'X-Webhook-Secret': 'secret'}, json={
        "content": "test msg", "channel_id": "test_channel", "audio_base64": "base64data"
    })
    assert response.status_code == 202
    assert mock_transcribe.called

@patch('routes.webhooks.get_config', return_value="secret")
@patch('routes.webhooks.save_webhook_attachment', return_value=None)
@patch('routes.webhooks.route_inbound_message', return_value=("in_1", "s1", True)) # Sync message (e.g. command)
def test_webhook_sync(mock_route, mock_save, mock_get, client):
    response = client.post('/api/webhook', headers={'X-Webhook-Secret': 'secret'}, json={
        "content": "/clear", "channel_id": "test_channel"
    })
    assert response.status_code == 200
    assert response.get_json()['status'] == 'received'

@patch('routes.webhooks.get_config', return_value="secret")
@patch('routes.webhooks.check_wa_permissions')
@patch('routes.webhooks.resolve_target_jid')
def test_webhook_wa_permissions_disabled(mock_resolve, mock_check, mock_get, client):
    mock_resolve.return_value = "wa_jid"
    mock_check.return_value = (False, "permissions_or_disabled")
    response = client.post('/api/webhook', headers={'X-Webhook-Secret': 'secret'}, json={
        "content": "test wa", "channel_id": "wa_web:123"
    })
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ignored'
    assert response.get_json()['reason'] == 'permissions_or_disabled'

@patch('routes.webhooks.get_config', return_value="secret")
@patch('routes.webhooks.check_wa_permissions')
@patch('routes.webhooks.resolve_target_jid')
@patch('requests.post')
def test_webhook_wa_rate_limit(mock_post, mock_resolve, mock_check, mock_get, client):
    mock_resolve.return_value = "wa_jid"
    mock_check.return_value = (False, "rate_limit")
    response = client.post('/api/webhook', headers={'X-Webhook-Secret': 'secret'}, json={
        "content": "test wa", "channel_id": "wa_web:123"
    })
    assert response.status_code == 200
    assert response.get_json()['reason'] == 'rate_limit'
    assert mock_post.called

@patch('routes.webhooks.get_config', return_value="secret")
@patch('routes.webhooks.check_wa_permissions', return_value=(True, ""))
@patch('routes.webhooks.resolve_target_jid', return_value="wa_jid")
@patch('routes.webhooks._send_composing_presence')
@patch('routes.webhooks.route_inbound_message', return_value=("in_1", "s1", False))
@patch('routes.webhooks.save_webhook_attachment', return_value=None)
def test_webhook_wa_success(mock_save, mock_route, mock_presence, mock_resolve, mock_check, mock_get, client):
    response = client.post('/api/webhook', headers={'X-Webhook-Secret': 'secret'}, json={
        "content": "test wa", "channel_id": "wa_web:123"
    })
    assert response.status_code == 202
    assert mock_presence.called
    assert mock_route.called
