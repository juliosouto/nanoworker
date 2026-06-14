import pytest
from unittest.mock import patch, MagicMock
from app import app
from database import get_db
import threading

@pytest.fixture
def test_app(mock_db_path):
    import database
    database.init_db()
    app.config['TESTING'] = True
    yield app

def test_route_inbound_message_duplicate(test_app):
    from router import route_inbound_message
    with test_app.app_context():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s1', 'a1', 'c1')")
        cursor.execute("INSERT INTO messages_in (id, session_id, content, client_message_id) VALUES ('m1', 's1', 'hi', 'client123')")
        conn.commit()
        conn.close()
        
        m_id, s_id, is_sync = route_inbound_message('c1', 'hi', client_message_id='client123')
        assert m_id == 'm1'
        assert s_id == 's1'
        assert is_sync is False

@patch('threading.Thread.start')
@patch('utils.message_utils.get_default_worker', return_value={'worker_name': 'test_worker'})
def test_route_inbound_message_new_session(mock_worker, mock_thread_start, test_app):
    from router import route_inbound_message
    with test_app.app_context():
        m_id, s_id, is_sync = route_inbound_message('new_channel', 'hello')
        assert is_sync is False
        assert m_id.startswith('msg-in')
        assert s_id.startswith('sess-')
        assert mock_thread_start.called

@patch('threading.Thread.start')
@patch('utils.message_utils.get_default_worker', return_value={'worker_name': 'test_worker'})
def test_route_inbound_message_existing_session(mock_worker, mock_thread_start, test_app):
    from router import route_inbound_message
    with test_app.app_context():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s2', 'agent-1', 'ext_channel')")
        conn.commit()
        conn.close()
        
        m_id, s_id, is_sync = route_inbound_message('ext_channel', 'hello')
        assert s_id == 's2'
        assert is_sync is False
        assert mock_thread_start.called

@patch('utils.message_utils.get_default_worker', return_value={'worker_name': 'test_worker'})
def test_route_inbound_message_clear_history(mock_worker, test_app):
    from router import route_inbound_message
    with test_app.app_context():
        cb = MagicMock()
        m_id, s_id, is_sync = route_inbound_message('some_channel', '/new', on_complete=cb)
        assert is_sync is True
        assert cb.called
        args, _ = cb.call_args
        assert args[0] == "History cleared! Starting a new conversation."

@patch('utils.message_utils.get_default_worker', return_value={'worker_name': 'test_worker'})
@patch('database.get_all_workers_with_capabilities')
def test_route_inbound_message_list_workers(mock_get_workers, mock_worker, test_app):
    from router import route_inbound_message
    with test_app.app_context():
        mock_get_workers.return_value = [
            {'worker_name': 'Bot1', 'worker_model': 'Model1', 'text_input': 1, 'text_output': 1, 'image_input': 1}
        ]
        cb = MagicMock()
        m_id, s_id, is_sync = route_inbound_message('some_channel', '/list', on_complete=cb)
        assert is_sync is True
        assert cb.called
        args, _ = cb.call_args
        assert "Bot1" in args[0]
        assert "Text" in args[0]
        assert "Image" in args[0]

@patch('utils.message_utils.get_default_worker', return_value={'worker_name': 'test_worker'})
@patch('database.get_all_workers_with_capabilities', return_value=[])
def test_route_inbound_message_list_workers_empty(mock_get_workers, mock_worker, test_app):
    from router import route_inbound_message
    with test_app.app_context():
        cb = MagicMock()
        m_id, s_id, is_sync = route_inbound_message('some_channel', '/list', on_complete=cb)
        assert is_sync is True
        assert cb.called
        args, _ = cb.call_args
        assert "Nenhum worker encontrado" in args[0]

@patch('threading.Thread.start')
def test_route_ide_message(mock_thread_start, test_app):
    from router import route_ide_message
    with test_app.app_context():
        m_id, s_id = route_ide_message('ide_chan', 'ide test')
        assert m_id.startswith('msg-in')
        assert s_id.startswith('sess-')
        assert mock_thread_start.called
