from flask import Blueprint, jsonify, request

from agent.llm_usage import get_prompt_calls, get_prompt_costs

api_costs_bp = Blueprint('api_costs', __name__)


def _int_arg(name, default, lo, hi):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, lo), hi)


@api_costs_bp.route('/api/costs/prompts', methods=['GET'])
def list_prompt_costs_api():
    result = get_prompt_costs(
        days=_int_arg('days', 7, 1, 90),
        page=_int_arg('page', 1, 1, 100000),
        per_page=_int_arg('per_page', 50, 1, 200),
        query=(request.args.get('q') or '').strip() or None,
    )
    return jsonify(result), 200


@api_costs_bp.route('/api/costs/prompts/<path:message_in_id>/calls', methods=['GET'])
def prompt_calls_api(message_in_id):
    return jsonify({"calls": get_prompt_calls(message_in_id)}), 200
