from flask import Blueprint, jsonify

from database import get_db

api_cron_bp = Blueprint('api_cron', __name__)

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

@api_cron_bp.route('/api/cron/<job_id>', methods=['DELETE'])
def delete_cron_job(job_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM cron_jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"}), 200
