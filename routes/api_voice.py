"""
Endpoint seguro para clientes de voz (ex.: app Android) falarem com um worker.

Autenticação: header `Authorization: Bearer <token>`. O token é gerado uma vez
com `python -m routes.api_voice` e só o hash SHA-256 fica guardado no banco.
"""
import hashlib
import hmac
import logging
import re
import secrets
import threading

from flask import Blueprint, jsonify, request

from agent.message_processor import VOICE_AGENT_CHANNEL_PREFIX, VOICE_CHANNEL_PREFIX
from database import get_all_workers_with_capabilities, get_config, set_config
from router import route_inbound_message
from security import limiter

logger = logging.getLogger(__name__)

voice_bp = Blueprint('api_voice', __name__)

TOKEN_HASH_KEY = 'VOICE_API_TOKEN_HASH'
REPLY_TIMEOUT_S = 120
# /agent runs tools, so it may take longer.
AGENT_REPLY_TIMEOUT_S = 300
# The app sends the conversation history it wants inside `text`, so the limit
# is generous; the server keeps no history for this channel.
MAX_TEXT_CHARS = 200_000
MIN_WORDS, MAX_WORDS, DEFAULT_WORDS = 10, 300, 60
CONVERSATION_RE = re.compile(r'^[a-z0-9-]{1,32}$')


def generate_voice_token() -> str:
    """Gera um novo token e guarda só o hash. Invalida o token anterior."""
    token = secrets.token_urlsafe(32)
    set_config(TOKEN_HASH_KEY, hashlib.sha256(token.encode()).hexdigest())
    return token


def _authorized() -> bool:
    stored = get_config(TOKEN_HASH_KEY)
    header = request.headers.get('Authorization', '')
    if not stored or not header.startswith('Bearer '):
        return False
    given = hashlib.sha256(header[len('Bearer '):].strip().encode()).hexdigest()
    return hmac.compare_digest(given, stored)


def _style_block(max_words: int) -> str:
    return (
        f"[Formato obrigatório desta resposta (canal de voz): no máximo {max_words} palavras, "
        "em português, sem listas, tabelas, markdown ou emojis, sem introdução e sem repetir "
        "a pergunta. Seja direto.]"
    )


def _plain_for_speech(text: str) -> str:
    """Remove markdown e tags (ex.: <audio>) que o TTS leria em voz alta."""
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    text = re.sub(r'</?[A-Za-z][^>]*>', ' ', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'[*_`#>]+', '', text)
    text = re.sub(r'^\s*[-•]\s+', '', text, flags=re.M)
    return re.sub(r'\s+', ' ', text).strip()


def _limit_words(text: str, max_words: int) -> str:
    """Corta a resposta no limite, preferindo terminar em uma frase completa."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    cut = ' '.join(words[:max_words])
    ends = list(re.finditer(r'[.!?](?=\s|$)', cut))
    if ends and ends[-1].start() + 1 > len(cut) * 0.5:
        return cut[:ends[-1].start() + 1]
    return cut.rstrip(',;:') + '.'


@voice_bp.after_request
def _cors(resp):
    # O app de voz roda de um arquivo local (origem "null"). A autenticação é
    # só pelo Bearer token; não há cookies, então liberar a origem é seguro.
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resp


@voice_bp.route('/api/voice/workers', methods=['GET'])
@limiter.limit("60 per minute")
def list_voice_workers():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    names = [w.get('worker_name') for w in get_all_workers_with_capabilities() if w.get('worker_name')]
    return jsonify({"workers": names}), 200


def _parse_request():
    """Validates the body shared by /ask and /agent.

    Returns ((worker_name, text, conversation, max_words), None) or
    (None, (response, status)).
    """
    data = request.get_json(silent=True) or {}
    worker = (data.get('worker') or '').strip()
    text = (data.get('text') or '').strip()
    conversation = (data.get('conversation') or 'default').strip().lower()

    try:
        max_words = int(data.get('max_words', DEFAULT_WORDS))
    except (TypeError, ValueError):
        return None, (jsonify({"error": "max_words must be an integer"}), 400)
    max_words = min(max(max_words, MIN_WORDS), MAX_WORDS)

    if not worker or not text:
        return None, (jsonify({"error": "worker and text are required"}), 400)
    if len(text) > MAX_TEXT_CHARS:
        return None, (jsonify({"error": f"text exceeds {MAX_TEXT_CHARS} characters"}), 413)
    if not CONVERSATION_RE.match(conversation):
        return None, (jsonify({"error": "invalid conversation id"}), 400)

    known = {w.get('worker_name', '').lower(): w.get('worker_name') for w in get_all_workers_with_capabilities()}
    if worker.lower() not in known:
        return None, (jsonify({"error": "unknown worker"}), 404)
    return (known[worker.lower()], text, conversation, max_words), None


@voice_bp.route('/api/voice/ask', methods=['POST'])
@limiter.limit("30 per minute")
def ask_worker():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    parsed, error = _parse_request()
    if error:
        return error
    worker_name, text, conversation, max_words = parsed

    done = threading.Event()
    box = {}

    def on_complete(reply):
        box['reply'] = reply
        done.set()

    # A menção "@worker" fixa o worker; o bloco de formato limita a verbosidade.
    content = f"@{worker_name} {_style_block(max_words)}\n{text}"
    try:
        route_inbound_message(
            channel_id=f"{VOICE_CHANNEL_PREFIX}{conversation}",
            content=content,
            sender_id='voice-app',
            on_complete=on_complete,
        )
    except Exception:
        logger.exception("voice ask: failed to dispatch message")
        return jsonify({"error": "dispatch failed"}), 500

    if not done.wait(REPLY_TIMEOUT_S):
        return jsonify({"error": "worker timeout"}), 504

    reply = _limit_words(_plain_for_speech(str(box.get('reply') or '')), max_words)
    return jsonify({"reply": reply, "worker": worker_name}), 200


class _FinalReply:
    """on_complete for /agent: process_message sends the final reply to
    ``on_final``; intermediate feedback (tool results, plans, retries) goes to
    the call itself and is ignored, so the app only hears the answer."""

    def __init__(self):
        self.done = threading.Event()
        self.reply = None

    def __call__(self, text):
        logger.debug("voice agent: intermediate feedback ignored: %.80s", text)

    def on_final(self, text):
        self.reply = text
        self.done.set()


@voice_bp.route('/api/voice/agent', methods=['POST'])
@limiter.limit("30 per minute")
def ask_worker_agent():
    """Same body as /ask, but the worker runs as it does on the other
    channels: its system prompt, standard rules, user memory, tools, database
    access and this conversation's server-side history."""
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401
    parsed, error = _parse_request()
    if error:
        return error
    worker_name, text, conversation, max_words = parsed

    callback = _FinalReply()
    content = f"@{worker_name} {_style_block(max_words)}\n{text}"
    try:
        route_inbound_message(
            channel_id=f"{VOICE_AGENT_CHANNEL_PREFIX}{conversation}",
            content=content,
            sender_id='voice-app',
            on_complete=callback,
        )
    except Exception:
        logger.exception("voice agent: failed to dispatch message")
        return jsonify({"error": "dispatch failed"}), 500

    if not callback.done.wait(AGENT_REPLY_TIMEOUT_S):
        return jsonify({"error": "worker timeout"}), 504

    reply = _limit_words(_plain_for_speech(str(callback.reply or '')), max_words)
    return jsonify({"reply": reply, "worker": worker_name}), 200


if __name__ == '__main__':
    from database import init_db
    init_db()
    print(generate_voice_token())
