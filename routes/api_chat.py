from flask import Blueprint, jsonify, request

from database import get_db

api_chat_bp = Blueprint('api_chat', __name__)

@api_chat_bp.route('/api/messages/poll', methods=['GET'])
def poll_messages():
    """
    Polling endpoint for frontends to fetch new messages.
    Query params:
      - message_in_id: the inbound message ID to find replies for
      - type: 'chat' or 'ide' — which message tables to query
    """
    message_in_id = request.args.get('message_in_id')
    msg_type = request.args.get('type', 'chat')

    if not message_in_id:
        return jsonify({"error": "message_in_id is required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    is_done = False

    if msg_type == 'ide':
        cursor.execute('''
            SELECT id, session_id, content, created_at
            FROM ide_messages_out
            WHERE in_reply_to = ?
            ORDER BY created_at ASC
        ''', (message_in_id,))
        rows = cursor.fetchall()
        
        cursor.execute('SELECT processed FROM ide_messages_in WHERE id = ?', (message_in_id,))
        status_row = cursor.fetchone()
    else:
        cursor.execute('''
            SELECT id, session_id, content, created_at
            FROM messages_out
            WHERE in_reply_to = ?
            ORDER BY created_at ASC
        ''', (message_in_id,))
        rows = cursor.fetchall()
        
        cursor.execute('SELECT processed FROM messages_in WHERE id = ?', (message_in_id,))
        status_row = cursor.fetchone()

    if status_row and status_row['processed'] == 2:
        is_done = True

    messages = []
    for row in rows:
        messages.append({
            "id": row["id"],
            "session_id": row["session_id"],
            "content": row["content"],
            "created_at": row["created_at"],
        })

    conn.close()
    return jsonify({"messages": messages, "is_done": is_done}), 200

@api_chat_bp.route('/api/chat/search', methods=['GET'])
def search_chat_sessions():
    """
    Search across all web-chat sessions for messages containing the query.
    Returns a list of matching channel_ids so the sidebar can be filtered.
    Query params:
      - q: search query string
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"matching_channels": []}), 200

    conn = get_db()
    cursor = conn.cursor()
    like_pattern = f'%{query}%'

    cursor.execute('''
        SELECT DISTINCT s.channel_id
        FROM sessions s
        WHERE s.channel_id LIKE 'web-chat%'
          AND (
              EXISTS (
                  SELECT 1 FROM messages_in mi
                  WHERE mi.session_id = s.id AND mi.content LIKE ? COLLATE NOCASE
              )
              OR EXISTS (
                  SELECT 1 FROM messages_out mo
                  WHERE mo.session_id = s.id AND mo.content LIKE ? COLLATE NOCASE
              )
          )
    ''', (like_pattern, like_pattern))

    rows = cursor.fetchall()
    matching = [row['channel_id'] for row in rows]
    conn.close()

    return jsonify({"matching_channels": matching}), 200

@api_chat_bp.route('/api/chat/<chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    conn = get_db()
    cursor = conn.cursor()
    channel_id = f"web-chat-{chat_id}" if chat_id != 'default' else 'web-chat'
    
    cursor.execute('SELECT id FROM sessions WHERE channel_id = ?', (channel_id,))
    session = cursor.fetchone()
    
    if session:
        session_id = session['id']
        cursor.execute('DELETE FROM messages_in WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM messages_out WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM cron_jobs WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
        conn.commit()
    
    conn.close()
    return jsonify({"status": "success"}), 200
