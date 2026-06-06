import asyncio
import threading
import json
import logging
from flask import Blueprint, jsonify, request
import pyatv
from pyatv.const import Protocol
from database import get_db, encrypt_value

api_appletv_bp = Blueprint('api_appletv', __name__)
logger = logging.getLogger(__name__)

# Global event loop for pyatv API tasks to avoid "Event loop is closed" errors
_api_loop = asyncio.new_event_loop()
def _start_loop():
    asyncio.set_event_loop(_api_loop)
    _api_loop.run_forever()

_api_thread = threading.Thread(target=_start_loop, daemon=True)
_api_thread.start()

# In-memory pairing sessions
pairing_sessions = {}

@api_appletv_bp.route('/api/tools/appletv/scan', methods=['GET'])
def scan_appletv():
    async def _scan():
        return await pyatv.scan(_api_loop)
    
    try:
        future = asyncio.run_coroutine_threadsafe(_scan(), _api_loop)
        results = future.result(timeout=10)
        devices = []
        for res in results:
            devices.append({
                "name": res.name,
                "identifier": res.identifier,
                "address": str(res.address)
            })
        return jsonify({"status": "success", "devices": devices})
    except Exception as e:
        logger.error(f"Scan error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@api_appletv_bp.route('/api/tools/appletv/start_pair', methods=['POST'])
def start_pair():
    data = request.json
    identifier = data.get('identifier')
    if not identifier:
        return jsonify({"status": "error", "message": "Identifier required"}), 400

    async def _start():
        scans = await pyatv.scan(_api_loop, identifier=identifier)
        if not scans:
            raise Exception("Device not found")
        conf = scans[0]
        # Initiate companion pairing
        pairing = await pyatv.pair(conf, Protocol.Companion, _api_loop)
        await pairing.begin()
        return pairing

    try:
        future = asyncio.run_coroutine_threadsafe(_start(), _api_loop)
        pairing_obj = future.result(timeout=15)
        session_id = identifier
        pairing_sessions[session_id] = pairing_obj
        return jsonify({"status": "success", "session_id": session_id})
    except Exception as e:
        logger.error(f"Start pair error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@api_appletv_bp.route('/api/tools/appletv/finish_pair', methods=['POST'])
def finish_pair():
    data = request.json
    session_id = data.get('session_id')
    pin = data.get('pin')
    
    if not session_id or not pin:
        return jsonify({"status": "error", "message": "session_id and pin required"}), 400

    pairing = pairing_sessions.get(session_id)
    if not pairing:
        return jsonify({"status": "error", "message": "Invalid or expired session"}), 400

    async def _finish():
        pairing.pin(pin)
        await pairing.finish()
        if pairing.has_paired:
            return pairing.service.credentials
        raise Exception("Failed to verify PIN")

    try:
        future = asyncio.run_coroutine_threadsafe(_finish(), _api_loop)
        creds = future.result(timeout=15)
        
        credentials_dict = {
            str(Protocol.Companion.value): creds
        }
        
        config_data = {
            "identifier": session_id,
            "credentials": credentials_dict
        }
        
        # Save to database
        conn = get_db()
        cursor = conn.cursor()
        tool_name = 'control_apple_tv'
        
        # Check if exists
        cursor.execute('SELECT COUNT(*) FROM tools_config WHERE tool_name = ?', (tool_name,))
        exists = cursor.fetchone()[0] > 0
        
        encrypted_data = encrypt_value(json.dumps(config_data))
        
        if exists:
            cursor.execute('UPDATE tools_config SET private_key = ? WHERE tool_name = ?', (encrypted_data, tool_name))
        else:
            cursor.execute('INSERT INTO tools_config (tool_name, private_key, enabled) VALUES (?, ?, 1)', (tool_name, encrypted_data))
            
        conn.commit()
        conn.close()
        
        # Cleanup session
        del pairing_sessions[session_id]
        
        # We should also tell the tool manager to reload the credentials if it's already running.
        # But for MVP, they can just restart or the tool manager will catch it on next command.
        # Wait, the tool manager caches the connection if it failed or succeeded. 
        # If it failed before, self.atv is None, so it will retry and pick up the new config.
        
        return jsonify({"status": "success", "message": "Paired successfully"})
    except Exception as e:
        logger.error(f"Finish pair error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
