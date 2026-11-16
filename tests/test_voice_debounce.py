"""The voice API channel skips the WhatsApp debounce; every other channel keeps it."""
from unittest.mock import MagicMock, patch

import pytest

from agent import message_processor as mp


class _ReachedPipeline(Exception):
    """Raised right after the debounce/batch step to stop the test there."""


@pytest.fixture
def db(mock_db_path):
    import database
    database.init_db()
    conn = database.get_db()
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-voice', 'agent-1', 'voice-default')")
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-wa', 'agent-1', 'wa_web:5511999999999@s.whatsapp.net')")
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-web', 'agent-1', 'web-chat-1')")
    for msg, sess in (('m-voice', 's-voice'), ('m-wa', 's-wa'), ('m-web', 's-web')):
        conn.execute("INSERT INTO messages_in (id, session_id, content) VALUES (?, ?, 'oi')", (msg, sess))
    conn.commit()
    conn.close()


def _run(message_id, session_id, superseded=False):
    stop_after_batch = MagicMock()
    stop_after_batch.set.side_effect = _ReachedPipeline
    with patch.object(mp, "stop_command_worker", return_value=None), \
         patch.object(mp.time, "sleep") as sleep, \
         patch.object(mp, "_superseded_by_newer_message", return_value=superseded) as sup, \
         patch.object(mp, "current_session_id", stop_after_batch):
        try:
            result = mp.process_message(message_id, session_id, "oi")
        except _ReachedPipeline:
            result = "pipeline"
    return result, sleep, sup


def test_voice_channel_skips_debounce_and_batching(db):
    result, sleep, sup = _run("m-voice", "s-voice", superseded=True)
    assert result == "pipeline"  # a newer request never cancels this one
    sleep.assert_not_called()
    sup.assert_not_called()


@pytest.mark.parametrize("message_id,session_id", [("m-wa", "s-wa"), ("m-web", "s-web")])
def test_other_channels_keep_debounce(db, message_id, session_id):
    result, sleep, sup = _run(message_id, session_id)
    assert result == "pipeline"
    sleep.assert_called_once_with(mp._DEBOUNCE_SECONDS)
    sup.assert_called_once()


@pytest.mark.parametrize("message_id,session_id", [("m-wa", "s-wa"), ("m-web", "s-web")])
def test_other_channels_keep_batching(db, message_id, session_id):
    result, _, _ = _run(message_id, session_id, superseded=True)
    assert result == (message_id, "Skipped to allow newer message to process batch.")


def test_unknown_session_keeps_debounce(db):
    _, sleep, _ = _run("m-wa", "s-missing")
    sleep.assert_called_once_with(mp._DEBOUNCE_SECONDS)
