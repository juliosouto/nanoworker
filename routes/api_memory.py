from flask import Blueprint, jsonify, request

from database import add_user_memory, delete_user_memory, get_all_user_memories, update_user_memory

api_memory_bp = Blueprint('api_memory', __name__)

@api_memory_bp.route('/api/user_memory', methods=['GET'])
def get_user_memory_api():
    memories = get_all_user_memories()
    return jsonify(memories), 200

@api_memory_bp.route('/api/user_memory', methods=['POST'])
def add_user_memory_api():
    data = request.json
    if not data or 'instruction' not in data:
        return jsonify({"error": "Missing instruction field"}), 400
    
    instruction = data['instruction'].strip()
    if not instruction:
        return jsonify({"error": "Instruction cannot be empty"}), 400
    
    mem_id = add_user_memory(instruction)
    return jsonify({"status": "success", "id": mem_id, "instruction": instruction}), 201

@api_memory_bp.route('/api/user_memory/<int:memory_id>', methods=['DELETE'])
def delete_user_memory_api(memory_id):
    success = delete_user_memory(memory_id)
    if success:
        return jsonify({"status": "success", "message": "Memory deleted"}), 200
    else:
        return jsonify({"error": "Memory not found"}), 404

@api_memory_bp.route('/api/user_memory/<int:memory_id>', methods=['PUT'])
def update_user_memory_api(memory_id):
    data = request.json
    if not data or 'instruction' not in data:
        return jsonify({"error": "Missing instruction field"}), 400
    
    instruction = data['instruction'].strip()
    if not instruction:
        return jsonify({"error": "Instruction cannot be empty"}), 400
    
    success = update_user_memory(memory_id, instruction)
    if success:
        return jsonify({"status": "success", "message": "Memory updated"}), 200
    else:
        return jsonify({"error": "Memory not found"}), 404
