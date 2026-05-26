import logging

from typing import Optional

from database import add_user_memory, delete_user_memory, get_all_user_memories, get_db, update_user_memory
from tools.browser import current_session_id

def manage_persistent_memory(action: str, memory_text: Optional[str] = None, memory_id: Optional[int] = None) -> str:
    """
    Manages persistent memory for the user (database).
    This tool allows the assistant to "remember", update, list, or delete things for future interactions.
    
    The instruction MUST be a short and concise sentence perfectly summarizing the information.
    The maximum limit is 150 characters. If it is longer, it will be automatically truncated.
    
    Args:
        action: The action to perform. Must be one of: 'add', 'update', 'delete', 'list'.
        memory_text: The text of the memory. Required for 'add' and 'update'. Maximum of 150 characters.
        memory_id: The ID of the memory. Required for 'update' and 'delete'.
        
    Returns:
        A message indicating success, error, or tool unavailability, or a list of memories.
    """
    session_id = current_session_id.get()
    
    if session_id:
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT channel_id FROM sessions WHERE id = ?', (session_id,))
            session_row = cursor.fetchone()
            if session_row:
                channel_id = session_row['channel_id']
                if channel_id and (channel_id.startswith('whatsapp:') or channel_id.startswith('wa_web:')):
                    return "Error: This tool is not available for WhatsApp users."
        except Exception as e:
            logging.error(f"Error checking channel_id in manage_persistent_memory: {e}")
        finally:
            conn.close()

    if action == 'list':
        try:
            memories = get_all_user_memories()
            if not memories:
                return "No persistent memories found."
            
            result = "Persistent Memories:\n"
            for mem in memories:
                result += f"- ID {mem['id']}: {mem['instruction']}\n"
            return result.strip()
        except Exception as e:
            logging.error(f"Error listing memories: {e}")
            return f"Error listing memories: {str(e)}"

    if action == 'delete':
        if memory_id is None:
            return "Error: memory_id is required for the 'delete' action."
        try:
            success = delete_user_memory(memory_id)
            if success:
                return f"Success: Memory with ID {memory_id} has been deleted."
            else:
                return f"Error: Memory with ID {memory_id} not found."
        except Exception as e:
            logging.error(f"Error deleting memory: {e}")
            return f"Error deleting memory: {str(e)}"

    if action in ('add', 'update'):
        if memory_text is None:
            return f"Error: memory_text is required for the '{action}' action."
            
        if len(memory_text) > 150:
            logging.warning(f"Memory exceeded 150 characters and was truncated. Original text: {memory_text}")
            memory_text = memory_text[:150]

        if action == 'add':
            try:
                new_id = add_user_memory(memory_text)
                return f"Success: Memory added with ID {new_id} (Text: '{memory_text}')"
            except Exception as e:
                logging.error(f"Error adding memory: {e}")
                return f"Error adding memory: {str(e)}"
                
        if action == 'update':
            if memory_id is None:
                return "Error: memory_id is required for the 'update' action."
            try:
                success = update_user_memory(memory_id, memory_text)
                if success:
                    return f"Success: Memory with ID {memory_id} has been updated to: '{memory_text}'"
                else:
                    return f"Error: Memory with ID {memory_id} not found."
            except Exception as e:
                logging.error(f"Error updating memory: {e}")
                return f"Error updating memory: {str(e)}"

    return f"Error: Invalid action '{action}'. Must be one of 'add', 'update', 'delete', 'list'."
