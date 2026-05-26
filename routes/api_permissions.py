import os
import subprocess

from flask import Blueprint, jsonify, request

api_permissions_bp = Blueprint('api_permissions', __name__)

@api_permissions_bp.route('/api/permissions/request/macos', methods=['POST'])
def request_os_permission_macos():
    data = request.json
    perm_type = data.get('permission')
    
    try:
        if perm_type == 'calendar':
            subprocess.run(['osascript', '-e', 'tell application "Calendar" to get calendars'], capture_output=True, timeout=5)
        elif perm_type == 'contacts':
            subprocess.run(['osascript', '-e', 'tell application "Contacts" to get name of people'], capture_output=True, timeout=5)
        elif perm_type == 'terminal':
            subprocess.run(['osascript', '-e', 'tell application "Terminal" to get windows'], capture_output=True, timeout=5)
        elif perm_type == 'safari':
            subprocess.run(['osascript', '-e', 'tell application "Safari" to get properties of front document'], capture_output=True, timeout=5)
        elif perm_type == 'fs':
            docs_path = os.path.expanduser('~/Documents')
            if os.path.exists(docs_path):
                subprocess.run(['ls', docs_path], capture_output=True, timeout=5)
        elif perm_type == 'photos':
            subprocess.run(['osascript', '-e', 'tell application "Photos" to get name of albums'], capture_output=True, timeout=5)
        elif perm_type == 'notes':
            subprocess.run(['osascript', '-e', 'tell application "Notes" to get name of folders'], capture_output=True, timeout=5)
        elif perm_type == 'reminders':
            subprocess.run(['osascript', '-e', 'tell application "Reminders" to get name of lists'], capture_output=True, timeout=5)
        elif perm_type == 'icloud':
            icloud_path = os.path.expanduser('~/Library/Mobile Documents/com~apple~CloudDocs/')
            if os.path.exists(icloud_path):
                subprocess.run(['ls', icloud_path], capture_output=True, timeout=5)
        elif perm_type == 'mail':
            subprocess.run(['osascript', '-e', 'tell application "Mail" to get name of accounts'], capture_output=True, timeout=5)
        elif perm_type == 'system_data':
            safari_path = os.path.expanduser('~/Library/Safari')
            if os.path.exists(safari_path):
                subprocess.run(['ls', safari_path], capture_output=True, timeout=5)
                
        return jsonify({"status": "success", "message": f"Permission requested for {perm_type} on macOS"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_permissions_bp.route('/api/permissions/request/linux', methods=['POST'])
def request_os_permission_linux():
    data = request.json
    perm_type = data.get('permission')
    
    # Linux generally doesn't have a granular UI prompt system for desktop apps.
    # We simply acknowledge the permission request.
    try:
        return jsonify({"status": "success", "message": f"Permission {perm_type} handled for Linux (internal config)"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_permissions_bp.route('/api/permissions/request/windows', methods=['POST'])
def request_os_permission_windows():
    data = request.json
    perm_type = data.get('permission')
    
    # Windows generally inherits permissions or prompts via UAC, which is not granular.
    # We simply acknowledge the permission request.
    try:
        return jsonify({"status": "success", "message": f"Permission {perm_type} handled for Windows (internal config)"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
