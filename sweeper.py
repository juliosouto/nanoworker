import logging
import threading
import time
import uuid
from datetime import datetime

from croniter import croniter

from agent_runner import process_message
from database import get_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('sweeper')

def make_baileys_callback(jid: str):
    """
    Cria uma função de callback específica para enviar mensagens via Baileys 
    (WhatsApp Web JS) para um determinado JID.
    
    Argumentos:
        jid (str): O ID do WhatsApp do destinatário.
        
    Retorna:
        function: A função de callback a ser executada ao concluir uma tarefa.
    """
    def callback(out_text: str):
        """
        Gera áudio (se aplicável) e envia a resposta de texto ou áudio via API interna.
        
        Argumentos:
            out_text (str): O texto gerado pelo agente para envio.
        """
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

def make_cloud_callback(sender_id: str):
    """
    Cria uma função de callback específica para enviar mensagens via WhatsApp Cloud API.
    
    Argumentos:
        sender_id (str): O identificador do remetente/destinatário na API Cloud.
        
    Retorna:
        function: A função de callback a ser executada ao concluir uma tarefa.
    """
    def callback(out_text: str):
        """
        Envia a mensagem de texto resultante utilizando a Cloud API.
        
        Argumentos:
            out_text (str): O texto gerado para ser enviado.
        """
        from channels.whatsapp_cloud import send_text_message
        try:
            logger.info(f"Cron job Cloud API callback triggered for {sender_id}")
            send_text_message(sender_id, out_text)
        except Exception as e:
            logger.error(f"Failed to send scheduled Cloud API message: {e}")
    return callback

def sweep():
    """
    Loop principal do Sweeper. Verifica a cada 10 segundos no banco de dados
    se há trabalhos agendados (cron_jobs) que precisam ser executados.
    
    Quando um trabalho está na hora, ele cria uma mensagem do sistema e despacha
    para o agente (LLM) processar num pool de threads. Atualiza as recorrências.
    """
    logger.info("Sweeper started. Polling for scheduled tasks...")
    from concurrent.futures import ThreadPoolExecutor
    executor = ThreadPoolExecutor(max_workers=5)
    
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            now = datetime.now()
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
            
            # Fetch due cron jobs with channel_id from sessions
            cursor.execute('''
                SELECT c.id, c.session_id, c.content, c.cron_expression, s.channel_id, c.execution_count, c.max_executions
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
                execution_count = job['execution_count'] or 0
                max_executions = job['max_executions']
                
                new_execution_count = execution_count + 1
                is_active = 1
                
                if max_executions is not None and new_execution_count >= max_executions:
                    is_active = 0
                
                # Update job based on recurrence
                if cron_expression:
                    try:
                        cron = croniter(cron_expression, now)
                        next_run = cron.get_next(datetime).strftime('%Y-%m-%d %H:%M:%S')
                        cursor.execute('UPDATE cron_jobs SET next_run = ?, execution_count = ?, is_active = ? WHERE id = ?', (next_run, new_execution_count, is_active, job_id))
                    except Exception as e:
                        logger.error(f"Error calculating next run for job {job_id}: {e}")
                        cursor.execute('UPDATE cron_jobs SET is_active = 0, execution_count = ? WHERE id = ?', (new_execution_count, job_id))
                else:
                    # One-shot job, deactivate
                    cursor.execute('UPDATE cron_jobs SET is_active = 0, execution_count = ? WHERE id = ?', (new_execution_count, job_id))
                
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
                
                # Dispatch processing in a background thread pool
                executor.submit(
                    process_message,
                    message_in_id, session_id, strict_content,
                    on_complete=on_complete_cb
                )
                
            conn.close()
            
        except Exception as e:
            logger.error(f"Error in sweeper loop: {e}")
            
        # Poll every 10 seconds
        time.sleep(10)

if __name__ == '__main__':
    sweep()

