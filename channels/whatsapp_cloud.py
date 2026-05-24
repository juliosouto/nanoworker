"""
WhatsApp Cloud API channel adapter.

Uses the official Meta WhatsApp Business Cloud API:
- Receives messages via webhook (POST from Meta)
- Sends messages via REST API (POST to graph.facebook.com)
- Handles webhook verification (GET from Meta)

Required env vars:
  WHATSAPP_ACCESS_TOKEN     — Permanent or System User token from Meta dashboard
  WHATSAPP_PHONE_NUMBER_ID  — The Phone Number ID (not the phone number itself)
  WHATSAPP_VERIFY_TOKEN     — Any string you choose, must match Meta dashboard config
"""
import logging
import os
import tempfile

import requests
from dotenv import load_dotenv

from database import get_config
from utils.audio_utils import transcribe_audio

load_dotenv(override=True)

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
GRAPH_API_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def download_media(media_id):
    """Download media from WhatsApp Cloud API and return the temporary file path."""
    cfg = get_config()
    if not cfg["access_token"]:
        return None
        
    url = f"{GRAPH_API_URL}/{media_id}"
    headers = {"Authorization": f"Bearer {cfg['access_token']}"}
    
    try:
        # Get media URL
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        media_url = res.json().get("url")
        
        if not media_url:
            return None
            
        # Download media bytes
        media_res = requests.get(media_url, headers=headers, timeout=30)
        media_res.raise_for_status()
        
        # Save to temp file
        ext = ".ogg"
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tf.write(media_res.content)
        tf.close()
        return tf.name
    except Exception as e:
        logger.error(f"Failed to download WhatsApp media {media_id}: {e}")
        return None




def get_config():
    """Read WhatsApp config from environment. Returns dict with keys or None values."""
    return {
        "access_token": get_config("WHATSAPP_ACCESS_TOKEN"),
        "phone_number_id": os.environ.get("WHATSAPP_PHONE_NUMBER_ID"),
        "verify_token": get_config("WHATSAPP_VERIFY_TOKEN"),
    }


def is_configured():
    """Check if all required WhatsApp credentials are set."""
    cfg = get_config()
    return all(cfg.values())


# ---------------------------------------------------------------------------
# Webhook verification (GET)
# ---------------------------------------------------------------------------

def verify_webhook(args):
    """
    Handle Meta's webhook verification challenge.
    
    Args:
        args: dict-like object with query parameters
              (hub.mode, hub.verify_token, hub.challenge)
    
    Returns:
        tuple: (response_body, status_code)
    """
    mode = args.get("hub.mode")
    token = args.get("hub.verify_token")
    challenge = args.get("hub.challenge")

    cfg = get_config()

    if mode == "subscribe" and token == cfg["verify_token"]:
        logger.info("WhatsApp webhook verified successfully")
        return challenge, 200
    else:
        logger.warning("WhatsApp webhook verification failed")
        return "Forbidden", 403


# ---------------------------------------------------------------------------
# Inbound message parsing (POST)
# ---------------------------------------------------------------------------

def parse_incoming_messages(payload):
    """
    Parse incoming webhook payload from Meta.
    
    Extracts text messages from the webhook event structure.
    WhatsApp Cloud API sends a nested structure:
    
      { "entry": [{ "changes": [{ "value": { "messages": [...] } }] }] }
    
    Args:
        payload: The JSON body from Meta's webhook POST
        
    Returns:
        List of dicts with keys: sender, message_id, content, timestamp
    """
    messages = []

    if not payload:
        return messages

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            
            # Skip if no messages (could be a status update)
            if "messages" not in value:
                continue

            # Extract contact info for sender name
            contacts = {c["wa_id"]: c.get("profile", {}).get("name", c["wa_id"]) 
                       for c in value.get("contacts", [])}

            for msg in value.get("messages", []):
                msg_type = msg.get("type")
                sender = msg.get("from")
                msg_id = msg.get("id")
                timestamp = msg.get("timestamp")
                sender_name = contacts.get(sender, sender)

                # Extract text content based on message type
                if msg_type == "text":
                    content = msg.get("text", {}).get("body", "")
                elif msg_type == "image":
                    caption = msg.get("image", {}).get("caption", "")
                    content = caption if caption else "[Image received]"
                elif msg_type == "audio":
                    media_id = msg.get("audio", {}).get("id")
                    if media_id:
                        temp_file = download_media(media_id)
                        if temp_file:
                            content = transcribe_audio(temp_file)
                            try:
                                os.unlink(temp_file)
                            except:
                                pass
                        else:
                            content = "[Audio message received - Download failed]"
                    else:
                        content = "[Audio message received]"
                elif msg_type == "video":
                    caption = msg.get("video", {}).get("caption", "")
                    content = caption if caption else "[Video received]"
                elif msg_type == "document":
                    caption = msg.get("document", {}).get("caption", "")
                    filename = msg.get("document", {}).get("filename", "")
                    content = caption if caption else f"[Document: {filename}]"
                elif msg_type == "location":
                    lat = msg.get("location", {}).get("latitude")
                    lon = msg.get("location", {}).get("longitude")
                    content = f"[Location: {lat}, {lon}]"
                elif msg_type == "reaction":
                    emoji = msg.get("reaction", {}).get("emoji", "")
                    content = f"[Reaction: {emoji}]"
                else:
                    content = f"[Unsupported message type: {msg_type}]"

                if content:
                    messages.append({
                        "sender": sender,
                        "sender_name": sender_name,
                        "message_id": msg_id,
                        "content": content,
                        "timestamp": timestamp,
                        "type": msg_type,
                    })

    return messages


# ---------------------------------------------------------------------------
# Outbound message sending
# ---------------------------------------------------------------------------

def send_text_message(to, text):
    """
    Send a text message via WhatsApp Cloud API.
    
    Args:
        to: Recipient phone number (with country code, no +)
        text: Message text to send
        
    Returns:
        dict: API response or error dict
    """
    cfg = get_config()
    if not cfg["access_token"] or not cfg["phone_number_id"]:
        return {"error": "WhatsApp not configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID."}

    url = f"{GRAPH_API_URL}/{cfg['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        logger.info("WhatsApp message sent", extra={"to": to, "message_id": result.get("messages", [{}])[0].get("id")})
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return {"error": str(e)}


def mark_as_read(message_id):
    """
    Mark a received message as read (sends blue checkmarks).
    
    Args:
        message_id: The WhatsApp message ID to mark as read
    """
    cfg = get_config()
    if not cfg["access_token"] or not cfg["phone_number_id"]:
        return

    url = f"{GRAPH_API_URL}/{cfg['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        requests.post(url, json=payload, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to mark message as read: {e}")
