import subprocess
import logging
import sqlite3
import os
import getpass
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def send_imessage(target: str, message: str) -> str:
    """
    Sends a text message via the MacOS Messages (iMessage) app.
    Use this tool whenever you need to send an iMessage.

    Args:
        target: The recipient's phone number or email address.
        message: The text message to send.

    Returns:
        A confirmation string indicating success or an error message.
    """
    # AppleScript to send an iMessage
    applescript_code = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{target}" of targetService
        send "{message}" to targetBuddy
    end tell
    '''
    
    try:
        # Run osascript to execute the AppleScript
        result = subprocess.run(
            ['osascript', '-e', applescript_code],
            capture_output=True,
            text=True,
            check=True
        )
        return f"Message sent successfully to {target}."
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to send iMessage to {target}: {e.stderr}")
        return f"Error sending iMessage: {e.stderr.strip()}. Ensure Messages app is open and configured."
    except Exception as e:
        logger.error(f"Unexpected error sending iMessage: {e}")
        return f"Error sending iMessage: {str(e)}"

def read_recent_imessages(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Reads the most recent messages from the local MacOS chat.db database.
    Requires 'Full Disk Access' permission for the terminal or IDE running this code.
    
    Args:
        limit: The maximum number of messages to retrieve.
        
    Returns:
        A list of dictionaries representing the recent messages, containing sender and text.
    """
    # The chat.db is located in the user's Library
    username = getpass.getuser()
    db_path = f"/Users/{username}/Library/Messages/chat.db"
    
    if not os.path.exists(db_path):
        return [{"error": f"chat.db not found at {db_path}. Ensure you are on MacOS and use iMessage."}]
        
    try:
        # Connect to the SQLite database
        # Note: We open it in read-only mode by passing uri=True
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query to get recent messages
        # We join message and handle tables to get the sender ID (phone/email)
        query = """
        SELECT 
            m.rowid, 
            m.text, 
            m.is_from_me, 
            h.id as sender_id,
            m.date
        FROM message m
        LEFT JOIN handle h ON m.handle_id = h.rowid
        WHERE m.text IS NOT NULL
        ORDER BY m.date DESC
        LIMIT ?
        """
        
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        
        messages = []
        for row in rows:
            msg_data = {
                "id": row["rowid"],
                "text": row["text"],
                "is_from_me": bool(row["is_from_me"]),
                "sender": row["sender_id"] if not row["is_from_me"] else "Me"
            }
            messages.append(msg_data)
            
        conn.close()
        # Return in chronological order (oldest to newest among the recent)
        return messages[::-1]
        
    except sqlite3.OperationalError as e:
        error_msg = str(e)
        logger.error(f"SQLite error reading chat.db: {error_msg}")
        if "unable to open database file" in error_msg.lower() or "operation not permitted" in error_msg.lower():
            return [{"error": "Operation not permitted. The application needs 'Full Disk Access' in MacOS System Settings > Privacy & Security to read chat.db."}]
        return [{"error": f"Database error: {error_msg}"}]
    except Exception as e:
        logger.error(f"Unexpected error reading iMessages: {e}")
        return [{"error": f"Unexpected error: {str(e)}"}]
