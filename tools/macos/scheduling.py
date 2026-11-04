import os
import uuid
from datetime import datetime
from typing import Optional

from croniter import croniter

from database import get_db

def schedule_task(description: str, prompt: str, cron_expression: Optional[str] = None, process_after: Optional[str] = None, max_executions: Optional[int] = None, script: Optional[str] = None) -> str:
    """
    Creates a cron job / scheduled task: runs a prompt later or periodically (reminders, recurring reports, monitoring a chat every N minutes). This is how you create, rewrite or replace cron jobs; there is no server crontab or SSH involved.
    For a job that must repeat the same logic every time (monitoring, rules, counting), pass a Python `script` instead of relying on yourself at each run.
    
    Args:
        description: A short summary of what this job does.
        prompt: The instruction for the agent to execute when the time comes. For checks/monitoring, say when to write to the chat (e.g. 'if X sent a message, delete it and tell the group; otherwise stay silent'); runs with nothing to report send no message.
        cron_expression: A standard cron expression (e.g. "0 9 * * 1-5" for weekdays at 9am). If provided, the task will repeat.
        process_after: An ISO formatted timestamp (e.g., "2023-12-31 23:59:59") for a one-shot task. 
                       If both are provided, cron_expression takes precedence for the first execution.
        max_executions: The maximum number of times this task should run. If provided, the task will automatically deactivate after reaching this count.
        script: A Python 3 script to run instead of asking the agent. Prefer it whenever the job must do the same thing every time: checking a chat, counting, fetching data, applying a rule (e.g. delete a user's message when they post). The script runs on its own, costs no model calls and is exact; what it prints is sent to the chat, and printing nothing keeps the chat silent. It runs with a 120 second limit and needs the Terminal permission. Use `prompt` only for jobs that need judgment each run (writing a reply, summarizing); if you give both, the script runs and the prompt is kept for reference.
    
    Returns:
        A confirmation string with the scheduled task ID.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    from utils.session import current_session_id
    session_id = current_session_id.get()
    
    if not session_id:
        return "Error: No active session found to schedule the task."
    
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    
    now = datetime.now()
    if cron_expression:
        try:
            cron = croniter(cron_expression, now)
            next_run = cron.get_next(datetime).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            return f"Error parsing cron expression: {e}"
    elif process_after:
        next_run = process_after
    else:
        next_run = now.strftime('%Y-%m-%d %H:%M:%S')
    
    query = '''
        INSERT INTO cron_jobs (id, session_id, description, content, script, cron_expression, next_run, max_executions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    '''
    params = (job_id, session_id, description, prompt, (script or '').strip() or None, cron_expression, next_run, max_executions)
        
    try:
        cursor.execute(query, params)
        conn.commit()
    except Exception as e:
        conn.close()
        return f"Error scheduling task: {e}"
        
    conn.close()
    
    if cron_expression:
        return f"Task scheduled successfully with recurrence '{cron_expression}'. First run at: {next_run}. ID: {job_id}"
    else:
        return f"Task scheduled successfully to run at '{next_run}'. ID: {job_id}"

def list_scheduled_tasks() -> str:
    """
    Lists the active cron jobs (scheduled tasks) of the current chat. Use this to check if a cron job already exists before creating, rewriting or deleting one.
    """
    conn = get_db()
    cursor = conn.cursor()
    from utils.session import current_session_id
    session_id = current_session_id.get()
    
    if not session_id:
        return "Error: No active session found."
        
    try:
        cursor.execute('SELECT id, description, cron_expression, next_run, execution_count, max_executions FROM cron_jobs WHERE session_id = ? AND is_active = 1', (session_id,))
        jobs = cursor.fetchall()
        if not jobs:
            return "No active scheduled tasks for this session."
            
        result = "Active Scheduled Tasks:\n"
        for j in jobs:
            cron_info = f"cron: '{j['cron_expression']}'" if j['cron_expression'] else "one-shot"
            exec_info = f", execs: {j['execution_count']}/{j['max_executions']}" if j['max_executions'] else f", execs: {j['execution_count']}"
            result += f"- ID: {j['id']} | {j['description']} | next: {j['next_run']} | {cron_info}{exec_info}\n"
        return result
    except Exception as e:
        return f"Error listing tasks: {e}"
    finally:
        conn.close()

def delete_scheduled_task(job_id: str) -> str:
    """
    Cancels/deletes a cron job (scheduled task) by ID. To rewrite a cron job, delete it and create a new one with schedule_task.
    
    Args:
        job_id: The ID of the job to cancel (e.g. job-12345678).
    """
    conn = get_db()
    cursor = conn.cursor()
    from utils.session import current_session_id
    session_id = current_session_id.get()
    
    if not session_id:
        return "Error: No active session found."
        
    try:
        cursor.execute('UPDATE cron_jobs SET is_active = 0 WHERE id = ? AND session_id = ?', (job_id, session_id))
        conn.commit()
        if cursor.rowcount > 0:
            return f"Task {job_id} was successfully canceled."
        else:
            return f"Task {job_id} not found or you don't have permission to cancel it."
    except Exception as e:
        return f"Error canceling task: {e}"
    finally:
        conn.close()

SCHEDULING_TOOLS = [schedule_task, list_scheduled_tasks, delete_scheduled_task]
