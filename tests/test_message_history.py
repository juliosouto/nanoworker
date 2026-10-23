"""Tests for the message_history timeline (text-only, per-channel, N-message
retention) and the webhook 'history_only' flow.

The autouse ``mock_db_path`` fixture (tests/conftest.py) points database.DB_PATH
at a temporary file; these tests initialize the schema themselves so they also
exercise the sqlite-vec table creation guard.
"""
import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest
from app import app

import database
from database import (
    clear_channel_history,
    get_message_history_size,
    get_recent_message_history,
    init_db,
    insert_message_history,
    mark_message_history_processed,
)

CHANNEL = "wa_web:12036301234567890@g.us"


@pytest.fixture
def db():
    init_db()
    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as c:
        with app.app_context():
            yield c


def _count(conn, channel=CHANNEL):
    return conn.execute(
        'SELECT COUNT(*) FROM message_history WHERE channel_id = ?', (channel,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# database helpers
# ---------------------------------------------------------------------------

def test_message_history_table_created(db):
    names = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert 'message_history' in names


def test_insert_splits_timestamp_metadata(db):
    ts = 1700000000  # fixed epoch; components derived in server local time
    row_id = insert_message_history(
        message_id='WA-1',
        channel_id=CHANNEL,
        remote_jid='12036301234567890@g.us',
        is_group=1,
        sender_id='5511999999999',
        sender_id_alt='111222333',
        sender_name='Julio',
        content='bom dia galera',
        msg_timestamp=ts,
    )
    assert row_id is not None
    row = db.execute('SELECT * FROM message_history WHERE id = ?', (row_id,)).fetchone()
    expected = datetime.fromtimestamp(ts)
    assert row['is_group'] == 1
    assert row['from_me'] == 0
    assert row['sender_name'] == 'Julio'
    assert row['msg_date'] == expected.strftime('%Y-%m-%d')
    assert row['msg_hour'] == expected.hour
    assert row['msg_minute'] == expected.minute
    assert row['msg_second'] == expected.second
    assert row['was_processed'] == 0
    assert row['worker_mentioned'] == 0


def test_history_size_zero_keeps_nothing(db):
    assert get_message_history_size() == 10000  # production default
    database.set_config('MESSAGE_HISTORY_SIZE', '0')
    assert get_message_history_size() == 0
    row_id = insert_message_history(
        message_id='WA-Z', channel_id=CHANNEL, content='x', msg_timestamp=1,
    )
    assert row_id is not None  # inserted, then immediately trimmed away
    assert _count(db) == 0


def test_insert_deduplicates_message_id(db):
    first = insert_message_history(
        message_id='WA-DUP', channel_id=CHANNEL, content='hello'
    )
    second = insert_message_history(
        message_id='WA-DUP', channel_id=CHANNEL, content='hello'
    )
    assert first is not None
    assert second is None
    assert _count(db) == 1


def test_insert_rejects_invalid_rows(db):
    assert insert_message_history(channel_id=None, content='x') is None
    assert insert_message_history(channel_id=CHANNEL, content='') is None
    assert insert_message_history(channel_id=CHANNEL, content='   ') is None
    assert _count(db) == 0


def test_trim_keeps_n_newest_per_channel(db):
    database.set_config('MESSAGE_HISTORY_SIZE', '5')
    assert get_message_history_size() == 5

    for i in range(10):
        insert_message_history(
            message_id=f'WA-{i}',
            channel_id=CHANNEL,
            content=f'msg {i}',
            msg_timestamp=1700000000 + i,
        )

    assert _count(db) == 5
    kept = [r['content'] for r in db.execute(
        'SELECT content FROM message_history ORDER BY msg_timestamp ASC'
    )]
    assert kept == ['msg 5', 'msg 6', 'msg 7', 'msg 8', 'msg 9']

    # Other channels are untouched by the trim.
    insert_message_history(
        message_id='OTHER-1', channel_id='wa_web:other', content='x'
    )
    assert _count(db, 'wa_web:other') == 1


def test_mark_processed_and_clear_channel(db):
    insert_message_history(
        message_id='WA-M', channel_id=CHANNEL, content='@worker hi'
    )
    mark_message_history_processed('WA-M')
    row = db.execute(
        'SELECT was_processed, worker_mentioned FROM message_history WHERE message_id = ?',
        ('WA-M',),
    ).fetchone()
    assert row['was_processed'] == 1
    # worker_mentioned is NOT set by mark(): private chats / note-to-self are
    # processed without any mention.
    assert row['worker_mentioned'] == 0

    insert_message_history(
        message_id='OTHER-2', channel_id='wa_web:other', content='x'
    )
    assert clear_channel_history(CHANNEL) == 1
    assert _count(db) == 0
    assert _count(db, 'wa_web:other') == 1


def test_get_recent_message_history_order_and_exclude(db):
    for i in range(4):
        insert_message_history(
            message_id=f'WA-{i}',
            channel_id=CHANNEL,
            content=f'msg {i}',
            msg_timestamp=1700000000 + i,
        )
    cursor = db.cursor()
    rows = get_recent_message_history(cursor, CHANNEL)
    assert [r['content'] for r in rows] == ['msg 0', 'msg 1', 'msg 2', 'msg 3']

    rows = get_recent_message_history(cursor, CHANNEL, limit=2)
    assert [r['content'] for r in rows] == ['msg 2', 'msg 3']

    rows = get_recent_message_history(cursor, CHANNEL, exclude_message_id='WA-3')
    assert [r['content'] for r in rows] == ['msg 0', 'msg 1', 'msg 2']


def test_history_roles_distinguish_bot_from_owner(db):
    """Regression: from_me=1 alone used to map to 'model'. The human owner
    typing on their own phone (from_me=1, is_bot=0) must stay a 'user' turn;
    only actual bot replies (is_bot=1) become 'model' turns."""
    insert_message_history(
        message_id='OWN-1', channel_id=CHANNEL, content='minha anotacao',
        from_me=1, msg_timestamp=1700000010,
    )
    insert_message_history(
        message_id='BOT-1', channel_id=CHANNEL, content='sou o bot',
        from_me=1, is_bot=1, msg_timestamp=1700000011,
    )

    from agent.message_processor import _build_history_from_message_history
    cursor = db.cursor()
    hist = _build_history_from_message_history(cursor, CHANNEL)
    assert [(c.role, c.parts[0].text) for c in hist] == [
        ('user', 'minha anotacao'),
        ('model', 'sou o bot'),
    ]


# ---------------------------------------------------------------------------
# Webhook integration: history_only vs mention processing
# ---------------------------------------------------------------------------

def _wa_payload(**overrides):
    payload = {
        'channel_id': CHANNEL,
        'remote_jid': '12036301234567890@g.us',
        'sender_id': '5511999999999',
        'sender_id_alt': '111222333',
        'sender_name': 'Julio',
        'content': 'oi galera, tudo bem?',
        'message_id': 'WA-WH-1',
        'msg_timestamp': 1700000000,
        'from_me': False,
    }
    payload.update(overrides)
    return payload


@patch('routes.webhooks.get_config', return_value='secret')
def test_webhook_history_only_saves_without_processing(mock_get, client):
    with patch('routes.webhooks.route_inbound_message') as mock_route:
        response = client.post(
            '/api/webhook',
            headers={'X-Webhook-Secret': 'secret'},
            json=_wa_payload(history_only=True),
        )
    assert response.status_code == 200
    assert response.get_json()['status'] == 'saved_only'
    assert not mock_route.called

    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT * FROM message_history WHERE message_id = ?', ('WA-WH-1',)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row['content'] == 'oi galera, tudo bem?'
    assert row['channel_id'] == CHANNEL
    assert row['is_group'] == 1
    assert row['sender_name'] == 'Julio'
    assert row['was_processed'] == 0
    assert row['worker_mentioned'] == 0


@patch('routes.webhooks.get_config', return_value='secret')
def test_webhook_history_only_duplicate(mock_get, client):
    payload = _wa_payload(history_only=True)
    first = client.post('/api/webhook', headers={'X-Webhook-Secret': 'secret'}, json=payload)
    second = client.post('/api/webhook', headers={'X-Webhook-Secret': 'secret'}, json=payload)
    assert first.get_json()['status'] == 'saved_only'
    assert second.get_json()['status'] == 'duplicate'

    conn = sqlite3.connect(database.DB_PATH)
    assert conn.execute('SELECT COUNT(*) FROM message_history').fetchone()[0] == 1
    conn.close()


@patch('routes.webhooks.get_config', return_value='secret')
@patch('routes.webhooks.check_wa_permissions', return_value=(True, ''))
@patch('routes.webhooks.resolve_target_jid', return_value='12036301234567890@g.us')
@patch('routes.webhooks._send_composing_presence')
@patch('routes.webhooks.route_inbound_message', return_value=('in_1', 's1', False))
@patch('routes.webhooks.save_webhook_attachment', return_value=None)
def test_webhook_mention_saves_and_processes(
    mock_save, mock_route, mock_presence, mock_resolve, mock_check, mock_get, client
):
    response = client.post(
        '/api/webhook',
        headers={'X-Webhook-Secret': 'secret'},
        json=_wa_payload(content='@Nano resuma isso', message_id='WA-WH-2'),
    )
    assert response.status_code == 202
    assert mock_route.called

    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT was_processed, worker_mentioned FROM message_history WHERE message_id = ?',
        ('WA-WH-2',),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row['was_processed'] == 1
    assert row['worker_mentioned'] == 0


@patch('routes.webhooks.get_config', return_value='secret')
@patch('routes.webhooks.check_wa_permissions', return_value=(False, 'no_worker_mentioned'))
@patch('routes.webhooks.resolve_target_jid', return_value='12036301234567890@g.us')
@patch('routes.webhooks.route_inbound_message')
def test_webhook_refused_message_is_still_recorded(
    mock_route, mock_resolve, mock_check, mock_get, client
):
    response = client.post(
        '/api/webhook',
        headers={'X-Webhook-Secret': 'secret'},
        json=_wa_payload(message_id='WA-WH-3'),
    )
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ignored'
    assert not mock_route.called

    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT was_processed FROM message_history WHERE message_id = ?',
        ('WA-WH-3',),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row['was_processed'] == 0


# ---------------------------------------------------------------------------
# Bot replies join the timeline (from_me=1)
# ---------------------------------------------------------------------------

@patch('requests.post')
@patch('utils.audio_utils.extract_and_generate_audio')
def test_bot_reply_recorded_in_history(mock_extract, mock_post, client):
    mock_extract.return_value = ('hello text', None)
    resp_mock = mock_post.return_value
    resp_mock.status_code = 200
    resp_mock.json.return_value = {'message_id': 'bot-msg-1'}

    from routes.webhooks import _build_wa_callback
    cb = _build_wa_callback('12036301234567890@g.us', channel_id=CHANNEL)
    cb('hello text')

    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT * FROM message_history WHERE message_id = ?', ('bot-msg-1',)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row['content'] == 'hello text'
    assert row['from_me'] == 1
    assert row['is_bot'] == 1
    assert row['is_group'] == 1
    assert row['was_processed'] == 1
    assert row['worker_mentioned'] == 0


@patch('requests.post')
@patch('utils.audio_utils.extract_and_generate_audio')
def test_progress_messages_not_recorded(mock_extract, mock_post, client):
    mock_extract.return_value = ('🔄 Agent reflecting (Iteration 1/3)...', None)
    resp_mock = mock_post.return_value
    resp_mock.status_code = 200
    resp_mock.json.return_value = {'message_id': 'bot-progress'}

    from routes.webhooks import _build_wa_callback
    cb = _build_wa_callback('12036301234567890@g.us', channel_id=CHANNEL)
    cb('🔄 Agent reflecting (Iteration 1/3)...')

    conn = sqlite3.connect(database.DB_PATH)
    count = conn.execute(
        'SELECT COUNT(*) FROM message_history WHERE message_id = ?', ('bot-progress',)
    ).fetchone()[0]
    conn.close()
    assert count == 0