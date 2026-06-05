"""
Helper for inserting feedback/status messages into the output tables.
Centralizes the repeated INSERT INTO pattern used across the agent pipeline.
"""
import uuid


def insert_feedback(cursor, table: str, session_id: str, message_in_id: str, content: str) -> str:
    """
    Inserts a feedback message into the specified output table.

    Arguments:
        cursor: Database cursor (must have cursor.connection for commit).
        table (str): Target table name (e.g. 'messages_out' or 'ide_messages_out').
        session_id (str): Session identifier.
        message_in_id (str): ID of the input message being processed.
        content (str): The feedback message content.

    Returns:
        str: The generated message ID.
    """
    msg_id = f"msg-out-{uuid.uuid4().hex[:8]}"
    cursor.execute(f'''
        INSERT INTO {table} (id, session_id, in_reply_to, content)
        VALUES (?, ?, ?, ?)
    ''', (msg_id, session_id, message_in_id, content))
    cursor.connection.commit()
    return msg_id
