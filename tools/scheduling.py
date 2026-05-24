import os
import uuid
from datetime import datetime
from typing import Optional

from croniter import croniter

from database import get_db

def schedule_task(description: str, prompt: str, cron_expression: Optional[str] = None, process_after: Optional[str] = None, max_executions: Optional[int] = None) -> str:
    """
    Schedules a task to be processed in the future or periodically.
    
    Args:
        description: A short summary of what this job does.
        prompt: The instruction or task description for the agent to execute when the time comes.
        cron_expression: A standard cron expression (e.g. "0 9 * * 1-5" for weekdays at 9am). If provided, the task will repeat.
        process_after: An ISO formatted timestamp (e.g., "2023-12-31 23:59:59") for a one-shot task. 
                       If both are provided, cron_expression takes precedence for the first execution.
        max_executions: The maximum number of times this task should run. If provided, the task will automatically deactivate after reaching this count.
    
    Returns:
        A confirmation string with the scheduled task ID.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    from tools.browser import current_session_id
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
        INSERT INTO cron_jobs (id, session_id, description, content, cron_expression, next_run, max_executions)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    '''
    params = (job_id, session_id, description, prompt, cron_expression, next_run, max_executions)
        
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
    Lists all active scheduled tasks for the current session. Use this to check if a task is already scheduled before creating a new one.
    """
    conn = get_db()
    cursor = conn.cursor()
    from tools.browser import current_session_id
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
    Cancels/Deletes a scheduled task by ID.
    
    Args:
        job_id: The ID of the job to cancel (e.g. job-12345678).
    """
    conn = get_db()
    cursor = conn.cursor()
    from tools.browser import current_session_id
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
