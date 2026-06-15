import pytest
import inspect
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

def test_chat_page_with_sessions(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'web-chat-123')")
    cursor.execute("INSERT INTO messages_in (id, session_id, content) VALUES ('m1', 's1', 'hello')")
    cursor.execute("INSERT INTO messages_out (id, session_id, content) VALUES ('m2', 's1', 'hi')")
    conn.commit()
    conn.close()
    
    # Test without explicit chat_id (should default to first session)
    response = client.get('/chat')
    assert response.status_code == 200
    
    # Test with explicit chat_id
    response = client.get('/chat?chat_id=123')
    assert response.status_code == 200
    
    # Test with default chat_id
    response = client.get('/chat?chat_id=default')
    assert response.status_code == 200

def test_ide_page(client):
    response = client.get('/ide')
    assert response.status_code == 200

def test_ide_page_with_sessions(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s2', 'a1', 'ide-456')")
    cursor.execute("INSERT INTO ide_messages_in (id, session_id, content) VALUES ('m3', 's2', 'hello')")
    cursor.execute("INSERT INTO ide_messages_out (id, session_id, content) VALUES ('m4', 's2', 'hi')")
    conn.commit()
    conn.close()
    
    response = client.get('/ide?chat_id=456')
    assert response.status_code == 200

def test_settings_page(client):
    response = client.get('/settings')
    assert response.status_code == 200

def test_whatsapp_settings_page(client):
    response = client.get('/settings/whatsapp')
    assert response.status_code == 200

@patch('routes.views.get_db')
def test_whatsapp_settings_page_exceptions(mock_get_db, client):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    
    # Return a MagicMock that raises KeyError for the try blocks
    mock_config = MagicMock()
    mock_config.__bool__.return_value = True
    def side_effect(k):
        if k in ['allowed_from', 'allowed_to', 'bot_enabled']:
            return 'dummy'
        raise KeyError("Missing")
    mock_config.__getitem__.side_effect = side_effect
    
    mock_cursor.fetchone.return_value = mock_config
    mock_conn.cursor.return_value = mock_cursor
    mock_get_db.return_value = mock_conn
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

@patch('utils.message_utils.get_default_worker')
@patch('routes.views.get_config')
def test_agent_behavior_config_page_exceptions(mock_get_config, mock_get_default_worker, client):
    mock_get_default_worker.return_value = None
    mock_get_config.side_effect = lambda k, d="": "invalid_int" if k in ["AUTONOMOUS_MODE", "MESSAGE_SLICE_SIZE_TOKENS"] else d
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

def test_tools_management_page_exceptions(client):
    # Create a dummy tool that raises exception on inspect.signature
    def dummy_tool():
        """Docs"""
        pass
    dummy_tool.__module__ = 'self_developed.tools'
    dummy_tool.__name__ = 'test_self_dev'
    import sys
    sys.modules['self_developed.tools'] = type('DummyModule', (), {'__file__': '/nonexistent/path.py'})()
    
    # Second tool with no docs to hit fallback
    def dummy_no_doc(): pass
    
    # Third tool self-developed that exists
    def dummy_self_dev_exists(): pass
    dummy_self_dev_exists.__module__ = 'self_developed.tools_exist'
    dummy_self_dev_exists.__name__ = 'test_self_dev_exists'
    sys.modules['self_developed.tools_exist'] = type('DummyModule', (), {'__file__': '/nonexistent/exists.py'})()
    
    with patch('tools.AVAILABLE_TOOLS', [dummy_tool, dummy_no_doc, dummy_self_dev_exists]):
        with patch('os.path.exists', side_effect=lambda p: True if 'exists.py' in p else False):
            with patch('inspect.signature', side_effect=Exception("Inspect error")):
                response = client.get('/settings/tools')
                assert response.status_code == 200

def test_llm_config_page(client):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO llm_config (provider, model_name, api_key, text_input, image_input, audio_input, video_input, document_input, text_output, image_output, audio_output, json_output, thinking, function_calling) VALUES ('OpenAI', 'gpt-4', 'key123', 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)")
    cursor.execute("INSERT INTO llm_config (provider, model_name, api_key) VALUES ('OpenAI', 'gpt-3', NULL)")
    conn.commit()
    conn.close()
    
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
@patch('routes.views.get_db')
def test_dashboard_page(mock_get_db, mock_get_permitted_tools, mock_get_default_worker, client):
    mock_get_default_worker.return_value = {'worker_name': 'Test', 'worker_instructions': 'System Prompt'}
    
    def dummy_tool(a: int, b="test"):
        """Docstring"""
        pass
        
    def dummy_tool_no_doc():
        pass
        
    mock_get_permitted_tools.return_value = [dummy_tool, dummy_tool_no_doc, len]
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'instruction': 'test mem'}]
    mock_conn.cursor.return_value = mock_cursor
    mock_get_db.return_value = mock_conn
    
    with patch('database.get_ide_config', return_value='/test'):
        with patch('database.get_config', return_value='false'):
            original_sig = inspect.signature
            original_source = inspect.getsource
            def mock_sig(t):
                if getattr(t, '__name__', '') == 'dummy_tool_no_doc':
                    raise Exception("Sig error")
                return original_sig(t)
            def mock_source(t):
                if getattr(t, '__name__', '') == 'dummy_tool_no_doc':
                    raise Exception("Source error")
                return original_source(t)
                
            with patch('inspect.signature', side_effect=mock_sig):
                with patch('inspect.getsource', side_effect=mock_source):
                    response = client.get('/dashboard')
                    assert response.status_code == 200
