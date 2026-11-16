"""Voice API channel: lean prompt (worker instructions + text, plain-text reply).

Every other channel must keep the full prompt, history and JSON contract.
"""
from unittest.mock import MagicMock, patch

import pytest

from agent import message_processor as mp

# The real function, kept before the autouse fixture below patches it.
_REAL_VOICE_CONTEXT = mp._voice_context

WORKER = {
    'worker_name': 'Voz', 'worker_model': 'deepseek-chat', 'tools_enabled': 0,
    'worker_instructions': 'Seja breve.', 'show_tools_results': 0,
}


@pytest.fixture
def db(mock_db_path):
    import database
    database.init_db()
    conn = database.get_db()
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-voice', 'agent-1', 'voice-default')")
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s-web', 'agent-1', 'web-chat-1')")
    # Earlier turns: the voice channel must not send them; web chat must.
    for sess in ('s-voice', 's-web'):
        conn.execute("INSERT INTO messages_in (id, session_id, content, sender_id, processed) "
                     "VALUES (?, ?, 'pergunta antiga', 'voice-app', 2)", (f'old-{sess}', sess))
        conn.execute("INSERT INTO messages_out (id, session_id, in_reply_to, content) "
                     "VALUES (?, ?, ?, 'resposta antiga')", (f'out-{sess}', sess, f'old-{sess}'))
        conn.execute("INSERT INTO messages_in (id, session_id, content, sender_id) "
                     "VALUES (?, ?, '@Voz que horas são?', 'voice-app')", (f'new-{sess}', sess))
    conn.commit()
    conn.close()


def _run(session_id):
    with patch.object(mp.time, 'sleep'), \
         patch.object(mp, 'resolve_worker_from_content', return_value=dict(WORKER)), \
         patch('utils.message_utils.resolve_worker_from_content', return_value=dict(WORKER)), \
         patch.object(mp, '_resolve_models', return_value=['deepseek-chat']), \
         patch.object(mp, 'build_system_prompt', return_value='FULL PROMPT') as bsp, \
         patch.object(mp, '_fetch_user_memory', create=True, return_value='MEM'), \
         patch.object(mp, 'execute_autonomous_loop', return_value='resposta') as loop:
        _, reply = mp.process_message(f'new-{session_id}', session_id, '@Voz que horas são?')
    assert reply == 'resposta'
    args = loop.call_args.args
    return {'history': args[0], 'config': args[1], 'content': args[2], 'build_prompt': bsp}


CTX = 'Data e hora atuais: domingo, 2026-11-15 10:00. Local do usuário: Recife.'


@pytest.fixture(autouse=True)
def _fixed_context():
    with patch.object(mp, '_voice_context', return_value=CTX):
        yield


def test_voice_sends_context_worker_instructions_and_text(db):
    call = _run('s-voice')
    assert call['history'] == []
    assert call['config']['system_instruction'] == f'{CTX}\n\nSeja breve.'
    assert call['config']['plain_text_reply'] is True
    assert call['content'] == ['que horas são?']
    call['build_prompt'].assert_not_called()


def test_voice_without_instructions_still_has_context(db):
    with patch.dict(WORKER, {'worker_instructions': ''}):
        call = _run('s-voice')
    assert call['config']['system_instruction'] == CTX


def test_real_voice_context(monkeypatch):
    import datetime

    import standard_prompts

    class FakeDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 16, 9, 5)

    monkeypatch.setattr(datetime, 'datetime', FakeDT)
    monkeypatch.setattr(standard_prompts, '_get_user_location', lambda: 'Recife, PE, BR')
    text = _REAL_VOICE_CONTEXT()
    assert text == 'Data e hora atuais: segunda-feira, 2026-11-16 09:05. Local do usuário: Recife, PE, BR.'


def test_other_channels_keep_full_prompt_and_history(db):
    call = _run('s-web')
    assert call['config']['system_instruction'] == 'FULL PROMPT'
    assert 'plain_text_reply' not in call['config']
    assert call['history']  # earlier turns are sent
    assert 'Message from' in str(call['content'])
    call['build_prompt'].assert_called_once()


class TestRouterPlainTextReply:
    def _route(self, config_kwargs):
        import agent_runner

        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = {
            'provider': 'DeepSeek', 'api_key': 'enc', 'thinking': 0,
        }
        with patch('database.get_db', return_value=conn), \
             patch('database.decrypt_value', return_value='key'), \
             patch('agent.lc.outputs.structured_output_enabled', return_value=True), \
             patch('agent.llm_providers.call_deepseek_llm', return_value='DS') as ds:
            agent_runner.route_llm_call(
                'deepseek-chat', [], config_kwargs, 'q', MagicMock(), 'sid', 'mid', is_ide=False
            )
        return ds.call_args.args[2]

    def test_json_contract_kept_by_default(self):
        sent = self._route({})
        assert 'lc_openai_response_format' in sent

    def test_plain_text_reply_skips_json_contract(self):
        sent = self._route({'plain_text_reply': True})
        assert 'lc_openai_response_format' not in sent
        assert 'plain_text_reply' not in sent  # never reaches the provider
