import os
import uuid
from datetime import datetime
from typing import Optional
from croniter import croniter
from database import get_db

def schedule_task(description: str, prompt: str, cron_expression: Optional[str] = None, process_after: Optional[str] = None) -> str:
    """
    Schedules a task to be processed in the future or periodically.
    
    Args:
        description: A short summary of what this job does.
        prompt: The instruction or task description for the agent to execute when the time comes.
        cron_expression: A standard cron expression (e.g. "0 9 * * 1-5" for weekdays at 9am). If provided, the task will repeat.
        process_after: An ISO formatted timestamp (e.g., "2023-12-31 23:59:59") for a one-shot task. 
                       If both are provided, cron_expression takes precedence for the first execution.
    
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
        INSERT INTO cron_jobs (id, session_id, description, content, cron_expression, next_run)
        VALUES (?, ?, ?, ?, ?, ?)
    '''
    params = (job_id, session_id, description, prompt, cron_expression, next_run)
        
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

SCHEDULING_TOOLS = [schedule_task]
