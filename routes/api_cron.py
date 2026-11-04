import uuid
from datetime import datetime

from croniter import croniter
from flask import Blueprint, jsonify, request

from database import get_db, set_config

api_cron_bp = Blueprint('api_cron', __name__)

_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def _parse_job_fields(data: dict, now: datetime):
    """Validates the editable fields of a cron job.

    Returns (fields, None), or (None, error message). A cron expression wins
    over a one-shot date, as in schedule_task.
    """
    description = (data.get('description') or '').strip()
    content = (data.get('content') or '').strip()
    if not description or not content:
        return None, 'Description and prompt are required.'

    cron_expression = (data.get('cron_expression') or '').strip() or None
    run_at = (data.get('next_run') or '').strip()
    if cron_expression:
        try:
            next_run = croniter(cron_expression, now).get_next(datetime).strftime(_DATE_FORMAT)
        except Exception as e:
            return None, f'Invalid cron expression: {e}'
    elif run_at:
        try:
            next_run = datetime.fromisoformat(run_at.replace('T', ' ')).strftime(_DATE_FORMAT)
        except ValueError:
            return None, 'Invalid date. Use YYYY-MM-DD HH:MM:SS.'
    else:
        return None, 'Give a cron expression or a date to run.'

    max_executions = data.get('max_executions')
    if max_executions in (None, ''):
        max_executions = None
    else:
        try:
            max_executions = int(max_executions)
        except (TypeError, ValueError):
            return None, 'Max executions must be a number.'
        if max_executions < 1:
            return None, 'Max executions must be at least 1.'

    return {
        'description': description,
        'content': content,
        'cron_expression': cron_expression,
        'next_run': next_run,
        'max_executions': max_executions,
    }, None


@api_cron_bp.route('/api/cron/<job_id>/toggle', methods=['POST'])
def toggle_cron_job(job_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT is_active FROM cron_jobs WHERE id = ?', (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Job not found"}), 404
        
    new_status = 0 if row['is_active'] else 1
    cursor.execute('UPDATE cron_jobs SET is_active = ? WHERE id = ?', (new_status, job_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "is_active": bool(new_status)}), 200


@api_cron_bp.route('/api/cron', methods=['POST'])
def create_cron_job():
    data = request.json or {}
    fields, error = _parse_job_fields(data, datetime.now())
    if error:
        return jsonify({"error": error}), 400

    session_id = data.get('session_id')
    conn = get_db()
    try:
        if not session_id or not conn.execute('SELECT 1 FROM sessions WHERE id = ?', (session_id,)).fetchone():
            return jsonify({"error": "Choose a valid chat."}), 400
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        conn.execute(
            'INSERT INTO cron_jobs (id, session_id, description, content, cron_expression, next_run, max_executions) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (job_id, session_id, fields['description'], fields['content'], fields['cron_expression'],
             fields['next_run'], fields['max_executions']),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"status": "success", "id": job_id}), 201


@api_cron_bp.route('/api/cron/<job_id>', methods=['PUT'])
def update_cron_job(job_id):
    data = request.json or {}
    fields, error = _parse_job_fields(data, datetime.now())
    if error:
        return jsonify({"error": error}), 400

    conn = get_db()
    try:
        if not conn.execute('SELECT 1 FROM cron_jobs WHERE id = ?', (job_id,)).fetchone():
            return jsonify({"error": "Job not found"}), 404
        conn.execute(
            'UPDATE cron_jobs SET description = ?, content = ?, cron_expression = ?, next_run = ?, '
            'max_executions = ?, is_active = ? WHERE id = ?',
            (fields['description'], fields['content'], fields['cron_expression'], fields['next_run'],
             fields['max_executions'], 1 if data.get('is_active', True) else 0, job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"status": "success"}), 200


@api_cron_bp.route('/api/cron/preferences', methods=['POST'])
def save_cron_preferences():
    data = request.json or {}
    for i in range(1, 6):
        key = f"cron_pref_{i}"
        db_key = f"CRON_WORKER_PREF_{i}"
        if key in data:
            set_config(db_key, data[key] or "")
    return jsonify({"status": "success"}), 200


@api_cron_bp.route('/api/cron/<job_id>', methods=['DELETE'])
def delete_cron_job(job_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM cron_jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"}), 200
