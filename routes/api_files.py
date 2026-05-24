import os
import subprocess

from flask import Blueprint, jsonify, request, send_file

import state
from database import set_ide_config
from utils.file_utils import get_file_tree

api_files_bp = Blueprint('api_files', __name__)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@api_files_bp.route('/api/files', methods=['GET'])
def list_files():
    root_dir = state.CURRENT_PROJECT_PATH if state.CURRENT_PROJECT_PATH else ROOT_DIR
    tree = get_file_tree(root_dir, root_dir)
    return jsonify(tree)

@api_files_bp.route('/api/files/content', methods=['GET'])
def get_file_content():
    file_path = request.args.get('path')
    if not file_path:
        return jsonify({"error": "Path is required"}), 400
    
    root_dir = state.CURRENT_PROJECT_PATH if state.CURRENT_PROJECT_PATH else ROOT_DIR
    safe_path = os.path.abspath(os.path.join(root_dir, file_path))
    if not safe_path.startswith(root_dir):
        return jsonify({"error": "Access denied"}), 403
        
    if not os.path.exists(safe_path) or os.path.isdir(safe_path):
        return jsonify({"error": "File not found"}), 404
        
    try:
        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({"content": content, "path": file_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_files_bp.route('/api/files/save', methods=['POST'])
def save_file_content():
    data = request.json
    if not data or 'path' not in data or 'content' not in data:
        return jsonify({"error": "Missing path or content"}), 400
        
    file_path = data['path']
    content = data['content']
    
    root_dir = state.CURRENT_PROJECT_PATH if state.CURRENT_PROJECT_PATH else ROOT_DIR
    safe_path = os.path.abspath(os.path.join(root_dir, file_path))
    if not safe_path.startswith(root_dir):
        return jsonify({"error": "Access denied"}), 403
        
    try:
        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"status": "success", "message": "File saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_files_bp.route('/api/temp/<path:filename>')
def serve_temp_file(filename):
    temp_dir = os.path.abspath(os.path.join(ROOT_DIR, "temp"))
    safe_path = os.path.abspath(os.path.join(temp_dir, filename))
    if not safe_path.startswith(temp_dir):
        return "Access denied", 403
    if not os.path.exists(safe_path):
        return "File not found", 404
    return send_file(safe_path)

@api_files_bp.route('/api/set_project_path', methods=['POST'])
def set_project_path():
    data = request.json
    project_path = data.get('project_path')
    
    if not project_path:
        return jsonify({"error": "Missing project_path"}), 400
    
    abs_path = os.path.abspath(project_path)
    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        return jsonify({"error": "Invalid directory path"}), 400
        
    state.CURRENT_PROJECT_PATH = abs_path
    set_ide_config('CURRENT_PROJECT_PATH', abs_path)
    return jsonify({"status": "success", "project_path": abs_path})

@api_files_bp.route('/api/select_folder_dialog', methods=['GET'])
def select_folder_dialog():
    try:
        script = '''
        tell application "System Events"
            activate
            set theFolder to choose folder with prompt "Select Project Folder:"
            POSIX path of theFolder
        end tell
        '''
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if result.returncode == 0:
            folder_path = result.stdout.strip()
            return jsonify({"status": "success", "path": folder_path})
        else:
            return jsonify({"status": "cancelled", "path": None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
