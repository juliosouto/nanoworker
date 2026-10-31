"""
Helper for inserting feedback/status messages into the output tables.
Centralizes the repeated INSERT INTO pattern used across the agent pipeline.
"""
import threading
import uuid


class ThreadSafeCursor:
    """A sqlite cursor usable from worker threads.

    sqlite3 objects may only be used in the thread that created them, but the
    LangGraph tool node runs tools (and so the feedback callback and the /stop
    check) in a worker thread. In the owner thread this proxies the original
    cursor; in any other thread it uses that thread's own connection.
    """

    def __init__(self, cursor):
        self._cursor = cursor
        self._owner = threading.get_ident()
        self._local = threading.local()

    def _target(self):
        if threading.get_ident() == self._owner:
            return self._cursor
        cursor = getattr(self._local, "cursor", None)
        if cursor is None:
            from database import get_db

            cursor = get_db().cursor()
            self._local.cursor = cursor
        return cursor

    def __getattr__(self, name):
        return getattr(self._target(), name)


def thread_safe_cursor(cursor):
    """Wrap ``cursor`` once in a ThreadSafeCursor (None stays None)."""
    if cursor is None or isinstance(cursor, ThreadSafeCursor):
        return cursor
    return ThreadSafeCursor(cursor)


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
