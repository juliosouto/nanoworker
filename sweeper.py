import time
import uuid
import logging
import threading
from datetime import datetime
from croniter import croniter
from database import get_db
from agent_runner import process_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('sweeper')

def make_baileys_callback(jid):
    def callback(out_text):
        import requests as req
        from utils.audio_utils import extract_and_generate_audio
        try:
            logger.info(f"Cron job Baileys callback triggered for JID {jid}")
            text_to_send, audio_path = extract_and_generate_audio(out_text)
            if text_to_send:
                resp = req.post('http://127.0.0.1:3000/send', json={"text": text_to_send, "jid": jid}, timeout=5)
                logger.info(f"Baileys text response code: {resp.status_code}")
            if audio_path:
                resp = req.post('http://127.0.0.1:3000/send_audio', json={"file_path": audio_path, "jid": jid}, timeout=5)
                logger.info(f"Baileys audio response code: {resp.status_code}")
        except Exception as e:
            logger.error(f"Failed to send scheduled Baileys message: {e}")
    return callback

def make_cloud_callback(sender_id):
    def callback(out_text):
        from channels.whatsapp_cloud import send_text_message
        try:
            logger.info(f"Cron job Cloud API callback triggered for {sender_id}")
            send_text_message(sender_id, out_text)
        except Exception as e:
            logger.error(f"Failed to send scheduled Cloud API message: {e}")
    return callback

def sweep():
    logger.info("Sweeper started. Polling for scheduled tasks...")
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            now = datetime.now()
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
            
            # Fetch due cron jobs with channel_id from sessions
            cursor.execute('''
                SELECT c.id, c.session_id, c.content, c.cron_expression, s.channel_id
                FROM cron_jobs c
                JOIN sessions s ON c.session_id = s.id
                WHERE c.is_active = 1 
                AND c.next_run <= ?
            ''', (now_str,))
            
            due_jobs = cursor.fetchall()
            
            for job in due_jobs:
                job_id = job['id']
                session_id = job['session_id']
                content = job['content']
                cron_expression = job['cron_expression']
                channel_id = job['channel_id']
                
                # Update job based on recurrence
                if cron_expression:
                    try:
                        cron = croniter(cron_expression, now)
                        next_run = cron.get_next(datetime).strftime('%Y-%m-%d %H:%M:%S')
                        cursor.execute('UPDATE cron_jobs SET next_run = ? WHERE id = ?', (next_run, job_id))
                    except Exception as e:
                        logger.error(f"Error calculating next run for job {job_id}: {e}")
                        cursor.execute('UPDATE cron_jobs SET is_active = 0 WHERE id = ?', (job_id,))
                else:
                    # One-shot job, deactivate
                    cursor.execute('UPDATE cron_jobs SET is_active = 0 WHERE id = ?', (job_id,))
                
                strict_content = f"[SYSTEM: SCHEDULED TASK TRIGGERED]\nPlease execute ONLY the following task and nothing else. Do not repeat previous tasks:\n{content}"
                
                # Insert into messages_in for processing
                message_in_id = f"msg-in-{uuid.uuid4().hex[:8]}"
                cursor.execute('''
                    INSERT INTO messages_in (id, session_id, content, sender_id, processed)
                    VALUES (?, ?, ?, ?, ?)
                ''', (message_in_id, session_id, strict_content, 'scheduler', 1))
                
                conn.commit()
                
                logger.info(f"Dispatching scheduled job {job_id} as message {message_in_id} for session {session_id}")
                
                # Determine callback based on channel
                on_complete_cb = None
                if channel_id:
                    if channel_id.startswith('wa_web:'):
                        target_jid = channel_id.replace('wa_web:', '')
                        if '@' not in target_jid:
                            if '-' in target_jid or target_jid.startswith('120363'):
                                target_jid = f"{target_jid}@g.us"
                            else:
                                target_jid = f"{target_jid}@s.whatsapp.net"
                        on_complete_cb = make_baileys_callback(target_jid)
                    elif channel_id.startswith('whatsapp:'):
                        sender_id = channel_id.replace('whatsapp:', '')
                        on_complete_cb = make_cloud_callback(sender_id)
                
                # Dispatch processing in a background thread
                thread = threading.Thread(
                    target=process_message,
                    args=(message_in_id, session_id, strict_content),
                    kwargs={"on_complete": on_complete_cb},
                    daemon=True
                )
                thread.start()
                
            conn.close()
            
        except Exception as e:
            logger.error(f"Error in sweeper loop: {e}")
            
        # Poll every 10 seconds
        time.sleep(10)

if __name__ == '__main__':
    sweep()

