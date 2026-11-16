from unittest.mock import patch

import pytest

from app import app
from routes import api_voice


@pytest.fixture
def client(mock_db_path):
    import database
    database.init_db()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def token(client):
    return api_voice.generate_voice_token()


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


WORKERS = [{'worker_name': 'Quen', 'worker_model': 'x'}]


def test_ask_requires_token(client):
    r = client.post('/api/voice/ask', json={'worker': 'Quen', 'text': 'oi'})
    assert r.status_code == 401


def test_wrong_token_rejected(client, token):
    r = client.post('/api/voice/ask', json={'worker': 'Quen', 'text': 'oi'},
                    headers={'Authorization': 'Bearer errado'})
    assert r.status_code == 401


def test_token_stored_as_hash_only(client, token, mock_db_path):
    import database
    stored = database.get_config(api_voice.TOKEN_HASH_KEY)
    assert stored and stored != token and len(stored) == 64


def test_unknown_worker_404(client, token):
    with patch('routes.api_voice.get_all_workers_with_capabilities', return_value=WORKERS):
        r = client.post('/api/voice/ask', json={'worker': 'Nope', 'text': 'oi'}, headers=_auth(token))
    assert r.status_code == 404


def test_text_too_long_413(client, token):
    with patch('routes.api_voice.get_all_workers_with_capabilities', return_value=WORKERS):
        r = client.post('/api/voice/ask', json={'worker': 'Quen', 'text': 'a' * 2001},
                        headers=_auth(token))
    assert r.status_code == 413


def test_ask_returns_limited_plain_reply(client, token):
    def fake_route(channel_id, content, sender_id, on_complete):
        assert '@Quen' in content
        assert 'no máximo 10 palavras' in content
        on_complete("**Resposta** muito longa " + " ".join(["palavra"] * 50) + ".")
    with patch('routes.api_voice.get_all_workers_with_capabilities', return_value=WORKERS), \
         patch('routes.api_voice.route_inbound_message', side_effect=fake_route):
        r = client.post('/api/voice/ask', json={'worker': 'quen', 'text': 'oi', 'max_words': 10},
                        headers=_auth(token))
    assert r.status_code == 200
    body = r.get_json()
    assert body['worker'] == 'Quen'
    assert '**' not in body['reply']
    assert len(body['reply'].split()) <= 10


def test_max_words_is_clamped(client, token):
    seen = {}
    def fake_route(channel_id, content, sender_id, on_complete):
        seen['content'] = content
        on_complete("ok")
    with patch('routes.api_voice.get_all_workers_with_capabilities', return_value=WORKERS), \
         patch('routes.api_voice.route_inbound_message', side_effect=fake_route):
        client.post('/api/voice/ask', json={'worker': 'Quen', 'text': 'oi', 'max_words': 99999},
                    headers=_auth(token))
    assert 'no máximo 300 palavras' in seen['content']


def test_invalid_conversation_400(client, token):
    with patch('routes.api_voice.get_all_workers_with_capabilities', return_value=WORKERS):
        r = client.post('/api/voice/ask', json={'worker': 'Quen', 'text': 'oi', 'conversation': '../x'},
                        headers=_auth(token))
    assert r.status_code == 400


def test_workers_list(client, token):
    with patch('routes.api_voice.get_all_workers_with_capabilities', return_value=WORKERS):
        r = client.get('/api/voice/workers', headers=_auth(token))
    assert r.status_code == 200
    assert r.get_json() == {'workers': ['Quen']}


def test_cors_headers_on_voice_responses(client):
    r = client.get('/api/voice/workers')
    assert r.headers.get('Access-Control-Allow-Origin') == '*'
    assert 'Authorization' in r.headers.get('Access-Control-Allow-Headers', '')


def test_plain_for_speech_removes_tags():
    out = api_voice._plain_for_speech("<audio>Agora fazem 25 graus.</audio>")
    assert out == "Agora fazem 25 graus."


def test_limit_words_cuts_at_sentence():
    text = "Uma duas tres quatro cinco seis sete. " + " ".join(["palavra"] * 30)
    out = api_voice._limit_words(text, 8)
    assert out == "Uma duas tres quatro cinco seis sete."


def test_limit_words_adds_period_when_no_sentence_end():
    out = api_voice._limit_words(" ".join(["palavra"] * 30), 5)
    assert out == "palavra palavra palavra palavra palavra."
