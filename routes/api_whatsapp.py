import logging
import os
import shutil
import subprocess

from flask import Blueprint, Response, jsonify, request

import state
from channels.whatsapp_cloud import mark_as_read as wa_mark_read
from channels.whatsapp_cloud import parse_incoming_messages as wa_parse
from channels.whatsapp_cloud import send_text_message as wa_send
from channels.whatsapp_cloud import verify_webhook as wa_verify
from database import get_db
from router import route_inbound_message
from utils.message_utils import should_process_wa_message

api_whatsapp_bp = Blueprint('api_whatsapp', __name__)

@api_whatsapp_bp.route('/api/whatsapp/config', methods=['POST'])
def save_whatsapp_config():
    data = request.json
    allowed_from = data.get('allowed_from', '')
    allowed_to = data.get('allowed_to', '')
    bot_enabled = 1 if data.get('bot_enabled') else 0
    allow_mentions = 1 if data.get('allow_mentions') else 0
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE whatsapp_config 
        SET allowed_from = ?, allowed_to = ?, bot_enabled = ?, allow_mentions = ?
        WHERE id = 1
    ''', (allowed_from, allowed_to, bot_enabled, allow_mentions))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@api_whatsapp_bp.route('/api/whatsapp/auth-stream')
def whatsapp_auth_stream():
    """
    SSE endpoint to stream QR code from the Node.js Baileys subprocess.
    """
    def generate():
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'node_scripts', 'wa_auth.js')
        process = subprocess.Popen(
            ['node', script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    yield f"data: {line.strip()}\n\n"
        finally:
            process.terminate()
            process.wait()

    return Response(generate(), mimetype='text/event-stream')

@api_whatsapp_bp.route('/api/whatsapp/logout', methods=['POST'])
def whatsapp_logout():
    auth_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.store', 'auth')
    if os.path.exists(auth_dir):
        shutil.rmtree(auth_dir)
    return jsonify({"status": "success"})

@api_whatsapp_bp.route('/api/whatsapp/restart', methods=['POST'])
def whatsapp_restart():
    try:
        if state.worker_process:
            logging.info("Terminating existing Baileys worker...")
            state.worker_process.terminate()
            state.worker_process.wait(timeout=5)
        
        worker_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'node_scripts', 'wa_worker.js')
        if os.path.exists(worker_script):
            logging.info("Restarting Baileys WhatsApp Worker (wa_worker.js)...")
            state.worker_process = subprocess.Popen(['node', worker_script])
            return jsonify({"status": "success", "message": "Worker restarted"})
        else:
            return jsonify({"status": "error", "message": "Worker script not found"}), 404
    except Exception as e:
        logging.error(f"Failed to restart worker: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@api_whatsapp_bp.route('/whatsapp/webhook', methods=['GET'])
def whatsapp_verify():
    body, status = wa_verify(request.args)
    return body, status

@api_whatsapp_bp.route('/whatsapp/webhook', methods=['POST'])
def whatsapp_inbound():
    payload = request.json
    messages = wa_parse(payload)

    for msg in messages:
        sender_id = msg["sender"]
        
        if not should_process_wa_message(sender_id):
            logging.info(f"Ignored Cloud API message from {sender_id} due to WhatsApp config permissions.")
            continue

        channel_id = f"whatsapp:{sender_id}"
        content = msg["content"]
        wa_mark_read(msg["message_id"])
        
        # Build callback to send reply via WhatsApp Cloud API
        def make_wa_callback(sid):
            def callback(out_text):
                wa_send(sid, out_text)
            return callback

        route_inbound_message(
            channel_id=channel_id,
            content=content,
            sender_id=sender_id,
            on_complete=make_wa_callback(sender_id)
        )

    return jsonify({"status": "ok"}), 200
