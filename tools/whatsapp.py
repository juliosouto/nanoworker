import requests
import logging

logger = logging.getLogger(__name__)

BAILEYS_URL = "http://127.0.0.1:3000/send"

def is_allowed_to(phone_number: str) -> bool:
    if not phone_number or phone_number.lower() == "self":
        return True

    from database import get_db
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT allowed_to FROM whatsapp_config WHERE id = 1')
        config = cursor.fetchone()
        conn.close()
        
        if not config:
            return True
            
        allowed_to = config['allowed_to']
        
        clean_target = phone_number.strip().replace("+", "").replace(" ", "")
        if "@" not in clean_target:
            clean_target = clean_target.replace("-", "")

        import requests
        try:
            resp = requests.get('http://127.0.0.1:3000/me', timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                own_number = data.get('number')
                lid_number = data.get('lid_number')
                if own_number and clean_target == str(own_number):
                    return True
                if lid_number and clean_target == str(lid_number):
                    return True
        except Exception:
            pass

        if not allowed_to or not allowed_to.strip():
            return False
            
        allowed_list = [num.strip() for num in allowed_to.split(',') if num.strip()]
        sanitized_allowed_list = []
        for num in allowed_list:
            n = num.strip().replace("+", "").replace(" ", "")
            if "@" not in n:
                n = n.replace("-", "")
            sanitized_allowed_list.append(n)
            
        clean_target = phone_number.strip().replace("+", "").replace(" ", "")
        if "@" not in clean_target:
            clean_target = clean_target.replace("-", "")
            
        if clean_target not in sanitized_allowed_list:
            return False
            
        return True
    except Exception as e:
        logger.error(f"Error checking allowed_to: {e}")
        return True



def send_whatsapp_message(phone_number: str, message: str) -> str:
    """
    Sends a text message to a phone number via WhatsApp.
    DO NOT use this tool to reply to the current active conversation. Your text responses are automatically sent back to the current chat!
    ONLY use this tool if you explicitly need to initiate a new message to a DIFFERENT phone number.

    Args:
        phone_number: The recipient's phone number with country code, without '+' or spaces.
                      Example: '5511999998888' for a Brazilian number.
                      If you want to send to the user's own number (the connected account), pass 'self'.
        message: The text message to send.

    Returns:
        A confirmation string indicating success or an error message.
    """
    from utils.audio_utils import extract_and_generate_audio
    text_to_send, audio_path = extract_and_generate_audio(message)
    
    if not is_allowed_to(phone_number):
        return (f"Error: Access Denied. Sending messages to {phone_number} is blocked. "
                f"You MUST reply to the user EXACTLY with this English sentence: "
                f"'You must add the number {phone_number} to the Allowed To list in the WhatsApp Settings page before I can send messages to it.'")
    
    try:
        if text_to_send:
            payload = {"text": text_to_send}
    
            if phone_number and phone_number.lower() != "self":
                # Format as WhatsApp JID
                jid = phone_number.strip().replace("+", "").replace(" ", "")
                if "@" not in jid:
                    jid = jid.replace("-", "")
                    jid = f"{jid}@s.whatsapp.net"
                payload["jid"] = jid
    
            response = requests.post(BAILEYS_URL, json=payload, timeout=15)
    
            if response.status_code == 503:
                return "Error: WhatsApp client is not connected. Please check the connection in Settings."
            elif response.status_code != 200:
                return f"Error sending WhatsApp message: HTTP {response.status_code} - {response.text}"
                
        if audio_path:
            audio_payload = {"file_path": audio_path}
            if phone_number and phone_number.lower() != "self":
                jid = phone_number.strip().replace("+", "").replace(" ", "")
                if "@" not in jid:
                    jid = jid.replace("-", "")
                    jid = f"{jid}@s.whatsapp.net"
                audio_payload["jid"] = jid
                
            audio_url = BAILEYS_URL.replace("/send", "/send_audio")
            audio_response = requests.post(audio_url, json=audio_payload, timeout=30)
            
            if audio_response.status_code == 503:
                return "Error: WhatsApp client is not connected."
            elif audio_response.status_code != 200:
                return f"Error sending audio message: HTTP {audio_response.status_code}"
                
        return "Message sent successfully."

    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to WhatsApp service. Make sure the WhatsApp worker is running."
    except requests.exceptions.Timeout:
        return "Error: WhatsApp service timed out. Please try again."
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return f"Error sending WhatsApp message: {str(e)}"

def send_whatsapp_file(phone_number: str, file_path: str, caption: str = "") -> str:
    """
    Sends a local file to a phone number via WhatsApp.
    Use this tool whenever you need to send a requested file or document to someone on WhatsApp.

    Args:
        phone_number: The recipient's phone number with country code, without '+' or spaces.
                      Example: '5511999998888' for a Brazilian number.
                      If you want to send to the user's own number (the connected account), pass 'self'.
        file_path: The absolute path to the local file to be sent.
        caption: Optional text caption to accompany the file.

    Returns:
        A confirmation string indicating success or an error message.
    """
    import os
    import shutil
    import uuid
    import mimetypes

    if not is_allowed_to(phone_number):
        return (f"Error: Access Denied. Sending files to {phone_number} is blocked. "
                f"You MUST reply to the user EXACTLY with this English sentence: "
                f"'You must add the number {phone_number} to the Allowed To list in the WhatsApp Settings page before I can send files to it.'")

    if not os.path.isfile(file_path):
        return f"Error: File not found at {file_path}"

    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    file_name = os.path.basename(file_path)
    unique_id = uuid.uuid4().hex[:8]
    temp_file_name = f"{unique_id}_{file_name}"
    temp_file_path = os.path.join(temp_dir, temp_file_name)

    try:
        shutil.copy2(file_path, temp_file_path)
    except Exception as e:
        logger.error(f"Failed to copy file to temp: {e}")
        return f"Error copying file to temporary directory: {str(e)}"

    try:
        mimetype, _ = mimetypes.guess_type(temp_file_path)
        if not mimetype:
            mimetype = "application/octet-stream"
        
        payload = {
            "file_path": temp_file_path,
            "mimetype": mimetype,
            "file_name": file_name,
            "caption": caption
        }

        if phone_number and phone_number.lower() != "self":
            # Format as WhatsApp JID
            jid = phone_number.strip().replace("+", "").replace(" ", "")
            if "@" not in jid:
                jid = jid.replace("-", "")
                jid = f"{jid}@s.whatsapp.net"
            payload["jid"] = jid

        # Assuming Baileys is listening on the same host but endpoint is /send_file
        send_file_url = BAILEYS_URL.replace("/send", "/send_file")
        response = requests.post(send_file_url, json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            target = data.get("target", phone_number)
            return f"File '{file_name}' sent successfully to {target}."
        elif response.status_code == 503:
            return "Error: WhatsApp client is not connected. Please check the connection in Settings."
        else:
            return f"Error sending WhatsApp file: HTTP {response.status_code} - {response.text}"

    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to WhatsApp service. Make sure the WhatsApp worker is running."
    except requests.exceptions.Timeout:
        return "Error: WhatsApp service timed out while sending file. Please try again."
    except Exception as e:
        logger.error(f"Failed to send WhatsApp file: {e}")
        return f"Error sending WhatsApp file: {str(e)}"
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.error(f"Failed to delete temp file {temp_file_path}: {e}")
