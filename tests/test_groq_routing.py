import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path to find modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_runner
from google.genai import types

class TestGroqRouting(unittest.TestCase):
    @patch('database.get_db')
    @patch('agent_runner.call_groq_llm')
    @patch('database.decrypt_value')
    def test_routing_to_groq(self, mock_decrypt, mock_call_groq, mock_get_db):
        # Setup mock db and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Row mock returning groq as provider
        mock_cursor.fetchone.return_value = {
            'provider': 'groq',
            'api_key': 'encrypted_api_key',
            'thinking': 0
        }
        mock_decrypt.return_value = 'decrypted_api_key'
        
        # Define mock arguments
        history = [types.Content(role='user', parts=[types.Part.from_text(text='hello')])]
        config_kwargs = {}
        content = 'test'
        cursor = MagicMock()
        session_id = 'session-123'
        message_in_id = 'msg-123'
        
        # Invoke route_llm_call
        agent_runner.route_llm_call('llama-3.3-70b', history, config_kwargs, content, cursor, session_id, message_in_id, is_ide=False)
        
        # Check call_groq_llm is invoked
        mock_call_groq.assert_called_once_with(
            'llama-3.3-70b',
            history,
            config_kwargs,
            content,
            cursor,
            session_id,
            message_in_id,
            'messages_out',
            'decrypted_api_key',
            None
        )

if __name__ == '__main__':
    unittest.main()
