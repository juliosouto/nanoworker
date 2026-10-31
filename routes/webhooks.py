import logging
import re
import threading

import requests as req
from flask import Blueprint, jsonify, request, session
from database import get_config

from router import route_ide_message, route_inbound_message
from utils.audio_utils import transcribe_webhook_audio
from utils.file_utils import save_webhook_attachment
from utils.message_utils import check_wa_permissions, resolve_target_jid

webhooks_bp = Blueprint('webhooks', __name__)

BAILEYS_URL = 'http://127.0.0.1:3000'

# Markdown image tags pointing at the temp-files route, e.g.
# ![imagem gerada](/api/temp/gen_abc123.png). Emitted by the image-generation
# backend; the web chat / IDE render them natively, and WhatsApp converts them
# into native media messages.
_IMAGE_MD_RE = re.compile(r'!\[[^\]]*\]\(/api/temp/([^)\s]+)\)')


# ---------------------------------------------------------------------------
# Helper functions (specific to this endpoint's integration with Baileys API)
# ---------------------------------------------------------------------------

def _resolve_temp_image_path(filename):
    """
    Safely resolves a /api/temp/<filename> reference to an absolute path inside
    the temp directory. Returns None if it escapes the temp dir or doesn't exist.
    """
    import os

    from utils.file_utils import get_temp_dir

    temp_dir = os.path.abspath(get_temp_dir())
    safe_path = os.path.abspath(os.path.join(temp_dir, filename))
    if not safe_path.startswith(temp_dir + os.sep):
        return None
    if not os.path.exists(safe_path):
        return None
    return safe_path


def extract_and_send_images(out_text, target_jid):
    """
    Detects Markdown image tags pointing at /api/temp/<file>, sends each as a
    native WhatsApp media message via the Baileys /send_file endpoint, and
    strips the tags from the text.

    The first image carries the remaining text as its caption, so the caller
    should not re-send that text as a separate message when images were
    delivered.

    Args:
        out_text (str): The agent reply, possibly containing ![](/api/temp/...).
        target_jid (str): The WhatsApp JID to deliver the media to.

    Returns:
        tuple: (remaining_text, images_sent) where remaining_text is the reply
        with the image tags removed and images_sent is the number of images
        actually delivered.
    """
    import mimetypes
    import os

    matches = list(_IMAGE_MD_RE.finditer(out_text))
    if not matches:
        return out_text, 0

    # Remove the image tags to compute the caption / remaining text.
    remaining = _IMAGE_MD_RE.sub("", out_text).strip()
    # Collapse the blank line the image tag leaves behind.
    remaining = "\n".join(
        line for line in remaining.splitlines() if line.strip()
    ).strip()

    sent = 0
    for idx, match in enumerate(matches):
        filename = match.group(1)
        try:
            abs_path = _resolve_temp_image_path(filename)
            if not abs_path:
                logging.warning(
                    f"Skipping image send: {filename} not found in temp dir"
                )
                continue

            mimetype, _ = mimetypes.guess_type(abs_path)
            if not mimetype:
                mimetype = "image/png"

            payload = {
                "file_path": abs_path,
                "mimetype": mimetype,
                "file_name": os.path.basename(abs_path),
                "caption": remaining if idx == 0 else "",
                "jid": target_jid,
            }
            resp = req.post(
                f"{BAILEYS_URL}/send_file", json=payload, timeout=30
            )
            logging.info(
                f"Image send response: {resp.status_code} {resp.text}"
            )
            sent += 1
        except Exception as e:
            logging.error(f"Failed to send image via Baileys Worker: {e}")

    return remaining, sent


def _build_wa_callback(target_jid, reply_to_msg_id=None, channel_id=None, worker_name=None):
    """Build an on_complete callback that sends the agent reply via Baileys.

    ``worker_name`` is recorded as the sender of the bot's replies in the
    channel timeline, so history and RAG show which worker answered.
    """
    from utils.audio_utils import extract_and_generate_audio

    last_progress_msg_id = None
    # The bot's own replies join the same channel timeline (from_me=1) so the
    # LLM history rebuilt from message_history keeps the assistant turns
    # interleaved with the (possibly mention-less) group messages.
    history_channel_id = channel_id or f"wa_web:{(target_jid or '').split(':')[0]}"

    def on_complete(out_text):
        nonlocal last_progress_msg_id
        try:
            logging.info(f"on_complete triggered for {target_jid} with text length {len(out_text)}")

            # Deliver generated images as native WhatsApp media. The first
            # image carries the remaining text as its caption, so when images
            # were sent we must not re-send that text via /send (avoids a
            # duplicated message).
            out_text, images_sent = extract_and_send_images(out_text, target_jid)

            text_to_send, audio_path = extract_and_generate_audio(out_text)

            is_progress_msg = bool(
                text_to_send and (
                    "Agent reflecting" in text_to_send
                    or "Error on attempt" in text_to_send
                    or "Quota exceeded" in text_to_send
                    or "Rate limit (" in text_to_send
                    or "Model overloaded (503)" in text_to_send
                    or "Model provider temporarily unavailable" in text_to_send
                    or "Empty response from model" in text_to_send
                )
            )

            # If this is a final successful response and we previously posted
            # a progress / retry error message, delete that progress message first.
            if not is_progress_msg and last_progress_msg_id:
                try:
                    del_payload = {"message_id": last_progress_msg_id, "jid": target_jid}
                    del_resp = req.post(f'{BAILEYS_URL}/delete', json=del_payload, timeout=5)
                    logging.info(f"Progress message deletion response: {del_resp.status_code} {del_resp.text}")
                except Exception as del_err:
                    logging.warning(f"Failed to delete progress message {last_progress_msg_id}: {del_err}")
                finally:
                    last_progress_msg_id = None

            # When images were delivered, the remaining text already rode along
            # as the first image's caption; only send it separately if no image
            # was actually sent.
            if text_to_send and not images_sent:
                payload = {"text": text_to_send, "jid": target_jid}
                if is_progress_msg and last_progress_msg_id:
                    payload["edit_msg_id"] = last_progress_msg_id
                elif reply_to_msg_id:
                    payload["quoted_msg_id"] = reply_to_msg_id

                resp = req.post(f'{BAILEYS_URL}/send', json=payload, timeout=5)
                logging.info(f"Text send response: {resp.status_code} {resp.text}")

                if resp.status_code == 200:
                    data = resp.json()
                    msg_id = data.get("message_id")
                    if is_progress_msg and msg_id:
                        last_progress_msg_id = msg_id
                    elif not is_progress_msg:
                        last_progress_msg_id = None

                    # Record the delivered reply (text only) in the channel
                    # timeline. Progress/heartbeat messages are NOT recorded.
                    # is_bot=1 marks it as an assistant turn (from_me alone
                    # would also cover the human owner typing on their phone).
                    if not is_progress_msg and text_to_send:
                        try:
                            import time as _time
                            from database import insert_message_history
                            bot_row_id = insert_message_history(
                                message_id=msg_id,
                                channel_id=history_channel_id,
                                remote_jid=target_jid,
                                is_group=target_jid.endswith('@g.us'),
                                from_me=1,
                                is_bot=1,
                                sender_name=worker_name,
                                content=text_to_send,
                                msg_timestamp=int(_time.time()),
                                was_processed=1,
                            )
                            if bot_row_id is not None:
                                from agent.lc.history_rag import vectorize_message
                                vectorize_message(bot_row_id)
                        except Exception as history_err:
                            logging.error(f"Failed to record bot reply in message_history: {history_err}")

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

    if 'audio_base64' in data or 'quoted_audio_base64' in data:
        # Transcription can take many seconds; the Baileys worker awaits this
        # request before forwarding its next message, so audio is handled in
        # the background and the request returns at once.
        threading.Thread(
            target=_handle_inbound_safely, args=(data,), daemon=True,
            name="webhook-audio",
        ).start()
        return jsonify({"status": "processing"}), 202

    body, status = _handle_inbound(data)
    return jsonify(body), status


def _handle_inbound_safely(data):
    """Runs _handle_inbound in a background thread, logging any failure."""
    try:
        _handle_inbound(data)
    except Exception:
        logging.exception("Background webhook processing failed")


def _handle_inbound(data):
    """Processes one inbound message; returns (response body, status code)."""
    content = data['content']

    # 1. Transcribe audio (before permission checks so transcription feeds mention detection)
    if 'audio_base64' in data:
        content = transcribe_webhook_audio(content, data['audio_base64'], data.get('mimetype', ''))

    # Transcribe quoted audio if present
    quoted_text = data.get('quoted_text') or ''
    if 'quoted_audio_base64' in data:
        quoted_text = transcribe_webhook_audio(
            quoted_text or '[Quoted audio received, waiting for transcription...]',
            data['quoted_audio_base64'],
            data.get('quoted_mimetype', '')
        )

    # 2. WhatsApp-specific checks
    on_complete = None
    if data['channel_id'].startswith('wa_web:'):
        target_jid = resolve_target_jid(data)

        # 2.0 Record EVERY text message into the channel timeline BEFORE the
        # permission gate. Group messages without a worker mention used to be
        # discarded by the worker; now they are saved with metadata into
        # message_history but never reach the agent pipeline.
        history_saved = None
        try:
            from database import insert_message_history
            history_saved = insert_message_history(
                message_id=data.get('message_id'),
                channel_id=data['channel_id'],
                remote_jid=data.get('remote_jid') or '',
                is_group=1 if (data.get('remote_jid') or '').endswith('@g.us') else 0,
                sender_id=data.get('sender_id'),
                sender_id_alt=data.get('sender_id_alt'),
                sender_name=data.get('sender_name'),
                from_me=1 if data.get('from_me') else 0,
                content=content,
                msg_timestamp=data.get('msg_timestamp'),
            )
        except Exception as history_err:
            logging.error(f"Failed to record inbound message in message_history: {history_err}")

        # Vectorize the stored message (sqlite-vec). Fail-open: on any error the
        # message stays text-only in the timeline and the boot backfill retries.
        if history_saved is not None:
            from agent.lc.history_rag import vectorize_message
            vectorize_message(history_saved)

        if data.get('history_only'):
            # Mention-less text message from the Baileys worker: saved above,
            # never processed. The worker keeps replying only when mentioned.
            return ({
                "status": "saved_only" if history_saved else "duplicate",
            }), 200

        allowed, reason = check_wa_permissions(data, content)
        if not allowed:
            # Every refusal must short-circuit here. should_process_wa_message returns
            # specific reasons (e.g. "no_worker_mentioned_in_transcription",
            # "sender_not_allowed", "bot_disabled"), so any reason not explicitly
            # handled below MUST still return before routing — otherwise refused
            # messages (e.g. audios without a worker mention) would be processed anyway.
            if reason == "rate_limit":
                callback = _build_wa_callback(target_jid, data.get('message_id'))
                callback("Rate limit reached. Please wait a minute.")
            return ({"status": "ignored", "reason": reason or "permissions_or_disabled"}), 200

        # The message reached the processing pipeline: flag its history row.
        if history_saved:
            try:
                from database import mark_message_history_processed
                mark_message_history_processed(data.get('message_id'))
            except Exception:
                pass

        from utils.message_utils import resolve_worker_from_content
        worker = resolve_worker_from_content(content) or {}
        on_complete = _build_wa_callback(
            target_jid, data.get('message_id'), channel_id=data['channel_id'],
            worker_name=worker.get('worker_name'),
        )
        _send_composing_presence(target_jid)

    # 3. Save attachment
    file_path = save_webhook_attachment(data)
    file_mime_type = data.get('file_mime_type')
    file_name = data.get('file_name')

    # If current message doesn't have an attachment but quoted message does, use quoted attachment
    if not file_path and 'quoted_image_base64' in data:
        from utils.file_utils import save_base64_attachment
        quoted_mime = data.get('quoted_mimetype') or 'image/jpeg'
        ext = 'jpg'
        if 'png' in quoted_mime: ext = 'png'
        elif 'pdf' in quoted_mime: ext = 'pdf'
        elif 'mp4' in quoted_mime: ext = 'mp4'
        elif 'ogg' in quoted_mime: ext = 'ogg'
        file_path = save_base64_attachment(data['quoted_image_base64'], f'quoted_media.{ext}')
        file_mime_type = quoted_mime
        file_name = f'quoted_media.{ext}'

    # Build enriched content with quoted context if present
    if quoted_text or data.get('quoted_sender'):
        quoted_sender = data.get('quoted_sender') or 'User'
        quoted_header = f"[Quoted message from: {quoted_sender}]"
        content = f"{quoted_header}\n{quoted_text}\n\n{content}"

    # Anti-hallucination guard: when audio arrives already transcribed, tell the
    # model explicitly. Small models have been observed hallucinating a call to
    # the nonexistent open() tool to "read the audio file" instead of answering
    # from the [Transcription]: text that was already in the prompt.
    if '[Transcription]:' in content:
        content = (
            f"{content}\n\n"
            "(Internal note: any audio in this message is already transcribed as text above. "
            "Never try to open or read audio/media files, and only call tools that are explicitly available.)"
        )

    # 4. Route message
    in_id, session_id, is_sync = route_inbound_message(
        channel_id=data['channel_id'],
        content=content,
        sender_id=data.get('sender_id'),
        sender_id_alt=data.get('sender_id_alt'),
        sender_name=data.get('sender_name'),
        image_base64=file_path,
        file_mime_type=file_mime_type,
        file_name=file_name,
        on_complete=on_complete,
        client_message_id=data.get('message_id')
    )

    # 5. Response
    if is_sync:
        return ({
            "status": "received",
            "message_in_id": in_id,
            "session_id": session_id,
            "response_text": "History cleared! Starting a new conversation.",
            "created_at": "Just now"
        }), 200

    return ({
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
