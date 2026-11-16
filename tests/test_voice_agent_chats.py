"""Voice agent channel: pick any WhatsApp chat and use the chat tools on it.

Every other channel keeps the chat tools bound to the chat being answered.
"""
from unittest.mock import patch

import pytest

from tools import chat_history as ch
from utils.session import current_session_id

GROUP = 'wa_web:120363000000000001@g.us'
OTHER_GROUP = 'wa_web:120363000000000002@g.us'
PRIVATE = 'wa_web:5581999990000@s.whatsapp.net'
SUBJECTS = {'120363000000000001@g.us': 'Família Souto', '120363000000000002@g.us': 'Trabalho'}


@pytest.fixture
def db(mock_db_path):
    import database
    database.init_db()
    conn = database.get_db()
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-agent', 'agent-1', 'voiceagent-default')")
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-group', 'agent-1', ?)", (OTHER_GROUP,))
    conn.execute("INSERT INTO messages_in (id, session_id, content, client_message_id) "
                 "VALUES ('m1', 's-group', 'oi', 'wa-current')")
    rows = [
        (GROUP, 1, 'Ana', 'a viagem para Gramado ficou para dezembro', 100),
        (GROUP, 1, 'Beto', 'vou levar o carro', 101),
        (OTHER_GROUP, 1, 'Caio', 'reunião amanhã', 102),
        (PRIVATE, 0, 'Dani', 'me liga depois', 103),
    ]
    for i, (channel, is_group, sender, text, ts) in enumerate(rows):
        conn.execute(
            "INSERT INTO message_history (message_id, channel_id, is_group, sender_name, content, "
            "msg_timestamp, msg_date) VALUES (?, ?, ?, ?, ?, ?, '2026-11-10')",
            (f'h{i}', channel, is_group, sender, text, ts),
        )
    conn.commit()
    conn.close()
    ch._selected_chats.clear()
    with patch.object(ch, '_group_subjects', return_value=SUBJECTS):
        yield
    ch._selected_chats.clear()


@pytest.fixture
def session():
    tokens = []

    def use(session_id):
        tokens.append(current_session_id.set(session_id))

    yield use
    for t in reversed(tokens):
        current_session_id.reset(t)


def test_list_chats_names_groups_and_contacts(db, session):
    session('s-agent')
    out = ch.list_whatsapp_chats()
    assert 'group · Família Souto · 120363000000000001@g.us · 2 messages' in out
    assert 'group · Trabalho' in out
    assert 'private · Dani · 5581999990000@s.whatsapp.net' in out


def test_list_chats_filter(db, session):
    session('s-agent')
    out = ch.list_whatsapp_chats('famí')
    assert 'Família Souto' in out and 'Trabalho' not in out


def test_select_by_name_then_read_the_group(db, session):
    session('s-agent')
    assert 'Família Souto' in ch.select_whatsapp_chat('família souto')
    assert ch._current_channel() == (GROUP, None)
    out = ch.read_chat_messages(10)
    assert 'Gramado' in out and 'reunião' not in out


def test_select_ambiguous_asks_for_jid(db, session):
    session('s-agent')
    out = ch.select_whatsapp_chat('120363')
    assert out.startswith("Error: '120363' matches 2 chats")
    assert ch._current_channel() == (None, None)


def test_select_unknown(db, session):
    session('s-agent')
    assert ch.select_whatsapp_chat('nada').startswith('Error: no chat matches')


def test_voice_agent_without_pick_has_no_chat(db, session):
    session('s-agent')
    assert ch._current_channel() == (None, None)


def test_other_channels_cannot_list_or_pick(db, session):
    session('s-group')
    assert ch.list_whatsapp_chats().startswith('Error: this tool only works on the voice agent channel')
    assert ch.select_whatsapp_chat('Família').startswith('Error: this tool only works on the voice agent channel')
    # Still bound to its own chat.
    assert ch._current_channel() == (OTHER_GROUP, 'wa-current')


def test_pick_is_per_session(db, session):
    session('s-agent')
    ch.select_whatsapp_chat('Trabalho')
    session('s-group')
    assert ch._current_channel() == (OTHER_GROUP, 'wa-current')


def test_search_tool_uses_the_picked_chat(db, session):
    from tools.macos import chat_search

    session('s-agent')
    ch.select_whatsapp_chat('Família Souto')
    with patch('agent.lc.history_rag.search_history', return_value=[]) as search:
        chat_search.search_chat_history('viagem')
    assert search.call_args.args[1] == GROUP


def test_chat_tools_always_kept_on_voice_agent():
    from agent import message_processor as mp

    assert mp._is_chat_tool(ch.select_whatsapp_chat)
    assert mp._is_chat_tool(ch.read_chat_messages)
    from tools.macos import chat_search
    assert mp._is_chat_tool(chat_search.search_chat_history)


def test_prefix_matches_processor():
    from agent.message_processor import VOICE_AGENT_CHANNEL_PREFIX
    assert ch.VOICE_AGENT_CHANNEL_PREFIX == VOICE_AGENT_CHANNEL_PREFIX


@pytest.mark.parametrize('session_id,offered', [('s-agent', True), ('s-group', False)])
def test_pick_tools_offered_only_on_voice_agent(db, session_id, offered):
    from unittest.mock import MagicMock

    from agent import message_processor as mp

    worker = {'worker_name': 'Quen', 'worker_model': 'm', 'tools_enabled': 1}
    with patch.object(mp.time, 'sleep'), \
         patch.object(mp, 'resolve_worker_from_content', return_value=worker), \
         patch.object(mp, '_resolve_models', return_value=['m']), \
         patch.object(mp, '_check_is_admin', return_value=True), \
         patch.object(mp, 'build_system_prompt', return_value='P'), \
         patch.object(mp, 'get_permitted_tools',
                      return_value=[ch.list_whatsapp_chats, ch.select_whatsapp_chat, ch.read_chat_messages]), \
         patch.object(mp, 'build_config_kwargs', return_value={}) as bck, \
         patch.object(mp, 'execute_autonomous_loop', return_value='ok'):
        import database
        conn = database.get_db()
        conn.execute("INSERT INTO messages_in (id, session_id, content) VALUES ('m-t', ?, '@Quen oi')", (session_id,))
        conn.commit()
        conn.close()
        mp.process_message('m-t', session_id, '@Quen oi')
    names = [t.__name__ for t in bck.call_args.kwargs['tools']]
    assert 'read_chat_messages' in names
    assert ('select_whatsapp_chat' in names) is offered
    assert ('list_whatsapp_chats' in names) is offered
