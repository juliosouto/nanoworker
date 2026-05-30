from flask import Blueprint, jsonify, request

from database import encrypt_value, get_db

api_llm_bp = Blueprint('api_llm', __name__)

@api_llm_bp.route('/api/llm_models', methods=['POST'])
def add_llm_model():
    data = request.json
    if not data or 'model_name' not in data or 'provider' not in data:
        return jsonify({"error": "Missing model_name or provider"}), 400
        
    api_key_val = data.get('api_key')
    duplicate_from_id = data.get('duplicate_from_id')
    
    if api_key_val == '••••••••••••' and duplicate_from_id:
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT api_key FROM llm_config WHERE id = ?', (duplicate_from_id,))
            row = cursor.fetchone()
            if row:
                api_key_val = row['api_key']
        except Exception as e:
            print(f"Error copying duplicated API Key: {e}")
        finally:
            conn.close()
    elif api_key_val:
        api_key_val = encrypt_value(api_key_val)
        
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO llm_config (
                model_name, provider, api_key, enabled, json_output, thinking, function_calling,
                context_window, max_output_tokens, text_input, image_input, audio_input,
                video_input, document_input, rate_tpm, rate_rpm, rate_rpd,
                text_output, image_output, audio_output, video_output, document_output
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('model_name'),
            data.get('provider'),
            api_key_val,
            1 if data.get('enabled') else 0,
            1 if data.get('json_output') else 0,
            1 if data.get('thinking') else 0,
            1 if data.get('function_calling') else 0,
            data.get('context_window') or None,
            data.get('max_output_tokens') or None,
            1 if data.get('text_input') else 0,
            1 if data.get('image_input') else 0,
            1 if data.get('audio_input') else 0,
            1 if data.get('video_input') else 0,
            1 if data.get('document_input') else 0,
            data.get('rate_tpm') or None,
            data.get('rate_rpm') or None,
            data.get('rate_rpd') or None,
            1 if data.get('text_output') else 0,
            1 if data.get('image_output') else 0,
            1 if data.get('audio_output') else 0,
            1 if data.get('video_output') else 0,
            1 if data.get('document_output') else 0
        ))
        conn.commit()
        return jsonify({"status": "success", "message": "Model added"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@api_llm_bp.route('/api/llm_models/<int:model_id>', methods=['DELETE'])
def delete_llm_model(model_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM llm_config WHERE id = ?', (model_id,))
        conn.commit()
        if cursor.rowcount > 0:
            return jsonify({"status": "success", "message": "Model deleted"}), 200
        else:
            return jsonify({"error": "Model not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@api_llm_bp.route('/api/llm_models/<int:model_id>', methods=['PUT'])
def update_llm_model(model_id):
    data = request.json
    if not data or 'model_name' not in data or 'provider' not in data:
        return jsonify({"error": "Missing model_name or provider"}), 400
        
    api_key_val = data.get('api_key')
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        updates = [
            ("model_name", data.get('model_name')),
            ("provider", data.get('provider')),
            ("enabled", 1 if data.get('enabled') else 0),
            ("json_output", 1 if data.get('json_output') else 0),
            ("thinking", 1 if data.get('thinking') else 0),
            ("function_calling", 1 if data.get('function_calling') else 0),
            ("context_window", data.get('context_window') or None),
            ("max_output_tokens", data.get('max_output_tokens') or None),
            ("text_input", 1 if data.get('text_input') else 0),
            ("image_input", 1 if data.get('image_input') else 0),
            ("audio_input", 1 if data.get('audio_input') else 0),
            ("video_input", 1 if data.get('video_input') else 0),
            ("document_input", 1 if data.get('document_input') else 0),
            ("rate_tpm", data.get('rate_tpm') or None),
            ("rate_rpm", data.get('rate_rpm') or None),
            ("rate_rpd", data.get('rate_rpd') or None),
            ("text_output", 1 if data.get('text_output') else 0),
            ("image_output", 1 if data.get('image_output') else 0),
            ("audio_output", 1 if data.get('audio_output') else 0),
            ("video_output", 1 if data.get('video_output') else 0),
            ("document_output", 1 if data.get('document_output') else 0),
        ]
        
        if api_key_val != '••••••••••••':
            encrypted_key = encrypt_value(api_key_val) if api_key_val else None
            updates.append(("api_key", encrypted_key))
            
        set_clause = ", ".join([f"{k}=?" for k, v in updates])
        values = [v for k, v in updates] + [model_id]
        
        cursor.execute(f"UPDATE llm_config SET {set_clause} WHERE id=?", values)
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Model not found"}), 404
        return jsonify({"status": "success", "message": "Model updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@api_llm_bp.route('/api/llm_models/<int:model_id>/toggle', methods=['POST'])
def toggle_llm_model(model_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT enabled FROM llm_config WHERE id = ?', (model_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Model not found"}), 404
        new_status = 0 if row['enabled'] else 1
        cursor.execute('UPDATE llm_config SET enabled = ? WHERE id = ?', (new_status, model_id))
        conn.commit()
        return jsonify({"status": "success", "enabled": bool(new_status)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# Workers API Routes
@api_llm_bp.route('/api/workers', methods=['POST'])
def add_worker():
    data = request.json
    if not data or 'worker_name' not in data or 'worker_model' not in data:
        return jsonify({"error": "Missing worker_name or worker_model"}), 400
        
    is_default = 1 if data.get('is_default') else 0
    thinking_enabled = 1 if data.get('thinking_enabled') else 0
    tools_enabled = 0 if data.get('tools_enabled') is False else 1
    conn = get_db()
    cursor = conn.cursor()
    try:
        if is_default:
            cursor.execute('UPDATE workers_config SET is_default = 0')
        cursor.execute('''
            INSERT INTO workers_config (worker_name, worker_model, worker_instructions, is_default, thinking_enabled, tools_enabled) VALUES (?, ?, ?, ?, ?, ?)
        ''', (data.get('worker_name'), data.get('worker_model'), data.get('worker_instructions'), is_default, thinking_enabled, tools_enabled))
        conn.commit()
        return jsonify({"status": "success", "message": "Worker added"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@api_llm_bp.route('/api/workers/<int:worker_id>', methods=['PUT'])
def update_worker(worker_id):
    data = request.json
    if not data or 'worker_name' not in data or 'worker_model' not in data:
        return jsonify({"error": "Missing worker_name or worker_model"}), 400
        
    is_default = 1 if data.get('is_default') else 0
    thinking_enabled = 1 if data.get('thinking_enabled') else 0
    tools_enabled = 0 if data.get('tools_enabled') is False else 1
    conn = get_db()
    cursor = conn.cursor()
    try:
        if is_default:
            cursor.execute('UPDATE workers_config SET is_default = 0 WHERE id != ?', (worker_id,))
        cursor.execute('''
            UPDATE workers_config SET worker_name = ?, worker_model = ?, worker_instructions = ?, is_default = ?, thinking_enabled = ?, tools_enabled = ? WHERE id = ?
        ''', (data.get('worker_name'), data.get('worker_model'), data.get('worker_instructions'), is_default, thinking_enabled, tools_enabled, worker_id))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Worker not found"}), 404
        return jsonify({"status": "success", "message": "Worker updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@api_llm_bp.route('/api/workers/<int:worker_id>', methods=['DELETE'])
def delete_worker(worker_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM workers_config WHERE id = ?', (worker_id,))
        conn.commit()
        if cursor.rowcount > 0:
            return jsonify({"status": "success", "message": "Worker deleted"}), 200
        else:
            return jsonify({"error": "Worker not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
