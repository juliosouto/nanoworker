import logging

from flask import Blueprint, jsonify, request

from router import route_ide_message, route_inbound_message
from utils.message_utils import should_process_wa_message

webhooks_bp = Blueprint('webhooks', __name__)

@webhooks_bp.route('/api/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data or 'content' not in data or 'channel_id' not in data:
        return jsonify({"error": "Missing required fields"}), 400

    content = data['content']
    
    # Process audio if present BEFORE permission checks, so the transcribed text can be evaluated
    if 'audio_base64' in data:
        from utils.audio_utils import process_base64_audio_to_text
        try:
            transcription = process_base64_audio_to_text(data['audio_base64'], data.get('mimetype', ''))
            content = f"{content}\n[Transcription]: {transcription}"
        except Exception as e:
            logging.error(f"Failed to process webhook audio: {e}")
            content = f"{content}\n[Internal error processing audio]"
    on_complete = None
    if data['channel_id'].startswith('wa_web:'):
        def on_complete(out_text):
            import requests as req
            from utils.audio_utils import extract_and_generate_audio
            target_jid = data.get('remote_jid') or data.get('sender_jid')
            if not target_jid:
                target_jid = f"{data.get('sender_id')}@s.whatsapp.net"
            
            try:
                logging.info(f"on_complete triggered for {target_jid} with text length {len(out_text)}")
                text_to_send, audio_path = extract_and_generate_audio(out_text)
                
                if text_to_send:
                    resp = req.post('http://127.0.0.1:3000/send', json={"text": text_to_send, "jid": target_jid}, timeout=5)
                    logging.info(f"Text send response: {resp.status_code} {resp.text}")
                    
                if audio_path:
                    resp = req.post('http://127.0.0.1:3000/send_audio', json={"file_path": audio_path, "jid": target_jid}, timeout=5)
                    logging.info(f"Audio send response: {resp.status_code} {resp.text}")
                elif '<audio>' in out_text and not audio_path:
                    resp = req.post('http://127.0.0.1:3000/send', json={"text": "[Error generating audio]", "jid": target_jid}, timeout=5)
                    logging.info(f"Audio error send response: {resp.status_code} {resp.text}")

            except Exception as e:
                logging.error(f"Failed to send reply to Baileys Worker: {e}")

        channel_base = data['channel_id'].replace('wa_web:', '')
        is_group = '@g.us' in data['channel_id']
        if not should_process_wa_message(channel_base, content, is_group) and \
           not should_process_wa_message(data.get('sender_id'), content, is_group):
            logging.info(f"Ignored message from {data.get('sender_id')} in channel {channel_base} due to WhatsApp config permissions.")
            return jsonify({"status": "ignored", "reason": "permissions_or_disabled"}), 200

        from utils.message_utils import check_rate_limit
        if not check_rate_limit(data.get('sender_id')):
            logging.warning(f"Rate limit exceeded for {data.get('sender_id')}")
            on_complete("Rate limit reached. Please wait a minute.")
            return jsonify({"status": "ignored", "reason": "rate_limit"}), 200

        try:
            import requests as req
            target_jid = data.get('remote_jid') or data.get('sender_jid')
            if not target_jid:
                target_jid = f"{data.get('sender_id')}@s.whatsapp.net"
            req.post('http://127.0.0.1:3000/presence', json={"jid": target_jid, "state": "composing"}, timeout=1)
        except Exception as e:
            logging.error(f"Failed to send composing presence: {e}")


    file_path = None
    b64_data = data.get('file_base64') or data.get('image_base64')
    if b64_data:
        from utils.file_utils import save_base64_attachment
        fname = data.get('file_name', 'attachment')
        file_path = save_base64_attachment(b64_data, fname)

    in_id, session_id, is_sync = route_inbound_message(
        channel_id=data['channel_id'],
        content=content,
        sender_id=data.get('sender_id'),
        image_base64=file_path,
        file_mime_type=data.get('file_mime_type'),
        file_name=data.get('file_name'),
        on_complete=on_complete
    )
    
    # /new command is synchronous — return immediate response
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
