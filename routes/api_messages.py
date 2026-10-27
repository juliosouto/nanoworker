from flask import Blueprint, jsonify, request

from database import (
    MESSAGE_LIST_MODES,
    delete_message_history_rows,
    list_messages_admin,
)

api_messages_bp = Blueprint('api_messages', __name__)


def _int_arg(name, default, lo, hi):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, lo), hi)


@api_messages_bp.route('/api/messages', methods=['GET'])
def list_messages_api():
    mode = request.args.get('mode', 'all')
    if mode not in MESSAGE_LIST_MODES:
        return jsonify({"error": "Invalid mode"}), 400

    try:
        threshold = float(request.args.get('threshold', 0.9))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid threshold"}), 400
    if not 0.5 <= threshold <= 1.0:
        return jsonify({"error": "Threshold must be between 0.5 and 1.0"}), 400

    result = list_messages_admin(
        channel_id=request.args.get('channel_id') or None,
        query=(request.args.get('q') or '').strip() or None,
        mode=mode,
        threshold=threshold,
        page=_int_arg('page', 1, 1, 100000),
        per_page=_int_arg('per_page', 50, 1, 200),
    )
    return jsonify(result), 200


@api_messages_bp.route('/api/messages/delete', methods=['POST'])
def delete_messages_api():
    data = request.get_json(silent=True) or {}
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Missing ids"}), 400
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "ids must be integers"}), 400

    result = delete_message_history_rows(ids)
    return jsonify({"status": "success", **result}), 200


@api_messages_bp.route('/api/messages/<int:message_id>', methods=['DELETE'])
def delete_message_api(message_id):
    result = delete_message_history_rows([message_id])
    if result['deleted'] == 0:
        return jsonify({"error": "Message not found"}), 404
    return jsonify({"status": "success", **result}), 200
