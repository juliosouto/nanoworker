import logging

import requests as req
from flask import Blueprint, jsonify, request, session
from database import get_config

from router import route_ide_message, route_inbound_message
from utils.audio_utils import transcribe_webhook_audio
from utils.file_utils import save_webhook_attachment
from utils.message_utils import check_wa_permissions, resolve_target_jid

webhooks_bp = Blueprint('webhooks', __name__)

BAILEYS_URL = 'http://127.0.0.1:3000'


# ---------------------------------------------------------------------------
# Helper functions (specific to this endpoint's integration with Baileys API)
# ---------------------------------------------------------------------------

def _build_wa_callback(target_jid):
    """Build an on_complete callback that sends the agent reply via Baileys."""
    from utils.audio_utils import extract_and_generate_audio

    def on_complete(out_text):
        try:
            logging.info(f"on_complete triggered for {target_jid} with text length {len(out_text)}")
            text_to_send, audio_path = extract_and_generate_audio(out_text)

            if text_to_send:
                resp = req.post(f'{BAILEYS_URL}/send', json={"text": text_to_send, "jid": target_jid}, timeout=5)
                logging.info(f"Text send response: {resp.status_code} {resp.text}")

            if audio_path:
                resp = req.post(f'{BAILEYS_URL}/send_audio', json={"file_path": audio_path, "jid": target_jid}, timeout=5)
                logging.info(f"Audio send response: {resp.status_code} {resp.text}")
            elif '<audio>' in out_text:
                resp = req.post(f'{BAILEYS_URL}/send', json={"text": "[Error generating audio]", "jid": target_jid}, timeout=5)
                logging.info(f"Audio error send response: {resp.status_code} {resp.text}")

        except Exception as e:
            logging.error(f"Failed to send reply to Baileys Worker: {e}")

    return on_complete


def _send_composing_presence(target_jid):
    """Notify the WhatsApp chat that the bot is typing."""
    try:
        req.post(f'{BAILEYS_URL}/presence', json={"jid": target_jid, "state": "composing"}, timeout=1)
    except Exception as e:
        logging.error(f"Failed to send composing presence: {e}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@webhooks_bp.before_request
def authenticate_webhooks():
    if request.path not in ['/api/webhook', '/api/ide-webhook']:
        return

    secret = request.headers.get('X-Webhook-Secret')
    expected_secret = get_config('WEBHOOK_SECRET')

    if secret and expected_secret and secret == expected_secret:
        return  # Valid internal service

    if session.get('logged_in'):
        csrf_token = request.headers.get('X-CSRFToken')
        try:
            from flask_wtf.csrf import validate_csrf
            validate_csrf(csrf_token)
            return  # Valid authenticated frontend request
        except Exception:
            return jsonify({"error": "Invalid CSRF token"}), 403
            
    return jsonify({"error": "Unauthorized"}), 401

@webhooks_bp.route('/api/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or 'content' not in data or 'channel_id' not in data:
        return jsonify({"error": "Missing required fields"}), 400

    content = data['content']

    # 1. Transcribe audio (before permission checks so transcription feeds mention detection)
    if 'audio_base64' in data:
        content = transcribe_webhook_audio(content, data['audio_base64'], data.get('mimetype', ''))

    # 2. WhatsApp-specific checks
    on_complete = None
    if data['channel_id'].startswith('wa_web:'):
        target_jid = resolve_target_jid(data)

        allowed, reason = check_wa_permissions(data, content)
        if not allowed:
            if reason == "permissions_or_disabled":
                return jsonify({"status": "ignored", "reason": "permissions_or_disabled"}), 200
            elif reason == "rate_limit":
                callback = _build_wa_callback(target_jid)
                callback("Rate limit reached. Please wait a minute.")
                return jsonify({"status": "ignored", "reason": "rate_limit"}), 200

        on_complete = _build_wa_callback(target_jid)
        _send_composing_presence(target_jid)

    # 3. Save attachment
    file_path = save_webhook_attachment(data)

    # 4. Route message
    in_id, session_id, is_sync = route_inbound_message(
        channel_id=data['channel_id'],
        content=content,
        sender_id=data.get('sender_id'),
        sender_id_alt=data.get('sender_id_alt'),
        sender_name=data.get('sender_name'),
        image_base64=file_path,
        file_mime_type=data.get('file_mime_type'),
        file_name=data.get('file_name'),
        on_complete=on_complete,
        client_message_id=data.get('message_id')
    )

    # 5. Response
    if is_sync:
        return jsonify({
            "status": "received",
            "message_in_id": in_id,
            "session_id": session_id,
            "response_text": "History cleared! Starting a new conversation.",
            "created_at": "Just now"
        }), 200

    return jsonify({
        "status": "processing",
        "message_in_id": in_id,
        "session_id": session_id,
    }), 202


@webhooks_bp.route('/api/ide-webhook', methods=['POST'])
def ide_webhook():
    data = request.json
    if not data or 'content' not in data or 'channel_id' not in data:
        return jsonify({"error": "Missing required fields"}), 400

    in_id, session_id = route_ide_message(
        channel_id=data['channel_id'],
        content=data['content'],
        sender_id=data.get('sender_id')
    )

    return jsonify({
        "status": "processing",
        "message_in_id": in_id,
        "session_id": session_id,
    }), 202
