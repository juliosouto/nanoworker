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

def sweep():
    logger.info("Sweeper started. Polling for scheduled tasks...")
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            now = datetime.now()
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
            
            # Fetch due cron jobs
            cursor.execute('''
                SELECT id, session_id, content, cron_expression 
                FROM cron_jobs 
                WHERE is_active = 1 
                AND next_run <= ?
            ''', (now_str,))
            
            due_jobs = cursor.fetchall()
            
            for job in due_jobs:
                job_id = job['id']
                session_id = job['session_id']
                content = job['content']
                cron_expression = job['cron_expression']
                
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
                
                # Dispatch processing in a background thread
                thread = threading.Thread(
                    target=process_message,
                    args=(message_in_id, session_id, strict_content),
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
